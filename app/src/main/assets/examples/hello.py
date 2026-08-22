"""The smallest thing that proves the runtime works."""

import platform
import sys


def main() -> None:
    print("Hello from PyCmd!")
    print(f"Python  : {sys.version.split()[0]}")
    print(f"Platform: {platform.machine()}")
    name = input("What's your name? ")
    print(f"Nice to meet you, {name or 'stranger'}.")


if __name__ == "__main__":
    main()
