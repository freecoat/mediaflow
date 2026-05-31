# Mobile v2 · Fase A (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dare al mobile (`/m`) un look curato (dark Claqo affinato) e una navigazione a **drawer laterale** scalabile, sostituendo la bottom tab bar v1 — senza aggiungere nuove schermate-entità (quelle sono Fase B-D).

**Architecture:** Rifattorizzare `base_mobile.html` (header con ☰ + drawer + overlay + icone lucide) e `mobile.css` (design system: tokens + componenti rifiniti, PRESERVANDO i nomi-classe usati dal render JS delle 5 schermate). `mobile.js` guadagna gli helper drawer open/close + init lucide. Le 5 schermate esistenti adottano lo stile via CSS (ritocchi JS minimi solo per icone). Spec: `docs/superpowers/specs/2026-05-31-mobile-v2-faseA-foundation-design.md`.

**Tech Stack:** Jinja2 + vanilla JS + CSS (no framework), lucide (vendored `static/js/lucide.min.js`), pytest. Venv `.venv/Scripts/python.exe`. **La qualità visiva (Task 2) usa la skill `frontend-design`.** Cache-buster `?v={{ app_version }}`.

**Vincolo iniziativa:** editor pesanti (righe quote, timeline drag, listino) restano desktop.

---

## File map
- `app/templates/mobile/base_mobile.html` — MODIFICA: header(☰)+drawer+overlay, lucide load+init, rimossa bottom tab bar.
- `app/static/js/mobile.js` — MODIFICA: helper `mDrawerOpen/Close/Toggle` + init lucide + wiring.
- `app/static/css/mobile.css` — REWRITE: design system (tokens + componenti + drawer), preserva nomi-classe.
- `app/templates/mobile/{oggi,timbra,assegnazioni,ferie,notifiche}.html` — ritocchi minimi (icone lucide nei render dove c'erano emoji; struttura invariata).
- `tests/test_mobile.py` — MODIFICA: smoke markup drawer.

---

## Task 1: Drawer navigation (base_mobile.html + mobile.js)

**Files:** Modify `app/templates/mobile/base_mobile.html`, `app/static/js/mobile.js`, `tests/test_mobile.py`.

- [ ] **Step 1: Failing smoke test** (append to `tests/test_mobile.py`)

```python
def test_base_mobile_has_drawer_markup():
    html = open("app/templates/mobile/base_mobile.html", encoding="utf-8").read()
    # header con hamburger che apre il drawer
    assert "m-drawer" in html
    assert "m-drawer-overlay" in html
    assert "mDrawerToggle" in html or "mDrawerOpen" in html
    # le 5 voci operative nel drawer
    for label in ("Oggi", "Timbr", "Assegnazion", "Ferie", "Notifich"):
        assert label in html
    # lucide caricato + init
    assert "lucide" in html
    # bottom tab bar v1 rimossa
    assert "m-tabbar" not in html


def test_mobile_js_has_drawer_helpers():
    js = open("app/static/js/mobile.js", encoding="utf-8").read()
    assert "mDrawerToggle" in js or "mDrawerOpen" in js
```

- [ ] **Step 2: Run → FAIL** (`.venv/Scripts/python.exe -m pytest tests/test_mobile.py -q`).

- [ ] **Step 3: Rewrite `base_mobile.html`** — header con ☰ + drawer + overlay + lucide, niente tab bar:

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
    <button class="m-top-burger" aria-label="Menu" onclick="mDrawerToggle()"><i data-lucide="menu"></i></button>
    <span class="m-top-title">{% block topbar %}Claqo{% endblock %}</span>
    <a class="m-top-action" href="/m/notifiche" aria-label="Notifiche"><i data-lucide="bell"></i></a>
  </header>

  <div class="m-drawer-overlay" id="m-drawer-overlay" onclick="mDrawerClose()"></div>
  <aside class="m-drawer" id="m-drawer" aria-hidden="true">
    <div class="m-drawer-head">
      <span class="m-drawer-brand">Claqo</span>
      {% if user %}<span class="m-drawer-user">{{ user.full_name or user.email }}</span>{% endif %}
    </div>
    <nav class="m-drawer-nav">
      <div class="m-drawer-group">Operativo</div>
      <a href="/m"               class="m-drawer-item {% if active=='oggi' %}active{% endif %}"><i data-lucide="home"></i>Oggi</a>
      <a href="/m/assegnazioni"  class="m-drawer-item {% if active=='assegnazioni' %}active{% endif %}"><i data-lucide="clipboard-list"></i>Assegnazioni</a>
      <a href="/m/timbra"        class="m-drawer-item {% if active=='timbra' %}active{% endif %}"><i data-lucide="clock"></i>Timbratura</a>
      <a href="/m/ferie"         class="m-drawer-item {% if active=='ferie' %}active{% endif %}"><i data-lucide="palmtree"></i>Ferie</a>
      <a href="/m/notifiche"     class="m-drawer-item {% if active=='notifiche' %}active{% endif %}"><i data-lucide="bell"></i>Notifiche</a>
    </nav>
    <a class="m-drawer-logout" href="/auth/logout"><i data-lucide="log-out"></i>Esci</a>
  </aside>

  <main class="m-main" id="m-main">
    {% block content %}{% endblock %}
  </main>

  <script src="/static/js/lucide.min.js?v={{ app_version }}"></script>
  <script>
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => navigator.serviceWorker.register('/static/sw.js').catch(()=>{}));
    }
  </script>
  <script src="/static/js/mobile.js?v={{ app_version }}"></script>
  <script>
    document.addEventListener('keydown', e => { if (e.key === 'Escape') mDrawerClose(); });
    if (window.lucide && lucide.createIcons) lucide.createIcons();
  </script>
  {% block scripts %}{% endblock %}
