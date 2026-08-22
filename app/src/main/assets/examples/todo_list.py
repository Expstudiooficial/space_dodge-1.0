"""A to-do list that survives between runs.

Everything under the workspace folder is private storage that stays on the
device between launches. This script reads and writes a JSON file there, so
running it more than once shows your list growing.
"""

import json
import os

STORE = os.path.join(os.getcwd(), "todo.json")


def load() -> list[str]:
    if not os.path.exists(STORE):
        return []
    with open(STORE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save(items: list[str]) -> None:
    with open(STORE, "w", encoding="utf-8") as handle:
        json.dump(items, handle, indent=2)


def main() -> None:
    items = load()

    print(f"You have {len(items)} item(s) saved.")
    for i, item in enumerate(items, start=1):
        print(f"  {i}. {item}")

    new_item = input("\nAdd an item (blank to skip): ").strip()
    if new_item:
        items.append(new_item)
        save(items)
        print(f"Saved. Run this again and it will still be here.")
    else:
        print("Nothing added.")


if __name__ == "__main__":
    main()
