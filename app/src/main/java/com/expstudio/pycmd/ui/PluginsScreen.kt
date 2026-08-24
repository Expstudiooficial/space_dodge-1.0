package com.expstudio.pycmd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
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
import com.expstudio.pycmd.plugins.InstalledPlugin
import com.expstudio.pycmd.plugins.PluginGroup
import com.expstudio.pycmd.plugins.PluginIds
import com.expstudio.pycmd.plugins.PluginSpec
import com.expstudio.pycmd.plugins.Plugins

/**
 * The plugin list: what ships in the app, and what the user installed.
 *
 * The two are kept visibly apart. A built-in switch can only reach behaviour
 * that is already compiled in; an installed plugin is somebody else's Python
 * running with the app's own permissions. Presenting them as the same kind of
 * thing would be the most dangerous piece of design in the app.
 */
@Composable
fun PluginsScreen(
    enabled: Set<String>,
    installed: List<InstalledPlugin>,
    installedEnabled: Set<String>,
    busy: String,
    onToggle: (String, Boolean) -> Unit,
    onOpen: (PluginSpec) -> Unit,
    onEnableAll: () -> Unit,
    onReset: () -> Unit,
    onInstallFile: () -> Unit,
    onInstallFolder: () -> Unit,
    onInstallWorkspace: (java.io.File) -> Unit,
    onRefreshCandidates: () -> Unit,
    workspaceCandidates: List<java.io.File> = emptyList(),
    onToggleInstalled: (String, Boolean) -> Unit,
    onOpenPanel: (InstalledPlugin) -> Unit,
    onRemoveInstalled: (InstalledPlugin) -> Unit,
    onReadGuide: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val fullKit = PluginIds.CORE.all { it in enabled }
    val poweredUp = PluginIds.POWER_PACK in enabled
    var query by remember { mutableStateOf("") }
    var warning by remember { mutableStateOf<PendingInstall?>(null) }
    var pendingRemoval by remember { mutableStateOf<InstalledPlugin?>(null) }
    var pickingFromWorkspace by remember { mutableStateOf(false) }

    val needle = query.trim().lowercase()
    fun matches(vararg fields: String?): Boolean =
        needle.isEmpty() || fields.any { it?.lowercase()?.contains(needle) == true }

    val shownInstalled = installed.filter {
        matches(it.name, it.description, it.author, it.id)
    }
    val shownBuiltIn = Plugins.ALL.filter {
        matches(it.name, it.tagline, it.description, it.id)
    }

    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            SearchField(
                value = query,
                onValueChange = { query = it },
                placeholder = "Search plugins",
            )
        }

        if (needle.isEmpty()) {
            item {
                KitBanner(fullKit = fullKit, active = enabled.size, total = Plugins.ALL.size)
            }
            item {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    GhostButton("Turn all on", PyIcons.Add, onEnableAll, Modifier.weight(1f))
                    GhostButton("Reset", PyIcons.RestartAlt, onReset, Modifier.weight(1f))
                }
            }

            item {
                InstallCard(
                    busy = busy,
                    onFile = { warning = PendingInstall.File },
                    onFolder = { warning = PendingInstall.Folder },
                    onWorkspace = { warning = PendingInstall.Workspace },
                    onGuide = onReadGuide,
                )
            }
        }

        if (shownInstalled.isNotEmpty()) {
            item {
                Spacer(Modifier.height(4.dp))
                SectionTitle("Installed by you (${shownInstalled.size})")
            }
            items(shownInstalled, key = { "custom-${it.id}" }) { plugin ->
                InstalledRow(
                    plugin = plugin,
                    isOn = plugin.id in installedEnabled,
                    onToggle = { on -> onToggleInstalled(plugin.id, on) },
                    onOpen = { onOpenPanel(plugin) },
                    onRemove = { pendingRemoval = plugin },
                )
            }
        }

        PluginGroup.entries.forEach { group ->
            val inGroup = shownBuiltIn.filter { it.group == group }
            if (inGroup.isEmpty()) return@forEach

            item(key = "header-${group.name}") {
                Spacer(Modifier.height(4.dp))
                SectionTitle(group.label)
            }

            items(inGroup, key = { it.id }) { spec ->
                PluginRow(
                    spec = spec,
                    isOn = spec.id in enabled,
                    poweredUp = poweredUp && spec.id != PluginIds.POWER_PACK,
                    blockedBy = spec.requires.firstOrNull { it !in enabled }
                        ?.let { Plugins.spec(it)?.name },
                    onToggle = { on -> onToggle(spec.id, on) },
                    onOpen = { onOpen(spec) },
                )
            }
        }

        if (shownBuiltIn.isEmpty() && shownInstalled.isEmpty()) {
            item {
                EmptyState(
                    icon = PyIcons.Search,
                    title = "No plugin matches that",
                    hint = "Clear the search to see all ${Plugins.ALL.size + installed.size}.",
                )
            }
        }

        if (needle.isEmpty()) {
            item {
                Spacer(Modifier.height(6.dp))
                PyCard {
                    Text("What a plugin is here", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        text = "The built-in ones ship inside the app: nothing is downloaded " +
                            "and no code is loaded at runtime, so a switch can only reach " +
                            "behaviour that is already in the binary. An installed plugin is " +
                            "the opposite - it is code you added, and it runs with everything " +
                            "the app can do.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }

    warning?.let { pending ->
        UnverifiedWarningDialog(
            source = pending,
            onDismiss = { warning = null },
            onConfirm = {
                warning = null
                when (pending) {
                    PendingInstall.Folder -> onInstallFolder()
                    PendingInstall.File -> onInstallFile()
                    PendingInstall.Workspace -> {
                        onRefreshCandidates()
                        pickingFromWorkspace = true
                    }
                }
            },
        )
    }

    if (pickingFromWorkspace) {
        WorkspacePluginDialog(
            candidates = workspaceCandidates,
            onDismiss = { pickingFromWorkspace = false },
            onPick = {
                pickingFromWorkspace = false
                onInstallWorkspace(it)
            },
        )
    }

    pendingRemoval?.let { plugin ->
        ConfirmDialog(
            title = "Remove ${plugin.name}?",
            message = "Its folder and anything it saved there are deleted. Files it wrote " +
                "into the workspace stay where they are.",
            confirmLabel = "Remove",
            destructive = true,
            onDismiss = { pendingRemoval = null },
            onConfirm = {
                pendingRemoval = null
                onRemoveInstalled(plugin)
            },
        )
    }
}

private enum class PendingInstall { File, Folder, Workspace }

/**
 * The screen between "install a plugin" and actually installing one.
 *
 * Worth its own dialog rather than a line of small print: a plugin is not
 * sandboxed, cannot be sandboxed by anything CPython offers, and the only
 * real protection is a person deciding they trust the author.
 */
@Composable
private fun UnverifiedWarningDialog(
    source: PendingInstall,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    ConfirmDialog(
        title = "Plugins are not checked",
        message = "A plugin is Python that runs inside PyCmd with everything PyCmd can do: " +
            "it can read and change every file in your workspace, open network " +
            "connections, install packages, and keep running while the app is open.\n\n" +
            "Nobody reviews these. There is no sandbox - CPython has nothing that would " +
            "hold one. Install a plugin only if you wrote it or you trust whoever did, " +
            "and read the code first if you are not sure.\n\n" +
            "You can switch it off or remove it at any time from this screen.",
        confirmLabel = when (source) {
            PendingInstall.Folder -> "I understand - pick a folder"
            PendingInstall.File -> "I understand - pick a file"
            PendingInstall.Workspace -> "I understand - show me the workspace"
        },
        destructive = true,
        onDismiss = onDismiss,
        onConfirm = onConfirm,
    )
}

@Composable
private fun InstallCard(
    busy: String,
    onFile: () -> Unit,
    onFolder: () -> Unit,
    onWorkspace: () -> Unit,
    onGuide: () -> Unit,
) {
    PyCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                PyIcons.Add,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.tertiary,
                modifier = Modifier.size(20.dp),
            )
            Spacer(Modifier.width(10.dp))
            Text("Install a plugin", style = MaterialTheme.typography.titleMedium)
        }
        Spacer(Modifier.height(6.dp))
        Text(
            "A .py file, a folder, or a .zip of a folder. You are warned before the " +
                "picker opens, because an installed plugin runs with the app's own powers.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(10.dp))
        if (busy.isNotEmpty()) {
            BusyRow(busy)
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ActionButton(
                    text = "File or zip",
                    icon = PyIcons.FileUpload,
                    onClick = onFile,
                    modifier = Modifier.weight(1f),
                    containerColor = MaterialTheme.colorScheme.tertiary,
                )
                GhostButton("Folder", PyIcons.Folder, onFolder, Modifier.weight(1f))
            }
            Spacer(Modifier.height(8.dp))
            // The system picker cannot see the app's own storage, so a plugin
            // written here in PyCmd needs its own way in.
            GhostButton(
                "From the workspace",
                PyIcons.FolderOpen,
                onWorkspace,
                Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(6.dp))
            TextButton(onClick = onGuide) {
                Text("How do I write one?", style = MaterialTheme.typography.labelLarge)
            }
        }
    }
}

