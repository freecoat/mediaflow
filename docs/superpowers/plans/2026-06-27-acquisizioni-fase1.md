# Acquisizioni Fase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pipeline trattative di acquisizione (lead→commessa) con log attività/comunicazioni, contatti multipli, mini-agenda, potenziale pesato per reparto, vista kanban+tabella, capability AI propose_*, e fix modifica stato progetto.

**Architecture:** Nuova entità `Acquisition` (la trattativa, può precedere un Progetto) con tag reparti M:N, entità `Contact` (contatti multipli per cliente) e `Activity` (log comunicazioni). Servizio `acquisition_service.py` per probabilità/pesato/summary/agenda/conversione. Router form-based tenant-scoped. Pagina `/acquisitions` ibrida kanban⇄tabella. Capability copilot `propose_*` come gancio per la Fase 2.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (`Mapped`/`mapped_column`) + Jinja2 + SQLite, vanilla JS, pytest. Niente nuove dipendenze.

## Global Constraints

- Python 3.11+ (priorità 3.14). Niente python-jose/passlib/WeasyPrint.
- Ogni query tenant-scoped: `CURRENT_TENANT = 1` in cima al router, filtro `tenant_id == CURRENT_TENANT` su ogni by-id query.
- Soft-delete (`is_active=False`), mai DELETE fisico.
- API form-based (`Form(...)`); frontend usa `FormData`.
- SQLAlchemy 2.0: `Mapped[type]` + `mapped_column`. Decimal/`Numeric` per valori monetari.
- i18n 5 lingue (`it/en/fr/de/es`) in `app/static/js/i18n.js` + `data-i18n` nei template, **stesso commit**.
- Ordini menu/colonne deterministici (clienti alfabetico `localeCompare`; reparti/stadi per `sort_order`/ordine enum).
- Migrazione manuale idempotente `scripts/migrate_acquisitions.py` + `_auto_migrate_columns()`/`create_tables()` al boot.
- Cache-buster automatico via `app_version` Jinja per static toccati (bump `app.main` version).
- Test runner: `.venv/Scripts/python.exe -m pytest`.
- Commit a fine versione: bump `app/main.py` version + CHANGELOG + STATO nello stesso giro.
- Stadi pipeline: `lead, qualified, quoting, negotiation, won, lost`.
- Probabilità default-da-stadio: lead 10, qualified 30, quoting 50, negotiation 70, won 100, lost 0.

---

### Task 1: Enums + modelli Acquisition / Contact / Activity

**Files:**
- Modify: `app/models/models.py` (aggiungi enum + 3 classi + tabella M:N + relationship su Client)
- Test: `tests/test_acquisition_model.py`

**Interfaces:**
- Produces: `AcquisitionStage` (enum: lead/qualified/quoting/negotiation/won/lost), `ActivityType` (email/call/meeting/note/task), `ActivityDirection` (inbound/outbound), `Acquisition`, `Contact`, `Activity`, tabella assoc `acquisition_departments`. `Acquisition` ha campi come da spec; relationship `departments` (M:N Department), `activities` (1:N), `client`, `project`, `owner`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_acquisition_model.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Department, User, UserRole,
    Acquisition, AcquisitionStage, Contact, Activity, ActivityType,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="Lucky Red")); s.flush()
    s.add(Department(id=1, tenant_id=1, name="DI", sort_order=1)); s.flush()
    s.add(User(id=1, tenant_id=1, email="c@t.local", full_name="Commerciale",
               hashed_password="x", role=UserRole.manager, is_active=True))
    s.commit()
    yield s
    s.close()


def test_acquisition_defaults_and_relationships(db):
    acq = Acquisition(tenant_id=1, title="Nuovo film", client_id=1,
                      stage=AcquisitionStage.lead, estimated_value=80000,
                      owner_user_id=1, created_by=1)
    dep = db.query(Department).get(1)
    acq.departments.append(dep)
    db.add(acq); db.commit(); db.refresh(acq)
    assert acq.is_active is True
    assert acq.stage == AcquisitionStage.lead
    assert [d.name for d in acq.departments] == ["DI"]


def test_contact_and_activity_link(db):
    c = Contact(tenant_id=1, client_id=1, name="Mario Rossi", email="m@x.it")
    db.add(c); db.commit(); db.refresh(c)
    assert c.is_primary is False and c.is_active is True
    a = Activity(tenant_id=1, client_id=1, contact_id=c.id,
                 type=ActivityType.email, subject="Primo contatto", created_by=1)
    db.add(a); db.commit(); db.refresh(a)
    assert a.type == ActivityType.email
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisition_model.py -v`
Expected: FAIL con `ImportError: cannot import name 'Acquisition'`.

- [ ] **Step 3: Write minimal implementation**

In `app/models/models.py`, vicino alle altre enum (dopo `ProjectStatus`, ~riga 174) aggiungi:

```python
class AcquisitionStage(str, enum.Enum):
    lead = "lead"; qualified = "qualified"; quoting = "quoting"
    negotiation = "negotiation"; won = "won"; lost = "lost"

class ActivityType(str, enum.Enum):
    email = "email"; call = "call"; meeting = "meeting"
    note = "note"; task = "task"

class ActivityDirection(str, enum.Enum):
    inbound = "inbound"; outbound = "outbound"
```

In fondo al file (dopo l'ultima classe modello, prima di eventuali blocchi non-classe), aggiungi la tabella M:N e le 3 classi. Usa `Table` per l'associazione (importa `Table`, `Column` se non già importati in cima — verifica gli import esistenti di SQLAlchemy):

```python
from sqlalchemy import Table, Column  # assicurati siano negli import in cima

acquisition_departments = Table(
    "acquisition_departments", Base.metadata,
    Column("acquisition_id", ForeignKey("acquisitions.id", ondelete="CASCADE"), primary_key=True),
    Column("department_id", ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True),
)


