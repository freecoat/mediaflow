# Bundle L — Tech specs unified (Asset ↔ Deliverable ↔ QC)

**Status:** Design v1 — pending user approval
**Date:** 2026-05-26
**Owner:** Matteo Lepore (product) + Claude Opus 4.7 (design)
**Target version:** v3.5.0-alpha.172.94 → 100 (5 stack consecutivi)
**Brainstorm session:** `.superpowers/brainstorm/1596-1779807005/` (9 schermate Q1→Q9)

---

## 1. Context & Problem Statement

MediaFlow oggi tratta le specifiche tecniche di consegna come JSON freeform su 3 modelli indipendenti:

- `DeliveryTemplate.spec_json_full` (template gerarchico 8 blocchi: video/audio/text/head/textless/naming/archive/metadata)
- `JobDeliverable.spec_json` (libero, prefill da template)
- `Asset.tech_specs` non esiste (estratto on-demand via ffprobe, perso)

Il flusso reale di una casa di post-produzione invece è una catena di **tre layer + un loop di verifica**:

```
CAPITOLATO CLIENTE  →  DELIVERABLE PIANIFICATO  →  ASSET PRODOTTO  →  QC REPORT
   (template)             (work order)              (file reale)        (verdetto)
```

Manca:

1. Un **modello strutturato unificato** per le varianti di consegna (Master HD IT, Trailer 60s textless, IMF OV+SUB en SDH, …). Ogni capitolato è una matrice complessa: Versione × Lingua × Sottotitoli × Textless × Territorio × Formato.
2. **Persistenza tech specs Asset** estese da ffprobe + tooling per estensione (MediaInfo, AI vision, ContentArmor).
3. **Modello QC report** multi-iterazione (un deliverable può subire N QC: pass/reject/re-export). Excel attuale di Matteo (`docs/qc/FbF_QC-Report_Template.xlsx`) come schema canonico.
4. **Ingest capitolati** in modo automatizzato: 17 corpus esistenti + nuovi che arrivano + bridge automatico verso il listino (PriceItem suggestion per voci tech).
5. **Versionatura schema**: il mondo broadcast evolve (HDR PQ 2026, Atmos new specs, …). Stack consecutivi richiedono evoluzione senza rotture.

Bundle L risolve tutto questo come **cantiere centrale snodo planning ↔ asset management**.

---

## 2. Decisioni chiave (recap brainstorm Q1→Q9)

| # | Domanda | Decisione |
|---|---------|-----------|
| Q1 | Da dove partire? | **A — Capitolato-first**. La verità sta nel capitolato; tutto deriva. |
| Q2 | Scope corpus per estrazione schema canonico? | **C — Tutti 17 in batch AI**. Copertura totale subito. |
| Q3 | Modello combinazioni (vers/lingua/sub/textless)? | **B — Catalog `DeliveryVariant`** entità separata referenziata da `JobDeliverable.variant_id`. Modularità + zero duplicazione. |
| Q4 | Struttura interna variant? | **C — JSON con schema-version + JSON Schema validation**. UI form auto-generata dallo schema; stack consecutivi = nuova versione schema, back-compat. |
| Q5 | Modello QC report multi-iter? | **C — Event-sourced `QCEvent` append-only**. Audit perfetto, replay possibile, projection materializzata `QCReport`. |
| Q6 | Snapshot tech specs Asset? | **D — Extractor service estensibile** (ffprobe oggi, MediaInfo/AI vision/ContentArmor domani). Plugin registry. `Asset.tech_specs_json` cached + snapshot immutabile in QCEvent. |
| Q7 | AI capabilities primo stack? | **B + E + F**: `ingest_qc_excel`, `suggest_variants_for_job`, `export_qc_report`. `propose_qc_from_asset_diff` (C) promossa in Stack 2. Capability A `extract_capitolato_to_variants` rimandata a Stack 5. |
| Q8 | Pipeline parsing capitolati + bridge listino? | **C — Ibrido**: batch one-shot ora (Stack 1) + capability runtime dopo (Stack 5). Classificazione **T1 tech / T2 doc / T3 compilation**. Solo T1 → suggested PriceItem listino. |
| Q9 | Roadmap stack? | **A — Confermo 5 stack** nell'ordine 1→5. |

