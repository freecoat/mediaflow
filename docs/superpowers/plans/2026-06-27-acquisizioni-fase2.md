# Acquisizioni Fase 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nel copilot esistente: incolla una conversazione email → l'AI propone (confermabili) log attività + contatto + aggiornamento cliente + avanzamento trattativa; più uno step web esplicito ("🔎 Cerca sul web") ristretto a fonti configurabili in Impostazioni.

**Architecture:** Nessuna pagina nuova. Si estende il copilot: 2 capability nuove (`update_client`, `propose_client_work`), `web_search` arricchito con `include_domains` da `Tenant.web_sources`, system prompt "email-aware", 2 bottoni nel drawer copilot, e una sezione Impostazioni per le fonti web. Riusa il flusso AIAction propose→apply esistente.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Jinja2 + SQLite, vanilla JS, pytest, Tavily (web_search.py). Niente nuove dipendenze.

## Global Constraints

- Python 3.11+ (priorità 3.14). Test runner: `.venv/Scripts/python.exe -m pytest`.
- Capability AI = handler `@ai_capability("name")` su `_h_name(db, data) -> dict` in `app/services/ai_assistant.py` (ritorna dict con `message`, raise `ValueError` su campi mancanti, `tenant_id=current_tenant_id()` sui record creati/risolti) + tool descriptor in `app/services/ai_tools.py` (enum coerenti coi valori reali, description chiare) + eventuale context in `ai_context.py`.
- Ogni query tenant-scoped (`current_tenant_id()`); soft-delete dove applicabile.
- Egress web: ogni uscita passa da `egress_guard.web_search_allowed_current(db)` (Content Lockdown TPN). Mai chiamata esterna se bloccato.
- i18n 5 lingue (`it/en/fr/de/es`) per ogni stringa UI nuova, stesso commit; `data-i18n`.
- Migrazione manuale idempotente `scripts/migrate_*.py` + `_auto_migrate_columns()` al boot per colonne nuove.
- Cache-buster automatico via `app_version` Jinja per static toccati (bump in Task 8).
- Modello estrazione = provider attivo del copilot (nessuna promozione al modello forte).
- Fonti web default seed: `["filmitalia.org", "cinema.cultura.gov.it", "imdb.com", "mymovies.it"]`.
- NO `JSON.stringify` in `onclick`; reuse global helpers (`api`, `escapeHtml`, `toast`, `mfT`).

---

### Task 1: `Tenant.web_sources` + migrazione + seed

**Files:**
- Modify: `app/models/models.py` (colonna su `Tenant`, ~riga 641 vicino a `naming_conventions`)
- Create: `scripts/migrate_web_sources.py`
- Modify: `app/main.py` (`_auto_migrate_columns`: ALTER `tenants` ADD `web_sources`)
- Test: `tests/test_web_sources_model.py`

**Interfaces:**
- Produces: `Tenant.web_sources` (JSON list[str], nullable). `DEFAULT_WEB_SOURCES` constant in `scripts/migrate_web_sources.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_sources_model.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant


def test_tenant_web_sources_column():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    t = Tenant(id=1, name="T", slug="t", is_active=True,
               web_sources=["filmitalia.org", "imdb.com"])
    s.add(t); s.commit(); s.refresh(t)
    assert t.web_sources == ["filmitalia.org", "imdb.com"]
    t2 = Tenant(id=2, name="U", slug="u", is_active=True)
    s.add(t2); s.commit(); s.refresh(t2)
    assert t2.web_sources is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_sources_model.py -v`
Expected: FAIL (`TypeError: 'web_sources' is an invalid keyword argument for Tenant`).

- [ ] **Step 3: Write minimal implementation**

In `app/models/models.py`, nella classe `Tenant`, vicino a `naming_conventions`:

```python
    # v3.5.0-alpha.172.237 — fonti web (domini) per l'incrocio dati AI (include_domains Tavily)
    web_sources: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
```

Crea `scripts/migrate_web_sources.py`:

