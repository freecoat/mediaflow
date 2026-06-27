# KDM UI Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pagina KDM: tab "Link" dedicata, link editabili, select-all + filtri sui link, multiselect/bulk-delete su Cinema/Server.

**Architecture:** Modifiche contenute a `app/routers/kdm.py` (2 endpoint nuovi + 1 esteso), `app/static/js/kdm.js` + `app/templates/pages/kdm.html` (UI), `app/static/js/i18n.js`. Riusa i pattern già presenti nella stessa pagina (multiselect/filtri delle Richieste).

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Jinja2 + SQLite, vanilla JS, pytest.

## Global Constraints

- Test runner: `.venv/Scripts/python.exe -m pytest <path> -v`.
- Tutto tenant-scoped (`current_tenant_id()`); gate `manage_kdm` sui mutator (helper `_require_kdm(request, db)` già usato in kdm.py).
- Soft-delete (`is_active=False`), coerente con `delete_facility`/`revoke_link` esistenti. Mai hard-delete.
- API form-based (`Form(...)`); frontend `FormData`. Riusa `_parse_ids(csv)` (già in kdm.py) per gli id CSV.
- i18n 5 lingue (`it/en/fr/de/es`) per ogni stringa UI nuova in `app/static/js/i18n.js` + `data-i18n`, stesso commit.
- No `JSON.stringify` in `onclick`. Reuse global helpers `api`/`escapeHtml`/`toast`/`mfT`/`openModal`/`closeModal`.
- Pattern di riferimento già in `kdm.js`: richieste multiselect = `kdmRowToggle`/`kdmToggleSelectAll(cb)`/`kdmUpdateBulkToolbar`/`kdmBulkDelete`; filtri = `kdmInitFilters`/`kdmFilteredRequests`. Link esistenti = `kdmLoadLinks`/`kdmLinkToggle`/`kdmBulkRevokeLinks` + endpoint `POST /api/links/bulk-revoke`.
- Fatti modello: `KdmRequestLink(id, tenant_id, token, label, project_id?, prefill_json(dict), duration_days?, expires_at?, is_active, created_at)`. "Revoca" = `is_active=False` (NIENTE campo `revoked`). `CinemaFacility.servers` cascade ORM; `delete_facility` soft-delete senza toccare i server. `Project` NON ha `broadcaster` → filtro link per **cliente** (project.client), non per emittente.

---

### Task 1: `PUT /kdm/api/links/{lid}` — modifica link

**Files:**
- Modify: `app/routers/kdm.py` (nuovo endpoint dopo `revoke_link`)
- Test: `tests/test_kdm_link_edit.py`

**Interfaces:**
- Produces: `PUT /kdm/api/links/{lid}` (Form `label?`, `project_id?`, `duration_days?`, `prefill_title?`, `prefill_cpl_uuid?`, `prefill_notes?`) → aggiorna il link attivo; ricalcola `expires_at` da `duration_days` (now+gg, o None se 0/assente-esplicito); link `is_active=False` → 400. Ritorna dict link aggiornato.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_link_edit.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole, Client, Project, KdmRequestLink
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
    role = Role(tenant_id=1, code="admin", name="A", permissions=["manage_kdm"],
                is_system=True, is_active=True)
    s.add(role); s.flush()
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.admin, role_id=role.id, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Arcadia")); s.flush()
    s.add(Project(id=1, tenant_id=1, code="P1", title="Film1", client_id=1)); s.flush()
    s.add(KdmRequestLink(id=1, tenant_id=1, token="tok1", label="Vecchio", is_active=True))
    s.add(KdmRequestLink(id=2, tenant_id=1, token="tok2", label="Revocato", is_active=False))
    s.commit()
    database.engine = e; database.SessionLocal = S
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "a@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_edit_link_updates_fields(client):
    c, s = client
    r = c.put("/kdm/api/links/1", data={"label": "Nuovo", "project_id": "1",
              "duration_days": "30", "prefill_title": "Queer"})
    assert r.status_code == 200, r.text
    s.expire_all()
    lnk = s.get(KdmRequestLink, 1)
    assert lnk.label == "Nuovo"
    assert lnk.project_id == 1
    assert lnk.expires_at is not None
    assert (lnk.prefill_json or {}).get("requested_title") == "Queer"


