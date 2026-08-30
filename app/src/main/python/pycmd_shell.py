"""Shell-style commands for the console, in front of Python.

`pip install flask` is not Python. Typed into a REPL it is a syntax error, so
the way to install anything used to be::

    import os
    os.system("pip install flask")

which is three lines of ceremony for the one command everybody already knows -
and on Android it does not even work, because there is no pip binary to run:
the installer lives inside this app. So the console takes the line first.

The rule for what gets taken is deliberately narrow, because a console that
swallows Python is worse than one that does not know `ls`:

* one line only, and the first word has to be a command listed here;
* if that word is a name in your session (`ls = [1, 2]`), Python wins;
* anything that looks like Python - an assignment, a call, a dotted name,
  an import, a keyword - goes to Python untouched.

Everything else runs here, prints like a command should, and never touches
your namespace.
"""

from __future__ import annotations

import os
import shutil
import sys
import time

__all__ = ["handle", "commands", "help_text", "is_command"]

# What the app is asked to do for commands that are not really about files:
# opening the editor, starting a server, switching tabs. Sent through the same
# bridge plugins use, under a reserved id the app always trusts.
SHELL_ID = "pycmd.shell"

# A line starting with any of these is Python, whatever its first word is.
_PYTHON_KEYWORDS = {
    "import", "from", "def", "class", "if", "elif", "else", "for", "while",
    "try", "except", "finally", "with", "return", "yield", "raise", "assert",
    "lambda", "global", "nonlocal", "pass", "break", "continue", "del",
    "async", "await", "print", "not", "in", "is", "and", "or",
}


