package it.mediaflow.atacroma.data.local

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "stops",
    indices = [Index("nameLower"), Index("lat"), Index("lon")]
)
data class StopEntity(
    @PrimaryKey val stopId: String,
    val code: String?,
    val name: String,
    val nameLower: String,
    val lat: Double,
    val lon: Double,
)

@Entity(tableName = "routes")
data class RouteEntity(
    @PrimaryKey val routeId: String,
    val shortName: String,
    val longName: String,
    /** GTFS route_type: 0 tram, 1 metro, 3 bus, ... */
    val type: Int,
    /** colore esadecimale senza '#', può essere vuoto */
    val color: String,
)
