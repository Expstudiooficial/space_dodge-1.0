"""A public address for a page running on the phone.

A phone is behind carrier NAT. Nothing on the internet can dial it, whatever
port is open, so "anyone anywhere can see my page" cannot be done by this app
alone - something with a public address has to accept the connection and pass
it down to us. That is what a tunnel is, and this is a tunnel client.

The protocol is localtunnel's, which is small enough to implement honestly:

1. `GET https://localtunnel.me/?new` hands back an id, a TCP port, how many
   connections to keep open, and the URL that will point at us.
2. The client opens that many TCP connections to the same host on that port.
   Each one sits idle until a visitor arrives, at which point the server pipes
   the visitor's bytes down it.
3. The client opens a connection to the local page, pumps bytes both ways
   until either side closes, and then opens a fresh relay to replace the one
   it just used.

There is no framing and no protocol of our own on top: it is a byte pipe, so
whatever the page speaks - HTTP, server-sent events, anything - crosses
unchanged.

What this is not:

* **Not a stable address.** The URL is random, and a new one is issued every
  time. Nothing here can give you `yourname.com`; Cloudflare Pages can, and
  `pycmd_cloudflare` is the door to it.
* **Not up when the app is not.** The tunnel is threads in this process. Close
  the app and the address stops answering.
* **Not private.** Anybody with the URL can reach the page, and the URL is not
  a secret - it is a name on somebody else's server. Do not put behind it what
  you would not put on the open web.
* **Not ours.** localtunnel.me is a free service run by other people. It is
  down sometimes, and when it is, this says so rather than pretending.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["open_tunnel", "close", "close_all", "status", "listing", "point_at"]

DEFAULT_SERVICE = "https://localtunnel.me"
SERVICE = DEFAULT_SERVICE

# How long to wait on the handshake before deciding the service is not there.
REQUEST_TIMEOUT = 20

# How long a relay socket waits before looking at the stop flag again. A tunnel
# that only notices it should close when a visitor arrives is not a tunnel that
# closes.
IDLE_TICK = 1.0

# Relay sockets kept open at once. The service suggests a number; this is the
# ceiling, because each one is a thread on a phone.
MAX_RELAYS = 6

_tunnels: dict = {}
_lock = threading.RLock()


def point_at(service: str = "") -> dict:
    """Uses a different tunnel service, or puts the default back."""
    global SERVICE

    service = (service or "").strip().rstrip("/")
    if not service:
        SERVICE = DEFAULT_SERVICE
        return {"ok": True, "service": SERVICE}
    local = service.startswith("http://127.0.0.1") or service.startswith("http://localhost")
    if not local and not service.startswith("https://"):
        return {"ok": False, "error": "a tunnel service has to be https"}
    SERVICE = service
    return {"ok": True, "service": SERVICE}


class _Tunnel:
    """One page's tunnel: a handful of relay threads and the URL they serve."""

    def __init__(self, key: str, local_port: int, url: str, host: str, port: int, relays: int):
        self.key = key
        self.local_port = local_port
        self.url = url
        self.host = host
        self.port = port
        self.relays = relays
        self.stop = threading.Event()
        self.threads: list = []
        self.opened = time.time()
        self.served = 0
        self.error = ""

    def as_dict(self) -> dict:
        return {
            "id": self.key,
            "url": self.url,
            "local_port": self.local_port,
            "relays": self.relays,
            "served": self.served,
            "uptime": int(time.time() - self.opened),
            "alive": any(thread.is_alive() for thread in self.threads),
            "error": self.error,
        }


