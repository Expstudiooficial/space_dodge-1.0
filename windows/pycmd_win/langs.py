"""The languages, as they are on Windows.

The shared registry in ``pycmd_langs`` is written for the phone, where a whole
category of language is honestly labelled *editable but not runnable*: Android
has not let an app execute code it generated itself since API 29, so a C++
compiler could produce correct machine code and never run a byte of it.

Windows has no such rule, and this module is the difference. It does two
things to the shared table and nothing else:

* **Re-labels what already runs.** C++, Java, Kotlin, Ruby, PHP, Swift and Lua
  stop saying "no toolchain here" and start saying which toolchain runs them.
* **Adds the ones a phone had no reason to carry.** C#, F#, Haskell, Julia, R,
  Dart, Zig, Nim, Crystal, Elixir, Erlang, Scala, Clojure, OCaml, Racket,
  Fortran, COBOL, Pascal, assembly, PowerShell, batch, and the rest.

The shared table is never mutated. This builds a new list from it, so the
Android build and its tests are unaffected by anything here, and a fix to a
template on one side is a fix on both.
"""

from __future__ import annotations

import os
import sys

_ENGINE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "app", "src", "main", "python",
)
if os.path.isdir(_ENGINE) and _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from pycmd_langs import registry as shared  # noqa: E402

from . import toolchains  # noqa: E402

RUN = shared.RUN
PREVIEW = shared.PREVIEW
EDIT = shared.EDIT
MEDIA = shared.MEDIA

Language = shared.Language


def _note(chain_names: str, extra: str = "") -> str:
    text = f"Runs with {chain_names} if it is installed - the Toolchains screen says whether it is."
    return f"{text} {extra}".strip()


# ---------------------------------------------------------------------------
# What the shared table already has, with the Android caveats lifted.
#
# Keyed by language id. A value of None means "leave it exactly as it is".
# ---------------------------------------------------------------------------

RELABELLED = {
    "pdf": "Opens in the preview and reads properly - the Windows WebView has "
           "a PDF viewer built in, which Android's does not.",
    "c": _note(
        "GCC, Clang or MSVC",
        "With none of them, PyCmd falls back to the C interpreter it carries - "
        "the same one the phone build uses - so a .c file runs either way.",
    ),
    "cpp": _note("G++, Clang++ or MSVC"),
    "go": _note(
        "the real Go toolchain",
        "Without it, the built-in Go interpreter runs the file instead.",
    ),
    "rust": _note(
        "rustc",
        "Without it, the built-in Rust interpreter runs the file instead - that "
        "one does not check ownership, and rustc very much does.",
    ),
    "javascript": _note(
        "Node, Deno or Bun",
        "Without any of them it runs in the app's own JavaScript engine.",
    ),
    "typescript": _note("Deno, Bun or tsc with Node behind it"),
    "java": _note(
        "a JDK",
        "Java 11 and later run a single .java file with no separate compile step.",
    ),
    "kotlin": _note(
        "kotlinc",
        "It compiles to a jar and runs that, which means two JVM starts - the "
        "first run of a file takes a while.",
    ),
    "ruby": _note("Ruby"),
    "php": _note("PHP"),
    "swift": _note("the Swift toolchain for Windows"),
    "lua": _note("Lua"),
    "sql": _note("sqlite3", "The script runs against an in-memory database."),
    "shell": (
        "Windows has no /bin/sh of its own, but Git for Windows brings one and "
        "so does WSL. With either installed a .sh file runs; without one, "
        "PowerShell and .bat files are the native way round."
    ),
    "dockerfile": (
        "Kept, highlighted and servable. Building it needs Docker Desktop, which "
        "PyCmd does not drive."
    ),
    "makefile": _note("GNU make, if it is on your PATH"),
}

# Which languages become runnable once a toolchain exists for them.
_NOW_RUNS = {
    "cpp", "java", "kotlin", "ruby", "php", "swift", "lua", "sql", "typescript",
}


def _clone(language, mode=None, note=None):
    return Language(
        language.id, language.name, list(language.extensions),
        mode if mode is not None else language.mode,
        language.highlight, language.comment, language.template,
        note if note is not None else language.note,
        language.mime,
    )


# ---------------------------------------------------------------------------
# The new ones.
# ---------------------------------------------------------------------------