class Acquisition(Base):
    __tablename__ = "acquisitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    title: Mapped[str] = mapped_column(String(255))
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    prospect_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    stage: Mapped[AcquisitionStage] = mapped_column(SAEnum(AcquisitionStage), default=AcquisitionStage.lead, index=True)
    estimated_value: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    win_probability_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_close_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    owner_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    next_action: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    next_action_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    lost_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    client: Mapped[Optional["Client"]] = relationship(foreign_keys=[client_id])
    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])
    owner: Mapped[Optional["User"]] = relationship(foreign_keys=[owner_user_id])
    departments: Mapped[List["Department"]] = relationship(secondary=acquisition_departments)
    activities: Mapped[List["Activity"]] = relationship(
        back_populates="acquisition", cascade="all, delete-orphan",
        primaryjoin="Acquisition.id == Activity.acquisition_id")


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_extracted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class Activity(Base):
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    acquisition_id: Mapped[Optional[int]] = mapped_column(ForeignKey("acquisitions.id"), nullable=True, index=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"), nullable=True, index=True)
    type: Mapped[ActivityType] = mapped_column(SAEnum(ActivityType), default=ActivityType.note)
    direction: Mapped[Optional[ActivityDirection]] = mapped_column(SAEnum(ActivityDirection), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_action_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    ai_extracted: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    acquisition: Mapped[Optional["Acquisition"]] = relationship(
        back_populates="activities", foreign_keys=[acquisition_id])
```

Verifica che `Numeric`, `Date`, `Table`, `Column`, `SAEnum`, `ForeignKey`, `Float` siano negli import SQLAlchemy in cima al file (la maggior parte c'è già; aggiungi i mancanti).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisition_model.py -v`
Expected: PASS (2 test).

- [ ] **Step 5: Commit**

```bash
git add app/models/models.py tests/test_acquisition_model.py
git commit -m "feat(acquisizioni): modelli Acquisition/Contact/Activity + enum"
```

---

### Task 2: Migrazione + wiring boot

**Files:**
- Create: `scripts/migrate_acquisitions.py`
- Modify: `app/main.py` (le tabelle nuove sono create da `create_tables()`/`Base.metadata.create_all`; nessuna ALTER serve — verifica che `create_tables()` giri al boot)
- Test: `tests/test_migrate_acquisitions.py`

**Interfaces:**
- Consumes: modelli da Task 1.
- Produces: tabelle `acquisitions`, `contacts`, `activities`, `acquisition_departments` create idempotentemente.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrate_acquisitions.py
from sqlalchemy import create_engine, inspect
import scripts.migrate_acquisitions as mig


def test_migration_creates_tables(monkeypatch, tmp_path):
    db_file = tmp_path / "t.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    monkeypatch.setattr(mig, "engine", engine)
    mig.main()  # prima volta crea
    insp = inspect(engine)
    for t in ("acquisitions", "contacts", "activities", "acquisition_departments"):
        assert t in insp.get_table_names()
    mig.main()  # idempotente, non esplode
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_acquisitions.py -v`
Expected: FAIL con `ModuleNotFoundError: scripts.migrate_acquisitions`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/migrate_acquisitions.py
"""Migrazione non distruttiva — Acquisizioni Fase 1.
Crea le tabelle acquisitions/contacts/activities/acquisition_departments.
Idempotente (create_all salta le tabelle esistenti)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import engine
from app.models.models import (
    Acquisition, Contact, Activity, acquisition_departments,  # noqa: F401
)
from app.models.models import Base


def main():
    Base.metadata.create_all(engine, tables=[
        Acquisition.__table__, Contact.__table__,
        Activity.__table__, acquisition_departments,
    ])
    print("OK: tabelle acquisizioni create/verificate.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_acquisitions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_acquisitions.py tests/test_migrate_acquisitions.py
git commit -m "feat(acquisizioni): migrazione tabelle idempotente"
```

---

### Task 3: Permessi RBAC

**Files:**
- Modify: `app/services/rbac.py` (aggiungi keys `view_acquisitions`/`manage_acquisitions` in `PERMISSIONS`, assegna in `PRESET_PERMISSIONS` a `manager`/`producer`/`accounting`)
- Test: `tests/test_acquisitions_rbac.py`

**Interfaces:**
- Produces: permessi `view_acquisitions`, `manage_acquisitions`. `has_permission(manager_user, "manage_acquisitions")` → True.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_acquisitions_rbac.py
from app.services.rbac import ALL_PERMISSION_KEYS, PRESET_PERMISSIONS


def test_acquisition_permissions_registered():
    assert "view_acquisitions" in ALL_PERMISSION_KEYS
    assert "manage_acquisitions" in ALL_PERMISSION_KEYS


def test_acquisition_permissions_on_presets():
    for role in ("manager", "producer", "accounting"):
        assert "manage_acquisitions" in PRESET_PERMISSIONS[role]
        assert "view_acquisitions" in PRESET_PERMISSIONS[role]
    # operator/viewer NON gestiscono
    assert "manage_acquisitions" not in PRESET_PERMISSIONS.get("viewer", [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisitions_rbac.py -v`
Expected: FAIL (key assente).

- [ ] **Step 3: Write minimal implementation**

In `app/services/rbac.py`, dentro il dict `PERMISSIONS` (categoria adatta, es. vicino a `view_clients`/`view_projects`):

```python
        "view_acquisitions":   ["Visualizza acquisizioni/trattative"],
        "manage_acquisitions": ["Gestisce acquisizioni/trattative"],
```

In `PRESET_PERMISSIONS`, aggiungi a `manager`, `producer`, `accounting` (alle rispettive liste) le stringhe `"view_acquisitions", "manage_acquisitions"`. `admin` le eredita automaticamente (`list(ALL_PERMISSION_KEYS)`).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisitions_rbac.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/rbac.py tests/test_acquisitions_rbac.py
git commit -m "feat(acquisizioni): permessi view/manage_acquisitions su preset"
```

---

### Task 4: Servizio — probabilità + pesato

**Files:**
- Create: `app/services/acquisition_service.py`
- Test: `tests/test_acquisition_service_calc.py`

**Interfaces:**
- Consumes: `Acquisition`, `AcquisitionStage`.
- Produces: `DEFAULT_ACQ_PROBABILITY: dict[AcquisitionStage, float]`, `effective_probability(acq) -> float`, `weighted_value(acq) -> Decimal`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_acquisition_service_calc.py
from decimal import Decimal
from app.models.models import Acquisition, AcquisitionStage
from app.services.acquisition_service import (
    effective_probability, weighted_value, DEFAULT_ACQ_PROBABILITY,
)


def test_default_probability_by_stage():
    assert DEFAULT_ACQ_PROBABILITY[AcquisitionStage.lead] == 10
    assert DEFAULT_ACQ_PROBABILITY[AcquisitionStage.negotiation] == 70
    assert DEFAULT_ACQ_PROBABILITY[AcquisitionStage.won] == 100
    assert DEFAULT_ACQ_PROBABILITY[AcquisitionStage.lost] == 0


def test_effective_probability_override_wins():
    acq = Acquisition(stage=AcquisitionStage.lead, win_probability_pct=42)
    assert effective_probability(acq) == 42
    acq2 = Acquisition(stage=AcquisitionStage.quoting, win_probability_pct=None)
    assert effective_probability(acq2) == 50


def test_weighted_value():
    acq = Acquisition(stage=AcquisitionStage.negotiation,
                      estimated_value=Decimal("80000"), win_probability_pct=None)
    assert weighted_value(acq) == Decimal("56000.00")  # 80000 * 0.70
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisition_service_calc.py -v`
Expected: FAIL (modulo assente).

- [ ] **Step 3: Write minimal implementation**

```python
# app/services/acquisition_service.py
"""Servizio Acquisizioni — probabilità, potenziale pesato, summary, agenda,
conversione a progetto. Decimal per i valori monetari."""
from __future__ import annotations
from decimal import Decimal
from app.models.models import Acquisition, AcquisitionStage

DEFAULT_ACQ_PROBABILITY: dict[AcquisitionStage, float] = {
    AcquisitionStage.lead: 10,
    AcquisitionStage.qualified: 30,
    AcquisitionStage.quoting: 50,
    AcquisitionStage.negotiation: 70,
    AcquisitionStage.won: 100,
    AcquisitionStage.lost: 0,
}


def effective_probability(acq: Acquisition) -> float:
    if acq.win_probability_pct is not None:
        return float(acq.win_probability_pct)
    return float(DEFAULT_ACQ_PROBABILITY.get(acq.stage, 0))


def weighted_value(acq: Acquisition) -> Decimal:
    val = Decimal(str(acq.estimated_value or 0))
    prob = Decimal(str(effective_probability(acq))) / Decimal("100")
    return (val * prob).quantize(Decimal("0.01"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisition_service_calc.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/acquisition_service.py tests/test_acquisition_service_calc.py
git commit -m "feat(acquisizioni): service probabilità + potenziale pesato"
```

---

### Task 5: Servizio — summary pipeline + mini-agenda

**Files:**
- Modify: `app/services/acquisition_service.py`
- Test: `tests/test_acquisition_service_summary.py`

**Interfaces:**
- Consumes: `Acquisition`, `weighted_value`, `Department`, `Activity`.
- Produces: `pipeline_summary(db, tenant_id, *, department_id=None, owner_id=None, client_id=None) -> dict` con chiavi `by_stage` (dict stage→{count, weighted}), `by_department` (dict dept_name→weighted), `total_weighted` (Decimal), `open_count` (int). `upcoming_actions(db, tenant_id, *, owner_id=None, days=30) -> list[dict]` con `{kind, id, title, date, acquisition_id}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_acquisition_service_summary.py
import pytest
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Department, Acquisition, AcquisitionStage, Activity, ActivityType,
)
from app.services.acquisition_service import pipeline_summary, upcoming_actions


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="X")); s.flush()
    di = Department(id=1, tenant_id=1, name="DI", sort_order=1); s.add(di); s.flush()
    a1 = Acquisition(tenant_id=1, title="A", client_id=1, stage=AcquisitionStage.lead,
                     estimated_value=100000)  # weighted 10000
    a1.departments.append(di)
    a2 = Acquisition(tenant_id=1, title="B", client_id=1, stage=AcquisitionStage.won,
                     estimated_value=50000)   # weighted 50000, non "open"
    s.add_all([a1, a2]); s.commit()
    yield s, a1
    s.close()


def test_pipeline_summary(db):
    s, _ = db
    out = pipeline_summary(s, 1)
    assert out["open_count"] == 1  # won non è open
    assert out["total_weighted"] == Decimal("60000.00")
    assert out["by_department"]["DI"] == Decimal("10000.00")


def test_upcoming_actions(db):
    s, a1 = db
    a1.next_action = "Call regista"; a1.next_action_date = date.today() + timedelta(days=2)
    s.commit()
    out = upcoming_actions(s, 1, days=30)
    assert any(x["acquisition_id"] == a1.id for x in out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisition_service_summary.py -v`
Expected: FAIL (`pipeline_summary` assente).

- [ ] **Step 3: Write minimal implementation**

Aggiungi a `app/services/acquisition_service.py`:

```python
from datetime import date, timedelta
from sqlalchemy.orm import Session, selectinload

_OPEN_STAGES = {AcquisitionStage.lead, AcquisitionStage.qualified,
                AcquisitionStage.quoting, AcquisitionStage.negotiation}


def _filtered_query(db: Session, tenant_id, department_id, owner_id, client_id):
    from app.models.models import Acquisition as A, acquisition_departments
    q = (db.query(A).options(selectinload(A.departments))
         .filter(A.tenant_id == tenant_id, A.is_active == True))  # noqa: E712
    if owner_id:
        q = q.filter(A.owner_user_id == owner_id)
    if client_id:
        q = q.filter(A.client_id == client_id)
    if department_id:
        q = q.join(acquisition_departments).filter(
            acquisition_departments.c.department_id == department_id)
    return q


def pipeline_summary(db, tenant_id, *, department_id=None, owner_id=None, client_id=None):
    rows = _filtered_query(db, tenant_id, department_id, owner_id, client_id).all()
    by_stage, by_department = {}, {}
    total = Decimal("0.00"); open_count = 0
    for acq in rows:
        w = weighted_value(acq)
        total += w
        st = acq.stage.value
        agg = by_stage.setdefault(st, {"count": 0, "weighted": Decimal("0.00")})
        agg["count"] += 1; agg["weighted"] += w
        if acq.stage in _OPEN_STAGES:
            open_count += 1
        for d in acq.departments:
            by_department[d.name] = by_department.get(d.name, Decimal("0.00")) + w
    return {"by_stage": by_stage, "by_department": by_department,
            "total_weighted": total, "open_count": open_count}


def upcoming_actions(db, tenant_id, *, owner_id=None, days=30):
    from app.models.models import Acquisition as A, Activity
    horizon = date.today() + timedelta(days=days)
    out = []
    aq = (db.query(A).filter(A.tenant_id == tenant_id, A.is_active == True,  # noqa: E712
                             A.next_action_date.isnot(None),
                             A.next_action_date <= horizon))
    if owner_id:
        aq = aq.filter(A.owner_user_id == owner_id)
    for acq in aq.all():
        out.append({"kind": "acquisition", "id": acq.id, "acquisition_id": acq.id,
                    "title": acq.next_action or acq.title, "date": acq.next_action_date.isoformat()})
    act = (db.query(Activity).filter(Activity.tenant_id == tenant_id,
                                     Activity.is_active == True,  # noqa: E712
                                     Activity.next_action_date.isnot(None),
                                     Activity.next_action_date <= horizon))
    for a in act.all():
        out.append({"kind": "activity", "id": a.id, "acquisition_id": a.acquisition_id,
                    "title": a.subject, "date": a.next_action_date.isoformat()})
    out.sort(key=lambda x: x["date"])
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisition_service_summary.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/acquisition_service.py tests/test_acquisition_service_summary.py
git commit -m "feat(acquisizioni): pipeline_summary + upcoming_actions"
```

---

### Task 6: Servizio — cambio stadio + conversione a Progetto

**Files:**
- Modify: `app/services/acquisition_service.py`
- Test: `tests/test_acquisition_service_convert.py`

**Interfaces:**
- Consumes: `Acquisition`, `Project`, `ProjectStatus`, `Client`.
- Produces: `apply_stage_change(db, acq, new_stage: AcquisitionStage) -> None` (aggiorna stage; se win_probability_pct era None lo lascia None così segue il default; se project collegato, sincronizza Project.status via `STAGE_TO_PROJECT_STATUS`). `convert_to_project(db, acq, *, code: str, title: str | None = None) -> Project` (crea Project con status da stage, collega `acq.project_id`; se `acq.client_id` None ma `prospect_name`, crea Client minimale e collega). `STAGE_TO_PROJECT_STATUS: dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_acquisition_service_convert.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Project, ProjectStatus, Acquisition, AcquisitionStage,
)
from app.services.acquisition_service import apply_stage_change, convert_to_project


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="X")); s.commit()
    yield s
    s.close()


def test_convert_creates_project_and_links(db):
    acq = Acquisition(tenant_id=1, title="Film Y", client_id=1,
                      stage=AcquisitionStage.won, estimated_value=10000)
    db.add(acq); db.commit()
    p = convert_to_project(db, acq, code="PRJ-Y", title="Film Y")
    assert p.id and acq.project_id == p.id
    assert p.status == ProjectStatus.active  # won → active
    assert p.client_id == 1


def test_convert_prospect_creates_client(db):
    acq = Acquisition(tenant_id=1, title="Lead Z", client_id=None,
                      prospect_name="Nuova Casa SRL", stage=AcquisitionStage.qualified,
                      estimated_value=0)
    db.add(acq); db.commit()
    p = convert_to_project(db, acq, code="PRJ-Z")
    assert acq.client_id is not None
    cl = db.query(Client).get(acq.client_id)
    assert cl.name == "Nuova Casa SRL"
    assert p.status == ProjectStatus.quoting  # qualified→quoting per default mapper


def test_apply_stage_change_syncs_project(db):
    p = Project(tenant_id=1, code="P1", title="P1", client_id=1, status=ProjectStatus.prospect)
    db.add(p); db.commit()
    acq = Acquisition(tenant_id=1, title="A", client_id=1, project_id=p.id,
                      stage=AcquisitionStage.lead, estimated_value=0)
    db.add(acq); db.commit()
    apply_stage_change(db, acq, AcquisitionStage.won)
    assert acq.stage == AcquisitionStage.won
    assert db.query(Project).get(p.id).status == ProjectStatus.active
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisition_service_convert.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Aggiungi a `app/services/acquisition_service.py`:

```python
from app.models.models import ProjectStatus

STAGE_TO_PROJECT_STATUS = {
    AcquisitionStage.lead: ProjectStatus.prospect,
    AcquisitionStage.qualified: ProjectStatus.quoting,
    AcquisitionStage.quoting: ProjectStatus.quoting,
    AcquisitionStage.negotiation: ProjectStatus.quoting,
    AcquisitionStage.won: ProjectStatus.active,
    AcquisitionStage.lost: ProjectStatus.archived,
}


def apply_stage_change(db, acq, new_stage):
    acq.stage = new_stage
    if acq.project_id:
        from app.models.models import Project
        p = db.query(Project).filter(Project.id == acq.project_id,
                                     Project.tenant_id == acq.tenant_id).first()
        if p:
            p.status = STAGE_TO_PROJECT_STATUS.get(new_stage, p.status)
    db.commit()


def convert_to_project(db, acq, *, code, title=None):
    from app.models.models import Project, Client
    if acq.client_id is None:
        cl = Client(tenant_id=acq.tenant_id, name=(acq.prospect_name or acq.title))
        db.add(cl); db.flush()
        acq.client_id = cl.id
    if acq.project_id:
        return db.query(Project).filter(Project.id == acq.project_id).first()
    p = Project(tenant_id=acq.tenant_id, code=code, title=title or acq.title,
                client_id=acq.client_id,
                status=STAGE_TO_PROJECT_STATUS.get(acq.stage, ProjectStatus.prospect))
    db.add(p); db.flush()
    acq.project_id = p.id
    db.commit()
    return p
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisition_service_convert.py -v`
Expected: PASS (3 test).

- [ ] **Step 5: Commit**

```bash
git add app/services/acquisition_service.py tests/test_acquisition_service_convert.py
git commit -m "feat(acquisizioni): apply_stage_change + convert_to_project"
```

---

### Task 7: Router acquisitions — CRUD + summary + agenda

**Files:**
- Create: `app/routers/acquisitions.py`
- Modify: `app/main.py` (import + `app.include_router(acquisitions.router)`)
- Test: `tests/test_acquisitions_api.py`

**Interfaces:**
- Consumes: modelli + `acquisition_service` (`pipeline_summary`, `upcoming_actions`, `weighted_value`, `effective_probability`).
- Produces: endpoint GET `/acquisitions/api/list`, `/acquisitions/api/summary`, `/acquisitions/api/agenda`, GET `/acquisitions/api/{id}`, POST `/acquisitions/api`, PUT `/acquisitions/api/{id}`, DELETE `/acquisitions/api/{id}`. Serializer `_acq_dict(acq)` con `weighted_value`/`effective_probability`/`departments` (lista {id,name}).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_acquisitions_api.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole, Client, Department
from app.services.auth import create_access_token


@pytest.fixture
def client():
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    role = Role(tenant_id=1, code="manager", name="Mgr",
                permissions=["view_acquisitions", "manage_acquisitions"],
                is_system=True, is_active=True)
    s.add(role); s.flush()
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.manager, role_id=role.id, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Lucky")); s.flush()
    s.add(Department(id=1, tenant_id=1, name="DI", sort_order=1)); s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "a@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_create_list_get_acquisition(client):
    c, s = client
    r = c.post("/acquisitions/api", data={
        "title": "Film X", "client_id": "1", "stage": "lead",
        "estimated_value": "80000", "department_ids": "1"})
    assert r.status_code in (200, 201), r.text
    aid = r.json()["id"]
    lst = c.get("/acquisitions/api/list").json()
    assert any(a["id"] == aid for a in lst["items"])
    det = c.get(f"/acquisitions/api/{aid}").json()
    assert det["title"] == "Film X"
    assert det["weighted_value"] == "8000.00"  # 80000*10%
    assert det["departments"][0]["name"] == "DI"


def test_summary_and_agenda(client):
    c, _ = client
    c.post("/acquisitions/api", data={"title": "A", "client_id": "1",
           "stage": "negotiation", "estimated_value": "100000"})
    summ = c.get("/acquisitions/api/summary").json()
    assert summ["open_count"] == 1
    assert summ["total_weighted"] == "70000.00"
    ag = c.get("/acquisitions/api/agenda").json()
    assert "items" in ag


def test_delete_soft(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "Z", "client_id": "1",
                 "stage": "lead", "estimated_value": "0"}).json()["id"]
    assert c.delete(f"/acquisitions/api/{aid}").status_code == 200
    lst = c.get("/acquisitions/api/list").json()
    assert all(a["id"] != aid for a in lst["items"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisitions_api.py -v`
Expected: FAIL (404 / router assente).

- [ ] **Step 3: Write minimal implementation**

Crea `app/routers/acquisitions.py` seguendo il pattern di `app/routers/departments.py` (CRUD pulito). Punti chiave:

```python
from __future__ import annotations
from typing import Optional
from decimal import Decimal
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, selectinload
from app.database import get_db
from app.context import current_tenant_id
from app.models.models import (
    Acquisition, AcquisitionStage, Department, Client, Project, Quote,
)
from app.services.rbac import requires_permission
from app.services.acquisition_service import (
    weighted_value, effective_probability, pipeline_summary, upcoming_actions,
)

router = APIRouter(tags=["acquisitions"])
RequireView = Depends(requires_permission("view_acquisitions"))
RequireManage = Depends(requires_permission("manage_acquisitions"))


def _acq_dict(acq: Acquisition) -> dict:
    return {
        "id": acq.id, "title": acq.title,
        "client_id": acq.client_id,
        "client_name": acq.client.name if acq.client else acq.prospect_name,
        "prospect_name": acq.prospect_name,
        "project_id": acq.project_id,
        "stage": acq.stage.value,
        "estimated_value": str(Decimal(str(acq.estimated_value or 0)).quantize(Decimal("0.01"))),
        "win_probability_pct": acq.win_probability_pct,
        "effective_probability": effective_probability(acq),
        "weighted_value": str(weighted_value(acq)),
        "expected_close_date": acq.expected_close_date.isoformat() if acq.expected_close_date else None,
        "owner_user_id": acq.owner_user_id,
        "next_action": acq.next_action,
        "next_action_date": acq.next_action_date.isoformat() if acq.next_action_date else None,
        "source": acq.source, "lost_reason": acq.lost_reason,
        "departments": [{"id": d.id, "name": d.name} for d in acq.departments],
    }


def _set_departments(db, acq, dept_ids_csv):
    acq.departments.clear()
    for x in (dept_ids_csv or "").split(","):
        x = x.strip()
        if x.isdigit():
            d = db.query(Department).filter(Department.id == int(x),
                                            Department.tenant_id == current_tenant_id()).first()
            if d:
                acq.departments.append(d)


@router.get("/acquisitions/api/list", dependencies=[RequireView])
async def list_acquisitions(stage: Optional[str] = None, department_id: Optional[int] = None,
                            owner_id: Optional[int] = None, client_id: Optional[int] = None,
                            state: Optional[str] = None, db: Session = Depends(get_db)):
    q = (db.query(Acquisition).options(selectinload(Acquisition.departments),
                                       selectinload(Acquisition.client))
         .filter(Acquisition.tenant_id == current_tenant_id(),
                 Acquisition.is_active == True))  # noqa: E712
    if stage:
        q = q.filter(Acquisition.stage == AcquisitionStage(stage))
    if owner_id:
        q = q.filter(Acquisition.owner_user_id == owner_id)
    if client_id:
        q = q.filter(Acquisition.client_id == client_id)
    if state == "won":
        q = q.filter(Acquisition.stage == AcquisitionStage.won)
    elif state == "lost":
        q = q.filter(Acquisition.stage == AcquisitionStage.lost)
    elif state == "open":
        q = q.filter(Acquisition.stage.notin_([AcquisitionStage.won, AcquisitionStage.lost]))
    rows = q.order_by(Acquisition.updated_at.desc()).all()
    if department_id:
        rows = [a for a in rows if any(d.id == department_id for d in a.departments)]
    return {"items": [_acq_dict(a) for a in rows]}


@router.get("/acquisitions/api/summary", dependencies=[RequireView])
async def summary(department_id: Optional[int] = None, owner_id: Optional[int] = None,
                  client_id: Optional[int] = None, db: Session = Depends(get_db)):
    s = pipeline_summary(db, current_tenant_id(), department_id=department_id,
                         owner_id=owner_id, client_id=client_id)
    return {
        "by_stage": {k: {"count": v["count"], "weighted": str(v["weighted"])}
                     for k, v in s["by_stage"].items()},
        "by_department": {k: str(v) for k, v in s["by_department"].items()},
        "total_weighted": str(s["total_weighted"]),
        "open_count": s["open_count"],
    }


@router.get("/acquisitions/api/agenda", dependencies=[RequireView])
async def agenda(owner_id: Optional[int] = None, days: int = 30, db: Session = Depends(get_db)):
    return {"items": upcoming_actions(db, current_tenant_id(), owner_id=owner_id, days=days)}


@router.get("/acquisitions/api/{aid}", dependencies=[RequireView])
async def get_acquisition(aid: int, db: Session = Depends(get_db)):
    acq = db.query(Acquisition).filter(Acquisition.id == aid,
                                       Acquisition.tenant_id == current_tenant_id()).first()
    if not acq:
        raise HTTPException(404, "Acquisizione non trovata")
    d = _acq_dict(acq)
    # quotazioni collegate (del progetto o, se assente, del cliente)
    qq = db.query(Quote).filter(Quote.tenant_id == current_tenant_id())
    if acq.project_id:
        qq = qq.filter(Quote.project_id == acq.project_id)
    elif acq.client_id:
        qq = qq.filter(Quote.client_id == acq.client_id)
    else:
        qq = qq.filter(False)
    d["quotes"] = [{"id": q.id, "number": q.number, "status": q.status.value,
                    "total_with_vat": q.total_with_vat} for q in qq.all()]
    return d


def _parse_date(v):
    return date.fromisoformat(v) if v else None


@router.post("/acquisitions/api", dependencies=[RequireManage])
async def create_acquisition(request: Request, title: str = Form(...),
                             client_id: Optional[int] = Form(None),
                             prospect_name: Optional[str] = Form(None),
                             stage: str = Form("lead"),
                             estimated_value: float = Form(0),
                             win_probability_pct: Optional[float] = Form(None),
                             expected_close_date: Optional[str] = Form(None),
                             owner_user_id: Optional[int] = Form(None),
                             next_action: Optional[str] = Form(None),
                             next_action_date: Optional[str] = Form(None),
                             source: Optional[str] = Form(None),
                             department_ids: Optional[str] = Form(None),
                             db: Session = Depends(get_db)):
    from app.services.rbac import current_user_optional
    u = current_user_optional(request)
    acq = Acquisition(tenant_id=current_tenant_id(), title=title.strip(),
                      client_id=client_id, prospect_name=(prospect_name or None),
                      stage=AcquisitionStage(stage), estimated_value=estimated_value,
                      win_probability_pct=win_probability_pct,
                      expected_close_date=_parse_date(expected_close_date),
                      owner_user_id=owner_user_id or (u.id if u else None),
                      next_action=next_action, next_action_date=_parse_date(next_action_date),
                      source=source, created_by=(u.id if u else None))
    db.add(acq); db.flush()
    _set_departments(db, acq, department_ids)
    db.commit(); db.refresh(acq)
    return _acq_dict(acq)


@router.put("/acquisitions/api/{aid}", dependencies=[RequireManage])
async def update_acquisition(aid: int, title: Optional[str] = Form(None),
                             client_id: Optional[int] = Form(None),
                             prospect_name: Optional[str] = Form(None),
                             estimated_value: Optional[float] = Form(None),
                             win_probability_pct: Optional[float] = Form(None),
                             expected_close_date: Optional[str] = Form(None),
                             owner_user_id: Optional[int] = Form(None),
                             next_action: Optional[str] = Form(None),
                             next_action_date: Optional[str] = Form(None),
                             source: Optional[str] = Form(None),
                             lost_reason: Optional[str] = Form(None),
                             department_ids: Optional[str] = Form(None),
                             db: Session = Depends(get_db)):
    acq = db.query(Acquisition).filter(Acquisition.id == aid,
                                       Acquisition.tenant_id == current_tenant_id()).first()
    if not acq:
        raise HTTPException(404, "Acquisizione non trovata")
    if title is not None: acq.title = title.strip()
    if client_id is not None: acq.client_id = client_id or None
    if prospect_name is not None: acq.prospect_name = prospect_name or None
    if estimated_value is not None: acq.estimated_value = estimated_value
    if win_probability_pct is not None: acq.win_probability_pct = win_probability_pct
    if expected_close_date is not None: acq.expected_close_date = _parse_date(expected_close_date)
    if owner_user_id is not None: acq.owner_user_id = owner_user_id or None
    if next_action is not None: acq.next_action = next_action or None
    if next_action_date is not None: acq.next_action_date = _parse_date(next_action_date)
    if source is not None: acq.source = source or None
    if lost_reason is not None: acq.lost_reason = lost_reason or None
    if department_ids is not None: _set_departments(db, acq, department_ids)
    db.commit(); db.refresh(acq)
    return _acq_dict(acq)


@router.delete("/acquisitions/api/{aid}", dependencies=[RequireManage])
async def delete_acquisition(aid: int, db: Session = Depends(get_db)):
    acq = db.query(Acquisition).filter(Acquisition.id == aid,
                                       Acquisition.tenant_id == current_tenant_id()).first()
    if not acq:
        raise HTTPException(404, "Acquisizione non trovata")
    acq.is_active = False
    db.commit()
    return {"ok": True, "id": aid}
```

In `app/main.py`: aggiungi `acquisitions` all'import dei router e `app.include_router(acquisitions.router)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisitions_api.py -v`
Expected: PASS (3 test).

- [ ] **Step 5: Commit**

```bash
git add app/routers/acquisitions.py app/main.py tests/test_acquisitions_api.py
git commit -m "feat(acquisizioni): router CRUD + summary + agenda"
```

---

### Task 8: Router acquisitions — cambio stadio + conversione

**Files:**
- Modify: `app/routers/acquisitions.py`
- Test: `tests/test_acquisitions_stage_convert.py`

**Interfaces:**
- Consumes: `apply_stage_change`, `convert_to_project`.
- Produces: POST `/acquisitions/api/{id}/stage` (Form `stage`), POST `/acquisitions/api/{id}/convert` (Form `code`, opt `title`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_acquisitions_stage_convert.py
# Riusa la fixture `client` di test_acquisitions_api.py via import.
from tests.test_acquisitions_api import client  # noqa: F401


def test_stage_change(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "A", "client_id": "1",
                 "stage": "lead", "estimated_value": "1000"}).json()["id"]
    r = c.post(f"/acquisitions/api/{aid}/stage", data={"stage": "negotiation"})
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "negotiation"
    assert r.json()["effective_probability"] == 70


def test_convert_to_project(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "Film Q", "client_id": "1",
                 "stage": "won", "estimated_value": "0"}).json()["id"]
    r = c.post(f"/acquisitions/api/{aid}/convert", data={"code": "PRJ-Q", "title": "Film Q"})
    assert r.status_code == 200, r.text
    assert r.json()["project_id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisitions_stage_convert.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Aggiungi a `app/routers/acquisitions.py`:

```python
from app.services.acquisition_service import apply_stage_change, convert_to_project


@router.post("/acquisitions/api/{aid}/stage", dependencies=[RequireManage])
async def change_stage(aid: int, stage: str = Form(...), db: Session = Depends(get_db)):
    acq = db.query(Acquisition).filter(Acquisition.id == aid,
                                       Acquisition.tenant_id == current_tenant_id()).first()
    if not acq:
        raise HTTPException(404, "Acquisizione non trovata")
    apply_stage_change(db, acq, AcquisitionStage(stage))
    db.refresh(acq)
    return _acq_dict(acq)


@router.post("/acquisitions/api/{aid}/convert", dependencies=[RequireManage])
async def convert(aid: int, code: str = Form(...), title: Optional[str] = Form(None),
                  db: Session = Depends(get_db)):
    acq = db.query(Acquisition).filter(Acquisition.id == aid,
                                       Acquisition.tenant_id == current_tenant_id()).first()
    if not acq:
        raise HTTPException(404, "Acquisizione non trovata")
    p = convert_to_project(db, acq, code=code.strip(), title=title)
    db.refresh(acq)
    out = _acq_dict(acq)
    out["project_id"] = p.id
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisitions_stage_convert.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routers/acquisitions.py tests/test_acquisitions_stage_convert.py
git commit -m "feat(acquisizioni): endpoint cambio stadio + conversione"
```

---

### Task 9: Router activities — timeline CRUD

**Files:**
- Modify: `app/routers/acquisitions.py` (stessi prefissi consentiti) o nuovo `app/routers/activities.py`. **Scelta: aggiungi a `acquisitions.py`** (responsabilità affine, evita router extra).
- Test: `tests/test_activities_api.py`

**Interfaces:**
- Produces: GET `/acquisitions/api/{aid}/activities`, POST `/acquisitions/api/{aid}/activities` (Form: type, occurred_at?, subject, body?, contact_id?, direction?, next_action_date?), PUT `/activities/api/{id}`, DELETE `/activities/api/{id}`. Serializer `_activity_dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_activities_api.py
from tests.test_acquisitions_api import client  # noqa: F401


def test_add_list_activity(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "A", "client_id": "1",
                 "stage": "lead", "estimated_value": "0"}).json()["id"]
    r = c.post(f"/acquisitions/api/{aid}/activities", data={
        "type": "email", "subject": "Primo contatto", "body": "Ciao",
        "direction": "outbound"})
    assert r.status_code in (200, 201), r.text
    lst = c.get(f"/acquisitions/api/{aid}/activities").json()
    assert lst["items"][0]["subject"] == "Primo contatto"
    assert lst["items"][0]["type"] == "email"


def test_delete_activity(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "A", "client_id": "1",
                 "stage": "lead", "estimated_value": "0"}).json()["id"]
    act_id = c.post(f"/acquisitions/api/{aid}/activities",
                    data={"type": "note", "subject": "x"}).json()["id"]
    assert c.delete(f"/activities/api/{act_id}").status_code == 200
    assert c.get(f"/acquisitions/api/{aid}/activities").json()["items"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_activities_api.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Aggiungi a `app/routers/acquisitions.py` (import `Activity, ActivityType, ActivityDirection`, `datetime`, `now_utc`):

```python
from app.models.models import Activity, ActivityType, ActivityDirection
from app.services.clock import now_utc
from datetime import datetime


def _activity_dict(a: Activity) -> dict:
    return {"id": a.id, "acquisition_id": a.acquisition_id, "client_id": a.client_id,
            "project_id": a.project_id, "contact_id": a.contact_id,
            "type": a.type.value, "direction": a.direction.value if a.direction else None,
            "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
            "subject": a.subject, "body": a.body,
            "next_action_date": a.next_action_date.isoformat() if a.next_action_date else None,
            "ai_extracted": a.ai_extracted}


@router.get("/acquisitions/api/{aid}/activities", dependencies=[RequireView])
async def list_activities(aid: int, db: Session = Depends(get_db)):
    rows = (db.query(Activity).filter(Activity.tenant_id == current_tenant_id(),
            Activity.acquisition_id == aid, Activity.is_active == True)  # noqa: E712
            .order_by(Activity.occurred_at.desc(), Activity.id.desc()).all())
    return {"items": [_activity_dict(a) for a in rows]}


@router.post("/acquisitions/api/{aid}/activities", dependencies=[RequireManage])
async def add_activity(aid: int, request: Request, type: str = Form("note"),
                       subject: str = Form(...), body: Optional[str] = Form(None),
                       direction: Optional[str] = Form(None),
                       contact_id: Optional[int] = Form(None),
                       occurred_at: Optional[str] = Form(None),
                       next_action_date: Optional[str] = Form(None),
                       db: Session = Depends(get_db)):
    from app.services.rbac import current_user_optional
    acq = db.query(Acquisition).filter(Acquisition.id == aid,
                                       Acquisition.tenant_id == current_tenant_id()).first()
    if not acq:
        raise HTTPException(404, "Acquisizione non trovata")
    u = current_user_optional(request)
    a = Activity(tenant_id=current_tenant_id(), acquisition_id=aid,
                 client_id=acq.client_id, project_id=acq.project_id,
                 contact_id=contact_id, type=ActivityType(type),
                 direction=ActivityDirection(direction) if direction else None,
                 occurred_at=datetime.fromisoformat(occurred_at) if occurred_at else now_utc(),
                 subject=subject.strip(), body=body,
                 next_action_date=_parse_date(next_action_date),
                 created_by=(u.id if u else None))
    db.add(a); db.commit(); db.refresh(a)
    return _activity_dict(a)


@router.put("/activities/api/{act_id}", dependencies=[RequireManage])
async def update_activity(act_id: int, subject: Optional[str] = Form(None),
                          body: Optional[str] = Form(None),
                          next_action_date: Optional[str] = Form(None),
                          db: Session = Depends(get_db)):
    a = db.query(Activity).filter(Activity.id == act_id,
                                  Activity.tenant_id == current_tenant_id()).first()
    if not a:
        raise HTTPException(404, "Attività non trovata")
    if subject is not None: a.subject = subject.strip()
    if body is not None: a.body = body
    if next_action_date is not None: a.next_action_date = _parse_date(next_action_date)
    db.commit(); db.refresh(a)
    return _activity_dict(a)


@router.delete("/activities/api/{act_id}", dependencies=[RequireManage])
async def delete_activity(act_id: int, db: Session = Depends(get_db)):
    a = db.query(Activity).filter(Activity.id == act_id,
                                  Activity.tenant_id == current_tenant_id()).first()
    if not a:
        raise HTTPException(404, "Attività non trovata")
    a.is_active = False
    db.commit()
    return {"ok": True, "id": act_id}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_activities_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routers/acquisitions.py tests/test_activities_api.py
git commit -m "feat(acquisizioni): timeline attività CRUD"
```

---

### Task 10: Router contacts — CRUD + sync referente primario

**Files:**
- Create: `app/routers/contacts.py`
- Modify: `app/main.py` (include router)
- Test: `tests/test_contacts_api.py`

**Interfaces:**
- Produces: GET `/clients/api/{cid}/contacts`, POST `/clients/api/{cid}/contacts`, PUT `/contacts/api/{id}`, DELETE `/contacts/api/{id}`. Settare `is_primary=True` sincronizza `Client.contact_name/email/phone/role`.
- Gate: `view_clients`/`edit_clients` (riusa permessi clienti esistenti; i contatti sono sotto-risorsa cliente).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_contacts_api.py
from tests.test_acquisitions_api import client  # riusa fixture (role manager ha edit_clients? aggiungi)
from app.models.models import Client


def test_contact_crud_and_primary_sync(client):
    c, s = client
    # garantisci permessi clienti sulla role della fixture
    role = s.query(__import__("app.models.models", fromlist=["Role"]).Role).first()
    for p in ("view_clients", "edit_clients"):
        if p not in (role.permissions or []):
            role.permissions = (role.permissions or []) + [p]
    s.commit()
    r = c.post("/clients/api/1/contacts", data={"name": "Mario Rossi",
               "email": "m@x.it", "role": "Producer", "is_primary": "true"})
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    lst = c.get("/clients/api/1/contacts").json()
    assert any(x["id"] == cid for x in lst["items"])
    # primary sync su Client
    cl = s.query(Client).get(1)
    assert cl.contact_name == "Mario Rossi"
    assert cl.contact_email == "m@x.it"
    assert c.delete(f"/contacts/api/{cid}").status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_api.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
# app/routers/contacts.py
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from app.database import get_db
from app.context import current_tenant_id
from app.models.models import Contact, Client
from app.services.rbac import requires_permission

router = APIRouter(tags=["contacts"])
RequireView = Depends(requires_permission("view_clients"))
RequireEdit = Depends(requires_permission("edit_clients"))


def _contact_dict(c: Contact) -> dict:
    return {"id": c.id, "client_id": c.client_id, "name": c.name, "role": c.role,
            "email": c.email, "phone": c.phone, "notes": c.notes,
            "is_primary": c.is_primary, "ai_extracted": c.ai_extracted}


def _bool(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "on", "yes", "si", "sì")


def _sync_primary(db, contact: Contact):
    cl = db.query(Client).filter(Client.id == contact.client_id,
                                 Client.tenant_id == current_tenant_id()).first()
    if cl:
        cl.contact_name = contact.name
        cl.contact_email = contact.email
        cl.contact_phone = contact.phone
        cl.contact_role = contact.role
    # un solo primario per cliente
    others = db.query(Contact).filter(Contact.client_id == contact.client_id,
                                      Contact.id != contact.id, Contact.is_primary == True)  # noqa: E712
    for o in others:
        o.is_primary = False


@router.get("/clients/api/{cid}/contacts", dependencies=[RequireView])
async def list_contacts(cid: int, db: Session = Depends(get_db)):
    rows = (db.query(Contact).filter(Contact.tenant_id == current_tenant_id(),
            Contact.client_id == cid, Contact.is_active == True)  # noqa: E712
            .order_by(Contact.is_primary.desc(), Contact.name).all())
    return {"items": [_contact_dict(c) for c in rows]}


@router.post("/clients/api/{cid}/contacts", dependencies=[RequireEdit])
async def create_contact(cid: int, name: str = Form(...), role: Optional[str] = Form(None),
                         email: Optional[str] = Form(None), phone: Optional[str] = Form(None),
                         notes: Optional[str] = Form(None), is_primary: Optional[str] = Form(None),
                         db: Session = Depends(get_db)):
    cl = db.query(Client).filter(Client.id == cid, Client.tenant_id == current_tenant_id()).first()
    if not cl:
        raise HTTPException(404, "Cliente non trovato")
    c = Contact(tenant_id=current_tenant_id(), client_id=cid, name=name.strip(),
                role=role, email=email, phone=phone, notes=notes, is_primary=_bool(is_primary))
    db.add(c); db.flush()
    if c.is_primary:
        _sync_primary(db, c)
    db.commit(); db.refresh(c)
    return _contact_dict(c)


@router.put("/contacts/api/{cid}", dependencies=[RequireEdit])
async def update_contact(cid: int, name: Optional[str] = Form(None), role: Optional[str] = Form(None),
                         email: Optional[str] = Form(None), phone: Optional[str] = Form(None),
                         notes: Optional[str] = Form(None), is_primary: Optional[str] = Form(None),
                         db: Session = Depends(get_db)):
    c = db.query(Contact).filter(Contact.id == cid, Contact.tenant_id == current_tenant_id()).first()
    if not c:
        raise HTTPException(404, "Contatto non trovato")
    if name is not None: c.name = name.strip()
    if role is not None: c.role = role
    if email is not None: c.email = email
    if phone is not None: c.phone = phone
    if notes is not None: c.notes = notes
    if is_primary is not None: c.is_primary = _bool(is_primary)
    if c.is_primary:
        _sync_primary(db, c)
    db.commit(); db.refresh(c)
    return _contact_dict(c)


@router.delete("/contacts/api/{cid}", dependencies=[RequireEdit])
async def delete_contact(cid: int, db: Session = Depends(get_db)):
    c = db.query(Contact).filter(Contact.id == cid, Contact.tenant_id == current_tenant_id()).first()
    if not c:
        raise HTTPException(404, "Contatto non trovato")
    c.is_active = False
    db.commit()
    return {"ok": True, "id": cid}
```

In `app/main.py`: include `contacts.router`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routers/contacts.py app/main.py tests/test_contacts_api.py
git commit -m "feat(acquisizioni): contatti multipli cliente + sync referente"
```

---

### Task 11: Capability AI propose_acquisition / propose_activity / propose_contact / propose_acquisition_stage

**Files:**
- Modify: `app/services/ai_assistant.py` (4 handler `@ai_capability`)
- Modify: `app/services/ai_tools.py` (4 tool descriptor)
- Modify: `app/services/ai_context.py` (includi trattative aperte nel `build_context`)
- Test: `tests/test_acquisition_capabilities.py`

**Interfaces:**
- Consumes: registry `ai_capability`, modelli, `acquisition_service.apply_stage_change`.
- Produces: handler `_h_propose_acquisition(db, data)`, `_h_propose_activity(db, data)`, `_h_propose_contact(db, data)`, `_h_propose_acquisition_stage(db, data)` — ognuno ritorna dict con `message`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_acquisition_capabilities.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, Client, Acquisition, AcquisitionStage
from app.services.ai_capability_registry import get_handler


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="Lucky")); s.commit()
    yield s
    s.close()