def _handshake() -> dict:
    """Asks the service for an address. Raises on anything that is not one."""
    url = f"{SERVICE}/?new"
    request = urllib.request.Request(url, headers={"User-Agent": "PyCmd-tunnel"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = json.loads(response.read(64 * 1024).decode("utf-8", "replace"))
    if not payload.get("url") or not payload.get("port"):
        raise ValueError("the tunnel service answered without an address")
    return payload


def _pump(source: socket.socket, target: socket.socket, stop: threading.Event) -> None:
    """Copies bytes one way until the source ends or the tunnel is closed."""
    source.settimeout(IDLE_TICK)
    while not stop.is_set():
        try:
            chunk = source.recv(32 * 1024)
        except socket.timeout:
            continue
        except OSError:
            return
        if not chunk:
            return
        try:
            target.sendall(chunk)
        except OSError:
            return


def _relay(tunnel: _Tunnel) -> None:
    """One relay: wait for a visitor, hand them the page, then do it again."""
    while not tunnel.stop.is_set():
        remote = None
        local = None
        try:
            remote = socket.create_connection((tunnel.host, tunnel.port), timeout=REQUEST_TIMEOUT)
            remote.settimeout(IDLE_TICK)

            # Nothing arrives until a visitor does, so this waits - in ticks,
            # so closing the tunnel does not have to wait for one.
            first = b""
            while not tunnel.stop.is_set():
                try:
                    first = remote.recv(32 * 1024)
                    break
                except socket.timeout:
                    continue
                except OSError:
                    break
            if not first or tunnel.stop.is_set():
                continue

            local = socket.create_connection(("127.0.0.1", tunnel.local_port), timeout=10)
            local.sendall(first)
            tunnel.served += 1

            back = threading.Thread(
                target=_pump, args=(local, remote, tunnel.stop),
                name=f"pycmd-tunnel-{tunnel.key}-down", daemon=True,
            )
            back.start()
            _pump(remote, local, tunnel.stop)
            back.join(timeout=2)
        except OSError as error:
            tunnel.error = str(error)
            # A service that has gone away should not be hammered.
            if tunnel.stop.wait(2.0):
                return
        finally:
            for handle in (remote, local):
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass


def open_tunnel(key: str, local_port: int) -> dict:
    """Opens a tunnel to a port on this phone. Returns the public URL."""
    if not local_port:
        return {"ok": False, "error": "which port?"}

    with _lock:
        existing = _tunnels.get(key)
        if existing is not None and not existing.stop.is_set():
            return {"ok": True, "url": existing.url, "already": True}

    try:
        payload = _handshake()
    except urllib.error.HTTPError as error:
        return {"ok": False, "error": f"The tunnel service refused us (HTTP {error.code}). "
                                      "It is a free service and does that when it is busy - "
                                      "try again in a minute."}
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as error:
        return {"ok": False, "error": f"Could not reach the tunnel service: {error}"}

    url = payload["url"]
    # The relays are dialled on the *service* host, not on the subdomain it
    # just handed out: `abc.loca.lt` is a name their front end answers for
    # visitors, while the port for relay connections is on the service itself.
    # Getting this backwards produces a tunnel that opens, reports a URL, and
    # never carries a single request.
    host = urllib.parse.urlparse(SERVICE).hostname or urllib.parse.urlparse(url).hostname
    relays = max(1, min(int(payload.get("max_conn_count", 3) or 3), MAX_RELAYS))

    tunnel = _Tunnel(key, int(local_port), url, host, int(payload["port"]), relays)
    for index in range(relays):
        thread = threading.Thread(
            target=_relay, args=(tunnel,),
            name=f"pycmd-tunnel-{key}-{index}", daemon=True,
        )
        tunnel.threads.append(thread)
        thread.start()

    with _lock:
        _tunnels[key] = tunnel
    return {"ok": True, "url": url, "relays": relays, "host": host}


def close(key: str) -> dict:
    with _lock:
        tunnel = _tunnels.pop(key, None)
    if tunnel is None:
        return {"ok": True, "already": True}
    tunnel.stop.set()
    for thread in tunnel.threads:
        thread.join(timeout=2)
    return {"ok": True, "url": tunnel.url}


def close_all() -> dict:
    with _lock:
        keys = list(_tunnels)
    for key in keys:
        close(key)
    return {"ok": True, "closed": len(keys)}


def status(key: str) -> dict:
    with _lock:
        tunnel = _tunnels.get(key)
    return tunnel.as_dict() if tunnel else {"id": key, "url": "", "alive": False}


def listing() -> list:
    with _lock:
        return [tunnel.as_dict() for tunnel in _tunnels.values()]
