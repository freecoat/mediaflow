# Editor specs deliverable vincolato al tipo file — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vincolare i campi spec di un deliverable al suo tipo file: auto-popolare le specs dal `delivery_item_id`, nascondere i campi non pertinenti (per `media_kind`/package), e bloccare il save quando le combinazioni sono incoerenti (regole ERROR), riusando `delivery_item_validation.py` come single source.

**Architecture:** Funzione pura `field_relevance` + le 9 regole `validate_delivery_item` esistenti, esposte da un endpoint `spec-schema` (read-only) che l'editor consuma per hide/disable + findings live. Enforcement ERROR (HTTP 422) sul `PUT /delivery-items/api/{id}` (edit manuale, planning + capitolato; AI/import restano warn perché passano da un altro path). Auto-populate del modal planning dal `delivery_item_id`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + SQLite, Jinja2, vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-06-03-deliverable-spec-constraints-design.md`

**Refinement D4 (scoperto in planning):** l'editor specs planning (`dsmSaveStructured`) scrive sul `PUT /delivery-items/api/{id}` — lo stesso endpoint usato dall'editor item del capitolato. Quindi l'enforcement ERROR sta su QUEL endpoint e vale per ogni **edit manuale** (planning + capitolato). AI/import NON usano questo endpoint (passano da `delivery_items_parser.materialize_items`), quindi restano warn-only senza modifiche — coerente con lo spirito di D4 ("AI propone, utente dispone").

**Convenzioni:** Form-based API, tenant scope, commit a fine versione. Severità dalle regole esistenti as-is (NB: R3 ProRes→QuickTime è **warning**, non error; non la ri-classifico — se Matteo vuole bloccarla, è un cambio di 1 riga, fuori scope).

---

## File Structure
- `app/services/delivery_item_validation.py` — aggiunge `field_relevance(...)` (pura) + helper `has_audio_tracks`.
- `app/routers/delivery_items.py` — endpoint `POST /delivery-items/api/spec-schema` + enforcement ERROR in `update_item`.
- `app/templates/pages/planning.html` — `dsmOpen` auto-populate + `dsmRenderStructured` field-gating/findings.
- `tests/test_spec_constraints.py` — nuovo (field_relevance + endpoint + enforcement).

---

## Task 1: `field_relevance` (pura) — TDD

**Files:**
- Modify: `app/services/delivery_item_validation.py` (append function)
- Test: `tests/test_spec_constraints.py` (new)

- [ ] **Step 1: Test (fallisce)**

Create `tests/test_spec_constraints.py`:
```python
"""Vincoli specs per tipo file (α.172.183): field_relevance + coerenza."""
from app.services import delivery_item_validation as dv


def test_audio_container_hides_video_and_color():
    g = dv.field_relevance(media_kind="audio", has_package=False,
                           video_codec_family=None, has_audio=True)
    assert g["video"] == "hide"
    assert g["color"] == "hide"
    assert g["audio"] == "show"


def test_image_seq_hides_audio():
    g = dv.field_relevance(media_kind="image_seq", has_package=False,
                           video_codec_family="jpeg2000", has_audio=False)
    assert g["audio"] == "hide"
    assert g["video"] == "show"


def test_video_with_audio_shows_both():
    g = dv.field_relevance(media_kind="video", has_package=False,
                           video_codec_family="prores", has_audio=True)
    assert g["video"] == "show"
    assert g["audio"] == "show"


def test_video_without_audio_hides_audio():
    g = dv.field_relevance(media_kind="video", has_package=False,
                           video_codec_family="prores", has_audio=False)
    assert g["audio"] == "hide"


def test_no_package_hides_package():
    g = dv.field_relevance(media_kind="video", has_package=False,
                           video_codec_family="prores", has_audio=True)
    assert g["package"] == "hide"


def test_with_package_shows_package():
    g = dv.field_relevance(media_kind="video", has_package=True,
                           video_codec_family="jpeg2000", has_audio=False)
    assert g["package"] == "show"


def test_unknown_media_kind_shows_all():
    g = dv.field_relevance(media_kind=None, has_package=False,
                           video_codec_family=None, has_audio=False)
    assert all(v == "show" for k, v in g.items() if k in ("video", "audio", "color"))
```

- [ ] **Step 2: FAIL** — `./.venv/Scripts/python.exe -m pytest tests/test_spec_constraints.py -v` → AttributeError field_relevance.