def test_edit_revoked_link_blocked(client):
    c, _ = client
    r = c.put("/kdm/api/links/2", data={"label": "X"})
    assert r.status_code == 400


def test_edit_unknown_link_404(client):
    c, _ = client
    assert c.put("/kdm/api/links/999", data={"label": "X"}).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kdm_link_edit.py -v`
Expected: FAIL (405/404 — endpoint assente).

- [ ] **Step 3: Write minimal implementation**

In `app/routers/kdm.py`, dopo `revoke_link` (riusa import esistenti: `KdmRequestLink`, `Form`, `Optional`, `now_utc`, `timedelta`, `current_tenant_id`):

```python
@router.put("/api/links/{lid}")
async def edit_link(
    lid: int,
    request: Request,
    db: Session = Depends(get_db),
    label: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    duration_days: Optional[int] = Form(None),
    prefill_title: Optional[str] = Form(None),
    prefill_cpl_uuid: Optional[str] = Form(None),
    prefill_notes: Optional[str] = Form(None),
):
    from app.services.clock import now_utc
    from datetime import timedelta
    _require_kdm(request, db)
    lnk = db.get(KdmRequestLink, lid)
    if not lnk or lnk.tenant_id != current_tenant_id():
        raise HTTPException(404, "Link non trovato")
    if not lnk.is_active:
        raise HTTPException(400, "Link revocato: non modificabile")
    if label is not None:
        lnk.label = label.strip() or None
    if project_id is not None:
        lnk.project_id = project_id or None
    if duration_days is not None:
        lnk.duration_days = duration_days or None
        lnk.expires_at = (now_utc() + timedelta(days=duration_days)) if duration_days else None
    prefill = dict(lnk.prefill_json or {})
    for key, val in (("requested_title", prefill_title),
                     ("requested_cpl_uuid", prefill_cpl_uuid),
                     ("notes", prefill_notes)):
        if val is not None:
            v = val.strip()
            if v:
                prefill[key] = v
            else:
                prefill.pop(key, None)
    lnk.prefill_json = prefill or None
    db.commit(); db.refresh(lnk)
    return {"ok": True, "id": lnk.id, "label": lnk.label, "project_id": lnk.project_id,
            "expires_at": lnk.expires_at.isoformat() if lnk.expires_at else None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kdm_link_edit.py -v`
Expected: PASS (3 test).

- [ ] **Step 5: Commit**

```bash
git add app/routers/kdm.py tests/test_kdm_link_edit.py
git commit -m "feat(kdm): PUT /api/links/{id} modifica link"
```

---

### Task 2: `GET /kdm/api/links` — includi revocati + campi per filtri

**Files:**
- Modify: `app/routers/kdm.py` (`list_links`, ~riga 968)
- Test: `tests/test_kdm_links_list_fields.py`

**Interfaces:**
- Produces: `GET /api/links` ora ritorna ANCHE i link revocati (`is_active=False`) con `"revoked": True`; ogni elemento ha in più `client_name` (da `project.client`), `requested_title` (da prefill), `revoked` (bool). I link attivi hanno `revoked=False`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_links_list_fields.py
# Riusa la fixture `client` di test_kdm_link_edit.py
from tests.test_kdm_link_edit import client  # noqa: F401


def test_list_includes_revoked_and_derived_fields(client):
    c, s = client
    data = c.get("/kdm/api/links").json()
    by_id = {x["id"]: x for x in data}
    # link 2 è revocato (is_active=False) → ora presente con revoked=True
    assert 2 in by_id and by_id[2]["revoked"] is True
    assert by_id[1]["revoked"] is False
    # client_name e requested_title presenti come chiavi
    assert "client_name" in by_id[1]
    assert "requested_title" in by_id[1]


def test_list_client_name_from_project(client):
    c, s = client
    from app.models.models import KdmRequestLink
    s.get(KdmRequestLink, 1).project_id = 1
    s.commit()
    data = {x["id"]: x for x in c.get("/kdm/api/links").json()}
    assert data[1]["client_name"] == "Arcadia"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kdm_links_list_fields.py -v`
Expected: FAIL (link 2 assente perché filtrato da is_active; chiavi mancanti).

- [ ] **Step 3: Write minimal implementation**

In `app/routers/kdm.py` `list_links`: rimuovi il filtro `is_active == True` (ritorna tutti), e arricchisci la response. Sostituisci il corpo dopo `_require_kdm(...)`:

```python
    from app.models import Project, Client
    rows = (db.query(KdmRequestLink)
            .filter(KdmRequestLink.tenant_id == current_tenant_id())
            .order_by(KdmRequestLink.created_at.desc()).all())
    base = _public_base(request)
    now = now_utc()
    proj_ids = {l.project_id for l in rows if l.project_id}
    proj_names, proj_client = {}, {}
    if proj_ids:
        projs = db.query(Project).filter(Project.id.in_(proj_ids)).all()
        client_ids = {p.client_id for p in projs if p.client_id}
        client_names = {}
        if client_ids:
            for cl in db.query(Client).filter(Client.id.in_(client_ids)).all():
                client_names[cl.id] = cl.name
        for p in projs:
            proj_names[p.id] = p.title
            proj_client[p.id] = client_names.get(p.client_id)
    out = []
    for lnk in rows:
        exp = lnk.expires_at
        out.append({
            "id": lnk.id, "token": lnk.token, "label": lnk.label,
            "project_id": lnk.project_id, "project_name": proj_names.get(lnk.project_id),
            "client_name": proj_client.get(lnk.project_id),
            "requested_title": (lnk.prefill_json or {}).get("requested_title"),
            "duration_days": lnk.duration_days,
            "created_at": lnk.created_at.isoformat() if lnk.created_at else None,
            "expires_at": exp.isoformat() if exp else None,
            "is_expired": bool(exp and exp < now),
            "revoked": not lnk.is_active,
            "url": f"{base}/public/kdm/{lnk.token}",
        })
    return out
```

(Assicurati che `from app.services.clock import now_utc` resti in cima alla funzione.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kdm_links_list_fields.py -v`
Expected: PASS (2 test).

- [ ] **Step 5: Commit**

```bash
git add app/routers/kdm.py tests/test_kdm_links_list_fields.py
git commit -m "feat(kdm): list_links include revocati + client_name/requested_title/revoked"
```

---

### Task 3: `POST /kdm/api/facilities/bulk-delete` — soft-delete cinema + server

**Files:**
- Modify: `app/routers/kdm.py` (dopo `delete_facility`, ~riga 683)
- Test: `tests/test_kdm_facility_bulk_delete.py`

**Interfaces:**
- Produces: `POST /api/facilities/bulk-delete` (Form `ids` CSV) → soft-delete `is_active=False` su ogni `CinemaFacility` del tenant + sui suoi `CinemaServer`. Ritorna `{deleted, servers_deleted, requested}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kdm_facility_bulk_delete.py
from tests.test_kdm_link_edit import client  # riusa fixture
from app.models.models import CinemaFacility, CinemaServer


def _seed_facilities(s):
    s.add(CinemaFacility(id=1, tenant_id=1, name="Cinema A", is_active=True))
    s.add(CinemaFacility(id=2, tenant_id=1, name="Cinema B", is_active=True))
    s.add(CinemaServer(id=1, tenant_id=1, facility_id=1, serial="S1", is_active=True))
    s.add(CinemaServer(id=2, tenant_id=1, facility_id=1, serial="S2", is_active=True))
    s.commit()


def test_bulk_delete_facilities_and_servers(client):
    c, s = client
    _seed_facilities(s)
    r = c.post("/kdm/api/facilities/bulk-delete", data={"ids": "1,999"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == 1
    assert body["servers_deleted"] == 2
    s.expire_all()
    assert s.get(CinemaFacility, 1).is_active is False
    assert s.get(CinemaServer, 1).is_active is False
    assert s.get(CinemaFacility, 2).is_active is True  # non toccato


def test_bulk_delete_empty_ids_400(client):
    c, _ = client
    assert c.post("/kdm/api/facilities/bulk-delete", data={"ids": ""}).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kdm_facility_bulk_delete.py -v`
Expected: FAIL (404 endpoint assente).

- [ ] **Step 3: Write minimal implementation**

In `app/routers/kdm.py`, dopo `delete_facility` (riusa `_parse_ids`, `CinemaFacility`, `CinemaServer`):

```python
@router.post("/api/facilities/bulk-delete")
async def bulk_delete_facilities(request: Request, db: Session = Depends(get_db),
                                 ids: str = Form(...)):
    _require_kdm(request, db)
    parsed = _parse_ids(ids)
    if not parsed:
        raise HTTPException(400, "Nessun id valido")
    deleted = servers_deleted = 0
    for fid in parsed:
        f = db.get(CinemaFacility, fid)
        if not f or f.tenant_id != current_tenant_id() or not f.is_active:
            continue
        f.is_active = False
        deleted += 1
        for srv in db.query(CinemaServer).filter(
                CinemaServer.facility_id == fid,
                CinemaServer.tenant_id == current_tenant_id(),
                CinemaServer.is_active == True):  # noqa: E712
            srv.is_active = False
            servers_deleted += 1
    db.commit()
    return {"ok": True, "deleted": deleted, "servers_deleted": servers_deleted,
            "requested": len(parsed)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_kdm_facility_bulk_delete.py -v`
Expected: PASS (2 test).

- [ ] **Step 5: Commit**

```bash
git add app/routers/kdm.py tests/test_kdm_facility_bulk_delete.py
git commit -m "feat(kdm): bulk-delete facilities + server in cascata (soft)"
```

---

### Task 4: UI — tab "🔗 Link" (sposta + edit + select-all + filtri)

**Files:**
- Modify: `app/templates/pages/kdm.html` (nuova tab + barra filtri; rimuovi link da Richieste)
- Modify: `app/static/js/kdm.js` (`kdmSwitchTab`, refactor `kdmLoadLinks`→`kdmRenderLinks`+filtri, edit modal, select-all)
- Modify: `app/static/js/i18n.js`
- Test: browser smoke (controller) + `import app.main`

**Interfaces:**
- Consumes: `PUT /api/links/{id}` (Task 1), esteso `GET /api/links` (Task 2), `POST /api/links/bulk-revoke` (esistente).

- [ ] **Step 1: HTML — nuova tab + spostamento**

In `kdm.html`:
- Aggiungi il bottone tab dopo `kdm-tab-btn-requests`:
```html
<button class="tab-btn" id="kdm-tab-btn-links" data-tab="links" onclick="kdmSwitchTab('links')">
  <span data-i18n="kdm.tab.links">Link</span>
</button>
```
- Crea il pane `<div id="kdm-tab-links" class="kdm-tab" style="display:none;">` e SPOSTA al suo interno: la barra genera-link (oggi nel pane requests) e il contenitore `<div id="kdm-links-list">` (rimuovilo dal pane requests). Aggiungi sopra la lista una barra filtri:
```html
<div class="kdm-link-filters" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
  <select id="kdm-link-f-status" class="form-select" onchange="kdmRenderLinks()">
    <option value="active" data-i18n="kdm.link.filter.active">Attivi</option>
    <option value="expired" data-i18n="kdm.link.filter.expired">Scaduti</option>
    <option value="revoked" data-i18n="kdm.link.filter.revoked">Revocati</option>
    <option value="all" data-i18n="kdm.link.filter.all">Tutti</option>
  </select>
  <select id="kdm-link-f-project" class="form-select" onchange="kdmRenderLinks()"></select>
  <select id="kdm-link-f-client" class="form-select" onchange="kdmRenderLinks()"></select>
  <input id="kdm-link-f-q" class="form-input" data-i18n="kdm.link.filter.search_ph" data-i18n-attr="placeholder" placeholder="Cerca nome/titolo" oninput="kdmRenderLinks()">
</div>
```
- Rimuovi dal pane Richieste il bottone toggle "Link attivi" (`kdm-show-links-btn`).

- [ ] **Step 2: JS — switch tab + render con filtri + select-all**

In `kdm.js`:
- In `kdmSwitchTab`, aggiungi `else if (name === 'links') kdmLoadLinks();`.
- Rinomina la logica: `kdmLoadLinks()` carica `_kdmLinks` da `GET /api/links` poi popola i select filtro (progetti/clienti distinti dai link) e chiama `kdmRenderLinks()`. Estrai il rendering in `kdmRenderLinks()` che filtra `_kdmLinks` via `kdmFilteredLinks()` e renderizza. La lista deve avere un **checkbox header select-all** che chiama `kdmLinkToggleSelectAll(this.checked)` (specchio di `kdmToggleSelectAll`: seleziona i link filtrati visibili in `_kdmLinkSel`, aggiorna la toolbar revoca). Ogni riga ha il checkbox per-riga (`kdmLinkToggle`) già esistente + un bottone "✎" che chiama `kdmEditLink(id)`.
- `kdmFilteredLinks()` applica: status (active = !revoked && !is_expired; expired = is_expired && !revoked; revoked; all), project_id, client_name, testo su `label`+`requested_title`. Pattern identico a `kdmFilteredRequests`.

```javascript
function kdmFilteredLinks() {
  var st = (document.getElementById('kdm-link-f-status')||{}).value || 'active';
  var pj = (document.getElementById('kdm-link-f-project')||{}).value || '';
  var cl = (document.getElementById('kdm-link-f-client')||{}).value || '';
  var q = ((document.getElementById('kdm-link-f-q')||{}).value || '').toLowerCase().trim();
  return _kdmLinks.filter(function(l) {
    if (st === 'active' && (l.revoked || l.is_expired)) return false;
    if (st === 'expired' && !(l.is_expired && !l.revoked)) return false;
    if (st === 'revoked' && !l.revoked) return false;
    if (pj && String(l.project_id||'') !== pj) return false;
    if (cl && (l.client_name||'') !== cl) return false;
    if (q) {
      var hay = ((l.label||'') + ' ' + (l.requested_title||'')).toLowerCase();
      if (hay.indexOf(q) === -1) return false;
    }
    return true;
  });
}
```

- [ ] **Step 3: JS — edit modal**

Aggiungi `kdmEditLink(id)`: trova il link in `_kdmLinks`, apri un modal (riusa un `kdm-modal-link-edit` da aggiungere in kdm.html con i campi nome/progetto/durata/prefill titolo) precompilato, e `kdmEditLinkSave(id)` che fa `PUT /api/links/{id}` via FormData poi `kdmLoadLinks()`. Niente JSON.stringify in onclick (passa solo l'id numerico).

- [ ] **Step 4: i18n + smoke**

In `i18n.js` aggiungi in 5 lingue: `kdm.tab.links`, `kdm.link.filter.active/expired/revoked/all/search_ph`, `kdm.link.filter.project_all`/`client_all`, `kdm.link.edit`, `kdm.link.edit_title`, `kdm.link.save`, `kdm.link.select_all`.
Verifica `import app.main`. Il controller esegue lo smoke browser: tab Link separata, filtri restringono, select-all + revoca, ✎ modifica salva.

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/kdm.html app/static/js/kdm.js app/static/js/i18n.js
git commit -m "feat(kdm): tab Link dedicata + edit + filtri + select-all"
```

---

### Task 5: UI — multiselect Cinema/Server + bulk delete

**Files:**
- Modify: `app/static/js/kdm.js` (`kdmLoadFacilities` render + nuovi handler)
- Modify: `app/static/js/i18n.js`
- Test: browser smoke (controller) + `import app.main`

**Interfaces:**
- Consumes: `POST /api/facilities/bulk-delete` (Task 3).

- [ ] **Step 1: JS — checkbox + select-all + toolbar**

In `kdmLoadFacilities` (render facilities), aggiungi per ogni riga facility un checkbox `kdmFacilityToggle(id, checked)`; un checkbox header select-all `kdmFacilityToggleSelectAll(checked)`; e una toolbar (nascosta finché 0 selezionati) con "Elimina selezionati" → `kdmFacilityBulkDelete()`. Stato selezione in `_kdmFacilitySel = {}`. Specchio esatto di `kdmRowToggle`/`kdmToggleSelectAll`/`kdmUpdateBulkToolbar`/`kdmBulkDelete` delle richieste.

```javascript
var _kdmFacilitySel = {};
function kdmFacilityToggle(id, on){ if(on) _kdmFacilitySel[id]=1; else delete _kdmFacilitySel[id]; kdmFacilityBulkBar(); }
function kdmFacilityToggleSelectAll(on){
  document.querySelectorAll('.kdm-fac-check').forEach(function(cb){ cb.checked=on; var id=parseInt(cb.value,10); if(on)_kdmFacilitySel[id]=1; else delete _kdmFacilitySel[id]; });
  kdmFacilityBulkBar();
}
function kdmFacilityBulkBar(){
  var n=Object.keys(_kdmFacilitySel).length;
  var bar=document.getElementById('kdm-fac-bulk');
  if(bar){ bar.style.display=n?'flex':'none'; var lbl=document.getElementById('kdm-fac-bulk-n'); if(lbl) lbl.textContent=mfT('kdm.facility.n_selected').replace('{n}',n); }
}
async function kdmFacilityBulkDelete(){
  var ids=Object.keys(_kdmFacilitySel);
  if(!ids.length) return;
  if(!confirm(mfT('kdm.facility.confirm_bulk').replace('{n}',ids.length))) return;
  try{
    var fd=new FormData(); fd.append('ids', ids.join(','));
    var r=await api('POST','/kdm/api/facilities/bulk-delete', fd);
    _kdmFacilitySel={};
    toast(mfT('kdm.facility.deleted_n').replace('{n}',r.deleted).replace('{m}',r.servers_deleted),'success');
    kdmLoadFacilities();
  }catch(e){ toast('Errore: '+(e.message||''),'error'); }
}
```

Inserisci `kdm-fac-bulk` (toolbar con `kdm-fac-bulk-n` + bottone) e il checkbox header nel markup generato da `kdmLoadFacilities`.

- [ ] **Step 2: i18n + smoke**

In `i18n.js` aggiungi in 5 lingue: `kdm.facility.select_all`, `kdm.facility.delete_selected`, `kdm.facility.n_selected` (`{n}`), `kdm.facility.confirm_bulk` (`{n}`), `kdm.facility.deleted_n` (`{n}`/`{m}`).
Verifica `import app.main`. Controller smoke: seleziona 2 cinema → Elimina selezionati → conferma → spariscono (con i loro server).

- [ ] **Step 3: Commit**

```bash
git add app/static/js/kdm.js app/static/js/i18n.js
git commit -m "feat(kdm): multiselect + bulk-delete Cinema/Server"
```

---

### Task 6: Integrazione — bump + suite + docs

**Files:**
- Modify: `app/main.py` (version `3.5.0-alpha.172.238`)
- Modify: `CHANGELOG.md`, `docs/STATO.md`
- Test: full suite

- [ ] **Step 1: Full suite** — `.venv/Scripts/python.exe -m pytest tests/ -q` → tutti verdi.
- [ ] **Step 2: Smoke browser end-to-end** (controller): tab Link separata + edit + filtri + select-all; Cinema multiselect + bulk delete; 0 errori console, 0 chiavi i18n grezze.
- [ ] **Step 3: Bump + docs** — version `3.5.0-alpha.172.238`; sezione CHANGELOG + STATO.
- [ ] **Step 4: graphify + commit**
```bash
graphify update .
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -m "chore(kdm): bump v3.5.0-alpha.172.238 + docs"
```
- [ ] **Step 5: Verifica finale** — full suite verde.

---

## Self-Review (eseguito)

**Spec coverage**: tab Link (T4) · link editabili (T1 backend + T4 UI) · select-all link (T4) · filtri link (T2 backend campi + T4 UI) · multiselect Cinema/Server (T3 backend + T5 UI) · bump/docs (T6). Tutte le 5 modifiche coperte. Correzione vs spec: il filtro link usa **cliente** (project.client); "emittente/broadcaster" NON è un campo Project → omesso (la spec lo derivava erroneamente; il piano usa solo client_name).

**Placeholder scan**: nessun TBD/TODO; codice concreto per i 3 endpoint + handler JS. Le task UI (T4/T5) descrivono markup+JS con snippet concreti e funzioni-specchio nominate esattamente (`kdmToggleSelectAll`, `kdmFilteredRequests`, `kdmBulkRevokeLinks`); lo smoke del controller è la verifica.

**Type consistency**: `GET /api/links` (T2) aggiunge `revoked`/`client_name`/`requested_title` consumati da `kdmFilteredLinks` (T4); `PUT /api/links/{id}` (T1) consumato da `kdmEditLink` (T4); `POST /api/facilities/bulk-delete` ritorna `{deleted, servers_deleted}` consumati da `kdmFacilityBulkDelete` (T5). Coerenti.

## Fuori scope
Hard-delete reale facility; modifica form pubblico `/public/kdm/{token}`; logica matching CPL; filtro link per emittente/broadcaster.
