package it.mediaflow.atacroma.data.gtfs

import it.mediaflow.atacroma.data.Endpoints
import it.mediaflow.atacroma.data.local.AppDatabase
import it.mediaflow.atacroma.data.local.RouteEntity
import it.mediaflow.atacroma.data.local.StopEntity
import it.mediaflow.atacroma.data.net.Http
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Request
import java.io.BufferedReader
import java.io.InputStreamReader
import java.util.zip.ZipInputStream

/**
 * Scarica il GTFS statico (zip) e importa SOLO stops.txt e routes.txt in Room.
 * stop_times.txt (enorme) non serve: le previsioni arrivano dal feed realtime.
 */
class StaticGtfsImporter(private val db: AppDatabase) {

    /** Ritorna il numero di fermate importate. */
    suspend fun importAll(): Int = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(Endpoints.STATIC_GTFS).build()
        Http.client.newCall(request).execute().use { resp ->
            if (!resp.isSuccessful) error("HTTP ${resp.code} scaricando il GTFS statico")
            val body = resp.body ?: error("Risposta vuota per il GTFS statico")
            var stopCount = 0
            ZipInputStream(body.byteStream()).use { zis ->
                var entry = zis.nextEntry
                while (entry != null) {
                    when (entry.name.substringAfterLast('/')) {
                        "stops.txt" -> stopCount = importStops(zis)
                        "routes.txt" -> importRoutes(zis)
                    }
                    zis.closeEntry()
                    entry = zis.nextEntry
                }
            }
            stopCount
        }
    }

    private suspend fun importStops(zis: ZipInputStream): Int {
        db.stopDao().clear()
        val reader = BufferedReader(InputStreamReader(zis, Charsets.UTF_8))
        val header = reader.readLine() ?: return 0
        val cols = Csv.parseLine(header).map { Csv.stripBom(it).trim() }
        val idI = cols.indexOf("stop_id")
        val codeI = cols.indexOf("stop_code")
        val nameI = cols.indexOf("stop_name")
        val latI = cols.indexOf("stop_lat")
        val lonI = cols.indexOf("stop_lon")
        if (idI < 0 || nameI < 0 || latI < 0 || lonI < 0) error("stops.txt: header inatteso")

        val batch = ArrayList<StopEntity>(2000)
        var total = 0
        var line = reader.readLine()
        while (line != null) {
            if (line.isNotBlank()) {
                val f = Csv.parseLine(line)
                val lat = f.getOrNull(latI)?.toDoubleOrNull()
                val lon = f.getOrNull(lonI)?.toDoubleOrNull()
                val id = f.getOrNull(idI)
                val name = f.getOrNull(nameI)
                if (!id.isNullOrBlank() && !name.isNullOrBlank() && lat != null && lon != null) {
                    batch.add(
                        StopEntity(
                            stopId = id,
                            code = if (codeI >= 0) f.getOrNull(codeI)?.ifBlank { null } else null,
                            name = name,
                            nameLower = name.lowercase(),
                            lat = lat,
                            lon = lon,
                        )
                    )
                    total++
                }
            }
            if (batch.size >= 2000) {
                db.stopDao().insertAll(batch); batch.clear()
            }
            line = reader.readLine()
        }
        if (batch.isNotEmpty()) db.stopDao().insertAll(batch)
        return total
    }

    private suspend fun importRoutes(zis: ZipInputStream) {
        db.routeDao().clear()
        val reader = BufferedReader(InputStreamReader(zis, Charsets.UTF_8))
        val header = reader.readLine() ?: return
        val cols = Csv.parseLine(header).map { Csv.stripBom(it).trim() }
        val idI = cols.indexOf("route_id")
        val shortI = cols.indexOf("route_short_name")
        val longI = cols.indexOf("route_long_name")
        val typeI = cols.indexOf("route_type")
        val colorI = cols.indexOf("route_color")
        if (idI < 0) error("routes.txt: header inatteso")

        val batch = ArrayList<RouteEntity>(1000)
        var line = reader.readLine()
        while (line != null) {
            if (line.isNotBlank()) {
                val f = Csv.parseLine(line)
                val id = f.getOrNull(idI)
                if (!id.isNullOrBlank()) {
                    val shortName = if (shortI >= 0) f.getOrNull(shortI).orEmpty() else ""
                    val longName = if (longI >= 0) f.getOrNull(longI).orEmpty() else ""
                    batch.add(
                        RouteEntity(
                            routeId = id,
                            shortName = shortName,
                            longName = longName,
                            type = if (typeI >= 0) f.getOrNull(typeI)?.toIntOrNull() ?: 3 else 3,
                            color = if (colorI >= 0) f.getOrNull(colorI)?.trim().orEmpty() else "",
                        )
                    )
                }
            }
            if (batch.size >= 1000) {
                db.routeDao().insertAll(batch); batch.clear()
            }
            line = reader.readLine()
        }
        if (batch.isNotEmpty()) db.routeDao().insertAll(batch)
    }
}
