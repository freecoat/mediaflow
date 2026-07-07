# Mobile responsive — Sotto-fase A: email + trattative — Design

> Data: 2026-07-07 · Ramo previsto: `feat/mobile-responsive-email` · Versione: `3.5.0-alpha.172.245` → `.246`

## Contesto e obiettivo

MediaFlow ha due UI: desktop (`base.html`, sidebar fissa) e una PWA mobile server-rendered sotto `/m/*` (drawer + topbar mobile, dati via API desktop). Un middleware in `main.py` (`mobile_force_view`) dirotta ogni navigazione HTML da smartphone (UA match) verso `/m`, salvo route esenti (`_MOBILE_REDIR_EXEMPT`) o cookie `prefer_desktop=1`.

Le funzioni arrivate dopo la v2 mobile (fine maggio 2026) NON sono su mobile:
- Client email `/mail` (webmail Gmail, α.244)
- Email trattative `EmailLink`/pin nella tab Email di `/acquisitions` (α.245)
- Acquisizioni CRM pipeline (α.236/237), Calendario (α.240), Documenti Drive (α.243)

**Obiettivo di questa sotto-fase**: portare su mobile **client email + email trattative**. Il resto (Calendario, Documenti, pipeline CRM completa) sono sotto-fasi successive con spec propri.

## Decisioni prese (brainstorming 7 lug)

1. **Incrementale**: email prima; le altre 4 aree come sotto-fasi separate (spec+plan+commit ciascuna).
2. **Mobile diventa anche strumento da manager** (email, trattative), non solo staff operativo.
3. **Approccio responsive, non native**: NON si duplica l'UI email in `/m/mail`; si rende responsive la shell desktop + `/mail` + `/acquisitions`.
4. **Esenzione redirect**: `/mail` e `/acquisitions` esenti dal redirect mobile → raggiungibili da telefono come "isole" desktop-responsive; tutto il resto continua a rimbalzare su `/m`.
5. **Shell responsive generica** su `base.html` (fondamenta riusabili), non CSS mirato alle 2 pagine.
6. **Client email completo**: lettura + compose (nuovo/rispondi/rispondi-tutti/inoltra/bozze/allegati) + F2 (assegna a trattativa, pin, anteprima, estrai-AI).

## Architettura

Nessun nuovo modello, nessun endpoint nuovo, nessuna migrazione DB. Il lavoro è: (a) CSS responsive, (b) piccoli refactor template per spostare stili inline in classi CSS ridefinibili, (c) JS minimale per lo stato-vista mobile di `/mail`, (d) una riga di esenzione nel middleware, (e) link nel drawer mobile, (f) i18n + versioning.

