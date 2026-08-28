"""Background servers: static folders and long-running scripts.

Each server owns a thread, a log channel, and a stop path. Two stop paths,
really — a graceful one that asks the server to close, and a kill that stops
waiting and forces the thread down. The kill exists because the whole point of
running your own code is that it sometimes hangs before it ever finishes
starting, and a stop button that politely waits for a server that never came up
is not a stop button.
"""

from __future__ import annotations

import http.server
import os
import socket
import socketserver
import threading
import time

import pycmd_runtime

__all__ = [
    "start_static",
    "start_script",
    "start_file",
    "how_to_run",
    "register_runner",
    "unregister_runner",
    "runners",
    "stop",
    "kill",
    "stop_all",
    "kill_all",
    "listing",
    "count",
    "local_ip",
    "port_available",
    "suggest_port",
    "log_lines",
]

# How long a graceful stop waits before the caller should escalate to kill().
GRACEFUL_TIMEOUT = 4.0
# Per-server log kept in Python as well, so a console reopened later is not blank.
LOG_LIMIT = 2000
# How long before the same server may offer another fix. Long enough that a
# refresh loop cannot spam the console, short enough that a real second problem
# still gets asked about.
OFFER_COOLDOWN = 20.0

_servers: dict[str, "_Entry"] = {}
_lock = threading.RLock()
_counter = 0


class _Entry:
    def __init__(self, handle: str, label: str, kind: str, port: int, host: str) -> None:
        self.handle = handle
        self.label = label
        self.kind = kind  # "static" or "script"
        self.port = port
        self.host = host
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self.httpd: socketserver.BaseServer | None = None
        self.status = "starting"
        self.error = ""
        self.started_at = time.time()
        self.requests = 0
        self.target = ""
        # A 404 storm must not become a wall of the same question, but one
        # answered offer must not silence the server for good either: a
        # cooldown does both.
        self.offered_at = 0.0
        self.log: list[tuple[str, str]] = []
        self.log_lock = threading.RLock()

    def add_log(self, stream: str, text: str) -> None:
        with self.log_lock:
            self.log.append((stream, text))
            if len(self.log) > LOG_LIMIT:
                del self.log[: len(self.log) - LOG_LIMIT]

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def as_dict(self) -> dict:
        alive = self.alive()
        status = self.status
        if status not in ("error", "stopped") and not alive:
            status = "stopped"
        row = {
            "handle": self.handle,
            "label": self.label,
            "kind": self.kind,
            "port": self.port,
            "host": self.host,
            "status": status,
            "error": self.error,
            "target": self.target,
            "uptime": int(time.time() - self.started_at),
            "requests": self.requests,
        }
        if self.port:
            shown = local_ip() if self.host == "0.0.0.0" else "127.0.0.1"
            row["url"] = f"http://{shown}:{self.port}/"
        else:
            row["url"] = ""
        return row


def _next_handle() -> str:
    global _counter
    with _lock:
        _counter += 1
        return f"srv{_counter}"


# Set while _log is emitting, so the observer does not file the same line
# twice. Thread-local, because two servers log at once and a shared flag would
# make one of them swallow the other's output.
_filing = threading.local()


def _log(entry: _Entry, stream: str, text: str) -> None:
    """Record on the Python side and push to the UI channel in one step."""
    entry.add_log(stream, text)
    _filing.busy = True
    try:
        pycmd_runtime.emit(stream, text, entry.handle)
    finally:
        _filing.busy = False


def _observe(stream: str, text: str, channel: str) -> None:
    """Keeps a copy of everything a server prints, in that server's own log.

    Without this, a script server's log held only the two lines this module
    writes itself, and reopening its console after switching tabs showed
    "Running x" and nothing the script had actually printed.
    """
    if getattr(_filing, "busy", False):
        return
    with _lock:
        entry = _servers.get(channel)
    if entry is None:
        return
    entry.add_log(stream, text)


pycmd_runtime.set_observer(_observe)


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------


