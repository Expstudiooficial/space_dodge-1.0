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


def _log(entry: _Entry, stream: str, text: str) -> None:
    """Record on the Python side and push to the UI channel in one step."""
    entry.add_log(stream, text)
    pycmd_runtime.emit(stream, text, entry.handle)


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
            _log(entry, "stderr", f"{fmt % args}\n")

    class Threaded(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    try:
        httpd = Threaded((host, port), Handler)
    except OSError as exc:
        return {"ok": False, "error": f"Could not bind {host}:{port} - {exc}"}

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


def start_script(
    path: str,
    port: int = 0,
    host: str = "0.0.0.0",
    label: str = "",
    args=None,
) -> dict:
    """Run a script on a background thread and track it as a server.

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

    entry = _Entry(_next_handle(), label or os.path.basename(path), "script", port, host)
    entry.target = path
    entry.status = "running"

    def run() -> None:
        entry.thread_id = threading.get_ident()
        pycmd_runtime.register_channel(entry.handle)
        _log(entry, "system", f"Running {os.path.basename(path)}\n")
        try:
            pycmd_runtime.exec_isolated(path, args=args, channel=entry.handle)
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
            _log(entry, "stderr", pycmd_runtime.format_exception(exc, os.path.basename(path)))
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

    Three escalating steps, because a thread can be stuck in different places:
    close the listening socket (frees the port and unblocks accept), raise
    SystemExit inside the thread (unblocks bytecode), and if it still will not
    die, stop tracking it so the port and the UI are not held hostage by a
    thread that is wedged in a C call.
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
        entry.thread.join(timeout=2.0)

    still_running = entry.alive()
    entry.status = "error" if still_running else "stopped"
    if still_running:
        entry.error = "Killed, but the thread is still finishing a blocking call."
        _log(entry, "stderr", "Killed. The thread is wedged in a blocking call "
                              "and will end when that call returns.\n")
    else:
        _log(entry, "system", "Killed.\n")

    _forget(handle)
    return {
        "ok": True,
        "killed": True,
        "detached": still_running,
        "port_freed": freed_port or not still_running,
    }


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
