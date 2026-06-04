# Copilot: leggi + rinomina deliverable HUB — Plan

> REQUIRED SUB-SKILL: subagent-driven-development. Target α.172.193.

**Goal:** dare al copilot 2 capability per operare sui deliverable del Planning HUB: (1) leggerli, (2) rinominarli in batch (mapping esplicito) gated da Apply. Così il copilot può eseguire richieste tipo "aggiungi suffisso episodio ai deliverable GLO" per qualsiasi progetto.

**Design (approvato):**
- READ tool `read_job_deliverables` (readonly, auto-eseguito nel loop) → lista deliverable di un job/progetto.
- MUTATION `propose_rename_deliverables` (gated Apply) → `{renames:[{deliverable_id, new_name}]}`, rinomina in batch.
- Il copilot legge → calcola i nuovi nomi secondo le regole NL dell'utente → propone → utente Applica. Logica episodi (batch6→ep, CD coppie, NC dispari) la fa il modello.

**Pattern di riferimento (verificato):**
- Registry `@ai_capability("name")` in `app/services/ai_capability_registry.py` (readonly inferito da prefisso `read_`/`list_`/...; `propose_`/`update_`=mutation). Handler firma `def _h(db, data: dict) -> dict`.
- Readonly: eseguito inline da `ai_loop._exec_readonly` → `_ACTION_HANDLERS[name](db, input)`.
- Mutation: salvata come AIAction `proposed`; su Apply `apply_action(db, action)` chiama l'handler. Verifica in `ai_assistant.apply_action` come dispatcha (handler riceve il payload).
- Schema tool in `app/services/ai_tools.py:TOOLS` (`{name, category, description, input_schema, handler}`). readonly per read, mutation per propose.
- Esempio readonly: `_h_read_quote_lines` (α.172.190). Esempio mutation: `_h_propose_quote_line`.
- `current_tenant_id` da `app.context`. `JobDeliverable`, `Job` in models.

---

### Task 1: handler `read_job_deliverables` (readonly) + TOOLS + test

**Files:** Modify `app/services/ai_assistant.py`, `app/services/ai_tools.py`; Test `tests/test_ai_deliverable_tools.py`.

- [ ] **Step 1: test**
```python
from datetime import date
from app.models import models as m
from app.services.ai_assistant import _h_read_job_deliverables


def _seed(db):
    if not db.query(m.Tenant).filter(m.Tenant.id == 1).first():
        db.add(m.Tenant(id=1, name="T", slug="t", default_currency="EUR")); db.flush()
    c = m.Client(tenant_id=1, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="GLO", title="Gomorra", client_id=c.id); db.add(p); db.flush()
    quote = m.Quote(tenant_id=1, number="Q-2026-008-v5", title="Q", issue_date=date.today(),
                    project_id=p.id, client_id=c.id, status=m.QuoteStatus.approved,
                    currency="EUR", fx_rate_to_base=1.0); db.add(quote); db.flush()
    job = m.Job(tenant_id=1, project_id=p.id, client_id=c.id, quote_id=quote.id,
                code="GLO-J007", title="J", status=m.JobStatus.active); db.add(job); db.flush()
    ql = m.QuoteLine(quote_id=quote.id, section="A", position="A.1", description="DCP",
                     quantity=1.0, unit="pc", unit_price=100.0, allowance=0.0,
                     line_discount_pct=0.0, total=100.0, hardcosts=0.0, sort_order=0,
                     section_label="Sky Italia"); db.add(ql); db.flush()
    for i in range(2):
        db.add(m.JobDeliverable(tenant_id=1, job_id=job.id, name=f"DCP - CS", quote_line_id=ql.id,
                                unit="pc", quantity_planned=1.0)); 
    db.flush()
    return p, job


def test_read_job_deliverables_by_job_id(db, monkeypatch):
    import app.services.ai_assistant as a
    monkeypatch.setattr(a, "current_tenant_id", lambda: 1) if hasattr(a, "current_tenant_id") else None
    p, job = _seed(db)
    res = _h_read_job_deliverables(db, {"job_id": job.id})
    assert res["count"] == 2
    assert res["items"][0]["name"] == "DCP - CS"
    assert "section_label" in res["items"][0]
    assert res["items"][0]["unit"] == "pc"


def test_read_job_deliverables_by_project_code(db, monkeypatch):
    p, job = _seed(db)
    res = _h_read_job_deliverables(db, {"project_code": "GLO"})
    assert res["count"] == 2
```
(Verifica come `_h_read_quote_lines` ottiene il tenant: usa `current_tenant_id` o costante locale `CURRENT_TENANT=1`? Allinea il monkeypatch/seed di conseguenza — guarda `_h_read_quote_lines`.)

- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** in ai_assistant.py (vicino a `_h_read_quote_lines`):
```python
@ai_capability("read_job_deliverables")
def _h_read_job_deliverables(db: Session, data: dict) -> dict:
    """READONLY. Lista dei deliverable (consegne) del Planning HUB per un job o
    progetto, con id/nome/unit/quantità/sezione/quote. Usa per ENUMERARE i
    deliverable prima di proporne il rinomino (propose_rename_deliverables).
    Payload: {"job_id": int} OPPURE {"project_code": str} OPPURE {"quote_number": str}.
    """
    CURRENT_TENANT = 1
    job = None
    if data.get("job_id"):
        job = db.query(Job).filter(Job.id == int(data["job_id"]), Job.tenant_id == CURRENT_TENANT).first()
    elif data.get("project_code"):
        proj = db.query(Project).filter(Project.code == data["project_code"].strip()).first()
        if proj:
            job = db.query(Job).filter(Job.project_id == proj.id).first()
    elif data.get("quote_number"):
        qz = db.query(Quote).filter(Quote.number == data["quote_number"].strip()).first()
        if qz:
            job = db.query(Job).filter(Job.quote_id == qz.id).first()
    if not job:
        raise ValueError("Job non trovato (passa job_id, project_code o quote_number)")
    from app.models import JobDeliverable as _JD, QuoteLine as _QL
    rows = db.query(_JD).filter(_JD.job_id == job.id, _JD.deleted_at.is_(None)).order_by(_JD.id).all()
    qlsec = {}
    qlids = {d.quote_line_id for d in rows if d.quote_line_id}
    if qlids:
        for ql in db.query(_QL).filter(_QL.id.in_(qlids)).all():
            qlsec[ql.id] = ql.section_label
    items = [{
        "id": d.id, "name": d.name, "unit": d.unit,
        "quantity": d.quantity_planned, "section_label": qlsec.get(d.quote_line_id),
        "status": d.status.value if hasattr(d.status, "value") else str(d.status),
    } for d in rows]
    return {"job_id": job.id, "job_code": job.code, "count": len(items), "items": items}
```
TOOLS entry (readonly), descrizione esplicita.
- [ ] **Step 4: run → PASS** + verifica registry: `import app.services.ai_assistant; 'read_job_deliverables' in get_handlers()` True, categoria readonly.
- [ ] **Step 5: commit** `feat(ai): read_job_deliverables (lista deliverable HUB per copilot)`.

---

### Task 2: handler `propose_rename_deliverables` (mutation) + TOOLS + test

**Files:** Modify `app/services/ai_assistant.py`, `app/services/ai_tools.py`; Test `tests/test_ai_deliverable_tools.py` (append).

