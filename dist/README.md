# Prebuilt APK

`PyCmd-1.2-debug.apk` — ready to install, nothing else needed.

| | |
|---|---|
| Package | `com.expstudio.pycmd.debug` |
| Version | 1.2-debug |
| Size | 33 MB |
| Signed with | the standard Android debug key |
| Works on | Android 7.0 (API 24) and newer, **arm64-v8a** (every phone since about 2016) |
| SHA-256 | see [SHA256SUMS.txt](SHA256SUMS.txt) |

## What is new in 1.2

**Plugins you write yourself.** A plugin is Python the app imports, plus an
optional HTML panel that becomes its own tab. Install from a file, a folder or
a zip - or from the workspace, for a plugin written inside PyCmd itself. They
are not sandboxed, and the app says so on a screen you have to read before the
picker opens. PLUGINS.md is the authoring guide, and the app can show it on the
phone: Plugins -> How do I write one?

**Preview that behaves like a browser.** A page is served over a loopback HTTP
server rooted at its own folder, so scripts run, stylesheets and images load by
relative path, `fetch` works, and links inside the site follow. Buttons work.
Preview also covers JavaScript (runs it and shows what it logged), JSON, CSV,
SVG and images.

**It offers to fix what it can.** A missing file one typo away from one that
exists, an import of a package that is not installed, a port already in use, a
served folder with no index page: the console says what it would change and
waits for `yes`. It never acts on its own.

**Upload from anywhere.** Files can take several files at once, or a whole
folder, from the system picker.

**Search** in the file list and in the plugin list.

**Two more screens** behind More: Guides (the manuals, on the phone) and System
(versions, storage, what is running, and housekeeping).

## What was checked before this was committed

The same source, built for x86_64, was installed on an Android 11 emulator and
driven through: Go, Rust and JavaScript ran from the Files tab with the right
output, an HTML page previewed with its external stylesheet and script loaded
and its button working, a plugin was installed from the workspace and switched
on, its console command answered, and its panel called back into its own
Python. The APK here is that source built for arm64 instead, which changes
the CPython binaries and nothing else.

479 checks run on a desktop CPython before any of this is committed:
`test_c.py` (54), `test_go.py` (92), `test_rust.py` (73), `test_js.js` (43),
`test_runtime.py` (124), `test_plugins.py` (62) and `test_doctor.py` (31). Each
language check is a real program paired with the output the real compiler
produces.

It is a debug build, so it is already signed and installs without any keystore
or Play Store involvement. It also carries the `.debug` package suffix, which
means it can sit alongside a release build of the same app without either one
replacing the other.

## Installing it on a phone

1. Download the APK onto the phone (or copy it across by USB).
2. Open it from the Files app or the download notification.
3. Android will ask whether to allow installs from this source — that prompt
   appears for any app that did not come from a store. Allow it, then confirm
   the install.
4. Launch **PyCmd**.

The first launch takes a few seconds longer than later ones: the Python
interpreter and its standard library are unpacked on that first run. The title
bar shows `starting` until it is ready, then switches to `Python 3.13.x`.

Once it's running, see [../TUTORIAL.md](../TUTORIAL.md) for a walkthrough of
every tab with things to paste in and try.

## Installing over USB

```bash
adb install -r dist/PyCmd-1.2-debug.apk
```

## Checking the download

```bash
sha256sum -c dist/SHA256SUMS.txt
```

## A note on the device requirement

This APK carries **arm64-v8a** binaries only, which is what keeps it to 32 MB
rather than 46 MB. Every Android phone sold in roughly the last decade is
arm64, so this is the right build for a real device.

Two cases need a different build. A 32-bit-only phone from before about 2016
cannot run it at all: Chaquopy's Python 3.13 runtime ships no 32-bit binaries.
An **x86_64 emulator** needs the x86_64 slice, which the default build
produces:

```bash
./gradlew :app:assembleDebug      # both ABIs, one APK per ABI plus a universal one
```

## Rebuilding it yourself

```bash
./gradlew :app:assembleDebug -Ppycmd.abi=arm64-v8a
# -> app/build/outputs/apk/debug/app-debug.apk
```

Leave the property off to build for both ABIs instead.

See the [main README](../README.md) for what the build needs.
