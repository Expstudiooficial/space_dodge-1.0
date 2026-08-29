"""Host-side tests for the modules that run inside the app.

The Kotlin layer talks to pycmd_runtime, pycmd_packages and pycmd_servers
through a small object contract, so a stand-in for that object is all these
need to run on a desktop CPython of the same minor version.

    python3.13 tools/test_runtime.py

Some checks reach PyPI, so the network has to be up.
"""

import os
import queue
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import pycmd_packages  # noqa: E402
import pycmd_runtime  # noqa: E402
import pycmd_servers  # noqa: E402

FAILURES = []


class FakeSink:
    """Stands in for the Kotlin sink, including its per-channel routing."""

    def __init__(self):
        self.chunks = []  # (stream, text, channel)
        self.queues = {}
        self.finished = []

    def queue_for(self, channel):
        return self.queues.setdefault(channel, queue.Queue())

    def onOutput(self, stream, text, channel="console"):  # noqa: N802
        self.chunks.append((stream, text, channel))

    def onReadLine(self, channel="console"):  # noqa: N802
        try:
            return self.queue_for(channel).get(timeout=2)
        except queue.Empty:
            return None

    def onFinished(self, run_id, status, millis):  # noqa: N802
        self.finished.append((run_id, status, millis))

    def text(self, stream=None, channel="console"):
        return "".join(
            t for s, t, c in self.chunks
            if (stream is None or s == stream) and (channel is None or c == channel)
        )

    def reset(self):
        self.chunks.clear()
        self.finished.clear()

    @property
    def stdin(self):
        return self.queue_for("console")


def _report_uncaught(exc_type, exc, tb):
    """The engine owns sys.stderr, so an unexpected crash needs a way out."""
    import traceback

    out = globals().get("real_stdout") or sys.__stdout__
    print("\nUNCAUGHT ERROR in the test script:", file=out)
    traceback.print_exception(exc_type, exc, tb, file=out)


sys.excepthook = _report_uncaught


def check(name, condition, detail=""):
    # sys.stdout belongs to the engine under test, so results go to the real one.
    out = globals().get("real_stdout") or sys.__stdout__
    if condition:
        print(f"  PASS  {name}", file=out)
    else:
        print(f"  FAIL  {name}  {detail}", file=out)
        FAILURES.append(name)


sink = FakeSink()
workspace = os.path.join(ROOT, "build", "test-workspace")
site_packages = os.path.join(ROOT, "build", "test-site-packages")
os.makedirs(workspace, exist_ok=True)
os.makedirs(site_packages, exist_ok=True)

real_stdout = sys.stdout
version = pycmd_runtime.configure(sink, workspace, site_packages)


def report(message):
    print(message, file=real_stdout)


report("\n== runtime: basics ==")
sink.reset()
status = pycmd_runtime.run_source("print('hello')")
check("print reaches stdout", sink.text("stdout") == "hello\n", repr(sink.text()))
check("status is ok", status == "ok", status)
check("onFinished fired", len(sink.finished) == 1, sink.finished)

report("\n== runtime: expression echo ==")
sink.reset()
pycmd_runtime.run_source("2 + 3")
check("last expression is echoed", sink.text("stdout") == "5\n", repr(sink.text()))

sink.reset()
pycmd_runtime.run_source("x = 41\nx + 1")
check("body runs before the echo", sink.text("stdout") == "42\n", repr(sink.text()))

sink.reset()
pycmd_runtime.run_source("None")
check("None is not echoed", sink.text("stdout") == "", repr(sink.text()))

sink.reset()
pycmd_runtime.run_source("print('a')", echo_result=False)
check("echo_result=False suppresses only the repr", sink.text("stdout") == "a\n", repr(sink.text()))

report("\n== runtime: state persists between runs ==")
sink.reset()
pycmd_runtime.run_source("counter = 7")
pycmd_runtime.run_source("counter * 2")
check("namespace survives", sink.text("stdout") == "14\n", repr(sink.text()))

sink.reset()
pycmd_runtime.reset_namespace()
pycmd_runtime.run_source("counter")
check("reset clears the namespace", "NameError" in sink.text("stderr"), repr(sink.text()))

report("\n== runtime: errors ==")
sink.reset()
status = pycmd_runtime.run_source("1/0")
check("ZeroDivisionError is reported", "ZeroDivisionError" in sink.text("stderr"), sink.text())
check("status is error", status == "error", status)
check("engine frames are hidden", "pycmd_runtime.py" not in sink.text("stderr"), sink.text("stderr"))

sink.reset()
status = pycmd_runtime.run_source("def broken(:\n    pass")
check("SyntaxError is reported", "SyntaxError" in sink.text("stderr"), sink.text())
check("syntax error status", status == "error", status)

