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
| `loop_forever.py` | Runs forever until you tap **Stop** — and a good Kill test as a script server |
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

Tap **Servers**. The form at the top is the whole thing:

1. Pick **Serve a folder** or **Run a file**.
2. Tap **Choose**. You land in Files with a banner. Tap any file to use it, or
   open a folder and tap **Use this folder** — both work in either mode.
3. Set the **port** — 8000 is fine. If it is taken, **Free one** finds the next
   one that isn't.
4. Optionally name it, and decide whether it is reachable on Wi-Fi or only on
   the phone itself.
5. Press **Run**.

Run stays greyed out until the form makes sense, and tells you what is missing
underneath.

**It runs more than Python.** The form says what pressing Run will do before it
does it:

| You pick | What happens |
|---|---|
| `.py` | Runs as a background script on its own thread |
| `.c`, `.go`, `.rs` | Runs on the interpreter built into the app |
| `.js` | Runs in the device's own JavaScript engine |
| `.html`, `.css`, `.md` | Serves the folder it sits in, opening on that page |
| a folder | Serves it |
| `.java`, `.cpp`, `.ts` | Refused up front, with the reason — no toolchain can run these here |

A running server has a **View** button that opens it in the preview, so you can
look at your own site without leaving the app.

You land straight in that server's own **console**. It shows what the server
printed, and with "Log each request" on you will see every hit as it happens:

```
Serving /data/.../workspace
Listening on http://192.168.1.42:8000/
192.168.1.58  "GET / HTTP/1.1" 200 -
```

Open that address from any other device on the same Wi-Fi and you will see your
workspace. Tap the copy icon in the console header to grab the URL.

The box at the bottom sends a line to the server's **stdin** — so a script that
calls `input()` is actually usable while it runs.

### Stop vs Kill

**Stop** asks the server to close and waits a few seconds. That is the normal
way to end one.

**Kill** is for when Stop cannot help — a script that hangs before it finishes
starting, or one that swallows interrupts. It closes the socket (freeing the
port even if the thread is stuck), forces the thread down, and stops tracking
it either way. Your port comes back regardless.

Try it: run `loop_forever.py` as a script server, then Kill it.

**Kill all** at the top of the list is the panic button, behind a confirmation.

Kill also works on a server that has frozen in its own `accept()` — it knocks
on the port to make the blocking call return, which is the only way an
exception can land inside one.

**Turn on Server Pro** (More → Plugins → *Ships with PyCmd*) and the Servers
tab grows a live board: whether each port really answers, restart, a free-port
finder, and the commands `servers`, `serve`, `restart`, `shut` and `ports`.

**Try the Flask example:** set **Run a script**, choose `flask_api.py`, set the
port to 5000, Run. Then visit `http://<your-phone-ip>:5000/` from another
device — a JSON API, served from your phone.

---

## 6. Other languages — Go, Rust, C and JavaScript

Files → **New file** → pick a language. Or paste one of these into the editor,
save it with the right extension, and press ▶.

`hello.go`

```go
package main

import "fmt"

func main() {
	ch := make(chan string, 1)
	go func() { ch <- "from a goroutine" }()
	fmt.Println(<-ch)

	squares := []int{}
	for i := 1; i <= 5; i++ {
		squares = append(squares, i*i)
	}
	fmt.Println(squares, len(squares))
}
```

`hello.rs`

```rust
use std::collections::HashMap;

fn main() {
    let mut counts: HashMap<&str, i32> = HashMap::new();
    for word in "a b a c a".split_whitespace() {
        *counts.entry(word).or_insert(0) += 1;
    }
    let mut keys: Vec<&str> = counts.keys().cloned().collect();
    keys.sort();
    for key in keys {
        print!("{}={} ", key, counts[key]);
    }
    println!();

    let squares: Vec<i32> = (1..=5).map(|n| n * n).collect();
    println!("{:?} sum={}", squares, squares.iter().sum::<i32>());
}
```

`hello.js`

```javascript
class Greeter {
  constructor(name) { this.name = name; }
  greet() { return `hello, ${this.name}`; }
}
console.log(new Greeter("phone").greet());
setTimeout(() => console.log("this still prints before the run ends"), 30);
```

