package com.expstudio.pycmd.plugins

import android.content.Context
import android.content.SharedPreferences
import com.expstudio.pycmd.util.DebugLog
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject

/**
 * One plugin the user installed themselves.
 *
 * Everything here comes from the plugin's own manifest, which means every
 * field is text somebody else wrote. It is shown, never trusted: the UI treats
 * a name as a label and nothing more.
 */
data class InstalledPlugin(
    val id: String,
    val name: String,
    val version: String,
    val author: String,
    val description: String,
    val panel: String?,
    val tabTitle: String?,
    /** One line under the tab's name in More. */
    val tabDescription: String,
    /** Absolute path of the image the plugin ships for its tab, if any. */
    val tabImage: String,
    val commands: List<PluginCommand>,
    val permissions: List<String>,
    val sizeBytes: Long,
    val files: List<String>,
    val loaded: Boolean,
    val error: String?,
    val broken: Boolean,
) {
    val hasPanel: Boolean get() = !panel.isNullOrEmpty()

    /** Whether this plugin asked for a place of its own in the More screen. */
    val hasTab: Boolean get() = !tabTitle.isNullOrEmpty() && hasPanel

    val readableSize: String
        get() = when {
            sizeBytes >= 1024 * 1024 -> "%.1f MB".format(sizeBytes / 1024.0 / 1024.0)
            sizeBytes >= 1024 -> "${sizeBytes / 1024} KB"
            else -> "$sizeBytes B"
        }

    companion object {
        fun from(json: JSONObject): InstalledPlugin {
            val tab = json.optJSONObject("tab")
            val commands = mutableListOf<PluginCommand>()
            json.optJSONArray("commands")?.let { array ->
                for (index in 0 until array.length()) {
                    val row = array.optJSONObject(index) ?: continue
                    val name = row.optString("name")
                    if (name.isNotEmpty()) {
                        commands += PluginCommand(name, row.optString("help"))
                    }
                }
            }
            val permissions = mutableListOf<String>()
            json.optJSONArray("permissions")?.let { array ->
                for (index in 0 until array.length()) permissions += array.optString(index)
            }
            val files = mutableListOf<String>()
            json.optJSONArray("files")?.let { array ->
                for (index in 0 until array.length()) files += array.optString(index)
            }

            return InstalledPlugin(
                id = json.optString("id"),
                name = json.optString("name").ifEmpty { json.optString("id") },
                version = json.optString("version"),
                author = json.optString("author"),
                description = json.optString("description"),
                panel = json.optString("panel").takeIf { it.isNotEmpty() },
                tabTitle = tab?.optString("title")?.takeIf { it.isNotEmpty() },
                tabDescription = tab?.optString("description").orEmpty(),
                tabImage = tab?.optString("image").orEmpty(),
                commands = commands,
                permissions = permissions,
                sizeBytes = json.optLong("size"),
                files = files,
                loaded = json.optBoolean("loaded"),
                error = json.optString("error").takeIf { it.isNotEmpty() },
                broken = json.optBoolean("broken"),
            )
        }
    }
}

data class PluginCommand(val name: String, val help: String)

/**
 * Which installed plugins the user has switched on.
 *
 * Only the on/off state lives here; the plugins themselves live on disk and
 * are listed by the Python side. Keeping the two apart means a plugin folder
 * can be deleted from under the app without leaving a dead switch behind.
 *
 * New plugins default to **off**. That is deliberate: installing something is
 * a decision to keep it, and running it is a second decision. A plugin that
 * started running the moment it landed would make the warning screen a lie.
 */
object CustomPlugins {

    private const val PREFS = "pycmd-custom-plugins"
    private const val KEY_ENABLED = "enabled"
    private const val TAG = "plugins"

    private var prefs: SharedPreferences? = null

    private val _enabled = MutableStateFlow<Set<String>>(emptySet())
    val enabled: StateFlow<Set<String>> = _enabled.asStateFlow()

    private val _installed = MutableStateFlow<List<InstalledPlugin>>(emptyList())
    val installed: StateFlow<List<InstalledPlugin>> = _installed.asStateFlow()

    fun init(context: Context) {
        val store = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        prefs = store
        _enabled.value = store.getStringSet(KEY_ENABLED, emptySet())?.toSet().orEmpty()
    }

    fun isOn(id: String): Boolean = id in _enabled.value

    fun setEnabled(id: String, on: Boolean) {
        val next = _enabled.value.toMutableSet().apply { if (on) add(id) else remove(id) }
        _enabled.value = next
        prefs?.edit()?.putStringSet(KEY_ENABLED, next)?.apply()
        DebugLog.info(TAG, "custom plugin $id ${if (on) "enabled" else "disabled"}")
    }

    /** Replaces the listing after an install, a removal, or a refresh. */
    fun setInstalled(plugins: List<InstalledPlugin>) {
        _installed.value = plugins
        // A plugin that is no longer on disk should not keep a switch.
        val alive = plugins.map { it.id }.toSet()
        val pruned = _enabled.value.filter { it in alive }.toSet()
        if (pruned != _enabled.value) {
            _enabled.value = pruned
            prefs?.edit()?.putStringSet(KEY_ENABLED, pruned)?.apply()
        }
    }

    fun forget(id: String) {
        setEnabled(id, false)
        _installed.value = _installed.value.filterNot { it.id == id }
    }

    /** The plugins that asked for a tab and are switched on. */
    fun tabs(): List<InstalledPlugin> =
        _installed.value.filter { it.id in _enabled.value && it.hasPanel && it.tabTitle != null }
}
