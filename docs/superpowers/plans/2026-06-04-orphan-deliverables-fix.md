# Fix deliverable orfani — Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Target α.172.192.

**Goal:** eliminare i deliverable orfani: (1) migrate_job soft-delete invece di detach-NULL, (2) cleanup una tantum, (3) funzione ghost-link.

**Architecture:** helper condiviso `_deliverable_safe_to_remove`; patch ramo orphan in `migrate_job`; script cleanup parametrico; endpoint+capability link-ghost su phantom quote.

**Tech:** FastAPI/SQLAlchemy; pytest chiamata diretta funzioni + monkeypatch current_tenant_id; zero rete.

**Contesto verificato:**
- `migrate_job` ramo orphan: `app/routers/quotes.py:4043-4048` (oggi `d.quote_line_id = None` se `orphan_strategy=="keep_as_extra"`).
- Guardia "vergine" già in `_respawn_line_artifacts` (`quotes.py:362-394`): `quantity_delivered>0` / `confirmed_at` / `billing_status in (in_batch,billed,paid)` / `BookingDeliverable` count>0 → bloccano.
- `now_utc` importato in quotes.py; `BookingDeliverable`, `DeliverableBillingStatus` (`_DBS`) disponibili.
- Phantom helper pattern: `_get_or_create_phantom` inline in `batch_delete_quote_lines` (PhantomStatus.standby).

---

### Task 1: helper `_deliverable_safe_to_remove` + Fix migrate_job (RC1)

**Files:** Modify `app/routers/quotes.py`; Test `tests/test_migrate_job_orphans.py`.

- [ ] **Step 1: test che falliscono** (`tests/test_migrate_job_orphans.py`)

Seed: progetto, quote v1 con 2 righe consegna (unit "pc"), convert→job (deliverable per ogni riga). Crea v2 (new_version) che DROPPA una riga (ne resta 1). migrate-job su v2. Atteso: il deliverable della riga droppata è soft-deleted (`deleted_at` non-null), NON duplicato; la riga rimasta ha 1 deliverable rebound (quote_line_id = riga v2). Secondo test: la riga droppata ha un BookingDeliverable → NON cancellato (kept).

Scrivi i test chiamando `_deliverable_safe_to_remove(db, d)` direttamente (unit) + un test d'integrazione su `migrate_job` se fattibile (altrimenti testa l'helper + una funzione estratta). Per l'helper:
```python
import asyncio
from datetime import date, datetime
import pytest
from app.models import models as m
from app.routers import quotes as q


def _mk_deliverable(db, job, **kw):
    d = m.JobDeliverable(tenant_id=1, job_id=job.id, name=kw.get("name", "DCP"),
                         quote_line_id=kw.get("quote_line_id"),
                         quantity_planned=1.0, quantity_delivered=kw.get("qd", 0.0),
                         billing_status=kw.get("bs", m.DeliverableBillingStatus.not_billed),
                         confirmed_at=kw.get("confirmed_at"))
    db.add(d); db.flush()
    return d


def _seed_job(db):
    db.add(m.Tenant(id=1, name="T", slug="t", default_currency="EUR")); db.flush()
    c = m.Client(tenant_id=1, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="P1", title="P", client_id=c.id); db.add(p); db.flush()
    quote = m.Quote(tenant_id=1, number="Q-1", title="Q", issue_date=date.today(),
                    project_id=p.id, client_id=c.id, status=m.QuoteStatus.approved,
                    currency="EUR", fx_rate_to_base=1.0)
    db.add(quote); db.flush()
    job = m.Job(tenant_id=1, project_id=p.id, client_id=c.id, quote_id=quote.id,
                code="J1", title="J", status=m.JobStatus.active)
    db.add(job); db.flush()
    return p, quote, job


def test_safe_to_remove_clean(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    p, quote, job = _seed_job(db)
    d = _mk_deliverable(db, job)
    assert q._deliverable_safe_to_remove(db, d) is True


def test_safe_to_remove_blocked_delivered(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    p, quote, job = _seed_job(db)
    d = _mk_deliverable(db, job, qd=2.0)
    assert q._deliverable_safe_to_remove(db, d) is False


def test_safe_to_remove_blocked_booking(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    p, quote, job = _seed_job(db)
    d = _mk_deliverable(db, job)
    # crea un BookingDeliverable che lo lega (verifica i campi reali del modello!)
    bd = m.BookingDeliverable(job_deliverable_id=d.id)  # ALLINEA ai campi NOT-NULL reali
    db.add(bd); db.flush()
    assert q._deliverable_safe_to_remove(db, d) is False
```
IMPORTANTE: verifica i campi reali di `BookingDeliverable` e `JobDeliverable` in `app/models/models.py` prima di costruirli; aggiungi i NOT-NULL mancanti. Se `BookingDeliverable` richiede un `booking_id` reale, crea un Booking minimale.

