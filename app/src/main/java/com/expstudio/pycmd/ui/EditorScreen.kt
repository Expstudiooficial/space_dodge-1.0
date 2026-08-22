package com.expstudio.pycmd.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FormatIndentDecrease
import androidx.compose.material.icons.filled.FormatIndentIncrease
import androidx.compose.material.icons.filled.NoteAdd
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Redo
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Undo
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/** Snippets and characters worth a single tap while writing code. */
private val EDITOR_KEYS = listOf(
    ":", "(", ")", "[", "]", "{", "}", "=", "\"", "'", ".", ",", "_", "->",
    "==", "!=", "+", "-", "*", "/", "%", "#", "self",
)

@Composable
fun EditorScreen(
    host: WebHost,
    state: EditorState,
    ready: Boolean,
    onContentChanged: (String) -> Unit,
    onCursorMoved: (Int, Int) -> Unit,
    onRun: () -> Unit,
    onSave: () -> Unit,
    onNew: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val currentContent by rememberUpdatedState(state.content)

    // Bridge callbacks arrive on the WebView's JS thread; hopping to the main
    // thread keeps state updates on the thread Compose expects.
    DisposableEffect(host) {
        host.bridge.editorChangedHandler = { text ->
            host.webView.post { onContentChanged(text) }
        }
        host.bridge.cursorMovedHandler = { line, column ->
            host.webView.post { onCursorMoved(line, column) }
        }
        host.bridge.editorReadyHandler = {
            host.eval("PyEditor.setContent(${jsString(currentContent)});")
        }
        onDispose {
            host.bridge.editorChangedHandler = {}
            host.bridge.cursorMovedHandler = { _, _ -> }
            host.bridge.editorReadyHandler = {}
        }
    }

    // Push content into the WebView only when a different document is loaded;
    // pushing on every keystroke would fight the editor for the caret.
    LaunchedEffect(state.epoch, host) {
        host.eval("if (window.PyEditor) { PyEditor.setContent(${jsString(currentContent)}); }")
    }

    Column(modifier.fillMaxSize()) {
        Row(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface)
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = state.fileName,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                    )
                    if (state.isDirty) {
                        Spacer(Modifier.width(8.dp))
                        StatusChip("unsaved", MaterialTheme.colorScheme.tertiary)
                    }
                }
                Text(
                    text = "Ln ${state.line}, Col ${state.column}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            IconButton(onClick = onNew) {
                Icon(
                    Icons.Filled.NoteAdd,
                    contentDescription = "New file",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onSave, enabled = ready) {
                Icon(
                    Icons.Filled.Save,
                    contentDescription = "Save",
                    tint = if (state.isDirty) {
                        MaterialTheme.colorScheme.tertiary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
            IconButton(onClick = onRun, enabled = ready) {
                Icon(
                    Icons.Filled.PlayArrow,
                    contentDescription = "Run",
                    tint = if (ready) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline,
                )
            }
        }

        Divider()

        Box(Modifier.weight(1f).fillMaxWidth()) {
            PersistentWebView(host, Modifier.fillMaxSize())
        }

        Row(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .padding(horizontal = 6.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            EditorToolButton(Icons.Filled.Undo, "Undo") { host.eval("PyEditor.undo();") }
            EditorToolButton(Icons.Filled.Redo, "Redo") { host.eval("PyEditor.redo();") }
            EditorToolButton(Icons.Filled.FormatIndentIncrease, "Indent") { host.eval("PyEditor.indent();") }
            EditorToolButton(Icons.Filled.FormatIndentDecrease, "Outdent") { host.eval("PyEditor.outdent();") }
        }

        KeyStrip(
            keys = EDITOR_KEYS,
            onKey = { key -> host.eval("PyEditor.insert(${jsString(key)});") },
        )
    }
}

@Composable
private fun EditorToolButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    description: String,
    onClick: () -> Unit,
) {
    IconButton(onClick = onClick, modifier = Modifier.size(40.dp)) {
        Icon(
            icon,
            contentDescription = description,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(19.dp),
        )
    }
}
