package com.expstudio.pycmd.ui

import android.annotation.SuppressLint
import android.view.ViewGroup
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
 * Shows a rendered HTML, Markdown or CSS file.
 *
 * The page is loaded with the file's own folder as the base URL, so a
 * stylesheet or an image sitting next to it resolves - a preview that shows
 * unstyled HTML because it could not find style.css is worse than none.
 *
 * JavaScript is on because plenty of pages need it to look right at all, and
 * the page is one the user just wrote. Navigation away from it is not: a link
 * to another site opens nothing here rather than turning the preview into an
 * unmarked browser.
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

    val webView = remember {
        WebView(context).apply {
            // Match the console's WebView: without explicit parameters the
            // view is added with wrap-content, and a page that sizes itself
            // against the viewport lays out against a strip a few hundred
            // pixels tall.
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.loadWithOverviewMode = true
            settings.useWideViewPort = true
            setBackgroundColor("#0B0F14".toColorInt())
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(
                    view: WebView?,
                    request: WebResourceRequest?,
                ): Boolean {
                    // Anything but the page itself is refused: a preview that
                    // can wander off to the open web is a browser in disguise.
                    DebugLog.debug("preview", "blocked navigation to ${request?.url}")
                    return true
                }
            }
        }
    }

    LaunchedEffect(page.html, page.baseDirectory) {
        webView.loadDataWithBaseURL(
            "file://${page.baseDirectory}",
            page.html,
            "text/html",
            "utf-8",
            null,
        )
    }

    DisposableEffect(Unit) {
        onDispose {
            webView.stopLoading()
            webView.destroy()
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
                    "Preview",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
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

        Divider()

        Box(Modifier.weight(1f).fillMaxWidth()) {
            AndroidView(factory = { webView }, modifier = Modifier.fillMaxSize())
        }
    }
}
