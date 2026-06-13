# Batch SAL + fix deliverables — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sistemare 3 bug nell'editor deliverables del planning e aggiungere 7 feature alla pagina `/finance/sal` (toggle ore/budget, colonne anno N±1, riga rossa su sforamento, filtri reparto/categoria/progetto, matrix passato/futuro con colori, legenda) rispettando 2 policy trasversali (i18n in 5 lingue, ordine menu deterministico).

**Architecture:** Estensioni read-only. Le metriche SAL vivono in `app/services/sal_metrics.py` (pure functions, già esistenti); le estendo con metriche euro + helper per-anno + logica passato/futuro. Gli endpoint `app/routers/finance.py` espongono i nuovi campi/filtri. La UI è in `app/templates/pages/sal.html` (vanilla JS, helper globali `api()`/`escapeHtml()`). I bug deliverables toccano la funzione pura `app/services/delivery_item_validation.py`, l'endpoint `app/routers/delivery_items.py` e il JS dell'editor in `app/templates/pages/planning.html`. Tutte le stringhe nuove via `app/static/js/i18n.js` (`data-i18n`).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Jinja2, vanilla JS, pytest (DB sqlite in-memory), Playwright (smoke E2E).

---

## Policy trasversali (applicano a OGNI task con UI)

- **P1 — i18n:** ogni stringa UI nuova → chiave in `app/static/js/i18n.js` (`window.MF_I18N`) con `{it, en, fr, de, es}` + `data-i18n="key"` nel template (o `mfT('key')` in JS dinamico). Stesso commit. Prefisso namespace `sal.*` / `deliv.*`.
- **P2 — ordine menu:** ogni select/colonna ordinabile → ordine esplicito. Anagrafiche (clienti/progetti) = alfabetico; reparti/categorie = `sort_order`.

---

## File map

| File | Responsabilità | Modifica |
|---|---|---|
| `app/services/delivery_item_validation.py` | regole codec/container (pure) | + `preferred_container_for_codec` |
| `app/routers/delivery_items.py` | endpoint spec-schema | + campo `preferred_container_id` |
| `app/templates/pages/planning.html` | editor tech-spec (JS `dsm*`) | auto-set container ProRes; fix select audio preset |
| `scripts/migrate_prores_container.py` | backfill container ProRes (nuovo) | crea |
| `app/services/sal_metrics.py` | metriche SAL (pure) | + euro, year-helpers, blended, matrix past/future |
| `app/routers/finance.py` | endpoint `/api/sal/*` | + filtri + campi euro/anno; matrix invariato (logica nel service) |
| `app/templates/pages/sal.html` | UI SAL | toggle ore/budget, colonne anno, riga rossa, filtri, legenda, colori matrix |
| `app/static/js/i18n.js` | dizionario i18n | + chiavi `sal.*` / `deliv.*` |
| `tests/test_sal_metrics.py` | unit service | + test euro/anno/matrix |
| `tests/test_sal_endpoints.py` | unit endpoint | + test filtri/campi |
| `tests/test_delivery_item_validation.py` | unit validation (nuovo) | crea |
| `CLAUDE.md` | convenzioni | + nota P2 |
| `app/main.py` + `CHANGELOG.md` | versione | bump |

---

## Task 1: Documentare la convenzione P2 in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (sezione "## Convenzioni di codice")

- [ ] **Step 1: Aggiungere il bullet sull'ordine menu**

Nella sezione `## Convenzioni di codice`, dopo il bullet `**Frontend**: niente framework…`, aggiungere:

```markdown
- **Ordine menu/colonne deterministico**: ogni `<select>`/dropdown e ogni colonna ordinabile ha un ordine esplicito. Liste anagrafiche (clienti, progetti, fornitori) = alfabetico case-insensitive (`localeCompare`); categorie/reparti/stati = `sort_order` poi nome. Mai affidarsi all'ordine di inserimento DB per i menu.
- **i18n da subito**: ogni stringa UI nuova va tradotta in tutte le 5 lingue (`it/en/fr/de/es`) in `app/static/js/i18n.js` + `data-i18n` nel template, nello stesso commit. Niente debito i18n.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(conventions): pin i18n-always + deterministic menu order (P1/P2)"
```

---

## Task 2: `preferred_container_for_codec` (funzione pura)

**Files:**
- Modify: `app/services/delivery_item_validation.py` (append dopo `valid_video_codec_ids`, ~riga 241)
- Test: `tests/test_delivery_item_validation.py` (nuovo)

- [ ] **Step 1: Scrivere il test che fallisce**

Creare `tests/test_delivery_item_validation.py`:

```python
"""delivery_item_validation — funzioni pure (no DB).

preferred_container_for_codec: dato il family del codec e la lista container,
ritorna l'id del container preferito (ProRes→QuickTime) o None.
"""
from app.services.delivery_item_validation import preferred_container_for_codec


class _C:
    def __init__(self, id, name, extension=None):
        self.id = id
        self.name = name
        self.extension = extension


def test_prores_prefers_quicktime_by_name():
    conts = [_C(1, "MXF OP1a"), _C(2, "QuickTime", ".mov"), _C(3, "MP4")]
    assert preferred_container_for_codec(codec_family="ProRes", containers=conts) == 2


def test_prores_prefers_by_mov_extension():
    conts = [_C(1, "MXF OP1a"), _C(7, "Movie wrapper", ".mov")]
    assert preferred_container_for_codec(codec_family="prores", containers=conts) == 7


def test_non_prores_family_returns_none():
    conts = [_C(2, "QuickTime", ".mov")]
    assert preferred_container_for_codec(codec_family="DNxHR", containers=conts) is None


def test_empty_family_returns_none():
    conts = [_C(2, "QuickTime", ".mov")]
    assert preferred_container_for_codec(codec_family="", containers=conts) is None
    assert preferred_container_for_codec(codec_family=None, containers=conts) is None


def test_prores_no_quicktime_available_returns_none():
    conts = [_C(1, "MXF OP1a"), _C(3, "MP4")]
    assert preferred_container_for_codec(codec_family="ProRes", containers=conts) is None


def test_accepts_dict_containers():
    conts = [{"id": 9, "name": "QuickTime", "extension": ".mov"}]
    assert preferred_container_for_codec(codec_family="ProRes", containers=conts) == 9
```

- [ ] **Step 2: Eseguire il test, verificare che fallisce**

Run: `python -m pytest tests/test_delivery_item_validation.py -q`
Expected: FAIL con `ImportError: cannot import name 'preferred_container_for_codec'`

- [ ] **Step 3: Implementare la funzione**

In `app/services/delivery_item_validation.py`, dopo la fine di `valid_video_codec_ids` (riga ~241), aggiungere:

```python
def preferred_container_for_codec(*, codec_family, containers) -> Optional[int]:
    """Id del container preferito per la famiglia codec. PURA: nessun DB.

    `containers` = iterabile di oggetti con `.id`/`.name`/`.extension` o dict con
    chiavi 'id'/'name'/'extension'. Il chiamante risolve e ordina i container.

    - family contiene 'prores' → id del primo container QuickTime/.mov nell'ordine
      ricevuto; None se nessun QuickTime disponibile.
    - altre family / family vuota/None → None (nessuna preferenza forzata).

    Deriva dalla regola R3 (ProRes tipicamente in QuickTime/.mov). Estendibile in
    futuro con altre coppie codec→container.
    """
    fam = (codec_family or "").strip().lower()
    if "prores" not in fam:
        return None
    for c in containers:
        if isinstance(c, dict):
            cid = c.get("id")
            name = (c.get("name") or "")
            ext = (c.get("extension") or "")
        else:
            cid = getattr(c, "id", None)
            name = getattr(c, "name", "") or ""
            ext = getattr(c, "extension", "") or ""
        nm = name.strip().lower()
        ex = ext.strip().lower()
        if "quicktime" in nm or "mov" in nm or ex in (".mov", "mov"):
            return cid
    return None
```

- [ ] **Step 4: Eseguire il test, verificare PASS**

Run: `python -m pytest tests/test_delivery_item_validation.py -q`
Expected: PASS (6 test)

- [ ] **Step 5: Commit**

```bash
git add app/services/delivery_item_validation.py tests/test_delivery_item_validation.py
git commit -m "feat(deliverables): preferred_container_for_codec (ProRes->QuickTime) pure fn"
```

---

## Task 3: Esporre `preferred_container_id` nell'endpoint spec-schema

**Files:**
- Modify: `app/routers/delivery_items.py:418-440` (funzione `spec_schema`)

- [ ] **Step 1: Aggiornare l'import e il return**

