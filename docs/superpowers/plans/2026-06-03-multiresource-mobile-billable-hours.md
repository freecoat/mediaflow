# Multi-risorsa mobile + policy ore fatturabili — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettere booking multi-risorsa anche su mobile e rendere configurabile per-booking come si contano le ore fatturabili al cliente quando ci sono ≥2 risorse umane (max / sum / specific / manual), default `max` = comportamento attuale invariato.

**Architecture:** Una funzione pura `compute_billable_hours` in `cost_line_sync.py` diventa la single source of truth; `_booking_billable_hours` la usa leggendo 3 nuove colonne su `Booking`. Un endpoint preview server-side espone lo stesso calcolo all'UI (niente drift JS). UI inline (totale ore live + selector) nel modal desktop e nella pagina mobile, visibile solo con ≥2 umane. Costo interno invariato.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (Mapped) + SQLite, Jinja2, vanilla JS, pytest.

**Spec di riferimento:** `docs/superpowers/specs/2026-06-03-multiresource-mobile-billable-hours-design.md`

**Convenzioni progetto (CLAUDE.md):** Form-based API (no JSON body), tenant filter `current_tenant_id()`, soft-delete, auto-migrate colonne al boot, commit a fine versione con bump `app/main.py` + CHANGELOG + STATO. Default mode `max` preserva l'esatto comportamento pre-feature.

---

## File Structure

- `app/models/models.py` — 3 colonne su `Booking` (model truth)
- `app/main.py` — `_auto_migrate_columns()`: ALTER difensivo al boot + bump versione
- `scripts/migrate_billable_hours_mode.py` — **nuovo**: migrazione esplicita idempotente
- `app/services/cost_line_sync.py` — `compute_billable_hours` (puro) + refactor `_booking_billable_hours`
- `app/routers/planning.py` — endpoint `preview-billable` + 3 campi Form in create/update booking + recompute su cambio mode
- `app/templates/pages/planning.html` — blocco UI nel modal booking
- `app/templates/mobile/booking_new.html` — multi-select risorse + blocco UI
- `tests/test_billable_hours_mode.py` — **nuovo**: unit funzione pura + endpoint preview
- `tests/test_billable_hours_recompute.py` — **nuovo**: integrazione recompute + regressione
- `CHANGELOG.md`, `docs/STATO.md` — chiusura versione

---

## Task 1: Colonne `Booking` + auto-migrate + script migrazione

**Files:**
- Modify: `app/models/models.py:2168` (dopo `original_end_datetime`, dentro `class Booking`)
- Modify: `app/main.py:133-145` (lista `booking_alter` in `_auto_migrate_columns`)
- Create: `scripts/migrate_billable_hours_mode.py`
- Test: copertura indiretta via boot (Task 2+ usano le colonne)

- [ ] **Step 1: Aggiungi le 3 colonne al modello**

In `app/models/models.py`, dentro `class Booking(Base)`, subito dopo la riga `original_end_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)` (riga ~2168), inserisci:

```python
    # v3.5.0-alpha.172.179 — Policy conteggio ore FATTURABILI al cliente quando
    # il booking ha ≥2 risorse umane. Default 'max' = comportamento storico
    # (override umana, max tra le persone). NON tocca il costo interno, che
    # somma sempre tutti gli assignment. Vedi cost_line_sync.compute_billable_hours.
    #   max      → max(ore per risorsa umana)  [default storico]
    #   sum      → somma delle ore di tutte le umane (lavoro parallelo)
    #   specific → ore della sola risorsa scelta (billable_hours_resource_id)
    #   manual   → ore digitate dal producer (billable_hours_manual)
    billable_hours_mode: Mapped[str] = mapped_column(String(16), default="max")
    billable_hours_resource_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("resources.id"), nullable=True
    )
    billable_hours_manual: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
```

- [ ] **Step 2: Estendi l'auto-migrate al boot**

In `app/main.py`, nella lista `booking_alter` (riga ~133-140), aggiungi le 3 voci:

```python
        booking_alter = [
            ("priority", "VARCHAR(16) NOT NULL DEFAULT 'normal'"),
            ("execution_status", "VARCHAR(16) NOT NULL DEFAULT 'planned'"),
            ("not_done_reason", "TEXT NULL"),
            ("count_in_costs", "BOOLEAN NOT NULL DEFAULT 0"),
            ("overtime_status", "VARCHAR(16) NOT NULL DEFAULT 'none'"),
            ("original_end_datetime", "DATETIME NULL"),
            # v3.5.0-alpha.172.179 — policy ore fatturabili per-booking
            ("billable_hours_mode", "VARCHAR(16) NOT NULL DEFAULT 'max'"),
            ("billable_hours_resource_id", "INTEGER NULL REFERENCES resources(id)"),
            ("billable_hours_manual", "FLOAT NULL"),
        ]
```

- [ ] **Step 3: Crea lo script di migrazione esplicito**

Create `scripts/migrate_billable_hours_mode.py`:

```python
"""Migrazione v3.5.0-alpha.172.179 — Policy ore fatturabili per-booking.

Aggiunge a `bookings`:
  - billable_hours_mode        VARCHAR(16) NOT NULL DEFAULT 'max'
  - billable_hours_resource_id INTEGER NULL  (FK resources.id)
  - billable_hours_manual      FLOAT NULL

Idempotente: ALTER TABLE solo se la colonna manca. Backfill 'max' implicito
dal DEFAULT (= comportamento storico, override umana max). Nessun dato esistente
modificato nei valori.

Uso:  python scripts/migrate_billable_hours_mode.py
"""
import sys
from sqlalchemy import inspect, text

# Consenti import app.* eseguendo dalla root del progetto
sys.path.insert(0, ".")
from app.database import engine  # noqa: E402


COLUMNS = [
    ("billable_hours_mode", "VARCHAR(16) NOT NULL DEFAULT 'max'"),
    ("billable_hours_resource_id", "INTEGER NULL REFERENCES resources(id)"),
    ("billable_hours_manual", "FLOAT NULL"),
]


def migrate() -> None:
    insp = inspect(engine)
    if "bookings" not in insp.get_table_names():
        print("[migrate] tabella 'bookings' assente — niente da fare.")
        return
    existing = {c["name"] for c in insp.get_columns("bookings")}
    added = 0
    with engine.begin() as conn:
        for col, ddl in COLUMNS:
            if col not in existing:
                print(f"[migrate] ADD COLUMN bookings.{col}")
                conn.execute(text(f"ALTER TABLE bookings ADD COLUMN {col} {ddl}"))
                added += 1
            else:
                print(f"[migrate] bookings.{col} già presente — skip")
    print(f"[migrate] completato ({added} colonne aggiunte).")


if __name__ == "__main__":
    migrate()
```