None of these is compiled — Android has not let an app run code it generated
itself since Android 10. C, Go and Rust run on interpreters inside the app, and
JavaScript goes to the engine your phone already has. Each language's card in
**More → Guides** says what that costs: no type checking in Go, no borrow
checker in Rust.

---

## 7. Preview — HTML, CSS, Markdown, JSON, CSV, images

Make `page.html` in Files:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font: 16px system-ui; padding: 24px; background: #101820; color: #eee; }
    button { font: inherit; padding: 10px 18px; border-radius: 10px; }
  </style>
</head>
<body>
  <h1 id="title">Tap the button</h1>
  <button onclick="document.getElementById('title').textContent = 'It works ' + new Date().toLocaleTimeString()">
    Press me
  </button>
</body>
</html>
```

Press ▶ on it in Files. The button **works** — the page is served over a local
HTTP server rooted at its own folder, so scripts run, stylesheets load, and
`fetch` works. Anything the page logs or throws lands in the debug console.

The same button previews Markdown, a JSON file (validated and pretty-printed),
a CSV (as a table), an SVG or an image, and a `.js` file (which runs it and
shows what it logged).

---

## 8. The plugins that ship with it

**More → Plugins**. Three sit under **Ships with PyCmd**, installed for you and
switched **off**:

* **Server Pro** — turns the Servers tab into a board you can work in.
* **Cloud** — Supabase and Firebase, from the console, a panel, or your own
  scripts.
* **Scheduler** — run a script again every so often.

Turn Cloud on, open **More → Cloud**, and connect a project. Then, from the
console:

```
sb select notes 5
fb get notes/today
```

or from a script — the same project, signed in as the same user:

```python
import pycmd_cloud

sb = pycmd_cloud.supabase()
for row in sb.table("notes").select("*").eq("done", False).limit(5).run():
    print(row["text"])
```

**Guides → The plugins that ship with it** lists everything both kinds can do.

---

## 9. Plugins you write yourself

Two examples are already in `examples/plugins`.

1. Scroll to **Install a plugin → From the workspace**.
2. Read the warning — a plugin is not sandboxed and runs with everything the
   app can do — and continue.
3. Pick `greet.py`. It appears under **Installed by you**, switched off.
4. Turn it on. Now type `greet Ada` in the console: a plugin command, not
   Python.
5. Install `hello-panel` the same way, turn it on, and press **Open**. That is
   a plugin's own screen, with its buttons calling its Python.

A plugin can also put a card of its own **inside** one of the app's screens —
that is how Server Pro reaches the Servers tab and Cloud reaches Files — and it
can publish a row in **More** with its own name, description and picture.
Neither needs the app to change.

**Plugins → How do I write one?** opens the full guide on the phone:
the manifest, the API, the events, the panel bridge, four complete plugins,
and a prompt you can paste into an AI to have one written for you.

---

## 10. When something goes wrong, it offers a fix

Make a file called `index2.html` in a folder, then a script next to it:

```python
with open("index.html") as handle:
    print(handle.read())
```

Run it. The console says:

```
[fix] index.html was not found, but index2.html is sitting next to it.
[fix] Rename index2.html to index.html?
[fix] Type yes to do it, no to leave it alone.
```

Type `no` and it says *OK — no fixing today* and leaves the error alone. Type
`yes` and it tells you what it is doing while it does it:

```
[fix] OK - renaming index2.html to index.html, so the code finds what it asks for.
[fix] Renamed index2.html to index.html. Start it again.
```

The same offers appear for a package that is not installed — where it says *OK
— downloading pygame from PyPI* and keeps talking while it downloads — a port
already in use, and a served folder with no index page. Nothing changes without
a yes, and answering never blocks the app: the work happens on its own thread,
so Stop and Kill keep working throughout.

---

## 11. Debug console — when something breaks

Tap the **bug icon** in the top bar, from any tab. This is not your script's
output — it is everything around it: interpreter startup, server lifecycles,
package installs, file errors, JavaScript errors inside the editor, and any
crash.

- The chips filter by level. Tap **Error** to see only what actually failed.
- The box above searches text and tags.
- Tap an entry with "tap for detail" to expand its stack trace.
- The icons copy the whole log, save it into your workspace as a `.log` file,
  or clear it.

A red badge on the bug icon is the number of errors waiting. On a healthy
start-up it should read three entries and no errors.

If you hit a bug worth reporting, save the log and send that — it is far more
useful than a description.

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
