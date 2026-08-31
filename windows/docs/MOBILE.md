# Coming from the phone

If you use PyCmd on Android, this is what carries over and what does not.

## Your plugins

**Most of them will just work, and that is not luck.** A PyCmd plugin is a
folder with a `plugin.json`, some Python and some HTML. None of that is
Android-specific, because the plugin API never was — it is the app's own
Python engine either side, and the panel is a WebView either side.

**Plugins → Bring a plugin over from the phone** takes a folder or a `.zip`.
Before installing anything, PyCmd *reads* it and tells you what it found.

### This is a beta, and here is exactly what that means

It is not "we have not tested it". It is that a plugin can ask for things this
machine does not have, and no amount of good will makes them appear. PyCmd
looks for four specific things and names each one it finds:

| What it finds | What happens here |
|---|---|
| `permissions: ["notifications"]` | Android's notification system. PyCmd's own toasts stand in, so the plugin is heard, but it will not look the same or survive the window closing. |
| `permissions: ["wakelock"]` | Android wake locks. Windows has no equivalent an app may take. Ignored; the Keep Awake built-in covers the same ground. |
| `permissions: ["media"]` | Android's media session — what draws the lock-screen controls. Windows has no lock screen to draw them on. |
| `from java import …`, `com.chaquo…`, `/storage/emulated`, `/data/user/0` | The plugin reaches for Android directly. Those lines will raise on Windows. Many plugins guard them and degrade gracefully; some do not. |

A plugin with none of those is reported as **should work**, and in practice it
does. One with any of them is reported as **partly**, with each finding named
and explained, and you decide.

Nothing is imported to find this out. Reading a plugin to decide whether to
run it, and running it to find out, are not the same thing — the second one is
how a plugin gets to do something you did not agree to.

Installed plugins arrive **switched off**, like any other.

## Your files

Copy them. The workspace is an ordinary folder here —
`%LOCALAPPDATA%\PyCmd\workspace` — so anything that came off the phone goes in
and works. There is no import step and no format.

Scripts that hard-code `/storage/emulated/0/...` will need those paths
changed; nothing else should.

## What you gain

- **Thirty-one more languages**, and forty-three that actually run instead of
  six.
- **Real compilers.** Your `.go` file runs on Go, not on our interpreter. Your
  `.rs` file gets a borrow checker.
- **A file system.** The workspace is a folder you can open in Explorer, put
  in git, or point another program at.
- **`pip install` of things with C extensions**, because there is a compiler.
- **A window you can resize**, and two panes side by side.

## What you lose

- **The Music tab.** It is not here. The library and playlists would port
  fine, but the half that mattered was Android's media session drawing
  controls on the lock screen and in quick settings, and Windows has no
  equivalent worth imitating. Play music in something built for it.
- **Running in your pocket.** Obviously. But the servers keep running while
  the window is minimised, which is the part that mattered.

## Settings

They do not sync — there is no account and nothing is uploaded. But the
built-in plugin switches use the same ids on both, so
`%LOCALAPPDATA%\PyCmd\builtins.json` and the phone's preferences mean the same
things, and copying one across does what you would expect.

## Updates

The two are separate releases on separate schedules, with separate manifests —
`dist/latest.json` for the APK, `dist-windows/latest.json` for the exe. The
Windows build will never offer you an APK, and the phone will never offer you
an exe.
