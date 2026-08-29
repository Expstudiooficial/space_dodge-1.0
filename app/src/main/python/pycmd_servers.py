"""Background servers: static folders and long-running scripts.

Each server owns a thread, a log channel, and a stop path. Two stop paths,
really — a graceful one that asks the server to close, and a kill that stops
waiting and forces the thread down. The kill exists because the whole point of
running your own code is that it sometimes hangs before it ever finishes
starting, and a stop button that politely waits for a server that never came up
is not a stop button.

A folder is a project, not a pile of files. Pointing Run at one used to mean
"hand it to a file server", so a Flask project answered with a directory
listing of `static/` and `templates/` - the files, correct and useless.
`folder_plan` looks inside instead and finds the front door: a script that
serves (`app.py` and friends, confirmed by what it imports), a page to open
(`index.html`), or the one runnable file in there. A listing is what is left
when there is genuinely nothing to run, and then it says so on the page.
"""

from __future__ import annotations

import http.server
import io
import os
import re
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
    "folder_plan",
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

# What a project calls its front door. Ordered: the first one found wins, and
# the order is the one people mean when a folder holds more than one of them.
ENTRY_SCRIPTS = (
    "app.py", "server.py", "wsgi.py", "asgi.py", "manage.py",
    "main.py", "run.py", "start.py", "index.py", "__main__.py",
)

# A page a folder is meant to open at.
ENTRY_PAGES = ("index.html", "index.htm")

# Imports that mean a script serves something itself, rather than being a
# helper that happens to sit beside the real one.
WEB_MARKERS = (
    "flask", "django", "fastapi", "bottle", "aiohttp", "quart", "starlette",
    "http.server", "socketserver", "wsgiref", "socket", "uvicorn", "waitress",
    "tornado",
)

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
        # Same idea for the https-on-an-http-port notice: said once, not once
        # per refused handshake, and a browser makes several.
        self.tls_warned_at = 0.0
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


def _looks_like_tls(text: str) -> bool:
    """Whether a rejected request was really a TLS handshake.

    http.server reports it as a bad request version, quoting the raw bytes: a
    ClientHello starts 0x16 0x03, which lands in the message as \\x16\\x03.
    """
    lowered = text.lower()
    return "\\x16\\x03" in lowered or (
        "bad request version" in lowered and "\\x" in lowered
    )


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
    _learn_port(entry, text)


def _learn_port(entry: "_Entry", text: str) -> None:
    """Takes the real port from what a framework prints when it starts.

    The card shows the port the form asked for, which is a guess until the
    thing that binds it says otherwise: a Flask app with `app.run(port=5000)`
    listens on 5000 whatever the form said, and a View button pointing at the
    other number is how a working server looks broken.
    """
    if entry.kind != "script":
        return
    match = _LISTENING.search(text)
    if match is None:
        return
    found = int(match.group(1))
    if found == entry.port or not 1 <= found <= 65535:
        return
    entry.port = found
    # Through _log, so it reaches the console being watched right now and not
    # only the copy replayed when the console is reopened. No recursion: _log
    # marks the thread, and this observer steps aside for its own lines.
    _log(entry, "system", f"It is listening on port {found}.\n")


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


_LISTING_CSS = """
:root { color-scheme: dark; }
body { margin: 0; padding: 18px; background: #0B1017; color: #D7E0EA;
       font: 15px/1.55 -apple-system, Roboto, system-ui, sans-serif; }
h1 { font-size: 19px; margin: 0 0 4px; color: #F2F6FA; word-break: break-all; }
.where { color: #7C8CA0; font-size: 13px; margin: 0 0 16px; }
ul { list-style: none; margin: 0; padding: 0; }
li { border-top: 1px solid #17222E; }
li:last-child { border-bottom: 1px solid #17222E; }
a { display: flex; gap: 10px; align-items: baseline; padding: 11px 4px;
    color: #8FC7FF; text-decoration: none; }
a:hover { background: #101A24; }
.name { flex: 1; word-break: break-all; }
.tag { font-size: 12px; color: #6F8296; white-space: nowrap; }
.dir .name { color: #FFD79A; }
.note { margin: 16px 0 0; padding: 12px 14px; border-radius: 10px;
        background: #121A24; border: 1px solid #1E2A38; color: #A9B8C8;
        font-size: 13px; }
.note b { color: #E7EEF5; }
"""


