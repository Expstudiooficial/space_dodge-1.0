package com.expstudio.pycmd.python

import android.content.Context
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.expstudio.pycmd.js.JsEngine
import com.expstudio.pycmd.util.DebugLog
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** The main console's channel name. Servers use their own handle. */
const val CONSOLE_CHANNEL = "console"

/** One line of console output, tagged with where it came from. */
data class OutputChunk(
    val stream: Stream,
    val text: String,
    val id: Long,
    val channel: String = CONSOLE_CHANNEL,
) {
    enum class Stream { STDOUT, STDERR, INPUT, SYSTEM }
}

/** What the console needs to know about the interpreter right now. */
data class EngineStatus(
    val ready: Boolean = false,
    val running: Boolean = false,
    val awaitingInput: Boolean = false,
    val pythonVersion: String = "",
    val startupError: String? = null,
)

/**
 * Owns the embedded CPython interpreter.
 *
 * Python runs on one dedicated thread for its whole life: CPython keeps
 * per-thread state, and Chaquopy is happiest when calls come from a consistent
 * thread. Everything the UI asks for is funnelled onto that thread, and output
 * comes back through [output].
 *
 * Stopping and killing servers deliberately do *not* use that thread. If a
 * script has wedged the interpreter, a stop request queued behind it would
 * never arrive — which is exactly when the user needs it most — so those calls
 * go through [controlDispatcher] and reach Python by taking the GIL from a
 * second thread.
 */
object PythonEngine {

    private const val TAG = "engine"
    private const val OUTPUT_BUFFER = 512

    /** Log tag for anything a custom plugin does. */
    private const val TAG_PLUGIN = "plugin"

    /** Files the device's own JavaScript engine runs, rather than Python. */
    private val JS_EXTENSIONS = setOf("js", "mjs", "cjs")