def _out(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def _err(text: str) -> None:
    sys.stderr.write(text + "\n")


def _size(count: int) -> str:
    if count >= 1024 * 1024 * 1024:
        return f"{count / 1024 / 1024 / 1024:.1f} GB"
    if count >= 1024 * 1024:
        return f"{count / 1024 / 1024:.1f} MB"
    if count >= 1024:
        return f"{count // 1024} KB"
    return f"{count} B"


def _workspace() -> str:
    import pycmd_runtime

    return getattr(pycmd_runtime, "_workspace", None) or os.getcwd()


def _resolve(path: str) -> str:
    """A path as typed, understood the way a shell would understand it."""
    path = os.path.expanduser(path.strip())
    if not path:
        return os.getcwd()
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    return os.path.normpath(path)


def _shorten(path: str) -> str:
    """Paths relative to the workspace, because that is where you are."""
    root = _workspace()
    path = os.path.normpath(path)
    if path == root:
        return "~"
    if path.startswith(root + os.sep):
        return "~/" + path[len(root) + 1:]
    return path


def _ask_app(action: str, **detail) -> bool:
    """Hands the app something only it can do. Never waits for an answer."""
    try:
        import pycmd_plugins

        return pycmd_plugins.app_action(SHELL_ID, action, **detail)
    except Exception:  # noqa: BLE001 - a command must not die over a UI hop
        return False


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def _cmd_ls(args: list) -> int:
    target = _resolve(args[0]) if args else os.getcwd()
    if os.path.isfile(target):
        _out(f"{_shorten(target)}  {_size(os.path.getsize(target))}")
        return 0
    if not os.path.isdir(target):
        _err(f"ls: {args[0] if args else target}: no such file or folder")
        return 1
    names = sorted(os.listdir(target), key=lambda n: (not os.path.isdir(
        os.path.join(target, n)), n.lower()))
    if not names:
        _out("(empty)")
        return 0
    for name in names:
        full = os.path.join(target, name)
        if os.path.isdir(full):
            _out(f"  {name}/")
        else:
            try:
                _out(f"  {name}{' ' * max(1, 28 - len(name))}{_size(os.path.getsize(full))}")
            except OSError:
                _out(f"  {name}")
    return 0


def _cmd_cd(args: list) -> int:
    target = _resolve(args[0]) if args else _workspace()
    if not os.path.isdir(target):
        _err(f"cd: {args[0] if args else target}: not a folder")
        return 1
    try:
        os.chdir(target)
    except OSError as error:
        _err(f"cd: {error}")
        return 1
    _out(_shorten(os.getcwd()))
    return 0


def _cmd_pwd(args: list) -> int:
    _out(os.getcwd())
    return 0


def _read_text(path: str, limit: int = 400_000) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError as error:
        _err(f"cannot read {os.path.basename(path)}: {error}")
        return None


def _cmd_cat(args: list) -> int:
    if not args:
        _err("cat: which file?")
        return 1
    for name in args:
        path = _resolve(name)
        if os.path.isdir(path):
            _err(f"cat: {name} is a folder")
            return 1
        if not os.path.isfile(path):
            _err(f"cat: {name}: no such file")
            return 1
        text = _read_text(path)
        if text is None:
            return 1
        if "\0" in text[:2048]:
            _out(f"{name} is not text - {_size(os.path.getsize(path))} of bytes.")
            continue
        _out(text.rstrip("\n"))
    return 0


def _cmd_head(args: list) -> int:
    return _partial(args, "head")


def _cmd_tail(args: list) -> int:
    return _partial(args, "tail")


def _partial(args: list, which: str) -> int:
    count = 10
    names = []
    for arg in args:
        if arg.startswith("-") and arg[1:].isdigit():
            count = int(arg[1:])
        elif arg.isdigit() and not names:
            count = int(arg)
        else:
            names.append(arg)
    if not names:
        _err(f"{which}: which file?")
        return 1
    path = _resolve(names[0])
    if not os.path.isfile(path):
        _err(f"{which}: {names[0]}: no such file")
        return 1
    text = _read_text(path)
    if text is None:
        return 1
    lines = text.splitlines()
    chosen = lines[:count] if which == "head" else lines[-count:]
    for line in chosen:
        _out(line)
    return 0


def _cmd_mkdir(args: list) -> int:
    if not args:
        _err("mkdir: which folder?")
        return 1
    for name in args:
        path = _resolve(name)
        try:
            os.makedirs(path, exist_ok=True)
            _out(f"made {_shorten(path)}/")
        except OSError as error:
            _err(f"mkdir: {error}")
            return 1
    return 0


def _cmd_touch(args: list) -> int:
    if not args:
        _err("touch: which file?")
        return 1
    for name in args:
        path = _resolve(name)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8"):
                os.utime(path, None)
            _out(f"touched {_shorten(path)}")
        except OSError as error:
            _err(f"touch: {error}")
            return 1
    return 0


def _cmd_rm(args: list) -> int:
    names = [a for a in args if not a.startswith("-")]
    recursive = any(a in ("-r", "-rf", "-fr") for a in args)
    if not names:
        _err("rm: which file? (rm -r for a folder)")
        return 1
    for name in names:
        path = _resolve(name)
        if not os.path.exists(path):
            _err(f"rm: {name}: no such file or folder")
            return 1
        if os.path.isdir(path):
            if not recursive:
                _err(f"rm: {name} is a folder - use rm -r {name}")
                return 1
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError as error:
                _err(f"rm: {error}")
                return 1
        _out(f"removed {_shorten(path)}")
    return 0


def _cmd_mv(args: list) -> int:
    return _move_or_copy(args, "mv")


def _cmd_cp(args: list) -> int:
    return _move_or_copy(args, "cp")


def _move_or_copy(args: list, which: str) -> int:
    names = [a for a in args if not a.startswith("-")]
    if len(names) < 2:
        _err(f"{which}: needs a source and a destination")
        return 1
    source = _resolve(names[0])
    target = _resolve(names[1])
    if not os.path.exists(source):
        _err(f"{which}: {names[0]}: no such file or folder")
        return 1
    if os.path.isdir(target):
        target = os.path.join(target, os.path.basename(source))
    try:
        if which == "mv":
            shutil.move(source, target)
        elif os.path.isdir(source):
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
    except (OSError, shutil.Error) as error:
        _err(f"{which}: {error}")
        return 1
    _out(f"{_shorten(source)}  ->  {_shorten(target)}")
    return 0


def _cmd_find(args: list) -> int:
    if not args:
        _err("find: what are you looking for?")
        return 1
    needle = args[0].lower()
    root = _resolve(args[1]) if len(args) > 1 else os.getcwd()
    hits = 0
    for folder, folders, files in os.walk(root):
        folders[:] = [d for d in folders if not d.startswith(".")]
        for name in files + folders:
            if needle in name.lower():
                _out("  " + _shorten(os.path.join(folder, name)))
                hits += 1
                if hits >= 200:
                    _out("  ... (stopping at 200)")
                    return 0
    if hits == 0:
        _out(f"nothing matching '{args[0]}' under {_shorten(root)}")
    return 0


def _cmd_tree(args: list) -> int:
    root = _resolve(args[0]) if args else os.getcwd()
    if not os.path.isdir(root):
        _err(f"tree: {_shorten(root)} is not a folder")
        return 1
    _out(_shorten(root) + "/")
    shown = 0

    def walk(folder: str, prefix: str, depth: int) -> None:
        nonlocal shown
        if depth > 4 or shown > 300:
            return
        try:
            names = sorted(os.listdir(folder), key=lambda n: (not os.path.isdir(
                os.path.join(folder, n)), n.lower()))
        except OSError:
            return
        names = [n for n in names if not n.startswith(".")]
        for index, name in enumerate(names):
            if shown > 300:
                _out(prefix + "...")
                return
            last = index == len(names) - 1
            full = os.path.join(folder, name)
            _out(prefix + ("└── " if last else "├── ") + name +
                 ("/" if os.path.isdir(full) else ""))
            shown += 1
            if os.path.isdir(full):
                walk(full, prefix + ("    " if last else "│   "), depth + 1)

    walk(root, "", 1)
    return 0


def _cmd_du(args: list) -> int:
    root = _resolve(args[0]) if args else os.getcwd()
    total = 0
    files = 0
    for folder, _folders, names in os.walk(root):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(folder, name))
                files += 1
            except OSError:
                pass
    _out(f"{_shorten(root)}  {_size(total)} in {files} files")
    return 0


