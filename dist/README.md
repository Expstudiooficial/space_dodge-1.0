# Prebuilt APK

`PyCmd-2.4.2.apk` — ready to install, nothing else needed.

| | |
|---|---|
| Package | `com.expstudio.pycmd.debug` |
| Version | 2.4.2 |
| Size | 18 MB |
| Signed with | the key in [`keystore/`](../keystore/), committed so updates can install over it |
| Works on | Android 7.0 (API 24) and newer, **arm64-v8a** (every phone since about 2016) |
| SHA-256 | see [SHA256SUMS.txt](SHA256SUMS.txt) |

## What is new in 2.4.2

**It is a release build now, and half the download.** **35 MB to 18 MB**, same
source, packaged the way an app is meant to be shipped.

Two things did it. R8 strips out the AndroidX and Compose code this app never
calls - 10 MB of dex down to 3 - and resources nothing references go with it;
the `debuggable` flag, which let anything with a USB cable read the app's
private storage, is gone at the same time. Then the native libraries: CPython
and its OpenSSL are 10 MB, and modern packaging stores them uncompressed so
Android can map them straight out of the APK. That is the right trade for an
app downloaded through a store, which compresses the transfer itself; this one
is a raw APK coming down somebody's phone connection, where 10 MB is 10 MB.
Compressed they are 3.7.

The cost of that second one is worth knowing: Android unpacks those libraries
when it installs, so the app takes about 10 MB more room on the device and the
install itself is a little slower. The download is half the size. If you would
rather have the storage back, that is one line in `app/build.gradle.kts`.

**And it still updates in place.** It carries the same application id and the
same signing key as every build before it, so it installs straight over
2.4.1-debug - or over 2.3 - and keeps the workspace. That is also why a release build says
`.debug` in its package name: Android has no way to change an installed app's
id, and a new one would install *beside* the old app rather than over it,
leaving the workspace behind in the copy nobody opens again. The id is a name,
not a claim about the build.

**Nothing else changes.** `latest.json` points at this APK, the app checks the
same address it always did, and **More → System → Check for updates** downloads
it, verifies the hash and the signature, and installs it over itself. There is
nothing to set up and no site to visit.

**What R8 was told to leave alone.** Everything reached by name rather than by
a call: Chaquopy's runtime, this app's own classes (Python calls back into
several of them by method name, and a renamed method is a crash that only
happens on a phone), and anything a WebView invokes from JavaScript. The build
now runs in the test suite too, so a keep rule that stops being right fails
here rather than after a download.

## What was new in 2.4.1

**Pointing Run at a folder runs the project in it.** It used to mean one thing -
hand the folder to a file server - so a Flask project answered with a directory
listing of `static/` and `templates/`: the files, correct and useless. A folder
is now looked into first, and the first of these wins:

| In the folder | What Run does |
|---|---|
| `app.py`, `server.py`, `wsgi.py`, `manage.py`, `main.py`... that imports Flask, Django, FastAPI, `http.server`... | Runs it. That is the app. |
| `index.html` | Serves the folder and opens that page |
| one of those entry names that serves nothing | Runs it anyway - it is still the front door |
| exactly one runnable file | Runs that one |
| none of the above | Serves it as a listing, and says why on the page |

Whether a script serves is read out of the file rather than guessed from its
name: `main.py` that imports Flask is a server, `main.py` that crunches numbers
is not, and starting the second one because it had the right filename would be
its own kind of wrong. The launch form says which it picked **before** you press
Run, and "Serve a folder" now offers a one-tap **Run app.py instead** when there
is something in there to run.

**Flask apps get the port you chose.** `app.run()` binds `127.0.0.1:5000` with
the auto-reloader on - on a phone that is a server nothing can reach,
restarting itself with a process launcher Android does not have. PyCmd now
fills in the host and port the form asked for wherever the code left them out,
and turns the reloader off. Code that names its own port still wins, and the
server card corrects itself to the port the app really took, read from what the
framework printed - a View button pointing at the wrong port is how a working
server looks broken.