def local_ip() -> str:
    """Best-effort LAN address, so the user knows what URL to open."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packets are actually sent; this just picks the outbound interface.
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def port_available(port: int, host: str = "0.0.0.0") -> bool:
    if not isinstance(port, int) or not (1 <= port <= 65535):
        return False
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def suggest_port(start: int = 8000, host: str = "0.0.0.0") -> int:
    """First free port at or above `start`, so the form can prefill sensibly."""
    for candidate in range(max(1, start), min(start + 200, 65535)):
        if port_available(candidate, host):
            return candidate
    return start


def _validate(port: int, host: str) -> str:
    if not isinstance(port, int) or not (1 <= port <= 65535):
        return f"Port must be between 1 and 65535 (got {port})."
    if port < 1024:
        return f"Port {port} is reserved; Android will not let an app bind it. Try 8000."
    if not port_available(port, host):
        return f"Port {port} is already in use. Try {suggest_port(port + 1, host)}."
    return ""


# ---------------------------------------------------------------------------
# Static file server
# ---------------------------------------------------------------------------


def start_static(
    directory: str,
    port: int = 8000,
    host: str = "0.0.0.0",
    label: str = "",
    log_requests: bool = True,
) -> dict:
    """Serve a directory over HTTP - the everyday 'python -m http.server'."""
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        return {"ok": False, "error": f"Not a folder: {directory}"}

    problem = _validate(port, host)
    if problem:
        return {"ok": False, "error": problem}

    entry = _Entry(
        _next_handle(),
        label or f"Serving {os.path.basename(directory) or '/'}",
        "static",
        port,
        host,
    )
    entry.target = directory

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            entry.requests += 1
            if log_requests:
                _log(entry, "stdout", f"{self.address_string()}  {fmt % args}\n")

        def log_error(self, fmt: str, *args) -> None:  # noqa: A003
            text = f"{fmt % args}\n"
            _log(entry, "stderr", text)
            # A 404 on the page a browser asks for first is the most common
            # way a static server looks broken, and it is usually one rename
            # away from working.
            if "404" in text and time.time() - entry.offered_at > OFFER_COOLDOWN:
                entry.offered_at = time.time()
                _offer_index(entry, directory)

    class Threaded(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    try:
        httpd = Threaded((host, port), Handler)
    except OSError as exc:
        # The launcher gets the message; the doctor gets the chance to offer a
        # port that is actually free.
        offer = _diagnose(str(exc), {"kind": "static", "channel": entry.handle,
                                     "directory": directory, "port": port})
        detail = f"Could not bind {host}:{port} - {exc}"
        if offer is not None:
            detail += f"\n{offer['message']} {offer['question']}"
        return {"ok": False, "error": detail, "fix": bool(offer)}

    entry.httpd = httpd
    entry.status = "running"

    def serve() -> None:
        entry.thread_id = threading.get_ident()
        pycmd_runtime.register_channel(entry.handle)
        _log(entry, "system", f"Serving {directory}\n")
        _log(entry, "system", f"Listening on {entry.as_dict()['url']}\n")
        try:
            httpd.serve_forever(poll_interval=0.4)
        except (KeyboardInterrupt, SystemExit):
            # A stop or a kill landing in the serve loop. Expected, and the
            # user pressed the button - printing a traceback would make a
            # deliberate shutdown look like a crash.
            pass
        except BaseException as exc:  # noqa: BLE001 - surfaced in the server log
            entry.status = "error"
            entry.error = f"{type(exc).__name__}: {exc}"
            _log(entry, "stderr", pycmd_runtime.format_exception(exc, entry.label))
        finally:
            try:
                httpd.server_close()
            except Exception:
                pass
            if entry.status != "error":
                entry.status = "stopped"
            _log(entry, "system", "Server stopped.\n")
            pycmd_runtime.unregister_channel()

    thread = threading.Thread(target=serve, name=f"pycmd-{entry.handle}", daemon=True)
    entry.thread = thread
    with _lock:
        _servers[entry.handle] = entry
    thread.start()

    result = entry.as_dict()
    result["ok"] = True
    return result


# ---------------------------------------------------------------------------
# Script server
# ---------------------------------------------------------------------------


# Extensions a plugin has claimed, and the callable that runs them. A plugin
# that teaches PyCmd a new file type gets it served here too, rather than only
# in the Files tab.
_runners: dict[str, object] = {}
_runner_notes: dict[str, str] = {}


def register_runner(extension: str, runner, note: str = "") -> bool:
    """Lets a plugin run its own file type as a server.

    `runner(path, channel)` is called on the server's thread, with stdout and
    stdin already pointed at that server's console. Returning normally means it
    finished; raising is reported like any other server error.

    `note` is what the launcher says this will do, before it does it. Without
    one the form can only say "a plugin runs this", which tells the user
    nothing they wanted to know.
    """
    extension = str(extension or "").strip().lower()
    if not extension.startswith("."):
        extension = "." + extension
    if extension in (".py", ".pyw") or _callable_of(runner) is None:
        # Python is ours, and something that cannot be called would only fail
        # later, deep inside a thread, where the message would be useless.
        return False
    _runners[extension] = runner
    _runner_notes[extension] = str(note or "")[:200]
    return True


def _callable_of(runner):
    """A plain callable, or an object with a `run` method.

    Kotlin registers the JavaScript runner this way: a Java object handed to
    Python is not callable, but its methods are, and insisting on a lambda
    would mean no cross-language runners at all.
    """
    if callable(runner):
        return runner
    method = getattr(runner, "run", None)
    return method if callable(method) else None


def unregister_runner(extension: str) -> None:
    extension = str(extension or "").strip().lower()
    if not extension.startswith("."):
        extension = "." + extension
    _runners.pop(extension, None)
    _runner_notes.pop(extension, None)


def runners() -> str:
    """Every extension a plugin has claimed, comma separated."""
    return ",".join(sorted(_runners))


def how_to_run(path: str) -> dict:
    """What pressing Run in the Servers tab would actually do with this file.

    The Servers tab asks first so it can say so in the form, rather than
    starting something and explaining afterwards.
    """
    if os.path.isdir(path):
        return {"how": "serve", "language": "Folder",
                "note": f"Serves {os.path.basename(path) or 'this folder'} over HTTP."}

    extension = os.path.splitext(path)[1].lower()

    if extension in (".py", ".pyw"):
        return {"how": "script", "language": "Python",
                "note": "Runs as a background script on its own thread."}

    try:
        from pycmd_langs import registry

        language = registry.for_path(path)
    except Exception:  # noqa: BLE001
        language = None

    if extension in _runners:
        # A registered runner wins, but the language registry still supplies
        # the name: JavaScript is run by a registered runner too, and calling
        # it "js, run by a plugin" would be a worse answer than the truth.
        note = _runner_notes.get(extension, "")
        return {
            "how": "plugin",
            "language": (language or {}).get("name") or extension.lstrip("."),
            "note": note or "Run by a plugin that claimed this file type.",
        }

    if language is None:
        return {"how": "unknown", "language": "", "note": "Unknown file type."}

    if language["mode"] == "run":
        if language["id"] == "javascript":
            # Only reachable when the JavaScript runner failed to register,
            # which means the engine is not there to run it.
            return {"how": "unsupported", "language": language["name"],
                    "note": "The JavaScript engine is not available in this session."}
        return {"how": "language", "language": language["name"],
                "note": f"Runs on the built-in {language['name']} interpreter."}

    if language["mode"] == "preview":
        return {"how": "serve", "language": language["name"],
                "note": f"Serves this folder over HTTP and opens {os.path.basename(path)}."}

    return {"how": "unsupported", "language": language["name"],
            "note": language.get("note") or f"{language['name']} cannot run on the device."}


def start_file(
    path: str,
    port: int = 0,
    host: str = "0.0.0.0",
    label: str = "",
    args=None,
) -> dict:
    """Runs whatever kind of file this is as a server.

    A server used to mean a Python script, which made the Servers tab a Python
    tab wearing a different hat. A page is a server too - serve its folder - and
    so is a Go or Rust or C program that listens on a socket, or anything a
    plugin has taught the app to run.
    """
    path = os.path.abspath(path)
    if os.path.isdir(path):
        # Pointing the runner at a folder means "serve this", which is what
        # anyone who typed a folder name meant. Refusing it on a technicality
        # would only send them to the other half of the same form.
        return start_static(
            path,
            port=port or suggest_port(8000, host),
            host=host,
            label=label or os.path.basename(path) or "workspace",
        )
    if not os.path.isfile(path):
        return {"ok": False, "error": f"No such file or folder: {path}"}

    plan = how_to_run(path)

    if plan["how"] == "serve":
        # A page is served, not executed: the folder becomes the site and the
        # file it was started from becomes the page to open.
        folder = os.path.dirname(path)
        result = start_static(
            folder,
            port=port or suggest_port(8000, host),
            host=host,
            label=label or os.path.basename(path),
        )
        if result.get("ok") and result.get("url"):
            result["url"] = result["url"].rstrip("/") + "/" + os.path.basename(path)
            result["opens"] = os.path.basename(path)
        return result

    if plan["how"] == "unsupported":
        return {"ok": False, "error": plan["note"]}

    if plan["how"] == "unknown":
        return {"ok": False, "error": "PyCmd does not know how to run that file."}

    return start_script(path, port=port, host=host, label=label, args=args)


def start_script(
    path: str,
    port: int = 0,
    host: str = "0.0.0.0",
    label: str = "",
    args=None,
) -> dict:
    """Run a file on a background thread and track it as a server.

    `port` is informational for a script - the script binds it itself - but it
    is checked first so a doomed run fails immediately with a clear message
    rather than deep inside somebody's traceback.
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return {"ok": False, "error": f"No such file: {path}"}

    if port:
        problem = _validate(port, host)
        if problem:
            return {"ok": False, "error": problem}

    extension = os.path.splitext(path)[1].lower()
    plugin_runner = _runners.get(extension)
    language = None
    if plugin_runner is None and extension not in (".py", ".pyw"):
        try:
            from pycmd_langs import registry

            language = registry.for_path(path)
            if language["mode"] != "run":
                return {"ok": False,
                        "error": language.get("note")
                        or f"{language['name']} cannot be run on the device."}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"language support failed to load: {exc}"}

    entry = _Entry(_next_handle(), label or os.path.basename(path), "script", port, host)
    entry.target = path
    entry.status = "running"

    def run() -> None:
        entry.thread_id = threading.get_ident()
        pycmd_runtime.register_channel(entry.handle)
        what = "Python" if language is None else language["name"]
        if plugin_runner is not None:
            what = "a plugin"
        _log(entry, "system", f"Running {os.path.basename(path)} ({what})\n")
        try:
            if plugin_runner is not None:
                _callable_of(plugin_runner)(path, entry.handle)
            elif language is None:
                pycmd_runtime.exec_isolated(path, args=args, channel=entry.handle)
            else:
                _run_language(entry, path, language)
        except KeyboardInterrupt:
            entry.status = "stopped"
            _log(entry, "system", "Stopped.\n")
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
            if code not in (0, None):
                entry.status = "error"
                entry.error = f"exited with code {code}"
                _log(entry, "stderr", f"SystemExit: {code}\n")
            else:
                entry.status = "stopped"
        except BaseException as exc:  # noqa: BLE001
            entry.status = "error"
            entry.error = f"{type(exc).__name__}: {exc}"
            report = pycmd_runtime.format_exception(exc, os.path.basename(path))
            _log(entry, "stderr", report)
            _offer_fix(entry, report, path=path)
        else:
            if entry.status != "error":
                entry.status = "stopped"
                _log(entry, "system", "Script finished.\n")
        finally:
            pycmd_runtime.unregister_channel()

    thread = threading.Thread(target=run, name=f"pycmd-{entry.handle}", daemon=True)
    entry.thread = thread
    with _lock:
        _servers[entry.handle] = entry
    thread.start()

    result = entry.as_dict()
    result["ok"] = True
    return result


