package com.expstudio.pycmd.python

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.expstudio.pycmd.MainActivity
import com.expstudio.pycmd.R
import com.expstudio.pycmd.plugins.PluginIds
import com.expstudio.pycmd.plugins.Plugins

/**
 * Keeps the process alive while Python servers are listening.
 *
 * Android will happily kill a backgrounded app, which would drop every socket
 * the user just opened. A foreground service with an ongoing notification is
 * the supported way to say "this app is doing something the user asked for".
 */
class ServerService : Service() {

    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                releaseWakeLock()
                stopForegroundCompat()
                stopSelf()
                return START_NOT_STICKY
            }
        }

        val summary = intent?.getStringExtra(EXTRA_SUMMARY) ?: "Python server running"
        startForegroundCompat(buildNotification(summary))
        if (Plugins.isOn(PluginIds.KEEP_AWAKE)) {
            holdWakeLock()
        } else {
            releaseWakeLock()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        releaseWakeLock()
        super.onDestroy()
    }

    /**
     * Holds the CPU on for the Keep Awake plugin.
     *
     * A foreground service stops the process being killed; it does not stop
     * the CPU being suspended when the screen goes off, and a suspended CPU
     * answers no sockets. The timeout is a safety net: a lock leaked by a
     * crash would otherwise drain the battery until the phone is rebooted.
     */
    private fun holdWakeLock() {
        if (wakeLock?.isHeld == true) return
        runCatching {
            val power = getSystemService(Context.POWER_SERVICE) as PowerManager
            val lock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "pycmd:servers")
            lock.setReferenceCounted(false)
            lock.acquire(WAKE_LOCK_MILLIS)
            wakeLock = lock
            Log.i(TAG, "wake lock held while servers run")
        }.onFailure { Log.w(TAG, "could not take a wake lock", it) }
    }

    private fun releaseWakeLock() {
        runCatching {
            wakeLock?.takeIf { it.isHeld }?.release()
        }
        wakeLock = null
    }

    private fun buildNotification(summary: String): Notification {
        val openApp = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("PyCmd")
            .setContentText(summary)
            .setSmallIcon(R.drawable.ic_notification)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setContentIntent(openApp)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()
    }

    /**
     * Android 12+ refuses a foreground start from the background. The servers
     * keep running either way - they just lose the keep-alive guarantee - so a
     * refusal is logged rather than allowed to take the process down.
     */
    private fun startForegroundCompat(notification: Notification) {
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
        }.onFailure { Log.w(TAG, "foreground start refused", it) }
    }

    private fun stopForegroundCompat() {
        stopForeground(STOP_FOREGROUND_REMOVE)
    }

    companion object {
        private const val TAG = "ServerService"
        const val CHANNEL_ID = "pycmd-servers"
        private const val NOTIFICATION_ID = 4201
        private const val ACTION_STOP = "com.expstudio.pycmd.STOP_SERVERS"
        private const val EXTRA_SUMMARY = "summary"

        /** Four hours, after which a leaked lock lets go by itself. */
        private const val WAKE_LOCK_MILLIS = 4L * 60 * 60 * 1000

        fun start(context: Context, summary: String) {
            val intent = Intent(context, ServerService::class.java).putExtra(EXTRA_SUMMARY, summary)
            // A foreground service needs its notification posted quickly; if the
            // OS refuses the start (background limits) the servers still run,
            // they just lose the keep-alive guarantee.
            runCatching {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(intent)
                } else {
                    context.startService(intent)
                }
            }
        }

        fun stop(context: Context) {
            runCatching {
                context.startService(Intent(context, ServerService::class.java).setAction(ACTION_STOP))
            }
            runCatching { NotificationManagerCompat.from(context).cancel(NOTIFICATION_ID) }
        }
    }
}
