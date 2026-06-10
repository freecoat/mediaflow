# Design — F2 Watch + Match (Asset Library metadata-only)

> **STATO: design approvato da Matteo il 10 giu 2026.**
> Segue F1 (α.172.210, registro asset metadata-only + agent). Fa parte del design
> madre `docs/superpowers/specs/2026-06-10-asset-library-metadata-only-design.md`
> (sezione "Fasi di build", riga F2). Prerequisito: F1 in produzione.

## Obiettivo

Eliminare il passo manuale "registra per percorso" di F1: l'agent **watcha** in
continuo le cartelle output della facility e propone l'asset appena un file nuovo è
stabile. Ogni proposta viene **auto-matchata** col `JobDeliverable` atteso (specs
tecniche + naming convention del capitolato), così l'operatore valida invece di
cercare il link. Review possibile anche da **mobile PWA**. Pattern invariato: "agent
propone, operatore dispone".

## Decisioni prese (Q&A 10 giu 2026)

1. **Watch = polling listing** (NON eventi FS): l'agent lista le `watch_dirs` ogni N
   sec e confronta con lo stato precedente. Robusto su SAN/NAS di rete (gli eventi FS
   SMB/NFS si perdono), zero dipendenze extra. Latenza accettabile (~N sec).
2. **Stabilità = size-stable + DCP/IMF base**: file singolo probato solo se `size`
   invariata tra due cicli; package DCP/IMF riconosciuto come cartella-unità via
   presenza `ASSETMAP` (+ `CPL`).
3. **Auto-match = forte/debole con soglie**: confronto specs probed (container, codec,
   risoluzione, frame rate) + naming vs `JobDeliverable`/`DeliveryItem`. Forte →
   pre-collega; debole → candidati ordinati; zero → proposta libera.
4. **Mobile review = lista + conferma/scarta/correggi-link** nella PWA `/m`.

## Architettura (cosa cambia rispetto a F1)

```
FACILITY agent                          CLAQO server
─────────────                           ────────────
agent/watch.py (nuovo)                  /agent-api/jobs/claim → job scan
  loop: ogni N sec                      process_job_result(scan) →
  - lista watch_dirs (ricorsivo)          per ogni file nuovo+stabile riportato:
  - stato locale {rel_path:(size,mtime)}    create_proposal_from_probe(...,
  - rileva nuovi/stabili                       registered_via='agent_watch')
  - skip se size cambia                     deliverable_match.match_proposal(asset)
  - package DCP/IMF = 1 unità                 → matched_deliverable_id (forte)
  - per ognuno: probe locale                  → candidati (debole)
    (ffprobe+xxhash, riusa probe.py)
  - manda risultati batch
```

