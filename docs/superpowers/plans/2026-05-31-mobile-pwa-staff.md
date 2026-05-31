# Mobile PWA (Staff) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** App mobile companion (PWA installabile) per lo staff operativo: Oggi, Timbratura, Mie assegnazioni (accetta/rifiuta), Ferie, Notifiche — sotto `/m/*`, riusando gli endpoint JSON esistenti.

**Architecture:** Nuovo router `app/routers/mobile.py` (prefix `/m`) che renderizza template Jinja lean (`templates/mobile/`, NON il base.html desktop) con `mobile.css`/`mobile.js` dedicati. I dati arrivano via fetch agli endpoint esistenti (my-bookings, punches, my-unavailabilities, notifications). PWA: `manifest.json` + `sw.js` (cache app shell, azioni online). Auth: middleware globale esistente protegge già `/m/*` (redirect `/auth/login`). Spec: `docs/superpowers/specs/2026-05-31-mobile-pwa-staff-design.md`.

**Tech Stack:** FastAPI + Jinja2 + vanilla JS, service worker/manifest (PWA), pytest. Venv `.venv/Scripts/python.exe`. Convenzioni: page route usa `current_user_optional(request)` (da `app.services.rbac`), `templates.TemplateResponse`; cache-buster `?v={{ app_version }}`; commit a ogni task.

---

## File map (nuovi salvo dove indicato)
- `app/routers/mobile.py` — router `/m`, route che renderizzano i template.
- `app/main.py` — `app.include_router(mobile.router)` (MODIFICA, 1 riga).
- `app/templates/mobile/base_mobile.html` — shell (head, manifest, SW reg, bottom tab bar).
- `app/templates/mobile/{oggi,timbra,assegnazioni,ferie,notifiche,offline}.html`.
- `app/static/css/mobile.css` — stile touch-first.
- `app/static/js/mobile.js` — helper fetch + render condiviso.
- `app/static/manifest.json`, `app/static/sw.js`.
- `app/routers/planning.py` — endpoint `respond` (MODIFICA, Task 8) + eventuale campo modello.
- `tests/test_mobile.py`, `tests/test_booking_respond.py`.

---

## Phase 0 — Scaffold

### Task 1: Router `/m` + shell + Oggi placeholder + smoke

**Files:** Create `app/routers/mobile.py`, `app/templates/mobile/base_mobile.html`, `app/templates/mobile/oggi.html`; Modify `app/main.py`; Test `tests/test_mobile.py`.

- [ ] **Step 1: Failing test** (`tests/test_mobile.py`)

```python
from app.routers import mobile as mob


def test_mobile_router_prefix_and_routes():
    paths = {r.path for r in mob.router.routes}
    assert "/m" in paths or "/m/" in paths
    # le route principali esistono
    for p in ("/m/timbra", "/m/assegnazioni", "/m/ferie", "/m/notifiche"):
        assert p in paths


def test_mobile_router_registered_in_app():
    import app.main as m
    app_paths = {r.path for r in m.app.routes}
    assert any(p.startswith("/m") for p in app_paths)
```

- [ ] **Step 2: Run → FAIL** (`.venv/Scripts/python.exe -m pytest tests/test_mobile.py -q`) — no module `app.routers.mobile`.

- [ ] **Step 3: Implement router** (`app/routers/mobile.py`)

