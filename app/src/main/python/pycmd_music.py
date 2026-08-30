"""The music library: what was imported, and what order to play it in.

Writing code on a phone is long and quiet work, and the phone that runs the
editor is the same phone that would otherwise be playing something. So the app
carries its own small library rather than sending anybody out to another app:
files are copied in once, kept in the app's own storage, and played from there
with no network and no permission to read the rest of the device.

The split is the usual one. This module is the *library* - what a track is,
what a playlist is, what order things are in, and what survives a restart.
Playback itself is Kotlin, because only Kotlin can hold a media session, put
controls on the lock screen and keep sound going while the app is not on
screen. Nothing here plays anything, and nothing here knows how.

Two things worth stating because they are decisions, not accidents:

* **A video file is imported for its audio.** People have `.mp4` files they
  want the sound of, and pulling out the audio at import time would mean
  transcoding on a phone. Instead the file is kept whole and the player is
  told to ignore its video track, which costs nothing and loses nothing.
* **Files are copied, not linked.** A track picked out of a content provider
  is a URI that may stop resolving the moment the picker forgets it, and a
  library of dead links is worse than an empty one. The copy is the library.

The registry is one JSON file written whole. A library is small - a few
hundred rows of a few fields - and the alternative, a database, would be a
migration to maintain for something that fits in a phone's clipboard.
"""

from __future__ import annotations

import json
import os
import re
import time

__all__ = [
    "configure",
    "library",
    "tracks_dir",
    "adopt",
    "rename_track",
    "remove_track",
    "create_playlist",
    "rename_playlist",
    "remove_playlist",
    "add_to_playlist",
    "remove_from_playlist",
    "move_in_playlist",
    "queue",
    "remember",
    "tidy",
    "stats",
    "MAX_TRACKS",
    "MAX_PLAYLISTS",
    "MAX_PLAYLIST_TRACKS",
]

# Ceilings, so a list stays a list. None of these is a technical limit; they
# are the point past which a screen stops being something you can read.
MAX_TRACKS = 2000
MAX_PLAYLISTS = 200
MAX_PLAYLIST_TRACKS = 1000

