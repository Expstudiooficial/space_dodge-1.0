"""Pages - websites that live in the app and can be switched on.

The Servers tab starts one thing and watches it. That is the right shape for
"run this file", and the wrong shape for "I have seven sites and three of them
should be up". A page is the second thing: a folder that has been named, given
a port, and remembered - so switching it on later is a tap rather than a
launch form filled in again from memory.

What a page *is* stays deliberately thin. It is a folder **you already have**
in the workspace and a row in a registry, and running one hands the folder to
`pycmd_servers`, which already knows what running a folder means: a Flask
`app.py` is started, an `index.html` is served, a single runnable file is run.
Nothing here re-invents any of that.

Picking the folder is the point. Making a page used to mean the app inventing
`workspace/pages/<slug>/` for you, which put a folder called `pages` in the
middle of a workspace that already has `vendor/` from Packages Pro, whatever
pip installed, and everybody's own folders - a name collision waiting to
happen, and a second place your files could be. Now a page *points at* a folder
you chose, and the only thing it makes on its own is a starter folder at the
top of the workspace when you ask for one from a template.

Deployment state is the other half of that split. What a page *is* lives in the
workspace, where you can edit it; what happened to a page - what was uploaded,
where it went, when - lives in this module's own storage, one folder per page,
outside the workspace entirely. Neither one can tread on the other.

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
    "folders",
    "create",
    "adopt",
    "stage",
    "deployments",
    "clear_build",
    "store_dir",
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
_projects = ""
_lock_note = "pycmd_pages.configure() has not been called"


def configure(pages_dir: str) -> str:
    """Called once by the app. Everything below lives under this folder.

    Note what is *not* here: the pages themselves. This folder is the registry
    and one small store per page - what was deployed and where. The files a
    page serves are in the workspace, because they are the user's files.
    """
    global _root, _registry_path, _projects

    _root = os.path.abspath(pages_dir)
    os.makedirs(_root, exist_ok=True)
    _registry_path = os.path.join(_root, "pages.json")
    _projects = os.path.join(_root, "projects")
    os.makedirs(_projects, exist_ok=True)
    return _root


def store_dir(page_id: str) -> str:
    """This page's own folder, outside the workspace. Made on first use."""
    _require()
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(page_id))[:40] or "unknown"
    folder = os.path.join(_projects, safe)
    os.makedirs(folder, exist_ok=True)
    return folder


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
# Picking a folder
# ---------------------------------------------------------------------------

# How deep into the workspace the picker looks. One level down finds
# `sites/blog` without turning the picker into a file browser, which the Files
# tab already is and does better.
PICKER_DEPTH = 2

# Folders nobody means when they say "my project": caches, version control,
# and the two the app itself fills.
PICKER_SKIP = {"__pycache__", ".git", "node_modules", ".idea", "venv", ".venv"}

MAX_PICKED = 200


def _shallow(folder: str) -> tuple:
    """What is directly in a folder, without walking into it.

    The picker asks this of every folder in the workspace, twice deep, every
    time the tab is opened. A full walk per folder is the difference between
    a list that appears and a list that arrives - so this counts what is in
    the folder itself and says as much on the row.
    """
    files = 0
    total = 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    if entry.is_file():
                        files += 1
                        total += entry.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass
    return files, total


def folders(workspace_dir: str = "") -> list:
    """The folders in the workspace a page could point at.

    Ordered the way somebody would look for one: the top of the workspace
    first, then a level down, alphabetically inside each. Every row says
    whether it is already a page and what running it would mean, so the choice
    is made with the answer visible rather than after the fact.
    """
    base = os.path.abspath(workspace_dir or _root)
    if not os.path.isdir(base):
        return []

    taken = {os.path.abspath(row.get("folder", "")) for row in _read()}
    found = []

    def walk(folder: str, depth: int) -> None:
        if depth > PICKER_DEPTH or len(found) >= MAX_PICKED:
            return
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return
        for name in names:
            if name in PICKER_SKIP or name.startswith("."):
                continue
            path = os.path.join(folder, name)
            if not os.path.isdir(path):
                continue
            here = _shallow(path)
            found.append({
                "path": path,
                "name": name,
                "relative": os.path.relpath(path, base).replace(os.sep, "/"),
                "files": here[0],
                "bytes": here[1],
                "taken": os.path.abspath(path) in taken,
            })
            if len(found) >= MAX_PICKED:
                return
            walk(path, depth + 1)

    walk(base, 1)
    return found


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
    """Starts a new folder from a template, and points a page at it.

    The folder lands at the top of the workspace under its own name - not in a
    `pages/` folder the app invented, which is a name that collides with
    everything else living up there. If you already have the folder, use
    [adopt] instead; the tab offers that first.
    """
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
    folder = os.path.join(base, _slug(clean))
    suffix = 2
    while os.path.exists(folder):
        folder = os.path.join(base, f"{_slug(clean)}-{suffix}")
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

    # The page's own folder - its history and its build copy - goes either
    # way: it describes a page that no longer exists.
    shutil.rmtree(store_dir(page_id), ignore_errors=True)

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