- [ ] **Step 4: Esegui la migrazione sul DB dev e verifica idempotenza**

Run: `./.venv/Scripts/python.exe scripts/migrate_billable_hours_mode.py`
Expected: prima esecuzione stampa 3 `ADD COLUMN`; seconda esecuzione stampa 3 `già presente — skip` e `0 colonne aggiunte`.

- [ ] **Step 5: Commit**

```bash
git add app/models/models.py app/main.py scripts/migrate_billable_hours_mode.py
git commit -m "feat(planning): colonne billable_hours_mode su Booking + migrazione"
```

---

## Task 2: `compute_billable_hours` (funzione pura) + refactor wrapper

**Files:**
- Modify: `app/services/cost_line_sync.py:174-224` (`_booking_billable_hours`)
- Test: `tests/test_billable_hours_mode.py`

- [ ] **Step 1: Scrivi i test della funzione pura (falliscono)**

Create `tests/test_billable_hours_mode.py`:

```python
"""Policy ore fatturabili per-booking (v3.5.0-alpha.172.179).

`compute_billable_hours` è la single source of truth: la usa sia il cost report
(via _booking_billable_hours) sia l'endpoint preview. Le opzioni impattano SOLO
le ore-cliente; il costo interno (non testato qui) somma sempre tutti.
"""
from app.services import cost_line_sync as cls

HUM = "person_internal"
FRE = "person_freelance"
ROOM = "studio"


def test_single_human_default_max():
    items = [(1, HUM, 8.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0


def test_two_humans_max():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0


def test_two_humans_sum():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "sum") == 14.0


def test_two_humans_specific():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "specific", specific_rid=2) == 6.0


def test_specific_resource_absent_returns_zero():
    items = [(1, HUM, 8.0)]
    assert cls.compute_billable_hours(items, "specific", specific_rid=99) == 0.0


def test_manual_overrides_everything():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "manual", manual=5.0) == 5.0


def test_manual_none_is_zero():
    items = [(1, HUM, 8.0)]
    assert cls.compute_billable_hours(items, "manual", manual=None) == 0.0


def test_human_plus_room_ignores_room():
    # Carlo 8h + Sala 8h → 8h (override umana, sala è costo interno)
    items = [(1, HUM, 8.0), (10, ROOM, 8.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0
    assert cls.compute_billable_hours(items, "sum") == 8.0  # 1 sola umana


def test_smart_split_same_human_aggregated_before_max():
    # Carlo AM 4h + Carlo PM 4h (stesso resource_id) → 8h, non 4h
    items = [(1, HUM, 4.0), (1, HUM, 4.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0
    assert cls.compute_billable_hours(items, "sum") == 8.0


def test_only_rooms_max_mode_ignored():
    # Nessuna umana → max tra non-umane, mode irrilevante
    items = [(10, ROOM, 8.0), (11, ROOM, 4.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0
    assert cls.compute_billable_hours(items, "sum") == 8.0


def test_empty_items_zero():
    assert cls.compute_billable_hours([], "max") == 0.0


def test_mixed_freelance_and_internal_sum():
    items = [(1, HUM, 8.0), (2, FRE, 6.0)]
    assert cls.compute_billable_hours(items, "sum") == 14.0
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_billable_hours_mode.py -v`
Expected: FAIL con `AttributeError: module 'app.services.cost_line_sync' has no attribute 'compute_billable_hours'`

- [ ] **Step 3: Implementa `compute_billable_hours` e refactor del wrapper**

In `app/services/cost_line_sync.py`, sostituisci INTEGRALMENTE la funzione `_booking_billable_hours` (righe ~174-224) con la coppia seguente. La docstring di esempio è preservata; la regola `max` con default è identica al comportamento pre-α.172.179.

