package it.mediaflow.atacroma.data

/**
 * Feed pubblici di Roma Servizi per la Mobilità (nessuna API key richiesta).
 * Fonte: https://romamobilita.it/it/tecnologie
 */
object Endpoints {
    const val STATIC_GTFS = "https://romamobilita.it/sites/default/files/rome_static_gtfs.zip"
    const val RT_TRIP_UPDATES = "https://romamobilita.it/sites/default/files/rome_rtgtfs_trip_updates_feed.pb"
    const val RT_SERVICE_ALERTS = "https://romamobilita.it/sites/default/files/rome_rtgtfs_service_alerts_feed.pb"
    const val RT_VEHICLE_POSITIONS = "https://romamobilita.it/sites/default/files/rome_rtgtfs_vehicle_positions_feed.pb"
}