# What the importer will take. The player reads far more than this, but a
# library that accepts a `.txt` because somebody renamed it is a library with
# a row in it that will never play.
AUDIO = {
    ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus", ".flac",
    ".mid", ".midi", ".amr", ".mka", ".wma", ".aiff", ".aif", ".3gp",
}
VIDEO = {".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".3g2", ".ts"}
PLAYABLE = AUDIO | VIDEO

LOOP_MODES = ("off", "all", "one")

# How recent a file has to be for `tidy` to leave it alone: long enough for a
# copy that has not been registered yet to finish.
GRACE = 120

_root = ""
_tracks = ""
_registry_path = ""


def configure(music_dir: str) -> str:
    """Called once by the app. Everything below lives under this folder."""
    global _root, _tracks, _registry_path

    _root = os.path.abspath(music_dir)
    _tracks = os.path.join(_root, "tracks")
    os.makedirs(_tracks, exist_ok=True)
    _registry_path = os.path.join(_root, "library.json")
    return _tracks


def tracks_dir() -> str:
    """Where the app copies an imported file to before registering it."""
    return _tracks


def _require() -> str:
    if not _root:
        raise RuntimeError("pycmd_music.configure() has not been called")
    return _root


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def _blank() -> dict:
    return {"tracks": [], "playlists": [], "state": {}}


def _read() -> dict:
    try:
        with open(_registry_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _blank()
    if not isinstance(data, dict):
        return _blank()
    # A file that was hand-edited, or written by an older build, should cost
    # the field it broke rather than the whole library.
    return {
        "tracks": [row for row in data.get("tracks", []) if isinstance(row, dict)],
        "playlists": [row for row in data.get("playlists", []) if isinstance(row, dict)],
        "state": data.get("state") if isinstance(data.get("state"), dict) else {},
    }


def _write(data: dict) -> None:
    _require()
    # Written to a neighbour and moved into place. The registry is the only
    # record of what is in the library, and a half-written one loses all of it.
    temporary = _registry_path + ".part"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(temporary, _registry_path)


def _identifier(prefix: str, used: set) -> str:
    stamp = int(time.time() * 1000)
    candidate = f"{prefix}-{stamp}"
    suffix = 1
    while candidate in used:
        candidate = f"{prefix}-{stamp}-{suffix}"
        suffix += 1
    return candidate


def _clean(text: str, limit: int = 90) -> str:
    """A title as somebody typed it, minus what would break a list or a path."""
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", str(text or "")).strip()
    cleaned = cleaned.replace("/", "-").replace("\\", "-")
    return cleaned[:limit]


def _inside(path: str) -> bool:
    """True when [path] really is one of ours, rather than somewhere else."""
    try:
        resolved = os.path.realpath(path)
        root = os.path.realpath(_tracks)
        return os.path.commonpath([resolved, root]) == root
    except (OSError, ValueError):
        return False


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _decorate(row: dict) -> dict:
    path = row.get("file", "")
    exists = bool(path) and os.path.isfile(path)
    return {
        "id": row.get("id", ""),
        "title": row.get("title", "") or os.path.splitext(os.path.basename(path))[0],
        "artist": row.get("artist", ""),
        "file": path,
        "name": os.path.basename(path),
        "bytes": row.get("bytes", 0) or _size(path),
        "duration": int(row.get("duration", 0) or 0),
        "added": row.get("added", 0),
        "video": bool(row.get("video", False)),
        # A file can still go missing - a delete that half worked, storage
        # cleared under the app - and saying so is better than a row that
        # fails the moment somebody presses it.
        "missing": not exists,
    }


def _find(rows: list, identifier: str):
    for row in rows:
        if row.get("id") == identifier:
            return row
    return None


# ---------------------------------------------------------------------------
# Reading the library
# ---------------------------------------------------------------------------


def library() -> dict:
    """Everything the Music tab draws, in one call."""
    if not _root:
        return {"tracks": [], "playlists": [], "state": {}, "bytes": 0, "ok": False}

    data = _read()
    tracks = [_decorate(row) for row in data["tracks"]]
    by_id = {track["id"]: track for track in tracks}

    playlists = []
    for row in data["playlists"]:
        members = [by_id[key] for key in row.get("tracks", []) if key in by_id]
        playlists.append({
            "id": row.get("id", ""),
            "name": row.get("name", "Playlist"),
            "created": row.get("created", 0),
            "tracks": [track["id"] for track in members],
            "count": len(members),
            "duration": sum(track["duration"] for track in members),
            "bytes": sum(track["bytes"] for track in members),
            # The first few names, so a playlist row can say what is in it
            # without the screen having to open it first.
            "preview": ", ".join(track["title"] for track in members[:3]),
        })

    state = dict(data["state"])
    if state.get("loop") not in LOOP_MODES:
        state["loop"] = "off"
    state["shuffle"] = bool(state.get("shuffle", False))

    return {
        "ok": True,
        "tracks": tracks,
        "playlists": playlists,
        "state": state,
        "bytes": sum(track["bytes"] for track in tracks),
        "missing": sum(1 for track in tracks if track["missing"]),
        "limits": {
            "tracks": MAX_TRACKS,
            "playlists": MAX_PLAYLISTS,
            "playlist_tracks": MAX_PLAYLIST_TRACKS,
        },
    }


def stats() -> dict:
    """The counts alone, for a screen that only wants a badge."""
    data = _read()
    return {
        "tracks": len(data["tracks"]),
        "playlists": len(data["playlists"]),
        "bytes": sum(_size(row.get("file", "")) for row in data["tracks"]),
    }


def queue(playlist_id: str = "") -> dict:
    """The tracks to hand the player, in the order they should be heard.

    An empty id means the whole library, which is what the Music tab shows
    when no playlist is open. Missing files are left out rather than handed
    over: a player that is given a file that is not there stops, and stopping
    in the middle of a queue reads as the app breaking.
    """
    everything = library()
    if not everything.get("ok"):
        return {"ok": False, "error": "the library is not ready", "tracks": []}

    if not playlist_id:
        return {
            "ok": True,
            "name": "Everything",
            "tracks": [t for t in everything["tracks"] if not t["missing"]],
        }

    for playlist in everything["playlists"]:
        if playlist["id"] == playlist_id:
            by_id = {track["id"]: track for track in everything["tracks"]}
            ordered = [by_id[key] for key in playlist["tracks"] if key in by_id]
            return {
                "ok": True,
                "name": playlist["name"],
                "tracks": [track for track in ordered if not track["missing"]],
            }
    return {"ok": False, "error": "no such playlist", "tracks": []}


# ---------------------------------------------------------------------------
# Changing it
# ---------------------------------------------------------------------------


def adopt(path: str, title: str = "", artist: str = "", duration: int = 0) -> dict:
    """Registers a file the app has already copied into the tracks folder.

    The copying is Kotlin's, because the file arrives as a content URI that
    only the picker can open. By the time this is called the bytes are ours,
    and all that is left is to decide what the row says.
    """
    _require()
    path = os.path.abspath(str(path or ""))
    if not path or not os.path.isfile(path):
        return {"ok": False, "error": "that file is not there"}
    if not _inside(path):
        # The library owns what it deletes. A row pointing outside it would
        # mean "remove this track" could delete somebody's file.
        return {"ok": False, "error": "a track has to live in the music folder"}

    extension = os.path.splitext(path)[1].lower()
    if extension not in PLAYABLE:
        return {"ok": False, "error": f"{extension or 'that'} is not audio or video"}

    data = _read()
    if len(data["tracks"]) >= MAX_TRACKS:
        return {"ok": False, "error": f"the library holds {MAX_TRACKS} tracks"}

    # The same file imported twice is the same track, not two of them.
    for row in data["tracks"]:
        if os.path.abspath(row.get("file", "")) == path:
            return {"ok": True, "id": row.get("id", ""), "already": True}

    name = os.path.splitext(os.path.basename(path))[0]
    row = {
        "id": _identifier("track", {r.get("id") for r in data["tracks"]}),
        "title": _clean(title) or _clean(name) or "Track",
        "artist": _clean(artist, 60),
        "file": path,
        "bytes": _size(path),
        "duration": max(0, int(duration or 0)),
        "added": int(time.time()),
        "video": extension in VIDEO,
    }
    data["tracks"].append(row)
    _write(data)
    return {"ok": True, "id": row["id"], "title": row["title"]}


def rename_track(track_id: str, title: str, artist: str = "") -> dict:
    data = _read()
    row = _find(data["tracks"], track_id)
    if row is None:
        return {"ok": False, "error": "no such track"}
    cleaned = _clean(title)
    if not cleaned:
        return {"ok": False, "error": "a track needs a name"}
    row["title"] = cleaned
    if artist:
        row["artist"] = _clean(artist, 60)
    _write(data)
    return {"ok": True, "id": track_id, "title": cleaned}


def remove_track(track_id: str, delete_file: bool = True) -> dict:
    """Takes a track out of the library, and out of every playlist with it."""
    data = _read()
    row = _find(data["tracks"], track_id)
    if row is None:
        return {"ok": False, "error": "no such track"}

    data["tracks"] = [r for r in data["tracks"] if r.get("id") != track_id]
    for playlist in data["playlists"]:
        playlist["tracks"] = [key for key in playlist.get("tracks", []) if key != track_id]
    if data["state"].get("track") == track_id:
        data["state"]["track"] = ""

    removed = False
    path = row.get("file", "")
    if delete_file and path and _inside(path):
        try:
            os.remove(path)
            removed = True
        except OSError:
            # The row goes either way. A file that cannot be deleted is a
            # nuisance; a library row for a track nobody can see is a bug.
            removed = False
    _write(data)
    return {"ok": True, "id": track_id, "deleted": removed, "title": row.get("title", "")}


def create_playlist(name: str) -> dict:
    _require()
    data = _read()
    if len(data["playlists"]) >= MAX_PLAYLISTS:
        return {"ok": False, "error": f"that is {MAX_PLAYLISTS} playlists already"}
    cleaned = _clean(name, 60)
    if not cleaned:
        return {"ok": False, "error": "a playlist needs a name"}
    row = {
        "id": _identifier("list", {r.get("id") for r in data["playlists"]}),
        "name": cleaned,
        "created": int(time.time()),
        "tracks": [],
    }
    data["playlists"].append(row)
    _write(data)
    return {"ok": True, "id": row["id"], "name": cleaned}


def rename_playlist(playlist_id: str, name: str) -> dict:
    data = _read()
    row = _find(data["playlists"], playlist_id)
    if row is None:
        return {"ok": False, "error": "no such playlist"}
    cleaned = _clean(name, 60)
    if not cleaned:
        return {"ok": False, "error": "a playlist needs a name"}
    row["name"] = cleaned
    _write(data)
    return {"ok": True, "id": playlist_id, "name": cleaned}


def remove_playlist(playlist_id: str) -> dict:
    """Deletes the playlist. The tracks in it stay in the library."""
    data = _read()
    row = _find(data["playlists"], playlist_id)
    if row is None:
        return {"ok": False, "error": "no such playlist"}
    data["playlists"] = [r for r in data["playlists"] if r.get("id") != playlist_id]
    if data["state"].get("playlist") == playlist_id:
        data["state"]["playlist"] = ""
    _write(data)
    return {"ok": True, "id": playlist_id, "name": row.get("name", "")}


def add_to_playlist(playlist_id: str, track_ids) -> dict:
    """Adds one track or several, keeping the order they were given in."""
    data = _read()
    playlist = _find(data["playlists"], playlist_id)
    if playlist is None:
        return {"ok": False, "error": "no such playlist"}

    wanted = [track_ids] if isinstance(track_ids, str) else list(track_ids or [])
    known = {row.get("id") for row in data["tracks"]}
    current = list(playlist.get("tracks", []))
    added = 0
    for key in wanted:
        if key not in known or key in current:
            continue
        if len(current) >= MAX_PLAYLIST_TRACKS:
            break
        current.append(key)
        added += 1

    playlist["tracks"] = current
    _write(data)
    return {"ok": True, "id": playlist_id, "added": added, "count": len(current)}


def remove_from_playlist(playlist_id: str, track_id: str) -> dict:
    data = _read()
    playlist = _find(data["playlists"], playlist_id)
    if playlist is None:
        return {"ok": False, "error": "no such playlist"}
    before = list(playlist.get("tracks", []))
    playlist["tracks"] = [key for key in before if key != track_id]
    _write(data)
    return {"ok": True, "id": playlist_id, "removed": len(before) - len(playlist["tracks"])}


def move_in_playlist(playlist_id: str, track_id: str, delta: int) -> dict:
    """Moves a track up or down. The order of a playlist is the point of it."""
    data = _read()
    playlist = _find(data["playlists"], playlist_id)
    if playlist is None:
        return {"ok": False, "error": "no such playlist"}
    order = list(playlist.get("tracks", []))
    if track_id not in order:
        return {"ok": False, "error": "that track is not in this playlist"}
    position = order.index(track_id)
    target = max(0, min(len(order) - 1, position + int(delta or 0)))
    if target == position:
        return {"ok": True, "id": playlist_id, "moved": False}
    order.pop(position)
    order.insert(target, track_id)
    playlist["tracks"] = order
    _write(data)
    return {"ok": True, "id": playlist_id, "moved": True, "position": target}


def remember(loop: str = "off", shuffle: bool = False,
             track_id: str = "", playlist_id: str = "") -> dict:
    """Keeps what was playing, so opening the tab again picks it up.

    Only the choice is remembered, never the position: resuming a song from
    the middle when somebody opened the app hours later is a surprise, and
    surprises in a music player are the whole of what people hate about them.
    """
    data = _read()
    data["state"] = {
        "loop": loop if loop in LOOP_MODES else "off",
        "shuffle": bool(shuffle),
        "track": str(track_id or ""),
        "playlist": str(playlist_id or ""),
        "at": int(time.time()),
    }
    _write(data)
    return {"ok": True, "state": data["state"]}


def tidy() -> dict:
    """Drops rows whose file has gone, and files no row points at.

    Both halves happen: a delete that failed after the row went leaves a row
    pointing nowhere, and an import interrupted after the copy but before the
    row leaves bytes nothing can reach. Neither is common; both are invisible
    without this, which is why it is a button rather than a background job.
    """
    _require()
    data = _read()
    kept = [row for row in data["tracks"] if os.path.isfile(row.get("file", ""))]
    dropped = len(data["tracks"]) - len(kept)
    data["tracks"] = kept

    known = {os.path.abspath(row.get("file", "")) for row in kept}
    freed = 0
    orphans = 0
    fresh = time.time() - GRACE
    try:
        for name in os.listdir(_tracks):
            path = os.path.abspath(os.path.join(_tracks, name))
            if not os.path.isfile(path) or path in known:
                continue
            # An import is a copy and then a row, in that order, so a file
            # written seconds ago may be an import still in flight rather than
            # an orphan. Deleting that would lose the track being added.
            try:
                if os.path.getmtime(path) > fresh:
                    continue
            except OSError:
                continue
            size = _size(path)
            try:
                os.remove(path)
            except OSError:
                continue
            orphans += 1
            freed += size
    except OSError:
        pass

    if dropped or orphans:
        for playlist in data["playlists"]:
            playlist["tracks"] = [
                key for key in playlist.get("tracks", [])
                if key in {row.get("id") for row in kept}
            ]
        _write(data)
    return {"ok": True, "dropped": dropped, "orphans": orphans, "freed": freed}
