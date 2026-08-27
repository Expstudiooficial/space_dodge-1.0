"""Reads an error, works out what would fix it, and offers to do it.

The rule this module lives by: **never fix anything on its own.** It says what
it thinks is wrong, says exactly what it would change, and waits for the word
`yes`. A tool that silently renames a file because it thought it knew better
is worse than one that reports the error and stops - you can debug an error
message; you cannot debug a file that changed under you.

Everything it can offer is something a person would have done by hand:

* a missing file that is one typo away from a file that does exist
* an import of a package that is not installed
* a port that something else is already listening on
* a folder served with no index page but exactly one page in it
"""

from __future__ import annotations

import difflib
import os
import re
import threading

__all__ = ["diagnose", "pending", "answer", "clear", "describe"]

# channel -> the offer waiting for a yes or a no
_pending = {}

MISSING_FILE = re.compile(
    r"(?:FileNotFoundError|IOError|OSError).*?No such file or directory:?\s*'([^']+)'"
)
MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
ADDRESS_IN_USE = re.compile(r"(?:Address already in use|EADDRINUSE|Errno 98)")
PERMISSION_DENIED = re.compile(r"(?:Permission denied|Errno 13)")

# Packages whose import name is not what you pip install.
PIP_NAMES = {
    "cv2": "opencv-python", "PIL": "pillow", "yaml": "pyyaml", "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn", "dateutil": "python-dateutil", "serial": "pyserial",
    "OpenGL": "PyOpenGL", "Crypto": "pycryptodome", "attr": "attrs", "git": "GitPython",
}

STANDARD_LIBRARY = {
    "os", "sys", "json", "re", "time", "math", "random", "socket", "threading",
    "http", "urllib", "sqlite3", "csv", "collections", "itertools", "pathlib",
}


def diagnose(text: str, context: dict) -> dict | None:
    """Looks at an error and returns an offer, or None if it has no idea.

    `context` says where the error came from:
      kind      "script" | "static" | "console"
      channel   where to ask the question
      path      the script that failed, if any
      directory the folder being served, if any
      port      the port in play, if any
    """
    if not text:
        return None

    channel = context.get("channel", "console")

    for finder in (_missing_file, _missing_module, _port_in_use, _permission):
        offer = finder(text, context)
        if offer is not None:
            offer["channel"] = channel
            _pending[channel] = offer
            return offer
    return None


def diagnose_missing_index(directory: str, context: dict) -> dict | None:
    """A folder served with no index page, but exactly one page in it."""
    if not os.path.isdir(directory):
        return None
    if os.path.isfile(os.path.join(directory, "index.html")):
        return None

    pages = [
        name for name in sorted(os.listdir(directory))
        if name.lower().endswith((".html", ".htm"))
    ]
    if len(pages) != 1:
        return None

    channel = context.get("channel", "console")
    offer = {
        "id": "missing-index",
        "message": (
            f"This folder has no index.html, so opening it shows a file listing. "
            f"There is exactly one page in it: {pages[0]}."
        ),
        "question": f"Copy {pages[0]} to index.html?",
        "fix": {"kind": "copy", "source": os.path.join(directory, pages[0]),
                "target": os.path.join(directory, "index.html")},
        "channel": channel,
    }
    _pending[channel] = offer
    return offer


# ------------------------------------------------------------------ finders

def _missing_file(text: str, context: dict) -> dict | None:
    match = MISSING_FILE.search(text)
    if not match:
        return None

    wanted = match.group(1)
    name = os.path.basename(wanted)
    folder = os.path.dirname(wanted)
    if not folder:
        folder = context.get("directory") or (
            os.path.dirname(context.get("path", "")) or os.getcwd()
        )
    if not os.path.isdir(folder):
        return None

    try:
        names = os.listdir(folder)
    except OSError:
        return None

    # The near-miss the user almost certainly meant: index2.html for
    # index.html, styles.css for style.css.
    close = difflib.get_close_matches(name, names, n=1, cutoff=0.6)
    if not close:
        stem = os.path.splitext(name)[0].lower()
        extension = os.path.splitext(name)[1].lower()
        same_kind = [
            candidate for candidate in names
            if os.path.splitext(candidate)[1].lower() == extension
            and stem in os.path.splitext(candidate)[0].lower()
        ]
        close = same_kind[:1]
    if not close:
        return None

    found = close[0]
    if found == name:
        return None

    return {
        "id": "missing-file",
        "message": (
            f"{name} was not found, but {found} is sitting next to it in "
            f"{os.path.basename(folder) or folder}."
        ),
        "question": f"Rename {found} to {name}?",
        "fix": {"kind": "rename", "source": os.path.join(folder, found),
                "target": os.path.join(folder, name)},
    }


