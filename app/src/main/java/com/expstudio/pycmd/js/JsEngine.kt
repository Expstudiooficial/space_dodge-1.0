package com.expstudio.pycmd.js

import android.annotation.SuppressLint
import android.content.Context
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import com.expstudio.pycmd.util.DebugLog
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/**
 * Runs JavaScript files in the device's own engine.
 *
 * There is no interpreter in this app for JavaScript, and there should not be:
 * every Android device carries a complete, fast, standards-compliant engine
 * inside its WebView, so a `.js` file gets the real thing - classes, async,
 * generators, regular expressions, `Intl`, the lot - rather than a subset
 * somebody wrote by hand.
 *
 * The page is reloaded before every run. That costs a few milliseconds and buys
 * a guarantee worth much more: a run never sees globals, timers or listeners
 * left behind by the one before it.
 *
 * One honest limitation: JavaScript in a WebView runs on a thread this app does
 * not own, and nothing can interrupt a `while (true) {}`. [stop] therefore
 * throws the whole engine away and builds a new one, which is the only thing
 * that reliably ends a runaway script.
 */
object JsEngine {

    private const val TAG = "js"
    private const val PAGE = "file:///android_asset/web/jsrun.html"

    /** What the caller wants done with the run's output and input. */
    interface Host {
        fun stdout(text: String)
        fun stderr(text: String)

        /** Blocks until a line arrives, or returns null when the run is cancelled. */
        fun readLine(): String?
    }

    /** How a run ended: `ok`, `error` or `stopped`, plus the exit status. */
    data class Result(val status: String, val exitCode: Int = 0)

    private val main = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val io = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val tokens = AtomicLong(0)

    private var webView: WebView? = null

    @Volatile
    private var active: Run? = null

    private class Run(
        val token: String,
        val host: Host,
        val done: CompletableDeferred<Result> = CompletableDeferred(),
    ) {
        @Volatile var cancelled = false
    }

    /**
     * The object the page calls back into.
     *
     * Every method here arrives on the WebView's own JavaScript-bridge thread,
     * so nothing may touch a view directly; anything that has to reach the
     * WebView is posted to the main thread first.
     */
    private val bridge = object {
        @JavascriptInterface
        fun ready() {
            // The page announces itself; the run is started from Kotlin once
            // onPageFinished has fired, so there is nothing to do here beyond
            // proving in the log that the bootstrap loaded at all.
            DebugLog.debug(TAG, "javascript runtime loaded")
        }

        @JavascriptInterface
        fun write(token: String, text: String) {
            forToken(token)?.host?.stdout(text)
        }

        @JavascriptInterface
        fun writeErr(token: String, text: String) {
            forToken(token)?.host?.stderr(text)
        }

        @JavascriptInterface
        fun readLine(token: String, id: String) {
            val run = forToken(token) ?: return
            // Reading blocks until the user types something, so it cannot
            // happen here: this thread is the one the page is waiting on.
            io.launch {
                val line = runCatching { run.host.readLine() }.getOrNull()
                if (run.cancelled || forToken(token) == null) return@launch
                withContext(Dispatchers.Main) {
                    val value = if (line == null) "null" else JSONObject.quote(line)
                    webView?.evaluateJavascript(
                        "__pycmd_resolve($id, ${line != null}, $value)",
                        null,
                    )
                }
            }
        }

        @JavascriptInterface
        fun finish(token: String, status: String, exitCode: String, detail: String) {
            val run = forToken(token) ?: return
            if (detail.isNotBlank()) DebugLog.debug(TAG, "run ended: $detail")
            active = null
            run.done.complete(Result(status, exitCode.toIntOrNull() ?: 0))
        }
    }

    private fun forToken(token: String): Run? = active?.takeIf { it.token == token && !it.cancelled }

    /**
     * Runs [source] and suspends until it has genuinely finished.
     *
     * "Finished" means the event loop is empty, not that the last statement
     * has been read: a script whose real work happens in `setTimeout` or an
     * awaited promise keeps the console busy until that work is done.
     */
    suspend fun run(context: Context, source: String, name: String, host: Host): Result {
        val previous = active
        if (previous != null && !previous.done.isCompleted) {
            return Result("error", 1).also {
                host.stderr("A JavaScript file is already running.\n")
            }
        }

        val run = Run(tokens.incrementAndGet().toString(), host)
        active = run

        val loaded = try {
            withContext(Dispatchers.Main) { loadPage(context.applicationContext) }
        } catch (error: Throwable) {
            active = null
            DebugLog.error(TAG, "could not start the JavaScript engine", error)
            host.stderr("JavaScript engine failed to start: ${error.message}\n")
            return Result("error", 1)
        }

        if (!loaded) {
            active = null
            host.stderr("JavaScript engine failed to start.\n")
            return Result("error", 1)
        }

        withContext(Dispatchers.Main) {
            webView?.evaluateJavascript(
                "__pycmd_run(${JSONObject.quote(source)}, ${JSONObject.quote(name)}, " +
                    "${JSONObject.quote(run.token)})",
                null,
            )
        }

        return run.done.await()
    }

    /**
     * Ends whatever is running.
     *
     * Nothing short of destroying the WebView can stop a script that has taken
     * its thread and refuses to give it back, so that is what happens: the
     * engine is thrown away and the next run builds a fresh one.
     */
    fun stop() {
        val run = active ?: return
        run.cancelled = true
        active = null
        main.launch {
            webView?.let { view ->
                view.stopLoading()
                view.destroy()
            }
            webView = null
            DebugLog.info(TAG, "JavaScript engine restarted to stop a run")
            run.done.complete(Result("stopped", 130))
        }
    }

    /** Frees the engine. Called when nothing needs JavaScript any more. */
    fun shutdown() {
        main.launch {
            webView?.destroy()
            webView = null
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private suspend fun loadPage(context: Context): Boolean {
        val ready = CompletableDeferred<Boolean>()

        val view = webView ?: WebView(context).also { fresh ->
            fresh.settings.javaScriptEnabled = true
            fresh.settings.domStorageEnabled = true
            // The page is one of ours and loads no network resources, so the
            // bridge is only ever reachable by code the user asked to run.
            fresh.addJavascriptInterface(bridge, "__pycmd")
            // The view is never attached to a window, and a page a browser
            // thinks is in the background has its timers slowed to a crawl.
            fresh.resumeTimers()
            fresh.webChromeClient = object : WebChromeClient() {
                override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                    // Anything the page itself logs is a bug in the bootstrap,
                    // not in the user's script: their console.log is bridged.
                    if (message.messageLevel() == ConsoleMessage.MessageLevel.ERROR) {
                        DebugLog.warn(
                            TAG,
                            message.message(),
                            "${message.sourceId()}:${message.lineNumber()}",
                        )
                    }
                    return true
                }
            }
            webView = fresh
        }

        view.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                if (!ready.isCompleted) ready.complete(true)
            }
        }

        view.loadUrl(PAGE)
        // A page that never finishes loading would otherwise leave the console
        // waiting for a run that can never start.
        return withTimeoutOrNull(15_000) { ready.await() } ?: false
    }
}
