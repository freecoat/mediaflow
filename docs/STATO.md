# STATO — MediaFlow

> Snapshot operativo, aggiornato a fine iterazione.
> Claude lo legge a inizio sessione per orientarsi, e lo aggiorna a fine giro.
> CLAUDE.md = visione/architettura. STATO.md = "dove siamo adesso, cosa fare dopo".

---

## Versione corrente

**v3.4.36** — 1 maggio 2026 notte profonda — Round 1 Audit: lifecycle Quote↔Job sano

Round 1 di 3 dell'audit logico richiesto. Chiude i bug critici lifecycle (B1, B3, B4, B5, C2): cancellare/modificare/aggiungere righe quote dopo approvazione del job ora sincronizza correttamente JobCostLine. Soft-detach Booking/TimePunch su delete JobCostLine. Migrazione cleanup `[M]` per orfani esistenti. Round 2 (job progress bar) e Round 3 (hardening RBAC/FSM/invariants) restano da fare.

**v3.4.35** — 1 maggio 2026 notte tarda — Undo stack + Salva su /quotes editor

Stack undo client-side per add/delete/reorder voci e reorder categorie. Bottone "↺ Annulla" in topbar + toast post-azione con annulla cliccabile (5s). Bottone "💾 Salva" cosmetico (auto-save resta attivo).

**v3.4.34.5** — 1 maggio 2026 notte tarda — Fix drag&drop listino→voci (regressione v3.4.34 multi-tbody)

**v3.4.34.4** — 1 maggio 2026 notte tarda — Listino allargato +35% (480→650px, 440→600px sotto 1400)

**v3.4.34.3** — 1 maggio 2026 notte tarda — Critical Assumptions reagisce al toggle Listino

Fix: la topbar (con Critical Assumptions inline) ora si stringe correttamente quando il pannello Listino flottante è aperto. Classe `.with-pricelist` applicata sull'intero wrapper `#quote-editor` (non solo sul body).

**v3.4.34.2** — 1 maggio 2026 notte tarda — Listino flottante + same-height top + IVA in Riepilogo

Listino ora `position:fixed` (sempre visibile durante scroll, non più sticky). Riepilogo e Stato&azioni hanno stessa altezza (align-items:stretch). IVA spostata da Stato a Riepilogo (editabile inline). Note/Termini compatti rows=1 espandibili al focus.

**v3.4.34.1** — 1 maggio 2026 notte tarda — Layout editor /quotes: Stato a sinistra, Listino sticky

"Stato & azioni" spostato nella colonna sinistra accanto a "Riepilogo economico" (grid 2 col). Colonna destra = solo pannello Listino sticky che resta a posizione fissa durante lo scroll della pagina (scroll interno alla lista risultati).

**v3.4.34** — 1 maggio 2026 notte tarda — Refactor layout editor /quotes (Critical Assumptions compatto, riepilogo sopra, riordino categorie)

Riorganizzazione UX dell'editor quotazione su richiesta Matteo: Critical Assumptions in topbar inline, bottone "+ Aggiungi voce" rimosso (lascia solo "📋 Listino"), Riepilogo economico sopra le voci, Stato & azioni sopra il Listino, riordino categorie con drag&drop (multi-tbody + SortableJS, persistito in `Quote.category_order` JSON nuovo).

**v3.4.33.1** — 1 maggio 2026 notte tarda — Pannello "Aggiungi voce" laterale persistente

Chiarimento UX listino /quotes. Il vecchio modal `#modal-add-line` e il mini-pannello `#side-pricelist` (v3.4.29) sostituiti da un singolo pannello laterale persistente `#side-add-line` (480px, GUI ricca con sidebar categorie + ricerca + risultati grandi cliccabili E draggable). Resta aperto fino click ✕. Aggiunta voce non chiude il pannello (multi-aggiunta in fila).

**v3.4.33** — 1 maggio 2026 notte — Cost report v2 (fonte Booking) + PDF cliente + listino /quotes default open