def _run_language(entry: "_Entry", path: str, language: dict) -> None:
    """Runs a C, Go or Rust file through its interpreter, on this thread."""
    import sys

    from pycmd_langs import registry

    result = registry.run_file(path, stdout=sys.stdout, stdin=sys.stdin)
    if result.get("ok"):
        code = result.get("exit", 0)
        if code:
            entry.status = "error"
            entry.error = f"exited with status {code}"
            _log(entry, "stderr", f"{language['name']} exited with status {code}\n")
        return

    problem = result.get("error", "could not run this file")
    entry.status = "error"
    entry.error = problem
    _log(entry, "stderr", problem + "\n")
    _offer_fix(entry, problem, path=path)


# ---------------------------------------------------------------------------
# Stopping
# ---------------------------------------------------------------------------


def stop(handle: str, timeout: float = GRACEFUL_TIMEOUT) -> dict:
    """Ask a server to shut down, and wait a little for it to do so."""
    with _lock:
        entry = _servers.get(handle)
    if entry is None:
        return {"ok": False, "error": "That server is no longer tracked."}

    if not entry.alive():
        _forget(handle)
        return {"ok": True, "killed": False, "note": "already stopped"}

    if entry.httpd is not None:
        # shutdown() blocks until serve_forever() returns, so it runs on a
        # helper thread and is waited on with a timeout instead.
        closer = threading.Thread(target=_safe_shutdown, args=(entry,), daemon=True)
        closer.start()
    else:
        pycmd_runtime.interrupt_thread(entry.thread_id, KeyboardInterrupt)

    entry.thread.join(timeout=timeout)
    if entry.alive():
        return {
            "ok": False,
            "error": "Server did not stop in time. Use Kill to force it.",
            "needs_kill": True,
        }

    entry.status = "stopped"
    _forget(handle)
    return {"ok": True, "killed": False}


