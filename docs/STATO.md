# STATO — MediaFlow

> Snapshot operativo, aggiornato a fine iterazione.
> Claude lo legge a inizio sessione per orientarsi, e lo aggiorna a fine giro.
> CLAUDE.md = visione/architettura. STATO.md = "dove siamo adesso, cosa fare dopo".

---

## Versione corrente

**v3.4.7** — 28 aprile 2026

## In corso

Cantiere **"Calendario e Pianificazione"** aperto. Chiusi: **D** (Booking multi-tenant, v3.4.6) e **timbrature/idle Opzione 2** (sezione HR `/hr` con `TimePunch`, v3.4.7). Prossimi: **A** UX calendario, **B** UI ferie/indisponibilità, **C** riconciliare Assignment↔Booking, **E** capability AI booking, **F** gantt per job. + sviluppo HR avanzato (aggregazioni, auto-timbratura login, costo orario nel cost report).

## Prossimo step concordato

**Verifica visiva sul Mac di Matteo** della sezione HR + integrazione calendario:
1. Aprire `/hr` → vedere filtri funzionanti, totali per kind, modal "+ Nuova timbratura" che salva e modal modifica via click su riga
2. Creare 2-3 timbrature di test (shift con job, idle, leave) per Luca/Sara
3. Aprire `/planning/calendar` → vedere i 2 eventSources sovrapposti (bookings + timbrature), toggle "Sorgenti" funzionante, toggle risorse funzionante (prima era no-op)
4. Click su un punch nel calendario → toast con durata o "in corso"

Dopo conferma, partire con **step A — UX calendario**:
- `editable: true` su FullCalendar + handler drag/resize → PUT `/planning/api/bookings/{id}` (endpoint da aggiungere) e PUT `/hr/api/punches/{id}` (esistente)
- Click su evento → modal di modifica/cancellazione (oggi è solo toast)
- Mostrare `ResourceUnavailability` come banded events grigi non cliccabili
- Filtro server-side su `from_date`/`to_date` (oggi FullCalendar passa start/end ma noi non li usiamo)

In parallelo, restano sospesi sul Mac: **verifica visiva v3.4.5** (modal "Aggiungi voce") e **test E2E #5** (AI search-first).

Per testare #5 servono prompt reali al copilot con provider AI attivo (Sonnet 4.6 consigliato, ma anche Ollama 8b dovrebbe funzionare grazie a SEARCH-FIRST esplicito nel system prompt).

Casi suggeriti:
1. **1 match chiaro** → `"aggiungi a Q-2026-001 due giorni di Color HDR"` deve produrre `propose_quote_line` con `price_item_id` e prezzo ereditato dal listino
2. **Match multipli** → `"aggiungi a Q-2026-001 del color"` deve elencare in markdown le 3+ voci color (SDR/HDR/dailies) e chiedere quale
3. **Voce esplicitamente nuova** → `"aggiungi a Q-2026-001 una nuova voce Foley editing, listino 350/giorno categoria Audio"` deve produrre `propose_new_item_and_line`
4. **0 match con domanda** → `"aggiungi a Q-2026-001 un Beauty fix"` (voce inesistente) deve elencare in markdown opzioni (a) voce libera vs (b) scenario C

Dopo conferma test sul Mac, passare a **#4 server-side abort**.

## Backlog (in ordine concordato)

**Cantiere Calendario / Pianificazione (in corso)**:
- ✅ **D** Booking multi-tenant (chiuso v3.4.6)
- ✅ **Timbrature/idle (Opzione 2)** sezione HR `/hr` con `TimePunch` separato + integrazione calendario come secondo eventSource (chiuso v3.4.7)
- 🔜 **A** UX calendario: drag/resize/move (editable:true), click evento → modal edit/cancel, mostrare `ResourceUnavailability` come banded grigi, filtro server-side su date range
- 🔜 **B** UI `/resources/{id}` tab Disponibilità (CRUD `ResourceUnavailability`)
- 🔜 **C** Riconciliare `JobResourceAssignment` (kanban `/assignments`) ↔ `Booking` (calendario): assegnare risorsa a job propone booking sulle date job; oppure rendere kanban una vista alternativa stesso modello
- 🔜 **E** Capability AI `propose_booking` + `propose_time_punch` (conflict-check booking già esistente lato server)
- 🔜 **F** Vista gantt per job (start_date → end_date) sovrapposto a booking risorse

**Sezione HR — sviluppo successivo**:
- Aggregazioni avanzate (ore per progetto/risorsa/mese, costo orario × ore in cost report, export CSV/PDF cedolino)
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
- Nessun altro bug noto.

## Procedura riavvio (se la sessione muore)

1. Apri nuova istanza Claude Code nella cartella `mediaflow_fase1bis`.
2. Comincia con: **"leggi docs/STATO.md e procedi"**.
3. Se git è inizializzato, Claude usa `git status`/`git diff` per vedere cosa è non committato.
4. Per recuperare il filo verbatim della sessione precedente: `/recall:session <session-id>`. Il session-id si trova:
   - subito quando esci da `claude` (lo stampa)
   - oppure `claude --sessions` da terminale esterno
   - oppure il `.jsonl` più recente in `~/.claude/projects/C--Users-frico-OneDrive-Documents-Claude-Projects-mediaflow-fase1bis/`

---

*Ultimo aggiornamento: 28 aprile 2026 — v3.4.7 chiusa: nuova sezione HR `/hr` con modello `TimePunch` separato (Opzione 2 scelta da Matteo), CRUD completo via API + UI con filtri/totali/modal, integrazione calendario come secondo eventSource con toggle sorgenti e filtro risorse server-side. CRUD smoke-tested E2E. Prossimo: verifica visiva sul Mac e poi step A (UX calendario drag/edit/unavailability).*
