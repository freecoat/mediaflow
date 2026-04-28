# STATO — MediaFlow

> Snapshot operativo, aggiornato a fine iterazione.
> Claude lo legge a inizio sessione per orientarsi, e lo aggiorna a fine giro.
> CLAUDE.md = visione/architettura. STATO.md = "dove siamo adesso, cosa fare dopo".

---

## Versione corrente

**v3.4.9** — 28 aprile 2026

## In corso

Re-design del flusso `Quote → Job → Booking → Consuntivo → Cost Report`. Step **v3.4.8** (auto-promote) e **v3.4.9** (lavorazioni come prima class) chiusi. Il Job ora ha pagina dettaglio dedicata con monte ore, lavorate, extra. Lavorazioni extra puro aggiungibili via UI.

Calendario brutto graficamente — Matteo lo confermerà nello step UX (rinviato post v3.4.13).

## Prossimo step concordato

**v3.4.10 — Booking legati a lavorazione + booking interni**:
- `Booking.job_cost_line_id` (FK opzionale): pianificare "Sara · Color HDR · Mare Nostrum" invece di "Sara · Mare Nostrum"
- `BookingKind` enum: `project | internal_maintenance | internal_research | internal_training`. Per i `internal_*` `job_id` resta NULL → costo senza profitto, visibili in cost report interno
- Suggerimento risorse del reparto della lavorazione quando si crea booking (non bloccante)
- Quando aggiungo Booking.job_cost_line_id, le ore pianificate per riga diventano calcolabili → aggiornamento `_aggregate_planned_hours` per riga (oggi è solo job-level)
- Stessa cosa per `TimePunch.job_cost_line_id` (così `actual_hours_punch` può essere distribuito per lavorazione)

Verifiche sul Mac sospese:
- v3.4.5 modal "Aggiungi voce"
- v3.4.6 booking multi-tenant
- v3.4.7 sezione HR + calendario integrato
- v3.4.8 flusso Quote → Job auto
- v3.4.8.1 hotfix STATUS_LABEL e FullCalendar CSS
- v3.4.9 dettaglio job (`/jobs/{id}`) — accessibile cliccando un job in `/planning` poi "→ Vai al dettaglio job"
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

**Cantiere Quote → Job → Cost Report (in corso)**:
- ✅ **v3.4.8** Auto-promote Quote → Job + bug fix planning + rimosso job manuale
- ✅ **v3.4.8.1** Hotfix STATUS_LABEL + FullCalendar CSS
- ✅ **v3.4.9** Pagina `/jobs/{id}` con lavorazioni first-class (ore quotate/pianificate/lavorate/extra) + `is_extra` flag + CRUD lavorazioni extra
- 🔜 **v3.4.10** `Booking.job_cost_line_id` + `BookingKind` per booking interni; aggregazione ore pianificate/lavorate per lavorazione
- 🔜 **v3.4.11** `ResourceUnavailability`/`TimePunch.kind=leave` ben visibili nel calendario come fasce bloccanti
- 🔜 **v3.4.12** Cost report interno arricchito (costi risorse rate × ore TimePunch + hardcost + booking interni)
- 🔜 **v3.4.13** Cost report esterno (consuntivo cliente: solo ore lavorate + extra; bottone "→ Genera quote v2")

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

*Ultimo aggiornamento: 28 aprile 2026 — v3.4.9 chiusa: pagina `/jobs/{id}` con lavorazioni first-class (ore quotate/pianificate calendario/lavorate timbrature/extra), `JobCostLine.is_extra` flag con CRUD limitato (modifica sempre, elimina solo se extra), aggregazione ore al livello job, link da modal `/planning`. Smoke test E2E completo. Prossimo: v3.4.10 (booking legati a lavorazione + booking interni).*