def _safe_shutdown(entry: _Entry) -> None:
    try:
        entry.httpd.shutdown()
    except Exception:  # noqa: BLE001
        pass


def kill(handle: str) -> dict:
    """Force a server down, for when a graceful stop will not do.

    A thread can be stuck in several different places, so this works through
    all of them rather than trying one and hoping:

    1. Close the listening socket we own. That frees the port even if
       ``serve_forever`` is wedged.
    2. Raise SystemExit inside the thread. That unblocks anything executing
       bytecode.
    3. Knock on the port. A script that opened its own socket is usually
       parked in ``accept()``, and an async exception cannot interrupt a
       blocking C call - but a connection arriving makes ``accept()`` return,
       and the exception fires the moment it does. This is the step that was
       missing, and why Kill appeared to do nothing to a script server that
       had frozen.
    4. Give up tracking it, so a thread wedged in a call that will never
       return does not hold the port, the list and the UI hostage.
    """
    with _lock:
        entry = _servers.get(handle)
    if entry is None:
        return {"ok": False, "error": "That server is no longer tracked."}

    freed_port = False
    if entry.httpd is not None:
        # server_close() first: it releases the socket even if serve_forever()
        # is wedged, which is what actually frees the port.
        try:
            entry.httpd.server_close()
            freed_port = True
        except Exception:  # noqa: BLE001
            pass
        threading.Thread(target=_safe_shutdown, args=(entry,), daemon=True).start()

    pycmd_runtime.interrupt_thread(entry.thread_id, SystemExit)

    if entry.thread is not None:
        entry.thread.join(timeout=1.0)

    if entry.alive():
        # Still there: wake whatever blocking call it is parked in, then ask
        # again. Two rounds, because the first poke often gets it as far as
        # the next bytecode and no further.
        for _ in range(2):
            _wake_blocking_call(entry)
            pycmd_runtime.interrupt_thread(entry.thread_id, SystemExit)
            entry.thread.join(timeout=1.0)
            if not entry.alive():
                break

    still_running = entry.alive()
    entry.status = "error" if still_running else "stopped"
    if still_running:
        entry.error = "Killed, but the thread is still finishing a blocking call."
        _log(entry, "stderr", "Killed. The thread is wedged in a call that has not "
                              "returned yet; it will end when that call does. The "
                              "server is no longer listed either way.\n")
    else:
        _log(entry, "system", "Killed.\n")

    _forget(handle)
    return {
        "ok": True,
        "killed": True,
        "detached": still_running,
        "port_freed": freed_port or not still_running or not _port_held(entry),
    }


