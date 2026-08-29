#!/usr/bin/env python3
"""Writes dist/latest.json - the file the app checks for updates.

The app reads this over HTTPS, compares the versionCode against its own, and
downloads the APK named here. Everything in it is read out of the APK itself
rather than typed in, because a hash that does not match the file is not a
release note, it is a download that will refuse to install.

    python3 tools/make_latest.py dist/PyCmd-2.4.2.apk --notes "..."

Run with no arguments to check the manifest that is already there against the
APK sitting beside it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

REPO = "expstudiooficial/space_dodge-1.0"
BRANCH = "claude/python-mobile-cmd-android-dj1ixb"
RAW = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(HERE, "dist", "latest.json")
GRADLE = os.path.join(HERE, "app", "build.gradle.kts")


def gradle_version() -> tuple[int, str]:
    """The versionCode and versionName the build is set to."""
    text = open(GRADLE, encoding="utf-8").read()
    code = re.search(r"versionCode\s*=\s*(\d+)", text)
    name = re.search(r'versionName\s*=\s*"([^"]+)"', text)
    if not code or not name:
        raise SystemExit("could not read the version out of app/build.gradle.kts")
    return int(code.group(1)), name.group(1)


def sdk_from_local_properties() -> str:
    """Where Gradle itself thinks the SDK is. The most reliable answer there is."""
    path = os.path.join(HERE, "local.properties")
    if not os.path.isfile(path):
        return ""
    for line in open(path, encoding="utf-8"):
        if line.strip().startswith("sdk.dir="):
            return line.split("=", 1)[1].strip().replace("\\:", ":")
    return ""


def find_aapt2() -> str:
    """The SDK's aapt2, if this machine has one."""
    found = shutil.which("aapt2")
    if found:
        return found
    for root in (sdk_from_local_properties(),
                 os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                 os.path.expanduser("~/android-sdk"), os.path.expanduser("~/Android/Sdk")):
        if not root:
            continue
        tools = os.path.join(root, "build-tools")
        if not os.path.isdir(tools):
            continue
        for version in sorted(os.listdir(tools), reverse=True):
            candidate = os.path.join(tools, version, "aapt2")
            if os.path.isfile(candidate):
                return candidate
    return ""


def apk_facts(apk: str) -> dict:
    """What the APK says it is: package, versionCode, versionName.

    Read out of the file rather than assumed from the build files, because the
    two can disagree - a release build carries no "-debug" in its name, and a
    manifest that describes a different APK to the one beside it is a download
    every phone would refuse after spending 30 MB on it. Falls back to the
    Gradle values when the SDK is not around, so this still works on a machine
    with nothing but Python.
    """
    aapt2 = find_aapt2()
    if not aapt2:
        code, name = gradle_version()
        return {"versionCode": code, "versionName": name, "package": "", "read": False}
    try:
        out = subprocess.run([aapt2, "dump", "badging", apk], capture_output=True,
                             text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        code, name = gradle_version()
        return {"versionCode": code, "versionName": name, "package": "", "read": False}
    line = next((row for row in out.splitlines() if row.startswith("package:")), "")
    package = re.search(r"name='([^']+)'", line)
    code = re.search(r"versionCode='(\d+)'", line)
    name = re.search(r"versionName='([^']*)'", line)
    if not (package and code and name):
        fallback_code, fallback_name = gradle_version()
        return {"versionCode": fallback_code, "versionName": fallback_name,
                "package": "", "read": False}
    return {"versionCode": int(code.group(1)), "versionName": name.group(1),
            "package": package.group(1), "read": True}


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_apk(path: str) -> bool:
    """A real APK, not a rename: it has to hold an AndroidManifest."""
    try:
        with zipfile.ZipFile(path) as archive:
            return "AndroidManifest.xml" in archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def build(apk: str, notes: str) -> dict:
    if not is_apk(apk):
        raise SystemExit(f"{apk} is not an APK")
    facts = apk_facts(apk)
    if not facts["read"]:
        print("  (no aapt2 here - using the version from app/build.gradle.kts)")
    relative = os.path.relpath(os.path.abspath(apk), HERE).replace(os.sep, "/")
    return {
        "versionCode": facts["versionCode"],
        "versionName": facts["versionName"],
        "package": facts["package"] or "com.expstudio.pycmd.debug",
        "url": RAW.format(repo=REPO, branch=BRANCH, path=relative),
        "sha256": sha256(apk),
        "bytes": os.path.getsize(apk),
        "notes": notes,
    }


def check(manifest: dict) -> list[str]:
    """The same rules Updater.parse applies, so a bad file is caught here."""
    problems = []
    code = manifest.get("versionCode")
    if not isinstance(code, int) or code <= 0:
        problems.append("versionCode must be a positive whole number")
    else:
        expected, _ = gradle_version()
        if code != expected:
            problems.append(f"versionCode is {code}, the build says {expected}")

    url = manifest.get("url", "")
    if not url.startswith("https://"):
        problems.append("url must be an https:// address")

    digest = manifest.get("sha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
        problems.append("sha256 must be 64 lowercase hex characters")

    # The APK named in the url has to be the one in dist/, byte for byte, and
    # has to describe itself the way the manifest says it does.
    local = os.path.join(HERE, "dist", url.rsplit("/", 1)[-1]) if url else ""
    if local and os.path.isfile(local):
        if sha256(local) != digest:
            problems.append(f"sha256 does not match {os.path.basename(local)}")
        if manifest.get("bytes") != os.path.getsize(local):
            problems.append("bytes does not match the APK's size")
        facts = apk_facts(local)
        if facts["read"]:
            if facts["versionCode"] != code:
                problems.append(
                    f"versionCode is {code}, the APK says {facts['versionCode']}")
            if facts["versionName"] != manifest.get("versionName"):
                problems.append(
                    f"versionName is {manifest.get('versionName')}, "
                    f"the APK says {facts['versionName']}")
            if facts["package"] != manifest.get("package"):
                problems.append(
                    f"package is {manifest.get('package')}, "
                    f"the APK says {facts['package']}")
    elif url:
        problems.append(f"there is no {os.path.basename(local)} in dist/")

    if not manifest.get("versionName"):
        problems.append("versionName is missing")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", nargs="?", help="the APK to publish")
    parser.add_argument("--notes", default="", help="one line shown in the app")
    args = parser.parse_args()

    if args.apk:
        manifest = build(args.apk, args.notes)
        problems = check(manifest)
        if problems:
            for problem in problems:
                print("  -", problem)
            return 1
        with open(MANIFEST, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)
            handle.write("\n")
        print(f"wrote {os.path.relpath(MANIFEST, HERE)}")
        print(json.dumps(manifest, indent=2))
        return 0

    if not os.path.isfile(MANIFEST):
        print("no dist/latest.json yet")
        return 1
    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    problems = check(manifest)
    if problems:
        print("dist/latest.json is wrong:")
        for problem in problems:
            print("  -", problem)
        return 1
    print(f"dist/latest.json is good: {manifest['versionName']} "
          f"(build {manifest['versionCode']}), {manifest['bytes']} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