- [ ] **Step 2: run → FAIL** (`_deliverable_safe_to_remove` assente).
`.\.venv\Scripts\python.exe -m pytest tests/test_migrate_job_orphans.py -v`

- [ ] **Step 3: implementa helper + patch**

In `quotes.py`, aggiungi (vicino a `_respawn_line_artifacts`):
```python
def _deliverable_safe_to_remove(db, d) -> bool:
    """True se il deliverable è 'vergine' e può essere soft-deleted senza
    perdere impegni a valle. Mirror della guardia di _respawn_line_artifacts."""
    if (d.quantity_delivered or 0.0) > 0.0:
        return False
    if d.confirmed_at:
        return False
    if d.billing_status in (DeliverableBillingStatus.in_batch,
                            DeliverableBillingStatus.billed,
                            DeliverableBillingStatus.paid):
        return False
    n_links = db.query(BookingDeliverable).filter(
        BookingDeliverable.job_deliverable_id == d.id
    ).count()
    return n_links == 0
```
(Verifica i nomi import: `DeliverableBillingStatus`, `BookingDeliverable` — già usati in `_respawn_line_artifacts`.)

Patch ramo orphan `quotes.py:4043-4048`:
```python
            elif d.quote_line_id:
                # v3.5.0-alpha.172.192 — riga V_old non più in V_new.
                # Soft-delete del deliverable se "vergine" (no NULL-detach: evita
                # orfani accumulati a ogni migrazione). Se ha impegni a valle
                # (booking/confermato/fatturato) NON si tocca → tracciato.
                if _deliverable_safe_to_remove(db, d):
                    d.deleted_at = now_utc()
                    deliverables_orphaned += 1
                else:
                    deliverables_kept_locked = locals().get("deliverables_kept_locked", 0) + 1
```
(Inizializza `deliverables_kept_locked = 0` insieme agli altri contatori a inizio funzione; aggiungilo al dict di risposta di migrate_job. NON usare `locals().get` nel codice finale — inizializza la variabile esplicitamente; lo pseudo sopra è solo indicativo.)

Rimuovi la dipendenza da `orphan_strategy=="keep_as_extra"` per il NULL-detach (non si fa più). Mantieni `orphan_strategy=="floating_job"` (job.quote_id=None) invariato.

- [ ] **Step 4: run → PASS** + regressione `.\.venv\Scripts\python.exe -m pytest -q -k "migrate or quote or deliverable"`.

- [ ] **Step 5: commit** `git commit -m "fix(quotes): migrate_job soft-delete deliverable di riga droppata (no orfani-NULL)"` + trailer Co-Authored-By.

---

### Task 2: script cleanup una tantum + test

**Files:** Create `scripts/cleanup_orphan_deliverables.py`; Test `tests/test_cleanup_orphans.py`.

- [ ] **Step 1: test** — seed job con 3 deliverable `quote_line_id=NULL` puliti + 1 NULL con BookingDeliverable. Funzione `cleanup_orphans(db, job_id=...)` → ritorna `{removed: 3, kept_locked: 1}`; i 3 hanno `deleted_at`, quello con booking no.
```python
def test_cleanup_removes_clean_null_orphans(db, monkeypatch):
    ...
    res = cleanup_orphans(db, job_id=job.id)
    assert res["removed"] == 3
    assert res["kept_locked"] == 1
```
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implementa** `scripts/cleanup_orphan_deliverables.py`:
  - funzione pura `cleanup_orphans(db, *, job_id=None, tenant_id=None, dry_run=False) -> dict` che seleziona `JobDeliverable` con `quote_line_id IS NULL, deleted_at IS NULL` (filtrati per job/tenant), applica `_deliverable_safe_to_remove` (import da `app.routers.quotes`), soft-delete dei sicuri (se non dry_run), ritorna `{candidates, removed, kept_locked, kept_ids}`.
  - blocco `if __name__ == "__main__":` con argparse (`--job-id`, `--tenant-id`, `--dry-run`, `--apply`) che stampa report; di default `--dry-run`.