NEW = [
    Language(
        "csharp", "C#", [".cs"], RUN, "c", "//",
        template=(
            'using System;\n\nclass Program\n{\n'
            '    static void Main()\n    {\n'
            '        Console.WriteLine("hello");\n    }\n}\n'
        ),
        note=_note(
            "the .NET SDK",
            "A .cs file wants a project around it; PyCmd writes a minimal "
            ".csproj beside it the first time you press Run.",
        ),
    ),
    Language(
        "fsharp", "F#", [".fs", ".fsx"], RUN, "c", "//",
        template='printfn "hello"\n',
        note=_note("the .NET SDK", "Run through F# Interactive, so no project is needed."),
    ),
    Language(
        "visualbasic", "Visual Basic", [".vb"], EDIT, "c", "'",
        template=(
            'Module Program\n    Sub Main()\n'
            '        Console.WriteLine("hello")\n    End Sub\nEnd Module\n'
        ),
        note=_note("the .NET SDK", "Needs a project, the same as C#."),
    ),
    Language(
        "haskell", "Haskell", [".hs", ".lhs"], RUN, "python", "--",
        template='main :: IO ()\nmain = putStrLn "hello"\n',
        note=_note("GHC (runghc)"),
    ),
    Language(
        "julia", "Julia", [".jl"], RUN, "python", "#",
        template='println("hello")\n', note=_note("Julia"),
    ),
    Language(
        # Just ".r": extensions are matched lowercased, so listing ".R" beside
        # it is the same entry twice and hides whichever came second.
        "r", "R", [".r"], RUN, "python", "#",
        template='cat("hello\\n")\n', note=_note("R (Rscript)"),
    ),
    Language(
        "dart", "Dart", [".dart"], RUN, "c", "//",
        template='void main() {\n  print("hello");\n}\n', note=_note("the Dart SDK"),
    ),
    Language(
        "zig", "Zig", [".zig"], RUN, "c", "//",
        template=(
            'const std = @import("std");\n\n'
            'pub fn main() !void {\n'
            '    std.debug.print("hello\\n", .{});\n}\n'
        ),
        note=_note("Zig"),
    ),
    Language(
        "nim", "Nim", [".nim"], RUN, "python", "#",
        template='echo "hello"\n', note=_note("Nim"),
    ),
    Language(
        "crystal", "Crystal", [".cr"], RUN, "python", "#",
        template='puts "hello"\n', note=_note("Crystal"),
    ),
    Language(
        "elixir", "Elixir", [".ex", ".exs"], RUN, "python", "#",
        template='IO.puts("hello")\n', note=_note("Elixir"),
    ),
    Language(
        "erlang", "Erlang", [".erl"], RUN, "python", "%",
        template=(
            'main(_) ->\n    io:format("hello~n").\n'
        ),
        note=_note("Erlang (escript)", "The file needs a `main/1` function."),
    ),
    Language(
        "scala", "Scala", [".scala", ".sc"], RUN, "c", "//",
        template='@main def run(): Unit = println("hello")\n', note=_note("Scala"),
    ),
    Language(
        "clojure", "Clojure", [".clj", ".cljs", ".cljc"], RUN, "python", ";",
        template='(println "hello")\n', note=_note("the Clojure CLI"),
    ),
    Language(
        "ocaml", "OCaml", [".ml", ".mli"], RUN, "python", "(*",
        template='let () = print_endline "hello"\n', note=_note("OCaml"),
    ),
    Language(
        "racket", "Racket", [".rkt"], RUN, "python", ";",
        template='#lang racket\n(displayln "hello")\n', note=_note("Racket"),
    ),
    Language(
        "scheme", "Scheme", [".scm", ".ss"], RUN, "python", ";",
        template='(display "hello")\n(newline)\n', note=_note("Guile"),
    ),
    Language(
        "fortran", "Fortran", [".f90", ".f95", ".f03", ".f"], RUN, "python", "!",
        template=(
            "program hello\n    print *, 'hello'\nend program hello\n"
        ),
        note=_note("gfortran"),
    ),
    Language(
        "cobol", "COBOL", [".cob", ".cbl"], RUN, "python", "*",
        template=(
            "IDENTIFICATION DIVISION.\nPROGRAM-ID. HELLO.\n"
            "PROCEDURE DIVISION.\n    DISPLAY 'hello'.\n    STOP RUN.\n"
        ),
        note=_note("GnuCOBOL (cobc)", "Compiled in free format."),
    ),
    Language(
        "pascal", "Pascal", [".pas", ".pp"], RUN, "python", "//",
        template=(
            "program Hello;\nbegin\n  writeln('hello');\nend.\n"
        ),
        note=_note("Free Pascal"),
    ),
    Language(
        "d", "D", [".d"], RUN, "c", "//",
        template='import std.stdio;\n\nvoid main() {\n    writeln("hello");\n}\n',
        note=_note("DMD"),
    ),
    Language(
        "vlang", "V", [".v"], RUN, "c", "//",
        template='fn main() {\n\tprintln("hello")\n}\n', note=_note("V"),
    ),
    Language(
        "groovy", "Groovy", [".groovy", ".gvy"], RUN, "c", "//",
        template='println "hello"\n', note=_note("Groovy"),
    ),
    Language(
        "objectivec", "Objective-C", [".m"], EDIT, "c", "//",
        template=(
            '#import <stdio.h>\n\nint main(void) {\n    printf("hello\\n");\n'
            '    return 0;\n}\n'
        ),
        note=_note(
            "Clang",
            "Objective-C without Apple's frameworks is a narrow thing on "
            "Windows: the C parts build, Foundation does not.",
        ),
    ),
    Language(
        "assembly", "Assembly (x86-64)", [".asm", ".s"], EDIT, "python", ";",
        template=(
            "section .text\n    global main\nmain:\n"
            "    mov rax, 0\n    ret\n"
        ),
        note=_note(
            "NASM",
            "PyCmd assembles to a .obj and stops there - linking one into "
            "something runnable is a choice of linker you should make.",
        ),
    ),
    Language(
        "powershell", "PowerShell", [".ps1", ".psm1"], RUN, "shell", "#",
        template='Write-Host "hello"\n',
        note="Runs on the PowerShell that ships with Windows. PyCmd passes "
             "-ExecutionPolicy Bypass so a script you just wrote will run.",
    ),
    Language(
        "batch", "Batch", [".bat", ".cmd"], RUN, "shell", "REM",
        template='@echo off\necho hello\n',
        note="Runs on cmd.exe, which every Windows has.",
    ),
    Language(
        "perl", "Perl", [".pl", ".pm"], RUN, "python", "#",
        template='print "hello\\n";\n', note=_note("Perl"),
    ),
    Language(
        "tcl", "Tcl", [".tcl"], RUN, "python", "#",
        template='puts "hello"\n', note=_note("tclsh"),
    ),
    Language(
        "awk", "AWK", [".awk"], RUN, "python", "#",
        template='BEGIN { print "hello" }\n', note=_note("gawk"),
    ),
    Language(
        "prolog", "Prolog", [".pro", ".pl0"], RUN, "python", "%",
        template='main :- write(\'hello\'), nl.\n',
        note=_note("SWI-Prolog", "The file needs a `main` predicate."),
    ),
]


