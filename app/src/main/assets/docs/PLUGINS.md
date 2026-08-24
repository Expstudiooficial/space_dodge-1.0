# Writing a PyCmd plugin

Everything you need to build a plugin that installs, loads and works — the
file layout, the manifest, the Python API, the events, the HTML panel that
becomes its own tab, four complete working plugins, and the exact prompt to
hand an AI if you would rather have it written for you.

The app can show this document on the phone: **Plugins → How do I write one?**

---

## 1. What a plugin actually is

A plugin is **Python that PyCmd imports into its own interpreter**, plus an
optional **HTML page** that becomes a tab.

That gives you a lot: the whole standard library, anything you installed from
the Packages tab, the user's workspace, sockets, threads. It also means one
thing that has to be said before anything else:

> **A plugin is not sandboxed.** It runs with exactly the permissions the app
> has. It can read and rewrite every file in the workspace, open network
> connections, and keep running for as long as the app is open. CPython has no
> sandbox worth the name — `exec` in a stripped namespace stops nobody who can
> spell `__builtins__`. PyCmd warns before installing, lists what a plugin
> declares, and lets you switch it off or delete it in two taps. Beyond that,
> the protection is you reading the code.

Install one only if you wrote it or you trust whoever did.

---

## 2. The three shapes

Any of these installs from **Plugins → Install a plugin**, either from your
phone's file picker or from a folder you point at.

### One file

```
wordcount.py
```

The manifest lives in the file itself as a `PLUGIN` dict. Good for something
small.

### A folder

```
my-plugin/
├── plugin.json        the manifest
├── main.py            the entry point
├── ui.html            optional: the panel, which becomes a tab
├── helper.py          optional: your own modules, imported normally
└── assets/            optional: images, CSS, data files
    └── logo.png
```

### A zip of that folder

```
my-plugin.zip
```

Zipping the folder itself or its contents both work — PyCmd strips a single
wrapping directory if it finds one.

---

## 3. The manifest

`plugin.json`:

```json
{
  "id": "com.yourname.wordcount",
  "name": "Word Count",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "Counts words, lines and characters in the open file.",
  "entry": "main.py",
  "panel": "ui.html",
  "tab": { "title": "Words", "icon": "puzzle" },
  "commands": [
    { "name": "wc", "help": "wc <text> — count words in some text" }
  ],
  "permissions": ["files"]
}
```

| Key | Required | What it does |
|---|---|---|
| `id` | **yes** | Unique. Lower-case letters, digits, `.`, `-`, `_`. Reinstalling the same id replaces the old copy. |
| `name` | **yes** | Shown in the plugin list. |
| `version` | no | Any string. Shown next to the name. Defaults to `1.0.0`. |
| `author` | no | Shown in the list. |
| `description` | no | One paragraph. Up to 600 characters. |
| `entry` | no | The module PyCmd imports. Defaults to `main.py`. |
| `panel` | no | An HTML file. Having one is what gives the plugin an **Open** button and a tab. |
| `tab` | no | `{"title": "…"}` or just a string. Needs `panel`. An `icon` is accepted and kept for a future version; nothing draws it yet. |
| `commands` | no | Console commands, for the list and the help text. You still register the handler in code. |
| `permissions` | no | `files`, `network`, `console`, `servers`, `packages`. **Documentation, not enforcement** — they are shown to the user so they know what to expect. Declare honestly. |

For a single-file plugin, put the same object in the module as a `PLUGIN`
dict:

```python
PLUGIN = {
    "id": "com.yourname.wordcount",
    "name": "Word Count",
    "version": "1.0.0",
    "commands": [{"name": "wc", "help": "wc <text>"}],
}
```

PyCmd reads that **without importing your module** — it parses the file and
evaluates only that literal. Deciding whether to run something by running it
would defeat the point.

---

## 4. The entry point

PyCmd imports your entry module and, if it finds a function called `setup`,
calls it with the API object:

```python
def setup(api):
    api.log("hello from my plugin")
```

Everything you register — commands, exports, event handlers — is registered
inside `setup`. Module-level code runs too, but `setup` is where the API is
handed to you.

If you want to clean up when the plugin is switched off:

```python
def teardown(api):
    api.log("goodbye")
```

Inside your entry module the API is also available as a module global named
`pycmd`, and your folder is `PLUGIN_DIR`:

```python
def helper():
    pycmd.log("callable from anywhere in the module")
    with open(f"{PLUGIN_DIR}/data.json") as handle:
        ...
```

Your plugin's folder is on `sys.path` while it loads, so `import helper` finds
`helper.py` next to `main.py`.

---

## 5. The API

Everything below is on the `api` object handed to `setup`.

### Talking to the user

```python
api.print("straight to the console the user is looking at")
api.print("no newline", end="")

api.log("goes to the debug console")          # info
api.warn("something looks off", "detail")     # warning
api.error("that failed", traceback_text)      # error, counted in the badge

api.toast("a short message at the bottom of the screen")
```

Use `print` for output the user asked for, `log`/`warn`/`error` for everything
else. The debug console is where plugin noise belongs.

### Files

```python
api.workspace_path()                 # /data/.../files/workspace
api.workspace_path("notes", "a.md")  # a path inside it

text = api.read("notes/a.md")             # None if it is not there
text = api.read("notes/a.md", "")         # or a fallback you choose
api.write("notes/a.md", "new contents")   # makes parent folders, returns True/False

for path in api.files("*.py"):       # every match in the workspace
    ...
```

Relative paths are resolved against the workspace. Absolute paths are used as
given — you can reach outside the workspace, and normal Python file handling
works too. `api.read`/`api.write` are conveniences, not a fence.

### Your own storage

```python
data = api.store()                    # a dict, {} the first time
data["count"] = data.get("count", 0) + 1
api.store(data)                       # saved as JSON next to your plugin
```

Deleted with the plugin. Good for settings and small state; use a real file or
a database in the workspace for anything larger.

### Console commands

```python
@api.command("todo", help="todo add <text> | todo list")
def todo(argument):
    api.print(f"you said: {argument}")
```

The user types `todo add milk` in the console and your handler gets
`"add milk"` — everything after the first word, as one string.

A command wins over Python only when the first word matches a command you
registered **and** the line has no `=` in it, so an ordinary assignment is
never swallowed. Anything you return is ignored; print what you want seen.

### Functions the panel can call

```python
@api.export
def analyse(payload):
    return {"words": len(payload["text"].split())}

@api.export(name="load_text")
def load(payload=None):
    return api.store().get("text", "")
```

An export takes one argument — whatever the panel passed, already decoded from
JSON — and returns anything JSON can carry. If your export takes no argument,
the panel can call it with none.

### Events

```python
@api.on("file_saved")
def saved(event):
    api.log("saved", event["path"])
```

| Event | When | Payload |
|---|---|---|
| `file_saved` | the editor wrote a file | `{"path": "...", "name": "..."}` |
| `file_opened` | a file was opened in the editor | `{"path": "...", "name": "..."}` |
| `run_started` | a script started | `{"path": "...", "language": "..."}` |
| `run_finished` | a script ended | `{"path": "...", "status": "ok\|error\|stopped"}` |
| `console_run` | the user ran a console line | `{"source": "..."}` |
| `server_started` | a server came up | `{"handle": "...", "port": 8000, "kind": "static"}` |
| `server_stopped` | a server went away | `{"handle": "..."}` |
| `plugin_loaded` | your plugin finished loading | `{"id": "..."}` |

Handlers run on whichever thread raised the event. Keep them quick; if you
need to do real work, start a thread.

An exception in a handler is caught, logged against your plugin, and the other
handlers still run. It will not take the app down.

### Pushing to your panel

