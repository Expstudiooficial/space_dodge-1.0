package com.expstudio.pycmd.ui

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.expstudio.pycmd.python.EngineStatus
import com.expstudio.pycmd.python.InstalledPackage
import com.expstudio.pycmd.python.OutputChunk
import com.expstudio.pycmd.python.PythonEngine
import com.expstudio.pycmd.python.RunningServer
import com.expstudio.pycmd.python.ServerService
import com.expstudio.pycmd.util.Workspace
import com.expstudio.pycmd.util.WorkspaceEntry
import java.io.File
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Which of the five tabs is showing. */
enum class Tab(val label: String) {
    CONSOLE("Console"),
    EDITOR("Editor"),
    FILES("Files"),
    PACKAGES("Packages"),
    SERVERS("Servers"),
}

data class EditorState(
    val file: File? = null,
    val content: String = DEFAULT_SNIPPET,
    val savedContent: String = DEFAULT_SNIPPET,
    val line: Int = 1,
    val column: Int = 1,
    /**
     * Bumped whenever a different document is loaded. The editor WebView keys
     * off this to know when to replace its buffer - the file path alone cannot
     * tell "new untitled" from "still untitled".
     */
    val epoch: Long = 0,
) {
    val fileName: String get() = file?.name ?: "untitled.py"
    val isDirty: Boolean get() = content != savedContent
}

data class FilesState(
    val directory: File? = null,
    val entries: List<WorkspaceEntry> = emptyList(),
    val loading: Boolean = true,
)

data class PackagesState(
    val installed: List<InstalledPackage> = emptyList(),
    val bundled: List<String> = emptyList(),
    val busy: Boolean = false,
    val progress: String = "",
)

data class ServersState(
    val servers: List<RunningServer> = emptyList(),
    val localIp: String = "",
    val busy: Boolean = false,
)

/** A transient message shown in the snackbar. */
data class Toast(val text: String, val id: Long)

private const val DEFAULT_SNIPPET = """# Welcome to PyCmd.
# Write Python here, then press Run. Output lands in the Console tab.

import sys


def main() -> None:
    print("Hello from PyCmd")
    print("Running Python", sys.version.split()[0])


if __name__ == "__main__":
    main()
"""

class MainViewModel(application: Application) : AndroidViewModel(application) {

    private val workspace = Workspace(application)
    private val engine = PythonEngine

    val engineStatus: StateFlow<EngineStatus> = engine.status
    val output: SharedFlow<OutputChunk> = engine.output
    val serverCount: StateFlow<Int> = engine.serverCount

    private val _tab = MutableStateFlow(Tab.CONSOLE)
    val tab: StateFlow<Tab> = _tab.asStateFlow()

    private val _editor = MutableStateFlow(EditorState())
    val editor: StateFlow<EditorState> = _editor.asStateFlow()

    private val _files = MutableStateFlow(FilesState())
    val files: StateFlow<FilesState> = _files.asStateFlow()

    private val _packages = MutableStateFlow(PackagesState())
    val packages: StateFlow<PackagesState> = _packages.asStateFlow()

    private val _servers = MutableStateFlow(ServersState())
    val servers: StateFlow<ServersState> = _servers.asStateFlow()

    private val _toast = MutableStateFlow<Toast?>(null)
    val toast: StateFlow<Toast?> = _toast.asStateFlow()

    private val _history = MutableStateFlow<List<String>>(emptyList())
    val history: StateFlow<List<String>> = _history.asStateFlow()

    val workspaceRoot: File get() = workspace.root

    /** Path shown in the UI, relative to the workspace root. */
    fun relativePath(file: File): String = workspace.relativePath(file)

    init {
        viewModelScope.launch {
            workspace.seedExamples()
            _files.value = FilesState(directory = workspace.root, loading = true)
            engine.start(getApplication())
            refreshFiles(workspace.root)
            refreshPackages()
            refreshServers()
        }
    }

    // ------------------------------------------------------------------ toasts

    fun showToast(text: String) {
        _toast.value = Toast(text, System.currentTimeMillis())
    }

    fun consumeToast() {
        _toast.value = null
    }

    fun selectTab(tab: Tab) {
        _tab.value = tab
        when (tab) {
            Tab.FILES -> refreshFiles(_files.value.directory ?: workspace.root)
            Tab.PACKAGES -> refreshPackages()
            Tab.SERVERS -> refreshServers()
            else -> Unit
        }
    }

    // ----------------------------------------------------------------- console

    fun runConsole(source: String) {
        val trimmed = source.trim()
        if (trimmed.isEmpty()) return
        rememberHistory(trimmed)
        viewModelScope.launch {
            engine.echo(trimmed + "\n", OutputChunk.Stream.INPUT)
            engine.run(trimmed)
            refreshServers()
        }
    }

    fun submitStdin(line: String) = engine.submitInput(line)

    fun stopExecution() {
        engine.requestStop()
        showToast("Stopping...")
    }

    fun clearNamespace() {
        viewModelScope.launch { engine.resetNamespace() }
    }