Cantiere "Cost Report doppio" avviato dopo conferme strategiche (Q1 fonte=Booking, Q2 una pagina + bottone export, Q3 ReportLab, Q4 fuori scope).

**v3.4.32.2** — 1 maggio 2026 notte — Patch v3.4.32.1 (timeline align + paste GUI + governance overtime + scaglioni CCNL)

Quattro fix raggruppati: (1) allineamento timeline label↔group ripristinato (rimossi min-height conflittuali); (2) paste GUI con click-to-paste + right-click "Incolla qui" + barra arancione in modalità incolla + Esc per annullare; (3) auto-approve overtime ammesso solo a manager+admin (NO producer) + notifica info agli altri manager per visibilità governance; (4) scaglioni overtime CCNL configurabili (`overtime_brackets` JSON + `ccnl_label`) — engine già pronto, UI in `/settings#hours`, compilazione preset via AI è iter successiva (capability `propose_working_hours_policy`).

**v3.4.32.1** — 1 maggio 2026 sera — Patch v3.4.32 dopo test locale (multi-risorsa, drop festivo, look timeline, temi/font)

Sei fix raggruppati: (1) override permessi su booking multi-risorsa con cascade ristretto; (2) bottoni durata `−30/−15/+15/+30`; (3) auto-approve overtime se chi estende ha permesso + 3 icone notifica nuove; (4) drop su festivo → soft block + workflow overtime invece di hard block; (5) timeline altezza riga uniforme + font label più chiari; (6) 5 temi colori nuovi + 6 varianti font.

**v3.4.32** — 1 maggio 2026 — Booking esecutivo (priorità + stato + workflow overtime + pozzo not_done)

Cantiere "booking come unità operativa". Trasformato il booking da pura intenzione di pianificazione a oggetto governabile dall'operatore: priorità (3 livelli low/normal/high) visibile per colore, ciclo di vita planned→in_progress→done|not_done con motivazione, modifica durata adattiva con cascade intra-day, workflow approvazione straordinari basato su WorkingHoursPolicy, sezione cost report dedicata + pozzo ore non maturate.

**Decisione architetturale chiarita** (memoria `project_costreport_vs_timesheet.md`): cost report = quotazioni + booking + hardcost (lente cliente/finance/fatturazione). Timesheet = HR + amministrazione (lente consulente del lavoro/buste paga). Due binari separati comunicanti solo nel planning per disponibilità risorse.

**Decisione strategica** (memoria `project_normativa_ccnl.md`): ferie/malattia → normativa italiana per ora. Straordinari → CCNL caricabili in impostazioni (Matteo cerca i CCNL applicabili al post-prod).

Sessione 1 maggio sera (commit unico): chiusa v3.4.32 dopo discussione completa di scope + 4 domande chiave (priorità a 3 livelli ✓, default normal/planned ✓, cascade intra-day con workflow overtime su sforamento ✓, pozzo come sezione del cost report progetto ✓).

## In corso

**Sessione 1 maggio notte chiusa.** v3.4.32→.32.2 + .33 da testare sul Mac al prossimo pull (o continua il test locale).

Da testare per **v3.4.33**:
- `/quotes`: pannello listino aperto di default quando entri nell'editor di una quote (prima nascosto)
- `/cost-report`: 8 KPI (compresi "Costo ore (booking)" e "Margine stimato")
- `/cost-report`: bottone "📄 Esporta PDF cliente" → apre PDF ReportLab con lavorazioni quote + extra + ore breakdown, niente hardcost/margine/rate
- Verifica numeri: ore nel cost report ora vengono dai Booking, NON più dai Timesheet (HR resta separato)

