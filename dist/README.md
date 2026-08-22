# Prebuilt APK

`PyCmd-1.0-debug.apk` — ready to install, nothing else needed.

| | |
|---|---|
| Package | `com.expstudio.pycmd.debug` |
| Version | 1.0-debug |
| Size | 53 MB |
| Signed with | the standard Android debug key |
| Works on | Android 7.0 (API 24) and newer, **arm64-v8a or x86_64** |
| SHA-256 | see [SHA256SUMS.txt](SHA256SUMS.txt) |

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

## Installing over USB

```bash
adb install -r dist/PyCmd-1.0-debug.apk
```

## Checking the download

```bash
sha256sum -c dist/SHA256SUMS.txt
```

## A note on the device requirement

The APK contains binaries for **arm64-v8a** and **x86_64** only. Chaquopy's
Python 3.13 runtime ships no 32-bit builds, so a phone from before roughly 2016
running a 32-bit-only Android will refuse to install it. Everything current is
arm64.

## Rebuilding it yourself

```bash
./gradlew :app:assembleDebug
# -> app/build/outputs/apk/debug/app-debug.apk
```

See the [main README](../README.md) for what the build needs.
