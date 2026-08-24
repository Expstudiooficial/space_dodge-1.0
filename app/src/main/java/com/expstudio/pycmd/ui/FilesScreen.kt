package com.expstudio.pycmd.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.expstudio.pycmd.python.LanguageInfo
import com.expstudio.pycmd.util.WorkspaceEntry
import java.io.File

@Composable
fun FilesScreen(
    state: FilesState,
    rootPath: String,
    relativePath: (File) -> String,
    onOpenDirectory: (File) -> Unit,
    onOpenFile: (File) -> Unit,
    onRunFile: (File) -> Unit,
    onUp: () -> Unit,
    onNewFile: (String) -> Unit,
    onNewFileOfType: (String, String) -> Unit,
    languages: List<LanguageInfo>,
    onNewFolder: (String) -> Unit,
    onRename: (File, String) -> Unit,
    onDelete: (File) -> Unit,
    onImport: (android.net.Uri) -> Unit,
    modifier: Modifier = Modifier,
    pickingFor: ServerKind? = null,
    onUseAsTarget: (File) -> Unit = {},
    onCancelPicking: () -> Unit = {},
) {
    var dialog by remember { mutableStateOf<FileDialog?>(null) }

    val importLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri -> if (uri != null) onImport(uri) }

    val atRoot = state.directory?.absolutePath == rootPath

    Column(modifier.fillMaxSize()) {
        Row(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface)
                .padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onUp, enabled = !atRoot) {
                Icon(
                    PyIcons.ArrowBack,
                    contentDescription = "Up one folder",
                    tint = if (atRoot) MaterialTheme.colorScheme.outline else MaterialTheme.colorScheme.onSurface,
                )
            }
            Column(Modifier.weight(1f)) {
                Text("Workspace", style = MaterialTheme.typography.titleMedium)
                Text(
                    text = state.directory?.let { relativePath(it) } ?: "/",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
            IconButton(onClick = { importLauncher.launch(arrayOf("*/*")) }) {
                Icon(
                    PyIcons.FileUpload,
                    contentDescription = "Import a file",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = { dialog = FileDialog.NewFolder }) {
                Icon(
                    PyIcons.CreateNewFolder,
                    contentDescription = "New folder",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = { dialog = FileDialog.NewFile }) {
                Icon(
                    PyIcons.NoteAdd,
                    contentDescription = "New file",
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }

        if (pickingFor != null) {
            PickerBanner(
                kind = pickingFor,
                directory = state.directory,
                onUse = { dir -> onUseAsTarget(dir) },
                onCancel = onCancelPicking,
            )
        }

        Divider()

        when {
            state.loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
            }

            state.entries.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                EmptyState(
                    icon = PyIcons.FolderOpen,
                    title = "This folder is empty",
                    hint = "Create a script or import one from your device.",
                )
            }

            else -> LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(bottom = 24.dp),
            ) {
                items(state.entries, key = { it.file.absolutePath }) { entry ->
                    FileRow(
                        entry = entry,
                        onOpen = {
                            when {
                                entry.isDirectory -> onOpenDirectory(entry.file)
                                pickingFor == ServerKind.SCRIPT -> onUseAsTarget(entry.file)
                                else -> onOpenFile(entry.file)
                            }
                        },
                        onRun = { onRunFile(entry.file) },
                        onRename = { dialog = FileDialog.Rename(entry.file) },
                        onDelete = { dialog = FileDialog.ConfirmDelete(entry.file) },
                    )
                }
            }
        }
    }

    when (val current = dialog) {
        FileDialog.NewFile -> NewFileDialog(
            languages = languages,
            onDismiss = { dialog = null },
            onCreate = { name, extension ->
                dialog = null
                if (extension.isEmpty()) onNewFile(name) else onNewFileOfType(name, extension)
            },
        )

        FileDialog.NewFolder -> TextPromptDialog(
            title = "New folder",
            label = "Folder name",
            initial = "",
            confirmLabel = "Create",
            onDismiss = { dialog = null },
            onConfirm = {
                dialog = null
                onNewFolder(it)
            },
        )

        is FileDialog.Rename -> TextPromptDialog(
            title = "Rename",
            label = "New name",
            initial = current.file.name,
            confirmLabel = "Rename",
            onDismiss = { dialog = null },
            onConfirm = {
                dialog = null
                onRename(current.file, it)
            },
        )

        is FileDialog.ConfirmDelete -> ConfirmDialog(
            title = "Delete ${current.file.name}?",
            message = if (current.file.isDirectory) {
                "The folder and everything inside it will be removed. This cannot be undone."
            } else {
                "This cannot be undone."
            },
            confirmLabel = "Delete",
            destructive = true,
            onDismiss = { dialog = null },
            onConfirm = {
                dialog = null
                onDelete(current.file)
            },
        )

        null -> Unit
    }
}

private sealed interface FileDialog {
    data object NewFile : FileDialog
    data object NewFolder : FileDialog
    data class Rename(val file: File) : FileDialog
    data class ConfirmDelete(val file: File) : FileDialog
}

