# Design — Timeline / TC Start / Audio Config sui Delivery Item

> Data: 2026-05-28 · Target: v3.5.0-alpha.172.127+ · Autore: Matteo Lepore + Claude
> Stato: APPROVATO (sezioni 1+2) — in attesa review spec prima del piano

## Problema

I capitolati definiscono dettagli tecnici critici che oggi MediaFlow **non cattura in forma strutturata**, quindi non sono né riportabili in modo affidabile né verificabili in QC:

1. **TC Start / Program Start** — es. Vision: i file partono da `00:59:59:00` (1s di nero prima del programma), programma a `01:00:00:00`. Se indicato, va **sempre** riportato.
2. **Timeline / "programma del file" (head/tail build)** — es. RAI: barre+toni, slate/coda di identificazione, counter RAI, nero, programma, code. Struttura precisa.
3. **Audio configuration code** — es. RAI `8T07`, `16T09`: codifiche rigide che mappano una configurazione audio precisa (N tracce con layout definito). Diverse combinazioni possibili, ma quasi sempre le stesse per emittente.

### Stato attuale (cosa esiste già)

- `DeliveryTemplate.head_format` (JSON, livello broadcaster) cattura **parzialmente** la timeline ma come **testo libero**, non strutturato, non QC-abile, non mostrato nella UI granulare Tier 2. Esempi reali nel DB:
  - RAI: `bars_required`, `slate_required`, `beep_2pop`, `timecode_start`, `head_sections`, `tail_sections`.
  - Vision: `timecode_start: "59:59:00"`, `program_start: "01:00:00:00"`, `tail_black`, `dcp_reel_structure: "Un logo = un rullo; titoli di testa = un rullo separato"`.
- `DeliveryItem.extra_specs` (JSON libero) ha roba sparsa (`timecode: "LTC coincidente con VITC"`).
- **Audio config code (8T07): non modellato per niente.**

Il problema non è "manca un posto", è che il dato è **sparso, non strutturato, non arriva al QC, e i codici audio mancano**.

## Decisioni di design (confermate con Matteo)

| # | Decisione | Scelta |
|---|-----------|--------|
| D1 | Quanto strutturato | **Campi dedicati + tabella preset audio** (no note libere, no JSON-bag generico) |
| D2 | Audio code → tracce | **Materializza** le `AudioTrackSpec` concrete (codice salvato come riferimento) |
| D3 | Livello TC/timeline | **Default su template, override su item** (eredità) |
| D4 | Scope preset audio | **Legati al DeliveryTemplate** (ogni capitolato porta i suoi codici, no riuso cross-template) |
| D5 | Fallback | Se il parser non struttura → riporta in `notes` (mai perdere info) |

## Sezione 1 — Modello dati

### 1.1 Nuovi campi su `DeliveryItem` (livello override)

| Campo | Tipo | Note |
|-------|------|------|
| `tc_start` | str nullable | es. `00:59:59:00` |
| `program_start` | str nullable | es. `01:00:00:00` |
| `timeline_segments` | JSON nullable | lista ordinata di segmenti (shape sotto) |
| `audio_config_preset_id` | FK → `audio_config_presets.id` nullable | preset scelto |
| `audio_config_code` | str nullable | denormalizzato per display/report rapido (es. `8T07`) |

### 1.2 Shape `timeline_segments`

```json
[
  {
    "order": 1,
    "kind": "bars_tone",
    "label": "Barre EBU + tono 1kHz -18dBFS",
    "tc_in": "00:58:30:00",
    "tc_out": "00:59:30:00",
    "duration": "00:01:00:00",
    "reel": null,
    "source": null,
    "notes": null
  }
]
```

- `kind` ∈ `bars_tone | slate | countdown | counter | black | program | textless | logo | main_titles | tail | other`
- `reel` — numero/id rullo DCP (Vision: "1 logo = 1 rullo; titoli di testa = 1 rullo separato")
- `source` — materiale sorgente (es. "ProRes logo via link Vimeo, approvazione preventiva Vision")
- Tutti i campi tranne `order`/`kind` sono opzionali → ciò che non si struttura va in `notes` del segmento o dell'item.

### 1.3 Nuovi campi su `DeliveryTemplate` (livello default emittente)

| Campo | Tipo | Note |
|-------|------|------|
| `default_tc_start` | str nullable | default emittente |
| `default_program_start` | str nullable | default emittente |
| `default_timeline_segments` | JSON nullable | stessa shape di 1.2 |

`head_format` **resta invariato** (legacy 8-block): è la fonte da cui la migrazione popola i `default_*`.

### 1.4 Nuova tabella `AudioConfigPreset` (legata al template)

| Campo | Tipo | Note |
|-------|------|------|
| `id` | PK | |
| `tenant_id` | FK nullable | denormalizzato (scope tenant) |
| `delivery_template_id` | FK → `delivery_templates.id` | proprietario del codice |
| `code` | str | es. `8T07`, `16T09` |
| `name` | str | descrizione breve |
| `description` | str nullable | |
| `track_layout` | JSON | definizione tracce (shape sotto) |
| `sort_order` | int | |
| `is_active` | bool | soft-delete |
| `created_at`/`updated_at` | datetime | |

- UNIQUE `(delivery_template_id, code)` — con `execution_options(include_deleted=True)` per evitare collisioni con soft-deleted.
- `track_layout` shape (si materializza in `AudioTrackSpec`):

