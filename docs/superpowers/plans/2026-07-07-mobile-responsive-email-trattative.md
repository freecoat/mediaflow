# Mobile responsive — Sotto-fase A: email + trattative — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere raggiungibili e usabili al tocco su smartphone il client email `/mail` e la pipeline trattative `/acquisitions` (con la tab Email F2), rendendo responsive la shell desktop condivisa.

**Architecture:** Nessun modello/endpoint/migrazione nuovi. Si esentano `/mail` e `/acquisitions` dal redirect mobile, si rende viewport-aware il toggle sidebar (off-canvas su ≤768px, CSS già presente), si aggiungono media query per `/mail` (vista-stato colonna singola + compose full-screen) e `/acquisitions` (dettaglio full-screen + tab scrollabili + kanban snap), si linkano le due pagine dal drawer mobile.

**Tech Stack:** FastAPI (middleware), Jinja2, vanilla JS, CSS media query, pytest, Playwright.

## Global Constraints

- **Ramo:** `feat/mobile-responsive-email`. Nessun push finché Matteo non fa smoke.
- **Nessun modello/endpoint/migrazione nuovi.** Solo CSS/JS/template + 1 riga middleware.
- **Breakpoint mobile:** `@media (max-width: 768px)` (coerente con l'unico media query esistente in `main.css:1421`).
- **Cache-buster:** gli asset usano già `?v={{ app_version }}`; nessun nuovo file statico introdotto (CSS in `<style>` di template o in `main.css`).
- **Helper JS globali** (`escapeHtml`, `api`, `toast`, `mfT`, `mfToggleSidebar`) da `global.js`/`mail.js`, non ridefiniti. No `JSON.stringify` in onclick.
- **Drawer mobile IT-only:** `base_mobile.html` non carica `i18n.js` e le voci esistenti sono hardcoded in italiano; le nuove voci seguono lo stesso pattern (nessun `data-i18n`). Le pagine esentate `/mail`/`/acquisitions` sono già i18n desktop.
- **Interprete test:** `.venv/Scripts/python.exe -m pytest ...`. Commit via `git commit -F <file>` (heredoc bloccato da hook; `printf` in bash).
- **Versione:** `3.5.0-alpha.172.245` → `.246` (Task 6).
- **Smoke server:** uvicorn SENZA reload, `127.0.0.1`, NON `APP_ENV=production`.

## File Structure

- `app/main.py` — `_MOBILE_REDIR_EXEMPT` (riga ~2527): aggiungere `/mail`, `/acquisitions`. Bump versione (riga ~2398).
- `app/static/js/global.js` — `mfToggleSidebar()` (riga ~1835): renderla viewport-aware (off-canvas su mobile).
- `app/templates/base.html` — aggiungere elemento backdrop off-canvas dopo la sidebar (riga ~57+).
- `app/static/css/main.css` — estendere il blocco `@media (max-width:768px)` (riga 1421) con backdrop + topbar compatta + safe-area.
- `app/templates/pages/mail.html` — spostare stili layout inline → `<style>` con classi; aggiungere regole responsive (vista-stato) + compose full-screen + barra mobile.
- `app/static/js/mail.js` — aggiungere `mailMobileView(view)`; hook in apertura thread e selezione etichetta.
- `app/templates/pages/acquisitions.html` — aggiungere blocco `@media (max-width:768px)` (dopo riga 152) per dettaglio full-screen + tab scrollabili + kanban snap.
- `app/templates/mobile/base_mobile.html` — nuovo gruppo drawer "Commerciale" con link Email + Trattative.
- `tests/test_mobile.py` — test esenzione redirect + presenza link drawer.
- `tests/test_mail_page.py` — test responsive mail (se esiste; altrimenti creare asserzioni nel file esistente).

---

### Task 1: Esenzione redirect mobile per `/mail` e `/acquisitions`

**Files:**
- Modify: `app/main.py` (`_MOBILE_REDIR_EXEMPT`, riga ~2527)
- Test: `tests/test_mobile.py`

**Interfaces:**
- Consumes: `app.main._MOBILE_REDIR_EXEMPT` (tupla di prefissi path esenti dal redirect mobile), `create_access_token` da `app.services.auth`.
- Produces: `/mail` e `/acquisitions` non più dirottati su `/m` per UA mobile.

- [ ] **Step 1: Write the failing tests**

Aggiungi in fondo a `tests/test_mobile.py`:

```python
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def test_mail_and_acquisitions_are_redirect_exempt():
    import app.main as m
    assert "/mail" in m._MOBILE_REDIR_EXEMPT
    assert "/acquisitions" in m._MOBILE_REDIR_EXEMPT


def _client_with_auth(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models.models import Base, Tenant, User, UserRole
    from app.services.auth import create_access_token
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", e)
    monkeypatch.setattr(database, "SessionLocal", S)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
               hashed_password="x", role=UserRole.admin, is_active=True))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    c = TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"})
    return c, main_mod, get_db


def test_mail_not_redirected_for_mobile_ua(monkeypatch):
    c, main_mod, get_db = _client_with_auth(monkeypatch)
    try:
        r = c.get("/mail", headers={"User-Agent": IPHONE_UA, "Accept": "text/html"},
                  follow_redirects=False)
        # esente: NON 302 verso /m (può essere 200)
        assert not (r.status_code == 302 and r.headers.get("location", "").startswith("/m"))
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)


def test_dashboard_still_redirected_for_mobile_ua(monkeypatch):
    c, main_mod, get_db = _client_with_auth(monkeypatch)
    try:
        r = c.get("/dashboard", headers={"User-Agent": IPHONE_UA, "Accept": "text/html"},
                  follow_redirects=False)
        assert r.status_code == 302 and r.headers.get("location", "").startswith("/m")
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mobile.py -v -k "exempt or mobile_ua"`
Expected: FAIL (`/mail` non in tupla → `test_..._exempt` fallisce; `/mail` redirette → `test_mail_not_redirected` fallisce).

- [ ] **Step 3: Add the exemptions**

In `app/main.py`, nella tupla `_MOBILE_REDIR_EXEMPT` (riga ~2527), aggiungi `"/mail"` e `"/acquisitions"`:

```python
_MOBILE_REDIR_EXEMPT = (
    "/m", "/static", "/auth", "/api", "/uploads", "/portal", "/health",
    "/favicon", "/docs", "/openapi", "/redoc", "/public",
    "/prefer-desktop", "/prefer-mobile", "/sw.js", "/manifest",
    "/mail", "/acquisitions",  # v.246 — isole desktop-responsive raggiungibili da telefono
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mobile.py -v -k "exempt or mobile_ua or dashboard"`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_mobile.py
git commit -F <msgfile>
# "feat(mobile): esenta /mail e /acquisitions dal redirect mobile (responsive A)"
```

---

### Task 2: Shell desktop responsive — toggle sidebar off-canvas + backdrop

**Files:**
- Modify: `app/static/js/global.js` (`mfToggleSidebar`, riga ~1835)
- Modify: `app/templates/base.html` (backdrop dopo la sidebar, riga ~57)
- Modify: `app/static/css/main.css` (blocco `@media (max-width:768px)`, riga 1421)
- Test: `tests/test_mobile.py` (presenza backdrop) + `node --check`

**Interfaces:**
- Consumes: `#sidebar`, `#mf-sidebar-toggle` (esistenti in base.html); classe CSS `.sidebar.open` (già in `main.css:1423`).
- Produces: `mfToggleSidebar()` viewport-aware; elemento `#mf-sidebar-backdrop`; funzione `mfCloseSidebarMobile()`.

- [ ] **Step 1: Write the failing test**

Aggiungi in `tests/test_mobile.py`:

```python
def test_base_has_sidebar_backdrop():
    html = open("app/templates/base.html", encoding="utf-8").read()
    assert 'id="mf-sidebar-backdrop"' in html


def test_global_toggle_is_viewport_aware():
    js = open("app/static/js/global.js", encoding="utf-8").read()
    assert "mfCloseSidebarMobile" in js
    assert "max-width:768px" in js.replace(" ", "") or "max-width: 768px" in js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mobile.py -v -k "backdrop or viewport"`
Expected: FAIL (backdrop assente, `mfCloseSidebarMobile` assente).

- [ ] **Step 3: Add backdrop element in base.html**

In `app/templates/base.html`, subito dopo la chiusura della sidebar `</aside>` (cerca `</aside>` che chiude `id="sidebar"`, ~riga 245), aggiungi:

```html
  <div class="mf-sidebar-backdrop" id="mf-sidebar-backdrop" onclick="mfCloseSidebarMobile()" aria-hidden="true"></div>
```

- [ ] **Step 4: Make `mfToggleSidebar` viewport-aware in global.js**

In `app/static/js/global.js`, sostituisci l'intera funzione `mfToggleSidebar()` (riga ~1835-1846) con:

```javascript
function mfToggleSidebar() {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  if (window.matchMedia && window.matchMedia('(max-width:768px)').matches) {
    // Mobile: off-canvas via classe .open + backdrop
    const open = !sb.classList.contains('open');
    sb.classList.toggle('open', open);
    const bd = document.getElementById('mf-sidebar-backdrop');
    if (bd) bd.classList.toggle('visible', open);
    return;
  }
  const collapsed = !sb.classList.contains('collapsed');
  sb.classList.toggle('collapsed', collapsed);
  document.body.classList.toggle('sidebar-collapsed', collapsed);
  try { localStorage.setItem('mf_sidebar_collapsed', collapsed ? '1' : '0'); } catch (_) {}
  _mfUpdateSidebarToggleIcon(collapsed);
  const tip = document.getElementById('mf-sidebar-tip');
  if (tip) tip.classList.remove('visible');
}
function mfCloseSidebarMobile() {
  const sb = document.getElementById('sidebar');
  if (sb) sb.classList.remove('open');
  const bd = document.getElementById('mf-sidebar-backdrop');
  if (bd) bd.classList.remove('visible');
}
```

- [ ] **Step 5: Add CSS in main.css**

In `app/static/css/main.css`, sostituisci il blocco `@media (max-width: 768px)` (righe 1421-1427) con:

```css
@media (max-width: 768px) {
  .sidebar {
    transform: translateX(-100%);
    position: fixed; top: 0; left: 0; height: 100dvh; z-index: 1200;
    transition: transform .2s ease;
  }
  .sidebar.open { transform: none; }
  .main-area { margin-left: 0; }
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
  .form-row { grid-template-columns: 1fr; }
  .mf-sidebar-backdrop {
    position: fixed; inset: 0; background: rgba(0,0,0,.45);
    z-index: 1150; opacity: 0; pointer-events: none; transition: opacity .2s ease;
  }
  .mf-sidebar-backdrop.visible { opacity: 1; pointer-events: auto; }
  .topbar { padding-left: max(10px, env(safe-area-inset-left)); padding-right: max(10px, env(safe-area-inset-right)); }
  .topbar-title { font-size: 15px; }
}
.mf-sidebar-backdrop { display: none; }
@media (max-width: 768px) { .mf-sidebar-backdrop { display: block; } }
```

- [ ] **Step 6: Verify JS syntax + tests**

Run: `node --check app/static/js/global.js` → nessun errore.
Run: `.venv/Scripts/python.exe -m pytest tests/test_mobile.py -v -k "backdrop or viewport"`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add app/static/js/global.js app/templates/base.html app/static/css/main.css tests/test_mobile.py
git commit -F <msgfile>
# "feat(mobile): shell desktop responsive - sidebar off-canvas + backdrop (responsive A)"
```

---

### Task 3: `/mail` responsive — vista-stato colonna singola + compose full-screen

**Files:**
- Modify: `app/templates/pages/mail.html` (stili inline → `<style>`; markup barra mobile)
- Modify: `app/static/js/mail.js` (`mailMobileView`; hook)
- Test: `tests/test_mail_page.py` + `node --check`

**Interfaces:**
- Consumes: `.mail-layout/.mail-nav/.mail-list/.mail-reading`, `#mail-compose`, `mfMailOpenThread`, `mfMailLoadThreads` (esistenti).
- Produces: attributo `data-mail-view` su `.mail-layout` ∈ {`list`,`read`,`labels`}; globale `mailMobileView(view)`; markup `#mail-mobile-bar` con bottoni "☰ Etichette" e "← Indietro".

- [ ] **Step 1: Write the failing test**

Crea/estendi `tests/test_mail_page.py` con:

```python
import pathlib


def test_mail_layout_uses_classes_not_inline_grid():
    html = pathlib.Path("app/templates/pages/mail.html").read_text(encoding="utf-8")
    # la griglia NON deve più stare inline (serve override responsive)
    assert "grid-template-columns:200px 320px 1fr" not in html.replace(" ", "")
    assert 'data-mail-view' in html or 'mailMobileView' in html
    assert 'id="mail-mobile-bar"' in html


def test_mail_js_has_mobile_view():
    src = pathlib.Path("app/static/js/mail.js").read_text(encoding="utf-8")
    assert "mailMobileView" in src


def test_mail_has_responsive_style_block():
    html = pathlib.Path("app/templates/pages/mail.html").read_text(encoding="utf-8")
    assert "@media" in html and "max-width" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mail_page.py -v`
Expected: FAIL (griglia ancora inline, `mailMobileView` assente).

- [ ] **Step 3: Refactor mail.html — stili in `<style>`, markup mobile**

Sostituisci le righe 3-14 di `app/templates/pages/mail.html` (il `<div class="mail-layout" style="...">` fino al `</div>` di chiusura layout) con:

```html
<div id="mail-mobile-bar" class="mail-mobile-bar">
  <button class="btn btn-secondary btn-sm" id="mail-mb-labels" onclick="mailMobileView('labels')">☰ Etichette</button>
  <button class="btn btn-secondary btn-sm" id="mail-mb-back" onclick="mailMobileView('list')">← Indietro</button>
</div>
<div class="mail-layout" data-mail-view="list">
  <aside class="mail-nav">
    <button class="btn btn-primary btn-block" onclick="mfMailCompose()" data-i18n="mail.compose">Scrivi</button>
    <div id="mail-labels" class="mail-labels"></div>
  </aside>
  <section class="mail-list">
    <input id="mail-search" class="form-input" data-i18n-attr="placeholder" data-i18n="mail.search"
           placeholder="Cerca nella posta…" onkeydown="if(event.key==='Enter')mfMailLoadThreads(true)">
    <div id="mail-thread-list" class="mail-thread-list"></div>
  </section>
  <section id="mail-reading" class="mail-reading"></section>
</div>
```

Poi, subito prima di `<script src="/static/js/mail.js...` (riga ~32), inserisci il blocco stile:

```html
<style>
  .mail-layout { display: grid; grid-template-columns: 200px 320px 1fr; gap: 12px; height: calc(100vh - 120px); }
  .mail-nav { display: flex; flex-direction: column; }
  .mail-labels { display: flex; flex-direction: column; gap: 4px; margin-top: 12px; }
  .mail-list { display: flex; flex-direction: column; gap: 8px; overflow: auto; }
  .mail-thread-list { display: flex; flex-direction: column; gap: 2px; }
  .mail-reading { overflow: auto; }
  .mail-mobile-bar { display: none; gap: 6px; margin-bottom: 8px; }
  @media (max-width: 768px) {
    .mail-mobile-bar { display: flex; }
    .mail-layout { grid-template-columns: 1fr; height: calc(100dvh - 150px); }
    /* default: mostra solo lista, nascondi nav e lettura */
    .mail-layout[data-mail-view="list"] .mail-nav,
    .mail-layout[data-mail-view="list"] .mail-reading { display: none; }
    .mail-layout[data-mail-view="read"] .mail-nav,
    .mail-layout[data-mail-view="read"] .mail-list { display: none; }
    .mail-layout[data-mail-view="labels"] .mail-list,
    .mail-layout[data-mail-view="labels"] .mail-reading { display: none; }
    /* "← Indietro" visibile solo in lettura; "☰ Etichette" solo in lista */
    .mail-layout[data-mail-view="read"] ~ * #mail-mb-back { display: inline-flex; }
    #mail-mb-back { display: none; }
    .mail-layout[data-mail-view="read"] #mail-mb-back { display: inline-flex; }
    #mail-compose .modal { position: fixed; inset: 0; min-width: 0 !important; max-width: none; width: 100vw; height: 100dvh; border-radius: 0; overflow: auto; }
  }
</style>
```

Nota: il selettore per mostrare "← Indietro" basato su `data-mail-view` può essere semplificato lato JS (Step 4 aggiorna direttamente lo stato); mantenere solo `#mail-mb-back { display:none }` di default e lasciare che `mailMobileView` gestisca la visibilità via classe sul bar. Vedi Step 4.

- [ ] **Step 4: Add `mailMobileView` in mail.js + hook**

In fondo a `app/static/js/mail.js`, aggiungi:

```javascript
function mailMobileView(view) {
  const layout = document.querySelector('.mail-layout');
  if (!layout) return;
  layout.setAttribute('data-mail-view', view);
  const back = document.getElementById('mail-mb-back');
  const labelsBtn = document.getElementById('mail-mb-labels');
  if (back) back.style.display = (view === 'read') ? 'inline-flex' : 'none';
  if (labelsBtn) labelsBtn.style.display = (view === 'read') ? 'none' : 'inline-flex';
}
```

Nel corpo di `mfMailOpenThread(threadId)` (dove parte l'apertura del thread, riga ~64), come prima istruzione aggiungi:

```javascript
  mailMobileView('read');
```

Nel click handler globale di `mail.js` sul ramo `data-label` (dove imposta `_mailLabel` e chiama `mfMailLoadThreads(true)`, riga ~125), subito dopo, aggiungi:

```javascript
    mailMobileView('list');
```

- [ ] **Step 5: Run test + JS syntax**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mail_page.py -v`
Expected: PASS (3 passed).
Run: `node --check app/static/js/mail.js` → nessun errore.

- [ ] **Step 6: Commit**

```bash
git add app/templates/pages/mail.html app/static/js/mail.js tests/test_mail_page.py
git commit -F <msgfile>
# "feat(mobile): /mail responsive - vista-stato colonna singola + compose full-screen (responsive A)"
```

---

### Task 4: `/acquisitions` responsive — dettaglio full-screen + tab scrollabili + kanban snap

**Files:**
- Modify: `app/templates/pages/acquisitions.html` (blocco `@media`, dopo riga 152)
- Test: `tests/test_acquisitions_page.py` (creare) presenza CSS

**Interfaces:**
- Consumes: `.acq-detail-panel`, `.acq-det-tabs`, `.acq-kanban`, `.acq-kanban-col` (esistenti).
- Produces: regole `@media (max-width:768px)` che rendono il dettaglio full-screen overlay.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_acquisitions_page.py`:

```python
import pathlib


def test_acquisitions_has_mobile_media_query():
    html = pathlib.Path("app/templates/pages/acquisitions.html").read_text(encoding="utf-8")
    assert "max-width: 768px" in html
    # dettaglio full-screen su mobile
    assert "position: fixed" in html


def test_acquisitions_tabs_scrollable_mobile():
    html = pathlib.Path("app/templates/pages/acquisitions.html").read_text(encoding="utf-8")
    # la barra tab deve poter scorrere in orizzontale su mobile
    assert "overflow-x" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisitions_page.py -v`
Expected: FAIL (`max-width: 768px` e `position: fixed` assenti; il file ha solo `@media (max-width: 900px)`).

- [ ] **Step 3: Add mobile CSS block**

In `app/templates/pages/acquisitions.html`, subito dopo il blocco `@media (max-width: 900px) { ... }` (riga 149-152) e prima di `</style>` (riga 153), aggiungi:

```css
@media (max-width: 768px) {
  .acq-detail-panel {
    position: fixed; inset: 0; width: 100vw; height: 100dvh; max-height: none;
    border-radius: 0; z-index: 1300; padding: 14px; overflow-y: auto;
  }
  .acq-det-tabs { overflow-x: auto; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; }
  .acq-det-tab { flex: 0 0 auto; white-space: nowrap; }
  .acq-kanban { scroll-snap-type: x mandatory; }
  .acq-kanban-col { min-width: 78vw; scroll-snap-align: start; }
  .acq-detail-actions .btn, .acq-det-tab { min-height: 40px; }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisitions_page.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/acquisitions.html tests/test_acquisitions_page.py
git commit -F <msgfile>
# "feat(mobile): /acquisitions responsive - dettaglio full-screen + tab scroll + kanban snap (responsive A)"
```

---

### Task 5: Link drawer mobile → Email + Trattative

**Files:**
- Modify: `app/templates/mobile/base_mobile.html` (nuovo gruppo "Commerciale")
- Test: `tests/test_mobile.py`

**Interfaces:**
- Consumes: pattern `.m-drawer-group` + `.m-drawer-item` (esistenti in base_mobile.html).
- Produces: link `/mail` e `/acquisitions` nel drawer mobile.

- [ ] **Step 1: Write the failing test**

Aggiungi in `tests/test_mobile.py`:

```python
def test_drawer_has_commerciale_links():
    html = open("app/templates/mobile/base_mobile.html", encoding="utf-8").read()
    assert 'href="/mail"' in html
    assert 'href="/acquisitions"' in html
    assert "Commerciale" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mobile.py -v -k commerciale`
Expected: FAIL (link e gruppo assenti).

- [ ] **Step 3: Add drawer group in base_mobile.html**

In `app/templates/mobile/base_mobile.html`, subito dopo il gruppo `Business` (dopo la riga del link `/m/cerca`, riga ~40) e prima di `<div class="m-drawer-group">Storage</div>` (riga 41), inserisci:

```html
      <div class="m-drawer-group">Commerciale</div>
      <a href="/mail"          class="m-drawer-item"><i data-lucide="mail"></i>Email</a>
      <a href="/acquisitions"  class="m-drawer-item"><i data-lucide="trending-up"></i>Trattative</a>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mobile.py -v -k commerciale`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add app/templates/mobile/base_mobile.html tests/test_mobile.py
git commit -F <msgfile>
# "feat(mobile): link Email + Trattative nel drawer mobile (responsive A)"
```

---

### Task 6: Chiusura fase — bump + suite + smoke browser + docs

**Files:**
- Modify: `app/main.py` (`.245` → `.246`), `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: Bump**

`app/main.py` (riga ~2398): `version="3.5.0-alpha.172.245"` → `"3.5.0-alpha.172.246"`.

- [ ] **Step 2: CHANGELOG** (nuova voce in cima)

```markdown
## v3.5.0-alpha.172.246 — Mobile responsive Sotto-fase A: email + trattative (7 lug 2026)

- **Client email `/mail` e pipeline `/acquisitions` raggiungibili e usabili da smartphone**: esentate dal redirect mobile (isole desktop-responsive), linkate dal drawer `/m` (gruppo "Commerciale").
- **Shell desktop responsive** (`base.html`/`main.css`, ≤768px): sidebar off-canvas con backdrop, `mfToggleSidebar()` viewport-aware, topbar compatta + safe-area. Fondamenta riusabili per le prossime sotto-fasi mobile.
- **`/mail` colonna singola**: vista-stato Etichette/Lista/Lettura (`mailMobileView`), barra "☰ Etichette"/"← Indietro", compose full-screen. Riusa le API `/mail/api/*`.
- **`/acquisitions` touch**: dettaglio trattativa full-screen, tab (incl. **Email** F2) scrollabili, kanban con scroll-snap. Porta su mobile la pipeline CRM completa.
- Nessun modello/endpoint/migrazione nuovi. Prima delle sotto-fasi mobile (B = calendario/documenti).
```

- [ ] **Step 3: STATO** — versione → `.246`; sezione `### α.172.246 ✅ (Mobile responsive Sotto-fase A — email + trattative — 7 lug)` coi punti sopra; **Prossimo step** → smoke Matteo su telefono reale + Sotto-fase mobile B (Calendario `/calendar` + Documenti Drive responsive). Ramo `feat/mobile-responsive-email` NON pushato.

- [ ] **Step 4: Full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tutti verdi (1152 + ~12 nuovi).

- [ ] **Step 5: Smoke browser (Playwright, viewport mobile)**

Avvia uvicorn no-reload su `127.0.0.1:8099`. Login `admin@mediaflow.it`/`admin123`. Con viewport 390×844:
- `/mail`: se senza opt-in Gmail → CTA "Collega Gmail" (ok). Se con dati: layout colonna singola, apri un thread → vista lettura con "← Indietro" → torna a lista; "☰ Etichette" apre le etichette; compose → full-screen.
- `/acquisitions`: apri una trattativa → dettaglio full-screen; scorri le tab → **Email**; incolla link Gmail (`https://mail.google.com/mail/u/0/#inbox/TESTID`) → **Aggancia** → compare in lista + Activity "email"; chiudi con ×.
- Shell: hamburger apre/chiude sidebar off-canvas + backdrop; click su link chiude.
- 0 errori console. Chiudi il server.

- [ ] **Step 6: Commit**

```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -F <msgfile>
# "chore(mobile): Mobile responsive Sotto-fase A v3.5.0-alpha.172.246"
```

---

## Self-Review

**1. Spec coverage:**
- Shell responsive generica (base.html) → Task 2 ✓
- `/mail` responsive (vista-stato + compose full-screen) → Task 3 ✓
- `/acquisitions` responsive (dettaglio full-screen + tab + kanban) → Task 4 ✓
- Esenzione redirect `/mail`+`/acquisitions` → Task 1 ✓
- Link drawer mobile → Task 5 ✓
- i18n: il drawer mobile è IT-only per convenzione del file (nessun `i18n.js` caricato); le pagine esentate sono già i18n desktop → Global Constraints ✓
- Bump/CHANGELOG/STATO + suite + smoke → Task 6 ✓
- Fuori scope (calendario/documenti/notifiche push) → non pianificati, coerente con la spec ✓

**2. Placeholder scan:** nessun TBD/TODO. Ogni step ha codice concreto e comandi con output atteso.

**3. Type consistency:**
- `mfToggleSidebar()` (Task 2) + `mfCloseSidebarMobile()` (Task 2, usato dall'onclick del backdrop) — coerenti.
- `mailMobileView(view)` (Task 3) — stesso nome in impl, hook e test.
- `data-mail-view` valori {`list`,`read`,`labels`} — coerenti tra CSS (Task 3 Step 3) e JS (Task 3 Step 4).
- `_MOBILE_REDIR_EXEMPT` (Task 1) — nome esatto da `main.py`.
- Classi CSS `.acq-detail-panel/.acq-det-tabs/.acq-kanban/.acq-kanban-col` (Task 4) — verificate in `acquisitions.html:43,101,112`.

## Note

- Il selettore CSS per "← Indietro" nel blocco `<style>` di Task 3 Step 3 è ridondante: la visibilità è gestita in modo autorevole da `mailMobileView` (Task 3 Step 4) via `style.display`. Lasciare solo `#mail-mb-back { display:none }` come default; l'implementatore può omettere il selettore `~ *` complicato.
- Task 4: `/acquisitions` esente porta l'intera pipeline su mobile — atteso (bonus "anche manager"); la tab Email F2 è il target primario di questa sotto-fase.
- Dopo le modifiche: `graphify update .`.