def _missing_module(text: str, context: dict) -> dict | None:
    match = MISSING_MODULE.search(text)
    if not match:
        return None

    module = match.group(1).split(".")[0]
    if module in STANDARD_LIBRARY:
        return None

    package = PIP_NAMES.get(module, module)
    return {
        "id": "missing-module",
        "message": f"This needs the {module} package, which is not installed.",
        "question": f"Install {package} now? It downloads from PyPI.",
        "fix": {"kind": "install", "package": package, "module": module},
    }


def _port_in_use(text: str, context: dict) -> dict | None:
    if not ADDRESS_IN_USE.search(text):
        return None

    port = context.get("port") or _port_from(text) or 8000
    free = _free_port(int(port) + 1)
    return {
        "id": "port-in-use",
        "message": f"Port {port} is already taken by something else.",
        "question": f"Use port {free} instead? The launcher form is updated for you.",
        "fix": {"kind": "port", "port": free},
    }


def _permission(text: str, context: dict) -> dict | None:
    if not PERMISSION_DENIED.search(text):
        return None
    port = int(context.get("port") or 0)
    if not port or port >= 1024:
        return None
    free = _free_port(8000)
    return {
        "id": "low-port",
        "message": (
            f"Android does not let an app listen on port {port}; anything below "
            f"1024 is reserved."
        ),
        "question": f"Use port {free} instead?",
        "fix": {"kind": "port", "port": free},
    }


