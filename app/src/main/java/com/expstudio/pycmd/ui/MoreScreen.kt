package com.expstudio.pycmd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * The destinations that do not fit in the bottom bar.
 *
 * Five items is the most a phone-width navigation bar can label without
 * wrapping, and there are eight screens, so the three least-used sit here.
 */
@Composable
fun MoreScreen(
    serverCount: Int,
    downloadCount: Int,
    pluginCount: Int,
    errorCount: Int,
    onSelect: (Tab) -> Unit,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = PaddingValues(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item { SectionTitle("More") }

        item {
            DestinationRow(
                icon = PyIcons.Inventory2,
                title = "Packages",
                subtitle = "Install Python libraries from PyPI onto the device",
                badge = null,
                onClick = { onSelect(Tab.PACKAGES) },
            )
        }
        item {
            DestinationRow(
                icon = PyIcons.FileUpload,
                title = "Downloads",
                subtitle = "Files fetched from a URL, and workspace exports",
                badge = if (downloadCount > 0) downloadCount.toString() else null,
                onClick = { onSelect(Tab.DOWNLOADS) },
            )
        }
        item {
            DestinationRow(
                icon = PyIcons.Add,
                title = "Plugins",
                subtitle = "Built-in features you can switch on and off",
                badge = if (pluginCount > 0) pluginCount.toString() else null,
                onClick = { onSelect(Tab.PLUGINS) },
            )
        }
        item {
            DestinationRow(
                icon = PyIcons.Description,
                title = "Guides",
                subtitle = "How to write a plugin, the tutorial, and what each file type does",
                badge = null,
                onClick = { onSelect(Tab.DOCS) },
            )
        }
        item {
            DestinationRow(
                icon = PyIcons.Tune,
                title = "System",
                subtitle = "Storage, versions, what is running, and the housekeeping buttons",
                badge = null,
                onClick = { onSelect(Tab.SYSTEM) },
            )
        }
        item {
            DestinationRow(
                icon = PyIcons.BugReport,
                title = "Debug console",
                subtitle = "Errors, server events and everything else the app did",
                badge = if (errorCount > 0) errorCount.toString() else null,
                destructiveBadge = errorCount > 0,
                onClick = { onSelect(Tab.DEBUG) },
            )
        }

        if (serverCount > 0) {
            item {
                Spacer(Modifier.height(4.dp))
                PyCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            PyIcons.Dns,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(Modifier.width(10.dp))
                        Text(
                            "$serverCount server${if (serverCount == 1) "" else "s"} running",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun DestinationRow(
    icon: ImageVector,
    title: String,
    subtitle: String,
    badge: String?,
    onClick: () -> Unit,
    destructiveBadge: Boolean = false,
) {
    PyCard(contentPadding = PaddingValues(0.dp)) {
        Row(
            Modifier
                .fillMaxWidth()
                .clickable(onClick = onClick)
                .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.secondary,
                modifier = Modifier.size(22.dp),
            )
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    title,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    subtitle,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (badge != null) {
                StatusChip(
                    badge,
                    if (destructiveBadge) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.primary
                    },
                )
            }
        }
    }
}