def test_propose_acquisition_registered_and_creates(db):
    import app.services.ai_assistant  # noqa: F401  (forza registrazione)
    h = get_handler("propose_acquisition")
    assert h is not None
    out = h(db, {"title": "Film X", "client_id": 1, "stage": "lead",
                 "estimated_value": 50000})
    db.commit()
    assert "acquisition_id" in out
    acq = db.query(Acquisition).get(out["acquisition_id"])
    assert acq.title == "Film X" and acq.stage == AcquisitionStage.lead


def test_propose_activity_and_stage(db):
    import app.services.ai_assistant  # noqa: F401
    acq = Acquisition(tenant_id=1, title="A", client_id=1, stage=AcquisitionStage.lead,
                      estimated_value=0)
    db.add(acq); db.commit()
    get_handler("propose_activity")(db, {"acquisition_id": acq.id, "type": "call",
                                         "subject": "Chiamata"})
    db.commit()
    get_handler("propose_acquisition_stage")(db, {"acquisition_id": acq.id, "stage": "quoting"})
    db.commit()
    db.refresh(acq)
    assert acq.stage == AcquisitionStage.quoting
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisition_capabilities.py -v`
Expected: FAIL (`get_handler("propose_acquisition")` → None).

- [ ] **Step 3: Write minimal implementation**

In `app/services/ai_assistant.py` (vicino agli altri handler, usa `current_tenant_id()` come fanno gli altri — importalo se serve):

```python
from app.context import current_tenant_id
from app.models.models import (
    Acquisition, AcquisitionStage, Activity, ActivityType, Contact,
)
from app.services.acquisition_service import apply_stage_change


