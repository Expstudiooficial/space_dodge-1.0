"""Background server management.

A "server" here is any script the user wants to keep running while they do
something else — an HTTP file server, a Flask app, a socket listener. Each one
runs on its own daemon thread and can be stopped independently.
"""

from __future__ import annotations

import http.server
import os
import socket
import socketserver
import threading
import traceback

_servers: dict[str, "_Entry"] = {}
_lock = threading.RLock()
_counter = 0


class _Entry:
    def __init__(self, handle: str, label: str, port: int) -> None:
        self.handle = handle
        self.label = label
        self.port = port
        self.thread: threading.Thread | None = None
        self.httpd: socketserver.BaseServer | None = None
        self.stop_event = threading.Event()
        self.status = "starting"
        self.error = ""


def _next_handle() -> str:
    global _counter
    with _lock:
        _counter += 1
        return f"srv{_counter}"


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


def port_available(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler without the per-request stderr logging.

    The default handler writes a line to stderr for every hit, which would fill
    the console with noise while the user is trying to work in it.
    """

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return None


def start_file_server(directory: str, port: int = 8000) -> dict:
    """Serve a directory over HTTP — the everyday 'python -m http.server'."""
    if not os.path.isdir(directory):
        return {"ok": False, "error": f"Not a directory: {directory}"}
    if not port_available(port):
        return {"ok": False, "error": f"Port {port} is already in use."}

    entry = _Entry(_next_handle(), f"HTTP file server ({os.path.basename(directory) or '/'})", port)

    def handler_factory(*args, **kwargs):
        return _QuietHandler(*args, directory=directory, **kwargs)

    class _Threaded(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    try:
        httpd = _Threaded(("0.0.0.0", port), handler_factory)
    except OSError as exc:
        return {"ok": False, "error": f"Could not bind port {port}: {exc}"}

    entry.httpd = httpd
    entry.status = "running"

    def serve() -> None:
        try:
            httpd.serve_forever(poll_interval=0.5)
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            entry.status = "error"
            entry.error = str(exc)
        finally:
            try:
                httpd.server_close()
            except Exception:
                pass
            if entry.status != "error":
                entry.status = "stopped"

    thread = threading.Thread(target=serve, name=f"pycmd-{entry.handle}", daemon=True)
    entry.thread = thread
    with _lock:
        _servers[entry.handle] = entry
    thread.start()

    return {
        "ok": True,
        "handle": entry.handle,
        "port": port,
        "url": f"http://{local_ip()}:{port}/",
        "label": entry.label,
    }


def start_script(path: str, port: int = 0, label: str = "") -> dict:
    """Run a script on a background thread and track it as a server."""
    if not os.path.isfile(path):
        return {"ok": False, "error": f"No such file: {path}"}

    entry = _Entry(_next_handle(), label or os.path.basename(path), port)
    entry.status = "running"

    def run() -> None:
        import pycmd_runtime

        try:
            pycmd_runtime.run_file(path)
        except BaseException as exc:  # noqa: BLE001
            entry.status = "error"
            entry.error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        else:
            if entry.status != "error":
                entry.status = "stopped"

    thread = threading.Thread(target=run, name=f"pycmd-{entry.handle}", daemon=True)
    entry.thread = thread
    with _lock:
        _servers[entry.handle] = entry
    thread.start()

    result = {"ok": True, "handle": entry.handle, "label": entry.label, "port": port}
    if port:
        result["url"] = f"http://{local_ip()}:{port}/"
    return result


def stop(handle: str) -> dict:
    with _lock:
        entry = _servers.get(handle)
    if entry is None:
        return {"ok": False, "error": "That server is no longer tracked."}

    entry.stop_event.set()
    if entry.httpd is not None:
        try:
            entry.httpd.shutdown()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Could not stop: {exc}"}
    else:
        # Script servers stop through the runtime's cooperative interrupt.
        import pycmd_runtime

        pycmd_runtime.request_stop()

    entry.status = "stopped"
    with _lock:
        _servers.pop(handle, None)
    return {"ok": True}


def stop_all() -> int:
    with _lock:
        handles = list(_servers)
    for handle in handles:
        stop(handle)
    return len(handles)


def listing() -> list:
    with _lock:
        entries = list(_servers.values())
    rows = []
    for entry in entries:
        alive = entry.thread.is_alive() if entry.thread else False
        status = entry.status if alive or entry.status == "error" else "stopped"
        row = {
            "handle": entry.handle,
            "label": entry.label,
            "port": entry.port,
            "status": status,
            "error": entry.error,
        }
        if entry.port:
            row["url"] = f"http://{local_ip()}:{entry.port}/"
        rows.append(row)
    return rows


def count() -> int:
    with _lock:
        return sum(1 for e in _servers.values() if e.thread and e.thread.is_alive())
