"""Demonstrates the Stop button.

Run this, watch the numbers climb, then tap Stop in the console toolbar.
The loop is interrupted within a fraction of a second and the console goes
back to "ready" - it does not need to finish or crash on its own.
"""

import time

n = 0
while True:
    n += 1
    print(f"tick {n}")
    time.sleep(0.5)