    /** The single thread every ordinary Python call runs on. */
    private val pythonExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "python-main").apply { isDaemon = true }
    }
    private val pythonDispatcher = pythonExecutor.asCoroutineDispatcher()

    /**
     * Control operations — stop, kill, listing — that must not queue behind the
     * code they are trying to control, nor block the UI thread waiting for the
     * GIL.
     */
    private val controlExecutor = Executors.newFixedThreadPool(2) { runnable ->
        Thread(runnable, "python-control").apply { isDaemon = true }
    }
    private val controlDispatcher = controlExecutor.asCoroutineDispatcher()

    private val _output = MutableSharedFlow<OutputChunk>(
        replay = OUTPUT_BUFFER,
        extraBufferCapacity = OUTPUT_BUFFER,
        // A script that floods stdout must not stall the interpreter thread
        // waiting for the UI: the oldest output scrolls away instead, which is
        // what a terminal does anyway.
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val output: SharedFlow<OutputChunk> = _output.asSharedFlow()

    private val _status = MutableStateFlow(EngineStatus())
    val status: StateFlow<EngineStatus> = _status.asStateFlow()

    private val _serverCount = MutableStateFlow(0)
    val serverCount: StateFlow<Int> = _serverCount.asStateFlow()

    /** Channels currently blocked inside `input()`. */
    private val _awaitingInput = MutableStateFlow<Set<String>>(emptySet())
    val awaitingInput: StateFlow<Set<String>> = _awaitingInput.asStateFlow()

    /** Hand-off between each channel's input box and its `input()` call. */
    private val stdinQueues = ConcurrentHashMap<String, LinkedBlockingQueue<String>>()
    private val cancelledChannels = ConcurrentHashMap<String, Boolean>()
    private val chunkId = AtomicLong(0)

    /** Groups stderr fragments arriving in quick succession into one entry. */
    private const val STDERR_COALESCE_MS = 180L
    private val stderrLock = Any()
    private val stderrBuffers = HashMap<String, StringBuilder>()
    private val stderrFlushes = HashMap<String, ScheduledFuture<*>>()
    private val stderrFlusher = Executors.newSingleThreadScheduledExecutor { runnable ->
        Thread(runnable, "python-stderr").apply { isDaemon = true }
    }

    private lateinit var runtime: PyObject
    private lateinit var packages: PyObject
    private lateinit var servers: PyObject
    private lateinit var downloads: PyObject
    private lateinit var tools: PyObject
    private lateinit var preview: PyObject
    private lateinit var pluginRuntime: PyObject

    private lateinit var appContext: Context
    private lateinit var workspaceDir: File
    private lateinit var sitePackagesDir: File
    private lateinit var downloadsDir: File
    private lateinit var pluginsDir: File

    private fun queueFor(channel: String): LinkedBlockingQueue<String> =
        stdinQueues.getOrPut(channel) { LinkedBlockingQueue(64) }

    /** Receives stdout/stderr from Python and supplies stdin. Called on Python threads. */
    @Suppress("unused") // Called from pycmd_runtime.py
    private val sink = object {
        fun onOutput(stream: String, text: String, channel: String) {
            val kind = when (stream) {
                "stderr" -> OutputChunk.Stream.STDERR
                "system" -> OutputChunk.Stream.SYSTEM
                else -> OutputChunk.Stream.STDOUT
            }
            emit(kind, text, channel)
            if (kind == OutputChunk.Stream.STDERR) {
                // Tracebacks are the single most useful thing in the debug log,
                // but they can arrive one line per write. Buffer the burst so a
                // traceback becomes one entry rather than a dozen.
                bufferStderr(channel, text)
            }
        }

        fun onReadLine(channel: String): String? = readLineFor(channel)

        fun onFinished(runId: Int, status: String, millis: Int) {
            DebugLog.debug(TAG, "run $runId finished: $status in ${millis}ms")
        }
    }

    /**
     * Collects stderr into one debug entry per burst.
     *
     * `sys.stderr.write` is called once per traceback by our own runner, but
     * anything writing line by line - threading's excepthook, a third-party
     * logger - would otherwise fill the debug console with fragments and
     * inflate the error count. A short quiet period marks the end of a burst.
     */
    private fun bufferStderr(channel: String, text: String) {
        synchronized(stderrLock) {
            stderrBuffers.getOrPut(channel) { StringBuilder() }.append(text)
            stderrFlushes.remove(channel)?.cancel(false)
            stderrFlushes[channel] = stderrFlusher.schedule(
                { flushStderr(channel) },
                STDERR_COALESCE_MS,
                TimeUnit.MILLISECONDS,
            )
        }
    }

    private fun flushStderr(channel: String) {
        val text = synchronized(stderrLock) {
            stderrFlushes.remove(channel)
            stderrBuffers.remove(channel)?.toString()
        } ?: return
        val trimmed = text.trim()
        if (trimmed.isEmpty()) return
        val tag = if (channel == CONSOLE_CHANNEL) "python" else "server:$channel"
        // The first line is the headline; a traceback's body is the detail.
        val lines = trimmed.lineSequence().toList()
        if (lines.size <= 1) {
            DebugLog.error(tag, trimmed)
        } else {
            DebugLog.error(tag, lines.last().ifBlank { lines.first() }, trimmed)
        }
    }

    /**
     * Waits for one line on [channel].
     *
     * Shared by Python's `input()` and JavaScript's `readLine()`: both are the
     * same promise to the user - the console shows an input box, and whatever
     * they type comes back here - so both should queue in the same place.
     */
    private fun readLineFor(channel: String): String? {
        markAwaiting(channel, true)
        try {
            val queue = queueFor(channel)
            while (true) {
                if (cancelledChannels.remove(channel) != null) return null
                val line = queue.poll(150, TimeUnit.MILLISECONDS)
                if (line != null) return line
            }
        } catch (interrupted: InterruptedException) {
            Thread.currentThread().interrupt()
            return null
        } finally {
            markAwaiting(channel, false)
        }
    }

    private fun markAwaiting(channel: String, waiting: Boolean) {
        _awaitingInput.value = _awaitingInput.value.toMutableSet().apply {
            if (waiting) add(channel) else remove(channel)
        }
        if (channel == CONSOLE_CHANNEL) {
            _status.value = _status.value.copy(awaitingInput = waiting)
        }
    }

    /** Reports installer progress back to the UI. Called on the Python thread. */
    private class ProgressSink(private val onMessage: (String) -> Unit) {
        @Suppress("unused") // Called from pycmd_packages.py
        fun onProgress(message: String) = onMessage(message)
    }

    // ------------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------------

    /** Starts CPython. Safe to call more than once; later calls are no-ops. */
    suspend fun start(context: Context): EngineStatus = withContext(pythonDispatcher) {
        if (_status.value.ready) return@withContext _status.value

        appContext = context.applicationContext
        workspaceDir = File(appContext.filesDir, "workspace").apply { mkdirs() }
        sitePackagesDir = File(appContext.filesDir, "site-packages").apply { mkdirs() }

        val startedAt = System.currentTimeMillis()
        DebugLog.info(TAG, "starting interpreter")
        try {
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(appContext))
            }
            val python = Python.getInstance()
            runtime = python.getModule("pycmd_runtime")
            packages = python.getModule("pycmd_packages")
            servers = python.getModule("pycmd_servers")
            downloads = python.getModule("pycmd_download")
            tools = python.getModule("pycmd_tools")
            preview = python.getModule("pycmd_preview")
            pluginRuntime = python.getModule("pycmd_plugins")

            val version = runtime.callAttr(
                "configure",
                sink,
                workspaceDir.absolutePath,
                sitePackagesDir.absolutePath,
            ).toString()
            packages.callAttr("configure", sitePackagesDir.absolutePath)
            downloadsDir = File(appContext.filesDir, "downloads").apply { mkdirs() }
            downloads.callAttr("configure", downloadsDir.absolutePath, workspaceDir.absolutePath)
            pluginsDir = File(appContext.filesDir, "plugins").apply { mkdirs() }
            pluginRuntime.callAttr(
                "configure", pluginsDir.absolutePath, workspaceDir.absolutePath, pluginHost,
            )

            val short = version.trim().split(" ").firstOrNull().orEmpty()
            _status.value = EngineStatus(ready = true, pythonVersion = short)
            emit(OutputChunk.Stream.SYSTEM, "Python $short ready. Type code and press Run.\n")
            DebugLog.info(
                TAG,
                "interpreter ready in ${System.currentTimeMillis() - startedAt}ms",
                "Python $short",
            )
        } catch (error: Throwable) {
            _status.value = EngineStatus(
                ready = false,
                startupError = error.message ?: error.javaClass.simpleName,
            )
            emit(OutputChunk.Stream.STDERR, "Interpreter failed to start: ${error.message}\n")
            DebugLog.error(TAG, "interpreter failed to start", error)
        }
        _status.value
    }

    private fun emit(
        stream: OutputChunk.Stream,
        text: String,
        channel: String = CONSOLE_CHANNEL,
    ) {
        if (text.isEmpty()) return
        // emit() is reached from the Python threads and the UI thread alike.
        _output.tryEmit(OutputChunk(stream, text, chunkId.incrementAndGet(), channel))
    }

    /** Echo something into a channel without going through Python. */
    fun echo(
        text: String,
        stream: OutputChunk.Stream = OutputChunk.Stream.SYSTEM,
        channel: String = CONSOLE_CHANNEL,
    ) = emit(stream, text, channel)

    // ------------------------------------------------------------------
    // Running code
    // ------------------------------------------------------------------

    /**
     * Runs [source] and suspends until it completes.
     *
     * Because every ordinary Python call shares one thread, a second run can
     * only begin once the first has returned — which is the behaviour a console
     * wants.
     */
    suspend fun run(source: String, sourceName: String = "<console>", echoResult: Boolean = true): String {
        if (!_status.value.ready) return "error"
        cancelledChannels.remove(CONSOLE_CHANNEL)
        queueFor(CONSOLE_CHANNEL).clear()
        _status.value = _status.value.copy(running = true)
        return try {
            withContext(pythonDispatcher) {
                runtime.callAttr("run_source", source, sourceName, echoResult).toString()
            }
        } catch (error: Throwable) {
            emit(OutputChunk.Stream.STDERR, "Internal error: ${error.message}\n")
            DebugLog.error(TAG, "run failed", error)
            "error"
        } finally {
            _status.value = _status.value.copy(running = false, awaitingInput = false)
            refreshServerCount()
        }
    }

    /**
     * Runs a file with whichever engine its extension calls for.
     *
     * Python keeps the console's namespace; C goes through the interpreter
     * built into the app; anything without an engine reports why rather than
     * failing silently.
     */
    suspend fun runAny(path: String): String {
        if (!_status.value.ready) return "error"
        if (path.substringAfterLast('.', "").lowercase() in JS_EXTENSIONS) {
            return runJavaScript(path)
        }
        cancelledChannels.remove(CONSOLE_CHANNEL)
        queueFor(CONSOLE_CHANNEL).clear()
        _status.value = _status.value.copy(running = true)
        return try {
            withContext(pythonDispatcher) { runtime.callAttr("run_any", path).toString() }
        } catch (error: Throwable) {
            emit(OutputChunk.Stream.STDERR, "Internal error: ${error.message}\n")
            DebugLog.error(TAG, "run_any failed: $path", error)
            "error"
        } finally {
            _status.value = _status.value.copy(running = false, awaitingInput = false)
            refreshServerCount()
        }
    }

    /**
     * Runs a `.js` file in the device's own JavaScript engine.
     *
     * This one deliberately never reaches Python. Writing a JavaScript
     * interpreter in Python, to run on a device that already ships a complete
     * one, would be slower and less correct in every corner that matters -
     * so the file goes straight to the real engine, and its output arrives on
     * the console channel exactly as Python's does.
     */
    private suspend fun runJavaScript(path: String): String {
        val file = File(path)
        val source = try {
            file.readText()
        } catch (error: Throwable) {
            emit(OutputChunk.Stream.STDERR, "cannot open $path: ${error.message}\n")
            return "error"
        }

        cancelledChannels.remove(CONSOLE_CHANNEL)
        queueFor(CONSOLE_CHANNEL).clear()
        _status.value = _status.value.copy(running = true)
        emit(OutputChunk.Stream.SYSTEM, "Running ${file.name} as JavaScript\n")

        val host = object : JsEngine.Host {
            override fun stdout(text: String) = emit(OutputChunk.Stream.STDOUT, text)
            override fun stderr(text: String) {
                emit(OutputChunk.Stream.STDERR, text)
                bufferStderr(CONSOLE_CHANNEL, text)
            }
            override fun readLine(): String? = readLineFor(CONSOLE_CHANNEL)
        }

        val started = System.currentTimeMillis()
        return try {
            val result = JsEngine.run(appContext, source, file.name, host)
            val millis = (System.currentTimeMillis() - started).toInt()
            when {
                result.status == "stopped" -> {
                    emit(OutputChunk.Stream.STDERR, "\nJavaScript stopped\n")
                    DebugLog.debug(TAG, "javascript run stopped after ${millis}ms")
                    "stopped"
                }
                result.status != "ok" -> "error"
                result.exitCode != 0 -> {
                    emit(
                        OutputChunk.Stream.STDERR,
                        "JavaScript exited with status ${result.exitCode}\n",
                    )
                    "error"
                }
                else -> "ok"
            }
        } catch (error: Throwable) {
            emit(OutputChunk.Stream.STDERR, "Internal error: ${error.message}\n")
            DebugLog.error(TAG, "javascript run failed: $path", error)
            "error"
        } finally {
            _status.value = _status.value.copy(running = false, awaitingInput = false)
        }
    }

    /**
     * Builds the page a previewable file shows.
     *
     * HTML is passed through, Markdown is converted, and a stylesheet gets a
     * demo page - a CSS file previewed on its own would otherwise render as a
     * blank screen, which looks like a bug rather than an answer.
     */
    suspend fun previewPage(path: String): PreviewPage? = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext null
        runCatching {
            val map = preview.callAttr("serve", path).asMap()
            if (map.str("ok") != "True") {
                DebugLog.warn(TAG, "preview failed", map.str("error"))
                return@runCatching null
            }
            val served = map.str("served") == "True"
            if (!served && map.str("error").isNotEmpty()) {
                DebugLog.warn(TAG, "preview is not being served", map.str("error"))
            }
            PreviewPage(
                name = map.str("name"),
                html = map.str("html"),
                baseDirectory = map.str("base"),
                url = map.str("url"),
                served = served,
            )
        }.getOrElse {
            DebugLog.error(TAG, "preview failed: $path", it)
            null
        }
    }

    /**
     * Answers a fix the app offered after an error.
     *
     * Goes through the control dispatcher so a server whose script is wedged
     * can still be answered, and returns whether the line was consumed - a
     * server's stdin is a real thing people type into, and "yes" might have
     * been meant for the program rather than for us.
     */
    suspend fun answerFix(channel: String, text: String): JSONObject =
        withContext(controlDispatcher) {
            if (!_status.value.ready) return@withContext JSONObject().put("handled", false)
            runCatching {
                // The console's offers live in the runtime, a server's in the
                // server module, because that is where each one's output goes.
                val module = if (channel == CONSOLE_CHANNEL) runtime else servers
                val map = module.callAttr("answer_fix", channel, text).asMap()
                JSONObject()
                    .put("handled", map.str("handled") == "True")
                    .put("applied", map.str("applied") == "True")
                    .put("message", map.str("message"))
                    .put("port", map.str("port"))
            }.getOrElse {
                DebugLog.debug(TAG, "no fix was pending", it.message.orEmpty())
                JSONObject().put("handled", false)
            }
        }

    /** Every extension the preview can show, so the file list knows. */
    suspend fun previewableExtensions(): Set<String> = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext emptySet()
        runCatching {
            preview.callAttr("extensions").toString()
                .split(",")
                .map { it.trim().removePrefix(".").lowercase() }
                .filter { it.isNotEmpty() }
                .toSet()
        }.getOrDefault(emptySet())
    }

    /** Shuts the preview server down when the preview closes. */
    suspend fun stopPreview() = withContext(controlDispatcher) {
        runCatching { preview.callAttr("stop") }
        Unit
    }

    /** Renders text the app is holding - a shipped document, say - as a page. */
    suspend fun previewText(text: String, name: String): PreviewPage? =
        withContext(controlDispatcher) {
            if (!_status.value.ready) return@withContext null
            runCatching {
                // Served over the same loopback path as a file preview, so a
                // shipped guide behaves like every other page: anchors jump,
                // scrolling is the browser's own, nothing is a special case.
                val map = preview.callAttr("serve_text", text, name).asMap()
                PreviewPage(
                    name = map.str("name"),
                    html = map.str("html"),
                    baseDirectory = map.str("base"),
                    url = map.str("url"),
                    served = map.str("served") == "True",
                )
            }.getOrElse {
                DebugLog.error(TAG, "could not render $name", it)
                null
            }
        }

    /** Every file type the new-file menu offers. */
    suspend fun languageCatalogue(includeAll: Boolean): List<LanguageInfo> =
        withContext(pythonDispatcher) {
            if (!_status.value.ready) return@withContext emptyList()
            runCatching {
                runtime.callAttr("language_catalogue", includeAll).asList().map { row ->
                    val map = row.asMap()
                    LanguageInfo(
                        id = map.str("id"),
                        name = map.str("name"),
                        extension = map.str("extension"),
                        mode = map.str("mode"),
                        highlight = map.str("highlight"),
                        note = map.str("note"),
                        extensions = map.str("extensions"),
                    )
                }
            }.getOrElse {
                DebugLog.error(TAG, "language catalogue failed", it)
                emptyList()
            }
        }

    suspend fun languageFor(path: String): LanguageInfo = withContext(pythonDispatcher) {
        val fallback = LanguageInfo("text", "Plain text", ".txt", "edit", "text", "")
        if (!_status.value.ready) return@withContext fallback
        runCatching {
            val map = runtime.callAttr("language_for", path).asMap()
            LanguageInfo(
                id = map.str("id"),
                name = map.str("name"),
                extension = map.str("extension"),
                mode = map.str("mode"),
                highlight = map.str("highlight"),
                note = map.str("note"),
                extensions = map.str("extensions"),
            )
        }.getOrDefault(fallback)
    }

    /** Starter content for a new file, chosen by its name. */
    suspend fun templateFor(name: String): String = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext ""
        runCatching { runtime.callAttr("template_for", name).toString() }.getOrDefault("")
    }

    suspend fun runFile(path: String): String {
        if (!_status.value.ready) return "error"
        cancelledChannels.remove(CONSOLE_CHANNEL)
        queueFor(CONSOLE_CHANNEL).clear()
        _status.value = _status.value.copy(running = true)
        return try {
            withContext(pythonDispatcher) { runtime.callAttr("run_file", path).toString() }
        } catch (error: Throwable) {
            emit(OutputChunk.Stream.STDERR, "Internal error: ${error.message}\n")
            DebugLog.error(TAG, "run_file failed: $path", error)
            "error"
        } finally {
            _status.value = _status.value.copy(running = false, awaitingInput = false)
            refreshServerCount()
        }
    }

    /**
     * Asks the console's running code to stop.
     *
     * Never goes through [pythonDispatcher] — that thread is busy running the
     * user's code, so a queued call would never arrive.
     */
    fun requestStop() {
        cancelledChannels[CONSOLE_CHANNEL] = true
        queueFor(CONSOLE_CHANNEL).clear()
        // Harmless when no JavaScript is running, and the only thing that
        // works when some is.
        JsEngine.stop()
        if (!_status.value.ready) return
        DebugLog.info(TAG, "stop requested")
        controlExecutor.execute {
            runCatching { runtime.callAttr("request_stop") }
                .onFailure { DebugLog.warn(TAG, "stop request failed", it.stackTraceToString()) }
        }
    }

    /** Feeds a line to a waiting `input()` on the given channel. */
    fun submitInput(line: String, channel: String = CONSOLE_CHANNEL) {
        emit(OutputChunk.Stream.INPUT, line + "\n", channel)
        if (!queueFor(channel).offer(line + "\n")) {
            emit(OutputChunk.Stream.STDERR, "Input buffer is full; nothing is reading stdin.\n", channel)
        }
    }

    suspend fun resetNamespace() = withContext(pythonDispatcher) {
        runCatching { runtime.callAttr("reset_namespace") }
            .onFailure { DebugLog.error(TAG, "namespace reset failed", it) }
        emit(OutputChunk.Stream.SYSTEM, "Namespace cleared.\n")
        DebugLog.info(TAG, "namespace cleared")
    }

    suspend fun completions(prefix: String): List<String> = withContext(pythonDispatcher) {
        if (!_status.value.ready || prefix.isBlank()) return@withContext emptyList()
        runCatching {
            runtime.callAttr("completions", prefix).asList().map { it.toString() }
        }.getOrDefault(emptyList())
    }

    suspend fun runtimeInfo(): Map<String, String> = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext emptyMap()
        runCatching {
            val info = runtime.callAttr("runtime_info").asMap()
            info.entries.associate { (key, value) -> key.toString() to value.toString() }
        }.getOrDefault(emptyMap())
    }

    // ------------------------------------------------------------------
    // Packages
    // ------------------------------------------------------------------

    suspend fun installPackage(name: String, version: String?, onProgress: (String) -> Unit): PackageResult =
        withContext(pythonDispatcher) {
            if (!_status.value.ready) return@withContext PackageResult(false, error = "Interpreter is not ready.")
            DebugLog.info(TAG, "installing $name${version?.let { "==$it" } ?: ""}")
            runCatching {
                val result = packages.callAttr(
                    "install",
                    name,
                    version?.takeIf { it.isNotBlank() },
                    ProgressSink(onProgress),
                ).asMap()
                result.toPackageResult()
            }.getOrElse {
                DebugLog.error(TAG, "install of $name failed", it)
                PackageResult(false, error = it.friendlyMessage())
            }.also {
                if (!it.ok) DebugLog.warn(TAG, "install of $name failed: ${it.error}")
            }
        }

    suspend fun uninstallPackage(name: String): PackageResult = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext PackageResult(false, error = "Interpreter is not ready.")
        runCatching { packages.callAttr("uninstall", name).asMap().toPackageResult() }
            .getOrElse {
                DebugLog.error(TAG, "uninstall of $name failed", it)
                PackageResult(false, error = it.friendlyMessage())
            }
    }

    suspend fun installedPackages(): List<InstalledPackage> = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext emptyList()
        runCatching {
            packages.callAttr("installed").asList().map { row ->
                val map = row.asMap()
                InstalledPackage(
                    name = map.str("name"),
                    version = map.str("version"),
                    summary = map.str("summary"),
                    fileCount = map.str("files").toIntOrNull() ?: 0,
                )
            }
        }.getOrDefault(emptyList())
    }

    suspend fun bundledPackages(): List<String> = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext emptyList()
        runCatching { packages.callAttr("bundled").asList().map { it.toString() } }
            .getOrDefault(emptyList())
    }

    // ------------------------------------------------------------------
    // Downloads
    // ------------------------------------------------------------------

    suspend fun downloadUrl(url: String, onProgress: (String) -> Unit): DownloadResult =
        withContext(controlDispatcher) {
            if (!_status.value.ready) return@withContext DownloadResult(false, error = "Interpreter is not ready.")
            DebugLog.info(TAG, "downloading $url")
            runCatching {
                val map = downloads.callAttr("download", url, ProgressSink(onProgress)).asMap()
                DownloadResult(
                    ok = map.str("ok") == "True",
                    name = map.str("name"),
                    path = map.str("path"),
                    bytes = map.str("bytes").toLongOrNull() ?: 0L,
                    error = map.str("error"),
                )
            }.getOrElse {
                DebugLog.error(TAG, "download failed", it)
                DownloadResult(false, error = it.friendlyMessage())
            }
        }.also { if (!it.ok) DebugLog.warn(TAG, "download failed: ${it.error}") }

    suspend fun exportWorkspace(): DownloadResult = exportZip(null)

    /** Zips one folder of the workspace, or the whole thing when [folder] is null. */
    suspend fun exportZip(folder: String?): DownloadResult = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext DownloadResult(false, error = "Interpreter is not ready.")
        runCatching {
            val map = if (folder == null) {
                downloads.callAttr("export_workspace", "").asMap()
            } else {
                downloads.callAttr("export_folder", folder, "").asMap()
            }
            DownloadResult(
                ok = map.str("ok") == "True",
                name = map.str("name"),
                path = map.str("path"),
                bytes = map.str("bytes").toLongOrNull() ?: 0L,
                files = map.str("files").toIntOrNull() ?: 0,
                error = map.str("error"),
            )
        }.getOrElse {
            DebugLog.error(TAG, "export failed", it)
            DownloadResult(false, error = it.friendlyMessage())
        }
    }

    /**
     * What a custom plugin reaches when it logs, toasts, or messages its panel.
     *
     * Called from whichever thread the plugin happens to be on, so it does the
     * same thing the output sink does: hand the value to a flow and get out.
     */
    @Suppress("unused") // Called from pycmd_plugins.py
    private val pluginHost = object {
        fun onPluginLog(level: String, message: String, detail: String) {
            when (level) {
                "error" -> DebugLog.error(TAG_PLUGIN, message, detail)
                "warn" -> DebugLog.warn(TAG_PLUGIN, message, detail)
                else -> DebugLog.info(TAG_PLUGIN, message, detail)
            }
        }

        fun onToast(message: String) {
            _pluginToasts.tryEmit(message)
        }

        fun onPluginMessage(pluginId: String, body: String) {
            _pluginMessages.tryEmit(pluginId to body)
        }
    }

    private val _pluginToasts = MutableSharedFlow<String>(extraBufferCapacity = 16,
        onBufferOverflow = BufferOverflow.DROP_OLDEST)

    /** Toasts a plugin asked for. */
    val pluginToasts: SharedFlow<String> = _pluginToasts.asSharedFlow()

    private val _pluginMessages = MutableSharedFlow<Pair<String, String>>(
        extraBufferCapacity = 64, onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )

    /** Messages a plugin pushed to its own panel. */
    val pluginMessages: SharedFlow<Pair<String, String>> = _pluginMessages.asSharedFlow()

    /**
     * Installs a plugin from a file, folder or zip already on disk.
     *
     * Everything about custom plugins runs on the control dispatcher: a plugin
     * that hangs on load must not take the console's thread with it, and the
     * user needs the list to keep answering so they can switch the thing off.
     */
    suspend fun installPlugin(path: String, sourceName: String = ""): JSONObject =
        pluginCall("install", path, sourceName)

    suspend fun listPlugins(): JSONObject = pluginCall("listing")

    suspend fun removePlugin(id: String): JSONObject = pluginCall("remove", id)

    suspend fun loadPlugins(enabled: Collection<String>): JSONObject =
        withContext(controlDispatcher) {
            runCatching {
                // Sent as one string rather than a collection: Chaquopy hands
                // Kotlin's EmptyList across as an object Python cannot iterate,
                // and a comma-separated list has no such corner.
                val ids = enabled.joinToString(",")
                JSONObject(pluginRuntime.callAttr("load_all", ids).toString())
            }.getOrElse { failure("load_all", it) }
        }

    suspend fun callPluginExport(id: String, name: String, payload: String): JSONObject =
        pluginCall("call_export", id, name, payload)

    suspend fun pluginCommands(): JSONObject = pluginCall("commands")

    suspend fun runPluginCommand(name: String, argument: String): JSONObject =
        withContext(pythonDispatcher) {
            // This one does go on the interpreter thread: a command prints to
            // the console and may touch the same namespace a script does.
            runCatching {
                JSONObject(pluginRuntime.callAttr("run_command", name, argument).toString())
            }.getOrElse { failure("run_command", it) }
        }

    suspend fun firePluginEvent(event: String, payload: String = "{}"): JSONObject =
        pluginCall("fire", event, payload)

    /** Where a plugin's files live, so its panel can load its own assets. */
    fun pluginDirectory(id: String): File = File(pluginsDir, id)

    suspend fun pluginPanel(id: String): String = withContext(controlDispatcher) {
        runCatching { pluginRuntime.callAttr("panel_html", id).toString() }
            .getOrElse { error ->
                DebugLog.error(TAG_PLUGIN, "panel failed for $id", error)
                "<h2>That panel could not be built.</h2>"
            }
    }

    private suspend fun pluginCall(function: String, vararg arguments: String): JSONObject =
        withContext(controlDispatcher) {
            if (!_status.value.ready) {
                return@withContext JSONObject()
                    .put("ok", false)
                    .put("error", "the interpreter is not ready yet")
            }
            runCatching {
                val reply = when (arguments.size) {
                    0 -> pluginRuntime.callAttr(function)
                    1 -> pluginRuntime.callAttr(function, arguments[0])
                    2 -> pluginRuntime.callAttr(function, arguments[0], arguments[1])
                    else -> pluginRuntime.callAttr(
                        function, arguments[0], arguments[1], arguments[2],
                    )
                }
                JSONObject(reply.toString())
            }.getOrElse { failure(function, it) }
        }

    private fun failure(what: String, error: Throwable): JSONObject {
        DebugLog.error(TAG_PLUGIN, "plugin call failed: $what", error)
        return JSONObject()
            .put("ok", false)
            .put("error", error.message ?: error.javaClass.simpleName)
    }

    /**
     * Runs one of the plugin tools.
     *
     * These go through the control dispatcher rather than the interpreter
     * thread: formatting a bit of JSON or sending an HTTP request has nothing
     * to do with the script that is running, and should not have to wait for
     * it to finish - least of all when that script is stuck.
     */
    suspend fun tool(name: String, arguments: JSONObject): JSONObject =
        withContext(controlDispatcher) {
            if (!_status.value.ready) {
                return@withContext JSONObject()
                    .put("ok", false)
                    .put("error", "the interpreter is not ready yet")
            }
            try {
                val reply = tools.callAttr("invoke", name, arguments.toString()).toString()
                JSONObject(reply)
            } catch (error: Throwable) {
                DebugLog.error(TAG, "tool $name failed", error)
                JSONObject()
                    .put("ok", false)
                    .put("error", error.message ?: error.javaClass.simpleName)
            }
        }

    suspend fun listDownloads(): List<DownloadedFile> = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext emptyList()
        runCatching {
            downloads.callAttr("listing").asList().map { row ->
                val map = row.asMap()
                DownloadedFile(
                    name = map.str("name"),
                    path = map.str("path"),
                    bytes = map.str("bytes").toLongOrNull() ?: 0L,
                    modifiedSeconds = map.str("modified").toLongOrNull() ?: 0L,
                )
            }
        }.getOrDefault(emptyList())
    }

    suspend fun deleteDownload(path: String): Boolean = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext false
        runCatching { downloads.callAttr("delete", path).asMap().str("ok") == "True" }
            .getOrDefault(false)
    }

    suspend fun copyDownloadToWorkspace(path: String): DownloadResult =
        withContext(controlDispatcher) {
            if (!_status.value.ready) return@withContext DownloadResult(false, error = "Interpreter is not ready.")
            runCatching {
                val map = downloads.callAttr("copy_to_workspace", path).asMap()
                DownloadResult(
                    ok = map.str("ok") == "True",
                    name = map.str("name"),
                    path = map.str("path"),
                    error = map.str("error"),
                )
            }.getOrElse { DownloadResult(false, error = it.friendlyMessage()) }
        }

    // ------------------------------------------------------------------
    // Servers
    // ------------------------------------------------------------------

    suspend fun startStaticServer(
        directory: String,
        port: Int,
        host: String,
        label: String,
        logRequests: Boolean,
    ): ServerActionResult = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext ServerActionResult(false, "Interpreter is not ready.")
        DebugLog.info(TAG, "starting static server on $host:$port", directory)
        runCatching {
            servers.callAttr("start_static", directory, port, host, label, logRequests)
                .asMap().toServerActionResult()
        }.getOrElse {
            DebugLog.error(TAG, "static server failed to start", it)
            ServerActionResult(false, it.friendlyMessage())
        }
    }.also { logServerResult("static", it); refreshServerCount() }

    suspend fun startScriptServer(
        path: String,
        port: Int,
        host: String,
        label: String,
    ): ServerActionResult = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext ServerActionResult(false, "Interpreter is not ready.")
        DebugLog.info(TAG, "starting script server on port $port", path)
        runCatching {
            servers.callAttr("start_script", path, port, host, label)
                .asMap().toServerActionResult()
        }.getOrElse {
            DebugLog.error(TAG, "script server failed to start", it)
            ServerActionResult(false, it.friendlyMessage())
        }
    }.also { logServerResult("script", it); refreshServerCount() }

    private fun logServerResult(kind: String, result: ServerActionResult) {
        if (result.ok) {
            DebugLog.info(TAG, "$kind server ${result.handle} started", result.url)
        } else {
            DebugLog.warn(TAG, "$kind server refused to start", result.error)
        }
    }

    /** Graceful stop. Runs off the main Python thread so it works while it is busy. */
    suspend fun stopServer(handle: String): ServerActionResult = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext ServerActionResult(false, "Interpreter is not ready.")
        DebugLog.info(TAG, "stopping server $handle")
        runCatching {
            val map = servers.callAttr("stop", handle).asMap()
            ServerActionResult(
                ok = map.str("ok") == "True",
                error = map.str("error"),
                needsKill = map.str("needs_kill") == "True",
            )
        }.getOrElse {
            DebugLog.error(TAG, "stop of $handle failed", it)
            ServerActionResult(false, it.friendlyMessage())
        }
    }.also { refreshServerCount() }

    /**
     * The kill switch.
     *
     * Frees the port, raises SystemExit inside the server's thread, and stops
     * tracking it either way, so a thread wedged in a blocking call can never
     * hold the UI or the port hostage.
     */
    suspend fun killServer(handle: String): ServerActionResult = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext ServerActionResult(false, "Interpreter is not ready.")
        DebugLog.warn(TAG, "killing server $handle")
        cancelledChannels[handle] = true
        runCatching {
            val map = servers.callAttr("kill", handle).asMap()
            ServerActionResult(
                ok = map.str("ok") == "True",
                error = map.str("error"),
                detached = map.str("detached") == "True",
            )
        }.getOrElse {
            DebugLog.error(TAG, "kill of $handle failed", it)
            ServerActionResult(false, it.friendlyMessage())
        }
    }.also { refreshServerCount() }

    suspend fun stopAllServers(): Int = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext 0
        runCatching { servers.callAttr("stop_all").asMap().str("stopped").toIntOrNull() ?: 0 }
            .getOrElse {
                DebugLog.error(TAG, "stop_all failed", it)
                0
            }
    }.also { refreshServerCount() }

    /** Panic button: force every server down regardless of state. */
    suspend fun killAllServers(): Int = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext 0
        DebugLog.warn(TAG, "killing every server")
        cancelledChannels.clear()
        runCatching { servers.callAttr("kill_all").asMap().str("killed").toIntOrNull() ?: 0 }
            .getOrElse {
                DebugLog.error(TAG, "kill_all failed", it)
                0
            }
    }.also { refreshServerCount() }

    suspend fun listServers(): List<RunningServer> = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext emptyList()
        runCatching {
            servers.callAttr("listing").asList().map { row ->
                val map = row.asMap()
                RunningServer(
                    handle = map.str("handle"),
                    label = map.str("label"),
                    kind = map.str("kind"),
                    port = map.str("port").toIntOrNull() ?: 0,
                    host = map.str("host"),
                    status = map.str("status"),
                    url = map.str("url"),
                    error = map.str("error"),
                    target = map.str("target"),
                    uptimeSeconds = map.str("uptime").toIntOrNull() ?: 0,
                    requests = map.str("requests").toIntOrNull() ?: 0,
                )
            }
        }.getOrElse {
            DebugLog.error(TAG, "server listing failed", it)
            emptyList()
        }
    }

    /** Replays a server's own log, so reopening its console is not blank. */
    suspend fun serverLog(handle: String): List<OutputChunk> = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext emptyList()
        runCatching {
            servers.callAttr("log_lines", handle).asList().map { row ->
                val map = row.asMap()
                val stream = when (map.str("stream")) {
                    "stderr" -> OutputChunk.Stream.STDERR
                    "system" -> OutputChunk.Stream.SYSTEM
                    else -> OutputChunk.Stream.STDOUT
                }
                OutputChunk(stream, map.str("text"), chunkId.incrementAndGet(), handle)
            }
        }.getOrDefault(emptyList())
    }

    suspend fun suggestPort(from: Int): Int = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext from
        runCatching { servers.callAttr("suggest_port", from).toInt() }.getOrDefault(from)
    }

    suspend fun localIp(): String = withContext(controlDispatcher) {
        if (!_status.value.ready) return@withContext "127.0.0.1"
        runCatching { servers.callAttr("local_ip").toString() }.getOrDefault("127.0.0.1")
    }

    /** Queues the refresh onto a control thread; never blocks the caller. */
    private fun refreshServerCount() {
        if (!_status.value.ready) return
        controlExecutor.execute {
            runCatching { _serverCount.value = servers.callAttr("count").toInt() }
        }
    }
}