```python
api.send({"kind": "progress", "done": 3, "total": 10})
```

Arrives in the panel as a `message` event. Ignored if no panel is open.

---

## 6. The panel: your own tab

Any HTML file works. PyCmd injects a stylesheet that matches the app and a
`window.pycmd` bridge, so a plain file is already a usable screen:

```html
<h1>Word Count</h1>
<div class="card">
  <textarea id="input" rows="6" placeholder="Paste some text"></textarea>
  <p><button id="go">Count</button></p>
  <pre id="out">—</pre>
</div>

<script>
  document.getElementById('go').onclick = async () => {
    const text = document.getElementById('input').value;
    const result = await pycmd.call('analyse', { text });
    document.getElementById('out').textContent = JSON.stringify(result, null, 2);
  };
</script>
```

### The panel API

```js
await pycmd.call('export_name', payload)   // runs your Python, resolves with its return
pycmd.on('message', (data) => { ... })     // receives api.send(...)
pycmd.toast('done')                        // the app's toast
pycmd.log('something happened')            // the debug console
pycmd.close()                              // back to the plugin list
pycmd.plugin                               // { id, name, version, author }
```

`pycmd.call` returns a promise. If your Python raises, the promise rejects
with the error message — so `try { await … } catch (e) { … }` shows the user
something better than nothing.

Your own CSS, images and scripts load from the plugin folder with relative
paths (`<img src="assets/logo.png">`). The page cannot navigate anywhere else:
links out are blocked, deliberately.

Set `tab` in the manifest and the panel gets a title of its own in the
plugin list and in **More**.

---

## 7. Four plugins that work

Copy any of these, install it, switch it on.

### 7.1 One file, one command

`greet.py`

```python
PLUGIN = {
    "id": "demo.greet",
    "name": "Greet",
    "version": "1.0.0",
    "description": "A command that says hello.",
    "commands": [{"name": "greet", "help": "greet <name>"}],
}


def setup(api):
    @api.command("greet", help="greet <name>")
    def greet(argument):
        who = argument.strip() or "world"
        api.print(f"hello, {who}")
```

Type `greet Ada` in the console.

### 7.2 Reacting to what the user does

`autobackup.py`

```python
import os
import time

PLUGIN = {
    "id": "demo.autobackup",
    "name": "Auto Backup",
    "version": "1.0.0",
    "description": "Keeps the last copy of every file you save, under .backups/.",
    "permissions": ["files"],
}


def setup(api):
    @api.on("file_saved")
    def backup(event):
        path = event.get("path", "")
        if not path or ".backups" in path:
            return
        text = api.read(path)
        if text is None:
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = os.path.basename(path)
        api.write(f".backups/{name}.{stamp}", text)
        api.log("backed up", name)
```

### 7.3 A panel with a tab

`counter/plugin.json`

```json
{
  "id": "demo.counter",
  "name": "Line Counter",
  "version": "1.0.0",
  "description": "Counts the lines of code in the workspace.",
  "entry": "main.py",
  "panel": "ui.html",
  "tab": { "title": "Lines" },
  "permissions": ["files"]
}
```

`counter/main.py`

```python
import os

PLUGIN = None  # the manifest is in plugin.json


def setup(api):
    @api.export
    def scan(payload=None):
        rows = []
        total = 0
        for path in api.files("*.py"):
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    lines = sum(1 for _ in handle)
            except OSError:
                continue
            total += lines
            rows.append({"name": os.path.basename(path), "lines": lines})
        rows.sort(key=lambda row: -row["lines"])
        return {"total": total, "files": rows[:50]}
```

`counter/ui.html`

```html
<h1>Lines of Python</h1>
<div class="card">
  <button id="scan">Scan the workspace</button>
  <p id="total"></p>
  <table id="rows"></table>
</div>

<script>
  document.getElementById('scan').onclick = async () => {
    const data = await pycmd.call('scan');
    document.getElementById('total').textContent = data.total + ' lines in ' + data.files.length + ' files';
    document.getElementById('rows').innerHTML = data.files
      .map((row) => `<tr><td>${row.name}</td><td style="text-align:right">${row.lines}</td></tr>`)
      .join('');
  };
</script>
```

