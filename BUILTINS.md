# The plugins that ship with PyCmd

Everything in the Plugins tab is off or on, and nothing here is downloaded.
There are two kinds, kept visibly apart because the difference matters:

**Built-in switches** change what the app itself does. Nothing is loaded at
runtime — the behaviour is already compiled into the APK, and the switch only
decides whether it is reachable. A switch cannot do anything the binary cannot
already do.

**Bundled plugins** are ordinary Python that ships inside the app. They are
installed for you on first run and left **off**, and when you turn one on it
runs with everything the app can do — exactly like a plugin you installed
yourself. They appear under *Ships with PyCmd*, and they cannot be deleted,
because the next start would only put them back.

If you want to write one of your own, [PLUGINS.md](PLUGINS.md) is the guide.

---

## Bundled plugins

### Server Pro

Makes the Servers tab somewhere you can work rather than somewhere you press
Start.

When it is on, a **Server Pro** card appears in the Servers tab with a live
board of everything running. For each server it shows the thing the tab could
not tell you on its own: whether the port **actually answers**. A thread being
alive is not the same as a service being up, and the difference is most of the
debugging.

* **Restart** stops a server and starts the same thing again on the same port,
  waiting for the socket to come back rather than racing it.
* **Kill** forces one down; **Stop** asks nicely first.
* **Free ports** finds the next eight ports nothing is listening on.
* **Write index.html** builds a real page listing a folder that has none, for
  when serving a folder shows a bare file listing.

Console commands:

| Command | What it does |
|---|---|
| `servers` | Everything running, with health, uptime and request counts |
| `serve <file-or-folder> [port]` | Starts anything — a script, a page, a folder |
| `restart <handle\|all>` | Stop and start again on the same port |
| `shut <handle\|all>` | Stop, and kill it if it will not go |
| `ports [from]` | Which ports are free |

### Cloud

Supabase and Firebase, over their REST APIs, with nothing to install. Neither
official SDK can be pip-installed onto a phone without a compiler, so this
talks to both services the way their SDKs do — JSON over HTTPS — and gives you
the same shape of API.

Connect a project once in **More → Cloud**. The keys are saved in the app's own
storage, never in the workspace, so exporting or sharing your files never
carries them along. After that the same project is reachable from a script, a
server, the console and the panel, signed in as the same user.

The panel does the everyday things: connect and test, sign a user up or in,
read and write rows or documents, browse storage, poke the Realtime Database,
call a Postgres function. It also adds a **Cloud storage** section to the Files
tab for sending a workspace file up or pulling one down.

Console commands:

| Command | What it does |
|---|---|
| `cloud` | What is connected, and how to connect it |
| `sb select notes 5` | Read five rows |
| `sb insert notes {"text":"hi"}` | Write a row |
| `sb delete notes id=3` | Delete matching rows |
| `sb rpc my_function {"a":1}` | Call a Postgres function |
| `sb count notes` | How many rows match |
| `sb signin <email> <password>` | Sign in and keep the session |
| `sb buckets` / `sb ls <bucket>` | Storage |
| `sb up <bucket> <file>` / `sb down <bucket> <remote>` | Files up and down |
| `fb get notes/today` | Read a Firestore document |
| `fb set notes/today {"done":true}` | Write one |
| `fb list notes 20` | List a collection |
| `fb query notes done == false` | A structured query |
| `fb rt get rooms` | The Realtime Database |
| `fb up <file>` / `fb down <remote>` | Storage |

And from your own code:

```python
import pycmd_cloud

sb = pycmd_cloud.supabase()
rows = sb.table("notes").select("*").eq("done", False).order("id").limit(10).run()
sb.table("notes").insert({"text": "written from a server"})

fb = pycmd_cloud.firebase()
fb.firestore.set("notes/today", {"text": "hello", "done": False})
print(fb.firestore.query("notes", where=[("done", "==", False)], limit=5))
```

That is 116 operations across the two services: PostgREST filters and queries,
GoTrue sign-up, sign-in, OTP and the admin endpoints, Supabase Storage and edge
functions, Firestore documents and structured queries, Identity Toolkit, the
Realtime Database and Firebase Storage.

**What is deliberately missing:** Supabase realtime subscriptions and Firestore
listeners. Both are WebSocket protocols, `urllib` does not speak WebSocket, and
a fake built out of polling would be a worse thing to have than an honest gap.
Poll the read calls yourself if you need to; they are cheap.

### Scheduler

Runs a script again every so often — a backup every ten minutes, a scrape every
hour — without writing a sleep loop into the script itself, which would stop it
being runnable any other way.

Adds a **Scheduled jobs** section to the Servers tab, and two commands:

| Command | What it does |
|---|---|
| `every 300 backup.py` | Run it every five minutes |
| `jobs` | What is scheduled, and when each one runs next |
| `jobs stop <id>` / `jobs stop all` | Stop one, or all of them |

Jobs live as long as the app does. Android gives an app no promise of being
alive later, so nothing here claims a schedule that survives being closed.

---

## Built-in switches

### The kit

| Plugin | What it does |
|---|---|
| **Polyglot Files** | Create and edit 25+ file types, not just `.py`. Decides which types the new-file menu offers. |
| **Polyglot Runner** | Actually run them: C, Go, Rust and JavaScript on the device. |
| **Power Pack** | Turns the other plugins up — more snippets, more tools, more of each panel. |

Turning all three on is what the plugin list calls the full kit.

### Languages, tools and workflow

| Plugin | What it does |
|---|---|
| **Snippets** | A bar of one-tap code fragments while you write, per language. |
| **Autosave** | Saves the editor a moment after you stop typing. |
| **Keep Awake** | Stops the screen sleeping while something is running. |
| **Downloader** | Fetch a file from a URL into Downloads. |
| **Workspace Export** | Zip the workspace, or any folder, and save it to the device. |
| **Workspace Search** | Search inside every file, not just the names. |
| **JSON Tools** | Validate, format and inspect JSON on its own screen. |
| **Text Tools** | Case, sort, dedupe, count, encode — the everyday text jobs. |
| **Regex Lab** | Write a pattern and watch it match, live. |
| **HTTP Client** | Build a request, send it, read the response. |

---

## Why the two kinds are kept apart

A built-in switch is auditable by construction: the code is in the binary you
installed, and the switch cannot reach anything else. A plugin — bundled or
yours — is Python running with the app's own powers, which is what makes
plugins worth having and also what makes them worth a warning. The install
screen says so before the file picker ever opens, and the same is true of the
three above: they are ours, but they are not a different kind of thing.