Nota Matteo (Q7): "Cerca di dividere gli item rilevanti per consegna files di tipo tecnico. Documentazione/contrattistica/compilativo sono catalogati ma decisamente meno rilevanti per ora." → guida la classificazione T1/T2/T3 durante parsing.

---

## 3. Architettura — Entità e relazioni

```
┌─────────────────────────┐
│ VariantSchemaVersion    │ ── JSON Schema versionato (v1, v2, …)
│  - id, version          │     per validazione + UI form gen
│  - schema_json (JSON)   │
│  - is_active            │
└────────────┬────────────┘
             │ FK
┌────────────▼────────────┐         ┌──────────────────────┐
│ DeliveryVariant         │         │ PriceItem            │
│  - tenant_id            │ ◀────── │  - variant_id (opt)  │
│  - code, name           │  hint   │                      │
│  - category (T1/T2/T3)  │         │  bridge T1 → listino │
│  - schema_version_id    │         └──────────────────────┘
│  - spec_json            │
│  - language, territory  │
│  - source_capitolato    │
└────────────┬────────────┘
             │ FK
┌────────────▼────────────┐         ┌──────────────────────┐
│ JobDeliverable (esiste) │         │ DeliveryTemplate     │
│  - variant_id (NEW FK)  │ ◀────── │  - default_variant_id│
│  + override fields ↑    │ legacy  └──────────────────────┘
└────────────┬────────────┘
             │ 1:N
┌────────────▼────────────┐         ┌──────────────────────┐
│ QCEvent (NEW, AOL)      │ ◀────── │ Asset (esistente)    │
│  - deliverable_id FK    │ snap    │  + tech_specs_json   │
│  - asset_id FK          │         │  + extractor_name    │
│  - qc_number            │         │  + extracted_at      │
│  - event_type           │         └──────────────────────┘
│  - payload_json         │
│  - operator_id          │              ▲
└────────────┬────────────┘              │
             │ projection                │
┌────────────▼────────────┐         ┌────┴─────────────────┐
│ QCReport (view materzd) │         │ tech_specs_extractor │
│  - deliverable_id       │         │   service registry   │
│  - last_qc_number       │         │  (ffprobe, MediaInfo,│
│  - overall_status       │         │   AI vision, …)      │
│  - errors_count, …      │         └──────────────────────┘
└─────────────────────────┘
```

**Punto chiave:** `JobDeliverable.variant_id` è la **single source of truth** per le specs richieste. La variant porta lo `spec_json` validato contro `VariantSchemaVersion.schema_json`. `Asset.tech_specs_json` è la fonte realtà. QCEvent registra le differenze.

---

## 4. Data model dettagliato

### 4.1 `VariantSchemaVersion`

```python
class VariantSchemaVersion(Base):
    __tablename__ = "variant_schema_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # "v1", "v2-hdr-2026"
    schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)            # JSON Schema draft-07
    description: Mapped[Optional[str]] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)             # solo 1 attivo per tenant
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

Schema attivo determina i campi disponibili in UI form. Variant precedenti restano valide contro la loro versione.

### 4.2 `DeliveryVariant` (NEW)

```python
class DeliveryVariantCategory(str, enum.Enum):
    t1_technical = "t1_technical"     # Master/IMF/DCP/Trailer/Textless/Audio/Sub/Archive/Stills
    t2_documentation = "t2_documentation"  # CDL, LUT, spotting list, metadata template
    t3_compilation = "t3_compilation"      # NDA, contratti, form

