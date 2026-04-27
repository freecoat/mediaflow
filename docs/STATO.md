# STATO — MediaFlow

> Snapshot operativo, aggiornato a fine iterazione.
> Claude lo legge a inizio sessione per orientarsi, e lo aggiorna a fine giro.
> CLAUDE.md = visione/architettura. STATO.md = "dove siamo adesso, cosa fare dopo".

---

## Versione corrente

**v3.4.3** — 27 aprile 2026 sera tardi

## In corso

Nessun lavoro a metà.

## Prossimo step concordato

**#5 — Search-first nel listino**

L'AI, quando deve aggiungere righe a una quote, deve prima cercare tra le voci di listino esistenti, presentare i match (con punteggio o ordine di rilevanza), e chiedere all'utente quale selezionare. Solo se l'utente conferma che nessuna voce è valida, fallback su scenario "C": singola transazione che crea voce listino + linea quote.

Chiude anche **bug #6** (copilot non aggiunge righe a quote esistente: oggi mette tutto in una flat con `unit_price=0` invece di matchare il listino).

Implementazione attesa:
- nuovo helper di matching nel servizio AI (es. `app/services/pricelist_matcher.py`) — già esistono utility in `client_enrichment.py` come pattern
- nuova capability `propose_match_pricelist` (proposta multi-opzione: l'AI elenca i 3-5 match migliori e chiede conferma)
- nuova capability `propose_quote_line_with_new_item` (transazione: crea price_item + aggiunge a quote)
- system prompt aggiornato con regola "search-first"

## Backlog (in ordine concordato)

1. **#5** Search-first nel listino + scenario C (next)
2. **#4 server-side** Abort lato server per Ollama/Claude (oggi è solo client-side `AbortController`).
3. **#1** Multi-valuta con cambio automatico ECB. Migrazione DB + servizio `app/services/fx.py` + UI dropdown valuta + capability AI `propose_quote_currency`. Conversione solo a display/PDF/export, EUR canonico in DB.
4. **F2** Gestione utenti + RBAC configurabile + link Resource→User con email password temp.
5. **F3** Cestino per-tenant con retention configurabile.

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

*Ultimo aggiornamento: 27 aprile 2026 sera tardi — v3.4.3 chiusa (card copilot human-readable + toggle JSON), in standby prima di #5.*
