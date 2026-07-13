# Media Library — Fase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attivare le azioni mutanti in `/media` (associa / archivia / export CSV / unlink) con semantica **supersede** (storico mantenuto + auto-reset stato consegna).

**Architecture:** Nuovo servizio `media_actions.py` (read-write) separato da `media_library.py` (read-only). Riusa `deliverable_assets.link_asset/unlink_asset` come fonte di verità dei link. Supersede via 3 colonne nuove su `DeliverableAsset`. Endpoint POST Form su `media.py` dietro gate `manage_assets`. UI vanilla estende `media_library.js`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (SQLite) + Jinja2 + vanilla JS (`global.js` helpers, `i18n.js`) + pytest + Playwright (smoke).

## Global Constraints

- Ramo: continuare su `feat/media-library` (Fase A già lì). Verificare `git branch --show-current` = `feat/media-library`.
- Tenant filter obbligatorio su OGNI query: `tenant_id == current_tenant_id()` (da `app.context`).
- Visibilità TPN: riusare `is_admin(user)` + `accessible_project_ids(user, db)` come in `media_library.py`.
- Form-based API per i POST: `Form(...)`, non JSON. Liste passate come stringa JSON in un campo Form (`items`), parse server-side con `safe_json_parse` o `json.loads` in try.
- Soft-delete / storico: mai DELETE fisico dei link superati. Supersede via colonne.
- i18n: ogni stringa UI nuova in 5 lingue (`it/en/fr/de/es`) in `app/static/js/i18n.js`, stesso commit.
- Auto-migrate al boot: ogni colonna nuova va aggiunta in `_auto_migrate_columns()` in `main.py`, altrimenti crash su DB non migrato.
- Nessun nuovo static file JS/CSS (si estende `media_library.js`); il bump versione a fine fase invalida `?v=`.
- Python: eseguire i test con `.venv/Scripts/python.exe -m pytest`.
- Test router: JWT cookie reale + `monkeypatch` di `app.database.engine`/`SessionLocal` + `dependency_overrides[get_db]` (pattern `tests/test_media_api.py`).
- Bump versione + CHANGELOG + STATO a fine Fase B (ultimo task). Versione corrente `3.5.0-alpha.172.244` → prossima `3.5.0-alpha.172.245`.

---

## File Structure

- **Modify** `app/models/models.py` — 3 colonne su `DeliverableAsset` (`superseded_at`, `superseded_by_id`, `supersede_reason`) + valore `deliverable_reopened_supersede` su `NotificationKind`.
- **Modify** `app/services/deliverable_assets.py` — `_resync_primary` ignora righe superseded.
- **Create** `scripts/migrate_deliverable_asset_supersede.py` — ALTER idempotente.
- **Modify** `app/main.py` — `_auto_migrate_columns()`: ADD COLUMN difensivo su `deliverable_assets`; bump versione.
- **Create** `app/services/media_actions.py` — `associate` / `set_flags` / `unlink` / `export_manifest_csv`.
- **Modify** `app/routers/media.py` — 5 endpoint nuovi (associate/flags/unlink/export/deliverables).
- **Modify** `app/templates/pages/media_library.html` — modal Associa + markup azioni.
- **Modify** `app/static/js/media_library.js` — abilita bulk + modal + azioni + badge supersede.
- **Modify** `app/static/js/i18n.js` — chiavi `media.*` azioni in 5 lingue.
- **Create** `tests/test_media_actions.py` — unit servizio.
- **Modify** `tests/test_media_api.py` — endpoint nuovi.
- **Modify** `CHANGELOG.md`, `docs/STATO.md` — a fine fase.

---

### Task 1: Modello supersede + migrazione + resync

**Files:**
- Modify: `app/models/models.py` (`DeliverableAsset` ~riga 3862; `NotificationKind` ~riga 481)
- Modify: `app/services/deliverable_assets.py` (`_resync_primary` righe 30-56)
- Create: `scripts/migrate_deliverable_asset_supersede.py`
- Modify: `app/main.py` (`_auto_migrate_columns` ~riga 41)
- Test: `tests/test_media_supersede_model.py`

**Interfaces:**
- Produces: colonne `DeliverableAsset.superseded_at: datetime|None`, `.superseded_by_id: int|None`, `.supersede_reason: str|None`; `NotificationKind.deliverable_reopened_supersede`; `_resync_primary` che ignora righe con `superseded_at != None`.

- [ ] **Step 1: Scrivere il test del modello + resync**

`tests/test_media_supersede_model.py`:
```python
from datetime import UTC, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Project, Job, Asset, AssetType, AssetProposedState,
    JobDeliverable, DeliverableAsset, DeliverableStatus, DeliverableNature,
    NotificationKind, User, UserRole,
)
from app.services.deliverable_assets import _resync_primary


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, expire_on_commit=False)()


def test_notificationkind_has_supersede():
    assert NotificationKind.deliverable_reopened_supersede.value == "deliverable_reopened_supersede"


def test_deliverableasset_supersede_columns_exist():
    cols = {c.name for c in DeliverableAsset.__table__.columns}
    assert {"superseded_at", "superseded_by_id", "supersede_reason"} <= cols


def test_resync_primary_ignores_superseded():
    db = _session()
    db.add(Tenant(id=1, name="T", slug="t")); db.flush()
    cl = Client(tenant_id=1, name="C"); db.add(cl); db.flush()
    pr = Project(tenant_id=1, code="P", title="P", client_id=cl.id); db.add(pr); db.flush()
    u = User(id=1, tenant_id=1, email="a@t.l", full_name="A", hashed_password="x",
             role=UserRole.admin, is_active=True); db.add(u); db.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    a_old = Asset(tenant_id=1, filename="old.mov", original_name="old.mov", file_path="/o",
                  file_size=1, mime_type="video/quicktime", asset_type=AssetType.video,
                  uploaded_by=1, project_id=pr.id, proposed_state=AssetProposedState.confirmed,
                  created_at=now); db.add(a_old)
    a_new = Asset(tenant_id=1, filename="new.mov", original_name="new.mov", file_path="/n",
                  file_size=1, mime_type="video/quicktime", asset_type=AssetType.video,
                  uploaded_by=1, project_id=pr.id, proposed_state=AssetProposedState.confirmed,
                  created_at=now); db.add(a_new); db.flush()
    jd = JobDeliverable(tenant_id=1, job_id=1, name="DCP", nature=DeliverableNature.digital,
                        status=DeliverableStatus.delivered); db.add(jd); db.flush()
    link_old = DeliverableAsset(tenant_id=1, job_deliverable_id=jd.id, asset_id=a_old.id)
    db.add(link_old); db.flush()
    link_new = DeliverableAsset(tenant_id=1, job_deliverable_id=jd.id, asset_id=a_new.id)
    db.add(link_new); db.flush()
    # marca old come superseded
    link_old.superseded_at = now
    link_old.superseded_by_id = link_new.id
    db.flush()
    _resync_primary(db, jd)
    assert jd.digital_asset_id == a_new.id   # il primario NON è il superseded
```

