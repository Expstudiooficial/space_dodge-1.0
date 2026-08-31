#!/usr/bin/env python3
"""Checks the app still says what it is called, before it ships.

`Branding.verify` stops the app at start-up if PyCmd's name has been taken out
of it. That is a reasonable thing to do to a build that has had its credit
stripped, and a catastrophic thing to do by accident to this one - so the same
conditions are asserted here, in the suite, where a mistake costs a red line
instead of an app that will not open.

Read as: if this file passes, `Branding.verify` cannot throw on this build.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JAVA = os.path.join(ROOT, "app", "src", "main", "java", "com", "expstudio", "pycmd")
RES = os.path.join(ROOT, "app", "src", "main", "res")

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}  {detail}")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as handle:
        return handle.read()


print("== the name is where the check looks for it ==")

branding = read(JAVA, "util", "Branding.kt")
match = re.search(r'const val NAME = "([^"]*)"', branding)
check("Branding.NAME exists", match is not None, branding[:200])
name = match.group(1) if match else ""
check("and is not empty", name.strip() != "", repr(name))
check("and is PyCmd", name == "PyCmd", repr(name))

strings = read(RES, "values", "strings.xml")
label = re.search(r'<string name="app_name">([^<]*)</string>', strings)
check("the launcher label exists", label is not None, strings[:200])
launcher = label.group(1) if label else ""
check("and carries the name", name.lower() in launcher.lower(), repr(launcher))

print("\n== which means the start-up check cannot fire ==")
# The same two rules Branding.missingFrom applies, in the same order.
missing = []
if not name.strip():
    missing.append("Branding.NAME")
if launcher and name.strip() and name.lower() not in launcher.lower():
    missing.append("R.string.app_name")
check("nothing is missing", not missing, missing)

print("\n== and the screens draw from the constant, not from copies ==")
app = read(JAVA, "ui", "App.kt")
system = read(JAVA, "ui", "SystemScreen.kt")
check("the title bar uses Branding.NAME", "Text(Branding.NAME" in app,
      "the top bar has the name typed into it instead")
check("About uses it too", "${Branding.NAME} $version" in app or
      "Branding.NAME" in app, "About has its own copy of the name")
check("System uses it", "InfoRow(Branding.NAME" in system,
      "the System card has its own copy")

print("\n== the check is fail-safe by construction ==")
check("reading the label cannot throw", "runCatching { context.getString" in branding,
      "a resource read is not guarded")
check("and neither can the whole rule",
      "runCatching { missingFrom(context) }" in branding,
      "verify() does not guard missingFrom")
check("an unreadable label is treated as fine",
      "launcher.isNotEmpty() &&" in branding,
      "an empty read would be treated as a missing name")
check("the match is contains, not equals",
      "ignoreCase = true" in branding and "contains(" in branding,
      "a fork that adds its own name beside ours would trip")

print("\n== forks are told, in the app and in the guide ==")
forking = read(ROOT, "FORKING.md")
check("the fork guide exists", len(forking) > 500, len(forking))
check("and states the conditions",
      "Keep the name and the credit" in forking, forking[:200])
check("and the System screen says forks are welcome",
      "Forks are welcome" in system, "no fork line on the System screen")
check("with an address to write to",
      "andrejbaltes4@proton.me" in system, "no contact address")

print("\n== one thread owns the plugin folders ==")
# Installing a plugin replaces its folder; loading one imports a module out of
# that folder; a panel reads its HTML from it. On separate threads those can
# happen at the same time, and then a plugin is imported while its own files
# are being moved out from under it:
#
#   FileNotFoundError: .../plugins/pycmd.cloud/main.py
#
# The rule is that everything reaching pycmd_plugins goes to the plugin
# thread, except run_command, which has to be on the interpreter thread
# because it prints to the console and shares that namespace.
engine = read(JAVA, "python", "PythonEngine.kt")
wrong = []
for match in re.finditer(r"pluginRuntime\.callAttr\(\s*\"?(\w+)", engine):
    name = match.group(1)
    # Look back for the dispatcher this call is running under.
    before = engine[:match.start()]
    dispatcher = ""
    for candidate in re.finditer(r"withContext\((\w+)\)", before):
        dispatcher = candidate.group(1)
    if name == "run_command":
        if dispatcher != "pythonDispatcher":
            wrong.append((name, dispatcher))
    elif dispatcher not in ("pluginDispatcher", "pythonDispatcher"):
        wrong.append((name, dispatcher))
check("every plugin call runs on the plugin thread", not wrong, wrong)
check("and there is a plugin thread to run them on",
      "newSingleThreadExecutor" in engine and "python-plugins" in engine,
      "the plugin dispatcher is gone")

print("\n== bundled plugins are installed before anything is loaded ==")
model = read(JAVA, "ui", "MainViewModel.kt")
install_at = model.find("installBundledPlugins()\n            refreshCustomPlugins()")
check("the startup order puts installing first", install_at > 0,
      "refreshCustomPlugins runs before installBundledPlugins again")
check("and the version check reads the real listing rather than a state flow",
      "engine.listPlugins()" in model.split("private suspend fun installBundledPlugins")[1][:1600],
      "an empty flow reads as 'nothing installed' and reinstalls everything")

print()
if FAILURES:
    print(f"{len(FAILURES)} branding checks failed")
    sys.exit(1)
print("all branding checks passed")
