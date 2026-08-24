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


YES = {"y", "yes", "yeah", "yep", "ok", "okay", "do it", "sure", "ano", "hej"}
NO = {"n", "no", "nope", "nah", "leave it", "nie", "ne"}


def answer(channel: str, text: str) -> dict:
    """Applies or dismisses the offer waiting on `channel`.

    Returns `handled: False` when there was nothing pending or the reply was
    not a yes or a no - the caller then treats the line as ordinary input,
    which matters because a server's stdin is a real thing people type into.
    """
    offer = _pending.get(channel)
    if offer is None:
        return {"handled": False}

    reply = (text or "").strip().lower()
    if reply in NO:
        _pending.pop(channel, None)
        return {"handled": True, "applied": False, "message": "[fix] Left alone."}
    if reply not in YES:
        return {"handled": False}

    _pending.pop(channel, None)
    result = _apply(offer["fix"])
    reply = {"handled": True, "applied": result["ok"], "message": result["message"],
             "fix": offer["fix"]}
    # The port fix is the one thing this module cannot do itself: the app owns
    # the launcher form, so it gets the number back and moves it.
    if offer["fix"].get("kind") == "port" and result["ok"]:
        reply["port"] = offer["fix"]["port"]
    return reply


def _apply(fix: dict) -> dict:
    kind = fix.get("kind")

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
        try:
            import pycmd_packages

            result = pycmd_packages.install(package)
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