```python
"""Migrazione non distruttiva — v3.5.0-alpha.172.237.
Aggiunge tenants.web_sources (JSON lista domini per incrocio web AI).
Idempotente. Seed default sui tenant con valore NULL."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import inspect, text
from app.database import engine

DEFAULT_WEB_SOURCES = ["filmitalia.org", "cinema.cultura.gov.it", "imdb.com", "mymovies.it"]


def main():
    insp = inspect(engine)
    if "tenants" not in insp.get_table_names():
        print("Tabella 'tenants' assente."); return
    cols = {c["name"] for c in insp.get_columns("tenants")}
    if "web_sources" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE tenants ADD COLUMN web_sources JSON NULL"))
        print("ADDED tenants.web_sources")
    # seed default dove NULL
    with engine.begin() as conn:
        conn.execute(text("UPDATE tenants SET web_sources = :v WHERE web_sources IS NULL"),
                     {"v": json.dumps(DEFAULT_WEB_SOURCES)})
    print("OK: seed default applicato dove mancante.")


if __name__ == "__main__":
    main()
```

In `app/main.py` `_auto_migrate_columns`, dopo il blocco `tenants` esistente (cerca `if "naming_conventions" not in tcols`), aggiungi nello stesso `if "tenants" in ...` block:

```python
        if "web_sources" not in tcols:
            print("[auto-migrate] tenants.web_sources mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN web_sources JSON NULL"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_sources_model.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models/models.py scripts/migrate_web_sources.py app/main.py tests/test_web_sources_model.py
git commit -m "feat(acquisizioni-f2): Tenant.web_sources + migrazione + seed"
```

---

### Task 2: `web_search` usa `include_domains` da `Tenant.web_sources`

**Files:**
- Modify: `app/services/ai_assistant.py` (`_h_web_search`, ~riga 746)
- Test: `tests/test_web_search_domains.py`

**Interfaces:**
- Consumes: `Tenant.web_sources` (Task 1), `egress_guard.web_search_allowed_current`, `web_search.tavily_search(query, max_results, search_depth, timeout, include_domains)`.
- Produces: `_h_web_search` ora passa `include_domains` = lista domini del tenant corrente (o `None` se vuota).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_search_domains.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant
import app.services.ai_assistant as aa


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True,
                 web_sources=["filmitalia.org", "imdb.com"])); s.commit()
    yield s
    s.close()


def test_web_search_passes_configured_domains(db, monkeypatch):
    captured = {}
    monkeypatch.setattr("app.services.egress_guard.web_search_allowed_current", lambda d: True)
    def fake_tavily(query, max_results=5, search_depth="basic", timeout=15, include_domains=None):
        captured["include_domains"] = include_domains
        return [{"title": "x", "url": "u", "content": "c"}]
    monkeypatch.setattr("app.services.web_search.tavily_search", fake_tavily)
    out = aa._h_web_search(db, {"query": "Lucky Red film 2026"})
    assert out["results"] is not None
    assert captured["include_domains"] == ["filmitalia.org", "imdb.com"]


def test_web_search_no_domains_when_empty(db, monkeypatch):
    db.query(Tenant).filter(Tenant.id == 1).first().web_sources = []
    db.commit()
    captured = {}
    monkeypatch.setattr("app.services.egress_guard.web_search_allowed_current", lambda d: True)
    monkeypatch.setattr("app.services.web_search.tavily_search",
        lambda query, **k: captured.update(k) or [{"title": "x", "url": "u", "content": "c"}])
    aa._h_web_search(db, {"query": "q"})
    assert captured.get("include_domains") in (None, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_search_domains.py -v`
Expected: FAIL (`include_domains` is None because handler doesn't pass it yet).

- [ ] **Step 3: Write minimal implementation**

In `app/services/ai_assistant.py` `_h_web_search`, prima della chiamata `tavily_search`, leggi i domini del tenant e passali:

```python
    from app.models.models import Tenant
    from app.context import current_tenant_id
    t = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first() if db is not None else None
    domains = (t.web_sources if t and t.web_sources else None)
    results = tavily_search(query, max_results=5, search_depth="basic", timeout=15,
                            include_domains=domains)
```

(Sostituisce la riga `results = tavily_search(query, max_results=5, search_depth="basic", timeout=15)`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_search_domains.py -v`
Expected: PASS (2 test).

- [ ] **Step 5: Commit**

```bash
git add app/services/ai_assistant.py tests/test_web_search_domains.py
git commit -m "feat(acquisizioni-f2): web_search usa include_domains dalle fonti tenant"
```

---

### Task 3: Capability `update_client`

**Files:**
- Modify: `app/services/ai_assistant.py` (nuovo handler)
- Modify: `app/services/ai_tools.py` (tool descriptor)
- Test: `tests/test_update_client_capability.py`

**Interfaces:**
- Produces: `@ai_capability("update_client")` `_h_update_client(db, data) -> dict` con `{updated, client_id, changed_fields, message}`. Aggiorna solo i campi forniti e non-None.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_update_client_capability.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, Client
from app.services.ai_capability_registry import get_handler
import app.services.ai_assistant  # noqa: F401  (registra handler)


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="Lucky Red", city="Roma")); s.commit()
    yield s
    s.close()