```python
def compute_billable_hours(items, mode="max", specific_rid=None, manual=None) -> float:
    """Single source of truth per le ore FATTURABILI al cliente di un booking.

    `items` = list di tuple (resource_id:int, rtype:str, hours:float).
    Aggrega le ore per resource_id PRIMA di applicare la modalità (smart_split:
    stessa risorsa con 2 slot AM+PM → somma 8h).

    Regole:
      - mode='manual' → ritorna `manual` (ore digitate dal producer), >=0.
      - se NON ci sono risorse umane → max(ore tra le non-umane), `mode` ignorato
        (comportamento storico per booking solo-sala/equipment).
      - mode='specific' → ore aggregate della risorsa `specific_rid` (0 se assente).
      - mode='sum'      → somma delle ore di tutte le risorse umane.
      - mode='max' (default) → max delle ore tra le risorse umane.

    Le opzioni NON toccano il costo interno (che somma sempre tutti gli assignment).
    """
    mode = (mode or "max").strip().lower()
    if mode == "manual":
        try:
            return max(0.0, float(manual or 0.0))
        except (TypeError, ValueError):
            return 0.0
    from collections import defaultdict
    human_by_res: dict = defaultdict(float)
    nonhuman_by_res: dict = defaultdict(float)
    for rid, rtype, hours in items:
        if hours is None or hours <= 0:
            continue
        if rtype in HUMAN_RESOURCE_TYPES:
            human_by_res[rid] += hours
        else:
            nonhuman_by_res[rid] += hours
    if not human_by_res:
        return max(nonhuman_by_res.values()) if nonhuman_by_res else 0.0
    if mode == "specific":
        if specific_rid in human_by_res:
            return human_by_res[specific_rid]
        if specific_rid in nonhuman_by_res:
            return nonhuman_by_res[specific_rid]
        return 0.0
    if mode == "sum":
        return sum(human_by_res.values())
    # default: max
    return max(human_by_res.values())


def _booking_billable_hours(b) -> float:
    """v3.5.0-alpha.171 (CR-2) — Ore "fatturabili al cliente" del booking.
    v3.5.0-alpha.172.97 — fix smart_split: somma per risorsa, poi max tra risorse.
    v3.5.0-alpha.172.179 — modalità configurabile per-booking via
    `billable_hours_mode` (max|sum|specific|manual). Thin wrapper su
    `compute_billable_hours` (single source of truth).

    Default mode='max' = comportamento storico (override umana, max tra persone).
    Costo interno invariato: vedi loop assignment×rate in recompute_cost_line_actual.

    Esempi:
    - Carlo 8h + Sala A 8h (max) → 8h (max umana)
    - Carlo AM 4h + Carlo PM 4h (smart_split, max) → 8h (sum stessa risorsa)
    - Carlo 8h + Mario 6h (sum) → 14h | (max) → 8h | (specific Mario) → 6h
    - Sala A 8h + Sala B 4h (nessuna umana) → 8h
    - mode=manual, manual=5 → 5h
    - Booking senza assignments → shell-duration (back-compat)
    """
    if not getattr(b, "assignments", None):
        if not b.start_datetime or not b.end_datetime:
            return 0.0
        return max(0.0, (b.end_datetime - b.start_datetime).total_seconds() / 3600.0)
    items = []
    for a in b.assignments:
        h = _assignment_hours(a)
        if h <= 0:
            continue
        res = getattr(a, "resource", None)
        if res is not None:
            rtype = res.type.value if hasattr(res.type, "value") else str(res.type)
        else:
            rtype = ""
        items.append((a.resource_id or 0, rtype, h))
    mode = getattr(b, "billable_hours_mode", None) or "max"
    return compute_billable_hours(
        items,
        mode,
        getattr(b, "billable_hours_resource_id", None),
        getattr(b, "billable_hours_manual", None),
    )
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_billable_hours_mode.py -v`
Expected: PASS (tutti i test della funzione pura).

- [ ] **Step 5: Esegui la suite cost_line per regressione**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_unit_turno.py -v`
Expected: PASS (la mappa ore/unit non è toccata).

- [ ] **Step 6: Commit**

```bash
git add app/services/cost_line_sync.py tests/test_billable_hours_mode.py
git commit -m "feat(cost): compute_billable_hours single-source + modalità per-booking"
```

---

## Task 3: Endpoint preview server-side

**Files:**
- Modify: `app/routers/planning.py` (aggiungi endpoint dopo `create_booking`, ~riga 1509)
- Test: `tests/test_billable_hours_mode.py` (estendi con test endpoint)

- [ ] **Step 1: Scrivi il test dell'endpoint (fallisce)**

Aggiungi in fondo a `tests/test_billable_hours_mode.py`. Usa le fixture esistenti in `tests/conftest.py` (segui il pattern di `tests/test_mobile.py` per autenticazione + creazione risorse: leggi quel file e riusa gli stessi helper/fixture). Il test crea 2 risorse umane e verifica le ore per ogni modalità.

```python
import json
import pytest


@pytest.fixture
def two_humans(db_session):
    """Crea 2 risorse umane interne nel tenant di default. Ritorna (id1, id2)."""
    from app.models import Resource, ResourceType
    r1 = Resource(tenant_id=1, name="Carlo", type=ResourceType.person_internal, is_active=True)
    r2 = Resource(tenant_id=1, name="Mario", type=ResourceType.person_internal, is_active=True)
    db_session.add_all([r1, r2])
    db_session.commit()
    db_session.refresh(r1); db_session.refresh(r2)
    return r1.id, r2.id


def _assignments_json(rid1, rid2):
    return json.dumps([
        {"resource_id": rid1, "start_datetime": "2026-06-10T09:00:00", "end_datetime": "2026-06-10T17:00:00"},  # 8h
        {"resource_id": rid2, "start_datetime": "2026-06-10T09:00:00", "end_datetime": "2026-06-10T15:00:00"},  # 6h
    ])


