# Multiselect righe quote — Elimina / Copia / Sposta — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Selezione multipla delle righe nell'editor quotazioni con azioni bulk Elimina / Copia / Sposta verso un'altra quotazione (esistente o nuova).

**Architecture:** Un endpoint atomico `lines-transfer` (copy|move, target existing|new) che riusa `_copy_quote_lines` per la clonazione e un nuovo helper condiviso `_remove_quote_lines` per la rimozione (estratto dal ramo non-approved di `batch_delete_quote_lines`, DRY). Endpoint `transfer-targets` per il picker. UI: checkbox per riga + barra bulk + modal trasferimento. Nessuna modifica DB.

**Tech Stack:** FastAPI (Form-based), SQLAlchemy 2.0, Jinja2 + vanilla JS inline, pytest (chiamata diretta alle funzioni async del router + monkeypatch `current_tenant_id`, no TestClient).

---

## File Structure

- **Modify** `app/routers/quotes.py`
  - Estrai `_remove_quote_lines(db, quote, ids) -> tuple[int, list]` (modulo-level).
  - Rewire ramo non-approved di `batch_delete_quote_lines` per usarlo.
  - Aggiungi `lines_transfer` endpoint `POST /api/{quote_id}/lines-transfer`.
  - Aggiungi `transfer_targets` endpoint `GET /api/transfer-targets`.
- **Modify** `app/templates/pages/quotes.html` (JS inline + markup riga)
  - Cella checkbox in `tr.ql-row` + select-all per sezione.
  - Stato selezione `_qlSelected` (Set) + barra bulk flottante.
  - Modal "Trasferisci righe" + funzioni `qlBulkDelete`, `qlOpenTransfer`, `qlSubmitTransfer`, `qlLoadTransferTargets`.
- **Create** `tests/test_quote_lines_transfer.py` (unit + endpoint-diretto).
- **Modify** `app/main.py` (version bump), `CHANGELOG.md`, `docs/STATO.md`.

Convenzioni note (già in `quotes.py`, non re-importare altrove):
`from app.services.reverse_quote import _next_position, _next_sort_order, _recalc_quote_totals`
`current_tenant_id`, `QuoteStatus`, `BookingStatus`, `Booking`, `JobCostLine`, `Quote`, `QuoteLine`, `_next_quote_number_progressive` sono già in scope nel modulo.

---

### Task 1: Helper condiviso `_remove_quote_lines` (refactor DRY)

**Files:**
- Modify: `app/routers/quotes.py` (vicino a `batch_delete_quote_lines`, ~riga 2484)
- Test: `tests/test_quote_lines_transfer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_quote_lines_transfer.py
"""v3.5.0-alpha.172.185 — multiselect righe quote: elimina/copia/sposta."""
import asyncio
from datetime import date
import pytest
from fastapi import HTTPException
from app.models import models as m
from app.routers import quotes as q


def _seed_quote(db, tenant=1, status=m.QuoteStatus.draft, number="Q-2026-001", n_lines=2):
    t = db.query(m.Tenant).filter(m.Tenant.id == tenant).first()
    if not t:
        t = m.Tenant(id=tenant, name="T", slug=f"t{tenant}", default_currency="EUR"); db.add(t)
    c = m.Client(tenant_id=tenant, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=tenant, code=f"P{number}", title="P", client_id=c.id); db.add(p); db.flush()
    quote = m.Quote(tenant_id=tenant, number=number, title="Q", issue_date=date.today(),
                    project_id=p.id, client_id=c.id, status=status,
                    currency="EUR", fx_rate_to_base=1.0)
    db.add(quote); db.flush()
    lines = []
    for i in range(n_lines):
        ln = m.QuoteLine(quote_id=quote.id, section="A", position=f"A.{i+1}",
                         description=f"L{i}", quantity=1.0, unit="pc", unit_price=100.0,
                         allowance=0.0, line_discount_pct=0.0, total=100.0, hardcosts=0.0,
                         sort_order=i)
        db.add(ln); lines.append(ln)
    db.flush()
    return quote, lines


def test_remove_quote_lines_deletes_clean(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    quote, lines = _seed_quote(db)
    ids = [lines[0].id]
    removed, details = q._remove_quote_lines(db, quote, ids)
    assert removed == 1
    remaining = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == quote.id).count()
    assert remaining == 1


def test_remove_quote_lines_blocks_on_active_booking(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    quote, lines = _seed_quote(db)
    # crea job + JCL + booking attivo collegati alla riga 0
    job = m.Job(tenant_id=1, project_id=quote.project_id, quote_id=quote.id,
                code="J1", title="J", status=m.JobStatus.active)
    db.add(job); db.flush()
    jcl = m.JobCostLine(tenant_id=1, job_id=job.id, quote_line_id=lines[0].id,
                        description="x", quantity=1.0, unit="pc", unit_cost=10.0, total_cost=10.0)
    db.add(jcl); db.flush()
    bk = m.Booking(tenant_id=1, job_cost_line_id=jcl.id, status=m.BookingStatus.confirmed,
                   start_date=date.today(), end_date=date.today())
    db.add(bk); db.flush()
    with pytest.raises(HTTPException) as ei:
        q._remove_quote_lines(db, quote, [lines[0].id])
    assert ei.value.status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_quote_lines_transfer.py -v`
