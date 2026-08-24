package com.expstudio.pycmd.ui

import android.annotation.SuppressLint
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.graphics.toColorInt
import com.expstudio.pycmd.python.PreviewPage
import com.expstudio.pycmd.util.DebugLog

/**
 * Shows a page the way a browser would.
 *
 * The page comes off a loopback HTTP server rooted at its own folder, so it is
 * a real site rather than a document: scripts run, stylesheets and images load
 * by relative path, `fetch` works, ES modules load, and a link to another page
 * of the same site goes there. A `file://` preview can do none of that, which
 * is why one that looked like plain text with dead buttons was the old
 * behaviour rather than a bug in any one place.
 *
 * Whatever the page logs or throws is copied into the app's debug console:
 * on a phone there is no other way to see a JavaScript error.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun PreviewScreen(
    page: PreviewPage,
    onClose: () -> Unit,
    onReload: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    var progress by remember { mutableIntStateOf(0) }
    var currentUrl by remember(page.url) { mutableStateOf(page.url) }
    var problems by remember(page.url) { mutableIntStateOf(0) }

    val webView = remember {
        WebView(context).apply {
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.databaseEnabled = true
            settings.loadWithOverviewMode = true
            settings.useWideViewPort = true
            settings.builtInZoomControls = true
            settings.displayZoomControls = false
            settings.mediaPlaybackRequiresUserGesture = false
            // Only matters for the fallback path, when no socket was free and
            // the page is loaded straight from disk.
            settings.allowFileAccess = true
            settings.allowContentAccess = false
            setBackgroundColor("#0B0F14".toColorInt())
        }
    }

    DisposableEffect(webView) {
        onDispose {
            webView.stopLoading()
            webView.loadUrl("about:blank")
            webView.destroy()
        }
    }

    LaunchedEffect(webView, page.origin) {
        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                progress = newProgress
            }

            override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                val where = "${message.sourceId().substringAfterLast('/')}:${message.lineNumber()}"
                val text = "${message.message()}  ($where)"
                when (message.messageLevel()) {
                    ConsoleMessage.MessageLevel.ERROR -> {
                        problems += 1
                        DebugLog.error("preview", text)
                    }
                    ConsoleMessage.MessageLevel.WARNING -> DebugLog.warn("preview", text)
                    else -> DebugLog.debug("preview", text)
                }
                return true
            }
        }

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?,
            ): Boolean {
                val target = request?.url?.toString().orEmpty()
                // Inside the previewed site, follow the link - that is what
                // makes a multi-page site previewable at all. Anywhere else,
                // refuse: this is a preview, not a browser.
                if (page.origin.isNotEmpty() && target.startsWith(page.origin)) {
                    currentUrl = target
                    return false
                }
                DebugLog.info("preview", "blocked a link out of the preview", target)
                return true
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                progress = 100
                if (url != null && url != "about:blank") currentUrl = url
            }

            override fun onReceivedError(
                view: WebView,
                request: WebResourceRequest,
                error: WebResourceError,
            ) {
                if (request.url.lastPathSegment == "favicon.ico") return
                // A missing stylesheet is the single most common reason a
                // preview looks wrong, and the only place it can be reported.
                problems += 1
                DebugLog.error(
                    "preview",
                    "could not load ${request.url.lastPathSegment}",
                    "${error.errorCode}: ${error.description}",
                )
            }

            override fun onReceivedHttpError(
                view: WebView,
                request: WebResourceRequest,
                response: WebResourceResponse,
            ) {
                // Every browser asks for a favicon and almost no page has one.
                // Reporting that as a problem would put a red badge on a page
                // with nothing wrong with it.
                if (request.url.lastPathSegment == "favicon.ico") return
                if (response.statusCode >= 400) {
                    problems += 1
                    DebugLog.error(
                        "preview",
                        "${response.statusCode} for ${request.url.lastPathSegment}",
                        request.url.toString(),
                    )
                }
            }
        }
    }

    LaunchedEffect(page.url, page.html) {
        progress = 0
        problems = 0
        if (page.served && page.url.isNotEmpty()) {
            webView.loadUrl(page.url)
        } else {
            webView.loadDataWithBaseURL(
                "file://${page.baseDirectory}",
                page.html,
                "text/html",
                "utf-8",
                null,
            )
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
                    contentDescription = "Close the preview",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.width(2.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    page.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                )
                Text(
                    when {
                        !page.served -> "Preview - served from disk"
                        currentUrl.isNotEmpty() -> currentUrl.substringAfter("://")
                        else -> "Preview"
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
            if (problems > 0) {
                StatusChip("$problems", MaterialTheme.colorScheme.error)
                Spacer(Modifier.width(4.dp))
            }
            if (webView.canGoBack()) {
                IconButton(onClick = { webView.goBack() }) {
                    Icon(
                        PyIcons.Undo,
                        contentDescription = "Back inside the page",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(19.dp),
                    )
                }
            }
            IconButton(onClick = onReload) {
                Icon(
                    PyIcons.RestartAlt,
                    contentDescription = "Reload",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(20.dp),
                )
            }
        }

        if (progress in 1..99) {
            LinearProgressIndicator(
                progress = { progress / 100f },
                modifier = Modifier.fillMaxWidth().height(2.dp),
                color = MaterialTheme.colorScheme.primary,
            )
        } else {
            Divider()
        }

        Box(Modifier.weight(1f).fillMaxWidth()) {
            AndroidView(factory = { webView }, modifier = Modifier.fillMaxSize())
        }
    }
}
