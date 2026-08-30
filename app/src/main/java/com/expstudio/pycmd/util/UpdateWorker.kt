package com.expstudio.pycmd.util

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.core.content.edit
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.expstudio.pycmd.BuildConfig
import com.expstudio.pycmd.MainActivity
import com.expstudio.pycmd.R
import java.util.concurrent.TimeUnit

/**
 * Looking for a newer PyCmd while the app is closed.
 *
 * The in-app check only runs while somebody is looking at the app, which is
 * the one time they are least likely to care. This is the other half: Android
 * wakes the app on its own schedule, it reads the manifest, and - if the
 * setting says so - downloads the APK so that installing it later is a tap
 * rather than a wait.
 *
 * ## What Android actually allows
 *
 * WorkManager is the supported way to do anything on a schedule, and it comes
 * with rules worth stating rather than pretending around:
 *
 * * **Not on the minute.** The shortest period is fifteen minutes, and the
 *   system batches work anyway. "Daily" here means "about once a day, when the
 *   phone is awake and on wifi", not at a time you pick.
 * * **Not while stopped.** Force-stopping an app cancels its work until the
 *   app is opened again. Some manufacturers do that on their own when a phone
 *   is idle; nothing an app can do changes it.
 * * **Never installs by itself.** The download is prepared; the install is a
 *   decision, and Android would ask anyway. The notification is how it says
 *   the wait is already over.
 */
class UpdateWorker(context: Context, parameters: WorkerParameters) :
    CoroutineWorker(context, parameters) {

    override suspend fun doWork(): Result {
        val context = applicationContext
        val settings = settings(context)
        if (!settings.getBoolean(KEY_BACKGROUND, false)) return Result.success()

        val source = settings.getString(KEY_SOURCE, null)?.takeIf { it.isNotBlank() }
            ?: Updater.DEFAULT_MANIFEST_URL

        val release = Updater.fetch(source).getOrElse {
            // A phone with no signal is not a failure worth retrying hard;
            // the next period comes round soon enough.
            DebugLog.debug(TAG, "the background check found nothing", it.message.orEmpty())
            return Result.success()
        }

        settings.edit { putLong(KEY_CHECKED, System.currentTimeMillis()) }

        if (release.versionCode <= BuildConfig.VERSION_CODE) return Result.success()
        if (release.packageName.isNotBlank() && release.packageName != context.packageName) {
            return Result.success()
        }

        var ready = false
        if (settings.getBoolean(KEY_AUTO_DOWNLOAD, false)) {
            val file = Updater.download(context, release) { _, _ -> }.getOrNull()
            if (file != null && Updater.blocker(context, file) == null) {
                Updater.keep(
                    context,
                    file,
                    settings.getLong(KEY_VERSIONS_CAP, DEFAULT_CAP),
                    BuildConfig.VERSION_CODE,
                )
                ready = true
            }
        }

        notify(context, release.versionName, ready)
        DebugLog.info(TAG, "a newer build is out", release.versionName)
        return Result.success()
    }

    private fun notify(context: Context, version: String, downloaded: Boolean) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, "android.permission.POST_NOTIFICATIONS") !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }

        val open = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        val text = if (downloaded) {
            "PyCmd $version is downloaded. Open System to install it - your files stay."
        } else {
            "PyCmd $version is out. Open System to download it."
        }

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("A newer PyCmd")
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setAutoCancel(true)
            .setContentIntent(open)
            .build()

        runCatching {
            context.getSystemService(NotificationManager::class.java)
                ?.notify(NOTIFICATION_ID, notification)
        }
    }

    companion object {
        private const val TAG = "update"
        const val CHANNEL_ID = "pycmd-updates"
        private const val NOTIFICATION_ID = 4201
        private const val WORK_NAME = "pycmd-update-check"

        // Shared with MainViewModel, which owns the same preferences file.
        const val PREFS = "pycmd-update"
        const val KEY_BACKGROUND = "background-checks"
        const val KEY_AUTO_DOWNLOAD = "background-download"
        const val KEY_SOURCE = "manifest-url"
        const val KEY_CHECKED = "checked-at"
        const val KEY_VERSIONS_CAP = "versions-cap"
        const val DEFAULT_CAP = 1024L * 1024 * 1024

        fun settings(context: Context) =
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

        /**
         * Starts or stops the schedule to match the setting.
         *
         * Called on every start as well as when the switch moves, so a phone
         * that dropped the work - a force-stop, a restore onto a new device -
         * gets it back rather than quietly never checking again.
         */
        fun sync(context: Context) {
            val manager = runCatching { WorkManager.getInstance(context) }.getOrNull() ?: return
            if (!settings(context).getBoolean(KEY_BACKGROUND, false)) {
                manager.cancelUniqueWork(WORK_NAME)
                return
            }
            val request = PeriodicWorkRequestBuilder<UpdateWorker>(1, TimeUnit.DAYS)
                .setConstraints(
                    Constraints.Builder()
                        // Unmetered, because a 17 MB download on somebody's
                        // data plan is not a thing to do without being asked.
                        .setRequiredNetworkType(NetworkType.UNMETERED)
                        .setRequiresBatteryNotLow(true)
                        .build(),
                )
                .setInitialDelay(2, TimeUnit.HOURS)
                .build()
            manager.enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
        }
    }
}
