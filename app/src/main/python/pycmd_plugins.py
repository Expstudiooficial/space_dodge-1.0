"""The custom-plugin runtime: install, load, run, and talk to the UI.

A plugin is Python that the app imports into its own interpreter, plus an
optional HTML panel that becomes a tab. That is the whole idea, and its cost
has to be said plainly rather than buried: a plugin runs with exactly the
permissions the app has. It can read and write the workspace, open sockets,
and install packages. There is no sandbox, because CPython does not have one
worth the name - `exec` in a stripped namespace stops nobody who can spell
``__builtins__``. The app therefore does the only honest thing: it says so
before installing, on a screen the user has to read.

Three shapes are accepted:

* ``thing.py``            - one file, with a ``PLUGIN = {...}`` dict in it.
* ``thing/``              - a folder with ``plugin.json`` and an entry module.
* ``thing.zip``           - the same folder, zipped.

See PLUGINS.md for the authoring guide; this module is the other half of that
document, and the two are meant to be read together.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import time
import traceback
import zipfile

__all__ = [
    "configure", "install", "listing", "remove", "load_all", "unload",
    "call_export", "run_command", "commands", "fire", "panel_html",
    "plugin_dir", "read_manifest", "errors",
]

MANIFEST_NAME = "plugin.json"
MAX_PLUGIN_BYTES = 32 * 1024 * 1024
MAX_FILES = 2000

# What a manifest may contain. Anything else is kept but ignored, so a plugin
# written for a later version still installs.
REQUIRED_KEYS = ("id", "name")
KNOWN_PERMISSIONS = ("files", "network", "console", "servers", "packages")

_plugins_dir = ""
_workspace_dir = ""
_host = None

# id -> {"manifest": dict, "module": module, "api": Api, "error": str}
_loaded = {}
_errors = {}


def configure(plugins_dir: str, workspace_dir: str, host=None) -> str:
    """Called once by the app. `host` is the Kotlin side, or None on desktop."""
    global _plugins_dir, _workspace_dir, _host

    _plugins_dir = plugins_dir
    _workspace_dir = workspace_dir
    _host = host
    os.makedirs(plugins_dir, exist_ok=True)
    return plugins_dir


def plugin_dir(plugin_id: str) -> str:
    return os.path.join(_plugins_dir, _safe_id(plugin_id))


# ----------------------------------------------------------------- installing

def install(source: str, source_name: str = "") -> str:
    """Installs from a file, a folder or a zip. Returns a JSON result."""
    try:
        manifest, staged = _stage(source, source_name)
    except PluginError as error:
        return _json({"ok": False, "error": str(error)})
    except Exception as error:  # noqa: BLE001
        return _json({"ok": False, "error": f"{type(error).__name__}: {error}"})

    target = plugin_dir(manifest["id"])
    replaced = os.path.isdir(target)
    try:
        if replaced:
            unload(manifest["id"])
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(staged, target)
    except OSError as error:
        shutil.rmtree(staged, ignore_errors=True)
        return _json({"ok": False, "error": f"could not save the plugin: {error}"})

    manifest["installed_at"] = int(time.time())
    _write_manifest(target, manifest)
    return _json({"ok": True, "replaced": replaced, "manifest": manifest})


def _stage(source: str, source_name: str):
    """Copies a candidate into a scratch folder and reads its manifest."""
    scratch = os.path.join(_plugins_dir, f".staging-{int(time.time() * 1000)}")
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch, exist_ok=True)

    try:
        if os.path.isdir(source):
            _copy_tree(source, scratch)
        elif zipfile.is_zipfile(source):
            _extract_zip(source, scratch)
        elif source.lower().endswith(".py"):
            name = os.path.basename(source_name or source)
            shutil.copy2(source, os.path.join(scratch, name))
        else:
            raise PluginError(
                "a plugin is a .py file, a folder, or a .zip of a folder"
            )

        manifest = read_manifest(scratch)
        return manifest, scratch
    except Exception:
        shutil.rmtree(scratch, ignore_errors=True)
        raise


def _copy_tree(source: str, target: str) -> None:
    total = 0
    count = 0
    for directory, folders, names in os.walk(source):
        folders[:] = [f for f in folders if not f.startswith(".") and f != "__pycache__"]
        relative = os.path.relpath(directory, source)
        destination = target if relative == "." else os.path.join(target, relative)
        os.makedirs(destination, exist_ok=True)
        for name in names:
            if name.startswith("."):
                continue
            path = os.path.join(directory, name)
            size = os.path.getsize(path)
            total += size
            count += 1
            if total > MAX_PLUGIN_BYTES:
                raise PluginError("that plugin is larger than 32 MB")
            if count > MAX_FILES:
                raise PluginError("that plugin has more than 2000 files")
            shutil.copy2(path, os.path.join(destination, name))


def _extract_zip(source: str, target: str) -> None:
    with zipfile.ZipFile(source) as archive:
        entries = [e for e in archive.infolist() if not e.is_dir()]
        if len(entries) > MAX_FILES:
            raise PluginError("that zip has more than 2000 files")
        if sum(e.file_size for e in entries) > MAX_PLUGIN_BYTES:
            raise PluginError("that zip unpacks to more than 32 MB")

        # A zip made by right-clicking a folder has everything under one top
        # directory; one made by selecting the contents does not. Both should
        # install, so the common prefix is stripped when there is exactly one.
        roots = {e.filename.split("/", 1)[0] for e in entries}
        strip = len(roots) == 1 and any("/" in e.filename for e in entries)

        for entry in entries:
            name = entry.filename
            if strip:
                name = name.split("/", 1)[1] if "/" in name else name
            if not name or name.startswith("__MACOSX"):
                continue
            destination = _safe_join(target, name)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with archive.open(entry) as handle, open(destination, "wb") as out:
                shutil.copyfileobj(handle, out)


def _safe_join(root: str, relative: str) -> str:
    """Refuses the `../../etc/passwd` trick that zip files are famous for.

    Both sides are made absolute before comparing, and the separator is part
    of the comparison: without it a folder called `pluginsX` would pass a
    prefix test against `plugins`.
    """
    base = os.path.abspath(root)
    target = os.path.abspath(os.path.join(base, relative))
    if target != base and not target.startswith(base + os.sep):
        raise PluginError(f"the zip tries to write outside its folder: {relative}")
    return target


class PluginError(Exception):
    pass


# ------------------------------------------------------------------ manifests

def read_manifest(folder: str) -> dict:
    """Finds and validates the manifest of a staged plugin folder."""
    path = os.path.join(folder, MANIFEST_NAME)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except ValueError as error:
            raise PluginError(f"{MANIFEST_NAME} is not valid JSON: {error}") from None
        if not isinstance(manifest, dict):
            raise PluginError(f"{MANIFEST_NAME} must contain an object")
        return _validate(manifest, folder)

    # A single-file plugin declares itself in the module.
    scripts = [n for n in sorted(os.listdir(folder)) if n.endswith(".py")]
    if not scripts:
        raise PluginError(
            f"no {MANIFEST_NAME} and no .py file - see PLUGINS.md for the two shapes"
        )
    entry = "main.py" if "main.py" in scripts else scripts[0]
    manifest = _manifest_from_source(os.path.join(folder, entry))
    manifest.setdefault("entry", entry)
    return _validate(manifest, folder)


def _manifest_from_source(path: str) -> dict:
    """Reads a `PLUGIN = {...}` dict without importing the module.

    Importing to find out what something is would run it, and the whole point
    of reading the manifest first is to decide whether to run it at all.
    """
    import ast

    try:
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=os.path.basename(path))
    except (OSError, SyntaxError) as error:
        raise PluginError(f"cannot read {os.path.basename(path)}: {error}") from None

    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "PLUGIN" in names:
                try:
                    value = ast.literal_eval(node.value)
                except ValueError:
                    raise PluginError(
                        "PLUGIN must be a plain dict of literals"
                    ) from None
                if isinstance(value, dict):
                    return dict(value)

    stem = os.path.splitext(os.path.basename(path))[0]
    return {
        "id": f"local.{stem.lower().replace(' ', '-')}",
        "name": stem.replace("_", " ").title(),
        "description": "Installed from a single file with no PLUGIN block.",
    }


def _validate(manifest: dict, folder: str) -> dict:
    for key in REQUIRED_KEYS:
        if not manifest.get(key):
            raise PluginError(f"the manifest needs a {key!r}")

    manifest = dict(manifest)
    manifest["id"] = _safe_id(str(manifest["id"]))
    manifest["name"] = str(manifest["name"])[:60]
    manifest.setdefault("version", "1.0.0")
    manifest.setdefault("author", "")
    manifest.setdefault("description", "")
    manifest["description"] = str(manifest["description"])[:600]

    entry = manifest.get("entry") or "main.py"
    manifest["entry"] = entry
    if not os.path.isfile(os.path.join(folder, entry)):
        raise PluginError(f"the entry file {entry!r} is not in the plugin")

    panel = manifest.get("panel")
    if panel:
        if not os.path.isfile(os.path.join(folder, panel)):
            raise PluginError(f"the panel file {panel!r} is not in the plugin")
        manifest["panel"] = panel

    tab = manifest.get("tab")
    if isinstance(tab, str):
        tab = {"title": tab}
    if isinstance(tab, dict):
        manifest["tab"] = {
            "title": str(tab.get("title") or manifest["name"])[:24],
            "icon": str(tab.get("icon") or "puzzle")[:24],
        }
    else:
        manifest.pop("tab", None)

    commands = []
    for command in manifest.get("commands") or []:
        if isinstance(command, str):
            command = {"name": command}
        if isinstance(command, dict) and command.get("name"):
            commands.append({
                "name": str(command["name"])[:32],
                "help": str(command.get("help", ""))[:200],
            })
    manifest["commands"] = commands

    permissions = [
        p for p in (manifest.get("permissions") or []) if p in KNOWN_PERMISSIONS
    ]
    manifest["permissions"] = permissions
    return manifest


def _safe_id(value: str) -> str:
    kept = [c for c in value.strip().lower() if c.isalnum() or c in "._-"]
    identifier = "".join(kept).strip("._-")
    if not identifier:
        raise PluginError("that id has no usable characters in it")
    return identifier[:80]


def _write_manifest(folder: str, manifest: dict) -> None:
    with open(os.path.join(folder, MANIFEST_NAME), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)


# ------------------------------------------------------------------- listing

def listing() -> str:
    """Every installed plugin, with whatever state the app needs to draw it."""
    rows = []
    if os.path.isdir(_plugins_dir):
        for name in sorted(os.listdir(_plugins_dir)):
            folder = os.path.join(_plugins_dir, name)
            if not os.path.isdir(folder) or name.startswith("."):
                continue
            try:
                manifest = read_manifest(folder)
            except PluginError as error:
                rows.append({
                    "id": name,
                    "name": name,
                    "broken": True,
                    "error": str(error),
                    "size": _folder_size(folder),
                })
                continue
            manifest["loaded"] = manifest["id"] in _loaded
            manifest["error"] = _errors.get(manifest["id"], "")
            manifest["size"] = _folder_size(folder)
            manifest["files"] = _folder_files(folder)
            rows.append(manifest)
    return _json({"ok": True, "plugins": rows})


def _folder_size(folder: str) -> int:
    total = 0
    for directory, _folders, names in os.walk(folder):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(directory, name))
            except OSError:
                pass
    return total


def _folder_files(folder: str) -> list:
    out = []
    for directory, _folders, names in os.walk(folder):
        for name in sorted(names):
            relative = os.path.relpath(os.path.join(directory, name), folder)
            out.append(relative)
            if len(out) >= 60:
                return out
    return out


def remove(plugin_id: str) -> str:
    unload(plugin_id)
    folder = plugin_dir(plugin_id)
    if not os.path.isdir(folder):
        return _json({"ok": False, "error": "that plugin is not installed"})
    shutil.rmtree(folder, ignore_errors=True)
    return _json({"ok": True})


def errors() -> str:
    return _json({"ok": True, "errors": _errors})


# ------------------------------------------------------------------- loading

def load_all(enabled_ids) -> str:
    """Loads the enabled plugins and unloads the rest. Returns what happened.

    Takes a comma-separated string as well as a list: what crosses the bridge
    from Kotlin is whatever the caller happened to have, and an empty Kotlin
    collection arrives as an object Python cannot iterate.
    """
    if isinstance(enabled_ids, str):
        names = [part for part in enabled_ids.split(",") if part.strip()]
    elif enabled_ids is None:
        names = []
    else:
        try:
            names = list(enabled_ids)
        except TypeError:
            names = []

    wanted = {_safe_id(str(i)) for i in names if str(i).strip()}

    for plugin_id in list(_loaded):
        if plugin_id not in wanted:
            unload(plugin_id)

    results = []
    for plugin_id in sorted(wanted):
        if plugin_id in _loaded:
            results.append({"id": plugin_id, "ok": True, "already": True})
            continue
        results.append(json.loads(load(plugin_id)))
    return _json({"ok": True, "results": results})


def load(plugin_id: str) -> str:
    """Imports one plugin's entry module with the `pycmd` API in place."""
    plugin_id = _safe_id(plugin_id)
    folder = plugin_dir(plugin_id)
    if not os.path.isdir(folder):
        return _json({"ok": False, "id": plugin_id, "error": "not installed"})

    try:
        manifest = read_manifest(folder)
    except PluginError as error:
        _errors[plugin_id] = str(error)
        return _json({"ok": False, "id": plugin_id, "error": str(error)})

    unload(plugin_id)
    api = Api(plugin_id, manifest, folder)
    module_name = f"pycmd_plugin_{plugin_id.replace('.', '_').replace('-', '_')}"
    entry = os.path.join(folder, manifest["entry"])

    # The plugin's own folder goes on sys.path so it can import its own
    # modules, and comes off again straight away so it cannot shadow anything.
    sys.path.insert(0, folder)
    try:
        specification = importlib.util.spec_from_file_location(module_name, entry)
        module = importlib.util.module_from_spec(specification)
        module.pycmd = api
        module.PLUGIN_DIR = folder
        sys.modules[module_name] = module
        specification.loader.exec_module(module)

        setup = getattr(module, "setup", None)
        if callable(setup):
            setup(api)
    except BaseException as error:  # noqa: BLE001 - a plugin may raise anything
        sys.modules.pop(module_name, None)
        detail = _format_error(error, manifest["name"])
        _errors[plugin_id] = detail
        _report("error", f"{manifest['name']} failed to load", detail)
        return _json({"ok": False, "id": plugin_id, "error": detail})
    finally:
        if sys.path and sys.path[0] == folder:
            sys.path.pop(0)

    _loaded[plugin_id] = {"manifest": manifest, "module": module, "api": api}
    _errors.pop(plugin_id, None)
    # Documented in PLUGINS.md, so it has to actually arrive: a plugin can
    # subscribe to its own load and do the work `setup` was too early for.
    for handler in api.listeners.get("plugin_loaded", []):
        try:
            handler({"id": plugin_id})
        except BaseException as error:  # noqa: BLE001
            _report("error", f"{manifest['name']} failed on plugin_loaded",
                    _format_error(error, manifest["name"]))
    _report("info", f"{manifest['name']} loaded", f"{len(api.exports)} exports, "
                                                  f"{len(api.command_names)} commands")
    return _json({"ok": True, "id": plugin_id, "manifest": manifest,
                  "exports": sorted(api.exports), "commands": api.command_names})