class DeliveryVariant(Base):
    __tablename__ = "delivery_variants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    code: Mapped[str] = mapped_column(String(80), index=True)         # "imf-master-hd-it"
    name: Mapped[str] = mapped_column(String(255))                    # "IMF Master HD — Italiano"
    category: Mapped[DeliveryVariantCategory] = mapped_column(
        SAEnum(DeliveryVariantCategory), default=DeliveryVariantCategory.t1_technical, index=True
    )
    schema_version_id: Mapped[int] = mapped_column(ForeignKey("variant_schema_versions.id"))
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False)     # validate contro schema_version
    # Campi promossi a colonne per query/filter veloci
    language: Mapped[Optional[str]] = mapped_column(String(10), index=True)    # "it", "en", "og"
    territory: Mapped[Optional[str]] = mapped_column(String(10), index=True)   # "WW", "IT", "US"
    has_textless: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    has_subtitles: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_format: Mapped[Optional[str]] = mapped_column(String(20), index=True)  # "IMF", "DCP", "ProRes", "MXF"
    # Origine / tracciabilità
    source_capitolato: Mapped[Optional[str]] = mapped_column(String(255))      # "Netflix_Deliverables.txt"
    source_section: Mapped[Optional[str]] = mapped_column(String(255))         # "Master Deliverables §3.1"
    suggested_price_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("price_items.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_variant_tenant_code"),)
```

### 4.3 `JobDeliverable` (estensione)

```python
# Aggiunte a JobDeliverable (modello esistente):
variant_id: Mapped[Optional[int]] = mapped_column(
    ForeignKey("delivery_variants.id"), nullable=True, index=True
)
# Campi promossi (override possibile della variant — copia "snapshot" al spawn)
variant_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
variant_territory: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
variant_format: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
# spec_json esistente diventa "override" della variant.spec_json (merge applicato)
```

**Decisione semantica:** quando `variant_id` è set, `spec_json` rappresenta SOLO i campi override (parziale). Il resolver applica `merged = {**variant.spec_json, **deliverable.spec_json}` a runtime per validation/display.

### 4.4 `Asset` (estensione)

```python
# Aggiunte a Asset (modello esistente):
tech_specs_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
tech_specs_extractor: Mapped[Optional[str]] = mapped_column(String(40))    # "ffprobe", "mediainfo", "ai_vision"
tech_specs_extracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
tech_specs_schema_version: Mapped[Optional[str]] = mapped_column(String(20))  # allinea al variant schema
```

### 4.5 `QCEvent` (NEW, append-only)

```python
class QCEventType(str, enum.Enum):
    qc_started = "qc_started"
    video_error_logged = "video_error_logged"
    audio_error_logged = "audio_error_logged"
    text_error_logged = "text_error_logged"
    recommendation_added = "recommendation_added"
    qc_passed = "qc_passed"
    qc_failed = "qc_failed"
    qc_conditional = "qc_conditional"
    snapshot_taken = "snapshot_taken"  # cristallizza tech_specs asset

class QCEvent(Base):
    __tablename__ = "qc_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    deliverable_id: Mapped[int] = mapped_column(ForeignKey("job_deliverables.id"), index=True)
    asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    qc_number: Mapped[int] = mapped_column(Integer, index=True)         # 1, 2, 3 … per deliverable
    sequence: Mapped[int] = mapped_column(Integer)                       # ordinamento intra-QC
    event_type: Mapped[QCEventType] = mapped_column(SAEnum(QCEventType), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)     # struttura tipizzata per event_type
    operator_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(40))            # "manual", "excel_ingest", "ai_diff"
    source_excel_path: Mapped[Optional[str]] = mapped_column(String(512))
