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
    def __init__(self):
        self.chunks = []
        self.stdin = queue.Queue()
        self.finished = []

    def onOutput(self, stream, text):  # noqa: N802 - mirrors the Kotlin name
        self.chunks.append((stream, text))

    def onReadLine(self):  # noqa: N802
        try:
            return self.stdin.get(timeout=2)
        except queue.Empty:
            return None

    def onFinished(self, run_id, status, millis):  # noqa: N802
        self.finished.append((run_id, status, millis))

    def text(self, stream=None):
        return "".join(t for s, t in self.chunks if stream is None or s == stream)

    def reset(self):
        self.chunks.clear()
        self.finished.clear()


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

report("\n== servers ==")
ip = pycmd_servers.local_ip()
check("local_ip returns something", isinstance(ip, str) and ip.count(".") == 3, ip)

started = pycmd_servers.start_file_server(workspace, 8123)
check("file server starts", started.get("ok") is True, started)
if started.get("ok"):
    time.sleep(0.4)
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:8123/sample.py", timeout=5) as response:
            body = response.read().decode()
        check("file server serves the workspace", "file says" in body, body[:80])
    except Exception as exc:  # noqa: BLE001
        check("file server serves the workspace", False, repr(exc))

    listing = pycmd_servers.listing()
    check("listing shows the server", len(listing) == 1 and listing[0]["status"] == "running", listing)
    check("count is 1", pycmd_servers.count() == 1, pycmd_servers.count())

    duplicate = pycmd_servers.start_file_server(workspace, 8123)
    check("port clash is reported", duplicate.get("ok") is False, duplicate)

    stopped = pycmd_servers.stop(started["handle"])
    check("stop succeeds", stopped.get("ok") is True, stopped)
    time.sleep(0.4)
    check("count returns to 0", pycmd_servers.count() == 0, pycmd_servers.count())

    again = pycmd_servers.start_file_server(workspace, 8123)
    check("port is reusable after stop", again.get("ok") is True, again)
    if again.get("ok"):
        pycmd_servers.stop(again["handle"])

bad = pycmd_servers.start_file_server(os.path.join(workspace, "nope"), 8124)
check("missing directory is rejected", bad.get("ok") is False, bad)

check("stop of unknown handle is rejected", pycmd_servers.stop("srv999")["ok"] is False, "accepted")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {FAILURES}", file=real_stdout)
    sys.exit(1)
print("all checks passed", file=real_stdout)
