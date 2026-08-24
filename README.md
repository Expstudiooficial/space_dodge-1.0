# PyCmd

A Python command line for Android. Write and run Python on the phone itself —
no server, no connection, no desktop involved.

Version 1.0. Kotlin and Jetpack Compose for the app, JavaScript for the console
and editor, CPython 3.13 embedded through [Chaquopy](https://chaquo.com/chaquopy/).

---

## What it does

**Console** — a real REPL. Type an expression and its value is printed back;
type a block and it runs. Output streams in as it is produced rather than
appearing all at once when the script ends, `input()` prompts you and waits,
and Stop interrupts a runaway loop. Terminal colours from libraries like `rich`
render properly. Completions for names in your session appear as you type.

**Editor** — a code editor with Python syntax highlighting, line numbers,
auto-indent, bracket matching, and a shortcut row for the characters phone
keyboards hide. Run the open file straight from the toolbar.

**Files** — a private workspace you can browse, create in, rename, delete, and
import into from anywhere on the device. Ten example scripts are there on
first launch, covering the console, the editor, packages and servers.

**Packages** — install pure-Python libraries from PyPI onto the device at
runtime. `requests`, `flask` and `rich` are already built in.

**Servers** — a launch form: serve a folder or run a script, pick the port
(with a "free one" button that finds an unused one), name it, choose whether it
is reachable on Wi-Fi or loopback only. Every server gets its own console with
its own scrollback and its own stdin box, and a **Kill** switch beside Stop for
when a script hangs before it ever finishes starting. Servers stay alive in the
background while you use other apps.

**Debug console** — one tap from anywhere in the top bar. Interpreter
lifecycle, server events, package installs, file errors, WebView JavaScript
errors and uncaught Java exceptions, with level filters, text search,
expandable stack traces, copy-all and save-to-workspace.

---

## Just want to try it

A ready-to-install debug APK is in [`dist/`](dist/) - download
[`PyCmd-1.1-debug.apk`](dist/PyCmd-1.1-debug.apk), open it on the phone, and
allow the install when Android asks. It is signed with the standard debug key,
so no keystore or store account is involved. See [dist/README.md](dist/README.md)
for the details.

Once it's installed, **[TUTORIAL.md](TUTORIAL.md)** walks through every tab
with ready-to-paste snippets — console one-liners, a script that uses the
Stop button, one that reads and writes a file, one that hits the network,
one with colour output, and how to serve a folder over Wi-Fi. Ten example
scripts covering the same ground also ship inside the app under
`Files → examples/`.

---

## Building

You need the Android SDK (platform 35), JDK 17 or newer, and a CPython **3.13**
on `PATH` as `python3.13` — Chaquopy uses it to resolve the pip requirements at
build time.

```bash
git clone https://github.com/Expstudiooficial/space_dodge-1.0.git
cd space_dodge-1.0
echo "sdk.dir=/path/to/android-sdk" > local.properties

./gradlew :app:assembleDebug
```

The APK lands in `app/build/outputs/apk/debug/app-debug.apk`.

If your Python 3.13 lives somewhere unusual:

```bash
./gradlew :app:assembleDebug -Ppycmd.buildPython=/usr/local/bin/python3.13
```

A release build (`./gradlew :app:assembleRelease`) produces an unsigned APK; add
a signing config before shipping it anywhere.

### Requirements on the device

Android 7.0 (API 24) or newer, on **arm64-v8a or x86_64**. Chaquopy's Python 3.13
runtime does not ship 32-bit binaries, which matters only for phones from before
about 2016.

The APK is large because a complete CPython interpreter and standard library are
inside it. The default build produces one APK per ABI plus a universal one
(36 MB each, 46 MB universal); `-Ppycmd.abi=arm64-v8a` drops the x86_64 runtime
that no phone can use and gives a single 33 MB APK, which is what `dist/` ships.

---

## Testing

```bash
tools/run-tests.sh
```

That runs three things: the embedded Python modules against a stand-in for the
Kotlin bridge (execution, error reporting, stdin, interrupt-and-recover,
completions, a real install/import/uninstall round trip against PyPI and a real
HTTP server), the WebView JavaScript under Node against a stub document, and a
debug build with Android Lint.

The suites can also be run on their own:

```bash
python3.13 tools/test_runtime.py
node tools/test_js.js
```

### What has been checked on a device

The shipped build was installed on an Android 11 x86_64 emulator and driven
through the UI. Confirmed there: the app launches without crashing, CPython
3.13.9 starts and reports itself in the title bar, the console and editor
WebViews render, the editor highlights Python and reports the caret position
back through the JS bridge, and pressing Run executes the buffer and streams
its output into the console.

The Servers tab was then driven end to end on the same emulator: choosing a
folder through the Files picker, launching it, confirming at the OS level that
the port was in `LISTEN`, fetching a real directory listing over HTTP through
an adb forward (200, with both requests appearing in that server's console),
then pressing Kill and confirming the port was released.

That is still not exhaustive. The emulator ran under software translation with
no hardware acceleration, so nothing about performance there means anything.
Installing a package from PyPI, reaching a server from another device over
real Wi-Fi, and the background-server notification have been tested only
against host CPython, not on a device.

---

## How it fits together

```
Compose UI  ──┬── ConsoleScreen ──┐
              ├── EditorScreen  ──┤   WebViews (assets/web/*.js)
              ├── FilesScreen     │   console + ANSI renderer, code editor
              ├── PackagesScreen  │
              ├── ServersScreen   │   launch form + one console per server
              └── DebugScreen ────┘   DebugLog (util/)
                     │
              MainViewModel
                     │
              PythonEngine (Kotlin)
                     │
       python-main ──┴── python-control      one interpreter thread, plus a
       runs code         stops and kills     second so stop/kill always land
                     │
       ┌─────────────┼──────────────┐
  pycmd_runtime  pycmd_packages  pycmd_servers      (src/main/python/*.py)
   execution      wheel installs   background listeners
   + channels                      + kill switch
                     │
              CPython 3.13 (Chaquopy)
```

A few decisions worth knowing about if you are changing this code:

**Python lives on one thread.** CPython keeps per-thread state, so every call
into the interpreter is funnelled onto a single executor. A second run cannot
start until the first returns, which is exactly what a console wants anyway.

**Stop uses `PyThreadState_SetAsyncExc`.** CPython cannot kill a thread
outright. Raising `KeyboardInterrupt` into the running thread through the C API
costs nothing while code runs; the alternative — a trace hook checking a flag on
every line — makes all Python about 1.8× slower. The trace hook is still there
as a fallback, and the engine probes the fast path at startup rather than
assuming it works. The mechanism actually in use is shown in the About dialog.

**Stop requests come from their own thread.** They cannot queue behind the code
they are trying to stop, and they must not block the UI thread waiting for the
GIL.

**The editor is a textarea over a highlighted `<pre>`.** The transparent
textarea keeps the platform caret, selection handles, IME and clipboard — all
things a hand-rolled editor gets subtly wrong — while the layer underneath
supplies the colour. The two only line up because both take their font metrics
and padding from the same CSS variables.

**The icons are hand-defined, not a library.** `material-icons-extended` ships
five complete icon styles and accounted for 13.7 MB of the 24 MB dex - over half
- to supply the twenty-nine glyphs this app draws. A debug build does no
shrinking, so all of that rode along into the download. `ui/PyIcons.kt` defines
those twenty-nine as Material path data instead.

**Output is channelled.** `sys.stdout` is one global object, so a server
running on its own thread would otherwise print into the main console. Every
write is tagged with the channel registered for the writing thread, and each
channel has its own stdin queue — which is what lets a server prompt for input
without stealing what you typed into the console.

**Stop and kill run off the interpreter thread.** Queued behind the code they
are trying to stop, they would never arrive, and that is precisely when they
are needed. Stop asks the server to close and waits; Kill closes the socket
(freeing the port even if the thread is wedged in a blocking call), raises
`SystemExit` inside the thread, and stops tracking it either way.

**Both WebViews outlive their tab.** They are created once and re-attached on
each tab switch, so console history and editor scroll position survive. The
editor tracks which document it currently holds so returning to the tab does not
throw the caret back to the top. They are also given explicit match-parent
layout params: without them the view is added as wrap-content, the page's
`height: 100%` resolves against a strip a couple of hundred pixels tall, and the
console scrolls nearly all of its output off the top of a viewport barely one
line high.

---

## Installing packages on the device

The Packages tab downloads universal wheels (`py3-none-any`) from PyPI and
unpacks them into a writable `site-packages` on `sys.path`. Wheel entries with
absolute or parent-escaping paths are refused rather than extracted.

`package` and `package==1.2.3` both work, the same spelling pip uses.

**What cannot be installed this way:** anything with compiled C extensions —
`pygame`, `scipy`, `pandas`, `lxml` and similar. Those need wheels built against
the Android NDK for the exact ABI and Python version; there is nothing on PyPI
for a phone to fetch. `numpy` and `pillow` are available as Android builds and
can be added to the `pip` block in `app/build.gradle.kts` at build time, which
bakes them into the APK.

---

## Layout

```
app/src/main/
  java/com/expstudio/pycmd/
    MainActivity.kt          entry point, notification permission
    PyCmdApp.kt              notification channel
    python/
      PythonEngine.kt        the interpreter bridge and its threading
      ServerService.kt       foreground service that keeps servers alive
    ui/                      Compose screens, theme, WebView hosting, icons
    util/Workspace.kt        file operations, all confined to the workspace
    util/DebugLog.kt         the process-wide record behind the debug console
  python/
    pycmd_runtime.py         execution, streams, interrupt, completions
    pycmd_packages.py        on-device wheel installs
    pycmd_servers.py         background listeners
  assets/
    web/                     console and editor pages, ANSI and highlighting
    examples/                scripts seeded into the workspace on first launch
tools/                       host-side test suites
```

---

## Licence

MIT. See [LICENSE](LICENSE).