```python
"""Area mobile /m — PWA companion staff (v3.5.0-alpha.172.158).

Template lean (templates/mobile/), riusa gli endpoint JSON esistenti via fetch.
Auth: il middleware globale (main.py) protegge già /m/* (redirect /auth/login).
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.rbac import current_user_optional

router = APIRouter(prefix="/m", tags=["mobile"])


def _tpl():
    from app.main import templates
    return templates


def _page(request, name, **ctx):
    user = current_user_optional(request)
    return _tpl().TemplateResponse(
        f"mobile/{name}.html",
        {"request": request, "user": user, **ctx},
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def m_oggi(request: Request, db: Session = Depends(get_db)):
    return _page(request, "oggi", active="oggi")


@router.get("/timbra", response_class=HTMLResponse)
async def m_timbra(request: Request):
    return _page(request, "timbra", active="timbra")


@router.get("/assegnazioni", response_class=HTMLResponse)
async def m_assegnazioni(request: Request):
    return _page(request, "assegnazioni", active="assegnazioni")


@router.get("/ferie", response_class=HTMLResponse)
async def m_ferie(request: Request):
    return _page(request, "ferie", active="ferie")


@router.get("/notifiche", response_class=HTMLResponse)
async def m_notifiche(request: Request):
    return _page(request, "notifiche", active="notifiche")


@router.get("/offline", response_class=HTMLResponse)
async def m_offline(request: Request):
    return _tpl().TemplateResponse("mobile/offline.html", {"request": request})
```

- [ ] **Step 4: base_mobile.html** (`app/templates/mobile/base_mobile.html`)

```html
<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, viewport-fit=cover">
  <meta name="theme-color" content="#6272f5">
  <link rel="manifest" href="/static/manifest.json">
  <link rel="apple-touch-icon" href="/static/icons/icon-192.png">
  <title>{% block title %}Claqo{% endblock %}</title>
  <link rel="stylesheet" href="/static/css/mobile.css?v={{ app_version }}">
</head>
<body>
  <header class="m-top">
    <span class="m-top-title">{% block topbar %}Claqo{% endblock %}</span>
  </header>
  <main class="m-main" id="m-main">
    {% block content %}{% endblock %}
  </main>
  <nav class="m-tabbar">
    <a href="/m" class="m-tab {% if active=='oggi' %}active{% endif %}"><span>🏠</span>Oggi</a>
    <a href="/m/assegnazioni" class="m-tab {% if active=='assegnazioni' %}active{% endif %}"><span>📋</span>Lavori</a>
    <a href="/m/timbra" class="m-tab {% if active=='timbra' %}active{% endif %}"><span>⏱</span>Timbra</a>
    <a href="/m/ferie" class="m-tab {% if active=='ferie' %}active{% endif %}"><span>🌴</span>Ferie</a>
    <a href="/m/notifiche" class="m-tab {% if active=='notifiche' %}active{% endif %}"><span>🔔</span>Avvisi</a>
  </nav>
  <script>
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => navigator.serviceWorker.register('/static/sw.js').catch(()=>{}));
    }
  </script>
  <script src="/static/js/mobile.js?v={{ app_version }}"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 5: oggi.html placeholder** (`app/templates/mobile/oggi.html`)

```html
{% extends "mobile/base_mobile.html" %}
{% block title %}Oggi — Claqo{% endblock %}
{% block topbar %}Oggi{% endblock %}
{% block content %}
  <div id="m-oggi-root" class="m-section"><div class="m-loading">Caricamento…</div></div>
{% endblock %}
```
(Le altre pagine — timbra/assegnazioni/ferie/notifiche/offline — sono create nei rispettivi task; per ora crea anche degli stub minimi che estendono base_mobile con un root vuoto, così le route non rompono. Stub esempio `offline.html`:)
```html
{% extends "mobile/base_mobile.html" %}
{% block topbar %}Offline{% endblock %}
{% block content %}<div class="m-section"><p>Sei offline. Riconnettiti per aggiornare i dati.</p></div>{% endblock %}
```
Crea stub analoghi (root `<div id="m-{name}-root">`) per timbra/assegnazioni/ferie/notifiche.

- [ ] **Step 6: Register router** in `app/main.py` — dopo `app.include_router(hr.router)` aggiungi:
```python
from app.routers import mobile as mobile_router  # in cima con gli altri import
app.include_router(mobile_router.router)
```
(Metti l'import insieme agli altri `from app.routers import ...` e l'include vicino agli altri include_router.)

- [ ] **Step 7: Create empty `app/static/css/mobile.css` and `app/static/js/mobile.js`** (vuoti per ora, riempiti in Task 2/3) + `app/static/sw.js` minimale (riempito Task 4) e `app/static/manifest.json` (Task 4) — così i `<link>`/registrazioni non danno 404 in test. Per ora `mobile.css`/`mobile.js` possono essere file vuoti; crea `sw.js` con `self.addEventListener('install',()=>self.skipWaiting());` e un manifest minimo valido.

- [ ] **Step 8: Run tests** → PASS. Jinja compile: `.venv/Scripts/python.exe -c "from jinja2 import Environment, FileSystemLoader; e=Environment(loader=FileSystemLoader('app/templates')); [e.get_template('mobile/'+t+'.html') for t in ('base_mobile','oggi','offline')]; print('OK')"`. Import app: `.venv/Scripts/python.exe -c "import app.main; print('OK')"`.

- [ ] **Step 9: Commit**
```bash
git add app/routers/mobile.py app/main.py app/templates/mobile/ app/static/css/mobile.css app/static/js/mobile.js app/static/sw.js app/static/manifest.json tests/test_mobile.py
git commit -m "feat(mobile): scaffold area /m PWA staff (router + shell + tab bar)"
```

---

### Task 2: mobile.css (touch-first)

**Files:** Modify `app/static/css/mobile.css`.

- [ ] **Step 1: Implement** un foglio di stile dark touch-first. Requisiti: variabili colore coerenti col desktop (indaco `#6272f5`, bg scuro), `.m-top` header fisso in alto, `.m-main` con padding + scroll + `padding-bottom` per non finire sotto la tab bar, `.m-tabbar` fixed in basso (5 tab, icone+label, stato `.active` indaco), `.m-card` (card con padding/raggio), bottoni `.m-btn`/`.m-btn-primary` ≥44px height, `.m-list`/`.m-list-item` per liste verticali, `.m-loading`/`.m-empty`. Usa `env(safe-area-inset-bottom)` per iPhone notch. Scrivi CSS completo e autosufficiente (~150-200 righe).