@Composable
private fun InstalledRow(
    plugin: InstalledPlugin,
    isOn: Boolean,
    onToggle: (Boolean) -> Unit,
    onOpen: () -> Unit,
    onRemove: () -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }

    PyCard {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        plugin.name,
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.Medium,
                    )
                    Spacer(Modifier.width(8.dp))
                    StatusChip("installed", MaterialTheme.colorScheme.tertiary)
                    if (plugin.loaded) {
                        Spacer(Modifier.width(6.dp))
                        StatusChip("running", MaterialTheme.colorScheme.primary)
                    }
                }
                Spacer(Modifier.height(2.dp))
                Text(
                    listOfNotNull(
                        plugin.version.takeIf { it.isNotEmpty() }?.let { "v$it" },
                        plugin.author.takeIf { it.isNotEmpty() },
                        plugin.readableSize,
                    ).joinToString("  ·  "),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (!plugin.broken) {
                Switch(checked = isOn, onCheckedChange = onToggle)
            }
        }

        if (plugin.description.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text(
                plugin.description,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        if (plugin.commands.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text(
                "Console commands: " + plugin.commands.joinToString(", ") { it.name },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.secondary,
            )
        }

        if (plugin.permissions.isNotEmpty()) {
            Spacer(Modifier.height(4.dp))
            Text(
                "Asks for: " + plugin.permissions.joinToString(", "),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        val problem = plugin.error
        if (!problem.isNullOrEmpty()) {
            Spacer(Modifier.height(8.dp))
            Box(
                Modifier
                    .fillMaxWidth()
                    .background(
                        MaterialTheme.colorScheme.error.copy(alpha = 0.12f),
                        RoundedCornerShape(10.dp),
                    )
                    .padding(10.dp),
            ) {
                Text(
                    problem.lineSequence().take(6).joinToString("\n"),
                    style = MaterialTheme.typography.labelSmall,
                    fontFamily = MonoFamily,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }

        if (expanded && plugin.files.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text(
                plugin.files.joinToString("\n"),
                style = MaterialTheme.typography.labelSmall,
                fontFamily = MonoFamily,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (plugin.hasPanel) {
                GhostButton("Open", PyIcons.PlayArrow, onOpen, Modifier.weight(1f))
            }
            GhostButton(
                if (expanded) "Hide files" else "Files",
                PyIcons.Description,
                { expanded = !expanded },
                Modifier.weight(1f),
            )
            IconButton(onClick = onRemove, modifier = Modifier.size(40.dp)) {
                Icon(
                    PyIcons.Delete,
                    contentDescription = "Remove ${plugin.name}",
                    tint = MaterialTheme.colorScheme.error,
                    modifier = Modifier.size(19.dp),
                )
            }
        }
    }
}

@Composable
private fun KitBanner(fullKit: Boolean, active: Int, total: Int) {
    val accent = if (fullKit) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline

    Box(
        Modifier
            .fillMaxWidth()
            .background(
                if (fullKit) {
                    MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
                } else {
                    MaterialTheme.colorScheme.surface
                },
                RoundedCornerShape(14.dp),
            )
            .border(1.dp, accent.copy(alpha = 0.5f), RoundedCornerShape(14.dp))
            .padding(16.dp),
    ) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    if (fullKit) PyIcons.Inventory2 else PyIcons.Info,
                    contentDescription = null,
                    tint = accent,
                    modifier = Modifier.size(20.dp),
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    if (fullKit) "Full kit active" else "The kit is not complete",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = if (fullKit) accent else MaterialTheme.colorScheme.onSurface,
                )
            }
            Spacer(Modifier.height(8.dp))
            Text(
                text = if (fullKit) {
                    "Polyglot Files, Polyglot Runner and Power Pack are all on. You can create " +
                        "and edit 25+ file types, run the ones the device can actually execute, " +
                        "and every other plugin is running with its extras."
                } else {
                    "Switch on Polyglot Files, Polyglot Runner and Power Pack together. Each is " +
                        "useful alone; the third one multiplies the other two."
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                "$active of $total plugins on",
                style = MaterialTheme.typography.labelSmall,
                color = accent,
            )
        }
    }
}

@Composable
private fun PluginRow(
    spec: PluginSpec,
    isOn: Boolean,
    poweredUp: Boolean,
    blockedBy: String?,
    onToggle: (Boolean) -> Unit,
    onOpen: () -> Unit,
) {
    PyCard {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        spec.name,
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.Medium,
                    )
                    if (spec.group == PluginGroup.KIT) {
                        Spacer(Modifier.width(8.dp))
                        StatusChip("kit", MaterialTheme.colorScheme.primary)
                    }
                }
                Spacer(Modifier.height(2.dp))
                Text(
                    spec.tagline,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.secondary,
                )
            }
            Switch(checked = isOn, onCheckedChange = onToggle)
        }

        Spacer(Modifier.height(8.dp))
        Text(
            spec.description,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        if (spec.poweredUp != null) {
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.Top) {
                Text(
                    if (poweredUp) "With Power Pack  " else "With Power Pack (off)  ",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (poweredUp) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.outline
                    },
                )
            }
            Text(
                spec.poweredUp,
                style = MaterialTheme.typography.labelSmall,
                color = if (poweredUp) {
                    MaterialTheme.colorScheme.onSurfaceVariant
                } else {
                    MaterialTheme.colorScheme.outline
                },
            )
        }

        if (blockedBy != null && isOn) {
            Spacer(Modifier.height(8.dp))
            Text(
                "Does nothing until $blockedBy is on.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.tertiary,
            )
        }

        if (spec.screen != null) {
            Spacer(Modifier.height(10.dp))
            TextButton(onClick = onOpen, enabled = isOn) {
                Text("Open ${spec.name}", style = MaterialTheme.typography.labelLarge)
            }
        }
    }
}