- [ ] **Step 2: Eseguire — deve fallire**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_supersede_model.py -v`
Expected: FAIL (`deliverable_reopened_supersede` assente / colonne assenti).

- [ ] **Step 3: Aggiungere il valore a `NotificationKind`**

In `app/models/models.py`, dentro `class NotificationKind` (dopo `deliverable_qc_rejected` ~riga 481):
```python
    deliverable_reopened_supersede = "deliverable_reopened_supersede"  # → view_finance (asset superseduto in Media Library)
```

- [ ] **Step 4: Aggiungere le colonne a `DeliverableAsset`**

In `app/models/models.py`, dentro `class DeliverableAsset` (dopo `notes` ~riga 3885):
```python
    # Fase B Media Library — supersede: un asset riprodotto (errore/QC negativo)
    # sostituisce il precedente. Il vecchio link resta come storico.
    superseded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    superseded_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deliverable_assets.id"), nullable=True
    )
    supersede_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
```
(Verificare che `Optional`, `datetime`, `DateTime`, `String`, `ForeignKey`, `mapped_column`, `Mapped` siano già importati in `models.py` — lo sono, usati ovunque.)

- [ ] **Step 5: Aggiornare `_resync_primary`**

In `app/services/deliverable_assets.py`, nella funzione `_resync_primary` (righe 40-49), aggiungere il filtro superseded alle due comprensioni:
```python
    prim_digital = next(
        (r.asset_id for r in rows
         if r.asset_id is not None
         and r.superseded_at is None
         and (r.source or "") not in _NON_PRIMARY_SOURCES),
        None,
    )
    prim_physical = next(
        (r.physical_asset_id for r in rows
         if r.physical_asset_id is not None
         and r.superseded_at is None
         and (r.source or "") not in _NON_PRIMARY_SOURCES),
        None,
    )
```

- [ ] **Step 6: Eseguire — devono passare**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_supersede_model.py -v`
Expected: PASS.

- [ ] **Step 7: Scrivere la migrazione**

Create `scripts/migrate_deliverable_asset_supersede.py`:
```python
"""Aggiunge le colonne supersede a deliverable_assets (Fase B Media Library).
Idempotente: rilanciabile senza effetti doppi."""
from sqlalchemy import inspect, text
from app.database import engine


def run():
    insp = inspect(engine)
    if "deliverable_assets" not in insp.get_table_names():
        print("[migrate_supersede] tabella deliverable_assets assente, skip")
        return
    cols = {c["name"] for c in insp.get_columns("deliverable_assets")}
    alters = [
        ("superseded_at", "DATETIME NULL"),
        ("superseded_by_id", "INTEGER NULL REFERENCES deliverable_assets(id)"),
        ("supersede_reason", "VARCHAR(255) NULL"),
    ]
    added = 0
    with engine.begin() as conn:
        for col, ddl in alters:
            if col not in cols:
                conn.execute(text(f"ALTER TABLE deliverable_assets ADD COLUMN {col} {ddl}"))
                added += 1
    print(f"[migrate_supersede] colonne aggiunte: {added}")


if __name__ == "__main__":
    run()
```

- [ ] **Step 8: Auto-migrate al boot**

In `app/main.py`, dentro `_auto_migrate_columns()` (dopo il blocco `users`, prima della fine funzione), aggiungere:
```python
    # v3.5.0-alpha.172.245 — Fase B Media Library: supersede su deliverable_assets
    if "deliverable_assets" in insp.get_table_names():
        da_cols = {c["name"] for c in insp.get_columns("deliverable_assets")}
        da_alter = [
            ("superseded_at", "DATETIME NULL"),
            ("superseded_by_id", "INTEGER NULL REFERENCES deliverable_assets(id)"),
            ("supersede_reason", "VARCHAR(255) NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in da_alter:
                if col not in da_cols:
                    print(f"[auto-migrate] deliverable_assets.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE deliverable_assets ADD COLUMN {col} {ddl}"))
```
(`insp`, `text`, `engine` sono già in scope nella funzione.)

- [ ] **Step 9: Commit**

```bash
git add app/models/models.py app/services/deliverable_assets.py scripts/migrate_deliverable_asset_supersede.py app/main.py tests/test_media_supersede_model.py
git commit -m "feat(media): colonne supersede DeliverableAsset + resync + migrazione"
```

---

### Task 2: Servizio `associate` + supersede + auto-reset

**Files:**
- Create: `app/services/media_actions.py`
- Test: `tests/test_media_actions.py`

**Interfaces:**
- Consumes: `deliverable_assets.link_asset`; colonne supersede (Task 1).
- Produces: `associate(db, user, *, deliverable_id: int, items: list[dict], reason: str|None = None) -> dict` con `{"linked": int, "superseded": int, "status_reset": bool}`. `items` = `[{"nature": "digital"|"physical", "id": int}]`.

