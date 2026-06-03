# Naming convention capitolati + default tenant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Catturare e mostrare la naming convention dei file in forma strutturata a 3 livelli (item > capitolato > default tenant), riusando il vocabolario token di `naming_helper`. La verifica QC sull'asset è esplicitamente BACKLOG.

**Architecture:** Una funzione pura `resolve_naming_convention` risolve per cascata item→capitolato→tenant (fallback a un default-tenant costante industry). Lo schema è un dict strutturato (`pattern`/`tokens`/regole/`examples`/`raw_note`). Tenant default editabile in `/settings` (lazy: costante fino al primo save). Parser estrae la naming strutturata di default a ogni ingest. Nessun valore fittizio: capitolato/item senza naming → vuoti, a runtime cade sul default tenant.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + SQLite, Jinja2, vanilla JS, pytest. Riusa `app/services/naming_helper.py` (TOKEN_HELP, PRESET_TEMPLATES, resolve_template).

**Spec:** `docs/superpowers/specs/2026-06-03-naming-convention-capitolati-design.md`

**Convenzioni progetto:** Form-based API, tenant scope `current_tenant_id()`, auto-migrate colonne al boot, commit a fine versione (bump `app/main.py` + CHANGELOG + STATO). Nessun seed scritto in DB: il default tenant è una COSTANTE fallback finché l'utente non salva (pattern "AI propone, utente dispone").

---

## File Structure

- `app/services/naming_helper.py` — aggiunge `KNOWN_TOKENS` (set) export del vocabolario.
- `app/services/naming_resolver.py` — **nuovo**: `NamingConvention` schema constants, `DEFAULT_TENANT_NAMING_CONVENTIONS`, `normalize_naming_convention()`, `resolve_naming_convention()`.
- `app/models/models.py` — `Tenant.naming_conventions` (JSON), `DeliveryItem.naming_convention` (JSON).
- `app/main.py` — auto-migrate delle 2 colonne.
- `scripts/migrate_naming_convention.py` — **nuovo**, migrazione idempotente.
- `app/routers/settings.py` — `GET/PUT /api/naming-conventions`.
- `app/routers/delivery_templates.py` — save naming strutturato capitolato + item override.
- `app/services/deliverables_parser.py` — prompt naming strutturato + uso di `normalize_naming_convention`.
- `app/templates/pages/settings.html` — sezione "Naming convention" tenant.
- `app/templates/pages/delivery_templates.html` — naming editabile + override item.
- `tests/test_naming_resolver.py`, `tests/test_naming_settings.py` — **nuovi**.

---

## Task 1: Colonne modello + token export + auto-migrate + script

**Files:**
- Modify: `app/models/models.py` (Tenant ~539, DeliveryItem ~991)
- Modify: `app/services/naming_helper.py` (dopo `TOKEN_HELP`, ~riga 168)
- Modify: `app/main.py` (`_auto_migrate_columns`)
- Create: `scripts/migrate_naming_convention.py`

- [ ] **Step 1: Export del vocabolario token in naming_helper**

In `app/services/naming_helper.py`, subito dopo la chiusura della lista `TOKEN_HELP` (dopo la riga `]` ~168), aggiungi:

```python
# v3.5.0-alpha.172.181 — set dei token noti, single source per validazione
# delle naming convention (capitolato/tenant/item). Derivato da TOKEN_HELP.
KNOWN_TOKENS: set = {t["token"] for t in TOKEN_HELP}
```

- [ ] **Step 2: Aggiungi `Tenant.naming_conventions`**

In `app/models/models.py`, dentro `class Tenant`, dopo `tech_specs_refresh_days` (~riga 570) aggiungi:

```python
    # v3.5.0-alpha.172.181 — Naming convention aziendali di default (per disciplina).
    # Shape: {"video": <conv>, "audio": <conv>} dove <conv> è lo schema strutturato
    # (vedi naming_resolver.normalize_naming_convention). NULL = usa i default
    # industry costanti (DEFAULT_TENANT_NAMING_CONVENTIONS) finché l'utente non salva.
    naming_conventions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 3: Aggiungi `DeliveryItem.naming_convention`**

In `app/models/models.py`, dentro `class DeliveryItem`, dopo `updated_at` (~riga 993, prima della relationship `audio_tracks`) aggiungi:

```python
    # v3.5.0-alpha.172.181 — Override naming convention per la singola voce.
    # NULL = eredita dal capitolato, poi dal default tenant (vedi naming_resolver).
    naming_convention: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 4: Auto-migrate al boot**

In `app/main.py`, dentro `_auto_migrate_columns()`, aggiungi due blocchi (dopo un blocco esistente, seguendo il pattern `if "<table>" in insp.get_table_names()`):

```python
    # v3.5.0-alpha.172.181 — naming convention (tenant default + item override)
    if "tenants" in insp.get_table_names():
        tcols = {c["name"] for c in insp.get_columns("tenants")}
        if "naming_conventions" not in tcols:
            print("[auto-migrate] tenants.naming_conventions mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN naming_conventions TEXT NULL"))
    if "delivery_items" in insp.get_table_names():
        dicols = {c["name"] for c in insp.get_columns("delivery_items")}
        if "naming_convention" not in dicols:
            print("[auto-migrate] delivery_items.naming_convention mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE delivery_items ADD COLUMN naming_convention TEXT NULL"))
```

