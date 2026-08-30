"""Packages Pro - packages for everything that is not Python.

The Packages tab installs wheels from PyPI, which is the right answer for
Python and no answer at all for the other half of what people write on this
app. A page that wants htmx, a chart, a 3D scene or a font has one option on a
phone: a CDN, which means it only works with a connection - and the preview
server here is a loopback server, so "works with a connection" is not the same
as "works".

So this fetches the file itself. jsDelivr serves every npm package as plain
static files, which is exactly what a vendored library is: one HTTPS request,
one file in `vendor/`, and a page that works on a plane.

The kits are the same idea one level up. The Servers tab knows how to run a
folder - find its app.py, or its index.html - so a starter project is worth
more here than a starter file: `kit new blog flask` is a folder that runs the
moment it exists.
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

# jsDelivr, which serves npm's contents as static files, and answers a small
# JSON API about what is in each package. Module-level so a test can point
# them at a local server instead of the internet.
DEFAULT_CDN = "https://cdn.jsdelivr.net/npm"
DEFAULT_DATA_API = "https://data.jsdelivr.com/v1"
CDN = DEFAULT_CDN
DATA_API = DEFAULT_DATA_API

TIMEOUT = 25
MAX_FILE_BYTES = 12 * 1024 * 1024

# The libraries worth a one-tap button, with the file that actually matters.
# Written out rather than guessed: npm packages disagree about where their
# built file lives, and a catalogue that fetches the wrong one is a catalogue
# of broken pages.
CATALOGUE = [
    {"id": "htmx", "name": "htmx", "npm": "htmx.org", "kind": "js",
     "files": ["dist/htmx.min.js"],
     "about": "HTML attributes that do AJAX. No build step, no framework."},
    {"id": "alpine", "name": "Alpine.js", "npm": "alpinejs", "kind": "js",
     "files": ["dist/cdn.min.js"],
     "about": "Small reactive framework that lives in your markup."},
    {"id": "tailwind", "name": "Tailwind (play)", "npm": "tailwindcss",
     "kind": "js", "files": ["lib/index.js"],
     "about": "Utility CSS. The play build compiles in the browser."},
    {"id": "bootstrap", "name": "Bootstrap", "npm": "bootstrap", "kind": "both",
     "files": ["dist/css/bootstrap.min.css", "dist/js/bootstrap.bundle.min.js"],
     "about": "The classic component and grid library."},
    {"id": "bulma", "name": "Bulma", "npm": "bulma", "kind": "css",
     "files": ["css/bulma.min.css"],
     "about": "CSS-only framework, no JavaScript at all."},
    {"id": "normalize", "name": "normalize.css", "npm": "normalize.css",
     "kind": "css", "files": ["normalize.css"],
     "about": "Makes browsers agree about defaults."},
    {"id": "three", "name": "three.js", "npm": "three", "kind": "js",
     "files": ["build/three.module.js"],
     "about": "3D in the browser. The preview runs it."},
    {"id": "chartjs", "name": "Chart.js", "npm": "chart.js", "kind": "js",
     "files": ["dist/chart.umd.js"],
     "about": "Charts on a canvas."},
    {"id": "d3", "name": "D3", "npm": "d3", "kind": "js",
     "files": ["dist/d3.min.js"],
     "about": "Data-driven documents, for charts you draw yourself."},
    {"id": "vue", "name": "Vue", "npm": "vue", "kind": "js",
     "files": ["dist/vue.global.prod.js"],
     "about": "A framework that works from a script tag."},
    {"id": "preact", "name": "Preact", "npm": "preact", "kind": "js",
     "files": ["dist/preact.min.js"],
     "about": "React's API in 3 KB."},
    {"id": "marked", "name": "marked", "npm": "marked", "kind": "js",
     "files": ["marked.min.js"],
     "about": "Markdown to HTML, in the browser."},
    {"id": "highlight", "name": "highlight.js", "npm": "@highlightjs/cdn-assets",
     "kind": "both", "files": ["highlight.min.js", "styles/github-dark.min.css"],
     "about": "Syntax highlighting for code on a page."},
    {"id": "lodash", "name": "Lodash", "npm": "lodash", "kind": "js",
     "files": ["lodash.min.js"],
     "about": "The utility belt."},
    {"id": "dayjs", "name": "Day.js", "npm": "dayjs", "kind": "js",
     "files": ["dayjs.min.js"],
     "about": "Dates, in 2 KB."},
    {"id": "font-inter", "name": "Inter (font)", "npm": "@fontsource/inter",
     "kind": "font", "files": ["index.css", "files/inter-latin-400-normal.woff2",
                               "files/inter-latin-700-normal.woff2"],
     "about": "A UI font, self-hosted, no Google request."},
    {"id": "font-jetbrains", "name": "JetBrains Mono (font)",
     "npm": "@fontsource/jetbrains-mono", "kind": "font",
     "files": ["index.css", "files/jetbrains-mono-latin-400-normal.woff2"],
     "about": "A monospace font for code on a page."},
]

_api = None
_settings = {}


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _get(url: str, binary: bool = True):
    request = urllib.request.Request(url, headers={"User-Agent": "PyCmd-packages-pro"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = response.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("that file is far too big to vendor")
    return data if binary else data.decode("utf-8", "replace")


def _versions(package: str) -> list:
    """Every published version of an npm package, newest first."""
    url = f"{DATA_API}/packages/npm/{urllib.parse.quote(package, safe='@/')}"
    payload = json.loads(_get(url, binary=False))
    versions = [row.get("version", "") for row in payload.get("versions", [])]
    return [v for v in versions if v]


def _latest(package: str) -> str:
    versions = _versions(package)
    if not versions:
        raise ValueError(f"npm has no package called {package}")
    # The API lists newest first, but a prerelease should not become the
    # default install just because it is newest.
    for version in versions:
        if not re.search(r"[a-zA-Z]", version):
            return version
    return versions[0]


def _file_list(package: str, version: str) -> list:
    """The files in one published version, as flat paths."""
    quoted = urllib.parse.quote(package, safe="@/")
    url = f"{DATA_API}/packages/npm/{quoted}@{urllib.parse.quote(version)}?structure=flat"
    payload = json.loads(_get(url, binary=False))
    return [row.get("name", "").lstrip("/") for row in payload.get("files", [])]


def _guess_files(files: list, minified: bool) -> list:
    """What to take from a package nobody wrote a catalogue entry for.

    A built library is nearly always one file under dist/ or umd/ named after
    the package. Ranked rather than filtered, so something is always chosen if
    anything plausible is there.
    """
    def rank(path: str) -> tuple:
        lowered = path.lower()
        score = 0
        if lowered.endswith(".min.js") or lowered.endswith(".min.css"):
            score -= 3 if minified else 0
        if "/umd/" in lowered or lowered.startswith("dist/") or "/dist/" in lowered:
            score -= 3
        if lowered.endswith(".js") or lowered.endswith(".css"):
            score -= 1
        if any(part in lowered for part in ("test", "example", "docs/", ".map", "esm")):
            score += 4
        return (score, len(path))

    usable = [f for f in files if f.lower().endswith((".js", ".css", ".woff2", ".woff"))]
    usable.sort(key=rank)
    return usable[:1]


def _vendor_root() -> str:
    folder = str(_settings.get("vendor_dir") or "vendor").strip().strip("/") or "vendor"
    return _api.workspace_path(folder)


def install(name: str, version: str = "") -> dict:
    """Fetches a library into the workspace. `name` may be a catalogue id.

    `chart.js@4.4.0` pins a version. The `@` that starts a scoped package -
    `@fontsource/inter` - is not that, which is why the search starts at the
    second character.
    """
    spec = name.strip()
    at = spec.rfind("@")
    if at > 0:
        version = version or spec[at + 1:]
        spec = spec[:at]

    # After the version is off, so `chart.js@4.4.0` still finds the catalogue
    # entry that knows which file of chart.js is the one worth having.
    entry = next((row for row in CATALOGUE
                  if row["id"] == spec or row["npm"] == spec
                  or row["name"].lower() == spec.lower()), None)
    package = entry["npm"] if entry else spec
    if not package:
        return {"ok": False, "error": "which library?"}

    try:
        resolved = version or _latest(package)
    except (urllib.error.URLError, ValueError, json.JSONDecodeError) as error:
        return {"ok": False, "error": f"could not look up {package}: {error}"}

    minified = bool(_settings.get("minified", True))
    wanted = list(entry["files"]) if entry else []
    if not wanted:
        try:
            wanted = _guess_files(_file_list(package, resolved), minified)
        except (urllib.error.URLError, ValueError, json.JSONDecodeError) as error:
            return {"ok": False, "error": f"could not read {package}'s files: {error}"}
    if not wanted:
        return {"ok": False, "error": f"{package} has no built .js or .css file to vendor"}

    folder = os.path.join(_vendor_root(), entry["id"] if entry else _safe(package))
    os.makedirs(folder, exist_ok=True)
    written = []
    quoted = urllib.parse.quote(package, safe="@/")
    for path in wanted:
        url = f"{CDN}/{quoted}@{urllib.parse.quote(resolved)}/{path}"
        try:
            data = _get(url)
        except (urllib.error.URLError, ValueError) as error:
            return {"ok": False, "error": f"{path}: {error}", "written": written}
        target = os.path.join(folder, os.path.basename(path))
        with open(target, "wb") as handle:
            handle.write(data)
        written.append(os.path.basename(path))

    record = {
        "name": entry["name"] if entry else package,
        "npm": package,
        "version": resolved,
        "files": written,
        "folder": folder,
        "when": int(time.time()),
    }
    _remember(record)
    return {"ok": True, **record, "html": _snippet(record)}


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", name).strip("-") or "library"


def _snippet(record: dict) -> str:
    """The tag to paste into a page, which is the point of vendoring at all."""
    root = _vendor_root()
    lines = []
    for name in record["files"]:
        relative = os.path.relpath(os.path.join(record["folder"], name),
                                   os.path.dirname(root))
        relative = relative.replace(os.sep, "/")
        if name.endswith(".css"):
            lines.append(f'<link rel="stylesheet" href="{relative}">')
        elif name.endswith(".js"):
            lines.append(f'<script src="{relative}"></script>')
    return "\n".join(lines)


def _ledger_path() -> str:
    return os.path.join(_vendor_root(), "installed.json")


def _ledger() -> list:
    try:
        with open(_ledger_path(), "r", encoding="utf-8") as handle:
            rows = json.load(handle)
            return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def _remember(record: dict) -> None:
    rows = [row for row in _ledger() if row.get("npm") != record["npm"]]
    rows.append(record)
    os.makedirs(_vendor_root(), exist_ok=True)
    try:
        with open(_ledger_path(), "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=2)
    except OSError:
        pass


def installed() -> list:
    """What is vendored, checked against what is actually on disk."""
    rows = []
    for row in _ledger():
        folder = row.get("folder", "")
        present = [f for f in row.get("files", [])
                   if os.path.isfile(os.path.join(folder, f))]
        if present:
            rows.append({**row, "files": present})
    return rows


def remove(name: str) -> dict:
    """Deletes a vendored library's files and forgets it."""
    rows = _ledger()
    match = next((row for row in rows
                  if name in (row.get("npm"), row.get("name"))
                  or os.path.basename(row.get("folder", "")) == name), None)
    if match is None:
        return {"ok": False, "error": f"{name} is not vendored here"}
    folder = match.get("folder", "")
    removed = 0
    for file_name in match.get("files", []):
        path = os.path.join(folder, file_name)
        if os.path.isfile(path):
            os.remove(path)
            removed += 1
    if os.path.isdir(folder) and not os.listdir(folder):
        os.rmdir(folder)
    rows = [row for row in rows if row is not match]
    try:
        with open(_ledger_path(), "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=2)
    except OSError:
        pass
    return {"ok": True, "removed": removed, "name": match.get("name", name)}


# ---------------------------------------------------------------------------
# Kits: a project, not a file
# ---------------------------------------------------------------------------


KITS = {
    "flask": "A Flask app with templates and static files. Servers -> Run a "
             "file -> pick the folder, and it runs.",
    "site": "A plain page with its own CSS and JavaScript.",
    "htmx": "An htmx page with a Flask backend that answers it.",
    "chart": "A page that draws a chart from data you edit.",
    "three": "A rotating 3D scene.",
    "api": "A Flask JSON API with two endpoints and a test script.",
    "cli": "A Python command-line program with argparse and a --help.",
}


def _write(folder: str, name: str, text: str) -> str:
    path = os.path.join(folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def new_kit(folder_name: str, kind: str = "site") -> dict:
    kind = (kind or "site").lower()
    if kind not in KITS:
        return {"ok": False, "error": f"no kit called '{kind}'. "
                                      f"Try: {', '.join(sorted(KITS))}"}
    folder = _api.workspace_path(folder_name)
    if os.path.exists(folder):
        return {"ok": False, "error": f"{folder_name} already exists"}
    os.makedirs(folder, exist_ok=True)

    made = _KIT_BUILDERS[kind](folder)
    return {
        "ok": True,
        "kind": kind,
        "folder": folder,
        "files": [os.path.relpath(path, folder) for path in made],
        "how": KITS[kind],
    }


def _kit_flask(folder: str) -> list:
    return [
        _write(folder, "app.py",
               'from flask import Flask, render_template\n\n'
               'app = Flask(__name__)\n\n\n'
               '@app.route("/")\n'
               'def home():\n'
               '    return render_template("index.html", title="It works")\n\n\n'
               'if __name__ == "__main__":\n'
               '    # PyCmd fills in the host and port from the Servers form.\n'
               '    app.run()\n'),
        _write(folder, "templates/index.html",
               '<!doctype html>\n<html>\n<head>\n  <meta charset="utf-8">\n'
               '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
               '  <title>{{ title }}</title>\n'
               '  <link rel="stylesheet" href="/static/style.css">\n'
               '</head>\n<body>\n  <h1>{{ title }}</h1>\n'
               '  <p>Edit templates/index.html and refresh.</p>\n</body>\n</html>\n'),
        _write(folder, "static/style.css",
               'body { font: 16px system-ui; margin: 0; padding: 32px;\n'
               '       background: #0B1017; color: #D7E0EA; }\n'
               'h1 { color: #8FC7FF; }\n'),
    ]


def _kit_site(folder: str) -> list:
    return [
        _write(folder, "index.html",
               '<!doctype html>\n<html>\n<head>\n  <meta charset="utf-8">\n'
               '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
               '  <title>A page</title>\n  <link rel="stylesheet" href="style.css">\n'
               '</head>\n<body>\n  <h1 id="title">A page</h1>\n'
               '  <button id="go">Press me</button>\n'
               '  <script src="app.js"></script>\n</body>\n</html>\n'),
        _write(folder, "style.css",
               'body { font: 16px system-ui; margin: 0; padding: 32px;\n'
               '       background: #0B1017; color: #D7E0EA; }\n'
               'button { font: inherit; padding: 10px 18px; border-radius: 10px;\n'
               '         border: 1px solid #2A3B4D; background: #131C26; color: inherit; }\n'),
        _write(folder, "app.js",
               "document.getElementById('go').addEventListener('click', () => {\n"
               "  document.getElementById('title').textContent =\n"
               "    'It works - ' + new Date().toLocaleTimeString();\n"
               "});\n"),
    ]


def _kit_htmx(folder: str) -> list:
    made = [
        _write(folder, "app.py",
               'from flask import Flask, render_template\n'
               'import datetime\n\n'
               'app = Flask(__name__)\n\n\n'
               '@app.route("/")\n'
               'def home():\n'
               '    return render_template("index.html")\n\n\n'
               '@app.route("/time")\n'
               'def now():\n'
               '    return f"<p>{datetime.datetime.now():%H:%M:%S}</p>"\n\n\n'
               'if __name__ == "__main__":\n'
               '    app.run()\n'),
        _write(folder, "templates/index.html",
               '<!doctype html>\n<html>\n<head>\n  <meta charset="utf-8">\n'
               '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
               '  <title>htmx</title>\n'
               '  <script src="/static/htmx.min.js"></script>\n'
               '</head>\n<body style="font: 16px system-ui; padding: 32px">\n'
               '  <h1>htmx</h1>\n'
               '  <button hx-get="/time" hx-target="#out">What time is it</button>\n'
               '  <div id="out"></div>\n</body>\n</html>\n'),
        _write(folder, "static/.keep", ""),
    ]
    result = install("htmx")
    if result.get("ok"):
        source = os.path.join(result["folder"], result["files"][0])
        target = os.path.join(folder, "static", "htmx.min.js")
        try:
            with open(source, "rb") as read, open(target, "wb") as write:
                write.write(read.read())
            made.append(target)
        except OSError:
            pass
    return made


def _kit_chart(folder: str) -> list:
    made = [
        _write(folder, "index.html",
               '<!doctype html>\n<html>\n<head>\n  <meta charset="utf-8">\n'
               '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
               '  <title>A chart</title>\n  <script src="chart.umd.js"></script>\n'
               '</head>\n<body style="font: 16px system-ui; padding: 24px; background: #0B1017">\n'
               '  <canvas id="c"></canvas>\n  <script src="app.js"></script>\n'
               '</body>\n</html>\n'),
        _write(folder, "app.js",
               "const data = [12, 19, 3, 5, 2, 3];\n"
               "new Chart(document.getElementById('c'), {\n"
               "  type: 'bar',\n"
               "  data: { labels: ['a','b','c','d','e','f'],\n"
               "          datasets: [{ label: 'edit app.js', data }] },\n"
               "});\n"),
    ]
    result = install("chartjs")
    if result.get("ok"):
        source = os.path.join(result["folder"], result["files"][0])
        try:
            with open(source, "rb") as read, \
                    open(os.path.join(folder, "chart.umd.js"), "wb") as write:
                write.write(read.read())
            made.append(os.path.join(folder, "chart.umd.js"))
        except OSError:
            pass
    return made


def _kit_three(folder: str) -> list:
    return [
        _write(folder, "index.html",
               '<!doctype html>\n<html>\n<head>\n  <meta charset="utf-8">\n'
               '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
               '  <title>3D</title>\n  <style>body{margin:0;overflow:hidden}</style>\n'
               '</head>\n<body>\n'
               '  <script type="importmap">\n'
               '  {"imports": {"three": "./three.module.js"}}\n'
               '  </script>\n'
               '  <script type="module" src="app.js"></script>\n</body>\n</html>\n'),
        _write(folder, "app.js",
               "import * as THREE from 'three';\n\n"
               "const scene = new THREE.Scene();\n"
               "const camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.1, 100);\n"
               "camera.position.z = 3;\n"
               "const renderer = new THREE.WebGLRenderer({ antialias: true });\n"
               "renderer.setSize(innerWidth, innerHeight);\n"
               "document.body.appendChild(renderer.domElement);\n"
               "const cube = new THREE.Mesh(\n"
               "  new THREE.BoxGeometry(),\n"
               "  new THREE.MeshNormalMaterial(),\n"
               ");\n"
               "scene.add(cube);\n"
               "renderer.setAnimationLoop(() => {\n"
               "  cube.rotation.x += 0.01; cube.rotation.y += 0.013;\n"
               "  renderer.render(scene, camera);\n"
               "});\n"),
        _write(folder, "README.md",
               "# A 3D scene\n\nRun `web install three` and copy "
               "`vendor/three/three.module.js` next to index.html, then serve "
               "this folder.\n"),
    ]


def _kit_api(folder: str) -> list:
    return [
        _write(folder, "app.py",
               'from flask import Flask, jsonify, request\n\n'
               'app = Flask(__name__)\n'
               'NOTES = []\n\n\n'
               '@app.get("/notes")\n'
               'def listing():\n'
               '    return jsonify(NOTES)\n\n\n'
               '@app.post("/notes")\n'
               'def add():\n'
               '    NOTES.append(request.get_json(force=True))\n'
               '    return jsonify(ok=True, count=len(NOTES))\n\n\n'
               'if __name__ == "__main__":\n'
               '    app.run()\n'),
        _write(folder, "try_it.py",
               'import json\nimport urllib.request\n\n'
               'BASE = "http://127.0.0.1:8000"\n\n'
               'urllib.request.urlopen(\n'
               '    urllib.request.Request(f"{BASE}/notes", method="POST",\n'
               '                           data=json.dumps({"text": "hello"}).encode(),\n'
               '                           headers={"Content-Type": "application/json"}))\n'
               'print(urllib.request.urlopen(f"{BASE}/notes").read().decode())\n'),
    ]


def _kit_cli(folder: str) -> list:
    return [
        _write(folder, "main.py",
               '"""A command-line program."""\n\n'
               'import argparse\n\n\n'
               'def main() -> None:\n'
               '    parser = argparse.ArgumentParser(description="What it does")\n'
               '    parser.add_argument("name", help="who to greet")\n'
               '    parser.add_argument("--loud", action="store_true")\n'
               '    args = parser.parse_args()\n'
               '    greeting = f"hello, {args.name}"\n'
               '    print(greeting.upper() if args.loud else greeting)\n\n\n'
               'if __name__ == "__main__":\n'
               '    main()\n'),
    ]


_KIT_BUILDERS = {
    "flask": _kit_flask,
    "site": _kit_site,
    "htmx": _kit_htmx,
    "chart": _kit_chart,
    "three": _kit_three,
    "api": _kit_api,
    "cli": _kit_cli,
}


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def setup(api):
    global _api, _settings, CDN, DATA_API

    _api = api
    _settings = {
        "vendor_dir": api.setting("vendor_dir", "vendor"),
        "minified": api.setting("minified", True),
        "open_after_kit": api.setting("open_after_kit", True),
    }
    mirror = str(api.setting("mirror", "") or "").strip().rstrip("/")
    if mirror.startswith("https://"):
        CDN = mirror
        DATA_API = mirror.replace("/npm", "") + "/v1" if "/npm" in mirror else DATA_API
        api.log("Packages Pro is using a mirror", CDN)
    api.log("Packages Pro is ready", f"{len(CATALOGUE)} libraries, {len(KITS)} kits")

    @api.export
    def point_at(payload=None):
        """Uses a different mirror, or puts the default back.

        jsDelivr is not reachable everywhere, and a fork may prefer its own
        mirror. Passing nothing restores the defaults. The two addresses have
        to be https, or a "library" could be anything at all.
        """
        global CDN, DATA_API

        payload = payload or {}
        cdn = str(payload.get("cdn", "") or "").strip().rstrip("/")
        api_base = str(payload.get("api", "") or "").strip().rstrip("/")
        if not cdn and not api_base:
            CDN, DATA_API = DEFAULT_CDN, DEFAULT_DATA_API
            return {"ok": True, "cdn": CDN, "api": DATA_API}
        local = cdn.startswith("http://127.0.0.1") or cdn.startswith("http://localhost")
        if not local and not (cdn.startswith("https://") and api_base.startswith("https://")):
            return {"ok": False, "error": "a mirror has to be https"}
        CDN = cdn or CDN
        DATA_API = api_base or DATA_API
        api.log("Packages Pro is using a mirror", CDN)
        return {"ok": True, "cdn": CDN, "api": DATA_API}

    @api.export
    def catalogue(payload=None):
        """The library list the panel draws."""
        have = {row.get("npm"): row for row in installed()}
        return [{**row, "installed": row["npm"] in have,
                 "version": have.get(row["npm"], {}).get("version", "")}
                for row in CATALOGUE]

    @api.export
    def kits(payload=None):
        return [{"id": key, "about": value} for key, value in sorted(KITS.items())]

    @api.export
    def vendored(payload=None):
        return installed()

    @api.export
    def add(payload):
        payload = payload or {}
        result = install(str(payload.get("name", "")).strip(),
                         str(payload.get("version", "")).strip())
        if result.get("ok"):
            api.toast(f"{result['name']} {result['version']} is in your workspace")
            api.refresh("files")
        return result

    @api.export
    def drop(payload):
        result = remove(str((payload or {}).get("name", "")).strip())
        if result.get("ok"):
            api.refresh("files")
        return result

    @api.export
    def scaffold(payload):
        payload = payload or {}
        folder = str(payload.get("folder", "")).strip()
        result = new_kit(folder, str(payload.get("kind", "site")).strip())
        if result.get("ok"):
            api.refresh("files")
            api.toast(f"Made {folder} - Servers can run it")
            if _settings.get("open_after_kit"):
                first = result["files"][0]
                api.open_file(os.path.join(result["folder"], first))
        return result

    @api.command("web", help="web install <name>[@version] | list | remove <x> | catalogue")
    def web_command(argument=""):
        parts = str(argument).split()
        action = parts[0] if parts else "catalogue"
        rest = parts[1:]

        if action in ("install", "add", "i"):
            if not rest:
                api.print("web install htmx        (or any npm package name)")
                return
            for spec in rest:
                name, _, version = spec.partition("@") if not spec.startswith("@") \
                    else (spec, "", "")
                api.print(f"Fetching {name}...")
                result = install(name, version)
                if result.get("ok"):
                    api.print(f"  {result['name']} {result['version']} -> "
                              f"{os.path.basename(result['folder'])}/"
                              f"{', '.join(result['files'])}")
                    if result.get("html"):
                        api.print("  paste into your page:")
                        for line in result["html"].splitlines():
                            api.print("    " + line)
                else:
                    api.print("  " + result.get("error", "could not fetch that"))
            api.refresh("files")
            return

        if action in ("list", "ls"):
            rows = installed()
            if not rows:
                api.print("Nothing vendored yet. Try: web install htmx")
                return
            for row in rows:
                api.print(f"  {row['name']:<22} {row['version']:<10} "
                          f"{', '.join(row['files'])}")
            return

        if action in ("remove", "rm", "uninstall"):
            if not rest:
                api.print("web remove <name>")
                return
            for name in rest:
                result = remove(name)
                api.print("  " + (f"removed {result.get('name', name)}"
                                  if result.get("ok")
                                  else result.get("error", "no")))
            api.refresh("files")
            return

        if action in ("catalogue", "catalog", "all"):
            for row in CATALOGUE:
                api.print(f"  {row['id']:<16} {row['name']:<22} {row['about']}")
            api.print("")
            api.print("  web install <id>, or any npm package by its own name.")
            return

        api.print(f"web: no idea what '{action}' means. "
                  "Try: web install htmx, web list, web catalogue")

    @api.command("kit", help="kit new <folder> <flask|site|htmx|chart|three|api|cli>")
    def kit_command(argument=""):
        parts = str(argument).split()
        if not parts or parts[0] in ("list", "kits", "?"):
            for key, about in sorted(KITS.items()):
                api.print(f"  {key:<8} {about}")
            api.print("")
            api.print("  kit new myapp flask")
            return
        if parts[0] != "new" or len(parts) < 2:
            api.print("kit new <folder> [kind]")
            return
        folder = parts[1]
        kind = parts[2] if len(parts) > 2 else "site"
        result = new_kit(folder, kind)
        if not result.get("ok"):
            api.print("  " + result.get("error", "could not make that"))
            return
        api.print(f"Made {folder}/ ({kind})")
        for name in result["files"]:
            api.print(f"  {name}")
        api.print("  " + result["how"])
        api.refresh("files")