Expected: FAIL — `AttributeError: module 'app.routers.quotes' has no attribute '_remove_quote_lines'`

(Nota: se i nomi dei campi `Job`/`JobCostLine`/`Booking` divergono, allinea il seed leggendo `app/models/models.py` PRIMA di implementare — non inventare colonne.)

- [ ] **Step 3: Implement `_remove_quote_lines`**

Inserisci a livello modulo, sopra `batch_delete_quote_lines`:

```python
def _remove_quote_lines(db, quote, ids):
    """Rimuove QuoteLine da una quote EDITABILE (non-approved).

    Per ogni line: hard-block 409 se ha booking attivi; altrimenti elimina le
    JobCostLine "pulite" collegate e poi la line. Ritorna (removed_count, details).
    NON gestisce la propagazione phantom (riservata al ramo approved del batch-delete).
    Il chiamante è responsabile di commit/rollback e del recalc totali.
    """
    removed = 0
    details = []
    for lid in ids:
        line = db.query(QuoteLine).filter(
            QuoteLine.id == lid, QuoteLine.quote_id == quote.id,
        ).first()
        if not line:
            details.append({"line_id": lid, "skipped": "not_found"})
            continue
        cost_lines = db.query(JobCostLine).filter(
            JobCostLine.quote_line_id == lid
        ).all()
        blocking = 0
        for jcl in cost_lines:
            blocking += db.query(Booking).filter(
                Booking.job_cost_line_id == jcl.id,
                Booking.status != BookingStatus.cancelled,
            ).count()
        if blocking > 0:
            db.rollback()
            raise HTTPException(
                409,
                f"Line #{lid} ha {blocking} booking attivi: annulla i booking prima "
                f"di eliminare/spostare."
            )
        for jcl in cost_lines:
            db.delete(jcl)
        db.delete(line)
        removed += 1
        details.append({"line_id": lid, "removed": True})
    return removed, details
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_quote_lines_transfer.py -v`
Expected: PASS (2 test)

- [ ] **Step 5: Commit**

```bash
git add app/routers/quotes.py tests/test_quote_lines_transfer.py
git commit -m "refactor(quotes): estrai _remove_quote_lines helper (DRY)"
```

---

### Task 2: Endpoint `lines-transfer` — copy verso quote esistente

**Files:**
- Modify: `app/routers/quotes.py` (dopo `batch_delete_quote_lines`)
- Test: `tests/test_quote_lines_transfer.py`

- [ ] **Step 1: Write the failing test**

