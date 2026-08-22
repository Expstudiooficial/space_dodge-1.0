"""A short quiz - several input() calls in a row, plus a running score.

Good for checking that input() behaves across multiple prompts in one run,
and that the console box clears itself after each answer.
"""

QUESTIONS = [
    ("What year was Python first released?", "1991"),
    ("What does 'py' stand for in PyCmd?", "python"),
    ("2 + 2 * 2 = ?", "6"),
]


def ask(question: str, answer: str) -> bool:
    given = input(f"{question} ").strip().lower()
    correct = given == answer.lower()
    print("Correct!" if correct else f"Nope, it was {answer}.")
    return correct


def main() -> None:
    print("Quick quiz - three questions.\n")
    score = sum(ask(q, a) for q, a in QUESTIONS)
    print(f"\nScore: {score}/{len(QUESTIONS)}")


if __name__ == "__main__":
    main()