Da testare per **v3.4.32→.32.2** (carry-over):
- Migrazione `[L]` (solo se DB esistente) — già auto-applicata al boot
- `/planning` tab "Le mie": card interattive con bordo priorità, bottoni `−30/−15/+15/+30`, `▶ Inizia / ✓ Fatto / ✗ Non fatto`
- Booking multi-risorsa: l'operatore può estendere; cascade non spinge le altre risorse del cascade
- Drop su giorno festivo nella timeline → confirm dialog "Sarà richiesta approvazione straordinario"
- Estensione overtime: producer → sempre pending; manager/admin → auto-approved con notifica info agli altri admin/manager
- Paste GUI: Ctrl+C poi Ctrl+V → barra arancione "Modalità incolla" → click sulla timeline incolla. O right-click area vuota → "Incolla qui (N)"
- `/settings#aspect`: 9 temi colori + 6 varianti font
- `/settings#hours`: scaglioni overtime (test: prime 2h al 1.30, oltre al 1.60)

Da testare ancora dalla v3.4.31 (carry-over):
- Fix sidebar `/settings#sidebar`
- Notifica `job_deadline_approaching` (strumenti `[T]`)
- Listino laterale + drag&drop in `/quotes`
- Calendario complessivo in `/hr`
- Scheda tecnica progetto + link pubblico

Cantieri rimasti aperti (precedenti):

### A) Cost Report doppio — sospeso a v3.4.21
- ✅ v3.4.21 — Soglie overtime + moltiplicatori in `WorkingHoursPolicy`, engine `compute_overtime()`, endpoint `/hr/api/overtime`, UI settings
- 🔜 Cost report **interno** `/jobs/{id}/cost-report`: rate × (regular + overtime×mult) + hardcost + booking interni
- 🔜 Cost report **esterno cliente**: solo ore + extra, bottone "→ Genera quote v2"
- 🔜 Pagina HR riepilogo sett/mese per risorsa + export CSV

### B) RBAC + UX (chiuso v3.4.22 → v3.4.24)
- ✅ v3.4.21.1 — Auth guard + UX login + topbar utente
- ✅ v3.4.22 — RBAC base + workflow ferie + timbratura semplificata + login centrato + look timeline polish
- ✅ v3.4.23 — Permessi configurabili + pannello admin utenti/ruoli + auto-User da Resource
- ✅ v3.4.24 — Fix `escapeHtml` globale (sblocca /admin/users + /admin/roles), rimozione scelta manuale overtime, ferie/malattia in "Le mie ore" + nel conteggio ore, anteprima permessi nel modal utente

### C) Backlog feedback Matteo (in attesa)
- ⏸ **Scheda tecnica progetti + link pubblico cliente** — Matteo allegherà PDF (quello del 30/04 era erroneamente `quote_Q-LFSB-1.pdf`, una quotazione)
- ✅ ~~Dove fa staff le richieste ferie?~~ Risolto in v3.4.24: form inline in `/planning/` tab "Le mie".

Cantiere **Core Planning** (6 fasi confermate dopo analisi top vendor — Float/Runn/Resource Guru/Productive/Mosaic/Ftrack):

- ✅ E1 — v3.4.14 — Editing diretto (drag/resize/delete + PUT API + snap adattivo + conflict viz + undo + Alt=duplica)
- ✅ E2 — v3.4.15 — Click&drag crea + ghost + tooltip durata + capacity heatmap + menu contestuale Sposta/Duplica/Annulla cross-resource
- 🔜 E3 — v3.4.16 — WorkingHoursPolicy globale+override + split smart + pausa rigida + ferie/malattia bloccanti + holiday Italia auto (lib `holidays`)
- 🔜 E4 — v3.4.17 — Multi-select + modifier keys completi + saved views + conflict viz live evoluto + bulk paste + snap line
- 🔜 E5 — v3.4.18 — Booking ricorrenti + tentative bookings (legati a quote draft/sent → committed quando approved) + audit log
- 🔜 E6 — v3.4.19 — AI auto-suggest assegnazione (capability `propose_booking`)

Cancellati dalla roadmap (gold plating o ridondante con altri vendor del mercato): cursori real-time, GraphQL, full-Gantt+critical-path, review/approval workflow Ftrack-style.

Cantiere "overlay prenotato vs effettivo + adeguamento" (era v3.4.15 nel plan precedente) → riassorbito in E5/E6 dopo E3 ferie e con tentative status.

