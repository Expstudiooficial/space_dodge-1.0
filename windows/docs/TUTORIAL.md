# Getting started

Fifteen minutes, from a downloaded exe to a program you compiled.

## 1. Open it

Double-click `PyCmd.exe`. There is no installer and no setup.

SmartScreen may warn you the first time — the exe is not signed by a
certificate Windows recognises. **More info → Run anyway**, or check the hash
first (see [README.md](README.md)).

The window opens on the **Console**, with a chip at the top saying which
Python is running. That Python is PyCmd's own, inside the exe; it is not your
system Python and cannot break it.

## 2. Say hello

Type into the box at the bottom:

```python
print("hello")
```

Press Enter. That is a real Python REPL — expressions print their value,
blocks run, and `input()` will stop and wait for you.

Now try something that is not Python:

```
ls
```

The console understands a small set of commands — `ls`, `cd`, `cat`, `run`,
`serve`, `tree`, `find`, `pip` — and everything else is Python. The split is
narrow on purpose: `ls` is a command, `ls = [1, 2]` is an assignment, and a
name you have defined always wins.

## 3. Install something

```
pip install requests
```

It installs into PyCmd's own `site-packages`, under
`%LOCALAPPDATA%\PyCmd\site-packages`. Nothing goes near your system Python.

```python
import requests
requests.get("https://example.com").status_code
```

## 4. Write a file

Go to **Editor**. Make a new file, choose **Python**, and you get a starter
template with highlighting, auto-indent and a snippet bar for that language.

Save it as `hello.py`. It lands in `%LOCALAPPDATA%\PyCmd\workspace` — an
ordinary Windows folder. Open it in Explorer if you like; PyCmd will not mind.

## 5. Run something that is not Python

This is the part the phone cannot do.

Make a new file, choose **Go**, and save it as `hello.go`:

```go
package main

import "fmt"

func main() {
	fmt.Println("hello from Go")
}
```

Go to **Run**, type `hello.go`, press Run. Watch the Console:

```
[PyCmd] no Go toolchain found - running on the interpreter built into PyCmd
hello from Go
```

It ran — on the Go interpreter PyCmd carries, the same one the Android build
uses. Now install the real thing.

## 6. Install a compiler

Go to **Toolchains**. It lists 51 compilers and interpreters and says which
are on this machine. Find **Go** under *Not installed* and press **Run**
beside `winget install GoLang.Go`.

Watch the Console — that is your own winget, running the line you would have
typed. When it finishes, press **Look again** at the top of the screen.

Run `hello.go` again:

```
[PyCmd] Go via Go 1.24.7
hello from Go
```

Same file, real compiler. That line is worth reading every time: the built-in
Go interpreter does not enforce types and the built-in Rust one has no borrow
checker, so a program that runs on an interpreter may still be rejected by the
compiler.

## 7. Serve something

Make a folder in the workspace with an `index.html` in it. Go to **Pages**,
point one at that folder, switch it on. It is served from your machine at a
real address — open it in a browser, `fetch` works, relative paths resolve.

Or from the console:

```
serve mysite
```

## 8. Look around

- **Languages** — all 65 file types, and whether this machine can run each.
- **Plugins** — thirteen built in, five that ship with the app, and a button
  to bring one over from your phone.
- **Guides** — everything, in the app.
- **System** — what is using disk, and whether there is a newer version.

## Where things are

```
%LOCALAPPDATA%\PyCmd\
  workspace\        your files
  site-packages\    what pip installed
  plugins\          installed plugins
  downloads\        fetched files and exports
  pages\            what was deployed, kept apart from your files
```

All ordinary folders. Back them up, put them in git, or point something else
at them.

## Making it portable

Put `PyCmd.exe` on a memory stick with a folder beside it, and start it with
`PYCMD_HOME` pointing at that folder:

```powershell
$env:PYCMD_HOME = "E:\PyCmd-data"
E:\PyCmd.exe
```

Your workspace, packages and plugins travel with the stick.