### 7.4 A background worker that reports progress

`watcher/plugin.json`

```json
{
  "id": "demo.watcher",
  "name": "Workspace Watcher",
  "version": "1.0.0",
  "description": "Watches the workspace and tells its panel when something changes.",
  "entry": "main.py",
  "panel": "ui.html",
  "tab": { "title": "Watcher" },
  "permissions": ["files"]
}
```

`watcher/main.py`

```python
import os
import threading
import time

STATE = {"running": False}


def setup(api):
    def snapshot():
        return {p: os.path.getmtime(p) for p in api.files("*")}

    def loop():
        previous = snapshot()
        while STATE["running"]:
            time.sleep(2)
            current = snapshot()
            changed = [p for p, t in current.items() if previous.get(p) != t]
            if changed:
                api.send({"changed": [os.path.basename(p) for p in changed]})
            previous = current

    @api.export
    def start(payload=None):
        if STATE["running"]:
            return {"running": True}
        STATE["running"] = True
        # A daemon thread dies with the app, which is what you want here.
        threading.Thread(target=loop, daemon=True).start()
        return {"running": True}

    @api.export
    def stop(payload=None):
        STATE["running"] = False
        return {"running": False}


def teardown(api):
    STATE["running"] = False
```

`watcher/ui.html`

```html
<h1>Watcher</h1>
<div class="card">
  <button id="start">Start</button>
  <button id="stop">Stop</button>
  <ul id="log"></ul>
</div>

<script>
  document.getElementById('start').onclick = () => pycmd.call('start');
  document.getElementById('stop').onclick = () => pycmd.call('stop');
  pycmd.on('message', (data) => {
    const item = document.createElement('li');
    item.textContent = new Date().toLocaleTimeString() + ' — ' + data.changed.join(', ');
    document.getElementById('log').prepend(item);
  });
</script>
```

---

## 8. Installing and testing

1. Put the plugin somewhere the phone can reach — the workspace, Downloads,
   or a cloud folder your file picker can see.
2. **Plugins → Install a plugin → File or zip** (or **Folder**).
3. Read the warning. Install.
4. Switch it on. It loads immediately; the switch is what runs it.
5. Check the **debug console** (the bug icon in the top bar). Everything your
   plugin logs, and every error it raises, lands there with its name attached.

If it does not load, the plugin's card shows the traceback in red. The most
common causes, in order: a typo in `plugin.json`, an `entry` that names a file
that is not there, and an import of a package that is not installed — install
it from the Packages tab first.

**Reinstalling replaces.** Same `id`, new files: install again and the old copy
is unloaded and deleted first. There is no need to remove it by hand while you
iterate.

---

## 9. Rules and limits

- **The interpreter is shared.** Your plugin runs in the same CPython as the
  user's scripts. Do not `sys.exit()`, do not replace `sys.stdout` permanently,
  do not `os.chdir` and leave it changed.
- **Blocking blocks.** A `setup` that sleeps for ten seconds freezes the plugin
  list for ten seconds. Do long work in a thread.
- **Threads must be daemons.** `threading.Thread(target=…, daemon=True)`, or
  the app will not close cleanly.
- **Size**: 32 MB and 2000 files per plugin.
- **A zip cannot write outside its own folder.** Paths with `..` are refused at
  install time.
- **Exports return JSON.** Return dicts, lists, strings, numbers, booleans and
  `None`. Anything else is turned into a string.
- **The panel cannot navigate.** No links out, no iframes to the web. Fetch
  through your Python if you need the network.
- **Nothing is verified.** Not by the app, not by anyone. Your plugin is as
  trustworthy as its author.

