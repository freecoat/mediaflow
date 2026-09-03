package it.mediaflow.atacroma.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

private val AtacRed = Color(0xFFC1121F)
private val AtacRedDark = Color(0xFF8B0E17)

private val LightColors = lightColorScheme(
    primary = AtacRed,
    onPrimary = Color.White,
    secondary = Color(0xFF3A6EA5),
    background = Color(0xFFF6F6F7),
    surface = Color.White,
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFFF6B6B),
    onPrimary = Color(0xFF3A0004),
    secondary = Color(0xFF9EC1E8),
    background = Color(0xFF121316),
    surface = Color(0xFF1D1F24),
)

@Composable
fun AtacRomaTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    val colors = if (darkTheme) DarkColors else LightColors
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = (if (darkTheme) AtacRedDark else AtacRed).toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = false
        }
    }
    MaterialTheme(
        colorScheme = colors,
        typography = Typography(),
        content = content
    )
}
