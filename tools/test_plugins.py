"""Checks the custom-plugin runtime.

Installs plugins in all three shapes, loads them, calls their exports and
commands, fires events at them, and - the part that matters most - makes sure
a plugin that misbehaves is reported rather than allowed to take the app with
it. A plugin system whose failure mode is "the app dies" is worse than none.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import pycmd_plugins as plugins  # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


class FakeHost:
    def __init__(self):
        self.logs = []
        self.toasts = []
        self.messages = []

    def onPluginLog(self, level, message, detail):  # noqa: N802
        self.logs.append((level, message, detail))

    def onToast(self, message):  # noqa: N802
        self.toasts.append(message)

    def onPluginMessage(self, plugin_id, body):  # noqa: N802
        self.messages.append((plugin_id, body))

    def text(self):
        return "\n".join(f"{l}:{m}:{d}" for l, m, d in self.logs)


scratch = tempfile.mkdtemp(prefix="pycmd-plugins-")
plugin_home = os.path.join(scratch, "plugins")
workspace = os.path.join(scratch, "workspace")
os.makedirs(workspace, exist_ok=True)
host = FakeHost()
plugins.configure(plugin_home, workspace, host)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def result(raw):
    return json.loads(raw)


SAID = []


def capture(call):
    """Runs `call`, collecting whatever it wrote to the console."""
    buffer = io.StringIO()
    previous = sys.stdout
    sys.stdout = buffer
    try:
        return call()
    finally:
        sys.stdout = previous
        if buffer.getvalue():
            SAID.append(buffer.getvalue())


# ------------------------------------------------- shape 1: a single .py file

print("\n== a single-file plugin ==")
single = write(os.path.join(scratch, "src", "wordcount.py"), '''
PLUGIN = {
    "id": "demo.wordcount",
    "name": "Word Count",
    "version": "1.2.0",
    "description": "Counts things.",
    "commands": [{"name": "wc", "help": "wc <text>"}],
}

TOTALS = {"calls": 0}


def setup(api):
    api.log("word count is up")

    @api.command("wc", help="wc <text>")
    def count(argument):
        TOTALS["calls"] += 1
        api.print(f"{len(argument.split())} words")
        return len(argument.split())

    @api.export
    def analyse(payload):
        text = (payload or {}).get("text", "")
        return {"words": len(text.split()), "characters": len(text)}

    @api.on("file_saved")
    def saved(event):
        api.log("saw a save", event.get("path", ""))
''')

installed = result(plugins.install(single))
check("a .py file installs", installed.get("ok"), installed)
check("its PLUGIN block is the manifest",
      installed.get("manifest", {}).get("name") == "Word Count", installed)
check("the version comes across",
      installed.get("manifest", {}).get("version") == "1.2.0", installed)

listed = result(plugins.listing())
check("it shows up in the listing", len(listed["plugins"]) == 1, listed)
check("and is not loaded yet", not listed["plugins"][0]["loaded"], listed)

loaded = result(plugins.load("demo.wordcount"))
check("it loads", loaded.get("ok"), loaded)
check("setup ran", "word count is up" in host.text(), host.text())
check("its export is registered", "analyse" in loaded.get("exports", []), loaded)
check("its command is registered", "wc" in loaded.get("commands", []), loaded)

called = result(plugins.call_export("demo.wordcount", "analyse", json.dumps({"text": "a b c"})))
check("an export can be called", called.get("ok"), called)
check("and returns its value", called.get("result", {}).get("words") == 3, called)

missing = result(plugins.call_export("demo.wordcount", "nope"))
check("an unknown export is an error, not a crash", not missing.get("ok"), missing)
check("and says what does exist", "analyse" in missing.get("error", ""), missing)

# The command writes to stdout, so capture it the way the console would.
captured = io.StringIO()
saved_stdout = sys.stdout
sys.stdout = captured
try:
    ran = result(plugins.run_command("wc", "one two three four"))
finally:
    sys.stdout = saved_stdout
check("a command runs", ran.get("handled") and ran.get("ok"), ran)
check("and its print reaches the console", "4 words" in captured.getvalue(),
      repr(captured.getvalue()))

unknown = result(plugins.run_command("definitely-not-a-command", ""))
check("an unknown command is left alone", not unknown.get("handled"), unknown)

fired = result(plugins.fire("file_saved", json.dumps({"path": "x.py"})))
check("an event reaches the plugin", fired.get("delivered") == 1, fired)
check("and the plugin saw the payload", "x.py" in host.text(), host.text())

fired = result(plugins.fire("nothing_listens_to_this", "{}"))
check("an event nobody wants is harmless", fired.get("delivered") == 0, fired)

# ------------------------------------------------------- shape 2: a folder

print("\n== a folder plugin with a panel ==")
folder = os.path.join(scratch, "src", "notes")
write(os.path.join(folder, "plugin.json"), json.dumps({
    "id": "demo.notes",
    "name": "Notes",
    "version": "0.1.0",
    "entry": "main.py",
    "panel": "ui.html",
    "tab": {"title": "Notes", "icon": "note"},
    "permissions": ["files"],
}))
write(os.path.join(folder, "main.py"), '''
def setup(api):
    @api.export
    def save(payload):
        api.store({"text": payload.get("text", "")})
        return {"saved": True}

    @api.export(name="load_text")
    def load(payload=None):
        return api.store().get("text", "")
''')
write(os.path.join(folder, "ui.html"), "<h1>Notes</h1><div id=x></div>")

installed = result(plugins.install(folder))
check("a folder installs", installed.get("ok"), installed)
check("the panel is recorded",
      installed.get("manifest", {}).get("panel") == "ui.html", installed)
check("the tab is normalised",
      installed.get("manifest", {}).get("tab", {}).get("title") == "Notes", installed)


print("\n== two plugins wanting the same command ==")
for index, folder_name in enumerate(("clash-a", "clash-b")):
    clash = os.path.join(scratch, "src", folder_name)
    write(os.path.join(clash, "plugin.json"), json.dumps({
        "id": f"demo.{folder_name}", "name": folder_name, "entry": "main.py",
    }))
    write(os.path.join(clash, "main.py"), f"""
