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
import into from anywhere on the device. Five example scripts are there on first
launch.

**Packages** — install pure-Python libraries from PyPI onto the device at
runtime. `requests`, `flask` and `rich` are already built in.

**Servers** — serve a folder over your Wi-Fi network, or run a script that
listens on a port, and keep it alive in the background while you use other apps.

---

## Just want to try it

A ready-to-install debug APK is in [`dist/`](dist/) - download
[`PyCmd-1.0-debug.apk`](dist/PyCmd-1.0-debug.apk), open it on the phone, and
allow the install when Android asks. It is signed with the standard debug key,
so no keystore or store account is involved. See [dist/README.md](dist/README.md)
for the details.

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

The APK is large — roughly 49 MB — because a complete CPython interpreter and
standard library are inside it, twice, once per ABI.

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

---

## How it fits together

```
Compose UI  ──┬── ConsoleScreen ──┐
              ├── EditorScreen  ──┤     WebViews (assets/web/*.js)
              ├── FilesScreen     │     console + ANSI renderer, code editor
              ├── PackagesScreen  │
              └── ServersScreen ──┘
                     │
              MainViewModel
                     │
              PythonEngine (Kotlin)  ── one dedicated thread
                     │
       ┌─────────────┼──────────────┐
  pycmd_runtime  pycmd_packages  pycmd_servers      (src/main/python/*.py)
   execution      wheel installs   background listeners
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

**Both WebViews outlive their tab.** They are created once and re-attached on
each tab switch, so console history and editor scroll position survive. The
editor tracks which document it currently holds so returning to the tab does not
throw the caret back to the top.

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
    ui/                      Compose screens, theme, WebView hosting
    util/Workspace.kt        file operations, all confined to the workspace
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