- [ ] **Step 3: Implementa** — in `app/services/delivery_item_validation.py`, in fondo al file (dopo `validate_summary`):
```python
# v3.5.0-alpha.172.183 — Pertinenza dei campi spec per tipo file. Pura, niente DB.
# Gruppi: video, audio, subtitle, package, color, timecode → "show"|"hide".
_RELEVANCE_GROUPS = ("video", "audio", "subtitle", "package", "color", "timecode")


def field_relevance(*, media_kind, has_package, video_codec_family=None, has_audio=False) -> dict:
    """Quali gruppi di campi sono pertinenti per il tipo file.

    media_kind: "video"|"audio"|"image_seq"|"mixed"|None (da Container.media_kind).
    has_package/has_audio: bool. video_codec_family: stringa o None.
    Default difensivo: media_kind sconosciuto/None → tutto "show" (non nascondere
    se non sappiamo). subtitle/timecode sempre "show".
    """
    mk = (media_kind or "").strip().lower()
    g = {k: "show" for k in _RELEVANCE_GROUPS}
    if mk == "audio":
        g["video"] = "hide"
        g["color"] = "hide"
        g["audio"] = "show"
    elif mk == "image_seq":
        g["audio"] = "hide"
        g["video"] = "show"
        g["color"] = "show"
    elif mk in ("video", "mixed"):
        g["video"] = "show"
        g["color"] = "show"
        g["audio"] = "show" if has_audio else "hide"
    # mk sconosciuto/None → tutto show (default difensivo)
    g["package"] = "show" if has_package else "hide"
    return g
```

- [ ] **Step 4: PASS** — `./.venv/Scripts/python.exe -m pytest tests/test_spec_constraints.py -v`.

- [ ] **Step 5: Commit**
```bash
git add app/services/delivery_item_validation.py tests/test_spec_constraints.py
git commit -m "feat(specs): field_relevance per tipo file (pura, single-source)"
```

---

## Task 2: Endpoint `spec-schema` (groups + findings) — TDD

**Files:**
- Modify: `app/routers/delivery_items.py` (new endpoint; imports `validate_delivery_item`, `field_relevance`)
- Test: `tests/test_spec_constraints.py` (extend)

- [ ] **Step 1: Test (fallisce)** — append a `tests/test_spec_constraints.py`. Riusa il fixture `client_admin` (replica da `tests/test_naming_settings.py`/`test_billable_hours_mode.py`; serve Tenant seed + role admin). Servono righe taxonomy reali: il test crea Container audio + Container MXF + VideoCodec ProRes via ORM nella sessione del client.
```python
import pytest

@pytest.fixture
def taxo(client_admin):
    """Crea taxonomy minima: container audio, container mxf, container quicktime,
    codec prores, codec j2k. Ritorna dict di id."""
    s = client_admin.session  # la sessione esposta dal fixture client_admin
    from app.models.models import Container, VideoCodec
    c_audio = Container(tenant_id=1, name="WAV", media_kind="audio")
    c_mxf = Container(tenant_id=1, name="MXF OP1a", media_kind="video", op_pattern="op1a")
    c_mov = Container(tenant_id=1, name="QuickTime", media_kind="video")
    vc_prores = VideoCodec(tenant_id=1, name="ProRes 4444", family="ProRes")
    vc_j2k = VideoCodec(tenant_id=1, name="JPEG2000", family="JPEG2000")
    s.add_all([c_audio, c_mxf, c_mov, vc_prores, vc_j2k]); s.commit()
    for o in (c_audio, c_mxf, c_mov, vc_prores, vc_j2k): s.refresh(o)
    return {"audio": c_audio.id, "mxf": c_mxf.id, "mov": c_mov.id,
            "prores": vc_prores.id, "j2k": vc_j2k.id}


def test_spec_schema_audio_hides_video(client_admin, taxo):
    r = client_admin.post("/delivery-items/api/spec-schema",
                          data={"container_id": taxo["audio"]})
    assert r.status_code == 200
    body = r.json()
    assert body["groups"]["video"] == "hide"


def test_spec_schema_prores_in_mxf_warns(client_admin, taxo):
    # ProRes in MXF → R3 warning (non error)
    r = client_admin.post("/delivery-items/api/spec-schema",
                          data={"container_id": taxo["mxf"], "video_codec_id": taxo["prores"]})
    assert r.status_code == 200
    codes = [f["code"] for f in r.json()["findings"]]
    assert "PRORES_PREFERS_QUICKTIME" in codes


def test_spec_schema_j2k_in_mov_errors(client_admin, taxo):
    # J2K fuori MXF → R4 error
    r = client_admin.post("/delivery-items/api/spec-schema",
                          data={"container_id": taxo["mov"], "video_codec_id": taxo["j2k"]})
    assert r.status_code == 200
    findings = r.json()["findings"]
    assert any(f["code"] == "J2K_REQUIRES_MXF" and f["severity"] == "error" for f in findings)
```
> NB fixture: verifica i nomi reali di Container/VideoCodec e dei loro campi (`media_kind`, `family`, `op_pattern`) in models.py (~772-810) e adatta. Se `client_admin` non espone `.session`, adattalo (il fixture in test_billable_hours_mode espone la sessione — replica quel meccanismo).