def _cmd_echo(args: list) -> int:
    _out(" ".join(args))
    return 0


# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------


def _cmd_pip(args: list) -> int:
    import pycmd_packages

    if not args or args[0] in ("-h", "--help", "help"):
        _out("pip install <name>[==version]   pip uninstall <name>")
        _out("pip list                        pip show <name>")
        _out("pip freeze")
        return 0

    action = args[0]
    rest = [a for a in args[1:] if not a.startswith("-")]

    if action in ("install", "i", "add"):
        if not rest:
            _err("pip: install what?")
            return 1
        failed = 0
        for spec in rest:
            name, _, version = spec.partition("==")
            _out(f"Installing {name}{' ' + version if version else ''}...")

            class _Progress:
                @staticmethod
                def onProgress(message: str) -> None:  # noqa: N802 - Java-side name
                    _out("  " + message)

            result = pycmd_packages.install(name, version or None, _Progress)
            if result.get("ok"):
                _out(f"Installed {result.get('name', name)} {result.get('version', '')}".rstrip())
                _out("  import it straight away - no restart needed.")
            else:
                _err("  " + result.get("error", "could not install that"))
                failed += 1
        return 1 if failed else 0

    if action in ("uninstall", "remove", "rm"):
        if not rest:
            _err("pip: uninstall what?")
            return 1
        for name in rest:
            result = pycmd_packages.uninstall(name)
            if result.get("ok"):
                _out(f"Removed {name}. Anything already imported stays until the "
                     "namespace is reset.")
            else:
                _err("  " + result.get("error", "could not remove that"))
                return 1
        return 0

    if action in ("list", "ls", "freeze"):
        rows = pycmd_packages.installed()
        bundled = pycmd_packages.bundled()
        if action == "freeze":
            for row in rows:
                _out(f"{row['name']}=={row['version']}")
            return 0
        if not rows:
            _out("Nothing installed on the device yet.")
        for row in rows:
            _out(f"  {row['name']:<24} {row['version']}")
        if bundled:
            _out("")
            _out("Built into the app: " + ", ".join(sorted(bundled)))
        return 0

    if action == "show":
        if not rest:
            _err("pip: show what?")
            return 1
        wanted = rest[0].lower()
        for row in pycmd_packages.installed():
            if row["name"].lower() == wanted:
                _out(f"{row['name']} {row['version']}")
                if row.get("summary"):
                    _out(row["summary"])
                _out(f"{row.get('files', 0)} files on the device")
                return 0
        _out(f"{rest[0]} is not installed here. Try: pip install {rest[0]}")
        return 1

    _err(f"pip: no idea what '{action}' means. Try: pip install <name>")
    return 1


