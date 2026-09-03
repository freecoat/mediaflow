package it.mediaflow.atacroma.data.model

/** Un passaggio in tempo reale a una fermata. */
data class Departure(
    val routeLabel: String,      // es. "64", "MEB", "8"
    val routeColor: String,      // hex senza '#', può essere vuoto
    val routeType: Int,          // 0 tram, 1 metro, 3 bus...
    val destination: String,     // capolinea best-effort
    val etaSeconds: Long,        // secondi da adesso al passaggio previsto
    val tripId: String,
    val isRealtime: Boolean,     // true = predizione dal feed RT
) {
    val etaMinutes: Int get() = (etaSeconds / 60).toInt()
}

/** Un avviso / interruzione di servizio dal feed GTFS-RT Service Alerts. */
data class ServiceAlert(
    val id: String,
    val title: String,
    val description: String,
    val cause: String?,
    val effect: String?,
    val routes: List<String>,    // route_id impattati
    val activeFromEpoch: Long?,
    val activeToEpoch: Long?,
    val url: String?,
)
