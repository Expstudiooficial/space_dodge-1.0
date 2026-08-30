package com.expstudio.pycmd.util

import android.content.Context
import com.expstudio.pycmd.R

/**
 * The app's own name, in one place, and a check that it is still there.
 *
 * Forks are welcome and the guide says so. The one condition is that PyCmd
 * stays named in the app it came from - so the name is a constant that the
 * screens actually draw from, rather than a string typed into each of them,
 * and start-up refuses to continue if it has been emptied out.
 *
 * ## Why it cannot go off by accident
 *
 * Everything it looks at is compiled into the APK and cannot vary at runtime:
 * a string resource and a constant in this file. No network, no clock, no
 * device state, nothing a user can change. A build either has the name in it
 * or does not, and which one it is was settled when it was built.
 *
 * The check is also **contains, not equals**: `PyCmd`, `PyCmd Neo`, `Foo
 * (based on PyCmd)` and `pycmd` all pass. Only removing the name entirely
 * fails. And `tools/test_branding.py` asserts the same conditions in the test
 * suite, so a build that would trip this fails on a laptop rather than on
 * somebody's phone.
 *
 * If it ever does fire, the message says exactly what is missing and where to
 * put it back. A tripwire that leaves people guessing would be worse than no
 * tripwire at all.
 */
object Branding {

    /** What this app is called. Drawn by the title bar, About and System. */
    const val NAME = "PyCmd"

    /** Shown under the version in About. */
    const val CREDIT = "by ExpStudio"

    private const val TAG = "branding"

    /**
     * Checks the name is still in the places the app shows it.
     *
     * Returns the list of places it is missing from - empty when all is well.
     * Separated from [verify] so the same rule can be tested and logged
     * without anything being thrown.
     */
    fun missingFrom(context: Context): List<String> {
        val places = mutableListOf<String>()

        val constant = NAME.trim()
        if (constant.isEmpty()) {
            places += "the app's own name (Branding.NAME)"
        }

        val launcher = runCatching { context.getString(R.string.app_name) }.getOrDefault("")
        if (launcher.isNotEmpty() && !launcher.contains(constant, ignoreCase = true)) {
            places += "the launcher label (R.string.app_name)"
        }

        return places
    }

    /**
     * Called once at start-up.
     *
     * Anything unexpected here is treated as fine: a check that cannot read a
     * resource has learned nothing, and stopping an app over that would be the
     * bug this is meant to avoid.
     */
    fun verify(context: Context) {
        val missing = runCatching { missingFrom(context) }.getOrDefault(emptyList())
        if (missing.isEmpty()) return

        DebugLog.error(TAG, "the app's name is missing", missing.joinToString(", "))
        throw IllegalStateException(
            "This build has had PyCmd's name taken out of " +
                missing.joinToString(" and ") + ".\n\n" +
                "Forks are welcome - the source is in the app, the update address " +
                "is editable, and the guide walks through publishing your own " +
                "builds. The one condition is that the name and the credit stay. " +
                "Put them back and this build runs.",
        )
    }
}