```

**Append-only** garantito da listener SQLAlchemy che rifiuta UPDATE/DELETE su QCEvent (eccetto super-admin).

### 4.6 `QCReport` projection (vista materializzata leggera)

Modello SQLAlchemy che è **derivato** da QCEvent stream — può essere:
- View SQL (semplice ma read-only ridotto)
- Tabella materializzata aggiornata da event listener (più potente, snapshot rapido)

**Scelta:** tabella materializzata aggiornata via SQLAlchemy `after_insert` listener su QCEvent. Refresh esplicito tramite `qc_report_rebuild(deliverable_id)` se serve.

```python
class QCReport(Base):
    __tablename__ = "qc_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deliverable_id: Mapped[int] = mapped_column(ForeignKey("job_deliverables.id"), unique=True, index=True)
    last_qc_number: Mapped[int] = mapped_column(Integer, default=0)
    overall_status: Mapped[str] = mapped_column(String(20))              # "pass", "fail", "conditional", "in_progress"
    video_errors_count: Mapped[int] = mapped_column(Integer, default=0)
    audio_errors_count: Mapped[int] = mapped_column(Integer, default=0)
    text_errors_count: Mapped[int] = mapped_column(Integer, default=0)
    max_grade: Mapped[Optional[int]] = mapped_column(Integer)            # 1-4 (4 = stop-down)
    last_operator_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    last_event_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    summary_json: Mapped[Optional[dict]] = mapped_column(JSON)           # cache per UI tabellare
```

---

## 5. JSON Schema canonico Variant v1 (esempio)

`schemas/variant_v1.json` (committato in repo, caricato in `VariantSchemaVersion` al boot):

```json
{
  "$schema": "https://json-schema.org/draft-07/schema",
  "$id": "claqo/variant/v1",
  "type": "object",
  "required": ["code", "name", "category"],
  "properties": {
    "code": {"type": "string", "pattern": "^[a-z0-9-]+$"},
    "name": {"type": "string", "minLength": 3},
    "category": {"enum": ["t1_technical", "t2_documentation", "t3_compilation"]},
    "container": {
      "type": "object",
      "properties": {
        "format": {"enum": ["IMF", "DCP", "ProRes", "MXF", "MOV", "MP4", "TIFF", "DPX", "WAV", "SCC", "TTML", "VTT"]}
      }
    },
    "video": {
      "type": "object",
      "properties": {
        "resolution": {"type": "string"},
        "codec": {"type": "string"},
        "framerate": {"type": "number"},
        "color_space": {"enum": ["BT.709", "BT.2020", "P3-D65", "P3-DCI", "DCI-XYZ"]},
        "hdr": {"type": "boolean"},
        "hdr_format": {"enum": [null, "PQ", "HLG", "Dolby Vision", "HDR10+"]},
        "chroma": {"enum": ["4:2:0", "4:2:2", "4:4:4"]},
        "bit_depth": {"enum": [8, 10, 12, 16]},
        "field_order": {"enum": ["progressive", "interlaced_uff", "interlaced_lff"]}
      }
    },
    "audio": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "track": {"type": "string"},
          "codec": {"enum": ["PCM", "Atmos", "AAC", "AC3", "EAC3", "DTS"]},
          "channels": {"type": "integer"},
          "sample_rate": {"enum": [48000, 96000]},
          "bit_depth": {"enum": [16, 24]},
          "language": {"type": "string"}
        }
      }
    },
    "subtitles": {"type": "object", "properties": {"present": {"type": "boolean"}, "type": {"enum": [null, "burnt", "sidecar_scc", "sidecar_vtt", "sidecar_ttml", "sdh"]}}},
    "textless": {"type": "object", "properties": {"tail_present": {"type": "boolean"}, "separate_file": {"type": "boolean"}}},
    "language": {"type": "string"},
    "territory": {"type": "string"},
    "naming": {"type": "string"},
    "head_format": {"type": "object"},
    "archive": {"type": "object"},
    "metadata": {"type": "object"}
  },
  "additionalProperties": true
}
```

`additionalProperties: true` permette stack consecutivi (nuovi field non breakano old variant). Per migration semantica → bump schema version v2 con `required` aggiornato.

---

## 6. Tech specs extractor service architecture

`app/services/tech_specs_extractor/`:

```
__init__.py            # registry + public API
base.py                # TechSpecsExtractor ABC
ffprobe_extractor.py   # default (estende asset_metadata esistente)
pillow_extractor.py    # fallback immagini
registry.py            # extractor by mime/codec
```

API pubblica:

```python
from app.services.tech_specs_extractor import extract_tech_specs

