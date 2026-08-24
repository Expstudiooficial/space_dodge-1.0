# Prebuilt APK

`PyCmd-1.1-debug.apk` — ready to install, nothing else needed.

| | |
|---|---|
| Package | `com.expstudio.pycmd.debug` |
| Version | 1.1-debug |
| Size | 33 MB |
| Signed with | the standard Android debug key |
| Works on | Android 7.0 (API 24) and newer, **arm64-v8a** (every phone since about 2016) |
| SHA-256 | see [SHA256SUMS.txt](SHA256SUMS.txt) |

## What is new in 1.1

Four more languages actually run on the device, rather than being editable and
nothing else:

* **Go** - goroutines, channels, structs, methods, interfaces, defer, panic
  and recover, plus fmt, strings, strconv, math, sort, errors, time, os,
  bufio, unicode and sync.
* **Rust** - traits, impl blocks, enums with payloads, match with real
  patterns, closures, iterator chains, Option and Result with `?`, Vec,
  HashMap, HashSet and the String methods.
* **JavaScript** - handed to the engine the device already has, so it is the
  real thing: classes, async/await, generators, regular expressions.
* **C** was already interpreted; it still is.

None of these is compiled, because Android has not allowed an app to execute
code it generated itself since API 29. They are interpreted, and each
language's card in the app says exactly what that costs: no type checking in
Go, no borrow checker in Rust.

Also new: HTML, Markdown and CSS preview; syntax highlighting per language;
and the ten plugins now do what their descriptions promise - JSON Tools, Text
Tools, Regex Lab, API Tester, Workspace Search, Snippets, Autosave, Keep
Awake, Downloader and Workspace Export.

## What was checked before this was committed

The same source, built for x86_64, was installed on an Android 11 emulator and
driven through: Go, Rust and JavaScript files were run from the Files tab and
produced the right output on the console, and a Markdown file rendered in the
preview. The APK here is that source built for arm64 instead, which changes
the CPython binaries and nothing else.

The interpreters themselves are covered by 262 checks that run on a desktop
CPython - `tools/test_c.py`, `test_go.py`, `test_rust.py`, `test_js.js` and
`test_runtime.py` - each one a real program paired with the output the real
compiler produces.

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
adb install -r dist/PyCmd-1.1-debug.apk
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
