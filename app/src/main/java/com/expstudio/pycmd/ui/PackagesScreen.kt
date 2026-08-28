package com.expstudio.pycmd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import com.expstudio.pycmd.python.InstalledPackage

/** One-tap installs for libraries that are pure Python and widely useful. */
private val SUGGESTIONS = listOf(
    "httpx", "beautifulsoup4", "pyyaml", "tabulate", "colorama", "click",
    "jinja2", "python-dateutil", "toml", "markdown",
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PackagesScreen(
    state: PackagesState,
    pythonVersion: String,
    onInstall: (String, String?) -> Unit,
    onUninstall: (String) -> Unit,
    modifier: Modifier = Modifier,
    /** Sections plugins have added to this screen; empty when none are on. */
    pluginSections: @Composable () -> Unit = {},
) {
    var query by remember { mutableStateOf("") }
    var pendingRemoval by remember { mutableStateOf<String?>(null) }

    fun install() {
        val name = query.trim()
        if (name.isEmpty()) return
        // "package==1.2.3" is the spelling people already know from pip.
        val (packageName, version) = if ("==" in name) {
            val parts = name.split("==", limit = 2)
            parts[0].trim() to parts[1].trim().takeIf { it.isNotEmpty() }
        } else {
            name to null
        }
        onInstall(packageName, version)
        query = ""
    }

    Column(modifier.fillMaxSize()) {
        Column(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface)
                .padding(14.dp),
        ) {
            Text("Packages", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(4.dp))
            Text(
                text = "Installs universal wheels from PyPI into Python $pythonVersion on this device.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Spacer(Modifier.height(12.dp))

            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("package  or  package==1.2.3", fontFamily = MonoFamily) },
                    singleLine = true,
                    enabled = !state.busy,
                    shape = RoundedCornerShape(12.dp),
                    textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = MonoFamily),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = MaterialTheme.colorScheme.primary,
                        unfocusedBorderColor = MaterialTheme.colorScheme.outline,
                    ),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Go),
                    keyboardActions = KeyboardActions(onGo = { install() }),
                )
                Spacer(Modifier.width(8.dp))
                ActionButton(
                    text = "Install",
                    icon = PyIcons.Add,
                    onClick = ::install,
                    enabled = !state.busy && query.isNotBlank(),
                )
            }

            if (state.busy) {
                BusyRow(state.progress.ifBlank { "Working..." })
            }
        }

        Divider()

        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                SectionTitle("Suggested")
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    SUGGESTIONS.forEach { name ->
                        val installed = state.installed.any { it.name.equals(name, ignoreCase = true) }
                        StatusChip(
                            text = name,
                            color = if (installed) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.secondary
                            },
                            modifier = Modifier.clickable(
                                enabled = !state.busy && !installed,
                            ) { onInstall(name, null) },
                        )
                    }
                }
            }

            if (state.bundled.isNotEmpty()) {
                item {
                    Spacer(Modifier.height(4.dp))
                    SectionTitle("Built in")
                    PyCard {
                        Text(
                            text = state.bundled.joinToString("  -  "),
                            style = MaterialTheme.typography.bodyMedium,
                            fontFamily = MonoFamily,
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            text = "Compiled into the app. These cannot be removed.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            item {
                Spacer(Modifier.height(4.dp))
                SectionTitle("Installed here (${state.installed.size})")
            }

            if (state.installed.isEmpty()) {
                item {
                    EmptyState(
                        icon = PyIcons.Inventory2,
                        title = "Nothing installed yet",
                        hint = "Search for a package above, or tap a suggestion.",
                    )
                }
            } else {
                items(state.installed, key = { it.name }) { entry ->
                    InstalledRow(
                        entry = entry,
                        enabled = !state.busy,
                        onRemove = { pendingRemoval = entry.name },
                    )
                }
            }

            item { pluginSections() }

        item {
                Spacer(Modifier.height(8.dp))
                PyCard {
                    Text(
                        "About native packages",
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        text = "Libraries with compiled C extensions - pygame, scipy, pandas and " +
                            "similar - need wheels built specifically for Android and cannot be " +
                            "fetched from PyPI at runtime. Pure-Python packages install normally.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }

    val removal = pendingRemoval
    if (removal != null) {
        ConfirmDialog(
            title = "Remove $removal?",
            message = "Its files are deleted from this device. You can install it again later.",
            confirmLabel = "Remove",
            destructive = true,
            onDismiss = { pendingRemoval = null },
            onConfirm = {
                pendingRemoval = null
                onUninstall(removal)
            },
        )
    }
}

@Composable
private fun InstalledRow(
    entry: InstalledPackage,
    enabled: Boolean,
    onRemove: () -> Unit,
) {
    PyCard(contentPadding = PaddingValues(start = 14.dp, end = 6.dp, top = 10.dp, bottom = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        entry.name,
                        style = MaterialTheme.typography.bodyLarge,
                        fontFamily = MonoFamily,
                    )
                    Spacer(Modifier.width(8.dp))
                    StatusChip(entry.version, MaterialTheme.colorScheme.primary)
                }
                if (entry.summary.isNotBlank()) {
                    Spacer(Modifier.height(3.dp))
                    Text(
                        entry.summary,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                    )
                }
            }
            IconButton(onClick = onRemove, enabled = enabled) {
                Icon(
                    PyIcons.Delete,
                    contentDescription = "Remove ${entry.name}",
                    tint = MaterialTheme.colorScheme.error,
                    modifier = Modifier.size(19.dp),
                )
            }
        }
    }
}