/** What the app knows about a file type. */
/**
 * The language whose extensions include [name]'s.
 *
 * Lives here rather than in the view model so that a composable can match on
 * the catalogue it already collects: matching through the view model reads a
 * flow's value without subscribing to it, and the row then never notices when
 * the catalogue finally arrives.
 */
fun List<LanguageInfo>.forFileName(name: String): LanguageInfo? {
    val extension = name.substringAfterLast('.', "").lowercase()
    if (extension.isEmpty()) return null
    return firstOrNull { info ->
        info.extensions.split(",").any { it.trim().removePrefix(".") == extension }
    }
}

/**
 * A page ready to show.
 *
 * When [served] is true the page is coming off a loopback HTTP server rooted
 * at its own folder, which is the only way a preview behaves like a browser:
 * modules load, fetch works, relative paths resolve, and a link to the next
 * page of the site actually goes there. [html] is kept as the fallback for
 * the rare case where no socket could be opened.
 */
data class PreviewPage(
    val name: String,
    val html: String,
    val baseDirectory: String,
    val url: String = "",
    val served: Boolean = false,
) {
    /** The origin the preview is allowed to navigate inside. */
    val origin: String get() = url.substringBefore("/", "").let {
        if (url.startsWith("http")) url.split("/").take(3).joinToString("/") else ""
    }
}

