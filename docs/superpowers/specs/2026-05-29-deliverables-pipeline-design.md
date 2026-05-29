# Design WIP — Pipeline Deliverables: Capitolato → Listino → Quote → Planning → Asset

> **STATO: brainstorming IN CORSO, design NON ancora approvato.** Niente codice finché approvato.
> Interrotto il 29 mag 2026 alla domanda "adapt vs greenfield" (vedi §Open).
> Alla ripresa: Matteo voleva *chiarire* quella domanda prima di rispondere → chiedergli cosa vuole chiarire.

## Obiettivo (parole di Matteo)
Collegare i due mondi oggi separati: capitolato (`DeliveryItem`, specs tecniche complete) e listino/quote/planning/asset. Pipeline:

```
Capitolato (DeliveryItem = menù completo specs)
  → Listino voci GENERICHE (bucket tecnico)        [pochissime, riusate]
  → Quote (picker a spunte → righe; specifiche capitolato nel campo detail di riga)
  → Job → Planning Deliveries (JobDeliverable: snapshot editabile dal DeliveryItem, affini specs per-file)
  → Asset popolato (specs attese → QC / delivery / LTO / transfer)
```
Principio: **capitolato = vedi/correggi TUTTE le opzioni (anche opzionali)**; **planning deliveries = selezioni le specifiche del file reale** dagli item → spinte all'asset.

## Decisioni prese (Q&A)

1. **Voce di listino = bucket tecnico GENERICO** keyed da `(package | container) + codec + risoluzione`.
   Es. "ProRes 422 HQ / 1080p25", "DCP / JPEG2000 / 2K", "IMF / JPEG2000 / UHD".
   **Molti DeliveryItem → una voce** (molti-a-uno). **Match-or-create** sulla tripla. Scope = **ridurre all'osso** il numero di voci + **uniformità**.
   - NIENTE `PriceItem.delivery_item_id` 1:1 (superato). Link via `DeliveryItem.price_item_id` (molti-a-uno) — *da verificare se il campo esiste; oggi c'è `suggested_price_item_id` su DeliveryItem usato da `delivery_item_pricelist_match`*.

2. **Specifiche di capitolato → campo `detail` della riga in QUOTE** (inline-edit esistente `data-field="detail"`, `saveLineField`). NON nella voce di listino. Esempio detail: piattaforma upload (Frame.io/Pix/Aspera), limiti accesso, frame range giornaliero, LUT custom, naming.
   - Descrizione della **voce listino** = sunto tecnico generico del bucket (NO roba di capitolato).

3. **Categoria "Deliveries"** generica per le voci bucket. Raggruppamento per-capitolato **NON** via FK 1:1 (una voce serve N capitolati → relazione N:N). Il legame al capitolato vive nella **QUOTE** (section/label di riga + detail per riga).

4. **Planning deliveries (cuore)**: JobDeliverable **precompilato via SNAPSHOT dal DeliveryItem** (container/package/codec/audio_tracks/timeline/lingue) → affini per-file (audio layout, lingua, tracce opzionali `is_optional`…) salvato in **`JobDeliverable.spec_json`**. Non tocca il capitolato.

5. **Asset**: confermato il JobDeliverable → nasce/collega Asset con specs affinate come **"attese"** (`digital_asset_id`/`physical_asset_id`). File reale allegato dopo → **QC confronta** file vs attese (riusa `qc_expected_for_deliverable`). LTO/transfer leggono dall'Asset.

6. **Quote = solo commerciale**: picker a spunte mostra le voci deliverable → sottoinsieme → righe (prezzo dal listino) + detail per riga. **JobDeliverable + affinamento SOLO in planning**, attingendo al capitolato collegato al job. Decoupled da quote lines.

7. **Booking modal (planning)**: mostra **tipo file (container/package) + nome item** del JobDeliverable collegato.

## Fatti di codice rilevanti (verificati)
- `JobDeliverable` (models.py:3270) ha già: `delivery_item_id` (provenienza), `delivery_template_id`, `price_item_id`, `spec_json` (→ snapshot affinato), `digital_asset_id`/`physical_asset_id`, `asset_locked_at`, campi QC. **Nessun campo nuovo necessario.**
- Esistente: `DeliveryTemplate.suggested_items` (JSON ref listino) + `POST /quotes/api/{id}/load-from-template` (bulk insert con `section` A/B/C). = la "funzione già esistente" da migliorare → diventa picker a spunte.
- `delivery_item_pricelist_match.py` = AI match DeliveryItem↔PriceItem (suggested_price_item_id).
- `qc_expected_for_deliverable` (delivery_timeline_service.py) = già calcola tc/timeline/audio attesi per QC.
- Listino attuale ~45 voci, di cui **~13 deliverable** non uniformi: categorie DELIVERABLES VIDEO(5), DELIVERABLES SOUND(5), MASTERING DCP/DCDM(3), + ARCHIVE/TRANSFER, DAILIES, LOCALIZATION, MIX, PICTURE/DI, PROJECT MANAGEMENT, QC/METADATA, SOUND EDIT, VFX.

