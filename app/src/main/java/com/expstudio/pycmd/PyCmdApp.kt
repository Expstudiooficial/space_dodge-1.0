package com.expstudio.pycmd

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import com.expstudio.pycmd.python.ServerService
import com.expstudio.pycmd.plugins.CustomPlugins
import com.expstudio.pycmd.plugins.Plugins
import com.expstudio.pycmd.util.Branding
import com.expstudio.pycmd.util.DebugLog

class PyCmdApp : Application() {

    override fun onCreate() {
        super.onCreate()
        // Installed before anything else so a crash during start-up is still
        // recorded for the debug console.
        DebugLog.installCrashHandler()
        DebugLog.info("app", "${Branding.NAME} starting")
        // Before anything is drawn: see Branding for what this is and why it
        // cannot fire on a build that still says what it is.
        Branding.verify(this)
        Plugins.init(this)
        CustomPlugins.init(this)
        createNotificationChannel()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            ServerService.CHANNEL_ID,
            getString(R.string.server_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = getString(R.string.server_channel_desc)
            setShowBadge(false)
        }
        getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
    }
}