sink.reset()
pycmd_runtime.run_source("raise ValueError('boom')", source_name="demo.py")
check("source name appears in the traceback", "demo.py" in sink.text("stderr"), sink.text("stderr"))

report("\n== runtime: SystemExit ==")
sink.reset()
status = pycmd_runtime.run_source("import sys; sys.exit(0)")
check("clean exit is ok", status == "ok", status)
sink.reset()
status = pycmd_runtime.run_source("import sys; sys.exit(3)")
check("non-zero exit is an error", status == "error", status)

report("\n== runtime: stdin ==")
sink.reset()
sink.stdin.put("Ada\n")
pycmd_runtime.run_source("name = input('Name? ')\nprint('hi', name)")
check("input() reads a queued line", "hi Ada" in sink.text("stdout"), repr(sink.text()))

sink.reset()
sink.stdin.put("1\n")
sink.stdin.put("2\n")
pycmd_runtime.run_source("a = input()\nb = input()\nprint(int(a) + int(b))")
check("two reads work", "3" in sink.text("stdout"), repr(sink.text()))

report("\n== runtime: stop ==")
sink.reset()
result = {}


def run_forever():
    result["status"] = pycmd_runtime.run_source("while True:\n    pass")


worker = threading.Thread(target=run_forever, daemon=True)
worker.start()
time.sleep(0.4)
pycmd_runtime.request_stop()
worker.join(timeout=5)
check("infinite loop is interruptible", not worker.is_alive(), "thread still running")
check("stop status", result.get("status") == "stopped", result)
check("KeyboardInterrupt is reported", "KeyboardInterrupt" in sink.text("stderr"), sink.text("stderr"))

report("\n== runtime: stop while waiting for input ==")
sink.reset()
blocked = {}


def run_blocked():
    # The sink returns None after 2s, which the engine treats as a stop.
    blocked["status"] = pycmd_runtime.run_source("value = input('waiting? ')\nprint(value)")


worker = threading.Thread(target=run_blocked, daemon=True)
worker.start()
time.sleep(0.3)
pycmd_runtime.request_stop()
worker.join(timeout=6)
check("blocked input() returns", not worker.is_alive(), "thread still blocked")
check("stop during input reads as stopped", blocked.get("status") == "stopped", blocked)
check("no EOFError leaks out", "EOFError" not in sink.text("stderr"), sink.text("stderr"))

report("\n== runtime: trace-hook fallback ==")
# Force the slow path to prove the fallback still interrupts a runaway loop.
saved_flag = pycmd_runtime._use_async_exc
pycmd_runtime._use_async_exc = False
try:
    sink.reset()
    fallback = {}

    def run_fallback():
        fallback["status"] = pycmd_runtime.run_source("while True:\n    pass")

    worker = threading.Thread(target=run_fallback, daemon=True)
    worker.start()
    time.sleep(0.4)
    pycmd_runtime.request_stop()
    worker.join(timeout=6)
    check("fallback interrupts the loop", not worker.is_alive(), "thread still running")
    check("fallback reports stopped", fallback.get("status") == "stopped", fallback)
finally:
    pycmd_runtime._use_async_exc = saved_flag

sink.reset()
pycmd_runtime.run_source("print('back on the fast path')")
check(
    "engine works again after the fallback run",
    "back on the fast path" in sink.text("stdout"),
    repr(sink.text()),
)

report("\n== runtime: interrupt mechanism ==")
check(
    "a mechanism was selected",
    pycmd_runtime.runtime_info()["interrupt"] in ("async-exc", "trace-hook"),
    pycmd_runtime.runtime_info().get("interrupt"),
)

report("\n== runtime: run after stop ==")
sink.reset()
status = pycmd_runtime.run_source("print('still alive')")
check("engine recovers after a stop", sink.text("stdout") == "still alive\n", repr(sink.text()))

report("\n== runtime: run_file ==")
script = os.path.join(workspace, "sample.py")
with open(script, "w", encoding="utf-8") as handle:
    handle.write("import sys\nprint('file says', __name__)\nprint('argv0', sys.argv[0])\n")
sink.reset()
status = pycmd_runtime.run_file(script)
check("run_file executes as __main__", "file says __main__" in sink.text("stdout"), sink.text())
check("run_file sets argv", "argv0" in sink.text("stdout"), sink.text())
check("run_file status", status == "ok", status)

sink.reset()
status = pycmd_runtime.run_file(os.path.join(workspace, "missing.py"))
check("missing file is an error", status == "error", status)
check("missing file explains itself", "cannot open" in sink.text("stderr"), sink.text("stderr"))