specs = extract_tech_specs(asset_path, mime_type, prefer="ffprobe")
# → dict con shape canonica schema variant_v1 (subset estraibile)
# → caller persiste in Asset.tech_specs_json
```

Plugin registry permette di registrare nuovi extractor:

```python
from app.services.tech_specs_extractor import register_extractor

@register_extractor(name="mediainfo", mime_priority=["video/*"])
class MediaInfoExtractor(TechSpecsExtractor):
    def extract(self, path, mime) -> dict: ...
```

**Refresh policy:** estrazione al primo upload (background task tramite `enqueue_thumbnail_generation` pattern già esistente). Refresh manuale "↻ Riestrai" + auto-refresh al QC start se `extracted_at > 30 giorni`.

---

## 7. QC event-sourced flow

### 7.1 Avvio QC

```python
def start_qc(db, deliverable_id, asset_id, operator_id) -> int:
    qc_number = next_qc_number(db, deliverable_id)
    db.add(QCEvent(
        deliverable_id=deliverable_id,
        asset_id=asset_id,
        qc_number=qc_number,
        sequence=1,
        event_type=QCEventType.qc_started,
        payload_json={"started_at": now()},
        operator_id=operator_id,
        source="manual",
    ))
    # Snapshot tech_specs immutabile
    asset = db.query(Asset).get(asset_id)
    db.add(QCEvent(
        deliverable_id=deliverable_id, asset_id=asset_id,
        qc_number=qc_number, sequence=2,
        event_type=QCEventType.snapshot_taken,
        payload_json={"specs": asset.tech_specs_json, "extractor": asset.tech_specs_extractor},
        source="auto",
    ))
    return qc_number
```

### 7.2 Logging errors

```python
def log_video_error(db, deliverable_id, qc_number, tc_in, tc_out, desc, grade, sector, operator_id):
    db.add(QCEvent(
        deliverable_id=deliverable_id, qc_number=qc_number,
        sequence=next_sequence(db, deliverable_id, qc_number),
        event_type=QCEventType.video_error_logged,
        payload_json={
            "tc_in": tc_in, "tc_out": tc_out,
            "description": desc, "grade": grade, "sector": sector,
            "video_audio_picture_field": "V"
        },
        operator_id=operator_id,
    ))
```

### 7.3 Chiusura QC

```python
def close_qc(db, deliverable_id, qc_number, overall, recommendations, operator_id):
    event_type = {"pass": QCEventType.qc_passed,
                  "fail": QCEventType.qc_failed,
                  "conditional": QCEventType.qc_conditional}[overall]
    db.add(QCEvent(
        deliverable_id=deliverable_id, qc_number=qc_number,
        sequence=next_sequence(db, deliverable_id, qc_number),
        event_type=event_type,
        payload_json={"recommendations": recommendations},
        operator_id=operator_id,
    ))
    # Cascade su JobDeliverable.qc_substatus (riusa Bundle I logic)
