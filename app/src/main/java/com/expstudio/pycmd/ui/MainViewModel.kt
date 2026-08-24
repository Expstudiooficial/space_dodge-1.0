package com.expstudio.pycmd.ui

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.expstudio.pycmd.python.CONSOLE_CHANNEL
import com.expstudio.pycmd.python.EngineStatus
import com.expstudio.pycmd.python.DownloadedFile
import com.expstudio.pycmd.python.InstalledPackage
import com.expstudio.pycmd.python.LanguageInfo
import com.expstudio.pycmd.python.OutputChunk
import com.expstudio.pycmd.python.PreviewPage
import com.expstudio.pycmd.python.forFileName
import com.expstudio.pycmd.python.PythonEngine
import com.expstudio.pycmd.python.RunningServer
import com.expstudio.pycmd.python.ServerService
import com.expstudio.pycmd.plugins.CustomPlugins
import com.expstudio.pycmd.plugins.InstalledPlugin
import com.expstudio.pycmd.plugins.PluginIds
import com.expstudio.pycmd.plugins.PluginScreen
import com.expstudio.pycmd.plugins.PluginSpec
import com.expstudio.pycmd.plugins.Plugins
import com.expstudio.pycmd.util.DebugLog
import com.expstudio.pycmd.util.LogEntry
import com.expstudio.pycmd.util.Imports
import com.expstudio.pycmd.util.Workspace
import com.expstudio.pycmd.util.WorkspaceEntry
import java.io.File
import org.json.JSONObject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Which screen is showing.
 *
 * Only the first five are in the bottom bar - seven destinations wrap their
 * labels onto two lines on a phone - so Packages, Downloads and Plugins live
 * behind More, and Debug stays in the top bar where it is reachable from
 * anywhere.
 */
enum class Tab(val label: String) {
    CONSOLE("Console"),
    EDITOR("Editor"),
    FILES("Files"),
    SERVERS("Servers"),
    MORE("More"),
    PACKAGES("Packages"),
    DOWNLOADS("Downloads"),
    PLUGINS("Plugins"),
    DEBUG("Debug"),
    TOOL("Tool"),
    PLUGIN_PANEL("Plugin"),
}

/** The five destinations in the bottom bar; the rest live behind More. */
val BOTTOM_TABS = listOf(Tab.CONSOLE, Tab.EDITOR, Tab.FILES, Tab.SERVERS, Tab.MORE)

data class DownloadsState(
    val files: List<DownloadedFile> = emptyList(),
    val busy: Boolean = false,
    val progress: String = "",
)

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

/** Log tag for the view model's own messages. */
private const val TAG_VIEW = "ui"

