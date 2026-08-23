package com.expstudio.pycmd.ui

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.expstudio.pycmd.python.CONSOLE_CHANNEL
import com.expstudio.pycmd.python.EngineStatus
import com.expstudio.pycmd.python.InstalledPackage
import com.expstudio.pycmd.python.OutputChunk
import com.expstudio.pycmd.python.PythonEngine
import com.expstudio.pycmd.python.RunningServer
import com.expstudio.pycmd.python.ServerService
import com.expstudio.pycmd.util.DebugLog
import com.expstudio.pycmd.util.LogEntry
import com.expstudio.pycmd.util.Workspace
import com.expstudio.pycmd.util.WorkspaceEntry
import java.io.File
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Which screen is showing. DEBUG is reached from the top bar, not the tab row. */
enum class Tab(val label: String) {
    CONSOLE("Console"),
    EDITOR("Editor"),
    FILES("Files"),
    PACKAGES("Packages"),
    SERVERS("Servers"),
    DEBUG("Debug"),
}

/** What a launch form is set up to start. */
enum class ServerKind(val label: String) {
    STATIC("Serve a folder"),
    SCRIPT("Run a script"),
}

/**
 * The Servers tab's launch form.
 *
 * Held in the ViewModel rather than the composable so a half-filled form
 * survives a trip to the Files tab to pick a target.
 */
data class LaunchForm(
    val kind: ServerKind = ServerKind.STATIC,
    val folder: File? = null,
    val script: File? = null,
    val port: String = "8000",
    val label: String = "",
    val exposeToNetwork: Boolean = true,
    val logRequests: Boolean = true,
) {
    val target: File? get() = if (kind == ServerKind.STATIC) folder else script

    val portNumber: Int? get() = port.trim().toIntOrNull()

    /** Why the Run button is disabled, or null when it is ready to go. */
    fun problem(): String? = when {
        target == null -> if (kind == ServerKind.STATIC) "Pick a folder to serve." else "Pick a script to run."
        port.isNotBlank() && portNumber == null -> "Port must be a number."
        portNumber != null && portNumber !in 1..65535 -> "Port must be between 1 and 65535."
        kind == ServerKind.STATIC && portNumber == null -> "A folder server needs a port."
        else -> null
    }
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
    val form: LaunchForm = LaunchForm(),
    /** Handle of the server whose console is open, or null for the list. */
    val openConsole: String? = null,
) {
    val running: Int get() = servers.count { it.isRunning }
}

/** A transient message shown in the snackbar. */
data class Toast(val text: String, val id: Long)

