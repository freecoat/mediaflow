# Whitelist container→codec proattivo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Filtrare proattivamente il dropdown dei video codec nell'editor specs planning in base al container scelto, derivando i codec ammessi dalle regole ERROR esistenti (J2K solo in MXF; container audio → nessun video codec), senza tabelle nuove.

**Architecture:** Funzione PURA `valid_video_codec_ids(media_kind, container_name, codecs)` in `delivery_item_validation.py` (deriva dai vincoli ERROR). Esposta aggiungendo `valid_video_codec_ids` alla risposta dell'endpoint esistente `POST /delivery-items/api/spec-schema`. L'editor planning `dsmApplySpecSchema` (già chiamato al cambio container) ricostruisce le opzioni del select codec dalla taxonomy cache ∩ id validi.

**Tech Stack:** FastAPI + SQLAlchemy + Jinja2 + vanilla JS + pytest.

**Spec:** `docs/superpowers/specs/2026-06-03-container-codec-whitelist-design.md`

**Convenzioni:** filtro solo per regole ERROR (J2K↔MXF) + media_kind audio. WARNING (ProRes) NON filtrati. Direzione container→codec. Scope solo planning editor.

---

## File Structure
- `app/services/delivery_item_validation.py` — `valid_video_codec_ids` (pura).
- `app/routers/delivery_items.py` — `spec_schema` endpoint: aggiunge `valid_video_codec_ids` alla risposta.
- `app/templates/pages/planning.html` — `dsmApplySpecSchema` ricostruisce le opzioni `dsm-s-vcodec`.
- `tests/test_spec_constraints.py` — estende (unit + endpoint).

---

## Task 1: `valid_video_codec_ids` (pura) + esposizione in spec-schema — TDD

**Files:**
- Modify: `app/services/delivery_item_validation.py` (append)
- Modify: `app/routers/delivery_items.py` (`spec_schema` ~riga 362-387)
- Test: `tests/test_spec_constraints.py` (extend)

- [ ] **Step 1: Unit test funzione pura (fallisce)** — append a `tests/test_spec_constraints.py`:
```python
def test_valid_codecs_audio_empty():
    assert dv.valid_video_codec_ids(
        media_kind="audio", container_name="WAV",
        codecs=[{"id": 1, "family": "PCM"}]) == []


def test_valid_codecs_nonmxf_excludes_j2k():
    codecs = [{"id": 1, "family": "ProRes"}, {"id": 2, "family": "JPEG2000"}]
    assert dv.valid_video_codec_ids(
        media_kind="mixed", container_name="QuickTime", codecs=codecs) == [1]


def test_valid_codecs_mxf_includes_j2k():
    codecs = [{"id": 1, "family": "ProRes"}, {"id": 2, "family": "JPEG2000"}]
    assert sorted(dv.valid_video_codec_ids(
        media_kind="mixed", container_name="MXF OP1a", codecs=codecs)) == [1, 2]


def test_valid_codecs_accepts_orm_like_objects():
    class _C:
        def __init__(self, i, f): self.id = i; self.family = f
    codecs = [_C(1, "ProRes"), _C(2, "JPEG 2000")]
    assert dv.valid_video_codec_ids(
        media_kind="video", container_name="QuickTime", codecs=codecs) == [1]
```
(`dv` è già importato in cima al file da SC-T1: `from app.services import delivery_item_validation as dv`.)

- [ ] **Step 2: FAIL** — `./.venv/Scripts/python.exe -m pytest tests/test_spec_constraints.py -k valid_codecs -v` → AttributeError.

- [ ] **Step 3: Implementa la funzione** — in `app/services/delivery_item_validation.py`, in fondo (dopo `field_relevance`):
```python
def valid_video_codec_ids(*, media_kind, container_name, codecs) -> list:
    """Id dei video codec ammessi nel container, derivati dalle regole ERROR.

    PURA: nessun DB. `codecs` = iterabile di oggetti con `.id`/`.family` o dict
    con chiavi 'id'/'family'. Il chiamante risolve container/codecs e passa qui.

    - media_kind == 'audio' → []  (nessun video codec; coerente con R8).
    - container NON-MXF (name senza 'mxf') → esclude family JPEG2000/J2K (R4: J2K solo MXF).
    - altrimenti → tutti gli id.
    (ProRes→QuickTime è WARNING, NON filtrato: resta selezionabile.)
    """
    mk = (media_kind or "").strip().lower()
    if mk == "audio":
        return []
    is_mxf = "mxf" in (container_name or "").strip().lower()
    out = []
    for c in codecs:
        cid = c["id"] if isinstance(c, dict) else c.id
        fam = (c["family"] if isinstance(c, dict) else getattr(c, "family", "")) or ""
        fam = fam.strip().lower()
        if ("jpeg" in fam or "j2k" in fam) and not is_mxf:
            continue
        out.append(cid)
    return out
```