report("\n== runtime: completions ==")
pycmd_runtime.reset_namespace()
pycmd_runtime.run_source("import os\nmy_variable = 1")
names = pycmd_runtime.completions("my_")
check("completes user names", "my_variable" in names, names)
names = pycmd_runtime.completions("pri")
check("completes builtins", "print" in names, names)
names = pycmd_runtime.completions("os.pa")
check("completes attributes", any(n.startswith("os.path") for n in names), names)
check("empty prefix returns nothing", pycmd_runtime.completions("") == [], "non-empty")
check("garbage prefix does not raise", pycmd_runtime.completions("!!!.x") == [], "raised or returned")

report("\n== runtime: info ==")
info = pycmd_runtime.runtime_info()
check("version reported", info["version"].startswith("3."), info.get("version"))
check("cwd reported", os.path.isdir(info["cwd"]), info.get("cwd"))

report("\n== runtime: unprintable repr ==")
sink.reset()
pycmd_runtime.run_source(
    "class Bad:\n"
    "    def __repr__(self):\n"
    "        raise RuntimeError('nope')\n"
    "Bad()"
)
check("bad repr does not kill the run", "unprintable" in sink.text("stdout"), repr(sink.text()))

report("\n== packages ==")
pycmd_packages.configure(site_packages)
check("installed() starts empty", pycmd_packages.installed() == [], pycmd_packages.installed())

result = pycmd_packages.install("")
check("empty name is rejected", result["ok"] is False, result)

result = pycmd_packages.uninstall("never-installed")
check("unknown uninstall is rejected", result["ok"] is False, result)


class ProgressCollector:
    def __init__(self):
        self.messages = []

    def onProgress(self, message):  # noqa: N802
        self.messages.append(message)


progress = ProgressCollector()
result = pycmd_packages.install("tabulate", progress=progress)
check("pure-python install succeeds", result.get("ok") is True, result)
check("progress was reported", len(progress.messages) >= 2, progress.messages)
if result.get("ok"):
    rows = pycmd_packages.installed()
    check("manifest lists the package", any(r["name"].lower() == "tabulate" for r in rows), rows)
    sink.reset()
    pycmd_runtime.run_source("import tabulate; print('tabulate', tabulate.__name__)")
    check("installed package imports", "tabulate" in sink.text("stdout"), sink.text())

    removed = pycmd_packages.uninstall("tabulate")
    check("uninstall succeeds", removed["ok"] is True, removed)
    check("manifest is emptied", pycmd_packages.installed() == [], pycmd_packages.installed())
    check(
        "files are gone",
        not os.path.exists(os.path.join(site_packages, "tabulate")),
        os.listdir(site_packages),
    )

result = pycmd_packages.install("numpy")
check(
    "native-only package is refused with an explanation",
    result["ok"] is False and "universal wheel" in result.get("error", ""),
    result,
)

report("\n== servers: helpers ==")
ip = pycmd_servers.local_ip()
check("local_ip returns something", isinstance(ip, str) and ip.count(".") == 3, ip)
check("suggest_port finds a free port", pycmd_servers.suggest_port(8300) >= 8300, "none")
check("port 0 is rejected", pycmd_servers.port_available(0) is False, "accepted")
check("port 99999 is rejected", pycmd_servers.port_available(99999) is False, "accepted")

report("\n== servers: static ==")
started = pycmd_servers.start_static(workspace, 8123, label="test folder")
check("static server starts", started.get("ok") is True, started)
handle = started.get("handle", "")

if started.get("ok"):
    time.sleep(0.5)
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:8123/sample.py", timeout=5) as response:
            body = response.read().decode()
        check("static server serves the workspace", "file says" in body, body[:60])
    except Exception as exc:  # noqa: BLE001
        check("static server serves the workspace", False, repr(exc))

    rows = pycmd_servers.listing()
    check("listing shows it running", len(rows) == 1 and rows[0]["status"] == "running", rows)
    check("listing carries a url", rows[0]["url"].startswith("http://"), rows[0])
    check("listing carries the target", rows[0]["target"] == workspace, rows[0])
    check("label is used", rows[0]["label"] == "test folder", rows[0])
    check("count is 1", pycmd_servers.count() == 1, pycmd_servers.count())
    check("requests were counted", rows[0]["requests"] >= 1, rows[0])

    check(
        "output went to the server channel",
        "Serving" in sink.text(channel=handle),
        sink.text(channel=handle)[:120],
    )
    check(
        "server output stayed out of the console",
        "Serving" not in sink.text(channel="console"),
        sink.text(channel="console")[-120:],
    )

    logged = pycmd_servers.log_lines(handle)
    check("log_lines replays the server log", any("Serving" in r["text"] for r in logged), logged[:2])

    duplicate = pycmd_servers.start_static(workspace, 8123)
    check("port clash is refused", duplicate.get("ok") is False, duplicate)
    check("clash message suggests another port", "in use" in duplicate.get("error", ""), duplicate)

    stopped = pycmd_servers.stop(handle)
    check("graceful stop works", stopped.get("ok") is True, stopped)
    time.sleep(0.3)
    check("count returns to 0", pycmd_servers.count() == 0, pycmd_servers.count())

    again = pycmd_servers.start_static(workspace, 8123)
    check("port is reusable after a stop", again.get("ok") is True, again)
    if again.get("ok"):
        pycmd_servers.kill(again["handle"])