- [ ] **Step 4: run → PASS**.
- [ ] **Step 5: commit** `feat(scripts): cleanup_orphan_deliverables (soft-delete orfani NULL guardati)`.

---

### Task 3: endpoint + capability "link-ghost" (RC3)

**Files:** Modify `app/routers/jobs.py` (endpoint) + `app/services/ai_assistant.py` (capability opzionale) + `app/services/ai_tools.py`; Test `tests/test_deliverable_link_ghost.py`.

- [ ] **Step 1: test** — deliverable con `quote_line_id=NULL` → `link_deliverable_to_ghost(db, deliverable_id)` crea/riusa phantom quote (is_phantom=True, standby) del progetto del job, aggiunge una QuoteLine, setta `deliverable.quote_line_id`. Idempotente: seconda chiamata riusa la stessa phantom. Ritorna `{ok, quote_id, quote_line_id}`.
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implementa**
  - Helper `_get_or_create_project_phantom(db, project_id, client_id)` (estrai/riusa il pattern da `batch_delete_quote_lines`; se già estraibile, condividi).
  - Service `link_deliverable_to_ghost(db, deliverable_id) -> dict`: carica deliverable (tenant scope via job→project), se ha già quote_line_id → ritorna invariato; altrimenti get/crea phantom, crea QuoteLine (description/unit/unit_price/quantity dal deliverable, section "A", position via `_next_position`), `deliverable.quote_line_id = nuova.id`, flush, ritorna ids.
  - Endpoint `POST /jobs/api/deliverables/{id}/link-ghost` (RBAC edit) che chiama il service + commit.
  - (Opzionale) capability AI `propose_link_deliverable_ghost` o readonly — SKIP se allunga troppo; l'endpoint basta. Decidi tu: minimale = solo endpoint.
- [ ] **Step 4: run → PASS** + full regression.
- [ ] **Step 5: commit** `feat(jobs): link-ghost deliverable a phantom quote (tracciabilità orfani manuali)`.

---

### Task 4: cleanup live GLO + bump + docs + export + push

- [ ] **Step 1: full pytest** verde.
- [ ] **Step 2: SNAPSHOT DB** in `db_snapshots/` (copia `mediaflow.db` → `snapshot-3.5.0-alpha.172.192-pre-orphan-cleanup.db`).
- [ ] **Step 3: cleanup live** — `.\.venv\Scripts\python.exe scripts/cleanup_orphan_deliverables.py --job-id 1 --dry-run` (report), poi `--apply`. Atteso ~20 removed (verifica kept_locked). Restart server :8000 e ricontrolla la lista planning deliverables GLO (deve calare di ~20).
- [ ] **Step 4: bump** main.py → 3.5.0-alpha.172.192; CHANGELOG + STATO.
- [ ] **Step 5: commit + export ZIP + push** (build_export_zip app_version 192, commit, git push).

---

## Self-Review
- Fix RC1 (soft-delete guardato) → Task 1 ✓
- Cleanup una tantum → Task 2 + esecuzione Task 4 ✓
- Ghost-link RC3 → Task 3 ✓
- Invariante: deliverable attivo → riga quote corrente o phantom; migrate non lascia residui ✓
- Snapshot pre-cleanup (reversibile) → Task 4 ✓

**Rischi/verifiche:** campi reali `BookingDeliverable`/`JobDeliverable` nei seed test; `migrate_job` è una funzione lunga — patch SOLO il ramo orphan + init contatore + response dict; non alterare rebind/new-lines. Il test d'integrazione su migrate_job può essere complesso (richiede new_version con parent_line_id): se troppo, coprire l'helper a fondo + un test mirato sul ramo orphan estraendo se serve, ma PREFERIRE un vero test migrate_job.
