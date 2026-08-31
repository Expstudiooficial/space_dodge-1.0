# PyCmd for Windows

`PyCmd.exe` — one file, nothing to install.

| | |
|---|---|
| Version | 1.0.0 |
| Works on | Windows 10 and newer, 64-bit |
| Runtime | Edge WebView2, which Windows 10 and 11 already have |
| Installer | none — it is one exe |
| Admin rights | none |
| Keeps things in | `%LOCALAPPDATA%\PyCmd` |
| SHA-256 | see [SHA256SUMS.txt](SHA256SUMS.txt) |

## Is there an exe here yet?

Check `latest.json`. If its `sha256` is empty, the manifest is **seeded** —
the version is decided and the address is fixed, but nobody has built it yet.
The app treats that correctly: it will not offer an update it cannot verify,
and it refuses any download without a checksum.

To make one:

- **On your own machine:**
  `powershell -ExecutionPolicy Bypass -File windows\build\build.ps1`
- **Or push a tag** `windows-v1.0.0` and let the workflow do it — it builds on
  a Windows runner, proves the exe starts, writes this manifest with the real
  hash, and attaches the exe to a release.

## What is new in 1.0.0

**The whole of PyCmd 2.5.9, as a Windows program, with the restriction that
shaped it removed.**

Android has not let an app execute code it compiled itself since API 29. That
one rule is why the phone build carries hand-written interpreters for C, Go
and Rust, and why a dozen other languages are honestly labelled "you can edit
and serve this, but not run it". Windows has no such rule, and this build is
what PyCmd looks like without it.

**65 file types, 43 of them runnable** — up from 34 and 6. Thirty-one
languages the phone had no reason to carry: C#, F#, Visual Basic, Haskell,
Julia, R, Dart, Zig, Nim, Crystal, Elixir, Erlang, Scala, Clojure, OCaml,
Racket, Scheme, Fortran, COBOL, Pascal, D, V, Groovy, Objective-C, assembly,
PowerShell, batch, Perl, Tcl, AWK and Prolog.

**51 toolchains it knows how to find and drive.** The Toolchains screen says
which are installed and what version, and for the rest gives the exact
`winget`, `scoop` or `choco` line with a button that runs it. PyCmd bundles no
compilers — a build carrying MSVC and a JDK would be gigabytes — so that
button runs your own package manager with the line you would have typed.

**The interpreters are still there, as the fallback.** With nothing installed,
a `.go` file still runs on day one. Install Go and the same file runs on the
real thing. The console says which one every time, because it matters: the
built-in Go interpreter does not enforce types and the built-in Rust one has
no borrow checker.

**Everything else came across.** The console with its shell, the editor, the
workspace, servers, pages, Cloudflare deploys, packages, the five bundled
plugins — Cloud, Creator, Packages Pro, Scheduler, Server Pro — and all
thirteen built-in ones, with the same ids the phone uses.

**Bring a plugin over from the phone.** A beta, and specifically so: PyCmd
reads the plugin before installing it and names exactly what this machine
cannot honour — Android permissions, `/storage` paths, `java` imports. A
plugin with none of those is reported as "should work", and it does.

**Where things live.** `%LOCALAPPDATA%\PyCmd` — ordinary folders you can open,
back up or put in git. Nothing is written to Program Files and nothing needs
administrator rights. Set `PYCMD_HOME` and the whole thing is portable.

**Its own update channel.** `dist-windows/latest.json`, separate from the
APK's. The Windows build will never offer you an APK.

### How much of this is actually new code

About 3,000 lines against 21,000 shared. The engine, the interpreters,
`console.js`, `editor.js`, every bundled plugin and the whole plugin API are
the same files the phone loads. What is Windows-only is where files live,
which compilers exist, how a run is planned, and the window itself.

### What was left out

**The Music tab.** The library and playlists would have ported fine; the half
that mattered was Android's media session drawing controls on a lock screen
and in quick settings, and Windows has no equivalent worth imitating.

### Verification

80 checks in `tools/test_windows.py`, which run anywhere. Sixteen languages —
Python, JavaScript, TypeScript, C, C++, Go, Rust, Java, Ruby, PHP, Perl, Bash
and more — compiled and ran through the real planner during development, and
`tools/test_toolchains_live.py` repeats that on any machine for whatever it
has. The interface was driven end to end in a browser against the real
backend.

What could not be checked without Windows: that the exe opens, and that
WebView2 renders it. The CI workflow does both on a Windows runner.