def test_preview_billable_max(client_admin, two_humans):
    r1, r2 = two_humans
    resp = client_admin.post("/planning/api/bookings/preview-billable", data={
        "assignments": _assignments_json(r1, r2),
        "billable_hours_mode": "max",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["billable_hours"] == 8.0
    assert body["human_count"] == 2
    assert len(body["breakdown"]) == 2


def test_preview_billable_sum(client_admin, two_humans):
    r1, r2 = two_humans
    resp = client_admin.post("/planning/api/bookings/preview-billable", data={
        "assignments": _assignments_json(r1, r2),
        "billable_hours_mode": "sum",
    })
    assert resp.status_code == 200
    assert resp.json()["billable_hours"] == 14.0


def test_preview_billable_specific(client_admin, two_humans):
    r1, r2 = two_humans
    resp = client_admin.post("/planning/api/bookings/preview-billable", data={
        "assignments": _assignments_json(r1, r2),
        "billable_hours_mode": "specific",
        "billable_hours_resource_id": r2,
    })
    assert resp.status_code == 200
    assert resp.json()["billable_hours"] == 6.0


def test_preview_billable_manual(client_admin, two_humans):
    r1, r2 = two_humans
    resp = client_admin.post("/planning/api/bookings/preview-billable", data={
        "assignments": _assignments_json(r1, r2),
        "billable_hours_mode": "manual",
        "billable_hours_manual": 5.0,
    })
    assert resp.status_code == 200
    assert resp.json()["billable_hours"] == 5.0
```

> NOTA per l'implementatore: i nomi fixture `db_session` / `client_admin` sono indicativi. PRIMA leggi `tests/conftest.py` e `tests/test_mobile.py` e usa i nomi reali delle fixture del progetto (session DB + TestClient autenticato come admin). Se non esiste un client admin, crealo nel test seguendo il pattern di `test_mobile.py`.

- [ ] **Step 2: Esegui il test e verifica che fallisca**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_billable_hours_mode.py -k preview -v`
Expected: FAIL con 404 (endpoint inesistente).

- [ ] **Step 3: Implementa l'endpoint**

In `app/routers/planning.py`, subito dopo la fine di `create_booking` (prima del commento `# ── Booking request flow`, ~riga 1510), inserisci. Verifica che in cima al file siano importati `Resource` e `current_tenant_id` (lo sono già: usati altrove nel router); importa `cost_line_sync as cls` localmente.

```python
@router.post("/api/bookings/preview-billable")
async def preview_billable_hours(
    request: Request,
    assignments: str = Form(...),
    billable_hours_mode: str = Form("max"),
    billable_hours_resource_id: Optional[int] = Form(None),
    billable_hours_manual: Optional[float] = Form(None),
    db: Session = Depends(get_db),
):
    """Preview read-only delle ore FATTURABILI per un set di assignment.

    Usa la stessa `cost_line_sync.compute_billable_hours` del cost report →
    niente drift JS-vs-server. L'UI lo chiama (debounce) al cambio di
    durata/risorse/modalità per mostrare "Ore fatturabili: Xh".
    """
    from app.services import cost_line_sync as cls
    try:
        ass_list = _json.loads(assignments)
    except Exception:
        raise HTTPException(400, "assignments deve essere JSON valido (lista)")
    if not isinstance(ass_list, list):
        raise HTTPException(400, "assignments deve essere una lista")

    rid_set = {
        int(a["resource_id"]) for a in ass_list
        if isinstance(a, dict) and a.get("resource_id")
    }
    res_map = {}
    if rid_set:
        for r in db.query(Resource).filter(
            Resource.id.in_(rid_set),
            Resource.tenant_id == current_tenant_id(),
        ).all():
            res_map[r.id] = r

    items = []
    breakdown = []
    seen_human = set()
    for a in ass_list:
        if not isinstance(a, dict):
            continue
        rid = a.get("resource_id")
        s = a.get("start_datetime")
        e = a.get("end_datetime")
        if not rid or not s or not e:
            continue
        try:
            sd = datetime.fromisoformat(s) if isinstance(s, str) else s
            ed = datetime.fromisoformat(e) if isinstance(e, str) else e
        except Exception:
            continue
        h = max(0.0, (ed - sd).total_seconds() / 3600.0)
        r = res_map.get(int(rid))
        if r is not None:
            rtype = r.type.value if hasattr(r.type, "value") else str(r.type)
            name = r.name
        else:
            rtype, name = "", f"#{rid}"
        items.append((int(rid), rtype, h))
        breakdown.append({
            "resource_id": int(rid), "name": name,
            "rtype": rtype, "hours": round(h, 2),
        })
        if rtype in cls.HUMAN_RESOURCE_TYPES:
            seen_human.add(int(rid))

    billable = cls.compute_billable_hours(
        items, billable_hours_mode,
        billable_hours_resource_id, billable_hours_manual,
    )
    return {
        "billable_hours": round(billable, 2),
        "human_count": len(seen_human),
        "breakdown": breakdown,
    }
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_billable_hours_mode.py -v`
Expected: PASS (funzione pura + 4 test endpoint).

- [ ] **Step 5: Commit**

```bash
git add app/routers/planning.py tests/test_billable_hours_mode.py
git commit -m "feat(planning): endpoint preview-billable (single-source ore fatturabili)"
```

---

## Task 4: Wiring campi nei create/update booking + recompute su cambio mode

**Files:**
- Modify: `app/routers/planning.py:1267-1280` (Form params create_booking)
- Modify: `app/routers/planning.py:1410-1417` e `1463-1471` (costruttori `Booking(...)`)
- Modify: `app/routers/planning.py:1613-1626` (Form params update_booking)
- Modify: `app/routers/planning.py:1745-1762` (set campi in update + trigger recompute)
- Test: `tests/test_billable_hours_recompute.py`

- [ ] **Step 1: Scrivi il test d'integrazione recompute (fallisce)**

Create `tests/test_billable_hours_recompute.py`. Riusa le fixture di `conftest.py`/`test_mobile.py` (leggile prima). Lo scenario: 1 JCL time-based (unit `hr`), 1 booking done con 2 umane (8h + 6h), poi cambio mode e ricalcolo.

```python
"""Integrazione: billable_hours_mode su Booking → quantity_actual nel cost report.
Costo interno (total_cost_accrued) invariato dal mode.
"""
import pytest
from datetime import datetime

from app.services.cost_line_sync import recompute_cost_line_actual


@pytest.fixture
def done_booking_two_humans(db_session):
    """JCL unit=hr + booking done con Carlo 8h e Mario 6h. Ritorna (jcl, booking)."""
    from app.models import (
        Resource, ResourceType, Job, JobCostLine, Booking, BookingAssignment,
        BookingStatus, BookingExecutionStatus, BookingState,
    )
    # NB: adatta la creazione di Job/JCL al minimo richiesto dal modello reale
    # (leggi i campi obbligatori in models.py). Lo scopo è avere una JCL time-based.
    r1 = Resource(tenant_id=1, name="Carlo", type=ResourceType.person_internal, is_active=True)
    r2 = Resource(tenant_id=1, name="Mario", type=ResourceType.person_internal, is_active=True)
    db_session.add_all([r1, r2]); db_session.flush()
    job = Job(tenant_id=1, code="J-TEST", title="Test")
    db_session.add(job); db_session.flush()
    jcl = JobCostLine(tenant_id=1, job_id=job.id, description="Color", unit="hr", unit_price=100.0)
    db_session.add(jcl); db_session.flush()
    b = Booking(
        tenant_id=1, job_id=job.id, job_cost_line_id=jcl.id,
        start_datetime=datetime(2026, 6, 10, 9, 0), end_datetime=datetime(2026, 6, 10, 17, 0),
        status=BookingStatus.confirmed, state=BookingState.done,
        execution_status=BookingExecutionStatus.done,
        billable_hours_mode="max",
    )
    db_session.add(b); db_session.flush()
    db_session.add_all([
        BookingAssignment(booking_id=b.id, resource_id=r1.id,
                          start_datetime=datetime(2026, 6, 10, 9, 0), end_datetime=datetime(2026, 6, 10, 17, 0)),
        BookingAssignment(booking_id=b.id, resource_id=r2.id,
                          start_datetime=datetime(2026, 6, 10, 9, 0), end_datetime=datetime(2026, 6, 10, 15, 0)),
    ])
    db_session.commit()
    db_session.refresh(jcl); db_session.refresh(b)
    return jcl, b


def test_mode_max_quantity_is_8(db_session, done_booking_two_humans):
    jcl, b = done_booking_two_humans
    recompute_cost_line_actual(db_session, jcl)
    assert jcl.quantity_actual == 8.0  # max(8,6)


def test_mode_sum_quantity_is_14(db_session, done_booking_two_humans):
    jcl, b = done_booking_two_humans
    b.billable_hours_mode = "sum"
    db_session.commit()
    recompute_cost_line_actual(db_session, jcl)
    assert jcl.quantity_actual == 14.0  # 8+6


def test_internal_cost_invariant_across_modes(db_session, done_booking_two_humans):
    """Il costo interno NON dipende dal mode: somma sempre tutte le ore×rate.
    Qui le risorse non hanno rate → cost 0 in entrambi i casi; il punto è che
    cambiando mode il valore di total_cost_accrued resta identico."""
    jcl, b = done_booking_two_humans
    recompute_cost_line_actual(db_session, jcl)
    cost_max = jcl.total_cost_accrued
    b.billable_hours_mode = "sum"
    db_session.commit()
    recompute_cost_line_actual(db_session, jcl)
    assert jcl.total_cost_accrued == cost_max
```

> NOTA: adatta i campi obbligatori di `Job`/`JobCostLine` leggendo `app/models/models.py`. Se la creazione diretta è complessa, riusa eventuali factory già presenti in `tests/`.

- [ ] **Step 2: Esegui il test e verifica che fallisca**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_billable_hours_recompute.py -v`
Expected: FAIL su `test_mode_sum_quantity_is_14` (oggi è sempre max → 8.0), perché update_booking non scrive ancora il mode (ma qui lo settiamo a mano, quindi il test sum dipende solo da Task 2 — DEVE già passare se Task 2 è completo). Se `test_mode_max` e `test_mode_sum` passano già, prosegui: questo task serve a esporre il mode via API.

- [ ] **Step 3: Aggiungi i 3 Form param a `create_booking`**

In `app/routers/planning.py`, nella firma di `create_booking` (dopo `force_single_type`, riga ~1279) aggiungi:

```python
    force_single_type: bool = Form(False),  # Bundle H1 v3.5.0-alpha.172.88 — bypass anomaly check
    billable_hours_mode: str = Form("max"),  # α.172.179 max|sum|specific|manual
    billable_hours_resource_id: Optional[int] = Form(None),
    billable_hours_manual: Optional[float] = Form(None),
    db: Session = Depends(get_db),
```

- [ ] **Step 4: Passa i campi ai costruttori `Booking(...)`**

In `create_booking` ci sono DUE costruttori `Booking(...)`: quello ricorrente (~riga 1410) e quello semplice (~riga 1463). In ENTRAMBI, aggiungi i 3 kwargs dopo `state=...`:

```python
                state=recur_state,
                billable_hours_mode=billable_hours_mode,
                billable_hours_resource_id=billable_hours_resource_id,
                billable_hours_manual=billable_hours_manual,
            )
```

e per il costruttore semplice:

```python
        state=initial_state,
        billable_hours_mode=billable_hours_mode,
        billable_hours_resource_id=billable_hours_resource_id,
        billable_hours_manual=billable_hours_manual,
    )
