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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.expstudio.pycmd.python.DownloadedFile
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Where downloaded and exported files land.
 *
 * Kept apart from the workspace on purpose: the workspace is what you wrote,
 * this is what came from somewhere else. Anything here can be moved across
 * with one tap when you actually want to work on it.
 */
@Composable
fun DownloadsScreen(
    state: DownloadsState,
    downloaderOn: Boolean,
    exportOn: Boolean,
    onDownload: (String) -> Unit,
    onOpen: (DownloadedFile) -> Unit,
    onCopyToWorkspace: (DownloadedFile) -> Unit,
    onDelete: (DownloadedFile) -> Unit,
    onExport: () -> Unit,
    onSaveToDevice: (DownloadedFile) -> Unit,
    modifier: Modifier = Modifier,
    /** Sections plugins have added to this screen; empty when none are on. */
    pluginSections: @Composable () -> Unit = {},
) {
    var url by remember { mutableStateOf("") }
    var pendingDelete by remember { mutableStateOf<DownloadedFile?>(null) }

    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (downloaderOn) {
            item {
                PyCard {
                    Text("Download a file", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(8.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        OutlinedTextField(
                            value = url,
                            onValueChange = { url = it },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            enabled = !state.busy,
                            placeholder = {
                                Text("https://...", fontFamily = MonoFamily,
                                     style = MaterialTheme.typography.bodySmall)
                            },
                            shape = RoundedCornerShape(12.dp),
                            textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = MonoFamily),
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = MaterialTheme.colorScheme.primary,
                                unfocusedBorderColor = MaterialTheme.colorScheme.outline,
                            ),
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Uri,
                                imeAction = ImeAction.Go,
                            ),
                            keyboardActions = KeyboardActions(onGo = {
                                if (url.isNotBlank()) {
                                    onDownload(url)
                                    url = ""
                                }
                            }),
                        )
                        Spacer(Modifier.width(8.dp))
                        ActionButton(
                            text = "Get",
                            icon = PyIcons.FileUpload,
                            onClick = {
                                onDownload(url)
                                url = ""
                            },
                            enabled = !state.busy && url.isNotBlank(),
                        )
                    }
                    if (state.busy) BusyRow(state.progress.ifBlank { "Working..." })
                }
            }
        } else {
            item {
                PyCard {
                    Text("Downloader is off", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Turn on the Downloader plugin to fetch files from a URL.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        if (exportOn) {
            item {
                GhostButton(
                    text = "Export the workspace as a zip",
                    icon = PyIcons.Inventory2,
                    onClick = onExport,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !state.busy,
                )
            }
        }

        item {
            Spacer(Modifier.height(2.dp))
            SectionTitle("Files (${state.files.size})")
        }

        if (state.files.isEmpty()) {
            item {
                EmptyState(
                    icon = PyIcons.FileUpload,
                    title = "Nothing here yet",
                    hint = if (downloaderOn) {
                        "Downloads and workspace exports land here."
                    } else {
                        "Workspace exports land here."
                    },
                )
            }
        } else {
            items(state.files, key = { it.path }) { file ->
                DownloadRow(
                    file = file,
                    onOpen = { onOpen(file) },
                    onCopy = { onCopyToWorkspace(file) },
                    onSave = { onSaveToDevice(file) },
                    onDelete = { pendingDelete = file },
                )
            }
        }

        item { pluginSections() }

        item {
            Spacer(Modifier.height(6.dp))
            PyCard {
                Text("Downloads and the workspace", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(6.dp))
                Text(
                    text = "These files are kept separately from the workspace so that what you " +
                        "wrote and what you fetched do not get mixed up. Move one across when " +
                        "you want to edit it or serve it, or save it to the device to copy it " +
                        "onto a computer. Any workspace folder can be exported here as a zip " +
                        "from its menu in the Files tab.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }

    val doomed = pendingDelete
    if (doomed != null) {
        ConfirmDialog(
            title = "Delete ${doomed.name}?",
            message = "It is removed from Downloads. Anything you already copied into the " +
                "workspace is untouched.",
            confirmLabel = "Delete",
            destructive = true,
            onDismiss = { pendingDelete = null },
            onConfirm = {
                pendingDelete = null
                onDelete(doomed)
            },
        )
    }
}

@Composable
private fun DownloadRow(
    file: DownloadedFile,
    onOpen: () -> Unit,
    onCopy: () -> Unit,
    onSave: () -> Unit,
    onDelete: () -> Unit,
) {
    PyCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                PyIcons.Description,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.secondary,
                modifier = Modifier.size(20.dp),
            )
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    file.name,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                )
                Text(
                    "${file.readableSize}  ${formatWhen(file.modifiedSeconds)}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onDelete, modifier = Modifier.size(36.dp)) {
                Icon(
                    PyIcons.Delete,
                    contentDescription = "Delete ${file.name}",
                    tint = MaterialTheme.colorScheme.error,
                    modifier = Modifier.size(18.dp),
                )
            }
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GhostButton("Open", PyIcons.Edit, onOpen, Modifier.weight(1f))
            GhostButton("To workspace", PyIcons.Folder, onCopy, Modifier.weight(1f))
        }
        Spacer(Modifier.height(8.dp))
        // The one route off the phone: the picker writes into shared storage
        // on our behalf, so a zip can land in the real Downloads folder and be
        // copied to a computer like anything else.
        GhostButton("Save to device", PyIcons.FileUpload, onSave, Modifier.fillMaxWidth())
    }
}

private fun formatWhen(seconds: Long): String =
    if (seconds <= 0) "" else SimpleDateFormat("dd MMM HH:mm", Locale.US).format(Date(seconds * 1000))
