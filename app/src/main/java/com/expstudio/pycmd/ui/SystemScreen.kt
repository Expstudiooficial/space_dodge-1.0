package com.expstudio.pycmd.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.expstudio.pycmd.util.UpdateState

/** What the app is using, and the housekeeping worth having a button for. */
data class SystemInfo(
    val pythonVersion: String = "",
    val appVersion: String = "",
    val abi: String = "",
    val androidVersion: String = "",
    val device: String = "",
    val workspaceBytes: Long = 0,
    val workspaceFiles: Int = 0,
    val packagesBytes: Long = 0,
    val downloadsBytes: Long = 0,
    val pluginBytes: Long = 0,
    val cacheBytes: Long = 0,
    val cacheFiles: Int = 0,
    val freeBytes: Long = 0,
    val servers: Int = 0,
    val plugins: Int = 0,
    val threads: Int = 0,
)

/**
 * The screen that answers "what is this app doing with my phone".
 *
 * Every number here is one somebody has asked about at some point: how much
 * space the workspace takes, whether pip's packages are the thing filling the
 * disk, and how much is safe to delete.
 */
@Composable
fun SystemScreen(
    info: SystemInfo,
    busy: String,
    onRefresh: () -> Unit,
    onClearCache: () -> Unit,
    onClearPycache: () -> Unit,
    onExportLog: () -> Unit,
    update: UpdateState,
    updateSource: String,
    onCheckForUpdate: () -> Unit,
    onDownloadUpdate: () -> Unit,
    onCancelUpdate: () -> Unit,
    onInstallUpdate: () -> Unit,
    onDismissUpdate: () -> Unit,
    onSetUpdateSource: (String) -> Unit,
    modifier: Modifier = Modifier,
    /** Null when the examples are still there and nothing needs restoring. */
    onRestoreExamples: (() -> Unit)? = null,
    /** Sections plugins have added to this screen; empty when none are on. */
    pluginSections: @Composable () -> Unit = {},
) {
    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item { SectionTitle("Runtime") }
        item {
            PyCard {
                InfoRow("Python", info.pythonVersion.ifEmpty { "starting..." })
                InfoRow("PyCmd", info.appVersion)
                InfoRow("Architecture", info.abi)
                InfoRow("Android", info.androidVersion)
                InfoRow("Device", info.device)
                InfoRow("Threads", info.threads.toString())
            }
        }

        item { SectionTitle("Updates") }
        item {
            UpdateCard(
                state = update,
                source = updateSource,
                onCheck = onCheckForUpdate,
                onDownload = onDownloadUpdate,
                onCancel = onCancelUpdate,
                onInstall = onInstallUpdate,
                onDismiss = onDismissUpdate,
                onSetSource = onSetUpdateSource,
            )
        }

        item { SectionTitle("Storage") }
        item {
            PyCard {
                InfoRow("Workspace", "${readable(info.workspaceBytes)}  ·  ${info.workspaceFiles} files")
                InfoRow("Installed packages", readable(info.packagesBytes))
                InfoRow("Downloads", readable(info.downloadsBytes))
                InfoRow("Plugins", readable(info.pluginBytes))
                InfoRow("Cache", "${readable(info.cacheBytes)}  ·  ${info.cacheFiles} files")
                Spacer(Modifier.height(6.dp))
                Divider()
                Spacer(Modifier.height(6.dp))
                InfoRow("Free on this phone", readable(info.freeBytes))
            }
        }

        item { SectionTitle("Right now") }
        item {
            PyCard {
                InfoRow("Servers running", info.servers.toString())
                InfoRow("Plugins loaded", info.plugins.toString())
            }
        }

        item { SectionTitle("Housekeeping") }
        item { pluginSections() }

        item {
            PyCard {
                Text(
                    "Nothing here touches your files. The cache is what the app " +
                        "made for itself, and __pycache__ folders are rebuilt the next " +
                        "time a script runs.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                if (busy.isNotEmpty()) {
                    BusyRow(busy)
                } else {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        GhostButton("Clear cache", PyIcons.Delete, onClearCache, Modifier.weight(1f))
                        GhostButton("Drop __pycache__", PyIcons.Delete, onClearPycache,
                                    Modifier.weight(1f))
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        GhostButton("Save the debug log", PyIcons.Save, onExportLog,
                                    Modifier.weight(1f))
                        GhostButton("Refresh", PyIcons.RestartAlt, onRefresh, Modifier.weight(1f))
                    }
                    // Only offered once they are gone: the app no longer puts
                    // them back by itself, so this is the way back.
                    if (onRestoreExamples != null) {
                        Spacer(Modifier.height(8.dp))
                        GhostButton(
                            "Put the examples back",
                            PyIcons.NoteAdd,
                            onRestoreExamples,
                            Modifier.fillMaxWidth(),
                        )
                    }
                }
            }
        }
    }
}

/**
 * Checking for a newer PyCmd, and installing it over this one.
 *
 * The whole point is that nothing gets uninstalled: Android replaces the app
 * in place and every file, package and setting stays. So the card says that
 * out loud - the fear of losing a workspace is exactly what makes people leave
 * an old build sitting there.
 *
 * It never installs anything on its own. It checks when asked, downloads when
 * asked, and the system installer still puts up its own confirmation.
 */
