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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

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
    modifier: Modifier = Modifier,
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
                }
            }
        }
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