- [ ] **Step 2: FAIL** — `./.venv/Scripts/python.exe -m pytest tests/test_spec_constraints.py -k spec_schema -v` → 404.

- [ ] **Step 3: Implementa endpoint** — in `app/routers/delivery_items.py`, aggiungi (dopo `update_item` o vicino agli endpoint taxonomy). Verifica import in cima: `Form`, `Optional`, `HTTPException`, `Depends`, `Session`, `get_db`, `current_tenant_id`, `DeliveryItem`, `Container`, `VideoCodec` (alcuni già presenti). 
```python
@router.post("/delivery-items/api/spec-schema")
async def spec_schema(
    container_id: Optional[int] = Form(None),
    package_id: Optional[int] = Form(None),
    video_codec_id: Optional[int] = Form(None),
    has_audio: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Read-only: dato un combo (container/package/codec), ritorna i gruppi di
    campi pertinenti + i findings di coerenza (riusa delivery_item_validation).
    Usato dall'editor specs per hide/disable + warning live."""
    from app.services.delivery_item_validation import field_relevance, validate_delivery_item
    from app.models.models import Container as _C, VideoCodec as _VC
    cont = db.get(_C, container_id) if container_id else None
    vc = db.get(_VC, video_codec_id) if video_codec_id else None
    media_kind = getattr(cont, "media_kind", None)
    vc_family = getattr(vc, "family", None)
    groups = field_relevance(
        media_kind=media_kind, has_package=bool(package_id),
        video_codec_family=vc_family, has_audio=has_audio,
    )
    # findings: costruisci un DeliveryItem transiente (NON aggiunto alla sessione)
    transient = DeliveryItem(
        tenant_id=current_tenant_id(), container_id=container_id,
        package_id=package_id, video_codec_id=video_codec_id,
    )
    findings = validate_delivery_item(db, transient)
    return {"groups": groups, "findings": findings}
```
> NB: `validate_delivery_item(db, transient)` usa `db.get(...)` sugli id e `item.id` (None→0 audio tracks). Un DeliveryItem transiente con soli FK id funziona. Se il costruttore richiede campi NOT NULL aggiuntivi, passali con valori innocui (verifica `class DeliveryItem` colonne non-nullable, es. `name`, `delivery_template_id` — se obbligatori, passa `name=""`, e per `delivery_template_id` usa un valore fittizio o rendi la costruzione tollerante; in alternativa valida via un dict-adapter — vedi fallback sotto).
> FALLBACK se il costruttore transiente è scomodo (FK NOT NULL): non costruire l'ORM; replica la sola risoluzione necessaria passando gli oggetti già risolti. Ma preferisci il transiente se `DeliveryItem(...)` con soli questi kwargs non solleva (la maggior parte dei campi è nullable). Testa subito con lo Step 4.

- [ ] **Step 4: PASS** — `./.venv/Scripts/python.exe -m pytest tests/test_spec_constraints.py -k spec_schema -v`.

- [ ] **Step 5: Commit**
```bash
git add app/routers/delivery_items.py tests/test_spec_constraints.py
git commit -m "feat(specs): endpoint spec-schema (groups + coerenza findings)"
```

---

## Task 3: Enforcement ERROR su `update_item` — TDD