</body>
</html>
```
> NB: verifica il path/route di logout esistente (grep `logout` in `app/routers/auth.py`); usa quello reale (`/auth/logout` o simile). Verifica che `lucide.min.js` esponga `window.lucide` con `createIcons` (la build vendored lo fa). Se l'init globale non basta dopo i render dinamici, le pagine richiameranno `lucide.createIcons()` dopo aver inserito icone (Task 3).

- [ ] **Step 4: Add drawer helpers to `mobile.js`** (append):

```javascript
function mDrawerOpen() {
  document.getElementById('m-drawer')?.classList.add('open');
  document.getElementById('m-drawer-overlay')?.classList.add('open');
  document.body.classList.add('m-no-scroll');
}
function mDrawerClose() {
  document.getElementById('m-drawer')?.classList.remove('open');
  document.getElementById('m-drawer-overlay')?.classList.remove('open');
  document.body.classList.remove('m-no-scroll');
}
function mDrawerToggle() {
  document.getElementById('m-drawer')?.classList.contains('open') ? mDrawerClose() : mDrawerOpen();
}
```

- [ ] **Step 5: Run tests → PASS.** Jinja compile base_mobile + 5 pagine (`.venv/Scripts/python.exe -c "from jinja2 import Environment, FileSystemLoader; e=Environment(loader=FileSystemLoader('app/templates')); [e.get_template('mobile/'+t+'.html') for t in ('base_mobile','oggi','timbra','assegnazioni','ferie','notifiche')]; print('OK')"`). `node --check app/static/js/mobile.js`.

- [ ] **Step 6: Commit**
```bash
git add app/templates/mobile/base_mobile.html app/static/js/mobile.js tests/test_mobile.py
git commit -m "feat(mobile): drawer nav (header+☰+overlay+lucide) sostituisce tab bar"
```

---

## Task 2: Design system — `mobile.css` v2 (USA skill frontend-design)

**Files:** Rewrite `app/static/css/mobile.css`.

**IMPORTANTE**: questo task è di **qualità visiva** → l'implementer DEVE usare la skill **`frontend-design`** (evita aesthetic generica). Vincoli: dark Claqo (`#6272f5`), touch-first (≥44px), CSS leggero (no framework), brand-consistent col desktop.

- [ ] **Step 1: Leggi** l'attuale `app/static/css/mobile.css` (419 righe v1) per i nomi-classe esistenti, e le 5 pagine + i loro render JS per quali classi consumano (`.m-card`, `.m-card-title`, `.m-list`, `.m-list-item`, `.m-empty`, `.m-loading`, `.m-badge*`, `.m-btn*`, `.m-section`, `.m-form-*`, `.m-toast`). E il nuovo markup drawer di Task 1 (`.m-top`, `.m-top-burger`, `.m-top-title`, `.m-top-action`, `.m-drawer`, `.m-drawer-overlay`, `.m-drawer-head/brand/user`, `.m-drawer-nav`, `.m-drawer-group`, `.m-drawer-item`, `.m-drawer-item.active`, `.m-drawer-logout`, `.m-no-scroll`).