## OPEN — RISOLTA (29 mag 2026, ripresa)
**Scelta = B (Consolida).** Riscrivo le ~13 voci deliverable esistenti nello schema uniforme per-tripla + rimappo i riferimenti quote/job. Un solo sistema.
**Rischio dati accettato esplicitamente da Matteo**: "non ti preoccupare dei progetti attualmente in opera, possiamo sbagliare". → Migrazione non difensiva, niente tabella di compatibilità old→new obbligatoria.

## Decisioni post-Open (29 mag 2026, RISOLTE)

8. **Chiave "tripla" voce-bucket** = `(package | container) + codec + risoluzione + HDR/colorspace`.
   - Framerate e aspect ratio NON nel bucket (stanno nelle specs item, non cambiano prezzo).
   - **HDR/colorspace SÌ nel nome** (es. "ProRes UHD HDR10" ≠ "ProRes UHD SDR": lavorazione/prezzo diversi).
   - Normalizzazione package vs container: **package se presente, altrimenti container** (un item ha package_id O container_id; alcuni entrambi → vince package come forma di consegna primaria).
   - Esempi nome: "DCP / JPEG2000 / 2K", "ProRes 422 HQ / 1080p / Rec.709", "IMF / JPEG2000 / UHD / HDR10".

9. **Link DeliveryItem→voce-bucket** = **riuso `suggested_price_item_id`** come link canonico (da "suggerito AI" a "confermato"). Zero migrazione schema, nessuna colonna nuova. La descrizione UI/semantica passa da "suggerito" a "voce bucket collegata".

10. **Sorgente picker quote** = **derivata dai DeliveryItem del template** collegato al job. Set = voci-bucket distinte dei DeliveryItem (via `suggested_price_item_id`). Live, riflette il capitolato reale, N:N naturale. `template.suggested_items` NON usato per questo.

11. **Audio NON usa la tripla video** (gap emerso dai dati reali: 61 item audio collassavano in 1 bucket "WAV"). `bucket_key()` **ramifica per media_kind**:
    - **video** → `(package|container) + codec + risoluzione + HDR` (es. "ProRes 422 HQ / 1080p", "DCP / JPEG2000 / 2K", "ProRes UHD HDR10")
    - **audio** → `mix_type/role + channel_config` dalla traccia primaria (es. "Full Mix 5.1", "M&E 5.1", "DME Stems 5.1", "LtRt Stereo", "Atmos ADM")
    - **sidecar** (subtitle/KDM/ISO/doc) → per tipo container (es. "Subtitle EBU-STL", "KDM", "ISO Disc", "Document")
    - Panorama reale 211 item → **~53 bucket** (~30 video + ~19 audio + ~4 sidecar). Riuso 4x.

## Trattamento vecchie 13 voci (B, rischio accettato)
- Le 13 voci cat MASTERING DCP(3)/DELIVERABLES VIDEO(4)/DELIVERABLES SOUND(9) → **soft-delete** dopo migrazione (superate dai bucket uniformi). NON rimappo le quote-line storiche (Matteo: "possiamo sbagliare" → niente migrazione difensiva). Restano puntate a item inattivi senza rompersi.
- Nuova categoria **"Deliveries"** unica per tutti i bucket. Match-or-create per `name` (= label bucket) entro la categoria.

## Fasatura build (CONFERMATA)
- **F1 — Modello + consolidamento listino**: service `bucket_key(delivery_item)` + match-or-create voce-bucket nella categoria "Deliveries" + migrazione B (riscrive le ~13 esistenti uniformi, rimappa quote/job, backfill `suggested_price_item_id` su tutti i 211 DeliveryItem). Test prima.
- **F2 — Quote picker a spunte**: endpoint "voci-bucket di questo capitolato" (derivato) + UI picker → genera righe (prezzo da listino, `detail` per specifiche capitolato). Migliora `load-from-template`.
- **F3 — Planning affinamento + asset + booking**: JobDeliverable snapshot da DeliveryItem in `spec_json` + affinamento per-file + conferma→Asset atteso + booking modal mostra tipo file + nome item.

## Stato ambiente (sessione 29 mag 2026)
- 6 commit pushati (ultimo `ad466e3`), v3.5.0-alpha.172.134. Lavori chiusi oggi: fix 500 extract-head, audio config UI+reattivo, timeline default ereditabile, **cascata estrazione testo-prima PyMuPDF4LLM** (+vision fallback), warning reword, export ZIP.
- `pymupdf4llm`+`pdfplumber` in venv + requirements. Server up (health 200), tunnel cloudflared attivo. Provider attivo = **DeepSeek** (text-only confermato, vision solo Claude).