def _listing_page(path: str, url_path: str, root: str) -> str:
    """The page a folder with no index.html shows.

    Python's own listing is a bare `<ul>` of names, which is where "I asked it
    to run my project" ends up looking like a filing cabinet. This one says
    where you are, what each thing is, and - at the top of the tree - what is
    missing for this to be a site rather than a list.
    """
    import html as html_escape
    import urllib.parse

    try:
        from pycmd_langs import registry
    except Exception:  # noqa: BLE001
        registry = None

    names = sorted(os.listdir(path), key=lambda item: (not os.path.isdir(
        os.path.join(path, item)), item.lower()))
    shown = os.path.basename(path.rstrip(os.sep)) or "/"
    rows = []

    if os.path.abspath(path) != os.path.abspath(root):
        rows.append("<li class='dir'><a href='..'><span class='name'>..</span>"
                    "<span class='tag'>up</span></a></li>")

    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(path, name)
        link = urllib.parse.quote(name)
        label = html_escape.escape(name)
        if os.path.isdir(full):
            rows.append(f"<li class='dir'><a href='{link}/'><span class='name'>{label}/"
                        "</span><span class='tag'>folder</span></a></li>")
            continue
        try:
            size = _readable_bytes(os.path.getsize(full))
        except OSError:
            size = ""
        tag = size
        if registry is not None:
            mode = registry.for_path(name)["mode"]
            extension = os.path.splitext(name)[1].lower()
            if mode == "run" or extension in _runners:
                tag = f"runnable &middot; {size}"
            elif mode == "media":
                tag = f"media &middot; {size}"
        rows.append(f"<li><a href='{link}'><span class='name'>{label}</span>"
                    f"<span class='tag'>{tag}</span></a></li>")

    if not rows:
        rows.append("<li><a href='.'><span class='name'>nothing in here</span></a></li>")

    note = ""
    if os.path.abspath(path) == os.path.abspath(root):
        plan = folder_plan(root)
        if plan["hint"]:
            note = (f"<p class='note'><b>Why you are looking at a list.</b> "
                    f"{html_escape.escape(plan['hint'])}</p>")
        elif plan["how"] == "script" and plan["entry"]:
            # Served on purpose, since the launcher offers to run this one
            # instead - but the page somebody is staring at should still say
            # that the list is not all there is.
            entry = html_escape.escape(plan["entry"])
            note = (f"<p class='note'><b>{entry} is in here.</b> This is the folder "
                    "served as files. To run it instead, go back to Servers, choose "
                    f"<b>Run a file</b>, pick this folder, and PyCmd starts {entry}.</p>")

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html_escape.escape(shown)}</title><style>{_LISTING_CSS}</style>"
        f"</head><body><h1>{html_escape.escape(shown)}</h1>"
        f"<p class='where'>{html_escape.escape(url_path)}</p>"
        f"<ul>{''.join(rows)}</ul>{note}</body></html>"
    )


