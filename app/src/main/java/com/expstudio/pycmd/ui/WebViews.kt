package com.expstudio.pycmd.ui

import android.annotation.SuppressLint
import android.content.Context
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.graphics.toColorInt
import org.json.JSONObject

private const val ASSET_BASE = "file:///android_asset/web/"

/** Must match --bg in console.css and editor.css, or the page flashes on load. */
private const val WEB_BACKGROUND = "#0B0F14"

/**
 * Callbacks the JS layer can reach.
 *
 * The lambdas are held in mutable fields rather than captured at construction:
 * the WebView outlives any single composition, so the bridge has to be able to
 * point at whatever the current composable wants.
 */
class PyBridge {
    var editorChangedHandler: (String) -> Unit = {}
    var cursorMovedHandler: (Int, Int) -> Unit = { _, _ -> }
    var editorReadyHandler: () -> Unit = {}

    // Every method below runs on the WebView's JS thread, never the main
    // thread, so the handlers must not touch views directly.
    @JavascriptInterface
    fun onEditorChanged(text: String) = editorChangedHandler(text)

    @JavascriptInterface
    fun onCursorMoved(line: Int, column: Int) = cursorMovedHandler(line, column)

    @JavascriptInterface
    fun onEditorReady() = editorReadyHandler()
}

/** A WebView plus the bridge wired into it. */
class WebHost(val webView: WebView, val bridge: PyBridge) {

    private var loaded = false

    /**
     * Which document the page currently holds.
     *
     * Lives on the host, not in a composable's `remember`: the WebView outlives
     * the composition, and re-pushing the same document on every tab switch
     * would throw the caret back to the top of the file.
     */
    var loadedEpoch: Long = -1L

    fun load(page: String) {
        if (loaded) return
        loaded = true
        webView.loadUrl(ASSET_BASE + page)
    }

    /** Fire-and-forget JS; results are never needed and errors are logged by the WebView. */
    fun eval(script: String) {
        webView.post { webView.evaluateJavascript(script, null) }
    }
}

@SuppressLint("SetJavaScriptEnabled")
private fun createWebView(context: Context, bridge: PyBridge): WebView =
    WebView(context).apply {
        // Without this the view is added with wrap-content and lays the page
        // out in a strip a couple of hundred pixels tall: the page's `height:
        // 100%` then resolves against that, and the console scrolls almost all
        // of its output off the top of a viewport that is barely one line high.
        layoutParams = ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT,
        )
        setBackgroundColor(WEB_BACKGROUND.toColorInt())
        // No remote content is ever loaded, so the usual JS caveats do not
        // apply: every page is an asset shipped inside the APK.
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        // Assets live behind file:///android_asset, so file access stays on;
        // cross-origin reads from a file URL remain disabled by default.
        settings.allowFileAccess = true
        settings.allowContentAccess = false
        settings.cacheMode = android.webkit.WebSettings.LOAD_NO_CACHE
        settings.textZoom = 100
        isVerticalScrollBarEnabled = true
        isHorizontalScrollBarEnabled = false
        overScrollMode = WebView.OVER_SCROLL_NEVER
        addJavascriptInterface(bridge, "PyBridge")
    }

@Composable
fun rememberWebHost(page: String): WebHost {
    val context = LocalContext.current
    return remember(page) {
        val bridge = PyBridge()
        // The activity context is what the soft keyboard and text-selection
        // handles need; the host dies with the composition, so it cannot leak
        // past the activity.
        WebHost(createWebView(context, bridge), bridge).also { it.load(page) }
    }
}

/**
 * Renders a hoisted WebView.
 *
 * The instance is created once and survives tab switches, so console history
 * and editor scroll position are not thrown away every time the user looks at
 * something else. Detaching from the previous parent is what makes reuse legal.
 */
@Composable
fun PersistentWebView(host: WebHost, modifier: Modifier = Modifier) {
    AndroidView(
        factory = {
            (host.webView.parent as? ViewGroup)?.removeView(host.webView)
            host.webView
        },
        modifier = modifier,
    )
}

/** Quotes a Kotlin string for safe interpolation into a JS expression. */
fun jsString(value: String): String = JSONObject.quote(value)
