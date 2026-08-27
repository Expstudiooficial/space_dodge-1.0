package com.expstudio.pycmd.util

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import java.io.File
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** A file or folder shown in the Files tab. */
data class WorkspaceEntry(
    val file: File,
    val name: String,
    val isDirectory: Boolean,
    val sizeBytes: Long,
    val modifiedMillis: Long,
) {
    val isPython: Boolean get() = !isDirectory && name.endsWith(".py", ignoreCase = true)

    val readableSize: String
        get() = when {
            isDirectory -> ""
            sizeBytes < 1024 -> "$sizeBytes B"
            sizeBytes < 1024 * 1024 -> "%.1f KB".format(Locale.US, sizeBytes / 1024.0)
            else -> "%.1f MB".format(Locale.US, sizeBytes / (1024.0 * 1024.0))
        }

    val readableDate: String
        get() = SimpleDateFormat("dd MMM yyyy HH:mm", Locale.US).format(Date(modifiedMillis))
}

/**
 * Everything file-related, kept inside the app's private storage.
 *
 * Staying in `filesDir` means no storage permissions, no scoped-storage
 * surprises, and the workspace travels with the app's backup.
 */
class Workspace(context: Context) {

    private val appContext = context.applicationContext
    val root: File = File(appContext.filesDir, "workspace").apply { mkdirs() }

    /** Guards against traversal walking out of the workspace. */
    fun isInsideWorkspace(file: File): Boolean {
        val canonicalRoot = runCatching { root.canonicalPath }.getOrNull() ?: return false
        val canonicalFile = runCatching { file.canonicalPath }.getOrNull() ?: return false
        return canonicalFile == canonicalRoot || canonicalFile.startsWith(canonicalRoot + File.separator)
    }

    fun relativePath(file: File): String {
        val prefix = root.absolutePath
        val path = file.absolutePath
        return when {
            path == prefix -> "/"
            path.startsWith(prefix + File.separator) -> path.removePrefix(prefix + File.separator)
            else -> file.name
        }
    }

    suspend fun list(directory: File): List<WorkspaceEntry> = withContext(Dispatchers.IO) {
        if (!isInsideWorkspace(directory) || !directory.isDirectory) return@withContext emptyList()
        directory.listFiles().orEmpty()
            .filterNot { it.name.startsWith(".") }
            .map {
                WorkspaceEntry(
                    file = it,
                    name = it.name,
                    isDirectory = it.isDirectory,
                    sizeBytes = if (it.isDirectory) 0L else it.length(),
                    modifiedMillis = it.lastModified(),
                )
            }
            // Folders first, then alphabetical - the ordering people expect.
            .sortedWith(compareByDescending<WorkspaceEntry> { it.isDirectory }.thenBy { it.name.lowercase() })
    }

    suspend fun read(file: File): Result<String> = withContext(Dispatchers.IO) {
        if (!isInsideWorkspace(file)) return@withContext Result.failure(IOException("Outside the workspace."))
        runCatching { file.readText() }
    }

    suspend fun write(file: File, content: String): Result<Unit> = withContext(Dispatchers.IO) {
        if (!isInsideWorkspace(file)) return@withContext Result.failure(IOException("Outside the workspace."))
        runCatching {
            file.parentFile?.mkdirs()
            file.writeText(content)
        }
    }

    suspend fun createFile(directory: File, name: String): Result<File> = withContext(Dispatchers.IO) {
        val safe = sanitise(name) ?: return@withContext Result.failure(IOException("Invalid name."))
        val target = File(directory, safe)
        if (!isInsideWorkspace(target)) return@withContext Result.failure(IOException("Outside the workspace."))
        if (target.exists()) return@withContext Result.failure(IOException("'$safe' already exists."))
        runCatching {
            target.parentFile?.mkdirs()
            if (!target.createNewFile()) throw IOException("Could not create '$safe'.")
            target
        }
    }

    suspend fun createFolder(directory: File, name: String): Result<File> = withContext(Dispatchers.IO) {
        val safe = sanitise(name) ?: return@withContext Result.failure(IOException("Invalid name."))
        val target = File(directory, safe)
        if (!isInsideWorkspace(target)) return@withContext Result.failure(IOException("Outside the workspace."))
        if (target.exists()) return@withContext Result.failure(IOException("'$safe' already exists."))
        runCatching {
            if (!target.mkdirs()) throw IOException("Could not create '$safe'.")
            target
        }
    }

    suspend fun rename(file: File, newName: String): Result<File> = withContext(Dispatchers.IO) {
        val safe = sanitise(newName) ?: return@withContext Result.failure(IOException("Invalid name."))
        val parent = file.parentFile ?: return@withContext Result.failure(IOException("No parent folder."))
        val target = File(parent, safe)
        if (!isInsideWorkspace(file) || !isInsideWorkspace(target)) {
            return@withContext Result.failure(IOException("Outside the workspace."))
        }
        if (target.exists()) return@withContext Result.failure(IOException("'$safe' already exists."))
        runCatching {
            if (!file.renameTo(target)) throw IOException("Could not rename '${file.name}'.")
            target
        }
    }

    suspend fun delete(file: File): Result<Unit> = withContext(Dispatchers.IO) {
        if (!isInsideWorkspace(file) || file.absolutePath == root.absolutePath) {
            return@withContext Result.failure(IOException("Refusing to delete that."))
        }
        runCatching {
            if (!file.deleteRecursively()) throw IOException("Could not delete '${file.name}'.")
        }
    }