def _port_from(text: str):
    match = re.search(r"port\s*[:=]?\s*(\d{2,5})", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _free_port(start: int) -> int:
    import socket

    for candidate in range(max(1024, start), max(1024, start) + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("0.0.0.0", candidate))
                return candidate
            except OSError:
                continue
    return start + 1


# ------------------------------------------------------------------ answers

def pending(channel: str = "console") -> dict | None:
    return _pending.get(channel)


def clear(channel: str = "console") -> None:
    _pending.pop(channel, None)


def describe(offer: dict) -> str:
    """The exact text the console shows when an offer is made."""
    return (
        f"\n[fix] {offer['message']}\n"
        f"[fix] {offer['question']}\n"
        f"[fix] Type yes to do it, no to leave it alone.\n"
    )


YES = {"y", "yes", "yeah", "yep", "yup", "ok", "okay", "k", "do it", "doit",
       "sure", "go", "go on", "go ahead", "please", "yes please", "fix it",
       "ano", "hej", "jasne", "davaj", "urob to", "si", "ja", "oui"}
NO = {"n", "no", "nope", "nah", "not now", "later", "leave it", "leave it alone",
      "stop", "cancel", "skip", "nie", "ne", "nay", "non"}

# What a fix says it is about to do, before it starts. The user asked to be
# told - "ok, fixing that", not silence followed by a result thirty seconds
# later - and on a slow network the silence is the whole complaint.
def _acknowledge(fix: dict) -> str:
    kind = fix.get("kind")
    if kind == "rename":
        return (f"[fix] OK - renaming {os.path.basename(fix['source'])} to "
                f"{os.path.basename(fix['target'])}, so the code finds what it asks for.")
    if kind == "copy":
        return (f"[fix] OK - copying {os.path.basename(fix['source'])} to "
                f"{os.path.basename(fix['target'])}, leaving the original where it is.")
    if kind == "install":
        return f"[fix] OK - downloading {fix['package']} from PyPI. This can take a minute."
    if kind == "port":
        return f"[fix] OK - moving to port {fix['port']}."
    return "[fix] OK - working on it."


def answer(channel: str, text: str, emit=None) -> dict:
    """Answers the offer waiting on `channel`, without blocking the caller.

    Returns as soon as the reply is understood. The fix itself runs on its own
    thread and reports through `emit(text)`, because the one fix that takes
    real time - a pip install - used to run on the thread the app calls in on,
    which is the same thread the Stop and Kill buttons need. Answering yes
    could therefore freeze the server *and* the button meant to rescue it.

    `handled: False` means the line was not an answer, so the caller passes it
    on as ordinary input - a server's stdin is a real thing people type into,
    and a program may well be asking a yes/no question of its own.
    """
    offer = _pending.get(channel)
    if offer is None:
        return {"handled": False}

    reply = " ".join((text or "").strip().lower().replace("!", " ").split())
    if reply in NO:
        _pending.pop(channel, None)
        return {"handled": True, "applied": False, "done": True,
                "message": "[fix] OK - no fixing today. The error stays as it is."}

    if reply not in YES:
        # Not an answer. Say so once, quietly, and let the line through: a
        # silent non-response is exactly what made this feel broken.
        return {"handled": False, "hint": "[fix] Still waiting on yes or no."}

    _pending.pop(channel, None)
    fix = offer["fix"]
    ack = _acknowledge(fix)

    reply_dict = {
        "handled": True,
        "applied": False,
        "done": False,
        "message": ack,
        "fix_kind": fix.get("kind", ""),
    }

    # The port fix is the one thing this module cannot do itself: the app owns
    # the launcher form, so it gets the number back and moves it.
    if fix.get("kind") == "port":
        _report(emit, ack)
        result = _apply(fix)
        reply_dict.update(applied=result["ok"], done=True,
                          message=ack + "\n" + result["message"],
                          port=fix["port"])
        return reply_dict

    def work() -> None:
        _report(emit, ack)
        try:
            result = _apply(fix, lambda line: _report(emit, line))
        except Exception as error:  # noqa: BLE001
            result = {"ok": False, "message": f"[fix] That did not work: {error}"}
        _report(emit, result["message"])

    thread = threading.Thread(target=work, name=f"pycmd-fix-{channel}", daemon=True)
    thread.start()
    return reply_dict


def _report(emit, line: str) -> None:
    """Says a line on the channel the offer was made on, whatever happens."""
    if emit is None:
        return
    try:
        emit(line if line.endswith("\n") else line + "\n")
    except Exception:  # noqa: BLE001
        pass


def _apply(fix: dict, say=None) -> dict:
    kind = fix.get("kind")

    def note(line: str) -> None:
        if say is not None:
            say(line)

    if kind in ("rename", "copy"):
        source = fix["source"]
        target = fix["target"]
        if not os.path.isfile(source):
            return {"ok": False, "message": f"[fix] {os.path.basename(source)} is gone."}
        if os.path.exists(target):
            return {"ok": False,
                    "message": f"[fix] {os.path.basename(target)} already exists now."}
        try:
            if kind == "rename":
                os.rename(source, target)
            else:
                import shutil

                shutil.copy2(source, target)
        except OSError as error:
            return {"ok": False, "message": f"[fix] That did not work: {error}"}
        verb = "Renamed" if kind == "rename" else "Copied"
        return {
            "ok": True,
            "message": f"[fix] {verb} {os.path.basename(source)} to "
                       f"{os.path.basename(target)}. Start it again.",
        }

    if kind == "install":
        package = fix["package"]
        note(f"[fix] Asking PyPI for {package}...")

        class _Progress:
            """Passes the installer's own running commentary straight through."""

            def onProgress(self, message):  # noqa: N802 - the installer's name
                note(f"[fix] {message}")

        try:
            import pycmd_packages

            result = pycmd_packages.install(package, progress=_Progress() if say else None)
        except Exception as error:  # noqa: BLE001
            return {"ok": False, "message": f"[fix] Could not install {package}: {error}"}
        if isinstance(result, dict) and not result.get("ok", True):
            return {"ok": False,
                    "message": f"[fix] {package} would not install: {result.get('error', '')}"}
        return {"ok": True, "message": f"[fix] Installed {package}. Run it again."}

    if kind == "port":
        # Nothing to do on this side: the app moves the form to the new port,
        # and says so.
        return {"ok": True, "message": f"[fix] Use port {fix['port']} and start it again."}

    return {"ok": False, "message": "[fix] Nothing to do."}