Esempio struttura minima (espandere):
```css
:root{--m-bg:#0f1117;--m-bg2:#171a23;--m-accent:#6272f5;--m-text:#e8eaf0;--m-muted:#8a90a2;--m-border:#262a36;}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--m-bg);color:var(--m-text);font:15px/1.4 -apple-system,system-ui,sans-serif}
.m-top{position:sticky;top:0;background:var(--m-bg2);padding:14px 16px;font-weight:700;border-bottom:1px solid var(--m-border);z-index:10}
.m-main{padding:12px 14px 84px}
.m-tabbar{position:fixed;left:0;right:0;bottom:0;display:flex;background:var(--m-bg2);border-top:1px solid var(--m-border);padding-bottom:env(safe-area-inset-bottom)}
.m-tab{flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;padding:8px 0;font-size:11px;color:var(--m-muted);text-decoration:none}
.m-tab.active{color:var(--m-accent)}
.m-tab span{font-size:20px}
.m-card{background:var(--m-bg2);border:1px solid var(--m-border);border-radius:12px;padding:14px;margin-bottom:12px}
.m-btn{display:block;width:100%;min-height:48px;border:none;border-radius:12px;font-size:16px;font-weight:600;background:var(--m-bg2);color:var(--m-text)}
.m-btn-primary{background:var(--m-accent);color:#fff}
.m-list-item{padding:12px 0;border-bottom:1px solid var(--m-border)}
.m-loading,.m-empty{color:var(--m-muted);text-align:center;padding:24px}
```

- [ ] **Step 2: Verify** — il file è CSS valido (nessun parse error evidente; opzionale: apri in node con un lint leggero non necessario). Jinja non coinvolto.

- [ ] **Step 3: Commit**
```bash
git add app/static/css/mobile.css
git commit -m "feat(mobile): mobile.css touch-first (tab bar, card, liste)"
```

---

### Task 3: mobile.js (helper fetch/render + auth-aware)

**Files:** Modify `app/static/js/mobile.js`.

