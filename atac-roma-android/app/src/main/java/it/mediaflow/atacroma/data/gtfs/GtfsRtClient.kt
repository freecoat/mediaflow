package it.mediaflow.atacroma.data.gtfs

import com.google.transit.realtime.GtfsRealtime.FeedMessage
import it.mediaflow.atacroma.data.net.Http
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Request

/** Scarica e decodifica un feed GTFS-Realtime (protobuf) da un URL .pb */
class GtfsRtClient {

    suspend fun fetch(url: String): FeedMessage = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(url).build()
        Http.client.newCall(request).execute().use { resp ->
            if (!resp.isSuccessful) error("HTTP ${resp.code} su $url")
            val bytes = resp.body?.bytes() ?: error("Risposta vuota da $url")
            FeedMessage.parseFrom(bytes)
        }
    }
}