---

## 10. The prompt to hand an AI

Paste this into any capable model, replace the last line, and you get a plugin
that installs into this app without editing.

````text
Write a plugin for PyCmd, an Android app that embeds CPython 3.13.

PLUGIN FORMAT
A plugin is either:
  (a) a single .py file with a module-level PLUGIN = {...} dict, or
  (b) a folder containing plugin.json plus an entry module (default main.py),
      and optionally an HTML panel file.

plugin.json / PLUGIN keys:
  id           required, unique, lowercase [a-z0-9._-]
  name         required
  version, author, description   optional strings
  entry        optional, default "main.py"
  panel        optional HTML file; having one gives the plugin its own tab
  tab          optional {"title": "...", "icon": "..."}
  commands     optional [{"name": "...", "help": "..."}]
  permissions  optional subset of ["files","network","console","servers","packages"]
               (documentation only - shown to the user, not enforced)

ENTRY MODULE
Define `def setup(api):` - PyCmd calls it with the API object. Optionally
`def teardown(api):`. Inside the module, `pycmd` is the same API object and
`PLUGIN_DIR` is the plugin's folder. The folder is on sys.path during load.

THE API
  api.print(*values, sep=" ", end="\n")   -> the user's console
  api.log(msg, detail="")                 -> debug console (also .warn, .error)
  api.toast(msg)                          -> a short on-screen message
  api.workspace_path(*parts)              -> path inside the workspace
  api.read(path, default=None)            -> text or default
  api.write(path, text) -> bool           -> creates parent folders
  api.files(pattern="*")                  -> matching paths in the workspace
  api.store()          -> dict            -> this plugin's saved JSON
  api.store(dict)                         -> saves it
  api.send(obj)                           -> pushes a message to the panel

  @api.command("name", help="...")        -> console command; handler(argument: str)
  @api.export                             -> callable from the panel; f(payload) -> JSON
  @api.export(name="other_name")
  @api.on("event")                        -> handler(event: dict)

EVENTS
  file_saved {path,name} | file_opened {path,name} | run_started {path,language}
  run_finished {path,status} | console_run {source} | server_started {handle,port,kind}
  server_stopped {handle} | plugin_loaded {id}

THE PANEL (optional HTML file)
PyCmd injects a dark stylesheet and a bridge. Available in the page:
  await pycmd.call('export_name', payload)  -> resolves with the Python return
  pycmd.on('message', cb)                   -> receives api.send(...)
  pycmd.toast(text) | pycmd.log(text) | pycmd.close() | pycmd.plugin
Relative paths load from the plugin folder. The page cannot navigate away.

RULES
- The interpreter is shared with the user's scripts: never sys.exit(), never
  leave sys.stdout replaced or the working directory changed.
- Never block in setup(); use threading.Thread(..., daemon=True).
- Exports must return JSON-serialisable values.
- Only the standard library, unless you state which package the user must
  install from the Packages tab first.
- Handle your own errors and report them with api.error(...).

OUTPUT
Give me every file in full, each in its own code block with its filename as
the heading, ready to zip. No placeholders, no "..." - working code.

THE PLUGIN I WANT:
<describe it here - what it does, what it shows, what it reacts to>
````

---

## 11. Where things live on the device

```
files/
├── workspace/          what the user writes; api.read/write default here
├── plugins/
│   └── <plugin id>/    your files, exactly as installed
│       └── .state.json api.store()
└── downloads/          the Downloads tab
```

Removing a plugin deletes its folder, `.state.json` and all. Files it wrote
into the workspace stay.

---

## 12. If you get stuck

- The **debug console** has everything: load errors with tracebacks, every
  `api.log`, and anything your panel logged.
- **Plugins → your plugin → Files** lists what actually got installed, which
  settles most "but I zipped it" questions.
- A plugin that will not load can still be **removed**, and installing a fixed
  copy with the same `id` replaces it.
