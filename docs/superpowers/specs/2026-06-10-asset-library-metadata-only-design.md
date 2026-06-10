# Design — Asset Library metadata-only + Claqo Agent (MAM facility-side)

> **STATO: design APPROVATO da Matteo il 10 giu 2026** (sezioni 1-6 confermate una a una).
> Visione: asset library stile "Content Hub/Backlot Netflix" integrata nel gestionale,
> con regola assoluta: **i file di contenuto NON vengono MAI caricati sul server Claqo**.

## Obiettivo (parole di Matteo)

Claqo legge **solo ed unicamente i metadata** dei file (via scansione filesystem della
facility) e salva quelli nell'asset management, insieme al percorso del file. Flusso
completo: commerciale crea progetto+quote con deliverables → approvazione → deliverables
diventano item planning/job → producer assegna lavorazioni via booking → operatore
produce il file su storage della facility (= tenant) → Claqo scansiona metadata e genera
l'asset → QC legata al file (bypassabile dal producer) → storia movimenti documentata
(upload cliente via link, copie HDD/LTO/CRU, distruzione documentata ma record permanente).
Processi automatizzati il più possibile: operatori = controllo e verifica. Preview eventi
QC visibili al producer nel rispetto TPN. Copie/upload **sempre verificati**. Catalogo LTO
sempre visibile + restore semi-automatico (operatore notificato di inserire il tape).

## Decisioni prese (Q&A 10 giu 2026)

1. **Topologia = B**: Claqo centrale su cloud/VPS + **agent facility** (demone Python)
   dentro la rete della facility. L'agent fa scan/ffprobe/checksum/preview in locale e
   manda SOLO metadata a Claqo via API.
2. **Scope agent = C**: scanner + esecutore comandi + **watch automatico continuo** delle
   cartelle output: l'agent propone l'asset appena il file appare, l'operatore valida solo.
3. **Preview QC = A configurabile + C opzione**: default streaming relay attraverso Claqo
   (zero persistenza VPS); opzione per-tenant bucket S3 di proprietà della facility.
4. **Upload DAM = doppio binario (A)**: asset di contenuto SOLO metadata-only via agent
   (upload bytes bloccato per asset media); documenti business (capitolati PDF, DDT,
   firme, fatture) continuano con upload server come oggi.
5. **Tool reali in facility**: "un po' tutto" lato transfer (Aspera, Media Shuttle, MASV,
   Frame.io, PIX, WeTransfer…) → architettura plugin. **LTO = SOLO YoYotta**, che genera
   MHL → **MHL = formato canonico di verifica**.
6. **Approccio = 1 (evoluzione incrementale)**: estendere `Asset`/`PhysicalAsset`/
   `AssetMovement`/`AssetMembership` esistenti; nuovi modelli solo per volume/agent/coda/
   transfer. NO modulo MAM greenfield.
7. **Connessione agent = solo OUTBOUND** (standard TPN): nessuna porta in ingresso in
   facility; long-poll della coda job + push risultati su HTTPS.
8. **StorageVolume per-tenant** (la SAN è infrastruttura facility); progetti agganciati
   via convenzione path (`/OUT/{project_code}/`) + override `output_dir` per-progetto.

## Sezione 1 — Architettura generale

```
┌─ CLAQO VPS (cloud) ──────────────────┐
│  FastAPI + SQLite                    │
│  - Registro asset (SOLO metadata)    │
│  - Coda AgentJob per facility        │
│  - UI producer/operatore/commerciale │
│  - Relay preview (no persistenza)    │
└──────────────▲───────────────────────┘
               │ HTTPS solo OUTBOUND dall'agent
               │ (long-poll coda job + push risultati)
┌─ FACILITY (= tenant) ────────────────┐
│  Claqo Agent (demone Python)         │
│  - mount volumi SAN/NAS (read +      │
│    write solo su cartelle config.)   │
│  - watch cartelle output             │
│  - ffprobe/MediaInfo + xxHash/MHL    │
│  - genera preview proxy watermark    │
│  - driver plugin: YoYotta (LTO),     │
│    Aspera/Shuttle/MASV (transfer)    │
└──────────────────────────────────────┘
```

1. **Nessun byte di contenuto sale sul VPS, mai.** Agent manda solo JSON (metadata,
   checksum, esiti job). Eccezione transitoria: stream preview in relay senza scrittura
   su disco VPS (oppure S3 tenant).
2. **Agent = 1 processo per facility**, token per-tenant, registrato come `AgentNode`,
   heartbeat periodico (Claqo sa se la facility è online). N volumi per agent.
3. **Comandi via coda** `AgentJob` (scan, probe, checksum, preview, copy, lto_archive,
   lto_restore, transfer, delete_verify); agent long-poll → esegue → riporta.
4. **"Agent propone, operatore dispone"**: file nuovo dal watch → proposta asset
   `pending_review`, conferma/scarto umano. Pattern AI-Action esteso all'agent.