report("\n== servers: validation ==")
check(
    "missing folder is refused",
    pycmd_servers.start_static(os.path.join(workspace, "nope"), 8124).get("ok") is False,
    "accepted",
)
check(
    "privileged port is refused with a reason",
    "reserved" in pycmd_servers.start_static(workspace, 80).get("error", ""),
    pycmd_servers.start_static(workspace, 80),
)
check(
    "missing script is refused",
    pycmd_servers.start_script(os.path.join(workspace, "nope.py")).get("ok") is False,
    "accepted",
)
check("stop of an unknown handle is refused", pycmd_servers.stop("srv999")["ok"] is False, "accepted")
check("kill of an unknown handle is refused", pycmd_servers.kill("srv999")["ok"] is False, "accepted")

report("\n== servers: script ==")
script_server = os.path.join(workspace, "server_script.py")
with open(script_server, "w", encoding="utf-8") as handle_file:
    handle_file.write(
        "import time\n"
        "print('script server up')\n"
        "while True:\n"
        "    time.sleep(0.05)\n"
    )
started = pycmd_servers.start_script(script_server, label="looping script")
check("script server starts", started.get("ok") is True, started)
script_handle = started.get("handle", "")
time.sleep(0.6)
check(
    "script output went to its own channel",
    "script server up" in sink.text(channel=script_handle),
    sink.text(channel=script_handle)[:120],
)
rows = pycmd_servers.listing()
check("script server is listed as running", any(r["status"] == "running" for r in rows), rows)

report("\n== servers: the kill switch ==")
killed = pycmd_servers.kill(script_handle)
check("kill reports success", killed.get("ok") is True, killed)
time.sleep(0.5)
check("killed script is gone from the listing", pycmd_servers.listing() == [], pycmd_servers.listing())
check("count is 0 after the kill", pycmd_servers.count() == 0, pycmd_servers.count())

report("\n== servers: kill a server that ignores a stop ==")
stubborn = os.path.join(workspace, "stubborn.py")
with open(stubborn, "w", encoding="utf-8") as handle_file:
    # Swallows KeyboardInterrupt, so only a kill (SystemExit) can end it.
    handle_file.write(
        "import time\n"
        "print('stubborn up')\n"
        "while True:\n"
        "    try:\n"
        "        time.sleep(0.05)\n"
        "    except KeyboardInterrupt:\n"
        "        pass\n"
    )
started = pycmd_servers.start_script(stubborn, label="stubborn")
stubborn_handle = started.get("handle", "")
time.sleep(0.6)
result = pycmd_servers.stop(stubborn_handle, timeout=1.0)
check("a stop that fails says so", result.get("ok") is False, result)
check("and asks for a kill", result.get("needs_kill") is True, result)
killed = pycmd_servers.kill(stubborn_handle)
check("kill stops the stubborn script", killed.get("ok") is True, killed)
time.sleep(0.4)
check("stubborn server is untracked", pycmd_servers.count() == 0, pycmd_servers.listing())

report("\n== servers: kill a script wedged in its own accept() ==")
listener = os.path.join(workspace, "listener.py")
with open(listener, "w", encoding="utf-8") as handle_file:
    # accept() is a blocking C call. An async exception cannot land inside one,
    # so the only way out is to make the call return - which is what kill does
    # by connecting to the port before raising again.
    handle_file.write(
        "import socket\n"
        "s = socket.socket()\n"
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "s.bind(('0.0.0.0', 8151))\n"
        "s.listen(1)\n"
        "print('listening')\n"
        "while True:\n"
        "    conn, _ = s.accept()\n"
        "    conn.close()\n"
    )
started = pycmd_servers.start_file(listener, port=8151, label="listener")
check("the listener starts", started.get("ok") is True, started)
time.sleep(1.0)
check("and holds the port", not pycmd_servers.port_available(8151, "127.0.0.1"))
killed = pycmd_servers.kill(started["handle"])
check("kill ends it rather than detaching", killed.get("detached") is False, killed)
time.sleep(0.4)
check("and the port comes back", pycmd_servers.port_available(8151, "127.0.0.1"))

report("\n== servers: kill_all ==")
pycmd_servers.start_static(workspace, 8131)
pycmd_servers.start_static(workspace, 8132)
time.sleep(0.4)
check("two servers are running", pycmd_servers.count() == 2, pycmd_servers.count())
result = pycmd_servers.kill_all()
check("kill_all reports both", result.get("killed") == 2, result)
time.sleep(0.4)
check("nothing is left running", pycmd_servers.count() == 0, pycmd_servers.listing())
check("ports were freed", pycmd_servers.port_available(8131), "8131 still bound")

