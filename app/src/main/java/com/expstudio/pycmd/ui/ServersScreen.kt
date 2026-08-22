package com.expstudio.pycmd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.text.KeyboardOptions
import com.expstudio.pycmd.python.RunningServer

@Composable
fun ServersScreen(
    state: ServersState,
    currentFolder: String,
    onStartFileServer: (Int) -> Unit,
    onStop: (String) -> Unit,
    onStopAll: () -> Unit,
    onCopy: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var portDialogOpen by remember { mutableStateOf(false) }

    val running = state.servers.count { it.status == "running" }

    Column(modifier.fillMaxSize()) {
        Column(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface)
                .padding(14.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Servers", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(3.dp))
                    Text(
                        text = if (state.localIp.isBlank()) {
                            "Anything you serve stays on your local network."
                        } else {
                            "This device is ${state.localIp} on your network."
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (running > 0) {
                    StatusChip("$running live", MaterialTheme.colorScheme.primary)
                }
            }

            Spacer(Modifier.height(12.dp))

            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                ActionButton(
                    text = "Serve folder",
                    icon = PyIcons.Folder,
                    onClick = { portDialogOpen = true },
                    enabled = !state.busy,
                    modifier = Modifier.weight(1f),
                )
                GhostButton(
                    text = "Stop all",
                    icon = PyIcons.Stop,
                    onClick = onStopAll,
                    enabled = running > 0,
                    modifier = Modifier.weight(1f),
                )
            }

            Spacer(Modifier.height(8.dp))
            Text(
                text = "Serving: $currentFolder",
                style = MaterialTheme.typography.labelSmall,
                fontFamily = MonoFamily,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
            )

            if (state.busy) {
                BusyRow("Starting...")
            }
        }

        Divider()

        if (state.servers.isEmpty()) {
            EmptyState(
                icon = PyIcons.Dns,
                title = "No servers running",
                hint = "Serve the current folder, or run a script that listens on a port.",
                modifier = Modifier.padding(top = 40.dp),
            )
        } else {
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(14.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(state.servers, key = { it.handle }) { server ->
                    ServerRow(server = server, onStop = { onStop(server.handle) }, onCopy = onCopy)
                }

                item {
                    Spacer(Modifier.height(6.dp))
                    PyCard {
                        Text("Keeping servers alive", style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.height(6.dp))
                        Text(
                            text = "While something is listening, PyCmd shows an ongoing " +
                                "notification. That is what stops Android from shutting the " +
                                "process down when you switch apps.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }

    if (portDialogOpen) {
        TextPromptDialog(
            title = "Serve this folder",
            label = "Port",
            initial = "8000",
            confirmLabel = "Start",
            supportingText = "Open the printed address from any device on the same Wi-Fi.",
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Number,
                imeAction = ImeAction.Done,
            ),
            onDismiss = { portDialogOpen = false },
            onConfirm = { text ->
                portDialogOpen = false
                onStartFileServer(text.trim().toIntOrNull() ?: 8000)
            },
        )
    }
}

@Composable
private fun ServerRow(
    server: RunningServer,
    onStop: () -> Unit,
    onCopy: (String) -> Unit,
) {
    val statusColor = when (server.status) {
        "running" -> MaterialTheme.colorScheme.primary
        "error" -> MaterialTheme.colorScheme.error
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }

    PyCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(server.label, style = MaterialTheme.typography.bodyLarge, maxLines = 1)
                    Spacer(Modifier.width(8.dp))
                    StatusChip(server.status, statusColor)
                }
                if (server.url.isNotBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        server.url,
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = MonoFamily,
                        color = MaterialTheme.colorScheme.secondary,
                    )
                }
                if (server.error.isNotBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        server.error,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }

            if (server.url.isNotBlank()) {
                IconButton(onClick = { onCopy(server.url) }, modifier = Modifier.size(38.dp)) {
                    Icon(
                        PyIcons.ContentCopy,
                        contentDescription = "Copy address",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }
            IconButton(onClick = onStop, modifier = Modifier.size(38.dp)) {
                Icon(
                    PyIcons.Stop,
                    contentDescription = "Stop ${server.label}",
                    tint = MaterialTheme.colorScheme.error,
                    modifier = Modifier.size(20.dp),
                )
            }
        }
    }
}