**The listing itself is worth reading now.** A folder with no `index.html` used
to answer with Python's bare `<ul>` of names. It is now a real page: folders
first, sizes, which files this device can run, a way back up - and, at the top
of the tree, a sentence saying why you are looking at a list at all. The most
useful one names the exact mistake behind the screenshot that prompted this
release: `templates/` and `static/` with no `app.py` is the *inside* of a Flask
project, and the app that renders those templates is the folder above.

**https on an http port says so.** Browsers increasingly try HTTPS first for a
bare address like `10.1.6.64:8000`. The handshake arrived as unparseable bytes
and produced a wall of "Bad request version" in the console. It is now one
line, once: something tried https, here is the http address to open.

## What was new in 2.4

**PyCmd can update itself now.** **More → System → Check for updates** reads a
small published manifest, and if there is a newer build it downloads it, checks
it against the fingerprint published beside it, checks it carries the same
signing key as the build you are running, and hands it to Android to install
**over** this one. Your workspace, the packages you installed with pip, your
plugins and every setting stay exactly where they are - Android replaces the
app rather than removing it. Deleting PyCmd first is the thing that loses all
of that, and until now that was the only way to move between versions.

**Which needed one key, kept in the repo.** Android only lets an APK replace an
installed one when both were signed by the same key, and Gradle's debug key is
generated per machine - so two builds of the same source, made in two places,
were two different apps to the installer. [`keystore/pycmd.keystore`](../keystore/)
is now that one key (the standard Android debug certificate; not a secret, not
for a store), and this APK is signed with it. It is the same key 2.3 was signed
with, so **2.4 installs straight over 2.3**. From here on, every build can.

**And it tells you an update exists.** Once a day, while the app is running, it
reads that one manifest by itself and puts a dot on **More** and a line on the
System card if something newer is out. That is the whole of it: nothing is
downloaded until you press Download, nothing is installed until you press
Install, and a check that fails on a phone with no signal says nothing at all,
because it is not a question you asked.

**It tells you before it cannot.** A build calling itself another package, or
signed with a different key, is refused with the reason instead of being handed
to the installer to fail as "App not installed" - the failure that makes people
uninstall the app, which is precisely what empties the workspace. The address
it checks is editable too, at the bottom of the card: a fork, another branch, a
machine of your own. The fingerprint check runs whatever it points at.

**Music, video and everything else you do not type.** The new-file menu now
offers audio, video, images, PDFs, archives and fonts, and picking one opens the
phone's picker instead of writing a template - an empty `.mp3` is not a file
anybody wanted. They come in through the same importer as everything else, sit
in the workspace, and export back out. This rides with **Polyglot Files**, the
built-in kit plugin, along with the rest of the file types.

**And they play.** Tap an `.mp3` or `.mp4` and it opens a real player - with a
seek bar you can drag, because the preview server now answers HTTP byte ranges
(206, `Content-Range`, open-ended and suffix ranges, 416 past the end). Browsers
will not let you scrub without that, which is why a media file opened from a
`file://` URL only ever plays from the start. What decodes is the phone's
business: MP3, AAC/M4A, FLAC, Ogg, WAV, MP4 and WebM are safe, MKV and MOV
depend on the device, and the player says so rather than showing a dead control.

**A file that is bytes is never opened as text.** Tapping media opens the
player, and anything else with a NUL in its first few KB refuses the editor
with a sentence. The editor reads text: it turns every byte it cannot decode
into a replacement character, and saving that writes the ruined version over a
file that was fine a moment ago.

## What was new in 2.3

**The examples folder can be deleted.** It was re-created on every start, which
made `examples/` a folder you were not allowed to be rid of - not the app's
call to make. Deleting it sticks now, and **More → System → Put the examples
back** is there if you change your mind.

**An import that would overwrite something asks first.** Bringing in a
corrected file used to become `notes-2.md` in silence, so the old one stayed
exactly where every script still pointed at it - which is how you end up
debugging a file you already fixed. Worse for folders: copying over an existing
one failed partway through and left some new files sitting beside some old
ones. Now it asks - **Replace**, **Keep both** or **Cancel** - and says how big
what is already there is and when it last changed. Replacing a folder removes
the old one first, so nothing of it is left mixed in; replacing a file writes to
a neighbour and moves it into place, so a failure halfway cannot leave you with
neither.

