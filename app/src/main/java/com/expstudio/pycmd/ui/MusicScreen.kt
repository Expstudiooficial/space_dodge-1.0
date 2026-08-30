package com.expstudio.pycmd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.expstudio.pycmd.music.MusicTrack
import com.expstudio.pycmd.music.Playback

/**
 * Music: something to listen to while the rest of the app is being used.
 *
 * The tab is a library and a set of controls, and almost none of what it shows
 * belongs to it. What is playing lives in a media session in a service, which
 * is why the sound carries on when this screen is closed, when another tab is
 * open, and when the phone is locked - and why the same play button appears in
 * the notification shade, on the lock screen and in the quick-settings media
 * chip without this file drawing any of them.
 *
 * Everything imported is copied into the app. A picked file is a permission to
 * read something, not a file, and the permission does not outlive the picker;
 * a library of them would empty itself. The copy is what makes it offline.
 *
 * A video file is welcome and only its sound is used. People have `.mp4` files
 * they want to hear, and the player is told to ignore the picture rather than
 * anything being converted at import time.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MusicScreen(
    state: MusicState,
    playback: Playback,
    onImport: () -> Unit,
    onPlay: (MusicTrack) -> Unit,
    onPlayAll: () -> Unit,
    onPlayPlaylist: (MusicPlaylist) -> Unit,
    onToggle: () -> Unit,
    onNext: () -> Unit,
    onPrevious: () -> Unit,
    onSeek: (Long) -> Unit,
    onStop: () -> Unit,
    onCycleLoop: () -> Unit,
    onToggleShuffle: () -> Unit,
    onOpenPlaylist: (String) -> Unit,
    onNewPlaylist: (String) -> Unit,
    onRenamePlaylist: (MusicPlaylist, String) -> Unit,
    onRemovePlaylist: (MusicPlaylist) -> Unit,
    onRenameTrack: (MusicTrack, String) -> Unit,
    onRemoveTrack: (MusicTrack) -> Unit,
    onAddToPlaylist: (String, MusicTrack) -> Unit,
    onRemoveFromPlaylist: (String, MusicTrack) -> Unit,
    onMove: (String, MusicTrack, Int) -> Unit,
    onTidy: () -> Unit,
    modifier: Modifier = Modifier,
    /** Sections plugins have added to this screen; empty when none are on. */
    pluginSections: @Composable () -> Unit = {},
) {
    var naming by remember { mutableStateOf(false) }
    var renamingList by remember { mutableStateOf<MusicPlaylist?>(null) }
    var removingList by remember { mutableStateOf<MusicPlaylist?>(null) }
    var renamingTrack by remember { mutableStateOf<MusicTrack?>(null) }
    var removingTrack by remember { mutableStateOf<MusicTrack?>(null) }
    var addingTo by remember { mutableStateOf<MusicTrack?>(null) }
    var expanded by remember { mutableStateOf("") }

    val open = state.current
    val visible = state.visible

    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            NowPlaying(
                playback = playback,
                onToggle = onToggle,
                onNext = onNext,
                onPrevious = onPrevious,
                onSeek = onSeek,
                onStop = onStop,
                onCycleLoop = onCycleLoop,
                onToggleShuffle = onToggleShuffle,
            )
        }

        item {
            PyCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Library", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.height(3.dp))
                        Text(
                            if (state.tracks.isEmpty()) {
                                "Nothing imported yet"
                            } else {
                                "${state.tracks.size} of ${state.maxTracks} - " +
                                    readableSize(state.bytes)
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (state.tracks.isNotEmpty()) {
                        GhostButton("Play all", PyIcons.PlayArrow, onPlayAll)
                    }
                }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ActionButton(
                        "Add music",
                        PyIcons.FileUpload,
                        onImport,
                        Modifier.weight(1f),
                        enabled = !state.importing && state.tracks.size < state.maxTracks,
                    )
                    GhostButton("New playlist", PyIcons.PlaylistAdd, { naming = true })
                }
                if (state.busy.isNotEmpty()) BusyRow(state.busy)
                if (state.missing > 0) {
                    Spacer(Modifier.height(8.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            "${state.missing} track(s) have lost their file.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.weight(1f),
                        )
                        TextButton(onClick = onTidy) { Text("Tidy up") }
                    }
                }
                if (state.tracks.isEmpty() && state.busy.isEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Audio or video, from anywhere on the phone. Video files are " +
                            "kept for their sound; nothing here ever shows a picture.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        if (state.playlists.isNotEmpty()) {
            item { SectionTitle("Playlists") }
            item {
                FlowRow(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    PlaylistChip("Everything", state.openPlaylist.isEmpty()) {
                        onOpenPlaylist("")
                    }
                    state.playlists.forEach { playlist ->
                        PlaylistChip(
                            "${playlist.name}  ${playlist.count}",
                            playlist.id == state.openPlaylist,
                        ) { onOpenPlaylist(playlist.id) }
                    }
                }
            }
        }

        if (open != null) {
            item {
                PyCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(open.name, style = MaterialTheme.typography.titleMedium)
                            Spacer(Modifier.height(3.dp))
                            Text(
                                "${open.count} track(s) - ${readableLength(open.duration)}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        IconButton(onClick = { onPlayPlaylist(open) }) {
                            Icon(
                                PyIcons.PlayArrow,
                                contentDescription = "Play ${open.name}",
                                tint = MaterialTheme.colorScheme.primary,
                            )
                        }
                        IconButton(onClick = { renamingList = open }) {
                            Icon(
                                PyIcons.DriveFileRenameOutline,
                                contentDescription = "Rename ${open.name}",
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.size(19.dp),
                            )
                        }
                        IconButton(onClick = { removingList = open }) {
                            Icon(
                                PyIcons.Delete,
                                contentDescription = "Delete ${open.name}",
                                tint = MaterialTheme.colorScheme.error,
                                modifier = Modifier.size(19.dp),
                            )
                        }
                    }
                }
            }
        }

        item { pluginSections() }

        item {
            SectionTitle(if (open != null) "In ${open.name}" else "Tracks")
        }

        if (visible.isEmpty()) {
            item {
                EmptyState(
                    icon = PyIcons.MusicNote,
                    title = if (open != null) "Nothing in here yet" else "No music yet",
                    hint = if (open != null) {
                        "Open Everything, then use a track's Add to playlist."
                    } else {
                        "Import an audio or video file and it stays in the app."
                    },
                )
            }
        }

        items(visible, key = { it.id }) { track ->
            TrackRow(
                track = track,
                playing = playback.trackId == track.id && playback.playing,
                current = playback.trackId == track.id,
                inPlaylist = open,
                expanded = expanded == track.id,
                // The row of the track that is already on is a pause button,
                // because that is what its icon says. Starting the queue over
                // when somebody meant to pause is the bug that reads as the
                // app ignoring them.
                onPlay = { if (playback.trackId == track.id) onToggle() else onPlay(track) },
                onExpand = { expanded = if (expanded == track.id) "" else track.id },
                onAdd = { addingTo = track },
                onRename = { renamingTrack = track },
                onRemove = { removingTrack = track },
                onTakeOut = { open?.let { onRemoveFromPlaylist(it.id, track) } },
                onMove = { delta -> open?.let { onMove(it.id, track, delta) } },
            )
        }

        item { Spacer(Modifier.height(20.dp)) }
    }

    if (naming) {
        TextPromptDialog(
            title = "New playlist",
            label = "Name",
            initial = "",
            confirmLabel = "Create",
            onDismiss = { naming = false },
            onConfirm = { name ->
                naming = false
                if (name.isNotBlank()) onNewPlaylist(name.trim())
            },
        )
    }

    renamingList?.let { playlist ->
        TextPromptDialog(
            title = "Rename playlist",
            label = "Name",
            initial = playlist.name,
            confirmLabel = "Rename",
            onDismiss = { renamingList = null },
            onConfirm = { name ->
                renamingList = null
                if (name.isNotBlank() && name != playlist.name) onRenamePlaylist(playlist, name.trim())
            },
        )
    }

    removingList?.let { playlist ->
        ConfirmDialog(
            title = "Delete ${playlist.name}?",
            message = "The playlist goes. The tracks in it stay in the library.",
            confirmLabel = "Delete",
            destructive = true,
            onDismiss = { removingList = null },
            onConfirm = {
                removingList = null
                onRemovePlaylist(playlist)
            },
        )
    }

    renamingTrack?.let { track ->
        TextPromptDialog(
            title = "Rename track",
            label = "Title",
            initial = track.title,
            confirmLabel = "Rename",
            onDismiss = { renamingTrack = null },
            onConfirm = { title ->
                renamingTrack = null
                if (title.isNotBlank() && title != track.title) onRenameTrack(track, title.trim())
            },
        )
    }

    removingTrack?.let { track ->
        ConfirmDialog(
            title = "Delete ${track.title}?",
            message = "The file is deleted from the app. Whatever it was copied from " +
                "is untouched.",
            confirmLabel = "Delete",
            destructive = true,
            onDismiss = { removingTrack = null },
            onConfirm = {
                removingTrack = null
                onRemoveTrack(track)
            },
        )
    }

    addingTo?.let { track ->
        ListDialog(title = "Add ${track.title} to", onDismiss = { addingTo = null }) {
            if (state.playlists.isEmpty()) {
                Text(
                    "There are no playlists yet. Make one first.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            state.playlists.forEach { playlist ->
                val already = playlist.trackIds.contains(track.id)
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clickable(enabled = !already) {
                            addingTo = null
                            onAddToPlaylist(playlist.id, track)
                        }
                        .padding(vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        PyIcons.QueueMusic,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(10.dp))
                    Text(playlist.name, style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.weight(1f))
                    Text(
                        if (already) "already in" else "${playlist.count}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

/**
 * The controls, and what they are controlling.
 *
 * Drawn from the session rather than from what this screen last asked for: the
 * notification, a headset button and the lock screen can all change what is
 * playing without this app being involved, and a screen that tracked its own
 * idea of "playing" would be wrong within seconds of somebody using them.
 */
@Composable
private fun NowPlaying(
    playback: Playback,
    onToggle: () -> Unit,
    onNext: () -> Unit,
    onPrevious: () -> Unit,
    onSeek: (Long) -> Unit,
    onStop: () -> Unit,
    onCycleLoop: () -> Unit,
    onToggleShuffle: () -> Unit,
) {
    PyCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                PyIcons.MusicNote,
                contentDescription = null,
                tint = if (playback.playing) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
                modifier = Modifier.size(22.dp),
            )
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    playback.title.ifBlank { "Nothing playing" },
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    when {
                        playback.error.isNotEmpty() -> playback.error
                        !playback.loaded -> "Pick something below"
                        playback.buffering -> "Loading..."
                        // The artist already falls back to the queue's name,
                        // so this is one line rather than two joined into
                        // "Everything - Everything".
                        playback.artist.isNotBlank() -> playback.artist
                        playback.queueName.isNotBlank() -> playback.queueName
                        else -> "Playing"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = if (playback.error.isNotEmpty()) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    maxLines = 1,
                )
            }
            if (playback.loaded) {
                IconButton(onClick = onStop) {
                    Icon(
                        PyIcons.Stop,
                        contentDescription = "Stop",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }
        }

        // A slider with no track loaded would be a control over nothing, and
        // dragging it would look like it should do something.
        if (playback.loaded) {
            Spacer(Modifier.height(6.dp))
            var dragging by remember { mutableStateOf(false) }
            var held by remember { mutableStateOf(0f) }
            val length = playback.duration.coerceAtLeast(1L).toFloat()
            val position = if (dragging) held else playback.position.toFloat()

            Slider(
                value = position.coerceIn(0f, length),
                onValueChange = {
                    dragging = true
                    held = it
                },
                onValueChangeFinished = {
                    dragging = false
                    onSeek(held.toLong())
                },
                valueRange = 0f..length,
                colors = SliderDefaults.colors(
                    thumbColor = MaterialTheme.colorScheme.primary,
                    activeTrackColor = MaterialTheme.colorScheme.primary,
                ),
                modifier = Modifier.fillMaxWidth(),
            )
            Row(Modifier.fillMaxWidth()) {
                Text(
                    readableLength(position.toLong()),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.weight(1f))
                Text(
                    readableLength(playback.duration),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        Spacer(Modifier.height(4.dp))
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceEvenly,
        ) {
            IconButton(onClick = onToggleShuffle) {
                Icon(
                    PyIcons.Shuffle,
                    contentDescription = if (playback.shuffle) "Shuffle off" else "Shuffle on",
                    tint = if (playback.shuffle) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.outline
                    },
                    modifier = Modifier.size(20.dp),
                )
            }
            IconButton(onClick = onPrevious, enabled = playback.loaded) {
                Icon(
                    PyIcons.SkipPrevious,
                    contentDescription = "Previous",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onToggle, enabled = playback.loaded) {
                Icon(
                    if (playback.playing) PyIcons.Pause else PyIcons.PlayArrow,
                    contentDescription = if (playback.playing) "Pause" else "Play",
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(30.dp),
                )
            }
            IconButton(onClick = onNext, enabled = playback.loaded) {
                Icon(
                    PyIcons.SkipNext,
                    contentDescription = "Next",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onCycleLoop) {
                Icon(
                    if (playback.loop == "one") PyIcons.RepeatOne else PyIcons.Repeat,
                    contentDescription = "Loop: ${playback.loop}",
                    tint = if (playback.loop == "off") {
                        MaterialTheme.colorScheme.outline
                    } else {
                        MaterialTheme.colorScheme.primary
                    },
                    modifier = Modifier.size(20.dp),
                )
            }
        }

        Text(
            "Keeps playing in other tabs, and with the app closed - the " +
                "notification and the lock screen have the same buttons.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun PlaylistChip(text: String, selected: Boolean, onClick: () -> Unit) {
    Box(
        Modifier
            .clip(RoundedCornerShape(20.dp))
            .background(
                if (selected) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.surface
                },
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 8.dp),
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelLarge,
            color = if (selected) {
                MaterialTheme.colorScheme.onPrimary
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
    }
}

/**
 * One track. Tapping it plays; the chevron opens what else can be done to it.
 *
 * The actions are a row that folds out rather than a menu: a dropdown anchored
 * to a small icon on a phone is a target people miss, and the fold-out is also
 * where the up and down arrows belong when a playlist is open, since ordering
 * is the entire point of having made the playlist.
 */
@Composable
private fun TrackRow(
    track: MusicTrack,
    playing: Boolean,
    current: Boolean,
    inPlaylist: MusicPlaylist?,
    expanded: Boolean,
    onPlay: () -> Unit,
    onExpand: () -> Unit,
    onAdd: () -> Unit,
    onRename: () -> Unit,
    onRemove: () -> Unit,
    onTakeOut: () -> Unit,
    onMove: (Int) -> Unit,
) {
    PyCard(contentPadding = PaddingValues(horizontal = 10.dp, vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onPlay, enabled = !track.missing) {
                Icon(
                    if (playing) PyIcons.Pause else PyIcons.PlayArrow,
                    contentDescription = "Play ${track.title}",
                    tint = when {
                        track.missing -> MaterialTheme.colorScheme.outline
                        current -> MaterialTheme.colorScheme.primary
                        else -> MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
            Column(
                Modifier
                    .weight(1f)
                    .clickable(enabled = !track.missing, onClick = onPlay),
            ) {
                Text(
                    track.title,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = if (current) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (current) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurface
                    },
                    maxLines = 1,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    when {
                        track.missing -> "Its file is gone"
                        else -> listOfNotNull(
                            track.artist.takeIf { it.isNotBlank() },
                            readableLength(track.duration).takeIf { track.duration > 0 },
                            readableSize(track.bytes),
                            "video".takeIf { track.video },
                        ).joinToString(" - ")
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = if (track.missing) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    maxLines = 1,
                )
            }
            IconButton(onClick = onExpand) {
                Icon(
                    if (expanded) PyIcons.ExpandLess else PyIcons.ExpandMore,
                    contentDescription = "What else",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(20.dp),
                )
            }
        }

        if (expanded) {
            Spacer(Modifier.height(4.dp))
            Divider()
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (inPlaylist != null) {
                    IconButton(onClick = { onMove(-1) }) {
                        Icon(
                            PyIcons.ArrowUpward,
                            contentDescription = "Move up",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                    IconButton(onClick = { onMove(1) }) {
                        Icon(
                            PyIcons.ArrowUpward,
                            contentDescription = "Move down",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            // Half a turn, so one arrow serves as both.
                            modifier = Modifier
                                .size(18.dp)
                                .rotate(180f),
                        )
                    }
                }
                TextButton(onClick = onAdd) { Text("Add to playlist") }
                TextButton(onClick = onRename) { Text("Rename") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (inPlaylist != null) {
                    TextButton(onClick = onTakeOut) { Text("Take out of ${inPlaylist.name}") }
                }
                TextButton(onClick = onRemove) {
                    Text("Delete", color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}

/** `3:07`, or `1:02:11` when it needs the hour. */
private fun readableLength(millis: Long): String {
    if (millis <= 0) return "0:00"
    val seconds = millis / 1000
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val rest = seconds % 60
    return if (hours > 0) {
        "$hours:${minutes.toString().padStart(2, '0')}:${rest.toString().padStart(2, '0')}"
    } else {
        "$minutes:${rest.toString().padStart(2, '0')}"
    }
}
