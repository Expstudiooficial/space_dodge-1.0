package com.expstudio.pycmd.util

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.documentfile.provider.DocumentFile
import java.io.File
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Copies things the user picked from outside the app onto our own disk.
 *
 * Android hands an app a content URI, not a path, and a folder arrives as a
 * tree of document URIs that only the picker can resolve. Everything
 * downstream - the plugin installer, the workspace, the zip reader - wants a
 * real file, so this is where the translation happens, once.
 *
 * Everything is bounded. A picker points at whatever the user chose, and "the
 * whole of Downloads" is one tap away from "one small plugin".
 */
object Imports {

    private const val TAG = "import"
    private const val MAX_BYTES = 64L * 1024 * 1024
    private const val MAX_FILES = 3000
    private const val MAX_DEPTH = 12
    private const val STALE_AFTER_MS = 10 * 60 * 1000L

    /** What was copied, and how big it turned out to be. */
    data class Staged(val root: File, val name: String, val files: Int, val bytes: Long)

    /** Copies a single picked file into a scratch folder. */
    suspend fun stageFile(context: Context, uri: Uri): Result<Staged> =
        withContext(Dispatchers.IO) {
            runCatching {
                val name = displayName(context, uri) ?: "imported"
                val root = scratch(context, name)
                val target = File(root, name)
                var bytes = 0L
                context.contentResolver.openInputStream(uri).use { input ->
                    requireNotNull(input) { "could not open that file" }
                    target.outputStream().use { output ->
                        bytes = copyBounded(input, output, MAX_BYTES)
                    }
                }
                DebugLog.debug(TAG, "staged $name", "$bytes bytes")
                Staged(target, name, 1, bytes)
            }
        }

    /**
     * Copies a picked folder, recursively.
     *
     * The picker's tree API is slow - one query per directory - so this is
     * firmly a background job, and the caller shows progress while it runs.
     */
    suspend fun stageTree(context: Context, treeUri: Uri): Result<Staged> =
        withContext(Dispatchers.IO) {
            runCatching {
                val source = DocumentFile.fromTreeUri(context, treeUri)
                    ?: throw IOException("that folder could not be opened")
                val name = source.name?.takeIf { it.isNotBlank() } ?: "folder"
                val root = File(scratch(context, name), sanitise(name))
                root.mkdirs()

                val counter = Counter()
                copyTree(context, source, root, counter, 0)
                if (counter.files == 0) throw IOException("that folder has no files in it")
                DebugLog.debug(TAG, "staged folder $name", "${counter.files} files, ${counter.bytes} bytes")
                Staged(root, name, counter.files, counter.bytes)
            }
        }

    private class Counter {
        var files = 0
        var bytes = 0L
    }

    private fun copyTree(
        context: Context,
        source: DocumentFile,
        target: File,
        counter: Counter,
        depth: Int,
    ) {
        if (depth > MAX_DEPTH) throw IOException("that folder is nested more than $MAX_DEPTH deep")

        for (child in source.listFiles()) {
            val childName = sanitise(child.name ?: continue)
            if (childName.isEmpty() || childName.startsWith(".")) continue

            if (child.isDirectory) {
                val folder = File(target, childName)
                folder.mkdirs()
                copyTree(context, child, folder, counter, depth + 1)
                continue
            }

            counter.files += 1
            if (counter.files > MAX_FILES) {
                throw IOException("that folder holds more than $MAX_FILES files")
            }
            val destination = File(target, childName)
            context.contentResolver.openInputStream(child.uri).use { input ->
                if (input == null) return@use
                destination.outputStream().use { output ->
                    counter.bytes += copyBounded(input, output, MAX_BYTES - counter.bytes)
                }
            }
        }
    }

    private fun copyBounded(
        input: java.io.InputStream,
        output: java.io.OutputStream,
        limit: Long,
    ): Long {
        if (limit <= 0) throw IOException("that is larger than ${MAX_BYTES / 1024 / 1024} MB")
        val buffer = ByteArray(64 * 1024)
        var total = 0L
        while (true) {
            val read = input.read(buffer)
            if (read <= 0) break
            total += read
            if (total > limit) throw IOException("that is larger than ${MAX_BYTES / 1024 / 1024} MB")
            output.write(buffer, 0, read)
        }
        return total
    }

    /** A fresh folder under the cache, so a failed import leaves nothing behind. */
    private fun scratch(context: Context, label: String): File {
        val root = File(context.cacheDir, "imports")
        root.mkdirs()
        // Clear out what an earlier import abandoned, but leave anything
        // recent alone: two imports can be in flight at once, and wiping the
        // folder wholesale would pull the first one's files out from under it.
        val stale = System.currentTimeMillis() - STALE_AFTER_MS
        root.listFiles()?.filter { it.lastModified() < stale }?.forEach { it.deleteRecursively() }
        val folder = File(root, "${System.currentTimeMillis()}-${sanitise(label).take(24)}")
        folder.mkdirs()
        return folder
    }

    fun displayName(context: Context, uri: Uri): String? {
        val fromProvider = runCatching {
            context.contentResolver.query(
                uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null,
            )?.use { cursor ->
                val column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (column >= 0 && cursor.moveToFirst()) cursor.getString(column) else null
            }
        }.getOrNull()

        val raw = fromProvider
            ?: uri.lastPathSegment?.substringAfterLast('/')?.substringAfterLast(':')
        return raw?.takeIf { it.isNotBlank() }?.let { sanitise(it) }
    }

    /** Strips separators and traversal from a name a content provider gave us. */
    private fun sanitise(name: String): String {
        val trimmed = name.trim().substringAfterLast('/').substringAfterLast('\\')
        if (trimmed == "." || trimmed == "..") return ""
        val illegal = charArrayOf(':', '*', '?', '"', '<', '>', '|')
        return trimmed.filterNot { it in illegal || it.isISOControl() }.take(120)
    }
}
