# Spec — Mobile v2 · Fase A (Foundation: look + navigazione)

**Data**: 2026-05-31
**Versione target**: v3.5.0-alpha.172.159+
**Richiesta**: Matteo — il mobile v1 è funzionante ma "molto limitato + look spartano".
Espandere verso un livello intermedio (operativo + gestionale). Prima fase: **fondazione
look + navigazione**, su cui costruire le aree successive.

Questa è la **Fase A** di un'iniziativa mobile-v2 in 4 fasi (vedi §9). Editor pesanti
(righe quote 50+, planning timeline drag, gestione listino) **restano desktop** per tutta
l'iniziativa (decisione Matteo).

---

## 1. Obiettivo

Trasformare il mobile da "spartano" a curato e dargli una navigazione **scalabile** che
regga molte aree (Agenda, Progetti, Quote, Clienti, Finance, QC, Copilot — aggiunte nelle
fasi B-D). Fase A NON aggiunge nuove schermate-entità: consegna il **design system** +
la **navigazione a drawer**, applicati alle 5 schermate staff esistenti
(Oggi/Timbra/Assegnazioni/Ferie/Notifiche). Risultato: app coerente, bella, pronta a
crescere.

## 2. Decisioni confermate

| # | Decisione | Scelta |
|---|-----------|--------|
| A1 | Navigazione | **Drawer laterale** (☰ in header, slide-in da sinistra, overlay) con TUTTE le sezioni. Sostituisce la bottom tab bar v1. |
| A2 | Estetica | **Affina dark Claqo** (dark indaco `#6272f5`, identità desktop) — componenti curati, gerarchia tipografica, spaziature, raggi/ombre, micro-interazioni, **icone lucide** (vendored) al posto delle emoji. |
| A3 | Editor pesanti | Restano **desktop** (vale per tutta l'iniziativa mobile-v2). |

## 3. Design system (`mobile.css` v2 + base_mobile)

Rifattorizzare `app/static/css/mobile.css` (oggi 419 righe v1) in un design system coerente.
PRESERVARE i nomi classe già usati dal render JS delle 5 schermate (`.m-card`,
`.m-list-item`, `.m-empty`, `.m-badge`, `.m-btn*`, `.m-section`, `.m-form-*`, ecc.) —
restyling, non rinomina, per non rompere il JS esistente. Aggiungere nuovi componenti.

- **Tokens**: scala spaziatura (4/8/12/16/24), raggi (8/12/16), ombre (elevazione card/drawer),
  scala tipografica (title/subtitle/body/caption), palette brand (bg/bg2/bg3/accent/muted/
  border/danger/success/warn) — variabili CSS.
- **Header** (`.m-top`): ☰ (apre drawer) + titolo pagina + slot azione destra (es. badge
  notifiche). Sticky, elevazione.
- **Drawer** (`.m-drawer` + `.m-drawer-overlay`): slide-in da sinistra, overlay scurente,
  chiusura su tap-overlay/Escape/voce; lista voci con icona lucide + label, sezione attiva
  evidenziata; header drawer con brand Claqo + utente loggato.
- **Componenti**: card (varianti), list-item (con leading icon/avatar, trailing meta/chevron),
  badge (stato: pending/approved/rejected/info/danger/success/warn), button (primary/secondary/
  danger/ghost, sizes), form controls (input/select/textarea/label/help), chip/pill,
  loading **skeleton** + empty state curati, toast (già presente, rifinito), pull-to-refresh
  opzionale (no, YAGNI — bottone refresh dove serve).
- **Icone**: lucide (già vendored `static/js/lucide.min.js`) via `data-lucide` + init
  (`lucide.createIcons()`); rimuovere le emoji dalla tab/nav.
- **Micro-interazioni**: stati `:active`/tap feedback, transizioni drawer/overlay, niente
  animazioni pesanti.

## 4. Navigazione (drawer)

- Rimuovere la bottom tab bar v1; introdurre il drawer come navigazione primaria.
- Header con ☰ a sinistra. Tap → apre drawer (overlay + slide). Chiusura: tap overlay,
  tap voce, Escape, swipe-left (opzionale).
- Voci drawer raggruppate. In Fase A il gruppo **Operativo** contiene le sezioni esistenti:
  Oggi · Timbratura · Assegnazioni · Ferie · Notifiche. Le aree future (Agenda/Progetti/
  Quote/Clienti/Finance/QC/Copilot) **NON appaiono finché non esistono** (le aggiungono le
  fasi B-D — niente voci "prossimamente" morte, YAGNI). Struttura drawer predisposta a
  gruppi multipli ("Operativo", "Gestione", "AI") per l'aggiunta incrementale.
- Sezione attiva evidenziata. Logout in fondo al drawer.

## 5. Applicazione alle 5 schermate esistenti

- `base_mobile.html`: nuovo header + drawer + lucide init; rimossa bottom tab bar.
- Le 5 pagine (oggi/timbra/assegnazioni/ferie/notifiche): adottano i componenti rifiniti.
  Il render JS esistente continua a funzionare (stesse classi, restyling). Dove il render
  usa emoji/markup grezzo, sostituire con i nuovi componenti/icone in modo NON invasivo
  (preferibilmente lato CSS; ritocchi JS minimi solo se necessario, mantenendo DOM-safe).
- Nessun nuovo endpoint/dato in Fase A.

## 6. Implementazione: design quality

L'esecuzione del look usa la skill **frontend-design** (qualità visiva, evita aesthetic
generica). Vincolo: dark Claqo, brand-consistent, touch-first (target ≥44px), performance
(CSS leggero, no framework). Mantenere `?v={{ app_version }}` cache-buster.

