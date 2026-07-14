# Client email — Sotto-fase 3: Rubrica Contatti — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `Contact` from a client-only sub-resource into a standalone rubrica (address book), fed by hybrid (deterministic + optional-AI) email extraction, linkable to clients/trattative/progetti, with a dedicated `/contacts` page, copilot capability, a tech-sheet bridge, and an on-demand notification badge — all while keeping the existing client-scoped Contact endpoints working unchanged.

**Architecture:** `Contact.client_id` becomes nullable (single FK — "azienda del contatto", 0..1) plus two new M:N join tables `contact_acquisitions` / `contact_projects` (many trattative/progetti per contatto). `app/routers/contacts.py` (existing) grows new endpoints: rubrica page, list/detail/create/link/unlink, extraction, match/dedup, tech-sheet bridge, notification badge. `app/services/contact_extract.py` (new) does regex-based participant/signature parsing with an optional LLM enrichment step (`get_provider_for_user`). `propose_contact` copilot capability gains optional `acquisition_id`/`project_id` links. Frontend: new `pages/contacts.html` + `static/js/contacts.js`, plus small hooks added to `mail.js`, `email_links.js`, and the tech-sheet editor in `project_detail.html`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (`Mapped`/`mapped_column`) + Jinja2 + SQLite, vanilla JS (`global.js` helpers: `api()`, `openModal()`/`closeModal()`, `MFFilterBar()`), pytest + `TestClient` with in-memory SQLite.

## Global Constraints

