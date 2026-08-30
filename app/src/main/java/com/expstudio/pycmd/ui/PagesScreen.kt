package com.expstudio.pycmd.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Checkbox
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
import androidx.compose.ui.unit.dp

/**
 * Pages: websites that live in the app and can be switched on.
 *
 * The Servers tab starts one thing and watches it; this holds many and
 * remembers them. A page is a folder with a name and a port, and running one
 * is a tap rather than a form filled in again from memory.
 *
 * The card is deliberately honest about the three addresses a page can have,
 * because they are not the same promise:
 *
 * * the **phone's own** address, which works for anyone on this wifi;
 * * a **public** one from a tunnel, which works from anywhere and lasts only
 *   as long as the app is open;
 * * a **deployed** one on Cloudflare, which is somebody else's server and
 *   stays up when the phone is off.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PagesScreen(
    state: PagesState,
    kitOn: Boolean,
    onCreate: (String, String) -> Unit,
    onStart: (PageProject) -> Unit,
    onStop: (PageProject) -> Unit,
    onOpen: (PageProject) -> Unit,
    onShare: (PageProject) -> Unit,
    onUnshare: (PageProject) -> Unit,
    onRename: (PageProject, String) -> Unit,
    onRemove: (PageProject, Boolean) -> Unit,
    onOpenFolder: (PageProject) -> Unit,
    onCopy: (String) -> Unit,
    onStopAll: () -> Unit,
    onConnectCloudflare: (String, String) -> Unit,
    onForgetCloudflare: () -> Unit,
    onDeploy: (PageProject) -> Unit,
    onSetHost: (PageProject, String) -> Unit,
    modifier: Modifier = Modifier,
    /** Sections plugins have added to this screen; empty when none are on. */
    pluginSections: @Composable () -> Unit = {},
) {
    var newName by remember { mutableStateOf("") }
    var template by remember(state.templates) {
        mutableStateOf(state.templates.firstOrNull()?.id ?: "static")
    }
    var renaming by remember { mutableStateOf<PageProject?>(null) }
    var removing by remember { mutableStateOf<PageProject?>(null) }

    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            PyCard {
                Text("Pages", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(4.dp))
                Text(
                    "Websites that live in this app. Switch one on and it is served " +
                        "from the phone, for real, to anyone on this wifi.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    StatusChip(
                        "${state.used} of ${state.maxProjects} pages",
                        if (state.full) {
                            MaterialTheme.colorScheme.error
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                    StatusChip(
                        "${state.active} of ${state.maxActive} running",
                        if (state.atRunningLimit) {
                            MaterialTheme.colorScheme.error
                        } else {
                            MaterialTheme.colorScheme.primary
                        },
                    )
                }
                if (state.busy.isNotEmpty()) {
                    BusyRow(state.busy)
                }
            }
        }

        item { SectionTitle("New page") }
        item {
            PyCard {
                OutlinedTextField(
                    value = newName,
                    onValueChange = { newName = it },
                    label = { Text("Name") },
                    singleLine = true,
                    enabled = !state.full,
                    shape = RoundedCornerShape(12.dp),
                    textStyle = MaterialTheme.typography.bodyMedium,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = MaterialTheme.colorScheme.primary,
                        unfocusedBorderColor = MaterialTheme.colorScheme.outline,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    "What it starts as",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(6.dp))
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    state.templates.forEach { row ->
                        StatusChip(
                            text = row.title,
                            color = if (template == row.id) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.onSurfaceVariant
                            },
                            modifier = Modifier.clickable { template = row.id },
                        )
                    }
                }
                state.templates.firstOrNull { it.id == template }?.let { chosen ->
                    Spacer(Modifier.height(6.dp))
                    Text(
                        chosen.about,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(12.dp))
                ActionButton(
                    text = if (state.full) "That is all ${state.maxProjects}" else "Create page",
                    icon = PyIcons.Add,
                    onClick = {
                        onCreate(newName.trim(), template)
                        newName = ""
                    },
                    enabled = newName.isNotBlank() && !state.full && state.busy.isEmpty(),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }

        if (state.projects.isNotEmpty()) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    SectionTitle("Your pages", Modifier.weight(1f))
                    if (state.active > 0) {
                        GhostButton("Stop all", PyIcons.Stop, onStopAll)
                    }
                }
            }
        }

        items(state.projects, key = { it.id }) { project ->
            PageCard(
                project = project,
                kitOn = kitOn,
                cloudflareConnected = state.cloudflare.connected,
                busy = state.busy.isNotEmpty() || state.cloudflare.busy.isNotEmpty(),
                atLimit = state.atRunningLimit,
                onStart = { onStart(project) },
                onStop = { onStop(project) },
                onOpen = { onOpen(project) },
                onShare = { onShare(project) },
                onUnshare = { onUnshare(project) },
                onRename = { renaming = project },
                onRemove = { removing = project },
                onOpenFolder = { onOpenFolder(project) },
                onCopy = onCopy,
                onDeploy = { onDeploy(project) },
                onSetHost = { host -> onSetHost(project, host) },
            )
        }

        if (state.projects.isEmpty()) {
            item {
                EmptyState(
                    icon = PyIcons.Dns,
                    title = "No pages yet",
                    hint = "Name one above and pick what it starts as.",
                )
            }
        }

        item { pluginSections() }

        item { SectionTitle("Cloudflare") }
        item {
            CloudflareCard(
                state = state.cloudflare,
                kitOn = kitOn,
                onConnect = onConnectCloudflare,
                onForget = onForgetCloudflare,
            )
        }

        item {
            PyCard {
                Text(
                    "About the three addresses",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "The phone's own address works for anyone on this wifi, and stops " +
                        "when the page does.\n\n" +
                        "Share it gives a random public address through a free tunnel " +
                        "service, which anyone anywhere can open - but it is a new " +
                        "address every time, it is not private, and it is only up while " +
                        "PyCmd is running.\n\n" +
                        "Deploying to Cloudflare puts the files on their servers: a " +
                        "proper pages.dev address that stays up when the phone is off, " +
                        "and takes your own domain. That one needs an account.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }

    val toRename = renaming
    if (toRename != null) {
        TextPromptDialog(
            title = "Rename ${toRename.name}",
            label = "Name",
            initial = toRename.name,
            confirmLabel = "Rename",
            onDismiss = { renaming = null },
            onConfirm = { name ->
                renaming = null
                onRename(toRename, name)
            },
        )
    }

    val toRemove = removing
    if (toRemove != null) {
        RemovePageDialog(
            project = toRemove,
            onDismiss = { removing = null },
            onConfirm = { alsoFiles ->
                removing = null
                onRemove(toRemove, alsoFiles)
            },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PageCard(
    project: PageProject,
    kitOn: Boolean,
    cloudflareConnected: Boolean,
    busy: Boolean,
    atLimit: Boolean,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onOpen: () -> Unit,
    onShare: () -> Unit,
    onUnshare: () -> Unit,
    onRename: () -> Unit,
    onRemove: () -> Unit,
    onOpenFolder: () -> Unit,
    onCopy: (String) -> Unit,
    onDeploy: () -> Unit,
    onSetHost: (String) -> Unit,
) {
    PyCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    project.name,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "port ${project.port}  ·  ${project.files} files  ·  ${readableSize(project.bytes)}",
                    style = MaterialTheme.typography.labelSmall,
                    fontFamily = MonoFamily,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            StatusChip(
                text = if (project.running) "running" else "stopped",
                color = if (project.running) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
        }

        if (!project.exists) {
            Spacer(Modifier.height(6.dp))
            Text(
                "Its folder is gone. Remove the page, or put the folder back.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }

        if (project.running && project.url.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            AddressLine("On this wifi", project.url, onCopy)
        }
        if (project.publicUrl.isNotEmpty()) {
            AddressLine("Public", project.publicUrl, onCopy)
        }
        if (project.deployedUrl.isNotEmpty()) {
            AddressLine("Deployed", project.deployedUrl, onCopy)
        }

        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (project.running) {
                GhostButton("Stop", PyIcons.Stop, onStop, Modifier.weight(1f), enabled = !busy)
                GhostButton("Open", PyIcons.OpenInFull, onOpen, Modifier.weight(1f), enabled = !busy)
            } else {
                ActionButton(
                    text = "Run",
                    icon = PyIcons.PlayArrow,
                    onClick = onStart,
                    enabled = !busy && project.exists && !atLimit,
                    modifier = Modifier.weight(1f),
                )
                GhostButton("Files", PyIcons.Folder, onOpenFolder, Modifier.weight(1f),
                            enabled = !busy)
            }
        }

        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (project.publicUrl.isEmpty()) {
                GhostButton("Share", PyIcons.Dns, onShare, Modifier.weight(1f),
                            enabled = !busy && project.running)
            } else {
                GhostButton("Unshare", PyIcons.Clear, onUnshare, Modifier.weight(1f), enabled = !busy)
            }
            GhostButton("Rename", PyIcons.DriveFileRenameOutline, onRename, Modifier.weight(1f),
                        enabled = !busy)
            GhostButton("Delete", PyIcons.Delete, onRemove, Modifier.weight(1f), enabled = !busy)
        }

        if (kitOn && cloudflareConnected) {
            Spacer(Modifier.height(10.dp))
            Divider()
            Spacer(Modifier.height(10.dp))
            Text(
                "Where this one lives",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                StatusChip(
                    text = "This phone",
                    color = if (!project.onCloudflare) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    modifier = Modifier.clickable { onSetHost("local") },
                )
                StatusChip(
                    text = "Cloudflare",
                    color = if (project.onCloudflare) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    modifier = Modifier.clickable { onSetHost("cloudflare") },
                )
            }
            Spacer(Modifier.height(8.dp))
            GhostButton(
                "Deploy to Cloudflare",
                PyIcons.ArrowUpward,
                onDeploy,
                Modifier.fillMaxWidth(),
                enabled = !busy && project.exists,
            )
        }
    }
}

@Composable
private fun AddressLine(label: String, url: String, onCopy: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().clickable { onCopy(url) }, verticalAlignment = Alignment.CenterVertically) {
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(92.dp),
        )
        Text(
            url,
            style = MaterialTheme.typography.bodySmall,
            fontFamily = MonoFamily,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier.weight(1f),
        )
    }
    Spacer(Modifier.height(4.dp))
}

/**
 * Connecting an account, which is the only part of this that holds a secret.
 *
 * The token is checked against the account before it is kept, so a typo is a
 * sentence here rather than a failed deploy later, and it is never shown back -
 * only its last four characters, enough to tell which token is loaded.
 */
@Composable
private fun CloudflareCard(
    state: CloudflareState,
    kitOn: Boolean,
    onConnect: (String, String) -> Unit,
    onForget: () -> Unit,
) {
    var account by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }

    PyCard {
        if (!kitOn) {
            Text(
                "Deploying to your own Cloudflare account is part of the full kit. " +
                    "More → Plugins → turn on Polyglot Files, Polyglot Runner and " +
                    "Power Pack, and it appears here.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            return@PyCard
        }

        if (state.connected) {
            InfoLine("Account", state.account)
            InfoLine("Token", "ends ${state.tokenTail}")
            Spacer(Modifier.height(8.dp))
            Text(
                "Pages you deploy go to this account. A Worker can go there too.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (state.busy.isNotEmpty()) {
                BusyRow(state.busy)
            }
            Spacer(Modifier.height(10.dp))
            GhostButton("Disconnect", PyIcons.Clear, onForget, Modifier.fillMaxWidth())
            return@PyCard
        }

        Text(
            "Connect an account and a page can be deployed to Cloudflare Pages " +
                "instead of served from the phone: a pages.dev address that stays " +
                "up when this app is not, and takes your own domain.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(10.dp))
        OutlinedTextField(
            value = account,
            onValueChange = { account = it },
            label = { Text("Account ID") },
            singleLine = true,
            shape = RoundedCornerShape(12.dp),
            textStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = MonoFamily),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = token,
            onValueChange = { token = it },
            label = { Text("API token") },
            singleLine = true,
            shape = RoundedCornerShape(12.dp),
            textStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = MonoFamily),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(6.dp))
        Text(
            "Make the token with Cloudflare Pages: Edit (and Workers Scripts: Edit " +
                "if you want Workers). A scoped token can be revoked on its own; the " +
                "Global API Key is every permission on your whole account and cannot " +
                "be. The token is kept in this app's private storage and never in " +
                "your workspace.",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (state.busy.isNotEmpty()) {
            BusyRow(state.busy)
        }
        Spacer(Modifier.height(10.dp))
        ActionButton(
            text = "Connect",
            icon = PyIcons.Add,
            onClick = {
                onConnect(account, token)
                token = ""
            },
            enabled = account.isNotBlank() && token.isNotBlank() && state.busy.isEmpty(),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun InfoLine(label: String, value: String) {
    Row(Modifier.fillMaxWidth()) {
        Text(
            label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(96.dp),
        )
        Text(
            value.ifEmpty { "—" },
            style = MaterialTheme.typography.bodySmall,
            fontFamily = MonoFamily,
            modifier = Modifier.weight(1f),
        )
    }
    Spacer(Modifier.height(4.dp))
}

/**
 * Removing a page, with the destructive half opt-in.
 *
 * Two different acts wear one word here: forgetting the page, and deleting
 * what you wrote. The second cannot be undone, so it is a checkbox somebody
 * has to reach for rather than a button sitting where Cancel usually is.
 */
@Composable
private fun RemovePageDialog(
    project: PageProject,
    onDismiss: () -> Unit,
    onConfirm: (Boolean) -> Unit,
) {
    var alsoFiles by remember { mutableStateOf(false) }

    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = MaterialTheme.colorScheme.surface,
        title = { Text("Remove ${project.name}?") },
        text = {
            Column {
                Text(
                    "The page stops and leaves the list. Its folder stays in your " +
                        "workspace, so nothing you wrote is lost.",
                    style = MaterialTheme.typography.bodySmall,
                )
                Spacer(Modifier.height(12.dp))
                Row(
                    Modifier.fillMaxWidth().clickable { alsoFiles = !alsoFiles },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Checkbox(checked = alsoFiles, onCheckedChange = { alsoFiles = it })
                    Spacer(Modifier.width(4.dp))
                    Text(
                        "Delete its files too - ${project.files} files, and no way back",
                        style = MaterialTheme.typography.bodySmall,
                        color = if (alsoFiles) {
                            MaterialTheme.colorScheme.error
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                }
            }
        },
        confirmButton = {
            androidx.compose.material3.TextButton(onClick = { onConfirm(alsoFiles) }) {
                Text(
                    if (alsoFiles) "Delete everything" else "Remove",
                    color = if (alsoFiles) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.primary
                    },
                )
            }
        },
        dismissButton = {
            androidx.compose.material3.TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}