**A file from the phone can go straight into Downloads.** It was a folder only
the app could fill - a URL fetch or an export - which made it the one place you
could not simply put something.

**Listings cannot show you the past.** Every refresh - files, downloads,
servers, packages - is tagged, and an older answer arriving late is dropped
instead of overwriting a newer one. Two refreshes racing is ordinary (an import
finishing while the Servers tab polls), and the slower one used to win whatever
it was holding.

**And two imports started in the same millisecond** were handed the same
staging folder, so the second one found the first one's files already sitting
in it.

## What was new in 2.2

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

835 checks run before any of this is committed: `test_runtime.py` (190),
`test_plugins.py` (120), `test_go.py` (92), `test_rust.py` (73),
`test_cloud.py` (68), `test_bundled.py` (61), `test_c.py` (54), `test_preview.py`
(51), `test_editor.js` (46), `test_js.js` (43) and `test_doctor.py` (37).
Each language check is a real program paired with the output the real compiler
produces. The rest go after the things that are
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

The preview suite covers this release's range serving directly: it asks the
real loopback server for `bytes=10-19`, an open-ended range and a suffix range,
and checks the status line, the `Content-Range` header and the exact bytes that
come back - plus a 416 past the end of the file and a nonsense `Range` falling
back to the whole file. `tools/make_latest.py` runs in the suite too, and fails
the build if `dist/latest.json` does not match the APK sitting beside it: a
manifest whose hash is stale is a download every phone would refuse.

The 2.4.2 packaging change was verified by building it and reading the result:
R8's own report says none of this app's classes or Chaquopy's were removed or
renamed (only empty static initialisers went), the APK still declares the same
package, versionCode 13 and the same signing certificate as 2.3 did, it is no
longer marked debuggable, and every asset - the Python runtime, the guides, the
bundled plugins, the examples - is still inside it. It has not been launched on
a device. If it misbehaves, install a newer build over it from the browser;
that path does not need the app to start.

The 2.4 changes were verified by those checks and by Lint on the built APK,
not on an emulator: this build machine has no hardware virtualisation, so no
emulator could be started for it. In particular, **the update flow has not been
run on a device** - what is checked here is that the manifest matches the APK,
that this APK carries the same signing certificate as 2.3
(`c318e126...4f8d6c`, confirmed with `apksigner`), and that the code paths
compile and lint clean.

It installs without any Play Store involvement. The signing key is in the repo,
which is what makes an update possible at all - and also means anybody can
build an APK this one would accept as an update. That is the price of shipping
an APK by hand rather than through a store; it is not a key to use for anything
published to one.

## Installing it on a phone

0. **Already running PyCmd? Do not uninstall it.** Install this straight over
   it - same key, same package, so Android upgrades it and keeps everything.
   Uninstalling is what deletes the workspace. (And from 2.4 on you will not
   need to do this by hand: **More → System → Check for updates**.)
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
adb install -r dist/PyCmd-2.4.2.apk
```

## Checking the download

```bash
sha256sum -c dist/SHA256SUMS.txt
```

## What `latest.json` is

The file the app checks. It is generated from the APK next to it, never typed:

```bash
python3 tools/make_latest.py dist/PyCmd-2.4.1-debug.apk --notes "one line"
python3 tools/make_latest.py            # checks the one that is there
```

| Field | What it is |
|---|---|
| `versionCode` | The build number. The app offers an update only when this is higher than its own. |
| `versionName` | What the card shows: `2.4.2`. |
| `package` | Which app this is for. A mismatch is refused before the download starts. |
| `url` | An `https://` address of the APK. Plain `http` is refused. |
| `sha256` | The APK's fingerprint. The download is checked against it and thrown away if it differs. |
| `bytes` | Its size, so the progress bar means something before the server says. |
| `notes` | One line, shown on the card. |

The check runs as part of `tools/run-tests.sh`, so a manifest that no longer
matches the APK in `dist/` fails the suite rather than reaching a phone.

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