```json
[
  {
    "track_label": "5.1 L",
    "channel_config": "5.1",
    "mix_type": "Full Mix",
    "mix_standard": "EBU R128",
    "codec": "PCM",
    "sample_rate": 48000,
    "bit_depth": 24
  }
]
```

I valori `channel_config`/`mix_type`/`mix_standard`/`codec` sono nomi che vengono risolti agli id taxonomy esistenti (`AudioChannelConfig`/`AudioMixType`/`MixStandard`/`AudioCodec`) in fase di materializzazione; se non risolti → si crea la traccia con i campi noti + nota.

### 1.5 Flusso audio (materializzazione)

1. L'operatore (o il parser) sceglie un `AudioConfigPreset` sull'item.
2. Si creano N `AudioTrackSpec` concrete a partire da `track_layout` (editabili dopo).
3. Si salva `audio_config_preset_id` + `audio_config_code` (denormalizzato) sull'item.
4. Cambiare preset → conferma utente, ri-materializza (sostituisce le tracce derivate; preserva eventuali tracce aggiunte a mano? → **decisione implementativa**: ri-materializza in blocco con conferma, l'utente riedita se serve).

## Sezione 2 — Parser, UI, QC, Migrazione

### 2.1 Parser (`app/services/delivery_items_parser.py`, pass 2)

- Per ogni item estrae `tc_start` / `program_start` se presenti nel capitolato.
- Costruisce `timeline_segments` da barre/toni/slate/counter/nero/program/tail (+ reel/source per DCP).
- Riconosce i codici audio (`8T07`, `16T09`, …): per ogni codice crea/collega un `AudioConfigPreset` sul template e materializza le `AudioTrackSpec` sull'item.
- A livello template estrae i `default_*` da `head_format` / sezione testa del documento.
- Fallback D5: ciò che non si struttura → `notes`.

### 2.2 UI (`/delivery-templates`, modal item — già 3 tab)

- **Tab Items → card item**: nuova sezione **"⏱ Timeline & TC"**:
  - campi `tc_start`, `program_start` (placeholder grigio = valore ereditato dal template se vuoto)
  - editor `timeline_segments`: tabella ordinabile (add/remove/riordino), colonne kind/label/tc_in/tc_out/reel/source/notes
  - dropdown **Audio config** popolato dai preset del template → on-select materializza le tracce nel pane Audio
- **Admin template**: sezione "Default emittente" (`default_tc_start`/`program`/`timeline`) + CRUD `AudioConfigPreset` per template.
- **Eredità**: campo item vuoto → mostra il default del template in grigio con etichetta "ereditato da {broadcaster}".
- Pattern UI esistenti: data-attribute (no JSON.stringify in onclick), escapeHtml da global.js, cache-buster automatico.

### 2.3 QC (minimo ora, estendibile)

- I campi spec (`tc_start`, `program_start`, `timeline_segments`, tracce audio materializzate) entrano nel **context del QC** come "valori attesi" che l'operatore verifica al QC.
- Auto-generazione di check-list QC dai segmenti (es. "verifica barre 00:58:30→00:59:30", "verifica TC start 00:59:59:00") → **fase successiva**, non in questo giro.

### 2.4 Migrazione (`scripts/migrate_*.py` idempotente, pattern del progetto)

- ALTER `delivery_items` (+5 colonne) e `delivery_templates` (+3 colonne) via SQL idempotente.
- Registrare le nuove colonne in `_auto_migrate_columns()` (lifespan `main.py`) per auto-migrazione al boot (lezione α.172.125: colonna senza check al boot = crash su DB non migrato).
- CREATE `audio_config_presets` + indici FK + UNIQUE.
- Backfill: popola `default_timeline_segments`/`default_tc_start`/`default_program_start` dei template parsando `head_format` esistente (RAI/Vision già hanno i dati).
- Nessun dato distrutto. Snapshot DB pre-migrazione in `db_snapshots/`.

## Convenzioni rispettate

- Tenant scope su tutte le query (`tenant_id`), helper `tenant_guard` dove applicabile.
- RBAC permission gate sui mutator (edit taxonomy/templates).
- Soft-delete (`is_active`) su `AudioConfigPreset`.
- Form-based API (non JSON) per i POST/PUT.
- Modelli SQLAlchemy 2.0 `Mapped[]` + `mapped_column`.
- AI capability: valutare `propose_audio_config_preset` / `propose_timeline_segment` nel registry copilot (coerente con feedback "ogni mutator → propose_*"). → **fase successiva**.

## Fuori scope (esplicito)

- Auto-generazione check-list QC dai segmenti (solo context ora).
- AI capability copilot per timeline/audio-config (valutate dopo).
- Validazione cross-tier su tc_start/timeline (nuove regole R10+) — possibile follow-up.

## Rischi / note aperte

- `track_layout` → risoluzione nomi a id taxonomy: gestire mismatch (crea traccia parziale + nota).
- Ri-materializzazione su cambio preset: conferma utente, sostituzione in blocco.
- Parser LLM: i codici audio e i TC vanno estratti con prompt mirato; rischio di sotto-estrazione su capitolati densi (vedi NBCU 1-item). Validare sul corpus reale (RAI/Vision/Sky).
