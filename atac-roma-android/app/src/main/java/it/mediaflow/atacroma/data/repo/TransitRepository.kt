package it.mediaflow.atacroma.data.repo

import com.google.transit.realtime.GtfsRealtime.Alert
import com.google.transit.realtime.GtfsRealtime.TranslatedString
import com.google.transit.realtime.GtfsRealtime.TripUpdate
import it.mediaflow.atacroma.data.Endpoints
import it.mediaflow.atacroma.data.gtfs.GtfsRtClient
import it.mediaflow.atacroma.data.gtfs.StaticGtfsImporter
import it.mediaflow.atacroma.data.local.AppDatabase
import it.mediaflow.atacroma.data.local.RouteEntity
import it.mediaflow.atacroma.data.local.StopEntity
import it.mediaflow.atacroma.data.model.Departure
import it.mediaflow.atacroma.data.model.ServiceAlert
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

class TransitRepository(private val db: AppDatabase) {

    private val rt = GtfsRtClient()
    private val importer = StaticGtfsImporter(db)

    @Volatile
    private var routeCache: Map<String, RouteEntity>? = null

    // ---- Dati statici (fermate / linee) ----

    suspend fun hasStaticData(): Boolean = db.stopDao().count() > 0

    /** Importa il GTFS statico se il DB è vuoto. Ritorna il numero di fermate. */
    suspend fun ensureStaticData(): Int {
        val existing = db.stopDao().count()
        if (existing > 0) return existing
        val n = importer.importAll()
        routeCache = null
        return n
    }

    suspend fun refreshStaticData(): Int {
        val n = importer.importAll()
        routeCache = null
        return n
    }

    suspend fun searchStops(query: String): List<StopEntity> {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return emptyList()
        return db.stopDao().search(q)
    }

    suspend fun stopById(id: String): StopEntity? = db.stopDao().byId(id)

    suspend fun nearbyStops(lat: Double, lon: Double, radiusMeters: Double = 800.0): List<StopEntity> {
        val dLat = radiusMeters / 111_320.0
        val dLon = radiusMeters / (111_320.0 * cos(Math.toRadians(lat)).coerceAtLeast(0.01))
        return db.stopDao()
            .inBox(lat - dLat, lat + dLat, lon - dLon, lon + dLon)
            .map { it to haversine(lat, lon, it.lat, it.lon) }
            .filter { it.second <= radiusMeters }
            .sortedBy { it.second }
            .take(40)
            .map { it.first }
    }

    private suspend fun routes(): Map<String, RouteEntity> {
        routeCache?.let { return it }
        val map = db.routeDao().all().associateBy { it.routeId }
        routeCache = map
        return map
    }

    // ---- Realtime ----

    /** Passaggi in tempo reale a una fermata, ordinati per orario previsto. */
    suspend fun departures(stopId: String): List<Departure> {
        val feed = rt.fetch(Endpoints.RT_TRIP_UPDATES)
        val routeMap = routes()
        val now = System.currentTimeMillis() / 1000
        val destCache = HashMap<String, String>()
        val result = ArrayList<Departure>()

        for (entity in feed.entityList) {
            if (!entity.hasTripUpdate()) continue
            val tu = entity.tripUpdate
            val stu = tu.stopTimeUpdateList.firstOrNull { it.stopId == stopId } ?: continue
            val eventTime = pickTime(stu) ?: continue
            val eta = eventTime - now
            if (eta < -60) continue // già passato

            val routeId = tu.trip.routeId
            val route = routeMap[routeId]
            val label = route?.shortName?.takeIf { it.isNotBlank() }
                ?: routeId.ifBlank { "?" }

            val destStopId = tu.stopTimeUpdateList.lastOrNull()?.stopId
            val destination = when {
                destStopId.isNullOrBlank() -> route?.longName.orEmpty()
                else -> destCache.getOrPut(destStopId) {
                    stopById(destStopId)?.name ?: route?.longName.orEmpty()
                }
            }

            result.add(
                Departure(
                    routeLabel = label,
                    routeColor = route?.color.orEmpty(),
                    routeType = route?.type ?: 3,
                    destination = destination,
                    etaSeconds = eta.coerceAtLeast(0),
                    tripId = tu.trip.tripId,
                    isRealtime = true,
                )
            )
        }
        return result.sortedBy { it.etaSeconds }
    }

    private fun pickTime(stu: TripUpdate.StopTimeUpdate): Long? {
        if (stu.hasDeparture() && stu.departure.hasTime() && stu.departure.time > 0) return stu.departure.time
        if (stu.hasArrival() && stu.arrival.hasTime() && stu.arrival.time > 0) return stu.arrival.time
        return null
    }

    /** Interruzioni / avvisi di servizio. */
    suspend fun alerts(): List<ServiceAlert> {
        val feed = rt.fetch(Endpoints.RT_SERVICE_ALERTS)
        val routeMap = routes()
        val out = ArrayList<ServiceAlert>()
        for (entity in feed.entityList) {
            if (!entity.hasAlert()) continue
            val a = entity.alert
            val routeIds = a.informedEntityList
                .mapNotNull { it.routeId.takeIf { r -> r.isNotBlank() } }
                .distinct()
            val labels = routeIds.map { routeMap[it]?.shortName?.takeIf { s -> s.isNotBlank() } ?: it }
            val period = a.activePeriodList.firstOrNull()
            out.add(
                ServiceAlert(
                    id = entity.id,
                    title = translate(a.headerText).ifBlank { "Avviso di servizio" },
                    description = translate(a.descriptionText),
                    cause = a.cause.takeIf { it != Alert.Cause.UNKNOWN_CAUSE }?.name,
                    effect = a.effect.takeIf { it != Alert.Effect.UNKNOWN_EFFECT }?.name,
                    routes = labels,
                    activeFromEpoch = period?.takeIf { it.hasStart() }?.start,
                    activeToEpoch = period?.takeIf { it.hasEnd() }?.end,
                    url = translate(a.url).ifBlank { null },
                )
            )
        }
        return out
    }

    private fun translate(ts: TranslatedString, prefer: List<String> = listOf("it", "en")): String {
        if (ts.translationCount == 0) return ""
        for (lang in prefer) {
            ts.translationList.firstOrNull { it.language.equals(lang, ignoreCase = true) }
                ?.let { return it.text }
        }
        // fallback: prima traduzione senza lingua o comunque la prima disponibile
        ts.translationList.firstOrNull { it.language.isNullOrBlank() }?.let { return it.text }
        return ts.getTranslation(0).text
    }

    private fun haversine(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val r = 6_371_000.0
        val dLat = Math.toRadians(lat2 - lat1)
        val dLon = Math.toRadians(lon2 - lon1)
        val a = sin(dLat / 2) * sin(dLat / 2) +
            cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) *
            sin(dLon / 2) * sin(dLon / 2)
        return r * 2 * atan2(sqrt(a), sqrt(1 - a))
    }
}