**Files:**
- Modify: `app/routers/delivery_items.py` (`update_item`, prima di `db.commit()` ~riga 346) + signature (`enforce_coherence` Form)
- Test: `tests/test_spec_constraints.py` (extend)

- [ ] **Step 1: Test (fallisce)** — append:
```python
@pytest.fixture
def prores_item(client_admin, taxo):
    """Un DeliveryItem valido (ProRes in QuickTime) già salvato. Ritorna iid."""
    s = client_admin.session
    from app.models.models import DeliveryItem, DeliveryTemplate
    tpl = DeliveryTemplate(tenant_id=1, code="T1", name="Test")
    s.add(tpl); s.commit(); s.refresh(tpl)
    it = DeliveryItem(tenant_id=1, delivery_template_id=tpl.id, name="Master",
                      container_id=taxo["mov"], video_codec_id=taxo["prores"])
    s.add(it); s.commit(); s.refresh(it)
    return it.id


def test_update_item_blocks_error_combo(client_admin, taxo, prores_item):
    # cambio container a QuickTime + codec J2K → R4 error → 422
    r = client_admin.put(f"/delivery-items/api/{prores_item}",
                         data={"video_codec_id": taxo["j2k"], "container_id": taxo["mov"]})
    assert r.status_code == 422
    body = r.json()
    # il detail contiene i findings error
    assert "J2K_REQUIRES_MXF" in str(body)


def test_update_item_allows_valid_combo(client_admin, taxo, prores_item):
    # J2K in MXF → valido → 200
    r = client_admin.put(f"/delivery-items/api/{prores_item}",
                         data={"video_codec_id": taxo["j2k"], "container_id": taxo["mxf"]})
    assert r.status_code == 200


def test_update_item_warning_does_not_block(client_admin, taxo, prores_item):
    # ProRes in MXF → R3 warning → 200 (non blocca)
    r = client_admin.put(f"/delivery-items/api/{prores_item}",
                         data={"video_codec_id": taxo["prores"], "container_id": taxo["mxf"]})
    assert r.status_code == 200
```
> NB adatta i campi obbligatori di DeliveryTemplate/DeliveryItem ai reali (leggi models.py).

- [ ] **Step 2: FAIL** — `./.venv/Scripts/python.exe -m pytest tests/test_spec_constraints.py -k update_item -v` → i due test "blocks" falliscono (oggi 200).

- [ ] **Step 3: Implementa enforcement** — in `app/routers/delivery_items.py`:
1. Aggiungi alla firma di `update_item` (dopo `audio_config_preset_id`, prima di `db: Session`):
```python
    enforce_coherence: bool = Form(True),
```
2. Subito PRIMA di `db.commit()` (~riga 346), inserisci:
```python
    # v3.5.0-alpha.172.183 — enforcement coerenza: edit manuale (planning/capitolato)
    # non può salvare combinazioni ERROR. AI/import non passano da qui (materialize_items)
    # → restano warn-only. WARNING non bloccano.
    if enforce_coherence:
        from app.services.delivery_item_validation import validate_delivery_item
        _errs = [f for f in validate_delivery_item(db, it) if f.get("severity") == "error"]
        if _errs:
            raise HTTPException(422, detail={"code": "SPEC_COHERENCE_ERROR", "findings": _errs})
```
(Le modifiche a `it` sono già applicate in memoria a questo punto; `validate_delivery_item` usa `db.get` sugli FK aggiornati. Il raise PRIMA del commit lascia la sessione senza commit → nessuna scrittura.)

- [ ] **Step 4: PASS** — `./.venv/Scripts/python.exe -m pytest tests/test_spec_constraints.py -v` (tutti).

- [ ] **Step 5: Commit**
```bash
git add app/routers/delivery_items.py tests/test_spec_constraints.py
git commit -m "feat(specs): enforcement ERROR coerenza su update_item (manual edit blocca)"
```

---

## Task 4: UI editor — field-gating + findings + auto-populate

**Files:**
- Modify: `app/templates/pages/planning.html` (`dsmOpen`, `dsmRenderStructured`, e i select container/codec/package)

> PRIMA: leggi in `planning.html` le funzioni `dsmOpen`, `dsmCapItemChange`, `dsmRenderStructured` (~2300-2460) e `dsmSaveStructured` (~2462+). Verifica come il payload del deliverable espone `delivery_item_id` (serializer `/jobs/api/deliverables/list` o `/jobs/api/deliverables/{id}`). Se `delivery_item_id` NON è nel payload del singolo deliverable, aggiungilo al serializer in `app/routers/jobs.py` (`_serialize_deliverable`) — è un dato già presente sul modello.

