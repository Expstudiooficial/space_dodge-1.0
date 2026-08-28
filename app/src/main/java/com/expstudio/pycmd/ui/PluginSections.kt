package com.expstudio.pycmd.ui

import android.graphics.BitmapFactory
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.expstudio.pycmd.plugins.InstalledPlugin
import com.expstudio.pycmd.plugins.PluginExtension
import com.expstudio.pycmd.plugins.PluginGuide
import java.io.File

/**
 * The sections plugins have added to one of the app's own screens.
 *
 * A plugin used to have two choices: a tab of its own, or nothing. That is the
 * wrong shape for a plugin that is *about* an existing screen - Server Pro
 * belongs in Servers, not beside it - so a plugin can now put a card at the
 * bottom of a screen it names, holding a page of its own.
 *
 * Collapsed by default unless the plugin asks otherwise, because a screen the
 * user opened for another reason should not rearrange itself; and the panel
 * inside is only built once it is opened, so a closed section costs a heading
 * and nothing else.
 */
/**
 * Picks out the sections switched-on plugins want to add to [tab].
 *
 * Takes the lists the caller has already collected rather than reading them
 * from the view model, so that switching a plugin on redraws the screen it
 * extends instead of waiting for something else to happen.
 */
fun sectionsFor(
    tab: Tab,
    installed: List<InstalledPlugin>,
    enabled: Set<String>,
): List<Pair<InstalledPlugin, PluginExtension>> {
    val name = tab.extensionName ?: return emptyList()
    return installed
        .filter { it.id in enabled }
        .flatMap { plugin -> plugin.extensions.filter { it.tab == name }.map { plugin to it } }
}

/**
 * Every guide a switched-on plugin has published.
 *
 * Takes the collected lists for the same reason [sectionsFor] does: switching
 * a plugin on should make its guide appear, not wait for something else to
 * redraw the screen. Only plugins that are on - a guide for something the user
 * cannot currently do would be a puzzle rather than a help.
 */
fun guidesFor(
    installed: List<InstalledPlugin>,
    enabled: Set<String>,
): List<Pair<InstalledPlugin, PluginGuide>> =
    installed
        .filter { it.id in enabled }
        .flatMap { plugin -> plugin.guides.map { plugin to it } }

@Composable
fun PluginSections(
    sections: List<Pair<InstalledPlugin, PluginExtension>>,
    viewModel: MainViewModel,
    modifier: Modifier = Modifier,
) {
    if (sections.isEmpty()) return

    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionTitle("From your plugins")
        sections.forEach { (plugin, extension) ->
            PluginSectionCard(plugin, extension, viewModel)
        }
    }
}

@Composable
private fun PluginSectionCard(
    plugin: InstalledPlugin,
    extension: PluginExtension,
    viewModel: MainViewModel,
) {
    var open by rememberSaveable("${plugin.id}:${extension.panel}") {
        mutableStateOf(extension.startsOpen)
    }
    val height = remember(extension.height) {
        when (extension.height) {
            "short" -> 220.dp
            "tall" -> 620.dp
            else -> 400.dp
        }
    }

    PyCard(contentPadding = PaddingValues(0.dp)) {
        Row(
            Modifier
                .fillMaxWidth()
                .clickable { open = !open }
                .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val image = remember(extension.image) { loadPluginImage(extension.image) }
            if (image != null) {
                Image(
                    bitmap = image,
                    contentDescription = null,
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.size(22.dp).clip(RoundedCornerShape(6.dp)),
                )
            } else {
                Icon(
                    if (open) PyIcons.ExpandLess else PyIcons.ExpandMore,
                    contentDescription = if (open) "Collapse" else "Expand",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(20.dp),
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    extension.title.ifBlank { plugin.name },
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    extension.description.ifBlank { plugin.name },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                )
            }
            // A tall panel inside a scrolling screen is workable but never
            // roomy; this opens the same page with the whole screen to itself.
            IconButton(
                onClick = { viewModel.openPluginPanel(plugin, extension.panel) },
                modifier = Modifier.size(34.dp),
            ) {
                Icon(
                    PyIcons.OpenInFull,
                    contentDescription = "Open ${extension.title} full screen",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(17.dp),
                )
            }
            Icon(
                if (open) PyIcons.ExpandLess else PyIcons.ExpandMore,
                contentDescription = if (open) "Collapse" else "Expand",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(20.dp),
            )
        }

        AnimatedVisibility(visible = open) {
            Box(Modifier.fillMaxWidth().height(height)) {
                PluginPanelView(
                    plugin = plugin,
                    viewModel = viewModel,
                    modifier = Modifier.fillMaxWidth().height(height),
                    panelFile = extension.panel,
                )
            }
        }
    }
}

/** The icon is drawn at 24dp; decoding anything much larger is wasted work. */
private const val ICON_TARGET_PIXELS = 128

/**
 * Decodes a picture a plugin ships, or gives up quietly.
 *
 * The file comes from a plugin, so its size is not ours to assume. It is
 * measured first and decoded scaled down, because a plugin that ships a photo
 * by mistake should cost a small bitmap and a shrug rather than a stutter on
 * the More screen every time it is opened.
 */
fun loadPluginImage(path: String): ImageBitmap? {
    if (path.isBlank()) return null
    // An SVG is not something BitmapFactory can read, and pulling in a vector
    // loader for a 24dp icon is not worth it; those fall back to the glyph.
    if (path.lowercase().endsWith(".svg")) return null
    val file = File(path)
    if (!file.isFile || file.length() > 4L * 1024 * 1024) return null

    return runCatching {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(path, bounds)
        val largest = maxOf(bounds.outWidth, bounds.outHeight)
        if (largest <= 0) return null

        var sample = 1
        while (largest / sample > ICON_TARGET_PIXELS * 2) sample *= 2

        BitmapFactory
            .decodeFile(path, BitmapFactory.Options().apply { inSampleSize = sample })
            ?.asImageBitmap()
    }.getOrNull()
}
