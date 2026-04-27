# STATO — MediaFlow

> Snapshot operativo, aggiornato a fine iterazione.
> Claude lo legge a inizio sessione per orientarsi, e lo aggiorna a fine giro.
> CLAUDE.md = visione/architettura. STATO.md = "dove siamo adesso, cosa fare dopo".

---

## Versione corrente

**v3.4.2** — 27 aprile 2026 sera tardi

## In corso

Nessun lavoro a metà.

## Prossimo step concordato

**#7 — UI human-readable per card AI nel copilot**

Refactor del template card di proposta (drawer copilot). Oggi mostra titolo + payload JSON crudo; va sostituito con renderer per type:

- `propose_client` → "Crea cliente: <nome> — <città/paese> — P.IVA xxx"
- `propose_project` → "Crea progetto <code>: <title> — cliente <nome>"
- `propose_quote` → tabella mini con righe (descrizione, qty, unit, prezzo, totale)
- `propose_quote_line` → "Aggiungi voce: <descrizione> — <qty> × <unit_price>"
- `propose_price_item` → "Aggiungi a listino: <descrizione> — <categoria>"
- `web_search` → "Cerca sul web: <query>"

Toggle in alto a destra "</> Mostra JSON" per visione tecnica/debug. Niente nuovi endpoint.

## Backlog (in ordine concordato)

1. **#7** UI human-readable card AI (next)
2. **#5** Search-first nel listino: AI cerca tra le voci esistenti, propone match con punteggio, chiede all'utente quale selezionare; solo se davvero non trova, scenario C (crea voce listino + linea quote in singola transazione). Chiude anche bug **#6** (copilot non aggiunge voci a quote esistente).
3. **#4 server-side** Abort lato server per Ollama/Claude (oggi è solo client-side `AbortController`).
4. **#1** Multi-valuta con cambio automatico ECB. Migrazione DB + servizio `app/services/fx.py` + UI dropdown valuta + capability AI `propose_quote_currency`. Conversione solo a display/PDF/export, EUR canonico in DB.
5. **F2** Gestione utenti + RBAC configurabile + link Resource→User con email password temp.
6. **F3** Cestino per-tenant con retention configurabile.

## Decisioni prese

- **Multi-valuta**: API ECB exchangerate.host (gratis, no key). EUR canonico in DB, conversione solo display/export.
- **Search-first AI**: priorità a match listino esistente. Fallback a scenario "C" (crea voce + linea in singola transazione) solo se utente conferma "non trovato".
- **Stop thinking**: tentare anche server-side abort (Matteo: "per evitare possibile sovraccarico richieste").
- **Esporta da copilot (#2 originale)**: skipped per ora.

## Bug aperti

- **#6 LLM matching listino**: il copilot, quando aggiunge righe a quote esistente, mette tutto in una `flat unit_price=0` invece di matchare voci listino. Risolto da #5 search-first.
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

*Ultimo aggiornamento: 27 aprile 2026 sera tardi — v3.4.2 chiusa, in standby prima di #7.*