- [ ] **Step 1: Scrivere i test associate + supersede + auto-reset**

`tests/test_media_actions.py` (fixture `ctx` analoga a `tests/test_media_library.py`: Tenant(1), Client, Project(code="PRJ001"), admin User, 2 Asset video confirmed `a_old`/`a_new`, 1 PhysicalAsset, 1 JobDeliverable `jd_delivered` status=delivered nature=digital, 1 `jd_progress` status=in_progress):
```python
from app.services import media_actions

def test_associate_creates_link(ctx):
    db, admin, jd = ctx["db"], ctx["admin"], ctx["jd_progress"]
    out = media_actions.associate(db, admin, deliverable_id=jd.id,
                                  items=[{"nature": "digital", "id": ctx["a_new"].id}])
    db.commit()
    assert out["linked"] == 1
    assert jd.digital_asset_id == ctx["a_new"].id

def test_associate_supersedes_active_same_nature(ctx):
    db, admin, jd = ctx["db"], ctx["admin"], ctx["jd_delivered"]
    # a_old già linkato attivo (nel fixture)
    out = media_actions.associate(db, admin, deliverable_id=jd.id,
                                  items=[{"nature": "digital", "id": ctx["a_new"].id}],
                                  reason="QC negativo")
    db.commit()
    assert out["superseded"] == 1
    from app.models.models import DeliverableAsset
    old = db.query(DeliverableAsset).filter(
        DeliverableAsset.job_deliverable_id == jd.id,
        DeliverableAsset.asset_id == ctx["a_old"].id).first()
    assert old.superseded_at is not None
    assert old.supersede_reason == "QC negativo"
    assert jd.digital_asset_id == ctx["a_new"].id

def test_associate_auto_reset_status_from_delivered(ctx):
    db, admin, jd = ctx["db"], ctx["admin"], ctx["jd_delivered"]
    from app.models.models import DeliverableStatus
    out = media_actions.associate(db, admin, deliverable_id=jd.id,
                                  items=[{"nature": "digital", "id": ctx["a_new"].id}])
    db.commit()
    assert out["status_reset"] is True
    assert jd.status == DeliverableStatus.in_progress
    assert jd.qc_substatus is None

def test_associate_no_reset_when_in_progress(ctx):
    db, admin, jd = ctx["db"], ctx["admin"], ctx["jd_progress"]
    from app.models.models import DeliverableStatus
    out = media_actions.associate(db, admin, deliverable_id=jd.id,
                                  items=[{"nature": "digital", "id": ctx["a_new"].id}])
    db.commit()
    assert out["status_reset"] is False
    assert jd.status == DeliverableStatus.in_progress

def test_associate_deliverable_other_tenant_raises(ctx):
    db, admin = ctx["db"], ctx["admin"]
    import pytest
    with pytest.raises(media_actions.MediaActionError):
        media_actions.associate(db, admin, deliverable_id=999999,
                                items=[{"nature": "digital", "id": ctx["a_new"].id}])
```
(Nel fixture: linkare `a_old` a `jd_delivered` con `DeliverableAsset(tenant_id=1, job_deliverable_id=jd_delivered.id, asset_id=a_old.id)` + `jd_delivered.digital_asset_id = a_old.id`.)

- [ ] **Step 2: Eseguire — deve fallire**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_actions.py -v`
Expected: FAIL (`media_actions` inesistente).

- [ ] **Step 3: Implementare `associate`**

Create `app/services/media_actions.py`:
```python
"""Media Library — azioni mutanti (Fase B). Read-write, tenant-scoped.
Riusa deliverable_assets.link_asset/unlink_asset come fonte di verità dei
link. Nessuna funzione committa (commit gestito dal router)."""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session

from app.models.models import (
    Asset, PhysicalAsset, JobDeliverable, DeliverableAsset,
    DeliverableStatus, now_utc,
)
from app.context import current_tenant_id
from app.services.rbac import is_admin
from app.services.project_access import accessible_project_ids
from app.services.deliverable_assets import link_asset, unlink_asset

# Stati consegna "avanzati" da cui un supersede fa tornare indietro a in_progress.
_REOPEN_FROM = {DeliverableStatus.qc, DeliverableStatus.delivered, DeliverableStatus.closed}


class MediaActionError(Exception):
    """Errore applicativo (entità mancante / non accessibile / input invalido)."""


def _get_deliverable(db: Session, user, deliverable_id: int) -> JobDeliverable:
    jd = db.query(JobDeliverable).filter(
        JobDeliverable.id == deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
        JobDeliverable.deleted_at.is_(None),
    ).first()
    if not jd:
        raise MediaActionError("Consegna non trovata")
    if not is_admin(user) and jd.job_id is not None:
        # visibilità: la consegna appartiene a un job del progetto accessibile
        from app.models.models import Job
        job = db.get(Job, jd.job_id)
        if job and job.project_id and job.project_id not in accessible_project_ids(user, db):
            raise MediaActionError("Consegna non accessibile")
    return jd


def _active_link_same_nature(db: Session, jd: JobDeliverable, nature: str) -> Optional[DeliverableAsset]:
    q = db.query(DeliverableAsset).filter(
        DeliverableAsset.job_deliverable_id == jd.id,
        DeliverableAsset.superseded_at.is_(None),
    )
    if nature == "digital":
        q = q.filter(DeliverableAsset.asset_id.isnot(None))
    else:
        q = q.filter(DeliverableAsset.physical_asset_id.isnot(None))
    return q.order_by(DeliverableAsset.confirmed_at.desc(), DeliverableAsset.id.desc()).first()