    /**
     * Copies a document the user picked with the system file picker.
     *
     * The name comes from the provider rather than the URI: a content URI's
     * last segment is usually an opaque id like "msf:42", not a filename.
     */
    suspend fun importFrom(uri: Uri, directory: File): Result<File> =
        withContext(Dispatchers.IO) {
            val safe = sanitise(displayName(uri)) ?: "imported.py"
            val target = uniqueTarget(directory, safe)
            if (!isInsideWorkspace(target)) return@withContext Result.failure(IOException("Outside the workspace."))
            runCatching {
                appContext.contentResolver.openInputStream(uri).use { input ->
                    requireNotNull(input) { "Could not open the selected file." }
                    target.outputStream().use { output -> input.copyTo(output) }
                }
                target
            }
        }

    /** Asks the content provider what the file is called, with sane fallbacks. */
    private fun displayName(uri: Uri): String {
        val fromProvider = runCatching {
            appContext.contentResolver.query(
                uri,
                arrayOf(OpenableColumns.DISPLAY_NAME),
                null,
                null,
                null,
            )?.use { cursor ->
                val column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (column >= 0 && cursor.moveToFirst()) cursor.getString(column) else null
            }
        }.getOrNull()

        val name = fromProvider
            ?: uri.lastPathSegment?.substringAfterLast('/')?.substringAfterLast(':')
        return name?.takeIf { it.isNotBlank() } ?: "imported.py"
    }

    private fun uniqueTarget(directory: File, name: String): File {
        var candidate = File(directory, name)
        if (!candidate.exists()) return candidate
        val stem = name.substringBeforeLast('.', name)
        val extension = name.substringAfterLast('.', "")
        var index = 2
        while (candidate.exists() && index < 1000) {
            val suffix = if (extension.isEmpty()) "" else ".$extension"
            candidate = File(directory, "$stem-$index$suffix")
            index += 1
        }
        return candidate
    }

    /** Rejects separators and traversal; keeps names usable as Python modules. */
    private fun sanitise(name: String): String? {
        val trimmed = name.trim()
        if (trimmed.isEmpty() || trimmed == "." || trimmed == "..") return null
        val illegal = charArrayOf('/', 0x5C.toChar(), ':', '*', '?', '"', '<', '>', '|')
        if (trimmed.any { it in illegal || it.isISOControl() }) return null
        return trimmed.take(120)
    }

    /**
     * Drops the bundled examples in, and tops them up on later versions.
     *
     * Only files that are not already there are written, so an example the
     * user edited is never overwritten - but an example added in a newer
     * version does arrive, which a one-shot "does the folder exist" check
     * would have hidden from everyone who already had the app.
     */
    suspend fun seedExamples(): Int = withContext(Dispatchers.IO) {
        val examplesDir = File(root, "examples").apply { mkdirs() }
        runCatching { copyAssets("examples", examplesDir) }.getOrDefault(0)
    }

    private fun copyAssets(assetPath: String, target: File): Int {
        val children = appContext.assets.list(assetPath).orEmpty()
        if (children.isEmpty()) {
            if (target.exists()) return 0
            target.parentFile?.mkdirs()
            appContext.assets.open(assetPath).use { input ->
                target.outputStream().use { output -> input.copyTo(output) }
            }
            return 1
        }
        target.mkdirs()
        var copied = 0
        children.forEach { name ->
            copied += copyAssets("$assetPath/$name", File(target, name))
        }
        return copied
    }

    /**
     * Unpacks the plugins that ship in the APK into a scratch folder.
     *
     * They are not installed from here - the installer does that, from Python,
     * so a bundled plugin goes through exactly the same manifest checks as one
     * a user picked off their phone. Returns one folder per bundled plugin.
     */
    suspend fun stageBundledPlugins(): List<File> = withContext(Dispatchers.IO) {
        val names = runCatching { appContext.assets.list("plugins").orEmpty() }
            .getOrDefault(emptyArray())
        if (names.isEmpty()) return@withContext emptyList()

        val root = File(appContext.cacheDir, "bundled-plugins")
        root.deleteRecursively()
        root.mkdirs()
        names.mapNotNull { name ->
            val target = File(root, name)
            runCatching { copyAssets("plugins/$name", target) }
                .map { target }
                .getOrNull()
                ?.takeIf { File(it, "plugin.json").isFile }
        }
    }

    /** Text of a document that ships in the APK, for the in-app guides. */
    suspend fun readAsset(path: String): String? = withContext(Dispatchers.IO) {
        runCatching {
            appContext.assets.open(path).bufferedReader().use { it.readText() }
        }.getOrNull()
    }

    /**
     * Things in the workspace that could be a plugin.
     *
     * The system file picker cannot see the app's private storage, so a plugin
     * written inside PyCmd itself would be uninstallable without this.
     */
    suspend fun pluginCandidates(): List<File> = withContext(Dispatchers.IO) {
        val found = mutableListOf<File>()

        fun scan(directory: File, depth: Int) {
            if (depth > 2) return
            directory.listFiles()?.sortedBy { it.name.lowercase() }?.forEach { entry ->
                when {
                    entry.isDirectory && File(entry, "plugin.json").isFile -> found += entry
                    entry.isDirectory -> scan(entry, depth + 1)
                    entry.name.endsWith(".zip", true) -> found += entry
                    entry.name.endsWith(".py", true) -> {
                        // A plugin declares itself; every other script would
                        // only be noise in the list.
                        val head = runCatching {
                            entry.bufferedReader().use { reader ->
                                buildString {
                                    repeat(40) { append(reader.readLine() ?: return@buildString) }
                                }
                            }
                        }.getOrDefault("")
                        if ("PLUGIN" in head) found += entry
                    }
                }
            }
        }

        scan(root, 0)
        found.take(60)
    }
}