In `app/routers/delivery_items.py`, riga 418, estendere l'import:

```python
    from app.services.delivery_item_validation import field_relevance, validate_delivery_item, valid_video_codec_ids, preferred_container_for_codec
```

Poi, subito prima del `return` finale (riga ~440), dopo il blocco `valid_ids`, aggiungere:

```python
    # v3.5.0 — container preferito per il codec selezionato (ProRes→QuickTime).
    # None = nessuna preferenza. L'editor lo usa per auto-compilare il container
    # vuoto o al cambio codec.
    preferred_container_id = None
    if vc is not None and getattr(vc, "family", None):
        _conts = (
            db.query(Container)
            .filter(Container.is_active == True)  # noqa: E712
            .order_by(Container.sort_order, Container.name)
            .all()
        )
        preferred_container_id = preferred_container_for_codec(
            codec_family=vc.family, containers=_conts)
    return {
        "groups": groups,
        "findings": findings,
        "valid_video_codec_ids": valid_ids,
        "preferred_container_id": preferred_container_id,
    }
```

(`Container` è già importato nel modulo — usato da `db.get(Container, ...)`.)

- [ ] **Step 2: Smoke manuale dell'endpoint**

Avviare il server (`.venv\Scripts\python.exe run.py`) e con un `video_codec_id` di famiglia ProRes noto:

Run (PowerShell):
```powershell
$fd = @{ video_codec_id = <ID_PRORES> }
Invoke-WebRequest -Uri http://localhost:8000/delivery-items/api/spec-schema -Method POST -Body $fd -UseBasicParsing
```
Expected: JSON con chiave `preferred_container_id` valorizzata all'id del container QuickTime (o `null` se non c'è QuickTime / codec non ProRes).

- [ ] **Step 3: Commit**

```bash
git add app/routers/delivery_items.py
git commit -m "feat(deliverables): spec-schema returns preferred_container_id"
```

---

## Task 4: Auto-set container al cambio codec ProRes (Bug 1 + Bug 2, lato editor)

**Files:**
- Modify: `app/templates/pages/planning.html` (funzione `dsmApplySpecSchema` ~2589-2637 e il binding listener ~2574-2579)

- [ ] **Step 1: Leggere il binding listener attuale**

Run: cercare in `app/templates/pages/planning.html` il blocco che fa `addEventListener('change', dsmApplySpecSchema)` (intorno a riga 2574):

```javascript
  ['dsm-s-container','dsm-s-vcodec','dsm-s-package'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', dsmApplySpecSchema);
  });
  dsmApplySpecSchema();
```

- [ ] **Step 2: Sostituire il binding per tracciare quale combo è cambiato**

Sostituire il blocco di Step 1 con:

```javascript
  ['dsm-s-container','dsm-s-vcodec','dsm-s-package'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', () => { _dsmLastChanged = id; dsmApplySpecSchema(); });
  });
  _dsmLastChanged = null;
  dsmApplySpecSchema();
```

- [ ] **Step 3: Dichiarare la variabile di modulo**

Immediatamente sopra `async function dsmApplySpecSchema() {` (riga 2589), aggiungere:

```javascript
// Traccia l'ultimo combo cambiato (container/vcodec/package) per decidere se
// auto-compilare il container al cambio codec. null all'apertura modal.
let _dsmLastChanged = null;
```

- [ ] **Step 4: Aggiungere la logica preferred-container in fondo a dsmApplySpecSchema**

Dentro `dsmApplySpecSchema`, subito prima della `}` di chiusura della funzione (dopo il blocco `valid_video_codec_ids`, riga ~2636), aggiungere:

```javascript
  // v3.5.0 — auto-compila il container quando si sceglie un codec ProRes
  // (Bug 1) o quando il container è vuoto su un item ProRes (Bug 2).
  // Scatta solo se è cambiato il codec OPPURE il container è vuoto: non
  // sovrascrive una scelta deliberata di container fatta dall'utente.
  const pref = data.preferred_container_id;
  if (pref && cont) {
    const codecChanged = (_dsmLastChanged === 'dsm-s-vcodec');
    const contEmpty = !cont.value;
    if ((contEmpty || codecChanged) && String(cont.value) !== String(pref)) {
      cont.value = String(pref);
      // Rilancia lo schema per il nuovo container (filtro opzioni codec).
      // Marca _dsmLastChanged='dsm-s-container' così questo ramo non si ripete.
      _dsmLastChanged = 'dsm-s-container';
      dsmApplySpecSchema();
      return;
    }
  }
```

(Terminazione garantita: alla seconda chiamata `cont.value === pref` e `codecChanged` è false → il ramo non rientra.)

- [ ] **Step 5: Riavviare il server e smoke browser**

Riavviare il server (OneDrive rompe il reload — kill + restart). Aprire `/planning/?view=deliverables`, aprire l'editor tech-spec di un deliverable video, selezionare un codec ProRes nel select "Video codec".
Expected: il select "Container" passa automaticamente a QuickTime. Aprendo un item ProRes che aveva container vuoto, il container si popola a QuickTime all'apertura.

- [ ] **Step 6: Commit**

```bash
git add app/templates/pages/planning.html
git commit -m "fix(deliverables): auto-set QuickTime container on ProRes codec (bug 1+2)"
```

---

## Task 5: Fix troncamento select preset audio (Bug 3)

**Files:**
- Modify: `app/templates/pages/planning.html` (funzione `_dsmRenderAudioSection` ~2655-2663)

- [ ] **Step 1: Allargare il select a riga piena**

Sostituire la riga 2663:

```javascript
  presetSel.style.cssText = 'height:30px;font-size:12px;flex:1;min-width:200px;';
```

con:

```javascript
  // flex-basis:100% + min-width:0 → il select va a riga piena sotto la label,
  // così il nome preset lungo non viene clippato dal box stretto.
  presetSel.style.cssText = 'height:30px;font-size:12px;flex:1 1 100%;min-width:0;width:100%;';
```

- [ ] **Step 2: Smoke browser**

Riavviare il server. Aprire l'editor tech-spec di un deliverable con audio, sezione "🔊 Audio", aprire il select "Preset config audio".
Expected: il nome del preset selezionato (anche lungo, es. un preset Atmos) è visibile per intero, non tagliato. Il select occupa l'intera larghezza della riga.

- [ ] **Step 3: Commit**

```bash
git add app/templates/pages/planning.html
git commit -m "fix(deliverables): audio preset select full-width (no text clip, bug 3)"
```

---

## Task 6: Migrazione backfill container ProRes (Bug 2, dati esistenti)

**Files:**
- Create: `scripts/migrate_prores_container.py`

- [ ] **Step 1: Scrivere lo script idempotente**

Creare `scripts/migrate_prores_container.py`:

```python
"""Backfill non distruttivo: DeliveryItem con codec famiglia ProRes e
container_id NULL → assegna il container QuickTime del loro tenant.

Idempotente: salta gli item che hanno già un container. Logga il conteggio.
Prerequisito: esiste un Container QuickTime/.mov attivo per il tenant; se manca
lo crea (name 'QuickTime', extension '.mov', media_kind 'video').

Uso:
    .venv\\Scripts\\python.exe scripts\\migrate_prores_container.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models.models import DeliveryItem, VideoCodec, Container


def _find_or_create_quicktime(db, tenant_id):
    q = (
        db.query(Container)
        .filter(Container.is_active == True)  # noqa: E712
        .order_by(Container.sort_order, Container.name)
    )
    if tenant_id is not None:
        q = q.filter((Container.tenant_id == tenant_id) | (Container.tenant_id.is_(None)))
    for c in q.all():
        nm = (c.name or "").strip().lower()
        ex = (c.extension or "").strip().lower()
        if "quicktime" in nm or "mov" in nm or ex in (".mov", "mov"):
            return c
    c = Container(
        tenant_id=tenant_id, name="QuickTime", extension=".mov",
        media_kind="video", is_active=True, sort_order=0,
        description="Auto-creato da migrate_prores_container",
    )
    db.add(c)
    db.flush()
    return c


def main():
    db = SessionLocal()
    try:
        prores_ids = {
            vc.id for vc in db.query(VideoCodec).all()
            if "prores" in ((vc.family or "").strip().lower())
        }
        if not prores_ids:
            print("Nessun VideoCodec ProRes in tassonomia: niente da fare.")
            return
        items = (
            db.query(DeliveryItem)
            .filter(
                DeliveryItem.video_codec_id.in_(prores_ids),
                DeliveryItem.container_id.is_(None),
            )
            .all()
        )
        if not items:
            print("Nessun DeliveryItem ProRes senza container. OK.")
            return
        touched = 0
        qt_by_tenant = {}
        for it in items:
            tid = getattr(it, "tenant_id", None)
            qt = qt_by_tenant.get(tid)
            if qt is None:
                qt = _find_or_create_quicktime(db, tid)
                qt_by_tenant[tid] = qt
            it.container_id = qt.id
            touched += 1
        db.commit()
        print(f"Backfill completato: {touched} DeliveryItem ProRes → QuickTime.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Eseguire la migrazione**

Run: `.venv\Scripts\python.exe scripts\migrate_prores_container.py`
Expected: stampa il conteggio item toccati (o "niente da fare"). Ri-eseguendolo: "Nessun DeliveryItem ProRes senza container. OK." (idempotente).

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_prores_container.py
git commit -m "feat(deliverables): migration backfill ProRes items -> QuickTime container"
```

