package com.expstudio.pycmd.plugins

import android.content.Context
import android.content.SharedPreferences
import com.expstudio.pycmd.util.DebugLog
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Where a plugin shows up in the list. */
enum class PluginGroup(val label: String) {
    KIT("The kit"),
    LANGUAGES("Languages"),
    TOOLS("Tools"),
    WORKFLOW("Workflow"),
}

/**
 * A built-in feature that can be switched on or off.
 *
 * Nothing is downloaded and no code is loaded at runtime: every plugin ships
 * inside the APK and its switch changes what the rest of the app does. That
 * keeps the whole thing auditable - a toggle can only reach behaviour that is
 * already in the binary.
 */
data class PluginSpec(
    val id: String,
    val name: String,
    val tagline: String,
    val description: String,
    val group: PluginGroup,
    val defaultEnabled: Boolean = false,
    /** Opens its own screen from the plugin list. */
    val screen: PluginScreen? = null,
    /** What Power Pack adds to this plugin when both are on. */
    val poweredUp: String? = null,
    /** Plugins that must be on for this one to do anything. */
    val requires: List<String> = emptyList(),
)

/** Plugins that have a screen of their own. */
enum class PluginScreen { JSON_TOOLS, TEXT_TOOLS, REGEX_LAB, HTTP_CLIENT, SEARCH }

object PluginIds {
    const val POLYGLOT_FILES = "polyglot-files"
    const val POLYGLOT_RUNNER = "polyglot-runner"
    const val POWER_PACK = "power-pack"

    const val SNIPPETS = "snippets"
    const val AUTOSAVE = "autosave"
    const val KEEP_AWAKE = "keep-awake"
    const val DOWNLOADER = "downloader"
    const val WORKSPACE_EXPORT = "workspace-export"
    const val SEARCH = "workspace-search"
    const val JSON_TOOLS = "json-tools"
    const val TEXT_TOOLS = "text-tools"
    const val REGEX_LAB = "regex-lab"
    const val HTTP_CLIENT = "http-client"

    /** Switching all three on is what the plugin list calls the full kit. */
    val CORE = listOf(POLYGLOT_FILES, POLYGLOT_RUNNER, POWER_PACK)
}

/**
 * The plugin registry.
 *
 * Enabled state lives in SharedPreferences so it survives a restart, and is
 * exposed as a flow because half the app reacts to it.
 */
object Plugins {

    private const val PREFS = "pycmd-plugins"
    private const val TAG = "plugins"