```

- [ ] **Step 5: Aggiungi i 3 Form param a `update_booking` + set + recompute**

In `app/routers/planning.py`, firma di `update_booking` (dopo `force_single_type`, riga ~1624) aggiungi:

```python
    force_single_type: bool = Form(False),  # Bundle H1 v3.5.0-alpha.172.88
    billable_hours_mode: Optional[str] = Form(None),  # α.172.179
    billable_hours_resource_id: Optional[int] = Form(None),
    billable_hours_manual: Optional[float] = Form(None),
    force_slice_unlock: bool = Depends(_force_unlock_dep),  # α.66.3 + α.111.23 admin-gate
    db: Session = Depends(get_db),
```

Poi, nel blocco di set dei metadata (dopo `if priority is not None ...`, ~riga 1748), aggiungi e traccia se è cambiato il calcolo billable:

```python
    if priority is not None and str(priority).strip():
        b.priority = _parse_priority(priority)
    # α.172.179 — policy ore fatturabili. Traccia il cambiamento per forzare
    # il recompute anche senza modifica assignments/JCL (mode cambia quantity).
    _billable_changed = False
    if billable_hours_mode is not None and str(billable_hours_mode).strip():
        if b.billable_hours_mode != billable_hours_mode:
            _billable_changed = True
        b.billable_hours_mode = billable_hours_mode.strip().lower()
    if billable_hours_resource_id is not None:
        if b.billable_hours_resource_id != billable_hours_resource_id:
            _billable_changed = True
        b.billable_hours_resource_id = billable_hours_resource_id
    if billable_hours_manual is not None:
        if b.billable_hours_manual != billable_hours_manual:
            _billable_changed = True
        b.billable_hours_manual = billable_hours_manual
```

E nella condizione `_need_recompute` (riga ~1758) aggiungi `_billable_changed`:

```python
    _need_recompute = (
        b.execution_status == BookingExecutionStatus.done
        and (assignments is not None
             or (_old_jcl_id_for_resync != b.job_cost_line_id)
             or _billable_changed)
    )
```

- [ ] **Step 6: Esegui i test (recompute + preview + funzione pura)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_billable_hours_mode.py tests/test_billable_hours_recompute.py -v`
Expected: PASS tutti.

- [ ] **Step 7: Smoke import del router (no ReferenceError lato Python)**

Run: `./.venv/Scripts/python.exe -c "import app.main; print('import OK')"`
Expected: `import OK` (nessun errore di sintassi/import nel router modificato).

- [ ] **Step 8: Commit**

```bash
git add app/routers/planning.py tests/test_billable_hours_recompute.py
git commit -m "feat(planning): wiring billable_hours_mode in create/update + recompute su cambio"
```

---

## Task 5: UI desktop — blocco nel modal booking (planning.html)

**Files:**
- Modify: `app/templates/pages/planning.html` (modal di creazione/modifica booking + JS submit)

