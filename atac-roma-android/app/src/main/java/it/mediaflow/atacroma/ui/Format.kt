package it.mediaflow.atacroma.ui

import androidx.compose.ui.graphics.Color
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val hhmm = SimpleDateFormat("HH:mm", Locale.ITALY)
private val dmHm = SimpleDateFormat("dd/MM HH:mm", Locale.ITALY)

fun clock(epochMillis: Long): String = hhmm.format(Date(epochMillis))
fun clockSeconds(epochSeconds: Long): String = hhmm.format(Date(epochSeconds * 1000))
fun dateTime(epochSeconds: Long): String = dmHm.format(Date(epochSeconds * 1000))

fun etaLabel(seconds: Long): String {
    val min = (seconds / 60).toInt()
    return if (min < 1) "in arrivo" else "$min min"
}

/** Emoji indicativa del mezzo dal GTFS route_type. */
fun modeEmoji(routeType: Int): String = when (routeType) {
    0 -> "🚊" // tram
    1 -> "Ⓜ️" // metro
    2 -> "🚆" // ferrovia
    3 -> "🚌" // bus
    else -> "🚍"
}

/** Colore da hex GTFS ("C1121F"); fallback se assente/non valido. */
fun routeColor(hex: String, fallback: Color): Color = try {
    if (hex.isBlank()) fallback else Color(("FF" + hex.removePrefix("#")).toLong(16))
} catch (_: Exception) {
    fallback
}
