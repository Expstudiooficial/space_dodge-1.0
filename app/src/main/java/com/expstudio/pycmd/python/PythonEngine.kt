package com.expstudio.pycmd.python

import android.content.Context
import android.util.Log
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext

/** One line of console output, tagged with where it came from. */
data class OutputChunk(
    val stream: Stream,
    val text: String,
    val id: Long,
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
 */
object PythonEngine {

    private const val TAG = "PythonEngine"
    private const val OUTPUT_BUFFER = 512

    /** The single thread every Python call runs on. */
    private val pythonExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "python-main").apply { isDaemon = true }
    }
    private val pythonDispatcher = pythonExecutor.asCoroutineDispatcher()

    /**
     * Stop requests cannot queue behind the code they are trying to stop, and
     * they must not block the UI thread waiting for the GIL, so they get their
     * own thread.
     */
    private val controlExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "python-control").apply { isDaemon = true }
    }

    private val _output = MutableSharedFlow<OutputChunk>(
        replay = OUTPUT_BUFFER,
        extraBufferCapacity = OUTPUT_BUFFER,
    )
    val output: SharedFlow<OutputChunk> = _output.asSharedFlow()

    private val _status = MutableStateFlow(EngineStatus())
    val status: StateFlow<EngineStatus> = _status.asStateFlow()

    private val _serverCount = MutableStateFlow(0)
    val serverCount: StateFlow<Int> = _serverCount.asStateFlow()

    /** Hand-off point between the console's input box and Python's `input()`. */
    private val stdinQueue = ArrayBlockingQueue<String>(16)
    private val stopRequested = AtomicBoolean(false)
    private var chunkId = 0L

    private lateinit var runtime: PyObject
    private lateinit var packages: PyObject
    private lateinit var servers: PyObject

    lateinit var workspaceDir: File
        private set
    lateinit var sitePackagesDir: File
        private set

    /** Receives stdout/stderr from Python and supplies stdin. Called on the Python thread. */
    @Suppress("unused") // Called from pycmd_runtime.py
    private val sink = object {
        fun onOutput(stream: String, text: String) {
            val kind = if (stream == "stderr") OutputChunk.Stream.STDERR else OutputChunk.Stream.STDOUT
            emit(kind, text)
        }

        fun onReadLine(): String? {
            _status.value = _status.value.copy(awaitingInput = true)
            try {
                while (true) {
                    if (stopRequested.get()) return null
                    val line = stdinQueue.poll(150, TimeUnit.MILLISECONDS)
                    if (line != null) return line
                }
            } catch (interrupted: InterruptedException) {
                Thread.currentThread().interrupt()
                return null
            } finally {
                _status.value = _status.value.copy(awaitingInput = false)
            }
        }

        fun onFinished(runId: Int, status: String, millis: Int) {
            Log.d(TAG, "run $runId finished: $status in ${millis}ms")
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

        val appContext = context.applicationContext
        workspaceDir = File(appContext.filesDir, "workspace").apply { mkdirs() }
        sitePackagesDir = File(appContext.filesDir, "site-packages").apply { mkdirs() }

        try {
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(appContext))
            }
            val python = Python.getInstance()
            runtime = python.getModule("pycmd_runtime")
            packages = python.getModule("pycmd_packages")
            servers = python.getModule("pycmd_servers")

            val version = runtime.callAttr(
                "configure",
                sink,
                workspaceDir.absolutePath,
                sitePackagesDir.absolutePath,
            ).toString()
            packages.callAttr("configure", sitePackagesDir.absolutePath)

            val short = version.trim().split(" ").firstOrNull().orEmpty()
            _status.value = EngineStatus(ready = true, pythonVersion = short)
            emit(OutputChunk.Stream.SYSTEM, "Python $short ready. Type code and press Run.\n")
        } catch (error: Throwable) {
            Log.e(TAG, "interpreter failed to start", error)
            _status.value = EngineStatus(
                ready = false,
                startupError = error.message ?: error.javaClass.simpleName,
            )
            emit(OutputChunk.Stream.STDERR, "Interpreter failed to start: ${error.message}\n")
        }
        _status.value
    }

    private fun emit(stream: OutputChunk.Stream, text: String) {
        if (text.isEmpty()) return
        chunkId += 1
        _output.tryEmit(OutputChunk(stream, text, chunkId))
    }

    /** Echo something into the console without going through Python. */
    fun echo(text: String, stream: OutputChunk.Stream = OutputChunk.Stream.SYSTEM) = emit(stream, text)

    // ------------------------------------------------------------------
    // Running code
    // ------------------------------------------------------------------

    /**
     * Runs [source] and suspends until it completes.
     *
     * Because every Python call shares one thread, a second run can only begin
     * once the first has returned — which is the behaviour a console wants.
     */
    suspend fun run(source: String, sourceName: String = "<console>", echoResult: Boolean = true): String {
        if (!_status.value.ready) return "error"
        stopRequested.set(false)
        stdinQueue.clear()
        _status.value = _status.value.copy(running = true)
        return try {
            withContext(pythonDispatcher) {
                runtime.callAttr("run_source", source, sourceName, echoResult).toString()
            }
        } catch (error: Throwable) {
            emit(OutputChunk.Stream.STDERR, "Internal error: ${error.message}\n")
            "error"
        } finally {
            _status.value = _status.value.copy(running = false, awaitingInput = false)
            refreshServerCount()
        }
    }

    suspend fun runFile(path: String): String {
        if (!_status.value.ready) return "error"
        stopRequested.set(false)
        stdinQueue.clear()
        _status.value = _status.value.copy(running = true)
        return try {
            withContext(pythonDispatcher) { runtime.callAttr("run_file", path).toString() }
        } catch (error: Throwable) {
            emit(OutputChunk.Stream.STDERR, "Internal error: ${error.message}\n")
            "error"
        } finally {
            _status.value = _status.value.copy(running = false, awaitingInput = false)
            refreshServerCount()
        }
    }

    /**
     * Asks the running code to stop.
     *
     * This does not go through [pythonDispatcher] — that thread is busy running
     * the user's code, so a queued call would never arrive. Setting the flag
     * from here is what makes Stop responsive.
     */
    fun requestStop() {
        stopRequested.set(true)
        stdinQueue.clear()
        if (!_status.value.ready) return
        controlExecutor.execute {
            runCatching { runtime.callAttr("request_stop") }
                .onFailure { Log.w(TAG, "stop request failed", it) }
        }
    }

    /** Feeds a line to a waiting `input()` call. */
    fun submitInput(line: String) {
        emit(OutputChunk.Stream.INPUT, line + "\n")
        if (!stdinQueue.offer(line + "\n")) {
            emit(OutputChunk.Stream.STDERR, "Input buffer is full; nothing is reading stdin.\n")
        }
    }

    suspend fun resetNamespace() = withContext(pythonDispatcher) {
        runCatching { runtime.callAttr("reset_namespace") }
        emit(OutputChunk.Stream.SYSTEM, "Namespace cleared.\n")
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
            runCatching {
                val result = packages.callAttr(
                    "install",
                    name,
                    version?.takeIf { it.isNotBlank() },
                    ProgressSink(onProgress),
                ).asMap()
                result.toPackageResult()
            }.getOrElse { PackageResult(false, error = it.friendlyMessage()) }
        }

    suspend fun uninstallPackage(name: String): PackageResult = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext PackageResult(false, error = "Interpreter is not ready.")
        runCatching { packages.callAttr("uninstall", name).asMap().toPackageResult() }
            .getOrElse { PackageResult(false, error = it.friendlyMessage()) }
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

    suspend fun searchPackage(name: String): PackageSearchResult = withContext(pythonDispatcher) {
        if (!_status.value.ready) {
            return@withContext PackageSearchResult(false, error = "Interpreter is not ready.")
        }
        runCatching {
            val map = packages.callAttr("search", name).asMap()
            if (map.str("ok") != "True") {
                PackageSearchResult(false, error = map.str("error"))
            } else {
                PackageSearchResult(
                    ok = true,
                    name = map.str("name"),
                    version = map.str("version"),
                    summary = map.str("summary"),
                    purePython = map.str("pure_python") == "True",
                )
            }
        }.getOrElse { PackageSearchResult(false, error = it.friendlyMessage()) }
    }

    // ------------------------------------------------------------------
    // Servers
    // ------------------------------------------------------------------

    suspend fun startFileServer(directory: String, port: Int): ServerActionResult =
        withContext(pythonDispatcher) {
            if (!_status.value.ready) return@withContext ServerActionResult(false, "Interpreter is not ready.")
            runCatching {
                val map = servers.callAttr("start_file_server", directory, port).asMap()
                if (map.str("ok") == "True") {
                    ServerActionResult(true, url = map.str("url"))
                } else {
                    ServerActionResult(false, map.str("error"))
                }
            }.getOrElse { ServerActionResult(false, it.friendlyMessage()) }
        }.also { refreshServerCount() }

    suspend fun startScriptServer(path: String, port: Int, label: String): ServerActionResult =
        withContext(pythonDispatcher) {
            if (!_status.value.ready) return@withContext ServerActionResult(false, "Interpreter is not ready.")
            runCatching {
                val map = servers.callAttr("start_script", path, port, label).asMap()
                if (map.str("ok") == "True") {
                    ServerActionResult(true, url = map.str("url"))
                } else {
                    ServerActionResult(false, map.str("error"))
                }
            }.getOrElse { ServerActionResult(false, it.friendlyMessage()) }
        }.also { refreshServerCount() }

    suspend fun stopServer(handle: String): ServerActionResult = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext ServerActionResult(false, "Interpreter is not ready.")
        runCatching {
            val map = servers.callAttr("stop", handle).asMap()
            if (map.str("ok") == "True") ServerActionResult(true) else ServerActionResult(false, map.str("error"))
        }.getOrElse { ServerActionResult(false, it.friendlyMessage()) }
    }.also { refreshServerCount() }

    suspend fun stopAllServers(): Int = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext 0
        runCatching { servers.callAttr("stop_all").toInt() }.getOrDefault(0)
    }.also { refreshServerCount() }

    suspend fun listServers(): List<RunningServer> = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext emptyList()
        runCatching {
            servers.callAttr("listing").asList().map { row ->
                val map = row.asMap()
                RunningServer(
                    handle = map.str("handle"),
                    label = map.str("label"),
                    port = map.str("port").toIntOrNull() ?: 0,
                    status = map.str("status"),
                    url = map.str("url"),
                    error = map.str("error"),
                )
            }
        }.getOrDefault(emptyList())
    }

    suspend fun localIp(): String = withContext(pythonDispatcher) {
        if (!_status.value.ready) return@withContext "127.0.0.1"
        runCatching { servers.callAttr("local_ip").toString() }.getOrDefault("127.0.0.1")
    }

    /** Queues the refresh onto the Python thread; never blocks the caller. */
    private fun refreshServerCount() {
        if (!_status.value.ready) return
        pythonExecutor.execute {
            runCatching { _serverCount.value = servers.callAttr("count").toInt() }
        }
    }
}

data class PackageResult(
    val ok: Boolean,
    val name: String = "",
    val version: String = "",
    val error: String = "",
)

data class PackageSearchResult(
    val ok: Boolean,
    val name: String = "",
    val version: String = "",
    val summary: String = "",
    val purePython: Boolean = false,
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
    val port: Int,
    val status: String,
    val url: String,
    val error: String,
)

data class ServerActionResult(
    val ok: Boolean,
    val error: String = "",
    val url: String = "",
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

/** Chaquopy wraps Python exceptions; the raw message is long and noisy. */
private fun Throwable.friendlyMessage(): String {
    val raw = message ?: javaClass.simpleName
    return raw.lineSequence().firstOrNull { it.isNotBlank() } ?: raw
}