    private fun rememberHistory(entry: String) {
        val current = _history.value.filterNot { it == entry }
        _history.value = (listOf(entry) + current).take(60)
    }

    suspend fun completionsFor(prefix: String): List<String> = engine.completions(prefix)

    suspend fun runtimeInfo(): Map<String, String> = engine.runtimeInfo()

    // ------------------------------------------------------------------ editor

    fun onEditorContentChanged(content: String) {
        _editor.value = _editor.value.copy(content = content)
    }

    fun onCursorMoved(line: Int, column: Int) {
        _editor.value = _editor.value.copy(line = line, column = column)
    }

    fun newFile() {
        _editor.value = EditorState(file = null, content = "", savedContent = "", epoch = nextEpoch())
        _tab.value = Tab.EDITOR
    }

    private var epochCounter = 0L

    private fun nextEpoch(): Long = ++epochCounter

    fun openInEditor(file: File) {
        viewModelScope.launch {
            workspace.read(file)
                .onSuccess { text ->
                    _editor.value = EditorState(
                        file = file,
                        content = text,
                        savedContent = text,
                        epoch = nextEpoch(),
                    )
                    _tab.value = Tab.EDITOR
                }
                .onFailure { showToast(it.message ?: "Could not open the file.") }
        }
    }

    /** Saves the open buffer, asking for a name first if it has never been saved. */
    fun saveEditor(nameIfUntitled: String? = null, onSaved: (File) -> Unit = {}) {
        val state = _editor.value
        val target = state.file ?: run {
            val name = nameIfUntitled?.trim().orEmpty().ifEmpty { "untitled.py" }
            File(_files.value.directory ?: workspace.root, if (name.endsWith(".py")) name else "$name.py")
        }
        viewModelScope.launch {
            workspace.write(target, state.content)
                .onSuccess {
                    _editor.value = state.copy(file = target, savedContent = state.content)
                    showToast("Saved ${target.name}")
                    refreshFiles(_files.value.directory ?: workspace.root)
                    onSaved(target)
                }
                .onFailure { showToast(it.message ?: "Could not save.") }
        }
    }

    /** Saves first when needed, then runs the buffer as a real file. */
    fun runEditor() {
        val state = _editor.value
        _tab.value = Tab.CONSOLE
        viewModelScope.launch {
            val file = state.file
            if (file != null && state.isDirty) {
                workspace.write(file, state.content).onFailure {
                    showToast(it.message ?: "Could not save before running.")
                    return@launch
                }
                _editor.value = _editor.value.copy(savedContent = state.content)
            }
            engine.echo("\n", OutputChunk.Stream.SYSTEM)
            if (file != null) {
                engine.echo("Running ${file.name}\n", OutputChunk.Stream.SYSTEM)
                engine.runFile(file.absolutePath)
            } else {
                engine.echo("Running untitled buffer\n", OutputChunk.Stream.SYSTEM)
                engine.run(state.content, sourceName = "untitled.py", echoResult = false)
            }
            refreshServers()
            refreshFiles(_files.value.directory ?: workspace.root)
        }
    }

    // ------------------------------------------------------------------- files

    fun refreshFiles(directory: File) {
        viewModelScope.launch {
            _files.value = _files.value.copy(directory = directory, loading = true)
            val entries = workspace.list(directory)
            _files.value = FilesState(directory = directory, entries = entries, loading = false)
        }
    }

    fun openDirectory(directory: File) = refreshFiles(directory)

    fun navigateUp(): Boolean {
        val current = _files.value.directory ?: return false
        if (current.absolutePath == workspace.root.absolutePath) return false
        val parent = current.parentFile ?: return false
        refreshFiles(parent)
        return true
    }

    fun createFile(name: String) {
        val directory = _files.value.directory ?: workspace.root
        viewModelScope.launch {
            val fileName = if (name.endsWith(".py") || name.contains('.')) name else "$name.py"
            workspace.createFile(directory, fileName)
                .onSuccess {
                    refreshFiles(directory)
                    showToast("Created ${it.name}")
                    openInEditor(it)
                }
                .onFailure { showToast(it.message ?: "Could not create the file.") }
        }
    }

    fun createFolder(name: String) {
        val directory = _files.value.directory ?: workspace.root
        viewModelScope.launch {
            workspace.createFolder(directory, name)
                .onSuccess {
                    refreshFiles(directory)
                    showToast("Created ${it.name}/")
                }
                .onFailure { showToast(it.message ?: "Could not create the folder.") }
        }
    }

    fun renameEntry(file: File, newName: String) {
        val directory = _files.value.directory ?: workspace.root
        viewModelScope.launch {
            workspace.rename(file, newName)
                .onSuccess { renamed ->
                    if (_editor.value.file?.absolutePath == file.absolutePath) {
                        _editor.value = _editor.value.copy(file = renamed)
                    }
                    refreshFiles(directory)
                    showToast("Renamed to ${renamed.name}")
                }
                .onFailure { showToast(it.message ?: "Could not rename.") }
        }
    }