## Prossimo step concordato

**Roadmap core-planning E1→E6 COMPLETA.** Backlog rifiniture e UI:

- v3.4.20.1 UI settings working hours editabile (form policy in /settings)
- v3.4.20.2 Modal multi-row leggibilità >5 (scroll/collapse)
- v3.4.20.3 Snap line visiva durante drag
- v3.4.20.4 Endpoint cambio status tentative↔confirmed dal modal
- v3.4.20.5 UI form ferie/malattia in /resources/{id}

Poi cantieri rinviati:
- Cost report doppio (interno/esterno cliente)
- Overlay "prenotato vs effettivo" (booking vs TimePunch)

**Vecchio backlog (legacy):**
- ~~E5 v3.4.19~~:
- Booking ricorrenti minimi: every weekday, every Mon, every Tue, ecc.
- Tentative bookings (`is_tentative` flag, viz tratteggiata) legati a quote draft/sent → committed quando approved
- Audit log su modifiche booking (estende pattern AIAction)

**E6 — v3.4.20 — AI auto-suggest assegnazione**:
- Capability `propose_booking` nel copilot
- Skill match + availability + storico

**Backlog UI**:
- Pagina `/settings#working-hours` con form policy editabile (mattina, pomeriggio, giorni, paese festività)
- Override policy per-risorsa nella pagina `/resources/{id}`
- Form ferie/malattia in `/resources/{id}` (oggi solo via API)

