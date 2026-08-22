package com.expstudio.pycmd.python

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.expstudio.pycmd.MainActivity
import com.expstudio.pycmd.R

/**
 * Keeps the process alive while Python servers are listening.
 *
 * Android will happily kill a backgrounded app, which would drop every socket
 * the user just opened. A foreground service with an ongoing notification is
 * the supported way to say "this app is doing something the user asked for".
 */
class ServerService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopForegroundCompat()
                stopSelf()
                return START_NOT_STICKY
            }
        }

        val summary = intent?.getStringExtra(EXTRA_SUMMARY) ?: "Python server running"
        startForegroundCompat(buildNotification(summary))
        return START_STICKY
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

    private fun startForegroundCompat(notification: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    @Suppress("DEPRECATION")
    private fun stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            stopForeground(true)
        }
    }

    companion object {
        const val CHANNEL_ID = "pycmd-servers"
        private const val NOTIFICATION_ID = 4201
        private const val ACTION_STOP = "com.expstudio.pycmd.STOP_SERVERS"
        private const val EXTRA_SUMMARY = "summary"

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