```python
def _call(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_transfer_copy_to_existing(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-001")
    dst, _ = _seed_quote(db, number="Q-2026-002", n_lines=0)
    res = _call(q.lines_transfer(
        quote_id=src.id,
        line_ids=f"{lines[0].id},{lines[1].id}",
        mode="copy", target="existing", target_quote_id=dst.id, db=db,
    ))
    assert res["ok"] is True
    assert res["mode"] == "copy"
    assert res["copied"] == 2
    assert res["removed"] == 0
    assert res["target_quote_id"] == dst.id
    # origine intatta
    assert db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == src.id).count() == 2
    # destinazione popolata
    assert db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == dst.id).count() == 2


def test_transfer_copy_preserves_capitolato_link(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-010")
    lines[0].section_label = "Sky Italia"; lines[0].delivery_item_id = 107; db.flush()
    dst, _ = _seed_quote(db, number="Q-2026-011", n_lines=0)
    _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                           mode="copy", target="existing", target_quote_id=dst.id, db=db))
    nl = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == dst.id).first()
    assert nl.section_label == "Sky Italia"
    assert nl.delivery_item_id == 107


def test_transfer_target_same_as_source_400(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db)
    with pytest.raises(HTTPException) as ei:
        _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                               mode="copy", target="existing", target_quote_id=src.id, db=db))
    assert ei.value.status_code == 400


def test_transfer_target_not_editable_409(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-020")
    dst, _ = _seed_quote(db, number="Q-2026-021", status=m.QuoteStatus.approved, n_lines=0)
    with pytest.raises(HTTPException) as ei:
        _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                               mode="copy", target="existing", target_quote_id=dst.id, db=db))
    assert ei.value.status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_quote_lines_transfer.py -k transfer -v`
Expected: FAIL — `has no attribute 'lines_transfer'`

- [ ] **Step 3: Implement `lines_transfer` (copy + target existing only, per ora)**

```python
@router.post("/api/{quote_id}/lines-transfer", dependencies=[RequireEditQuotes])
async def lines_transfer(
    quote_id: int,
    line_ids: str = Form(..., description="CSV di line IDs"),
    mode: str = Form(..., description="copy | move"),
    target: str = Form(..., description="existing | new"),
    target_quote_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """Copia o sposta righe selezionate verso un'altra quote (esistente o nuova)."""
    from datetime import date as _date, timedelta as _td
    if mode not in ("copy", "move"):
        raise HTTPException(400, "mode deve essere copy|move")
    if target not in ("existing", "new"):
        raise HTTPException(400, "target deve essere existing|new")
    try:
        ids = [int(x.strip()) for x in line_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "line_ids deve essere CSV di interi")
    if not ids:
        raise HTTPException(400, "line_ids vuoto")

    tid = current_tenant_id()
    source = db.query(Quote).filter(Quote.id == quote_id, Quote.tenant_id == tid).first()
    if not source:
        raise HTTPException(404, "Quote di origine non trovata")

    selected = db.query(QuoteLine).filter(
        QuoteLine.id.in_(ids), QuoteLine.quote_id == source.id,
    ).all()
    if not selected:
        raise HTTPException(400, "Nessuna riga valida da trasferire")

    # Risolvi destinazione
    if target == "existing":
        if not target_quote_id:
            raise HTTPException(400, "target_quote_id richiesto per target=existing")
        if target_quote_id == quote_id:
            raise HTTPException(400, "Destinazione coincide con l'origine")
        dest = db.query(Quote).filter(
            Quote.id == target_quote_id, Quote.tenant_id == tid
        ).first()
        if not dest:
            raise HTTPException(404, "Quote di destinazione non trovata")
        if not (dest.status == QuoteStatus.draft and not dest.is_phantom):
            raise HTTPException(
                409,
                "Destinazione non editabile (solo bozze). Crea prima una nuova versione."
            )
    else:  # new
        dest = Quote(
            number=_next_quote_number_progressive(db),
            version=1,
            project_id=source.project_id,
            client_id=source.client_id,
            title=f"Copia da {source.number}",
            status=QuoteStatus.draft,
            issue_date=_date.today(),
            valid_until=_date.today() + _td(days=30),
            currency=source.currency,
            fx_rate_to_base=source.fx_rate_to_base,
            tenant_id=tid,
        )
        db.add(dest); db.flush()

    # Copia (track_parent=False: trasferimento cross-quote, non versioning)
    new_lines = _copy_quote_lines(selected, dest.id, track_parent=False)
    for nl in new_lines:
        nl.position = _next_position(dest)
        nl.sort_order = _next_sort_order(dest)
        db.add(nl); db.flush()  # flush per progressivi corretti riga-per-riga
    _recalc_quote_totals(dest)

    removed = 0
    db.commit()
    db.refresh(dest)
    return {
        "ok": True, "mode": mode, "copied": len(new_lines), "removed": removed,
        "target_quote_id": dest.id, "target_number": dest.number,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_quote_lines_transfer.py -k transfer -v`
Expected: PASS (copy/preserve/400/409 — il test move arriva al Task 3)

- [ ] **Step 5: Commit**