# ---------------------------------------------------------------------------
# Running things
# ---------------------------------------------------------------------------


def _cmd_run(args: list) -> int:
    if not args:
        _err("run: which file?")
        return 1
    path = _resolve(args[0])
    if not os.path.isfile(path):
        _err(f"run: {args[0]}: no such file")
        return 1
    import pycmd_runtime

    if args[1:]:
        _out("(arguments are ignored here - run the file from the Servers tab "
             "to pass them)")
    return 0 if pycmd_runtime.run_any(path) == "ok" else 1


def _cmd_serve(args: list) -> int:
    import pycmd_servers

    port = 0
    targets = []
    for arg in args:
        if arg.isdigit():
            port = int(arg)
        elif not arg.startswith("-"):
            targets.append(arg)
    path = _resolve(targets[0]) if targets else os.getcwd()
    if not os.path.exists(path):
        _err(f"serve: {targets[0]}: no such file or folder")
        return 1
    result = pycmd_servers.start_file(path, port=port or pycmd_servers.suggest_port(8000))
    if not result.get("ok"):
        _err("serve: " + result.get("error", "could not start it"))
        return 1
    _out(f"Started {result.get('label', '')} on {result.get('url', '')}".rstrip())
    _out("  Servers tab has its console, and the Kill switch.")
    return 0


def _cmd_servers(args: list) -> int:
    import pycmd_servers

    rows = pycmd_servers.listing()
    if not rows:
        _out("Nothing is running.")
        return 0
    for row in rows:
        _out(f"  {row['handle']}  {row['status']:<8} {row['label']}  {row.get('url', '')}")
    return 0


def _cmd_stop(args: list) -> int:
    import pycmd_servers

    if not args or args[0] in ("all", "-a"):
        result = pycmd_servers.stop_all()
        _out(f"Stopped {result.get('stopped', 0)}.")
        return 0
    result = pycmd_servers.stop(args[0])
    if result.get("ok"):
        _out(f"Stopped {args[0]}.")
        return 0
    _err("stop: " + result.get("error", "could not stop that"))
    return 1


def _cmd_open(args: list) -> int:
    if not args:
        _err("open: which file?")
        return 1
    path = _resolve(args[0])
    if not os.path.exists(path):
        _err(f"open: {args[0]}: no such file")
        return 1
    if _ask_app("open_file", path=path):
        _out(f"Opened {_shorten(path)} in the editor.")
        return 0
    _err("open: the app did not take that.")
    return 1


def _cmd_preview(args: list) -> int:
    if not args:
        _err("preview: which file?")
        return 1
    path = _resolve(args[0])
    if not os.path.exists(path):
        _err(f"preview: {args[0]}: no such file")
        return 1
    if _ask_app("preview", path=path):
        _out(f"Previewing {_shorten(path)}.")
        return 0
    _err("preview: the app did not take that.")
    return 1


def _cmd_go(args: list) -> int:
    if not args:
        _err("go: which tab? console, editor, files, servers, packages, "
             "downloads, plugins, system, guides, debug")
        return 1
    if _ask_app("go_to", tab=args[0].lower()):
        return 0
    _err(f"go: no tab called '{args[0]}'.")
    return 1


def _cmd_clear(args: list) -> int:
    _ask_app("clear_console")
    return 0


# ---------------------------------------------------------------------------
# Telling you about itself
# ---------------------------------------------------------------------------


def _cmd_version(args: list) -> int:
    import pycmd_runtime

    info = pycmd_runtime.runtime_info()
    _out(f"Python {info['version']} on {info['platform']}")
    _out(f"cwd    {info['cwd']}")
    return 0


