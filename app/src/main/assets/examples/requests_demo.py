"""Uses the network from Python running on your phone.

requests is built into PyCmd, so this needs no install step. It needs a
working internet connection on the device, though - Wi-Fi or mobile data.
"""

import requests

print("Fetching a random GitHub API fact...")

try:
    response = requests.get("https://api.github.com/zen", timeout=10)
    response.raise_for_status()
    print()
    print(f'"{response.text}"')
    print()
    print(f"HTTP {response.status_code} in {response.elapsed.total_seconds():.2f}s")
except requests.RequestException as exc:
    print(f"Request failed: {exc}")
    print("Check that the device has an internet connection.")