def associate(db: Session, user, *, deliverable_id: int, items: list, reason: Optional[str] = None) -> dict:
    jd = _get_deliverable(db, user, deliverable_id)
    linked = superseded = 0
    for it in items or []:
        nature = it.get("nature")
        aid = int(it.get("id"))
        if nature not in ("digital", "physical"):
            continue
        prev = _active_link_same_nature(db, jd, nature)
        if nature == "digital":
            new_link = link_asset(db, jd, asset_id=aid, source="manual", user_id=user.id, notes=reason)
        else:
            new_link = link_asset(db, jd, physical_asset_id=aid, source="manual", user_id=user.id, notes=reason)
        linked += 1
        # supersede: c'era un attivo DIVERSO della stessa natura
        if prev is not None and prev.id != new_link.id:
            prev.superseded_at = now_utc()
            prev.superseded_by_id = new_link.id
            prev.supersede_reason = reason
            superseded += 1
    status_reset = False
    if superseded and jd.status in _REOPEN_FROM:
        jd.status = DeliverableStatus.in_progress
        jd.qc_substatus = None
        status_reset = True
        _notify_reopen(db, jd, user, reason)
    db.flush()
    return {"linked": linked, "superseded": superseded, "status_reset": status_reset}


def _notify_reopen(db, jd, user, reason):
    try:
        from app.services.notifications import notify_permission
        body = f"Consegna '{jd.name}' riaperta: asset superseduto in Media Library."
        if reason:
            body += f"\n\nMotivo: {reason}"
        notify_permission(
            db, permission="view_finance",
            kind="deliverable_reopened_supersede", severity="action_required",
            title=f"Consegna riaperta — {jd.name[:60]}", body=body,
            link=f"/cost-report#job-{jd.job_id}",
            payload={"deliverable_id": jd.id, "job_id": jd.job_id},
            actor_user_id=user.id, tenant_id=jd.tenant_id, commit=False,
        )
    except Exception as e:
        print(f"[media_actions] notify reopen failed (non bloccante): {e}")
```

- [ ] **Step 4: Eseguire — devono passare**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_actions.py -v`
Expected: PASS (i test associate/supersede/reset).

- [ ] **Step 5: Commit**

```bash
git add app/services/media_actions.py tests/test_media_actions.py
git commit -m "feat(media): media_actions.associate + supersede + auto-reset stato"
```

---

### Task 3: Servizio `set_flags` + `unlink`

**Files:**
- Modify: `app/services/media_actions.py`
- Test: `tests/test_media_actions.py`

**Interfaces:**
- Consumes: `unlink_asset` (deliverable_assets); modelli Asset/PhysicalAsset.
- Produces: `set_flags(db, user, items, *, internal_archive=None, delivered_external=None) -> dict` (`{"updated": int}`); `unlink(db, user, *, deliverable_id, items) -> dict` (`{"removed": int}`).

- [ ] **Step 1: Scrivere i test flags + unlink**

Aggiungere a `tests/test_media_actions.py`:
```python
def test_set_flags_toggle(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_actions.set_flags(db, admin,
        [{"nature": "digital", "id": ctx["a_new"].id},
         {"nature": "physical", "id": ctx["lto"].id}],
        internal_archive=True)
    db.commit()
    assert out["updated"] == 2
    db.refresh(ctx["a_new"]); db.refresh(ctx["lto"])
    assert ctx["a_new"].is_internal_archive is True
    assert ctx["lto"].is_internal_archive is True

def test_set_flags_tenant_scope(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_actions.set_flags(db, admin,
        [{"nature": "digital", "id": ctx["other_tenant_asset"].id}],
        delivered_external=True)
    db.commit()
    assert out["updated"] == 0  # altro tenant: non toccato

def test_unlink_removes_pivot(ctx):
    db, admin, jd = ctx["db"], ctx["admin"], ctx["jd_delivered"]
    out = media_actions.unlink(db, admin, deliverable_id=jd.id,
                               items=[{"nature": "digital", "id": ctx["a_old"].id}])
    db.commit()
    assert out["removed"] == 1
    from app.models.models import DeliverableAsset
    assert db.query(DeliverableAsset).filter(
        DeliverableAsset.job_deliverable_id == jd.id,
        DeliverableAsset.asset_id == ctx["a_old"].id).count() == 0
```
(Fixture: aggiungere `other_tenant_asset` di tenant 2 e `lto` PhysicalAsset se non già presenti.)

- [ ] **Step 2: Eseguire — nuovi test falliscono**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_actions.py -k "flags or unlink" -v`
Expected: FAIL.

- [ ] **Step 3: Implementare `set_flags` + `unlink`**

Aggiungere a `app/services/media_actions.py`:
```python
def set_flags(db: Session, user, items: list, *, internal_archive=None, delivered_external=None) -> dict:
    tid = current_tenant_id()
    updated = 0
    for it in items or []:
        nature = it.get("nature")
        aid = int(it.get("id"))
        model = Asset if nature == "digital" else PhysicalAsset if nature == "physical" else None
        if model is None:
            continue
        obj = db.query(model).filter(model.id == aid, model.tenant_id == tid).first()
        if not obj:
            continue
        if not is_admin(user):
            if obj.project_id is None or obj.project_id not in accessible_project_ids(user, db):
                continue
        if internal_archive is not None:
            obj.is_internal_archive = bool(internal_archive)
        if delivered_external is not None:
            obj.is_delivered_external = bool(delivered_external)
        updated += 1
    db.flush()
    return {"updated": updated}


def unlink(db: Session, user, *, deliverable_id: int, items: list) -> dict:
    jd = _get_deliverable(db, user, deliverable_id)
    removed = 0
    for it in items or []:
        nature = it.get("nature")
        aid = int(it.get("id"))
        if nature == "digital":
            removed += unlink_asset(db, jd, asset_id=aid)
        elif nature == "physical":
            removed += unlink_asset(db, jd, physical_asset_id=aid)
    db.flush()
    return {"removed": removed}
