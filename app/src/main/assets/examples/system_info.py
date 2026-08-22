"""Everything the phone will tell Python about itself."""

import os
import platform
import sys


def section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


section("Interpreter")
print(f"version      : {sys.version.split()[0]}")
print(f"implementation: {sys.implementation.name}")
print(f"platform     : {sys.platform}")

section("Machine")
print(f"machine  : {platform.machine()}")
print(f"processor: {platform.processor() or 'n/a'}")
print(f"cpus     : {os.cpu_count()}")

section("Paths")
print(f"cwd: {os.getcwd()}")
for entry in sys.path[:8]:
    print(f"  {entry or '(cwd)'}")