```bash
git add app/routers/quotes.py tests/test_quote_lines_transfer.py
git commit -m "feat(quotes): lines-transfer copy verso quote esistente/nuova"
```

---

### Task 3: `lines-transfer` — move + guard 422/booking + copy verso nuova

**Files:**
- Modify: `app/routers/quotes.py` (corpo `lines_transfer`)
- Test: `tests/test_quote_lines_transfer.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_transfer_copy_to_new(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-030")
    res = _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                                 mode="copy", target="new", target_quote_id=None, db=db))
    assert res["copied"] == 1
    new_q = db.query(m.Quote).filter(m.Quote.id == res["target_quote_id"]).first()
    assert new_q.project_id == src.project_id
    assert new_q.client_id == src.client_id
    assert new_q.status == m.QuoteStatus.draft


def test_transfer_move_from_editable(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-040")
    dst, _ = _seed_quote(db, number="Q-2026-041", n_lines=0)
    res = _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                                 mode="move", target="existing", target_quote_id=dst.id, db=db))
    assert res["mode"] == "move"
    assert res["copied"] == 1
    assert res["removed"] == 1
    # origine ha perso la riga
    assert db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == src.id).count() == 1
    assert db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == dst.id).count() == 1


def test_transfer_move_from_approved_422(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-050", status=m.QuoteStatus.approved)
    dst, _ = _seed_quote(db, number="Q-2026-051", n_lines=0)
    with pytest.raises(HTTPException) as ei:
        _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                               mode="move", target="existing", target_quote_id=dst.id, db=db))
    assert ei.value.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_quote_lines_transfer.py -k "move or to_new" -v`
Expected: `test_transfer_copy_to_new` passa già (copertura Task 2); i `move` falliscono (`removed` resta 0, nessun 422).

- [ ] **Step 3: Implement move branch**

Sostituisci il blocco `removed = 0 / db.commit()...` alla fine di `lines_transfer` con:

```python
    removed = 0
    if mode == "move":
        if not (source.status == QuoteStatus.draft and not source.is_phantom):
            db.rollback()
            raise HTTPException(
                422,
                "Spostamento non consentito da quote non editabile: usa Copia."
            )
        removed, _ = _remove_quote_lines(db, source, ids)  # 409 se booking attivi
        _recalc_quote_totals(source)

    db.commit()
    db.refresh(dest)
    return {
        "ok": True, "mode": mode, "copied": len(new_lines), "removed": removed,
        "target_quote_id": dest.id, "target_number": dest.number,
    }
```

Nota: la guard 422 va verificata PRIMA della rimozione ma DOPO la copia; su 422/409 il `db.rollback()` annulla anche la copia (atomicità). `_remove_quote_lines` fa già `db.rollback()` interno sul 409.

- [ ] **Step 4: Run all transfer tests**

Run: `python -m pytest tests/test_quote_lines_transfer.py -v`
Expected: PASS (tutti)

- [ ] **Step 5: Commit**

```bash
git add app/routers/quotes.py tests/test_quote_lines_transfer.py
git commit -m "feat(quotes): lines-transfer move (422 da approvata, 409 booking)"
```

---

### Task 4: Endpoint `transfer-targets` (picker)

**Files:**
- Modify: `app/routers/quotes.py`
- Test: `tests/test_quote_lines_transfer.py`

- [ ] **Step 1: Write the failing test**

```python
def test_transfer_targets_lists_editable_excludes_self(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, _ = _seed_quote(db, number="Q-2026-060", n_lines=0)
    d1, _ = _seed_quote(db, number="Q-2026-061", n_lines=0)
    appr, _ = _seed_quote(db, number="Q-2026-062", status=m.QuoteStatus.approved, n_lines=0)
    out = _call(q.transfer_targets(exclude=src.id, db=db))
    ids = {r["id"] for r in out}
    assert d1.id in ids          # bozza inclusa
    assert src.id not in ids     # self escluso
    assert appr.id not in ids    # approvata esclusa
    assert all(set(r) >= {"id", "number", "title", "project_name", "client_name"} for r in out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_quote_lines_transfer.py -k targets -v`
Expected: FAIL — `has no attribute 'transfer_targets'`

- [ ] **Step 3: Implement `transfer_targets`**

