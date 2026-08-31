"""The one object the window's JavaScript talks to.

On Android this job is split between Kotlin's `PythonEngine` - which owns the
interpreter and its threads - and `MainViewModel`, which owns what is on
screen. Here they are the same object, because there is no JNI boundary to
justify two, and because the whole UI is a web page: everything crosses as
JSON either way.

The surface is deliberately one method. `call(name, payload)` looks the name up
in [HANDLERS] and returns JSON. That is the same shape the plugin bridge has
always had, it is trivially testable without a window, and it means adding a
screen is adding a function to a dict rather than threading a new method
through two layers.

Three threads matter here:

* **the interpreter thread**, where somebody's Python runs, one at a time,
  because CPython has one GIL and pretending otherwise only moves the problem;
* **the run thread**, where a compiled language's build and execution happen;
* **the UI thread**, which must never wait for either.

Anything that can block gets its own thread and reports back through [emit].
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback

from . import builtins, bundle, langs, runner, store, toolchains

VERSION = "1.0.0"
BUILD = 1

_engine_ready = False


def _import_engine():
    """Puts the shared engine on the path and imports it.

    The modules are the phone's, unchanged - that is the point of the port.
    They are imported here rather than at module scope so that importing
    `pycmd_win.host` in a test does not drag the whole engine in with it.
    """
    engine = store.engine_path()
    if engine not in sys.path:
        sys.path.insert(0, engine)
    import pycmd_doctor
    import pycmd_download
    import pycmd_music
    import pycmd_packages
    import pycmd_pages
    import pycmd_plugins
    import pycmd_preview
    import pycmd_runtime
    import pycmd_servers
    import pycmd_shell
    import pycmd_tools

    return {
        "doctor": pycmd_doctor, "download": pycmd_download, "music": pycmd_music,
        "packages": pycmd_packages, "pages": pycmd_pages, "plugins": pycmd_plugins,
        "preview": pycmd_preview, "runtime": pycmd_runtime, "servers": pycmd_servers,
        "shell": pycmd_shell, "tools": pycmd_tools,
    }


class Host:
    """Everything the window can ask for."""

    def __init__(self, emit=None):
        # Where events go. The app replaces this with something that reaches
        # the page; until then they queue, so nothing is lost during boot.
        self._pending = queue.Queue(maxsize=8192)
        self._emit = emit
        self.engine = {}
        self.started_at = time.time()
        self._stdin = queue.Queue()
        self._log = []
        self._log_lock = threading.Lock()

    # -- events ------------------------------------------------------------

    def set_emit(self, emit) -> None:
        """Points events at the page, and flushes whatever waited for it."""
        self._emit = emit
        while True:
            try:
                event = self._pending.get_nowait()
            except queue.Empty:
                break
            self._deliver(event)

    def _deliver(self, event) -> None:
        emit = self._emit
        if emit is None:
            try:
                self._pending.put_nowait(event)
            except queue.Full:
                pass
            return
        try:
            emit(event)
        except Exception:  # noqa: BLE001 - the window may be closing
            pass

    def emit(self, kind: str, **detail) -> None:
        self._deliver({"kind": kind, **detail})

    def drain(self) -> list:
        """Every event waiting, for a UI that polls instead of being pushed to."""
        out = []
        while len(out) < 500:
            try:
                out.append(self._pending.get_nowait())
            except queue.Empty:
                break
        return out

    # -- the sink the engine writes through --------------------------------

    def onOutput(self, stream, text, channel="console"):  # noqa: N802 - engine's name
        self.emit("output", stream=stream, text=text, channel=channel)

    def onReadLine(self, channel="console"):  # noqa: N802
        """input() from somebody's script. Blocks the interpreter thread only."""
        self.emit("input-wanted", channel=channel)
        try:
            return self._stdin.get(timeout=600)
        except queue.Empty:
            return ""

    def onFinished(self, run_id, status, millis):  # noqa: N802
        self.emit("finished", run=run_id, status=status, millis=millis)

    # -- the callbacks plugins reach the app through -----------------------

    def onPluginLog(self, level, message, detail):  # noqa: N802
        self.log(level, message, detail)

    def onToast(self, message):  # noqa: N802
        self.emit("toast", text=str(message)[:300])

    def onPluginMessage(self, plugin_id, body):  # noqa: N802
        self.emit("plugin-message", plugin=plugin_id, body=body)

    def onPluginAction(self, plugin_id, action, detail):  # noqa: N802
        try:
            parsed = json.loads(detail) if isinstance(detail, str) else (detail or {})
        except ValueError:
            parsed = {"raw": detail}
        self.emit("plugin-action", plugin=plugin_id, action=action, detail=parsed)

    # -- the debug log -----------------------------------------------------

    def log(self, level, message, detail="") -> None:
        entry = {
            "at": time.time(), "level": str(level), "message": str(message)[:400],
            "detail": str(detail)[:4000],
        }
        with self._log_lock:
            self._log.append(entry)
            # Same ceiling the phone build uses, and the same reason: a chatty
            # server should cost a bounded amount of memory, not all of it.
            if len(self._log) > 3000:
                del self._log[:len(self._log) - 3000]
        self.emit("log", **entry)

    def log_entries(self) -> list:
        with self._log_lock:
            return list(self._log)

    # -- boot --------------------------------------------------------------

    def start(self) -> dict:
        """Wires the engine up. Idempotent."""
        global _engine_ready
        if _engine_ready and self.engine:
            return {"ok": True, "already": True, "version": VERSION,
                    "python": sys.version.split()[0], "root": store.root()}

        store.prepare()
        self.engine = _import_engine()

        workspace = store.folder("workspace")
        packages = store.folder("site-packages")

        self.engine["runtime"].configure(self, workspace, packages)
        self.engine["packages"].configure(packages)
        self.engine["plugins"].configure(store.folder("plugins"), workspace, self)

        # These grew their signatures at different times and not every build
        # has every one; ask for what exists rather than guessing.
        for name, args in (
            ("pages", (store.folder("pages"), workspace)),
            ("music", (store.folder("music"),)),
        ):
            configure = getattr(self.engine.get(name), "configure", None)
            if configure is None:
                continue
            for attempt in (args, args[:1]):
                try:
                    configure(*attempt)
                    break
                except TypeError:
                    continue
                except Exception as error:  # noqa: BLE001
                    self.log("warn", f"{name} would not configure", str(error))
                    break

        # Bundled plugins go in before anything is loaded, never beside it.
        # Installing replaces a plugin's folder and loading imports out of it;
        # on the phone those once ran at the same time and a plugin was
        # imported while its own files were being moved out from under it.
        staged = bundle.install_bundled(self.engine["plugins"], log=self.log)
        if staged.get("installed"):
            self.log("info", "bundled plugins installed",
                     ", ".join(staged["installed"]))

        _engine_ready = True
        self.log("info", f"PyCmd for Windows {VERSION} ready", store.root())
        return {
            "ok": True,
            "version": VERSION,
            "python": sys.version.split()[0],
            "root": store.root(),
        }


