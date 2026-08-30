package com.expstudio.pycmd.music

import android.app.PendingIntent
import android.content.Intent
import androidx.annotation.OptIn
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.DefaultMediaNotificationProvider
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import com.expstudio.pycmd.MainActivity
import com.expstudio.pycmd.R
import com.expstudio.pycmd.util.DebugLog

/**
 * The thing that actually makes sound, and the reason it keeps making it.
 *
 * Playing audio from inside a Compose screen would stop the moment the screen
 * went away, which is the opposite of what music is for while you are working.
 * A `MediaSessionService` is Android's answer: the player lives in a service,
 * the service publishes a session, and the system takes it from there -
 * notification, lock screen, the quick-settings media chip, a headset's pause
 * button, the car. None of that is drawn by this app; all of it comes from
 * having a session at all, which is why the player lives here rather than in
 * the view model.
 *
 * Three deliberate settings:
 *
 * * **Audio only, always.** A file may well be a video - people have `.mp4`
 *   files they want the sound of - and the video track is switched off rather
 *   than transcoded away at import. Nothing decodes a picture nobody can see.
 * * **Audio focus is honoured.** A call, a navigation prompt or another player
 *   ducks or pauses this one, and it comes back afterwards. An app that talks
 *   over a phone call is an app people uninstall.
 * * **Unplugging the headphones pauses.** Otherwise the room hears it.
 *
 * Swiping the app away is left to `MediaSessionService` itself, which stops
 * the service only when nothing is playing. That is the behaviour we want and
 * overriding it to say the same thing again is a way to get it wrong later.
 */
@OptIn(UnstableApi::class)
class MusicService : MediaSessionService() {

    private var session: MediaSession? = null

    override fun onCreate() {
        super.onCreate()

        val player = ExoPlayer.Builder(this)
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                    .setUsage(C.USAGE_MEDIA)
                    .build(),
                // true: take audio focus and give it back, rather than
                // playing over whatever else the phone is doing.
                true,
            )
            .setHandleAudioBecomingNoisy(true)
            .build()

        player.trackSelectionParameters = player.trackSelectionParameters
            .buildUpon()
            .setTrackTypeDisabled(C.TRACK_TYPE_VIDEO, true)
            .build()

        session = MediaSession.Builder(this, player)
            .setSessionActivity(openTheApp())
            .build()

        // The notification is Android's, built from the session - but the
        // small icon is ours, so what is playing says PyCmd in the status bar
        // rather than a generic note nobody can attribute.
        setMediaNotificationProvider(
            DefaultMediaNotificationProvider.Builder(this).build().apply {
                setSmallIcon(R.drawable.ic_notification)
            },
        )

        DebugLog.debug(TAG, "the media session is up")
    }

    /** Tapping the notification opens PyCmd rather than a player of its own. */
    private fun openTheApp(): PendingIntent = PendingIntent.getActivity(
        this,
        0,
        Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    override fun onDestroy() {
        session?.let { live ->
            live.player.release()
            live.release()
        }
        session = null
        super.onDestroy()
    }

    private companion object {
        const val TAG = "music"
    }
}
