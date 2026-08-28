# Prebuilt APK

`PyCmd-2.2-debug.apk` — ready to install, nothing else needed.

| | |
|---|---|
| Package | `com.expstudio.pycmd.debug` |
| Version | 2.2-debug |
| Size | 33 MB |
| Signed with | the standard Android debug key |
| Works on | Android 7.0 (API 24) and newer, **arm64-v8a** (every phone since about 2016) |
| SHA-256 | see [SHA256SUMS.txt](SHA256SUMS.txt) |

## What is new in 2.2

**A long line stopped being editable past a certain point.** The editor sized
its textarea from the highlighted layer underneath it, and that layer is an
absolutely positioned box - which shrink-to-fits *within its container*. Past
the width of the screen it stopped growing, so the textarea did too, and the
end of a long line became unreachable. Nothing is measured that way any more:
the character width is taken from the real font once and every width and height
after that is arithmetic, which cannot be capped by anything.

**And why it was intermittent.** The editor's page is built before its tab is
ever shown, so that one measurement landed on a view with no width and fell
back to a guess. It now notices it measured nothing and takes the numbers again
the moment the page has a size - and again if the font swaps in later.

**Wrap long lines**, in the editor's ⋮ menu, with the gutter kept honest: each
line number grows as tall as its line now takes, and it is redrawn when a line
gains a row rather than only when the file gains a line. **Go to line...** is
in the same menu.

**Each language indents its own way.** Python's rules were applied to all six,
so a Go file got no indent after `{` and an unwanted outdent after `return`.
Enter now follows the language, typing `}` steps back out a level, and the key
strip above the keyboard offers that language's characters - `;` and `//` for
the brace languages, `<` and `>` for markup - instead of `self` and `#` for
everything.

**The caret is kept on screen** while you type off the edge of a line, and the
editor no longer copies the whole document to work out which line it is on -
which it did on every tap, twice, and which is a good deal of why a long file
felt heavy. Android's swipe typing and autocorrect are also left alone
mid-word, rather than having the layer under them rewritten while a word is
still being composed.

## What was new in 2.1.1

**Plugin settings actually work.** Every control was drawn from the values
Python had returned, and nothing ever wrote back into that - so a switch sprang
back the instant it was tapped and a choice never moved. The form owns its
state now; saving is what happens afterwards, and typing is coalesced so a word
is one write rather than one per letter.

**A long description no longer makes a card taller than the screen.** It
collapses to three lines with *Show more*, and a plugin's file list caps at
twelve.

**Plugins can add their own guides.** A `guides` block lists documents of
yours - `.md`, `.txt` or `.html` - in the app's **Guides** screen under *From
your plugins*, opened in the same reader the app's own guides use. All three
bundled plugins now ship one, so switching Cloud on and wondering what to type
has an answer one tap away.

## What was new in 2.1

**A plugin's section scrolls.** Opening one inside an existing screen put a
scrolling page inside a scrolling list, and the list won every gesture - so the
section could not be scrolled at all. The page now claims a drag that starts
inside it, and hands it back at the top and the bottom so flicking past the
section still works. There is also a button on every section header that opens
the same page with the whole screen to itself.

**Plugins can do considerably more.**

* **Settings** - declare `text`, `number`, `switch` or `choice` fields and the
  app draws real controls in the plugin's row. `api.setting("name")` reads
  whatever the user chose. A plugin with one switch no longer needs a whole
  HTML page to offer it.
* **Lines in a file's menu** - `actions` puts your own entry in the ⋮ menu of a
  file or folder in the Files tab, filtered by extension, calling your export
  with the path.
* **Asking the app to do something** - `api.open_file`, `api.run_file`,
  `api.preview`, `api.serve`, `api.new_file`, `api.go_to`, `api.open_panel`
  and `api.refresh`. Requests rather than calls: they never wait, and they are
  ignored if the plugin has been switched off in the meantime.

The Cloud plugin uses all three: four settings, and *Upload to cloud storage*
on any file.

**`api.toast()` works.** It emitted into a flow nothing was reading, so it has
never shown anything. Found while wiring the rest of this.

**The About dialog says the right version.** It said 1.0 for four releases,
because a string in a composable has no way of knowing it is out of date. It
now reads the version out of the build, so it cannot drift again.

## What was new in 2.0

**Plugins can change the app, not just sit beside it.** A plugin already had a
tab of its own; now it can also put a card of its own **inside** one of the
app's existing screens - Files, Servers, Packages, Downloads, Plugins, System,
Debug or Guides - with its own page, its own icon and its own height. Nothing
about the app has to change to make room. That is how Server Pro reaches the
Servers tab and how Cloud reaches Files.

