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
