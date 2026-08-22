# Testing PyCmd — a first-run walkthrough

You've got the app installed. This is a tour through every tab with things to
paste in and try, so you're not staring at a blank screen wondering what to
type.

---

## 1. Console — type Python and press Run

Open the app. The title bar reads `starting` for a few seconds on first
launch (CPython is unpacking its standard library), then switches to
`Python 3.13.x`. That's your signal it's ready.

Paste these into the console box **one at a time** and hit the ▶ button:

```python
2 + 2
```
Prints `4` — the console echoes the value of the last expression, like a real
REPL.

```python
name = "world"
print(f"hello, {name}")
```
Two lines run as one block. Variables you set stick around for the next
thing you type — try just typing `name` next and running it.

```python
import sys
sys.version
```
Confirms which interpreter you're actually running.

```python
for i in range(5):
    print(i, i * i)
```
Multi-line blocks work fine — the console isn't line-by-line, it's block-by-block.

**Try `input()` too:**
```python
age = input("How old are you? ")
print(f"In 10 years you'll be {int(age) + 10}")
```
The console box turns into an answer box — type a number and hit send.

**Try a crash on purpose:**
```python
1 / 0
```
You'll get a real traceback in red, and the console stays usable — one bad
line doesn't kill your session.

---

## 2. Editor — write a file, run it, see it in Files

Tap the **Editor** tab. There's a starter snippet already there. Tap ▶ to
run it — output shows up back in Console.

Now tap the **new file** icon, paste this in:

```python
import time

for second in range(5, 0, -1):
    print(f"{second}...")
    time.sleep(1)
print("Go!")
```

Tap **Save**, name it `countdown.py`, then tap ▶. Watch it count down in the
Console tab in real time — output streams in as it happens, it doesn't wait
for the whole script to finish.

---

## 3. Files — the examples that ship with the app

Tap **Files**. You'll see an `examples/` folder seeded on first launch.
Open it. Tap any `.py` file to load it in the Editor, or tap the ▶ next to a
file to run it straight from the list without opening it.

What's in there, and why:

| File | What it shows |
|---|---|
| `hello.py` | The basics — `print`, an `input()` prompt |
| `system_info.py` | Reads real device info back through Python |
| `text_adventure.py` | Several `input()` calls in a row |
| `quiz.py` | A scored quiz — more `input()`, with feedback per answer |
| `loop_forever.py` | Runs forever until you tap **Stop** — try it |
| `todo_list.py` | Reads/writes a file in your workspace — run it twice, watch the list grow |
| `requests_demo.py` | Uses the network (needs Wi-Fi or data) |
| `rich_demo.py` | Colour and a table, rendered properly in the console |
| `http_server.py` | Serves a folder — see the Servers section below |
| `flask_api.py` | A JSON API running on the phone |

**Try creating your own.** Tap the new-file icon, call it `test.py`, paste in:

```python
import random

names = ["Ada", "Grace", "Alan", "Margaret"]
print(f"Random pick: {random.choice(names)}")
print(f"Dice roll: {random.randint(1, 6)}")
```

Run it a few times — different output each time confirms it's genuinely
executing on the device, not showing you canned text.

**Try importing a file.** Tap the import icon and pick any `.py` file from
your phone's downloads or storage — it copies into the workspace and shows
up in the list.

---

## 4. Packages — install something from PyPI, live

Tap **Packages**. `requests`, `flask` and `rich` are already built in (you
just used two of them above). Try installing something that *isn't*:

Type `tabulate` in the search box and tap **Install**. You'll see a short
progress message, then it lands in "Installed here". Go back to Console and
run:

```python
from tabulate import tabulate

data = [["Alice", 30], ["Bob", 25]]
print(tabulate(data, headers=["Name", "Age"]))
```

A real package, fetched from PyPI, installed on the device, imported and
used — needs the internet the first time you install it, works offline
after that.

**What won't work, and why:** try installing `numpy` or `pygame`. You'll get
a clear message instead of a silent failure — those ship compiled C code
that needs an Android-specific build, which nothing on PyPI provides. Pure
Python packages (the vast majority of PyPI) install fine.

---

## 5. Servers — serve something over your own Wi-Fi

Tap **Servers**. Tap **Serve folder**, accept the default port `8000`, tap
**Start**. You'll get an address like `http://192.168.1.42:8000/`.

On **any other device on the same Wi-Fi** — another phone, a laptop — open
that address in a browser. You'll see the files in your PyCmd workspace,
served live from your phone.

Switch to another app on the phone (home screen, a browser) — the server
keeps running. You'll see an ongoing notification; that's what stops Android
from killing the app in the background. Come back to Servers and tap **Stop**
when you're done.

**Try the Flask example too:** open `flask_api.py` from Files, run it, then
visit `http://<your-phone-ip>:5000/` from another device — it's a small
JSON API, not just static files.

---

## Things worth specifically checking

- **Stop actually stops.** Run `loop_forever.py`, watch a few ticks print,
  tap Stop. It should return to "ready" within well under a second, not hang.
- **The app survives a crash in your code.** Run something that errors
  (`1/0`, a typo, whatever) — the console shows the error and stays usable
  for the next thing you run.
- **Namespace reset.** Set a variable in Console, then tap the reset icon
  (top bar) — the variable should be gone if you try to use it again.
- **Rotate the phone / switch tabs mid-run.** Output shouldn't be lost, and
  a running script shouldn't stop just because you looked at another tab.

---

## If something looks wrong

This build has 139 automated checks behind it against the Python engine and
the JavaScript console/editor (see `tools/` in the repo), and it was
installed and driven on an Android 11 emulator: the app launches, Python
3.13.9 starts, and pressing Run in the editor prints its output to the
console.

What has *not* been verified on a device is most of what this page asks you
to try — installing a package, serving a folder over Wi-Fi, the Stop button,
`input()` prompts, and the background-server notification all work against
host CPython in the test suite but have not been tapped through on real
hardware. So if something here doesn't behave as described, that is worth
reporting rather than assuming you did it wrong: say what you ran, which
tab, and what happened instead.
