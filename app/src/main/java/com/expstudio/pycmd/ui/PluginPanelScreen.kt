package com.expstudio.pycmd.ui

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.view.MotionEvent
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.JsResult
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.RememberObserver
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.graphics.toColorInt
import com.expstudio.pycmd.plugins.InstalledPlugin
import com.expstudio.pycmd.python.PythonEngine
import com.expstudio.pycmd.util.DebugLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * One plugin page, hosted in a WebView.
 *
 * Used both for a plugin's own screen and for a section it adds to one of the
 * app's own tabs, so that the two behave identically: same stylesheet, same
 * bridge, same refusal to navigate anywhere.
 */
@SuppressLint("SetJavaScriptEnabled", "ClickableViewAccessibility")
@Composable
fun PluginPanelView(
    plugin: InstalledPlugin,
    viewModel: MainViewModel,
    modifier: Modifier = Modifier,
    panelFile: String = "",
) {
    val context = LocalContext.current
    val key = "${plugin.id}:$panelFile"

    // Taken once. A panel that has been shown before comes back whole - its
    // page, its scroll position, and whatever was typed into it - and a panel
    // that has not is built now.
    val lease = remember(key) {
        val kept = PanelViews.take(key)
        val bridge = kept?.bridge ?: PanelBridge(plugin)
        PanelLease(
            key = key,
            view = kept?.view ?: newPanelView(context, bridge, plugin),
            bridge = bridge,
            wasKept = kept != null,
        )
    }
    val bridge = lease.bridge
    val webView = lease.view

    DisposableEffect(webView, viewModel) {
        bridge.bind(viewModel)
        bridge.attach(webView)
        onDispose {
            bridge.detach()
            // Out of the list, not out of existence: this item may be two
            // scrolled rows away from being needed again.
            PanelViews.keep(key, webView, bridge)
        }
    }

    LaunchedEffect(key) {
        // Only the first time. Loading the page again on every visit is what
        // made scrolling past a section cost a page load - and it would throw
        // away everything the panel had on screen.
        if (lease.wasKept) return@LaunchedEffect
        val html = viewModel.pluginPanelHtml(plugin.id, panelFile)
        val base = "file://${PythonEngine.pluginDirectory(plugin.id).absolutePath}/"
        webView.loadDataWithBaseURL(base, html, "text/html", "utf-8", null)
    }

    // A plugin can push to its panel while it is open.
    LaunchedEffect(key) {
        PythonEngine.pluginMessages.collect { (id, body) ->
            if (id == plugin.id) bridge.deliver(body)
        }
    }

    AndroidView(factory = { webView }, modifier = modifier)
}

/**
 * The panel this composition has borrowed from [PanelViews].
 *
 * A `remember` that took something out of a shared pool has to be able to put
 * it back, and there is one case where nothing else will: Compose builds an
 * item, then throws the whole composition away before it is ever applied - a
 * lazy list looking ahead and changing its mind. `onDispose` never runs for
 * one of those, so without [onAbandoned] the panel would be gone from the
 * pool and held by nobody, which is a WebView leaked per near-miss scroll.
 */
private class PanelLease(
    val key: String,
    val view: WebView,
    val bridge: PanelBridge,
    /** Whether it came back from the pool, and so is already loaded. */
    val wasKept: Boolean,
) : RememberObserver {
    override fun onRemembered() = Unit

    override fun onForgotten() = Unit

    override fun onAbandoned() {
        PanelViews.keep(key, view, bridge)
    }
}

/**
 * A WebView set up the way every plugin panel wants one.
 *
 * Built here rather than inside the composable because the view outlives the
 * composition now - see [PanelViews] - and a factory that closes over
 * composition state would be a factory that kept it alive.
 */