report("\n== servers: running things that are not Python ==")
plan = pycmd_servers.how_to_run(os.path.join(workspace, "hello.py"))
check("a script says it is a script", plan["how"] == "script", plan)

go_file = os.path.join(workspace, "server.go")
with open(go_file, "w", encoding="utf-8") as handle_file:
    handle_file.write(
        'package main\n\nimport "fmt"\n\n'
        'func main() {\n\tfmt.Println("go server up")\n}\n'
    )
plan = pycmd_servers.how_to_run(go_file)
check("a Go file says which interpreter", plan["how"] == "language" and plan["language"] == "Go", plan)
started = pycmd_servers.start_file(go_file, label="go")
check("and it starts", started.get("ok") is True, started)
time.sleep(0.8)
check("its output lands in its own log",
      any("go server up" in text for _stream, text in
          [(row["stream"], row["text"]) for row in pycmd_servers.log_lines(started["handle"])]),
      pycmd_servers.log_lines(started["handle"]))
pycmd_servers.kill_all()

page_dir = os.path.join(workspace, "pages")
os.makedirs(page_dir, exist_ok=True)
page = os.path.join(page_dir, "home.html")
with open(page, "w", encoding="utf-8") as handle_file:
    handle_file.write("<h1>hi</h1>")
plan = pycmd_servers.how_to_run(page)
check("a page is served, not executed", plan["how"] == "serve", plan)
served = pycmd_servers.start_file(page, port=8141)
check("serving it works", served.get("ok") is True, served)
check("and the address opens that page", served.get("url", "").endswith("/home.html"), served)
time.sleep(0.3)
import urllib.request  # noqa: E402

fetched = urllib.request.urlopen(f"http://127.0.0.1:8141/home.html", timeout=3).read()
check("the page really is served", b"<h1>hi</h1>" in fetched, fetched)
pycmd_servers.kill_all()
time.sleep(0.3)

java_file = os.path.join(workspace, "A.java")
with open(java_file, "w", encoding="utf-8") as handle_file:
    handle_file.write("class A {}\n")
refused = pycmd_servers.start_file(java_file)
check("something with no engine is refused up front", refused.get("ok") is False, refused)
check("with the reason, not a stack trace", "compiler" in refused.get("error", ""), refused)

report("\n== servers: a folder is a project, not a pile of files ==")

# The bug this covers: pointing Run at a Flask project served static/ and
# templates/ as a directory listing, because "folder" meant "file server" and
# nothing looked inside.
project = os.path.join(workspace, "site")
os.makedirs(os.path.join(project, "templates"), exist_ok=True)
os.makedirs(os.path.join(project, "static"), exist_ok=True)
with open(os.path.join(project, "templates", "index.html"), "w", encoding="utf-8") as handle_file:
    handle_file.write("<h1>{{ title }}</h1>")
with open(os.path.join(project, "static", "app.css"), "w", encoding="utf-8") as handle_file:
    handle_file.write("body { margin: 0 }\n")

inside = pycmd_servers.folder_plan(project)
check("a templates-only folder is still served", inside["how"] == "serve", inside)
check("but it says why there is nothing to run", "Flask" in inside["hint"], inside)

with open(os.path.join(project, "app.py"), "w", encoding="utf-8") as handle_file:
    handle_file.write(
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "\n"
        "@app.route('/')\n"
        "def home():\n"
        "    return 'hello'\n"
    )
planned = pycmd_servers.folder_plan(project)
check("app.py is the front door", planned["how"] == "script", planned)
check("and it is named", planned["entry"] == "app.py", planned)
check("and the framework is named too", "flask" in planned["note"], planned)
check(
    "how_to_run says the same about the folder",
    pycmd_servers.how_to_run(project)["entry"] == "app.py",
    pycmd_servers.how_to_run(project),
)

# A page wins when there is no server script beside it.
plain = os.path.join(workspace, "plainsite")
os.makedirs(plain, exist_ok=True)
with open(os.path.join(plain, "index.html"), "w", encoding="utf-8") as handle_file:
    handle_file.write("<h1>a real page</h1>")
with open(os.path.join(plain, "build.py"), "w", encoding="utf-8") as handle_file:
    handle_file.write("print('built')\n")
page_plan = pycmd_servers.folder_plan(plain)
check("index.html beats a helper script", page_plan["entry"] == "index.html", page_plan)
check("and it is served, not executed", page_plan["how"] == "serve", page_plan)

# One runnable file and no ceremony: that is the one you meant.
single = os.path.join(workspace, "onefile")
os.makedirs(single, exist_ok=True)
with open(os.path.join(single, "worker.py"), "w", encoding="utf-8") as handle_file:
    handle_file.write("print('worked')\n")