/**
 * Picks a plugin out of the workspace.
 *
 * Only things that could actually be one are listed: a folder with a
 * plugin.json, a zip, or a .py file that declares a PLUGIN block. A list of
 * every file would make the wrong thing easy to tap.
 */
@Composable
private fun WorkspacePluginDialog(
    candidates: List<java.io.File>,
    onDismiss: () -> Unit,
    onPick: (java.io.File) -> Unit,
) {
    ListDialog(
        title = "Install from the workspace",
        onDismiss = onDismiss,
    ) {
        if (candidates.isEmpty()) {
            Text(
                "Nothing in the workspace looks like a plugin yet.\n\n" +
                    "A folder with plugin.json in it, a .zip, or a .py file with a " +
                    "PLUGIN = {...} block will show up here. There are examples in " +
                    "examples/plugins.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            candidates.forEach { candidate ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clickable { onPick(candidate) }
                        .padding(vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        if (candidate.isDirectory) PyIcons.Folder else PyIcons.Description,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.secondary,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(10.dp))
                    Text(candidate.name, style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}

/** The search box used by both this screen and Files. */
@Composable
fun SearchField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.fillMaxWidth(),
        singleLine = true,
        placeholder = { Text(placeholder, style = MaterialTheme.typography.bodyMedium) },
        leadingIcon = {
            Icon(
                PyIcons.Search,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(18.dp),
            )
        },
        trailingIcon = {
            if (value.isNotEmpty()) {
                IconButton(onClick = { onValueChange("") }) {
                    Icon(
                        PyIcons.Clear,
                        contentDescription = "Clear the search",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(17.dp),
                    )
                }
            }
        },
        shape = RoundedCornerShape(12.dp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = MaterialTheme.colorScheme.primary,
            unfocusedBorderColor = MaterialTheme.colorScheme.outline,
        ),
    )
}