## 7. Fuori scope (Fase A)

- Nuove schermate-entità (Agenda/Progetti/Quote/Clienti/Finance/QC/Copilot) → Fasi B-D.
- Nuove azioni/mutazioni → Fase C.
- Editor pesanti → desktop (tutta l'iniziativa).
- Offline-sync, push native → defer.

## 8. Testing

- Jinja: `base_mobile.html` + le 5 pagine compilano.
- JS: `node --check` su mobile.js + eventuale drawer/lucide init script (estratto da base_mobile).
- Funzionale (E2E/curl, server di test): le 5 route `/m/*` → 200 loggato; no-auth → redirect;
  asset (mobile.css/js, lucide, manifest) → 200.
- Drawer: smoke che l'HTML contiene il markup drawer + ☰ + le 5 voci; lucide init presente.
- Visivo (look, drawer animazione, leggibilità) → verifica manuale Matteo (tunnel).

## 9. Decomposizione iniziativa mobile-v2 (contesto)

| Fase | Contenuto | Stato |
|------|-----------|-------|
| **A** | Foundation: design system + drawer nav (questo spec) | in design |
| B | Consultazione entità: Agenda · Progetti · Quotazioni · Clienti · Finance overview (read + schede ricche) | dopo A |
| C | Azioni: approvazioni (ferie/quote stato), cambi stato progetto/job, QC actions, create/edit leggeri | dopo B |
| D | AI Copilot mobile + viste planning deliveries/progetti dedicate | dopo C |

Editor pesanti (quote righe, timeline drag, listino) → desktop in tutte le fasi.
Ogni fase: proprio spec → piano → build incrementale.

## 10. File toccati (stima Fase A)

`app/static/css/mobile.css` (rewrite design system), `app/templates/mobile/base_mobile.html`
(header + drawer + lucide init, rimossa tab bar), `app/static/js/mobile.js` (helper drawer
open/close + lucide init), le 5 pagine `app/templates/mobile/*.html` (adozione componenti,
ritocchi minimi), `tests/test_mobile.py` (smoke drawer markup).