def _wake_blocking_call(entry: "_Entry") -> None:
    """Nudges a thread out of accept() or recv() so its exception can land.

    Nothing here can fail in a way that matters: every step is a best-effort
    poke at a socket that may not exist, and a kill must not itself raise.
    """
    # A script that bound a port is almost certainly blocked accepting on it.
    ports = [entry.port] if entry.port else []
    if not ports:
        # No port was declared, so try the one it is actually listening on, if
        # the listing knows. Nothing else can be guessed safely.
        return
    for port in ports:
        for host in ("127.0.0.1", "::1"):
            try:
                family = socket.AF_INET6 if ":" in host else socket.AF_INET
                with socket.socket(family, socket.SOCK_STREAM) as poke:
                    poke.settimeout(0.3)
                    poke.connect((host, port))
                    try:
                        poke.sendall(b"\r\n")
                    except OSError:
                        pass
            except OSError:
                continue

    # A script parked on input() needs no poke here: the app marks the channel
    # cancelled before it calls kill, and the reader hands back end-of-input
    # within a tick of that.


def _port_held(entry: "_Entry") -> bool:
    """Whether the port is still bound by something after a kill."""
    if not entry.port:
        return False
    return not port_available(entry.port, "127.0.0.1")


def _forget(handle: str) -> None:
    with _lock:
        _servers.pop(handle, None)


