"""The thirteen plugins that are part of the app.

On the phone these live in Kotlin, as a list of `PluginSpec` with their
switches in SharedPreferences. They are not Python plugins and never were:
each one is a capability the app itself gains or loses, which is why they can
do things a sandboxed plugin cannot - add file types to the new-file menu,
change what the editor highlights, put a bar above the keyboard.

Porting them means porting the *registry*, not the features: the features are
implemented by whatever screen they belong to, exactly as before. What this
file owns is which ones exist, which are on, what depends on what, and what
each one gains when Power Pack is on beside it.

Same ids as the phone build, deliberately. A plugin that checks
``pycmd.plugin_on("pycmd.polyglot.files")`` should get the same answer on both,
and a settings file copied from one to the other should mean the same thing.
"""

from __future__ import annotations

import json
import os

from . import store

KIT = "kit"
LANGUAGES = "languages"
TOOLS = "tools"
WORKSPACE = "workspace"
SYSTEM = "system"

GROUP_NAMES = {
    KIT: "The kit",
    LANGUAGES: "Languages and editing",
    TOOLS: "Tools",
    WORKSPACE: "Workspace",
    SYSTEM: "System",
}


class Builtin:
    __slots__ = ("id", "name", "tagline", "description", "group", "default",
                 "powered_up", "requires", "windows_note")

    def __init__(self, id, name, tagline, description, group, default=True,
                 powered_up="", requires=(), windows_note=""):
        self.id = id
        self.name = name
        self.tagline = tagline
        self.description = description
        self.group = group
        self.default = default
        self.powered_up = powered_up
        self.requires = tuple(requires)
        # What is different about this one on Windows. Empty means nothing is.
        self.windows_note = windows_note

    def as_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "tagline": self.tagline,
            "description": self.description, "group": self.group,
            "group_name": GROUP_NAMES.get(self.group, self.group),
            "default": self.default, "powered_up": self.powered_up,
            "requires": list(self.requires), "windows_note": self.windows_note,
            "builtin": True,
        }


POLYGLOT_FILES = "pycmd.polyglot.files"
POLYGLOT_RUNNER = "pycmd.polyglot.runner"
POWER_PACK = "pycmd.powerpack"
SNIPPETS = "pycmd.snippets"
HTTP_CLIENT = "pycmd.http"
JSON_TOOLS = "pycmd.json"
TEXT_TOOLS = "pycmd.text"
REGEX_LAB = "pycmd.regex"
SEARCH = "pycmd.search"
DOWNLOADER = "pycmd.downloader"
EXPORT = "pycmd.export"
AUTOSAVE = "pycmd.autosave"
KEEP_AWAKE = "pycmd.keepawake"

CORE = (POLYGLOT_FILES, POLYGLOT_RUNNER, POWER_PACK)

ALL = [
    Builtin(
        POLYGLOT_FILES, "Polyglot Files",
        "Create and edit 65 file types, not just .py",
        "Adds every language PyCmd knows to the new-file menu, each with a "
        "starter template: JavaScript, TypeScript, HTML, CSS, JSON, Markdown, "
        "C, C++, Rust, Go, Java, Kotlin, C#, F#, Haskell, Julia, R, Dart, Zig, "
        "Nim, Crystal, Elixir, Erlang, Scala, Clojure, OCaml, Racket, Fortran, "
        "COBOL, Pascal, PowerShell, batch, SQL, YAML, TOML, XML and more. The "
        "editor highlights whichever language the file is, and Files shows a "
        "coloured icon per type. Music, video, images, PDFs, archives and fonts "
        "are brought in from the disk rather than written from a template.",
        KIT, powered_up="Adds README, LICENSE, .gitignore, Dockerfile, Makefile "
                        "and package manifests as one-click templates.",
        windows_note="Thirty-one more languages than the phone build, because "
                     "Windows lets an app run what it compiled.",
    ),
    Builtin(
        POLYGLOT_RUNNER, "Polyglot Runner", "Run more than Python",
        "Runs whatever you press Run on, using the real toolchain when one is "
        "installed and the interpreters PyCmd carries when there is not. C, Go, "
        "Rust and JavaScript run either way; forty-three languages run when "
        "their compiler is on the PATH. Previews HTML, CSS and Markdown. The "
        "console says which toolchain ran the file, every time.",
        KIT, powered_up="Adds a live preview that reloads as you type, and lets "
                        "you pick which toolchain runs a file when more than one "
                        "could.",
        requires=(POLYGLOT_FILES,),
        windows_note="This is the plugin the Windows build changes most. On a "
                     "phone it drives interpreters; here it drives GCC, Go, "
                     "rustc, the JDK, the .NET SDK and forty-odd others.",
    ),
    Builtin(
        POWER_PACK, "Power Pack", "Makes every other plugin do more",
        "The multiplier. Every plugin that says 'with Power Pack' below gains "
        "its extra behaviour while this is on: more templates, more languages, "
        "extra server options, richer tools and a bigger snippet library.",
        KIT,
    ),
    Builtin(
        SNIPPETS, "Snippets", "Insert boilerplate for the language you are in",
        "A snippet bar in the editor that changes with the file type - a Python "
        "main guard, an HTML skeleton, a fetch call, a CSS reset, a Windows "
        "service stub.",
        LANGUAGES, powered_up="Roughly triples the snippet library and adds "
                              "framework starters.",
    ),
    Builtin(
        HTTP_CLIENT, "API Tester", "Send HTTP requests and read the response",
        "A small REST client: method, URL, headers, body. Handy for poking at a "
        "server you just started.",
        TOOLS, powered_up="Saves a history of requests and can replay one.",
    ),
    Builtin(
        JSON_TOOLS, "JSON Tools", "Format, validate and query JSON",
        "Pretty-prints, minifies, tells you where the syntax error is, and runs "
        "a path query over a document.",
        TOOLS,
    ),
    Builtin(
        TEXT_TOOLS, "Text Tools", "The conversions you keep needing",
        "Base64, URL encoding, hashes, case conversion, line sorting, "
        "deduplication and a diff.",
        TOOLS, powered_up="Adds hex, JWT decoding and a character inspector.",
    ),
    Builtin(
        REGEX_LAB, "Regex Lab", "Build a pattern and watch it match",
        "A pattern, a subject, and the matches highlighted as you type, with "
        "the groups named.",
        TOOLS,
    ),
    Builtin(
        SEARCH, "Workspace Search", "Find text across every file",
        "Searches inside files rather than filenames, with a preview of each "
        "hit and a jump straight to the line.",
        WORKSPACE, powered_up="Adds regular expressions and filters by file type.",
    ),
    Builtin(
        DOWNLOADER, "Downloader", "Fetch a file from a URL",
        "Downloads to the Downloads folder, then copies into the workspace if "
        "you want it there.",
        WORKSPACE,
    ),
    Builtin(
        EXPORT, "Workspace Export", "Zip the workspace and save it out",
        "Writes a .zip of everything to Downloads, and on Windows can save it "
        "anywhere you can reach.",
        WORKSPACE,
        windows_note="Saves through the ordinary Windows file dialog, so it can "
                     "go to any folder or drive rather than only to Downloads.",
    ),
    Builtin(
        AUTOSAVE, "Autosave", "Never lose an edit",
        "Saves the open file a moment after you stop typing, and keeps the last "
        "few versions so a mistake is recoverable.",
        SYSTEM,
    ),
    Builtin(
        KEEP_AWAKE, "Keep Awake", "Do not sleep while something is running",
        "Holds off sleep while a script or a server is running, and lets go the "
        "moment it stops.",
        SYSTEM,
        windows_note="Uses the Windows power request API rather than Android's "
                     "wake lock. The screen may still turn off; the machine will "
                     "not suspend under a running server.",
    ),
]