def _build():
    out = []
    seen = set()
    for language in shared.LANGUAGES:
        note = RELABELLED.get(language.id, language.note)
        mode = RUN if language.id in _NOW_RUNS else language.mode
        out.append(_clone(language, mode=mode, note=note))
        seen.add(language.id)
    for language in NEW:
        if language.id in seen:
            continue
        out.append(language)
        seen.add(language.id)
    return out


LANGUAGES = _build()

_BY_ID = {language.id: language for language in LANGUAGES}
_BY_EXTENSION = {}
for _language in LANGUAGES:
    for _extension in _language.extensions:
        # First one wins, so a later language cannot quietly steal an
        # extension the phone build already gives to something else.
        _BY_EXTENSION.setdefault(_extension.lower(), _language)


def by_id(language_id: str):
    return _BY_ID.get(language_id)


def for_path(path: str) -> dict:
    """What this file is. Falls back to plain text, never to nothing."""
    name = os.path.basename(path).lower()
    # A few files are known by their whole name rather than an extension.
    if name in ("makefile", "dockerfile", ".gitignore"):
        special = {"makefile": "makefile", "dockerfile": "dockerfile",
                   ".gitignore": "gitignore"}[name]
        found = _BY_ID.get(special)
        if found:
            return found.as_dict()
    extension = os.path.splitext(name)[1]
    found = _BY_EXTENSION.get(extension) or _BY_ID["text"]
    return found.as_dict()


def catalogue() -> list:
    """Every language, for the new-file menu and the Toolchains screen."""
    rows = []
    for language in LANGUAGES:
        row = language.as_dict()
        chains = toolchains.for_language(language.id)
        row["toolchains"] = [chain.id for chain in chains]
        row["toolchain_names"] = [chain.name for chain in chains]
        rows.append(row)
    return rows


def runnable_ids() -> list:
    return [language.id for language in LANGUAGES if language.mode == RUN]


def stats() -> dict:
    modes = {}
    for language in LANGUAGES:
        modes[language.mode] = modes.get(language.mode, 0) + 1
    return {
        "total": len(LANGUAGES),
        "runnable": modes.get(RUN, 0),
        "preview": modes.get(PREVIEW, 0),
        "editable": modes.get(EDIT, 0),
        "media": modes.get(MEDIA, 0),
    }