def stop_all() -> dict:
    with _lock:
        handles = list(_servers)
    stopped, stubborn = 0, []
    for handle in handles:
        result = stop(handle)
        if result.get("ok"):
            stopped += 1
        else:
            stubborn.append(handle)
    return {"ok": True, "stopped": stopped, "needs_kill": stubborn}


def kill_all() -> dict:
    """The panic button: force everything down, whatever state it is in."""
    with _lock:
        handles = list(_servers)
    detached = 0
    for handle in handles:
        result = kill(handle)
        if result.get("detached"):
            detached += 1
    return {"ok": True, "killed": len(handles), "detached": detached}


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def listing() -> list:
    with _lock:
        entries = list(_servers.values())
    return [entry.as_dict() for entry in entries]


def count() -> int:
    with _lock:
        return sum(1 for e in _servers.values() if e.alive())


def log_lines(handle: str, limit: int = 500) -> list:
    """Replay a server's log, so reopening its console is not a blank screen."""
    with _lock:
        entry = _servers.get(handle)
    if entry is None:
        return []
    with entry.log_lock:
        rows = entry.log[-limit:]
    return [{"stream": stream, "text": text} for stream, text in rows]


# ---------------------------------------------------------------------------
# Working out what went wrong
# ---------------------------------------------------------------------------


def _diagnose(text: str, context: dict):
    """Asks the doctor, and never lets a diagnosis break the thing it looked at."""
    try:
        import pycmd_doctor

        return pycmd_doctor.diagnose(text, context)
    except Exception:  # noqa: BLE001
        return None


def _offer_fix(entry, report: str, path: str = "") -> None:
    offer = _diagnose(report, {
        "kind": entry.kind,
        "channel": entry.handle,
        "path": path or entry.target,
        "directory": os.path.dirname(path or entry.target or ""),
        "port": entry.port,
    })
    if offer is None:
        return
    import pycmd_doctor

    _log(entry, "system", pycmd_doctor.describe(offer))


def _offer_index(entry, directory: str) -> None:
    try:
        import pycmd_doctor

        offer = pycmd_doctor.diagnose_missing_index(directory, {"channel": entry.handle})
        if offer is not None:
            _log(entry, "system", pycmd_doctor.describe(offer))
    except Exception:  # noqa: BLE001
        pass


def answer_fix(handle: str, text: str) -> dict:
    """Answers a pending offer on a server's console. Called from the app.

    Returns the moment the reply is understood. The fix runs on its own thread
    and talks through `say`, so answering yes to "install pygame" cannot wedge
    the thread the Stop and Kill buttons come in on - which is what used to
    make a server freeze and then refuse to be killed.
    """
    try:
        import pycmd_doctor
    except Exception as exc:  # noqa: BLE001
        return {"handled": False, "error": str(exc)}

    with _lock:
        entry = _servers.get(handle)

    def say(line: str) -> None:
        target = entry
        if target is None:
            with _lock:
                target = _servers.get(handle)
        if target is not None:
            _log(target, "system", line)
        else:
            pycmd_runtime.emit("system", line, handle)

    try:
        result = pycmd_doctor.answer(handle, text, emit=say)
    except Exception as exc:  # noqa: BLE001
        return {"handled": False, "error": str(exc)}

    if entry is not None and result.get("handled"):
        # Answered, so the next real problem may ask again straight away.
        entry.offered_at = 0.0

    if result.get("handled") and result.get("done"):
        # A fix that finished on the spot said nothing through `say`, so its
        # one line is written here instead.
        say(result.get("message", "") + "\n")
    elif not result.get("handled") and result.get("hint"):
        say(result["hint"] + "\n")
    return result
