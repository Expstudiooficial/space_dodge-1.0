package com.expstudio.pycmd.music

import android.content.Context
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.provider.OpenableColumns
import com.expstudio.pycmd.util.DebugLog
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Getting a file off the device and into the library.
 *
 * The picker hands back a content URI, which is a permission to read
 * something for as long as the process remembers it - not a file, and not
 * something that will still resolve next week. A library built on those would
 * be a library that empties itself, so every import is a copy: the bytes land
 * in the app's own storage and the URI is never referred to again.
 *
 * Once the copy is here, the file itself is asked what it is. Almost every
 * audio file carries a title and an artist, and reading them beats naming
 * everything after a filename like `AUD-20240113-WA0002.m4a`.
 */
object MusicImport {

    private const val TAG = "music"

    /** Big enough for an album-length file, small enough to notice a mistake. */
    private const val MAX_BYTES = 512L * 1024 * 1024

    /** Never fill the phone: stop if the copy would leave less than this. */
    private const val KEEP_FREE = 200L * 1024 * 1024

    /** How much to copy between checks of how much room is left. */
    private const val LOOK_EVERY = 8L * 1024 * 1024

    /** What was imported, and what the file says about itself. */
    data class Imported(
        val file: File,
        val title: String,
        val artist: String,
        val duration: Long,
        val bytes: Long,
    )

    suspend fun copy(context: Context, uri: Uri, into: File): Result<Imported> =
        withContext(Dispatchers.IO) {
            runCatching {
                into.mkdirs()
                val name = displayName(context, uri) ?: "track"
                val target = free(into, name)

                var written = 0L
                try {
                    context.contentResolver.openInputStream(uri).use { input ->
                        requireNotNull(input) { "that file could not be opened" }
                        target.outputStream().use { output ->
                            written = pour(input, output, into)
                        }
                    }
                } catch (error: Throwable) {
                    // A half-copied file is not a track, and leaving it there
                    // would leave the library holding a file that cannot play.
                    target.delete()
                    throw error
                }

                if (written <= 0) {
                    target.delete()
                    throw IOException("that file is empty")
                }

                val facts = describe(target)
                DebugLog.debug(TAG, "imported ${target.name}", "$written bytes")
                Imported(
                    file = target,
                    title = facts.first,
                    artist = facts.second,
                    duration = facts.third,
                    bytes = written,
                )
            }
        }

    /**
     * Copies with both ceilings applied: the file's size, and the disk's.
     *
     * Free space is re-read every few megabytes rather than once at the start,
     * because the number that matters is the one during the copy - something
     * else on the phone can be filling the disk at the same time, and a copy
     * that runs a device out of storage takes more than this app down with it.
     */
    private fun pour(input: InputStream, output: OutputStream, into: File): Long {
        val buffer = ByteArray(128 * 1024)
        var total = 0L
        var sinceLook = 0L
        while (true) {
            val read = input.read(buffer)
            if (read <= 0) break
            total += read
            if (total > MAX_BYTES) {
                throw IOException("that file is larger than ${MAX_BYTES / (1024 * 1024)} MB")
            }
            sinceLook += read
            if (sinceLook >= LOOK_EVERY) {
                sinceLook = 0
                val free = runCatching { into.usableSpace }.getOrDefault(Long.MAX_VALUE)
                if (free < KEEP_FREE) {
                    throw IOException("there is not enough room on the phone for that")
                }
            }
            output.write(buffer, 0, read)
        }
        output.flush()
        return total
    }

    /** Title, artist and length as the file itself reports them. */
    private fun describe(file: File): Triple<String, String, Long> {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(file.absolutePath)
            val title = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_TITLE)
                ?.trim()
                .orEmpty()
            val artist = (
                retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ARTIST)
                    ?: retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ALBUMARTIST)
                )?.trim().orEmpty()
            val duration = retriever
                .extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull() ?: 0L
            Triple(title, artist, duration)
        } catch (error: RuntimeException) {
            // A file with no metadata, or one this phone's codecs do not know,
            // is still a file worth keeping: the name it came with will do.
            DebugLog.debug(TAG, "no metadata in ${file.name}", error.message.orEmpty())
            Triple("", "", 0L)
        } finally {
            runCatching { retriever.release() }
        }
    }

    /** A name inside [folder] that is not taken, keeping the extension. */
    private fun free(folder: File, name: String): File {
        val safe = sanitise(name)
        val stem = safe.substringBeforeLast('.', safe).take(80).ifBlank { "track" }
        val extension = safe.substringAfterLast('.', "").take(12)
        val suffix = if (extension.isBlank()) "" else ".$extension"

        var candidate = File(folder, "$stem$suffix")
        var index = 2
        while (candidate.exists()) {
            candidate = File(folder, "$stem-$index$suffix")
            index += 1
        }
        return candidate
    }

    /** Strips anything from a provider's name that is not a file name. */
    private fun sanitise(name: String): String {
        val trimmed = name.trim().substringAfterLast('/').substringAfterLast('\\')
        if (trimmed == "." || trimmed == "..") return "track"
        val illegal = charArrayOf(':', '*', '?', '"', '<', '>', '|')
        return trimmed
            .filterNot { it in illegal || it.isISOControl() }
            .take(120)
            .ifBlank { "track" }
    }

    private fun displayName(context: Context, uri: Uri): String? {
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
        return raw?.takeIf { it.isNotBlank() }
    }
}