data class LanguageInfo(
    val id: String,
    val name: String,
    val extension: String,
    /** "run", "preview" or "edit". */
    val mode: String,
    val highlight: String,
    val note: String,
    /** Every extension this language claims, comma separated. */
    val extensions: String = extension,
) {
    val canRun: Boolean get() = mode == "run"
    val canPreview: Boolean get() = mode == "preview"
}

data class DownloadResult(
    val ok: Boolean,
    val name: String = "",
    val path: String = "",
    val bytes: Long = 0L,
    val files: Int = 0,
    val error: String = "",
)

data class DownloadedFile(
    val name: String,
    val path: String,
    val bytes: Long,
    val modifiedSeconds: Long,
) {
    val readableSize: String
        get() = when {
            bytes < 1024 -> "$bytes B"
            bytes < 1024 * 1024 -> "%.1f KB".format(java.util.Locale.US, bytes / 1024.0)
            else -> "%.1f MB".format(java.util.Locale.US, bytes / (1024.0 * 1024.0))
        }
}

data class PackageResult(
    val ok: Boolean,
    val name: String = "",
    val version: String = "",
    val error: String = "",
)

data class InstalledPackage(
    val name: String,
    val version: String,
    val summary: String,
    val fileCount: Int,
)

data class RunningServer(
    val handle: String,
    val label: String,
    val kind: String,
    val port: Int,
    val host: String,
    val status: String,
    val url: String,
    val error: String,
    val target: String,
    val uptimeSeconds: Int,
    val requests: Int,
) {
    val isRunning: Boolean get() = status == "running"

    val readableUptime: String
        get() = when {
            uptimeSeconds < 60 -> "${uptimeSeconds}s"
            uptimeSeconds < 3600 -> "${uptimeSeconds / 60}m ${uptimeSeconds % 60}s"
            else -> "${uptimeSeconds / 3600}h ${(uptimeSeconds % 3600) / 60}m"
        }
}

data class ServerActionResult(
    val ok: Boolean,
    val error: String = "",
    val url: String = "",
    val handle: String = "",
    val needsKill: Boolean = false,
    val detached: Boolean = false,
)

/** Chaquopy maps are `Map<PyObject, PyObject>`; missing keys must read as empty. */
private fun Map<PyObject, PyObject>.str(key: String): String =
    entries.firstOrNull { it.key.toString() == key }?.value?.toString().orEmpty()

private fun Map<PyObject, PyObject>.toPackageResult(): PackageResult =
    PackageResult(
        ok = str("ok") == "True",
        name = str("name"),
        version = str("version"),
        error = str("error"),
    )

private fun Map<PyObject, PyObject>.toServerActionResult(): ServerActionResult =
    ServerActionResult(
        ok = str("ok") == "True",
        error = str("error"),
        url = str("url"),
        handle = str("handle"),
    )

/** Chaquopy wraps Python exceptions; the raw message is long and noisy. */
private fun Throwable.friendlyMessage(): String {
    val raw = message ?: javaClass.simpleName
    return raw.lineSequence().firstOrNull { it.isNotBlank() } ?: raw
}