def unload(plugin_id: str) -> None:
    plugin_id = _safe_id(plugin_id)
    entry = _loaded.pop(plugin_id, None)
    if entry is None:
        return
    api = entry["api"]
    try:
        teardown = getattr(entry["module"], "teardown", None)
        if callable(teardown):
            teardown(api)
    except BaseException:  # noqa: BLE001
        pass
    module_name = f"pycmd_plugin_{plugin_id.replace('.', '_').replace('-', '_')}"
    sys.modules.pop(module_name, None)


def _format_error(error: BaseException, name: str) -> str:
    lines = traceback.format_exception(type(error), error, error.__traceback__)
    text = "".join(lines)
    # The app's own frames are noise to a plugin author.
    kept = [line for line in text.splitlines() if "pycmd_plugins.py" not in line]
    return f"{name}: " + "\n".join(kept[-12:])


# ------------------------------------------------------------------- the API

class Api:
    """What a plugin sees as `pycmd`.

    Deliberately small and stable. Everything here is either something the app
    can do for a plugin, or something a plugin needs to be reachable from the
    UI; anything else a plugin wants, it does with the standard library like
    any other Python.
    """

    def __init__(self, plugin_id, manifest, folder) -> None:
        self.id = plugin_id
        self.manifest = manifest
        self.name = manifest.get("name", plugin_id)
        self.dir = folder
        self.workspace = _workspace_dir
        self.version = manifest.get("version", "")
        self.exports = {}
        self.commands = {}
        self.command_names = []
        self.listeners = {}
        self.state_path = os.path.join(folder, ".state.json")

    # -- talking to the user ------------------------------------------------

    def print(self, *values, sep=" ", end="\n") -> None:
        """Writes to the console the user is looking at."""
        text = sep.join(str(v) for v in values) + end
        try:
            sys.stdout.write(text)
        except Exception:  # noqa: BLE001
            pass

    def log(self, message, detail="") -> None:
        """Writes to the debug console, which is where plugin noise belongs."""
        _report("info", f"[{self.name}] {message}", str(detail))

    def warn(self, message, detail="") -> None:
        _report("warn", f"[{self.name}] {message}", str(detail))

    def error(self, message, detail="") -> None:
        _report("error", f"[{self.name}] {message}", str(detail))

    def toast(self, message) -> None:
        if _host is not None:
            try:
                _host.onToast(str(message)[:200])
            except Exception:  # noqa: BLE001
                pass

    # -- files --------------------------------------------------------------

    def workspace_path(self, *parts) -> str:
        return os.path.join(_workspace_dir, *parts)

    def read(self, path, default=None):
        try:
            with open(self._resolve(path), "r", encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            return default

    def write(self, path, text) -> bool:
        target = self._resolve(path)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(text)
            return True
        except OSError as error:
            self.error("could not write", f"{target}: {error}")
            return False

    def files(self, pattern="*"):
        import fnmatch

        found = []
        for directory, folders, names in os.walk(_workspace_dir):
            folders[:] = [f for f in folders if f != "__pycache__"]
            for name in names:
                if fnmatch.fnmatch(name, pattern):
                    found.append(os.path.join(directory, name))
        return sorted(found)

    def _resolve(self, path) -> str:
        return path if os.path.isabs(path) else os.path.join(_workspace_dir, path)

    # -- storage ------------------------------------------------------------

    def store(self, data=None):
        """Reads or writes this plugin's own little JSON store."""
        if data is None:
            try:
                with open(self.state_path, "r", encoding="utf-8") as handle:
                    return json.load(handle)
            except (OSError, ValueError):
                return {}
        try:
            with open(self.state_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            return data
        except (OSError, TypeError) as error:
            self.error("could not save state", str(error))
            return data

    # -- being called from elsewhere ---------------------------------------

    def export(self, function=None, *, name=None):
        """Makes a function callable from the plugin's HTML panel."""
        def register(target):
            self.exports[name or target.__name__] = target
            return target

        return register(function) if function is not None else register

    def command(self, name, help=""):
        """Registers a console command: the user types `name args...`."""
        def register(target):
            self.commands[name] = target
            if name not in self.command_names:
                self.command_names.append(name)
            return target

        return register

    def on(self, event, handler=None):
        """Subscribes to an app event. See PLUGINS.md for the list."""
        def register(target):
            self.listeners.setdefault(event, []).append(target)
            return target

        return register(handler) if handler is not None else register

    def send(self, message) -> None:
        """Pushes a message to the plugin's panel, if one is open."""
        if _host is None:
            return
        try:
            _host.onPluginMessage(self.id, _json(message))
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------- calling into them

def call_export(plugin_id: str, name: str, payload: str = "") -> str:
    """Runs an exported function for the panel. Always returns JSON."""
    entry = _loaded.get(_safe_id(plugin_id))
    if entry is None:
        return _json({"ok": False, "error": "that plugin is not loaded"})

    function = entry["api"].exports.get(name)
    if function is None:
        available = ", ".join(sorted(entry["api"].exports)) or "none"
        return _json({"ok": False, "error": f"no export called {name!r} (has: {available})"})

    try:
        argument = json.loads(payload) if payload else None
    except ValueError:
        argument = payload

    try:
        result = function(argument) if argument is not None else function()
    except BaseException as error:  # noqa: BLE001
        detail = _format_error(error, entry["manifest"]["name"])
        _report("error", f"{entry['manifest']['name']}.{name} raised", detail)
        return _json({"ok": False, "error": detail})

    try:
        return _json({"ok": True, "result": result})
    except TypeError:
        return _json({"ok": True, "result": str(result)})


def commands() -> str:
    """Every command every loaded plugin has registered."""
    rows = []
    for plugin_id, entry in _loaded.items():
        for name in entry["api"].command_names:
            rows.append({
                "plugin": plugin_id,
                "name": name,
                "help": next(
                    (c.get("help", "") for c in entry["manifest"].get("commands", [])
                     if c.get("name") == name),
                    "",
                ),
            })
    return _json({"ok": True, "commands": rows})


def run_command(name: str, argument: str = "") -> str:
    """Dispatches `name` to whichever plugin registered it."""
    for plugin_id, entry in _loaded.items():
        function = entry["api"].commands.get(name)
        if function is None:
            continue
        try:
            result = function(argument)
        except BaseException as error:  # noqa: BLE001
            detail = _format_error(error, entry["manifest"]["name"])
            sys.stderr.write(detail + "\n")
            return _json({"ok": False, "handled": True, "error": detail})
        return _json({"ok": True, "handled": True, "plugin": plugin_id,
                      "result": None if result is None else str(result)})
    return _json({"ok": True, "handled": False})


def fire(event: str, payload: str = "") -> str:
    """Tells every plugin that something happened. Never raises."""
    try:
        data = json.loads(payload) if payload else {}
    except ValueError:
        data = {"raw": payload}

    delivered = 0
    for plugin_id, entry in list(_loaded.items()):
        for handler in entry["api"].listeners.get(event, []):
            try:
                handler(data)
                delivered += 1
            except BaseException as error:  # noqa: BLE001
                detail = _format_error(error, entry["manifest"]["name"])
                _report("error", f"{entry['manifest']['name']} failed on {event}", detail)
    return _json({"ok": True, "delivered": delivered})


# --------------------------------------------------------------- the panel

BRIDGE = """
<script>
(function () {
  'use strict';
  var pending = {};
  var nextId = 1;
  var listeners = {};

  function call(name, payload) {
    var id = nextId++;
    return new Promise(function (resolve, reject) {
      pending[id] = { resolve: resolve, reject: reject };
      window.__pycmd_panel.call(String(id), name, JSON.stringify(payload === undefined ? null : payload));
    });
  }

  window.__pycmd_resolve = function (id, ok, body) {
    var slot = pending[id];
    if (!slot) return;
    delete pending[id];
    var parsed;
    try { parsed = JSON.parse(body); } catch (e) { parsed = body; }
    if (ok) slot.resolve(parsed && parsed.result !== undefined ? parsed.result : parsed);
    else slot.reject(new Error(parsed && parsed.error ? parsed.error : String(body)));
  };

  window.__pycmd_message = function (body) {
    var parsed;
    try { parsed = JSON.parse(body); } catch (e) { parsed = body; }
    (listeners.message || []).forEach(function (fn) { fn(parsed); });
  };

  window.pycmd = {
    call: call,
    on: function (event, fn) { (listeners[event] = listeners[event] || []).push(fn); },
    toast: function (text) { window.__pycmd_panel.toast(String(text)); },
    log: function (text) { window.__pycmd_panel.log(String(text)); },
    close: function () { window.__pycmd_panel.close(); },
    plugin: JSON.parse(window.__pycmd_panel.manifest())
  };

  window.addEventListener('error', function (event) {
    if (window.__pycmd_panel) window.__pycmd_panel.log('panel error: ' + event.message);
  });
})();
</script>
"""

PANEL_CSS = """
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 16px 14px 32px;
  background: #0B0F14; color: #DCE3EC;
  font: 15px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
}
h1, h2, h3 { color: #F1F5FA; line-height: 1.25; margin: 1.2em 0 .5em; }
h1 { font-size: 1.5em; } h2 { font-size: 1.2em; }
button {
  font: inherit; padding: 10px 16px; border-radius: 12px;
  border: 1px solid #2E7DD1; background: #16324D; color: #DCE3EC;
}
button:active { background: #1E4269; }
input, textarea, select {
  font: inherit; width: 100%; padding: 10px 12px; border-radius: 12px;
  border: 1px solid #223041; background: #10161F; color: #DCE3EC;
}
pre, code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .9em; }
pre { background: #10161F; border: 1px solid #223041; border-radius: 10px; padding: 12px; overflow-x: auto; }
.card { background: #121A24; border: 1px solid #223041; border-radius: 14px; padding: 14px; margin: 10px 0; }
a { color: #6FB3FF; }
</style>
"""


def panel_html(plugin_id: str) -> str:
    """The plugin's panel with the bridge and the house style injected."""
    plugin_id = _safe_id(plugin_id)
    folder = plugin_dir(plugin_id)
    try:
        manifest = read_manifest(folder)
    except PluginError as error:
        return _error_page(str(error))

    panel = manifest.get("panel")
    if not panel:
        return _error_page(f"{manifest['name']} has no panel to show.")

    try:
        with open(os.path.join(folder, panel), "r", encoding="utf-8") as handle:
            body = handle.read()
    except OSError as error:
        return _error_page(f"could not read {panel}: {error}")

    head = PANEL_CSS + BRIDGE
    lowered = body.lower()
    if "</head>" in lowered:
        index = lowered.index("</head>")
        return body[:index] + head + body[index:]
    if "<body" in lowered:
        index = lowered.index("<body")
        end = body.index(">", index) + 1
        return body[:end] + head + body[end:]
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        + head + "</head><body>" + body + "</body></html>"
    )


def _error_page(message: str) -> str:
    escaped = (message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        + PANEL_CSS +
        "</head><body><div class='card'><h2>This panel could not open</h2>"
        f"<pre>{escaped}</pre></div></body></html>"
    )


# ------------------------------------------------------------------ plumbing

def _json(value) -> str:
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError) as error:
        return json.dumps({"ok": False, "error": f"could not encode the result: {error}"})


def _report(level: str, message: str, detail: str = "") -> None:
    if _host is None:
        return
    try:
        _host.onPluginLog(level, message, detail)
    except Exception:  # noqa: BLE001
        pass
