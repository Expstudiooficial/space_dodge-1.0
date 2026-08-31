#!/usr/bin/env python3
"""Actually compiles and runs something in every language this machine can.

`test_windows.py` checks that the toolchain table is coherent - unique ids,
real placeholders, an install line for everything. It cannot check that the
commands *work*, because that needs the compilers.

This does. For every toolchain it finds installed, it writes a hello-world in
that language, runs it through the same `plan_for` the Run button uses, and
insists the program's own words come back. A toolchain whose arguments are
subtly wrong - a flag that moved, an output path in the wrong place - fails
here and nowhere else.

What it checks depends on what is installed, and that is the point: on the
Windows CI runner it covers whatever that image ships, on a developer's
machine it covers whatever they have, and on a bare machine it says so and
passes rather than pretending.

    python tools/test_toolchains_live.py
    python tools/test_toolchains_live.py --list
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "windows"))
sys.path.insert(0, os.path.join(ROOT, "app", "src", "main", "python"))

from pycmd_win import langs, toolchains  # noqa: E402

WORD = "pycmdlives"

# One program per language, each printing WORD and nothing else. Written out
# rather than generated from the registry's templates on purpose: a template
# is there to start somebody off and may print anything, and this needs to
# know exactly what to look for.
PROGRAMS = {
    "python": ("hello.py", f'print("{WORD}")\n'),
    "javascript": ("hello.js", f'console.log("{WORD}");\n'),
    "typescript": ("hello.ts", f'const w: string = "{WORD}";\nconsole.log(w);\n'),
    "c": ("hello.c", f'#include <stdio.h>\nint main(void){{printf("{WORD}\\n");return 0;}}\n'),
    "cpp": ("hello.cpp", f'#include <iostream>\nint main(){{std::cout<<"{WORD}"<<std::endl;}}\n'),
    "go": ("hello.go", f'package main\nimport "fmt"\nfunc main(){{fmt.Println("{WORD}")}}\n'),
    "rust": ("hello.rs", f'fn main(){{println!("{WORD}");}}\n'),
    "java": ("Hello.java",
             f'public class Hello{{public static void main(String[] a)'
             f'{{System.out.println("{WORD}");}}}}\n'),
    "kotlin": ("hello.kt", f'fun main() {{ println("{WORD}") }}\n'),
    "ruby": ("hello.rb", f'puts "{WORD}"\n'),
    "php": ("hello.php", f'<?php echo "{WORD}\\n";\n'),
    "perl": ("hello.pl", f'print "{WORD}\\n";\n'),
    "lua": ("hello.lua", f'print("{WORD}")\n'),
    "r": ("hello.r", f'cat("{WORD}\\n")\n'),
    "julia": ("hello.jl", f'println("{WORD}")\n'),
    "haskell": ("hello.hs", f'main :: IO ()\nmain = putStrLn "{WORD}"\n'),
    "dart": ("hello.dart", f'void main() {{ print("{WORD}"); }}\n'),
    "zig": ("hello.zig",
            f'const std = @import("std");\npub fn main() !void '
            f'{{ std.debug.print("{WORD}\\n", .{{}}); }}\n'),
    "nim": ("hello.nim", f'echo "{WORD}"\n'),
    "crystal": ("hello.cr", f'puts "{WORD}"\n'),
    "elixir": ("hello.exs", f'IO.puts("{WORD}")\n'),
    "scala": ("hello.scala", f'@main def run(): Unit = println("{WORD}")\n'),
    "ocaml": ("hello.ml", f'let () = print_endline "{WORD}"\n'),
    "racket": ("hello.rkt", f'#lang racket\n(displayln "{WORD}")\n'),
    "scheme": ("hello.scm", f'(display "{WORD}")(newline)\n'),
    "fortran": ("hello.f90", f"program h\n  print *, '{WORD}'\nend program h\n"),
    "pascal": ("hello.pas", f"program h;\nbegin\n  writeln('{WORD}');\nend.\n"),
    "cobol": ("hello.cob",
              "IDENTIFICATION DIVISION.\nPROGRAM-ID. H.\nPROCEDURE DIVISION.\n"
              f"    DISPLAY '{WORD}'.\n    STOP RUN.\n"),
    "d": ("hello.d", f'import std.stdio;\nvoid main(){{writeln("{WORD}");}}\n'),
    "vlang": ("hello.v", f'fn main() {{\n\tprintln("{WORD}")\n}}\n'),
    "groovy": ("hello.groovy", f'println "{WORD}"\n'),
    "powershell": ("hello.ps1", f'Write-Host "{WORD}"\n'),
    "batch": ("hello.bat", f"@echo off\necho {WORD}\n"),
    "shell": ("hello.sh", f'echo "{WORD}"\n'),
    "tcl": ("hello.tcl", f'puts "{WORD}"\n'),
    "awk": ("hello.awk", f'BEGIN {{ print "{WORD}" }}\n'),
    "prolog": ("hello.pro", f"main :- write('{WORD}'), nl.\n"),
    "erlang": ("hello.erl", f'main(_) ->\n    io:format("{WORD}~n").\n'),
    "sql": ("hello.sql", f"SELECT '{WORD}';\n"),
    "fsharp": ("hello.fsx", f'printfn "{WORD}"\n'),
}

FAILURES = []
SKIPPED = []
RAN = []


def run_one(folder: str, language_id: str, chain) -> tuple:
    """Builds and runs one program. Returns (ok, what happened)."""
    name, source = PROGRAMS[language_id]
    path = os.path.join(folder, language_id, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)

    plan = toolchains.plan_for(path, language_id, prefer=chain.id)
    if not plan.get("ok"):
        return False, plan.get("error", "no plan")
    if plan["toolchain"] != chain.id:
        return False, f"asked for {chain.id}, got {plan['toolchain']}"

    output = ""
    for command in plan["commands"]:
        try:
            finished = subprocess.run(
                command, cwd=plan["cwd"], capture_output=True, text=True,
                timeout=300, stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return False, f"{command[0]} vanished between finding it and running it"
        except subprocess.TimeoutExpired:
            return False, "it did not finish in five minutes"
        output += (finished.stdout or "") + (finished.stderr or "")
        if finished.returncode != 0:
            return False, f"exit {finished.returncode}: {output.strip()[:180]}"

    if WORD not in output:
        return False, f"it ran but did not say so: {output.strip()[:180]}"
    return True, "ok"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true",
                        help="say what is installed and stop")
    args = parser.parse_args(argv)

    installed = [c for c in toolchains.TOOLCHAINS if toolchains.detect(c.id).get("path")]

    if args.list:
        for chain in toolchains.TOOLCHAINS:
            found = toolchains.detect(chain.id)
            mark = "yes" if found.get("path") else " - "
            print(f"  {mark}  {chain.name:<24} {found.get('version', ''):<16} "
                  f"{', '.join(chain.languages)}")
        return 0

    print(f"== running real programs with what is installed "
          f"({len(installed)} of {len(toolchains.TOOLCHAINS)} toolchains) ==")

    if not installed:
        print("  nothing is installed, so there is nothing to check here.")
        print("  PyCmd still runs Python, C, Go, Rust and JavaScript on its own "
              "interpreters.")
        return 0

    folder = tempfile.mkdtemp(prefix="pycmd-live-")
    for chain in installed:
        for language_id in chain.languages:
            if language_id not in PROGRAMS:
                SKIPPED.append(f"{chain.id}/{language_id} (no sample program)")
                continue
            ok, detail = run_one(folder, language_id, chain)
            RAN.append(language_id)
            if ok:
                print(f"  PASS  {language_id:<12} via {chain.name}")
            else:
                FAILURES.append((chain.id, language_id, detail))
                print(f"  FAIL  {language_id:<12} via {chain.name}  - {detail}")

    print()
    if SKIPPED:
        print(f"{len(SKIPPED)} not checked: {', '.join(SKIPPED[:6])}")
    if FAILURES:
        print(f"{len(FAILURES)} of {len(RAN)} failed")
        return 1
    print(f"all {len(RAN)} languages that could be checked here ran and said so")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