- [ ] **Step 4: Unit PASS** — `./.venv/Scripts/python.exe -m pytest tests/test_spec_constraints.py -k valid_codecs -v`.

- [ ] **Step 5: Endpoint test (fallisce)** — append a `tests/test_spec_constraints.py` (riusa `client_admin`+`taxo` esistenti; aggiungi al `taxo` un codec J2K se non c'è — verifica: il fixture `taxo` di SC-T2 crea `vc_j2k` con family "JPEG2000" e ritorna `taxo["j2k"]`):
```python
def test_spec_schema_returns_valid_codec_ids_mxf(client_admin, taxo):
    r = client_admin.post("/delivery-items/api/spec-schema", data={"container_id": taxo["mxf"]})
    assert r.status_code == 200
    ids = r.json().get("valid_video_codec_ids")
    assert ids is not None
    assert taxo["j2k"] in ids        # J2K ammesso in MXF


def test_spec_schema_excludes_j2k_in_mov(client_admin, taxo):
    r = client_admin.post("/delivery-items/api/spec-schema", data={"container_id": taxo["mov"]})
    ids = r.json().get("valid_video_codec_ids")
    assert ids is not None
    assert taxo["j2k"] not in ids    # J2K escluso in QuickTime
    assert taxo["prores"] in ids     # ProRes resta (warning, non filtrato)


def test_spec_schema_no_container_null_filter(client_admin, taxo):
    r = client_admin.post("/delivery-items/api/spec-schema", data={})
    assert r.json().get("valid_video_codec_ids") is None
```

- [ ] **Step 6: FAIL** — `./.venv/Scripts/python.exe -m pytest tests/test_spec_constraints.py -k spec_schema -v` → i nuovi falliscono (chiave assente/None).

- [ ] **Step 7: Estendi l'endpoint** — in `app/routers/delivery_items.py`, funzione `spec_schema` (~362-387). Modifica l'import e il return:
```python
    from app.services.delivery_item_validation import field_relevance, validate_delivery_item, valid_video_codec_ids
    cont = db.get(Container, container_id) if container_id else None
    vc = db.get(VideoCodec, video_codec_id) if video_codec_id else None
    groups = field_relevance(
        media_kind=getattr(cont, "media_kind", None),
        has_package=bool(package_id),
        video_codec_family=getattr(vc, "family", None),
        has_audio=has_audio,
    )
    transient = DeliveryItem(
        tenant_id=current_tenant_id(), container_id=container_id,
        package_id=package_id, video_codec_id=video_codec_id,
    )
    findings = validate_delivery_item(db, transient)
    # v3.5.0-alpha.172.184 — whitelist proattivo: id codec ammessi nel container.
    # None = nessun filtro (container assente/sconosciuto → l'editor mostra tutti).
    valid_ids = None
    if cont is not None:
        _codecs = db.query(VideoCodec).filter(VideoCodec.is_active == True).all()  # noqa: E712
        valid_ids = valid_video_codec_ids(
            media_kind=cont.media_kind, container_name=cont.name, codecs=_codecs)
    return {"groups": groups, "findings": findings, "valid_video_codec_ids": valid_ids}
```
(Verifica che `VideoCodec` abbia `is_active`; lo ha — usato dalla taxonomy. Se il nome del campo differisse, allinealo a come `get_taxonomy` filtra i codec attivi.)

- [ ] **Step 8: Endpoint PASS** — `./.venv/Scripts/python.exe -m pytest tests/test_spec_constraints.py -v` (tutti, inclusi i precedenti).

- [ ] **Step 9: Commit**
```bash
git add app/services/delivery_item_validation.py app/routers/delivery_items.py tests/test_spec_constraints.py
git commit -m "feat(specs): valid_video_codec_ids (whitelist derivato) esposto da spec-schema"
```

---

## Task 2: UI — rebuild dropdown codec in `dsmApplySpecSchema`

**Files:**
- Modify: `app/templates/pages/planning.html` (`dsmApplySpecSchema` ~2477-2506)

> Contesto reale: `dsmApplySpecSchema` fa già POST a `/delivery-items/api/spec-schema` e usa `data.groups`/`data.findings`. La taxonomy completa è in `_dsmTaxonomy` (module-level, caricata da `_dsmLoadTaxonomy`); i video codec sono `_dsmTaxonomy.video_codecs` (oggetti con `id`,`name`). Il select è `dsm-s-vcodec`.

- [ ] **Step 1: Aggiungi la ricostruzione opzioni** — in `dsmApplySpecSchema`, DOPO il blocco che applica `groups` e PRIMA (o dopo) il blocco findings, inserisci:
```javascript
  // v3.5.0-alpha.172.184 — whitelist proattivo: filtra le opzioni del codec
  // video ai soli id ammessi nel container (valid_video_codec_ids). null = tutti.
  const validIds = data.valid_video_codec_ids;  // array | null | undefined
  if (vc && Array.isArray(validIds) && _dsmTaxonomy && Array.isArray(_dsmTaxonomy.video_codecs)) {
    const allowed = new Set(validIds);
    const current = vc.value;
    // ricostruisci opzioni: vuota ("— audio-only —") + solo codec ammessi
    while (vc.firstChild) vc.removeChild(vc.firstChild);
    const o0 = document.createElement('option'); o0.value = ''; o0.textContent = '— audio-only —';
    vc.appendChild(o0);
    _dsmTaxonomy.video_codecs.forEach(c => {
      if (!allowed.has(c.id)) return;
      const o = document.createElement('option');
      o.value = String(c.id);
      o.textContent = c.name;            // textContent: nome codec = dato, no innerHTML
      if (String(c.id) === String(current)) o.selected = true;
      vc.appendChild(o);
    });
    // se il codec selezionato non è più ammesso → azzera la selezione
    if (current && !allowed.has(Number(current))) vc.value = '';
  }
```
(`vc` è già `document.getElementById('dsm-s-vcodec')` nella funzione. Usa `_dsmTaxonomy` già in scope module-level.)

- [ ] **Step 2: Verifiche statiche**
- `./.venv/Scripts/python.exe -c "from jinja2 import Environment, FileSystemLoader as L; e=Environment(loader=L('app/templates')); e.get_template('pages/planning.html'); print('JINJA OK')"` → JINJA OK
- `./.venv/Scripts/python.exe -c "import app.main; print('import OK')"` → import OK
- Grep: il blocco usa `data.valid_video_codec_ids` + `_dsmTaxonomy.video_codecs`; `textContent` per `o.textContent`; nessun `innerHTML` con dati (solo `removeChild`).

- [ ] **Step 3: Commit**
```bash
git add app/templates/pages/planning.html
git commit -m "feat(specs-ui): dropdown codec filtrato per container (whitelist proattivo)"
```

---

## Task 3: Regressione + bump α.172.184 + CHANGELOG/STATO

**Files:** `app/main.py`, `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: Suite** — `./.venv/Scripts/python.exe -m pytest -q`. Tutti pass (≥ 368 + nuovi). Se rosso → investiga, no bump.
- [ ] **Step 2: Bump** — `app/main.py` versione `3.5.0-alpha.172.183` → `3.5.0-alpha.172.184`.
- [ ] **Step 3: CHANGELOG** — entry `v3.5.0-alpha.172.184 — Whitelist container→codec proattivo`: il dropdown video codec nell'editor specs planning ora mostra solo i codec ammessi nel container scelto (derivato dalle regole ERROR: J2K solo in MXF; container audio → nessun video codec). Funzione pura `valid_video_codec_ids` + esposizione via `spec-schema`. WARNING (ProRes→QuickTime) restano selezionabili. Scope: planning editor; capitolato resta protetto da enforcement 422. Backlog: severità R3; filtro proattivo anche nell'editor capitolato.
- [ ] **Step 4: STATO** — versione → α.172.184; fatto + Prossimo (test browser: container MXF → J2K nel dropdown; container QuickTime → J2K sparisce; codec selezionato J2K + cambio a QuickTime → azzerato). Mantieni i backlog precedenti (QC filename, UI naming per-item, severità R3, fixture→conftest, filtro proattivo capitolato editor).
- [ ] **Step 5: Commit**
```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -m "chore: α.172.184 whitelist container->codec proattivo"
```
> Push + export ZIP: controller.

---

## Self-Review (autore)

**Spec coverage:** §1 `valid_video_codec_ids` pura → Task 1 Step3 ✅; §2 esposizione spec-schema → Task 1 Step7 ✅; §3 editor rebuild opzioni codec + azzera se invalido → Task 2 ✅; §4 scope planning only → rispettato (capitolato non toccato) ✅; test (unit+endpoint) → Task 1; browser smoke → Task 3 Prossimo + controller. D1 nessuna tabella ✅; D2 solo ERROR (J2K) + audio, ProRes non filtrato → funzione esclude solo J2K-non-MXF, ProRes incluso (test `test_spec_schema_excludes_j2k_in_mov` asserisce prores presente) ✅; D3 container→codec only ✅; D4 planning only ✅.

**Placeholder scan:** nessun TODO/TBD con codice mancante.

**Type consistency:** `valid_video_codec_ids(*, media_kind, container_name, codecs) -> list` coerente Task 1 (unit dict/ORM) ↔ endpoint (ORM VideoCodec) ↔ chiave risposta `valid_video_codec_ids`. UI legge `data.valid_video_codec_ids` (stessa chiave). `_dsmTaxonomy.video_codecs` con `.id`/`.name` coerente con la taxonomy servita.