@ai_capability("propose_acquisition")
def _h_propose_acquisition(db: Session, data: dict) -> dict:
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("Manca 'title'")
    acq = Acquisition(
        tenant_id=current_tenant_id(), title=title,
        client_id=data.get("client_id"),
        prospect_name=data.get("prospect_name"),
        stage=AcquisitionStage(data.get("stage") or "lead"),
        estimated_value=data.get("estimated_value") or 0,
        next_action=data.get("next_action"))
    db.add(acq); db.flush()
    return {"created": True, "acquisition_id": acq.id,
            "message": f"Trattativa '{title}' creata (stadio {acq.stage.value})."}


@ai_capability("propose_activity")
def _h_propose_activity(db: Session, data: dict) -> dict:
    subject = (data.get("subject") or "").strip()
    if not subject:
        raise ValueError("Manca 'subject'")
    a = Activity(tenant_id=current_tenant_id(),
                 acquisition_id=data.get("acquisition_id"),
                 client_id=data.get("client_id"), project_id=data.get("project_id"),
                 type=ActivityType(data.get("type") or "note"), subject=subject,
                 body=data.get("body"))
    db.add(a); db.flush()
    return {"created": True, "activity_id": a.id,
            "message": f"Attività '{subject}' registrata."}


@ai_capability("propose_contact")
def _h_propose_contact(db: Session, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    cid = data.get("client_id")
    if not name or not cid:
        raise ValueError("Servono 'name' e 'client_id'")
    c = Contact(tenant_id=current_tenant_id(), client_id=cid, name=name,
                role=data.get("role"), email=data.get("email"),
                phone=data.get("phone"), ai_extracted=True)
    db.add(c); db.flush()
    return {"created": True, "contact_id": c.id,
            "message": f"Contatto '{name}' aggiunto al cliente {cid}."}


@ai_capability("propose_acquisition_stage")
def _h_propose_acquisition_stage(db: Session, data: dict) -> dict:
    aid = data.get("acquisition_id")
    acq = db.query(Acquisition).filter(Acquisition.id == aid,
                                       Acquisition.tenant_id == current_tenant_id()).first()
    if not acq:
        raise ValueError(f"Trattativa {aid} non trovata")
    apply_stage_change(db, acq, AcquisitionStage(data.get("stage")))
    return {"updated": True, "acquisition_id": acq.id,
            "message": f"Trattativa avanzata a stadio {acq.stage.value}."}
```

In `app/services/ai_tools.py`, aggiungi 4 descrittori al `TOOLS` (segui la forma degli esistenti, con `description` chiare e `enum` per `stage`/`type` coerenti con i dati reali — vedi `feedback_ai_schema_descriptions`):

```python
    {
        "name": "propose_acquisition",
        "description": "Crea una trattativa di acquisizione (lead→commessa). Usa client_id PK numerico o prospect_name se il cliente non esiste ancora.",
        "input_schema": {"type": "object", "properties": {
            "title": {"type": "string"},
            "client_id": {"type": "integer"},
            "prospect_name": {"type": "string"},
            "stage": {"type": "string", "enum": ["lead", "qualified", "quoting", "negotiation", "won", "lost"]},
            "estimated_value": {"type": "number"},
            "next_action": {"type": "string"},
        }, "required": ["title"]},
    },
    {
        "name": "propose_activity",
        "description": "Registra una comunicazione/attività su una trattativa (email/call/meeting/note/task).",
        "input_schema": {"type": "object", "properties": {
            "acquisition_id": {"type": "integer"},
            "client_id": {"type": "integer"},
            "type": {"type": "string", "enum": ["email", "call", "meeting", "note", "task"]},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        }, "required": ["subject"]},
    },
    {
        "name": "propose_contact",
        "description": "Aggiunge un contatto (persona) a un cliente esistente (client_id PK numerico).",
        "input_schema": {"type": "object", "properties": {
            "client_id": {"type": "integer"},
            "name": {"type": "string"},
            "role": {"type": "string"},
            "email": {"type": "string"},
            "phone": {"type": "string"},
        }, "required": ["client_id", "name"]},
    },
    {
        "name": "propose_acquisition_stage",
        "description": "Avanza/cambia lo stadio di una trattativa esistente (acquisition_id PK numerico).",
        "input_schema": {"type": "object", "properties": {
            "acquisition_id": {"type": "integer"},
            "stage": {"type": "string", "enum": ["lead", "qualified", "quoting", "negotiation", "won", "lost"]},
        }, "required": ["acquisition_id", "stage"]},
    },
```

In `app/services/ai_context.py` (`build_context`), aggiungi un blocco "TRATTATIVE APERTE" con le acquisizioni `is_active` e stadio non won/lost (id, title, client, stage, estimated_value) — segui il formato testuale già usato per gli altri elenchi nel context (così anche i provider legacy le vedono).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisition_capabilities.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/ai_assistant.py app/services/ai_tools.py app/services/ai_context.py tests/test_acquisition_capabilities.py
git commit -m "feat(acquisizioni): capability AI propose_* + context trattative"
```

---

### Task 12: Fix UI modifica stato Progetto

**Files:**
- Modify: `app/templates/pages/projects.html` (esponi selettore stato che salva via PUT)
- Modify (se serve): `app/routers/projects.py` (verifica che il PUT applichi `status`)
- Test: `tests/test_project_status_update.py`

**Interfaces:**
- Consumes: PUT progetto esistente.
- Produces: cambio stato progetto persistito dalla UI.

- [ ] **Step 1: Write the failing test**

Prima verifica il comportamento backend (potrebbe già passare — in tal caso il bug è solo UI e questo test fa da regressione):

```python
# tests/test_project_status_update.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole, Client, Project, ProjectStatus
from app.services.auth import create_access_token


@pytest.fixture
def client():
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False); s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    role = Role(tenant_id=1, code="manager", name="M",
                permissions=["view_projects", "edit_projects"], is_system=True, is_active=True)
    s.add(role); s.flush()
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.manager, role_id=role.id, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="X")); s.flush()
    s.add(Project(id=1, tenant_id=1, code="P1", title="P1", client_id=1,
                  status=ProjectStatus.prospect)); s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "a@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_project_status_update_persists(client):
    c, s = client
    r = c.put("/projects/api/1", data={"status": "active"})
    assert r.status_code in (200, 201), r.text
    s.expire_all()
    assert s.query(Project).get(1).status == ProjectStatus.active
```

(Verifica il path PUT reale in `projects.py` e adegua l'URL se diverso.)

- [ ] **Step 2: Run test to verify it fails (o passa già)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_project_status_update.py -v`
Se PASS → backend ok, il bug è solo UI: procedi allo Step 3 (UI). Se FAIL → correggi `projects.py` perché il PUT applichi `status`.

- [ ] **Step 3: Implementazione**

- Se backend rotto: in `app/routers/projects.py` assicurati che il blocco update applichi `status` (il campo è già nei `Form` e nella lista campi ~riga 261).
- UI: in `app/templates/pages/projects.html` aggiungi nel modal/dettaglio progetto un `<select>` stato con le opzioni `ProjectStatus` (prospect/quoting/active/completed/archived), `data-i18n` per ogni label, che invii il PUT esistente. Ordine opzioni esplicito (ordine enum). Bump cache-buster automatico via versione.

- [ ] **Step 4: Run test + smoke**

Run: `.venv/Scripts/python.exe -m pytest tests/test_project_status_update.py -v`
Expected: PASS. Smoke browser: cambia stato progetto dalla UI → persiste dopo reload.

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/projects.html app/routers/projects.py tests/test_project_status_update.py
git commit -m "fix(progetti): modifica stato progetto dalla UI"
```

---

### Task 13: Pagina /acquisitions (kanban + tabella + dettaglio) + nav + i18n

**Files:**
- Create: `app/templates/pages/acquisitions.html`
- Modify: `app/routers/acquisitions.py` (route GET `/acquisitions` che renderizza la pagina con `active_page="acquisitions"`)
- Modify: `app/templates/base.html` (voce nav sotto "Anagrafica")
- Modify: `app/static/js/i18n.js` (chiavi `acq.*` in 5 lingue)
- Test: smoke browser (manuale, vedi Step 4)

**Interfaces:**
- Consumes: tutti gli endpoint dei Task 7-9.

- [ ] **Step 1: Route pagina**

In `app/routers/acquisitions.py`:

```python
from fastapi import Request as _Req

@router.get("/acquisitions", response_class=HTMLResponse, dependencies=[RequireView])
async def acquisitions_page(request: _Req):
    from app.main import templates
    return templates.TemplateResponse("pages/acquisitions.html",
                                      {"request": request, "active_page": "acquisitions"})
```

- [ ] **Step 2: Nav**

In `app/templates/base.html`, nella sezione `nav.section.records` (Anagrafica), dopo "Progetti":

```html
        <a href="/acquisitions" data-nav-id="acquisitions" class="nav-item {% if active_page == 'acquisitions' %}active{% endif %}">
          <span class="nav-icon"><i data-lucide="target"></i></span> <span data-i18n="nav.acquisitions">Acquisizioni</span>
        </a>
```

- [ ] **Step 3: Pagina**

Crea `app/templates/pages/acquisitions.html` estendendo `base.html` (segui un template esistente con toggle vista, es. `finance/sal` o `planning`). Struttura minima:
- **Header KPI**: `Σ potenziale pesato` (da `/acquisitions/api/summary`), breakdown per-reparto, n° aperte.
- **Filtri**: reparto/commerciale/cliente/stato.
- **Toggle Kanban ⇄ Tabella** (bottone che mostra/nasconde i due container).
- **Kanban**: 6 colonne (lead…lost). Card draggable (HTML5 `draggable`); su drop chiama `POST /acquisitions/api/{id}/stage`. Card: titolo, cliente, €, prob%, badge reparti, prossima azione, owner.
- **Tabella**: righe con dropdown stadio inline (onchange → stage endpoint).
- **Striscia mini-agenda**: da `/acquisitions/api/agenda`.
- **Pannello dettaglio** (click card/riga): GET `/acquisitions/api/{id}` → mostra header + quotazioni collegate; tab Attività (lista + quick-add form → `POST .../activities`); tab Contatti (lista `/clients/api/{cid}/contacts` + add/edit); azioni Converti/Vinta/Persa.

Usa helper globali (`api`, `escapeHtml`, `toast`, `mfT`, `openModal/closeModal`) da `global.js`. Niente `JSON.stringify` in `onclick` (usa `data-*`). Tutte le stringhe `data-i18n`/`mfT`.

- [ ] **Step 4: i18n + smoke**

In `app/static/js/i18n.js` aggiungi tutte le chiavi `acq.*` e `nav.acquisitions` in 5 lingue (it/en/fr/de/es). Poi smoke browser:
- `/acquisitions` carica, 0 errori console.
- Crea trattativa → appare in kanban + tabella.
- Drag card tra colonne → stadio cambia (verifica via reload).
- KPI Σ pesato coerente.
- Dettaglio: aggiungi attività + contatto; converti in progetto.
- Verifica EN (lang switch) su tutti gli elementi nuovi (0 chiavi grezze).

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/acquisitions.html app/routers/acquisitions.py app/templates/base.html app/static/js/i18n.js
git commit -m "feat(acquisizioni): pagina kanban+tabella+dettaglio + nav + i18n"
```

---

### Task 14: Integrazione finale — version bump + suite + docs + menu strumenti

**Files:**
- Modify: `app/main.py` (bump versione `3.5.0-alpha.172.236`)
- Modify: `CHANGELOG.md`, `docs/STATO.md`
- Modify: `strumenti.bat` / `strumenti.sh` (voce per `migrate_acquisitions.py`)
- Test: full suite

- [ ] **Step 1: Run full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tutti verdi (i ~950 esistenti + i nuovi).

- [ ] **Step 2: Smoke browser end-to-end**

Avvia server, login, percorri: crea trattativa prospect (senza cliente) → aggiungi attività → avanza stadio (drag) → converti in progetto (crea cliente+progetto) → verifica stato progetto modificabile. 0 errori console.

- [ ] **Step 3: Bump + docs**

- `app/main.py`: `version="3.5.0-alpha.172.236"`.
- `CHANGELOG.md`: nuova sezione.
- `docs/STATO.md`: versione corrente + sezione + prossimo step (Fase 2 email-AI).
- `strumenti.bat`/`strumenti.sh`: voce migrazione acquisizioni.

- [ ] **Step 4: graphify + commit finale**

```bash
graphify update .
git add app/main.py CHANGELOG.md docs/STATO.md strumenti.bat strumenti.sh
git commit -m "chore(acquisizioni): bump v3.5.0-alpha.172.236 + docs + menu migrazione"
```

- [ ] **Step 5: Verifica finale**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: verde. STATO/CHANGELOG aggiornati.

---

## Self-Review (eseguito)

**Spec coverage**: entità Acquisition (T1) · prospect/convert (T6) · stadi (T1/T8) · potenziale pesato (T4) · tag reparti (T1/T7) · summary per-reparto (T5) · mini-agenda (T5/T13) · kanban+tabella (T13) · Contact (T1/T10) · Activity (T1/T9) · fix stato progetto (T12) · permessi (T3) · capability AI (T11) · migrazione/boot (T2) · i18n/version/docs (T13/T14). Tutte le sezioni spec coperte.

**Placeholder scan**: nessun TBD/TODO; codice concreto in ogni step. Task 13 (pagina) descrive la struttura UI con endpoint esatti ma senza incollare 500 righe di HTML — accettabile: i contratti API sono fissati nei Task 7-10 e gli helper globali sono noti; lo step di smoke verifica il risultato.

**Type consistency**: `_acq_dict` serializza gli stessi campi consumati dalla pagina; `AcquisitionStage`/`ActivityType` valori coerenti tra modello, service, router, tool descriptor; `weighted_value`/`effective_probability` firma stabile tra service e router; `apply_stage_change`/`convert_to_project` firma coerente tra T6, T8, T11.

## Out of scope (Fasi successive)
- **Fase 2**: incolla-email → AI estrae + incrocio web (Tavily) → propone attività/contatti/aggiornamenti. UI dedicata sopra le capability `propose_*` di T11.
- **Fase 3**: agenda piena + Google Calendar (OAuth) / ICS.
