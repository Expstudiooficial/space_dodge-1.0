package com.expstudio.pycmd.ui

import android.view.ViewGroup
import android.webkit.WebView
import com.expstudio.pycmd.util.DebugLog

/**
 * The WebViews plugin panels live in, kept alive between visits.
 *
 * A plugin's section is a card in a scrolling screen, which means it is a
 * `LazyColumn` item - and a `LazyColumn` throws items away the moment they
 * scroll off, then builds them again when they come back. With the WebView
 * built inside the item, scrolling past a section meant destroying a WebView
 * and making a new one: a hundred milliseconds of main-thread work each way,
 * the page loaded again, its JavaScript run again, and everything the person
 * had typed into it gone. Scroll up and down a screen with two open sections
 * and that is the app freezing, coming back, and freezing again.
 *
 * So the view outlives the item. It is detached from its parent rather than
 * destroyed, kept here by panel, and handed back the next time that panel is
 * shown - same page, same scroll position, same half-filled form, and no work
 * at all.
 *
 * ## What keeps this from being a leak
 *
 * A WebView holds a context, and holding one forever is how an activity is
 * kept alive after it should have gone. Three things bound it:
 *
 * * **A ceiling.** [LIMIT] panels; the least recently shown is destroyed to
 *   make room. Nobody has six plugin sections open at once, and if they do,
 *   the sixth costs what every panel used to cost.
 * * **Switching a plugin off** drops its panels ([forget]).
 * * **The screen going away** drops all of them ([clear]): `MainActivity`
 *   calls it after its composition has been torn down, and the view model
 *   calls it when it is cleared. Either is enough on its own; both is because
 *   an activity can be rebuilt while its view model lives on, and a panel
 *   holding a context that has been destroyed is worse than a panel that has
 *   to be built again.
 */
object PanelViews {

    private const val TAG = "plugin"

    /** How many panels stay warm. Past this, the oldest is let go. */
    private const val LIMIT = 5

    /** A panel that is not on screen: its view, and the bridge that serves it. */
    class Kept(val view: WebView, val bridge: PanelBridge)

    // Insertion-ordered, and re-inserted on every use, so the first entry is
    // always the one nobody has looked at for longest.
    private val kept = LinkedHashMap<String, Kept>()

    /**
     * The panel for [key], or null if there is not one yet.
     *
     * Detached from whatever it was in on the way out - a view can only have
     * one parent, and the caller is about to give it another - and woken up,
     * because a parked panel has its timers stopped.
     */
    @Synchronized
    fun take(key: String): Kept? {
        val panel = kept.remove(key) ?: return null
        (panel.view.parent as? ViewGroup)?.removeView(panel.view)
        runCatching { panel.view.onResume() }
        return panel
    }

    /**
     * Keeps a panel for [key], letting the oldest go if there is no room.
     *
     * Parked, not just stored: `onPause` stops the page's timers, and two of
     * the plugins that ship here poll on one. A section scrolled out of sight
     * that carried on asking Python for the server list every two seconds
     * would be a section that costs something to have ever opened.
     */
    @Synchronized
    fun keep(key: String, view: WebView, bridge: PanelBridge) {
        (view.parent as? ViewGroup)?.removeView(view)
        runCatching { view.onPause() }
        // The same panel can briefly exist twice - a section still composed
        // while its full-screen twin is opening - and the one being replaced
        // here has nobody left to destroy it if we only drop the reference.
        kept.remove(key)?.let { if (it.view !== view) destroy(it) }
        kept[key] = Kept(view, bridge)
        while (kept.size > LIMIT) {
            val oldest = kept.keys.firstOrNull() ?: break
            kept.remove(oldest)?.let { destroy(it) }
            DebugLog.debug(TAG, "let go of a panel to make room", oldest)
        }
    }

    /** Drops every panel belonging to a plugin - it has been switched off. */
    @Synchronized
    fun forget(pluginId: String) {
        val going = kept.keys.filter { it.substringBefore(':') == pluginId }
        going.forEach { key -> kept.remove(key)?.let { destroy(it) } }
    }

    /** Drops all of them. The activity is going. */
    @Synchronized
    fun clear() {
        kept.values.forEach(::destroy)
        kept.clear()
    }

    /** How many are being kept, for the debug screen and the tests. */
    @Synchronized
    fun size(): Int = kept.size

    private fun destroy(panel: Kept) {
        runCatching {
            panel.bridge.release()
            (panel.view.parent as? ViewGroup)?.removeView(panel.view)
            panel.view.stopLoading()
            panel.view.loadUrl("about:blank")
            panel.view.destroy()
        }
    }
}
