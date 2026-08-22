package com.expstudio.pycmd.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * The palette is shared with the WebView stylesheets (console.css, editor.css).
 * Change a colour here and change it there too, or the terminal will stop
 * matching the chrome around it.
 */
object PyColors {
    val Background = Color(0xFF0B0F14)
    val Surface = Color(0xFF111823)
    val SurfaceHigh = Color(0xFF17202D)
    val Outline = Color(0xFF243044)
    val OnBackground = Color(0xFFD7E0EA)
    val Muted = Color(0xFF8A9AAF)

    val Accent = Color(0xFF4DD0A0)
    val AccentDim = Color(0xFF2C8A6B)
    val Info = Color(0xFF7AA2F7)
    val Warning = Color(0xFFF2C97D)
    val Danger = Color(0xFFFF6B6B)
}

private val DarkScheme = darkColorScheme(
    primary = PyColors.Accent,
    onPrimary = Color(0xFF04231A),
    primaryContainer = PyColors.AccentDim,
    onPrimaryContainer = Color(0xFFE6FFF5),
    secondary = PyColors.Info,
    onSecondary = Color(0xFF06152E),
    tertiary = PyColors.Warning,
    onTertiary = Color(0xFF2B1F00),
    background = PyColors.Background,
    onBackground = PyColors.OnBackground,
    surface = PyColors.Surface,
    onSurface = PyColors.OnBackground,
    surfaceVariant = PyColors.SurfaceHigh,
    onSurfaceVariant = PyColors.Muted,
    outline = PyColors.Outline,
    outlineVariant = Color(0xFF1B2532),
    error = PyColors.Danger,
    onError = Color(0xFF2B0000),
)

val MonoFamily = FontFamily.Monospace

private val PyTypography = Typography(
    titleLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 20.sp, lineHeight = 26.sp),
    titleMedium = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 22.sp),
    bodyLarge = TextStyle(fontSize = 15.sp, lineHeight = 21.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
    bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 17.sp),
    labelLarge = TextStyle(fontWeight = FontWeight.Medium, fontSize = 14.sp),
    labelSmall = TextStyle(fontWeight = FontWeight.Medium, fontSize = 11.sp, letterSpacing = 0.4.sp),
)

/**
 * Always dark.
 *
 * The console and editor are WebViews with their own dark stylesheets; a light
 * Compose chrome around them would read as two different apps stitched
 * together, so the theme does not follow the system setting.
 */
@Composable
fun PyCmdTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkScheme,
        typography = PyTypography,
        content = content,
    )
}
