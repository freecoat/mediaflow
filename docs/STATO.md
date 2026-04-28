# STATO — MediaFlow

> Snapshot operativo, aggiornato a fine iterazione.
> Claude lo legge a inizio sessione per orientarsi, e lo aggiorna a fine giro.
> CLAUDE.md = visione/architettura. STATO.md = "dove siamo adesso, cosa fare dopo".

---

## Versione corrente

**v3.4.6** — 28 aprile 2026

## In corso

Cantiere **"Calendario e Pianificazione"** aperto. Step **D** (Booking multi-tenant) chiuso. Prossimi step in cascata: A (UX calendario drag/edit/filtro), B (UI ferie/indisponibilità), C (riconciliare Assignment↔Booking), E (capability AI booking), F (vista gantt job), + nuovo dominio **timbrature/idle** (entrata-uscita user, attività non legate a progetto) da modellare prima di B.

## Prossimo step concordato

**Decisione architetturale timbrature/idle** (prima di proseguire con A): Matteo vuole usare il calendario anche per timbrature user (entrata/uscita) e attività idle (non legate a un progetto). Tre opzioni:

1. **Booking con `job_id` nullable** + tipologia (`shift_in_out`, `idle`, `project`). Unifica tutto nel calendario, ma rompe il vincolo "Booking sempre legato a un job".
2. **Nuovo modello `TimePunch`** separato (user_id, start, end, type, note) + Booking resta com'è. Cleaner ma due viste da fondere lato UI calendario.
3. **Estendere `Timesheet` esistente** rendendo `job_id` nullable, con vista calendario sopra. Riusa modello esistente (timbratura ≈ timesheet di durata).

Da scegliere prima di partire con A. Successivamente:
- **A** UX calendario: drag/resize/sposta booking, filtro risorse server-side, click→modal modifica, mostrare unavailability come fascia grigia
- **B** UI ferie/indisponibilità su `/resources/{id}`
- **C** Riconciliare Assignment kanban ↔ Booking calendario
- **E** Capability AI `propose_booking`
- **F** Vista gantt per job

In parallelo, **verifica visiva v3.4.5** sul Mac (modal "Aggiungi voce" ridisegnato) e **test E2E #5 (AI search-first)** restano sospesi, da ricaricare quando Matteo apre il Mac.

Per testare #5 servono prompt reali al copilot con provider AI attivo (Sonnet 4.6 consigliato, ma anche Ollama 8b dovrebbe funzionare grazie a SEARCH-FIRST esplicito nel system prompt).

Casi suggeriti:
1. **1 match chiaro** → `"aggiungi a Q-2026-001 due giorni di Color HDR"` deve produrre `propose_quote_line` con `price_item_id` e prezzo ereditato dal listino
2. **Match multipli** → `"aggiungi a Q-2026-001 del color"` deve elencare in markdown le 3+ voci color (SDR/HDR/dailies) e chiedere quale
3. **Voce esplicitamente nuova** → `"aggiungi a Q-2026-001 una nuova voce Foley editing, listino 350/giorno categoria Audio"` deve produrre `propose_new_item_and_line`
4. **0 match con domanda** → `"aggiungi a Q-2026-001 un Beauty fix"` (voce inesistente) deve elencare in markdown opzioni (a) voce libera vs (b) scenario C

Dopo conferma test sul Mac, passare a **#4 server-side abort**.

## Backlog (in ordine concordato)

**Cantiere Calendario / Pianificazione (in corso, ordine D→A→B→C→E→F)**:
- ✅ **D** Booking multi-tenant (chiuso v3.4.6)
- 🔜 **Decisione architetturale timbrature/idle** (vedi sopra) prima di A
- 🔜 **A** UX calendario: drag/resize/move, filtro legenda funzionante (oggi è no-op), click evento → modal edit, mostrare `ResourceUnavailability` come banded events grigi
- 🔜 **B** UI `/resources/{id}` tab Disponibilità (CRUD `ResourceUnavailability`) + integrazione timbrature/idle
- 🔜 **C** Riconciliare `JobResourceAssignment` (kanban `/assignments`) ↔ `Booking` (calendario): assegnare risorsa a job propone booking sulle date job; oppure rendere kanban una vista alternativa stesso modello
- 🔜 **E** Capability AI `propose_booking` (conflict-check già esistente lato server)
- 🔜 **F** Vista gantt per job (start_date → end_date) sovrapposto a booking risorse

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

*Ultimo aggiornamento: 28 aprile 2026 — v3.4.6 chiusa: Booking ora ha `tenant_id` (fix coerenza Fase 1-bis), router `/planning` filtra per CURRENT_TENANT, migrazione idempotente `migrate_booking_tenant.py` voce [B]. Cantiere Calendario aperto: prossimo step decisione su modello timbrature/idle (3 opzioni in "Prossimo step concordato"), poi cascata A→B→C→E→F.*