def test_update_client_only_changes_given_fields(db):
    h = get_handler("update_client")
    out = h(db, {"client_id": 1, "vat_number": "IT01234567890", "website": "luckyred.it"})
    db.commit()
    c = db.query(Client).get(1)
    assert c.vat_number == "IT01234567890"
    assert c.website == "luckyred.it"
    assert c.city == "Roma"  # invariato
    assert c.name == "Lucky Red"  # invariato
    assert set(out["changed_fields"]) == {"vat_number", "website"}


def test_update_client_missing_id_raises(db):
    with pytest.raises(ValueError):
        get_handler("update_client")(db, {"website": "x.it"})


def test_update_client_unknown_client_raises(db):
    with pytest.raises(ValueError):
        get_handler("update_client")(db, {"client_id": 999, "city": "Milano"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_update_client_capability.py -v`
Expected: FAIL (`get_handler("update_client")` → None).

- [ ] **Step 3: Write minimal implementation**

In `app/services/ai_assistant.py` (vicino a `_h_propose_client`):

```python
_UPDATE_CLIENT_FIELDS = (
    "name", "legal_form", "contact_name", "contact_role", "contact_email",
    "contact_phone", "admin_email", "vat_number", "tax_code", "sdi_code",
    "pec", "address", "city", "country", "zip_code", "province", "website",
    "industry", "company_size", "founded_year", "notes",
)


@ai_capability("update_client")
def _h_update_client(db: Session, data: dict) -> dict:
    from app.context import current_tenant_id
    cid = data.get("client_id")
    if not cid:
        raise ValueError("Manca 'client_id'")
    c = db.query(Client).filter(Client.id == cid,
                                Client.tenant_id == current_tenant_id()).first()
    if not c:
        raise ValueError(f"Cliente {cid} non trovato")
    changed = []
    for f in _UPDATE_CLIENT_FIELDS:
        if f in data and data[f] is not None and str(data[f]).strip() != "":
            setattr(c, f, data[f]); changed.append(f)
    db.flush()
    return {"updated": True, "client_id": c.id, "changed_fields": changed,
            "message": f"Cliente '{c.name}': aggiornati {', '.join(changed) or 'nessun campo'}."}
```

In `app/services/ai_tools.py`, aggiungi al `TOOLS`:

```python
    {
        "name": "update_client",
        "description": "Aggiorna i campi di un cliente ESISTENTE (client_id PK numerico). Usa propose_client per crearne uno nuovo. Aggiorna SOLO i campi forniti.",
        "input_schema": {"type": "object", "properties": {
            "client_id": {"type": "integer"},
            "vat_number": {"type": "string"}, "tax_code": {"type": "string"},
            "pec": {"type": "string"}, "sdi_code": {"type": "string"},
            "address": {"type": "string"}, "city": {"type": "string"},
            "province": {"type": "string"}, "zip_code": {"type": "string"},
            "country": {"type": "string"}, "website": {"type": "string"},
            "contact_name": {"type": "string"}, "contact_role": {"type": "string"},
            "contact_email": {"type": "string"}, "contact_phone": {"type": "string"},
            "admin_email": {"type": "string"}, "industry": {"type": "string"},
            "notes": {"type": "string"},
        }, "required": ["client_id"]},
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_update_client_capability.py -v`
Expected: PASS (3 test).

- [ ] **Step 5: Commit**

```bash
git add app/services/ai_assistant.py app/services/ai_tools.py tests/test_update_client_capability.py
git commit -m "feat(acquisizioni-f2): capability update_client"
```

---

### Task 4: Capability `propose_client_work`

**Files:**
- Modify: `app/services/ai_assistant.py` (nuovo handler)
- Modify: `app/services/ai_tools.py` (tool descriptor)
- Test: `tests/test_propose_client_work.py`

**Interfaces:**
- Consumes: `ClientWork` (models.py:1349 — campi: client_id, title, year, kind, our_role, director, country, sources_json (Text), notes, ai_imported (bool)).
- Produces: `@ai_capability("propose_client_work")` `_h_propose_client_work(db, data) -> dict` con `{created, client_work_id, message}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_propose_client_work.py
import pytest, json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, Client, ClientWork
from app.services.ai_capability_registry import get_handler
import app.services.ai_assistant  # noqa: F401


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="Lucky Red")); s.commit()
    yield s
    s.close()


def test_propose_client_work_creates_filmography_entry(db):
    h = get_handler("propose_client_work")
    out = h(db, {"client_id": 1, "title": "Queer", "year": 2024,
                 "kind": "film", "director": "Guadagnino",
                 "sources": ["https://imdb.com/x"]})
    db.commit()
    w = db.query(ClientWork).get(out["client_work_id"])
    assert w.title == "Queer" and w.year == 2024 and w.client_id == 1
    assert w.ai_imported is True
    assert "imdb.com" in (w.sources_json or "")


def test_propose_client_work_requires_title_and_client(db):
    with pytest.raises(ValueError):
        get_handler("propose_client_work")(db, {"client_id": 1})
    with pytest.raises(ValueError):
        get_handler("propose_client_work")(db, {"title": "X"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_propose_client_work.py -v`
Expected: FAIL (handler None).

- [ ] **Step 3: Write minimal implementation**

In `app/services/ai_assistant.py`:

```python
@ai_capability("propose_client_work")
def _h_propose_client_work(db: Session, data: dict) -> dict:
    from app.context import current_tenant_id
    import json as _json
    from app.models.models import ClientWork
    cid = data.get("client_id")
    title = (data.get("title") or "").strip()
    if not cid:
        raise ValueError("Manca 'client_id'")
    if not title:
        raise ValueError("Manca 'title'")
    c = db.query(Client).filter(Client.id == cid,
                                Client.tenant_id == current_tenant_id()).first()
    if not c:
        raise ValueError(f"Cliente {cid} non trovato")
    sources = data.get("sources")
    sources_json = _json.dumps(sources) if sources else None
    w = ClientWork(tenant_id=current_tenant_id(), client_id=cid, title=title,
                   year=data.get("year"), kind=data.get("kind"),
                   our_role=data.get("our_role"), director=data.get("director"),
                   country=data.get("country"), notes=data.get("notes"),
                   sources_json=sources_json, ai_imported=True)
    db.add(w); db.flush()
    return {"created": True, "client_work_id": w.id,
            "message": f"Filmografia: '{title}' aggiunta al cliente {cid}."}
```

In `app/services/ai_tools.py`, aggiungi al `TOOLS`:

```python
    {
        "name": "propose_client_work",
        "description": "Aggiunge una voce di filmografia/portfolio a un cliente ESISTENTE (da dati web). client_id PK numerico + title obbligatori.",
        "input_schema": {"type": "object", "properties": {
            "client_id": {"type": "integer"},
            "title": {"type": "string"},
            "year": {"type": "integer"},
            "kind": {"type": "string"},
            "our_role": {"type": "string"},
            "director": {"type": "string"},
            "country": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string"}},
        }, "required": ["client_id", "title"]},
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_propose_client_work.py -v`
Expected: PASS (2 test).

- [ ] **Step 5: Commit**

```bash
git add app/services/ai_assistant.py app/services/ai_tools.py tests/test_propose_client_work.py
git commit -m "feat(acquisizioni-f2): capability propose_client_work"
```

---

### Task 5: System prompt "email-aware"

**Files:**
- Modify: `app/services/ai_assistant.py` (`build_system_prompt`, ~riga 81)
- Test: `tests/test_email_aware_prompt.py`

**Interfaces:**
- Consumes: `build_system_prompt(db, *, use_tools, project_id=None, ...)` (esistente).
- Produces: il system prompt include una sezione di guida all'estrazione email (costante `EMAIL_EXTRACTION_GUIDANCE`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_aware_prompt.py
from app.services.ai_assistant import build_system_prompt


def test_prompt_contains_email_guidance_tools_mode():
    p = build_system_prompt(None, use_tools=True)
    assert "email" in p.lower()
    assert "propose_activity" in p
    assert "update_client" in p


def test_prompt_contains_email_guidance_legacy_mode():
    p = build_system_prompt(None, use_tools=False)
    assert "email" in p.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_aware_prompt.py -v`
Expected: FAIL (guidance assente, e/o `update_client` non citato).

- [ ] **Step 3: Write minimal implementation**

In `app/services/ai_assistant.py`, definisci la costante (vicino agli altri prompt) e appendila in `build_system_prompt` al testo restituito (in entrambe le modalità). Leggi `build_system_prompt` per trovare il punto in cui compone la stringa finale e aggiungi `+ "\n\n" + EMAIL_EXTRACTION_GUIDANCE`:

```python
EMAIL_EXTRACTION_GUIDANCE = """\
ESTRAZIONE DA EMAIL (Acquisizioni):
Quando l'utente incolla una conversazione email, estrai le informazioni rilevanti e proponi in UN turno il sottoinsieme pertinente di azioni, collegandole al contesto corrente (trattativa/cliente/progetto se presente):
- propose_activity: registra la comunicazione (type="email", direction inbound/outbound inferita, subject sintetico, body = testo email rilevante, next_action_date se c'è una scadenza).
- propose_contact: se la firma/testo rivela una persona nuova (nome, ruolo, email, telefono).
- update_client: se l'email rivela dati del cliente ESISTENTE (P.IVA, sede, sito, PEC, referente). NON inventare dati assenti.
- propose_acquisition_stage: se l'intento implica un avanzamento (es. brief ricevuto→qualified, discussione prezzo→negotiation) + next_action.
Non cercare sul web automaticamente: se utile, suggerisci all'utente il pulsante "Cerca sul web".
Regola: proponi solo ciò che è effettivamente nell'email; non inventare recapiti o P.IVA."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_aware_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/ai_assistant.py tests/test_email_aware_prompt.py
git commit -m "feat(acquisizioni-f2): system prompt email-aware"
```

---

### Task 6: Impostazioni — gestione fonti web

**Files:**
- Modify: `app/routers/settings.py` (endpoint `GET/POST /settings/api/web-sources`)
- Modify: `app/templates/pages/settings.html` (sezione "Fonti web")
- Modify: `app/static/js/i18n.js` (chiavi `settings.web_sources.*`)
- Test: `tests/test_web_sources_api.py`

**Interfaces:**
- Consumes: `Tenant.web_sources` (Task 1), `current_tenant_id()`.
- Produces: `GET /settings/api/web-sources` → `{sources: [..]}`; `POST /settings/api/web-sources` (Form `sources` = CSV o newline-separated) → salva lista pulita su `Tenant.web_sources`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_sources_api.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole
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
    role = Role(tenant_id=1, code="admin", name="A",
                permissions=["manage_settings_global"], is_system=True, is_active=True)
    s.add(role); s.flush()
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.admin, role_id=role.id, is_active=True)); s.commit()
    monkeypatch_engine(database, main_mod, e, S, s)
    tok = create_access_token({"sub": "a@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def monkeypatch_engine(database, main_mod, e, S, s):
    from app.database import get_db
    database.engine = e; database.SessionLocal = S
    main_mod.app.dependency_overrides[get_db] = lambda: s


def test_get_and_set_web_sources(client):
    c, s = client
    r = c.post("/settings/api/web-sources", data={"sources": "filmitalia.org\nimdb.com\n  \nmymovies.it"})
    assert r.status_code == 200, r.text
    assert r.json()["sources"] == ["filmitalia.org", "imdb.com", "mymovies.it"]
    g = c.get("/settings/api/web-sources").json()
    assert g["sources"] == ["filmitalia.org", "imdb.com", "mymovies.it"]
```

NOTA: il fixture replica il pattern auth-middleware già usato (monkeypatch `database.engine`+`SessionLocal`+`get_db`). Se l'helper `monkeypatch_engine` collide con l'ordine import, in alternativa usa `monkeypatch` di pytest come in `tests/test_acquisitions_api.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_sources_api.py -v`
Expected: FAIL (404, endpoint assente).

- [ ] **Step 3: Write minimal implementation**

In `app/routers/settings.py` (vicino agli altri endpoint, riusa `_resolve_current_user`/`current_tenant_id`):

```python
from app.context import current_tenant_id
from app.models.models import Tenant


def _parse_sources(raw: str) -> list:
    out = []
    for line in (raw or "").replace(",", "\n").splitlines():
        d = line.strip().lower()
        if d and d not in out:
            out.append(d)
    return out


@router.get("/api/web-sources")
async def web_sources_get(access_token: Optional[str] = Cookie(None),
                          db: Session = Depends(get_db)):
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(404, "Utente non trovato")
    t = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    return {"sources": (t.web_sources if t and t.web_sources else [])}


@router.post("/api/web-sources")
async def web_sources_set(sources: str = Form(""),
                          access_token: Optional[str] = Cookie(None),
                          db: Session = Depends(get_db)):
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(404, "Utente non trovato")
    from app.services.rbac import has_permission
    if not has_permission(u, "manage_settings_global"):
        raise HTTPException(403, "Permesso mancante")
    t = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    if not t:
        raise HTTPException(404, "Tenant non trovato")
    t.web_sources = _parse_sources(sources)
    db.commit()
    return {"ok": True, "sources": t.web_sources}
```

In `app/templates/pages/settings.html`, nel tab AI (o nuova card sotto i provider) aggiungi una sezione "Fonti web" con `<textarea id="web-sources-box">` (un dominio per riga) + bottone Salva che chiama `POST /settings/api/web-sources`, e caricamento iniziale via `GET`. Stringhe con `data-i18n`. JS: usa `api()`/`toast()`/`mfT()` globali.

In `app/static/js/i18n.js` aggiungi `settings.web_sources.title/desc/save/saved/placeholder` in 5 lingue.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_sources_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routers/settings.py app/templates/pages/settings.html app/static/js/i18n.js tests/test_web_sources_api.py
git commit -m "feat(acquisizioni-f2): impostazioni fonti web (Tenant.web_sources)"
```

---

### Task 7: Drawer copilot — "📥 Incolla email" + "🔎 Cerca sul web"

**Files:**
- Modify: `app/templates/components/copilot.html` (2 bottoni + JS)
- Modify: `app/static/js/i18n.js` (chiavi `copilot.email.*` / `copilot.web.*`)
- Test: smoke browser (controller, Step 4)

**Interfaces:**
- Consumes: la funzione JS esistente che invia un messaggio al copilot (`POST /ai/api/chat`). Leggi `copilot.html` per il nome reale della funzione di invio (es. `cpSend`/`sendMessage`) e il campo input.

- [ ] **Step 1: Aggiungi i bottoni**

In `app/templates/components/copilot.html`, vicino alla `.cp-input-bar`, aggiungi due bottoni piccoli:

```html
<button type="button" id="cp-paste-email" class="btn btn-ghost btn-sm" data-i18n-attr="title" data-i18n="copilot.email.btn" title="Incolla email">📥</button>
<button type="button" id="cp-web-search" class="btn btn-ghost btn-sm" data-i18n-attr="title" data-i18n="copilot.web.btn" title="Cerca sul web">🔎</button>
```

- [ ] **Step 2: JS — incolla email**

Aggiungi (riusa la funzione di invio reale trovata in copilot.html; qui chiamata `cpSendMessage(text)` come placeholder — sostituisci col nome reale):

```javascript
document.getElementById('cp-paste-email')?.addEventListener('click', () => {
  const email = prompt(mfT('copilot.email.prompt'));
  if (!email || !email.trim()) return;
  const wrapped = mfT('copilot.email.instruction') + "\n\n" + email.trim();
  cpSendMessage(wrapped);   // <-- nome reale della funzione di invio
});
document.getElementById('cp-web-search')?.addEventListener('click', () => {
  cpSendMessage(mfT('copilot.web.instruction'));
});
```

`copilot.email.instruction` = "Estrai le informazioni rilevanti da questa email e proponi le azioni adatte (attività, contatto, aggiornamento cliente, avanzamento trattativa), collegandole al contesto corrente." ; `copilot.web.instruction` = "Cerca sul web informazioni sul cliente e sul progetto correnti usando le fonti configurate, poi proponi gli aggiornamenti."

- [ ] **Step 3: i18n**

In `app/static/js/i18n.js` aggiungi in 5 lingue: `copilot.email.btn`, `copilot.email.prompt`, `copilot.email.instruction`, `copilot.web.btn`, `copilot.web.instruction`.

- [ ] **Step 4: Smoke (controller)**

Verifica import: `.venv/Scripts/python.exe -c "import app.main"`. Il controller esegue lo smoke browser: aprire il drawer, cliccare 📥, incollare un'email demo, verificare che il copilot risponda con card AIAction; cliccare 🔎 con egress on/off. (Il subagent non ha browser: si limita a import + grep funzione invio corretta.)

- [ ] **Step 5: Commit**

```bash
git add app/templates/components/copilot.html app/static/js/i18n.js
git commit -m "feat(acquisizioni-f2): bottoni incolla-email + cerca-web nel copilot"
```

---

### Task 8: Integrazione — bump + suite + docs

**Files:**
- Modify: `app/main.py` (version `3.5.0-alpha.172.237`)
- Modify: `CHANGELOG.md`, `docs/STATO.md`
- Test: full suite

- [ ] **Step 1: Full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tutti verdi (992 esistenti + nuovi).

- [ ] **Step 2: Bump + docs**

- `app/main.py`: `version="3.5.0-alpha.172.237"`.
- `CHANGELOG.md` + `docs/STATO.md`: sezione Fase 2 (estrazione email + fonti web + capability update_client/propose_client_work + web_search domini). Prossimo step = Fase 3 (calendario).

- [ ] **Step 3: graphify + commit**

```bash
graphify update .
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -m "chore(acquisizioni-f2): bump v3.5.0-alpha.172.237 + docs"
```

- [ ] **Step 4: Verifica finale**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: verde.

---

## Self-Review (eseguito)

**Spec coverage**: email-aware prompt (T5) · estrazioni via propose_activity/contact/update_client(T3)/acquisition_stage · update_client (T3) · propose_client_work (T4) · web_search con include_domains (T2) · Tenant.web_sources + migrazione/seed (T1) · settings fonti web (T6) · bottoni drawer incolla-email + cerca-web (T7) · egress gate (riusato in web_search, T2) · bump/docs (T8). Tutte le sezioni spec coperte. Lo "step web = turno copilot" non richiede capability nuova oltre quelle: usa web_search(T2)+update_client(T3)+propose_project_metadata(esistente)+propose_client_work(T4) guidati dal prompt (T5/T7).

**Placeholder scan**: nessun TBD/TODO; codice concreto. T7 indica esplicitamente di sostituire `cpSendMessage` col nome reale della funzione di invio (trovato leggendo copilot.html) — non è un placeholder di logica ma un punto d'integrazione locale, con lo smoke a verifica.

**Type consistency**: `update_client` ritorna `changed_fields` (lista) coerente tra T3 e test; `propose_client_work` ritorna `client_work_id`; `web_search` passa `include_domains` (firma `tavily_search` esistente); `Tenant.web_sources` lista[str] coerente tra T1/T2/T6; `_parse_sources` normalizza (lowercase, dedup, no vuoti) coerente col test T6.

## Out of scope (Fase 3)
Agenda piena + Google Calendar (OAuth)/ICS; parsing allegati email; ingest mailbox automatico (IMAP/OAuth).
