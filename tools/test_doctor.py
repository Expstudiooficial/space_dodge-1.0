"""Checks the self-diagnosis: what it offers, and that it only acts on a yes."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import pycmd_doctor as doctor  # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


scratch = tempfile.mkdtemp(prefix="pycmd-doctor-")


def write(name, text="x"):
    path = os.path.join(scratch, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


print("\n== a file that is one typo away ==")
write("index2.html", "<h1>hi</h1>")
traceback = (
    "Traceback (most recent call last):\n"
    '  File "server.py", line 4, in <module>\n'
    "    with open('index.html') as handle:\n"
    "FileNotFoundError: [Errno 2] No such file or directory: 'index.html'\n"
)
offer = doctor.diagnose(traceback, {"kind": "script", "channel": "s1",
                                    "path": os.path.join(scratch, "server.py"),
                                    "directory": scratch})
check("a near-miss filename is spotted", offer is not None, offer)
check("it names the file that does exist", "index2.html" in offer["message"], offer)
check("it asks before doing anything", "Rename" in offer["question"], offer)
check("nothing has changed yet", os.path.isfile(os.path.join(scratch, "index2.html")))
check("and the target does not exist yet",
      not os.path.exists(os.path.join(scratch, "index.html")))

print("\n== an answer that is neither yes nor no ==")
result = doctor.answer("s1", "what?")
check("is not treated as consent", not result["handled"], result)
check("and the offer is still waiting", doctor.pending("s1") is not None)

print("\n== no ==")
result = doctor.answer("s1", "no")
check("is handled", result["handled"], result)
check("but changes nothing", not result["applied"], result)
check("the file is untouched", os.path.isfile(os.path.join(scratch, "index2.html")))
check("and the offer is gone", doctor.pending("s1") is None)

print("\n== yes ==")
doctor.diagnose(traceback, {"kind": "script", "channel": "s1", "directory": scratch})
result = doctor.answer("s1", "yes")
check("is applied", result["applied"], result)
check("the file was renamed", os.path.isfile(os.path.join(scratch, "index.html")))
check("and the old name is gone", not os.path.exists(os.path.join(scratch, "index2.html")))
check("it says what it did", "Renamed" in result["message"], result)

print("\n== a missing package ==")
offer = doctor.diagnose("ModuleNotFoundError: No module named 'flask'",
                        {"kind": "console", "channel": "console"})
check("is spotted", offer is not None, offer)
check("and names the package", "flask" in offer["question"], offer)
doctor.clear("console")

offer = doctor.diagnose("ModuleNotFoundError: No module named 'cv2'",
                        {"kind": "console", "channel": "console"})
check("an import name that differs from its package is translated",
      "opencv-python" in offer["question"], offer)
doctor.clear("console")

offer = doctor.diagnose("ModuleNotFoundError: No module named 'json'",
                        {"kind": "console", "channel": "console"})
check("the standard library is never offered for install", offer is None, offer)

print("\n== a port already in use ==")
offer = doctor.diagnose("OSError: [Errno 98] Address already in use",
                        {"kind": "static", "channel": "s2", "port": 8000})
check("is spotted", offer is not None, offer)
check("and a free port is suggested", offer["fix"]["port"] > 8000, offer)
doctor.clear("s2")

print("\n== a port Android will not allow ==")
offer = doctor.diagnose("PermissionError: [Errno 13] Permission denied",
                        {"kind": "static", "channel": "s3", "port": 80})
check("is spotted", offer is not None, offer)
check("and explains why", "1024" in offer["message"], offer)
doctor.clear("s3")

offer = doctor.diagnose("PermissionError: [Errno 13] Permission denied",
                        {"kind": "static", "channel": "s3", "port": 8080})
check("but a high port that is refused is not blamed on the rule", offer is None, offer)

print("\n== a folder with no index page ==")
folder = os.path.join(scratch, "site")
os.makedirs(folder, exist_ok=True)
with open(os.path.join(folder, "home.html"), "w") as handle:
    handle.write("<h1>home</h1>")
offer = doctor.diagnose_missing_index(folder, {"channel": "s4"})
check("is spotted", offer is not None, offer)
check("and offers to copy rather than rename",
      offer["fix"]["kind"] == "copy", offer)
doctor.answer("s4", "yes")
check("copying leaves the original", os.path.isfile(os.path.join(folder, "home.html")))
check("and makes the index", os.path.isfile(os.path.join(folder, "index.html")))

with open(os.path.join(folder, "about.html"), "w") as handle:
    handle.write("<h1>about</h1>")
os.remove(os.path.join(folder, "index.html"))
offer = doctor.diagnose_missing_index(folder, {"channel": "s5"})
check("two pages is too ambiguous to guess", offer is None, offer)

print("\n== nothing to say ==")
check("an ordinary error is left alone",
      doctor.diagnose("ValueError: invalid literal for int()", {"channel": "s6"}) is None)
check("and an empty error too", doctor.diagnose("", {"channel": "s6"}) is None)

shutil.rmtree(scratch, ignore_errors=True)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
    raise SystemExit(1)
print("all doctor checks passed")