- [ ] **Step 2: Rewrite `mobile.css`** come design system:
  - **Tokens** (`:root`): scala spaziatura (`--m-sp-1..5` = 4/8/12/16/24), raggi (`--m-r-1..3` = 8/12/16), ombre (`--m-shadow`, `--m-shadow-lg`), tipografia (`--m-fs-title/sub/body/cap`, weights), palette (bg `#0f1117`, bg2 `#171a23`, bg3, accent `#6272f5`, text, muted, border, danger/success/warn).
  - **Componenti rifiniti** (preservando i nomi-classe esistenti): header sticky con elevazione + ☰/azione; **drawer** (slide-in da sinistra `transform:translateX(-100%)`→`.open{translateX(0)}`, transizione, overlay fade, `z-index` corretti, larghezza ~78vw max 320, safe-area); card (elevazione, raggio, padding token); list-item (leading icon, trailing meta/chevron, divider, tap state); badge (varianti stato con colori semantici); button (primary/secondary/danger/ghost, sizes, tap feedback); form controls coerenti; loading **skeleton** + empty curati; toast rifinito; `.m-no-scroll{overflow:hidden}`; icone lucide sizing (`.m-drawer-item i, .m-top i {width:20px;height:20px}`); micro-interazioni (`:active` scale/opacity, transizioni 150-250ms).
  - Usa frontend-design per gerarchia, ritmo verticale, contrasto, polish. ~300-450 righe.

- [ ] **Step 3: Verify** — CSS parsa (braces bilanciate); il drawer ha gli stati `.open`; nessun nome-classe consumato dal JS è stato rimosso (grep i `.m-*` usati nelle 5 pagine e conferma che esistono in mobile.css).

- [ ] **Step 4: Commit**
```bash
git add app/static/css/mobile.css
git commit -m "feat(mobile): design system v2 (tokens, componenti rifiniti, drawer) [frontend-design]"
```

---

## Task 3: Polish schermate + icone + E2E

**Files:** Modify `app/templates/mobile/{oggi,timbra,assegnazioni,ferie,notifiche}.html` (ritocchi minimi).

- [ ] **Step 1: Leggi** le 5 pagine. Dove il render JS o il markup statico usa **emoji** o markup grezzo per icone/stati, sostituisci con icone lucide (`<i data-lucide="...">`) o badge `.m-badge*`, e richiama `lucide.createIcons()` DOPO aver inserito icone dinamiche nel DOM (così le icone nei contenuti fetchati vengono renderizzate). Mantieni DOM-safe (textContent/mEsc per i dati). NON cambiare la logica dati né le classi (solo presentazione/icone).

- [ ] **Step 2: Coerenza** — assicura che ogni pagina usi i componenti del design system (card/list/badge/skeleton al posto di "Caricamento…" grezzo dove sensato). Ritocchi minimi, non riscritture.

- [ ] **Step 3: Verify** — jinja compile delle 5 pagine; per ognuna estrai gli inline `<script>` e `node --check`.

- [ ] **Step 4: E2E smoke** (server di test su porta libera, es. 9100): login → `/m`, `/m/timbra`, `/m/assegnazioni`, `/m/ferie`, `/m/notifiche` → 200; asset (`/static/css/mobile.css`, `/static/js/mobile.js`, `/static/js/lucide.min.js`) → 200; HTML di `/m` contiene `m-drawer` + `data-lucide`. No-auth `/m` → redirect login. Spegni il server di test a fine.

- [ ] **Step 5: Commit**
```bash
git add app/templates/mobile/
git commit -m "feat(mobile): schermate adottano design system + icone lucide"
```

---

## Self-Review (autore)
- **Spec coverage**: §3 design system→T2; §4 drawer nav→T1; §5 applicazione 5 schermate→T3; A1 drawer→T1; A2 dark Claqo+lucide→T2/T3; §6 frontend-design→T2; §8 testing→T1(smoke)/T3(E2E). §9 decomposizione = contesto (fasi B-D fuori da questo piano). §7 fuori scope (nessuna entità nuova) → rispettato.
- **Placeholder**: T2 (CSS) demanda il polish a frontend-design con token-scaffold + lista componenti + vincoli espliciti — è qualità visiva, non logica mancante; i nomi-classe da preservare sono elencati. T1/T3 hanno markup/JS completi.
- **Consistency**: classi drawer in base_mobile (T1) == stili in mobile.css (T2) == verifica T2/T3. `mDrawerOpen/Close/Toggle` definiti T1, usati nel markup T1. `m-tabbar` rimosso (T1) ↔ test asserisce assenza.

## Note esecuzione
- T1→T2→T3 sequenziali (toccano base_mobile/mobile.css condivisi o dipendono dal markup di T1).
- T2 usa frontend-design; valutare modello capace per la qualità visiva.
- Verifica reale del look = manuale Matteo via tunnel (riavviare il server :9000 col nuovo codice dopo i commit).
- A fine Fase A: bump versione + CHANGELOG + STATO; poi Fase B (consultazione entità) come ciclo separato.