- [ ] **Step 1: Implement** helper condivisi. Scrivi:
```javascript
// mobile.js — helper condivisi area /m. v3.5.0-alpha.172.158
async function mapi(method, url, formData) {
  const opt = { method, headers: {}, credentials: 'same-origin' };
  if (formData) opt.body = formData;
  const r = await fetch(url, opt);
  if (r.status === 401 || r.status === 403) { location.href = '/auth/login?next=' + encodeURIComponent(location.pathname); throw new Error('auth'); }
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('application/json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.detail) ? data.detail : ('HTTP ' + r.status));
  return data;
}
function mEl(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
function mEsc(s) { const d = document.createElement('div'); d.textContent = (s == null ? '' : String(s)); return d.innerHTML; }
function mToast(msg) {
  const t = mEl('div', 'm-toast', mEsc(msg)); document.body.appendChild(t);
  setTimeout(() => t.classList.add('show'), 10); setTimeout(() => { t.classList.remove('show'); setTimeout(()=>t.remove(), 300); }, 2600);
}
function mFmtDate(iso) { if(!iso) return ''; const d = new Date(iso); return d.toLocaleDateString('it-IT', {day:'2-digit', month:'2-digit'}); }
function mFmtTime(iso) { if(!iso) return ''; const d = new Date(iso); return d.toLocaleTimeString('it-IT', {hour:'2-digit', minute:'2-digit'}); }
```
Aggiungi a `mobile.css` (Task 2 già committato → fai un piccolo append qui o nel Task 2; se Task 2 già chiuso, appendi in questo commit) lo stile `.m-toast` (fixed bottom, fade). Per semplicità: includi la regola `.m-toast{position:fixed;left:50%;transform:translateX(-50%);bottom:90px;background:#222;color:#fff;padding:10px 16px;border-radius:20px;opacity:0;transition:opacity .3s;z-index:50}.m-toast.show{opacity:1}` — se modifichi mobile.css qui, aggiungi mobile.css al commit.

- [ ] **Step 2: Verify** `node --check app/static/js/mobile.js` → exit 0.

- [ ] **Step 3: Commit**
```bash
git add app/static/js/mobile.js app/static/css/mobile.css
git commit -m "feat(mobile): mobile.js helper (mapi/render/toast) + stile toast"
```

---

### Task 4: PWA (manifest + service worker)

**Files:** Modify `app/static/manifest.json`, `app/static/sw.js`; Create icons `app/static/icons/icon-192.png`, `icon-512.png` (copia dal brand pack esistente).