- Tenant filter on every query via `current_tenant_id()` (module-level `CURRENT_TENANT` pattern not used in `contacts.py`; it calls `current_tenant_id()` directly like the existing file does).
- Soft delete via `is_active=False`, never physical DELETE on `Contact` (the two new join tables ARE physically deleted on unlink — this is an explicit, spec-approved exception: "scelta: righe fisiche con delete su unlink, coerente con join semplici").
- All POST/PUT endpoints use `Form(...)`, not JSON body (existing `contacts.py` convention). Exception: none needed here — the tech-sheet router's own JSON-body PUT is pre-existing and out of scope.
- Every new UI string added to `app/static/js/i18n.js` in all 5 languages (`it/en/fr/de/es`) in the SAME commit as the template/JS that uses it. No English-only or partial-language debt.
- `@ai_capability(...)` registration must happen in `app/services/ai_assistant.py` BEFORE the `_ACTION_HANDLERS = _registry_get_handlers()` snapshot at the bottom of the file (currently line 4609) — the existing `_h_propose_contact` is already above it, so editing it in place is safe.
- Backward compat: `GET/POST /clients/api/{cid}/contacts` and `PUT/DELETE /contacts/api/{cid}` (existing, param literally named `cid` but is the contact's own id) must keep behaving identically for callers that don't pass the new fields. `_sync_primary` continues to run only when `contact.client_id` is set.
- FastAPI/Starlette route-matching hazard: within `app/routers/contacts.py`, any **new literal-path GET** endpoint under `/contacts/api/...` (`list`, `match`, `notify-badge`) MUST be added to the file **before** the new `GET /contacts/api/{cid}` (detail) handler, otherwise Starlette's in-order route scan will try to parse `"list"`/`"match"`/`"notify-badge"` as the `int` path param and 422 instead of falling through. POST routes don't collide with this GET, but keep the same discipline for clarity.
- SQLite has no `ALTER COLUMN DROP NOT NULL`. **Confirmed by direct inspection of the live `mediaflow.db`** (see Task 2): `contacts.client_id` is physically `INTEGER NOT NULL` in the on-disk DDL, not just an ORM-level constraint. The migration MUST do a table rebuild (copy-and-rename), not a no-op. The codebase already has a proven precedent for this exact pattern: `scripts/migrate_deliverable_audio_label.py` (`_relax_item_notnull`), reused near-verbatim in Task 2.

---

### Diagnostic finding (do not re-derive — already established)

Ran directly against the project's live `mediaflow.db`:

```
CREATE TABLE contacts (
	id INTEGER NOT NULL,
	tenant_id INTEGER NOT NULL,
	client_id INTEGER NOT NULL,
	name VARCHAR(255) NOT NULL,
	...
	FOREIGN KEY(client_id) REFERENCES clients (id) ON DELETE CASCADE
)
```

`client_id` is `NOT NULL` at the physical DDL level. Decision locked in: **rebuild required** (option (a) from the spec's risk section), using the same regex-based "strip NOT NULL from the CREATE TABLE SQL, rebuild, reinstate indexes" approach as `migrate_deliverable_audio_label.py`.

---

## Task 1: Model changes — `Contact` nullable `client_id` + `company_text`/`source` + join tables

**Files:**
- Modify: `app/models/models.py:4814-4828` (the `Contact` class)
- Test: `tests/test_contact_model.py` (new)

**Interfaces:**
- Produces: `Contact.client_id: Optional[int]`, `Contact.company_text: Optional[str]`, `Contact.source: str` (default `"manual"`); `ContactAcquisition(id, tenant_id, contact_id, acquisition_id, role, created_at)`; `ContactProject(id, tenant_id, contact_id, project_id, role, created_at)`, both with `UniqueConstraint(contact_id, <other>_id)`.
- Consumes: nothing new (uses existing `Base`, `now_utc`, `Mapped`/`mapped_column` imports already at the top of `models.py`; `UniqueConstraint` is already imported there — used at `models.py:4231` for `TechSheetFieldOption`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_contact_model.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Contact, ContactAcquisition, ContactProject,
    Acquisition, Project,
)


@pytest.fixture
def session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                       poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Cliente"))
    s.add(Acquisition(id=1, tenant_id=1, title="Trattativa", client_id=1))
    s.add(Project(id=1, tenant_id=1, code="P1", title="Progetto", client_id=1))
    s.commit()
    yield s


def test_contact_client_id_is_nullable(session):
    c = Contact(tenant_id=1, client_id=None, name="Mario Rossi",
                company_text="Studio Libero", source="manual")
    session.add(c)
    session.commit()
    assert c.id is not None
    assert c.client_id is None
    assert c.company_text == "Studio Libero"
    assert c.source == "manual"


def test_contact_source_defaults_to_manual(session):
    c = Contact(tenant_id=1, client_id=1, name="Anna Bianchi")
    session.add(c)
    session.commit()
    assert c.source == "manual"


def test_contact_acquisitions_link_and_unique(session):
    c = Contact(tenant_id=1, client_id=None, name="Mario Rossi")
    session.add(c)
    session.commit()
    session.add(ContactAcquisition(tenant_id=1, contact_id=c.id, acquisition_id=1, role="referente"))
    session.commit()
    session.add(ContactAcquisition(tenant_id=1, contact_id=c.id, acquisition_id=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_contact_projects_link_and_unique(session):
    c = Contact(tenant_id=1, client_id=None, name="Mario Rossi")
    session.add(c)
    session.commit()
    session.add(ContactProject(tenant_id=1, contact_id=c.id, project_id=1, role="DIT"))
    session.commit()
    session.add(ContactProject(tenant_id=1, contact_id=c.id, project_id=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contact_model.py -v`
Expected: FAIL — `Contact.client_id` rejects `None` (NOT NULL at ORM level) and `ContactAcquisition`/`ContactProject` don't exist yet (`ImportError`).

- [ ] **Step 3: Modify `Contact` and add the two join-table models**

In `app/models/models.py`, replace the `client_id` line and add two columns inside the existing `Contact` class (`models.py:4814-4828`):

```python
class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True)
    company_text: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")
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


class ContactAcquisition(Base):
    """M:N contatto↔trattativa (Client email F3). Righe fisiche, delete su unlink."""
    __tablename__ = "contact_acquisitions"
    __table_args__ = (
        UniqueConstraint("contact_id", "acquisition_id", name="uq_contact_acquisition"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    acquisition_id: Mapped[int] = mapped_column(ForeignKey("acquisitions.id", ondelete="CASCADE"), index=True)
    role: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class ContactProject(Base):
    """M:N contatto↔progetto (Client email F3). Righe fisiche, delete su unlink."""
    __tablename__ = "contact_projects"
    __table_args__ = (
        UniqueConstraint("contact_id", "project_id", name="uq_contact_project"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    role: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
```

Keep `ContactAcquisition`/`ContactProject` placed directly after `Contact` (before `Activity`, `models.py:4831`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contact_model.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/models/models.py tests/test_contact_model.py
git commit -m "feat(contacts): Contact standalone (client_id nullable) + contact_acquisitions/contact_projects M:N"
```

---

## Task 2: Migration script — `contacts.client_id` rebuild + new columns/tables + boot wiring

**Files:**
- Create: `scripts/migrate_contacts_rubrica.py`
- Modify: `app/main.py` (add call inside `_auto_migrate_columns`, right after the existing `migrate_deliverable_audio_label` block, `app/main.py:1213-1221`)
- Modify: `strumenti.sh` (menu entry `u|U`, `strumenti.sh:33-58` for the header echo/read, and a new `u|U)` case block modeled on the existing `s|S)` block at `strumenti.sh:330-339`)
- Modify: `strumenti.bat` (menu entry `[U]`, header block `strumenti.bat:10-39`, dispatch line `strumenti.bat:67`, and a new `:migrate_contacts_rubrica` label modeled on `:migrate_email_links` at `strumenti.bat:410-420`)
- Test: `tests/test_migrate_contacts_rubrica.py` (new)

**Interfaces:**
- Consumes: `ContactAcquisition`, `ContactProject` from Task 1.
- Produces: `scripts.migrate_contacts_rubrica.migrate(engine) -> dict` with keys `columns_added: list[str]`, `contacts_rebuilt: bool`, `tables_created: list[str]`. Callable standalone (`python scripts/migrate_contacts_rubrica.py`) and importable from `app/main.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrate_contacts_rubrica.py`. It builds an **on-disk** SQLite file (rebuild needs `PRAGMA foreign_keys` / DDL that behaves differently on `:memory:` across connections) with the OLD pre-migration `contacts` shape, then runs `migrate()` and asserts the new shape + preserved data:

```python
import os
import tempfile

import pytest
from sqlalchemy import create_engine, text, inspect


@pytest.fixture
def old_shape_engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", future=True)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE tenants (id INTEGER PRIMARY KEY, name VARCHAR(100))
        """))
        conn.execute(text("""
            CREATE TABLE clients (id INTEGER PRIMARY KEY, tenant_id INTEGER, name VARCHAR(255))
        """))
        conn.execute(text("""
            CREATE TABLE contacts (
                id INTEGER NOT NULL,
                tenant_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                role VARCHAR(120),
                email VARCHAR(255),
                phone VARCHAR(50),
                notes TEXT,
                is_primary BOOLEAN NOT NULL,
                ai_extracted BOOLEAN NOT NULL,
                is_active BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                FOREIGN KEY(client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
        """))
        conn.execute(text(
            "CREATE INDEX ix_contacts_client_id ON contacts(client_id)"))
        conn.execute(text(
            "INSERT INTO tenants (id, name) VALUES (1, 'T')"))
        conn.execute(text(
            "INSERT INTO clients (id, tenant_id, name) VALUES (1, 1, 'Cliente')"))
        conn.execute(text(
            "INSERT INTO contacts (id, tenant_id, client_id, name, is_primary, "
            "ai_extracted, is_active, created_at, updated_at) VALUES "
            "(1, 1, 1, 'Mario Rossi', 0, 0, 1, '2026-07-01 00:00:00', '2026-07-01 00:00:00')"))
    yield engine
    engine.dispose()
    os.remove(path)


def test_migrate_relaxes_notnull_adds_columns_and_tables_preserving_data(old_shape_engine):
    from scripts.migrate_contacts_rubrica import migrate
    result = migrate(old_shape_engine)

    assert "contacts.company_text" in result["columns_added"]
    assert "contacts.source" in result["columns_added"]
    assert result["contacts_rebuilt"] is True
    assert set(result["tables_created"]) == {"contact_acquisitions", "contact_projects"}

    insp = inspect(old_shape_engine)
    cols = {c["name"]: c for c in insp.get_columns("contacts")}
    assert cols["client_id"]["nullable"] is True
    assert "company_text" in cols
    assert "source" in cols
    assert {"contact_acquisitions", "contact_projects"}.issubset(set(insp.get_table_names()))

    with old_shape_engine.begin() as conn:
        row = conn.execute(text("SELECT id, client_id, name FROM contacts WHERE id=1")).fetchone()
        assert row == (1, 1, "Mario Rossi")
        # nullable now actually accepts NULL
        conn.execute(text(
            "INSERT INTO contacts (id, tenant_id, client_id, name, is_primary, ai_extracted, "
            "is_active, created_at, updated_at, company_text, source) VALUES "
            "(2, 1, NULL, 'Orfano', 0, 0, 1, '2026-07-01 00:00:00', '2026-07-01 00:00:00', 'ACME', 'manual')"))


def test_migrate_is_idempotent(old_shape_engine):
    from scripts.migrate_contacts_rubrica import migrate
    migrate(old_shape_engine)
    result2 = migrate(old_shape_engine)
    assert result2["columns_added"] == []
    assert result2["contacts_rebuilt"] is False
    assert result2["tables_created"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_contacts_rubrica.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.migrate_contacts_rubrica'`.

- [ ] **Step 3: Write `scripts/migrate_contacts_rubrica.py`**

```python
"""v3.5.0-alpha.172.246 — Migrazione Client email F3: Rubrica Contatti.

Cosa fa (idempotente):
1. contacts += company_text (VARCHAR(255) NULL), source (VARCHAR(20) NOT NULL
   DEFAULT 'manual').
2. contacts.client_id: da NOT NULL a nullable. SQLite non supporta
   ALTER COLUMN -> rebuild tabella riusando lo schema reale da sqlite_master
   (stesso pattern di migrate_deliverable_audio_label.py: _relax_item_notnull),
   preservando dati + indici.
3. CREATE TABLE se mancanti: contact_acquisitions, contact_projects
   (create_all le crea gia' per DB nuovi; qui esplicito per DB esistenti,
   pattern migrate_documents.py).

Lanciabile standalone (`python scripts/migrate_contacts_rubrica.py`) o
importabile: `from scripts.migrate_contacts_rubrica import migrate`.
Chiamato anche dal boot (_auto_migrate_columns) per sicurezza zero-step.
"""
from __future__ import annotations
import re
from sqlalchemy import text, inspect
from sqlalchemy.engine import Engine


def _add_columns(engine: Engine) -> list[str]:
    done: list[str] = []
    insp = inspect(engine)
    if "contacts" not in insp.get_table_names():
        return done
    existing = {c["name"] for c in insp.get_columns("contacts")}
    additive = [
        ("company_text", "VARCHAR(255) NULL"),
        ("source", "VARCHAR(20) NOT NULL DEFAULT 'manual'"),
    ]
    with engine.begin() as conn:
        for col, ddl in additive:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE contacts ADD COLUMN {col} {ddl}"))
                done.append(f"contacts.{col}")
    return done


def _client_id_is_notnull(engine: Engine) -> bool:
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(contacts)")).fetchall()
    for r in rows:
        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        if r[1] == "client_id":
            return bool(r[3])
    return False


def _relax_client_id_notnull(engine: Engine) -> bool:
    """Rebuild contacts per rendere client_id nullable. Riusa lo schema reale
    (sqlite_master) togliendo solo il NOT NULL su quella colonna. Preserva
    dati e ricrea gli indici espliciti. Ritorna True se ha agito."""
    if not _client_id_is_notnull(engine):
        return False

    with engine.begin() as conn:
        create_sql = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='contacts'"
        )).scalar()
        if not create_sql:
            return False
        index_sqls = [
            row[0] for row in conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND tbl_name='contacts' AND sql IS NOT NULL"
            )).fetchall()
        ]

        # Togli il NOT NULL SOLO da client_id. Tollerante a spaziatura.
        new_create = re.sub(
            r'("?client_id"?\s+\w+)\s+NOT\s+NULL',
            r'\1',
            create_sql,
            count=1,
            flags=re.IGNORECASE,
        )
        if new_create == create_sql:
            raise RuntimeError(
                "migrate_contacts_rubrica: impossibile localizzare NOT NULL "
                "su client_id nello schema; rebuild annullato per sicurezza."
            )
        new_create = new_create.replace("contacts", "contacts_new", 1)

        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(contacts)")).fetchall()]
        col_list = ", ".join(f'"{c}"' for c in cols)

        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text(new_create))
        conn.execute(text(
            f"INSERT INTO contacts_new ({col_list}) SELECT {col_list} FROM contacts"
        ))
        conn.execute(text("DROP TABLE contacts"))
        conn.execute(text("ALTER TABLE contacts_new RENAME TO contacts"))
        for isql in index_sqls:
            conn.execute(text(isql))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_contacts_client_id ON contacts(client_id)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
    return True


def _create_join_tables(engine: Engine) -> list[str]:
    from app.models.models import ContactAcquisition, ContactProject
    done: list[str] = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "contact_acquisitions" not in tables:
        ContactAcquisition.__table__.create(bind=engine)
        done.append("contact_acquisitions")
    if "contact_projects" not in tables:
        ContactProject.__table__.create(bind=engine)
        done.append("contact_projects")
    return done


def migrate(engine: Engine) -> dict:
    """Esegue l'intera migrazione. Idempotente. Ritorna un riepilogo."""
    added = _add_columns(engine)
    rebuilt = _relax_client_id_notnull(engine)
    tables = _create_join_tables(engine)
    return {"columns_added": added, "contacts_rebuilt": rebuilt, "tables_created": tables}


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.database import engine  # type: ignore
    result = migrate(engine)
    print("[migrate_contacts_rubrica]", result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrate_contacts_rubrica.py -v`
Expected: 2 passed.

- [ ] **Step 5: Wire into boot `_auto_migrate_columns`**

In `app/main.py`, right after the existing block that ends at `app/main.py:1221` (`except Exception as e: print(f"[auto-migrate] deliverable audio\label FAILED: {e}")`), insert:

```python
    # v3.5.0-alpha.172.246 — Client email F3: Rubrica Contatti (contacts.client_id
    # nullable + company_text/source + contact_acquisitions/contact_projects).
    try:
        from scripts.migrate_contacts_rubrica import migrate as _mig_contacts_rubrica
        _res = _mig_contacts_rubrica(engine)
        if _res.get("columns_added") or _res.get("contacts_rebuilt") or _res.get("tables_created"):
            print(f"[auto-migrate] contacts rubrica: {_res}")
    except Exception as e:
        print(f"[auto-migrate] contacts rubrica FAILED: {e}")
```

- [ ] **Step 6: Add `strumenti.sh` menu entry `u|U`**

In `strumenti.sh`, add a new line to the menu listing near `strumenti.sh:53` (after the `[s] Migra Client email F2` line):

```
    echo "  [u] Migra Client email F3 - rubrica contatti (client_id nullable + link) [v3.5.0-alpha.172]"
```

Update the `read -p` prompt at `strumenti.sh:58` to include `u`, and add a new case block after the existing `t|T)` block (`strumenti.sh:340-349`):

```bash
        u|U)
            echo ""
            echo "Migrazione Client email F3: rende contacts.client_id nullable, aggiunge"
            echo "company_text/source, crea contact_acquisitions/contact_projects. Idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_contacts_rubrica.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
```

- [ ] **Step 7: Add `strumenti.bat` menu entry `[U]`**

In `strumenti.bat`, add to the header echo block near `strumenti.bat:34` (after `[S] Migra Client email F2`):

```
echo  [U] Migra Client email F3 - rubrica contatti (client_id nullable + link) [v3.5.0-alpha.172]
```

Add the dispatch line near `strumenti.bat:67` (after the `S` line):

```
if /i "%scelta%"=="U" goto migrate_contacts_rubrica
```

Add a new label block near `strumenti.bat:420` (after the `:migrate_email_links` block):

```batch
:migrate_contacts_rubrica
echo.
echo Migrazione Client email F3: rende contacts.client_id nullable, aggiunge
echo company_text/source, crea contact_acquisitions/contact_projects.
echo Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_contacts_rubrica.py
)
pause & goto menu
```

- [ ] **Step 8: Manual smoke of the boot wiring**

Run: `.venv/Scripts/python.exe -c "from app.main import _auto_migrate_columns; _auto_migrate_columns()"` against the real `mediaflow.db` copy (use a scratch copy, not the live file, to avoid touching Matteo's dev DB before he reviews) and confirm it prints `[auto-migrate] contacts rubrica: {...}` with `contacts_rebuilt: True` on first run and `{'columns_added': [], 'contacts_rebuilt': False, 'tables_created': []}`-shaped no-op on a second run.

- [ ] **Step 9: Commit**

```bash
git add scripts/migrate_contacts_rubrica.py app/main.py strumenti.sh strumenti.bat tests/test_migrate_contacts_rubrica.py
git commit -m "feat(contacts): migrazione rubrica (client_id nullable + join tables) + auto-migrate boot + strumenti"
```

---

## Task 3: Router — `GET /contacts/api/list` + `GET /contacts/api/match`

**Files:**
- Modify: `app/routers/contacts.py` (imports + append new endpoints after `delete_contact`, `contacts.py:162-173`)
- Test: `tests/test_contacts_rubrica_api.py` (new — this file accumulates across Tasks 3-5, 9)

**Interfaces:**
- Consumes: `Contact`, `ContactAcquisition`, `ContactProject` (Task 1).
- Produces: `_contact_dict(c) -> dict` (extended with `client_id`, `company_text`, `source`, unchanged keys otherwise — used by Task 4/5 too), `_link_counts(db, contact_id) -> {"acquisitions": int, "projects": int}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_contacts_rubrica_api.py` (fixture mirrors `tests/test_email_links_api.py`):

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, User, UserRole, Client, Acquisition, Project, Contact,
    ContactAcquisition, ContactProject,
)
from app.services.auth import create_access_token


@pytest.fixture
def client(monkeypatch):
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", e)
    monkeypatch.setattr(database, "SessionLocal", S)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
               hashed_password="x", role=UserRole.admin, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Cliente A"))
    s.add(Acquisition(id=1, tenant_id=1, title="Trattativa", client_id=1))
    s.add(Project(id=1, tenant_id=1, code="P1", title="Progetto", client_id=1))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_list_returns_all_active_contacts_with_link_counts(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=1, name="Mario Rossi"))
    s.add(Contact(id=2, tenant_id=1, client_id=None, name="Orfano", company_text="ACME"))
    s.commit()
    s.add(ContactAcquisition(tenant_id=1, contact_id=1, acquisition_id=1))
    s.commit()
    r = c.get("/contacts/api/list")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    m = next(i for i in items if i["id"] == 1)
    assert m["links"] == {"acquisitions": 1, "projects": 0}


def test_list_search_filters_by_name_email_company(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Mario Rossi", email="mario@acme.com"))
    s.add(Contact(id=2, tenant_id=1, client_id=None, name="Anna Bianchi", company_text="Studio X"))
    s.commit()
    r = c.get("/contacts/api/list?search=acme")
    assert [i["id"] for i in r.json()["items"]] == [1]
    r2 = c.get("/contacts/api/list?search=studio")
    assert [i["id"] for i in r2.json()["items"]] == [2]


def test_list_triage_returns_only_orphans(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=1, name="Con cliente"))
    s.add(Contact(id=2, tenant_id=1, client_id=None, name="Orfano puro"))
    s.add(Contact(id=3, tenant_id=1, client_id=None, name="Orfano ma linkato"))
    s.commit()
    s.add(ContactProject(tenant_id=1, contact_id=3, project_id=1))
    s.commit()
    r = c.get("/contacts/api/list?triage=1")
    assert [i["id"] for i in r.json()["items"]] == [2]


def test_match_by_email_case_insensitive(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Mario Rossi", email="Mario@Acme.com"))
    s.commit()
    r = c.get("/contacts/api/match?email=mario@acme.com")
    assert r.json()["id"] == 1
    r2 = c.get("/contacts/api/match?email=nope@x.com")
    assert r2.json()["id"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_rubrica_api.py -v`
Expected: FAIL — 404 on `/contacts/api/list` and `/contacts/api/match` (routes don't exist yet).

- [ ] **Step 3: Extend imports and add the two endpoints**

At the top of `app/routers/contacts.py`, extend the import block (`contacts.py:14-20`):

```python
from fastapi import APIRouter, Depends, HTTPException, Form, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.context import current_tenant_id
from app.models.models import (
    Contact, Client, ContactAcquisition, ContactProject, Acquisition, Project,
    Activity, EmailLink, ProjectTechSheet,
)
from app.services.rbac import requires_permission, current_user, has_permission
from app.services.tenant_guard import fetch_or_404
```

Extend `_contact_dict` (`contacts.py:27-38`) to include the new fields:

```python
def _contact_dict(c: Contact) -> dict:
    return {
        "id": c.id,
        "client_id": c.client_id,
        "company_text": c.company_text,
        "source": c.source,
        "name": c.name,
        "role": c.role,
        "email": c.email,
        "phone": c.phone,
        "notes": c.notes,
        "is_primary": c.is_primary,
        "ai_extracted": c.ai_extracted,
    }
```

Append at the end of `contacts.py` (after `delete_contact`, currently `contacts.py:162-173`):

```python
def _link_counts(db: Session, contact_id: int) -> dict:
    n_acq = db.query(ContactAcquisition).filter(
        ContactAcquisition.tenant_id == current_tenant_id(),
        ContactAcquisition.contact_id == contact_id).count()
    n_proj = db.query(ContactProject).filter(
        ContactProject.tenant_id == current_tenant_id(),
        ContactProject.contact_id == contact_id).count()
    return {"acquisitions": n_acq, "projects": n_proj}


@router.get("/contacts/api/list", dependencies=[RequireView])
async def list_contacts_rubrica(
    search: str = None, client_id: int = None, triage: str = None,
    source: str = None, db: Session = Depends(get_db),
):
    q = db.query(Contact).filter(
        Contact.tenant_id == current_tenant_id(),
        Contact.is_active == True,  # noqa: E712
    )
    if client_id:
        q = q.filter(Contact.client_id == client_id)
    if source:
        q = q.filter(Contact.source == source)
    if search:
        like = f"%{search.strip().lower()}%"
        q = q.filter(or_(
            func.lower(Contact.name).like(like),
            func.lower(Contact.email).like(like),
            func.lower(Contact.company_text).like(like),
        ))
    rows = q.order_by(func.lower(Contact.name)).all()
    if _bool(triage):
        acq_ids = {r[0] for r in db.query(ContactAcquisition.contact_id).filter(
            ContactAcquisition.tenant_id == current_tenant_id()).all()}
        proj_ids = {r[0] for r in db.query(ContactProject.contact_id).filter(
            ContactProject.tenant_id == current_tenant_id()).all()}
        rows = [r for r in rows if r.client_id is None
                and r.id not in acq_ids and r.id not in proj_ids]
    out = []
    for r in rows:
        d = _contact_dict(r)
        d["links"] = _link_counts(db, r.id)
        out.append(d)
    return {"items": out}


@router.get("/contacts/api/match", dependencies=[RequireView])
async def match_contact(email: str, db: Session = Depends(get_db)):
    email = (email or "").strip().lower()
    if not email:
        return {"id": None}
    match = db.query(Contact).filter(
        Contact.tenant_id == current_tenant_id(),
        Contact.is_active == True,  # noqa: E712
        func.lower(Contact.email) == email,
    ).first()
    return {"id": match.id, "name": match.name} if match else {"id": None}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_rubrica_api.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/routers/contacts.py tests/test_contacts_rubrica_api.py
git commit -m "feat(contacts): GET /contacts/api/list (search+triage+source) e /match (dedup lookup)"
```

---

## Task 4: Router — `GET /contacts/api/{cid}` detail + `POST /contacts/api/create`

**Files:**
- Modify: `app/routers/contacts.py` (append after Task 3's endpoints)
- Test: `tests/test_contacts_rubrica_api.py` (append)

**Interfaces:**
- Consumes: `_contact_dict`, `_link_counts` (Task 3).
- Produces: `GET /contacts/api/{cid}` → detail dict with `client`, `acquisitions[]`, `projects[]`, `activities[]`, `email_links[]`; `POST /contacts/api/create` → contact dict, or `{"existing_id": id, "contact": {...}}` on email-dedup match (no row created).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_contacts_rubrica_api.py`:

```python
def test_detail_includes_client_acquisitions_projects_activities_emails(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=1, name="Mario Rossi"))
    s.commit()
    s.add(ContactAcquisition(tenant_id=1, contact_id=1, acquisition_id=1, role="referente"))
    s.add(ContactProject(tenant_id=1, contact_id=1, project_id=1, role="DIT"))
    s.add(Activity(tenant_id=1, contact_id=1, subject="Chiamata", occurred_at=__import__("datetime").datetime(2026, 7, 1)))
    s.add(EmailLink(tenant_id=1, provider="google", thread_id="T1", subject="Oggetto",
                    acquisition_id=1, is_active=True))
    s.commit()
    r = c.get("/contacts/api/1")
    assert r.status_code == 200
    b = r.json()
    assert b["client"] == {"id": 1, "name": "Cliente A"}
    assert b["acquisitions"] == [{"id": 1, "title": "Trattativa", "role": "referente"}]
    assert b["projects"] == [{"id": 1, "code": "P1", "title": "Progetto", "role": "DIT"}]
    assert len(b["activities"]) == 1
    assert len(b["email_links"]) == 1
    assert b["email_links"][0]["thread_id"] == "T1"


def test_detail_404_cross_tenant(client):
    c, s = client
    s.add(Tenant(id=2, name="T2", slug="t2", is_active=True))
    s.add(Contact(id=1, tenant_id=2, client_id=None, name="Altro tenant"))
    s.commit()
    r = c.get("/contacts/api/1")
    assert r.status_code == 404


def test_create_standalone_orphan(client):
    c, s = client
    r = c.post("/contacts/api/create", data={
        "name": "Nuovo Contatto", "company_text": "ACME Srl", "email": "n@acme.com"})
    assert r.status_code == 200
    b = r.json()
    assert b["client_id"] is None
    assert b["company_text"] == "ACME Srl"
    assert b["source"] == "manual"


def test_create_dedups_by_email_returns_existing(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Mario Rossi", email="mario@acme.com"))
    s.commit()
    r = c.post("/contacts/api/create", data={"name": "Mario R.", "email": "Mario@ACME.com"})
    assert r.status_code == 200
    b = r.json()
    assert b["existing_id"] == 1
    assert s.query(Contact).count() == 1


def test_create_with_unknown_client_id_404(client):
    c, s = client
    r = c.post("/contacts/api/create", data={"name": "X", "client_id": "999"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_rubrica_api.py -v`
Expected: FAIL — new tests 404 (routes not implemented).

- [ ] **Step 3: Add the detail + create endpoints**

Append to `app/routers/contacts.py` (after the `match_contact` endpoint from Task 3):

```python
def _activity_dict_local(a: Activity) -> dict:
    return {
        "id": a.id,
        "type": a.type.value,
        "direction": a.direction.value if a.direction else None,
        "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
        "subject": a.subject,
        "body": a.body,
    }


@router.get("/contacts/api/{cid}", dependencies=[RequireView])
async def get_contact_detail(cid: int, db: Session = Depends(get_db)):
    c = fetch_or_404(db, Contact, cid, error="Contatto non trovato")
    client = None
    if c.client_id:
        cl = db.query(Client).filter(
            Client.id == c.client_id, Client.tenant_id == current_tenant_id()).first()
        if cl:
            client = {"id": cl.id, "name": cl.name}

    acq_rows = (
        db.query(ContactAcquisition, Acquisition)
        .join(Acquisition, Acquisition.id == ContactAcquisition.acquisition_id)
        .filter(ContactAcquisition.tenant_id == current_tenant_id(),
                ContactAcquisition.contact_id == cid)
        .all()
    )
    acquisitions = [{"id": a.id, "title": a.title, "role": link.role} for link, a in acq_rows]

    proj_rows = (
        db.query(ContactProject, Project)
        .join(Project, Project.id == ContactProject.project_id)
        .filter(ContactProject.tenant_id == current_tenant_id(),
                ContactProject.contact_id == cid)
        .all()
    )
    projects = [{"id": p.id, "code": p.code, "title": p.title, "role": link.role}
                for link, p in proj_rows]

    activities = (
        db.query(Activity)
        .filter(Activity.tenant_id == current_tenant_id(), Activity.contact_id == cid,
                Activity.is_active == True)  # noqa: E712
        .order_by(Activity.occurred_at.desc())
        .limit(20)
        .all()
    )

    aq_ids = [a["id"] for a in acquisitions]
    email_links = []
    if aq_ids:
        email_links = [
            {"id": e.id, "thread_id": e.thread_id, "subject": e.subject,
             "acquisition_id": e.acquisition_id}
            for e in db.query(EmailLink).filter(
                EmailLink.tenant_id == current_tenant_id(),
                EmailLink.acquisition_id.in_(aq_ids),
                EmailLink.is_active == True,  # noqa: E712
            ).order_by(EmailLink.created_at.desc()).all()
        ]

    out = _contact_dict(c)
    out.update({
        "client": client,
        "acquisitions": acquisitions,
        "projects": projects,
        "activities": [_activity_dict_local(a) for a in activities],
        "email_links": email_links,
    })
    return out


@router.post("/contacts/api/create", dependencies=[RequireEdit])
async def create_contact_standalone(
    name: str = Form(...),
    client_id: Optional[int] = Form(None),
    company_text: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name:
        raise HTTPException(400, "Nome richiesto")
    if client_id:
        cl = db.query(Client).filter(
            Client.id == client_id, Client.tenant_id == current_tenant_id()).first()
        if not cl:
            raise HTTPException(404, "Cliente non trovato")
    if email:
        existing = db.query(Contact).filter(
            Contact.tenant_id == current_tenant_id(),
            Contact.is_active == True,  # noqa: E712
            func.lower(Contact.email) == email.strip().lower(),
        ).first()
        if existing:
            return {"existing_id": existing.id, "contact": _contact_dict(existing)}
    c = Contact(
        tenant_id=current_tenant_id(), client_id=client_id, name=name,
        company_text=company_text if not client_id else None,
        role=role, email=email, phone=phone, notes=notes, source="manual",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _contact_dict(c)
```

Note: `get_contact_detail` is registered AFTER `list_contacts_rubrica`/`match_contact` (Task 3) in file order, satisfying the route-collision constraint from Global Constraints.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_rubrica_api.py -v`
Expected: 9 passed (4 from Task 3 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add app/routers/contacts.py tests/test_contacts_rubrica_api.py
git commit -m "feat(contacts): GET /contacts/api/{id} dettaglio + POST /contacts/api/create standalone con dedup"
```

---

## Task 5: Router — extend `PUT /contacts/api/{cid}` + `POST`/`DELETE /contacts/api/{id}/link`

**Files:**
- Modify: `app/routers/contacts.py:125-159` (existing `update_contact`) and append new link/unlink endpoints
- Test: `tests/test_contacts_rubrica_api.py` (append)

**Interfaces:**
- Produces: extended `PUT /contacts/api/{cid}` (adds `client_id`, `company_text`, `source` — `client_id` uses the "empty/`0` clears, missing = no change" sentinel convention, memory `feedback_empty_multipart_is_none`); `POST /contacts/api/{id}/link` Form(`target_type` in `client|acquisition|project`, `target_id`, `role?`) → `{"ok": true, "already_linked": bool}`; `DELETE /contacts/api/{id}/link` Form(`target_type`, `target_id`) → `{"ok": true}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_contacts_rubrica_api.py`:

```python
def test_update_contact_sets_company_text_and_source(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Orfano"))
    s.commit()
    r = c.put("/contacts/api/1", data={"company_text": "ACME", "source": "email"})
    assert r.status_code == 200
    b = r.json()
    assert b["company_text"] == "ACME"
    assert b["source"] == "email"


def test_update_contact_client_id_sentinel_zero_clears(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=1, name="Con cliente"))
    s.commit()
    r = c.put("/contacts/api/1", data={"client_id": "0"})
    assert r.status_code == 200
    assert r.json()["client_id"] is None


def test_update_contact_client_id_sets_new_value(client):
    c, s = client
    s.add(Client(id=2, tenant_id=1, name="Cliente B"))
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Orfano"))
    s.commit()
    r = c.put("/contacts/api/1", data={"client_id": "2"})
    assert r.status_code == 200
    assert r.json()["client_id"] == 2


def test_link_to_acquisition_then_idempotent(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Orfano"))
    s.commit()
    r = c.post("/contacts/api/1/link", data={"target_type": "acquisition", "target_id": "1", "role": "referente"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "already_linked": False}
    r2 = c.post("/contacts/api/1/link", data={"target_type": "acquisition", "target_id": "1"})
    assert r2.json() == {"ok": True, "already_linked": True}
    assert s.query(ContactAcquisition).count() == 1


def test_link_to_project(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Orfano"))
    s.commit()
    r = c.post("/contacts/api/1/link", data={"target_type": "project", "target_id": "1"})
    assert r.status_code == 200
    assert s.query(ContactProject).filter_by(contact_id=1, project_id=1).count() == 1


def test_link_to_client_sets_fk_directly(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Orfano"))
    s.commit()
    r = c.post("/contacts/api/1/link", data={"target_type": "client", "target_id": "1"})
    assert r.status_code == 200
    s.refresh(s.get(Contact, 1))
    assert s.get(Contact, 1).client_id == 1


def test_unlink_acquisition(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Orfano"))
    s.commit()
    s.add(ContactAcquisition(tenant_id=1, contact_id=1, acquisition_id=1))
    s.commit()
    r = c.request("DELETE", "/contacts/api/1/link", data={"target_type": "acquisition", "target_id": "1"})
    assert r.status_code == 200
    assert s.query(ContactAcquisition).count() == 0


def test_link_invalid_target_type_400(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Orfano"))
    s.commit()
    r = c.post("/contacts/api/1/link", data={"target_type": "bogus", "target_id": "1"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_rubrica_api.py -v`
Expected: FAIL — `client_id`/`company_text`/`source` ignored by `update_contact`; `/link` routes 404.

- [ ] **Step 3: Extend `update_contact` and add link/unlink**

Replace `update_contact` in `app/routers/contacts.py:125-159`:

```python
@router.put("/contacts/api/{cid}", dependencies=[RequireEdit])
async def update_contact(
    cid: int,
    name: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    is_primary: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    company_text: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    c = db.query(Contact).filter(
        Contact.id == cid,
        Contact.tenant_id == current_tenant_id(),
        Contact.is_active == True,  # noqa: E712
    ).first()
    if not c:
        raise HTTPException(404, "Contatto non trovato")
    if name is not None:
        c.name = name.strip()
    if role is not None:
        c.role = role
    if email is not None:
        c.email = email
    if phone is not None:
        c.phone = phone
    if notes is not None:
        c.notes = notes
    if is_primary is not None:
        c.is_primary = _bool(is_primary)
    if client_id is not None:
        # sentinel: "" o "0" -> pulisce (memoria feedback_empty_multipart_is_none)
        if client_id.strip() in ("", "0"):
            c.client_id = None
        else:
            cid_int = int(client_id)
            cl = db.query(Client).filter(
                Client.id == cid_int, Client.tenant_id == current_tenant_id()).first()
            if not cl:
                raise HTTPException(404, "Cliente non trovato")
            c.client_id = cid_int
    if company_text is not None:
        c.company_text = company_text
    if source is not None:
        c.source = source
    if c.is_primary:
        _sync_primary(db, c)
    db.commit()
    db.refresh(c)
    return _contact_dict(c)
```

Append, after `create_contact_standalone` (end of `contacts.py`):

```python
_LINK_TYPES = ("client", "acquisition", "project")


def _check_link_permission(user, target_type: str) -> None:
    if not has_permission(user, "edit_clients"):
        raise HTTPException(403, "Permesso negato")
    if target_type == "acquisition" and not has_permission(user, "manage_acquisitions"):
        raise HTTPException(403, "Permesso negato (manage_acquisitions)")
    if target_type == "project" and not has_permission(user, "edit_projects"):
        raise HTTPException(403, "Permesso negato (edit_projects)")


@router.post("/contacts/api/{cid}/link")
async def link_contact(
    cid: int,
    request: Request,
    target_type: str = Form(...),
    target_id: int = Form(...),
    role: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    if target_type not in _LINK_TYPES:
        raise HTTPException(400, "target_type deve essere client|acquisition|project")
    user = current_user(request)
    _check_link_permission(user, target_type)
    c = fetch_or_404(db, Contact, cid, error="Contatto non trovato")

    if target_type == "client":
        cl = db.query(Client).filter(
            Client.id == target_id, Client.tenant_id == current_tenant_id()).first()
        if not cl:
            raise HTTPException(404, "Cliente non trovato")
        already = c.client_id == target_id
        c.client_id = target_id
        db.commit()
        return {"ok": True, "already_linked": already}

    if target_type == "acquisition":
        fetch_or_404(db, Acquisition, target_id, error="Trattativa non trovata")
        existing = db.query(ContactAcquisition).filter(
            ContactAcquisition.tenant_id == current_tenant_id(),
            ContactAcquisition.contact_id == cid,
            ContactAcquisition.acquisition_id == target_id,
        ).first()
        if existing:
            return {"ok": True, "already_linked": True}
        db.add(ContactAcquisition(tenant_id=current_tenant_id(), contact_id=cid,
                                   acquisition_id=target_id, role=role))
        db.commit()
        return {"ok": True, "already_linked": False}

    # project
    fetch_or_404(db, Project, target_id, error="Progetto non trovato")
    existing = db.query(ContactProject).filter(
        ContactProject.tenant_id == current_tenant_id(),
        ContactProject.contact_id == cid,
        ContactProject.project_id == target_id,
    ).first()
    if existing:
        return {"ok": True, "already_linked": True}
    db.add(ContactProject(tenant_id=current_tenant_id(), contact_id=cid,
                          project_id=target_id, role=role))
    db.commit()
    return {"ok": True, "already_linked": False}


@router.delete("/contacts/api/{cid}/link")
async def unlink_contact(
    cid: int,
    request: Request,
    target_type: str = Form(...),
    target_id: int = Form(...),
    db: Session = Depends(get_db),
):
    if target_type not in _LINK_TYPES:
        raise HTTPException(400, "target_type deve essere client|acquisition|project")
    user = current_user(request)
    _check_link_permission(user, target_type)
    c = fetch_or_404(db, Contact, cid, error="Contatto non trovato")

    if target_type == "client":
        if c.client_id == target_id:
            c.client_id = None
            db.commit()
        return {"ok": True}
    if target_type == "acquisition":
        db.query(ContactAcquisition).filter(
            ContactAcquisition.tenant_id == current_tenant_id(),
            ContactAcquisition.contact_id == cid,
            ContactAcquisition.acquisition_id == target_id,
        ).delete()
        db.commit()
        return {"ok": True}
    db.query(ContactProject).filter(
        ContactProject.tenant_id == current_tenant_id(),
        ContactProject.contact_id == cid,
        ContactProject.project_id == target_id,
    ).delete()
    db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_rubrica_api.py -v`
Expected: 17 passed (9 from Tasks 3-4 + 8 new).

- [ ] **Step 5: Commit**

```bash
git add app/routers/contacts.py tests/test_contacts_rubrica_api.py
git commit -m "feat(contacts): PUT esteso (client_id/company_text/source) + link/unlink client|acquisition|project"
```

---

## Task 6: Service — `contact_extract.py` deterministic extraction

**Files:**
- Create: `app/services/contact_extract.py`
- Test: `tests/test_contact_extract.py` (new)

**Interfaces:**
- Produces: `extract_from_thread(thread: dict) -> list[dict]` where `thread` is the shape returned by `app.services.gmail.get_thread` (`{"id": str, "messages": [{"from", "to", "cc", "subject", "date", "snippet", "body_html", "body_text", "attachments"}]}`). Each candidate: `{"name": str, "email": str, "phone": Optional[str], "role": Optional[str], "company_text": Optional[str], "source": "email"}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_contact_extract.py`:

```python
from app.services.contact_extract import extract_from_thread, _parse_address


def test_parse_address_display_name_and_bare():
    assert _parse_address('"Mario Rossi" <mario@acme.com>') == {"name": "Mario Rossi", "email": "mario@acme.com"}
    assert _parse_address("mario@acme.com") == {"name": "mario", "email": "mario@acme.com"}
    assert _parse_address("") is None
    assert _parse_address("not an address") is None


def test_extract_from_thread_dedups_participants_by_email():
    thread = {
        "id": "T1",
        "messages": [
            {"from": "Mario Rossi <mario@acme.com>", "to": "Noi <noi@casa.it>", "cc": "",
             "body_text": "Ciao,\ngrazie.\n"},
            {"from": "Noi <noi@casa.it>", "to": "Mario Rossi <mario@acme.com>", "cc": "",
             "body_text": "Prego."},
        ],
    }
    cands = extract_from_thread(thread)
    emails = sorted(c["email"] for c in cands)
    assert emails == ["mario@acme.com", "noi@casa.it"]


def test_extract_pulls_phone_and_role_from_signature_block():
    body = (
        "Ciao,\n\nconfermo l'invio dei materiali.\n\n"
        "Mario Rossi\nDIT Supervisor\nAcme Post S.r.l.\n"
        "Tel: +39 02 1234 5678\nmario@acme.com\n"
    )
    thread = {
        "id": "T1",
        "messages": [{"from": "Mario Rossi <mario@acme.com>", "to": "a@b.com", "cc": "",
                      "body_text": body}],
    }
    cands = extract_from_thread(thread)
    m = next(c for c in cands if c["email"] == "mario@acme.com")
    assert m["phone"] and "1234" in m["phone"]
    assert m["company_text"] and "acme" in m["company_text"].lower()
    assert m["source"] == "email"


def test_extract_ignores_quoted_reply_chain_for_signature():
    body = (
        "Va bene, procedo.\n\nMario Rossi\nProduttore\n\n"
        "Il giorno 1 luglio 2026 Anna Bianchi ha scritto:\n"
        "> vecchio messaggio\n> altra riga citata\n"
    )
    thread = {
        "id": "T1",
        "messages": [{"from": "mario@acme.com", "to": "a@b.com", "cc": "", "body_text": body}],
    }
    cands = extract_from_thread(thread)
    m = next(c for c in cands if c["email"] == "mario@acme.com")
    assert m["role"] == "Produttore"


def test_extract_empty_thread_returns_empty_list():
    assert extract_from_thread({"id": "T1", "messages": []}) == []
    assert extract_from_thread({}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contact_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.contact_extract'`.

- [ ] **Step 3: Write `app/services/contact_extract.py`**

```python
"""app/services/contact_extract.py — Client email F3.

Estrazione contatti da thread email: ibrido deterministico (nessuna
dipendenza AI, regex su header From/To/Cc + euristiche sul blocco firma)
+ arricchimento AI opzionale (enrich_with_ai), chiamato solo su richiesta
esplicita utente. Best-effort, mai eccezione al chiamante."""
from __future__ import annotations

import json
import re
from typing import Optional

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s\-.]{7,}\d)(?!\d)")
_COMPANY_HINTS = ("srl", "s.r.l", "spa", "s.p.a", "ltd", "llc", "gmbh", "inc", "sas", "snc")
_QUOTE_MARKERS = ("ha scritto:", "wrote:")


def _parse_address(raw: str) -> Optional[dict]:
    """'Display Name <addr@x.com>' o 'addr@x.com' -> {name, email}. None se
    non contiene un indirizzo valido."""
    raw = (raw or "").strip()
    if not raw:
        return None
    m = re.match(r'^"?([^"<]*)"?\s*<([^<>]+)>$', raw)
    if m:
        name = m.group(1).strip()
        email = m.group(2).strip()
    else:
        email_m = EMAIL_RE.search(raw)
        if not email_m:
            return None
        email = email_m.group(0)
        name = raw[: email_m.start()].strip(' "<')
    if not EMAIL_RE.fullmatch(email):
        return None
    return {"name": name or email.split("@")[0], "email": email.lower()}


def _participants(thread: dict) -> list[dict]:
    seen: dict[str, dict] = {}
    for msg in thread.get("messages") or []:
        for field in ("from", "to", "cc"):
            raw = msg.get(field) or ""
            for part in raw.split(","):
                cand = _parse_address(part)
                if cand and cand["email"] not in seen:
                    seen[cand["email"]] = cand
    return list(seen.values())


def _signature_block(text: str) -> list[str]:
    """Ultime righe non vuote del corpo, tagliate alla prima riga di
    citazione (euristica firma dell'ultimo messaggio)."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    cut = len(lines)
    for i, l in enumerate(lines):
        low = l.lower()
        if l.startswith(">") or any(marker in low for marker in _QUOTE_MARKERS):
            cut = i
            break
    return lines[:cut][-8:]


def _extract_signature_fields(lines: list[str]) -> dict:
    out: dict = {}
    for l in lines:
        if "phone" not in out:
            pm = PHONE_RE.search(l)
            if pm and sum(ch.isdigit() for ch in pm.group(1)) >= 8:
                out["phone"] = pm.group(1).strip()
        low = l.lower()
        if "company_text" not in out and any(h in low for h in _COMPANY_HINTS):
            out["company_text"] = l
        elif ("role" not in out and not EMAIL_RE.search(l) and not PHONE_RE.search(l)
              and 1 <= len(l.split()) <= 6 and not any(h in low for h in _COMPANY_HINTS)):
            out["role"] = l
    return out


def extract_from_thread(thread: dict) -> list[dict]:
    """Ritorna candidati deterministici: partecipanti (From/To/Cc) arricchiti
    con phone/role/company_text euristici dal blocco firma dell'ultimo
    messaggio con corpo testuale. Dedup per email."""
    candidates = _participants(thread or {})
    if not candidates:
        return []
    sig_fields: dict = {}
    for msg in reversed((thread or {}).get("messages") or []):
        body = msg.get("body_text") or ""
        if body.strip():
            sig_fields = _extract_signature_fields(_signature_block(body))
            break
    for c in candidates:
        c["phone"] = sig_fields.get("phone")
        c["role"] = sig_fields.get("role")
        c["company_text"] = sig_fields.get("company_text")
        c["source"] = "email"
    return candidates


def enrich_with_ai(candidate: dict, signature_text: str, provider) -> dict:
    """Arricchisce role/company_text dalla firma via LLM. Best-effort:
    provider assente/errore -> candidato invariato. Non alza mai eccezioni."""
    if not provider or not signature_text:
        return candidate
    prompt = (
        "Estrai da questa firma email SOLO ruolo e azienda della persona, "
        'in JSON: {"role": str|null, "company_text": str|null}. '
        f"Nome noto: {candidate.get('name')}. Firma:\n{signature_text}"
    )
    try:
        raw = provider.complete(
            "Sei un estrattore di dati strutturati. Rispondi SOLO con JSON valido.",
            prompt, max_tokens=200, temperature=0,
        )
        data = json.loads((raw or "").strip().strip("`"))
        out = dict(candidate)
        if data.get("role"):
            out["role"] = data["role"]
        if data.get("company_text"):
            out["company_text"] = data["company_text"]
        return out
    except Exception:
        return candidate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contact_extract.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/contact_extract.py tests/test_contact_extract.py
git commit -m "feat(contacts): contact_extract.py — estrazione deterministica partecipanti+firma da thread"
```

---

## Task 7: Router — `POST /contacts/api/extract` + `POST /contacts/api/extract/enrich`

**Files:**
- Modify: `app/routers/contacts.py` (imports + append)
- Test: `tests/test_contacts_extract_api.py` (new)

**Interfaces:**
- Consumes: `contact_extract.extract_from_thread`, `contact_extract.enrich_with_ai` (Task 6); `gmail.get_thread` (existing, `app/services/gmail.py:132`); `get_provider_for_user` (existing, `app/services/ai_provider.py:1091`).
- Produces: `POST /contacts/api/extract` Form(`thread_id`) → `{"candidates": [...]}`; `POST /contacts/api/extract/enrich` Form(`name?`, `email?`, `role?`, `phone?`, `company_text?`, `signature`) → enriched candidate dict.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_contacts_extract_api.py` (fixture identical to `tests/test_contacts_rubrica_api.py`; duplicated here per the codebase's existing per-file-fixture convention, e.g. `tests/test_email_links_api.py` vs `tests/test_contacts_rubrica_api.py`):

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole
from app.services.auth import create_access_token


@pytest.fixture
def client(monkeypatch):
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", e)
    monkeypatch.setattr(database, "SessionLocal", S)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
               hashed_password="x", role=UserRole.admin, is_active=True))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_extract_returns_candidates_from_thread(client, monkeypatch):
    c, s = client
    import app.routers.contacts as contacts_mod
    monkeypatch.setattr(contacts_mod.gmail, "get_thread", lambda db, uid, tid: {
        "id": tid,
        "messages": [{"from": "Mario Rossi <mario@acme.com>", "to": "a@b.com", "cc": "",
                      "body_text": "Ciao\n\nMario Rossi\nDIT\nmario@acme.com"}],
    })
    r = c.post("/contacts/api/extract", data={"thread_id": "T1"})
    assert r.status_code == 200
    cands = r.json()["candidates"]
    assert any(x["email"] == "mario@acme.com" for x in cands)


def test_extract_no_gmail_token_returns_empty_candidates(client, monkeypatch):
    c, s = client
    import app.routers.contacts as contacts_mod
    monkeypatch.setattr(contacts_mod.gmail, "get_thread", lambda db, uid, tid: None)
    r = c.post("/contacts/api/extract", data={"thread_id": "T1"})
    assert r.status_code == 200
    assert r.json()["candidates"] == []


def test_extract_enrich_no_provider_returns_candidate_unchanged(client, monkeypatch):
    c, s = client
    import app.routers.contacts as contacts_mod
    monkeypatch.setattr(contacts_mod, "get_provider_for_user", lambda uid, db: None)
    r = c.post("/contacts/api/extract/enrich", data={
        "name": "Mario", "email": "mario@acme.com", "signature": "Mario Rossi\nDIT\nAcme Srl"})
    assert r.status_code == 200
    b = r.json()
    assert b["name"] == "Mario"
    assert b["email"] == "mario@acme.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_extract_api.py -v`
Expected: FAIL — 404 on both new routes.

- [ ] **Step 3: Extend imports and add the two endpoints**

Add to the top of `app/routers/contacts.py` (alongside the imports from Task 3):

```python
from app.services import gmail
from app.services import contact_extract
from app.services.ai_provider import get_provider_for_user
```

Append at the end of `app/routers/contacts.py`:

```python
@router.post("/contacts/api/extract", dependencies=[RequireEdit])
async def extract_contacts(
    request: Request, thread_id: str = Form(...), db: Session = Depends(get_db),
):
    user = current_user(request)
    thread = gmail.get_thread(db, user.id, thread_id)
    if not thread:
        return {"candidates": []}
    return {"candidates": contact_extract.extract_from_thread(thread)}


@router.post("/contacts/api/extract/enrich", dependencies=[RequireEdit])
async def extract_contacts_enrich(
    request: Request,
    signature: str = Form(...),
    name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    company_text: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = current_user(request)
    candidate = {"name": name, "email": email, "role": role, "phone": phone,
                 "company_text": company_text}
    provider = get_provider_for_user(user.id, db)
    return contact_extract.enrich_with_ai(candidate, signature, provider)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_extract_api.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/routers/contacts.py tests/test_contacts_extract_api.py
git commit -m "feat(contacts): POST /contacts/api/extract e /extract/enrich (estrazione ibrida da thread)"
```

---

## Task 8: Router — `POST /contacts/api/from-tech-sheet` (bridge scheda tecnica)

**Files:**
- Modify: `app/routers/contacts.py` (append)
- Test: `tests/test_contacts_tech_sheet_bridge.py` (new)

**Interfaces:**
- Consumes: `ProjectTechSheet` (existing model, `app/models/models.py:4175`), its `data["contacts"]` shape `[{role, resource_id, name_text, email, phone, contact_id?}]` (existing, `app/models/models.py:4204` docstring / `scripts/seed_demo.py` etc.).
- Produces: `POST /contacts/api/from-tech-sheet` Form(`project_id`, `idx`, `name`, `email?`, `phone?`, `role?`) → `{"id": int, "existing": bool, "name": str}`. Writes `contact_id` into `ProjectTechSheet.data["contacts"][idx]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_contacts_tech_sheet_bridge.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, User, UserRole, Client, Project, ProjectTechSheet, Contact, ContactProject,
)
from app.services.auth import create_access_token


@pytest.fixture
def client(monkeypatch):
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", e)
    monkeypatch.setattr(database, "SessionLocal", S)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
               hashed_password="x", role=UserRole.admin, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Cliente"))
    s.add(Project(id=1, tenant_id=1, code="P1", title="Progetto", client_id=1))
    s.add(ProjectTechSheet(id=1, tenant_id=1, project_id=1, data={
        "contacts": [{"role": "DIT", "resource_id": None, "name_text": "Mario Rossi",
                      "email": "mario@acme.com", "phone": "123"}],
    }))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_from_tech_sheet_creates_contact_links_project_and_writes_back_id(client):
    c, s = client
    r = c.post("/contacts/api/from-tech-sheet", data={
        "project_id": "1", "idx": "0", "name": "Mario Rossi",
        "email": "mario@acme.com", "phone": "123", "role": "DIT"})
    assert r.status_code == 200
    b = r.json()
    assert b["existing"] is False
    cid = b["id"]
    assert s.query(ContactProject).filter_by(contact_id=cid, project_id=1).count() == 1
    ts = s.query(ProjectTechSheet).filter_by(project_id=1).first()
    assert ts.data["contacts"][0]["contact_id"] == cid


def test_from_tech_sheet_dedups_by_email_reuses_existing_contact(client):
    c, s = client
    s.add(Contact(id=5, tenant_id=1, client_id=None, name="Mario Rossi", email="mario@acme.com"))
    s.commit()
    r = c.post("/contacts/api/from-tech-sheet", data={
        "project_id": "1", "idx": "0", "name": "Mario Rossi", "email": "mario@acme.com"})
    assert r.status_code == 200
    b = r.json()
    assert b["existing"] is True
    assert b["id"] == 5
    assert s.query(Contact).count() == 1


def test_from_tech_sheet_invalid_idx_400(client):
    c, s = client
    r = c.post("/contacts/api/from-tech-sheet", data={
        "project_id": "1", "idx": "9", "name": "X"})
    assert r.status_code == 400


def test_from_tech_sheet_unknown_project_404(client):
    c, s = client
    r = c.post("/contacts/api/from-tech-sheet", data={
        "project_id": "999", "idx": "0", "name": "X"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_tech_sheet_bridge.py -v`
Expected: FAIL — 404 on `/contacts/api/from-tech-sheet`.

- [ ] **Step 3: Add the endpoint**

Add `Project` (already imported in Task 3/4) and `ProjectTechSheet` (already added to the import in Task 3) — confirm both are present in the top-of-file import from Task 3. Append at the end of `app/routers/contacts.py`:

```python
@router.post("/contacts/api/from-tech-sheet")
async def create_contact_from_tech_sheet(
    request: Request,
    project_id: int = Form(...),
    idx: int = Form(...),
    name: str = Form(...),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = current_user(request)
    if not has_permission(user, "edit_projects"):
        raise HTTPException(403, "Permesso negato")
    proj = fetch_or_404(db, Project, project_id, error="Progetto non trovato")
    ts = db.query(ProjectTechSheet).filter(
        ProjectTechSheet.project_id == proj.id,
        ProjectTechSheet.tenant_id == current_tenant_id(),
    ).first()
    if not ts:
        raise HTTPException(404, "Scheda tecnica non trovata")
    contacts_arr = list((ts.data or {}).get("contacts") or [])
    if idx < 0 or idx >= len(contacts_arr):
        raise HTTPException(400, "Indice contatto non valido")
    name = name.strip()
    if not name:
        raise HTTPException(400, "Nome richiesto")

    existing = None
    if email:
        existing = db.query(Contact).filter(
            Contact.tenant_id == current_tenant_id(),
            Contact.is_active == True,  # noqa: E712
            func.lower(Contact.email) == email.strip().lower(),
        ).first()
    if existing:
        c = existing
    else:
        c = Contact(tenant_id=current_tenant_id(), client_id=None, name=name,
                    role=role, email=email, phone=phone, source="manual")
        db.add(c)
        db.flush()

    link_exists = db.query(ContactProject).filter(
        ContactProject.tenant_id == current_tenant_id(),
        ContactProject.contact_id == c.id, ContactProject.project_id == proj.id,
    ).first()
    if not link_exists:
        db.add(ContactProject(tenant_id=current_tenant_id(), contact_id=c.id,
                              project_id=proj.id, role=role))

    new_arr = list(contacts_arr)
    new_arr[idx] = dict(new_arr[idx], contact_id=c.id)
    new_data = dict(ts.data or {})
    new_data["contacts"] = new_arr
    ts.data = new_data

    db.commit()
    db.refresh(c)
    return {"id": c.id, "existing": existing is not None, "name": c.name}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_tech_sheet_bridge.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/routers/contacts.py tests/test_contacts_tech_sheet_bridge.py
git commit -m "feat(contacts): POST /contacts/api/from-tech-sheet — ponte scheda tecnica -> rubrica"
```

---

## Task 9: Router — `GET /contacts/api/notify-badge` (notifica on-demand)

**Files:**
- Modify: `app/routers/contacts.py` (append — literal path, must still be added before... N/A, this is a sibling literal path to `list`/`match`, no new collision since `{cid}` GET already exists in the file from Task 4; `notify-badge` is added AFTER `{cid}` in file order which WOULD collide. Add it BEFORE `get_contact_detail`'s line, i.e. insert it into the file among the Task 3 literal routes, not appended at the very end.)
- Test: `tests/test_contacts_notify_badge.py` (new)

**Interfaces:**
- Consumes: `ContactAcquisition`, `Contact`, `EmailLink`, `gmail.list_threads` (existing, `app/services/gmail.py:112`).
- Produces: `GET /contacts/api/notify-badge?acquisition_id=` → `{"count": int}`. Never 500 (best-effort, matches `gmail.list_threads`'s own no-token → `{"threads": [], ...}` contract).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_contacts_notify_badge.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, User, UserRole, Client, Acquisition, Contact, ContactAcquisition, EmailLink,
)
from app.services.auth import create_access_token


@pytest.fixture
def client(monkeypatch):
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", e)
    monkeypatch.setattr(database, "SessionLocal", S)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
               hashed_password="x", role=UserRole.admin, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Cliente"))
    s.add(Acquisition(id=1, tenant_id=1, title="Trattativa", client_id=1))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_badge_zero_when_no_linked_contacts_have_email(client):
    c, s = client
    r = c.get("/contacts/api/notify-badge?acquisition_id=1")
    assert r.status_code == 200
    assert r.json() == {"count": 0}


def test_badge_no_gmail_token_returns_zero_not_500(client, monkeypatch):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Mario", email="mario@acme.com"))
    s.commit()
    s.add(ContactAcquisition(tenant_id=1, contact_id=1, acquisition_id=1))
    s.commit()
    import app.routers.contacts as contacts_mod
    monkeypatch.setattr(contacts_mod.gmail, "list_threads",
                        lambda db, uid, **kw: {"threads": [], "next_page_token": None})
    r = c.get("/contacts/api/notify-badge?acquisition_id=1")
    assert r.status_code == 200
    assert r.json() == {"count": 0}


def test_badge_counts_threads_excluding_already_linked(client, monkeypatch):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Mario", email="mario@acme.com"))
    s.commit()
    s.add(ContactAcquisition(tenant_id=1, contact_id=1, acquisition_id=1))
    s.add(EmailLink(tenant_id=1, provider="google", thread_id="TALREADY", subject="x",
                    acquisition_id=1, is_active=True))
    s.commit()
    import app.routers.contacts as contacts_mod
    monkeypatch.setattr(contacts_mod.gmail, "list_threads",
                        lambda db, uid, **kw: {"threads": [{"id": "TALREADY"}, {"id": "TNEW"}],
                                                "next_page_token": None})
    r = c.get("/contacts/api/notify-badge?acquisition_id=1")
    assert r.status_code == 200
    assert r.json() == {"count": 1}


def test_badge_unknown_acquisition_404(client):
    c, s = client
    r = c.get("/contacts/api/notify-badge?acquisition_id=999")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_notify_badge.py -v`
Expected: FAIL — 404 on `/contacts/api/notify-badge` (or a routing collision error if inserted after `{cid}`).

- [ ] **Step 3: Insert the endpoint BEFORE `get_contact_detail`**

In `app/routers/contacts.py`, insert this function immediately before `@router.get("/contacts/api/{cid}", ...)` (the `get_contact_detail` function added in Task 4) — i.e. between `match_contact` (Task 3) and `get_contact_detail` (Task 4) in file order, so the literal `/notify-badge` path is scanned before the `{cid}` pattern:

```python
@router.get("/contacts/api/notify-badge")
async def contacts_notify_badge(
    acquisition_id: int, request: Request, db: Session = Depends(get_db),
):
    user = current_user(request)
    if not has_permission(user, "view_acquisitions"):
        raise HTTPException(403, "Permesso negato")
    acq = fetch_or_404(db, Acquisition, acquisition_id, error="Trattativa non trovata")

    contacts = (
        db.query(Contact)
        .join(ContactAcquisition, ContactAcquisition.contact_id == Contact.id)
        .filter(ContactAcquisition.tenant_id == current_tenant_id(),
                ContactAcquisition.acquisition_id == acq.id,
                Contact.tenant_id == current_tenant_id(),
                Contact.email.isnot(None), Contact.email != "")
        .all()
    )
    if not contacts:
        return {"count": 0}
    known_emails = sorted({c.email.strip().lower() for c in contacts if c.email})
    if not known_emails:
        return {"count": 0}

    already_linked = {
        e.thread_id for e in db.query(EmailLink).filter(
            EmailLink.tenant_id == current_tenant_id(),
            EmailLink.acquisition_id == acq.id,
            EmailLink.is_active == True,  # noqa: E712
        ).all()
    }
    query = " OR ".join(f"from:{e}" for e in known_emails)
    res = gmail.list_threads(db, user.id, query=query, max_results=25)
    threads = res.get("threads") or []
    count = sum(1 for t in threads if t.get("id") not in already_linked)
    return {"count": count}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_notify_badge.py -v`
Expected: 4 passed. Also re-run `.venv/Scripts/python.exe -m pytest tests/test_contacts_rubrica_api.py -v` to confirm no route regression from the insertion (17 still passed).

- [ ] **Step 5: Commit**

```bash
git add app/routers/contacts.py tests/test_contacts_notify_badge.py
git commit -m "feat(contacts): GET /contacts/api/notify-badge — notifica on-demand email note non agganciate"
```

---

## Task 10: AI copilot — extend `propose_contact` with `acquisition_id`/`project_id` links

**Files:**
- Modify: `app/services/ai_tools.py:1215-1227` (the `propose_contact` tool descriptor)
- Modify: `app/services/ai_assistant.py:39-41` (imports) and `app/services/ai_assistant.py:4514-4525` (the `_h_propose_contact` handler)
- Test: `tests/test_propose_contact_links.py` (new)

**Interfaces:**
- Consumes: `ContactAcquisition`, `ContactProject` (Task 1).
- Produces: `_h_propose_contact(db, data) -> dict` now accepts optional `acquisition_id`/`project_id`/`company_text`, `client_id` becomes optional (breaking change to the old `required: [client_id, name]` — now `required: [name]`, matching the spec goal of standalone contacts). Registered via `@ai_capability("propose_contact")` — unchanged decorator call, still above the `_ACTION_HANDLERS` snapshot at `ai_assistant.py:4609`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_propose_contact_links.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Acquisition, Project, Contact, ContactAcquisition, ContactProject,
)
from app.context import current_tenant_id  # noqa: F401 (ensures context module loaded)


@pytest.fixture
def db_session(monkeypatch):
    import app.context as ctx
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Cliente"))
    s.add(Acquisition(id=1, tenant_id=1, title="Trattativa", client_id=1))
    s.add(Project(id=1, tenant_id=1, code="P1", title="Progetto", client_id=1))
    s.commit()
    monkeypatch.setattr(ctx, "current_tenant_id", lambda: 1)
    yield s


def test_propose_contact_standalone_no_client_id(db_session):
    from app.services.ai_assistant import _h_propose_contact
    res = _h_propose_contact(db_session, {"name": "Mario Rossi"})
    assert res["created"] is True
    c = db_session.query(Contact).filter_by(id=res["contact_id"]).first()
    assert c.client_id is None
    assert c.source == "ai"


def test_propose_contact_with_acquisition_and_project_links(db_session):
    from app.services.ai_assistant import _h_propose_contact
    res = _h_propose_contact(db_session, {
        "name": "Anna Bianchi", "acquisition_id": 1, "project_id": 1, "role": "Producer"})
    assert res["created"] is True
    cid = res["contact_id"]
    assert db_session.query(ContactAcquisition).filter_by(contact_id=cid, acquisition_id=1).count() == 1
    assert db_session.query(ContactProject).filter_by(contact_id=cid, project_id=1).count() == 1


def test_propose_contact_unknown_acquisition_raises(db_session):
    from app.services.ai_assistant import _h_propose_contact
    with pytest.raises(ValueError):
        _h_propose_contact(db_session, {"name": "X", "acquisition_id": 999})


def test_propose_contact_missing_name_raises(db_session):
    from app.services.ai_assistant import _h_propose_contact
    with pytest.raises(ValueError):
        _h_propose_contact(db_session, {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_propose_contact_links.py -v`
Expected: FAIL — `test_propose_contact_standalone_no_client_id` fails (`ValueError: Servono 'name' e 'client_id'`); `test_propose_contact_with_acquisition_and_project_links` fails (no links created, current handler ignores `acquisition_id`/`project_id`).

- [ ] **Step 3: Extend the import and the handler**

In `app/services/ai_assistant.py:39-41`, extend the import:

```python
from app.models.models import (
    Acquisition, AcquisitionStage, Activity, ActivityType, Contact,
    ContactAcquisition, ContactProject,
)
```

Replace `_h_propose_contact` at `app/services/ai_assistant.py:4514-4525`:

```python
@ai_capability("propose_contact")
def _h_propose_contact(db: Session, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Serve 'name'")
    cid = data.get("client_id")
    if cid is not None:
        cl = db.query(Client).filter(
            Client.id == cid, Client.tenant_id == current_tenant_id()).first()
        if not cl:
            raise ValueError(f"Cliente {cid} non trovato")
    c = Contact(
        tenant_id=current_tenant_id(), client_id=cid, name=name,
        role=data.get("role"), email=data.get("email"), phone=data.get("phone"),
        company_text=data.get("company_text") if not cid else None,
        source="ai", ai_extracted=True,
    )
    db.add(c)
    db.flush()

    links_msg = []
    aid = data.get("acquisition_id")
    if aid:
        acq = db.query(Acquisition).filter(
            Acquisition.id == aid, Acquisition.tenant_id == current_tenant_id()).first()
        if not acq:
            raise ValueError(f"Trattativa {aid} non trovata")
        db.add(ContactAcquisition(tenant_id=current_tenant_id(), contact_id=c.id, acquisition_id=aid))
        links_msg.append(f"trattativa {aid}")
    pid = data.get("project_id")
    if pid:
        proj = db.query(Project).filter(
            Project.id == pid, Project.tenant_id == current_tenant_id()).first()
        if not proj:
            raise ValueError(f"Progetto {pid} non trovato")
        db.add(ContactProject(tenant_id=current_tenant_id(), contact_id=c.id, project_id=pid))
        links_msg.append(f"progetto {pid}")
    db.flush()

    extra = f" (collegato a {', '.join(links_msg)})" if links_msg else ""
    return {"created": True, "contact_id": c.id,
            "message": f"Contatto '{name}' aggiunto alla rubrica{extra}."}
```

- [ ] **Step 4: Update the tool descriptor**

In `app/services/ai_tools.py:1215-1227`, replace:

```python
    {
        "name": "propose_contact",
        "category": "mutation",
        "description": ("Aggiunge un contatto (persona) alla rubrica, opzionalmente collegato "
                        "a un cliente, una trattativa e/o un progetto esistenti (id PK numerici)."),
        "input_schema": {"type": "object", "properties": {
            "client_id": {"type": "integer",
                         "description": "PK numerico del cliente (azienda del contatto). Opzionale: il contatto può restare orfano."},
            "acquisition_id": {"type": "integer",
                               "description": "PK numerico della trattativa a cui collegare il contatto."},
            "project_id": {"type": "integer",
                          "description": "PK numerico del progetto a cui collegare il contatto."},
            "name": {"type": "string", "description": "Nome della persona (obbligatorio)."},
            "role": {"type": "string"},
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "company_text": {"type": "string",
                             "description": "Azienda in testo libero, usata solo se client_id non è fornito."},
        }, "required": ["name"]},
        "handler": "propose_contact",
    },
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_propose_contact_links.py -v`
Expected: 4 passed.

Then run the full AI capability regression suites to confirm nothing else broke:

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisition_capabilities.py tests/test_calendar_capability.py tests/test_kdm_ai.py -v`
Expected: all pass (these exercise the same `_ACTION_HANDLERS` snapshot mechanism and must be unaffected).

- [ ] **Step 6: Commit**

```bash
git add app/services/ai_tools.py app/services/ai_assistant.py tests/test_propose_contact_links.py
git commit -m "feat(contacts): propose_contact copilot — client_id opzionale + link acquisition_id/project_id"
```

---

## Task 11: Frontend — `/contacts` page route + template skeleton + sidebar nav + i18n base

**Files:**
- Modify: `app/routers/contacts.py` (add `GET /contacts` page route — must be registered BEFORE `GET /contacts/api/{cid}` isn't relevant since `/contacts` and `/contacts/api/{cid}` are different path shapes; add near the top of the file, right after the router setup)
- Create: `app/templates/pages/contacts.html`
- Modify: `app/templates/base.html` (sidebar nav entry, after the `/acquisitions` link at `base.html:82-84`)
- Modify: `app/static/js/i18n.js` (add `nav.contacts` + base `contact.*` keys used by this task's skeleton)
- Test: `tests/test_contacts_page_route.py` (new)

**Interfaces:**
- Produces: `GET /contacts` → renders `pages/contacts.html` with `active_page="contacts"`, gated `view_clients`. Template provides `<div id="contacts-filterbar">`, `<div id="contacts-list">`, and a detail modal `#modal-contact-detail` — all consumed by `contacts.js` in Task 12.

- [ ] **Step 1: Write the failing test**

Create `tests/test_contacts_page_route.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole
from app.services.auth import create_access_token


@pytest.fixture
def client(monkeypatch):
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", e)
    monkeypatch.setattr(database, "SessionLocal", S)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
               hashed_password="x", role=UserRole.admin, is_active=True))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_contacts_page_renders_200(client):
    c, s = client
    r = c.get("/contacts")
    assert r.status_code == 200
    assert b"contacts-list" in r.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_page_route.py -v`
Expected: FAIL — 404 on `GET /contacts`.

- [ ] **Step 3: Add the page route**

`Request` is already imported in `app/routers/contacts.py` by Task 3's import extension (`from fastapi import APIRouter, Depends, HTTPException, Form, Request`). Add `from fastapi.responses import HTMLResponse` to the imports (matching the exact convention of `app/routers/acquisitions.py:31`: `@router.get("/acquisitions", response_class=HTMLResponse, dependencies=[RequireView])`). Right after `RequireEdit = Depends(...)` (`contacts.py:24`), add:

```python
@router.get("/contacts", response_class=HTMLResponse, dependencies=[RequireView])
async def contacts_page(request: Request):
    from app.main import templates
    return templates.TemplateResponse(
        "pages/contacts.html", {"request": request, "active_page": "contacts"})
```

- [ ] **Step 4: Create `app/templates/pages/contacts.html`**

```html
{% extends "base.html" %}
{% set active_page = "contacts" %}
{% block title %}Rubrica — Claqo{% endblock %}
{% block topbar_title %}<span data-i18n="contact.pageTitle">Rubrica Contatti</span>{% endblock %}
{% block topbar_actions %}
  <button class="btn btn-primary btn-sm" id="contacts-btn-new" data-i18n="contact.new">+ Nuovo contatto</button>
{% endblock %}

{% block content %}
<div id="contacts-filterbar"></div>
<div id="contacts-list" class="card"></div>

<div class="modal" id="modal-contact-new">
  <div class="modal-content" style="max-width:480px;">
    <div class="modal-header">
      <h3 data-i18n="contact.new">+ Nuovo contatto</h3>
      <button class="modal-close" onclick="closeModal('modal-contact-new')">&times;</button>
    </div>
    <div class="modal-body">
      <div class="form-group">
        <label class="form-label" data-i18n="contact.name">Nome</label>
        <input class="form-input" id="cn-name">
      </div>
      <div class="form-group">
        <label class="form-label" data-i18n="contact.companyText">Azienda (testo libero)</label>
        <input class="form-input" id="cn-company">
      </div>
      <div class="form-group">
        <label class="form-label" data-i18n="contact.email">Email</label>
        <input class="form-input" type="email" id="cn-email">
      </div>
      <div class="form-group">
        <label class="form-label" data-i18n="contact.phone">Telefono</label>
        <input class="form-input" id="cn-phone">
      </div>
      <div class="form-group">
        <label class="form-label" data-i18n="contact.role">Ruolo</label>
        <input class="form-input" id="cn-role">
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn" onclick="closeModal('modal-contact-new')" data-i18n="common.cancel">Annulla</button>
      <button class="btn btn-primary" id="contacts-btn-save-new" data-i18n="common.save">Salva</button>
    </div>
  </div>
</div>

<div class="modal" id="modal-contact-detail">
  <div class="modal-content" style="max-width:560px;">
    <div class="modal-header">
      <h3 id="cd-name" data-i18n="contact.detailTitle">Dettaglio contatto</h3>
      <button class="modal-close" onclick="closeModal('modal-contact-detail')">&times;</button>
    </div>
    <div class="modal-body" id="cd-body"></div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Register sidebar nav entry**

In `app/templates/base.html`, right after the `/acquisitions` link (`base.html:82-84`):

```html
        <a href="/contacts" data-nav-id="contacts" class="nav-item {% if active_page == 'contacts' %}active{% endif %}">
          <span class="nav-icon"><i data-lucide="contact"></i></span> <span data-i18n="nav.contacts">Rubrica</span>
        </a>
```

Only render it for users with `view_clients`, matching the router's own gate — wrap with `{% if has_permission(_user, 'view_clients') %}...{% endif %}` (the `has_permission` Jinja global is already used for `nav.kdm`/`nav.trash` at `base.html:173`/`223`).

- [ ] **Step 6: Add i18n keys**

In `app/static/js/i18n.js`, add `nav.contacts` next to `nav.clients` (near `i18n.js:41`):

```javascript
  'nav.contacts':            {it: 'Rubrica',           en: 'Contacts',          fr: 'Répertoire',       de: 'Kontakte',         es: 'Contactos'},
```

Add a new `contact.*` block (append near the end of the `window.MF_I18N` object, following the existing sectioning convention):

```javascript
  // ── Rubrica Contatti (Client email F3) ────────────
  'contact.pageTitle':       {it: 'Rubrica Contatti',  en: 'Contacts',          fr: 'Répertoire',        de: 'Kontakte',         es: 'Contactos'},
  'contact.new':             {it: '+ Nuovo contatto',  en: '+ New contact',     fr: '+ Nouveau contact', de: '+ Neuer Kontakt',  es: '+ Nuevo contacto'},
  'contact.name':            {it: 'Nome',              en: 'Name',              fr: 'Nom',               de: 'Name',             es: 'Nombre'},
  'contact.companyText':     {it: 'Azienda',           en: 'Company',           fr: 'Société',           de: 'Firma',            es: 'Empresa'},
  'contact.email':           {it: 'Email',             en: 'Email',             fr: 'E-mail',            de: 'E-Mail',           es: 'Correo'},
  'contact.phone':           {it: 'Telefono',          en: 'Phone',             fr: 'Téléphone',         de: 'Telefon',          es: 'Teléfono'},
  'contact.role':            {it: 'Ruolo',             en: 'Role',              fr: 'Rôle',              de: 'Rolle',            es: 'Rol'},
  'contact.detailTitle':     {it: 'Dettaglio contatto', en: 'Contact detail',   fr: 'Détail contact',    de: 'Kontaktdetails',   es: 'Detalle contacto'},
```

`common.cancel`/`common.save` already exist elsewhere in `i18n.js` — verify with a quick search (`grep "'common.save'" app/static/js/i18n.js`) and reuse; do not duplicate the key if found.

- [ ] **Step 7: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_contacts_page_route.py -v`
Expected: 1 passed.

- [ ] **Step 8: Commit**

```bash
git add app/routers/contacts.py app/templates/pages/contacts.html app/templates/base.html app/static/js/i18n.js tests/test_contacts_page_route.py
git commit -m "feat(contacts): pagina /contacts skeleton + nav sidebar + i18n base (5 lingue)"
```

---

## Task 12: Frontend — `static/js/contacts.js` (list, filter, detail, create, link/unlink)

**Files:**
- Create: `app/static/js/contacts.js` (list/filter/detail/create/associa/dissocia, including the "+ Associa" picker)
- Modify: `app/templates/pages/contacts.html` (script include + the `#modal-contact-link-picker` markup — page-specific scripts are NOT in `base.html`; confirmed by inspection: `email_links.js` is included at the bottom of `pages/acquisitions.html:496` as `<script src="/static/js/email_links.js?v={{ app_version }}"></script>`, `mail.js` likewise at the bottom of `pages/mail.html:32`. `contacts.js` follows the same per-page pattern, appended at the bottom of `pages/contacts.html`.)
- Modify: `app/static/js/i18n.js` (append associa/list/link strings, all 5 languages)
- Test: manual browser smoke for this task (JS has no automated unit-test harness in this codebase — the associate/dissociate round-trip is verified in the Task 16 browser checklist Step 3.1; the `/contacts/api/{id}/link` endpoint it drives is already unit-tested in Task 5).

**Interfaces:**
- Consumes: `GET /contacts/api/list`, `GET /contacts/api/{id}`, `POST /contacts/api/create`, `PUT /contacts/api/{id}`, `POST/DELETE /contacts/api/{id}/link` (Tasks 3-5); the picker also consumes existing list endpoints — `GET /clients/api` (returns a JSON array of `{id, name, ...}`, confirmed `clients.py:169`), `GET /projects/api` (JSON array of `{id, code, title, client_name, ...}`, confirmed `projects.py:44`), `GET /acquisitions/api/list` (returns `{items:[{id, title, client_name, ...}]}`, confirmed `acquisitions.py:70`); `MFFilterBar`, `openModal`/`closeModal`, `api()`, `escapeHtml`, `toast` (all existing in `app/static/js/global.js`).
- Produces: `mfContactsInit()` (called from `contacts.html` inline `<script>` on load, following the `mfMailInit()`/`mfEmailInit(aid)` convention), `mfContactOpenDetail(id)`, `mfContactSaveNew()`, `mfContactOpenLinkPicker(cid, targetType)`, `mfContactLinkPickerLoad(q)`, `mfContactLink(cid, targetType, targetId, role)`, `mfContactUnlink(cid, targetType, targetId)` — all exposed as `window`-scope functions per the codebase's no-module-bundler convention.

- [ ] **Step 1: Write `app/static/js/contacts.js`**

```javascript
// app/static/js/contacts.js — Client email F3: Rubrica Contatti
let _mfContactsFilterState = {};

async function mfContactsLoad() {
  const box = document.getElementById('contacts-list');
  if (!box) return;
  const params = new URLSearchParams();
  Object.keys(_mfContactsFilterState).forEach(function (k) {
    const v = _mfContactsFilterState[k];
    if (v) params.set(k, v);
  });
  try {
    const d = await (await fetch('/contacts/api/list?' + params.toString())).json();
    const items = d.items || [];
    if (!items.length) {
      box.innerHTML = '<div class="muted" style="padding:20px;">' + mfT('contact.empty') + '</div>';
      return;
    }
    box.innerHTML = '<table class="table"><thead><tr>' +
      '<th>' + mfT('contact.name') + '</th><th>' + mfT('contact.companyText') + '</th>' +
      '<th>' + mfT('contact.email') + '</th><th>' + mfT('contact.phone') + '</th>' +
      '<th>' + mfT('contact.links') + '</th></tr></thead><tbody>' +
      items.map(function (it) {
        const company = it.company_text || '';
        const orphan = !it.client_id && it.links.acquisitions === 0 && it.links.projects === 0
          ? ' <span class="badge">' + mfT('contact.orphan') + '</span>' : '';
        return '<tr class="clickable" data-contact-open="' + it.id + '">' +
          '<td>' + escapeHtml(it.name) + orphan + '</td>' +
          '<td>' + escapeHtml(company) + '</td>' +
          '<td>' + escapeHtml(it.email || '') + '</td>' +
          '<td>' + escapeHtml(it.phone || '') + '</td>' +
          '<td>' + it.links.acquisitions + ' 🎯 · ' + it.links.projects + ' 🎬</td></tr>';
      }).join('') + '</tbody></table>';
  } catch (e) { box.innerHTML = '<div class="muted">' + mfT('contact.error') + '</div>'; }
}

function mfContactsInitFilterBar() {
  const host = document.getElementById('contacts-filterbar');
  if (!host || typeof MFFilterBar !== 'function') return;
  MFFilterBar({
    host,
    filters: [
      {id: 'search', kind: 'text', label: mfT('contact.search'), minWidth: '220px'},
      {id: 'triage', kind: 'select', label: mfT('contact.triage'), options: [
        {value: '', label: mfT('contact.all')}, {value: '1', label: mfT('contact.orphansOnly')}]},
    ],
    onChange: function (vals) { _mfContactsFilterState = vals; mfContactsLoad(); },
  });
}

async function mfContactOpenDetail(id) {
  const body = document.getElementById('cd-body');
  const title = document.getElementById('cd-name');
  if (!body) return;
  try {
    const d = await (await fetch('/contacts/api/' + encodeURIComponent(id))).json();
    if (title) title.textContent = d.name;
    const acqRows = (d.acquisitions || []).map(function (a) {
      return '<li>' + escapeHtml(a.title) + (a.role ? ' — ' + escapeHtml(a.role) : '') +
        ' <button class="btn btn-sm" data-contact-unlink="' + id + '" data-target-type="acquisition" data-target-id="' + a.id + '">✕</button></li>';
    }).join('') || '<li class="muted">' + mfT('contact.none') + '</li>';
    const projRows = (d.projects || []).map(function (p) {
      return '<li>' + escapeHtml(p.code) + ' — ' + escapeHtml(p.title) +
        (p.role ? ' — ' + escapeHtml(p.role) : '') +
        ' <button class="btn btn-sm" data-contact-unlink="' + id + '" data-target-type="project" data-target-id="' + p.id + '">✕</button></li>';
    }).join('') || '<li class="muted">' + mfT('contact.none') + '</li>';
    const emailRows = (d.email_links || []).map(function (e) {
      return '<li>' + escapeHtml(e.subject || e.thread_id) + '</li>';
    }).join('') || '<li class="muted">' + mfT('contact.none') + '</li>';
    // "+ Associa" per sezione (create-link). Il picker apre modal-contact-link-picker.
    const assocBtn = function (type) {
      return ' <button class="btn btn-sm" data-contact-link-open="' + id +
        '" data-target-type="' + type + '">' + mfT('contact.linkBtn') + '</button>';
    };
    const clientBlock = d.client
      ? escapeHtml(d.client.name) +
        ' <button class="btn btn-sm" data-contact-unlink="' + id + '" data-target-type="client" data-target-id="' + d.client.id + '">✕</button>'
      : escapeHtml(d.company_text || '—');
    body.innerHTML =
      '<div class="form-group"><label class="form-label">' + mfT('contact.email') + '</label>' +
      '<div>' + escapeHtml(d.email || '—') + '</div></div>' +
      '<div class="form-group"><label class="form-label">' + mfT('contact.phone') + '</label>' +
      '<div>' + escapeHtml(d.phone || '—') + '</div></div>' +
      '<div class="form-group"><label class="form-label">' + mfT('contact.client') + assocBtn('client') + '</label>' +
      '<div>' + clientBlock + '</div></div>' +
      '<div class="form-group"><label class="form-label">' + mfT('contact.acquisitions') + assocBtn('acquisition') + '</label><ul>' + acqRows + '</ul></div>' +
      '<div class="form-group"><label class="form-label">' + mfT('contact.projects') + assocBtn('project') + '</label><ul>' + projRows + '</ul></div>' +
      '<div class="form-group"><label class="form-label">' + mfT('contact.emailLinks') + '</label><ul>' + emailRows + '</ul></div>';
    openModal('modal-contact-detail');
  } catch (e) { if (window.toast) toast(mfT('contact.error'), 'error'); }
}

// ── Picker "+ Associa": cliente / trattativa / progetto ──────────
const _MF_PICK_LABEL = {
  client: 'contact.pickClient', acquisition: 'contact.pickAcquisition', project: 'contact.pickProject',
};
let _mfLinkPicker = {cid: null, type: null};

function mfContactOpenLinkPicker(cid, targetType) {
  _mfLinkPicker = {cid: cid, type: targetType};
  const titleEl = document.getElementById('clp-title');
  const searchEl = document.getElementById('clp-search');
  const roleEl = document.getElementById('clp-role');
  if (titleEl) titleEl.textContent = mfT(_MF_PICK_LABEL[targetType] || 'contact.linkBtn');
  if (searchEl) searchEl.value = '';
  if (roleEl) roleEl.value = '';
  openModal('modal-contact-link-picker');
  mfContactLinkPickerLoad('');
}

async function mfContactLinkPickerLoad(q) {
  const box = document.getElementById('clp-results');
  if (!box) return;
  const type = _mfLinkPicker.type;
  q = (q || '').trim().toLowerCase();
  box.innerHTML = '<div class="muted">…</div>';
  try {
    let rows = [];
    if (type === 'client') {
      const arr = await (await fetch('/clients/api')).json();
      rows = (arr || [])
        .filter(function (c) { return !q || (c.name || '').toLowerCase().indexOf(q) >= 0; })
        .map(function (c) { return {id: c.id, label: c.name || ('#' + c.id)}; });
    } else if (type === 'project') {
      const arr = await (await fetch('/projects/api')).json();
      rows = (arr || [])
        .filter(function (p) { return !q || ((p.code || '') + ' ' + (p.title || '')).toLowerCase().indexOf(q) >= 0; })
        .map(function (p) { return {id: p.id, label: (p.code || '') + ' — ' + (p.title || '')}; });
    } else {  // acquisition — endpoint ritorna {items:[...]}
      const d = await (await fetch('/acquisitions/api/list')).json();
      rows = (d.items || [])
        .filter(function (a) { return !q || ((a.title || '') + ' ' + (a.client_name || '')).toLowerCase().indexOf(q) >= 0; })
        .map(function (a) { return {id: a.id, label: (a.title || '') + (a.client_name ? ' · ' + a.client_name : '')}; });
    }
    if (!rows.length) { box.innerHTML = '<div class="muted">' + mfT('contact.none') + '</div>'; return; }
    box.innerHTML = rows.map(function (r) {
      return '<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--border);">' +
        '<span>' + escapeHtml(r.label) + '</span>' +
        '<button class="btn btn-sm btn-primary" data-link-pick-id="' + escapeHtml(String(r.id)) + '">' + mfT('contact.linkBtn') + '</button></div>';
    }).join('');
  } catch (e) { box.innerHTML = '<div class="muted">' + mfT('contact.error') + '</div>'; }
}

async function mfContactLink(cid, targetType, targetId, role) {
  const fd = new FormData();
  fd.append('target_type', targetType);
  fd.append('target_id', targetId);
  if (role) fd.append('role', role);
  try {
    const r = await fetch('/contacts/api/' + encodeURIComponent(cid) + '/link', {method: 'POST', body: fd});
    const b = await r.json();
    if (r.ok) {
      if (window.toast) toast(b.already_linked ? mfT('contact.alreadyLinked') : mfT('contact.linked'), 'success');
      closeModal('modal-contact-link-picker');
      mfContactOpenDetail(cid);  // refresh sezioni del dettaglio
      mfContactsLoad();          // refresh conteggi link nella lista
    } else if (window.toast) toast(mfT('contact.error'), 'error');
  } catch (e) { if (window.toast) toast(mfT('contact.error'), 'error'); }
}

async function mfContactSaveNew() {
  const fd = new FormData();
  const map = {name: 'cn-name', company_text: 'cn-company', email: 'cn-email',
               phone: 'cn-phone', role: 'cn-role'};
  Object.keys(map).forEach(function (k) {
    const el = document.getElementById(map[k]);
    if (el && el.value.trim()) fd.append(k, el.value.trim());
  });
  if (!fd.get('name')) { if (window.toast) toast(mfT('contact.nameRequired'), 'error'); return; }
  try {
    const r = await fetch('/contacts/api/create', {method: 'POST', body: fd});
    const b = await r.json();
    if (!r.ok) { if (window.toast) toast(mfT('contact.error'), 'error'); return; }
    if (b.existing_id) { if (window.toast) toast(mfT('contact.dedupFound'), 'success'); }
    else if (window.toast) toast(mfT('contact.created'), 'success');
    closeModal('modal-contact-new');
    mfContactsLoad();
  } catch (e) { if (window.toast) toast(mfT('contact.error'), 'error'); }
}

async function mfContactUnlink(cid, targetType, targetId) {
  const fd = new FormData();
  fd.append('target_type', targetType);
  fd.append('target_id', targetId);
  try {
    const r = await fetch('/contacts/api/' + encodeURIComponent(cid) + '/link', {method: 'DELETE', body: fd});
    if (r.ok) mfContactOpenDetail(cid);
  } catch (e) { if (window.toast) toast(mfT('contact.error'), 'error'); }
}

function mfContactsInit() {
  mfContactsInitFilterBar();
  mfContactsLoad();
  const newBtn = document.getElementById('contacts-btn-new');
  if (newBtn) newBtn.addEventListener('click', function () { openModal('modal-contact-new'); });
  const saveBtn = document.getElementById('contacts-btn-save-new');
  if (saveBtn) saveBtn.addEventListener('click', mfContactSaveNew);
  const clpSearch = document.getElementById('clp-search');
  if (clpSearch) clpSearch.addEventListener('input', function () { mfContactLinkPickerLoad(this.value); });
  document.addEventListener('click', function (ev) {
    const t = ev.target;
    const open = t.closest && t.closest('[data-contact-open]');
    if (open) { mfContactOpenDetail(open.getAttribute('data-contact-open')); return; }
    const linkOpen = t.closest && t.closest('[data-contact-link-open]');
    if (linkOpen) {
      mfContactOpenLinkPicker(linkOpen.getAttribute('data-contact-link-open'),
                              linkOpen.getAttribute('data-target-type'));
      return;
    }
    const pick = t.closest && t.closest('[data-link-pick-id]');
    if (pick) {
      const roleEl = document.getElementById('clp-role');
      mfContactLink(_mfLinkPicker.cid, _mfLinkPicker.type,
                    pick.getAttribute('data-link-pick-id'),
                    roleEl ? roleEl.value.trim() : '');
      return;
    }
    const unlink = t.closest && t.closest('[data-contact-unlink]');
    if (unlink) {
      mfContactUnlink(unlink.getAttribute('data-contact-unlink'),
                      unlink.getAttribute('data-target-type'),
                      unlink.getAttribute('data-target-id'));
      return;
    }
  });
}
```

**Note on the click-delegation order:** the `[data-link-pick-id]` branch must be checked *before* `[data-contact-unlink]` only matters if an element could carry both — it can't, so order among the four branches is safe. But `[data-link-pick-id]` buttons live inside `#modal-contact-link-picker`, which is a sibling of the row table; the single document-level listener handles both because the picker markup (Step 2b) is added to the same page.

- [ ] **Step 2: Wire the script include and the page's init call**

In `app/templates/pages/contacts.html` (created in Task 11), add at the bottom of the `content` block, right before `{% endblock %}`:

```html
<script src="/static/js/contacts.js?v={{ app_version }}"></script>
<script>document.addEventListener('DOMContentLoaded', mfContactsInit);</script>
```

(`{{ app_version }}` is the existing cache-buster convention used by `pages/acquisitions.html:496` and `pages/mail.html:32` — bumping `app_version` on the next release, as already done project-wide per memory `feedback_cache_buster_static`, is what invalidates the browser cache; no per-file query-string literal to maintain here.)

- [ ] **Step 2b: Add the "+ Associa" picker modal to `contacts.html`**

The `mfContactOpenLinkPicker`/`mfContactLinkPickerLoad` functions rely on a modal element `#modal-contact-link-picker` being present in the DOM (`openModal(id)` toggles an existing element by id — see `global.js:473`). Add this markup inside the `content` block of `app/templates/pages/contacts.html`, right after the `#modal-contact-detail` modal added in Task 11:

```html
<div class="modal" id="modal-contact-link-picker">
  <div class="modal-content" style="max-width:480px;">
    <div class="modal-header">
      <h3 id="clp-title" data-i18n="contact.linkBtn">+ Associa</h3>
      <button class="modal-close" onclick="closeModal('modal-contact-link-picker')">&times;</button>
    </div>
    <div class="modal-body">
      <div class="form-group">
        <label class="form-label" data-i18n="contact.role">Ruolo</label>
        <input class="form-input" id="clp-role" data-i18n="contact.roleOptional" data-i18n-attr="placeholder" placeholder="(opzionale)">
      </div>
      <div class="form-group">
        <label class="form-label" data-i18n="contact.search">Cerca</label>
        <input class="form-input" id="clp-search">
      </div>
      <div id="clp-results" style="max-height:320px;overflow-y:auto;"></div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add the remaining i18n keys used by `contacts.js`**

Append to the `contact.*` block in `app/static/js/i18n.js` (started in Task 11):

```javascript
  'contact.empty':           {it: 'Nessun contatto.', en: 'No contacts.',      fr: 'Aucun contact.',    de: 'Keine Kontakte.',  es: 'Sin contactos.'},
  'contact.error':           {it: 'Errore.',           en: 'Error.',            fr: 'Erreur.',           de: 'Fehler.',          es: 'Error.'},
  'contact.links':           {it: 'Collegamenti',      en: 'Links',             fr: 'Liens',             de: 'Verknüpfungen',    es: 'Enlaces'},
  'contact.orphan':          {it: 'orfano',            en: 'orphan',            fr: 'orphelin',          de: 'verwaist',         es: 'huérfano'},
  'contact.search':          {it: 'Cerca',             en: 'Search',            fr: 'Rechercher',        de: 'Suchen',           es: 'Buscar'},
  'contact.triage':          {it: 'Triage',            en: 'Triage',            fr: 'Triage',            de: 'Triage',           es: 'Triage'},
  'contact.all':             {it: 'Tutti',             en: 'All',               fr: 'Tous',              de: 'Alle',             es: 'Todos'},
  'contact.orphansOnly':     {it: 'Solo orfani',       en: 'Orphans only',      fr: 'Orphelins seulement', de: 'Nur verwaist',   es: 'Solo huérfanos'},
  'contact.client':          {it: 'Cliente',           en: 'Client',            fr: 'Client',            de: 'Kunde',            es: 'Cliente'},
  'contact.acquisitions':    {it: 'Trattative',        en: 'Deals',             fr: 'Affaires',          de: 'Geschäfte',        es: 'Negocios'},
  'contact.projects':        {it: 'Progetti',          en: 'Projects',          fr: 'Projets',           de: 'Projekte',         es: 'Proyectos'},
  'contact.emailLinks':      {it: 'Email agganciate',  en: 'Linked emails',     fr: 'E-mails liés',      de: 'Verknüpfte E-Mails', es: 'Correos vinculados'},
  'contact.none':            {it: 'Nessuno',           en: 'None',              fr: 'Aucun',             de: 'Keine',            es: 'Ninguno'},
  'contact.nameRequired':    {it: 'Nome richiesto',    en: 'Name required',     fr: 'Nom requis',        de: 'Name erforderlich', es: 'Nombre requerido'},
  'contact.created':         {it: 'Contatto creato',   en: 'Contact created',   fr: 'Contact créé',      de: 'Kontakt erstellt', es: 'Contacto creado'},
  'contact.dedupFound':      {it: 'Contatto già esistente collegato', en: 'Existing contact linked', fr: 'Contact existant lié', de: 'Bestehender Kontakt verknüpft', es: 'Contacto existente vinculado'},
  'contact.linkBtn':         {it: '+ Associa',         en: '+ Link',            fr: '+ Associer',        de: '+ Verknüpfen',     es: '+ Asociar'},
  'contact.roleOptional':    {it: '(opzionale)',       en: '(optional)',        fr: '(facultatif)',      de: '(optional)',       es: '(opcional)'},
  'contact.pickClient':      {it: 'Associa a cliente', en: 'Link to client',    fr: 'Associer au client', de: 'Mit Kunde verknüpfen', es: 'Asociar a cliente'},
  'contact.pickAcquisition': {it: 'Associa a trattativa', en: 'Link to deal',   fr: 'Associer à l’affaire', de: 'Mit Geschäft verknüpfen', es: 'Asociar a negocio'},
  'contact.pickProject':     {it: 'Associa a progetto', en: 'Link to project',  fr: 'Associer au projet', de: 'Mit Projekt verknüpfen', es: 'Asociar a proyecto'},
  'contact.linked':          {it: 'Collegamento creato', en: 'Link created',    fr: 'Lien créé',         de: 'Verknüpfung erstellt', es: 'Enlace creado'},
  'contact.alreadyLinked':   {it: 'Già collegato',     en: 'Already linked',    fr: 'Déjà lié',          de: 'Bereits verknüpft', es: 'Ya vinculado'},
```

- [ ] **Step 4: Manual browser smoke**

Start the server (`.venv/Scripts/python.exe run.py` or the project's usual launcher — no `reload=True`, per memory `feedback_uvicorn_reload_orphans_smoke`), navigate to `/contacts`, and verify: page loads, filter bar renders, "+ Nuovo contatto" opens the modal, creating a contact refreshes the list, clicking a row opens the detail modal with acquisitions/projects/email sections. Then exercise the **associate** flow: in the detail modal click "+ Associa" on the Trattative section → the picker modal opens, search filters the list, clicking "+ Associa" on a row POSTs the link and the detail refreshes showing the new association (with its ✕ unlink button); repeat for Progetti and Cliente. Confirm the list's link-count column updates. Check the browser console for `ReferenceError`/`SyntaxError` (memory `feedback_smoke_e2e_browser`: backend smoke alone won't catch these).

- [ ] **Step 5: Commit**

```bash
git add app/static/js/contacts.js app/templates/pages/contacts.html app/static/js/i18n.js
git commit -m "feat(contacts): contacts.js — lista/filtri/dettaglio/creazione/associa/dissocia UI"
```

---

## Task 13: Frontend — "Estrai contatto" in `/mail` thread view and `email_links.js`

**Files:**
- Modify: `app/static/js/mail.js:82-84` (message actions row) and its click-delegation block (`mail.js:123-153`)
- Modify: `app/static/js/email_links.js` (email row actions, `email_links.js:23-27` and click-delegation, `email_links.js:98-114`)
- Create: shared helper in `app/static/js/contacts.js` (append)
- Modify: `app/static/js/i18n.js` (append `email.extractContact` + preview-modal strings)
- Test: manual browser smoke (JS, no pytest — verified in Task 16 Playwright pass)

**Interfaces:**
- Consumes: `POST /contacts/api/extract`, `POST /contacts/api/extract/enrich`, `POST /contacts/api/create` (Tasks 4/7).
- Produces: `mfContactExtractOpen(threadId)` (shared, called from both `mail.js` and `email_links.js`) — opens a lightweight preview using `alert`-free DOM (a small inline panel, not a full new modal, to keep this task scoped) listing candidates with a "Salva" button per candidate that calls `POST /contacts/api/create`.

- [ ] **Step 1: Add the shared extraction UI to `contacts.js`**

Append to `app/static/js/contacts.js` (from Task 12):

```javascript
async function mfContactExtractOpen(threadId, hostId) {
  const host = document.getElementById(hostId);
  if (!host) return;
  host.innerHTML = '<div class="muted">' + mfT('contact.extracting') + '</div>';
  try {
    const fd = new FormData();
    fd.append('thread_id', threadId);
    const r = await fetch('/contacts/api/extract', {method: 'POST', body: fd});
    const d = await r.json();
    const cands = d.candidates || [];
    if (!cands.length) { host.innerHTML = '<div class="muted">' + mfT('contact.none') + '</div>'; return; }
    host.innerHTML = cands.map(function (c, i) {
      return '<div class="contact-cand" style="border:1px solid var(--border);border-radius:6px;padding:8px;margin-bottom:6px;">' +
        '<b>' + escapeHtml(c.name || '') + '</b> <span class="muted">' + escapeHtml(c.email || '') + '</span>' +
        (c.role ? '<div class="muted">' + escapeHtml(c.role) + '</div>' : '') +
        (c.company_text ? '<div class="muted">' + escapeHtml(c.company_text) + '</div>' : '') +
        (c.phone ? '<div class="muted">' + escapeHtml(c.phone) + '</div>' : '') +
        '<button class="btn btn-sm" data-contact-cand-save="' + i + '" data-cand-host="' + hostId + '">' +
        mfT('contact.saveCandidate') + '</button></div>';
    }).join('');
    host._mfCandidates = cands;
  } catch (e) { host.innerHTML = '<div class="muted">' + mfT('contact.error') + '</div>'; }
}

async function mfContactSaveCandidate(hostId, idx) {
  const host = document.getElementById(hostId);
  const cand = host && host._mfCandidates && host._mfCandidates[idx];
  if (!cand) return;
  const fd = new FormData();
  fd.append('name', cand.name || '');
  if (cand.email) fd.append('email', cand.email);
  if (cand.phone) fd.append('phone', cand.phone);
  if (cand.role) fd.append('role', cand.role);
  if (cand.company_text) fd.append('company_text', cand.company_text);
  try {
    const r = await fetch('/contacts/api/create', {method: 'POST', body: fd});
    if (r.ok) { if (window.toast) toast(mfT('contact.created'), 'success'); }
    else if (window.toast) toast(mfT('contact.error'), 'error');
  } catch (e) { if (window.toast) toast(mfT('contact.error'), 'error'); }
}

document.addEventListener('click', function (ev) {
  const t = ev.target;
  const save = t.closest && t.closest('[data-contact-cand-save]');
  if (save) {
    mfContactSaveCandidate(save.getAttribute('data-cand-host'),
                          parseInt(save.getAttribute('data-contact-cand-save'), 10));
  }
});
```

- [ ] **Step 2: Add the button + preview host to `mail.js`**

In `app/static/js/mail.js`, inside `mfMailOpenThread` (`mail.js:81-85`), add a button next to `data-mail-assign` and a preview host div:

```javascript
        '<button class="btn btn-sm" data-mail-assign="' + escapeHtml(threadId) + '">' + mfT('email.assign') + '</button> ' +
        '<button class="btn btn-sm" data-mail-extract-contact="' + escapeHtml(threadId) + '">' + mfT('email.extractContact') + '</button>' +
        '</div><div class="mail-contact-cands" id="mail-cands-' + escapeHtml(threadId) + '"></div></div>';
```

(This replaces the closing `'</div></div>';` on `mail.js:85` — the extra `<div class="mail-contact-cands">` becomes the new last child before the outer `</div>`.)

In the click-delegation block (`mail.js:123-153`), add a branch before the closing `});` (after the `asg` branch, `mail.js:151-152`):

```javascript
  const extc = t.closest && t.closest('[data-mail-extract-contact]');
  if (extc) {
    const tid = extc.getAttribute('data-mail-extract-contact');
    mfContactExtractOpen(tid, 'mail-cands-' + tid);
    return;
  }
```

- [ ] **Step 3: Add the button + preview host to `email_links.js`**

In `app/static/js/email_links.js`, inside `mfEmailList` (`email_links.js:19-28`), add a button next to `data-em-extract` and a preview host div:

```javascript
        '<button class="btn btn-sm" data-em-extract="' + escapeHtml(e.thread_id) + '">' + mfT('email.extract') + '</button>' +
        '<button class="btn btn-sm" data-em-extract-contact="' + escapeHtml(e.thread_id) + '">' + mfT('email.extractContact') + '</button>' +
        '<button class="btn btn-sm" data-em-remove="' + e.id + '" data-em-aid="' + escapeHtml(String(aid)) + '">🗑</button>' +
        '</div><div class="em-preview" id="em-prev-' + escapeHtml(e.thread_id) + '"></div>' +
        '<div class="em-contact-cands" id="em-cands-' + escapeHtml(e.thread_id) + '"></div></div>';
```

In `mfEmailInit`'s click delegation (`email_links.js:98-114`), add a branch after the `ext` branch (`email_links.js:107-108`):

```javascript
      const extc = t.closest && t.closest('[data-em-extract-contact]');
      if (extc) {
        const tid = extc.getAttribute('data-em-extract-contact');
        mfContactExtractOpen(tid, 'em-cands-' + tid);
        return;
      }
```

- [ ] **Step 4: Add i18n keys**

Append to `app/static/js/i18n.js` (near the existing `email.*` keys and the `contact.*` block):

```javascript
  'email.extractContact':    {it: 'Estrai contatto',  en: 'Extract contact',  fr: 'Extraire contact', de: 'Kontakt extrahieren', es: 'Extraer contacto'},
  'contact.extracting':      {it: 'Estrazione in corso…', en: 'Extracting…',   fr: 'Extraction…',      de: 'Extrahiere…',      es: 'Extrayendo…'},
  'contact.saveCandidate':   {it: 'Salva in rubrica',  en: 'Save to contacts', fr: 'Enregistrer',       de: 'In Kontakte speichern', es: 'Guardar en contactos'},
```

- [ ] **Step 5: Manual browser smoke**

Restart the server (template/JS changes need a restart per memory `feedback_template_change_needs_restart`, and bump the `?v=` cache-buster if `contacts.js`/`mail.js`/`email_links.js` already had one — memory `feedback_cache_buster_static`). Navigate to `/mail`, open a thread (with a mocked/real Gmail connection), click "Estrai contatto", confirm candidates render and "Salva in rubrica" creates a contact (verify via `/contacts`). Repeat from an acquisition detail page's Email tab (`email_links.js` path). Check browser console for errors.

- [ ] **Step 6: Commit**

```bash
git add app/static/js/mail.js app/static/js/email_links.js app/static/js/contacts.js app/static/js/i18n.js
git commit -m "feat(contacts): bottone 'Estrai contatto' in /mail e trattativa (email_links.js) con preview candidati"
```

---

## Task 14: Frontend — "Salva in rubrica" nella scheda tecnica progetto

**Files:**
- Modify: `app/templates/pages/project_detail.html` (`tsRenderContacts`, `~project_detail.html:1718-1738`, and the `Contatti/Crew` pane data-flow)
- Modify: `app/static/js/i18n.js` (append `tech_sheet.saveToContacts` strings)
- Test: manual browser smoke (JS, no pytest — verified in Task 16 Playwright pass)

**Interfaces:**
- Consumes: `POST /contacts/api/from-tech-sheet` (Task 8).
- Produces: `tsSaveContactToRubrica(idx)` — new function alongside the existing `tsAddContact`/`tsRemoveContact`/`tsContactChange` in `project_detail.html`.

- [ ] **Step 1: Extend `tsRenderContacts` with the "Salva in rubrica" control**

Replace `tsRenderContacts` in `app/templates/pages/project_detail.html` (`~project_detail.html:1718-1738`):

```javascript
function tsRenderContacts() {
  const host = document.getElementById('ts-contacts-list');
  const arr = (tsState.data && tsState.data.contacts) || [];
  if (!arr.length) {
    host.innerHTML = '<div class="text-muted text-sm" style="padding:12px;text-align:center;">Nessun contatto. Clicca "+ Aggiungi contatto".</div>';
    return;
  }
  host.innerHTML = arr.map((c, i) => {
    const saved = !!c.contact_id;
    const saveBtn = saved
      ? '<span class="badge" title="In rubrica #' + c.contact_id + '">✓ Rubrica</span>'
      : '<button class="btn btn-ghost btn-sm" onclick="tsSaveContactToRubrica(' + i + ')">💾 Salva in rubrica</button>';
    return `
    <div class="card mb-3" style="background:var(--bg);">
      <div class="form-row">
        <div class="form-group"><label class="form-label">Ruolo</label><input class="form-input" value="${escapeHtml(c.role||'')}" onchange="tsContactChange(${i},'role',this.value)" placeholder="DIT / Colorist / DMT…"></div>
        <div class="form-group" style="flex:2;"><label class="form-label">Nome</label><input class="form-input" value="${escapeHtml(c.name_text||'')}" onchange="tsContactChange(${i},'name_text',this.value)" placeholder="Nome (o TBD)"></div>
        <button class="btn btn-ghost btn-sm color-rose" onclick="tsRemoveContact(${i})" style="align-self:flex-end;">✕</button>
      </div>
      <div class="form-row">
        <div class="form-group" style="flex:2;"><label class="form-label">Email</label><input class="form-input" type="email" value="${escapeHtml(c.email||'')}" onchange="tsContactChange(${i},'email',this.value)"></div>
        <div class="form-group"><label class="form-label">Telefono</label><input class="form-input" value="${escapeHtml(c.phone||'')}" onchange="tsContactChange(${i},'phone',this.value)"></div>
      </div>
      <div class="form-row" style="justify-content:flex-end;">${saveBtn}</div>
    </div>
  `;
  }).join('');
}

async function tsSaveContactToRubrica(idx) {
  const c = tsState.data.contacts[idx];
  if (!c || !(c.name_text || '').trim()) { toast('Serve un nome per salvare in rubrica', 'error'); return; }
  const fd = new FormData();
  fd.append('project_id', PROJECT_ID);
  fd.append('idx', idx);
  fd.append('name', c.name_text.trim());
  if (c.email) fd.append('email', c.email);
  if (c.phone) fd.append('phone', c.phone);
  if (c.role) fd.append('role', c.role);
  try {
    const res = await api('POST', '/contacts/api/from-tech-sheet', fd);
    tsState.data.contacts[idx] = Object.assign({}, c, {contact_id: res.id});
    tsRenderContacts();
    toast(res.existing ? 'Contatto esistente collegato' : 'Contatto salvato in rubrica', 'success');
  } catch (e) { toast(e.message, 'error'); }
}
```

- [ ] **Step 2: Add i18n keys (for consistency, even though this pane currently uses hardcoded Italian strings)**

The existing tech-sheet Crew pane (`project_detail.html:417-424`) is NOT currently `data-i18n`-tagged (pre-existing debt, out of scope to retrofit here). The two new user-facing strings this task introduces (`toast()` calls) are plain JS string literals, matching the surrounding code's existing convention in this specific pane. Do **not** introduce a `data-i18n` island here — that would be an inconsistent, partial retrofit of a page area that predates the i18n convention. Flag this explicitly in the task's own commit message so it's traceable, and leave a one-line comment above `tsSaveContactToRubrica`:

```javascript
// NB: pane Crew/Contatti (project_detail.html) precede l'adozione i18n.js;
// stringhe qui sotto in italiano hardcoded per coerenza con il resto della pane,
// non un'eccezione alla regola i18n per superfici NUOVE (vedi CLAUDE.md).
```

- [ ] **Step 3: Manual browser smoke**

Restart the server. Open a project's scheda tecnica, add a Crew contact with name+email, click "💾 Salva in rubrica", confirm it becomes "✓ Rubrica" and the contact appears in `/contacts`. Re-open the tech sheet (reload) and confirm the `contact_id` persisted (badge still shows "✓ Rubrica" after reload, not the button).

- [ ] **Step 4: Commit**

```bash
git add app/templates/pages/project_detail.html app/static/js/i18n.js
git commit -m "feat(contacts): bottone 'Salva in rubrica' nella scheda tecnica (pane Crew)"
```

---

## Task 15: Frontend — badge notifica on-demand nella trattativa

**Files:**
- Modify: `app/static/js/email_links.js` (append badge function + call site)
- Modify: `app/templates/pages/acquisitions.html` (add a badge placeholder in the detail panel's Email tab area — grep for where `mfEmailInit(aid)` is invoked to find the exact anchor)
- Modify: `app/static/js/i18n.js` (append badge string)
- Test: manual browser smoke (JS, no pytest — verified in Task 16 Playwright pass)

**Interfaces:**
- Consumes: `GET /contacts/api/notify-badge?acquisition_id=` (Task 9).
- Produces: `mfContactsBadgeInit(aid)` — appended to `email_links.js` (thematically it's the email/contacts intersection, matching where `mfEmailInit` already lives), called alongside `mfEmailInit(aid)`.

- [ ] **Step 1: Locate the exact call site of `mfEmailInit(aid)`**

Run: `grep -n "mfEmailInit" app/templates/pages/acquisitions.html`

This finds the line inside the acquisition detail panel's tab-switch/render logic where `mfEmailInit(aid)` is invoked (per the design doc, this is the Email tab of the trattativa detail). Note the exact line for Step 3.

- [ ] **Step 2: Add the badge function to `email_links.js`**

Append to `app/static/js/email_links.js`:

```javascript
async function mfContactsBadgeInit(aid) {
  const el = document.getElementById('em-contacts-badge');
  if (!el) return;
  el.style.display = 'none';
  try {
    const d = await (await fetch('/contacts/api/notify-badge?acquisition_id=' + encodeURIComponent(aid))).json();
    const count = d.count || 0;
    if (count > 0) {
      el.textContent = count + ' ' + mfT('contact.badgeNewEmails');
      el.style.display = '';
    }
  } catch (e) { /* best-effort: badge nascosto, mai errore visibile */ }
}
```

- [ ] **Step 3: Add the badge element + call site in `acquisitions.html`**

At the line found in Step 1 (where `mfEmailInit(aid)` is called), add a sibling call and, in the Email tab's HTML (near the `em-list`/`em-search` elements — grep `id="em-list"` in `acquisitions.html` to find the exact container), add:

```html
<div id="em-contacts-badge" class="badge" style="display:none;margin-bottom:8px;"></div>
```

and immediately after the existing `mfEmailInit(aid);` call:

```javascript
mfContactsBadgeInit(aid);
```

- [ ] **Step 4: Add i18n key**

Append to `app/static/js/i18n.js`:

```javascript
  'contact.badgeNewEmails':  {it: 'email recenti da contatti noti non ancora agganciate', en: 'recent emails from known contacts not yet linked', fr: 'e-mails récents de contacts connus non liés', de: 'aktuelle E-Mails bekannter Kontakte, noch nicht verknüpft', es: 'correos recientes de contactos conocidos sin vincular'},
```

- [ ] **Step 5: Manual browser smoke**

Restart the server. Open a trattativa with a linked contact whose email matches recent Gmail threads not yet pinned; confirm the badge appears with the right count in the Email tab. Open a trattativa with no linked contacts; confirm the badge stays hidden (never a console error, per the best-effort contract).

- [ ] **Step 6: Commit**

```bash
git add app/static/js/email_links.js app/templates/pages/acquisitions.html app/static/js/i18n.js
git commit -m "feat(contacts): badge notifica on-demand — email note da contatti collegati non agganciate"
```

---

## Task 16: Full regression + Playwright smoke

**Files:**
- No source changes expected (verification-only task); fix-forward if regressions surface.

**Interfaces:**
- N/A — this task's deliverable is a verified-green state of the whole suite plus a browser smoke pass, per the project's mandatory "test-before-claiming-done" rule and memory `feedback_smoke_e2e_browser`.

- [ ] **Step 1: Run the full backend test suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass, including every new file from Tasks 1-10 (`test_contact_model.py`, `test_migrate_contacts_rubrica.py`, `test_contacts_rubrica_api.py`, `test_contact_extract.py`, `test_contacts_extract_api.py`, `test_contacts_tech_sheet_bridge.py`, `test_contacts_notify_badge.py`, `test_propose_contact_links.py`, `test_contacts_page_route.py`) and all pre-existing suites (in particular `tests/test_email_links_api.py`, `tests/test_acquisition_capabilities.py`, and anything touching `ProjectTechSheet`/`Contact`/`Client`).

- [ ] **Step 2: Grep for stale references**

Run: `grep -rn "propose_contact" app/ tests/` and confirm every call site expects the new optional-`client_id` contract (no leftover assumption that `client_id` is required).

Run: `grep -rn "data-em-extract-contact\|data-mail-extract-contact\|data-contact-\|data-link-pick-id\|data-target-type\|data-target-id" app/static/js/*.js` and confirm every `data-*` attribute referenced in a click handler has a matching attribute emitted in the corresponding render function, and vice versa (catches the classic "handler wired, attribute typo'd" bug class — especially the picker's `data-contact-link-open` / `data-link-pick-id` pair added in Task 12).

- [ ] **Step 3: Boot the server without `reload=True` and run a full manual click-through**

Per memory `feedback_uvicorn_reload_orphans_smoke`, start via the project's non-reload launcher bound to `127.0.0.1`. Walk the full feature:
1. `/contacts` — create a standalone contact, search/filter/triage, open detail, then use the "+ Associa" control in each of the Cliente / Trattative / Progetti sections (Task 12): the picker modal opens, search filters, selecting a row POSTs `/contacts/api/{id}/link` and the detail refreshes with the new association + its ✕ unlink button, and the list's link-count column updates. Unlink via ✕ and confirm the row disappears. Confirm the picker sources the right endpoint per type (`/clients/api`, `/acquisitions/api/list`, `/projects/api`).
2. `/mail` — open a thread, click "Estrai contatto", save a candidate, confirm it lands in `/contacts`.
3. Acquisition detail → Email tab — same extraction flow, confirm the notification badge appears/hides correctly.
4. Project detail → scheda tecnica → Crew pane — "Salva in rubrica", confirm persistence across reload.
5. Copilot — ask it to add a contact linked to an existing trattativa (`propose_contact` with `acquisition_id`), confirm the AIAction card proposes correctly and Apply creates both the `Contact` and the `ContactAcquisition` row.

Check the browser console at every step for `ReferenceError`/`SyntaxError`/failed network requests (memory `feedback_smoke_e2e_browser` — this is the step backend tests structurally cannot cover).

- [ ] **Step 4: Update `CHANGELOG.md` and `docs/STATO.md`**

Per the project convention ("Git tenuto pulito... Commit a ogni versione finita"), bump the version marker and add a changelog entry summarizing: Contact standalone + M:N links, hybrid extraction, tech-sheet bridge, copilot extension, on-demand badge. Update `docs/STATO.md`'s "in corso"/"prossimo step" sections to reflect this feature as closed and name the next planned work.

- [ ] **Step 5: Final commit**

```bash
git add CHANGELOG.md docs/STATO.md
git commit -m "chore(contacts): chiude Client email F3 — rubrica contatti, changelog + STATO"
```

---

## Self-review notes (for the plan author, kept for traceability)

- **Spec coverage** — all 8 areas from the design doc are covered: (1) model in Task 1, (2) page/router in Tasks 3-5/11-12, (3) hybrid extraction in Tasks 6-7/13, (4) match/dedup in Tasks 3-4 (`/match`, dedup-on-create), (5) tech-sheet bridge in Task 8/14, (6) copilot in Task 10, (7) notifications in Task 9/15, (8) migration/i18n/tests woven into every task + consolidated in Task 2 and Task 16.
- **Deliberate deviation flagged**: `propose_contact`'s `required` shrinks from `["client_id", "name"]` to `["name"]` (Task 10) — this is the spec-mandated standalone-contact behavior, not an oversight, but it changes what a well-formed AI tool call looks like; called out explicitly in Task 10's Interfaces.
- **Create-link UI is in scope (spec §2)**: the Task 12 detail modal exposes a "+ Associa" control per section (Cliente / Trattative / Progetti) that opens a picker sourcing the existing list endpoints and POSTs `/contacts/api/{id}/link` — full associa/dissocia round-trip, matching the spec's "sezioni Clienti/Trattative/Progetti con associa/dissocia (riusa openModal/closeModal)". The link endpoint itself is unit-tested in Task 5; the JS handler wiring is verified in the Task 16 browser smoke checklist (Step 3.1), since this codebase has no JS unit-test harness.