@Composable
private fun UpdateCard(
    state: UpdateState,
    source: String,
    onCheck: () -> Unit,
    onDownload: () -> Unit,
    onCancel: () -> Unit,
    onInstall: () -> Unit,
    onDismiss: () -> Unit,
    onSetSource: (String) -> Unit,
) {
    PyCard {
        when (state) {
            is UpdateState.Idle -> {
                Text(
                    "Installing a newer build over this one keeps everything: your " +
                        "workspace, the packages you installed and every setting. " +
                        "Deleting PyCmd first is what loses them - so do not.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                GhostButton("Check for updates", PyIcons.Download, onCheck, Modifier.fillMaxWidth())
            }

            is UpdateState.Checking -> BusyRow("Looking for a newer build...")

            is UpdateState.UpToDate -> {
                InfoRow("Installed", state.versionName)
                Text(
                    "This is the newest build published.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                GhostButton("Check again", PyIcons.RestartAlt, onCheck, Modifier.fillMaxWidth())
            }

            is UpdateState.Available -> {
                Text(
                    "PyCmd ${state.release.versionName} is out.",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                if (state.release.notes.isNotBlank()) {
                    Spacer(Modifier.height(6.dp))
                    Text(
                        state.release.notes,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(8.dp))
                InfoRow(
                    "Download",
                    if (state.release.bytes > 0) readable(state.release.bytes) else "an APK",
                )
                Text(
                    "It installs over this one. Nothing is deleted and nothing is " +
                        "uninstalled.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ActionButton("Download", PyIcons.Download, onDownload, Modifier.weight(1f))
                    GhostButton("Not now", PyIcons.Clear, onDismiss, Modifier.weight(1f))
                }
            }

            is UpdateState.Downloading -> {
                val done = state.bytes
                val total = state.total
                Text(
                    "Downloading ${state.release.versionName}...",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(8.dp))
                // A server that will not say how big the file is gets the
                // indeterminate bar rather than a progress figure invented here.
                if (total > 0) {
                    LinearProgressIndicator(
                        progress = { (done.toFloat() / total).coerceIn(0f, 1f) },
                        modifier = Modifier.fillMaxWidth(),
                    )
                } else {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                }
                Spacer(Modifier.height(8.dp))
                Text(
                    if (total > 0) "${readable(done)} of ${readable(total)}" else readable(done),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = MonoFamily,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                GhostButton("Stop", PyIcons.Stop, onCancel, Modifier.fillMaxWidth())
            }

            is UpdateState.Ready -> {
                Text(
                    "PyCmd ${state.release.versionName} is ready to install.",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    "Checked against the published fingerprint, and it is signed with " +
                        "the same key as this build - so Android will replace this app " +
                        "and keep your files. Android asks you to confirm; PyCmd closes " +
                        "while it installs and everything is where you left it after.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ActionButton("Install", PyIcons.Download, onInstall, Modifier.weight(1f))
                    GhostButton("Delete it", PyIcons.Delete, onDismiss, Modifier.weight(1f))
                }
            }

            is UpdateState.Failed -> {
                Text(
                    state.message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
                if (state.detail.isNotBlank()) {
                    Spacer(Modifier.height(6.dp))
                    Text(
                        state.detail,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    GhostButton("Try again", PyIcons.RestartAlt, onCheck, Modifier.weight(1f))
                    GhostButton("Close", PyIcons.Clear, onDismiss, Modifier.weight(1f))
                }
            }
        }

        Spacer(Modifier.height(10.dp))
        UpdateSourceRow(source, onSetSource)
    }
}

/**
 * Where the check looks, for anybody who needs it to look somewhere else.
 *
 * A branch gets renamed, a fork carries the build somebody actually wants, or
 * the update lives on a machine at home. Folded away by default: nobody needs
 * to see a URL to press one button.
 */
@Composable
private fun UpdateSourceRow(source: String, onSetSource: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    var draft by remember(source) { mutableStateOf(source) }

    TextButton(onClick = { open = !open }) {
        Text(
            if (open) "Hide where updates come from" else "Where updates come from",
            style = MaterialTheme.typography.labelSmall,
        )
    }
    if (!open) return

    OutlinedTextField(
        value = draft,
        onValueChange = { draft = it },
        label = { Text("Address of latest.json") },
        singleLine = false,
        textStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = MonoFamily),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
        modifier = Modifier.fillMaxWidth(),
    )
    Spacer(Modifier.height(6.dp))
    Text(
        "https only. The file it points at names the version and the fingerprint " +
            "of the APK; PyCmd checks the download against that fingerprint before " +
            "it offers to install anything.",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.height(8.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        GhostButton("Use this", PyIcons.Save, { onSetSource(draft) }, Modifier.weight(1f))
        GhostButton("Back to default", PyIcons.RestartAlt, { onSetSource("") }, Modifier.weight(1f))
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth()) {
        Text(
            label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(150.dp),
        )
        Text(
            value.ifEmpty { "—" },
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Medium,
            fontFamily = MonoFamily,
            modifier = Modifier.weight(1f),
        )
    }
    Spacer(Modifier.height(6.dp))
}

private fun readable(bytes: Long): String = when {
    bytes >= 1024L * 1024 * 1024 -> "%.2f GB".format(bytes / 1024.0 / 1024.0 / 1024.0)
    bytes >= 1024L * 1024 -> "%.1f MB".format(bytes / 1024.0 / 1024.0)
    bytes >= 1024 -> "${bytes / 1024} KB"
    else -> "$bytes B"
}