@Composable
private fun FileRow(
    entry: WorkspaceEntry,
    onOpen: () -> Unit,
    onRun: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    var menuOpen by remember { mutableStateOf(false) }

    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpen)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = if (entry.isDirectory) PyIcons.Folder else PyIcons.Description,
            contentDescription = null,
            tint = when {
                entry.isDirectory -> MaterialTheme.colorScheme.secondary
                entry.isPython -> MaterialTheme.colorScheme.primary
                else -> MaterialTheme.colorScheme.onSurfaceVariant
            },
            modifier = Modifier.size(22.dp),
        )
        Spacer(Modifier.width(14.dp))

        Column(Modifier.weight(1f)) {
            Text(
                text = entry.name,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = if (entry.isDirectory) FontWeight.Medium else FontWeight.Normal,
                maxLines = 1,
            )
            Text(
                text = buildString {
                    append(entry.readableDate)
                    if (!entry.isDirectory) {
                        append("  -  ")
                        append(entry.readableSize)
                    }
                },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        if (entry.isPython) {
            IconButton(onClick = onRun, modifier = Modifier.size(38.dp)) {
                Icon(
                    PyIcons.PlayArrow,
                    contentDescription = "Run ${entry.name}",
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(20.dp),
                )
            }
        }

        Box {
            IconButton(onClick = { menuOpen = true }, modifier = Modifier.size(38.dp)) {
                Icon(
                    PyIcons.MoreVert,
                    contentDescription = "More actions",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(20.dp),
                )
            }
            DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                DropdownMenuItem(
                    text = { Text("Rename") },
                    leadingIcon = { Icon(PyIcons.DriveFileRenameOutline, contentDescription = null) },
                    onClick = {
                        menuOpen = false
                        onRename()
                    },
                )
                DropdownMenuItem(
                    text = { Text("Delete", color = MaterialTheme.colorScheme.error) },
                    leadingIcon = {
                        Icon(
                            PyIcons.Delete,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.error,
                        )
                    },
                    onClick = {
                        menuOpen = false
                        onDelete()
                    },
                )
            }
        }
    }
    Box(
        Modifier
            .padding(start = 50.dp)
            .fillMaxWidth()
            .height(1.dp)
            .background(MaterialTheme.colorScheme.outlineVariant),
    )
}

/**
 * Shown while the Servers tab is waiting for a folder or script.
 *
 * A folder is confirmed with the button (you have to be standing in it); a
 * script is picked by tapping it in the list.
 */
@Composable
private fun PickerBanner(
    kind: ServerKind,
    directory: File?,
    onUse: (File) -> Unit,
    onCancel: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.primaryContainer)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                text = if (kind == ServerKind.STATIC) "Choose a folder to serve" else "Tap the script to run",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
            Text(
                text = if (kind == ServerKind.STATIC) {
                    "Open the folder you want, then confirm."
                } else {
                    "Any .py file in this workspace."
                },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
        }
        if (kind == ServerKind.STATIC && directory != null) {
            TextButton(onClick = { onUse(directory) }) { Text("Use this folder") }
        }
        TextButton(onClick = onCancel) { Text("Cancel") }
    }
}

/**
 * New-file dialog with a type picker.
 *
 * The list comes from the language registry, so it grows and shrinks with the
 * Polyglot Files plugin rather than being hard-coded here. Each type carries a
 * starter template, which is what makes "new Dockerfile" useful rather than
 * just an empty buffer with a name.
 */
@Composable
private fun NewFileDialog(
    languages: List<LanguageInfo>,
    onDismiss: () -> Unit,
    onCreate: (String, String) -> Unit,
) {
    var name by remember { mutableStateOf("script") }
    var chosen by remember(languages) {
        mutableStateOf(languages.firstOrNull { it.id == "python" } ?: languages.firstOrNull())
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(18.dp),
        title = { Text("New file", style = MaterialTheme.typography.titleMedium) },
        text = {
            Column {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Name") },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = MonoFamily),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = MaterialTheme.colorScheme.primary,
                        unfocusedBorderColor = MaterialTheme.colorScheme.outline,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )

                Spacer(Modifier.height(6.dp))
                Text(
                    text = chosen?.let { "${it.name}  ->  $name${it.extension}" } ?: name,
                    style = MaterialTheme.typography.labelSmall,
                    fontFamily = MonoFamily,
                    color = MaterialTheme.colorScheme.secondary,
                )

                if (chosen?.note?.isNotBlank() == true) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        chosen!!.note,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                Spacer(Modifier.height(10.dp))
                SectionTitle("Type")
                LazyColumn(Modifier.heightIn(max = 260.dp)) {
                    items(languages, key = { it.id }) { language ->
                        val selected = chosen?.id == language.id
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clickable { chosen = language }
                                .padding(vertical = 8.dp, horizontal = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(
                                    language.name,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = if (selected) {
                                        MaterialTheme.colorScheme.primary
                                    } else {
                                        MaterialTheme.colorScheme.onSurface
                                    },
                                )
                                Text(
                                    language.extension + runLabel(language),
                                    style = MaterialTheme.typography.labelSmall,
                                    fontFamily = MonoFamily,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            if (selected) {
                                Text(
                                    "selected",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onCreate(name.trim(), chosen?.extension.orEmpty()) },
                enabled = name.isNotBlank() && chosen != null,
            ) { Text("Create") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

private fun runLabel(language: LanguageInfo): String = when (language.mode) {
    "run" -> "   runs on the device"
    "preview" -> "   previewable"
    else -> ""
}