def _cmd_env(args: list) -> int:
    interesting = ("HOME", "PATH", "PORT", "HOST", "TMPDIR", "LANG",
                   "FLASK_RUN_PORT", "FLASK_RUN_HOST")
    for key in interesting:
        if key in os.environ:
            _out(f"  {key}={os.environ[key]}")
    return 0


def _cmd_which(args: list) -> int:
    if not args:
        _err("which: which command?")
        return 1
    name = args[0]
    target = ALIASES.get(name, (name, []))[0]
    if target in COMMANDS:
        _out(f"{name} is a PyCmd console command - {COMMANDS[target][1]}")
        return 0
    _out(f"{name} is not a console command. If it is a Python name, just type it.")
    return 1


def _cmd_help(args: list) -> int:
    if args:
        name = args[0]
        target = ALIASES.get(name, (name, []))[0]
        if target in COMMANDS:
            if target != name:
                _out(f"{name} means {target} "
                     f"{' '.join(ALIASES[name][1])}".rstrip())
            _out(f"{target}  -  {COMMANDS[target][1]}")
            if COMMANDS[target][2]:
                _out(COMMANDS[target][2])
            return 0
        _err(f"help: nothing here called '{name}'")
        return 1
    _out(help_text())
    return 0


def help_text() -> str:
    """The one screen somebody reads before deciding this console is any good."""
    groups = [
        ("Packages", ["pip"]),
        ("Files", ["ls", "cd", "pwd", "cat", "head", "tail", "mkdir", "touch",
                   "rm", "mv", "cp", "find", "tree", "du"]),
        ("Running", ["run", "serve", "servers", "stop", "open", "preview"]),
        ("The app", ["go", "clear", "version", "env", "which", "help"]),
    ]
    lines = ["Commands (everything else is Python):", ""]
    for title, names in groups:
        lines.append(f"  {title}")
        for name in names:
            lines.append(f"    {name:<10} {COMMANDS[name][1]}")
        lines.append("")
    lines.append("  pip install flask        works exactly like that.")
    lines.append("  Anything Python still is Python: 2 + 2, import os, def f(): ...")
    return "\n".join(lines).rstrip()


# name -> (function, one-line usage, extra help)
COMMANDS = {
    "pip": (_cmd_pip, "install, remove and list Python packages",
            "pip install flask  ·  pip install rich==13.9.4  ·  pip list\n"
            "The installer is inside this app; there is no pip binary on Android."),
    "ls": (_cmd_ls, "what is in a folder", ""),
    "cd": (_cmd_cd, "change folder (no argument goes to the workspace)", ""),
    "pwd": (_cmd_pwd, "where you are", ""),
    "cat": (_cmd_cat, "print a file", ""),
    "head": (_cmd_head, "the first lines of a file  (head -20 notes.md)", ""),
    "tail": (_cmd_tail, "the last lines of a file", ""),
    "mkdir": (_cmd_mkdir, "make a folder", ""),
    "touch": (_cmd_touch, "make an empty file", ""),
    "rm": (_cmd_rm, "delete a file, or a folder with -r", ""),
    "mv": (_cmd_mv, "move or rename", ""),
    "cp": (_cmd_cp, "copy a file or folder", ""),
    "find": (_cmd_find, "search for a name under a folder", ""),
    "tree": (_cmd_tree, "the folder, drawn", ""),
    "du": (_cmd_du, "how much space a folder takes", ""),
    "echo": (_cmd_echo, "print the rest of the line", ""),
    "run": (_cmd_run, "run a file, whatever language it is", ""),
    "serve": (_cmd_serve, "serve a folder or run a project  (serve . 8000)", ""),
    "servers": (_cmd_servers, "what is running", ""),
    "stop": (_cmd_stop, "stop a server by handle, or all of them", ""),
    "open": (_cmd_open, "open a file in the editor", ""),
    "preview": (_cmd_preview, "open a file in the preview", ""),
    "go": (_cmd_go, "switch to another tab", ""),
    "clear": (_cmd_clear, "clear the console", ""),
    "version": (_cmd_version, "what Python this is", ""),
    "env": (_cmd_env, "the environment variables that matter here", ""),
    "which": (_cmd_which, "what a word means to this console", ""),
    "help": (_cmd_help, "this list", ""),
}