/** How many lines each server console keeps. */
private const val CONSOLE_LIMIT = 1500

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

    /** Output per server channel, so each server console has its own scrollback. */
    private val _serverConsoles = MutableStateFlow<Map<String, List<OutputChunk>>>(emptyMap())
    val serverConsoles: StateFlow<Map<String, List<OutputChunk>>> = _serverConsoles.asStateFlow()

    val awaitingInput: StateFlow<Set<String>> = engine.awaitingInput

    val debugEntries: StateFlow<List<LogEntry>> = DebugLog.entries
    val debugErrorCount: StateFlow<Int> = DebugLog.errorCount

    val workspaceRoot: File get() = workspace.root

    /** Path shown in the UI, relative to the workspace root. */
    fun relativePath(file: File): String = workspace.relativePath(file)

    init {
        // Everything a server prints is tagged with its handle; the console
        // ignores those and each server console keeps only its own.
        viewModelScope.launch {
            engine.output.collect { chunk ->
                if (chunk.channel == CONSOLE_CHANNEL) return@collect
                val current = _serverConsoles.value[chunk.channel].orEmpty()
                val updated = (current + chunk).takeLast(CONSOLE_LIMIT)
                _serverConsoles.value = _serverConsoles.value + (chunk.channel to updated)
            }
        }

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

    /** Saves the buffer if needed, then hands it to the Servers tab as a script. */
    fun runEditorAsServer() {
        val state = _editor.value
        val file = state.file
        if (file == null) {
            showToast("Save the file first, then run it as a server.")
            return
        }
        viewModelScope.launch {
            if (state.isDirty) {
                workspace.write(file, state.content).onFailure {
                    showToast(it.message ?: "Could not save before running.")
                    return@launch
                }
                _editor.value = _editor.value.copy(savedContent = state.content)
            }
            updateLaunchForm { it.copy(kind = ServerKind.SCRIPT, script = file) }
            _tab.value = Tab.SERVERS
            showToast("Set as the script to run - check the port, then press Run")
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

    fun updateLaunchForm(transform: (LaunchForm) -> LaunchForm) {
        _servers.value = _servers.value.copy(form = transform(_servers.value.form))
    }

    /** Fills the form's port with the first one actually free. */
    fun suggestPort() {
        viewModelScope.launch {
            val from = _servers.value.form.portNumber ?: 8000
            val free = engine.suggestPort(from)
            updateLaunchForm { it.copy(port = free.toString()) }
            if (free != from) showToast("Port $from is taken; using $free")
        }
    }

    /** Sends the user to Files to choose the folder or script to launch. */
    fun pickLaunchTarget() {
        _pickingFor.value = _servers.value.form.kind
        _tab.value = Tab.FILES
        showToast(
            if (_servers.value.form.kind == ServerKind.STATIC) {
                "Open the folder to serve, then tap Use this folder"
            } else {
                "Tap the script to run"
            },
        )
    }

    private val _pickingFor = MutableStateFlow<ServerKind?>(null)
    val pickingFor: StateFlow<ServerKind?> = _pickingFor.asStateFlow()

    fun cancelPicking() {
        _pickingFor.value = null
    }

    /** Called from Files when the user confirms a target for the launch form. */
    fun useAsLaunchTarget(file: File) {
        val kind = _pickingFor.value ?: return
        _pickingFor.value = null
        updateLaunchForm { form ->
            if (kind == ServerKind.STATIC) {
                form.copy(kind = ServerKind.STATIC, folder = file)
            } else {
                form.copy(kind = ServerKind.SCRIPT, script = file)
            }
        }
        _tab.value = Tab.SERVERS
        showToast("Selected ${file.name}")
    }

    fun launchServer() {
        val form = _servers.value.form
        val problem = form.problem()
        if (problem != null) {
            showToast(problem)
            return
        }
        val target = form.target ?: return
        val host = if (form.exposeToNetwork) "0.0.0.0" else "127.0.0.1"
        val port = form.portNumber ?: 0

        viewModelScope.launch {
            _servers.value = _servers.value.copy(busy = true)
            val result = when (form.kind) {
                ServerKind.STATIC -> engine.startStaticServer(
                    directory = target.absolutePath,
                    port = port,
                    host = host,
                    label = form.label.trim(),
                    logRequests = form.logRequests,
                )

                ServerKind.SCRIPT -> engine.startScriptServer(
                    path = target.absolutePath,
                    port = port,
                    host = host,
                    label = form.label.trim(),
                )
            }
            _servers.value = _servers.value.copy(busy = false)
            if (result.ok) {
                showToast(if (result.url.isNotBlank()) "Started - ${result.url}" else "Started ${target.name}")
                // Drop straight into the new server's console: that is where
                // its output and any startup failure will show up.
                _servers.value = _servers.value.copy(openConsole = result.handle.ifBlank { null })
            } else {
                showToast(result.error.ifBlank { "Could not start." })
            }
            refreshServers()
        }
    }

    fun openServerConsole(handle: String) {
        _servers.value = _servers.value.copy(openConsole = handle)
        if (_serverConsoles.value[handle].isNullOrEmpty()) {
            // Only as a safety net. The live collector has been capturing this
            // channel since the process started, and for a script server it
            // holds more than Python's own log does - a script's print() goes
            // straight through the output sink and never reaches that log - so
            // replaying over a populated buffer would lose output, not restore it.
            viewModelScope.launch {
                val existing = engine.serverLog(handle)
                if (existing.isNotEmpty() && _serverConsoles.value[handle].isNullOrEmpty()) {
                    _serverConsoles.value =
                        _serverConsoles.value + (handle to existing.takeLast(CONSOLE_LIMIT))
                }
            }
        }
    }

    fun closeServerConsole() {
        _servers.value = _servers.value.copy(openConsole = null)
    }

    fun submitServerInput(handle: String, line: String) {
        engine.submitInput(line, handle)
    }

    fun clearServerConsole(handle: String) {
        _serverConsoles.value = _serverConsoles.value + (handle to emptyList())
    }

    fun stopServer(handle: String) {
        viewModelScope.launch {
            val result = engine.stopServer(handle)
            if (!result.ok) {
                showToast(
                    if (result.needsKill) {
                        "It would not stop. Use Kill to force it."
                    } else {
                        result.error.ifBlank { "Could not stop." }
                    },
                )
            } else {
                showToast("Stopped")
            }
            refreshServers()
        }
    }

    fun killServer(handle: String) {
        viewModelScope.launch {
            val result = engine.killServer(handle)
            when {
                !result.ok -> showToast(result.error.ifBlank { "Could not kill." })
                result.detached -> showToast("Killed. The port is free; the thread is finishing a blocking call.")
                else -> showToast("Killed")
            }
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

    fun killAllServers() {
        viewModelScope.launch {
            val killed = engine.killAllServers()
            showToast(if (killed > 0) "Killed $killed server(s)" else "Nothing was running")
            refreshServers()
        }
    }

    // ------------------------------------------------------------------- debug

    fun clearDebugLog() {
        DebugLog.clear()
        DebugLog.info("debug", "log cleared")
    }

    fun debugLogText(): String = DebugLog.exportText()

    /** Writes the debug log into the workspace so it can be shared or kept. */
    fun saveDebugLog() {
        viewModelScope.launch {
            val name = "debug-" + System.currentTimeMillis() + ".log"
            val target = File(workspace.root, name)
            workspace.write(target, DebugLog.exportText())
                .onSuccess {
                    showToast("Saved $name to the workspace")
                    refreshFiles(_files.value.directory ?: workspace.root)
                }
                .onFailure { showToast(it.message ?: "Could not save the log.") }
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