# ---------------------------------------------------------------------------
# What happened to a page, kept away from what a page is
# ---------------------------------------------------------------------------

# How many deployments to remember per page. A history is for answering "what
# did I send, and when", not for being a log.
MAX_HISTORY = 20

# What never goes up with a deployment. The same rules `pycmd_cloudflare` uses
# when it walks a folder, applied a step earlier so the copy is the answer.
STAGE_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".idea", "venv", ".venv"}
STAGE_SKIP_NAMES = {".DS_Store", "Thumbs.db"}

# A phone, and a free hosting tier. Past this something has gone wrong.
MAX_STAGE_FILES = 5000
MAX_STAGE_BYTES = 200 * 1024 * 1024


def _history_path(page_id: str) -> str:
    return os.path.join(store_dir(page_id), "deploy.json")


def deployments(page_id: str) -> dict:
    """Everywhere this page has been sent, newest first."""
    try:
        with open(_history_path(page_id), "r", encoding="utf-8") as handle:
            rows = json.load(handle)
    except (OSError, ValueError):
        rows = []
    if not isinstance(rows, list):
        rows = []
    return {"ok": True, "deployments": rows[:MAX_HISTORY], "store": store_dir(page_id)}


def stage(page_id: str) -> dict:
    """Copies what would be deployed into this page's own build folder.

    Deploying straight out of the workspace uploads whatever the folder
    happens to contain at the moment the upload reaches each file, which is
    not a thing anybody can reason about afterwards. The copy is the answer to
    "what did I actually send": it is made once, uploaded from, and left
    behind for looking at - outside the workspace, so it is never in the way.
    """
    rows = _read()
    row = next((r for r in rows if r.get("id") == page_id), None)
    if row is None:
        return {"ok": False, "error": "no page with that id"}

    source = row.get("folder", "")
    if not os.path.isdir(source):
        return {"ok": False, "error": "That page's folder is not there any more."}

    build = os.path.join(store_dir(page_id), "build")
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(build, exist_ok=True)

    files = 0
    total = 0
    for walk, subfolders, names in os.walk(source):
        subfolders[:] = [d for d in subfolders if d not in STAGE_SKIP_DIRS
                         and not d.startswith(".")]
        for name in sorted(names):
            if name in STAGE_SKIP_NAMES or name.startswith("."):
                continue
            full = os.path.join(walk, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if files >= MAX_STAGE_FILES or total + size > MAX_STAGE_BYTES:
                # Half a copy is worse than none: it would sit there looking
                # like the answer to "what did I send".
                shutil.rmtree(build, ignore_errors=True)
                return {"ok": False, "error": "That folder is too big to deploy: "
                                              f"{MAX_STAGE_FILES} files or "
                                              f"{MAX_STAGE_BYTES // (1024 * 1024)} MB is the limit.",
                        "files": files, "bytes": total}
            relative = os.path.relpath(full, source)
            target = os.path.join(build, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                shutil.copy2(full, target)
            except OSError:
                continue
            files += 1
            total += size

    if files == 0:
        shutil.rmtree(build, ignore_errors=True)
        return {"ok": False, "error": "There is nothing in that folder to deploy."}
    return {"ok": True, "folder": build, "files": files, "bytes": total}


def clear_build(page_id: str) -> dict:
    """Throws away the copy of the last deployment. The history stays."""
    build = os.path.join(store_dir(page_id), "build")
    freed = _folder_bytes(build) if os.path.isdir(build) else 0
    shutil.rmtree(build, ignore_errors=True)
    return {"ok": True, "freed": freed}


def note_deployment(page_id: str, url: str, project: str = "",
                    files: int = 0, size: int = 0) -> dict:
    """Records where a page was sent, on the row and in its own history."""
    rows = _read()
    row = next((r for r in rows if r.get("id") == page_id), None)
    if row is None:
        return {"ok": False, "error": "no page with that id"}
    when = int(time.time())
    row["deployed_url"] = url
    row["deployed_at"] = when
    if project:
        row["cloudflare_project"] = project
    _write(rows)

    # The full record lives in the page's own folder rather than the registry:
    # a registry that grows a history per page is a registry that gets slower
    # every time anybody deploys anything.
    history = deployments(page_id)["deployments"]
    history.insert(0, {
        "at": when,
        "url": url,
        "project": project,
        "files": int(files or 0),
        "bytes": int(size or 0),
        "host": row.get("host", "cloudflare"),
    })
    try:
        with open(_history_path(page_id), "w", encoding="utf-8") as handle:
            json.dump(history[:MAX_HISTORY], handle, indent=2)
    except OSError:
        pass
    return {"ok": True, "deployments": len(history[:MAX_HISTORY])}