# ---------------------------------------------------------------------------
# The handlers
#
# Each takes (host, payload dict) and returns something JSON can carry.
# ---------------------------------------------------------------------------

def _h_hello(host, payload):
    return {
        "version": VERSION, "build": BUILD,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "root": store.root(),
        "started": host.started_at,
        "ready": bool(host.engine),
    }


def _h_console_run(host, payload):
    """Runs a console line on the interpreter thread and returns at once."""
    text = str(payload.get("text", ""))
    channel = str(payload.get("channel", "console"))

    def work():
        try:
            # One argument, not two. The channel is the engine's own idea and
            # it tracks it itself; passing one here was a TypeError that only
            # showed up as "nothing happens when I press Run".
            host.engine["runtime"].run_console(text)
        except Exception as error:  # noqa: BLE001 - somebody's code may do anything
            host.onOutput("stderr", f"{type(error).__name__}: {error}\n", channel)
            host.log("error", "console line failed", traceback.format_exc())

    threading.Thread(target=work, name="pycmd-console", daemon=True).start()
    return {"queued": True}


def _h_console_stdin(host, payload):
    host._stdin.put(str(payload.get("text", "")))
    return {}


def _h_console_stop(host, payload):
    host.engine["runtime"].request_stop()
    runner.stop_all()
    return {}


def _h_console_reset(host, payload):
    host.engine["runtime"].reset_namespace()
    return {}