- [ ] **Step 1: Icone** — copia/deriva due PNG quadrate dal brand pack (`docs/brand/` o l'icona app esistente in `app/static/`). Cerca un'icona esistente (`grep -ri "icon" app/templates/base.html | head`; o file in `app/static/`). Crea `app/static/icons/icon-192.png` e `icon-512.png` (ridimensiona se serve con Pillow: `from PIL import Image; ...`). Se non trovi sorgente raster, genera un PNG placeholder indaco con la lettera "C" via Pillow.

- [ ] **Step 2: manifest.json**
```json
{
  "name": "Claqo",
  "short_name": "Claqo",
  "start_url": "/m",
  "scope": "/m",
  "display": "standalone",
  "background_color": "#0f1117",
  "theme_color": "#6272f5",
  "icons": [
    {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
  ]
}
```

- [ ] **Step 3: sw.js** (cache app shell, network per dati, offline fallback)
```javascript
const CACHE = 'claqo-m-v1';
const SHELL = ['/static/css/mobile.css','/static/js/mobile.js','/static/icons/icon-192.png','/m/offline'];
self.addEventListener('install', e => { self.skipWaiting(); e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(()=>{})); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k!==CACHE).map(k => caches.delete(k))))); self.clients.claim(); });
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return; // azioni online: passa diretto
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(resp => { const cp = resp.clone(); caches.open(CACHE).then(c=>c.put(e.request, cp)); return resp; }).catch(()=>r)));
    return;
  }
  if (url.pathname.startsWith('/m')) {
    e.respondWith(fetch(e.request).catch(() => caches.match('/m/offline')));
  }
});
```

- [ ] **Step 4: Test** (`tests/test_mobile.py` extend)
```python
import json, pathlib
def test_manifest_valid():
    m = json.loads(pathlib.Path("app/static/manifest.json").read_text(encoding="utf-8"))
    assert m["start_url"] == "/m"
    assert m["display"] == "standalone"
    assert any(i["sizes"] == "512x512" for i in m["icons"])
```
Run pytest + `node --check app/static/sw.js`.

- [ ] **Step 5: Commit**
```bash
git add app/static/manifest.json app/static/sw.js app/static/icons/ tests/test_mobile.py
git commit -m "feat(mobile): PWA manifest + service worker (shell cache, offline fallback)"
```

---

## Phase 1 — Schermate (ognuna: route già pronta in Task 1; qui template + render JS)

> Per OGNI schermata: l'implementer DEVE leggere l'endpoint riusato in `app/routers/*` per mappare i NOMI ESATTI dei campi JSON nella render (il contratto dati è già definito dal codice esistente). Gli URL sono indicati; i campi vanno letti dalla route.

### Task 5: Oggi (home)
**Endpoint:** `GET /planning/api/my-bookings?today_only=true`, `GET /hr/api/punches`, `GET /notifications/api/unread-count`.
**Files:** Modify `app/templates/mobile/oggi.html` (+ render in `mobile.js` o `<script>` in pagina).

- [ ] Step 1: Leggi le 3 route per i campi. Step 2: in `oggi.html` `{% block scripts %}`, scrivi `loadOggi()` che fetcha le mie assegnazioni di oggi (lista card: orario+job/booking title), lo stato timbratura corrente (ultimo punch → IN/OUT + bottone che linka a /m/timbra), e il badge notifiche non lette. Usa `mapi`, `mEsc`, `mFmtTime`. Render in `#m-oggi-root`. Gestisci stato vuoto (`.m-empty`). Step 3: jinja compile + `node --check` dello script estratto. Step 4: commit `feat(mobile): schermata Oggi`.

### Task 6: Timbra
**Endpoint:** `GET /hr/api/punches` (storico + stato), `POST /hr/api/punches` (toggle in/out — leggi i campi form richiesti dalla route).
**Files:** Modify `app/templates/mobile/timbra.html`.

- [ ] Leggi la route punches (GET shape + POST params: tipo in/out, eventuale user/resource — la route timbra l'utente loggato). Schermata: bottone grande IN/OUT (stato corrente derivato dall'ultimo punch), al tap POST → ricarica; lista timbrature recenti (data/ora, tipo). `node --check`, jinja compile, commit `feat(mobile): schermata Timbratura`.

### Task 7: Notifiche
**Endpoint:** `GET /notifications/api/list`, `POST /notifications/api/{id}/read`, `POST /notifications/api/mark-all-read`.
**Files:** Modify `app/templates/mobile/notifiche.html`.

- [ ] Lista notifiche (titolo/testo/data, non lette evidenziate), tap → segna letto, bottone "segna tutte lette". Leggi i campi dalla route list. jinja + node-check, commit `feat(mobile): schermata Notifiche`.

### Task 8: Assegnazioni + endpoint respond (accetta/rifiuta)
**Files:** Modify `app/templates/mobile/assegnazioni.html`, `app/routers/planning.py` (+ eventuale modello/auto-migrate); Test `tests/test_booking_respond.py`.

- [ ] **Step 1 — Investiga**: leggi `GET /planning/api/my-bookings` (campi) e il modello `BookingAssignment` in `app/models/models.py`. Verifica se esiste già un campo/endpoint per la risposta dello staff (accept/reject). Cerca attorno a `booking-requests` e agli stati assignment.
- [ ] **Step 2 — Endpoint respond** (se non esiste): aggiungi a `planning.py`:
```python
@router.post("/api/my-bookings/{booking_id}/respond")
async def respond_my_booking(booking_id: int, request: Request, action: str = Form(...), db: Session = Depends(get_db)):
    """Staff accetta/rifiuta la PROPRIA assegnazione. 403 se il booking non è
    assegnato a una Resource dell'utente loggato."""
    # 1) risolvi user loggato (current_user_optional) + le sue Resource
    # 2) verifica che il booking abbia un BookingAssignment con resource dell'utente → else 403
    # 3) action in {accept, reject} → setta lo stato risposta sull'assignment (campo esistente o nuovo response_status)
    # 4) commit + ritorna {ok, status}
```
Se il modello `BookingAssignment` NON ha un campo per la risposta, aggiungi `response_status: Mapped[Optional[str]]` (es. "accepted"/"rejected"/null) + entry in `_auto_migrate_columns` (`main.py`) per la tabella assignments (pattern idempotente esistente).
- [ ] **Step 3 — Test** (`tests/test_booking_respond.py`): chiamando la coroutine `respond_my_booking` con db fixture + monkeypatch `current_user_optional`: accept del proprio booking → status accepted; reject → rejected; booking di altra resource → HTTPException 403. (Costruisci Tenant/User/Resource/Job/Booking/BookingAssignment minimi.)
- [ ] **Step 4 — UI** `assegnazioni.html`: lista mie assegnazioni per giorno; ogni card con bottoni Accetta/Rifiuta → `POST /planning/api/my-bookings/{id}/respond` (form `action`), refresh; mostra lo stato risposta. Leggi i campi da my-bookings.
- [ ] **Step 5**: pytest (targeted + full), jinja + node-check, commit `feat(mobile): schermata Assegnazioni + endpoint respond accetta/rifiuta`.

### Task 9: Ferie
**Endpoint:** `GET /planning-unavailabilities/my-unavailabilities`, `POST /planning-unavailabilities/unavailabilities` (leggi i campi form richiesti: date/tipo/note).
**Files:** Modify `app/templates/mobile/ferie.html`.

- [ ] Lista mie richieste (periodo, tipo, stato approvazione); form "nuova richiesta" (date da/a + tipo + note) → POST → refresh. Leggi i campi richiesti dalla route POST. jinja + node-check, commit `feat(mobile): schermata Ferie`.

---

## Phase 2 — Verifica E2E

### Task 10: Smoke E2E mobile
- [ ] Restart server pulito (`avvia_muto.bat` o uvicorn :PORT). Login. Visita `/m`, `/m/timbra`, `/m/assegnazioni`, `/m/ferie`, `/m/notifiche` → 200; `/static/manifest.json` 200; `/static/sw.js` 200. Senza cookie → `/m` redirige a `/auth/login`. Full pytest verde. (DevTools mobile / Lighthouse PWA installabilità = verifica manuale lato Matteo.)

---

## Self-Review (autore)
- **Spec coverage**: D1 staff→tutte le schermate; D2 /m dedicata→Task1; D3 PWA→Task4; D4 entry esplicito (no auto-redirect)→nessun redirect UA, solo middleware auth. §5 schermate→Task5-9; §6 respond→Task8; §7 sicurezza→respond 403 + endpoint user-scoped; §9 test→ogni task + Task10.
- **Placeholder**: le render JS per-schermata rimandano alla lettura dei campi dell'endpoint esistente (contratto già nel codice) — è codebase-reading legittimo, non logica mancante; struttura/skeleton forniti. Scaffold/PWA hanno codice completo.
- **Consistency**: route `/m/*` (Task1) == tab bar href (base_mobile) == smoke (Task10). `mapi`/`mEsc`/`mFmtTime` definiti Task3, usati Task5-9. manifest `start_url=/m` == scope SW.

## Note esecuzione
- Scaffold Task1-4 sequenziali (stessi file base). Schermate Task5-9 indipendenti (file template distinti) ma Task8 tocca planning.py/models → sequenziale rispetto ad altri che toccano planning.
- A fine: bump versione + CHANGELOG + STATO + ZIP/push come da convenzione.