- [ ] **Step 1: Auto-populate (Obs 1)** — in `dsmOpen(did)`, dopo aver caricato il deliverable: se `deliverable.delivery_item_id` è valorizzato e il deliverable è in modalità non-linkata di default, pre-seleziona quell'item e renderizza strutturato. Concretamente, replica ciò che fa `dsmCapItemChange` ma SENZA il PUT (il link esiste già): carica `api('GET', '/delivery-items/api/' + iid)` + `_dsmLoadTaxonomy()`, set `_dsmDeliveryItemId = iid`, `_dsmStructured = true`, mostra `dsm-cap-unlink`, chiama `dsmRenderStructured(item, tax)`. Esempio (adatta ai nomi reali letti):
```javascript
// in dsmOpen, dopo aver ottenuto l'oggetto deliverable (es. `d`):
if (d.delivery_item_id) {
  try {
    const [item, tax] = await Promise.all([
      api('GET', '/delivery-items/api/' + d.delivery_item_id),
      _dsmLoadTaxonomy(),
    ]);
    _dsmStructured = true; _dsmDeliveryItemId = d.delivery_item_id;
    const pf = document.getElementById('dsm-prefill-bar'); if (pf) pf.style.display = 'none';
    const ul = document.getElementById('dsm-cap-unlink'); if (ul) ul.style.display = '';
    dsmRenderStructured(item, tax);
    return; // salta il path legacy JSON
  } catch (e) { /* fallback al path legacy sotto */ }
}
```

- [ ] **Step 2: Field-gating + findings in `dsmRenderStructured`** — dopo aver costruito il form, aggiungi una funzione che chiama `spec-schema` e applica i gruppi + mostra findings. Aggiungi un contenitore findings nel banner e applica hide ai gruppi. I campi del form vanno raggruppati per data-attribute così il gating può nasconderli. Concretamente:
  1. Marca i wrapper `<div>` dei campi con `data-spec-group`: video → container/vcodec/res/bitdepth/chroma/fr/aspect/scan; color → hdr/color/cprim; package → package; audio → (eventuale sezione audio); subtitle → subfmt/sublang. (Aggiungi `data-spec-group="video"` ecc. ai div esistenti.)
  2. Aggiungi `<div id="dsm-spec-findings"></div>` nel banner.
  3. Funzione:
```javascript
async function dsmApplySpecSchema() {
  const cont = document.getElementById('dsm-s-container');
  const vc = document.getElementById('dsm-s-vcodec');
  const pkg = document.getElementById('dsm-s-package');
  if (!cont) return;
  const fd = new FormData();
  if (cont.value) fd.append('container_id', cont.value);
  if (pkg && pkg.value) fd.append('package_id', pkg.value);
  if (vc && vc.value) fd.append('video_codec_id', vc.value);
  let data;
  try {
    const r = await fetch('/delivery-items/api/spec-schema', {method:'POST', body:fd, credentials:'same-origin'});
    data = await r.json();
  } catch(e){ return; }
  // hide/show gruppi
  const groups = data.groups || {};
  document.querySelectorAll('#dsm-blocks-host [data-spec-group]').forEach(el => {
    const grp = el.getAttribute('data-spec-group');
    el.style.display = (groups[grp] === 'hide') ? 'none' : '';
  });
  // findings
  const fh = document.getElementById('dsm-spec-findings');
  if (fh) {
    fh.innerHTML = '';
    (data.findings || []).forEach(f => {
      const d = document.createElement('div');
      d.style.cssText = 'font-size:11px;margin-top:4px;color:' + (f.severity==='error' ? 'var(--rose)' : 'var(--amber, #d99a00)');
      d.textContent = (f.severity === 'error' ? '⛔ ' : '⚠ ') + f.message;
      fh.appendChild(d);
    });
  }
}
```
  4. Chiama `dsmApplySpecSchema()` alla fine di `dsmRenderStructured`, e su `change` di container/vcodec/package:
```javascript
['dsm-s-container','dsm-s-vcodec','dsm-s-package'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('change', dsmApplySpecSchema);
});
```
  (Nomi dato via `textContent`; `innerHTML=''` solo clear. `f.message` via textContent.)