```python
@router.get("/api/transfer-targets", dependencies=[RequireEditQuotes])
async def transfer_targets(exclude: Optional[int] = None, db: Session = Depends(get_db)):
    """Quote editabili (bozze non-phantom) del tenant, per il picker di trasferimento."""
    tid = current_tenant_id()
    qry = db.query(Quote).filter(
        Quote.tenant_id == tid,
        Quote.status == QuoteStatus.draft,
        Quote.is_phantom == False,  # noqa: E712
    )
    if exclude:
        qry = qry.filter(Quote.id != exclude)
    rows = qry.order_by(Quote.number.desc()).all()
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "number": r.number,
            "title": r.title or "",
            "project_name": (r.project.title if r.project else ""),
            "client_name": (r.client.name if r.client else ""),
        })
    return out
```

(Verifica i nomi relazione `r.project.title` / `r.client.name` su `app/models/models.py`; se differiscono, allinea.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_quote_lines_transfer.py -v`
Expected: PASS (tutti)

- [ ] **Step 5: Commit**

```bash
git add app/routers/quotes.py tests/test_quote_lines_transfer.py
git commit -m "feat(quotes): transfer-targets endpoint (picker bozze)"
```

---

### Task 5: UI — checkbox selezione righe + stato

**Files:**
- Modify: `app/templates/pages/quotes.html`

Premessa: la riga è renderizzata a ~riga 2236 (`<tr class="ql-row..." data-line-id="${l.id}">`). Individua la funzione che renderizza le righe (cerca `ql-row` nel template) e l'header di sezione.

- [ ] **Step 1: Aggiungi cella checkbox nella riga**

Nel template della riga, come PRIMA cella `<td>`:

```html
<td class="ql-sel-cell"><input type="checkbox" class="ql-sel" data-line-id="${l.id}" onchange="qlToggleSel(${l.id}, this.checked)"></td>
```

Aggiungi una cella header corrispondente (vuota o con select-all) nell'intestazione di sezione:

```html
<th class="ql-sel-cell"><input type="checkbox" onchange="qlToggleSelSection('${secKey}', this.checked)" title="Seleziona sezione"></th>
```

(`secKey` = identificatore sezione già usato nel loop; se non esiste, usa la lettera sezione `A`/`B`/`C`.)

- [ ] **Step 2: Aggiungi stato + helper JS**

Vicino agli altri helper dell'editor quote:

```javascript
const _qlSelected = new Set();

function qlToggleSel(id, on) {
  if (on) _qlSelected.add(id); else _qlSelected.delete(id);
  const row = document.querySelector(`.ql-row[data-line-id="${id}"]`);
  if (row) row.classList.toggle('ql-row-selected', on);
  qlRenderBulkBar();
}

function qlToggleSelSection(secKey, on) {
  document.querySelectorAll(`.ql-sel`).forEach(cb => {
    const row = cb.closest('.ql-row');
    if (!row) return;
    // filtro per sezione: confronta col data-section se presente, altrimenti tutte
    const matchSec = !row.dataset.section || row.dataset.section === secKey;
    if (matchSec) { cb.checked = on; qlToggleSel(parseInt(cb.dataset.lineId, 10), on); }
  });
}

function qlClearSel() {
  _qlSelected.clear();
  document.querySelectorAll('.ql-sel').forEach(cb => cb.checked = false);
  document.querySelectorAll('.ql-row-selected').forEach(r => r.classList.remove('ql-row-selected'));
  qlRenderBulkBar();
}
```

Aggiungi CSS minimale (nel blocco `<style>` del template o in `main.css`):

```css
.ql-row-selected { outline: 2px solid var(--accent, #6272f5); outline-offset: -2px; }
.ql-sel-cell { width: 28px; text-align: center; }
```

- [ ] **Step 3: Smoke grep (no JS test harness)**

Run: `python -c "import re,sys; s=open(r'app/templates/pages/quotes.html',encoding='utf-8').read(); [sys.exit('MISSING '+n) for n in ['qlToggleSel','qlToggleSelSection','qlClearSel','_qlSelected','ql-sel'] if n not in s]; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Verifica template Jinja parsa**

Run: `python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('pages/quotes.html'); print('template ok')"`
Expected: `template ok` (se il template usa global Jinja custom e fallisce per quello, ignora SOLO errori di global non definiti; errori di sintassi `{% %}` vanno corretti.)

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/quotes.html
git commit -m "feat(quotes-ui): checkbox multiselect righe + stato selezione"
```

---

### Task 6: UI — barra bulk + Elimina

**Files:**
- Modify: `app/templates/pages/quotes.html`

- [ ] **Step 1: Aggiungi container barra bulk**

Nel markup dell'editor (vicino alla tabella righe), un contenitore fisso:

```html
<div id="qlBulkBar" class="ql-bulk-bar" style="display:none;"></div>
```

CSS:

```css
.ql-bulk-bar { position: sticky; bottom: 12px; z-index: 30; margin: 12px auto; display: flex; gap: 8px; align-items: center;
  background: var(--panel, #1c1f2e); border: 1px solid var(--accent, #6272f5); border-radius: 10px; padding: 8px 14px; width: fit-content; box-shadow: 0 6px 24px rgba(0,0,0,.35); }
.ql-bulk-bar button { padding: 6px 12px; }
.ql-bulk-bar [disabled] { opacity: .45; cursor: not-allowed; }
```

- [ ] **Step 2: Render barra + Elimina wiring**

```javascript
// _quoteEditable: booleano già usato altrove per stato editabile della quote corrente.
// Se non esiste con questo nome, riusa la logica di _ensureEditableQuoteOrVersion / lo stato corrente.
function qlRenderBulkBar() {
  const bar = document.getElementById('qlBulkBar');
  if (!bar) return;
  const n = _qlSelected.size;
  if (n === 0) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  const moveDisabled = !_quoteEditable ? 'disabled title="Solo da bozze"' : '';
  bar.style.display = 'flex';
  bar.innerHTML = `
    <span><b>${n}</b> selezionate</span>
    <button onclick="qlBulkDelete()">Elimina</button>
    <button onclick="qlOpenTransfer('copy')">Copia in…</button>
    <button onclick="qlOpenTransfer('move')" ${moveDisabled}>Sposta in…</button>
    <button onclick="qlClearSel()">×</button>`;
}

async function qlBulkDelete() {
  const ids = [..._qlSelected];
  if (!ids.length) return;
  if (!confirm(`Eliminare ${ids.length} righe selezionate?`)) return;
  const fd = new FormData();
  fd.append('line_ids', ids.join(','));
  try {
    const r = await api(`/quotes/api/${_currentQuoteId}/lines-batch-delete`, { method: 'POST', body: fd });
    let msg = `Eliminate ${r.deleted} righe`;
    if (r.propagated_to_phantom) msg += ` · propagato su Consuntivo`;
    toast(msg);
    qlClearSel();
    reloadQuote();
  } catch (e) { toast(e.message || 'Errore eliminazione', 'error'); }
}
```

(`_currentQuoteId`, `api`, `toast`, `reloadQuote` sono helper esistenti — verifica i nomi reali nel template/`global.js` e allinea. `reloadQuote` è il nome confermato in α.172.180.)

- [ ] **Step 3: Smoke grep**

Run: `python -c "import sys; s=open(r'app/templates/pages/quotes.html',encoding='utf-8').read(); [sys.exit('MISSING '+n) for n in ['qlRenderBulkBar','qlBulkDelete','qlBulkBar','lines-batch-delete'] if n not in s]; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Verifica nomi helper esistenti**

Run: `python -c "s=open(r'app/templates/pages/quotes.html',encoding='utf-8').read(); print('reloadQuote' in s, 'function reloadQuote' in s or 'reloadQuote =' in s); print('api(' in s, 'toast(' in s)"`
Expected: i nomi usati esistono già; se `_currentQuoteId`/`_quoteEditable` non esistono, sostituisci con le variabili reali di stato editor (cerca come viene tracciato l'id quote aperta).

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/quotes.html
git commit -m "feat(quotes-ui): barra bulk + elimina multiselect"
```

---

### Task 7: UI — modal trasferimento (copia/sposta) + picker

**Files:**
- Modify: `app/templates/pages/quotes.html`

- [ ] **Step 1: Markup modal**

Aggiungi (riusa il pattern modal esistente del template — `openModal`/`closeModal`):

```html
<div id="qlTransferModal" class="modal" style="display:none;">
  <div class="modal-content">
    <h3 id="qlTransferTitle">Trasferisci righe</h3>
    <label><input type="radio" name="ql-tgt" value="existing" checked onchange="qlTransferTargetMode()"> Quote esistente</label>
    <label><input type="radio" name="ql-tgt" value="new" onchange="qlTransferTargetMode()"> Nuova quote</label>
    <div id="qlTransferExisting">
      <input type="text" id="qlTransferPicker" placeholder="Cerca quote (numero, titolo, cliente)…" autocomplete="off">
      <input type="hidden" id="qlTransferTargetId">
      <div id="qlTransferResults" class="ql-picker-results"></div>
    </div>
    <div id="qlTransferNew" style="display:none;">
      <p class="muted">Crea una nuova bozza (eredita progetto e cliente di origine).</p>
    </div>
    <div class="modal-actions">
      <button onclick="closeModal('qlTransferModal')">Annulla</button>
      <button id="qlTransferSubmit" onclick="qlSubmitTransfer()">Conferma</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: JS modal + submit**

```javascript
let _qlTransferMode = 'copy';

function qlOpenTransfer(mode) {
  if (!_qlSelected.size) return;
  _qlTransferMode = mode;
  document.getElementById('qlTransferTitle').textContent =
    (mode === 'copy' ? 'Copia ' : 'Sposta ') + _qlSelected.size + ' righe';
  document.querySelector('input[name="ql-tgt"][value="existing"]').checked = true;
  document.getElementById('qlTransferTargetId').value = '';
  document.getElementById('qlTransferPicker').value = '';
  document.getElementById('qlTransferResults').innerHTML = '';
  qlTransferTargetMode();
  qlLoadTransferTargets();
  openModal('qlTransferModal');
}

function qlTransferTargetMode() {
  const v = document.querySelector('input[name="ql-tgt"]:checked').value;
  document.getElementById('qlTransferExisting').style.display = v === 'existing' ? '' : 'none';
  document.getElementById('qlTransferNew').style.display = v === 'new' ? '' : 'none';
}

let _qlTargets = [];
async function qlLoadTransferTargets() {
  try {
    _qlTargets = await api(`/quotes/api/transfer-targets?exclude=${_currentQuoteId}`);
    qlRenderTargets(_qlTargets);
  } catch (e) { toast(e.message || 'Errore caricamento quote', 'error'); }
}

function qlRenderTargets(list) {
  const box = document.getElementById('qlTransferResults');
  box.innerHTML = list.map(t =>
    `<div class="ql-picker-row" onclick="qlPickTarget(${t.id}, '${(t.number || '').replace(/'/g, "\\'")}')">
       <b>${escapeHtml(t.number)}</b> — ${escapeHtml(t.title)} · ${escapeHtml(t.client_name)}
     </div>`).join('') || '<div class="muted">Nessuna bozza disponibile.</div>';
}

function qlPickTarget(id, number) {
  document.getElementById('qlTransferTargetId').value = id;
  document.getElementById('qlTransferPicker').value = number;
  document.getElementById('qlTransferResults').innerHTML = '';
}

// filtro client-side sul picker
document.addEventListener('input', (e) => {
  if (e.target && e.target.id === 'qlTransferPicker') {
    const term = e.target.value.toLowerCase();
    qlRenderTargets(_qlTargets.filter(t =>
      `${t.number} ${t.title} ${t.client_name}`.toLowerCase().includes(term)));
  }
});

async function qlSubmitTransfer() {
  const target = document.querySelector('input[name="ql-tgt"]:checked').value;
  const tgtId = document.getElementById('qlTransferTargetId').value;
  if (target === 'existing' && !tgtId) { toast('Seleziona una quote di destinazione', 'error'); return; }
  const btn = document.getElementById('qlTransferSubmit');
  btn.disabled = true;
  const fd = new FormData();
  fd.append('line_ids', [..._qlSelected].join(','));
  fd.append('mode', _qlTransferMode);
  fd.append('target', target);
  if (target === 'existing') fd.append('target_quote_id', tgtId);
  try {
    const r = await api(`/quotes/api/${_currentQuoteId}/lines-transfer`, { method: 'POST', body: fd });
    toast(`${r.mode === 'move' ? 'Spostate' : 'Copiate'} ${r.copied} righe → ${r.target_number}`);
    closeModal('qlTransferModal');
    qlClearSel();
    reloadQuote();  // move rimuove le righe dall'origine; copy le lascia
  } catch (e) {
    toast(e.message || 'Errore trasferimento', 'error');
  } finally { btn.disabled = false; }
}
```

(`escapeHtml`, `openModal`, `closeModal`, `api`, `toast` = helper globali esistenti in `global.js` — NON ridefinirli nel template, cfr. lezione v3.4.23.)

- [ ] **Step 3: Smoke grep**

Run: `python -c "import sys; s=open(r'app/templates/pages/quotes.html',encoding='utf-8').read(); [sys.exit('MISSING '+n) for n in ['qlOpenTransfer','qlSubmitTransfer','qlLoadTransferTargets','qlTransferModal','lines-transfer','transfer-targets'] if n not in s]; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Verifica template parsa**

Run: `python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('pages/quotes.html'); print('template ok')"`
Expected: `template ok`

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/quotes.html
git commit -m "feat(quotes-ui): modal trasferimento righe copia/sposta + picker"
```

---

### Task 8: Smoke browser + version bump + docs

**Files:**
- Modify: `app/main.py`, `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: Smoke browser end-to-end**

Backend già su :8000 (tunnel attivo). Apri una quote draft con ≥2 righe e verifica:
1. Checkbox compaiono; selezione mostra barra bulk con conteggio.
2. **Copia in…** → modal → scegli un'altra bozza → conferma → toast "Copiate N → Q-…"; le righe restano in origine; compaiono nella destinazione.
3. **Sposta in…** da bozza → righe rimosse dall'origine, presenti in destinazione.
4. Su quote **approvata**: **Sposta** disabilitato; **Copia** funziona.
5. **Elimina** → conferma → righe rimosse.
6. **Nuova quote**: copia → crea bozza nuova e ci mette le righe.

Usa Playwright MCP (`browser_navigate` su `http://localhost:8000`, login, naviga a `/quotes`) o test manuale. Annota esito.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest -q`
Expected: tutti verdi (375 precedenti + ~8 nuovi).

- [ ] **Step 3: Version bump**

In `app/main.py` trova la costante versione (`3.5.0-alpha.172.184`) → `3.5.0-alpha.172.185`.

- [ ] **Step 4: CHANGELOG + STATO**

`CHANGELOG.md`: nuova voce α.172.185 con sintesi feature.
`docs/STATO.md`: nuova sezione α.172.185 in cima (cosa fatto + "Prossimo: test browser Matteo" + backlog ereditato).

- [ ] **Step 5: Commit**

```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -m "chore: v3.5.0-alpha.172.185 multiselect righe quote elimina/copia/sposta"
```

---

## Self-Review

**Spec coverage:**
- Endpoint `lines-transfer` (copy/move, existing/new) → Task 2+3 ✓
- Refactor `_remove_quote_lines` DRY → Task 1 ✓
- `transfer-targets` picker → Task 4 ✓
- Move 422 da approvata / 409 booking → Task 3 ✓ / Task 1 ✓
- Tenant scope → Task 2 (filtri `tenant_id`) + test targets ✓
- UI checkbox + select-all → Task 5 ✓
- Barra bulk + Elimina (riusa batch-delete) → Task 6 ✓
- Modal trasferimento + picker → Task 7 ✓
- Copy preserva section_label/delivery_item_id → Task 2 test ✓
- Nessuna migrazione → confermato (zero schema change) ✓
- Smoke browser + bump + docs → Task 8 ✓

**Placeholder scan:** nessun TBD/TODO; tutti gli step hanno codice o comando concreto. Le note "verifica nome reale" sono richieste di allineamento a simboli esistenti (non placeholder di logica).

**Type consistency:** `lines_transfer` ritorna sempre `{ok, mode, copied, removed, target_quote_id, target_number}` in tutti i rami; `_remove_quote_lines` ritorna `(int, list)` usato sia da Task 1 sia da Task 3; nomi JS (`_qlSelected`, `qlRenderBulkBar`, `qlClearSel`, `qlOpenTransfer`, `qlSubmitTransfer`, `_currentQuoteId`) coerenti tra Task 5/6/7.

**Rischi noti da verificare in esecuzione (non bloccanti):**
- Nomi reali helper editor JS (`_currentQuoteId`, `_quoteEditable`, `reloadQuote`) — confermare nel template prima di Task 6/7.
- Nomi colonne `Job`/`JobCostLine`/`Booking` nel seed test — confermare in `models.py` prima di Task 1.
- Relazioni `quote.project.title` / `quote.client.name` — confermare in Task 4.