5. Upload server attuale resta SOLO per documenti business; bloccato per contenuto.

## Sezione 2 — Modello dati

### Nuovi modelli (4)

| Modello | Campi chiave |
|---|---|
| `StorageVolume` | tenant_id, name, mount_path (lato agent), watch_dirs JSON, read_only, total_gb/free_gb (refresh da agent), is_active |
| `AgentNode` | tenant_id, name, auth_token_hash, last_heartbeat_at, version, capabilities JSON (plugin disponibili), status online/offline/degraded |
| `AgentJob` | tenant_id, agent_id, type (scan/probe/checksum/preview/copy/lto_archive/lto_restore/transfer/delete_verify), payload JSON, status (queued→claimed→running→done/failed/cancelled), result JSON, error, progress %, requested_by_user_id, asset_id/physical_asset_id opzionali |
| `TransferOrder` | asset(s), tool (aspera/shuttle/masv/frameio/wetransfer/pix…), destination, status, verification (checksum/MHL esito), link_url + scadenza, agent_job_id, recipient_email. Genera AssetMovement alla conferma |

### Estensioni esistenti

- **`Asset`**: + `storage_volume_id` FK, + `rel_path` (relativo al volume),
  + `content_state` enum (`online` su SAN / `archived_only` solo LTO-HDD / `deleted`
  distrutto ovunque — record VIVE per sempre), + `checksum_xxhash` + `mhl_ref`,
  + `registered_via` (agent_watch/agent_scan/manual_path), + `proposed_state`
  (pending_review/confirmed). `file_path` legacy resta per documenti business.
- **`QCEvent`**: + `preview_status` (none/requested/ready/expired/failed) + `preview_ref`
  (chiave staging agent o S3 key). Preview legata all'EVENTO contestato, non all'asset.
- **`PhysicalAsset`**: + `yoyotta_catalog_ref`. Contenuto tape già coperto da
  `AssetMembership` (checksum + path_on_media esistenti; backfill dal parse MHL YoYotta).
- **`AssetMovement`**: + tipi `destroyed` (chi/quando/perché/approvato da) e `restored`.

### Verifica MHL-centrica

Ogni copia/archive/transfer produce o consuma un MHL. Claqo salva l'MHL (XML piccolo =
metadata, può stare su VPS) e confronta hash attesi vs riportati. Mismatch → job `failed`
+ anomalia. xxHash registrato all'ingest = riferimento per tutta la vita dell'asset.

## Sezione 3 — Flusso "file prodotto → asset → QC"

Percorso automatico (watch):
1. Operatore esporta su SAN nella cartella output (convenzione `/OUT/{project_code}/`
   da `StorageVolume.watch_dirs`, override per-progetto possibile).
2. Agent rileva file **stabile** (size invariata N sec; package DCP/IMF = cartella
   completa via ASSETMAP/CPL).
3. Agent: probe (ffprobe/MediaInfo) + xxHash → metadata a Claqo.
4. Claqo crea proposta (`pending_review`) + **match automatico col JobDeliverable
   atteso**: specs estratte vs `spec_json` (container, codec, risoluzione, naming
   convention capitolato). Match forte → pre-collegata; debole → candidati.
5. Operatore (anche mobile PWA): conferma / corregge link deliverable / scarta.
   Conferma → Asset reale, `JobDeliverable.status → qc`, scheda QC aperta con confronto
   attese-vs-reali (`qc_expected_for_deliverable` esistente).
6. Percorso manuale sempre disponibile: incolla path in UI → job `probe` → stessa trafila.

QC = sistema event-sourced esistente (pass/reject/note/bypass producer). Reject con
evento contestato → richiesta preview (Sezione 5).

## Sezione 4 — Orchestrazione operazioni

**Ogni tool esterno = adapter plugin sull'agent, 2 livelli:**
- **Driven**: agent comanda il tool via CLI/API (ascp Aspera, API Shuttle/MASV/Frame.io).
- **Assisted**: tool guidato dall'operatore (es. YoYotta UI), ma Claqo genera il **ticket
  operativo** (cosa, dove, naming) e l'agent **verifica a posteriori** (parse MHL +
  check filesystem/catalogo). Cascata di controlli anche senza API.

**LTO YoYotta (v1 = assisted + read-side automatico):**
- Archive: ordine → ticket + `AgentJob lto_archive` → operatore lancia YoYotta → agent
  intercetta MHL/report → backfill `AssetMembership` (tape, path, checksum) +
  `PhysicalAsset.used_gb` → `content_state` aggiornato. Hash MHL vs xxHash ingest:
  mismatch = anomalia.
- **Catalogo sempre visibile**: parse periodico cataloghi/MHL YoYotta → contenuto di ogni
  tape noto senza inserirlo.

**Restore semi-automatico:**
1. "Restore" su asset `archived_only` → tape risolti via `AssetMembership`.
2. Tape in library (da `location`)? Sì → job. No → **notifica operatore** "Inserire LTO
   #042"; scan QR del tape (esistente) = conferma inserimento → job parte.
