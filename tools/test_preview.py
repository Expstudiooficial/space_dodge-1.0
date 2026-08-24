"""Checks the preview renderer, the loopback server, and folder exports.

The behaviour worth guarding here is the awkward kind: a page that scrolls, a
document that finds its own sections, and an archive that refuses to reach
outside the workspace.
"""

from __future__ import annotations

import os
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

import pycmd_download as download  # noqa: E402
import pycmd_preview as preview  # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


scratch = tempfile.mkdtemp(prefix="pycmd-preview-")


def write(name, text):
    path = os.path.join(scratch, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


print("\n== a page that can be scrolled ==")
page = preview.render_text("# Title\n\n    a very long line " + "x" * 400 + "\n", "doc.md")
check("code blocks wrap rather than scroll sideways", "white-space: pre-wrap" in page["html"])
check("long words break", "overflow-wrap: anywhere" in page["html"])
check("vertical drags belong to the page", "touch-action: pan-y" in page["html"])

print("\n== a long document finds its own sections ==")
long_doc = "# Guide\n\n" + "".join(f"## Section {n}\n\ntext\n\n" for n in range(1, 7))
rendered = preview.render_text(long_doc, "guide.md")["html"]
check("a contents panel appears", 'class="pycmd-toc"' in rendered)
check("every heading is addressable", rendered.count("<h2 id=") == 6)
check("the jump links point at them", rendered.count('<a href="#s') == 6)

short = preview.render_text("# One\n\n## Only\n\ntext\n", "short.md")["html"]
check("a short document gets no panel", 'class="pycmd-toc"' not in short)

print("\n== plain text is readable, not raw ==")
text = preview.render_text("alpha\nbeta\ngamma\n", "notes.txt")["html"]
check("text is counted for the reader", "3 lines" in text and "3 words" in text)
check("text is monospaced", "pycmd-text" in text)
check("a text file gets no contents panel", 'class="pycmd-toc"' not in text)

print("\n== documents are served, like every other page ==")
served = preview.serve_text(long_doc, "guide.md")
check("the document is served", served.get("served") is True, str(served.get("url")))
check("over loopback only", str(served.get("url", "")).startswith("http://127.0.0.1:"))
fetched = urllib.request.urlopen(served["url"], timeout=5).read().decode("utf-8")
check("and the server hands back that page", "<h1>Guide</h1>" in fetched)

print("\n== a file preview serves its own folder ==")
write("site/index.html", "<h1>hi</h1><script src='app.js'></script>")
write("site/app.js", "console.log('ok')")
opened = preview.serve(os.path.join(scratch, "site", "index.html"))
check("html is served as itself", opened.get("url", "").endswith("/index.html"), str(opened))
sibling = opened["url"].rsplit("/", 1)[0] + "/app.js"
check(
    "a relative script loads",
    urllib.request.urlopen(sibling, timeout=5).read().decode("utf-8").startswith("console.log"),
)
preview.stop()

print("\n== exporting one folder ==")
downloads = tempfile.mkdtemp(prefix="pycmd-downloads-")
workspace = tempfile.mkdtemp(prefix="pycmd-workspace-")
download.configure(downloads, workspace)
os.makedirs(os.path.join(workspace, "project", "sub"), exist_ok=True)
for name in ("project/main.py", "project/sub/util.py", "other.py"):
    with open(os.path.join(workspace, name), "w", encoding="utf-8") as handle:
        handle.write("print(1)\n")

result = download.export_folder(os.path.join(workspace, "project"))
check("the folder is zipped", result.get("ok") is True, str(result.get("error")))
check("with everything under it", result.get("files") == 2, str(result.get("files")))
check("named after the folder", str(result.get("name", "")).startswith("project"), str(result))

import zipfile  # noqa: E402

with zipfile.ZipFile(result["path"]) as archive:
    names = sorted(archive.namelist())
check("paths are relative to the folder", names == ["main.py", os.path.join("sub", "util.py")], str(names))

whole = download.export_workspace()
check("the whole workspace still exports", whole.get("ok") is True and whole.get("files") == 3, str(whole))

outside = download.export_folder(os.path.dirname(workspace))
check("a folder outside the workspace is refused", outside.get("ok") is False, str(outside))

os.makedirs(os.path.join(workspace, "empty"), exist_ok=True)
nothing = download.export_folder(os.path.join(workspace, "empty"))
check("an empty folder is not a silent empty zip", nothing.get("ok") is False, str(nothing))
check("and leaves nothing behind", not any(n.startswith("empty") for n in os.listdir(downloads)))

print()
if FAILURES:
    print(f"{len(FAILURES)} preview checks failed")
    sys.exit(1)
print("all preview checks passed")