- [ ] **Step 5: Script di migrazione esplicito**

Create `scripts/migrate_naming_convention.py`:

```python
"""Migrazione v3.5.0-alpha.172.181 — Naming convention strutturata.

Aggiunge:
  - tenants.naming_conventions       TEXT NULL  (JSON {"video":..,"audio":..})
  - delivery_items.naming_convention TEXT NULL  (JSON override per voce)

Idempotente: ALTER solo se la colonna manca. Nessun seed scritto: il default
tenant è costante (DEFAULT_TENANT_NAMING_CONVENTIONS) finché l'utente non salva.

Uso:  python scripts/migrate_naming_convention.py
"""
import sys
from sqlalchemy import inspect, text

sys.path.insert(0, ".")
from app.database import engine  # noqa: E402

TARGETS = [
    ("tenants", "naming_conventions", "TEXT NULL"),
    ("delivery_items", "naming_convention", "TEXT NULL"),
]


def migrate() -> None:
    insp = inspect(engine)
    added = 0
    with engine.begin() as conn:
        for table, col, ddl in TARGETS:
            if table not in insp.get_table_names():
                print(f"[migrate] tabella '{table}' assente — skip")
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            if col not in existing:
                print(f"[migrate] ADD COLUMN {table}.{col}")
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                added += 1
            else:
                print(f"[migrate] {table}.{col} già presente — skip")
    print(f"[migrate] completato ({added} colonne aggiunte).")


if __name__ == "__main__":
    migrate()
```

- [ ] **Step 6: Esegui migrazione + verifica idempotenza + import**

Run: `./.venv/Scripts/python.exe scripts/migrate_naming_convention.py`
Expected: prima esecuzione fino a 2 `ADD COLUMN`; seconda esecuzione 2 `già presente — skip`, `0 colonne aggiunte`.
Run: `./.venv/Scripts/python.exe -c "import app.main; print('import OK')"`
Expected: `import OK`

- [ ] **Step 7: Commit**

```bash
git add app/models/models.py app/services/naming_helper.py app/main.py scripts/migrate_naming_convention.py
git commit -m "feat(naming): colonne naming_conventions (tenant) + naming_convention (item) + token export"
```

---

## Task 2: `naming_resolver.py` — schema, normalize, resolve (TDD)

**Files:**
- Create: `app/services/naming_resolver.py`
- Test: `tests/test_naming_resolver.py`

- [ ] **Step 1: Scrivi i test (falliscono)**

Create `tests/test_naming_resolver.py`:

```python
"""Naming convention strutturata: normalize + resolve cascade (α.172.181)."""
from app.services import naming_resolver as nr


def test_default_tenant_has_video_and_audio():
    d = nr.DEFAULT_TENANT_NAMING_CONVENTIONS
    assert "video" in d and "audio" in d
    assert d["video"]["pattern"] and isinstance(d["video"]["tokens"], list)


def test_normalize_keeps_valid_shape():
    raw = {
        "pattern": "{project_code}_{title}_{date_iso}",
        "tokens": ["project_code", "title", "date_iso"],
        "separator": "_", "allowed_chars": "A-Za-z0-9_-",
        "max_length": 120, "case": "upper", "extension": ".mov",
        "examples": ["MARE_X_2026-06-03.mov"], "source": "capitolato",
    }
    out = nr.normalize_naming_convention(raw)
    assert out["pattern"] == raw["pattern"]
    assert out["case"] == "upper"
    assert out["max_length"] == 120
    assert out["tokens"] == ["project_code", "title", "date_iso"]


def test_normalize_invalid_case_defaults_asis():
    out = nr.normalize_naming_convention({"pattern": "{title}", "case": "SHOUT"})
    assert out["case"] == "asis"


def test_normalize_maxlength_non_int_becomes_none():
    out = nr.normalize_naming_convention({"pattern": "{title}", "max_length": "abc"})
    assert out["max_length"] is None


def test_normalize_unknown_tokens_flagged():
    out = nr.normalize_naming_convention({"pattern": "{title}_{nope}", "tokens": ["title", "nope"]})
    # token sconosciuti restano ma sono segnalati in `unknown_tokens`
    assert "nope" in out["unknown_tokens"]
    assert "title" not in out["unknown_tokens"]


def test_normalize_none_returns_none():
    assert nr.normalize_naming_convention(None) is None
    assert nr.normalize_naming_convention({}) is None  # senza pattern → None


def test_resolve_falls_back_to_tenant_default_when_all_empty():
    # nessun item, nessun template, tenant senza naming → default costante video
    conv = nr.resolve_naming_convention(
        db=None, delivery_item=None, delivery_template=None,
        discipline="video", tenant_naming=None,
    )
    assert conv["_source"] == "tenant_default"
    assert conv["pattern"] == nr.DEFAULT_TENANT_NAMING_CONVENTIONS["video"]["pattern"]


def test_resolve_prefers_item_over_template_over_tenant():
    item_conv = {"pattern": "ITEM_{title}", "source": "item"}
    tpl_conv = {"pattern": "TPL_{title}", "source": "capitolato"}
    tenant = {"video": {"pattern": "TENANT_{title}"}}
    # item wins
    r = nr.resolve_naming_convention(db=None, delivery_item_conv=item_conv,
                                     delivery_template_conv=tpl_conv,
                                     discipline="video", tenant_naming=tenant)
    assert r["pattern"] == "ITEM_{title}" and r["_source"] == "item"
    # no item → template wins
    r2 = nr.resolve_naming_convention(db=None, delivery_item_conv=None,
                                      delivery_template_conv=tpl_conv,
                                      discipline="video", tenant_naming=tenant)
    assert r2["pattern"] == "TPL_{title}" and r2["_source"] == "capitolato"


def test_resolve_template_per_discipline_dict():
    # capitolato con naming distinto video/audio → seleziona per discipline
    tpl_conv = {"video": {"pattern": "V_{title}"}, "audio": {"pattern": "A_{title}"}}
    r = nr.resolve_naming_convention(db=None, delivery_item_conv=None,
                                     delivery_template_conv=tpl_conv,
                                     discipline="audio", tenant_naming=None)
    assert r["pattern"] == "A_{title}" and r["_source"] == "capitolato"
```

