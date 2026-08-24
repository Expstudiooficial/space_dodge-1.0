package com.expstudio.pycmd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.expstudio.pycmd.plugins.PluginGroup
import com.expstudio.pycmd.plugins.PluginIds
import com.expstudio.pycmd.plugins.PluginSpec
import com.expstudio.pycmd.plugins.Plugins

/**
 * The plugin list.
 *
 * Every switch here changes behaviour that is already compiled into the app -
 * nothing is downloaded and no code is loaded at runtime, which is what keeps
 * a toggle from being able to do anything the binary cannot already do.
 */
@Composable
fun PluginsScreen(
    enabled: Set<String>,
    onToggle: (String, Boolean) -> Unit,
    onOpen: (PluginSpec) -> Unit,
    onEnableAll: () -> Unit,
    onReset: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val fullKit = PluginIds.CORE.all { it in enabled }
    val poweredUp = PluginIds.POWER_PACK in enabled

    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
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

        PluginGroup.entries.forEach { group ->
            val inGroup = Plugins.ALL.filter { it.group == group }
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

        item {
            Spacer(Modifier.height(6.dp))
            PyCard {
                Text("What a plugin is here", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(6.dp))
                Text(
                    text = "All of these ship inside the app. Nothing is downloaded and no code " +
                        "is loaded at runtime, so a switch can only reach behaviour that is " +
                        "already in the binary. Turning one off costs nothing but the feature.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
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