```

### 7.4 Projection refresh

Listener `after_insert` su QCEvent ricalcola QCReport per quel deliverable.

---

## 8. AI capabilities specs (B + E + F primo round)

### 8.1 `ingest_qc_excel` (Stack 3)

Input form-data: `excel_path` (uploaded Excel template QC) + `deliverable_id`.

Flow:
1. Parse 5 fogli con `openpyxl` (header detection + range walk).
2. AI Claude (Sonnet/Opus): valida shape + estrae meta (QC#, operator, date, overall status) + errors list.
3. Output: lista propose_qc_event JSON-action (1 per error/recommendation).
4. Apply atomic: crea `qc_started` event + N `*_error_logged` + 1 `qc_passed/failed/conditional`.

### 8.2 `suggest_variants_for_job` (Stack 4)

Input: `job_id`.

Flow:
1. Context build: project_type, client.name, length_minutes, attached capitolato (se esiste), quote lines.
2. Catalog query: variants attive tenant ordered by frequency-of-use desc.
3. AI Claude: ranking + suggerisce variant esistenti + propone nuove (`propose_new_variant`).
4. Output: propose_action lista per spawn `JobDeliverable.variant_id=…` o `propose_variant + propose_deliverable_with_variant`.

### 8.3 `export_qc_report` (Stack 3)

Input: `qc_report_id` o `(deliverable_id, qc_number)` + `format=excel|pdf`.

Flow:
1. Carica QCEvent stream filtered per qc_number.
2. Bind a template Excel (`docs/qc/FbF_QC-Report_Template.xlsx`) via `openpyxl`. Mantenere cell positioning fedele.
3. PDF: rendering tramite ReportLab (riusa pattern quote PDF).
4. AI compose testo "Comments" e "Recommendations" se vuoti (opzionale, prompt minimale).
5. Output: download response.

### 8.4 Capability future (Stack 2 e 5)

- `propose_qc_from_asset_diff` (Stack 2): diff `asset.tech_specs_json` vs `variant.spec_json` resolved → propose video/audio errors + grade suggestion.
- `extract_capitolato_to_variants` (Stack 5): upload PDF/DOCX/XLSX → AI estrae N variants + suggested PriceItem.
- `web_research_capitolato_field` (Stack 5): Tavily query + citation per riempire field schema ambigui.

---

## 9. Parser capitolati batch script (Stack 1)

`scripts/parse_capitolati.py`:

```bash
.venv/Scripts/python.exe scripts/parse_capitolati.py \
  --corpus docs/capitolati_esempio \
  --out docs/superpowers/specs/capitolati-parsed/ \
  --schema-version v1 \
  --ai-provider claude --ai-model claude-sonnet-4-6