@SuppressLint("SetJavaScriptEnabled", "ClickableViewAccessibility")
private fun newPanelView(
    context: android.content.Context,
    bridge: PanelBridge,
    plugin: InstalledPlugin,
): WebView {
    run {
        // Where the finger was on the previous move, so the direction of a
        // drag is known before deciding who should own it. A one-element array
        // rather than a captured var: it belongs to this WebView, and there is
        // one of these per panel.
        val lastTouchY = floatArrayOf(0f)

        return WebView(context).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            // A panel loads its own images and stylesheets from the plugin's
            // folder, which is inside the app's private storage.
            settings.allowFileAccess = true
            settings.allowContentAccess = false
            setBackgroundColor("#0B0F14".toColorInt())
            isVerticalScrollBarEnabled = true
            overScrollMode = WebView.OVER_SCROLL_IF_CONTENT_SCROLLS
            // A panel sitting inside one of the app's own screens is a
            // scrolling view inside a scrolling list, and the list wins every
            // gesture by default - so a section you opened could not be
            // scrolled at all. Claiming the gesture on touch-down hands the
            // drag to the page; letting go of the claim when the page has
            // nothing left to scroll gives it back to the list, so flicking
            // past a section still works.
            setOnTouchListener { view, event ->
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        view.parent?.requestDisallowInterceptTouchEvent(true)
                        lastTouchY[0] = event.y
                    }

                    MotionEvent.ACTION_MOVE -> {
                        val page = view as WebView
                        val goingUp = event.y > lastTouchY[0]
                        val atTop = page.scrollY <= 0
                        val atBottom = !page.canScrollVertically(1)
                        // At either end, the page has nothing more to give.
                        if ((goingUp && atTop) || (!goingUp && atBottom)) {
                            view.parent?.requestDisallowInterceptTouchEvent(false)
                        }
                        lastTouchY[0] = event.y
                    }

                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL ->
                        view.parent?.requestDisallowInterceptTouchEvent(false)
                }
                false
            }
            addJavascriptInterface(bridge, "__pycmd_panel")
            // Without a chrome client a WebView answers `alert`, `confirm` and
            // `prompt` by ignoring them - and `confirm` then reads as "no",
            // silently, which is how a panel's "are you sure?" turns into a
            // button that does nothing. These are the app's dialogs, so a
            // panel asking a question looks like the rest of the app asking.
            webChromeClient = object : WebChromeClient() {
                override fun onJsAlert(
                    view: WebView?,
                    url: String?,
                    message: String?,
                    result: JsResult,
                ): Boolean {
                    AlertDialog.Builder(context)
                        .setMessage(message.orEmpty())
                        .setPositiveButton("OK") { _, _ -> result.confirm() }
                        .setOnCancelListener { result.cancel() }
                        .show()
                    return true
                }

                override fun onJsConfirm(
                    view: WebView?,
                    url: String?,
                    message: String?,
                    result: JsResult,
                ): Boolean {
                    AlertDialog.Builder(context)
                        .setMessage(message.orEmpty())
                        .setPositiveButton("Yes") { _, _ -> result.confirm() }
                        .setNegativeButton("No") { _, _ -> result.cancel() }
                        .setOnCancelListener { result.cancel() }
                        .show()
                    return true
                }

                override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                    // A panel's JavaScript error is otherwise invisible: the
                    // page just stops doing anything.
                    val where = "${message.sourceId().substringAfterLast('/')}" +
                        ":${message.lineNumber()}"
                    val text = "[${plugin.name}] ${message.message()}  ($where)"
                    when (message.messageLevel()) {
                        ConsoleMessage.MessageLevel.ERROR -> DebugLog.error("plugin", text)
                        ConsoleMessage.MessageLevel.WARNING -> DebugLog.warn("plugin", text)
                        else -> DebugLog.debug("plugin", text)
                    }
                    return true
                }
            }
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(
                    view: WebView?,
                    request: WebResourceRequest?,
                ): Boolean {
                    // A panel stays a panel. Anything trying to navigate is
                    // logged and refused rather than opening a browser the
                    // user did not ask for.
                    DebugLog.debug("plugin", "panel blocked navigation to ${request?.url}")
                    return true
                }
            }
        }
    }
}