    fun deleteEntry(file: File) {
        val directory = _files.value.directory ?: workspace.root
        viewModelScope.launch {
            workspace.delete(file)
                .onSuccess {
                    if (_editor.value.file?.absolutePath == file.absolutePath) {
                        _editor.value = EditorState(
                            file = null,
                            content = "",
                            savedContent = "",
                            epoch = nextEpoch(),
                        )
                    }
                    refreshFiles(directory)
                    showToast("Deleted ${file.name}")
                }
                .onFailure { showToast(it.message ?: "Could not delete.") }
        }
    }

    fun importFile(uri: Uri) {
        val directory = _files.value.directory ?: workspace.root
        viewModelScope.launch {
            workspace.importFrom(uri, directory)
                .onSuccess {
                    refreshFiles(directory)
                    showToast("Imported ${it.name}")
                }
                .onFailure { showToast(it.message ?: "Could not import that file.") }
        }
    }

    fun runFile(file: File) {
        _tab.value = Tab.CONSOLE
        viewModelScope.launch {
            engine.echo("\nRunning ${file.name}\n", OutputChunk.Stream.SYSTEM)
            engine.runFile(file.absolutePath)
            refreshServers()
        }
    }

    // ---------------------------------------------------------------- packages

    fun refreshPackages() {
        viewModelScope.launch {
            _packages.value = _packages.value.copy(
                installed = engine.installedPackages(),
                bundled = engine.bundledPackages(),
            )
        }
    }

    fun installPackage(name: String, version: String?) {
        if (name.isBlank()) {
            showToast("Enter a package name.")
            return
        }
        viewModelScope.launch {
            _packages.value = _packages.value.copy(busy = true, progress = "Resolving...")
            val result = engine.installPackage(name.trim(), version) { message ->
                _packages.value = _packages.value.copy(progress = message)
            }
            _packages.value = _packages.value.copy(busy = false, progress = "")
            if (result.ok) {
                showToast("Installed ${result.name} ${result.version}")
                refreshPackages()
            } else {
                showToast(result.error.ifBlank { "Install failed." })
            }
        }
    }

    fun uninstallPackage(name: String) {
        viewModelScope.launch {
            _packages.value = _packages.value.copy(busy = true, progress = "Removing $name...")
            val result = engine.uninstallPackage(name)
            _packages.value = _packages.value.copy(busy = false, progress = "")
            if (result.ok) {
                showToast("Removed $name")
                refreshPackages()
            } else {
                showToast(result.error.ifBlank { "Could not remove $name." })
            }
        }
    }

    // ----------------------------------------------------------------- servers

    fun refreshServers() {
        viewModelScope.launch {
            val list = engine.listServers()
            _servers.value = _servers.value.copy(servers = list, localIp = engine.localIp())
            syncForegroundService(list)
        }
    }

    fun startFileServer(port: Int) {
        val directory = _files.value.directory ?: workspace.root
        viewModelScope.launch {
            _servers.value = _servers.value.copy(busy = true)
            val result = engine.startFileServer(directory.absolutePath, port)
            _servers.value = _servers.value.copy(busy = false)
            if (result.ok) showToast("Serving on ${result.url}") else showToast(result.error)
            refreshServers()
        }
    }

    fun startScriptServer(file: File, port: Int) {
        viewModelScope.launch {
            _servers.value = _servers.value.copy(busy = true)
            val result = engine.startScriptServer(file.absolutePath, port, file.name)
            _servers.value = _servers.value.copy(busy = false)
            if (result.ok) showToast("Started ${file.name}") else showToast(result.error)
            refreshServers()
        }
    }

    fun stopServer(handle: String) {
        viewModelScope.launch {
            val result = engine.stopServer(handle)
            if (!result.ok) showToast(result.error)
            refreshServers()
        }
    }

    fun stopAllServers() {
        viewModelScope.launch {
            val stopped = engine.stopAllServers()
            showToast(if (stopped > 0) "Stopped $stopped server(s)" else "Nothing was running")
            refreshServers()
        }
    }

    /** Last summary handed to the service, so an unchanged state is left alone. */
    private var serviceSummary: String? = null

    /**
     * The notification exists exactly while something is listening.
     *
     * refreshServers() runs often, so this only touches the service when the
     * state it would show actually changed.
     */
    private fun syncForegroundService(list: List<RunningServer>) {
        val running = list.count { it.status == "running" }
        val context = getApplication<Application>()
        if (running > 0) {
            val summary = if (running == 1) {
                list.firstOrNull { it.status == "running" }?.let { server ->
                    if (server.url.isNotBlank()) "${server.label} - ${server.url}" else server.label
                } ?: "1 server running"
            } else {
                "$running servers running"
            }
            if (summary != serviceSummary) {
                serviceSummary = summary
                ServerService.start(context, summary)
            }
        } else if (serviceSummary != null) {
            serviceSummary = null
            ServerService.stop(context)
        }
    }
}