def _h_completions(host, payload):
    return {"items": host.engine["runtime"].completions(str(payload.get("text", "")))}


def _h_run_file(host, payload):
    """Runs a file with a real toolchain, streaming as it goes."""
    path = str(payload.get("path", ""))
    prefer = str(payload.get("toolchain", ""))
    channel = str(payload.get("channel", "console"))

    def work():
        def write(text):
            host.onOutput("stdout", text, channel)

        started = time.monotonic()
        result = runner.run_file(path, write, prefer=prefer)
        host.onFinished(
            result.get("run", {}).get("id", 0),
            "ok" if result.get("ok") else "error",
            int((time.monotonic() - started) * 1000),
        )

    threading.Thread(target=work, name="pycmd-run", daemon=True).start()
    return {"queued": True}


def _h_run_stop(host, payload):
    run_id = str(payload.get("id", ""))
    return {"stopped": runner.stop(run_id) if run_id else runner.stop_all()}


def _h_run_active(host, payload):
    return {"runs": runner.active()}


# -- languages and toolchains ----------------------------------------------

def _h_languages(host, payload):
    return {"languages": langs.catalogue(), "stats": langs.stats()}


def _h_toolchains(host, payload):
    refresh = bool(payload.get("refresh"))
    return {
        "toolchains": toolchains.detect_all(refresh=refresh),
        "summary": toolchains.summary(refresh=False),
    }


def _h_toolchain_check(host, payload):
    return {"found": toolchains.detect(str(payload.get("id", "")), refresh=True)}


def _h_toolchain_install(host, payload):
    """Runs the install line for a toolchain, streaming what the installer says.

    PyCmd does not bundle compilers - a build carrying MSVC and a JDK would be
    gigabytes - so this shells out to whichever package manager the machine
    has. It is the user's own winget, running the line they would have typed.
    """
    chain = toolchains.by_id(str(payload.get("id", "")))
    if chain is None:
        return {"ok": False, "error": "no such toolchain"}
    manager = str(payload.get("with", "winget"))
    line = {"winget": chain.winget, "scoop": chain.scoop,
            "choco": chain.choco}.get(manager, "")
    if not line:
        return {"ok": False, "error": f"{chain.name} has no {manager} package",
                "site": chain.site}

    def work():
        host.onOutput("system", f"[PyCmd] {line}\n", "console")
        try:
            process = subprocess.Popen(
                line.split(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                               if os.name == "nt" else 0),
            )
        except FileNotFoundError:
            host.onOutput("stderr", f"[PyCmd] {manager} is not installed here.\n", "console")
            return
        for chunk in process.stdout or []:
            host.onOutput("stdout", chunk, "console")
        process.wait()
        toolchains.detect(chain.id, refresh=True)
        host.emit("toolchains-changed", id=chain.id)

    threading.Thread(target=work, name="pycmd-install", daemon=True).start()
    return {"queued": True, "command": line}


# -- everything else delegates ---------------------------------------------

def _json_call(module, name, *args):
    """Calls an engine function that answers with a JSON string."""
    function = getattr(module, name, None)
    if function is None:
        return {"ok": False, "error": f"{name} is not in this build"}
    reply = function(*args)
    if isinstance(reply, str):
        try:
            return json.loads(reply)
        except ValueError:
            return {"ok": True, "text": reply}
    return reply if isinstance(reply, (dict, list)) else {"ok": True, "value": reply}


def _h_shell(host, payload):
    return _json_call(host.engine["shell"], "handle",
                      str(payload.get("line", "")), str(payload.get("channel", "console")))


def _h_plugins(host, payload):
    """Both halves of the Plugins tab: the thirteen built in, and the installed."""
    installed = _json_call(host.engine["plugins"], "listing")
    return {
        "builtin": builtins.listing(),
        "installed": installed.get("plugins", []),
        "enabled": builtins.enabled_ids(),
    }


def _h_builtin_set(host, payload):
    return builtins.set_enabled(str(payload.get("id", "")), bool(payload.get("on")))


def _h_builtin_reset(host, payload):
    return builtins.reset()


def _h_plugin_inspect(host, payload):
    """Reads a plugin before installing it - used by the mobile-import button."""
    return bundle.inspect_mobile(str(payload.get("path", "")))


