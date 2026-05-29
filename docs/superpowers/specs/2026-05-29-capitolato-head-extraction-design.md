# Design — Estrazione TC / Timeline / Audio-config dai capitolati (vision pipeline)

> Data: 2026-05-29 · Target: v3.5.0-alpha.172.128+ · Autore: Matteo Lepore + Claude
> Stato: APPROVATO (sezioni 1-3) — in attesa review spec prima del piano
> Prerequisito: feature timeline/TC/audio-config (α.172.127) già su main.

## Problema

I campi `default_tc_start`/`default_program_start`/`default_timeline_segments` (template) e `AudioConfigPreset` (codici audio d'emittente tipo RAI 8T07/16T09 con mappatura tracce) introdotti in α.172.127 sono **vuoti o grezzi**: il backfill da `head_format` produce solo TC parziali e nessuna mappatura tracce. La fonte vera è nei **17 capitolati** in `docs/capitolati_esempio/`.

Una prova (dry-run su RAI) ha dimostrato che l'estrazione LLM **funziona** (8T07/16T09 + loudness + timeline estratti) ma con un **limite chiave**: `pypdf` non legge le **tabelle audio** (la mappatura per-traccia L/R/C/LFE/M&E del Capitolo 10 RAI viene persa → "Vedere Capitolo 10"). Serve un pipeline che preservi il dato tabellare.

## Decisioni di design (confermate con Matteo)

| # | Decisione | Scelta |
|---|-----------|--------|
| E1 | Lettura documento | **Vision su PDF** (pagine→immagini via PyMuPDF/`fitz`); docx/xlsx/txt = estrazione testo esistente (hybrid) |
| E2 | Livello popolamento | **Template default + AudioConfigPreset** (gli item ereditano TC/timeline; assegnazione codice→item resta manuale) |
| E3 | Workflow | **Entrambi**: bottone UI per-template (preview/Applica) + script batch per il bulk iniziale dei 13 |
| E4 | Taxonomy | Il modello **può proporre** nuove voci (`suggested_taxonomy`), ma **NO auto-integrazione**: proposte mostrate, le aggiunge l'utente |
| E5 | Pagine | **Scan tutte le pagine** (no targeting); cap di sicurezza alto + warning, mai silent truncation |
| E6 | Dipendenza | **PyMuPDF** (pip-only, niente binari esterni — coerente con policy no-WeasyPrint) |

## Sezione 1 — Architettura & flusso

### 1.1 Servizio `app/services/capitolato_head_extractor.py`

- `render_document_for_llm(file_bytes, filename) -> dict`
  - PDF → `fitz` apre, ogni pagina → PNG (DPI ~150), ritorna `{"mode":"vision","images":[bytes,...],"page_count":N}`. Se `N > CAP` (default 60) → include tutte ma logga warning "documento di N pagine, costo elevato".
  - docx/xlsx/txt/doc → `{"mode":"text","text": extract_text_from_file(...)}`.
- `extract_head_specs(provider, rendered, broadcaster, taxonomy_vocab) -> dict`
  - mode vision → `provider.chat` con messaggi multimodali (immagini + prompt); mode text → `provider.complete(system, user)`.
  - `taxonomy_vocab`: dict dei nomi taxonomy attivi iniettato nel prompt per il mapping ai nomi canonici.
  - Ritorna il JSON del contratto (Sez. 3). **Nessuna scrittura DB.**
- `apply_head_specs(db, template_id, parsed, tenant_id) -> dict`
  - Idempotente. Setta `template.default_tc_start/program_start/default_timeline_segments` **solo se presenti** nella preview (preview vuota non azzera).
  - Upsert `AudioConfigPreset` per `(delivery_template_id, code)`: se esiste aggiorna `name/description/track_layout`, else crea. `track_layout` con **name-keys** (channel_config/mix_type/mix_standard/codec) risolvibili da `apply_audio_config_preset`.
  - **NON** crea voci taxonomy (E4).
  - Ritorna `{tc_set, program_set, segments_n, presets_created, presets_updated, suggested_taxonomy}`.

### 1.2 Endpoint (router `delivery_items.py`, tenant-scoped + RequireEdit)

- `POST /delivery-templates/api/{tid}/extract-head` — risolve il file sorgente (`source_document_path` o per nome in `docs/capitolati_esempio/`), rende, estrae con `get_provider_for_user(current_user, db)`, **ritorna preview JSON (no write)**.
- `POST /delivery-templates/api/{tid}/apply-head` — riceve la preview JSON (Form `payload_json`, eventualmente editata), chiama `apply_head_specs`. Logga `AIAction` (kind `extract_head_specs`, status applied) per audit.

### 1.3 UI (`delivery_templates.html`, modal template)

Bottone **"🤖 Estrai TC/Timeline/Audio"** accanto a "🤖 Estrai items". Click → spinner → POST extract-head → **card preview**: TC start/program, lista segmenti timeline, preset audio (code + name + tracce), box "voci taxonomy da aggiungere a mano" (link `/settings/delivery-taxonomy`). Bottoni **Applica** (POST apply-head con il JSON) / **Annulla**. Pattern: data-attribute, escapeHtml, no JSON.stringify in onclick.

### 1.4 Batch `scripts/extract_head_specs_batch.py`

Per ogni template attivo con sorgente: extract + apply, report a tabella (template, tc, n segmenti, preset creati/aggiornati, n suggested_taxonomy). Flag `--dry-run` (solo preview/stampa, no write), `--only RAI,VISION` (filtro per code/broadcaster). Per il backfill iniziale dei 13.

### 1.5 Flusso

trigger (UI/batch) → `render_document_for_llm` (vision|text) → `extract_head_specs` (Claude) → preview → `apply_head_specs` (upsert idempotente). Re-run sicuro.

## Sezione 2 — Contratto di estrazione

```json
{
  "default_tc_start": "HH:MM:SS:FF | null",
  "default_program_start": "HH:MM:SS:FF | null",
  "timeline_segments": [
    {"order":1,"kind":"bars_tone|slate|countdown|counter|black|program|textless|logo|main_titles|tail|other",
     "label":"","tc_in":"","tc_out":"","duration":"","reel":null,"source":null,"notes":""}
  ],
  "audio_config_codes": [
    {"code":"8T07","name":"","description":"loudness/spec","tracks":[
       {"track_label":"T1","channel_config":"5.1","mix_type":"Full Mix","mix_standard":"EBU R128","codec":"PCM","sample_rate":48000,"bit_depth":24}
    ]}
  ],
  "suggested_taxonomy": [
    {"kind":"mix_type|channel_config|mix_standard|codec","name":"…","seen_as":"termine nel capitolato"}
  ],
  "confidence": 0.0,
  "source_notes": "non-strutturabile → qui (mai perdere info)"
}
```

### Strategia prompt

1. **Inietta vocabolario taxonomy** (nomi attivi di `AudioChannelConfig`/`AudioMixType`/`MixStandard`/`AudioCodec`) → il modello mappa i termini del capitolato ai **nomi canonici**; termini non presenti → li mette comunque (nome grezzo) **e** li elenca in `suggested_taxonomy`.
2. **TC normalizzato** HH:MM:SS:FF; prosa → estrai TC, resto in `notes`.
3. **Vision**: istruzione esplicita a leggere le **tabelle audio riga per riga** per la mappatura per-traccia (punto debole di pypdf).
4. **Fallback D5**: non-strutturabile → `source_notes` / `notes`.

## Sezione 3 — Edge case & testing

### Edge case
- **Sorgente mancante** (né `source_document_path` né file per nome in `docs/capitolati_esempio/`) → 404/errore chiaro; nel batch: skip con warning.
- **Doc non-PDF** → path testo.
- **Re-apply idempotente**: upsert preset per `(template, code)`; preview vuota non azzera i default.
- **Doc grande**: tutte le pagine in vision; cap alto (60) + warning se superato (no silent truncation).
- **TC prosa** → TC pulito, prosa in note.
- **Taxonomy non risolta**: traccia con nome grezzo + nota; nome in `suggested_taxonomy`. Nessuna auto-creazione.

### Testing
- **Unit (no LLM)**:
  - `apply_head_specs`: idempotenza (create→update preset, niente duplicati); setta TC/timeline; **preview vuota non azzera**; track_layout name-keys preservati; `suggested_taxonomy` ritornato.
  - `render_document_for_llm`: mode `vision` per `.pdf`, `text` per `.docx/.txt/.xlsx`; `page_count` corretto.
  - normalizzazione TC (prosa → HH:MM:SS:FF | null).
- **Estrazione LLM**: non deterministica → test del layer `apply` con dict fisso; **eval manuale** su RAI/Vision/Sky (preview validata da Matteo).

## Convenzioni rispettate
- Tenant scope + RBAC (RequireEdit) sugli endpoint mutator.
- `get_provider_for_user` (key per-utente cifrata) — non config globale.
- `AIAction` per audit dell'apply (pattern "AI propone, utente dispone").
- Idempotenza upsert; soft-delete preset già esistente.
- No JSON.stringify in onclick, escapeHtml, cache-buster automatico.
- PyMuPDF pip-only.

## Fuori scope (esplicito)
- Assegnazione automatica `audio_config_code` ai singoli item (E2: manuale via dropdown).
- Auto-creazione voci taxonomy (E4: solo proposte).
- Re-estrazione per-item delle spec tecniche (già coperta da `parse_delivery_items_v2`).
- OCR di PDF scansionati (i capitolati sono PDF testuali/tabellari nativi; se emerge uno scansionato → follow-up).

## Rischi / note
- Costo token vision su doc grandi (RAI ~molte pagine) → log costo, eval su 1 prima del batch.
- Mapping nomi→taxonomy imperfetto → `suggested_taxonomy` + note rendono il gap visibile e correggibile a mano.
- PyMuPDF licenza AGPL: uso interno/tool, accettabile; se distribuzione pubblica → rivalutare (nota per rebrand/lancio).
