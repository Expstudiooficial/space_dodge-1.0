"""Checks the plugins that ship inside the APK.

These are installed for every user on first run, so a mistake in one of them is
a mistake everybody gets. The checks here are the ones that would otherwise be
found on a phone: that each manifest is valid, that each panel renders, that
the commands they promise are the commands they register, and that the sections
they add name screens the app actually has.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))
ASSETS = os.path.join(ROOT, "app", "src", "main", "assets", "plugins")

import pycmd_cloud  # noqa: E402
import pycmd_plugins as plugins  # noqa: E402
import pycmd_runtime  # noqa: E402
import pycmd_servers  # noqa: E402

FAILURES = []
REAL = sys.__stdout__


def say(text=""):
    REAL.write(str(text) + "\n")
    REAL.flush()


def check(name, condition, detail=""):
    if condition:
        say(f"  PASS  {name}")
    else:
        say(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


class Sink:
    def onOutput(self, stream, text, channel):  # noqa: N802
        pass

    def onReadLine(self, channel):  # noqa: N802
        return None

    def onFinished(self, run_id, status, millis):  # noqa: N802
        pass


class Host:
    def __init__(self):
        self.logs = []

    def onPluginLog(self, level, message, detail):  # noqa: N802
        self.logs.append((level, message, detail))

    def onToast(self, message):  # noqa: N802
        pass

    def onPluginMessage(self, plugin_id, body):  # noqa: N802
        pass


workspace = tempfile.mkdtemp(prefix="pycmd-bundled-ws-")
pycmd_runtime.configure(Sink(), workspace, tempfile.mkdtemp())
pycmd_cloud.configure_storage(tempfile.mkdtemp())
host = Host()
plugins.configure(tempfile.mkdtemp(prefix="pycmd-bundled-"), workspace, host)


def result(raw):
    return json.loads(raw)


say("\n== every bundled plugin installs ==")
names = sorted(n for n in os.listdir(ASSETS) if os.path.isdir(os.path.join(ASSETS, n)))
check("there are some to check", len(names) >= 3, names)

installed = {}
for name in names:
    reply = result(plugins.install(os.path.join(ASSETS, name), name, "1"))
    check(f"{name} installs", reply.get("ok"), reply.get("error"))
    if reply.get("ok"):
        installed[reply["manifest"]["id"]] = reply["manifest"]

check("and every one is marked as ours, not the user's",
      all(m.get("bundled") for m in installed.values()),
      {i: m.get("bundled") for i, m in installed.items()})

say("\n== what they promise is what they register ==")
loaded = result(plugins.load_all(",".join(installed)))
check("all of them load", all(row["ok"] for row in loaded["results"]),
      [(r.get("id"), r.get("error")) for r in loaded["results"] if not r["ok"]])

for row in loaded["results"]:
    manifest = installed[row["id"]]
    promised = {c["name"] for c in manifest.get("commands", [])}
    registered = set(row["commands"])
    check(f"{row['id']} registers everything it lists",
          promised <= registered, promised - registered)
    check(f"{row['id']} lists everything it registers",
          registered <= promised, registered - promised)

listed = result(plugins.commands())["commands"]
check("no two of them fight over a command",
      not any(row["shadowed"] for row in listed),
      [row["name"] for row in listed if row["shadowed"]])

say("\n== their panels render ==")
for plugin_id, manifest in installed.items():
    pages = {manifest.get("panel", "")}
    pages |= {section["panel"] for section in manifest.get("extends", [])}
    for page_name in sorted(p for p in pages if p):
        page = plugins.panel_html(plugin_id, page_name)
        check(f"{plugin_id}/{page_name} renders",
              "<html" in page.lower() and "__pycmd_panel" in page, page[:120])

say("\n== the screens they extend exist ==")
for plugin_id, manifest in installed.items():
    for section in manifest.get("extends", []):
        check(f"{plugin_id} extends a real screen",
              section["tab"] in plugins.EXTENDABLE_TABS, section)
        if section.get("image"):
            check(f"{plugin_id}'s section icon is where it says",
                  os.path.isfile(section["image"]), section["image"])
    tab = manifest.get("tab")
    if tab and tab.get("image"):
        check(f"{plugin_id}'s tab icon is where it says",
              os.path.isfile(tab["image"]), tab["image"])

say("\n== Server Pro drives real servers ==")
folder = os.path.join(workspace, "site")
os.makedirs(folder, exist_ok=True)
with open(os.path.join(folder, "home.html"), "w", encoding="utf-8") as handle:
    handle.write("<h1>hi</h1>")

port = pycmd_servers.suggest_port(8400)
started = pycmd_servers.start_static(folder, port=port, label="test")
check("a server starts", started.get("ok"), started)
time.sleep(0.4)

board = result(plugins.call_export("pycmd.server-pro", "board_now", "{}"))["result"]
check("the board sees it", board["running"] >= 1, board)
row = next((r for r in board["servers"] if r["handle"] == started["handle"]), None)
check("and knows the port answers", row and row["health"] == "answering", row)

restarted = result(plugins.call_export(
    "pycmd.server-pro", "restart_one", json.dumps({"handle": started["handle"]}),
))["result"]
check("restart brings it back", restarted.get("ok"), restarted)
check("on the same port", restarted.get("port") == port, restarted)

written = result(plugins.call_export(
    "pycmd.server-pro", "write_index", json.dumps({"folder": folder}),
))["result"]
check("it writes an index for a folder with none", written.get("ok"), written)
check("listing what is there", written.get("files") == 1, written)
with open(os.path.join(folder, "index.html"), encoding="utf-8") as handle:
    page = handle.read()
check("and the page links to it", 'href="home.html"' in page, page[:200])

again = result(plugins.call_export(
    "pycmd.server-pro", "write_index", json.dumps({"folder": folder}),
))["result"]
check("but never overwrites one that exists", not again.get("ok"), again)
pycmd_servers.kill_all()
time.sleep(0.3)

say("\n== Scheduler runs a script again ==")
script = os.path.join(workspace, "tick.py")
with open(script, "w", encoding="utf-8") as handle:
    handle.write("open(__file__ + '.count', 'a').write('x')\n")

job = result(plugins.call_export(
    "pycmd.scheduler", "add", json.dumps({"path": "tick.py", "seconds": 5}),
))["result"]
check("a job is scheduled", job.get("ok"), job)
deadline = time.time() + 5
while time.time() < deadline and not os.path.exists(script + ".count"):
    time.sleep(0.05)
check("and it runs straight away", os.path.exists(script + ".count"))
listing = result(plugins.call_export("pycmd.scheduler", "jobs", "{}"))["result"]
check("the list shows it", len(listing["jobs"]) == 1, listing)
stopped = result(plugins.call_export("pycmd.scheduler", "remove_all", "{}"))["result"]
check("and stopping clears it", stopped["stopped"] == 1, stopped)

missing = result(plugins.call_export(
    "pycmd.scheduler", "add", json.dumps({"path": "nope.py", "seconds": 5}),
))["result"]
check("a script that is not there is refused", not missing.get("ok"), missing)

say("\n== Cloud says what it needs ==")
state = result(plugins.call_export("pycmd.cloud", "state", "{}"))["result"]
check("it reports nothing connected yet",
      state["supabase"]["configured"] is False, state)
saved = result(plugins.call_export("pycmd.cloud", "save_supabase", json.dumps({
    "url": "https://example.supabase.co", "key": "anon",
})))["result"]
check("saving a project is remembered", saved["supabase"]["configured"], saved)
check("and the key is never handed back whole",
      "anon" not in json.dumps(saved), saved)
failed = result(plugins.call_export("pycmd.cloud", "run_query", json.dumps({
    "provider": "supabase", "name": "",
})))["result"]
check("an empty table name is refused, not sent", not failed.get("ok"), failed)
pycmd_cloud.forget()

say()
if FAILURES:
    say(f"{len(FAILURES)} bundled-plugin checks failed")
    sys.exit(1)
say("all bundled plugin checks passed")