```
(Nota: `set_flags` per asset con `project_id is None` (coda interna) e utente non-admin li salta — coerente con la visibilità restrittiva sulle mutazioni. Admin tocca tutto.)

- [ ] **Step 4: Eseguire — tutti passano**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_actions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/media_actions.py tests/test_media_actions.py
git commit -m "feat(media): media_actions.set_flags + unlink"
```

---

### Task 4: Servizio `export_manifest_csv`

**Files:**
- Modify: `app/services/media_actions.py`
- Test: `tests/test_media_actions.py`

**Interfaces:**
- Consumes: `media_library.list_assets` (per il ramo filtri); `media_library.asset_detail` (per il ramo items).
- Produces: `export_manifest_csv(db, user, *, items=None, filters=None, cap=5000) -> str` (stringa CSV UTF-8 con header).

- [ ] **Step 1: Scrivere il test export**

Aggiungere a `tests/test_media_actions.py`:
```python
def test_export_csv_from_filters(ctx):
    db, admin = ctx["db"], ctx["admin"]
    csv = media_actions.export_manifest_csv(db, admin, filters={"nature": "digital"})
    lines = csv.strip().splitlines()
    assert lines[0].startswith("nature,name,type")
    assert any("a.mov" in ln for ln in lines[1:]) or any("new.mov" in ln for ln in lines[1:])

def test_export_csv_from_items(ctx):
    db, admin = ctx["db"], ctx["admin"]
    csv = media_actions.export_manifest_csv(db, admin,
        items=[{"nature": "physical", "id": ctx["lto"].id}])
    assert "LTO-SMK-001" in csv or "physical" in csv
```

- [ ] **Step 2: Eseguire — falliscono**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_actions.py -k export -v`
Expected: FAIL.

- [ ] **Step 3: Implementare `export_manifest_csv`**

Aggiungere a `app/services/media_actions.py` (import `csv`, `io` in cima al file):
```python
import csv as _csv
import io

_CSV_COLUMNS = ["nature", "name", "type", "project_code", "client", "department",
                "delivery_status", "linked_to_delivery", "checksum", "size_bytes",
                "storage_path", "created_at"]


def _row_to_csv_dict(r: dict) -> dict:
    return {
        "nature": r.get("nature"),
        "name": r.get("name"),
        "type": r.get("asset_type") or r.get("physical_kind") or "",
        "project_code": (r.get("project") or {}).get("code") if r.get("project") else "",
        "client": (r.get("client") or {}).get("name") if r.get("client") else "",
        "department": (r.get("department") or {}).get("name") if r.get("department") else "",
        "delivery_status": r.get("delivery_status") or "",
        "linked_to_delivery": "yes" if r.get("linked_to_delivery") else "no",
        "checksum": r.get("checksum") or "",
        "size_bytes": r.get("size_bytes") or "",
        "storage_path": (r.get("storage") or {}).get("path") if r.get("storage") else "",
        "created_at": r.get("created_at") or "",
    }


def export_manifest_csv(db: Session, user, *, items=None, filters=None, cap: int = 5000) -> str:
    from app.services import media_library
    rows = []
    if items:
        for it in items:
            d = media_library.asset_detail(db, user, it.get("nature"), int(it.get("id")))
            if d:
                rows.append(d)
    else:
        out = media_library.list_assets(db, user, filters or {}, offset=0, limit=cap)
        rows = out["rows"]
    buf = io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(_row_to_csv_dict(r))
    return buf.getvalue()
```

- [ ] **Step 4: Eseguire — passano**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_actions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/media_actions.py tests/test_media_actions.py
git commit -m "feat(media): media_actions.export_manifest_csv"
```

---

### Task 5: Endpoint router + API test

**Files:**
- Modify: `app/routers/media.py`
- Test: `tests/test_media_api.py`

**Interfaces:**
- Consumes: `media_actions.associate/set_flags/unlink/export_manifest_csv`; `media_gate.requires_manage_assets`.
- Produces: `POST /media/api/associate`, `POST /media/api/flags`, `POST /media/api/unlink`, `GET /media/api/export`, `GET /media/api/deliverables`.

- [ ] **Step 1: Scrivere i test router**

Aggiungere a `tests/test_media_api.py`:
```python
def test_associate_ok(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_actions, "associate",
                        lambda db, u, **k: {"linked": 1, "superseded": 1, "status_reset": True})
    r = c.post("/media/api/associate", data={"deliverable_id": "1",
               "items": '[{"nature":"digital","id":5}]', "reason": "QC"})
    assert r.status_code == 200 and r.json()["superseded"] == 1

def test_associate_bad_items_400(client):
    c, s = client
    r = c.post("/media/api/associate", data={"deliverable_id": "1", "items": "not-json"})
    assert r.status_code == 400

def test_associate_missing_deliverable_404(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    def _raise(db, u, **k):
        raise m.media_actions.MediaActionError("x")
    monkeypatch.setattr(m.media_actions, "associate", _raise)
    r = c.post("/media/api/associate", data={"deliverable_id": "9",
               "items": '[{"nature":"digital","id":5}]'})
    assert r.status_code == 404

def test_flags_ok(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_actions, "set_flags", lambda db, u, items, **k: {"updated": 2})
    r = c.post("/media/api/flags", data={"items": '[{"nature":"digital","id":1}]',
               "internal_archive": "1"})
    assert r.status_code == 200 and r.json()["updated"] == 2

def test_unlink_ok(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_actions, "unlink", lambda db, u, **k: {"removed": 1})
    r = c.post("/media/api/unlink", data={"deliverable_id": "1",
               "items": '[{"nature":"digital","id":1}]'})
    assert r.status_code == 200 and r.json()["removed"] == 1

def test_export_csv_download(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_actions, "export_manifest_csv", lambda db, u, **k: "nature,name\ndigital,x\n")
    r = c.get("/media/api/export?nature=digital")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")

def test_associate_denied_viewer(client):
    c, s = client
    vc = _viewer_client(s)
    r = vc.post("/media/api/associate", data={"deliverable_id": "1", "items": "[]"})
    assert r.status_code == 403
```

