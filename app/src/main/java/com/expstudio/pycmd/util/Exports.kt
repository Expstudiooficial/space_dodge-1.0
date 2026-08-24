package com.expstudio.pycmd.util

import android.content.Context
import android.net.Uri
import java.io.File
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Writes a file we hold onto wherever the user pointed the system picker.
 *
 * The mirror image of [Imports]. An app's own folders are invisible to the
 * rest of the phone, so a zip sitting in Downloads is not a file the user can
 * hand to a computer until it has been copied out through the picker - which
 * is the only way to write into shared storage without asking for a
 * storage permission at all.
 */
object Exports {

    private const val TAG = "export"

    /** Copies [source] to the picked destination. Returns the byte count. */
    suspend fun saveTo(context: Context, source: File, target: Uri): Result<Long> =
        withContext(Dispatchers.IO) {
            runCatching {
                if (!source.isFile) throw IOException("${source.name} is not a file")
                var bytes = 0L
                context.contentResolver.openOutputStream(target, "wt").use { output ->
                    requireNotNull(output) { "could not write there" }
                    source.inputStream().use { input ->
                        bytes = input.copyTo(output)
                    }
                    output.flush()
                }
                DebugLog.debug(TAG, "saved ${source.name} to the device", "$bytes bytes")
                bytes
            }.onFailure { DebugLog.warn(TAG, "could not save ${source.name}", it.message.orEmpty()) }
        }

    /** The MIME type the picker should offer for a name, best effort. */
    fun mimeFor(name: String): String = when (name.substringAfterLast('.', "").lowercase()) {
        "zip" -> "application/zip"
        "json" -> "application/json"
        "html", "htm" -> "text/html"
        "css" -> "text/css"
        "js" -> "text/javascript"
        "csv" -> "text/csv"
        "md", "txt", "log", "py", "c", "go", "rs" -> "text/plain"
        "png" -> "image/png"
        "jpg", "jpeg" -> "image/jpeg"
        "svg" -> "image/svg+xml"
        else -> "application/octet-stream"
    }
}