- [ ] **Step 3: Save 422 handling in `dsmSaveStructured`** — quando il PUT `/delivery-items/api/{id}` ritorna 422 con `detail.code === 'SPEC_COHERENCE_ERROR'`, mostra i findings (toast o nel container) e NON chiudere. Leggi la struttura attuale di `dsmSaveStructured` e aggiungi:
```javascript
// dopo il fetch PUT:
if (r.status === 422) {
  const e = await r.json().catch(()=>({}));
  const fnd = (e.detail && e.detail.findings) || [];
  toast('Specs incoerenti: ' + fnd.map(x=>x.message).join(' · '), 'error', 6000);
  return;
}
```

- [ ] **Step 4: Verifiche statiche**
- `./.venv/Scripts/python.exe -c "from jinja2 import Environment, FileSystemLoader as L; e=Environment(loader=L('app/templates')); e.get_template('pages/planning.html'); print('JINJA OK')"`
- `./.venv/Scripts/python.exe -c "import app.main; print('import OK')"`
- Grep consistenza: `dsmApplySpecSchema` definita+chiamata; `data-spec-group` presente sui wrapper; id coerenti.

- [ ] **Step 5: Commit**
```bash
git add app/templates/pages/planning.html app/routers/jobs.py
git commit -m "feat(specs-ui): auto-populate da delivery_item_id + field-gating per tipo + findings"
```
(includi jobs.py solo se hai aggiunto delivery_item_id al serializer)

---

## Task 5: Regressione + bump + CHANGELOG/STATO

**Files:** `app/main.py`, `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: Suite** — `./.venv/Scripts/python.exe -m pytest -q`. Tutti pass. Se rosso → investiga, no bump.
- [ ] **Step 2: Bump** — `app/main.py` versione `3.5.0-alpha.172.182` → `3.5.0-alpha.172.183`.
- [ ] **Step 3: CHANGELOG** — entry `v3.5.0-alpha.172.183 — Editor specs deliverable vincolato al tipo file`: auto-populate specs da delivery_item_id; field-gating per `media_kind`/package (`field_relevance`); endpoint `spec-schema`; enforcement ERROR coerenza su `update_item` (edit manuale planning/capitolato blocca, AI/import warn); riuso `delivery_item_validation` 9 regole. Backlog: whitelist container↔codec proattivo; severità R3.
- [ ] **Step 4: STATO** — versione → α.172.183; fatto + Prossimo (test browser Matteo: aprire deliverable con delivery_item_id → specs pre-popolate; cambiare container ad audio → campi video spariscono; salvare combo J2K+QuickTime → bloccato 422). Mantieni i backlog precedenti (QC filename, UI naming per-item, whitelist container↔codec).
- [ ] **Step 5: Commit**
```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -m "chore: α.172.183 editor specs vincolato al tipo file"
```
> Push + export ZIP: controller.

---

## Self-Review (autore)

**Spec coverage:** §1 auto-populate→Task 4 Step1 ✅; §2 field_relevance→Task 1 ✅; §3 validate severità→Task 3 (riuso) ✅; §4 endpoint spec-schema + enforcement→Task 2+3 ✅; §5 UI gating/findings→Task 4 ✅; §6 capitolato/AI warn→coperto dal fatto che enforcement è su update_item (manual) e AI usa materialize_items (no block) — documentato nel header refinement ✅; §7 test→Task 1/2/3 + browser smoke Task 4 ✅.

**Placeholder scan:** nessun TODO/TBD con codice mancante. Le NOTE "leggi e adatta nomi reali / campi NOT NULL del costruttore transiente" sono istruzioni di verifica in loco (taxonomy/serializer reali), con fallback esplicito per il transiente.

**Type consistency:** `field_relevance(media_kind, has_package, video_codec_family, has_audio)->dict[group→show|hide]` coerente Task 1↔2↔4. `validate_delivery_item(db, item)->list[{severity,code,message,fields}]` (esistente) usato in Task 2+3. Endpoint `POST /delivery-items/api/spec-schema` con input container_id/package_id/video_codec_id/has_audio coerente Task 2↔4. Enforcement `detail={code:'SPEC_COHERENCE_ERROR', findings:[...]}` coerente Task 3↔4 Step3.