> PRIMA di scrivere: leggi in `app/templates/pages/planning.html` il modal del booking (cerca gli `id` dei campi risorsa/orari e la funzione JS che fa il POST a `/planning/api/bookings`). Aggancia il blocco nuovo a quel modal e aggiungi i campi alla FormData esistente. Riusa gli helper globali (`api`, `escapeHtml`, `toast`) — NON ridefinirli (memory: helper centralizzati).

- [ ] **Step 1: Aggiungi il markup del blocco billable nel modal**

Dentro il modal del booking, dopo la sezione delle risorse/orari, aggiungi un contenitore nascosto di default:

```html
<div id="bk-billable-block" style="display:none;margin-top:12px;padding:10px;border:1px solid var(--border);border-radius:8px;">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
    <strong>Ore fatturabili al cliente</strong>
    <span id="bk-billable-total" style="font-variant-numeric:tabular-nums;">—</span>
  </div>
  <div style="margin-top:8px;display:flex;flex-direction:column;gap:6px;">
    <label><input type="radio" name="bk-billable-mode" value="max" checked> Max (una principale, le altre assistono)</label>
    <label><input type="radio" name="bk-billable-mode" value="sum"> Somma (tutte in parallelo, fatturano tutte)</label>
    <label><input type="radio" name="bk-billable-mode" value="specific"> Solo una risorsa:
      <select id="bk-billable-res" disabled></select></label>
    <label><input type="radio" name="bk-billable-mode" value="manual"> Manuale:
      <input id="bk-billable-manual" type="number" min="0" step="0.5" disabled style="width:90px;"> h</label>
  </div>
</div>
```

- [ ] **Step 2: Aggiungi il JS: mostra blocco se ≥2 umane + preview live**

Nel `<script>` del modal (vicino alla logica che gestisce le risorse selezionate), aggiungi. `currentAssignments()` deve restituire l'array `[{resource_id,start_datetime,end_datetime}]` che il modal già costruisce per il submit — riusa quella funzione esistente; se ha altro nome, adatta. `RESOURCES` è la lista risorse già caricata dal modal (con `id`, `name`, `type`). Adatta i nomi reali.

```javascript
function bkHumanResourceIds(assignments) {
  var humanTypes = ['person_internal', 'person_freelance', 'person'];
  var ids = {};
  assignments.forEach(function (a) {
    var r = (RESOURCES || []).find(function (x) { return x.id === a.resource_id; });
    if (r && humanTypes.indexOf(r.type) !== -1) ids[r.id] = r.name;
  });
  return ids;
}

var _bkPreviewTimer = null;
async function bkRefreshBillable() {
  var assignments = currentAssignments();           // [{resource_id,start_datetime,end_datetime}]
  var humans = bkHumanResourceIds(assignments);
  var humanIds = Object.keys(humans);
  var block = document.getElementById('bk-billable-block');
  if (humanIds.length < 2) { block.style.display = 'none'; return; }
  block.style.display = '';
  // popola dropdown 'specific' con le sole umane
  var sel = document.getElementById('bk-billable-res');
  if (sel.options.length !== humanIds.length) {
    sel.innerHTML = '';
    humanIds.forEach(function (id) {
      var o = document.createElement('option'); o.value = id; o.textContent = humans[id]; sel.appendChild(o);
    });
  }
  var mode = (document.querySelector('input[name=bk-billable-mode]:checked') || {}).value || 'max';
  document.getElementById('bk-billable-res').disabled = (mode !== 'specific');
  document.getElementById('bk-billable-manual').disabled = (mode !== 'manual');
  // preview server-side (debounce)
  clearTimeout(_bkPreviewTimer);
  _bkPreviewTimer = setTimeout(async function () {
    var fd = new FormData();
    fd.append('assignments', JSON.stringify(assignments));
    fd.append('billable_hours_mode', mode);
    if (mode === 'specific') fd.append('billable_hours_resource_id', sel.value);
    if (mode === 'manual') fd.append('billable_hours_manual', document.getElementById('bk-billable-manual').value || '0');
    try {
      var r = await fetch('/planning/api/bookings/preview-billable', { method: 'POST', body: fd, credentials: 'same-origin' });
      var d = await r.json();
      document.getElementById('bk-billable-total').textContent = (d.billable_hours != null ? d.billable_hours + ' h' : '—');
    } catch (e) { document.getElementById('bk-billable-total').textContent = '—'; }
  }, 200);
}

// trigger: cambio risorse/orari/modalità
document.querySelectorAll('input[name=bk-billable-mode]').forEach(function (el) {
  el.addEventListener('change', bkRefreshBillable);
});
document.getElementById('bk-billable-res').addEventListener('change', bkRefreshBillable);
document.getElementById('bk-billable-manual').addEventListener('input', bkRefreshBillable);
```

E chiama `bkRefreshBillable()` ogni volta che il modal aggiorna le risorse/orari (aggancia alle stesse callback esistenti) e all'apertura del modal in modifica (precompilando i radio dal booking caricato).

- [ ] **Step 3: Aggiungi i campi alla FormData del submit**

Nella funzione che fa il POST/PUT del booking, prima del `fetch`, aggiungi (solo se il blocco è visibile = ≥2 umane):

```javascript
if (document.getElementById('bk-billable-block').style.display !== 'none') {
  var bmode = (document.querySelector('input[name=bk-billable-mode]:checked') || {}).value || 'max';
  fd.append('billable_hours_mode', bmode);
  if (bmode === 'specific') fd.append('billable_hours_resource_id', document.getElementById('bk-billable-res').value);
  if (bmode === 'manual') fd.append('billable_hours_manual', document.getElementById('bk-billable-manual').value || '0');
}
```

- [ ] **Step 4: Bump cache-buster se modifichi JS esterni**

Se hai toccato un file in `app/static/js/*.js`, NON serve bumpare a mano: il progetto usa `?v={{ app_version }}` (memory `feedback_cache_buster_static`). Se invece il JS è inline in `planning.html`, nessuna azione. Verifica che il JS sia inline nel template (lo è per il modal booking).

- [ ] **Step 5: Smoke browser desktop (obbligatorio — memory smoke_e2e_browser)**