```

Per ogni file capitolato:
1. Estrae testo (PDF via `pdfplumber`, DOCX via `python-docx`, TXT/XLSX direct).
2. Chunk a ~6k token sliding window con overlap.
3. AI prompt strutturato: estrai items, classifica T1/T2/T3, mappa a schema variant_v1.
4. Output JSON: `<vendor>.variants.json` con `[{ code, name, category, spec_json, source_section, suggested_price_item }, ...]`.
5. Report markdown comparativo `capitolati-parsed/REPORT.md` con counts + esempi per vendor.

**Output committato nel repo** (no auto-import in DB). Matteo revisiona + script secondario `scripts/import_parsed_variants.py` per push DB con confirm.

---

## 10. Roadmap implementation (5 stack consecutivi)

| Stack | Versioni | Contenuto | Effort stimato |
|-------|----------|-----------|----------------|
| **1 — Foundation** | α.172.94 → 96 | `VariantSchemaVersion` + `DeliveryVariant` models + migrations + extractor service registry (ffprobe plugin) + `JobDeliverable.variant_id` FK + script `parse_capitolati.py` + script `import_parsed_variants.py` + JSON Schema v1 committato + UI listing `/delivery-variants` minimal | 3-4 gg |
| **2 — QC core** | α.172.97 → 99 | `QCEvent` append-only + listener immutability + `QCReport` projection + UI modal QC submit + storia QC# nel deliverable + capability AI `propose_qc_from_asset_diff` | 3 gg |
| **3 — QC ingest+export** | α.172.100 → 102 | Capability `ingest_qc_excel` + `export_qc_report` (Excel + PDF) + UI upload/download + binding template FbF | 3 gg |
| **4 — Planning UI + Asset modal** | α.172.103 → 105 | Modal deliverable in /planning con dropdown variant + override + modal asset detail riscritto sezioni tipizzate + diff vs variant + capability `suggest_variants_for_job` + bridge variant ↔ PriceItem (suggestion in /pricelist) | 4 gg |
| **5 — Capability runtime + web research** | α.172.106+ | Capability `extract_capitolato_to_variants` (UI upload) + `web_research_capitolato_field` (Tavily) + UI pagina /capitolati management | 3 gg |

Totale stimato: **3 settimane di lavoro**.

Ogni stack chiude con commit + push + test. Stack 1+2+3 = primo round con valore concreto. Stack 4+5 successivi.

---

## 11. Migrazioni

### Stack 1
1. `ALTER TABLE` ADD `variant_id` (FK nullable) su `job_deliverables`.
2. `ALTER TABLE` ADD `tech_specs_json`, `tech_specs_extractor`, `tech_specs_extracted_at`, `tech_specs_schema_version` su `assets`.
3. `CREATE TABLE` `variant_schema_versions` + `delivery_variants`.
4. Seed `VariantSchemaVersion(v="v1", schema_json=...)` from `schemas/variant_v1.json`.
5. Backfill: per ogni `JobDeliverable` esistente, keyword match su name → suggested `variant_id` (best-effort, può restare NULL).

### Stack 2
6. `CREATE TABLE` `qc_events` + `qc_reports`.
7. Listener SQLAlchemy `before_update` su QCEvent → raise per immutability.
8. Backfill: per ogni `JobDeliverable.qc_report_json` non-null legacy → spawn QCEvent stream sintetico (1 qc_started + 1 qc_passed/failed).

Tutti auto-applicati al boot via pattern `_auto_migrate_bundle_l_stack_*()` in `app/main.py`.

---

## 12. Non-goal (esclusioni esplicite)

- **No event-store generico**: QCEvent è dedicato. Altri flussi (booking, billing) restano modello relazionale standard.
- **No realtime collaborative QC**: il QC corrente è single-operator. Multi-utente lock/merge non in scope.
- **No DRM/watermark management**: ContentArmor/TPN compliance già coperti α.66.22 sprint TPN. Bundle L estrae solo metadata, non gestisce protezione.
- **No AI auto-decision on QC pass/fail**: AI propone errors/grade, operatore decide overall_status. Pattern "AI propone, utente dispone" intatto.

---

## 13. Open questions per implementation phase

1. **JSON Schema validation lib**: `jsonschema` (deps Python esistente?) o impl minimale custom? → verificare requirements.txt.
2. **UI form generator da JSON Schema**: scrivere mini-generator HTML (input/select per type) o usare `react-jsonschema-form` portato vanilla? → preferenza no-build per MediaFlow → mini-generator custom.
3. **Excel template binding** Stack 3: bind via openpyxl cell-by-cell o template render (`xlsxwriter`)? → openpyxl preserva layout originale FbF, scelto.
4. **Backfill keyword match Stack 1**: lista keyword → variant code mapping va revisionata insieme dopo parser batch eseguito (output guida vocabolario).

---

## 14. Riferimenti

- Brainstorm session: `.superpowers/brainstorm/1596-1779807005/content/` (9 screenshots Q1→Q9)
- Capitolati corpus: `docs/capitolati_esempio/` (17 file)
- QC template: `docs/qc/FbF_QC-Report_Template.xlsx`
- Modello attuale: `app/models/models.py` (Asset 2597, JobDeliverable 2898, DeliveryTemplate cerca)
- Service esistente: `app/services/asset_metadata.py` (sarà generalizzato in `tech_specs_extractor`)
- Bundle precedente correlato: I (status nested), J (HUB planning), H3 (asset metadata read-only)