# Words people type meaning one of the above. The second half is what the
# alias implies: `install flask` is `pip install flask`, not `pip flask`.
ALIASES = {
    "dir": ("ls", []),
    "l": ("ls", []),
    "ll": ("ls", []),
    "install": ("pip", ["install"]),
    "uninstall": ("pip", ["uninstall"]),
    "packages": ("pip", ["list"]),
    "python": ("run", []),
    "python3": ("run", []),
    "type": ("cat", []),
    "cls": ("clear", []),
    "?": ("help", []),
    "man": ("help", []),
    "kill": ("stop", []),
    "edit": ("open", []),
}


def commands() -> list:
    """Every command name, for completion and for the app's help sheet."""
    return sorted(set(COMMANDS) | set(ALIASES))


def is_command(word: str) -> bool:
    return word in COMMANDS or word in ALIASES


def _split(line: str) -> list:
    """Splits a command line, respecting quotes, without shlex's strictness.

    shlex raises on an unbalanced quote, and a console that answers a typo
    with ValueError has not helped anybody.
    """
    parts = []
    current = []
    quote = ""
    for char in line:
        if quote:
            if char == quote:
                quote = ""
            else:
                current.append(char)
        elif char in "\"'":
            quote = char
        elif char.isspace():
            if current:
                parts.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return parts


# What can follow a name in Python but never follows a command word.
#
# Three characters that look like operators are left out on purpose, because
# after a space they are almost always a path: `.` (cd .., ls ./src), `/`
# (ls /sdcard) and `~` (cat ~/notes.md). A dot or a bracket touching the name
# is still Python - `ls.sort()` never reaches this test.
_PYTHON_NEXT = set("([,=+*%<>!:&|^)]}@")


def _looks_like_python(line: str, head: str) -> bool:
    """Whether this line is Python that merely starts with a command's name.

    The hard case is the one that matters: `ls` is a command and `ls = [1, 2]`
    is an assignment, and they differ only in what comes after the name. So
    look past the spaces - `ls   = 1` is still an assignment - and treat an
    operator there as Python.
    """
    if head in _PYTHON_KEYWORDS:
        return True
    rest = line[len(head):]
    if not rest:
        return False
    if rest[0] not in " \t":
        # `ls(...)`, `ls.x`, `ls[0]`, `lsx` - none of them the command.
        return True
    stripped = rest.lstrip()
    if not stripped:
        return False
    # `ls if x else y` is a conditional expression. Only an exact word counts:
    # `cat or.txt` is a file called or.txt.
    second = stripped.split(None, 1)[0]
    if second in _PYTHON_KEYWORDS or second in ("if", "for", "in", "while"):
        return True
    first = stripped[0]
    if first in _PYTHON_NEXT:
        return True
    if first == "-":
        # The ambiguous one. `ls -l` and `head -3` are flags; `ls - 1` is
        # arithmetic, and the space is the only thing that says which.
        after = stripped[1:2]
        return not (after.isalnum() or after == "-")
    return False


def handle(line: str, taken_names=()) -> dict:
    """Runs `line` as a command, or says it is not one.

    `taken_names` is what the console's namespace already defines: a session
    that did `ls = [1, 2]` means `ls` and should get its list back, not a
    directory listing.
    """
    result = {"handled": False, "status": "ok"}
    try:
        text = line.strip()
        if not text or "\n" in text:
            return result
        parts = _split(text)
        if not parts:
            return result
        head = parts[0]
        if not is_command(head):
            return result
        if head in taken_names:
            return result
        if _looks_like_python(text, head):
            return result

        name, implied = ALIASES.get(head, (head, []))
        function = COMMANDS[name][0]
        started = time.monotonic()
        code = function(implied + parts[1:])
        result["handled"] = True
        result["status"] = "ok" if code == 0 else "error"
        result["seconds"] = round(time.monotonic() - started, 3)
        return result
    except KeyboardInterrupt:
        _err("stopped")
        return {"handled": True, "status": "stopped"}
    except Exception as error:  # noqa: BLE001 - a bad command is not a crash
        _err(f"{type(error).__name__}: {error}")
        return {"handled": True, "status": "error"}
