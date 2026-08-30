"""Pages - websites that live in the app and can be switched on.

The Servers tab starts one thing and watches it. That is the right shape for
"run this file", and the wrong shape for "I have seven sites and three of them
should be up". A page is the second thing: a folder that has been named, given
a port, and remembered - so switching it on later is a tap rather than a
launch form filled in again from memory.

What a page *is* stays deliberately thin. It is a folder in the workspace and a
row in a registry, and running one hands the folder to `pycmd_servers`, which
already knows what running a folder means: a Flask `app.py` is started, an
`index.html` is served, a single runnable file is run. Nothing here re-invents
any of that, and a page you built by hand in Files is a page this can adopt.

Two limits, which the app shows rather than discovers:

* **70 projects.** A registry, not a filesystem: past a certain number a list
  stops being something you can look at.
* **25 running at once.** Every running page is a thread and a socket, and a
  phone that is holding seventy of them is a phone doing nothing else.

The address a page gets is the phone's own - a LAN address that works for
anyone on the same wifi. Reaching it from anywhere else needs either a tunnel
(`pycmd_tunnel`) or a real host (`pycmd_cloudflare`), and both are the page's
choice rather than something done to it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time

import pycmd_servers

__all__ = [
    "configure",
    "listing",
    "create",
    "adopt",
    "rename",
    "remove",
    "start",
    "stop",
    "stop_all",
    "detail",
    "templates",
    "MAX_PROJECTS",
    "MAX_ACTIVE",
]

# A list you can still read, and a number of threads a phone can still carry.
MAX_PROJECTS = 70
MAX_ACTIVE = 25

# Ports handed out to pages, kept away from the 8000s the Servers tab suggests
# so that starting a page never collides with a server somebody launched.
PORT_FROM = 8600
PORT_TO = 8999

_root = ""
_registry_path = ""
_lock_note = "pycmd_pages.configure() has not been called"


def configure(pages_dir: str) -> str:
    """Called once by the app. Everything below lives under this folder."""
    global _root, _registry_path

    _root = os.path.abspath(pages_dir)
    os.makedirs(_root, exist_ok=True)
    _registry_path = os.path.join(_root, "pages.json")
    return _root


def _require() -> str:
    if not _root:
        raise RuntimeError(_lock_note)
    return _root


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def _read() -> list:
    try:
        with open(_registry_path, "r", encoding="utf-8") as handle:
            rows = json.load(handle)
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def _write(rows: list) -> None:
    _require()
    # Written to a neighbour and moved into place: the registry is the only
    # record of what a page is, and a half-written one loses every page.
    temporary = _registry_path + ".part"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    os.replace(temporary, _registry_path)


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", str(name)).strip()
    return cleaned[:48]


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", _safe_name(name).lower()).strip("-")
    return slug or "page"


def _free_port(rows: list) -> int:
    taken = {row.get("port") for row in rows}
    for port in range(PORT_FROM, PORT_TO + 1):
        if port in taken:
            continue
        if pycmd_servers.port_available(port):
            return port
    # Every port in the range is spoken for, which needs saying rather than
    # silently reusing one and failing at bind time.
    return 0


def _running() -> dict:
    """Handles of pages that are actually listening, by page id."""
    alive = {}
    for row in pycmd_servers.listing():
        if row.get("status") == "running":
            alive[row.get("handle")] = row
    return alive


def _decorate(row: dict, alive: dict) -> dict:
    handle = row.get("handle", "")
    server = alive.get(handle)
    folder = row.get("folder", "")
    return {
        **row,
        "running": server is not None,
        "url": (server or {}).get("url", ""),
        "requests": (server or {}).get("requests", 0),
        "uptime": (server or {}).get("uptime", 0),
        "files": _count_files(folder),
        "bytes": _folder_bytes(folder),
        "exists": os.path.isdir(folder),
    }


def _count_files(folder: str) -> int:
    total = 0
    for _walk, _folders, names in os.walk(folder):
        total += len(names)
        if total > 5000:
            break
    return total


def _folder_bytes(folder: str) -> int:
    """How big a page is, stopping rather than walking a huge tree.

    This runs on every listing, and a listing runs whenever the tab is opened.
    A page with a thousand files does not need measuring to the byte for a line
    that says roughly how big it is.
    """
    total = 0
    seen = 0
    for walk, _folders, names in os.walk(folder):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(walk, name))
            except OSError:
                pass
            seen += 1
            if seen >= 5000:
                return total
    return total


def listing() -> list:
    """Every page, with whether it is up and where."""
    alive = _running()
    return [_decorate(row, alive) for row in _read()]


def detail(page_id: str) -> dict:
    """One page, with what the Servers tab would do with its folder."""
    alive = _running()
    row = next((r for r in _read() if r.get("id") == page_id), None)
    if row is None:
        return {"ok": False, "error": "no page with that id"}
    decorated = _decorate(row, alive)
    plan = pycmd_servers.folder_plan(row.get("folder", ""))
    return {"ok": True, "page": decorated, "plan": plan}


def counts() -> dict:
    rows = _read()
    alive = _running()
    return {
        "projects": len(rows),
        "max_projects": MAX_PROJECTS,
        "active": sum(1 for row in rows if row.get("handle") in alive),
        "max_active": MAX_ACTIVE,
    }


# ---------------------------------------------------------------------------
# Templates: what a new page starts as
# ---------------------------------------------------------------------------


TEMPLATES = {
    "static": {
        "title": "A page",
        "about": "index.html, a stylesheet and a script. Served as files.",
        "needs": [],
    },
    "python": {
        "title": "A Python site",
        "about": "app.py with Flask, templates and static files. Runs as a program.",
        "needs": ["flask"],
    },
    "api": {
        "title": "A JSON API",
        "about": "app.py answering /api with JSON, and a page that calls it.",
        "needs": ["flask"],
    },
    "empty": {
        "title": "Empty",
        "about": "A folder and nothing else. Put in whatever you like.",
        "needs": [],
    },
}


def templates() -> list:
    return [{"id": key, **value} for key, value in TEMPLATES.items()]


def _write_file(folder: str, name: str, text: str) -> None:
    path = os.path.join(folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _fill(folder: str, template: str, title: str) -> None:
    if template == "empty":
        return

    if template == "static":
        _write_file(folder, "index.html",
                    '<!doctype html>\n<html>\n<head>\n  <meta charset="utf-8">\n'
                    '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
                    f'  <title>{title}</title>\n'
                    '  <link rel="stylesheet" href="style.css">\n</head>\n<body>\n'
                    f'  <h1>{title}</h1>\n'
                    '  <p>Served from a phone. Edit index.html and refresh.</p>\n'
                    '  <button id="go">Press me</button>\n'
                    '  <script src="app.js"></script>\n</body>\n</html>\n')
        _write_file(folder, "style.css",
                    'body { font: 16px system-ui; margin: 0; padding: 32px;\n'
                    '       background: #0B1017; color: #D7E0EA; }\n'
                    'h1 { color: #8FC7FF; }\n'
                    'button { font: inherit; padding: 10px 18px; border-radius: 10px;\n'
                    '         border: 1px solid #2A3B4D; background: #131C26; color: inherit; }\n')
        _write_file(folder, "app.js",
                    "document.getElementById('go').addEventListener('click', (event) => {\n"
                    "  event.target.textContent = 'It works - ' + new Date().toLocaleTimeString();\n"
                    "});\n")
        return

    if template == "python":
        _write_file(folder, "app.py",
                    'from flask import Flask, render_template\n\n'
                    'app = Flask(__name__)\n\n\n'
                    '@app.route("/")\n'
                    'def home():\n'
                    f'    return render_template("index.html", title="{title}")\n\n\n'
                    'if __name__ == "__main__":\n'
                    '    # PyCmd fills in the host and port this page was given.\n'
                    '    app.run()\n')
        _write_file(folder, "templates/index.html",
                    '<!doctype html>\n<html>\n<head>\n  <meta charset="utf-8">\n'
                    '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
                    '  <title>{{ title }}</title>\n'
                    '  <link rel="stylesheet" href="/static/style.css">\n</head>\n'
                    '<body>\n  <h1>{{ title }}</h1>\n'
                    '  <p>Rendered by Flask, on the phone.</p>\n</body>\n</html>\n')
        _write_file(folder, "static/style.css",
                    'body { font: 16px system-ui; margin: 0; padding: 32px;\n'
                    '       background: #0B1017; color: #D7E0EA; }\n'
                    'h1 { color: #8FC7FF; }\n')
        return

    if template == "api":
        _write_file(folder, "app.py",
                    'import datetime\n\n'
                    'from flask import Flask, jsonify, render_template\n\n'
                    'app = Flask(__name__)\n\n\n'
                    '@app.route("/")\n'
                    'def home():\n'
                    '    return render_template("index.html")\n\n\n'
                    '@app.get("/api")\n'
                    'def api():\n'
                    '    return jsonify(ok=True, now=datetime.datetime.now().isoformat())\n\n\n'
                    'if __name__ == "__main__":\n'
                    '    app.run()\n')
        _write_file(folder, "templates/index.html",
                    '<!doctype html>\n<html>\n<head>\n  <meta charset="utf-8">\n'
                    '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
                    f'  <title>{title}</title>\n</head>\n'
                    '<body style="font: 16px system-ui; padding: 32px; '
                    'background: #0B1017; color: #D7E0EA">\n'
                    f'  <h1>{title}</h1>\n'
                    '  <button onclick="load()">Call /api</button>\n'
                    '  <pre id="out"></pre>\n'
                    '  <script>\n'
                    '    async function load() {\n'
                    '      const reply = await fetch("/api");\n'
                    '      document.getElementById("out").textContent =\n'
                    '        JSON.stringify(await reply.json(), null, 2);\n'
                    '    }\n'
                    '  </script>\n</body>\n</html>\n')
        return


# ---------------------------------------------------------------------------
# Making, renaming, removing
# ---------------------------------------------------------------------------


def create(name: str, template: str = "static", workspace_dir: str = "") -> dict:
    """Makes a page: a folder, a port, and a row in the registry."""
    _require()
    rows = _read()
    if len(rows) >= MAX_PROJECTS:
        return {"ok": False, "error": f"That is {MAX_PROJECTS} pages, which is the limit. "
                                      "Delete one to make room."}

    clean = _safe_name(name)
    if not clean:
        return {"ok": False, "error": "Give the page a name."}
    if any(row.get("name", "").lower() == clean.lower() for row in rows):
        return {"ok": False, "error": f"There is already a page called {clean}."}
    if template not in TEMPLATES:
        return {"ok": False, "error": f"No template called '{template}'."}

    base = workspace_dir or _root
    folder = os.path.join(base, "pages", _slug(clean))
    suffix = 2
    while os.path.exists(folder):
        folder = os.path.join(base, "pages", f"{_slug(clean)}-{suffix}")
        suffix += 1
    os.makedirs(folder, exist_ok=True)
    _fill(folder, template, clean)

    port = _free_port(rows)
    if not port:
        return {"ok": False, "error": "No free port left in the range pages use."}

    row = {
        "id": f"pg{int(time.time() * 1000) % 100000000}{len(rows)}",
        "name": clean,
        "folder": folder,
        "template": template,
        "port": port,
        "public": False,
        "handle": "",
        "host": "local",
        "created": int(time.time()),
    }
    rows.append(row)
    _write(rows)
    return {"ok": True, "page": _decorate(row, _running())}


def adopt(name: str, folder: str) -> dict:
    """Makes a page out of a folder that already exists."""
    _require()
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        return {"ok": False, "error": "That folder is not there."}
    rows = _read()
    if len(rows) >= MAX_PROJECTS:
        return {"ok": False, "error": f"That is {MAX_PROJECTS} pages, which is the limit."}
    if any(os.path.abspath(row.get("folder", "")) == folder for row in rows):
        return {"ok": False, "error": "That folder is already a page."}

    clean = _safe_name(name) or _safe_name(os.path.basename(folder)) or "page"
    port = _free_port(rows)
    if not port:
        return {"ok": False, "error": "No free port left in the range pages use."}
    row = {
        "id": f"pg{int(time.time() * 1000) % 100000000}{len(rows)}",
        "name": clean,
        "folder": folder,
        "template": "adopted",
        "port": port,
        "public": False,
        "handle": "",
        "host": "local",
        "created": int(time.time()),
    }
    rows.append(row)
    _write(rows)
    return {"ok": True, "page": _decorate(row, _running())}


def rename(page_id: str, name: str) -> dict:
    """Changes the name only. The folder keeps the name it was made with."""
    clean = _safe_name(name)
    if not clean:
        return {"ok": False, "error": "Give the page a name."}
    rows = _read()
    row = next((r for r in rows if r.get("id") == page_id), None)
    if row is None:
        return {"ok": False, "error": "no page with that id"}
    if any(r.get("name", "").lower() == clean.lower() and r is not row for r in rows):
        return {"ok": False, "error": f"There is already a page called {clean}."}
    row["name"] = clean
    _write(rows)
    return {"ok": True, "page": _decorate(row, _running())}


def remove(page_id: str, delete_files: bool = False) -> dict:
    """Forgets a page, and deletes its folder only if asked to."""
    rows = _read()
    row = next((r for r in rows if r.get("id") == page_id), None)
    if row is None:
        return {"ok": False, "error": "no page with that id"}

    if row.get("handle"):
        _close_tunnel(row)
        pycmd_servers.kill(row["handle"])

    folder = row.get("folder", "")
    removed = False
    if delete_files and os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)
        removed = not os.path.isdir(folder)

    _write([r for r in rows if r is not row])
    return {"ok": True, "name": row.get("name", ""), "files_deleted": removed}


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def start(page_id: str, expose: bool = True) -> dict:
    """Switches a page on, on the port it was given."""
    rows = _read()
    row = next((r for r in rows if r.get("id") == page_id), None)
    if row is None:
        return {"ok": False, "error": "no page with that id"}

    alive = _running()
    if row.get("handle") in alive:
        return {"ok": True, "already": True, "page": _decorate(row, alive)}

    active = sum(1 for r in rows if r.get("handle") in alive)
    if active >= MAX_ACTIVE:
        return {"ok": False, "error": f"{MAX_ACTIVE} pages are already running, which is "
                                      "the limit. Stop one to start another."}

    folder = row.get("folder", "")
    if not os.path.isdir(folder):
        return {"ok": False, "error": f"{row.get('name')} has no folder any more."}

    port = row.get("port") or _free_port(rows)
    if not pycmd_servers.port_available(port):
        port = _free_port(rows)
        if not port:
            return {"ok": False, "error": "No free port left in the range pages use."}
        row["port"] = port

    result = pycmd_servers.start_file(
        folder,
        port=port,
        host="0.0.0.0" if expose else "127.0.0.1",
        label=row.get("name", "page"),
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "could not start it")}

    row["handle"] = result.get("handle", "")
    row["last_started"] = int(time.time())
    _write(rows)
    return {"ok": True, "page": _decorate(row, _running()), "url": result.get("url", "")}


def stop(page_id: str) -> dict:
    """Switches a page off, and takes its tunnel down with it."""
    rows = _read()
    row = next((r for r in rows if r.get("id") == page_id), None)
    if row is None:
        return {"ok": False, "error": "no page with that id"}

    handle = row.get("handle", "")
    if not handle:
        return {"ok": True, "already": True}

    _close_tunnel(row)
    result = pycmd_servers.stop(handle)
    if not result.get("ok"):
        pycmd_servers.kill(handle)
    row["handle"] = ""
    row["public"] = False
    row["public_url"] = ""
    _write(rows)
    return {"ok": True, "name": row.get("name", "")}


def stop_all() -> dict:
    rows = _read()
    stopped = 0
    for row in rows:
        if row.get("handle"):
            _close_tunnel(row)
            pycmd_servers.kill(row["handle"])
            row["handle"] = ""
            row["public"] = False
            row["public_url"] = ""
            stopped += 1
    _write(rows)
    return {"ok": True, "stopped": stopped}


def _close_tunnel(row: dict) -> None:
    if not row.get("public"):
        return
    try:
        import pycmd_tunnel

        pycmd_tunnel.close(row.get("id", ""))
    except Exception:  # noqa: BLE001 - a page must still stop
        pass


# ---------------------------------------------------------------------------
# The public address
# ---------------------------------------------------------------------------


def share(page_id: str) -> dict:
    """Opens a tunnel so a running page has an address off this network."""
    rows = _read()
    row = next((r for r in rows if r.get("id") == page_id), None)
    if row is None:
        return {"ok": False, "error": "no page with that id"}
    if row.get("handle") not in _running():
        return {"ok": False, "error": "Start the page first - there is nothing to share yet."}

    import pycmd_tunnel

    result = pycmd_tunnel.open_tunnel(row["id"], int(row.get("port") or 0))
    if not result.get("ok"):
        return result
    row["public"] = True
    row["public_url"] = result.get("url", "")
    _write(rows)
    return {"ok": True, "url": row["public_url"], "page": _decorate(row, _running())}


def unshare(page_id: str) -> dict:
    rows = _read()
    row = next((r for r in rows if r.get("id") == page_id), None)
    if row is None:
        return {"ok": False, "error": "no page with that id"}
    _close_tunnel(row)
    row["public"] = False
    row["public_url"] = ""
    _write(rows)
    return {"ok": True}


def set_host(page_id: str, host: str) -> dict:
    """Remembers whether this page belongs on the phone or on Cloudflare."""
    if host not in ("local", "cloudflare"):
        return {"ok": False, "error": "a page is hosted either 'local' or 'cloudflare'"}
    rows = _read()
    row = next((r for r in rows if r.get("id") == page_id), None)
    if row is None:
        return {"ok": False, "error": "no page with that id"}
    row["host"] = host
    _write(rows)
    return {"ok": True, "host": host}


def note_deployment(page_id: str, url: str, project: str = "") -> dict:
    """Records where a page was last deployed, so the card can link to it."""
    rows = _read()
    row = next((r for r in rows if r.get("id") == page_id), None)
    if row is None:
        return {"ok": False, "error": "no page with that id"}
    row["deployed_url"] = url
    row["deployed_at"] = int(time.time())
    if project:
        row["cloudflare_project"] = project
    _write(rows)
    return {"ok": True}