- [ ] **Step 2: Esegui e verifica FAIL**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_naming_resolver.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.naming_resolver`).

- [ ] **Step 3: Implementa `naming_resolver.py`**

Create `app/services/naming_resolver.py`:

```python
"""Naming convention strutturata — schema, normalizzazione, risoluzione a cascata.

Gerarchia override (per ogni deliverable/asset):
    item.naming_convention -> template.naming_convention -> tenant.naming_conventions[discipline]
    -> DEFAULT_TENANT_NAMING_CONVENTIONS[discipline] (costante industry, ultimo fallback).

Lo schema `<conv>` è un dict:
    {pattern, tokens[], separator, allowed_chars, max_length, case, extension,
     examples[], source, raw_note, unknown_tokens[]}
Token ammessi = naming_helper.KNOWN_TOKENS (vocabolario condiviso).
La verifica del filename asset NON è qui (è backlog QC).
"""
from __future__ import annotations
from typing import Optional

from app.services.naming_helper import KNOWN_TOKENS

_CASES = {"upper", "lower", "asis"}

# Default industry (DCP/IMF/Netflix), proposti come fallback tenant finché
# l'utente non salva una propria configurazione in /settings.
DEFAULT_TENANT_NAMING_CONVENTIONS: dict = {
    "video": {
        "pattern": "{project_code}_{film_name}_{deliverable_kind}_{resolution}_{lang_audio}_{date_compact}",
        "tokens": ["project_code", "film_name", "deliverable_kind", "resolution", "lang_audio", "date_compact"],
        "separator": "_",
        "allowed_chars": "A-Za-z0-9_-",
        "max_length": 120,
        "case": "asis",
        "extension": "",
        "examples": ["MARE-2026_MareNostrum_PRORES_UHD_it_20260612.mov"],
        "source": "tenant_default",
        "raw_note": "Default azienda video (ispirato a ISDCF DCP / Netflix archival).",
    },
    "audio": {
        "pattern": "{project_code}_{film_name}_{audio_config}_{lang_audio}_{date_compact}",
        "tokens": ["project_code", "film_name", "audio_config", "lang_audio", "date_compact"],
        "separator": "_",
        "allowed_chars": "A-Za-z0-9_-",
        "max_length": 120,
        "case": "asis",
        "extension": "",
        "examples": ["MARE-2026_MareNostrum_51_it_20260612.wav"],
        "source": "tenant_default",
        "raw_note": "Default azienda audio.",
    },
}


def normalize_naming_convention(raw: Optional[dict]) -> Optional[dict]:
    """Valida/ripulisce un dict naming convention (output AI o form).
    Ritorna None se `raw` è vuoto o privo di `pattern`. Non solleva: difensivo.
    """
    if not raw or not isinstance(raw, dict):
        return None
    pattern = (raw.get("pattern") or "").strip()
    raw_note = (raw.get("raw_note") or "").strip()
    if not pattern and not raw_note:
        return None
    tokens = raw.get("tokens") or []
    if not isinstance(tokens, list):
        tokens = []
    tokens = [str(t).strip() for t in tokens if str(t).strip()]
    unknown = [t for t in tokens if t not in KNOWN_TOKENS]
    case = str(raw.get("case") or "asis").strip().lower()
    if case not in _CASES:
        case = "asis"
    ml = raw.get("max_length")
    try:
        max_length = int(ml) if ml is not None and str(ml).strip() != "" else None
    except (TypeError, ValueError):
        max_length = None
    examples = raw.get("examples") or []
    if not isinstance(examples, list):
        examples = []
    examples = [str(e).strip() for e in examples if str(e).strip()]
    return {
        "pattern": pattern,
        "tokens": tokens,
        "separator": str(raw.get("separator") or "_"),
        "allowed_chars": str(raw.get("allowed_chars") or "A-Za-z0-9_-"),
        "max_length": max_length,
        "case": case,
        "extension": str(raw.get("extension") or ""),
        "examples": examples,
        "source": str(raw.get("source") or "manual"),
        "raw_note": raw_note,
        "unknown_tokens": unknown,
    }