only = pycmd_servers.folder_plan(single)
check("the only runnable file is the plan", only["entry"] == "worker.py", only)

many = os.path.join(workspace, "manyfiles")
os.makedirs(many, exist_ok=True)
for name in ("one.py", "two.py", "three.py"):
    with open(os.path.join(many, name), "w", encoding="utf-8") as handle_file:
        handle_file.write("print('x')\n")
crowd = pycmd_servers.folder_plan(many)
check("several candidates and no front door means serve", crowd["how"] == "serve", crowd)
check("and the hint names them", "one.py" in crowd["hint"], crowd)

# Running the folder runs the entry point, rather than listing it.
ran = pycmd_servers.start_file(single, port=8151, label="folder run")
check("running a folder starts its entry point", ran.get("ok") is True, ran)
time.sleep(0.8)
check(
    "and the entry point really ran",
    any("worked" in row["text"] for row in pycmd_servers.log_lines(ran.get("handle", ""))),
    pycmd_servers.log_lines(ran.get("handle", "")),
)
pycmd_servers.kill_all()
time.sleep(0.3)

# Serving the folder that has nothing to run gives a listing worth reading.
listed = pycmd_servers.start_file(project, port=8152)
check("a project with an app.py runs instead of serving", listed.get("kind") == "script", listed)
pycmd_servers.kill_all()
time.sleep(0.3)

os.remove(os.path.join(project, "app.py"))
listed = pycmd_servers.start_file(project, port=8153)
check("with the app.py gone it serves again", listed.get("ok") is True, listed)
time.sleep(0.4)
page = urllib.request.urlopen("http://127.0.0.1:8153/", timeout=3).read().decode()
check("the listing is a real page", "<!doctype html>" in page.lower(), page[:80])
check("it lists the folders", "templates/" in page, page[:200])
check("it says why it is a listing", "Why you are looking at a list" in page, page[:400])
check("and links are usable", "href='templates/'" in page, page[:400])
# templates/ holds an index.html, so that one is served rather than listed -
# which is the ordinary rule and worth not breaking.
served_index = urllib.request.urlopen("http://127.0.0.1:8153/templates/", timeout=3).read()
check("a folder with an index.html still serves it", b"{{ title }}" in served_index, served_index)

sub = urllib.request.urlopen("http://127.0.0.1:8153/static/", timeout=3).read().decode()
check("a subfolder with no index is listed", "app.css" in sub, sub[:300])
check("with a way back up", "href='..'" in sub, sub[:300])
pycmd_servers.kill_all()
time.sleep(0.3)

report("\n== servers: http, https and the port a framework really took ==")
check(
    "a TLS handshake on an http port is recognised",
    pycmd_servers._looks_like_tls("code 400, message Bad request version ('\\x16\\x03\\x01')"),
    "not recognised",
)
check(
    "an ordinary 404 is not mistaken for one",
    not pycmd_servers._looks_like_tls("code 404, message File not found"),
    "mistaken",
)


class _FakeEntry:
    kind = "script"
    port = 8000
    handle = "srvport"

    def __init__(self):
        self.lines = []

    def add_log(self, stream, text):
        self.lines.append(text)


# The other half of "the address does not work": a Flask app written on a
# laptop says app.run(), which binds 127.0.0.1:5000 with the auto-reloader on -
# a server the phone's browser cannot reach, restarting itself with a process
# launcher Android does not have. Checked against a stand-in Flask, so the
# suite does not need the real one installed to prove the patch.
import types  # noqa: E402

fake_flask = types.ModuleType("flask")
ran_with = []


class _FakeFlaskApp:
    def run(self, host=None, port=None, debug=None, **options):
        ran_with.append(dict(options, host=host, port=port, debug=debug))


fake_flask.Flask = _FakeFlaskApp
sys.modules["flask"] = fake_flask


class _BindEntry:
    kind = "script"
    port = 8000
    handle = "srvbind"

    def __init__(self):
        self.lines = []

    def add_log(self, stream, text):
        self.lines.append(text)


bind_entry = _BindEntry()
pycmd_servers._patch_flask()
pycmd_servers._binding.value = ("0.0.0.0", 8161, bind_entry)

_FakeFlaskApp().run()
check("app.run() gets the host the form asked for", ran_with[-1]["host"] == "0.0.0.0", ran_with[-1])
check("and the port", ran_with[-1]["port"] == 8161, ran_with[-1])
check(
    "and the reloader Android cannot run is off",
    ran_with[-1]["use_reloader"] is False,
    ran_with[-1],
)

_FakeFlaskApp().run(port=5000)
check("a port the code names is left alone", ran_with[-1]["port"] == 5000, ran_with[-1])
check("and the card is corrected to it", bind_entry.port == 5000, bind_entry.port)