- [ ] **Step 2: Eseguire — falliscono**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_api.py -k "associate or flags or unlink or export" -v`
Expected: FAIL.

- [ ] **Step 3: Implementare gli endpoint**

In `app/routers/media.py`, aggiungere import in cima:
```python
import json
from fastapi import Form
from fastapi.responses import PlainTextResponse
from app.database import get_db
from app.services import media_actions
```
(alcuni import già presenti; non duplicare). Poi aggiungere in fondo al file:
```python
def _parse_items(raw: str):
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        raise HTTPException(400, "items malformato (atteso JSON)")
    if not isinstance(data, list):
        raise HTTPException(400, "items deve essere una lista")
    return data


def _bool_or_none(v):
    if v in (None, ""):
        return None
    return v in ("1", "true", "True", "on", True)


@router.post("/api/associate")
async def media_associate(user=_Gate, db: Session = Depends(get_db),
                          deliverable_id: int = Form(...), items: str = Form(...),
                          reason: str = Form(None)):
    parsed = _parse_items(items)
    try:
        out = media_actions.associate(db, user, deliverable_id=deliverable_id,
                                      items=parsed, reason=reason or None)
        db.commit()
    except media_actions.MediaActionError as e:
        db.rollback()
        raise HTTPException(404, str(e))
    except Exception:
        db.rollback()
        raise
    return out


@router.post("/api/flags")
async def media_flags(user=_Gate, db: Session = Depends(get_db),
                      items: str = Form(...), internal_archive: str = Form(None),
                      delivered_external: str = Form(None)):
    parsed = _parse_items(items)
    out = media_actions.set_flags(db, user, parsed,
                                  internal_archive=_bool_or_none(internal_archive),
                                  delivered_external=_bool_or_none(delivered_external))
    db.commit()
    return out


@router.post("/api/unlink")
async def media_unlink(user=_Gate, db: Session = Depends(get_db),
                       deliverable_id: int = Form(...), items: str = Form(...)):
    parsed = _parse_items(items)
    try:
        out = media_actions.unlink(db, user, deliverable_id=deliverable_id, items=parsed)
        db.commit()
    except media_actions.MediaActionError as e:
        db.rollback()
        raise HTTPException(404, str(e))
    return out