    val ALL: List<PluginSpec> = listOf(
        PluginSpec(
            id = PluginIds.POLYGLOT_FILES,
            name = "Polyglot Files",
            tagline = "Create and edit 25+ file types, not just .py",
            description = "Adds JavaScript, TypeScript, HTML, CSS, JSON, Markdown, C, C++, " +
                "Rust, Go, Java, Kotlin, SQL, YAML, TOML, XML, shell and more to the new-file " +
                "menu, each with a starter template. The editor highlights whichever language " +
                "the file is, and Files shows a coloured icon per type.",
            group = PluginGroup.KIT,
            defaultEnabled = true,
            poweredUp = "Adds README, LICENSE, .gitignore, Dockerfile, Makefile and package " +
                "manifests as one-tap templates.",
        ),
        PluginSpec(
            id = PluginIds.POLYGLOT_RUNNER,
            name = "Polyglot Runner",
            tagline = "Run more than Python",
            description = "Runs JavaScript in a real engine, previews HTML, CSS and Markdown " +
                "live, and executes shell commands. Servers can serve a site written in any " +
                "language. Compiled languages - C, Rust, Go, Java - can be written and served " +
                "but not built: there is no compiler on the device, and the app says so rather " +
                "than failing quietly.",
            group = PluginGroup.KIT,
            defaultEnabled = true,
            poweredUp = "Adds a console for JavaScript with its own scrollback, and lets a " +
                "preview reload itself as you edit.",
            requires = listOf(PluginIds.POLYGLOT_FILES),
        ),
        PluginSpec(
            id = PluginIds.POWER_PACK,
            name = "Power Pack",
            tagline = "Makes every other plugin do more",
            description = "The multiplier. Every plugin that says 'with Power Pack' below gains " +
                "its extra behaviour while this is on: more templates, more languages, extra " +
                "server options, richer tools and a bigger snippet library.",
            group = PluginGroup.KIT,
            defaultEnabled = true,
        ),

        PluginSpec(
            id = PluginIds.SNIPPETS,
            name = "Snippets",
            tagline = "Insert boilerplate for the language you are in",
            description = "A snippet bar in the editor that changes with the file type - a " +
                "Python main guard, an HTML skeleton, a fetch call, a CSS reset.",
            group = PluginGroup.LANGUAGES,
            defaultEnabled = true,
            poweredUp = "Roughly triples the snippet library and adds framework starters.",
        ),
        PluginSpec(
            id = PluginIds.HTTP_CLIENT,
            name = "API Tester",
            tagline = "Send HTTP requests and read the response",
            description = "A small REST client: method, URL, headers, body. Handy for poking " +
                "at a server you just started on the phone.",
            group = PluginGroup.TOOLS,
            screen = PluginScreen.HTTP_CLIENT,
            poweredUp = "Adds custom headers and saves the last request.",
        ),
        PluginSpec(
            id = PluginIds.JSON_TOOLS,
            name = "JSON Tools",
            tagline = "Format, validate and minify JSON",
            description = "Paste JSON, get it pretty-printed with the error location if it is " +
                "invalid. Works on the open editor file too.",
            group = PluginGroup.TOOLS,
            screen = PluginScreen.JSON_TOOLS,
            poweredUp = "Adds sorted keys and a JSON-to-Python-literal conversion.",
        ),
        PluginSpec(
            id = PluginIds.TEXT_TOOLS,
            name = "Text Tools",
            tagline = "Base64, hashes, URL encoding, case conversion",
            description = "The conversions you would otherwise open a website for, done on the " +
                "device with nothing leaving it.",
            group = PluginGroup.TOOLS,
            screen = PluginScreen.TEXT_TOOLS,
            poweredUp = "Adds SHA-1, SHA-512, hex and ROT13.",
        ),
        PluginSpec(
            id = PluginIds.REGEX_LAB,
            name = "Regex Lab",
            tagline = "Test a pattern against text as you type",
            description = "Live match count, highlighted matches and capture groups, using " +
                "Python's own re module so it behaves exactly like your script will.",
            group = PluginGroup.TOOLS,
            screen = PluginScreen.REGEX_LAB,
            poweredUp = "Adds named groups, a substitution preview and the common flags.",
        ),
        PluginSpec(
            id = PluginIds.SEARCH,
            name = "Workspace Search",
            tagline = "Find text across every file",
            description = "Searches the whole workspace and takes you to the file. Faster than " +
                "opening ten files to find where you wrote something.",
            group = PluginGroup.WORKFLOW,
            screen = PluginScreen.SEARCH,
            poweredUp = "Adds case sensitivity, whole-word and regex matching.",
        ),
        PluginSpec(
            id = PluginIds.DOWNLOADER,
            name = "Downloader",
            tagline = "Pull a file from a URL into the workspace",
            description = "Paste a link and it lands in Downloads, ready to open in the editor " +
                "or serve. Useful for grabbing a script, a dataset or a stylesheet.",
            group = PluginGroup.WORKFLOW,
            defaultEnabled = true,
            poweredUp = "Shows download progress and keeps a history you can re-download from.",
        ),
        PluginSpec(
            id = PluginIds.WORKSPACE_EXPORT,
            name = "Workspace Export",
            tagline = "Zip the whole workspace into Downloads",
            description = "One tap to package everything you have written into a single .zip - " +
                "for backing up, or moving it to a computer.",
            group = PluginGroup.WORKFLOW,
            defaultEnabled = true,
            poweredUp = "Adds exporting a single folder, and importing a zip back in.",
        ),
        PluginSpec(
            id = PluginIds.AUTOSAVE,
            name = "Autosave",
            tagline = "Never lose the editor buffer",
            description = "Saves the open file a couple of seconds after you stop typing, so " +
                "switching tabs or getting a phone call cannot cost you work.",
            group = PluginGroup.WORKFLOW,
            defaultEnabled = true,
        ),
        PluginSpec(
            id = PluginIds.KEEP_AWAKE,
            name = "Keep Awake",
            tagline = "Hold the CPU on while a server runs",
            description = "Takes a wake lock for as long as something is listening, so a server " +
                "keeps answering after the screen turns off. Costs battery, which is why it is " +
                "a switch.",
            group = PluginGroup.WORKFLOW,
        ),
    )

    private val byId = ALL.associateBy { it.id }

    private var prefs: SharedPreferences? = null

    private val _enabled = MutableStateFlow(ALL.filter { it.defaultEnabled }.map { it.id }.toSet())
    val enabled: StateFlow<Set<String>> = _enabled.asStateFlow()

    fun init(context: Context) {
        val store = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        prefs = store
        val stored = ALL.filter { spec ->
            store.getBoolean(spec.id, spec.defaultEnabled)
        }.map { it.id }.toSet()
        _enabled.value = stored
        DebugLog.info(TAG, "${stored.size} of ${ALL.size} plugins enabled", stored.sorted().joinToString(", "))
    }

    fun spec(id: String): PluginSpec? = byId[id]

    /**
     * Whether a plugin's behaviour should apply.
     *
     * A plugin whose prerequisites are off is inert even when its own switch is
     * on, so callers never have to check the chain themselves.
     */
    fun isOn(id: String): Boolean {
        if (id !in _enabled.value) return false
        val spec = byId[id] ?: return false
        return spec.requires.all { it in _enabled.value }
    }

    /** True when Power Pack is on as well - the "and more with Power Pack" case. */
    fun isPoweredUp(id: String): Boolean = isOn(id) && isOn(PluginIds.POWER_PACK)

    fun setEnabled(id: String, on: Boolean) {
        val spec = byId[id] ?: return
        val next = _enabled.value.toMutableSet().apply { if (on) add(id) else remove(id) }
        _enabled.value = next
        prefs?.edit()?.putBoolean(id, on)?.apply()
        DebugLog.info(TAG, "${spec.name} ${if (on) "enabled" else "disabled"}")
    }

    /** All three of the kit are on. */
    fun fullKit(): Boolean = PluginIds.CORE.all { it in _enabled.value }

    fun enableAll() {
        ALL.forEach { setEnabled(it.id, true) }
    }

    fun resetToDefaults() {
        ALL.forEach { setEnabled(it.id, it.defaultEnabled) }
    }
}