**Three plugins now ship with it**, installed on first run and switched off
until you want them, listed under *Ships with PyCmd* instead of pretending you
installed them:

* **Server Pro** - a live board in the Servers tab with a health check that
  says whether each port really answers, restart, a free-port finder, an
  index-page writer, and the commands `servers`, `serve`, `restart`, `shut`
  and `ports`.
* **Cloud** - Supabase and Firebase over their REST APIs, with nothing to
  install.
* **Scheduler** - run a script again every so often: `every 300 backup.py`.

**Supabase and Firebase, properly.** 116 operations across the two: PostgREST
selects, filters, inserts, upserts, counts and Postgres functions; GoTrue
sign-up, sign-in, OTP and the admin endpoints; Supabase Storage and edge
functions; Firestore documents, typed values and structured queries; Identity
Toolkit; the Realtime Database; Firebase Storage. Connect a project once in
More → Cloud and a script, a server, a console command and the panel all reach
it as the same user. The keys live in the app's own storage, never in the
workspace, so exporting your files never carries them along. Realtime
subscriptions are the one honest gap - both are WebSocket protocols and
`urllib` does not speak WebSocket, so there is a gap rather than a fake.

**The Servers tab does more.** It takes a folder as happily as a file, and a
running server has a **View** button that opens it in the preview.

**A new guide**, on the phone and in the repo: *The plugins that ship with it*
covers every built-in switch and every bundled plugin, and the difference
between the two.

## What was new in 1.4

**The Servers tab runs anything, not just Python.** A C, Go or Rust file goes
to its interpreter; a `.js` file to the device's own JavaScript engine; an
HTML page serves the folder it sits in and opens on that page. The form says
which of those it is about to do *before* you press Run, and refuses up front
anything that cannot run here at all, with the reason.

**Plugins can add a tab of their own.** A `tab` block in the manifest - a name,
one line of description, and an image file the plugin ships - puts a row in
**More** that opens the plugin's panel. No change to the app, and it only
appears while the plugin is switched on. PLUGINS.md documents it, and
**Server Pro** is a working example of it.

**Server Pro**, a plugin that ships switched off. Turn it on and you get a live
board of everything running with a health check that says whether the port
actually answers, Restart and Kill on each one, a free-port finder, an
index-page writer for a folder that has none, and the console commands
`servers`, `serve`, `restart`, `shut` and `ports`.

**Answering the doctor no longer freezes anything.** Saying `yes` to "install
pygame" used to run the download on the thread the Stop and Kill buttons come
in on - so the server froze, and the button meant to rescue it was stuck behind
the same queue. The fix now runs on its own thread, Stop and Kill have threads
nothing else can occupy, and the console says what is happening as it happens:
*OK - downloading pygame from PyPI*, *OK - renaming index2.html to index.html*,
*OK - no fixing today*. A reply that is neither yes nor no gets an answer too,
instead of silence.

**Kill works on a wedged server.** A script parked in its own `accept()` cannot
be interrupted - an async exception has nowhere to land inside a blocking C
call - so Kill now knocks on the port first, which makes the call return and
the exception fire. Before this it detached and left the port held.

**Pasting a long program is instant.** It used to take about twenty seconds:
the console's input box laid out every line of what you pasted before it could
draw six of them, on every redraw. A pasted program is now held beside the box
as *"2 599 lines pasted"* with Run and Clear. The editor got the same
treatment - a big document repaints immediately in plain text and colours
itself once you stop typing - and console output is now sent to the screen in
batches rather than one line at a time.

**A server's console keeps what the script printed.** It only ever kept its own
two lines, so reopening a server console showed "Running x" and nothing else.

## What was new in 1.3

**Previews that scroll.** A code block used to be its own sideways scroll
strip, and on a touch screen a strip like that swallows a vertical drag - which
is why a long document, the plugin guide most of all, felt like it was ignoring
the scroll. Code now wraps instead, so the drag reaches the page. Long
documents also get a Contents panel that jumps to any section, and there are
A- / A+ buttons for text size.

**Previews for plain text.** A `.txt` or `.log` file opens as a readable page
with its line, word and character counts, instead of raw unwrapped text.

**Everything is served the same way.** The guides that ship inside the app now
come off the same loopback server as a file preview, so anchors, scrolling and
reloading behave identically wherever you are.

**Folders out to the device.** Any workspace folder can be exported as a zip
from its menu in Files, and anything in Downloads has a *Save to device*
button that writes it out through the system picker - into the phone's real
Downloads folder, or straight onto a USB drive. That is the route off the
phone: a picker can hand over a file, never a folder, so a folder becomes a
zip first. Single workspace files have the same *Save to device* item.

## What was new in 1.2