**Vecchio E4 — v3.4.18 — Polish + multi-select**:
- Modello `WorkingHoursPolicy` (globale + per-risorsa override): start_time, end_time, lunch_start, lunch_end, working_days
- Engine `split_booking_smart(start, end, policy) → list[Slot]` che ritaglia weekend, orario non-lavorativo, pausa pranzo rigida (es. 13-14)
- Modello `ResourceUnavailability` evoluto: ferie/malattia come fasce bloccanti, drag/drop su quelle = HARD block (popup, no warning)
- Holiday calendar Italia predefinito (libreria Python `holidays.IT()`) + custom holidays
- Pagina `/settings#working-hours` per configurare policy
- Toggle "Smart split" nel modal create (default ON), preview "creerà N booking"
- Migration script idempotente
Verifiche sul Mac sospese (cumulative):
- v3.4.5 modal "Aggiungi voce"
- v3.4.6 booking multi-tenant
- v3.4.7 sezione HR + calendario integrato
- v3.4.8 flusso Quote → Job auto
- v3.4.8.1 hotfix STATUS_LABEL e FullCalendar CSS
- v3.4.9 dettaglio job
- v3.4.9.1 hotfix finance budget
- v3.4.10 aggregazione ore per lavorazione (colonne Pian./Lavor. in `/jobs/{id}`)
- v3.4.11 hub `/planning/` con 5 viste (Tabella, Calendario, Trimestre, Agenda, Le mie) + 9 filtri trasversali
- v3.4.12 Resource Timeline vis-timeline (tab #6, zoom Giorno/Sett/Mese/Trim, raggruppata per reparto, riusa filtri)
- v3.4.13 UX cleanup: tasto Oggi parte da oggi, selettore data Vai-a, label settimana/mese, zebra rows, filtri collassabili, vista Trimestre rimossa, voce sidebar Calendario rimossa
- v3.4.13.1 hotfix: filtri collassabili stabili (flex+min-width:0), click su timeline → modal nuovo booking pre-popolato (risorsa+ora+job+lavorazione)
- v3.4.14 E1 editing diretto: drag/resize/delete, snap adattivo 15/30/60min, conflict border rosso live, undo toast 5s, Alt+drag duplica, doppio click vuoto = nuovo
- v3.4.15 E2: click&drag crea con ghost+durata, capacity heatmap %/giorno, menu contestuale Sposta/Duplica/Annulla cross-resource, pan disabilitato (scroll/bottoni)
- v3.4.15.1 hotfix: drag pan ripristinato, Shift+drag = nuovo booking, right-click menu su item (Modifica/Duplica/Sposta/Elimina) e vuoto, heatmap robusto (update foglie)
- Test E2E AI search-first (v3.4.4)

Per testare #5 servono prompt reali al copilot con provider AI attivo (Sonnet 4.6 consigliato, ma anche Ollama 8b dovrebbe funzionare grazie a SEARCH-FIRST esplicito nel system prompt).

Casi suggeriti:
1. **1 match chiaro** → `"aggiungi a Q-2026-001 due giorni di Color HDR"` deve produrre `propose_quote_line` con `price_item_id` e prezzo ereditato dal listino
2. **Match multipli** → `"aggiungi a Q-2026-001 del color"` deve elencare in markdown le 3+ voci color (SDR/HDR/dailies) e chiedere quale
3. **Voce esplicitamente nuova** → `"aggiungi a Q-2026-001 una nuova voce Foley editing, listino 350/giorno categoria Audio"` deve produrre `propose_new_item_and_line`
4. **0 match con domanda** → `"aggiungi a Q-2026-001 un Beauty fix"` (voce inesistente) deve elencare in markdown opzioni (a) voce libera vs (b) scenario C

Dopo conferma test sul Mac, passare a **#4 server-side abort**.

## Backlog (in ordine concordato)

**Cantiere Calendario / Pianificazione (chiuso parzialmente)**:
- ✅ **D** Booking multi-tenant (v3.4.6)
- ✅ **Timbrature/idle Opzione 2** — sezione HR `/hr` con `TimePunch` separato + integrazione calendario (v3.4.7)
- 🔜 **A** UX calendario (editable, drag/resize, click→modal edit/cancel, banded unavailability, filtro server-side) — rinviato dopo il re-design Quote→Job
- 🔜 **B** UI `/resources/{id}` tab Disponibilità (CRUD `ResourceUnavailability`)
- 🔜 **C** Riconciliare Assignment kanban ↔ Booking (potrebbe sparire del tutto in favore del flusso quote→job→booking)
- 🔜 **E** Capability AI `propose_booking` + `propose_time_punch`
- 🔜 **F** Gantt per job

**Cantiere Quote → Job → Cost Report (sospeso)**:
- ✅ **v3.4.8** Auto-promote Quote → Job + bug fix planning + rimosso job manuale
- ✅ **v3.4.8.1** Hotfix STATUS_LABEL + FullCalendar CSS
- ✅ **v3.4.9** Pagina `/jobs/{id}` con lavorazioni first-class
- ✅ **v3.4.9.1** Hotfix finance.budget → finance.budget_quoted
- ✅ **v3.4.10** Booking legati a lavorazione + booking interni
- 🔜 **v3.4.13** Ferie/malattia come fasce bloccanti nel calendario
- 🔜 **v3.4.14** Cost report interno arricchito (rate × ore + hardcost + booking interni)
- 🔜 **v3.4.15** Cost report esterno cliente (solo ore + extra, bottone "→ Genera quote v2")
- 🔜 **UX calendario** (modal "+ Booking" aggiornato, redesign visuale)

**Cantiere Visualizzazioni Pianificazione (in corso)**:
- ✅ **v3.4.11** Hub `/planning/` 5 viste + 9 filtri trasversali (Tabella, Calendario, Trimestre, Agenda, Le mie)
- ✅ **v3.4.12** Resource Timeline (vis-timeline, righe verticali risorse raggruppate per reparto, zoom giorno/sett/mese/trim)
- ✅ **v3.4.13** UX cleanup: Oggi=da-oggi, Vai-a, label sett/mese, zebra rows, filtri collassabili, drop Trimestre + voce sidebar Calendario
- ✅ **v3.4.13.1** Hotfix filtri (flex+min-width:0) + click vuoto timeline → modal nuovo booking pre-popolato
- ✅ **v3.4.14** E1: editing diretto timeline (drag/resize/delete + PUT/restore API + snap 15/30/60min adattivo + conflict viz live + undo toast 5s + Alt+drag duplica + doubleClick vuoto = nuovo)
- ✅ **v3.4.15** E2: click&drag crea + ghost rect + tooltip durata + capacity heatmap %/giorno (live update con zoom) + menu contestuale Sposta/Duplica/Annulla cross-resource
- ✅ **v3.4.15.1** Hotfix: drag pan ripristinato (era preferenza utente) → Shift+drag per nuovo. Right-click menu su item e vuoto. Heatmap update solo foglie (preserva nesting).
- 🔜 **v3.4.16** E3: WorkingHoursPolicy + split smart + pausa pranzo rigida + ferie hard-block + holiday Italia auto
- 🔜 **v3.4.15** Prenotato vs effettivo overlay + adeguamento + report delta producer
- 🔜 **post-15** Kanban per stato job (SortableJS) + Gantt per job (`/jobs/{id}`, Frappe Gantt)

**Sezione HR — sviluppo successivo**:
- Aggregazioni avanzate (ore per progetto/risorsa/mese, export CSV/PDF cedolino)
- Auto-timbratura via topbar per chi è loggato ("🟢 Inizio turno" / "🔴 Fine turno")
- Orari standard per tipo risorsa (full-time / part-time / freelance) per calcolo straordinari automatici

**Backlog "altri"**:
1. **#4 server-side** Abort lato server per Ollama/Claude (oggi è solo client-side `AbortController`). Ollama supporta `client.abort()` best-effort. Anthropic SDK richiede una `Cancelable` request.
2. **#1** Multi-valuta con cambio automatico ECB. Migrazione DB (`Quote.currency`, `exchange_rate`, `currency_locked`, `exchange_rate_date`) + servizio `app/services/fx.py` con cache JSON + UI dropdown valuta + capability AI `propose_quote_currency`. Conversione solo a display/PDF/export, EUR canonico in DB.
3. **F2** Gestione utenti + RBAC configurabile + link Resource→User con email password temp.
4. **F3** Cestino per-tenant con retention configurabile.

## Decisioni prese

- **Multi-valuta**: API ECB exchangerate.host (gratis, no key). EUR canonico in DB, conversione solo display/export.
- **Search-first AI**: priorità a match listino esistente. Fallback a scenario "C" (crea voce + linea in singola transazione) solo se utente conferma "non trovato".
- **Stop thinking**: tentare anche server-side abort (Matteo: "per evitare possibile sovraccarico richieste").
- **Esporta da copilot (#2 originale)**: skipped per ora.

## Bug aperti

- ✅ **#6 LLM matching listino** risolto in v3.4.4 (voci listino nel context AI + REGOLA SEARCH-FIRST nel system prompt). Da verificare con test E2E sul Mac.
- ✅ ~~**Modal multi-risorsa: leggibilità >5 risorse**~~ risolto in v3.4.20.2 (scroll interno + badge numerazione + counter).

## Procedura riavvio (se la sessione muore)

1. Apri nuova istanza Claude Code nella cartella `mediaflow_fase1bis`.
2. Comincia con: **"leggi docs/STATO.md e procedi"**.
3. Se git è inizializzato, Claude usa `git status`/`git diff` per vedere cosa è non committato.
4. Per recuperare il filo verbatim della sessione precedente: `/recall:session <session-id>`. Il session-id si trova:
   - subito quando esci da `claude` (lo stampa)
   - oppure `claude --sessions` da terminale esterno
   - oppure il `.jsonl` più recente in `~/.claude/projects/C--Users-frico-OneDrive-Documents-Claude-Projects-mediaflow-fase1bis/`

---

*Ultimo aggiornamento: 1 maggio 2026 sera — chiusa v3.4.32 (Booking esecutivo). 37 commit ahead origin/main. Push da concordare.

**v3.4.32**: 5 colonne nuove su `bookings` (priority/execution_status/not_done_reason/count_in_costs/overtime_status/original_end_datetime) + 3 NotificationKind nuovi (`booking_status_changed`, `booking_overtime_pending`, `booking_overtime_resolved`) + permesso `approve_overtime` su admin/manager/producer. Servizi nuovi `app/services/booking_cost.py` (engine costo per fascia oraria) + `app/services/booking_cascade.py` (cascade intra-day + split overtime giorno successivo). 6 endpoint nuovi su `/planning/api/`: priority, execution, extend, overtime, count-in-costs, my-bookings. 2 endpoint nuovi su `/cost-report/api/job/{id}/`: booking-summary, not-done-pool/{bid}/discard. UI: `/planning` "Le mie" card interattive (bordo priorità, drag handle ±, bottoni stato, modal motivazione), Dashboard "I miei booking di oggi" + colonne stato in tabella generica, Cost report sezione "Ore booking per fascia" + "Pozzo ore non maturate".

**Distinzione architetturale fissata in memoria**: Cost report (quote+booking+hardcost) ≠ Timesheet (HR/buste paga). Due binari separati. Il vecchio cost_report.py basato su Timesheet resta come legacy, conviverà col nuovo finché si farà rifacimento completo.

---

*Versione precedente: 30 aprile 2026 notte tarda — sessione maratona 12 commit (v3.4.21→v3.4.27). **Push eseguito**: tutto su origin/main su richiesta esplicita di Matteo. Aggiunto sistema notifiche generico (cantiere riusabile per booking_conflict, quote_status_changed, job_deadline_approaching, ecc.).

**v3.4.27** (ultimo): modello Notification + servizio notifications.py + router /notifications/api/* + 3 hook ferie (create pending → manager, approve/reject → richiedente) + UI campanella topbar con badge + drawer laterale + polling 30s + card "Richieste in attesa" in /hr/. Pattern una-row-per-destinatario. NotificationKind estendibile (4 valori riservati per cantieri futuri).

**Direttiva strategica Matteo (memorizzata)**: sempre approccio generico riusabile, mai tappare buchi singoli. Esplorare in-depth conseguenze. Proposte ampie. Domande quando servono.

---

*Versione precedente: 30 aprile 2026 notte — riapertura post-test sul Mac, chiuso v3.4.24 con i 4 punti emersi (3 dei quali collassati su un singolo bug `escapeHtml` non globale). 27 commit ahead origin/main.

**v3.4.24**: (1) `escapeHtml` spostato in `global.js` → /admin/users e /admin/roles tornano funzionanti, l'auto-User da Resource era già OK ma sembrava rotto a causa del crash render lista; (2) modal timbratura senza scelta manuale "straordinario" (calcolo deterministico via policy); (3) "Le mie ore" planning ora ha card riepilogo ore (regolari+straordinari+notturne+ferie+malattia+totale) + form richiesta ferie/malattia + lista delle proprie con stato; `/hr/api/overtime` esteso con campi `unavailability` e `grand_total_hours` per la rendicontazione amministrativa; nuovo endpoint `/planning/api/my-unavailabilities`; (4) anteprima badge permessi sotto dropdown ruolo nel modal `/admin/users`.

---

*Versione precedente: 30 aprile 2026 sera — sessione lunghissima 5 commit (v3.4.21 → v3.4.21.1 → v3.4.22 → v3.4.23). 26 commit ahead origin/main. Aperto cantiere Cost Report (overtime engine), poi pivot su feedback Matteo → RBAC pesante. v3.4.22: ruolo producer + service rbac + sidebar conditional + auth guard blacklist + scope HR/planning + workflow approvazione ferie + timbratura semplificata (no job per staff) + overlay timbrature timeline + bug fix booking modal + login centrato + look timeline polish. v3.4.23: sistema permessi configurabili (modello Role + 23 permessi granulari + 6 preset built-in admin/manager/producer/accounting/operator/viewer), pannello /admin/users e /admin/roles con matrix permessi, auto-User da Resource personale, fix bug /hr/ 500 + drag inerziale timeline + nuovo progetto staff. Migrazioni nuove [I][J] in strumenti. Working tree pulito. Prossima sessione: testare RBAC + permessi sul Mac, poi proseguire cost report O scheda tecnica progetti (manca doc).*
