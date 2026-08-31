package com.expstudio.pycmd.util

import android.util.Log
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Strips ANSI escapes.
 *
 * Python 3.13 colourises tracebacks, and the console WebView renders those
 * codes properly - but the debug log is plain text, on screen and in an export,
 * so the codes would show up as literal noise.
 */
private val ANSI = Regex("\u001B\\[[0-9;?]*[ -/]*[@-~]|\u001B][^\u0007\u001B]*(?:\u0007|\u001B\\\\)?")

fun stripAnsiCodes(text: String): String = if (text.indexOf('\u001B') < 0) text else ANSI.replace(text, "")

enum class LogLevel(val label: String, val short: String) {
    DEBUG("Debug", "DBG"),
    INFO("Info", "INF"),
    WARN("Warning", "WRN"),
    ERROR("Error", "ERR"),
}

/** One line in the debug console. */
data class LogEntry(
    val id: Long,
    val timeMillis: Long,
    val level: LogLevel,
    val tag: String,
    val message: String,
    val detail: String? = null,
) {
    val time: String get() = TIME_FORMAT.format(Date(timeMillis))

    /** Everything about this entry, for copy-all and export. */
    fun toPlainText(): String = buildString {
        append(time).append("  ").append(level.short).append("  ").append(tag).append("  ")
        append(message)
        if (!detail.isNullOrBlank()) {
            append('\n')
            detail.trimEnd().lineSequence().forEach { append("    ").append(it).append('\n') }
        }
    }

    private companion object {
        val TIME_FORMAT = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)
    }
}

/**
 * A process-wide record of everything that went wrong, and a fair amount that
 * went right.
 *
 * The console shows a script's own output; this shows the machinery around it
 * — interpreter startup, server lifecycles, package installs, file errors,
 * WebView JavaScript errors and uncaught Java exceptions. When something
 * misbehaves and the console has nothing useful to say, this is the place that
 * does.
 *
 * Writes are cheap and safe from any thread, and *staying* cheap is the whole
 * design. This used to copy the entire three-thousand-entry buffer and count
 * its errors on every single line, then publish both - so one line cost two
 * passes over three thousand entries, and a burst of a few hundred lines
 * (a chatty server, a page throwing in a loop) cost hundreds of thousands of
 * operations and hundreds of recompositions on the main thread. That is what
 * "the app froze for a second" was made of.
 *
 * Now a write is O(1): the entry goes on the end, the error count moves by one
 * if it has to, and a snapshot is published on a timer at most a few times a
 * second. A hundred lines in one burst is one snapshot and one recomposition.
 */
object DebugLog {

    private const val TAG = "PyCmd"
    private const val CAPACITY = 3000

    /** How often a burst of writing turns into a redraw. */
    private const val PUBLISH_EVERY_MS = 120L

    private val lock = Any()
    private val buffer = ArrayDeque<LogEntry>(CAPACITY)
    private val nextId = AtomicLong(0)

    /** Kept as the buffer changes rather than counted on every write. */
    private var errors = 0

    private val publishPending = AtomicBoolean(false)
    private val publisher = Executors.newSingleThreadScheduledExecutor { runnable ->
        Thread(runnable, "pycmd-log").apply { isDaemon = true }
    }

    private val _entries = MutableStateFlow<List<LogEntry>>(emptyList())
    val entries: StateFlow<List<LogEntry>> = _entries.asStateFlow()

    private val _errorCount = MutableStateFlow(0)
    val errorCount: StateFlow<Int> = _errorCount.asStateFlow()

    fun debug(tag: String, message: String, detail: String? = null) =
        add(LogLevel.DEBUG, tag, message, detail)

    fun info(tag: String, message: String, detail: String? = null) =
        add(LogLevel.INFO, tag, message, detail)

    fun warn(tag: String, message: String, detail: String? = null) =
        add(LogLevel.WARN, tag, message, detail)

    fun error(tag: String, message: String, detail: String? = null) =
        add(LogLevel.ERROR, tag, message, detail)

    /** Records a throwable with its stack trace as the detail. */
    fun error(tag: String, message: String, throwable: Throwable) =
        add(LogLevel.ERROR, tag, message, throwable.stackTraceToString())

    private fun add(level: LogLevel, tag: String, message: String, detail: String?) {
        val entry = LogEntry(
            id = nextId.incrementAndGet(),
            timeMillis = System.currentTimeMillis(),
            level = level,
            tag = tag,
            message = stripAnsiCodes(message).take(4000),
            detail = detail?.let(::stripAnsiCodes)?.take(20000),
        )

        synchronized(lock) {
            buffer.addLast(entry)
            if (entry.level == LogLevel.ERROR) errors += 1
            while (buffer.size > CAPACITY) {
                if (buffer.removeFirst().level == LogLevel.ERROR) errors -= 1
            }
        }
        publishSoon()

        // Mirror to logcat so `adb logcat` still shows everything.
        when (level) {
            LogLevel.DEBUG -> Log.d(TAG, "[$tag] $message")
            LogLevel.INFO -> Log.i(TAG, "[$tag] $message")
            LogLevel.WARN -> Log.w(TAG, "[$tag] $message")
            LogLevel.ERROR -> Log.e(TAG, "[$tag] $message${detail?.let { "\n$it" } ?: ""}")
        }
    }

    /**
     * Publishes the buffer to whoever is watching, at most once every
     * [PUBLISH_EVERY_MS].
     *
     * The first write after a quiet spell schedules the flush; every write
     * until it runs joins it. So a line on its own still reaches the screen in
     * a tenth of a second, and a thousand at once still cost one copy.
     */
    private fun publishSoon() {
        if (!publishPending.compareAndSet(false, true)) return
        runCatching {
            publisher.schedule(::publishNow, PUBLISH_EVERY_MS, TimeUnit.MILLISECONDS)
        }.onFailure {
            // No scheduler (a shutting-down process): publish here instead of
            // dropping the line.
            publishPending.set(false)
            publishNow()
        }
    }

    private fun publishNow() {
        publishPending.set(false)
        val snapshot: List<LogEntry>
        val count: Int
        synchronized(lock) {
            snapshot = buffer.toList()
            count = errors
        }
        _entries.value = snapshot
        _errorCount.value = count
    }

    fun clear() {
        synchronized(lock) {
            buffer.clear()
            errors = 0
        }
        _entries.value = emptyList()
        _errorCount.value = 0
    }

    /** Everything written so far, flushed first so nothing is a beat behind. */
    fun snapshot(): List<LogEntry> {
        publishNow()
        return _entries.value
    }

    /** The whole log as text, for copying to the clipboard or saving to a file. */
    fun exportText(): String = buildString {
        append("PyCmd debug log\n")
        append(SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date()))
        append("\n\n")
        snapshot().forEach { append(it.toPlainText()).append('\n') }
    }

    /**
     * Routes crashes here before the process dies.
     *
     * The entry will not survive the crash, but anything logged in the seconds
     * before it will already be on screen, and a crash that is caught on a
     * background thread often does not take the app down at all.
     */
    fun installCrashHandler() {
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            runCatching {
                error("crash", "Uncaught on ${thread.name}: ${throwable.javaClass.simpleName}", throwable)
                // The process may not live long enough for the next flush.
                publishNow()
            }
            previous?.uncaughtException(thread, throwable)
        }
    }
}