---

## Task 7: Metriche euro in sal_metrics

**Files:**
- Modify: `app/services/sal_metrics.py` (nuove fn + estensione `job_metrics`/`project_metrics`/`by_department`)
- Test: `tests/test_sal_metrics.py`

- [ ] **Step 1: Scrivere i test che falliscono**

In `tests/test_sal_metrics.py`, in fondo al file, aggiungere:

```python
# ── Gruppo euro (v3.5.0) ─────────────────────────────────────────

def test_quoted_accrued_amount(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    j1 = _jcl(db, job, unit="hr", qty=10)
    j1.total_quoted = 1000.0
    j1.total_accrued = 400.0
    j2 = _jcl(db, job, unit="day", qty=2)
    j2.total_quoted = 500.0
    j2.total_accrued = 500.0
    db.flush()
    assert sal_metrics.quoted_amount(job) == 1500.0
    assert sal_metrics.accrued_amount(job) == 900.0


def test_job_metrics_includes_eur(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    j1 = _jcl(db, job, unit="hr", qty=10)
    j1.total_quoted = 1000.0
    j1.total_accrued = 250.0
    db.flush()
    m = sal_metrics.job_metrics(job)
    assert m["quoted_eur"] == 1000.0
    assert m["accrued_eur"] == 250.0
    assert m["pct_eur"] == 0.25


def test_job_metrics_pct_eur_zero_quoted(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    j1 = _jcl(db, job, unit="hr", qty=0)
    j1.total_quoted = 0.0
    j1.total_accrued = 100.0
    db.flush()
    assert sal_metrics.job_metrics(job)["pct_eur"] == 0.0


def test_project_metrics_includes_eur(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    j1 = _jcl(db, job, unit="hr", qty=10)
    j1.total_quoted = 800.0
    j1.total_accrued = 200.0
    db.flush()
    db.refresh(prj)
    m = sal_metrics.project_metrics(db, prj)
    assert m["quoted_eur"] == 800.0
    assert m["accrued_eur"] == 200.0
    assert m["pct_eur"] == 0.25
```

- [ ] **Step 2: Eseguire, verificare FAIL**

Run: `python -m pytest tests/test_sal_metrics.py -k "amount or eur" -q`
Expected: FAIL (`AttributeError: module 'app.services.sal_metrics' has no attribute 'quoted_amount'`)

- [ ] **Step 3: Implementare le metriche euro**

In `app/services/sal_metrics.py`, dopo `quoted_hours` (riga ~56), aggiungere:

```python
def quoted_amount(job) -> float:
    """Σ JobCostLine.total_quoted (euro quotati) del job."""
    return sum(
        float(getattr(j, "total_quoted", 0.0) or 0.0)
        for j in (getattr(job, "cost_lines", None) or [])
    )


def accrued_amount(job) -> float:
    """Σ JobCostLine.total_accrued (euro maturati) del job."""
    return sum(
        float(getattr(j, "total_accrued", 0.0) or 0.0)
        for j in (getattr(job, "cost_lines", None) or [])
    )


def blended_rate(quoted_eur: float, quoted_hours: float) -> float:
    """€/ora medio del progetto/job (per stimare €-anno dalle ore). 0 se 0 ore."""
    return (quoted_eur / quoted_hours) if quoted_hours and quoted_hours > 0 else 0.0
```

In `job_metrics` (riga ~149), estendere il dict di ritorno:

```python
def job_metrics(job, *, daily_hours: float = DEFAULT_DAILY_HOURS) -> dict:
    """{quoted, planned, worked, pct, alarm, quoted_eur, accrued_eur, pct_eur}."""
    quoted = quoted_hours(job, daily_hours=daily_hours)
    planned = planned_hours(job)
    worked = worked_hours(job)
    pct = (worked / quoted) if quoted > 0 else 0.0
    q_eur = quoted_amount(job)
    a_eur = accrued_amount(job)
    return {
        "quoted": quoted,
        "planned": planned,
        "worked": worked,
        "pct": pct,
        "alarm": _alarm_from(quoted, planned, worked),
        "quoted_eur": q_eur,
        "accrued_eur": a_eur,
        "pct_eur": (a_eur / q_eur) if q_eur > 0 else 0.0,
    }
```

In `project_metrics` (riga ~188), accumulare gli euro:

```python
def project_metrics(db, project) -> dict:
    quoted = planned = worked = 0.0
    quoted_eur = accrued_eur = 0.0
    job_count = 0
    has_red = has_amber = False
    for job in (getattr(project, "jobs", None) or []):
        job_count += 1
        daily = _daily_hours_for_job(db, job)
        m = job_metrics(job, daily_hours=daily)
        quoted += m["quoted"]
        planned += m["planned"]
        worked += m["worked"]
        quoted_eur += m["quoted_eur"]
        accrued_eur += m["accrued_eur"]
        if m["alarm"] == "red":
            has_red = True
        elif m["alarm"] == "amber":
            has_amber = True
    pct = (worked / quoted) if quoted > 0 else 0.0
    alarm = "red" if has_red else ("amber" if has_amber else "none")
    return {
        "quoted": quoted,
        "planned": planned,
        "worked": worked,
        "pct": pct,
        "alarm": alarm,
        "job_count": job_count,
        "quoted_eur": quoted_eur,
        "accrued_eur": accrued_eur,
        "pct_eur": (accrued_eur / quoted_eur) if quoted_eur > 0 else 0.0,
    }
```

In `by_department` (riga ~94), aggiungere gli euro al bucket. Cambiare `_bucket`:

```python
    def _bucket(dep_id: int) -> dict:
        return out.setdefault(dep_id, {
            "quoted": 0.0, "planned": 0.0, "worked": 0.0,
            "quoted_eur": 0.0, "accrued_eur": 0.0,
        })
```

e nel loop "Quotato per reparto", dopo `_bucket(dep_id or 0)["quoted"] += h`, aggiungere (dentro lo stesso `for jcl`, ma fuori dal `if h <= 0: continue` — gli euro vanno sommati anche per le voci a corpo):

```python
    # Euro per reparto: total_quoted/total_accrued della JCL attribuiti al
    # reparto del suo PriceItem (anche per voci non a tempo).
    for jcl in (getattr(job, "cost_lines", None) or []):
        pi = getattr(jcl, "price_item", None)
        dep_id = getattr(pi, "department_id", None) if pi is not None else None
        b = _bucket(dep_id or 0)
        b["quoted_eur"] += float(getattr(jcl, "total_quoted", 0.0) or 0.0)
        b["accrued_eur"] += float(getattr(jcl, "total_accrued", 0.0) or 0.0)
```

(Inserire questo secondo loop subito dopo il primo loop "Quotato per reparto", prima del loop bookings.)

- [ ] **Step 4: Eseguire, verificare PASS**

Run: `python -m pytest tests/test_sal_metrics.py -k "amount or eur" -q`
Expected: PASS (4 test)

- [ ] **Step 5: Commit**

```bash
git add app/services/sal_metrics.py tests/test_sal_metrics.py
git commit -m "feat(sal): euro metrics (quoted/accrued/pct_eur) + blended_rate"
```

---

## Task 8: Helper ore per-anno in sal_metrics

**Files:**
- Modify: `app/services/sal_metrics.py` (nuove fn dopo `worked_hours`)
- Test: `tests/test_sal_metrics.py`

- [ ] **Step 1: Scrivere i test che falliscono**

In `tests/test_sal_metrics.py`, aggiungere:

```python
# ── Gruppo per-anno (v3.5.0) ─────────────────────────────────────

def test_worked_planned_hours_in_year(db):
    from app.models import BookingExecutionStatus
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    # 2025: 8h done; 2027: 8h planned
    _booking(db, job, start=datetime(2025, 3, 3, 9), end=datetime(2025, 3, 3, 17),
             execution=BookingExecutionStatus.done)
    _booking(db, job, start=datetime(2027, 3, 3, 9), end=datetime(2027, 3, 3, 17),
             execution=BookingExecutionStatus.planned)
    db.refresh(job)
    assert sal_metrics.worked_hours_in_year(job, 2025) == 8.0
    assert sal_metrics.worked_hours_in_year(job, 2027) == 0.0  # planned, non done
    assert sal_metrics.planned_hours_in_year(job, 2027) == 8.0
    assert sal_metrics.planned_hours_in_year(job, 2025) == 8.0  # done conta come planned


def test_blended_rate():
    assert sal_metrics.blended_rate(1000.0, 50.0) == 20.0
    assert sal_metrics.blended_rate(1000.0, 0.0) == 0.0
```

- [ ] **Step 2: Eseguire, verificare FAIL**

Run: `python -m pytest tests/test_sal_metrics.py -k "in_year or blended_rate" -q`
Expected: FAIL (`AttributeError: ... 'worked_hours_in_year'`)

- [ ] **Step 3: Implementare gli helper**

In `app/services/sal_metrics.py`, dopo `worked_hours` (riga ~81), aggiungere:

```python
def _booking_year(b):
    sd = getattr(b, "start_datetime", None)
    return sd.year if sd is not None else None


def worked_hours_in_year(job, year: int) -> float:
    """Σ ore lavorate (done) dei booking non-cancelled con start_datetime in year."""
    from app.models import BookingExecutionStatus
    return sum(
        _booking_billable_hours(b)
        for b in _non_cancelled_bookings(job)
        if b.execution_status == BookingExecutionStatus.done
        and _booking_year(b) == year
    )


def planned_hours_in_year(job, year: int) -> float:
    """Σ ore pianificate (tutti i booking non-cancelled) con start_datetime in year."""
    return sum(
        _booking_billable_hours(b)
        for b in _non_cancelled_bookings(job)
        if _booking_year(b) == year
    )
```

(`blended_rate` è già stata aggiunta nel Task 7.)

- [ ] **Step 4: Eseguire, verificare PASS**

Run: `python -m pytest tests/test_sal_metrics.py -k "in_year or blended_rate" -q`
Expected: PASS (2 test)

- [ ] **Step 5: Commit**

```bash
git add app/services/sal_metrics.py tests/test_sal_metrics.py
git commit -m "feat(sal): worked/planned_hours_in_year helpers"
```

---

## Task 9: Matrix passato/futuro con flag `basis`

**Files:**
- Modify: `app/services/sal_metrics.py` (`matrix_metrics`, riga ~333)
- Test: `tests/test_sal_metrics.py`

- [ ] **Step 1: Scrivere il test che fallisce**

