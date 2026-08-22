"""A short interactive script — shows that input() works in the console."""

import random

TREASURES = ["a rusty key", "a glowing stone", "an old map", "a silver coin"]


def main() -> None:
    print("You are standing at the mouth of a cave.")
    found = []

    for room in range(1, 4):
        answer = input(f"Room {room}: go [l]eft or [r]ight? ").strip().lower()
        direction = "left" if answer.startswith("l") else "right"
        prize = random.choice(TREASURES)
        found.append(prize)
        print(f"  You went {direction} and found {prize}.")

    print()
    print("You leave the cave carrying:")
    for item in found:
        print(f"  - {item}")


if __name__ == "__main__":
    main()