Breakpoint mobile: **`@media (max-width: 768px)`** (coerente con l'unico media query esistente in `main.css`). I telefoni reali (360–430px) sono il target primario; tablet portrait rientrano.

### Componente 1 — Shell desktop responsive (`base.html` + `main.css`)

Struttura attuale: `.app-shell` > `.sidebar#sidebar` + `.main-area` > `.topbar` + contenuto. Esiste già `mfToggleSidebar()` (collapse Ctrl+B) e l'hamburger `#mf-sidebar-toggle`.

Su `≤768px`:
- `.sidebar` → `position:fixed; top:0; left:0; height:100dvh; transform:translateX(-100%); transition:transform .2s; z-index alto`. Classe `.sidebar.mf-open` → `translateX(0)`. Backdrop `.mf-sidebar-backdrop` (nuovo elemento o `::after` su `.app-shell`) cliccabile per chiudere.
- L'hamburger `#mf-sidebar-toggle` su mobile apre/chiude l'off-canvas (toggle classe `mf-open` + backdrop) invece del collapse desktop. `mfToggleSidebar()` diventa viewport-aware: `if (matchMedia('(max-width:768px)').matches) { off-canvas } else { collapse }`.
- `.main-area` full-width (nessun margine sidebar); `.topbar` compatta con `flex-wrap`/overflow per le azioni secondarie; safe-area: `padding` con `env(safe-area-inset-*)`.
- Chiusura off-canvas su click di un link nav e su Escape.

Interfaccia: nessun cambiamento di API JS pubblica oltre a `mfToggleSidebar()` reso viewport-aware. Verificare che nessun altro chiamante di `mfToggleSidebar()` si rompa (grep).

### Componente 2 — `/mail` responsive (`mail.html` + `mail.css` + `mail.js`)

Struttura attuale: `.mail-layout` con `grid-template-columns:200px 320px 1fr` **inline**; tre figli `.mail-nav` (etichette), `.mail-list` (ricerca+thread), `.mail-reading`; compose in `#mail-compose.modal-overlay.hidden`.

Passi:
1. **Refactor stili inline → classi**: spostare `grid-template-columns`, `height`, `overflow` da `style="..."` inline a regole in `mail.css` sulle classi `.mail-layout/.mail-nav/.mail-list/.mail-reading`. (Gli stili inline vincono sul media query; vanno rimossi per permettere l'override responsive.) Nessun cambiamento funzionale desktop.
2. **Vista-stato mobile** (`≤768px`): una vista alla volta. Stato `data-mail-view` su `.mail-layout` ∈ {`list`,`read`,`labels`}. Default `list`.
   - `list`: mostra `.mail-list`, nasconde `.mail-nav` e `.mail-reading`. Barra superiore con bottone "☰ Etichette" (apre `labels`) + il campo ricerca.
   - Selezione thread (`mfMailOpenThread`) → imposta vista `read`, mostra `.mail-reading` con header "← Indietro" (torna a `list`).
   - `labels`: `.mail-nav` a tutta larghezza; selezione etichetta → torna `list`.
   - JS nuovo `mailMobileView(v)` (in `mail.js`) che imposta l'attributo; il CSS fa il resto. Su desktop l'attributo è ignorato (media query non attivo → griglia 3 colonne).
3. **Compose full-screen**: `#mail-compose` su `≤768px` → overlay a tutto schermo (`inset:0`, form scrollabile, azioni sticky in fondo). Allegati, bozze, invio invariati.
4. **Opt-in Gmail**: stessa CTA "Collega Gmail" quando `/mail/api/status` segnala scope mancante.

Interfaccia: `mailMobileView(view: 'list'|'read'|'labels')` globale; hook in `mfMailOpenThread` (set `read`) e nella selezione etichetta (set `list`). Nessuna modifica alle API di rete.

### Componente 3 — `/acquisitions` responsive (`acquisitions.html` + relativo CSS)

- **Kanban**: contenitore colonne → `overflow-x:auto; scroll-snap-type:x mandatory`; ogni colonna `min-width:80vw; scroll-snap-align:start`. Mantiene il feel a colonne swipe-abili. Vista Tabella → wrapper `overflow-x:auto`.
- **Pannello dettaglio** (`#acq-detail-panel`, oggi side-panel): su `≤768px` → full-screen overlay (`position:fixed; inset:0; z-index alto`), header con "×" già presente (`acqCloseDetail()`). Le tab (`.acq-det-tab`) in una barra `overflow-x:auto` scrollabile.
- **Tab Email (F2)**: già semplice (lista pin, ricerca, incolla-link, anteprima iframe sandbox, assegna, estrai-AI, 🗑). Solo adattamento CSS touch (bottoni ≥44px, input full-width). Nessuna logica nuova.
- La pipeline completa (KPI header, filtri) resta usabile; i filtri collassano in colonna su mobile.

### Componente 4 — Plumbing

1. **Esenzione redirect** (`main.py`): aggiungere `"/mail"` e `"/acquisitions"` a `_MOBILE_REDIR_EXEMPT`. La logica esistente (`path == p or path.startswith(p + "/")`) copre le sotto-route. Le API `/acquisitions/api/*` e `/mail/api/*` sono già escluse (Accept non-HTML + check `/api/`).
2. **Drawer mobile** (`base_mobile.html`): nuovo gruppo `Commerciale` con link **Email** → `/mail` (icona `mail`) e **Trattative** → `/acquisitions` (icona `handshake`/`trending-up`). Nota UX accettata: aprendo queste isole il telefono mostra la shell desktop responsive (off-canvas), non la chrome `/m`; la navigazione verso altre pagine desktop rimbalza su `/m` (isole controllate).
3. **i18n**: chiavi nav per le nuove voci drawer in 5 lingue (`nav.mail` esiste già da F1; aggiungere `nav.trattative`/riuso `acq.title`, e `nav.group.commerciale` se serve). `data-i18n` nei template.
4. **Versioning**: `app/main.py` `.245` → `.246`; CHANGELOG voce; STATO sezione α.246 + prossimo step (sotto-fase mobile B: Calendario/Documenti).

## Error handling / edge

- Off-canvas sidebar: garantire che il backdrop non intercetti il contenuto quando chiuso (`pointer-events:none` a riposo).
- `mfToggleSidebar()` viewport-aware: al resize da mobile→desktop, rimuovere classe `mf-open`/backdrop per non lasciare stato sporco.
- `/mail` vista-stato: al passaggio desktop↔mobile (resize/rotazione) l'attributo `data-mail-view` è inerte su desktop; nessun reset necessario, ma evitare che `read` nasconda pannelli su desktop (le regole show/hide stanno SOLO dentro il media query).
- Esenzione `/acquisitions`: verificare che non esistano altre pagine il cui path inizia con `/acquisitions` che vogliamo invece redirette (non ce ne sono; è un modulo unico).

## Testing

**pytest** (`tests/test_mobile.py` esteso):
- GET `/mail` con header `User-Agent` mobile (es. iPhone) + `Accept: text/html` + senza cookie `prefer_desktop` → **200** (non 302 verso `/m`).
- Idem GET `/acquisitions` → **200**.
- Regressione: GET `/dashboard` con stessa UA → **302** verso `/m` (redirect ancora attivo per il resto).
- GET `/mail/api/status` con UA mobile → non redirette (già coperto da check API), 200/best-effort.

**Playwright** (viewport 390×844, UA mobile):
- `/mail`: layout colonna singola; default vista `list`; apri un thread → vista `read` con "← Indietro"; torna a `list`; apri "☰ Etichette" → vista `labels`; apri compose → full-screen. 0 errori console. (Se senza opt-in Gmail: CTA "Collega Gmail", accettabile.)
- `/acquisitions`: apri trattativa (id reale) → dettaglio full-screen; scrolla le tab → tab **Email**; incolla link Gmail → **Aggancia** → compare in lista + Activity email loggata. 0 errori console.
- Shell: hamburger apre/chiude sidebar off-canvas; click su link chiude il drawer.

**JS syntax**: `node --check` su `mail.js` e ogni JS modificato.

## Fuori scope (sotto-fasi successive)

- Calendario mobile (`/calendar` responsive) e Documenti Drive mobile → sotto-fase mobile B.
- Notifiche push per nuova email / email agganciata → territorio Client email Sotto-fase 3 (auto-flow).
- Ritiro della PWA `/m` / convergenza totale desktop responsive → decisione strategica futura, non ora.

## Note implementative

- Rispettare le convenzioni: i18n 5 lingue stesso commit, cache-buster `?v={{ app_version }}` già presente sugli asset, helper JS in `global.js`/`mail.js` non ridefiniti, no `JSON.stringify` in onclick.
- Il refactor inline→classi in `mail.html` deve essere byte-neutro sul rendering desktop (verificare visivamente lo smoke desktop dopo).
- `graphify update .` dopo le modifiche.