- [ ] **Step 1: test**
```python
from app.services.ai_assistant import _h_propose_rename_deliverables


def test_rename_deliverables_applies(db, monkeypatch):
    p, job = _seed(db)
    rows = db.query(m.JobDeliverable).filter(m.JobDeliverable.job_id == job.id).order_by(m.JobDeliverable.id).all()
    renames = [{"deliverable_id": rows[0].id, "new_name": "DCP - CS - ep. 101"},
               {"deliverable_id": rows[1].id, "new_name": "DCP - CS - ep. 102"}]
    res = _h_propose_rename_deliverables(db, {"renames": renames})
    assert res["renamed"] == 2
    db.refresh(rows[0]); db.refresh(rows[1])
    assert rows[0].name == "DCP - CS - ep. 101"
    assert rows[1].name == "DCP - CS - ep. 102"


def test_rename_deliverables_skips_foreign_tenant(db, monkeypatch):
    p, job = _seed(db)
    res = _h_propose_rename_deliverables(db, {"renames": [{"deliverable_id": 999999, "new_name": "X"}]})
    assert res["renamed"] == 0
    assert res.get("skipped", 0) == 1


def test_rename_deliverables_empty_400(db):
    import pytest
    with pytest.raises(ValueError):
        _h_propose_rename_deliverables(db, {"renames": []})
```
- [ ] **Step 2: run → FAIL**.
- [ ] **Step 3: implement** in ai_assistant.py:
```python
@ai_capability("propose_rename_deliverables")
def _h_propose_rename_deliverables(db: Session, data: dict) -> dict:
    """MUTATION (gated Apply). Rinomina in batch i deliverable del Planning HUB.
    Payload: {"renames": [{"deliverable_id": int, "new_name": str}, ...]}.
    Scope tenant. Salta gli id non trovati/altro tenant (li conta in 'skipped').
    """
    CURRENT_TENANT = 1
    renames = data.get("renames") or []
    if not renames:
        raise ValueError("renames vuoto")
    from app.models import JobDeliverable as _JD
    renamed = 0
    skipped = 0
    details = []
    for r in renames:
        did = r.get("deliverable_id")
        new_name = (r.get("new_name") or "").strip()
        if not did or not new_name:
            skipped += 1; continue
        d = db.query(_JD).filter(_JD.id == int(did), _JD.tenant_id == CURRENT_TENANT,
                                 _JD.deleted_at.is_(None)).first()
        if not d:
            skipped += 1; continue
        old = d.name
        d.name = new_name[:255]
        renamed += 1
        details.append({"id": did, "old": old, "new": d.name})
    db.flush()
    return {"renamed": renamed, "skipped": skipped, "details": details[:100]}
```
TOOLS entry (mutation), descrizione esplicita + esempio (es. "per sequenze episodi: leggi prima con read_job_deliverables, poi proponi i new_name").
Aggiungi `propose_rename_deliverables` a `VALID_ACTION_TYPES` se non derivato dal registry (verifica: dovrebbe esserlo via registry). Verifica che il drawer copilot mostri la card Apply per questa mutation (usa il flusso generico AIAction → nessun codice UI nuovo).
- [ ] **Step 4: run → PASS** + full regression `.\.venv\Scripts\python.exe -m pytest -q`.
- [ ] **Step 5: commit** `feat(ai): propose_rename_deliverables (rinomino batch deliverable HUB, gated Apply)`.

---

### Task 3: smoke live + bump + docs + export + push

- [ ] **Step 1: full pytest** verde.
- [ ] **Step 2: restart server :8000**.
- [ ] **Step 3: smoke live DeepSeek** — copilot su /planning: "leggi i deliverable di GLO e proponi il rinomino con suffisso episodio: i batch da 6 → ' - ep. 101'..'106', i CD → coppie '101+102/103+104/105+106', gli NC → dispari '101/103/105'". Verifica: il copilot chiama `read_job_deliverables`, poi propone `propose_rename_deliverables` (AIAction). NON applicare in automatico — confermare che la proposta appare. (Se vuoi, applica 1 caso per validare il rename end-to-end, poi è dato reale di Matteo → lascia decidere a lui.) Annota esito.
- [ ] **Step 4: bump** main.py → 3.5.0-alpha.172.193; CHANGELOG + STATO (capability read_job_deliverables + propose_rename_deliverables; ora il copilot può leggere e rinominare i deliverable HUB).
- [ ] **Step 5: commit + export ZIP + push.**

---

## Self-Review
- Read tool deliverable → Task 1 ✓ (colma gap "copilot non vede lista planning")
- Mutation rename batch → Task 2 ✓ (gated Apply, scope tenant)
- Smoke live + bump → Task 3 ✓
- Generico: il copilot calcola i nomi (qualsiasi logica), il tool applica → riusabile per ogni progetto/job ✓
- Caso GLO: risolto dal copilot stesso via le 2 capability ✓

**Rischi:** verifica come `_h_read_quote_lines` ottiene il tenant (CURRENT_TENANT=1 vs current_tenant_id) e allinea; verifica che `apply_action` dispatchi correttamente l'handler mutation col payload `renames`; conferma che il drawer mostra la card Apply per la nuova mutation senza codice UI nuovo (flusso AIAction generico). Rinominare non tocca billing/quote → nessuna guardia di immutabilità necessaria.