def _pick_for_discipline(conv: Optional[dict], discipline: str) -> Optional[dict]:
    """Una `<conv>` può essere singola o un dict per-disciplina {video,audio}.
    Ritorna la conv applicabile per `discipline`, o None."""
    if not conv or not isinstance(conv, dict):
        return None
    # dict per-disciplina se contiene chiavi disciplina e NON un pattern diretto
    if "pattern" not in conv and (discipline in conv):
        return conv.get(discipline)
    if "pattern" in conv:
        return conv
    return None


def resolve_naming_convention(
    db=None,
    *,
    delivery_item=None,
    delivery_template=None,
    delivery_item_conv: Optional[dict] = None,
    delivery_template_conv: Optional[dict] = None,
    discipline: str = "video",
    tenant_naming: Optional[dict] = None,
) -> dict:
    """Risolve la naming convention applicabile per cascata.

    Accetta o gli ORM (`delivery_item`/`delivery_template`, da cui legge
    `.naming_convention`) o direttamente i dict (`*_conv`, utile nei test).
    `tenant_naming` = Tenant.naming_conventions (dict {video,audio}) o None.
    Ritorna SEMPRE un dict <conv> con chiave extra `_source`
    ('item'|'capitolato'|'tenant'|'tenant_default').
    """
    discipline = (discipline or "video").strip().lower()
    if discipline not in ("video", "audio"):
        discipline = "video"

    item_conv = delivery_item_conv
    if item_conv is None and delivery_item is not None:
        item_conv = getattr(delivery_item, "naming_convention", None)
    tpl_conv = delivery_template_conv
    if tpl_conv is None and delivery_template is not None:
        tpl_conv = getattr(delivery_template, "naming_convention", None)

    picked = _pick_for_discipline(item_conv, discipline)
    if picked and picked.get("pattern"):
        return {**picked, "_source": "item"}
    picked = _pick_for_discipline(tpl_conv, discipline)
    if picked and picked.get("pattern"):
        return {**picked, "_source": "capitolato"}
    if tenant_naming and isinstance(tenant_naming, dict):
        tconv = tenant_naming.get(discipline)
        if tconv and tconv.get("pattern"):
            return {**tconv, "_source": "tenant"}
    return {**DEFAULT_TENANT_NAMING_CONVENTIONS[discipline], "_source": "tenant_default"}
```

- [ ] **Step 4: Esegui e verifica PASS**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_naming_resolver.py -v`
Expected: PASS (tutti).

- [ ] **Step 5: Commit**

```bash
git add app/services/naming_resolver.py tests/test_naming_resolver.py
git commit -m "feat(naming): naming_resolver (schema + normalize + cascade resolve) + default industry"
```

---

## Task 3: Settings endpoint GET/PUT naming-conventions (TDD)

**Files:**
- Modify: `app/routers/settings.py` (dopo `fs_scan_paths_set`, ~riga 838)
- Test: `tests/test_naming_settings.py`

- [ ] **Step 1: Scrivi il test (fallisce)**

Create `tests/test_naming_settings.py`. Riusa il pattern del client autenticato già creato in `tests/test_billable_hours_mode.py` (fixture `client_admin` con StaticPool + JWT cookie): leggi quel file e importa/replica la fixture. In mancanza, replica lo stesso schema.

```python
import json
import pytest


def test_get_returns_defaults_when_unset(client_admin):
    r = client_admin.get("/settings/api/naming-conventions")
    assert r.status_code == 200
    body = r.json()
    # quando il tenant non ha naming salvata → ritorna i default industry + is_default
    assert body["is_default"] is True
    assert "video" in body["conventions"] and "audio" in body["conventions"]
    assert body["conventions"]["video"]["pattern"]


def test_put_persists_and_get_reflects(client_admin):
    payload = {
        "video": {"pattern": "{project_code}_{title}", "tokens": ["project_code", "title"], "case": "upper"},
        "audio": {"pattern": "{project_code}_{audio_config}", "tokens": ["project_code", "audio_config"]},
    }
    r = client_admin.put("/settings/api/naming-conventions", data={"conventions_json": json.dumps(payload)})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    g = client_admin.get("/settings/api/naming-conventions")
    body = g.json()
    assert body["is_default"] is False
    assert body["conventions"]["video"]["pattern"] == "{project_code}_{title}"
    assert body["conventions"]["video"]["case"] == "upper"


def test_token_help_exposed(client_admin):
    r = client_admin.get("/settings/api/naming-conventions")
    assert isinstance(r.json().get("token_help"), list)
    assert any(t["token"] == "project_code" for t in r.json()["token_help"])
```