L'agent NON tiene una coda persistente nuova: il watch è un job `scan` ricorrente che
Claqo riaccoda (o l'agent self-scheda il prossimo scan dopo ogni ciclo). Lo stato
"file già visto" vive lato agent (in-memory) + dedup checksum lato server (F1) come
rete di sicurezza.

## Sezione 1 — Watch agent-side (`agent/watch.py`)

- **Input**: lista volumi+watch_dirs dall'heartbeat (F1 li ritorna già).
- **Ciclo** (ogni `CLAQO_WATCH_SECONDS`, default 30): per ogni `(volume, watch_dir)`
  cammina ricorsivamente (`os.walk`), raccoglie `{rel_path: (size, mtime)}`.
- **Stabilità file singolo**: un rel_path è candidato-probe se presente nel ciclo
  corrente **e** nel precedente con **stessa size** (≥1 intervallo di quiete). Esclude
  file in scrittura.
- **Package DCP/IMF**: se una cartella contiene `ASSETMAP` (case-insensitive) →
  trattata come unità singola; rel_path = la cartella; stabile quando `ASSETMAP`
  presente e nessun file interno cresce tra due cicli. Si prova a probare il CPL
  principale (il `.mxf` video più grande referenziato, o fallback: nessun probe →
  `tech_specs.tool='package'`, size = somma cartella).
- **Dedup locale**: set di rel_path già proposti in sessione (per non riproporre ogni
  ciclo). Il dedup forte resta lato server (checksum).
- **Output**: i file/package stabili nuovi vengono probati con `probe.py` (F1) e
  riportati come risultato di un job `scan` (lista di probe-result), oppure ognuno
  come singolo `probe` job-result. Scelta implementativa: **un job `scan` ritorna una
  lista** `{volume_id, items:[probe_result...]}` per ridurre il chatter.
- **Robustezza**: volume smontato → `os.walk` fallisce → log + skip (no crash). File
  sparito tra walk e probe → skip con traccia. Errori isolati per-file: un file rotto
  non blocca il ciclo.

## Sezione 2 — Match server-side (`app/services/deliverable_match.py`)

Funzione pura `score_match(probe, deliverable, delivery_item) -> MatchResult`
(testabile senza DB) + orchestratore `match_proposal(db, asset) -> None` che popola
`asset.matched_deliverable_id` o lascia i candidati per la UI.

- **Candidate set**: dal `rel_path` deriva il `project_code` (convenzione
  `watch_dirs` `/OUT/{project_code}/...`; override futuro per-progetto = backlog).
  Candidati = `JobDeliverable` dei job di quel progetto con `digital_asset_id IS NULL`
  e `status NOT IN (delivered, accepted)` e non cestinati.
- **Dimensioni di score** (ognuna pesata, somma normalizzata 0..1):
  - **naming** (peso alto): filename probed vs `JobDeliverable.file_naming` /
    `DeliveryItem.naming_convention` (match esatto / pattern-token / substring).
  - **container**: container probed vs `DeliveryItem.container_id`→nome.
  - **video codec**: codec probed vs `DeliveryItem.video_codec_id`→nome (mappa alias
    ffprobe→listino, es. `prores`↔ProRes, `h264`↔AVC).
  - **risoluzione**: `width×height` probed vs `DeliveryItem.resolution_id`→dims.
  - **frame rate**: probed `r_frame_rate` vs `DeliveryItem.frame_rate_id`→fps.
- **Soglie**: **forte** = naming concorde **e** ≥2 specs tecniche concordi (o score ≥
  0.75) → `matched_deliverable_id` settato (suggerimento, NON conferma). **debole** =
  0.4..0.75 → lista candidati ordinata, nessun pre-link. **zero** = <0.4 → proposta
  libera. Se manca `delivery_item_id` sul deliverable → match solo su naming + `spec_json`.
- **Idempotente**: rieseguibile; non scrive nulla se non c'è candidate set.

## Sezione 3 — Conferma + QC

- Conferma proposta (F1 `confirm_proposal`, esteso): se la proposta ha un deliverable
  scelto (match forte accettato o corretto dall'operatore) → set
  `JobDeliverable.digital_asset_id = asset.id`, `status → qc`, e apre la scheda QC
  riusando `qc_expected_for_deliverable` (confronto attese-vs-reali esistente).
- Correzione link: l'operatore può cambiare il deliverable suggerito tra i candidati
  (o cercarne uno) prima di confermare. Scarto = proposta `discarded` (F1).

## Sezione 4 — UI

- **`/storage` tab Proposte**: nuova colonna "Match" con badge (🟢 forte → nome
  deliverable / 🟡 debole → "N candidati" / ⚪ nessuno) + dropdown candidati per
  correggere il link prima di "Conferma". Conferma con deliverable scelto chiama
  l'endpoint esteso.
- **Mobile PWA `/m/proposte`** (nuova vista): lista proposte pending del tenant
  (nome, volume, size, badge match), tap → dettaglio (specs+checksum+candidati),
  bottoni **Conferma** / **Scarta** / **Correggi link** (dropdown candidati).
  Riusa il pattern delle viste mobile esistenti (`app/routers/mobile.py`).

## Sezione 5 — Modello dati

- **`Asset += matched_deliverable_id`** (FK `job_deliverables.id`, nullable, index):
  suggerimento di match PRE-conferma. Distinto da `JobDeliverable.digital_asset_id`
  (link confermato post-conferma). Auto-migrate colonna al boot (pattern F1/T2).
- Nessun nuovo modello. Watch = `AgentJob.type=scan` (già nell'enum F1). Stato watch
  = locale all'agent (in-memory), non persistito sul server.
- I candidati deboli NON sono persistiti: ricalcolati on-read dall'endpoint proposte
  (match è puro e veloce sul candidate set ristretto del progetto). Solo il match
  forte viene "cristallizzato" in `matched_deliverable_id`.

## Sezione 6 — Sicurezza / errori

- Scan rispetta `StorageVolume.read_only` (solo read; il watch non scrive mai).
- File sparito prima della conferma → la conferma fallisce con messaggio chiaro
  (asset orfano resta `pending_review`, l'operatore può scartarlo); job re-scan non
  lo ripropone (non più sul filesystem). Backlog: auto-scarto proposte con file
  sparito da > X (richiede un probe di verifica, F2.1).
- `project_code` non risolvibile dal path → proposta senza match (libera), nessun errore.
- Match cross-tenant impossibile: candidate set filtrato per `tenant_id` del volume.
- Watch interval e watch_dirs sono già config per-volume (F1); nessun nuovo segreto.

## Testing

- **Unit watch** (`tests/test_agent_watch.py`): dir finta con file che cresce poi si
  stabilizza → proposto solo dopo quiete; cartella con ASSETMAP → unità singola; file
  sparito → skip; volume inesistente → no crash. (Funzioni pure, no rete.)
- **Unit match** (`tests/test_deliverable_match.py`): `score_match` puro su coppie
  probe/deliverable note → forte/debole/zero; alias codec; deliverable senza
  delivery_item → naming-only; candidate set escluso (già linkato/cestinato/delivered).
- **E2E** (estende `tools/_e2e_f1.py` o nuovo): watch dir finta → file appare →
  proposta `agent_watch` + match forte su un JobDeliverable seed → conferma →
  `digital_asset_id` settato + `status=qc`.
- **Mobile smoke**: `/m/proposte` render + conferma da PWA.

## Fuori scope F2 (esplicito → fasi successive)

- Preview QC / streaming relay (F3).
- LTO YoYotta / MHL parse / restore (F4).
- TransferOrder / adapter tool (F5).
- Distruzione documentata / dashboard storage (F6).
- Override `output_dir` per-progetto (oggi solo convenzione path); auto-scarto proposte
  con file sparito; persistenza candidati deboli; long-poll vero (resta polling F1).

## Build incrementale

Ogni pezzo usabile/testabile da solo: (1) colonna+migrazione, (2) service match puro +
test, (3) wiring match nella creazione proposta + endpoint candidati, (4) watch agent +
test, (5) conferma→QC, (6) UI /storage match, (7) mobile, (8) E2E. Ordine
interfaccia-prima: modello → match → server wiring → agent → UI.