def _readable_bytes(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    if size >= 1024:
        return f"{size // 1024} KB"
    return f"{size} B"


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

        def list_directory(self, path):
            """A folder with no index.html, shown as something readable."""
            try:
                body = _listing_page(path, self.path, directory).encode("utf-8", "replace")
            except OSError:
                self.send_error(404, "That folder cannot be listed")
                return None
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return io.BytesIO(body)

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            entry.requests += 1
            if log_requests:
                _log(entry, "stdout", f"{self.address_string()}  {fmt % args}\n")

        def log_error(self, fmt: str, *args) -> None:  # noqa: A003
            text = f"{fmt % args}\n"
            # A browser that decided to try https first sends a TLS handshake,
            # which arrives here as unparseable bytes. Saying so beats a wall
            # of "Bad request version" for something the user cannot see.
            if _looks_like_tls(text):
                if time.time() - entry.tls_warned_at > OFFER_COOLDOWN:
                    entry.tls_warned_at = time.time()
                    _log(entry, "system",
                         "Something tried to reach this server over https. It only "
                         f"speaks plain http: open {entry.as_dict()['url']} - with "
                         "http:// typed in front, or the browser will keep guessing "
                         "https and failing.\n")
                return
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


def _reads_as_web(path: str) -> str:
    """The framework a script serves with, or "" if it only computes.

    Read rather than guessed: `app.py` beside a `templates/` folder is almost
    always the thing to run, but a `main.py` that crunches numbers is not a
    server and pretending otherwise would start something nobody asked for.
    Only the head of the file, because imports live at the top.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(8192).lower()
    except OSError:
        return ""
    for marker in WEB_MARKERS:
        if f"import {marker}" in head or f"from {marker}" in head:
            return marker
    return ""


def _runnable_in(directory: str) -> list:
    """Top-level files this device can actually execute, in listing order."""
    try:
        from pycmd_langs import registry
    except Exception:  # noqa: BLE001
        registry = None

    found = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return found
    for name in names:
        full = os.path.join(directory, name)
        if not os.path.isfile(full) or name.startswith("."):
            continue
        extension = os.path.splitext(name)[1].lower()
        if extension in (".py", ".pyw") or extension in _runners:
            found.append(name)
            continue
        if registry is not None and registry.for_path(name)["mode"] == "run":
            found.append(name)
    return found


def folder_plan(directory: str) -> dict:
    """What "run this folder" should mean for this particular folder.

    A folder used to mean one thing - hand it to a static file server - which
    is why pointing PyCmd at a Flask project produced a directory listing of
    `static/` and `templates/` instead of the site. A folder is a project, and
    a project has a front door: `app.py`, `index.html`, or the one runnable
    file in there. This finds it, and says which it found so the launcher can
    print that before anything starts.

    Returns `how` ("script", "serve"), `entry` (a name inside the folder, or
    "" for a plain listing), `language`, `note`, and `hint` - a sentence for
    the cases where the honest answer is "the thing you want is not in here".
    """
    directory = os.path.abspath(directory)
    name = os.path.basename(directory) or "this folder"
    listing_note = f"Serves {name} over HTTP as a file listing."

    if not os.path.isdir(directory):
        return {"how": "serve", "entry": "", "language": "Folder",
                "note": listing_note, "hint": "", "serves": False}

    def has(child: str) -> bool:
        return os.path.isfile(os.path.join(directory, child))

    # 1. A script that serves something is the front door, even when there is
    #    an index.html beside it: the app is what puts the page together.
    for candidate in ENTRY_SCRIPTS:
        if not has(candidate):
            continue
        framework = _reads_as_web(os.path.join(directory, candidate))
        if framework:
            return {
                "how": "script",
                "entry": candidate,
                "language": "Python",
                "note": f"Runs {candidate}, which serves with {framework}.",
                "hint": "",
                "serves": True,
            }

    # 2. Otherwise a page to open, served with its folder around it.
    for page in ENTRY_PAGES:
        if has(page):
            return {"how": "serve", "entry": page, "language": "HTML",
                    "note": f"Serves {name} and opens {page}.", "hint": "",
                    "serves": False}

    # 3. Otherwise an entry script that does not serve: still the front door.
    for candidate in ENTRY_SCRIPTS:
        if has(candidate):
            return {"how": "script", "entry": candidate, "language": "Python",
                    "note": f"Runs {candidate}.", "hint": "", "serves": False}

    # 4. Otherwise, if exactly one file in here can run, that is the answer.
    runnable = _runnable_in(directory)
    if len(runnable) == 1:
        only = runnable[0]
        return {"how": "script", "entry": only, "language": "",
                "note": f"Runs {only}, the only runnable file in here.", "hint": "",
                "serves": bool(_reads_as_web(os.path.join(directory, only)))}

    # 5. Nothing to run. Serve it - but say what is missing, because a listing
    #    of static/ and templates/ is the shape of a project whose code lives
    #    one floor up, and that is worth saying rather than shrugging.
    hint = ""
    if os.path.isdir(os.path.join(directory, "templates")):
        hint = (
            "This looks like the inside of a Flask project: templates/ holds pages "
            "that only mean something once the app renders them. The app.py that "
            "does that is usually the folder above this one - point Run at that "
            "instead, and this listing becomes the site."
        )
    elif len(runnable) > 1:
        hint = (
            "There are several files in here that could run ("
            + ", ".join(runnable[:4])
            + (", ..." if len(runnable) > 4 else "")
            + ") and no app.py or index.html to choose between them. Point Run at "
            "the one you meant and PyCmd will run that."
        )
    else:
        hint = (
            "No index.html and nothing runnable in here, so this is a file listing. "
            "Add an index.html and it becomes a site; add an app.py and Run starts it."
        )
    return {"how": "serve", "entry": "", "language": "Folder",
            "note": listing_note, "hint": hint, "serves": False}


def how_to_run(path: str) -> dict:
    """What pressing Run in the Servers tab would actually do with this file.

    The Servers tab asks first so it can say so in the form, rather than
    starting something and explaining afterwards.
    """
    if os.path.isdir(path):
        plan = folder_plan(path)
        note = plan["note"]
        if plan["hint"]:
            note = note + " " + plan["hint"]
        return {"how": plan["how"], "language": plan["language"], "note": note,
                "entry": plan["entry"]}

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
        # A folder is a project, not a pile of files. If there is a front door
        # in there - app.py, index.html, the one runnable file - that is what
        # "run this" meant; a listing is what is left when there is not.
        plan = folder_plan(path)
        entry = plan["entry"]
        if plan["how"] == "script" and entry:
            # A port is claimed for something that will listen. A plain script
            # that happens to be the folder's entry point binds nothing, and
            # refusing to start it because port 8000 was busy would be a rule
            # about a port it was never going to use.
            serves = bool(plan.get("serves"))
            return start_script(
                os.path.join(path, entry),
                port=port or (suggest_port(8000, host) if serves else 0),
                host=host,
                label=label or f"{os.path.basename(path)}/{entry}",
                args=args,
                serves=serves,
            )
        result = start_static(
            path,
            port=port or suggest_port(8000, host),
            host=host,
            label=label or os.path.basename(path) or "workspace",
        )
        if result.get("ok") and entry and result.get("url"):
            result["url"] = result["url"].rstrip("/") + "/" + entry
            result["opens"] = entry
        return result
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


# Where the server running on this thread was told to listen. Thread-local,
# because two servers run at once and one must not answer for the other.
_binding = threading.local()


def _bind_web_frameworks(entry: "_Entry", host: str, port: int) -> None:
    """Point a web framework at the host and port the launcher chose.

    Only fills in what the code left out. `app.run(port=5000)` still binds
    5000 - it said so - and PyCmd corrects the port it shows instead of
    overruling the file. What this does fix is the ordinary case: `app.run()`
    on a phone binds 127.0.0.1:5000, which the phone's own browser cannot
    reach at the address the Servers tab is showing, and turns on a reloader
    that re-executes the interpreter - something an Android app may not do.
    """
    _binding.value = (host, port, entry)
    os.environ["PORT"] = str(port)
    os.environ["HOST"] = host
    os.environ["FLASK_RUN_PORT"] = str(port)
    os.environ["FLASK_RUN_HOST"] = host
    _patch_flask()
    _log(entry, "system",
         f"Anything this starts with a framework will listen on {host}:{port} "
         "unless the code names its own.\n")


def _unbind_web_frameworks() -> None:
    _binding.value = None


def _patch_flask() -> None:
    """Teaches Flask's `run` to take PyCmd's host and port as its defaults.

    Patched once, and it does nothing on a thread that is not a PyCmd server,
    so a Flask app started any other way behaves exactly as it always did.
    """
    try:
        import flask
    except Exception:  # noqa: BLE001 - flask is optional, this is a courtesy
        return
    if getattr(flask.Flask.run, "_pycmd_patched", False):
        return

    original = flask.Flask.run

    def run(self, host=None, port=None, debug=None, **options):  # noqa: ANN001
        chosen = getattr(_binding, "value", None)
        if chosen is not None:
            wanted_host, wanted_port, entry = chosen
            if host is None:
                host = wanted_host
            elif host in ("127.0.0.1", "localhost") and wanted_host == "0.0.0.0":
                _log(entry, "system",
                     f"This app asks for host {host}, so only this phone can open "
                     "it. Change it to 0.0.0.0 to reach it from another device.\n")
            if port is None:
                port = wanted_port
            elif int(port) != wanted_port:
                _log(entry, "system",
                     f"This app asks for port {port}, so that is where it is, not "
                     f"{wanted_port}.\n")
                entry.port = int(port)
            # Werkzeug's reloader restarts the interpreter, which is not a
            # thing an Android app can do. Off, unless the code insists.
            options.setdefault("use_reloader", False)
        return original(self, host=host, port=port, debug=debug, **options)

    run._pycmd_patched = True
    flask.Flask.run = run


# What a framework prints when it finally knows where it is listening. The
# port on the server card comes from the form; this is the port it really got.
_LISTENING = re.compile(
    r"(?:running on|serving on|listening on|started server on)\s+"
    r"https?://(?:[^\s:/]+):(\d{2,5})",
    re.IGNORECASE,
)


def start_script(
    path: str,
    port: int = 0,
    host: str = "0.0.0.0",
    label: str = "",
    args=None,
    serves: bool = False,
) -> dict:
    """Run a file on a background thread and track it as a server.

    `port` is informational for a script - the script binds it itself - but it
    is checked first so a doomed run fails immediately with a clear message
    rather than deep inside somebody's traceback.

    `serves` says this script is expected to listen, which is worth knowing:
    a Flask app written on a laptop says `app.run()`, and that binds
    127.0.0.1:5000 with the auto-reloader on. On a phone that is a server
    nothing can reach, restarting itself with a process launcher Android does
    not have. With `serves` set, PyCmd fills in the host and port the form
    asked for - only where the code left them unsaid - and says so in the log.
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
        if serves and port:
            _bind_web_frameworks(entry, host, port)
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
            _unbind_web_frameworks()
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