_FakeFlaskApp().run(host="127.0.0.1")
check(
    "a loopback host is honoured, and said out loud",
    ran_with[-1]["host"] == "127.0.0.1"
    and any("only this phone" in line for line in bind_entry.lines),
    bind_entry.lines,
)

pycmd_servers._binding.value = None
_FakeFlaskApp().run()
check(
    "off a PyCmd server thread it changes nothing",
    ran_with[-1]["host"] is None and ran_with[-1]["port"] is None,
    ran_with[-1],
)
del sys.modules["flask"]

fake = _FakeEntry()
pycmd_servers._learn_port(fake, " * Running on http://127.0.0.1:5000\n")
check("the real port is taken from what the framework printed", fake.port == 5000, fake.port)
pycmd_servers._learn_port(fake, "GET / HTTP/1.1 200 -\n")
check("and ordinary output does not move it", fake.port == 5000, fake.port)


report("\n== servers: a plugin can claim a file type ==")


class _Runner:
    """What Kotlin registers for JavaScript, in miniature."""

    def __init__(self):
        self.ran = []

    def run(self, path, channel):
        self.ran.append((path, channel))


runner = _Runner()
check("a runner registers",
      pycmd_servers.register_runner(".widget", runner, "Run by the widget plugin") is True)
check("Python cannot be claimed", pycmd_servers.register_runner(".py", runner) is False)
check("nor can something uncallable", pycmd_servers.register_runner(".x", object()) is False)
widget = os.path.join(workspace, "thing.widget")
with open(widget, "w", encoding="utf-8") as handle_file:
    handle_file.write("anything\n")
plan = pycmd_servers.how_to_run(widget)
check("the launcher says what the plugin will do",
      plan["how"] == "plugin" and plan["note"] == "Run by the widget plugin", plan)
started = pycmd_servers.start_file(widget)
check("and starting it reaches the plugin", started.get("ok") is True, started)
time.sleep(0.5)
check("with the file and its channel", runner.ran and runner.ran[0][0] == widget, runner.ran)
pycmd_servers.unregister_runner(".widget")
check("unregistering puts it back", pycmd_servers.how_to_run(widget)["how"] == "unsupported")
pycmd_servers.kill_all()
time.sleep(0.3)

report("\n== languages: registry ==")
from pycmd_langs import registry  # noqa: E402

check("python is runnable", registry.for_path("a.py")["mode"] == "run", registry.for_path("a.py"))
check("C is runnable", registry.for_path("a.c")["mode"] == "run", registry.for_path("a.c"))
check("javascript is runnable", registry.for_path("a.js")["mode"] == "run", registry.for_path("a.js"))
check("html previews", registry.for_path("a.html")["mode"] == "preview", registry.for_path("a.html"))
check("rust is runnable", registry.for_path("a.rs")["mode"] == "run", registry.for_path("a.rs"))
check("go is runnable", registry.for_path("a.go")["mode"] == "run", registry.for_path("a.go"))
check(
    "rust admits it has no borrow checker",
    "borrow" in registry.for_path("a.rs")["note"],
    registry.for_path("a.rs")["note"],
)
check(
    "java still says why it cannot run",
    "compiler" in registry.for_path("A.java")["note"],
    registry.for_path("A.java")["note"],
)
check("unknown extension falls back to text", registry.for_path("a.zzz")["id"] == "text",
      registry.for_path("a.zzz"))
check("README is markdown", registry.for_path("README.md")["id"] == "markdown",
      registry.for_path("README.md"))
check("catalogue is large", len(registry.catalogue()) >= 25, len(registry.catalogue()))
check(
    "restricted catalogue is python-only",
    all(r["id"] in ("python", "text", "markdown") for r in registry.catalogue(False)),
    registry.catalogue(False),
)
# Media: recognised everywhere, never written from a template, and part of
# what the kit plugin adds rather than something the app has on its own.
check("mp3 is media", registry.for_path("song.mp3")["mode"] == "media",
      registry.for_path("song.mp3"))
check("mp4 is media", registry.for_path("clip.MP4")["mode"] == "media",
      registry.for_path("clip.MP4"))
check("media is not creatable", registry.for_path("song.mp3")["creatable"] is False,
      registry.for_path("song.mp3"))
check("media carries a picker type", registry.for_path("song.mp3")["mime"] == "audio/*",
      registry.for_path("song.mp3"))
check("a zip is picked with no filter", registry.for_path("x.zip")["mime"] == "*/*",
      registry.for_path("x.zip"))
check("media has no template", registry.template_for("song.mp3") == "",
      repr(registry.template_for("song.mp3")))
check("code is still creatable", registry.for_path("x.py")["creatable"] is True,
      registry.for_path("x.py"))
