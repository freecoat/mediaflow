package it.mediaflow.atacroma.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface StopDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(stops: List<StopEntity>)

    @Query("SELECT COUNT(*) FROM stops")
    suspend fun count(): Int

    @Query("DELETE FROM stops")
    suspend fun clear()

    @Query(
        "SELECT * FROM stops WHERE nameLower LIKE '%' || :q || '%' " +
            "ORDER BY nameLower LIMIT 60"
    )
    suspend fun search(q: String): List<StopEntity>

    @Query("SELECT * FROM stops WHERE stopId = :id LIMIT 1")
    suspend fun byId(id: String): StopEntity?

    /** Bounding box grezzo; il filtro fine per raggio avviene in Kotlin (haversine). */
    @Query(
        "SELECT * FROM stops WHERE lat BETWEEN :minLat AND :maxLat " +
            "AND lon BETWEEN :minLon AND :maxLon LIMIT 400"
    )
    suspend fun inBox(minLat: Double, maxLat: Double, minLon: Double, maxLon: Double): List<StopEntity>
}

@Dao
interface RouteDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(routes: List<RouteEntity>)

    @Query("DELETE FROM routes")
    suspend fun clear()

    @Query("SELECT * FROM routes")
    suspend fun all(): List<RouteEntity>
}
