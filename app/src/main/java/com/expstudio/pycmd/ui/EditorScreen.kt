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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.expstudio.pycmd.plugins.Snippets
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * Characters worth a single tap, per language.
 *
 * The strip used to be Python's for every file, so a Go file offered `self`
 * and `#` and no `//`. The keys a phone keyboard buries are different in each
 * language, which is the whole reason the strip exists.
 */
private val COMMON_KEYS = listOf(
    "(", ")", "[", "]", "{", "}", "=", "\"", "'", ".", ",", "_",
    "==", "!=", "+", "-", "*", "/", "%", "<", ">",
)

private val PYTHON_KEYS = listOf(":", "#", "self", "->", "|") + COMMON_KEYS
private val BRACE_KEYS = listOf(";", "//", "->", "&&", "||", "=>") + COMMON_KEYS
private val MARKUP_KEYS = listOf("<", ">", "/", ":", ";", "-") + COMMON_KEYS

private fun keysFor(highlight: String): List<String> = when (highlight) {
    "python", "shell", "yaml" -> PYTHON_KEYS
    "html", "markdown", "css" -> MARKUP_KEYS
    "text" -> COMMON_KEYS
    else -> BRACE_KEYS
}

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
    onSaveAs: () -> Unit = {},
    onRunAsServer: () -> Unit = {},
    onOpenDebug: () -> Unit = {},
    onCopyAll: (String) -> Unit = {},
    languageId: String = "python",
    languageName: String = "",
    highlightAs: String = "python",
    snippetsOn: Boolean = false,
    snippetsPoweredUp: Boolean = false,
) {
    var menuOpen by remember { mutableStateOf(false) }
    var goToLineOpen by remember { mutableStateOf(false) }
    // Off by default: code is written in columns, and a wrapped line hides
    // that. It is here for the lines that are longer than any phone.
    var wrapping by remember { mutableStateOf(false) }
    val currentContent by rememberUpdatedState(state.content)
    val currentEpoch by rememberUpdatedState(state.epoch)
    val currentWrapping by rememberUpdatedState(wrapping)
    val currentHighlight by rememberUpdatedState(highlightAs)

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
            // The page reloaded (first load, or the system reclaimed it), so
            // whatever is in the buffer has to be put back - the wrap setting
            // included, or a reload silently unwraps the file you are reading.
            host.loadedEpoch = currentEpoch
            host.eval("PyEditor.setLanguage(${jsString(currentHighlight)});")
            host.eval("PyEditor.setContent(${jsString(currentContent)});")
            host.eval("PyEditor.setWrap($currentWrapping);")
        }
        onDispose {
            host.bridge.editorChangedHandler = {}
            host.bridge.cursorMovedHandler = { _, _ -> }
            host.bridge.editorReadyHandler = {}
        }
    }

    // Push content into the WebView only when a different document is loaded;
    // pushing on every keystroke would fight the editor for the caret, and
    // pushing on every tab switch would reset it.
    LaunchedEffect(state.epoch, host) {
        if (host.loadedEpoch == state.epoch) return@LaunchedEffect
        host.loadedEpoch = state.epoch
        host.eval("if (window.PyEditor) { PyEditor.setContent(${jsString(currentContent)}); }")
    }

    // The grammar follows the file, not the document: switching from a .py to
    // a .go file has to repaint even though both are just text to the editor.
    LaunchedEffect(highlightAs, host) {
        host.eval("if (window.PyEditor) { PyEditor.setLanguage(${jsString(highlightAs)}); }")
    }

    // The page can be reloaded out from under us, so the wrap setting is
    // pushed back rather than assumed to have survived.
    LaunchedEffect(wrapping, state.epoch, host) {
        host.eval("if (window.PyEditor) { PyEditor.setWrap($wrapping); }")
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
                    text = "Ln ${state.line}, Col ${state.column}" +
                        if (languageName.isNotEmpty()) "  ·  $languageName" else "",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            IconButton(onClick = onNew) {
                Icon(
                    PyIcons.NoteAdd,
                    contentDescription = "New file",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onSave, enabled = ready) {
                Icon(
                    PyIcons.Save,
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
                    PyIcons.PlayArrow,
                    contentDescription = "Run",
                    tint = if (ready) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline,
                )
            }

            Box {
                IconButton(onClick = { menuOpen = true }) {
                    Icon(
                        PyIcons.MoreVert,
                        contentDescription = "Commands",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                    EditorCommand("Run", PyIcons.PlayArrow) { menuOpen = false; onRun() }
                    EditorCommand("Run as a server", PyIcons.Dns) { menuOpen = false; onRunAsServer() }
                    EditorCommand("Save", PyIcons.Save) { menuOpen = false; onSave() }
                    EditorCommand("Save as...", PyIcons.NoteAdd) { menuOpen = false; onSaveAs() }
                    EditorCommand("Copy all", PyIcons.ContentCopy) {
                        menuOpen = false
                        onCopyAll(state.content)
                    }
                    EditorCommand(
                        if (wrapping) "Stop wrapping lines" else "Wrap long lines",
                        PyIcons.WrapText,
                    ) {
                        menuOpen = false
                        wrapping = !wrapping
                        host.eval("PyEditor.setWrap($wrapping);")
                    }
                    EditorCommand("Go to line...", PyIcons.FormatIndentIncrease) {
                        menuOpen = false
                        goToLineOpen = true
                    }
                    EditorCommand("Undo", PyIcons.Undo) { menuOpen = false; host.eval("PyEditor.undo();") }
                    EditorCommand("Redo", PyIcons.Redo) { menuOpen = false; host.eval("PyEditor.redo();") }
                    EditorCommand("Debug console", PyIcons.BugReport) { menuOpen = false; onOpenDebug() }
                }
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
            EditorToolButton(PyIcons.Undo, "Undo") { host.eval("PyEditor.undo();") }
            EditorToolButton(PyIcons.Redo, "Redo") { host.eval("PyEditor.redo();") }
            EditorToolButton(PyIcons.FormatIndentIncrease, "Indent") { host.eval("PyEditor.indent();") }
            EditorToolButton(PyIcons.FormatIndentDecrease, "Outdent") { host.eval("PyEditor.outdent();") }
        }

        if (snippetsOn) {
            val snippets = remember(languageId, snippetsPoweredUp) {
                Snippets.forLanguage(languageId, snippetsPoweredUp)
            }
            KeyStrip(
                keys = snippets.map { it.label },
                onKey = { label ->
                    snippets.firstOrNull { it.label == label }?.let { snippet ->
                        val (text, caret) = Snippets.split(snippet.body)
                        host.eval("PyEditor.insertSnippet(${jsString(text)}, $caret);")
                    }
                },
            )
        }

        KeyStrip(
            keys = remember(highlightAs) { keysFor(highlightAs) },
            onKey = { key -> host.eval("PyEditor.insert(${jsString(key)});") },
        )
    }

    if (goToLineOpen) {
        TextPromptDialog(
            title = "Go to line",
            label = "Line number",
            initial = state.line.toString(),
            confirmLabel = "Go",
            supportingText = "Jumps the caret there and scrolls it into view.",
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Number,
                imeAction = ImeAction.Done,
            ),
            onDismiss = { goToLineOpen = false },
            onConfirm = { typed ->
                goToLineOpen = false
                typed.trim().toIntOrNull()?.let { host.eval("PyEditor.goToLine($it);") }
            },
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

@Composable
private fun EditorCommand(
    label: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: () -> Unit,
) {
    DropdownMenuItem(
        text = { Text(label) },
        leadingIcon = {
            Icon(
                icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(18.dp),
            )
        },
        onClick = onClick,
    )
}
