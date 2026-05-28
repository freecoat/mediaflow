# Timeline / TC Start / Audio Config — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Catturare in forma strutturata TC start, timeline/head build e audio config code (RAI 8T07) sui DeliveryItem, con default ereditati dal template e preset audio che materializzano AudioTrackSpec.

**Architecture:** Nuove colonne su `DeliveryItem` (override) + `DeliveryTemplate` (default emittente) + nuova tabella `AudioConfigPreset` legata al template. Servizi puri per materializzazione audio ed eredità timeline. Parser esteso. UI nel modal item esistente. QC riceve i valori attesi nel context.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (`Mapped[]`) + SQLite + Jinja2 + vanilla JS. Test: pytest (fixture `db`, `tenant_id` in `tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-05-28-delivery-timeline-tc-audioconfig-design.md`

---

## File Structure

| File | Responsabilità | Azione |
|------|----------------|--------|
| `app/models/models.py` | Colonne nuove + `AudioConfigPreset` | Modify |
| `scripts/migrate_delivery_timeline_audioconfig.py` | Migrazione idempotente + backfill default | Create |
| `app/main.py` | Registrare colonne in `_auto_migrate_columns()` | Modify |
| `app/services/audio_config_service.py` | Materializzazione preset → AudioTrackSpec | Create |
| `app/services/delivery_timeline_service.py` | Eredità timeline/TC item←template | Create |
| `app/routers/delivery_items.py` | CRUD preset + apply preset + estendere update_item/_serialize_item | Modify |
| `app/services/delivery_items_parser.py` | Pass2: estrarre tc/timeline/audio code + materialize | Modify |
| `app/templates/pages/delivery_templates.html` | UI sezione Timeline&TC + dropdown audio config + admin default/preset | Modify |
| `tests/test_audio_config_service.py` | Test materializzazione | Create |
| `tests/test_delivery_timeline_service.py` | Test eredità | Create |
| `tests/test_audio_config_preset_model.py` | Test modello | Create |

---

## Task 1: Modello — colonne DeliveryItem/Template + AudioConfigPreset

**Files:**
- Modify: `app/models/models.py` (DeliveryItem ~917, DeliveryTemplate ~671, nuova classe dopo AudioTrackSpec ~997)
- Test: `tests/test_audio_config_preset_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audio_config_preset_model.py
from app.models.models import DeliveryItem, DeliveryTemplate, AudioConfigPreset


def test_delivery_item_has_timeline_fields():
    cols = {c.name for c in DeliveryItem.__table__.columns}
    assert {"tc_start", "program_start", "timeline_segments",
            "audio_config_preset_id", "audio_config_code"} <= cols


def test_delivery_template_has_default_timeline_fields():
    cols = {c.name for c in DeliveryTemplate.__table__.columns}
    assert {"default_tc_start", "default_program_start",
            "default_timeline_segments"} <= cols


def test_audio_config_preset_model(db, tenant_id):
    t = DeliveryTemplate(tenant_id=tenant_id, code="TST-AC", name="Test AC")
    db.add(t); db.flush()
    p = AudioConfigPreset(
        tenant_id=tenant_id, delivery_template_id=t.id, code="8T07",
        name="8 tracce 5.1+ST",
        track_layout=[{"track_label": "5.1 L", "channel_config": "5.1",
                       "codec": "PCM", "sample_rate": 48000, "bit_depth": 24}],
    )
    db.add(p); db.flush()
    assert p.id is not None
    assert p.is_active is True
    assert p.track_layout[0]["track_label"] == "5.1 L"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio_config_preset_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'AudioConfigPreset'` / missing columns.

- [ ] **Step 3: Add columns to DeliveryItem**

In `app/models/models.py`, dentro `class DeliveryItem`, subito dopo il blocco `# Subtitle layer` (dopo `subtitle_languages`, riga ~945) aggiungi:

```python
    # Timeline / TC layer (v3.5.0-alpha.172.127) — override; default sul template.
    tc_start: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)        # "00:59:59:00"
    program_start: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)   # "01:00:00:00"
    # Lista ordinata segmenti testa/coda. Shape:
    # [{order,kind,label,tc_in,tc_out,duration,reel,source,notes}]
    # kind ∈ bars_tone|slate|countdown|counter|black|program|textless|logo|main_titles|tail|other
    timeline_segments: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Audio config code (es. RAI 8T07) + FK al preset del template.
    audio_config_preset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("audio_config_presets.id"), nullable=True
    )
    audio_config_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
```

- [ ] **Step 4: Add default columns to DeliveryTemplate**

In `class DeliveryTemplate`, dopo `metadata_requirements` (riga ~693) aggiungi:

```python
    # Default emittente timeline/TC (v3.5.0-alpha.172.127). Gli item ereditano
    # questi se i propri campi sono vuoti. `head_format` resta come legacy/fonte.
    default_tc_start: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    default_program_start: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    default_timeline_segments: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 5: Add AudioConfigPreset class**

In `app/models/models.py`, subito dopo la classe `AudioTrackSpec` (dopo riga ~996) aggiungi:

```python
class AudioConfigPreset(Base):
    """Codice di configurazione audio d'emittente (es. RAI 8T07, 16T09).
    Legato a UN DeliveryTemplate (D4: no riuso cross-template). `track_layout`
    si materializza in AudioTrackSpec concrete sull'item (D2)."""
    __tablename__ = "audio_config_presets"
    __table_args__ = (
        UniqueConstraint("delivery_template_id", "code", name="uq_audio_preset_template_code"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    delivery_template_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_templates.id"), index=True
    )
    code: Mapped[str] = mapped_column(String(40))            # "8T07"
    name: Mapped[str] = mapped_column(String(120))           # "8 tracce: 5.1 + Stereo"
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # [{track_label, channel_config, mix_type, mix_standard, codec, sample_rate, bit_depth}]
    track_layout: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio_config_preset_model.py -v`
Expected: PASS (3 test). La tabella `audio_config_presets` viene creata da `Base.metadata.create_all` nella fixture `db`.

- [ ] **Step 7: Commit**

```bash
git add app/models/models.py tests/test_audio_config_preset_model.py
git commit -m "feat(model): timeline/TC fields + AudioConfigPreset"
```

---

## Task 2: Migrazione idempotente + auto-migrate al boot

**Files:**
- Create: `scripts/migrate_delivery_timeline_audioconfig.py`
- Modify: `app/main.py` (`_auto_migrate_columns`, dopo il blocco users ~riga 110, in coda alla funzione)

- [ ] **Step 1: Write the migration script**

```python
# scripts/migrate_delivery_timeline_audioconfig.py
"""v3.5.0-alpha.172.127 — Migrazione timeline/TC + audio_config_presets.

Idempotente: ALTER TABLE ADD COLUMN guardati da introspection, CREATE tabella
via create_all, backfill default_* dei template da head_format esistente.

Uso: .venv/Scripts/python.exe scripts/migrate_delivery_timeline_audioconfig.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, text
from app.database import engine, SessionLocal
from app.models.models import Base, DeliveryTemplate

ITEM_COLS = [
    ("tc_start", "VARCHAR(20) NULL"),
    ("program_start", "VARCHAR(20) NULL"),
    ("timeline_segments", "JSON NULL"),
    ("audio_config_preset_id", "INTEGER NULL"),
    ("audio_config_code", "VARCHAR(40) NULL"),
]
TEMPLATE_COLS = [
    ("default_tc_start", "VARCHAR(20) NULL"),
    ("default_program_start", "VARCHAR(20) NULL"),
    ("default_timeline_segments", "JSON NULL"),
]


def _add_cols(table, coldefs):
    insp = inspect(engine)
    existing = {c["name"] for c in insp.get_columns(table)}
    with engine.begin() as conn:
        for col, ddl in coldefs:
            if col not in existing:
                print(f"  + {table}.{col}")
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def _backfill_template_defaults(db):
    """Promuove head_format → default_tc_start/program_start dei template."""
    n = 0
    for t in db.query(DeliveryTemplate).all():
        hf = t.head_format or {}
        if not isinstance(hf, dict):
            continue
        changed = False
        if not t.default_tc_start and hf.get("timecode_start"):
            t.default_tc_start = str(hf["timecode_start"])[:20]
            changed = True
        if not t.default_program_start and hf.get("program_start"):
            t.default_program_start = str(hf["program_start"])[:20]
            changed = True
        if changed:
            n += 1
    db.commit()
    return n


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("-> create_all (crea audio_config_presets se mancante)...")
    Base.metadata.create_all(bind=engine)
    print("-> ALTER colonne delivery_items / delivery_templates...")
    _add_cols("delivery_items", ITEM_COLS)
    _add_cols("delivery_templates", TEMPLATE_COLS)
    db = SessionLocal()
    try:
        n = _backfill_template_defaults(db)
        print(f"-> backfill default da head_format: {n} template aggiornati")
    finally:
        db.close()
    print("[OK] migrazione completata.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the migration**

Run: `.venv/Scripts/python.exe scripts/migrate_delivery_timeline_audioconfig.py`
Expected: stampa colonne aggiunte + "backfill default da head_format: N template aggiornati" + "[OK]".

- [ ] **Step 3: Verify columns exist**

Run:
```bash
.venv/Scripts/python.exe -c "from sqlalchemy import inspect; from app.database import engine; i=inspect(engine); print('audio_config_presets' in i.get_table_names()); print({c['name'] for c in i.get_columns('delivery_items')} >= {'tc_start','audio_config_code'})"
```
Expected: `True` / `True`.

- [ ] **Step 4: Register in _auto_migrate_columns (boot safety)**

In `app/main.py`, dentro `_auto_migrate_columns()`, in fondo alla funzione (prima del `return` o dopo l'ultimo blocco esistente ~riga 110+), aggiungi:

```python
    # v3.5.0-alpha.172.127 — timeline/TC + audio_config_presets (boot safety).
    insp2 = inspect(engine)
    if "delivery_items" in insp2.get_table_names():
        di_cols = {c["name"] for c in insp2.get_columns("delivery_items")}
        di_add = [
            ("tc_start", "VARCHAR(20) NULL"),
            ("program_start", "VARCHAR(20) NULL"),
            ("timeline_segments", "JSON NULL"),
            ("audio_config_preset_id", "INTEGER NULL"),
            ("audio_config_code", "VARCHAR(40) NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in di_add:
                if col not in di_cols:
                    print(f"[auto-migrate] delivery_items.{col} -> ALTER")
                    conn.execute(text(f"ALTER TABLE delivery_items ADD COLUMN {col} {ddl}"))
    if "delivery_templates" in insp2.get_table_names():
        dt_cols = {c["name"] for c in insp2.get_columns("delivery_templates")}
        dt_add = [
            ("default_tc_start", "VARCHAR(20) NULL"),
            ("default_program_start", "VARCHAR(20) NULL"),
            ("default_timeline_segments", "JSON NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in dt_add:
                if col not in dt_cols:
                    print(f"[auto-migrate] delivery_templates.{col} -> ALTER")
                    conn.execute(text(f"ALTER TABLE delivery_templates ADD COLUMN {col} {ddl}"))
```

(`inspect` e `text` sono già importati in cima a `_auto_migrate_columns`.)

- [ ] **Step 5: Verify app boots clean**

Run: `.venv/Scripts/python.exe -c "from app.main import app; print('import OK', app.version)"`
Expected: `import OK 3.5.0-alpha.172.x` senza traceback.

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_delivery_timeline_audioconfig.py app/main.py
git commit -m "feat(migrate): timeline/TC columns + audio_config_presets + boot auto-migrate"
```

---

## Task 3: Service — materializzazione audio config → AudioTrackSpec

**Files:**
- Create: `app/services/audio_config_service.py`
- Test: `tests/test_audio_config_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audio_config_service.py
from app.models.models import (
    DeliveryTemplate, DeliveryItem, AudioConfigPreset, AudioTrackSpec,
    AudioChannelConfig, AudioCodec,
)
from app.services.audio_config_service import apply_audio_config_preset


def _setup(db, tenant_id):
    t = DeliveryTemplate(tenant_id=tenant_id, code="RAI-X", name="RAI test")
    db.add(t); db.flush()
    db.add(AudioChannelConfig(tenant_id=None, name="5.1", channel_count=6))
    db.add(AudioCodec(tenant_id=None, name="PCM"))
    db.flush()
    preset = AudioConfigPreset(
        tenant_id=tenant_id, delivery_template_id=t.id, code="8T07",
        name="8T07", track_layout=[
            {"track_label": "5.1", "channel_config": "5.1", "codec": "PCM",
             "sample_rate": 48000, "bit_depth": 24},
            {"track_label": "Stereo", "channel_config": "Stereo", "codec": "PCM"},
        ])
    db.add(preset); db.flush()
    item = DeliveryItem(tenant_id=tenant_id, delivery_template_id=t.id, name="HDTV")
    db.add(item); db.flush()
    return item, preset


def test_apply_preset_materializes_tracks(db, tenant_id):
    item, preset = _setup(db, tenant_id)
    n = apply_audio_config_preset(db, item, preset)
    db.flush()
    tracks = db.query(AudioTrackSpec).filter(
        AudioTrackSpec.delivery_item_id == item.id).order_by(AudioTrackSpec.sort_order).all()
    assert n == 2
    assert len(tracks) == 2
    assert tracks[0].track_label == "5.1"
    # nome risolto a id taxonomy esistente
    assert tracks[0].channel_config_id is not None
    assert tracks[0].sample_rate_hz == 48000
    # nome non risolto (Stereo non seedato) -> id None ma traccia creata con nota
    assert tracks[1].channel_config_id is None
    assert item.audio_config_preset_id == preset.id
    assert item.audio_config_code == "8T07"


def test_apply_preset_replaces_existing_derived_tracks(db, tenant_id):
    item, preset = _setup(db, tenant_id)
    apply_audio_config_preset(db, item, preset)
    db.flush()
    apply_audio_config_preset(db, item, preset)  # ri-applica
    db.flush()
    tracks = db.query(AudioTrackSpec).filter(
        AudioTrackSpec.delivery_item_id == item.id).all()
    assert len(tracks) == 2  # non duplica
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio_config_service.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.audio_config_service`.

- [ ] **Step 3: Write the service**

```python
# app/services/audio_config_service.py
"""v3.5.0-alpha.172.127 — Materializzazione AudioConfigPreset → AudioTrackSpec.

Selezionare un preset (es. RAI 8T07) crea le tracce audio concrete sull'item
(D2). I nomi nel track_layout (channel_config/mix_type/mix_standard/codec) sono
risolti agli id taxonomy esistenti; se non risolti la traccia è creata comunque
con i campi noti + nota (fallback D5).
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session
from app.models.models import (
    AudioTrackSpec, AudioConfigPreset, DeliveryItem,
    AudioChannelConfig, AudioMixType, MixStandard, AudioCodec,
)


def _resolve_id(db: Session, model, name: Optional[str], tenant_id: int) -> Optional[int]:
    """Risolve un nome taxonomy a id (preset globali tenant_id NULL OR del tenant)."""
    if not name:
        return None
    rec = (
        db.query(model.id)
        .filter(model.name == name)
        .filter((model.tenant_id == tenant_id) | (model.tenant_id.is_(None)))
        .first()
    )
    return rec[0] if rec else None


def apply_audio_config_preset(db: Session, item: DeliveryItem,
                              preset: AudioConfigPreset) -> int:
    """Materializza le tracce del preset sull'item. Sostituisce le tracce
    esistenti derivate da un preset (ri-applicazione idempotente). Ritorna il
    numero di tracce create. NON committa (lascia al caller)."""
    # Rimuovi tracce esistenti dell'item (sostituzione in blocco, D2 nota).
    db.query(AudioTrackSpec).filter(
        AudioTrackSpec.delivery_item_id == item.id
    ).delete(synchronize_session=False)

    layout = preset.track_layout or []
    created = 0
    for idx, tr in enumerate(layout):
        cc_id = _resolve_id(db, AudioChannelConfig, tr.get("channel_config"), item.tenant_id)
        mt_id = _resolve_id(db, AudioMixType, tr.get("mix_type"), item.tenant_id)
        ms_id = _resolve_id(db, MixStandard, tr.get("mix_standard"), item.tenant_id)
        ac_id = _resolve_id(db, AudioCodec, tr.get("codec"), item.tenant_id)
        unresolved = [k for k, v in (
            ("channel_config", tr.get("channel_config") and cc_id is None),
            ("mix_type", tr.get("mix_type") and mt_id is None),
            ("mix_standard", tr.get("mix_standard") and ms_id is None),
            ("codec", tr.get("codec") and ac_id is None),
        ) if v]
        note = None
        if unresolved:
            note = "taxonomy non risolta: " + ", ".join(
                f"{k}={tr.get(k)}" for k in unresolved)
        db.add(AudioTrackSpec(
            delivery_item_id=item.id,
            sort_order=idx * 10,
            track_label=tr.get("track_label") or f"Track {idx + 1}",
            channel_config_id=cc_id,
            mix_type_id=mt_id,
            mix_standard_id=ms_id,
            audio_codec_id=ac_id,
            sample_rate_hz=tr.get("sample_rate"),
            bit_depth=tr.get("bit_depth"),
            notes=note,
        ))
        created += 1

    item.audio_config_preset_id = preset.id
    item.audio_config_code = preset.code
    return created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_audio_config_service.py -v`
Expected: PASS (2 test).

- [ ] **Step 5: Commit**

```bash
git add app/services/audio_config_service.py tests/test_audio_config_service.py
git commit -m "feat(service): apply_audio_config_preset materializes AudioTrackSpec"
```

---

## Task 4: Service — eredità timeline/TC item ← template

**Files:**
- Create: `app/services/delivery_timeline_service.py`
- Test: `tests/test_delivery_timeline_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_delivery_timeline_service.py
from app.models.models import DeliveryTemplate, DeliveryItem
from app.services.delivery_timeline_service import effective_timeline


def test_item_inherits_template_default(db, tenant_id):
    t = DeliveryTemplate(tenant_id=tenant_id, code="V-X", name="Vision",
                         default_tc_start="00:59:59:00",
                         default_program_start="01:00:00:00")
    db.add(t); db.flush()
    item = DeliveryItem(tenant_id=tenant_id, delivery_template_id=t.id, name="DCP")
    db.add(item); db.flush()
    eff = effective_timeline(db, item)
    assert eff["tc_start"] == "00:59:59:00"
    assert eff["tc_start_inherited"] is True
    assert eff["program_start"] == "01:00:00:00"


def test_item_override_wins(db, tenant_id):
    t = DeliveryTemplate(tenant_id=tenant_id, code="V-Y", name="Vision",
                         default_tc_start="00:59:59:00")
    db.add(t); db.flush()
    item = DeliveryItem(tenant_id=tenant_id, delivery_template_id=t.id, name="Trailer",
                        tc_start="10:00:00:00")
    db.add(item); db.flush()
    eff = effective_timeline(db, item)
    assert eff["tc_start"] == "10:00:00:00"
    assert eff["tc_start_inherited"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_delivery_timeline_service.py -v`
Expected: FAIL — module non esiste.

- [ ] **Step 3: Write the service**

```python
# app/services/delivery_timeline_service.py
"""v3.5.0-alpha.172.127 — Eredità timeline/TC: l'item usa i propri campi se
valorizzati, altrimenti eredita i default del DeliveryTemplate (D3)."""
from __future__ import annotations
from sqlalchemy.orm import Session
from app.models.models import DeliveryItem, DeliveryTemplate


def effective_timeline(db: Session, item: DeliveryItem) -> dict:
    """Ritorna i valori timeline/TC effettivi + flag *_inherited per la UI."""
    tpl = db.get(DeliveryTemplate, item.delivery_template_id)

    def pick(item_val, tpl_val):
        if item_val not in (None, "", []):
            return item_val, False
        if tpl_val not in (None, "", []):
            return tpl_val, True
        return None, False

    tc, tc_inh = pick(item.tc_start, tpl.default_tc_start if tpl else None)
    pg, pg_inh = pick(item.program_start, tpl.default_program_start if tpl else None)
    seg, seg_inh = pick(item.timeline_segments,
                        tpl.default_timeline_segments if tpl else None)
    return {
        "tc_start": tc, "tc_start_inherited": tc_inh,
        "program_start": pg, "program_start_inherited": pg_inh,
        "timeline_segments": seg or [], "timeline_segments_inherited": seg_inh,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_delivery_timeline_service.py -v`
Expected: PASS (2 test).

- [ ] **Step 5: Commit**

```bash
git add app/services/delivery_timeline_service.py tests/test_delivery_timeline_service.py
git commit -m "feat(service): effective_timeline inheritance item<-template"
```

---

## Task 5: Router — CRUD preset + apply + estensione update_item/_serialize_item

**Files:**
- Modify: `app/routers/delivery_items.py` (`_serialize_item` ~69, `update_item` ~210, nuovi endpoint in coda)

- [ ] **Step 1: Estendi `_serialize_item`**

In `app/routers/delivery_items.py`, dentro `_serialize_item` (riga ~69), aggiungi al dict ritornato i nuovi campi (importa `effective_timeline` in cima al file: `from app.services.delivery_timeline_service import effective_timeline`):

```python
    # ... dopo i campi esistenti, prima del return / dentro il dict:
    d["tc_start"] = it.tc_start
    d["program_start"] = it.program_start
    d["timeline_segments"] = it.timeline_segments or []
    d["audio_config_preset_id"] = it.audio_config_preset_id
    d["audio_config_code"] = it.audio_config_code
```

(Se `_serialize_item` riceve già `db`, aggiungi anche `d["effective_timeline"] = effective_timeline(db, it)`. Se non riceve `db`, lascia solo i campi raw e calcola l'effective nel GET item — vedi Step 2.)

- [ ] **Step 2: Estendi `update_item` per accettare i nuovi campi**

In `update_item` (riga ~210), aggiungi i parametri `Form` e l'assegnazione. I campi JSON (`timeline_segments`) arrivano come stringa JSON nel form e vanno parsati con `safe_json_parse`:

```python
    # firma: aggiungi parametri
    tc_start: Optional[str] = Form(None),
    program_start: Optional[str] = Form(None),
    timeline_segments_json: Optional[str] = Form(None),
    audio_config_preset_id: Optional[str] = Form(None),
```

```python
    # corpo: dopo le assegnazioni esistenti
    from app.services.ai_providers import safe_json_parse  # se non già importato
    if tc_start is not None:
        item.tc_start = tc_start.strip() or None
    if program_start is not None:
        item.program_start = program_start.strip() or None
    if timeline_segments_json is not None:
        item.timeline_segments = safe_json_parse(timeline_segments_json) or []
    if audio_config_preset_id is not None:
        pid = int(audio_config_preset_id) if audio_config_preset_id.strip() else None
        if pid:
            from app.models.models import AudioConfigPreset
            from app.services.audio_config_service import apply_audio_config_preset
            preset = db.get(AudioConfigPreset, pid)
            if preset and preset.delivery_template_id == item.delivery_template_id:
                apply_audio_config_preset(db, item, preset)
        else:
            item.audio_config_preset_id = None
            item.audio_config_code = None
```

(Verifica il nome reale dell'helper JSON lenient nel progetto — `safe_json_parse` in `app/services/ai_providers.py`. Se diverso, usa quello.)

- [ ] **Step 3: Add AudioConfigPreset CRUD + list-by-template endpoints**

In coda a `app/routers/delivery_items.py` aggiungi:

```python
# ── AudioConfigPreset (v3.5.0-alpha.172.127) ──────────────────
def _serialize_preset(p) -> dict:
    return {
        "id": p.id, "delivery_template_id": p.delivery_template_id,
        "code": p.code, "name": p.name, "description": p.description,
        "track_layout": p.track_layout or [], "sort_order": p.sort_order,
        "is_active": p.is_active,
    }


@router.get("/delivery-templates/api/{tid}/audio-presets")
async def list_audio_presets(tid: int, db: Session = Depends(get_db)):
    from app.models.models import AudioConfigPreset
    rows = (db.query(AudioConfigPreset)
            .filter(AudioConfigPreset.delivery_template_id == tid,
                    AudioConfigPreset.tenant_id == current_tenant_id(),
                    AudioConfigPreset.is_active == True)  # noqa: E712
            .order_by(AudioConfigPreset.sort_order, AudioConfigPreset.code).all())
    return [_serialize_preset(p) for p in rows]


@router.post("/delivery-templates/api/{tid}/audio-presets", dependencies=[RequireEdit])
async def create_audio_preset(tid: int, code: str = Form(...), name: str = Form(...),
                              description: Optional[str] = Form(None),
                              track_layout_json: Optional[str] = Form(None),
                              db: Session = Depends(get_db)):
    from app.models.models import AudioConfigPreset
    from app.services.ai_providers import safe_json_parse
    p = AudioConfigPreset(
        tenant_id=current_tenant_id(), delivery_template_id=tid,
        code=code.strip(), name=name.strip(), description=description,
        track_layout=safe_json_parse(track_layout_json) if track_layout_json else [],
    )
    db.add(p); db.commit(); db.refresh(p)
    return _serialize_preset(p)


@router.put("/delivery-audio-presets/api/{pid}", dependencies=[RequireEdit])
async def update_audio_preset(pid: int, code: Optional[str] = Form(None),
                              name: Optional[str] = Form(None),
                              description: Optional[str] = Form(None),
                              track_layout_json: Optional[str] = Form(None),
                              db: Session = Depends(get_db)):
    from app.models.models import AudioConfigPreset
    from app.services.ai_providers import safe_json_parse
    p = db.query(AudioConfigPreset).filter(
        AudioConfigPreset.id == pid,
        AudioConfigPreset.tenant_id == current_tenant_id()).first()
    if not p:
        raise HTTPException(404, "preset non trovato")
    if code is not None: p.code = code.strip()
    if name is not None: p.name = name.strip()
    if description is not None: p.description = description
    if track_layout_json is not None:
        p.track_layout = safe_json_parse(track_layout_json) or []
    db.commit()
    return _serialize_preset(p)


@router.delete("/delivery-audio-presets/api/{pid}", dependencies=[RequireEdit])
async def delete_audio_preset(pid: int, db: Session = Depends(get_db)):
    from app.models.models import AudioConfigPreset
    p = db.query(AudioConfigPreset).filter(
        AudioConfigPreset.id == pid,
        AudioConfigPreset.tenant_id == current_tenant_id()).first()
    if not p:
        raise HTTPException(404, "preset non trovato")
    p.is_active = False  # soft-delete
    db.commit()
    return {"ok": True}
```

(Verifica che `current_tenant_id`, `RequireEdit`, `HTTPException`, `Form`, `Optional` siano già importati nel file — lo sono per gli endpoint esistenti.)

- [ ] **Step 4: Smoke test endpoints (manual, server running)**

Run (con server attivo + login come negli step precedenti della sessione):
```bash
.venv/Scripts/python.exe -c "
import urllib.request, urllib.parse, http.cookiejar, json
cj=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.open('http://localhost:8000/auth/login', urllib.parse.urlencode({'email':'admin@mediaflow.it','password':'admin123'}).encode())
r=op.open('http://localhost:8000/delivery-templates/api/1/audio-presets'); print('list', r.status, r.read()[:200])
"
```
Expected: `list 200 []` (nessun preset ancora) o lista.

- [ ] **Step 5: Commit**

```bash
git add app/routers/delivery_items.py
git commit -m "feat(api): audio-preset CRUD + update_item timeline/TC/audio-config"
```

---

## Task 6: Parser — estrarre tc/timeline/audio code in pass2 + materialize

**Files:**
- Modify: `app/services/delivery_items_parser.py` (prompt pass2 ~riga 121, `materialize_items` ~230)

- [ ] **Step 1: Estendi lo schema item nel prompt pass2**

In `delivery_items_parser.py`, nel testo del prompt che elenca i campi item (intorno a riga 121, dove c'è `- audio_tracks: lista [...]`), aggiungi le righe:

```text
- tc_start: timecode di inizio file se indicato (es. "00:59:59:00"), altrimenti null
- program_start: timecode di inizio programma se indicato (es. "01:00:00:00"), altrimenti null
- timeline_segments: lista ordinata della testa/coda se descritta nel capitolato.
  Ogni elemento: {order, kind, label, tc_in, tc_out, duration, reel, source, notes}.
  kind ∈ bars_tone|slate|countdown|counter|black|program|textless|logo|main_titles|tail|other.
  reel = numero rullo DCP (es. Vision "1 logo = 1 rullo"); source = materiale sorgente.
  Se non descritta, lista vuota.
- audio_config_code: codice di configurazione audio d'emittente se citato (es. RAI "8T07", "16T09"), altrimenti null
Quello che non riesci a strutturare, mettilo in `notes` (non perdere informazioni).
```

- [ ] **Step 2: Estendi `materialize_items` per persistere i nuovi campi**

In `materialize_items` (riga ~251), dentro la costruzione di `DeliveryItem(...)`, aggiungi i campi dopo `notes=it.get("notes")`:

```python
            tc_start=it.get("tc_start"),
            program_start=it.get("program_start"),
            timeline_segments=it.get("timeline_segments") or None,
            audio_config_code=it.get("audio_config_code"),
```

- [ ] **Step 3: Crea/collega AudioConfigPreset dal codice estratto**

In `materialize_items`, dopo `db.flush()` (riga ~280, dove c'è `item.id` popolato) e prima del loop `audio_tracks`, aggiungi:

```python
        # v3.5.0-alpha.172.127 — se il parser ha trovato un audio_config_code,
        # crea/collega un AudioConfigPreset sul template (idempotente per code).
        acode = (it.get("audio_config_code") or "").strip()
        if acode:
            from app.models.models import AudioConfigPreset
            preset = (db.query(AudioConfigPreset)
                      .filter(AudioConfigPreset.delivery_template_id == delivery_template_id,
                              AudioConfigPreset.code == acode).first())
            if not preset:
                preset = AudioConfigPreset(
                    tenant_id=tenant_id, delivery_template_id=delivery_template_id,
                    code=acode, name=acode,
                    track_layout=it.get("audio_tracks") or [],
                )
                db.add(preset); db.flush()
            item.audio_config_preset_id = preset.id
```

- [ ] **Step 4: Test parser materialize (no LLM, dict diretto)**

```python
# aggiungi a tests/test_parse_capitolati.py (o nuovo test)
def test_materialize_persists_timeline_and_audio_code(db, tenant_id):
    from app.models.models import DeliveryTemplate, DeliveryItem, AudioConfigPreset
    from app.services.delivery_items_parser import materialize_items
    t = DeliveryTemplate(tenant_id=tenant_id, code="RAI-MZ", name="RAI mz")
    db.add(t); db.flush()
    parsed = {"items": [{
        "name": "HDTV 1080i25", "tc_start": "10:00:00:00",
        "program_start": "10:00:00:00",
        "timeline_segments": [{"order": 1, "kind": "bars_tone", "label": "barre"}],
        "audio_config_code": "8T07",
        "audio_tracks": [{"track_label": "5.1"}],
    }]}
    saved, skipped = materialize_items(db, t.id, parsed, tenant_id)
    assert saved == 1
    it = db.query(DeliveryItem).filter(DeliveryItem.delivery_template_id == t.id).first()
    assert it.tc_start == "10:00:00:00"
    assert it.timeline_segments[0]["kind"] == "bars_tone"
    assert it.audio_config_code == "8T07"
    p = db.query(AudioConfigPreset).filter(
        AudioConfigPreset.delivery_template_id == t.id, AudioConfigPreset.code == "8T07").first()
    assert p is not None
    assert it.audio_config_preset_id == p.id
```

- [ ] **Step 5: Run test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_parse_capitolati.py::test_materialize_persists_timeline_and_audio_code -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/delivery_items_parser.py tests/test_parse_capitolati.py
git commit -m "feat(parser): extract tc_start/program_start/timeline/audio_config_code"
```

---

## Task 7: UI — sezione Timeline & TC + dropdown audio config + admin default/preset

**Files:**
- Modify: `app/templates/pages/delivery_templates.html` (modal item editor; admin template section)

- [ ] **Step 1: Aggiungi la sezione "Timeline & TC" nel modal item editor**

Nel modal editor item (cerca la funzione JS che costruisce il form dell'item, vicino agli altri campi come `subtitle_format`), aggiungi un blocco HTML:

```html
<div class="dt-section">
  <div class="dt-section-title">⏱ Timeline &amp; TC</div>
  <div class="form-row">
    <label>TC Start</label>
    <input id="item-tc-start" class="form-input" placeholder="es. 00:59:59:00">
    <span id="item-tc-start-inh" class="hint-inherited"></span>
  </div>
  <div class="form-row">
    <label>Program Start</label>
    <input id="item-program-start" class="form-input" placeholder="es. 01:00:00:00">
  </div>
  <div class="form-row">
    <label>Audio config</label>
    <select id="item-audio-config" class="form-select"><option value="">—</option></select>
  </div>
  <div class="form-row">
    <label>Timeline (testa/coda)</label>
    <div id="item-timeline-segments"></div>
    <button type="button" class="btn btn-ghost btn-sm" onclick="addTimelineSegment()">+ Segmento</button>
  </div>
</div>
```

- [ ] **Step 2: Popola al load dell'item (usa effective_timeline + preset list)**

Nella funzione JS che apre/popola il modal item (dopo aver fetchato l'item via `/delivery-items/api/{iid}`), aggiungi:

```javascript
// timeline/TC (usa valori raw; placeholder grigio se ereditato)
document.getElementById('item-tc-start').value = item.tc_start || '';
document.getElementById('item-program-start').value = item.program_start || '';
const eff = item.effective_timeline || {};
const inhEl = document.getElementById('item-tc-start-inh');
inhEl.textContent = (!item.tc_start && eff.tc_start)
  ? `ereditato: ${eff.tc_start}` : '';
renderTimelineSegments(item.timeline_segments || []);
// dropdown audio config dal template
const tid = item.delivery_template_id;
const presets = await api('GET', `/delivery-templates/api/${tid}/audio-presets`);
const sel = document.getElementById('item-audio-config');
sel.innerHTML = '<option value="">—</option>' + presets.map(p =>
  `<option value="${p.id}" ${p.id===item.audio_config_preset_id?'selected':''}>`
  + `${escapeHtml(p.code)} — ${escapeHtml(p.name)}</option>`).join('');
```

- [ ] **Step 3: Editor segmenti timeline (tabella add/remove)**

Aggiungi le funzioni JS (no JSON.stringify in onclick — usa data-attribute/closure):

```javascript
let _tlSegments = [];
function renderTimelineSegments(segs) {
  _tlSegments = Array.isArray(segs) ? segs.slice() : [];
  const box = document.getElementById('item-timeline-segments');
  box.innerHTML = _tlSegments.map((s, i) => `
    <div class="tl-seg" data-idx="${i}">
      <select class="tl-kind">${['bars_tone','slate','countdown','counter','black','program','textless','logo','main_titles','tail','other'].map(k=>`<option ${s.kind===k?'selected':''}>${k}</option>`).join('')}</select>
      <input class="tl-label" value="${escapeHtml(s.label||'')}" placeholder="label">
      <input class="tl-tcin" value="${escapeHtml(s.tc_in||'')}" placeholder="tc in">
      <input class="tl-tcout" value="${escapeHtml(s.tc_out||'')}" placeholder="tc out">
      <input class="tl-reel" value="${escapeHtml(s.reel||'')}" placeholder="reel">
      <input class="tl-source" value="${escapeHtml(s.source||'')}" placeholder="source">
      <button type="button" class="btn btn-ghost btn-sm" onclick="removeTimelineSegment(${i})">✕</button>
    </div>`).join('');
}
function addTimelineSegment() {
  collectTimelineSegments();
  _tlSegments.push({order:_tlSegments.length+1, kind:'bars_tone', label:'', tc_in:'', tc_out:'', reel:'', source:''});
  renderTimelineSegments(_tlSegments);
}
function removeTimelineSegment(i) {
  collectTimelineSegments(); _tlSegments.splice(i,1); renderTimelineSegments(_tlSegments);
}
function collectTimelineSegments() {
  const rows = document.querySelectorAll('#item-timeline-segments .tl-seg');
  _tlSegments = Array.from(rows).map((r, i) => ({
    order: i+1,
    kind: r.querySelector('.tl-kind').value,
    label: r.querySelector('.tl-label').value || null,
    tc_in: r.querySelector('.tl-tcin').value || null,
    tc_out: r.querySelector('.tl-tcout').value || null,
    reel: r.querySelector('.tl-reel').value || null,
    source: r.querySelector('.tl-source').value || null,
  }));
  return _tlSegments;
}
```

- [ ] **Step 4: Invia i campi nel save dell'item**

Nella funzione che fa il PUT `/delivery-items/api/{iid}` (FormData), aggiungi:

```javascript
collectTimelineSegments();
fd.append('tc_start', document.getElementById('item-tc-start').value);
fd.append('program_start', document.getElementById('item-program-start').value);
fd.append('timeline_segments_json', JSON.stringify(_tlSegments));
fd.append('audio_config_preset_id', document.getElementById('item-audio-config').value);
```

- [ ] **Step 5: Admin — default emittente + CRUD preset audio nel template**

Nella sezione admin del template (dove si editano broadcaster/version), aggiungi campi `default_tc_start`/`default_program_start` (input → inviati al PUT del template; estendi l'endpoint `update_template` in `delivery_templates.py` per accettarli, stesso pattern dei Form esistenti) e un pannello "Audio config presets" che lista/crea/edita via gli endpoint del Task 5 (`/delivery-templates/api/{tid}/audio-presets`).

(Nota: l'estensione di `update_template` per `default_tc_start`/`default_program_start`/`default_timeline_segments_json` segue lo stesso pattern di `update_item` Task 5 Step 2 — aggiungi i `Form(None)` e le assegnazioni.)

- [ ] **Step 6: Bump cache-buster + smoke render**

Il cache-buster è automatico via `app_version` Jinja global (Sprint 4). Verifica che la pagina renderizzi:
```bash
.venv/Scripts/python.exe -c "
import urllib.request, urllib.parse, http.cookiejar
cj=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.open('http://localhost:8000/auth/login', urllib.parse.urlencode({'email':'admin@mediaflow.it','password':'admin123'}).encode())
r=op.open('http://localhost:8000/delivery-templates/'); print('STATUS', r.status, 'len', len(r.read()))
"
```
Expected: `STATUS 200`.

- [ ] **Step 7: Grep nomi funzioni JS (lezione smoke E2E)**

Run: `grep -n "addTimelineSegment\|collectTimelineSegments\|renderTimelineSegments" app/templates/pages/delivery_templates.html`
Expected: ogni funzione definita e referenziata coerentemente (no typo loadX vs reloadX).

- [ ] **Step 8: Commit**

```bash
git add app/templates/pages/delivery_templates.html app/routers/delivery_templates.py
git commit -m "feat(ui): timeline&TC section + audio config dropdown + admin defaults/presets"
```

---

## Task 8: QC — esporre valori attesi nel context

**Files:**
- Modify: il punto dove si costruisce il context QC per un deliverable (cerca dove `JobDeliverable` → spec viene passato alla UI/AI QC). Identificare con: `grep -rn "qc" app/routers/*.py | grep -i context` o nel serializer del deliverable.

- [ ] **Step 1: Identifica il serializer deliverable usato dal QC**

Run: `grep -rn "delivery_item_id\|spec_json\|def _serialize.*deliverable" app/routers/jobs.py app/routers/*qc* 2>/dev/null | head`
Expected: trovi dove il deliverable espone la sua spec.

- [ ] **Step 2: Aggiungi i valori attesi (tc_start/program_start/timeline/audio tracks) al payload**

Dove il deliverable linka un `DeliveryItem` (via `delivery_item_id`), includi nel serializer i valori `effective_timeline(db, item)` + il codice audio + le tracce, come blocco "expected" che l'operatore QC verifica:

```python
from app.services.delivery_timeline_service import effective_timeline
# dove si serializza il deliverable con delivery_item:
if deliverable.delivery_item_id:
    di = db.get(DeliveryItem, deliverable.delivery_item_id)
    if di:
        payload["qc_expected"] = {
            **effective_timeline(db, di),
            "audio_config_code": di.audio_config_code,
        }
```

- [ ] **Step 3: Smoke — verifica che un deliverable con delivery_item esponga qc_expected**

Run: query manuale su un deliverable collegato (se esiste nel DB) o test minimale che chiama il serializer e asserisce la chiave `qc_expected`.
Expected: chiave presente quando `delivery_item_id` è valorizzato.

- [ ] **Step 4: Commit**

```bash
git add app/routers/jobs.py
git commit -m "feat(qc): expose timeline/TC/audio-config expected values in deliverable context"
```

---

## Task 9: Validazione corpus + bump versione + changelog

**Files:**
- Modify: `app/main.py` (version), `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: Snapshot DB pre-validazione**

```bash
.venv/Scripts/python.exe -c "import shutil; shutil.copy('mediaflow.db', 'db_snapshots/snapshot-pre-timeline-audioconfig.db'); print('snapshot OK')"
```

- [ ] **Step 2: Re-parse mirato RAI/Vision/Sky per popolare i nuovi campi**

Esegui il batch parser (o l'AI-extract via endpoint) su RAI-SDHDUHD-1.4, VISION-DIST-IT, SKY-ITA-AV-DELIVERY. Verifica che `tc_start`/`timeline_segments`/`audio_config_code` si popolino:
```bash
.venv/Scripts/python.exe -c "
from app.database import SessionLocal
from app.models.models import DeliveryItem, DeliveryTemplate, AudioConfigPreset
db=SessionLocal()
for code in ['RAI-SDHDUHD-1.4','VISION-DIST-IT']:
    t=db.query(DeliveryTemplate).filter(DeliveryTemplate.code==code).first()
    print(code, 'default_tc_start=', t.default_tc_start if t else None)
    ac=db.query(AudioConfigPreset).filter(AudioConfigPreset.delivery_template_id==t.id).count() if t else 0
    print('  audio presets:', ac)
"
```
Expected: Vision `default_tc_start` popolato (00:59:59:00 dal backfill head_format); RAI con audio presets se il re-parse trova i codici.

- [ ] **Step 3: Run full test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: tutti PASS (inclusi i nuovi test Task 1/3/4/6).

- [ ] **Step 4: Bump versione + changelog + STATO**

In `app/main.py` bump `version="3.5.0-alpha.172.127"`. Aggiungi entry CHANGELOG e STATO (pattern delle versioni precedenti).

- [ ] **Step 5: Restart server + verify health**

Run: kill python + relaunch (pattern avvia_muto / background) + `curl -s http://localhost:8000/health` → version `172.127`.

- [ ] **Step 6: Commit finale**

```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -m "v3.5.0-alpha.172.127 — timeline/TC/audio-config delivery item (feature completa)"
```

---

## Self-Review (compilato in fase di scrittura)

- **Spec coverage:** D1 (campi dedicati) → Task 1; D2 (materializza) → Task 3; D3 (eredità) → Task 4; D4 (preset per-template) → Task 1/5; D5 (fallback notes) → Task 3 (note traccia) + Task 6 (prompt). TC start/program → Task 1/2/6. Timeline segments + reel/source → Task 1/6/7. QC → Task 8. ✓
- **Placeholder scan:** nessun TBD; i 2 punti che richiedono verifica nel codice (nome `safe_json_parse`, sede serializer QC) hanno istruzioni esplicite di grep per risolverli in-task. ✓
- **Type consistency:** `apply_audio_config_preset(db, item, preset)`, `effective_timeline(db, item)`, chiavi `track_layout`/`timeline_segments`/`audio_config_code`/`audio_config_preset_id` coerenti tra model, service, router, parser, UI. ✓

## Note di rischio per l'esecutore

- Verifica il nome reale dell'helper JSON lenient (`safe_json_parse`) prima di usarlo (Task 5/6) — vedi memory `feedback_ai_json_lenient`.
- La sede del context QC (Task 8) va individuata con grep: il QC è event-sourced (QCEvent/QCReport); l'integrazione qui è minima (solo expected values nel serializer del deliverable).
- Re-parse LLM (Task 9 Step 2) ha costo/latenza e rischio sotto-estrazione su capitolati densi — validare manualmente RAI/Vision dopo.
- Restart server obbligatorio dopo modifiche (OneDrive rompe il reload-watcher — lezione α.172.125).