- [ ] **Step 2: Esegui FAIL**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_naming_settings.py -v`
Expected: FAIL 404.

- [ ] **Step 3: Implementa gli endpoint**

In `app/routers/settings.py`, dopo `fs_scan_paths_set` (~riga 838) aggiungi. Verifica che `Form`, `Cookie`, `HTTPException`, `_resolve_current_user`, `_require_admin`, `current_tenant_id`, `get_db` siano già importati nel file (lo sono, usati da fs-scan-paths).

```python
@router.get("/api/naming-conventions")
async def naming_conventions_get(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Naming convention di default del tenant (video/audio). Se non salvate,
    ritorna i default industry costanti con is_default=True. Include il
    vocabolario token per il picker UI."""
    from app.models import Tenant
    from app.services.naming_resolver import DEFAULT_TENANT_NAMING_CONVENTIONS
    from app.services.naming_helper import TOKEN_HELP
    u = _resolve_current_user(db, access_token)
    _require_admin(u)
    t = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    if not t:
        raise HTTPException(404)
    stored = t.naming_conventions
    is_default = not bool(stored)
    conventions = stored if stored else DEFAULT_TENANT_NAMING_CONVENTIONS
    return {"conventions": conventions, "is_default": is_default, "token_help": TOKEN_HELP}


@router.put("/api/naming-conventions")
async def naming_conventions_set(
    conventions_json: str = Form(...),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Salva le naming convention tenant. conventions_json = {"video":<conv>,"audio":<conv>}.
    Ogni <conv> viene normalizzata (normalize_naming_convention)."""
    import json as _json
    from app.models import Tenant
    from app.services.naming_resolver import normalize_naming_convention
    u = _resolve_current_user(db, access_token)
    _require_admin(u)
    try:
        raw = _json.loads(conventions_json)
    except _json.JSONDecodeError:
        raise HTTPException(400, "conventions_json malformato")
    if not isinstance(raw, dict):
        raise HTTPException(400, "conventions_json deve essere un oggetto")
    out = {}
    for disc in ("video", "audio"):
        norm = normalize_naming_convention(raw.get(disc))
        if norm is not None:
            norm["source"] = "tenant"
            out[disc] = norm
    t = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    if not t:
        raise HTTPException(404)
    t.naming_conventions = out or None
    db.commit()
    return {"ok": True, "conventions": out}
```

- [ ] **Step 4: Esegui PASS**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_naming_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routers/settings.py tests/test_naming_settings.py
git commit -m "feat(settings): endpoint GET/PUT naming-conventions tenant (default industry lazy)"
```

---

## Task 4: Parser — estrazione naming strutturata + normalize

**Files:**
- Modify: `app/services/deliverables_parser.py` (~riga 175, blocco prompt naming_convention; + dove si costruisce il dict template/item dal risultato AI)
- Test: estende `tests/test_naming_resolver.py` con un test su normalize applicato a un output AI sporco (no AI reale).

- [ ] **Step 1: Leggi il parser e individua i 2 punti**

PRIMA di editare, leggi `app/services/deliverables_parser.py` attorno a riga 175 (testo del prompt che descrive `naming_convention`) e trova dove l'output AI viene assemblato nel dict del template e dei singoli item (cerca `naming_convention` e la costruzione del record template/item). Annota i nomi reali delle funzioni/variabili.

- [ ] **Step 2: Rendi il prompt naming strutturato**

Aggiorna il frammento di prompt naming (era `naming_convention: {pattern, examples, special_chars_allowed, max_length, ...}`) chiedendo esplicitamente lo schema token-based. Usa questo testo (adatta all'idioma del prompt esistente, italiano/inglese coerente col resto del file):

```
"naming_convention" (oggetto, opzionale — compila SOLO se il capitolato specifica una convenzione di nomenclatura file; altrimenti ometti o lascia null):
  - "pattern": stringa con token tra graffe scelti TRA QUESTI: {project_code, film_name, title, content_type, aspect, resolution, framerate, audio_config, lang_audio, lang_subs, territory, version, revision, standard, package_type, deliverable_kind, date_iso, date_compact, studio_code, facility_code}. Esempio: "{film_name}_{content_type}_{resolution}_{lang_audio}_{date_compact}".
  - "separator": carattere separatore (es. "_").
  - "case": "upper" | "lower" | "asis".
  - "extension": estensione file se indicata (es. ".mxf", ".wav") o "".
  - "max_length": numero massimo caratteri se indicato, altrimenti null.
  - "allowed_chars": classe caratteri ammessi se indicata (es. "A-Za-z0-9_-").
  - "examples": lista di nomi-file di esempio citati nel capitolato.
  - "raw_note": se la convenzione è descritta a parole ma NON mappabile a un pattern pulito, riporta qui il testo verbatim.
Estrai questo blocco SIA per il capitolato nel suo insieme SIA, quando il capitolato distingue, per ogni singola voce/deliverable.
```

- [ ] **Step 3: Normalizza l'output AI prima del save**

Nei punti dove il parser costruisce il dict del template e di ogni item, passa il `naming_convention` grezzo dell'AI attraverso `normalize_naming_convention`. Aggiungi in cima al file (con gli altri import):

```python
from app.services.naming_resolver import normalize_naming_convention
```

E dove assegni la naming al record template/item, avvolgi:

```python
# v3.5.0-alpha.172.181 — naming convention strutturata + validata
template_record["naming_convention"] = normalize_naming_convention(ai_result.get("naming_convention"))
# e per ogni item:
item_record["naming_convention"] = normalize_naming_convention(ai_item.get("naming_convention"))
```

(Adatta `template_record`/`ai_result`/`item_record`/`ai_item` ai nomi reali trovati allo Step 1. Se il parser non assembla item con un campo naming, aggiungilo seguendo la struttura degli altri campi item.)

- [ ] **Step 4: Test normalize su output AI sporco**

Aggiungi a `tests/test_naming_resolver.py`:

```python
def test_normalize_ai_dirty_output():
    # output AI tipico: max_length come stringa, case maiuscolo, token misti
    ai = {"pattern": "{film_name}_{resolution}_{lang_audio}",
          "tokens": ["film_name", "resolution", "lang_audio", "weird_token"],
          "case": "UPPER", "max_length": "100", "examples": ["X_UHD_it"]}
    out = nr.normalize_naming_convention(ai)
    assert out["case"] == "upper"
    assert out["max_length"] == 100
    assert "weird_token" in out["unknown_tokens"]
```

- [ ] **Step 5: Esegui + import**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_naming_resolver.py -v`
Expected: PASS.
Run: `./.venv/Scripts/python.exe -c "import app.services.deliverables_parser; print('OK')"`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add app/services/deliverables_parser.py tests/test_naming_resolver.py
git commit -m "feat(parser): estrazione naming convention strutturata a ogni ingest + normalize"
```

---

## Task 5: UI Settings tenant — sezione Naming convention

**Files:**
- Modify: `app/templates/pages/settings.html`

> PRIMA: leggi `app/templates/pages/settings.html` per capire il pattern delle sezioni/tab esistenti (es. come è fatta la sezione "Azienda" o "AI") e come fanno fetch/save (helper `api()`). Aggancia la nuova sezione con lo stesso stile.

- [ ] **Step 1: Markup sezione**

Aggiungi una card/tab "Naming convention" con, per disciplina **video** e **audio**: input `pattern`, `separator`, select `case` (upper/lower/asis), input `extension`, `max_length`, `allowed_chars`, textarea `examples` (una per riga), e un blocco anteprima `#nc-preview-video` / `#nc-preview-audio`. Più un elenco token disponibili (dal `token_help`). Usa `textContent` per i nomi token (no innerHTML con dati).

```html
<div class="card" id="naming-conv-card">
  <div class="card-title">Naming convention (default azienda)</div>
  <p class="text-muted text-sm">Convenzione applicata a tutti gli asset prodotti, salvo override del capitolato o della singola voce. Token tra <code>{graffe}</code>.</p>
  <div id="nc-token-help" class="text-xs text-muted" style="margin:6px 0;"></div>
  <div id="nc-editors"></div>
  <button class="btn btn-primary btn-sm" id="nc-save" style="margin-top:10px;">Salva naming convention</button>
</div>
```

- [ ] **Step 2: JS — load, render editor per disciplina, preview live, save**

Aggiungi nel `<script>` della pagina (adatta `api()` al reale helper). La preview usa una resolve client-side semplice (sostituzione token con un valore demo) — NON serve endpoint: la generazione reale del nome è in `naming_helper` lato server, qui è solo specchio visivo del pattern.

```javascript
async function ncLoad() {
  const data = await api('GET', '/settings/api/naming-conventions');
  // token help
  const th = document.getElementById('nc-token-help');
  th.textContent = 'Token: ' + (data.token_help || []).map(t => '{' + t.token + '}').join('  ');
  const host = document.getElementById('nc-editors');
  host.innerHTML = '';
  window._ncState = JSON.parse(JSON.stringify(data.conventions || {}));
  ['video', 'audio'].forEach(disc => {
    const c = (window._ncState[disc]) || {pattern:'', separator:'_', case:'asis', extension:'', max_length:'', allowed_chars:'A-Za-z0-9_-', examples:[]};
    window._ncState[disc] = c;
    const box = document.createElement('div');
    box.style.cssText = 'border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:10px;';
    const title = document.createElement('div'); title.style.fontWeight='600'; title.style.marginBottom='6px';
    title.textContent = disc === 'video' ? 'Video' : 'Audio';
    box.appendChild(title);
    const mk = (label, key, val) => {
      const w = document.createElement('label'); w.style.cssText='display:block;font-size:12px;margin:4px 0;';
      w.textContent = label + ' ';
      const i = document.createElement('input'); i.className='form-input'; i.value = val || '';
      i.addEventListener('input', () => { window._ncState[disc][key] = i.value; ncPreview(disc); });
      w.appendChild(i); return w;
    };
    box.appendChild(mk('Pattern', 'pattern', c.pattern));
    box.appendChild(mk('Separatore', 'separator', c.separator));
    box.appendChild(mk('Estensione', 'extension', c.extension));
    box.appendChild(mk('Max length', 'max_length', c.max_length));
    // case select
    const cw = document.createElement('label'); cw.style.cssText='display:block;font-size:12px;margin:4px 0;'; cw.textContent='Case ';
    const cs = document.createElement('select'); cs.className='form-select';
    ['asis','upper','lower'].forEach(v => { const o=document.createElement('option'); o.value=v; o.textContent=v; if(v===(c.case||'asis')) o.selected=true; cs.appendChild(o); });
    cs.addEventListener('change', () => { window._ncState[disc].case = cs.value; ncPreview(disc); });
    cw.appendChild(cs); box.appendChild(cw);
    const prev = document.createElement('div'); prev.id = 'nc-preview-' + disc; prev.style.cssText='font-size:12px;margin-top:6px;color:var(--indigo2);';
    box.appendChild(prev);
    host.appendChild(box);
    ncPreview(disc);
  });
}
function ncPreview(disc) {
  const c = window._ncState[disc] || {};
  const demo = {project_code:'MARE-2026', film_name:'MareNostrum', title:'MareNostrum', resolution:'UHD', lang_audio:'it', audio_config:'51', date_compact:'20260612', deliverable_kind:'PRORES'};
  let out = (c.pattern || '').replace(/\{([a-z_]+)\}/gi, (m, k) => demo[k.toLowerCase()] || '__');
  if (c.case === 'upper') out = out.toUpperCase(); else if (c.case === 'lower') out = out.toLowerCase();
  if (c.extension) out += c.extension;
  const el = document.getElementById('nc-preview-' + disc);
  if (el) el.textContent = 'Anteprima: ' + out;
}
async function ncSave() {
  // tokens derivati dal pattern
  ['video','audio'].forEach(disc => {
    const c = window._ncState[disc] || {};
    c.tokens = [...new Set((c.pattern||'').match(/\{([a-z_]+)\}/gi) || [])].map(s => s.replace(/[{}]/g,'').toLowerCase());
    if (c.max_length === '') c.max_length = null;
  });
  const fd = new FormData(); fd.append('conventions_json', JSON.stringify(window._ncState));
  try { await api('PUT', '/settings/api/naming-conventions', fd); toast('Naming convention salvata', 'success'); }
  catch(e) { toast(e.message || 'Errore salvataggio', 'error'); }
}
document.getElementById('nc-save')?.addEventListener('click', ncSave);
// chiama ncLoad() quando la sezione/tab diventa visibile (aggancia al pattern tab esistente)
```

- [ ] **Step 3: Aggancia ncLoad al ciclo di vita della tab + cache-buster**

Chiama `ncLoad()` all'apertura della tab (segui come le altre sezioni inizializzano i loro fetch). Se il JS è inline nel template, nessun cache-buster; se in un .js esterno, il progetto usa `?v={{ app_version }}` automatico.

- [ ] **Step 4: Jinja parse + smoke**

Run: `./.venv/Scripts/python.exe -c "from jinja2 import Environment, FileSystemLoader as L; L2=Environment(loader=L('app/templates')); L2.get_template('pages/settings.html'); print('JINJA OK')"`
Expected: `JINJA OK`.
(Smoke browser fatto dal controller.)

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/settings.html
git commit -m "feat(settings-ui): sezione Naming convention tenant (editor video/audio + preview)"
```

---

## Task 6: UI capitolato — naming editabile + override item

**Files:**
- Modify: `app/templates/pages/delivery_templates.html`
- Modify: `app/routers/delivery_templates.py` (save naming strutturato + item override)

> PRIMA: leggi `delivery_templates.html` (blocco naming attuale, righe ~117/264/363) e `delivery_templates.py` (handler save del template + endpoint item, se esiste). Annota nomi reali (funzione save, come serializza i blocchi JSON, endpoint item).

- [ ] **Step 1: Capitolato — naming block editabile**

Rendi il blocco `naming_convention` del capitolato editabile (oggi mostrato read-only). Riusa gli stessi campi della sezione settings (pattern/separator/case/extension/max_length/examples/raw_note). Al save del template, il blocco va serializzato come JSON (il save già fa `JSON.stringify(parsed[k])` per i blocchi — assicura che `naming_convention` passi da `normalize` lato server, vedi Step 3).

- [ ] **Step 2: Item — naming override**

Per ogni item del capitolato, aggiungi un controllo "Naming (override)" opzionale: se vuoto, mostra badge "eredita da capitolato/tenant" e (read-only) la convenzione ereditata calcolata client-side dal capitolato/tenant; se compilato, salva `naming_convention` sull'item.

- [ ] **Step 3: Server — normalize su save (template + item)**

In `app/routers/delivery_templates.py`, nel handler che salva il template, fai passare il `naming_convention` ricevuto da `normalize_naming_convention` prima di scriverlo:

```python
from app.services.naming_resolver import normalize_naming_convention
# ... dove si assegna il blocco naming al DeliveryTemplate:
tpl.naming_convention = normalize_naming_convention(naming_payload)
```

Per l'item: nell'endpoint che crea/aggiorna un `DeliveryItem`, accetta un Form `naming_convention_json` opzionale e:

```python
import json as _json
from app.services.naming_resolver import normalize_naming_convention
if naming_convention_json is not None:
    try:
        item.naming_convention = normalize_naming_convention(_json.loads(naming_convention_json))
    except _json.JSONDecodeError:
        raise HTTPException(400, "naming_convention_json malformato")
```

(Adatta ai nomi reali: la variabile del payload naming del template, il nome dell'endpoint item, la firma Form.)

- [ ] **Step 4: Jinja parse + import + smoke**

Run: `./.venv/Scripts/python.exe -c "from jinja2 import Environment, FileSystemLoader as L; e=Environment(loader=L('app/templates')); e.get_template('pages/delivery_templates.html'); print('JINJA OK')"`
Run: `./.venv/Scripts/python.exe -c "import app.main; print('import OK')"`
Expected: `JINJA OK` + `import OK`.

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/delivery_templates.html app/routers/delivery_templates.py
git commit -m "feat(capitolati-ui): naming convention editabile + override per item"
```

---

## Task 7: Regressione + bump + CHANGELOG/STATO + backlog QC

**Files:**
- Modify: `app/main.py` (versione), `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: Suite completa**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: tutti PASS (≥ 338 + nuovi). Se rosso → investiga, NON bumpare.

- [ ] **Step 2: Bump versione**

In `app/main.py` riga della versione: `3.5.0-alpha.172.180` → `3.5.0-alpha.172.181`.

- [ ] **Step 3: CHANGELOG**

Aggiungi in cima a `CHANGELOG.md` una entry `v3.5.0-alpha.172.181` con: naming convention strutturata 3 livelli (item>capitolato>tenant default), schema token (riusa naming_helper), default tenant editabile in /settings (DCP/IMF/Netflix, lazy), estrazione parser di default a ogni ingest (template+item), `resolve_naming_convention` single-source. Nota esplicita: **verifica QC asset = BACKLOG**.

- [ ] **Step 4: STATO + backlog QC**

In `docs/STATO.md`: versione corrente → α.172.181; sezione fatto; **Prossimo** = (1) test browser Matteo (settings naming, capitolato naming editabile, override item, re-ingest capitolato e verifica naming estratta), (2) **BACKLOG QC**: "verifica `Asset.filename` vs `resolve_naming_convention` (regole pattern/regex/allowed_chars/max_length/case/extension), richiede analisi+refactor `qc_specs_compare.py`".

- [ ] **Step 5: Commit**

```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -m "chore: α.172.181 naming convention capitolati + default tenant (QC verifica = backlog)"
```

> Push + export ZIP: gestiti dal controller su richiesta di Matteo.

---

## Self-Review (autore del piano)

**Spec coverage:**
- §1 gerarchia/resolver → Task 2 (`resolve_naming_convention`) ✅
- §2 modello (Tenant.naming_conventions, DeliveryItem.naming_convention) → Task 1 ✅
- §3 schema strutturato + token vocab → Task 1 (KNOWN_TOKENS) + Task 2 (normalize/schema) ✅
- §4 estrazione default a ogni ingest → Task 4 ✅
- §5 UI settings tenant + preview → Task 3 (endpoint) + Task 5 (UI) ✅
- §6 UI capitolato/item → Task 6 ✅
- §7 QC = backlog → Task 7 Step 4 (annotato STATO) ✅
- Test (spec §Test) → Task 2/3/4 (resolver, normalize, settings, parser-normalize) + Task 7 (regressione) ✅
- D4 "AI propone utente dispone" (default lazy, non scritto finché non si salva) → Task 1 (no seed) + Task 3 (GET ritorna default con is_default) ✅
- D6 default per disciplina video/audio → Task 2 DEFAULT_TENANT_NAMING_CONVENTIONS ✅

**Placeholder scan:** nessun TODO/TBD con codice mancante. Le NOTE "leggi prima il file e adatta i nomi reali" in Task 4/5/6 sono istruzioni di lettura per il parser/UI (nomi runtime da verificare in loco), non placeholder di logica.

**Type consistency:** `normalize_naming_convention(raw)->dict|None`, `resolve_naming_convention(...,discipline,tenant_naming)->dict con _source`, `KNOWN_TOKENS:set`, `DEFAULT_TENANT_NAMING_CONVENTIONS:{video,audio}` usati coerentemente in tutte le task. Endpoint `/settings/api/naming-conventions` GET/PUT con `conventions_json` Form coerente tra test (Task 3) e UI (Task 5). Campo modello `Tenant.naming_conventions` e `DeliveryItem.naming_convention` coerenti tra modello (Task 1), resolver (Task 2), endpoint (Task 3), parser (Task 4), capitolato save (Task 6).
