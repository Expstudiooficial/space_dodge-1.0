"""The window.

PyCmd's UI has always been half web page - the console, the editor, every
plugin panel and the whole preview are HTML in a WebView, and only the chrome
around them was Compose. So the Windows port keeps the half that was already
portable and replaces the half that was not: the chrome becomes HTML too, and
the window is Edge WebView2, which every Windows 10 and 11 machine has.

That choice is what makes this a port rather than a rewrite. `console.js`,
`editor.js`, `highlight.js` and every plugin's `ui.html` are the same files the
phone loads, byte for byte.

**Why there is an HTTP server in here.** The page could be loaded from
`file://`, and then every relative path, every `fetch`, and every plugin panel
would be fighting the browser's rules about local files. Serving the same
folders over `127.0.0.1` on a random high port removes that whole class of
problem, costs a few milliseconds at start-up, and is bound to the loopback
interface so nothing outside the machine can reach it. The token in the URL is
belt and braces: another program on the same machine that guessed the port
still does not get an answer.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import posixpath
import secrets
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import host as host_module
from . import store, updates

TITLE = "PyCmd"
WINDOW = (1180, 760)
MINIMUM = (860, 560)


class _Handler(BaseHTTPRequestHandler):
    """Serves the app's own files, and nothing else.

    Every path is resolved and then checked to be inside one of the roots.
    That check is the whole security model of this server: a request for
    ``/../../../Windows/System32/config/SAM`` resolves to somewhere outside
    every root and gets a 404 like anything else that is not ours.
    """

    server_version = "PyCmd"
    protocol_version = "HTTP/1.1"

    # Filled in by the server that owns us.
    roots: dict = {}
    token: str = ""

    def log_message(self, *args):  # noqa: D102 - quiet by default
        pass

    def _deny(self, code=404):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _authorised(self, query) -> bool:
        """Whether this request may have anything at all.

        The window opens the entry point with `?t=<token>` and gets the token
        back as a cookie, so every request the page makes afterwards carries
        it without the page having to do anything. Everything is checked, not
        just the first request: the workspace is served from here, and those
        are the user's own files - another program on this machine that
        guessed the port should not be able to read them.
        """
        if not self.token:
            return True
        if query.get("t", [""])[0] == self.token:
            return True
        cookie = self.headers.get("Cookie", "")
        return f"pycmd={self.token}" in cookie

    def _resolve(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if not self._authorised(query):
            return None

        path = urllib.parse.unquote(parsed.path)
        if path in ("", "/"):
            path = "/index.html"
        parts = [p for p in posixpath.normpath(path).split("/") if p not in ("", ".", "..")]
        if not parts:
            return None

        prefix = parts[0]
        root = self.roots.get(prefix)
        if not isinstance(root, str):
            root = None
        if root is not None:
            candidate = os.path.join(root, *parts[1:])
        else:
            candidate = os.path.join(self.roots["_ui"], *parts)

        candidate = os.path.abspath(candidate)
        allowed = [os.path.abspath(value) for key, value in self.roots.items()
                   if isinstance(value, str)]
        if not any(candidate == base or candidate.startswith(base + os.sep)
                   for base in allowed):
            return None
        return candidate if os.path.isfile(candidate) else None

    def do_GET(self):  # noqa: N802
        target = self._resolve()
        if target is None:
            return self._deny()
        try:
            with open(target, "rb") as handle:
                body = handle.read()
        except OSError:
            return self._deny()

        kind = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/javascript", "application/json"):
            kind += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # Handed out on the way in, so the page's own requests carry it.
        # HttpOnly because no script needs to read it, SameSite=Strict
        # because nothing outside this origin should ever send it.
        if self.token and "t=" in urllib.parse.urlsplit(self.path).query:
            self.send_header(
                "Set-Cookie",
                f"pycmd={self.token}; Path=/; HttpOnly; SameSite=Strict",
            )
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        """The same API the window uses, over HTTP.

        `--serve-only` exists so the interface can be opened in a browser -
        which is how it is tested where there is no Windows, and a genuine
        fallback on a machine whose WebView2 is broken. It would be a pretence
        without this: the page can draw, but it could not ask Python anything.

        Same cookie, same rules. This is not a public API and is not reachable
        from off the machine.
        """
        parsed = urllib.parse.urlsplit(self.path)
        if not self._authorised(urllib.parse.parse_qs(parsed.query)):
            return self._deny(403)
        if parsed.path not in ("/api/call", "/api/events"):
            return self._deny()

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > 8 * 1024 * 1024:
            return self._deny(413)
        raw = self.rfile.read(length) if length else b"{}"

        try:
            asked = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            asked = {}

        host = self.roots.get("_host")
        if host is None:
            reply = {"ok": False, "error": "PyCmd is still starting"}
        elif parsed.path == "/api/events":
            reply = {"ok": True, "events": host.drain()}
        else:
            reply = host_module.call(host, str(asked.get("name", "")), asked.get("payload") or {})

        body = json.dumps(reply).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):  # noqa: N802
        target = self._resolve()
        if target is None:
            return self._deny()
        self.send_response(200)
        self.send_header("Content-Length", str(os.path.getsize(target)))
        self.end_headers()


def serve(roots: dict) -> tuple:
    """Starts the loopback server. Returns (url, server)."""
    token = secrets.token_urlsafe(16)
    handler = type("_Bound", (_Handler,), {"roots": roots, "token": token})
    # Port 0 asks the OS for a free one, which avoids both a clash and the
    # guessing game of picking a "probably free" number.
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, name="pycmd-ui", daemon=True).start()
    return f"http://127.0.0.1:{port}/index.html?t={token}", server


class Api:
    """What the page calls. One method in, one method out.

    pywebview hands these straight to JavaScript, so every argument arrives as
    whatever JSON made of it and every return value has to survive the trip
    back. Keeping that to two methods means there is one place to look when
    something does not.
    """

    def __init__(self, host):
        self._host = host

    def call(self, name, payload=None):
        return host_module.call(self._host, str(name), payload or {})

    def events(self):
        """Everything that has happened since the last ask.

        The page polls this rather than being pushed to. Pushing would mean
        `evaluate_js` from whichever thread produced the event, and a console
        printing quickly would then be a thousand cross-thread calls a second.
        One poll that returns a hundred lines is cheaper and simpler.
        """
        return {"ok": True, "events": self._host.drain()}


def _boot(host, window=None):
    """Starts the engine off the UI thread, so the window paints immediately."""
    def work():
        try:
            host.start()
            host.emit("ready", **host_module.call(host, "hello"))
        except Exception as error:  # noqa: BLE001 - a failure here must be visible
            import traceback

            host.log("error", "PyCmd could not start", traceback.format_exc())
            host.emit("boot-failed", error=f"{type(error).__name__}: {error}")

    threading.Thread(target=work, name="pycmd-boot", daemon=True).start()


def build_roots() -> dict:
    """The folders the window may load from."""
    here = os.path.dirname(os.path.abspath(__file__))
    ui = os.path.join(os.path.dirname(here), "ui")
    if not os.path.isdir(ui):
        ui = store.asset("ui")
    assets = store.assets_path()
    return {
        "_ui": ui,
        "web": os.path.join(assets, "web"),
        "plugins": store.folder("plugins"),
        "docs": os.path.join(assets, "docs"),
        "workspace": store.folder("workspace"),
        "wdocs": os.path.join(store.bundled(), "windows", "docs"),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pycmd", description="PyCmd for Windows")
    parser.add_argument("--home", help="keep everything here instead of %LOCALAPPDATA%")
    parser.add_argument("--serve-only", action="store_true",
                        help="start the UI server and print its address, without a window")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)

    if args.version:
        print(f"PyCmd for Windows {host_module.VERSION}")
        return 0

    if args.home:
        store.use(args.home)

    host = host_module.Host()
    roots = build_roots()
    roots["_host"] = host
    url, server = serve(roots)

    if args.serve_only:
        _boot(host)
        print(url, flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
        return 0

    try:
        import webview
    except ImportError:
        sys.stderr.write(
            "PyCmd needs pywebview to open a window.\n"
            "    pip install pywebview\n"
            "On Windows it uses Edge WebView2, which Windows 10 and 11 already have.\n"
            f"\nThe interface is running at {url} if you would rather use a browser.\n"
        )
        return 2

    api = Api(host)
    window = webview.create_window(
        TITLE, url, js_api=api,
        width=WINDOW[0], height=WINDOW[1],
        min_size=MINIMUM, background_color="#0B0F14",
        text_select=True,
    )
    _boot(host, window)
    updates.start_background_check(host)
    webview.start(debug=bool(os.environ.get("PYCMD_DEBUG")))
    server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