def setup(api):
    @api.command("both", help="both")
    def both(argument):
        return "from {folder_name}"
""")
    result(plugins.install(clash))
    result(plugins.load(f"demo.{folder_name}"))

host.logs.clear()
listed = result(plugins.commands())["commands"]
both = [row for row in listed if row["name"] == "both"]
check("both are listed", len(both) == 2, both)
check("one is marked as shadowed",
      sum(1 for row in both if row["shadowed"]) == 1, both)
check("and the clash is reported",
      any("both" in message for _level, message, _detail in host.logs), host.logs)

print("\n== a command that returns its answer ==")
returner = os.path.join(scratch, "src", "returner")
write(os.path.join(returner, "plugin.json"), json.dumps({
    "id": "demo.returner", "name": "Returner", "entry": "main.py",
}))
write(os.path.join(returner, "main.py"), """
def setup(api):
    @api.command("echo2", help="echo2 <text>")
    def echo2(argument):
        return "you said " + argument.strip()

    @api.command("quiet", help="says nothing")
    def quiet(argument):
        return None
""")
result(plugins.install(returner))
result(plugins.load("demo.returner"))
SAID.clear()
reply = capture(lambda: result(plugins.run_command("echo2", "hello there")))
check("the command is handled", reply.get("handled"), reply)
check("and what it returned is printed",
      any("you said hello there" in text for text in SAID), SAID)
SAID.clear()
capture(lambda: result(plugins.run_command("quiet", "")))
check("returning nothing prints nothing", SAID == [], SAID)

print("\n== a tab in the More screen ==")
# The icon is a real file inside the plugin, because a plugin author cannot
# add a drawable to the app.
icon_folder = os.path.join(scratch, "src", "withicon")
write(os.path.join(icon_folder, "plugin.json"), json.dumps({
    "id": "demo.icon",
    "name": "With Icon",
    "entry": "main.py",
    "panel": "ui.html",
    "tab": {"title": "Board", "description": "A live board", "icon": "logo.png"},
}))
write(os.path.join(icon_folder, "main.py"), "def setup(api):\n    pass\n")
write(os.path.join(icon_folder, "ui.html"), "<h1>Board</h1>")
with open(os.path.join(icon_folder, "logo.png"), "wb") as handle:
    handle.write(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

installed = result(plugins.install(icon_folder))
check("a plugin with an image icon installs", installed.get("ok"), installed)

listed = result(plugins.listing())["plugins"]
row = next((p for p in listed if p["id"] == "demo.icon"), None)
check("its tab survives the install", row and row["tab"]["title"] == "Board", row)
check("with its own description", row["tab"]["description"] == "A live board", row)
check("and the icon resolves to where it now lives",
      os.path.isfile(row["tab"]["image"]), row["tab"])
check("which is inside the installed plugin, not the staging folder",
      "staging" not in row["tab"]["image"], row["tab"]["image"])

saved = json.load(open(os.path.join(plugins.plugin_dir("demo.icon"), "plugin.json")))
check("the absolute path is not written down",
      "image" not in saved["tab"], saved["tab"])

print("\n== a section inside one of the app's own tabs ==")
ext = os.path.join(scratch, "src", "extender")
write(os.path.join(ext, "plugin.json"), json.dumps({
    "id": "demo.extender",
    "name": "Extender",
    "entry": "main.py",
    "panel": "ui.html",
    "extends": [
        {"tab": "servers", "title": "Board", "description": "live", "panel": "board.html",
         "height": "tall", "open": True},
        {"tab": "files"},
    ],
}))
write(os.path.join(ext, "main.py"), "def setup(api):\n    pass\n")
write(os.path.join(ext, "ui.html"), "<h1>x</h1>")
write(os.path.join(ext, "board.html"), "<h1>board</h1>")

installed = result(plugins.install(ext))
check("a plugin that extends a tab installs", installed.get("ok"), installed)
sections = installed.get("manifest", {}).get("extends", [])
check("both sections are kept", len(sections) == 2, sections)
check("the first names its own panel and height",
      sections[0]["panel"] == "board.html" and sections[0]["height"] == "tall", sections[0])
check("and can ask to start open", sections[0]["open"] is True, sections[0])
check("the second falls back to the plugin's panel",
      sections[1]["panel"] == "ui.html" and sections[1]["title"] == "Extender", sections[1])
check("and is closed by default", sections[1]["open"] is False, sections[1])

page = plugins.panel_html("demo.extender", "board.html")
check("its section panel renders", "<h1>board</h1>" in page, page[:200])
check("with the bridge injected", "__pycmd_panel" in page or "pycmd" in page)
main_page = plugins.panel_html("demo.extender")
check("and the main panel still renders", "<h1>x</h1>" in main_page, main_page[:200])
escaped = plugins.panel_html("demo.extender", "../../../etc/passwd")
check("a panel outside the plugin is refused", "<h1>" not in escaped or "passwd" not in escaped)

bad_tab = os.path.join(scratch, "src", "badtab")
write(os.path.join(bad_tab, "plugin.json"), json.dumps({
    "id": "demo.badtab", "name": "Bad Tab", "entry": "main.py", "panel": "ui.html",
    "extends": [{"tab": "wherever"}],
}))
write(os.path.join(bad_tab, "main.py"), "def setup(api):\n    pass\n")
write(os.path.join(bad_tab, "ui.html"), "<h1>x</h1>")
refused = result(plugins.install(bad_tab))
check("a screen that does not exist is refused", not refused.get("ok"), refused)
check("and the message lists the real ones", "servers" in refused.get("error", ""), refused)

print("\n== a tab needs something to open ==")
bad = os.path.join(scratch, "src", "tabnopanel")
write(os.path.join(bad, "plugin.json"), json.dumps({
    "id": "demo.tabnopanel", "name": "No Panel", "entry": "main.py",
    "tab": {"title": "Nowhere"},
}))
write(os.path.join(bad, "main.py"), "def setup(api):\n    pass\n")
refused = result(plugins.install(bad))
check("a tab without a panel is refused", not refused.get("ok"), refused)
check("and says why", "panel" in refused.get("error", ""), refused)

missing = os.path.join(scratch, "src", "tabnoicon")
write(os.path.join(missing, "plugin.json"), json.dumps({
    "id": "demo.tabnoicon", "name": "Missing Icon", "entry": "main.py",
    "panel": "ui.html", "tab": {"title": "Gone", "icon": "absent.png"},
}))
write(os.path.join(missing, "main.py"), "def setup(api):\n    pass\n")
write(os.path.join(missing, "ui.html"), "<h1>x</h1>")
refused = result(plugins.install(missing))
check("an icon that is not there is refused", not refused.get("ok"), refused)

loaded = result(plugins.load("demo.notes"))
check("the folder plugin loads", loaded.get("ok"), loaded)
check("a renamed export keeps its new name",
      "load_text" in loaded.get("exports", []), loaded)

result(plugins.call_export("demo.notes", "save", json.dumps({"text": "hello"})))
back = result(plugins.call_export("demo.notes", "load_text"))
check("its store round-trips", back.get("result") == "hello", back)

page = plugins.panel_html("demo.notes")
check("the panel gets the bridge", "window.pycmd" in page, page[:200])
check("the panel keeps its own markup", "<h1>Notes</h1>" in page, page[:200])
check("the panel gets the house style", "background: #0B0F14" in page, page[:200])

# ---------------------------------------------------------- shape 3: a zip

print("\n== a zipped plugin ==")
zip_path = os.path.join(scratch, "src", "clock.zip")
with zipfile.ZipFile(zip_path, "w") as archive:
    archive.writestr("clock/plugin.json", json.dumps({
        "id": "demo.clock", "name": "Clock", "entry": "main.py",
    }))
    archive.writestr("clock/main.py", "def setup(api):\n    api.log('tick')\n")

installed = result(plugins.install(zip_path))
check("a zip installs", installed.get("ok"), installed)
check("the wrapping folder is stripped",
      os.path.isfile(os.path.join(plugin_home, "demo.clock", "main.py")),
      os.listdir(os.path.join(plugin_home, "demo.clock")))

# ------------------------------------------------------------ misbehaviour

print("\n== plugins that misbehave ==")
broken = write(os.path.join(scratch, "src", "broken.py"), '''
PLUGIN = {"id": "demo.broken", "name": "Broken"}

raise RuntimeError("I explode on import")
''')
result(plugins.install(broken))
loaded = result(plugins.load("demo.broken"))
check("an exploding plugin does not take the app down", not loaded.get("ok"), loaded)
check("the failure names the plugin", "Broken" in loaded.get("error", ""), loaded)
check("and the traceback is kept", "I explode on import" in loaded.get("error", ""), loaded)

throwing = write(os.path.join(scratch, "src", "throwing.py"), '''
PLUGIN = {"id": "demo.throwing", "name": "Throwing"}


def setup(api):
    @api.export
    def boom(payload=None):
        raise ValueError("no")

    @api.on("run_finished")
    def handler(event):
        raise KeyError("also no")
''')
result(plugins.install(throwing))
result(plugins.load("demo.throwing"))
called = result(plugins.call_export("demo.throwing", "boom"))
check("an export that raises is reported", not called.get("ok"), called)
check("with the real message", "no" in called.get("error", ""), called)

fired = result(plugins.fire("run_finished", "{}"))
check("a listener that raises does not stop the event", fired.get("ok"), fired)

no_manifest = os.path.join(scratch, "src", "empty")
os.makedirs(no_manifest, exist_ok=True)
write(os.path.join(no_manifest, "readme.txt"), "nothing here")
installed = result(plugins.install(no_manifest))
check("a folder with no python is refused", not installed.get("ok"), installed)
check("and says what a plugin needs", "PLUGINS.md" in installed.get("error", ""), installed)

bad_json = os.path.join(scratch, "src", "badjson")
write(os.path.join(bad_json, "plugin.json"), "{not json")
write(os.path.join(bad_json, "main.py"), "def setup(api):\n    pass\n")
installed = result(plugins.install(bad_json))
check("a broken manifest is refused", not installed.get("ok"), installed)
check("and points at the JSON", "JSON" in installed.get("error", ""), installed)

missing_entry = os.path.join(scratch, "src", "noentry")
write(os.path.join(missing_entry, "plugin.json"), json.dumps({
    "id": "demo.noentry", "name": "No Entry", "entry": "somewhere.py",
}))
write(os.path.join(missing_entry, "main.py"), "def setup(api):\n    pass\n")
installed = result(plugins.install(missing_entry))
check("a missing entry file is refused", not installed.get("ok"), installed)

escaping = os.path.join(scratch, "src", "escape.zip")
with zipfile.ZipFile(escaping, "w") as archive:
    archive.writestr("plugin.json", json.dumps({"id": "demo.escape", "name": "Escape",
                                                "entry": "main.py"}))
    archive.writestr("main.py", "def setup(api):\n    pass\n")
    archive.writestr("../../../outside.txt", "should never be written")
installed = result(plugins.install(escaping))
check("a zip that writes outside itself is refused", not installed.get("ok"), installed)
check("nothing escaped", not os.path.exists(os.path.join(scratch, "outside.txt")),
      os.listdir(scratch))

# --------------------------------------------------------- the plugin's API

print("\n== the API a plugin is given ==")
api_test = write(os.path.join(scratch, "src", "apitest.py"), '''
PLUGIN = {"id": "demo.api", "name": "Api Test"}

SEEN = {}


def setup(api):
    SEEN["workspace"] = api.workspace_path()
    api.write("from_plugin.txt", "written by a plugin")
    SEEN["read_back"] = api.read("from_plugin.txt")
    SEEN["missing"] = api.read("nope.txt", "fallback")
    SEEN["files"] = len(api.files("*.txt"))
    api.toast("hello from a plugin")

    @api.export
    def seen(payload=None):
        return SEEN
''')
result(plugins.install(api_test))
result(plugins.load("demo.api"))
seen = result(plugins.call_export("demo.api", "seen")).get("result", {})
check("workspace_path points at the workspace", seen.get("workspace") == workspace, seen)
check("write then read round-trips", seen.get("read_back") == "written by a plugin", seen)
check("a missing read returns the fallback", seen.get("missing") == "fallback", seen)
check("files() finds what was written", seen.get("files") == 1, seen)
check("toast reaches the host", "hello from a plugin" in host.toasts, host.toasts)
check("the file really is in the workspace",
      os.path.isfile(os.path.join(workspace, "from_plugin.txt")), os.listdir(workspace))

# ------------------------------------------------------- loading in batches

print("\n== enabling and disabling ==")
check("an empty string asks for nothing", result(plugins.load_all(""))["ok"],
      plugins.load_all(""))
check("None asks for nothing", result(plugins.load_all(None))["ok"], plugins.load_all(None))
check("a comma-separated string works like a list",
      {r["id"] for r in result(plugins.load_all("demo.wordcount,demo.notes"))["results"]}
      == {"demo.wordcount", "demo.notes"},
      plugins.load_all("demo.wordcount,demo.notes"))

outcome = result(plugins.load_all(["demo.wordcount", "demo.notes"]))
ok_ids = {r["id"] for r in outcome["results"] if r.get("ok")}
check("load_all loads what was asked for", ok_ids == {"demo.wordcount", "demo.notes"}, outcome)

listed = result(plugins.listing())
states = {p["id"]: p.get("loaded") for p in listed["plugins"]}
check("the others were unloaded", states.get("demo.api") is False, states)
check("and the wanted ones are loaded", states.get("demo.notes") is True, states)

ran = result(plugins.run_command("wc", "still here"))
check("a reloaded plugin still answers", ran.get("handled"), ran)

removed = result(plugins.remove("demo.clock"))
check("a plugin can be removed", removed.get("ok"), removed)
listed = result(plugins.listing())
check("and is gone from the listing",
      "demo.clock" not in {p["id"] for p in listed["plugins"]}, listed)

# ---------------------------------------------------------------- reporting

print("\n== the listing ==")
listed = result(plugins.listing())
by_id = {p["id"]: p for p in listed["plugins"]}
check("a broken plugin is still listed", "demo.broken" in by_id, list(by_id))
check("with its load error attached", by_id["demo.broken"].get("error"), by_id["demo.broken"])
check("sizes are reported", by_id["demo.notes"]["size"] > 0, by_id["demo.notes"])
check("file lists are reported", "ui.html" in by_id["demo.notes"]["files"],
      by_id["demo.notes"])

shutil.rmtree(scratch, ignore_errors=True)

total = 0
print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
    raise SystemExit(1)
print("all plugin checks passed")
