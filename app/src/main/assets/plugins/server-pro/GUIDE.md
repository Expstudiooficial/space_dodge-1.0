# Using Server Pro

Everything here appears once Server Pro is switched on.

## The board

Open the **Servers** tab. Below the launcher there is a **Server Pro** card
with every server you have running.

The column worth having is **health**. A server can be "running" — meaning its
thread is alive — and still not be answering anything, because it crashed
between binding the socket and serving, or never bound one at all. Health says
which:

| It says | It means |
|---|---|
| `answering` | Something connected to that port and got a reply |
| `not answering` | The port is not accepting connections |
| `no port` | It never declared one, so there is nothing to check |

**Restart** stops a server and starts the same thing again on the same port,
waiting for the socket to be released rather than racing it. **Kill** forces
one down; **Stop** asks first.

## Free ports

Tapping **Find free ports** lists the next eight nothing is listening on,
starting from whatever you type. Useful before starting three things at once.

## A folder with no index page

Serving a folder that has no `index.html` shows a bare file listing. Put the
folder's full path in **Write index.html** and it builds a real page linking to
everything in it. It refuses to overwrite one that already exists.

## Console commands

```
servers                 # everything running, with health and uptime
serve site 8000         # start a folder, a file, or a page
serve app.py            # a script - any language the app can run
restart srv1            # or: restart all
shut srv1               # stop, then kill if it will not go
ports 8100              # free ports from 8100 up
```

`serve` takes the same things the Servers tab does: a Python script, a C, Go or
Rust program, a JavaScript file, an HTML page (its folder gets served), or a
whole folder.