Con il server attivo su :8000, via Playwright MCP: apri `/planning`, apri il modal "nuovo booking", aggiungi 2 risorse umane → verifica che appaia "Ore fatturabili" con valore, cambia in "Somma" → il totale aggiorna. Controlla la console: nessun `ReferenceError`.

Run (manuale/agente): naviga e verifica. Expected: blocco visibile con ≥2 umane, totale che cambia con la modalità, console pulita.

- [ ] **Step 6: Commit**

```bash
git add app/templates/pages/planning.html
git commit -m "feat(planning-ui): blocco ore fatturabili inline nel modal booking"
```

---

## Task 6: UI mobile — multi-risorsa + blocco billable (booking_new.html)

**Files:**
- Modify: `app/templates/mobile/booking_new.html`

- [ ] **Step 1: Sostituisci il single-select risorsa con multi-select**

In `app/templates/mobile/booking_new.html`, sostituisci il `m-form-group` della risorsa (righe ~24-27) con una lista a checkbox:

```html
    <div class="m-form-group">
      <label class="m-label">Risorse</label>
      <div id="bn-resources" class="m-checklist" style="display:flex;flex-direction:column;gap:6px;max-height:240px;overflow:auto;">
        <div style="opacity:.6;">— caricamento… —</div>
      </div>
    </div>
    <div class="m-form-group" id="bn-billable-block" style="display:none;">
      <label class="m-label">Ore fatturabili al cliente: <span id="bn-billable-total">—</span></label>
      <select class="m-select" id="bn-billable-mode">
        <option value="max">Max (una principale)</option>
        <option value="sum">Somma (tutte in parallelo)</option>
        <option value="specific">Solo una risorsa</option>
        <option value="manual">Manuale</option>
      </select>
      <select class="m-select" id="bn-billable-res" style="display:none;margin-top:6px;"></select>
      <input class="m-input" id="bn-billable-manual" type="number" min="0" step="0.5" placeholder="ore" style="display:none;margin-top:6px;">
    </div>
```

- [ ] **Step 2: Aggiorna il JS — carica risorse come checkbox**

Nel `<script>`, sostituisci la parte che riempiva `resEl` con il rendering della checklist. Mantieni `mapi`/`mClear`/`mToast`. Aggiungi una struttura per i tipi risorsa (serve per contare le umane):

```javascript
  var resBox = document.getElementById("bn-resources");
  var RES_CACHE = [];

  function selectedAssignments() {
    var date = dateEl.value;
    var st = document.getElementById("bn-start").value;
    var en = document.getElementById("bn-end").value;
    var out = [];
    resBox.querySelectorAll("input[type=checkbox]:checked").forEach(function (cb) {
      out.push({
        resource_id: parseInt(cb.value, 10),
        start_datetime: date + "T" + st + ":00",
        end_datetime: date + "T" + en + ":00",
      });
    });
    return out;
  }

  function humanSelected() {
    var humanTypes = ["person_internal", "person_freelance", "person"];
    var res = [];
    resBox.querySelectorAll("input[type=checkbox]:checked").forEach(function (cb) {
      var r = RES_CACHE.find(function (x) { return x.id === parseInt(cb.value, 10); });
      if (r && humanTypes.indexOf(r.type) !== -1) res.push(r);
    });
    return res;
  }
```

Nella funzione `load()`, sostituisci il blocco risorse:

```javascript
    try {
      var res = await mapi("GET", "/resources/api");
      RES_CACHE = (res || []).filter(function (r) { return r.is_active !== false; });
      resBox.innerHTML = "";
      RES_CACHE.forEach(function (r) {
        var row = document.createElement("label");
        row.style.cssText = "display:flex;align-items:center;gap:8px;";
        var cb = document.createElement("input");
        cb.type = "checkbox"; cb.value = String(r.id);
        cb.addEventListener("change", bnRefreshBillable);
        row.appendChild(cb);
        var span = document.createElement("span");
        span.textContent = r.name + (r.role ? " (" + r.role + ")" : "");
        row.appendChild(span);
        resBox.appendChild(row);
      });
    } catch (e) { resBox.innerHTML = "<div style='color:var(--danger)'>— errore risorse —</div>"; }
```

- [ ] **Step 3: Aggiungi la preview live mobile**

Aggiungi nel `<script>`:

```javascript
  var modeEl = document.getElementById("bn-billable-mode");
  var billBlock = document.getElementById("bn-billable-block");
  var billRes = document.getElementById("bn-billable-res");
  var billManual = document.getElementById("bn-billable-manual");
  var _bnTimer = null;

  async function bnRefreshBillable() {
    var humans = humanSelected();
    if (humans.length < 2) { billBlock.style.display = "none"; return; }
    billBlock.style.display = "";
    if (billRes.options.length !== humans.length) {
      billRes.innerHTML = "";
      humans.forEach(function (r) {
        var o = document.createElement("option"); o.value = String(r.id); o.textContent = r.name; billRes.appendChild(o);
      });
    }
    var mode = modeEl.value;
    billRes.style.display = (mode === "specific") ? "" : "none";
    billManual.style.display = (mode === "manual") ? "" : "none";
    clearTimeout(_bnTimer);
    _bnTimer = setTimeout(async function () {
      var fd = new FormData();
      fd.append("assignments", JSON.stringify(selectedAssignments()));
      fd.append("billable_hours_mode", mode);
      if (mode === "specific") fd.append("billable_hours_resource_id", billRes.value);
      if (mode === "manual") fd.append("billable_hours_manual", billManual.value || "0");
      try {
        var r = await fetch("/planning/api/bookings/preview-billable", { method: "POST", body: fd, credentials: "same-origin" });
        var d = await r.json();
        document.getElementById("bn-billable-total").textContent = (d.billable_hours != null ? d.billable_hours + " h" : "—");
      } catch (e) { document.getElementById("bn-billable-total").textContent = "—"; }
    }, 200);
  }
  modeEl.addEventListener("change", bnRefreshBillable);
  billRes.addEventListener("change", bnRefreshBillable);
  billManual.addEventListener("input", bnRefreshBillable);
  dateEl.addEventListener("change", bnRefreshBillable);
  document.getElementById("bn-start").addEventListener("change", bnRefreshBillable);
  document.getElementById("bn-end").addEventListener("change", bnRefreshBillable);
```