check("svg is still xml, not an image", registry.for_path("logo.svg")["id"] == "xml",
      registry.for_path("logo.svg"))
check("media rides with the kit", any(r["mode"] == "media" for r in registry.catalogue()),
      [r["id"] for r in registry.catalogue() if r["mode"] == "media"])
check("and is gone without it", not any(r["mode"] == "media" for r in registry.catalogue(False)),
      registry.catalogue(False))
check("media_types lists exactly those", 
      {r["id"] for r in registry.media_types()} ==
      {r["id"] for r in registry.catalogue() if r["mode"] == "media"},
      [r["id"] for r in registry.media_types()])
check("every media type says how it is picked",
      all(r["mime"] for r in registry.media_types()),
      [(r["id"], r["mime"]) for r in registry.media_types()])

check("C template compiles", "int main" in registry.template_for("x.c"), registry.template_for("x.c"))
check("LICENSE template is the MIT text", "MIT License" in registry.template_for("LICENSE"),
      registry.template_for("LICENSE")[:40])
check("gitignore template", "__pycache__" in registry.template_for(".gitignore"),
      registry.template_for(".gitignore"))

report("\n== languages: running a C file through the runtime ==")
c_file = os.path.join(workspace, "demo.c")
with open(c_file, "w", encoding="utf-8") as handle:
    handle.write(
        "#include <stdio.h>\n"
        "int main(void) {\n"
        "    for (int i = 1; i <= 3; i++) printf(\"%d \", i * i);\n"
        "    printf(\"\\n\");\n"
        "    return 0;\n"
        "}\n"
    )
sink.reset()
status = pycmd_runtime.run_any(c_file)
check("run_any runs C", status == "ok", status)
check("C output reached the console", "1 4 9" in sink.text("stdout"), repr(sink.text()))
check("it announced the language", "as C" in sink.text("system"), sink.text("system"))

bad_c = os.path.join(workspace, "bad.c")
with open(bad_c, "w", encoding="utf-8") as handle:
    handle.write("int main() { int x = ; }\n")
sink.reset()
status = pycmd_runtime.run_any(bad_c)
check("a broken C file reports an error", status == "error", status)
check("the C error is explained", "C syntax error" in sink.text("stderr"), sink.text("stderr"))

report("\n== languages: running Go and Rust through the runtime ==")
rust_file = os.path.join(workspace, "demo.rs")
with open(rust_file, "w", encoding="utf-8") as handle:
    handle.write(
        "fn main() {\n"
        "    let squares: Vec<i32> = (1..=3).map(|n| n * n).collect();\n"
        '    println!("{:?}", squares);\n'
        "}\n"
    )
sink.reset()
status = pycmd_runtime.run_any(rust_file)
check("run_any runs Rust", status == "ok", status)
check("Rust output reached the console", "[1, 4, 9]" in sink.text("stdout"), repr(sink.text()))

go_file = os.path.join(workspace, "demo.go")
with open(go_file, "w", encoding="utf-8") as handle:
    handle.write(
        "package main\n\nimport \"fmt\"\n\n"
        "func main() {\n"
        "\tfor i := 1; i <= 3; i++ {\n"
        "\t\tfmt.Print(i*i, \" \")\n"
        "\t}\n"
        "\tfmt.Println()\n"
        "}\n"
    )
sink.reset()
status = pycmd_runtime.run_any(go_file)
check("run_any runs Go", status == "ok", status)
check("Go output reached the console", "1 4 9" in sink.text("stdout"), repr(sink.text()))

bad_go = os.path.join(workspace, "bad.go")
with open(bad_go, "w", encoding="utf-8") as handle:
    handle.write("package main\n\nfunc main() { x := }\n")
sink.reset()
status = pycmd_runtime.run_any(bad_go)
check("a broken Go file reports an error", status == "error", status)
check("the Go error is explained", "Go syntax error" in sink.text("stderr"), sink.text("stderr"))

java_file = os.path.join(workspace, "Demo.java")
with open(java_file, "w", encoding="utf-8") as handle:
    handle.write("public class Demo { }\n")
sink.reset()
status = pycmd_runtime.run_any(java_file)
check("java is refused", status == "error", status)
check("and says why", "compiler" in sink.text("stderr"), sink.text("stderr"))

sink.reset()
status = pycmd_runtime.run_any(os.path.join(workspace, "sample.py"))
check("run_any still runs python", status == "ok", status)

report("\n== channels ==")
sink.reset()
pycmd_runtime.run_source("print('console line')")
check(
    "console output carries the console channel",
    all(c == "console" for _, _, c in sink.chunks),
    {c for _, _, c in sink.chunks},
)
check("current_channel defaults to console", pycmd_runtime.current_channel() == "console", "not console")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {FAILURES}", file=real_stdout)
    sys.exit(1)
print("all checks passed", file=real_stdout)