3. Restore → verifica checksum vs membership → `content_state=online`, notifica richiedente.

**Transfer (`TransferOrder`):** selezione asset → tool + destinatario → job agent →
upload → verifica (checksum dove il tool lo riporta, altrimenti size+esito) →
`AssetMovement outgest` + link salvato + scadenza → opzionale email cliente. Storia
movimenti completa per asset.

**Distruzione documentata:** richiesta → **doppia conferma** (operatore richiede,
producer/admin approva, RBAC esistente) → agent cancella o verifica cancellazione manuale
→ `AssetMovement destroyed` + `content_state=deleted`. Record e storia PERMANENTI.
Copie residue su tape → stato resta `archived_only`, non `deleted`.

## Sezione 5 — Preview QC (TPN-compliant)

**Generazione (agent-side):** reject QC a TC X → `AgentJob preview` (path, TC in/out =
evento ± handle, default 5s) → ffmpeg: H.264 low-res (960px), **watermark forte** (utente
richiedente + timestamp + "QC PREVIEW"), burn-in TC, audio downmix stereo. Solo i secondi
dell'evento, MAI il file intero. Eventi audio → estratto WAV/AAC stessa logica.

**Fruizione (2 backend per-tenant):**
- **Default relay**: proxy resta su staging agent (`.claqo_previews/`); producer apre
  scheda QC → Claqo chiede stream all'agent → pass-through al browser, zero persistenza
  VPS. URL firmato, scadenza 24h, permesso QC sul progetto richiesto. Limite: agent
  offline = preview non visibile (stato mostrato in UI).
- **Opzione S3 tenant**: agent carica proxy sul bucket della facility, Claqo tiene la key
  → presigned URL. Visibile anche ad agent spento.

**Retention**: cancellazione automatica a QC chiuso (job `delete_verify` o lifecycle S3).
Ogni visualizzazione → audit log (esistente, TPN).

## Sezione 6 — Sicurezza, errori, fasi

**Sicurezza:**
- Token per-agent (hash su DB, revocabile da UI), scope = solo suo tenant, TLS obbligatorio.
- Agent con utente OS a permessi minimi: read sui volumi, write SOLO su staging preview e
  destinazioni copia configurate. Mai delete senza job approvato.
- Ogni job → audit log (ordinante, approvante, esito, hash). Integrazione megaswitch
  egress/TPN (α.172.195): lockdown tenant → blocco `TransferOrder` verso destinazioni
  non whitelistate.

**Errori:**
- Agent offline → job `queued`, banner UI "Facility offline da X min" (heartbeat), retry
  al rientro.
- Job failed (checksum mismatch, tool error, path sparito) → anomalia/notifica, mai
  silenzioso.
- File sparito prima della conferma → proposta auto-scartata con traccia. Stesso hash
  rilevato 2 volte → dedup.
- VPS irraggiungibile → agent bufferizza esiti in coda locale (SQLite agent-side),
  reinvia al rientro.

**Fasi di build (ognuna = spec/plan/test proprio, usabile da sola):**

| Fase | Contenuto |
|---|---|
| **F1 Fondamenta** | Modelli (StorageVolume, AgentNode, AgentJob, estensioni Asset) + agent demone (register/heartbeat/long-poll) + job scan/probe/checksum + registrazione per path manuale + UI proposta/conferma + blocco upload contenuti DAM + migrazione asset esistenti |
| **F2 Watch + match** | Watch dirs, file stabile/package, auto-match JobDeliverable atteso, mobile review proposta |
| **F3 Preview QC** | Job preview, relay streaming + opzione S3, player in scheda QC, retention |
| **F4 LTO YoYotta** | Parse MHL/cataloghi, backfill membership, ticket archive assisted, restore con notifica/QR |
| **F5 TransferOrder** | Adapter interface + primi 2 tool driven (proposta: Aspera CLI + Media Shuttle API), link tracking, verifica, movimenti |
| **F6 Distruzione + polish** | Delete doppia-conferma, dashboard "dove vive ogni asset", report storage |

**Test**: unit su parser MHL e match logic; agent testabile contro Claqo locale con
volume finto; E2E per fase con file di prova. Agent = pacchetto Python separato nel repo
(`agent/`), versionato insieme, stesso stile di codice.

## Fuori scope (esplicito)

- Automazione write-side YoYotta via API (resta assisted finché non si valuta YoYotta
  Automation; il design già lo prevede come upgrade del livello adapter).
- Portali consegna specifici per broadcaster (roadmap separata già in CLAUDE.md).
- Multi-agent per tenant (multi-sede): il modello `AgentNode` lo permette (N agent per
  tenant), ma orchestrazione cross-sede non in v1.
- Cifratura at-rest dei proxy preview su staging agent (valutare in F3 se richiesta TPN).