_BY_ID = {plugin.id: plugin for plugin in ALL}

_SETTINGS_NAME = "builtins.json"
_state = None


def _settings_path() -> str:
    return os.path.join(store.root(), _SETTINGS_NAME)


def _load() -> dict:
    global _state
    if _state is not None:
        return _state
    _state = {plugin.id: plugin.default for plugin in ALL}
    try:
        with open(_settings_path(), "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        if isinstance(saved, dict):
            for key, value in saved.items():
                if key in _state:
                    _state[key] = bool(value)
    except (OSError, ValueError):
        # No file yet, or one somebody edited into nonsense. The defaults are
        # a working app, so there is nothing to report and nothing to fix.
        pass
    return _state


def _save() -> None:
    try:
        with open(_settings_path(), "w", encoding="utf-8") as handle:
            json.dump(_load(), handle, indent=2)
    except OSError:
        pass


def is_on(plugin_id: str) -> bool:
    return bool(_load().get(plugin_id, False))


def powered_up(plugin_id: str) -> bool:
    """Whether this one is on *and* Power Pack is on beside it."""
    return is_on(plugin_id) and is_on(POWER_PACK)


def set_enabled(plugin_id: str, on: bool) -> dict:
    """Switches one on or off, and honours what depends on what.

    Switching off something another plugin requires switches that one off too,
    rather than leaving it on and quietly broken. Switching one on brings its
    requirements with it, for the same reason.
    """
    state = _load()
    if plugin_id not in state:
        return {"ok": False, "error": f"{plugin_id} is not a built-in plugin"}

    changed = {plugin_id: bool(on)}
    if on:
        for needed in _BY_ID[plugin_id].requires:
            if not state.get(needed):
                changed[needed] = True
    else:
        for other in ALL:
            if plugin_id in other.requires and state.get(other.id):
                changed[other.id] = False

    state.update(changed)
    _save()
    return {"ok": True, "changed": changed}


def enabled_ids() -> list:
    return [plugin.id for plugin in ALL if is_on(plugin.id)]


def listing() -> dict:
    """Everything the Plugins tab needs to draw the built-in half."""
    state = _load()
    groups = {}
    for plugin in ALL:
        row = plugin.as_dict()
        row["enabled"] = bool(state.get(plugin.id))
        row["powered_up"] = plugin.powered_up
        row["is_powered_up"] = row["enabled"] and bool(state.get(POWER_PACK))
        groups.setdefault(plugin.group, []).append(row)
    return {
        "ok": True,
        "groups": [
            {"id": key, "name": GROUP_NAMES.get(key, key), "plugins": groups[key]}
            for key in (KIT, LANGUAGES, TOOLS, WORKSPACE, SYSTEM)
            if key in groups
        ],
        "count": len(ALL),
        "enabled": len(enabled_ids()),
        "kit_complete": all(state.get(one) for one in CORE),
    }


def reset() -> dict:
    """Back to the defaults. Used by the tests and by the System screen."""
    global _state
    _state = {plugin.id: plugin.default for plugin in ALL}
    _save()
    return {"ok": True, "enabled": enabled_ids()}