@router.get("/api/export")
async def media_export(request: Request, user=_Gate, db: Session = Depends(get_db),
                       items: str = None):
    if items:
        parsed = _parse_items(items)
        csv_text = media_actions.export_manifest_csv(db, user, items=parsed)
    else:
        filters = {k: v for k, v in request.query_params.items() if k in _FILTER_KEYS and v}
        csv_text = media_actions.export_manifest_csv(db, user, filters=filters)
    return PlainTextResponse(csv_text, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=media_export.csv"})


@router.get("/api/deliverables")
async def media_deliverables(user=_Gate, db: Session = Depends(get_db),
                             project_id: int = None, job_id: int = None, q: str = None):
    from app.models.models import JobDeliverable, Job, Project
    from app.context import current_tenant_id
    query = db.query(JobDeliverable).filter(
        JobDeliverable.tenant_id == current_tenant_id(),
        JobDeliverable.deleted_at.is_(None))
    if job_id:
        query = query.filter(JobDeliverable.job_id == job_id)
    if q:
        query = query.filter(JobDeliverable.name.like(f"%{q}%"))
    out = []
    for jd in query.order_by(JobDeliverable.id.desc()).limit(200).all():
        job = db.get(Job, jd.job_id) if jd.job_id else None
        if project_id and (not job or job.project_id != project_id):
            continue
        proj = db.get(Project, job.project_id) if (job and job.project_id) else None
        out.append({"id": jd.id, "name": jd.name,
                    "job": {"id": job.id, "code": job.code} if job else None,
                    "project": {"id": proj.id, "code": proj.code} if proj else None,
                    "status": getattr(jd.status, "value", None) or str(jd.status)})
    return out
```
(Nota: il gate `_Gate` inietta `user` e applica `manage_assets` → viewer 403 automatico. Verificare che `Request`, `HTTPException`, `Depends`, `Session` siano già importati dalla Fase A — lo sono.)

- [ ] **Step 4: Eseguire — passano**

Run: `.venv/Scripts/python.exe -m pytest tests/test_media_api.py -v`
Expected: PASS (vecchi Fase A + nuovi).

- [ ] **Step 5: Commit**

```bash
git add app/routers/media.py tests/test_media_api.py
git commit -m "feat(media): endpoint associate/flags/unlink/export/deliverables"
```

---

### Task 6: Frontend azioni + i18n + smoke + chiusura

**Files:**
- Modify: `app/templates/pages/media_library.html`
- Modify: `app/static/js/media_library.js`
- Modify: `app/static/js/i18n.js`
- Modify: `app/main.py` (bump versione), `CHANGELOG.md`, `docs/STATO.md`

**Interfaces:**
- Consumes: endpoint Task 5.

- [ ] **Step 1: Markup modal Associa + azioni**

In `media_library.html`, sostituire i 3 bottoni bulk `disabled` con bottoni attivi + aggiungere Unlink, e aggiungere il modal Associa. Nella `#media-actionbar` (sostituire il blocco dei 3 button disabled):
```html
    <button class="btn btn-primary btn-sm" onclick="mfMediaOpenAssociate()" data-i18n="media.assocBtn">Associa a consegna</button>
    <button class="btn btn-secondary btn-sm" onclick="mfMediaArchive(true)" data-i18n="media.archiveBtn">Archivia</button>
    <button class="btn btn-secondary btn-sm" onclick="mfMediaArchive(false)" data-i18n="media.unarchiveBtn">Smarca archivio</button>
    <button class="btn btn-secondary btn-sm" onclick="mfMediaUnlinkPrompt()" data-i18n="media.unlinkBtn">Unlink</button>
```
E in fondo al `{% block content %}` (prima di `{% endblock %}`) aggiungere il modal:
```html
<div id="media-assoc-modal" class="modal-overlay" style="display:none;">
  <div class="modal" style="max-width:480px;">
    <div class="modal-header"><strong data-i18n="media.assocTitle">Associa a consegna</strong>
      <button class="btn btn-secondary btn-sm" onclick="mfMediaCloseAssociate()">✕</button></div>
    <div class="modal-body">
      <label class="text-sm" data-i18n="media.fltProject">Progetto</label>
      <select id="assoc-project" class="form-select" onchange="mfMediaAssocLoadDeliv()"><option value=""></option></select>
      <label class="text-sm" data-i18n="media.assocSearch">Cerca consegna</label>
      <input type="text" id="assoc-search" class="form-input" oninput="mfMediaAssocLoadDeliv()">
      <label class="text-sm" data-i18n="media.assocDeliverable">Consegna</label>
      <select id="assoc-deliverable" class="form-select"><option value=""></option></select>
      <label class="text-sm" data-i18n="media.reason">Motivo (opzionale)</label>
      <input type="text" id="assoc-reason" class="form-input" data-i18n="media.reasonPh" data-i18n-attr="placeholder">
      <p class="text-muted text-sm" data-i18n="media.supersedeWarn">Se la consegna ha già un asset attivo della stessa natura, verrà superseduto (storico mantenuto).</p>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary btn-sm" onclick="mfMediaCloseAssociate()" data-i18n="media.cancel">Annulla</button>
      <button class="btn btn-primary btn-sm" onclick="mfMediaConfirmAssociate()" data-i18n="media.confirm">Conferma</button>
    </div>
  </div>
</div>
```
(Verificare le classi modal reali del progetto: cercare `modal-overlay`/`openModal` in `global.js` e in un template esistente, es. `physical_assets.html`; adattare le classi a quelle in uso — questo è uno step di verifica: `grep -n "modal-overlay\|class=\"modal\"" app/templates/pages/physical_assets.html`.)

- [ ] **Step 2: JS azioni**

In `media_library.js` aggiungere le funzioni (usano `api()`, `escapeHtml()`, `mfT()`, `toast()`, e lo stato `_mediaSel`/`_mediaRowIndex` già esistenti):
```javascript
function _mediaSelItems() {
  return Array.from(_mediaSel).map(k => { const [nature, id] = k.split(':'); return { nature, id: parseInt(id) }; });
}

async function mfMediaOpenAssociate() {
  if (!_mediaSel.size) { toast(mfT('media.selectFirst'), 'error'); return; }
  // popola progetti dal filter_options già caricato in init (rileggi endpoint filters)
  try {
    const opt = await api('GET', '/media/api/filters');
    _mediaFillSelect('assoc-project', (opt.projects || []).map(p => ({ v: p.id, t: (p.code || '') + ' ' + (p.title || '') })));
  } catch (e) { console.error(e); }
  document.getElementById('assoc-deliverable').innerHTML = '<option value=""></option>';
  document.getElementById('media-assoc-modal').style.display = 'flex';
  mfMediaAssocLoadDeliv();
}

function mfMediaCloseAssociate() { document.getElementById('media-assoc-modal').style.display = 'none'; }

async function mfMediaAssocLoadDeliv() {
  const pid = document.getElementById('assoc-project').value;
  const q = document.getElementById('assoc-search').value.trim();
  const params = new URLSearchParams();
  if (pid) params.set('project_id', pid);
  if (q) params.set('q', q);
  let list = [];
  try { list = await api('GET', '/media/api/deliverables?' + params.toString()); } catch (e) { console.error(e); }
  const sel = document.getElementById('assoc-deliverable');
  sel.innerHTML = '<option value=""></option>' + list.map(d =>
    `<option value="${d.id}">${escapeHtml((d.project ? d.project.code + ' · ' : '') + d.name + ' [' + d.status + ']')}</option>`).join('');
}

async function mfMediaConfirmAssociate() {
  const did = document.getElementById('assoc-deliverable').value;
  if (!did) { toast(mfT('media.pickDeliverable'), 'error'); return; }
  const reason = document.getElementById('assoc-reason').value.trim();
  const fd = new FormData();
  fd.append('deliverable_id', did);
  fd.append('items', JSON.stringify(_mediaSelItems()));
  if (reason) fd.append('reason', reason);
  try {
    const out = await api('POST', '/media/api/associate', fd);
    toast(mfT('media.assocDone').replace('{n}', out.linked).replace('{s}', out.superseded), 'success');
    mfMediaCloseAssociate();
    _mediaSel.clear();
    mfMediaLoad(true);
  } catch (e) { toast(mfT('media.actionError'), 'error'); }
}

async function mfMediaArchive(on) {
  if (!_mediaSel.size) { toast(mfT('media.selectFirst'), 'error'); return; }
  const fd = new FormData();
  fd.append('items', JSON.stringify(_mediaSelItems()));
  fd.append('internal_archive', on ? '1' : '0');
  try {
    const out = await api('POST', '/media/api/flags', fd);
    toast(mfT('media.flagsDone').replace('{n}', out.updated), 'success');
    _mediaSel.clear(); mfMediaLoad(true);
  } catch (e) { toast(mfT('media.actionError'), 'error'); }
}

async function mfMediaUnlinkPrompt() {
  if (!_mediaSel.size) { toast(mfT('media.selectFirst'), 'error'); return; }
  // riusa il modal associa per scegliere la consegna da cui scollegare
  await mfMediaOpenAssociate();
  document.getElementById('media-assoc-modal').setAttribute('data-mode', 'unlink');
}

async function mfMediaExport() {
  const items = _mediaSel.size ? '?items=' + encodeURIComponent(JSON.stringify(_mediaSelItems()))
    : '?' + new URLSearchParams(mfMediaCollectFilters()).toString();
  window.location = '/media/api/export' + items;
}
```
Collegare Export: cambiare l'`onclick` del bottone Export (Step 1) in `onclick="mfMediaExport()"` con `data-i18n="media.exportBtn"`.
(Nota unlink: per semplicità Fase B, `mfMediaConfirmAssociate` legge `data-mode`; se `unlink`, chiama `/media/api/unlink` invece di `/associate`. Aggiungere il ramo in `mfMediaConfirmAssociate`:)
```javascript
  const mode = document.getElementById('media-assoc-modal').getAttribute('data-mode');
  const url = mode === 'unlink' ? '/media/api/unlink' : '/media/api/associate';
  // ...append reason solo se associate...
  const out = await api('POST', url, fd);
  document.getElementById('media-assoc-modal').removeAttribute('data-mode');
```

- [ ] **Step 3: Badge supersede nel dettaglio**

In `media_library.js`, in `mfMediaOpenDetail`, dove si rende `d.deliverables`, marcare i link superseded. Prima estendere `asset_detail` server-side per includere lo stato supersede del link — in `app/services/media_library.py`, `_deliverables_list` aggiungere `"superseded": ln.superseded_at is not None` al dict. Poi nel JS:
```javascript
    const dl = d.deliverables.map(x =>
      `<li style="${x.superseded ? 'text-decoration:line-through;opacity:.6;' : ''}">${escapeHtml(x.job || '')} — <em>${escapeHtml(x.status || '')}</em>${x.superseded ? ' <span class="badge">' + escapeHtml(mfT('media.superseded')) + '</span>' : ''}</li>`).join('');
```
(Aggiornare anche `tests/test_media_library.py::test_asset_detail_digital` per accettare la chiave `superseded` — o lasciare invariato se il test non la asserisce.)

- [ ] **Step 4: i18n 5 lingue**

In `app/static/js/i18n.js`, nel blocco `media.*` (dopo `media.fltDelivered`), aggiungere le chiavi in **5 lingue** (`it/en/fr/de/es`): `media.assocBtn`, `media.archiveBtn`, `media.unarchiveBtn`, `media.unlinkBtn`, `media.exportBtn`, `media.assocTitle`, `media.assocSearch`, `media.assocDeliverable`, `media.reason`, `media.reasonPh`, `media.supersedeWarn`, `media.cancel`, `media.confirm`, `media.selectFirst`, `media.pickDeliverable`, `media.assocDone` (`{n}`/`{s}`), `media.flagsDone` (`{n}`), `media.actionError`, `media.superseded`. Esempio riga:
```javascript
  'media.assocBtn':     {it: 'Associa a consegna', en: 'Link to delivery', fr: 'Lier à livraison', de: 'Mit Lieferung verknüpfen', es: 'Vincular a entrega'},
  'media.superseded':   {it: 'superseduto', en: 'superseded', fr: 'remplacé', de: 'ersetzt', es: 'reemplazado'},
```
(Completare TUTTE le chiavi elencate con traduzioni nelle 5 lingue.)

- [ ] **Step 5: Smoke Playwright**

- Copiare il DB: `cp mediaflow.db smoke_media.db`.
- Seed: 1 `Project`, 1 `Job`, 1 `JobDeliverable(status=delivered, nature=digital)` con `a_old` già linkato, + `a_new` asset confermato, tutti tenant 1 (script python one-off con `DATABASE_URL=sqlite:///./smoke_media.db`, `uploaded_by` = id admin).
- Boot: `DATABASE_URL="sqlite:///./smoke_media.db" .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8099 --log-level warning` (background, no reload).
- Playwright: login `admin@mediaflow.it/admin123` → `/media` → seleziona `a_new` → "Associa a consegna" → scegli progetto + consegna delivered → Conferma → verifica toast, poi apri dettaglio della consegna/asset e verifica badge "superseduto" sul vecchio link + (via API o ricarica) stato consegna `in_progress`. **0 errori console** su `/media`.
- Cleanup: `TaskStop` server + `rm -f smoke_media.db`.

- [ ] **Step 6: Bump + docs + commit**

- `app.version` → `3.5.0-alpha.172.245` in `main.py`.
- Voce `CHANGELOG.md` (prepend) + aggiornamento `docs/STATO.md` (versione corrente + sezione α.172.245 + prossimo step: merge o Fase C).
```bash
git add app/templates/pages/media_library.html app/static/js/media_library.js app/static/js/i18n.js app/services/media_library.py app/main.py CHANGELOG.md docs/STATO.md tests/test_media_library.py
git commit -m "feat(media): UI azioni Media Library + supersede badge + i18n (Fase B)"
```

---

## Self-Review

**Spec coverage:** modello supersede → Task 1; associate+supersede+auto-reset+notify → Task 2; set_flags+unlink → Task 3; export CSV → Task 4; endpoint (associate/flags/unlink/export/deliverables) → Task 5; UI modal cascata+ricerca, bulk attivi, badge supersede, i18n, smoke, bump → Task 6. Ogni sezione dello spec ha un task.

**Placeholder scan:** gli unici "step di verifica" espliciti sono: classi modal reali (Task 6 Step 1, con comando grep fornito) e chiavi i18n da completare in 5 lingue (Task 6 Step 4, elenco esatto + esempio). Nessun TODO di logica.

**Type consistency:** `associate/set_flags/unlink/export_manifest_csv` firme stabili fra Task 2-4 e usate identiche in Task 5; `MediaActionError` definita in Task 2, catturata in Task 5; `items` sempre `list[{nature,id}]`; `_resync_primary` (Task 1) consumato implicitamente da `link_asset`/`unlink_asset` in Task 2-3. `deliverable_reopened_supersede` registrato in `NotificationKind` (Task 1) e usato in `_notify_reopen` (Task 2).

**Rischi noti:** classi CSS modal da confermare (step di verifica); `set_flags` salta asset coda-interna per non-admin (scelta restrittiva documentata); export cap 5000 (documentato nello spec).