/** How long typing has to stop before Autosave writes the file. */
private const val AUTOSAVE_DELAY_MS = 2000L

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

    private val _downloads = MutableStateFlow(DownloadsState())
    val downloads: StateFlow<DownloadsState> = _downloads.asStateFlow()

    val pluginsEnabled: StateFlow<Set<String>> = Plugins.enabled

    /** Extensions the preview can show, which is wider than what can run. */
    private val _previewable = MutableStateFlow<Set<String>>(emptySet())
    val previewable: StateFlow<Set<String>> = _previewable.asStateFlow()

    private val _languages = MutableStateFlow<List<LanguageInfo>>(emptyList())
    val languages: StateFlow<List<LanguageInfo>> = _languages.asStateFlow()

    private val _servers = MutableStateFlow(ServersState())
    val servers: StateFlow<ServersState> = _servers.asStateFlow()

    /** Plugins the user installed themselves, and which of them are on. */
    val customPlugins: StateFlow<List<InstalledPlugin>> = CustomPlugins.installed
    val customPluginsEnabled: StateFlow<Set<String>> = CustomPlugins.enabled

    private val _pluginBusy = MutableStateFlow("")
    val pluginBusy: StateFlow<String> = _pluginBusy.asStateFlow()

    /** The custom plugin whose panel is open, if any. */
    private val _openPanel = MutableStateFlow<InstalledPlugin?>(null)
    val openPanel: StateFlow<InstalledPlugin?> = _openPanel.asStateFlow()

    /** Commands the loaded plugins have registered, by name. */
    private val _pluginCommands = MutableStateFlow<Map<String, String>>(emptyMap())
    val pluginCommands: StateFlow<Map<String, String>> = _pluginCommands.asStateFlow()

    /** The page shown by the preview overlay, when one is open. */
    private val _preview = MutableStateFlow<PreviewPage?>(null)
    val preview: StateFlow<PreviewPage?> = _preview.asStateFlow()

    /** Which plugin tool is open, if any. */
    private val _activeTool = MutableStateFlow<PluginScreen?>(null)
    val activeTool: StateFlow<PluginScreen?> = _activeTool.asStateFlow()

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
            refreshDownloads()
            refreshLanguages()
            _previewable.value = engine.previewableExtensions()
            refreshCustomPlugins()
        }
    }

    // --------------------------------------------------------------- plugins

    fun setPluginEnabled(id: String, on: Boolean) {
        Plugins.setEnabled(id, on)
        // Polyglot Files decides which file types exist, so the catalogue has
        // to follow it rather than be read once at startup.
        if (id == PluginIds.POLYGLOT_FILES || id == PluginIds.POWER_PACK) refreshLanguages()
    }

    fun enableAllPlugins() {
        Plugins.enableAll()
        refreshLanguages()
        showToast("Every plugin is on")
    }

    fun resetPlugins() {
        Plugins.resetToDefaults()
        refreshLanguages()
        showToast("Plugins reset")
    }

    fun isPluginOn(id: String): Boolean = Plugins.isOn(id)

    // ------------------------------------------------------- custom plugins

    /** Re-reads what is on disk, then loads whatever is switched on. */
    /**
     * Tells every loaded plugin that something happened.
     *
     * Fire-and-forget on purpose: a plugin that is slow, or broken, must not
     * make saving a file feel slow or fail. Errors are caught on the Python
     * side and reported against the plugin that caused them.
     */
    private fun firePlugins(event: String, payload: JSONObject = JSONObject()) {
        if (CustomPlugins.enabled.value.isEmpty()) return
        viewModelScope.launch { engine.firePluginEvent(event, payload.toString()) }
    }

    fun refreshCustomPlugins(reload: Boolean = true) {
        viewModelScope.launch {
            val reply = engine.listPlugins()
            if (!reply.optBoolean("ok")) {
                DebugLog.warn(TAG_VIEW, "could not list plugins", reply.optString("error"))
                return@launch
            }
            val rows = reply.optJSONArray("plugins") ?: return@launch
            val parsed = (0 until rows.length()).mapNotNull { index ->
                rows.optJSONObject(index)?.let(InstalledPlugin::from)
            }
            CustomPlugins.setInstalled(parsed)
            if (reload) loadEnabledPlugins()
        }
    }

    private suspend fun loadEnabledPlugins() {
        val wanted = CustomPlugins.enabled.value
        engine.loadPlugins(wanted)
        val commands = engine.pluginCommands()
        val rows = commands.optJSONArray("commands")
        val table = mutableMapOf<String, String>()
        if (rows != null) {
            for (index in 0 until rows.length()) {
                val row = rows.optJSONObject(index) ?: continue
                table[row.optString("name")] = row.optString("help")
            }
        }
        _pluginCommands.value = table
        // The listing carries a loaded flag and any load error, so it has to
        // be read back after loading rather than before.
        val reply = engine.listPlugins()
        val listed = reply.optJSONArray("plugins")
        if (listed != null) {
            CustomPlugins.setInstalled(
                (0 until listed.length()).mapNotNull { index ->
                    listed.optJSONObject(index)?.let(InstalledPlugin::from)
                },
            )
        }
    }

    fun setCustomPluginEnabled(id: String, on: Boolean) {
        CustomPlugins.setEnabled(id, on)
        viewModelScope.launch {
            loadEnabledPlugins()
            val plugin = CustomPlugins.installed.value.firstOrNull { it.id == id }
            val failure = plugin?.error
            if (on && !failure.isNullOrEmpty()) {
                showToast("${plugin.name} failed to load - see the debug console")
            }
        }
    }

    /** Installs a plugin the user picked from outside the app. */
    fun installPluginFromUri(uri: Uri, isFolder: Boolean) {
        _pluginBusy.value = if (isFolder) "Copying the folder..." else "Copying the file..."
        viewModelScope.launch {
            val staged = if (isFolder) {
                Imports.stageTree(getApplication(), uri)
            } else {
                Imports.stageFile(getApplication(), uri)
            }
            staged
                .onSuccess { install(it.root.absolutePath, it.name) }
                .onFailure {
                    _pluginBusy.value = ""
                    showToast(it.message ?: "That could not be read.")
                }
        }
    }

    /** Installs a plugin that is already in the workspace. */
    fun installPluginFromWorkspace(file: File) {
        _pluginBusy.value = "Installing..."
        viewModelScope.launch { install(file.absolutePath, file.name) }
    }

    private suspend fun install(path: String, name: String) {
        _pluginBusy.value = "Installing..."
        val reply = engine.installPlugin(path, name)
        _pluginBusy.value = ""
        if (!reply.optBoolean("ok")) {
            val problem = reply.optString("error", "that is not a plugin")
            showToast(problem)
            DebugLog.warn(TAG_VIEW, "plugin install refused", "$name: $problem")
            return
        }
        val manifest = reply.optJSONObject("manifest")
        val installed = manifest?.optString("name").orEmpty().ifEmpty { name }
        showToast(
            if (reply.optBoolean("replaced")) "$installed updated" else "$installed installed",
        )
        DebugLog.info(TAG_VIEW, "installed plugin $installed", manifest?.optString("id").orEmpty())
        refreshCustomPlugins()
    }

    fun removeCustomPlugin(plugin: InstalledPlugin) {
        viewModelScope.launch {
            val reply = engine.removePlugin(plugin.id)
            if (reply.optBoolean("ok")) {
                CustomPlugins.forget(plugin.id)
                showToast("${plugin.name} removed")
                refreshCustomPlugins()
            } else {
                showToast(reply.optString("error", "could not remove that"))
            }
        }
    }

    private val _pluginCandidates = MutableStateFlow<List<File>>(emptyList())

    /** Plugins sitting in the workspace, which the system picker cannot see. */
    val pluginCandidates: StateFlow<List<File>> = _pluginCandidates.asStateFlow()

    fun refreshPluginCandidates() {
        viewModelScope.launch { _pluginCandidates.value = workspace.pluginCandidates() }
    }

    /** Shows the plugin authoring guide that ships in the APK. */
    fun openGuide(asset: String = "docs/PLUGINS.md", title: String = "PLUGINS.md") {
        viewModelScope.launch {
            val text = workspace.readAsset(asset)
            if (text == null) {
                showToast("That guide is missing from this build.")
                return@launch
            }
            _preview.value = engine.previewText(text, title)
        }
    }

    fun openPluginPanel(plugin: InstalledPlugin) {
        if (!CustomPlugins.isOn(plugin.id)) {
            showToast("${plugin.name} is switched off.")
            return
        }
        _openPanel.value = plugin
        _tab.value = Tab.PLUGIN_PANEL
    }

    fun closePluginPanel() {
        _openPanel.value = null
        _tab.value = Tab.PLUGINS
    }

    suspend fun pluginPanelHtml(id: String): String = engine.pluginPanel(id)

    suspend fun callPluginExport(id: String, name: String, payload: String): JSONObject =
        engine.callPluginExport(id, name, payload)

    fun isPluginPoweredUp(id: String): Boolean = Plugins.isPoweredUp(id)

    /** Opens a plugin's own screen. */
    fun openPlugin(spec: PluginSpec) {
        val screen = spec.screen ?: return
        if (!Plugins.isOn(spec.id)) {
            showToast("${spec.name} is off.")
            return
        }
        _activeTool.value = screen
        _tab.value = Tab.TOOL
    }

    fun closeTool() {
        _activeTool.value = null
        _tab.value = Tab.PLUGINS
    }

    /**
     * Runs a plugin tool and hands back what it said.
     *
     * The tools live in Python because that is where the batteries are, and
     * because Regex Lab has to use the same `re` module the user's script
     * will - a regex tester that disagrees with the language is worse than
     * none at all.
     */
    suspend fun runTool(name: String, arguments: JSONObject): JSONObject =
        engine.tool(name, arguments)

    /** The text of the file open in the editor, for the tools that offer it. */
    fun editorContent(): String = _editor.value.content

    fun replaceEditorContent(content: String) {
        val state = _editor.value
        if (state.file == null) {
            showToast("Open a file first.")
            return
        }
        _editor.value = state.copy(content = content, epoch = nextEpoch())
        showToast("Editor updated")
    }

    /** Opens a search hit at the right file. */
    fun openSearchHit(path: String) {
        val file = File(path)
        if (!file.exists()) {
            showToast("That file is gone.")
            return
        }
        _activeTool.value = null
        openInEditor(file)
    }

    private fun refreshLanguages() {
        viewModelScope.launch {
            _languages.value = engine.languageCatalogue(Plugins.isOn(PluginIds.POLYGLOT_FILES))
        }
    }

    // ------------------------------------------------------------- downloads

    fun refreshDownloads() {
        viewModelScope.launch {
            _downloads.value = _downloads.value.copy(files = engine.listDownloads())
        }
    }

    fun downloadUrl(url: String) {
        if (url.isBlank()) {
            showToast("Enter a URL.")
            return
        }
        viewModelScope.launch {
            _downloads.value = _downloads.value.copy(busy = true, progress = "Starting...")
            val result = engine.downloadUrl(url) { message ->
                _downloads.value = _downloads.value.copy(progress = message)
            }
            _downloads.value = _downloads.value.copy(busy = false, progress = "")
            showToast(if (result.ok) "Saved ${result.name}" else result.error.ifBlank { "Download failed." })
            refreshDownloads()
        }
    }

    fun exportWorkspace() {
        viewModelScope.launch {
            _downloads.value = _downloads.value.copy(busy = true, progress = "Zipping the workspace...")
            val result = engine.exportWorkspace()
            _downloads.value = _downloads.value.copy(busy = false, progress = "")
            showToast(
                if (result.ok) "Exported ${result.files} files to ${result.name}"
                else result.error.ifBlank { "Export failed." },
            )
            refreshDownloads()
        }
    }

    fun deleteDownload(file: DownloadedFile) {
        viewModelScope.launch {
            if (engine.deleteDownload(file.path)) {
                showToast("Deleted ${file.name}")
            } else {
                showToast("Could not delete it.")
            }
            refreshDownloads()
        }
    }

    fun copyDownloadToWorkspace(file: DownloadedFile) {
        viewModelScope.launch {
            val result = engine.copyDownloadToWorkspace(file.path)
            if (result.ok) {
                showToast("Copied to the workspace")
                refreshFiles(_files.value.directory ?: workspace.root)
            } else {
                showToast(result.error.ifBlank { "Could not copy it." })
            }
        }
    }

    /** Opens a download in the editor, copying it across first. */
    fun openDownload(file: DownloadedFile) {
        viewModelScope.launch {
            val result = engine.copyDownloadToWorkspace(file.path)
            if (!result.ok) {
                showToast(result.error.ifBlank { "Could not open it." })
                return@launch
            }
            refreshFiles(_files.value.directory ?: workspace.root)
            openInEditor(File(result.path))
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
            Tab.DOWNLOADS -> refreshDownloads()
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

            // A plugin command gets first refusal, because `todo add milk` is
            // a syntax error in Python and a sensible command everywhere else.
            // Only a bare word that a plugin actually registered qualifies, so
            // nothing a Python line can start with is ever swallowed.
            val head = trimmed.substringBefore(' ').trim()
            if (head in _pluginCommands.value && !trimmed.contains('=')) {
                val reply = engine.runPluginCommand(head, trimmed.substringAfter(' ', ""))
                if (reply.optBoolean("handled")) {
                    refreshServers()
                    return@launch
                }
            }

            engine.run(trimmed)
            engine.firePluginEvent("console_run", JSONObject().put("source", trimmed).toString())
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
        scheduleAutosave()
    }

    fun onCursorMoved(line: Int, column: Int) {
        _editor.value = _editor.value.copy(line = line, column = column)
    }

    fun newFile() {
        _editor.value = EditorState(file = null, content = "", savedContent = "", epoch = nextEpoch())
        _tab.value = Tab.EDITOR
    }

    private var epochCounter = 0L

    /** The pending autosave, cancelled and replaced on every keystroke. */
    private var autosaveJob: kotlinx.coroutines.Job? = null

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
                    firePlugins(
                        "file_opened",
                        JSONObject().put("path", file.absolutePath).put("name", file.name),
                    )
                }
                .onFailure { showToast(it.message ?: "Could not open the file.") }
        }
    }

    /** Saves the open buffer, asking for a name first if it has never been saved. */
    /**
     * Saves a couple of seconds after typing stops, when Autosave is on.
     *
     * Debounced rather than saving on every keystroke: writing a file per
     * character would spend the flash budget for nothing, and the point is
     * only to survive a phone call or a tab switch, not to save mid-word. A
     * file that has never been named is left alone - there is nowhere to put
     * it without asking.
     */
    private fun scheduleAutosave() {
        if (!Plugins.isOn(PluginIds.AUTOSAVE)) return
        val state = _editor.value
        if (state.file == null || !state.isDirty) return

        autosaveJob?.cancel()
        autosaveJob = viewModelScope.launch {
            delay(AUTOSAVE_DELAY_MS)
            val current = _editor.value
            val target = current.file ?: return@launch
            if (!current.isDirty) return@launch
            runCatching { workspace.write(target, current.content) }
                .onSuccess {
                    _editor.value = _editor.value.copy(savedContent = current.content)
                    DebugLog.debug(TAG_VIEW, "autosaved ${target.name}")
                    firePlugins(
                        "file_saved",
                        JSONObject().put("path", target.absolutePath).put("name", target.name),
                    )
                    _files.value.directory?.let { refreshFiles(it) }
                }
                .onFailure { error ->
                    DebugLog.error(TAG_VIEW, "autosave failed for ${target.name}", error)
                }
        }
    }

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
                    firePlugins(
                        "file_saved",
                        JSONObject().put("path", target.absolutePath).put("name", target.name),
                    )
                    onSaved(target)
                }
                .onFailure { showToast(it.message ?: "Could not save.") }
        }
    }

    /** Saves first when needed, then runs the buffer as a real file. */
    fun runEditor() {
        val state = _editor.value
        val previewable = state.file != null &&
            languageForName(state.file.name)?.canPreview == true

        viewModelScope.launch {
            val file = state.file
            if (file != null && state.isDirty) {
                workspace.write(file, state.content).onFailure {
                    showToast(it.message ?: "Could not save before running.")
                    return@launch
                }
                _editor.value = _editor.value.copy(savedContent = state.content)
            }
            // Save first either way: a preview reads the file from disk, so an
            // unsaved buffer would show the previous version.
            if (previewable && file != null) {
                previewFile(file)
                return@launch
            }

            _tab.value = Tab.CONSOLE
            engine.echo("\n", OutputChunk.Stream.SYSTEM)
            if (file != null) {
                engine.echo("Running ${file.name}\n", OutputChunk.Stream.SYSTEM)
                // runAny, not runFile: the editor runs whatever the file is,
                // and calling the Python runner on a .go file would try to
                // execute Go as Python.
                engine.runAny(file.absolutePath)
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

    /**
     * Copies a folder the user picked from outside into the workspace.
     *
     * Staged into the cache first and then moved, so a folder that turns out
     * to be enormous, or that fails halfway, leaves nothing behind in the
     * user's files.
     */
    fun importFolder(uri: Uri) {
        val directory = _files.value.directory ?: workspace.root
        showToast("Copying the folder...")
        viewModelScope.launch {
            Imports.stageTree(getApplication(), uri)
                .onSuccess { staged ->
                    val target = File(directory, staged.root.name)
                    val moved = runCatching {
                        staged.root.copyRecursively(target, overwrite = false)
                    }
                    staged.root.deleteRecursively()
                    if (moved.isSuccess) {
                        refreshFiles(directory)
                        showToast("Copied ${staged.files} files into ${target.name}")
                    } else {
                        showToast("Could not copy that folder in - a name is already taken.")
                    }
                }
                .onFailure { showToast(it.message ?: "That folder could not be read.") }
        }
    }

    /** The language of a file, from the catalogue already loaded. */
    fun languageForName(name: String): LanguageInfo? = _languages.value.forFileName(name)

    /**
     * Renders a previewable file.
     *
     * The base directory is handed to the WebView so a page's own stylesheet
     * and images load: a preview that shows unstyled HTML because the CSS
     * next to it could not be found is not much of a preview.
     */
    fun previewFile(file: File) {
        if (!Plugins.isOn(PluginIds.POLYGLOT_RUNNER)) {
            showToast("Turn on Polyglot Runner to preview files.")
            return
        }
        viewModelScope.launch {
            val page = engine.previewPage(file.absolutePath)
            if (page == null) {
                showToast("Could not build a preview of ${file.name}.")
                return@launch
            }
            _preview.value = page
        }
    }

    fun closePreview() {
        _preview.value = null
        // The preview server exists for the length of the preview and no
        // longer: a socket left open after the screen closes is a leak the
        // user has no way to see.
        viewModelScope.launch { engine.stopPreview() }
    }

    fun runFile(file: File) {
        // HTML, CSS, Markdown, JSON, CSV, SVG and images have nothing to
        // print; the button on those means "show me", so it opens the preview
        // rather than the console.
        val extension = file.name.substringAfterLast('.', "").lowercase()
        val previewOnly = languageForName(file.name)?.canRun != true &&
            (languageForName(file.name)?.canPreview == true || extension in _previewable.value)
        if (previewOnly) {
            previewFile(file)
            return
        }
        _tab.value = Tab.CONSOLE
        viewModelScope.launch {
            engine.echo("\n", OutputChunk.Stream.SYSTEM)
            firePlugins(
                "run_started",
                JSONObject()
                    .put("path", file.absolutePath)
                    .put("language", languageForName(file.name)?.id ?: "text"),
            )
            // runAny picks the engine from the extension: Python keeps the
            // console namespace, C, Go and Rust go through their interpreters,
            // JavaScript to the device's engine, and anything without one
            // explains itself rather than failing silently.
            val status = engine.runAny(file.absolutePath)
            firePlugins(
                "run_finished",
                JSONObject().put("path", file.absolutePath).put("status", status),
            )
            refreshServers()
        }
    }

    /** New-file creation with a starter template for the chosen type. */
    fun createFileOfType(name: String, extension: String) {
        val directory = _files.value.directory ?: workspace.root
        val fileName = if (name.contains('.') || extension.isEmpty()) name else name + extension
        viewModelScope.launch {
            workspace.createFile(directory, fileName)
                .onSuccess { created ->
                    val template = engine.templateFor(created.name)
                    if (template.isNotEmpty()) {
                        workspace.write(created, template)
                    }
                    refreshFiles(directory)
                    showToast("Created ${created.name}")
                    openInEditor(created)
                }
                .onFailure { showToast(it.message ?: "Could not create the file.") }
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
                firePlugins(
                    "server_started",
                    JSONObject()
                        .put("handle", result.handle)
                        .put("port", port)
                        .put("kind", form.kind.name.lowercase()),
                )
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
                firePlugins("server_stopped", JSONObject().put("handle", handle))
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