- [ ] **Step 4: Aggiorna `submit()` — multi-risorsa + campi billable**

Sostituisci la lettura `rid` e la costruzione `assignments` in `submit()` (righe ~109-131):

```javascript
    var kind = kindEl.value, date = dateEl.value;
    var st = document.getElementById("bn-start").value, en = document.getElementById("bn-end").value;
    var assignments = selectedAssignments();
    if (!assignments.length) return showErr("Seleziona almeno una risorsa.");
    if (!date || !st || !en) return showErr("Data, inizio e fine obbligatori.");
    if (en <= st) return showErr("La fine deve essere dopo l'inizio.");
    if (kind === "project" && !jobEl.value) return showErr("Seleziona un job per i booking di progetto.");
    if (kind === "project" && !jclEl.value) return showErr("Seleziona la lavorazione (JCL) del job.");

    var notes = document.getElementById("bn-notes").value.trim();
    function buildFd(force) {
      var fd = new FormData();
      fd.append("assignments", JSON.stringify(assignments));
      fd.append("kind", kind);
      fd.append("status", document.getElementById("bn-status").value);
      if (kind === "project") { fd.append("job_id", jobEl.value); fd.append("job_cost_line_id", jclEl.value); }
      if (notes) fd.append("notes", notes);
      if (force) fd.append("force_single_type", "true");
      // α.172.179 — billable mode (solo se ≥2 umane = blocco visibile)
      if (billBlock.style.display !== "none") {
        var m = modeEl.value;
        fd.append("billable_hours_mode", m);
        if (m === "specific") fd.append("billable_hours_resource_id", billRes.value);
        if (m === "manual") fd.append("billable_hours_manual", billManual.value || "0");
      }
      return fd;
    }
```

(Il resto di `submit()` — `post(force)`, gate `SINGLE_TYPE_WARNING`, redirect — resta invariato.)

- [ ] **Step 5: Smoke mobile (obbligatorio)**

Con server su :8000, via Playwright MCP con viewport mobile: apri `/m/booking-new` (verifica la route reale in `app/routers/` mobile), seleziona 2 risorse umane → compare "Ore fatturabili", cambia modalità → aggiorna. Crea il booking → verifica redirect a `/m/assegnazioni` e che il booking esista. Console senza `ReferenceError`.

- [ ] **Step 6: Esegui i test mobile esistenti (regressione)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mobile.py -v`
Expected: PASS (o adatta se un test asseriva il single-select; in tal caso aggiorna il test al nuovo markup).

- [ ] **Step 7: Commit**

```bash
git add app/templates/mobile/booking_new.html tests/test_mobile.py
git commit -m "feat(mobile): booking multi-risorsa + blocco ore fatturabili inline"
```

---

## Task 7: Regressione finale + chiusura versione

**Files:**
- Modify: `app/main.py:2132` (versione)
- Modify: `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: Esegui l'intera suite di test**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (nessuna regressione). Annota il numero di test passati.

- [ ] **Step 2: Verifica health + boot pulito su DB esistente**

Run: riavvia il server (`./.venv/Scripts/python.exe run.py`), poi `Invoke-WebRequest http://localhost:8000/health`.
Expected: 200, version aggiornata; nei log di boot le ALTER `billable_hours_*` o assenti (già migrato) o eseguite una volta, senza errori.

- [ ] **Step 3: Bump versione**

In `app/main.py:2132`, cambia `version="3.5.0-alpha.172.178"` → `version="3.5.0-alpha.172.179"`.

- [ ] **Step 4: Aggiorna CHANGELOG + STATO**

Aggiungi una voce in `CHANGELOG.md` (in cima) per `3.5.0-alpha.172.179`: booking multi-risorsa su mobile + policy ore fatturabili per-booking (max/sum/specific/manual, default max), endpoint preview, costo interno invariato. Aggiorna `docs/STATO.md`: versione corrente + sezione "fatto" + prossimo step (test browser Matteo).

- [ ] **Step 5: Commit + export ZIP (policy push)**

```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -m "chore: α.172.179 multi-risorsa mobile + policy ore fatturabili"
```

> Se Matteo chiede il push: genera prima l'export DB ZIP in `docs/` (memory `feedback_export_zip_at_push`) e poi pusha. Altrimenti fermati al commit locale.

---

## Self-Review (compilata dall'autore del piano)

**Spec coverage:**
- §1 Modello dati → Task 1 ✅
- §2 Calcolo single-source → Task 2 ✅
- §3 Endpoint preview → Task 3 ✅
- §4 UI desktop → Task 5 ✅
- §5 UI mobile multi-risorsa → Task 6 ✅
- §6 Migrazione + boot → Task 1 (script + auto-migrate) ✅
- §7 RBAC → coperto: create/update passano dai gate esistenti (`can_create_booking`, `_enforce_planning_scope`, slice-lock); nessun permesso nuovo (Task 4 non li altera) ✅
- Test (spec §Test) → Task 2 (funzione pura), Task 3 (preview), Task 4 (recompute + invariante costo interno), Task 6 (regressione mobile), Task 7 (suite intera) ✅
- D5 edit operatore silenzioso → nessun codice nuovo (comportamento esistente di recompute), confermato in §non-goal ✅
- D6 booking fatturato HARD-BLOCK → `_assert_no_blocking_slice` esistente in update, invariato ✅

**Placeholder scan:** nessun TBD/TODO con codice mancante. Le NOTE all'implementatore ("leggi conftest/test_mobile", "adatta nomi fixture/RESOURCES") sono dovute al fatto che i nomi reali di fixture e variabili JS vanno verificati nel codice — sono istruzioni esplicite di lettura, non placeholder di logica.

**Type consistency:** `billable_hours_mode` / `billable_hours_resource_id` / `billable_hours_manual` usati con gli stessi nomi in modello, migrazione, endpoint, create/update, UI desktop e mobile. `compute_billable_hours(items, mode, specific_rid, manual)` con la stessa firma in tutte le chiamate (wrapper + endpoint). Endpoint `/planning/api/bookings/preview-billable` identico in test, desktop, mobile.