**Plugins you write yourself.** A plugin is Python the app imports, plus an
optional HTML panel that becomes its own tab. Install from a file, a folder or
a zip - or from the workspace, for a plugin written inside PyCmd itself. They
are not sandboxed, and the app says so on a screen you have to read before the
picker opens. PLUGINS.md is the authoring guide, and the app can show it on the
phone: Plugins -> How do I write one?

**Preview that behaves like a browser.** A page is served over a loopback HTTP
server rooted at its own folder, so scripts run, stylesheets and images load by
relative path, `fetch` works, and links inside the site follow. Buttons work.
Preview also covers JavaScript (runs it and shows what it logged), JSON, CSV,
SVG and images.

**It offers to fix what it can.** A missing file one typo away from one that
exists, an import of a package that is not installed, a port already in use, a
served folder with no index page: the console says what it would change and
waits for `yes`. It never acts on its own.

**Upload from anywhere.** Files can take several files at once, or a whole
folder, from the system picker.

**Search** in the file list and in the plugin list.

**Two more screens** behind More: Guides (the manuals, on the phone) and System
(versions, storage, what is running, and housekeeping).

## What was checked before this was committed

The same source, built for x86_64, was installed on an Android 11 emulator and
driven through: Go, Rust and JavaScript ran from the Files tab with the right
output, an HTML page previewed with its external stylesheet and script loaded
and its button working, a plugin was installed from the workspace and switched
on, its console command answered, and its panel called back into its own
Python. The APK here is that source built for arm64 instead, which changes
the CPython binaries and nothing else.

762 checks run before any of this is committed: `test_runtime.py` (145),
`test_plugins.py` (120), `test_go.py` (92), `test_rust.py` (73),
`test_cloud.py` (68), `test_bundled.py` (61), `test_c.py` (54), `test_js.js`
(43), `test_editor.js` (46), `test_doctor.py` (37) and `test_preview.py` (23). Each language check is a real program paired with the
output the real compiler produces. The rest go after the things that are
awkward to be sure of by looking: a script wedged in `accept()` is started for
real and killed, to prove the port comes back; the preview checks fetch pages
back off the loopback server; the editor checks run the real
editor against a stand-in DOM and read back the widths and heights it writes,
so the sizing is arithmetic that can be checked - including the case that
caused this release: a page measured before it was ever on screen. `tools/run-tests.sh` runs the lot, then
a debug build and Android Lint.

`test_cloud.py` runs a local HTTP server that plays Supabase and Firebase,
records exactly what the client sent, and answers the way the real APIs do -
which is what makes the URL shapes, the PostgREST filter syntax and Firestore's
typed values checkable rather than hopeful. `test_bundled.py` installs the three
bundled plugins the way the app does and drives them: it starts a real server
and restarts it through Server Pro, schedules a real job, and renders every
panel.

The 2.2 changes were verified by those checks and by Lint on the built APK,
not on an emulator: this build machine has no hardware virtualisation, so no
emulator could be started for it.

It is a debug build, so it is already signed and installs without any keystore
or Play Store involvement. It also carries the `.debug` package suffix, which
means it can sit alongside a release build of the same app without either one
replacing the other.

## Installing it on a phone

1. Download the APK onto the phone (or copy it across by USB).
2. Open it from the Files app or the download notification.
3. Android will ask whether to allow installs from this source — that prompt
   appears for any app that did not come from a store. Allow it, then confirm
   the install.
4. Launch **PyCmd**.

The first launch takes a few seconds longer than later ones: the Python
interpreter and its standard library are unpacked on that first run. The title
bar shows `starting` until it is ready, then switches to `Python 3.13.x`.

Once it's running, see [../TUTORIAL.md](../TUTORIAL.md) for a walkthrough of
every tab with things to paste in and try.

## Installing over USB

```bash
adb install -r dist/PyCmd-2.2-debug.apk
```

## Checking the download

```bash
sha256sum -c dist/SHA256SUMS.txt
```

## A note on the device requirement

This APK carries **arm64-v8a** binaries only, which is what keeps it to 32 MB
rather than 46 MB. Every Android phone sold in roughly the last decade is
arm64, so this is the right build for a real device.

Two cases need a different build. A 32-bit-only phone from before about 2016
cannot run it at all: Chaquopy's Python 3.13 runtime ships no 32-bit binaries.
An **x86_64 emulator** needs the x86_64 slice, which the default build
produces:

```bash
./gradlew :app:assembleDebug      # both ABIs, one APK per ABI plus a universal one
```

## Rebuilding it yourself

```bash
./gradlew :app:assembleDebug -Ppycmd.abi=arm64-v8a
# -> app/build/outputs/apk/debug/app-debug.apk
```

Leave the property off to build for both ABIs instead.

See the [main README](../README.md) for what the build needs.
