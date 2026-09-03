# ATAC Roma Live — app Android

App Android nativa (Kotlin + Jetpack Compose) che mostra in **tempo reale** i
trasporti pubblici di Roma (ATAC e Roma TPL):

- 🚏 **Fermate** — ricerca per nome o "fermate vicine" via GPS.
- ⏱️ **Arrivi/partenze in tempo reale** — per ogni fermata, i prossimi passaggi
  previsti (linea, direzione, minuti all'arrivo), aggiornati ogni 30 s.
- ⚠️ **Interruzioni** — avvisi e disservizi di servizio con linee coinvolte e
  periodo di validità.

## Fonte dati

Feed **pubblici** di *Roma Servizi per la Mobilità* (nessuna API key, nessuna
registrazione) — <https://romamobilita.it/it/tecnologie>:

| Dato | Endpoint |
|------|----------|
| GTFS statico (fermate, linee) | `rome_static_gtfs.zip` |
| Arrivi/partenze (GTFS-RT Trip Updates) | `rome_rtgtfs_trip_updates_feed.pb` |
| Interruzioni (GTFS-RT Service Alerts) | `rome_rtgtfs_service_alerts_feed.pb` |
| Posizione mezzi (GTFS-RT Vehicle Positions) | `rome_rtgtfs_vehicle_positions_feed.pb` |

URL completi in `app/.../data/Endpoints.kt`.

## Come funziona

1. Al primo avvio scarica il GTFS statico e importa **solo** `stops.txt` e
   `routes.txt` in un DB Room locale (import veloce: `stop_times.txt`, enorme,
   non serve — le previsioni arrivano dal feed realtime).
2. Aprendo una fermata, scarica il feed *Trip Updates* (protobuf), filtra i
   passaggi per quella fermata e mostra i minuti previsti, con linea/colore dal
   GTFS statico e capolinea stimato dall'ultima fermata della corsa.
3. La tab *Interruzioni* decodifica il feed *Service Alerts*.

## Compilare

Serve **Android Studio** (o Android SDK + `ANDROID_HOME`). In questo repo è già
incluso il Gradle wrapper.

```bash
cd atac-roma-android
# Android Studio: "Open" su questa cartella, poi Run ▶
# oppure da terminale (con Android SDK installato):
./gradlew assembleDebug        # genera app/build/outputs/apk/debug/app-debug.apk
./gradlew installDebug         # installa su un device/emulatore collegato
```

> Nota: il progetto è stato scritto e revisionato staticamente, ma **non è stato
> compilato in questo ambiente** perché privo di Android SDK. La prima build in
> Android Studio scarica le dipendenze e può richiedere qualche minuto.

## Stack

- Kotlin 1.9.24, AGP 8.5.2, Gradle 8.9, `minSdk 24`, `targetSdk 34`
- Jetpack Compose (BOM 2024.09) + Material 3, Navigation Compose
- Room 2.6.1 (KSP) per il GTFS statico
- OkHttp per i download
- `com.google.transit:gtfs-realtime-bindings:0.0.4` (protobuf) per i feed RT
- Google Play Services Location (opzionale, solo per "fermate vicine")

## Struttura

```
app/src/main/java/it/mediaflow/atacroma/
├─ data/
│  ├─ Endpoints.kt              # URL dei feed
│  ├─ net/Http.kt               # OkHttp
│  ├─ gtfs/                     # download+parsing GTFS statico e RT
│  ├─ local/                    # Room: StopEntity, RouteEntity, DAO, DB
│  ├─ model/                    # Departure, ServiceAlert
│  └─ repo/TransitRepository.kt # logica: mappa i feed sui modelli
├─ ui/
│  ├─ theme/  · Format.kt · Deps.kt
│  ├─ AtacRomaApp.kt            # navigazione + bottom bar
│  ├─ screens/                  # StopsScreen, DeparturesScreen, AlertsScreen
│  └─ vm/ViewModels.kt          # StateFlow + coroutine
├─ AtacApp.kt · MainActivity.kt
```

## Possibili estensioni

- Mappa live dei mezzi (Vehicle Positions) — richiede una Google Maps API key.
- Preferiti / notifiche push su linee o fermate.
- Fallback su orario programmato (import `stop_times.txt`) quando non c'è RT.
- Widget home screen con i prossimi passaggi della fermata preferita.

---

App indipendente, ospitata in questo repo per comodità: non dipende da MediaFlow.