def _h_plugin_install(host, payload):
    """Installs a plugin folder or zip, from anywhere on the disk."""
    path = str(payload.get("path", ""))
    if not path:
        return {"ok": False, "error": "nothing to install"}
    name = os.path.basename(path.rstrip("\\/")) or "plugin"
    reply = _json_call(host.engine["plugins"], "install", path, name, "")
    if reply.get("ok"):
        host.log("info", "plugin installed", reply.get("manifest", {}).get("id", name))
    return reply


def _h_plugin_load(host, payload):
    return _json_call(host.engine["plugins"], "load_all",
                      ",".join(payload.get("enabled", []) or []))


def _h_plugin_panel(host, payload):
    return {"html": host.engine["plugins"].panel_html(
        str(payload.get("id", "")), str(payload.get("panel", "")))}


def _h_plugin_export(host, payload):
    return _json_call(host.engine["plugins"], "call_export",
                      str(payload.get("id", "")), str(payload.get("name", "")),
                      json.dumps(payload.get("payload")))


def _h_plugin_remove(host, payload):
    return _json_call(host.engine["plugins"], "remove", str(payload.get("id", "")))


def _h_plugin_settings(host, payload):
    return _json_call(host.engine["plugins"], "plugin_settings", str(payload.get("id", "")))


def _h_plugin_set_setting(host, payload):
    return _json_call(host.engine["plugins"], "set_plugin_setting",
                      str(payload.get("id", "")), str(payload.get("name", "")),
                      str(payload.get("value", "")))


def _h_plugin_guide(host, payload):
    return _json_call(host.engine["plugins"], "guide_text",
                      str(payload.get("id", "")), str(payload.get("file", "")))


def _h_servers(host, payload):
    return _json_call(host.engine["servers"], "listing")


def _h_packages(host, payload):
    return _json_call(host.engine["packages"], "listing")


def _h_pages(host, payload):
    return _json_call(host.engine["pages"], "listing")


def _h_music(host, payload):
    return _json_call(host.engine["music"], "library")


def _h_system(host, payload):
    return {
        "store": store.describe(),
        "version": VERSION,
        "python": sys.version.split()[0],
        "languages": langs.stats(),
        "toolchains": toolchains.summary(),
    }


def _h_log(host, payload):
    return {"entries": host.log_entries()}


def _h_drain(host, payload):
    return {"events": host.drain()}


HANDLERS = {
    "hello": _h_hello,
    "console.run": _h_console_run,
    "console.stdin": _h_console_stdin,
    "console.stop": _h_console_stop,
    "console.reset": _h_console_reset,
    "console.completions": _h_completions,
    "run.file": _h_run_file,
    "run.stop": _h_run_stop,
    "run.active": _h_run_active,
    "languages": _h_languages,
    "toolchains": _h_toolchains,
    "toolchain.check": _h_toolchain_check,
    "toolchain.install": _h_toolchain_install,
    "shell": _h_shell,
    "plugins": _h_plugins,
    "builtin.set": _h_builtin_set,
    "builtin.reset": _h_builtin_reset,
    "plugin.inspect": _h_plugin_inspect,
    "plugin.install": _h_plugin_install,
    "plugin.load": _h_plugin_load,
    "plugin.panel": _h_plugin_panel,
    "plugin.export": _h_plugin_export,
    "plugin.remove": _h_plugin_remove,
    "plugin.settings": _h_plugin_settings,
    "plugin.setting.set": _h_plugin_set_setting,
    "plugin.guide": _h_plugin_guide,
    "servers": _h_servers,
    "packages": _h_packages,
    "pages": _h_pages,
    "music": _h_music,
    "system": _h_system,
    "log": _h_log,
    "drain": _h_drain,
}


def call(host: Host, name: str, payload=None) -> dict:
    """The whole API. Never raises: the page gets an answer either way."""
    handler = HANDLERS.get(name)
    if handler is None:
        return {"ok": False, "error": f"{name!r} is not something PyCmd can do"}
    try:
        result = handler(host, payload or {})
    except Exception as error:  # noqa: BLE001 - one bad call must not end the app
        host.log("error", f"{name} failed", traceback.format_exc())
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    if isinstance(result, dict):
        result.setdefault("ok", True)
        return result
    return {"ok": True, "result": result}
