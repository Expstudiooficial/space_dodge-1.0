package com.expstudio.pycmd.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.Row
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.expstudio.pycmd.python.OutputChunk

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PyCmdRoot(viewModel: MainViewModel = viewModel()) {
    val context = LocalContext.current
    val snackbarHost = remember { SnackbarHostState() }

    val tab by viewModel.tab.collectAsState()
    val status by viewModel.engineStatus.collectAsState()
    val editorState by viewModel.editor.collectAsState()
    val filesState by viewModel.files.collectAsState()
    val packagesState by viewModel.packages.collectAsState()
    val serversState by viewModel.servers.collectAsState()
    val history by viewModel.history.collectAsState()
    val toast by viewModel.toast.collectAsState()
    val serverCount by viewModel.serverCount.collectAsState()

    // Both WebViews are created once and reused for the life of the screen, so
    // console history and editor state survive tab switches.
    val consoleHost = rememberWebHost("console.html")
    val editorHost = rememberWebHost("editor.html")

    var aboutOpen by remember { mutableStateOf(false) }
    var saveAsOpen by remember { mutableStateOf(false) }
    var runtimeInfo by remember { mutableStateOf<Map<String, String>>(emptyMap()) }

    // Collected here rather than inside ConsoleScreen: output must keep
    // arriving while the user is looking at another tab.
    LaunchedEffect(consoleHost) {
        viewModel.output.collect { chunk ->
            consoleHost.eval(consoleAppendScript(chunk))
        }
    }

    LaunchedEffect(toast) {
        val message = toast ?: return@LaunchedEffect
        snackbarHost.showSnackbar(message.text)
        viewModel.consumeToast()
    }

    LaunchedEffect(aboutOpen) {
        if (aboutOpen) runtimeInfo = viewModel.runtimeInfo()
    }

    // Back inside Files walks up the tree before leaving the app; anywhere
    // else it returns to the console first.
    BackHandler(enabled = tab != Tab.CONSOLE) {
        if (tab == Tab.FILES && viewModel.navigateUp()) return@BackHandler
        viewModel.selectTab(Tab.CONSOLE)
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(snackbarHost) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface,
                ),
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("PyCmd", style = MaterialTheme.typography.titleLarge)
                        Spacer(Modifier.width(10.dp))
                        when {
                            status.startupError != null -> StatusChip(
                                "interpreter failed",
                                MaterialTheme.colorScheme.error,
                            )

                            status.ready -> StatusChip(
                                "Python ${status.pythonVersion}",
                                MaterialTheme.colorScheme.primary,
                            )

                            else -> Row(verticalAlignment = Alignment.CenterVertically) {
                                CircularProgressIndicator(
                                    strokeWidth = 2.dp,
                                    modifier = Modifier.size(13.dp),
                                    color = MaterialTheme.colorScheme.primary,
                                )
                                Spacer(Modifier.width(8.dp))
                                Text(
                                    "starting",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                },
                actions = {
                    IconButton(onClick = { viewModel.clearNamespace() }, enabled = status.ready) {
                        Icon(
                            Icons.Filled.RestartAlt,
                            contentDescription = "Reset variables",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    IconButton(onClick = { aboutOpen = true }) {
                        Icon(
                            Icons.Filled.Info,
                            contentDescription = "About",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                },
            )
        },
        bottomBar = {
            NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
                TabItem(Tab.CONSOLE, Icons.Filled.Terminal, tab, viewModel::selectTab)
                TabItem(Tab.EDITOR, Icons.Filled.Edit, tab, viewModel::selectTab, dot = editorState.isDirty)
                TabItem(Tab.FILES, Icons.Filled.Folder, tab, viewModel::selectTab)
                TabItem(Tab.PACKAGES, Icons.Filled.Inventory2, tab, viewModel::selectTab)
                TabItem(Tab.SERVERS, Icons.Filled.Dns, tab, viewModel::selectTab, count = serverCount)
            }
        },
    ) { padding ->
        Box(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .background(MaterialTheme.colorScheme.background),
        ) {
            when (tab) {
                Tab.CONSOLE -> ConsoleScreen(
                    host = consoleHost,
                    status = status,
                    history = history,
                    onRun = viewModel::runConsole,
                    onStdin = viewModel::submitStdin,
                    onStop = viewModel::stopExecution,
                    onClear = { consoleHost.eval("PyConsole.clear();") },
                )

                Tab.EDITOR -> EditorScreen(
                    host = editorHost,
                    state = editorState,
                    ready = status.ready,
                    onContentChanged = viewModel::onEditorContentChanged,
                    onCursorMoved = viewModel::onCursorMoved,
                    onRun = viewModel::runEditor,
                    onSave = {
                        if (editorState.file == null) saveAsOpen = true else viewModel.saveEditor()
                    },
                    onNew = viewModel::newFile,
                )

                Tab.FILES -> FilesScreen(
                    state = filesState,
                    rootPath = viewModel.workspaceRoot.absolutePath,
                    relativePath = { file ->
                        file.absolutePath.removePrefix(viewModel.workspaceRoot.absolutePath)
                            .removePrefix("/")
                            .ifEmpty { "/" }
                    },
                    onOpenDirectory = viewModel::openDirectory,
                    onOpenFile = viewModel::openInEditor,
                    onRunFile = viewModel::runFile,
                    onUp = { viewModel.navigateUp() },
                    onNewFile = viewModel::createFile,
                    onNewFolder = viewModel::createFolder,
                    onRename = viewModel::renameEntry,
                    onDelete = viewModel::deleteEntry,
                    onImport = viewModel::importFile,
                )

                Tab.PACKAGES -> PackagesScreen(
                    state = packagesState,
                    pythonVersion = status.pythonVersion.ifBlank { "3.13" },
                    onInstall = viewModel::installPackage,
                    onUninstall = viewModel::uninstallPackage,
                )

                Tab.SERVERS -> ServersScreen(
                    state = serversState,
                    currentFolder = (filesState.directory ?: viewModel.workspaceRoot).absolutePath
                        .removePrefix(viewModel.workspaceRoot.absolutePath)
                        .removePrefix("/")
                        .ifEmpty { "workspace root" },
                    onStartFileServer = viewModel::startFileServer,
                    onStop = viewModel::stopServer,
                    onStopAll = viewModel::stopAllServers,
                    onCopy = { text ->
                        copyToClipboard(context, text)
                        viewModel.showToast("Copied $text")
                    },
                )
            }
        }
    }

    if (saveAsOpen) {
        TextPromptDialog(
            title = "Save as",
            label = "File name",
            initial = "script.py",
            confirmLabel = "Save",
            onDismiss = { saveAsOpen = false },
            onConfirm = { name ->
                saveAsOpen = false
                viewModel.saveEditor(name)
            },
        )
    }

    if (aboutOpen) {
        AboutDialog(
            info = runtimeInfo,
            status = status,
            onDismiss = { aboutOpen = false },
        )
    }
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.TabItem(
    target: Tab,
    icon: ImageVector,
    current: Tab,
    onSelect: (Tab) -> Unit,
    count: Int = 0,
    dot: Boolean = false,
) {
    NavigationBarItem(
        selected = current == target,
        onClick = { onSelect(target) },
        icon = {
            BadgedBox(
                badge = {
                    when {
                        count > 0 -> Badge { Text(count.toString()) }
                        dot -> Badge()
                        else -> Unit
                    }
                },
            ) {
                Icon(icon, contentDescription = target.label)
            }
        },
        label = { Text(target.label, style = MaterialTheme.typography.labelSmall) },
        colors = NavigationBarItemDefaults.colors(
            selectedIconColor = MaterialTheme.colorScheme.onPrimary,
            selectedTextColor = MaterialTheme.colorScheme.primary,
            indicatorColor = MaterialTheme.colorScheme.primary,
            unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
            unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
        ),
    )
}

@Composable
private fun AboutDialog(
    info: Map<String, String>,
    status: com.expstudio.pycmd.python.EngineStatus,
    onDismiss: () -> Unit,
) {
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = MaterialTheme.colorScheme.surface,
        title = { Text("PyCmd 1.0", style = MaterialTheme.typography.titleMedium) },
        text = {
            Column {
                Text(
                    "A Python command line, editor and server runner for Android.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
                InfoRow("Python", info["full_version"] ?: status.pythonVersion)
                InfoRow("Platform", info["platform"] ?: "android")
                InfoRow("Working dir", info["cwd"] ?: "")
                if (status.startupError != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Startup error: ${status.startupError}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        },
        confirmButton = {
            androidx.compose.material3.TextButton(onClick = onDismiss) { Text("Close") }
        },
    )
}

@Composable
private fun InfoRow(label: String, value: String) {
    if (value.isBlank()) return
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(
            label.uppercase(),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(value, style = MaterialTheme.typography.bodySmall, fontFamily = MonoFamily)
    }
}

/**
 * Builds the JS that appends one chunk.
 *
 * Output can arrive before console.js has finished loading, so anything early
 * is parked in a queue the script drains on start-up.
 */
private fun consoleAppendScript(chunk: OutputChunk): String {
    val stream = when (chunk.stream) {
        OutputChunk.Stream.STDERR -> "stderr"
        OutputChunk.Stream.SYSTEM -> "system"
        OutputChunk.Stream.INPUT -> "input"
        OutputChunk.Stream.STDOUT -> "stdout"
    }
    val text = jsString(chunk.text)
    return """
        (function () {
          var payload = { stream: ${jsString(stream)}, text: $text };
          if (window.PyConsole) {
            window.PyConsole.append(payload.stream, payload.text);
          } else {
            window.PyConsoleQueue = window.PyConsoleQueue || [];
            window.PyConsoleQueue.push(payload);
          }
        })();
    """.trimIndent()
}

private fun copyToClipboard(context: Context, text: String) {
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
    clipboard?.setPrimaryClip(ClipData.newPlainText("PyCmd", text))
}
