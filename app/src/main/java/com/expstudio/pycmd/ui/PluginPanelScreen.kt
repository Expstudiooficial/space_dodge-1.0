package com.expstudio.pycmd.ui

import android.annotation.SuppressLint
import android.webkit.JavascriptInterface
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
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
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * A custom plugin's own screen.
 *
 * The plugin supplies HTML; the app supplies a WebView, the house stylesheet
 * and a bridge with exactly four verbs - call, toast, log, close. A panel can
 * therefore do anything a web page can do and nothing an app can do, which is
 * the right side of the line to keep it on: the dangerous half of a plugin is
 * its Python, and that is what the install warning is about.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun PluginPanelScreen(
    plugin: InstalledPlugin,
    viewModel: MainViewModel,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    val bridge = remember(plugin.id) { PanelBridge(plugin, viewModel, scope) }

    val webView = remember(plugin.id) {
        WebView(context).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            // A panel loads its own images and stylesheets from the plugin's
            // folder, which is inside the app's private storage.
            settings.allowFileAccess = true
            settings.allowContentAccess = false
            setBackgroundColor("#0B0F14".toColorInt())
            addJavascriptInterface(bridge, "__pycmd_panel")
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

    DisposableEffect(webView) {
        bridge.attach(webView)
        onDispose {
            bridge.detach()
            webView.stopLoading()
            webView.destroy()
        }
    }

    LaunchedEffect(plugin.id) {
        val html = viewModel.pluginPanelHtml(plugin.id)
        val base = "file://${PythonEngine.pluginDirectory(plugin.id).absolutePath}/"
        webView.loadDataWithBaseURL(base, html, "text/html", "utf-8", null)
    }

    // A plugin can push to its panel while it is open.
    LaunchedEffect(plugin.id) {
        PythonEngine.pluginMessages.collect { (id, body) ->
            if (id == plugin.id) bridge.deliver(body)
        }
    }

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
            AndroidView(factory = { webView }, modifier = Modifier.fillMaxSize())
        }
    }
}

/**
 * The object a panel's JavaScript calls.
 *
 * Every method arrives on the WebView's bridge thread, so none of them touch
 * the view directly: the reply is posted back on the main thread once Python
 * has answered.
 */
private class PanelBridge(
    private val plugin: InstalledPlugin,
    private val viewModel: MainViewModel,
    private val scope: CoroutineScope,
) {
    @Volatile
    private var view: WebView? = null

    fun attach(webView: WebView) {
        view = webView
    }

    fun detach() {
        view = null
    }

    @JavascriptInterface
    fun call(id: String, name: String, payload: String) {
        scope.launch {
            val reply = viewModel.callPluginExport(plugin.id, name, payload)
            val ok = reply.optBoolean("ok")
            withContext(Dispatchers.Main) {
                view?.evaluateJavascript(
                    "__pycmd_resolve(${JSONObject.quote(id)}, $ok, " +
                        "${JSONObject.quote(reply.toString())})",
                    null,
                )
            }
        }
    }

    @JavascriptInterface
    fun toast(message: String) {
        scope.launch { viewModel.showToast(message.take(200)) }
    }

    @JavascriptInterface
    fun log(message: String) {
        DebugLog.info("plugin", "[${plugin.name}] ${message.take(400)}")
    }

    @JavascriptInterface
    fun close() {
        scope.launch { withContext(Dispatchers.Main) { viewModel.closePluginPanel() } }
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