In `tests/test_sal_metrics.py`, aggiungere (usa l'anno corrente per il confine):

```python
# ── Gruppo matrix past/future (v3.5.0) ───────────────────────────

def test_matrix_basis_past_worked_future_planned(db):
    from datetime import date
    from app.models import BookingExecutionStatus
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="hr", qty=100)  # 100h quotate
    yr = date.today().year
    # Gennaio (passato salvo che oggi sia gennaio): 10h done
    _booking(db, job, start=datetime(yr, 1, 6, 9), end=datetime(yr, 1, 6, 19),
             execution=BookingExecutionStatus.done)
    # Dicembre (futuro): 10h planned (non done)
    _booking(db, job, start=datetime(yr, 12, 8, 9), end=datetime(yr, 12, 8, 19),
             execution=BookingExecutionStatus.planned)
    db.refresh(prj)
    m = sal_metrics.matrix_metrics(db, year=yr, granularity="month")
    row = m["projects"][0]
    jan = row["cells"][0]
    dec = row["cells"][11]
    assert jan["basis"] == "worked"
    assert dec["basis"] == "planned"
    # Dicembre cumula anche il planned di dicembre (futuro): 10+10=20h → 20%
    assert dec["worked_cum"] == 20.0
    # Le celle del totale hanno anch'esse basis
    assert m["total"]["cells"][0]["basis"] == "worked"
```

- [ ] **Step 2: Eseguire, verificare FAIL**

Run: `python -m pytest tests/test_sal_metrics.py -k "matrix_basis" -q`
Expected: FAIL (`KeyError: 'basis'`)

- [ ] **Step 3: Modificare matrix_metrics**

In `app/services/sal_metrics.py`, sostituire l'intero corpo di `matrix_metrics` dalla riga `tid = current_tenant_id()` in poi. Punti chiave: calcolare `cur_first`, raccogliere `planned_events` oltre a `done_events`, scegliere events per cella in base al confine, aggiungere `basis`.

Aggiungere l'import della data dopo gli import esistenti della funzione:

```python
    from datetime import date as _date
```

Dopo il calcolo di `labels`/`cutoffs`, aggiungere:

```python
    today = _date.today()
    cur_first = _dt(today.year, today.month, 1)

    def _basis_for(cutoff):
        # periodo interamente passato (cutoff = primo istante del periodo
        # successivo ≤ primo giorno del mese corrente) → lavorato; altrimenti
        # (mese corrente + futuri) → pianificato.
        return "worked" if cutoff <= cur_first else "planned"
```

Nel loop progetti, sostituire la raccolta `done_events` con due liste:

```python
    for prj in projects:
        quoted = 0.0
        done_events: list[tuple] = []
        planned_events: list[tuple] = []
        for job in (prj.jobs or []):
            dh = _daily_hours_for_job(db, job)
            quoted += quoted_hours(job, daily_hours=dh)
            for b in _non_cancelled_bookings(job):
                sd = getattr(b, "start_datetime", None)
                if sd is None:
                    continue
                h = _booking_billable_hours(b)
                if h <= 0:
                    continue
                planned_events.append((sd, h))
                if b.execution_status == BookingExecutionStatus.done:
                    done_events.append((sd, h))

        cum_cells = []
        for i, cutoff in enumerate(cutoffs):
            basis = _basis_for(cutoff)
            events = done_events if basis == "worked" else planned_events
            cum = sum(h for sd, h in events if sd < cutoff)
            pct = (cum / quoted) if quoted > 0 else 0.0
            cum_cells.append({"label": labels[i], "worked_cum": round(cum, 2),
                              "pct": pct, "basis": basis})

        final_cum = cum_cells[-1]["worked_cum"] if cum_cells else 0.0
        if quoted <= 0 and final_cum <= 0:
            continue

        rows.append({
            "id": prj.id,
            "code": prj.code,
            "title": prj.title,
            "client": prj.client.name if prj.client else None,
            "quoted": round(quoted, 2),
            "cells": cum_cells,
        })
        total_quoted += quoted
        for i, c in enumerate(cum_cells):
            total_cum[i] += c["worked_cum"]
```

Sostituire la costruzione di `total_cells`:

```python
    total_cells = [
        {"label": labels[i], "worked_cum": round(total_cum[i], 2),
         "pct": (total_cum[i] / total_quoted) if total_quoted > 0 else 0.0,
         "basis": _basis_for(cutoffs[i])}
        for i in range(len(cutoffs))
    ]
```

(Il `return` finale resta identico.) Aggiornare la docstring per riflettere past=worked/future=planned.

- [ ] **Step 4: Eseguire, verificare PASS**

Run: `python -m pytest tests/test_sal_metrics.py -k "matrix" -q`
Expected: PASS (incluso il test esistente sul matrix + il nuovo `matrix_basis`).

- [ ] **Step 5: Commit**

```bash
git add app/services/sal_metrics.py tests/test_sal_metrics.py
git commit -m "feat(sal): matrix cells past=worked / future=planned with basis flag"
```

---

## Task 10: Endpoint `/api/sal/projects` — filtri + campi euro/anno

**Files:**
- Modify: `app/routers/finance.py:2978-3047` (funzione `sal_projects`)
- Test: `tests/test_sal_endpoints.py`

- [ ] **Step 1: Scrivere i test che falliscono**

In `tests/test_sal_endpoints.py`, dopo i test esistenti su `sal_projects`, aggiungere (usano la fixture `client_admin` esistente; adattare gli helper di creazione dati al pattern del file — `client_admin` espone `(client, session, token)` o simile: seguire i test esistenti nel file per costruire progetto+job+JCL+booking e fare la GET). Test minimi richiesti:

```python
def test_sal_projects_returns_eur_and_year_fields(client_admin):
    client, session, headers = _setup_one_project(client_admin)  # helper locale come negli altri test
    r = client.get("/finance/api/sal/projects", headers=headers)
    assert r.status_code == 200
    row = r.json()[0]
    for k in ("quoted_eur", "accrued_eur", "pct_eur",
              "prev_year", "next_year", "prev_year_eur", "next_year_eur"):
        assert k in row


def test_sal_projects_filter_by_department(client_admin):
    # progetto con JCL in reparto A; filtrando per reparto B → 0 righe.
    client, session, headers, dep_a, dep_b = _setup_two_departments(client_admin)
    r = client.get(f"/finance/api/sal/projects?department_id={dep_b}", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_sal_projects_filter_by_category(client_admin):
    client, session, headers, cat_a, cat_b = _setup_two_categories(client_admin)
    r = client.get(f"/finance/api/sal/projects?category_id={cat_b}", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_sal_projects_filter_by_project_id(client_admin):
    client, session, headers, pid, other_pid = _setup_two_projects(client_admin)
    r = client.get(f"/finance/api/sal/projects?project_id={pid}", headers=headers)
    assert r.status_code == 200
    ids = [row["id"] for row in r.json()]
    assert ids == [pid]
```

> Nota implementativa per chi esegue: riusare il pattern di costruzione dati già presente in `tests/test_sal_endpoints.py` (sezione `sal_projects`). Gli helper `_setup_*` sono thin wrapper attorno a quel pattern; se il file non li ha, costruire i dati inline come negli altri test del file (Client/Project/Job/JobCostLine/PriceItem/PriceCategory/Department con `session`).

- [ ] **Step 2: Eseguire, verificare FAIL**

Run: `python -m pytest tests/test_sal_endpoints.py -k "eur_and_year or filter_by" -q`
Expected: FAIL (campi mancanti / filtri inesistenti).

- [ ] **Step 3: Estendere l'endpoint**

In `app/routers/finance.py`, sostituire la firma e il corpo di `sal_projects` (righe 2978-3047). Nuova firma:

```python
@router.get("/api/sal/projects", dependencies=[RequireViewFinance])
async def sal_projects(
    status: Optional[str] = None,
    client_id: Optional[int] = None,
    q: Optional[str] = None,
    alarm_only: Optional[bool] = False,
    department_id: Optional[int] = None,
    category_id: Optional[int] = None,
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
```

Dopo i filtri SQL esistenti (`client_id`/`status`/`q`), aggiungere:

```python
    if project_id:
        query = query.filter(Project.id == project_id)
```

Aggiungere prima del loop, per gli anni:

```python
    from app.services import sal_metrics
    cur_year = date.today().year
    prev_year = cur_year - 1
    next_year = cur_year + 1

    def _project_has_department(prj, dep_id):
        for job in (prj.jobs or []):
            for jcl in (job.cost_lines or []):
                pi = getattr(jcl, "price_item", None)
                if pi is not None and getattr(pi, "department_id", None) == dep_id:
                    return True
            for b in sal_metrics._non_cancelled_bookings(job):
                if sal_metrics._booking_department_id(b) == dep_id:
                    return True
        return False

    def _project_has_category(prj, cat_id):
        for job in (prj.jobs or []):
            for jcl in (job.cost_lines or []):
                pi = getattr(jcl, "price_item", None)
                if pi is not None and getattr(pi, "category_id", None) == cat_id:
                    return True
        return False
```

Sostituire il corpo del loop `for prj in query.order_by(...).all():` con:

```python
    rows = []
    for prj in query.order_by(Project.created_at.desc()).all():
        # Row-filter categoria (solo presenza; non ri-scala le metriche).
        if category_id and not _project_has_category(prj, category_id):
            continue
        # Row-filter reparto + ri-scala metrica al reparto.
        if department_id and not _project_has_department(prj, department_id):
            continue

        m = sal_metrics.project_metrics(db, prj)

        # Se filtro reparto attivo, ri-scala quoted/planned/worked (+eur) al
        # solo reparto, aggregando by_department su tutti i job del progetto.
        if department_id:
            dq = dp = dw = 0.0
            dqe = dae = 0.0
            for job in (prj.jobs or []):
                daily = sal_metrics._daily_hours_for_job(db, job)
                bd = sal_metrics.by_department(job, daily_hours=daily)
                v = bd.get(department_id)
                if v:
                    dq += v["quoted"]; dp += v["planned"]; dw += v["worked"]
                    dqe += v["quoted_eur"]; dae += v["accrued_eur"]
            m = {
                **m,
                "quoted": dq, "planned": dp, "worked": dw,
                "pct": (dw / dq) if dq > 0 else 0.0,
                "quoted_eur": dqe, "accrued_eur": dae,
                "pct_eur": (dae / dqe) if dqe > 0 else 0.0,
            }

        if alarm_only and m["alarm"] == "none":
            continue

        # Quotazioni distinte dei job del progetto.
        seen: set = set()
        quotes = []
        for job in (prj.jobs or []):
            qt = getattr(job, "quote", None)
            if qt is not None and qt.id not in seen:
                seen.add(qt.id)
                quotes.append({"number": qt.number, "title": qt.title})

        # Colonne anno N-1 (lavorate) / N+1 (pianificate), in ore.
        py_h = ny_h = 0.0
        for job in (prj.jobs or []):
            py_h += sal_metrics.worked_hours_in_year(job, prev_year)
            ny_h += sal_metrics.planned_hours_in_year(job, next_year)
        rate = sal_metrics.blended_rate(m["quoted_eur"], m["quoted"])

        rows.append({
            "id": prj.id,
            "code": prj.code,
            "title": prj.title,
            "client": prj.client.name if prj.client else None,
            "quotes": quotes,
            "quoted": m["quoted"],
            "planned": m["planned"],
            "worked": m["worked"],
            "pct": m["pct"],
            "alarm": m["alarm"],
            "job_count": m["job_count"],
            "quoted_eur": m["quoted_eur"],
            "accrued_eur": m["accrued_eur"],
            "pct_eur": m["pct_eur"],
            "prev_year": py_h,
            "next_year": ny_h,
            "prev_year_eur": py_h * rate,
            "next_year_eur": ny_h * rate,
            "prev_year_label": prev_year,
            "next_year_label": next_year,
        })
    return rows
```

(Rimuovere il vecchio `from app.services import sal_metrics` duplicato se già presente in cima alla funzione — tenerne uno solo.)

- [ ] **Step 4: Eseguire, verificare PASS**

Run: `python -m pytest tests/test_sal_endpoints.py -q`
Expected: PASS (test nuovi + esistenti).

- [ ] **Step 5: Commit**

```bash
git add app/routers/finance.py tests/test_sal_endpoints.py
git commit -m "feat(sal): projects API filters (dept/category/project) + eur/year fields"
```

---

## Task 11: Chiavi i18n per il batch SAL

**Files:**
- Modify: `app/static/js/i18n.js` (`window.MF_I18N`)

- [ ] **Step 1: Aggiungere le chiavi (5 lingue)**

In `app/static/js/i18n.js`, dentro `window.MF_I18N`, aggiungere il blocco (mantenere la formattazione a colonne del file):

```javascript
  // ── SAL batch (v3.5.0) ──────────────────────────────────────────
  'sal.unit.hours':        {it: 'Ore',        en: 'Hours',      fr: 'Heures',     de: 'Stunden',    es: 'Horas'},
  'sal.unit.budget':       {it: 'Budget (€)', en: 'Budget (€)', fr: 'Budget (€)', de: 'Budget (€)', es: 'Presupuesto (€)'},
  'sal.filter.department': {it: 'Reparto',    en: 'Department', fr: 'Département', de: 'Abteilung',  es: 'Departamento'},
  'sal.filter.category':   {it: 'Tipo lavorazione', en: 'Work type', fr: 'Type de travail', de: 'Arbeitstyp', es: 'Tipo de trabajo'},
  'sal.filter.project':    {it: 'Progetto',   en: 'Project',    fr: 'Projet',     de: 'Projekt',    es: 'Proyecto'},
  'sal.filter.category.hint': {it: 'Filtra i progetti con lavorazioni di questo tipo (non ri-scala le ore).', en: 'Filters projects having this work type (does not rescale hours).', fr: 'Filtre les projets ayant ce type de travail (ne redimensionne pas les heures).', de: 'Filtert Projekte mit diesem Arbeitstyp (skaliert Stunden nicht).', es: 'Filtra proyectos con este tipo de trabajo (no reescala las horas).'},
  'sal.opt.all':           {it: '— tutti —',  en: '— all —',    fr: '— tous —',   de: '— alle —',   es: '— todos —'},
  'sal.col.prev_year':     {it: 'Anno prec.', en: 'Prev. year', fr: 'Année préc.', de: 'Vorjahr',   es: 'Año ant.'},
  'sal.col.next_year':     {it: 'Anno succ.', en: 'Next year',  fr: 'Année suiv.', de: 'Folgejahr', es: 'Año sig.'},
  'sal.col.prev_year.hint':{it: 'Ore lavorate nell\'anno precedente.', en: 'Hours worked in the previous year.', fr: 'Heures travaillées l\'année précédente.', de: 'Im Vorjahr geleistete Stunden.', es: 'Horas trabajadas el año anterior.'},
  'sal.col.next_year.hint':{it: 'Ore pianificate nell\'anno successivo.', en: 'Hours planned in the next year.', fr: 'Heures planifiées l\'année suivante.', de: 'Im Folgejahr geplante Stunden.', es: 'Horas planificadas el año siguiente.'},
  'sal.col.eur_estimate.hint': {it: 'Stima € = ore × tariffa media (quotato/ore quotate).', en: 'Estimate € = hours × blended rate (quoted/quoted hours).', fr: 'Estimation € = heures × tarif moyen (devis/heures devisées).', de: 'Schätzung € = Stunden × Mischsatz (Angebot/angebotene Stunden).', es: 'Estimación € = horas × tarifa media (cotizado/horas cotizadas).'},
  'sal.monte.quoted':      {it: 'Quotate',    en: 'Quoted',     fr: 'Devisé',     de: 'Angeboten',  es: 'Cotizado'},
  'sal.monte.planned':     {it: 'Pianif',     en: 'Planned',    fr: 'Planifié',   de: 'Geplant',    es: 'Planif.'},
  'sal.monte.worked':      {it: 'Lavorate',   en: 'Worked',     fr: 'Travaillé',  de: 'Geleistet',  es: 'Trabajado'},
  'sal.eur.quoted':        {it: 'Quotato',    en: 'Quoted',     fr: 'Devisé',     de: 'Angeboten',  es: 'Cotizado'},
  'sal.eur.accrued':       {it: 'Maturato',   en: 'Accrued',    fr: 'Acquis',     de: 'Aufgelaufen', es: 'Devengado'},
  'sal.legend.title':      {it: 'Legenda',    en: 'Legend',     fr: 'Légende',    de: 'Legende',    es: 'Leyenda'},
  'sal.legend.worked':     {it: 'Lavorato (cumulato)', en: 'Worked (cumulative)', fr: 'Travaillé (cumulé)', de: 'Geleistet (kumuliert)', es: 'Trabajado (acumulado)'},
  'sal.legend.planned':    {it: 'Pianificato (cumulato)', en: 'Planned (cumulative)', fr: 'Planifié (cumulé)', de: 'Geplant (kumuliert)', es: 'Planificado (acumulado)'},
  'sal.legend.overrun':    {it: 'Sforamento (>100%)', en: 'Overrun (>100%)', fr: 'Dépassement (>100%)', de: 'Überschreitung (>100%)', es: 'Exceso (>100%)'},
  'sal.legend.formula':    {it: 'La cella mostra l\'avanzamento cumulativo a fine periodo: ore cumulate ÷ ore quotate.', en: 'The cell shows cumulative progress at end of period: cumulative hours ÷ quoted hours.', fr: 'La cellule montre l\'avancement cumulé en fin de période : heures cumulées ÷ heures devisées.', de: 'Die Zelle zeigt den kumulierten Fortschritt am Periodenende: kumulierte Stunden ÷ angebotene Stunden.', es: 'La celda muestra el avance acumulado al final del período: horas acumuladas ÷ horas cotizadas.'},
```

- [ ] **Step 2: Verifica sintassi JS**

Run: `node -e "require('./app/static/js/i18n.js'); console.log('ok')"`
Se il file non è require-abile (usa `window`), in alternativa verificare con un parse:
Run: `node --check app/static/js/i18n.js`
Expected: nessun errore di sintassi.

- [ ] **Step 3: Commit**

```bash
git add app/static/js/i18n.js
git commit -m "i18n(sal): batch keys (toggle, filters, year cols, legend) in 5 langs"
```

---

## Task 12: UI — filtri reparto/categoria/progetto (item 12)

**Files:**
- Modify: `app/templates/pages/sal.html` (filter bar HTML ~28-50 + JS populate/params)

- [ ] **Step 1: Aggiungere i 3 select alla filter bar**

In `app/templates/pages/sal.html`, dentro la `<div>` filter bar (dopo il blocco "Cliente", riga ~44, prima del label "Solo in allarme"), inserire:

```html
      <div class="form-group" style="min-width:150px;">
        <label class="form-label" style="font-size:11px;" data-i18n="sal.filter.department">Reparto</label>
        <select class="form-select" id="sal-f-dept" onchange="onSalFilterChange()">
          <option value="" data-i18n="sal.opt.all">— tutti —</option>
        </select>
      </div>
      <div class="form-group" style="min-width:170px;">
        <label class="form-label" style="font-size:11px;" data-i18n="sal.filter.category" title="" data-i18n-attr="title">Tipo lavorazione</label>
        <select class="form-select" id="sal-f-category" onchange="onSalFilterChange()">
          <option value="" data-i18n="sal.opt.all">— tutti —</option>
        </select>
      </div>
      <div class="form-group" style="min-width:180px;">
        <label class="form-label" style="font-size:11px;" data-i18n="sal.filter.project">Progetto</label>
        <select class="form-select" id="sal-f-project" onchange="onSalFilterChange()">
          <option value="" data-i18n="sal.opt.all">— tutti —</option>
        </select>
      </div>
```

- [ ] **Step 2: Funzioni di popolamento (ordine P2)**

In `app/templates/pages/sal.html`, nel blocco `<script>`, dopo `_salLoadClients` (riga ~397), aggiungere:

```javascript
// Reparti (sort_order dal server) per il filtro.
async function _salLoadDepartments() {
  const sel = document.getElementById('sal-f-dept');
  try {
    const depts = await api('GET', '/departments/api');
    const cur = sel.value;
    sel.innerHTML = `<option value="">${mfT('sal.opt.all')}</option>` +
      (depts || [])
        .filter(d => d.is_active !== false)
        .map(d => `<option value="${d.id}">${escapeHtml(d.name || '—')}</option>`)
        .join('');
    sel.value = cur;
  } catch (e) { /* silente */ }
}

// Categorie listino (sort_order dal server) per il filtro "tipo lavorazione".
async function _salLoadCategories() {
  const sel = document.getElementById('sal-f-category');
  try {
    const cats = await api('GET', '/pricelist/api/categories');
    const cur = sel.value;
    sel.innerHTML = `<option value="">${mfT('sal.opt.all')}</option>` +
      (cats || [])
        .map(c => `<option value="${c.id}">${escapeHtml(c.name || '—')}</option>`)
        .join('');
    sel.value = cur;
  } catch (e) { /* silente */ }
}

// Progetti (alfabetico per titolo — P2) per il filtro.
async function _salLoadProjects() {
  const sel = document.getElementById('sal-f-project');
  try {
    const prjs = await api('GET', '/projects/api');
    const cur = sel.value;
    sel.innerHTML = `<option value="">${mfT('sal.opt.all')}</option>` +
      (prjs || [])
        .slice()
        .sort((a, b) => (a.title || '').localeCompare(b.title || ''))
        .map(p => `<option value="${p.id}">${escapeHtml(p.title || p.code || '—')}</option>`)
        .join('');
    sel.value = cur;
  } catch (e) { /* silente */ }
}
```

- [ ] **Step 3: Includere i filtri nei params e nel reset**

In `loadSalProjects` (riga ~215), dopo la lettura di `alarmOnly`, aggiungere:

```javascript
  const deptId = document.getElementById('sal-f-dept').value;
  const categoryId = document.getElementById('sal-f-category').value;
  const projectId = document.getElementById('sal-f-project').value;
```

e dopo `if (alarmOnly) params.set('alarm_only', 'true');`:

```javascript
  if (deptId) params.set('department_id', deptId);
  if (categoryId) params.set('category_id', categoryId);
  if (projectId) params.set('project_id', projectId);
```

In `resetSalFilters` (riga ~207), aggiungere prima di `loadSalProjects()`:

```javascript
  document.getElementById('sal-f-dept').value = '';
  document.getElementById('sal-f-category').value = '';
  document.getElementById('sal-f-project').value = '';
```

In `DOMContentLoaded` (riga ~485), dopo `await _salLoadClients();`:

```javascript
  await _salLoadDepartments();
  await _salLoadCategories();
  await _salLoadProjects();
```

- [ ] **Step 4: Riavviare e smoke browser**

Riavviare il server. Aprire `/finance/sal`. Verificare i 3 nuovi select popolati (reparti per sort_order, progetti alfabetici). Selezionare un reparto → la lista si filtra e le metriche di riga sono quelle del reparto. Selezionare una categoria → la lista si filtra (metriche di progetto intere). Reset azzera tutto.

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/sal.html
git commit -m "feat(sal): department/category/project filters with deterministic order"
```

---

## Task 13: UI — toggle Ore/Budget + colonne anno + riga rossa (item 4, 8, 9)

**Files:**
- Modify: `app/templates/pages/sal.html` (header tab, tabella, render)
- Modify: `app/static/css/main.css` (classe `sal-row-overrun`)

- [ ] **Step 1: Aggiungere il toggle Ore/Budget sopra la tabella**

In `app/templates/pages/sal.html`, dentro `#pane-projects`, subito dopo la `</div>` di chiusura della filter bar (riga ~50) e prima di `<div class="table-wrap">`, inserire:

```html
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
      <div class="btn-group" role="group" style="display:inline-flex;border:1px solid var(--border);border-radius:6px;overflow:hidden;">
        <button type="button" id="sal-unit-hours" class="btn btn-sm" onclick="setSalUnit('hours')" data-i18n="sal.unit.hours">Ore</button>
        <button type="button" id="sal-unit-budget" class="btn btn-sm btn-ghost" onclick="setSalUnit('budget')" data-i18n="sal.unit.budget">Budget (€)</button>
      </div>
    </div>
```

- [ ] **Step 2: Aggiornare gli header della tabella**

Sostituire il `<thead>` (righe 54-64) con (aggiunge colonne anno; "Monte" e "%" restano ma con id per relabel):

```html
        <thead>
          <tr>
            <th style="min-width:140px;" data-i18n="col.client">Cliente</th>
            <th style="min-width:240px;">Progetto</th>
            <th style="min-width:160px;">Quotazioni</th>
            <th style="min-width:220px;" id="sal-th-monte"><span data-i18n="sal.unit.hours">Ore</span></th>
            <th style="min-width:180px;" data-i18n="col.progress">% Avanzamento</th>
            <th style="width:90px;text-align:right;" id="sal-th-prevyear" data-i18n="sal.col.prev_year">Anno prec.</th>
            <th style="width:90px;text-align:right;" id="sal-th-nextyear" data-i18n="sal.col.next_year">Anno succ.</th>
            <th style="width:90px;text-align:center;" data-i18n="sal.col.alarm">Allarme</th>
            <th style="width:60px;text-align:right;">Job</th>
          </tr>
        </thead>
```

(Il `colspan` del placeholder/empty row passa da 7 a 9: aggiornare le 2 occorrenze `colspan="7"` → `colspan="9"` nel template e in `renderSalProjects` l'`<td colspan="7"` → `colspan="9"`, e in `loadSalProjects` l'errore `colspan="7"` → `colspan="9"`. Anche il drill-down `cell.colSpan = 7` → `9`.)

- [ ] **Step 3: Stato unità + helper di formato**

Nel blocco `<script>`, dopo le variabili `let _salProjects...` (riga ~111), aggiungere:

```javascript
let _salUnit = (localStorage.getItem('sal_unit') === 'budget') ? 'budget' : 'hours';

function setSalUnit(u) {
  _salUnit = (u === 'budget') ? 'budget' : 'hours';
  localStorage.setItem('sal_unit', _salUnit);
  // Aggiorna stile bottoni.
  const hb = document.getElementById('sal-unit-hours');
  const bb = document.getElementById('sal-unit-budget');
  if (hb && bb) {
    hb.className = 'btn btn-sm' + (_salUnit === 'hours' ? '' : ' btn-ghost');
    bb.className = 'btn btn-sm' + (_salUnit === 'budget' ? '' : ' btn-ghost');
  }
  // Aggiorna label header "Monte".
  const th = document.getElementById('sal-th-monte');
  if (th) th.innerHTML = `<span>${_salUnit === 'budget' ? mfT('sal.unit.budget') : mfT('sal.unit.hours')}</span>`;
  renderSalProjects();
}
```

- [ ] **Step 4: Render colonne in base all'unità + riga rossa**

Sostituire `renderSalProjects` (righe ~240-264) con:

```javascript
function renderSalProjects() {
  const tbody = document.getElementById('sal-projects-tbody');
  if (!_salProjects.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="text-muted" style="text-align:center;padding:24px;">Nessun progetto corrisponde ai filtri</td></tr>';
    return;
  }
  const budget = (_salUnit === 'budget');
  tbody.innerHTML = _salProjects.map(function(r) {
    const quotes = (r.quotes || []).map(function(qt) {
      const lbl = qt.number + (qt.title ? ' · ' + qt.title : '');
      return `<span class="badge" title="${escapeHtml(lbl)}" style="font-size:10px;margin:1px 2px;">${escapeHtml(qt.number || '—')}</span>`;
    }).join('');
    const monte = budget
      ? _salMonteEur(r.quoted_eur, r.accrued_eur)
      : _salMonteOre(r.quoted, r.planned, r.worked);
    const pct = budget ? (r.pct_eur * 100) : (r.pct * 100);
    const prev = budget ? _salFmtEur(r.prev_year_eur) : _salFmtHours(r.prev_year);
    const next = budget ? _salFmtEur(r.next_year_eur) : _salFmtHours(r.next_year);
    const overrunCls = (r.alarm === 'red') ? ' sal-row-overrun' : '';
    return `<tr class="sal-prj-row${overrunCls}" data-project-id="${r.id}" style="cursor:pointer;" onclick="toggleSalDetail(${r.id})">
      <td class="text-sm">${escapeHtml(r.client || '—')}</td>
      <td>
        <div style="font-weight:500;">${escapeHtml(r.title || '—')}</div>
        <div class="mono" style="font-size:11px;color:var(--text3);margin-top:2px;">${escapeHtml(r.code || '')}</div>
      </td>
      <td>${quotes || '<span class="text-muted">—</span>'}</td>
      <td>${monte}</td>
      <td>${_salBar(pct)}</td>
      <td style="text-align:right;" class="mono" title="${escapeHtml(mfT(budget ? 'sal.col.eur_estimate.hint' : 'sal.col.prev_year.hint'))}">${prev}</td>
      <td style="text-align:right;" class="mono" title="${escapeHtml(mfT(budget ? 'sal.col.eur_estimate.hint' : 'sal.col.next_year.hint'))}">${next}</td>
      <td style="text-align:center;">${_salAlarmBadge(r.alarm)}</td>
      <td style="text-align:right;" class="mono">${r.job_count}</td>
    </tr>`;
  }).join('');
}

// Cella monte in euro: Quotato / Maturato.
function _salMonteEur(quotedEur, accruedEur) {
  return `<div style="font-size:12px;line-height:1.5;">
    <span class="text-muted">${mfT('sal.eur.quoted')}</span> ${_salFmtEur(quotedEur)} ·
    <span class="text-muted">${mfT('sal.eur.accrued')}</span> ${_salFmtEur(accruedEur)}
  </div>`;
}
```

In `loadSalProjects` aggiornare il colspan dell'errore: `colspan="7"` → `colspan="9"`. In `toggleSalDetail` aggiornare `cell.colSpan = 7;` → `cell.colSpan = 9;`.

In `setSalUnit` la chiamata finale `renderSalProjects()` re-renderizza; chiamare `setSalUnit(_salUnit)` una volta dentro `DOMContentLoaded` (dopo il load) per impostare lo stato iniziale dei bottoni/header.

- [ ] **Step 5: CSS riga rossa**

In `app/static/css/main.css`, in fondo, aggiungere:

```css
/* SAL — riga progetto in sforamento (ore o budget oltre il quotato). */
.sal-prj-row.sal-row-overrun > td {
  background: rgba(239, 68, 68, 0.10);
}
.sal-prj-row.sal-row-overrun:hover > td {
  background: rgba(239, 68, 68, 0.16);
}
```

- [ ] **Step 6: Riavviare e smoke browser**

Riavviare il server. `/finance/sal`: toggle Ore↔Budget cambia la colonna monte (ore vs €), la % (avanzamento vs pct_eur) e le colonne anno (ore vs €-stima). Un progetto in sforamento ha la riga rossa. Tooltip sulle colonne anno corretti.

- [ ] **Step 7: Commit**

```bash
git add app/templates/pages/sal.html app/static/css/main.css
git commit -m "feat(sal): ore/budget toggle + prev/next year columns + overrun red row"
```

---

## Task 14: UI — matrix colori passato/futuro + legenda (item 5, 6)

**Files:**
- Modify: `app/templates/pages/sal.html` (legenda HTML ~90-92, `_salMatrixCell` ~410-426)

- [ ] **Step 1: Sostituire la legenda piatta con un box**

Sostituire il blocco `form-hint` (righe 90-92):

```html
      <div class="form-hint" style="padding-bottom:10px;">
        Cella = avanzamento <strong>cumulativo</strong> a fine periodo (ore lavorate cumulate / ore quotate).
      </div>
```

con:

```html
      <div id="sal-matrix-legend" style="flex-basis:100%;margin-top:4px;">
        <div style="display:flex;flex-wrap:wrap;align-items:center;gap:14px;padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg2,#1e2030);font-size:11px;">
          <strong style="text-transform:uppercase;letter-spacing:0.04em;color:var(--text2);" data-i18n="sal.legend.title">Legenda</strong>
          <span style="display:inline-flex;align-items:center;gap:6px;">
            <span style="width:14px;height:14px;border-radius:3px;background:rgba(98,114,245,0.65);display:inline-block;"></span>
            <span data-i18n="sal.legend.worked">Lavorato (cumulato)</span>
          </span>
          <span style="display:inline-flex;align-items:center;gap:6px;">
            <span style="width:14px;height:14px;border-radius:3px;background:rgba(46,196,182,0.45);border:1px dashed rgba(46,196,182,0.9);display:inline-block;"></span>
            <span data-i18n="sal.legend.planned">Pianificato (cumulato)</span>
          </span>
          <span style="display:inline-flex;align-items:center;gap:6px;">
            <span style="width:14px;height:14px;border-radius:3px;background:rgba(239,68,68,0.5);display:inline-block;"></span>
            <span data-i18n="sal.legend.overrun">Sforamento (&gt;100%)</span>
          </span>
          <span class="text-muted" style="flex-basis:100%;" data-i18n="sal.legend.formula">La cella mostra l'avanzamento cumulativo a fine periodo: ore cumulate ÷ ore quotate.</span>
        </div>
      </div>
```

- [ ] **Step 2: Colorare la cella in base a `basis`**

Sostituire `_salMatrixCell` (righe 410-426):

```javascript
function _salMatrixCell(c) {
  // Cella calendario: % cumulativa con heat-color. basis 'worked' = indaco;
  // basis 'planned' = teal tratteggiato (previsione); >100% = rosso.
  const pct = c.pct || 0;
  if (pct <= 0 && (c.worked_cum || 0) <= 0) {
    return '<td style="text-align:center;color:var(--text3);font-size:11px;">—</td>';
  }
  const pctInt = Math.round(pct * 100);
  const over = pct > 1.0;
  const planned = (c.basis === 'planned');
  const alpha = Math.min(0.85, Math.max(0.08, pct * 0.7));
  let bg, extra = '';
  if (over) {
    bg = 'rgba(239,68,68,' + Math.min(0.5, alpha) + ')';
  } else if (planned) {
    bg = 'rgba(46,196,182,' + Math.min(0.55, alpha) + ')';
    extra = 'border:1px dashed rgba(46,196,182,0.7);';
  } else {
    bg = 'rgba(98,114,245,' + alpha + ')';
  }
  const fg = (pct >= 0.55 || over) ? '#fff' : 'var(--text)';
  const basisLbl = planned ? mfT('sal.legend.planned') : mfT('sal.legend.worked');
  const title = _salFmtHours(c.worked_cum) + ' · ' + basisLbl;
  return '<td style="text-align:center;background:' + bg + ';color:' + fg + ';' + extra +
    'font-size:11px;font-weight:600;min-width:52px;" title="' + escapeHtml(title) + '">' +
    pctInt + '%</td>';
}
```

- [ ] **Step 3: Riavviare e smoke browser**

Riavviare il server. `/finance/sal` → tab Temporale. Le celle dei mesi passati sono indaco; dei mesi correnti/futuri teal tratteggiate; >100% rosse. La legenda è un box con swatch colorati. Tooltip cella mostra ore + base (Lavorato/Pianificato).

- [ ] **Step 4: Commit**

```bash
git add app/templates/pages/sal.html
git commit -m "feat(sal): matrix past/future cell colors + redesigned legend"
```

---

## Task 15: Suite test completa + smoke E2E browser

**Files:** (nessuna modifica codice salvo fix emersi)

- [ ] **Step 1: Eseguire l'intera suite pytest**

Run: `python -m pytest -q`
Expected: tutti i test passano (baseline 790 + nuovi). Se qualcosa fallisce, correggere prima di proseguire (systematic-debugging).

- [ ] **Step 2: Smoke E2E browser — SAL**

Con server attivo e tunnel/localhost, via Playwright:
- `/finance/sal`: toggle Ore/Budget; verificare colonne anno; riga rossa su progetto sforato; filtri reparto/categoria/progetto popolati e funzionanti; tab Temporale con celle passato/futuro colorate diversamente + legenda box.

- [ ] **Step 3: Smoke E2E browser — deliverables**

- `/planning/?view=deliverables`: editor tech-spec → select audio preset non tagliato; cambio codec ProRes → container = QuickTime; item ProRes precedentemente senza container ora popolato.

- [ ] **Step 4: Smoke i18n**

Cambiare lingua (menu lingue → English): verificare che toggle, filtri, header colonne anno, legenda, label monte siano tradotti (nessuna chiave grezza `sal.*` visibile).

- [ ] **Step 5: (Se emergono fix) commit mirati**

```bash
git add -A
git commit -m "fix(sal): smoke E2E adjustments"
```

---

## Task 16: Bump versione + CHANGELOG + push + export ZIP

**Files:**
- Modify: `app/main.py` (versione), `CHANGELOG.md`
- Modify: `docs/STATO.md` (versione + sezione in corso + prossimo step)

- [ ] **Step 1: Bump versione**

In `app/main.py` aggiornare la versione corrente (da `3.5.0-alpha.172.218` a `3.5.0-alpha.172.219`). Verificare anche eventuale costante versione usata da `/health`.

- [ ] **Step 2: CHANGELOG**

In `CHANGELOG.md`, in cima, aggiungere la voce `3.5.0-alpha.172.219` con il riepilogo: fix deliverables (auto-set container ProRes, select audio preset, backfill) + SAL (toggle ore/budget, colonne anno N±1, riga rossa, filtri reparto/categoria/progetto, matrix passato/futuro + colori, legenda) + policy i18n/ordine-menu.

- [ ] **Step 3: STATO.md**

Aggiornare `docs/STATO.md`: versione corrente, sezione "in corso" (chiusa), "prossimo step".

- [ ] **Step 4: Export ZIP DB**

Generare l'export ZIP importabile in `docs/` (formato `/settings > Dati`) come da policy push.

- [ ] **Step 5: Commit + push**

```bash
git add app/main.py CHANGELOG.md docs/STATO.md docs/
git commit -m "chore: bump 3.5.0-alpha.172.219 - batch SAL + fix deliverables"
git push
```

Expected: push ok sul remoto.

---

## Self-review (eseguita)

**Spec coverage:**
- Bug 1 → Task 2-4. Bug 2 → Task 2-4 + Task 6. Bug 3 → Task 5.
- Item 4 (colonne anno) → Task 8 (helper) + Task 10 (API) + Task 13 (UI).
- Item 5 (matrix passato/futuro) → Task 9 (service) + Task 14 (UI colori).
- Item 6 (legenda) → Task 14.
- Item 7 (i18n) → P1 + Task 11 + verifiche Task 15. Item 10 (ordine menu) → P2 + Task 1 + Task 12.
- Item 8 (riga rossa) → Task 13.
- Item 9 (budget) → Task 7 (service) + Task 10 (API) + Task 13 (UI toggle).
- Item 12 (filtri) → Task 10 (API) + Task 12 (UI).

**Placeholder scan:** nessun TBD/TODO; ogni step di codice ha codice reale. L'unica nota "adattare gli helper `_setup_*`" in Task 10 rimanda esplicitamente al pattern già presente nel file di test — non è un placeholder di codice produttivo.

**Type consistency:** `worked_cum`/`basis`/`pct` coerenti fra `matrix_metrics` (Task 9) e `_salMatrixCell` (Task 14). `quoted_eur`/`accrued_eur`/`pct_eur`/`prev_year`/`next_year`/`*_eur` coerenti fra service (Task 7), endpoint (Task 10) e UI (Task 13). `preferred_container_id` coerente fra endpoint (Task 3) e JS (Task 4). `_dsmLastChanged` dichiarata (Task 4 Step 3) e usata (Step 2/4).