/**
 * A custom plugin's own screen.
 *
 * The plugin supplies HTML; the app supplies a WebView, the house stylesheet
 * and a bridge with exactly four verbs - call, toast, log, close.
 */
@Composable
fun PluginPanelScreen(
    plugin: InstalledPlugin,
    viewModel: MainViewModel,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    /** Which page of the plugin to show; empty means its main panel. */
    panelFile: String = "",
) {
    Column(
        modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface)
                .padding(horizontal = 8.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onClose) {
                Icon(
                    PyIcons.ArrowBack,
                    contentDescription = "Back to the plugin list",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.width(2.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    plugin.tabTitle ?: plugin.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                )
                Text(
                    "${plugin.name} ${plugin.version}".trim(),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
            StatusChip("plugin", MaterialTheme.colorScheme.tertiary)
        }

        Divider()

        Box(Modifier.weight(1f).fillMaxWidth()) {
            PluginPanelView(plugin, viewModel, Modifier.fillMaxSize(), panelFile)
        }
    }
}

/**
 * The object a panel's JavaScript calls.
 *
 * Every method arrives on the WebView's bridge thread, so none of them touch
 * the view directly: the reply is posted back on the main thread once Python
 * has answered.
 *
 * It has a scope of its own rather than the composition's. The view it serves
 * outlives any one composition now - a section scrolled out of a list keeps
 * its page - and a bridge holding a cancelled scope would be a panel whose
 * buttons quietly stopped working the second time you looked at it.
 */
class PanelBridge(private val plugin: InstalledPlugin) {

    // Off the main thread. A reply can be large - the Creator plugin's block
    // catalogue is three hundred odd entries - and turning that back into a
    // string to hand to the page is real work that has no business happening
    // between two frames.
    private val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())

    @Volatile
    private var view: WebView? = null

    @Volatile
    private var host: MainViewModel? = null

    /** Points the bridge at the view model of whoever is showing it now. */
    fun bind(viewModel: MainViewModel) {
        host = viewModel
    }

    fun attach(webView: WebView) {
        view = webView
    }

    fun detach() {
        view = null
    }

    /** The panel is gone for good; nothing it asked for matters any more. */
    fun release() {
        view = null
        host = null
        scope.cancel()
    }

    @JavascriptInterface
    fun call(id: String, name: String, payload: String) {
        val model = host ?: return
        scope.launch {
            val reply = model.callPluginExport(plugin.id, name, payload)
            val ok = reply.optBoolean("ok")
            // Built here, on a background thread; the main thread only gets
            // handed the finished string.
            val script = "__pycmd_resolve(${JSONObject.quote(id)}, $ok, " +
                "${JSONObject.quote(reply.toString())})"
            withContext(Dispatchers.Main) {
                view?.evaluateJavascript(script, null)
            }
        }
    }

    @JavascriptInterface
    fun toast(message: String) {
        val model = host ?: return
        scope.launch { model.showToast(message.take(200)) }
    }

    @JavascriptInterface
    fun log(message: String) {
        DebugLog.info("plugin", "[${plugin.name}] ${message.take(400)}")
    }

    @JavascriptInterface
    fun close() {
        val model = host ?: return
        scope.launch { withContext(Dispatchers.Main) { model.closePluginPanel() } }
    }

    @JavascriptInterface
    fun manifest(): String = JSONObject()
        .put("id", plugin.id)
        .put("name", plugin.name)
        .put("version", plugin.version)
        .put("author", plugin.author)
        .toString()

    /** Pushes a message from the plugin's Python into its page. */
    fun deliver(body: String) {
        val target = view ?: return
        target.post {
            target.evaluateJavascript("__pycmd_message(${JSONObject.quote(body)})", null)
        }
    }
}
