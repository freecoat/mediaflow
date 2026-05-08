# STATO — MediaFlow

> Snapshot operativo, aggiornato a fine iterazione.
> Claude lo legge a inizio sessione per orientarsi, e lo aggiorna a fine giro.
> CLAUDE.md = visione/architettura. STATO.md = "dove siamo adesso, cosa fare dopo".

---

## Versione corrente

**v3.5.0-alpha.51.1** — 8 maggio 2026 — Fix audit α.41→α.51 (3 critici + 4 minori)

Audit logico completo ha rivelato 3 bug critici e 4 alti sulla maratona
α.41→α.51, fissati prima di passare alle feature nuove.

**Chiuso α.51.1:**
- ✅ **C3 sicurezza /uploads**: rimosso `/uploads/` da `PUBLIC_PATHS`. Pre-fix
  tutti gli asset DAM e i capitolati copilot erano scaricabili senza auth.
- ✅ **C1 JCL.work_date populate**: `cost_line_sync.recompute_cost_line_actual`
  ora popola `work_date = max(start_datetime.date())` dei booking done.
  Backfill one-shot al boot via marker `uploads/.work_date_backfilled_v1`.
  Sblocca l'auto-derivazione periodo in `billing.preview_transmission`.
- ✅ **C2 AI resize/move recompute**: `_h_propose_resize_booking` e
  `_h_propose_move_booking` ora chiamano `recompute_for_booking`, allineato
  a `_h_propose_delete_booking`.
- ✅ **A2 JCL locked**: nuovo `_assert_jcl_not_locked` blocca AI su booking
  con JCL in stato `in_batch|billed|paid` (corromperebbe snapshot batch).
- ✅ **A4 BookingChange audit AI**: log in `booking_changes` per le 3
  capability AI (kind=`ai_move|ai_resize|ai_delete`).
- ✅ **A1 tenant_id**: filtro su `_resolve_booking_for_planning` e
  `set_jcl_billing_status` (via JOIN job→project).
- ✅ **A3 Invoice.number scoped**: check unicità via JOIN client per tenant.
- ✅ **M1 cancel_batch rilascia anche `lost`**: oltre a `in_batch`.
- ✅ **M5 cache-buster `global.js`**: bump α.43 → α.51.1 in `base.html`.

**Aperti (refactor non bloccante):**
- B1 OneDrive `st_mtime` su Mac (cleanup_old_attachments)
- B2 system prompt esplicitare "spostare booking done = retroattivo"
- M2/M3/M4 workflow tweaks

**Verifica smoke:**
- App boot pulita: version `3.5.0-alpha.51.1`, 258 route
- Backfill `work_date` runs al primo boot, marker per idempotenza

**v3.5.0-alpha.51** — 7 maggio 2026 — Upload documenti per copilot (PDF/DOCX/TXT/MD/immagini)

Richiesta serale Matteo. MVP solido: upload via clip 📎 o drag&drop nel
drawer copilot, estrazione testo PDF/DOCX/TXT/MD inline nel messaggio AI,
immagini salvate con placeholder testuale (vision integration in α.52).

**Chiuso α.51:**
- ✅ Servizio `app/services/copilot_attachments.py`: save/extract/embed/cleanup
- ✅ Endpoint `POST /ai/api/upload` (multipart, max 20MB, ammette
  pdf/docx/txt/md/jpg/jpeg/png/webp/gif)
- ✅ Storage `uploads/copilot/{uuid}.{ext}` + mount `/uploads` pubblico
- ✅ Cleanup auto > 7gg in lifespan startup
- ✅ Endpoint `/ai/api/chat` integra `attachments[]` via embed inline
  nell'ultimo messaggio user
- ✅ UI: bottone clip in input bar, drag&drop overlay tutto il drawer,
  lista allegati con badge tipo/size/× rimuovi
- ✅ Stati ⏳ uploading + ⚠ errore con border rosso
- ✅ PDF estratto via pypdf, DOCX via python-docx, TXT/MD raw
- ✅ Immagini: dimensioni Pillow + placeholder testuale per AI
- ✅ Cache-buster copilot.js?v=3.5.0-alpha.51

**Verifica live richiesta a Matteo:**
- Apri copilot da qualsiasi pagina
- Click 📎 → seleziona PDF (es. capitolato cliente)
- Card appare con nome + caratteri estratti + size + ×
- Scrivi prompt tipo "Leggi questo capitolato e proponi una quote"
- Send → AI riceve testo PDF inline + risponde proponendo azioni
- Test drag&drop: trascina file nel drawer → overlay "Rilascia qui" → upload
- Test rimozione × prima del send
- Test errore: trascina file > 20MB → toast errore

**Limitazioni note MVP**:
- Immagini: caricate + visibili in card ma AI riceve solo placeholder
  testuale (vision blocks per Claude/OpenAI/Gemini in α.52)
- Niente persistenza DB: dopo refresh allegati spariscono dal client
  (file su disk fino al cleanup 7gg)
- Niente OCR per screenshot con testo

**Prossimi step:**
- α.52: vision integration per immagini (Anthropic Messages API supporta
  image blocks → modifica build_messages per provider che hanno vision)
- Domani: fattura formale PDF + anagrafica cliente + dati aziendali tenant
  (rimandato da stasera per stanchezza)
- Capability copilot avanzate: recurring_bookings, bulk_move,
  analyze_conflicts, find_free_slots
- Notifiche proattive sul FAB

**v3.5.0-alpha.50** — 7 maggio 2026 — Copilot in-depth integration nella pianificazione

Pre-α.50 il copilot vedeva clienti/progetti/listino/quote ma NIENTE
pianificazione viva → poteva creare booking ma "alla cieca". Ora ha
context completo + 3 capability per operare su booking esistenti +
quick prompts contestuali per pagina.

**Chiuso α.50:**
- ✅ Sezione PIANIFICAZIONE VIVA in `build_context` (booking 14gg,
  conflitti, carico per risorsa, indisponibilità, job critici), filtra
  per project_id/job_id se presenti
- ✅ 3 capability nuove: `propose_move_booking` (shift/new_date/
  new_resource/remap), `propose_resize_booking` (delta minuti),
  `propose_delete_booking` (soft-delete con reason). Tutti con
  conflict-check pre-apply, atomic
- ✅ Tool spec in `ai_tools.py` per provider tool_use nativo + handler
  in `ai_assistant.py`
- ✅ System prompt rinforzato con sezione "PIANIFICAZIONE — operazioni
  sulla timeline" (7 regole: consulta context, rispetta indisponibilità,
  carico bilanciato, segnala conflitti, spiega perché, ricorrenti uno
  alla volta, link a job_cost_line)
- ✅ Quick prompts contestuali nel drawer per pagina (/planning ha 7
  prompt dedicati: Diagnostica + Pianificazione)
- ✅ Renderer human-readable per le 3 nuove card in copilot.js
- ✅ Cache-buster copilot.js?v=3.5.0-alpha.50

**Verifica live richiesta a Matteo:**
- Pull → app parte
- /planning → click FAB copilot → vedi quick prompts dedicati
  ("Mostrami i conflitti", "Sposta booking", ecc.)
- "Mostrami i conflitti orari della prossima settimana" → AI risponde
  consultando il context PIANIFICAZIONE VIVA
- "Sposta il booking #42 di +1 giorno" → AI propone
  `propose_move_booking` → card conferma → Apply → booking spostato
- "Allunga il booking #42 di 2 ore" → propose_resize → conferma → apply
- "Cancella il booking #42" → propose_delete → conferma → soft-delete
  (recuperabile dal Cestino)

**Prossimi step (futuri):**
- Capability avanzate: recurring_bookings, bulk_move, analyze_conflicts,
  find_free_slots
- Notifiche proattive sul FAB se rilevati problemi
- Capability per Billing: propose_transmit_to_billing
- Domani: fattura formale PDF con dati cliente (P.IVA) + dati aziendali
  proprietario (configurazione tenant settings)

**Bug ancora aperti:**
- Freeze Chrome Mac specifico (workaround light mode in toolbar)

**v3.5.0-alpha.49** — 7 maggio 2026 — Step 4 Cost Report → Billing flow: UI /finance batch

Step 4 chiuso. Pagina `/finance` ora ha tab dedicata "📦 Batch fatturazione"
con lista filtrata, drawer dettaglio editabile, bottoni azione complete
(approve/cancel/emit invoice), anteprima IVA live, sezione perso aggregato
per progetto.

**Chiuso α.49:**
- ✅ Tab `📦 Batch fatturazione` in /finance con badge giallo count draft
- ✅ Tabella batch: code, project, status, periodo, proposto/approvato/perso, fattura
- ✅ Filtro status (draft/approved/invoiced/cancelled)
- ✅ Auto-open via deep-link `/finance#batch-{id}` (link da cost report)
- ✅ Modal dettaglio batch (920px): meta-grid + lines table + footer dinamico
- ✅ Edit line inline (solo draft + manager+): input importo + prompt
  loss_reason se ridotto < proposed → PATCH endpoint α.47 + toast delta
- ✅ Bottone ✅ Approva (draft → approved)
- ✅ Bottone 💶 Emetti fattura (modal con number/date/VAT live + POST emit)
- ✅ Bottone ↩ Annulla batch (rosso, con conferma)
- ✅ Pannello "Perso aggregato" con totale + breakdown by_reason
- ✅ Auto-load batch al boot (per badge tab anche se utente è su altra tab)

**Verifica richiesta a Matteo:**
- Pull → app parte
- /finance → click tab "📦 Batch fatturazione"
- Vedi lista batch (se hai trasmesso da cost report)
- Click su batch draft → modal dettaglio con lines editabili
- Modifica importo (es. 100 → 80) → prompt motivo → vedi 20 perso + totale aggiornato
- ✅ Approva → batch approved
- 💶 Emetti fattura → numero+data → Invoice creata + visibile in tab Fatture
- Test deep-link: /cost-report → click su una card batch → /finance si apre
  con modal dettaglio aperto direttamente

**Bug ancora aperti:**
- Freeze Chrome Mac specifico (non bug MediaFlow, workaround light mode)

**Prossimi step:**
- α.50: notifica fine mese auto + chiusura progetto (producer "Chiudi
  lavorazioni") + report finanziario completo

**v3.5.0-alpha.48.2** — 7 maggio 2026 — Periodo trasmissione auto-derivato dai booking

Richiesta Matteo. GET /finance/api/billing/preview calcola period_start/end
da min/max work_date JCL candidate (popolate da cost_line_sync su booking
done). Modal Trasmetti popola defaults dal preview, mostra anteprima
righe+totale, label sorgente periodo (📅 from_bookings vs ⚠ fallback).
Submit disabled se zero candidate.

**v3.5.0-alpha.48.1** — 7 maggio 2026 — Bottone Ritira su card batch (cancel pre-invoice)

Bottone ↩ Ritira (rosso) sulla card batch nel widget cost report.
Visibile solo se status in {draft, approved}. Confirm + cancel endpoint
α.47 → JCL rilasciate, LossEntry cancellate, batch → cancelled.

**v3.5.0-alpha.48** — 7 maggio 2026 — Step 3 Cost Report → Billing flow: UI Cost Report

Step 3 del workflow billing. UI Cost Report ora mostra stato fatturazione
per riga + widget Fatturazione (sommario + batch elenco) + modal Trasmetti.
Endpoint API α.47 collegati al frontend.

**Chiuso α.48:**
- ✅ API `cost_report.py` estesa: `cost_lines[]` con billing_status/
  billing_batch_id/billed_amount/is_extra; `job` con project_id;
  `billing_batches[]` + `billing_summary` aggregati per stato
- ✅ Helper backend `_billing_batches_for_job` + `_billing_summary_for_job`
- ✅ Template colonna `Fatt.` con badge colorato per stato (5 colori)
- ✅ Marcatore `[extra]` arancio sulle righe is_extra
- ✅ Widget Fatturazione header: 5 card sommario + elenco batch
  cliccabili (link `/finance#batch-{id}`)
- ✅ Bottone `📤 Trasmetti a fatturazione` + modal con periodo/extras/note
- ✅ Submit chiama `POST /finance/api/billing` (α.47), refresh report
  per vedere nuovi stati

**Verifica live richiesta a Matteo:**
- Pull → app parte normale
- Apri `/cost-report` → seleziona un job con maturato (booking done +
  total_accrued > 0)
- Vedi nuova colonna `Fatt.` nella tabella cost lines (default tutti
  grigio "Da fatturare")
- Vedi widget Fatturazione sopra la tabella con 5 card sommario
- Click bottone `📤 Trasmetti a fatturazione` → modal apre
- Default periodo = mese corrente. Submit → batch creato (toast)
- Refresh: righe diventano ambra "In approv." + card batch appare
  nel widget
- Click sulla card batch → apre `/finance` in nuova scheda (UI batch
  arriva in α.49)

**Bug ancora aperti:**
- Freeze Chrome Mac specifico (workaround light mode disponibile)
- Step 4-5 cost report flow (UI /finance, notifiche, chiusura progetto)

**Prossimi step:**
- α.49: UI `/finance` con elenco batch + edit manager + voce perso
- α.50: notifica fine mese + chiusura progetto + report finanziario

**v3.5.0-alpha.47.1** — 7 maggio 2026 — HOTFIX Bulk button non attivava dopo ROI/Esc

Matteo: "Bulk non funziona quando bookings multiselected. Dovrebbe attivarsi?"

**Diagnosi**: vis-timeline 7.x emette `select` event SOLO per click utente,
non per `setSelection()` programmatico. Il ROI/area (tasto S + drag) usa
setSelection da codice → no event → `tlOnSelectionChange` mai chiamato →
button Bulk disabled anche con selezione popolata.

**Chiuso α.47.1:**
- ✅ Helper `_tlSetSel(ids)` che wraps setSelection + tlOnSelectionChange
  + sync cache `window._tlPrevSelection` per sticky α.42
- ✅ Sostituite 2 chiamate "nude" con il wrapper:
  ROI/area in `tlRoi*` + Esc clear in keyboard handler
- ✅ Le 4 select-by-* avevano già tlOnSelectionChange manuale → no toccate

**Verifica live richiesta a Matteo:**
- `/planning` → tasto S → drag area su 2-3 booking → bottone Bulk in
  toolbar deve diventare attivo (indigo + counter "(N)")
- Click Bulk → modal apre normalmente
- Esc per pulire → bottone torna disabled

**v3.5.0-alpha.47** — 7 maggio 2026 — Step 2 Cost Report → Billing flow: API endpoints

Step 2 del workflow billing concordato con Matteo. **9 endpoint API**
backend pronti, ancora niente UI (arriva in α.48-49).

Quick fix UI incluso: bottone `⛶ Finestra` in toolbar timeline ora
nascosto in `/planning/full` (era illogico).

**Endpoint creati** (`app/routers/billing.py`, prefix `/finance/api/billing`):
1. `POST /` transmit JCL maturate → BillingBatch (draft)
2. `GET /` lista con filtri
3. `GET /{id}` dettaglio + lines snapshot
4. `PATCH /{id}/lines/{lid}` manager edit importo (auto LossEntry)
5. `POST /{id}/approve` manager approva
6. `POST /{id}/invoice` emette Invoice + linka, JCL→billed
7. `POST /{id}/cancel` annulla batch (rilascia JCL→not_billed)
8. `PATCH /jcl/{id}/billing-status` override manuale stato
9. `GET /loss/project/{id}` sommario perso (rendicontazione)

**Logica chiave:**
- Auto-numero `BB-{anno}-{NNN}` (no riciclo cancelled)
- Snapshot immutabile (BatchLine cattura proposed al transmit)
- Loss tracking: edit manager < proposed → LossEntry
- Cap di sicurezza: approved ≤ proposed × 1.5
- JCL state machine: not_billed→in_batch→billed→paid (loss in caso di approved=0)
- Numero fattura MANUALE (no interferenza con gestionale fiscale esterno)
- VAT default 22% configurabile per chiamata
- RBAC: view_finance per read+transmit, manager+ per modifica/approve/invoice/cancel

**Verifica richiesta a Matteo:**
- Pull → app parte senza crash (auto-migrate α.46 + nuove tabelle già OK)
- Apri `http://localhost:8000/docs` → sezione `billing` → vedi 9 endpoint
- Flusso completo via /docs (oppure curl):
  1. POST `/finance/api/billing` con project_id, period_start, period_end
  2. GET `/finance/api/billing/{batch_id}` → vedi snapshot
  3. PATCH `/lines/{lid}` con total_approved ridotto → LossEntry generata
  4. POST `/{id}/approve` → status approved
  5. POST `/{id}/invoice` con number+date → Invoice creata + JCL=billed
  6. GET `/loss/project/{pid}` → totale perso
- Test bottone Finestra: apri `/planning/full` → toolbar non deve avere `⛶ Finestra`

**Bug ancora aperti:**
- Freeze Chrome Mac specifico (non bug MediaFlow, conferma da test PC OK)
- Light mode α.46.2 resta come safety net

**Prossimi step:**
- α.48: UI Cost Report con stati billing colorati + bottone "Trasmetti"
- α.49: UI `/finance` con batch list + edit manager + perso
- α.50: notifica fine mese auto + chiusura progetto + report finanziario

**v3.5.0-alpha.46.2** — 7 maggio 2026 — Modalità leggera timeline (vera causa freeze)

α.46.1 ipotizzava Bitwarden come causa principale del freeze Chrome.
Test Matteo in **incognito** (no estensioni) → freeze persiste.
Diagnosi sbagliata. Riapertura analisi trace.

**Vera causa:** vis-timeline con `stack: true` ricalcola overlap di
TUTTI gli items per evitarne la sovrapposizione. Algoritmo O(N²).
Con 30+ booking + 600+ background items (ferie/festa/weekend/punch
moltiplicati × 20 risorse) + zoom mese, ogni `requestAnimationFrame`
blocca 200+ms.

Numeri trace conferma:
- Top RunTask: 480ms, 416ms, 414ms, 396ms, 342ms, 337ms, 304ms (~3s
  congelati nei 7 task più lunghi)
- PageAnimator (single rAF): 225ms picco
- Layout: 92ms picco
- 18,761 Paint events

**Chiuso α.46.2:**
- ✅ Bottone `🪶 Light` in toolbar timeline (persistenza
  `localStorage.mf_tl_light_mode`)
- ✅ Light ON disabilita: `stack: false` + `stackSubgroups: false` +
  background items (ferie/festa/punch) + animazioni/transition CSS
  su `.vis-item`
- ✅ Toast informativo on toggle
- ✅ CSS `#tl-host[data-light="on"]` disabilita filter:hover, animation,
  transition (riducono i 18k Paint events)

**Verifica richiesta a Matteo:**
- Chrome (anche normale, non solo incognito) → `/planning` → click
  bottone `🪶 Light` in toolbar → diventa indigo evidenziato
- Zoom mese 30+ booking → deve scorrere fluido
- Trade-off: items sovrapposti visivamente (no impilamento). Per
  leggibilità precisa, zoom giorno/settimana o disattiva light mode

**Bug ancora possibili:**
- Se anche light mode freeza → vis-timeline 7.7.3 ha bug native pure
  senza stack. Soluzione finale: sostituzione libreria (Bryntum/DHTMLX),
  backlog Round 12

**v3.5.0-alpha.46.1** — 7 maggio 2026 — Mitigazione freeze Chrome (estensioni autofill)

Performance trace Chrome di Matteo ha identificato il colpevole: NON è
vis-timeline da solo (2.4s su 65s totali), ma Bitwarden + altre estensioni
autofill che osservano il DOM e scansionano migliaia di nodi creati da
vis-timeline durante zoom mese.

**Numeri dal trace `Trace-20260507T171123.json.gz`:**
- 24,124 chiamate a Bitwarden script (838ms)
- 41 callback `CollectAutofillContentService.handleMutationObserverMutation`
- 55 `setupOverlayOnField` schedule via setTimeout
- vs. solo 22ms global.js MediaFlow

**Chiuso α.46.1:**
- ✅ `data-bwignore` + `data-lpignore` + `data-1p-ignore` + `autocomplete="off"`
  su `#tl-host` e form modal booking → estensioni well-behaved skippano scan
- ✅ FAQ manuale aggiornata con workaround Chrome (incognito test, exclude
  localhost Bitwarden, Firefox, pagina standalone, heatmap off)

**Test richiesto a Matteo:**
- **Cmd+Shift+N** (incognito Chrome) → `localhost:8000/planning` → zoom
  mese 30+ booking. Se in incognito funziona fluido = causa CONFERMATA
  estensioni. Soluzione: Bitwarden Settings → Excluded Domains → aggiungi
  `localhost`. Allora anche Chrome normale funzionerà
- Verifica anche pull dei nuovi attributi `data-bwignore`: rebooting
  app + hard refresh

**Bug ancora aperti:**
- ⚠ Vis-timeline 7.7.3 da solo è pesante (2.4s su 65s del trace) ma non
  causa il freeze. Sostituzione libreria (Bryntum/DHTMLX) resta nel backlog
  ma NON è urgente con la mitigazione attuale
- ⚠ Cost Report flow: implementato solo Step 1 (modello dati α.46),
  prossimi step α.47-50 (API + UI)

**v3.5.0-alpha.46** — 7 maggio 2026 — Step 1 Cost Report → Billing flow: modello dati

Primo step del workflow Cost Report ↔ Fatturazione concordato con Matteo.
**Solo modello dati + migrazione**, niente API/UI nuove (arrivano in α.47-50).

**Workflow target (NON ancora attivo):**
1. Cost Report → "Trasmetti a fatturazione" (manuale + notifica fine mese)
2. BillingBatch creato (snapshot JCL maturate del periodo)
3. Manager in /finance rivede + può modificare importi (delta → LossEntry)
4. Approva → emette fattura → JCL.billing_status=billed
5. Pagata → JCL=paid
6. A chiusura progetto: producer click "Chiudi" → fattura finale + perso
   aggregato per rendicontazione finanziaria

**Chiuso α.46:**
- ✅ Enum: JCLBillingStatus, BillingBatchStatus, LossReason
- ✅ JobCostLine esteso: billing_status, billing_batch_id, billed_amount
- ✅ BillingBatch (code BB-{anno}-{NNN}, project_id, period, totali,
  audit transmit/approve, invoice_id)
- ✅ BillingBatchLine (snapshot immutabile JCL al transmit)
- ✅ LossEntry (importo, reason, project_id, audit user)
- ✅ Auto-migrate al boot in main.py per le 3 colonne JCL
- ✅ Script esplicito scripts/migrate_billing_flow.py
- ✅ Models __init__.py exporta i nuovi nomi

**Verifica Matteo dopo pull:**
- App parte senza crash (auto-migrate dovrebbe gestire ALTER TABLE)
- Se preferisce esplicito: `python scripts/migrate_billing_flow.py`
- Niente da testare in UI: tutto invariato dal punto di vista utente
- Cost report mostra ancora le stesse info di α.45 (i nuovi campi
  esistono ma non sono ancora esposti)

**Prossimi step concordati:**
- α.47: API trasmissione/approvazione/emissione fattura da batch
- α.48: UI Cost Report con stati colorati + bottone "Trasmetti"
- α.49: UI /finance con batch + modifica manager + perso
- α.50: notifica fine mese + chiusura progetto + report finanziario

**Bug ancora aperti:**
- ⚠ Freeze Chrome con 30+ booking + zoom mese (Firefox OK). Matteo sta
  facendo test debug. Workaround "modalità leggera" pronto da implementare

**v3.5.0-alpha.45** — 7 maggio 2026 — Bulk visibile + "Fatto" in fondo

Quick fix utenza dopo test α.44.1:

**Chiuso α.45:**
- ✅ Bottone "✏ Bulk" toolbar timeline sempre visibile (era display:none
  → Matteo "sparito"). Disabled+grigio se no selezione, attivo+indigo
  con counter (N) quando ha item selezionati
- ✅ Sort "Le mie" + "Per progetto": booking con execution_status terminale
  (done/not_done) vanno SEMPRE in fondo, prima i task ancora attivi.
  Modifica in `_cmpByPrioThenDate`

**Bug ancora aperti:**
- ⚠ **Freeze Chrome con 30+ booking + zoom mese PERSISTE** anche dopo
  α.44.1. NON era né heatmap né resize loop la causa primaria. Ipotesi
  residue:
  - vis-timeline 7.7.3 `stack:true` con O(N²) overlap detection
    esplode con N>30 + items larghi (zoom mese)
  - background items (ferie/festa/punch) raddoppiano il count
  - Bug Chrome rendering vis-timeline specifico
  Serve **Performance profile DevTools** da Matteo per puntare il
  problema. Possibile workaround: modalità "leggera" che disabilita
  stack/animazioni/background
- ⚠ Warning CSP "blocks eval" Chrome — collegato? Probabilmente no
  ma da indagare insieme

**v3.5.0-alpha.44.1** — 7 maggio 2026 — HOTFIX freeze Chrome 30+ booking

Test α.44 su Chrome/Mac con 30+ booking + 20+ risorse: timeline sfarfalla
da 2 settimane in su, sparisce griglia giorni a zoom mese, Chrome si
blocca. Firefox/Mac stesso scenario funziona.

**Diagnosi:** rangechanged callback ricostruiva via `tlBuildGroups()` +
`groupsDS.update()` TUTTI i groups foglia ad ogni evento. Dopo fix α.41
(heatmap cells come HTMLElement), 20 risorse × 30 giorni zoom mese =
**600+ DOM nodes ricreati ad ogni rangechanged**. Vis-timeline emette
rangechanged anche per piccoli movimenti pan → cascade DOM thrash →
main thread bloccato Chrome.

**Chiuso α.44.1:**
- ✅ Skip rangechanged update se `prefs.heatmap=false` (default α.44):
  nessun contenuto dinamico nei groups → niente rebuild necessario
- ✅ Dedup range signature `window._tlLastRangeSig` (skip se
  start+end identici al precedente)
- ✅ Throttle bumped 150→500ms su `_tlHeatTimer`
- ✅ Batch update: `groupsDS.update(arr)` invece di N call separate
- ✅ Anti-loop `_tlBindResize`: skip se delta height < 8px,
  throttle 250ms, tracking `window._tlLastHeight`
- ✅ `_doRenderTimeline` resetta `_tlLastRangeSig` + clearTimeout
  `_tlHeatTimer` per nuova istanza

**Verifica live richiesta a Matteo:**
- `/planning` su Chrome con 30+ booking. Zoom: settimana → mese.
  Non deve più sfarfallare né bloccare la pagina
- Ridimensiona finestra browser → no loop di resize
- Se attivi heatmap (📊 toolbar) e poi zoom mese: con questi fix il
  rebuild è throttled ma comunque presente. Su monitor lento può
  ancora pesare. Soluzione futura se persiste: rendere heatmap
  generata con CSS (background-image gradient) invece di N div

**Bug ancora aperti:**
- ⚠ Warning CSP "blocks eval" in Chrome — probabilmente vis-timeline
  7.7.3 usa `new Function()` interno. Non sembra causa del freeze (era
  ovunque, non solo > 30 booking). Da rivisitare se freeze persiste
- ⚠ Timeline nera in Chrome — separato. In attesa info DevTools

**Niente migrate, solo template planning.html + bump main.py.**

## v3.5.0-alpha.44 — Heatmap toggle + altezza dinamica + finestra standalone (7 maggio 2026)

Test live α.43 ha riportato 4 issue + 1 da indagare. Risolti: heatmap
"quadratini verdi" (era una feature pre-esistente che ora si vede grazie
al fix font α.41 — default cambiato a OFF), altezza fissa 600px che
sprecava monitor grandi e schiacciava 20+ risorse (ora dinamica viewport),
richiesta scorporo timeline in finestra dedicata (`/planning/full` standalone).

**Chiuso α.44:**
- ✅ Heatmap default OFF (`TL_PREFS_DEFAULTS.heatmap=false`) +
  bottone toolbar `📊 Heatmap` con sync popover ⚙
- ✅ Altezza timeline dinamica: `tlComputeHeight(host)` da viewport
  (`window.innerHeight - host.top - 24`, min 400px). Listener `resize`
  con debounce 150ms → `setOptions({height})` senza re-render
- ✅ Pagina `/planning/full`: nuovo route che render `planning.html`
  con `full_screen=True`. `base.html` condizionali skip sidebar+topbar.
  CSS `body.no-chrome`. Refactor helper `_planning_render` per
  condividere la logica con `/planning`. Bottone `⛶ Finestra` in toolbar
  che fa `window.open` con popup features (fallback tab)
- ✅ Cache-buster CSS bumpato a `?v=3.5.0-alpha.44`

**Verifica live richiesta a Matteo:**
- `/planning` → tab Timeline. Cella heatmap NON deve apparire più sotto
  i nomi (default OFF). Bottone `📊 Heatmap` in toolbar → click attiva,
  click di nuovo disattiva. Stato persiste in localStorage
- Ridimensiona finestra browser → la timeline si ridimensiona di
  altezza automaticamente (era fissa a 600px)
- Su monitor grande (es. 27" 4K) la timeline occupa tutto lo spazio
  utile, non solo 600px iniziali
- Bottone `⛶ Finestra` → si apre popup/tab a `/planning/full` senza
  sidebar e senza topbar. Solo card timeline + filtri sidebar interna
  (la `.pl-sidebar` di pagina)
- Sulla pagina /planning/full la stessa funzionalità (drag, multi-move,
  Ctrl+Z, Ctrl+B per sidebar — quest'ultimo nullo perché non c'è
  sidebar globale)

**Bug ancora aperto:**
- Timeline nera in Chrome (solo Chrome, Firefox OK su Mac). Da
  diagnosticare con info DevTools da Matteo: dove esattamente succede,
  console errors, tab Elements → background del `.vis-timeline`

**Niente migrate.**

## Storico recenti

**v3.5.0-alpha.43** — 7 maggio 2026 — Sidebar collassabile + Manuale d'uso wiki

Quality-of-life: sidebar collapse a 64px (toggle topbar + Ctrl+B + persistenza
localStorage), tooltip flottante hover 1s su icone collassate. Pagina /manuale
wiki interna con TOC sticky + content + search client-side + IntersectionObserver.
11 sezioni con bozze contenuti. Voce sidebar "Manuale" in nuova sezione "Aiuto".

**v3.5.0-alpha.42** — 7 maggio 2026 — Multi-move atomico + sticky multi-selection

Test live (2 booking ricorrenti split risorsa multipla) ha esposto 3
sintomi convergenti su unica root cause: `onMove` chiamava in sequenza 3
funzioni indipendenti, ognuna con suo PUT/POST + push undo + render
parziale. Sintomi: "booking spariscono" (render parziale), "14 undo per
ripristinare" (push frammentato), conflitti fantasma (check su stato
intermedio), click+drag deseleziona. Fix: endpoint atomico
`POST /planning/api/multi-move` con conflict check escludendo TUTTI gli
aids della transazione + all-or-nothing rollback; frontend
`_tlApplyMultiMove` (anchor + sibling + altri + loro-sibling con dedup)
con 1 push undo atomico + 1 renderTimeline finale; sticky multi-selection
con loop guard sincrono.

**v3.5.0-alpha.41** — 7 maggio 2026 — Font label timeline via HTMLElement (vis-timeline strippa style annidati)

α.40 ha messo inline styles brutali nelle stringhe HTML del content delle
label risorsa, ma il bold/font sui nomi operatore restava invisibile (header
reparto invece corretto). Diagnosi confermata da DOM dump Matteo: tutti i
class+style annidati spariti. Vis-timeline 7.7.3 sanifica gli HTML string
passati come `group.content` quando contengono nested elements. Fix: passare
HTMLElement detached (`document.createElement` + `style.cssText` +
`textContent`). Header reparto invariato (single `<span>` root).

**v3.5.0-alpha.40** — 6 maggio 2026 — Inline styles font + no-confirm multi-move + no race split

α.39 ha sistemato i tint colore-risorsa (visibili) ma il bold/font su
nome operatore + funzione restavano invisibili nonostante CSS
`!important`. La fix con inline styles brutali NON ha risolto (vedi α.41
per la diagnosi vera: vis-timeline strippa style+class annidati).
Restano validi gli altri due interventi: NO-CONFIRM multi-move +
tlPushUndo + NO RACE SPLIT.

**v3.5.0-alpha.39** — 6 maggio 2026 — Fix tint+font + multidrag bulk + render mutex

Tre bug bloccanti chiusi: tint sfondo via `_tlInjectResourceTints` (era
silenziato da `window.RESOURCES_SEED` undefined), multidrag refactor a
bulk-edit (1 round-trip), render serializzato via promise queue. Il
font/bold restava invisibile nonostante CSS aggressivo: chiuso in α.40
con inline styles.

**v3.5.0-alpha.38** — 6 maggio 2026 — Polish ROI/look + bulk-edit esteso + filtro orario

Round di rifiniture: rimosso bottone Seleziona, ROI selezione additiva,
look label timeline (font + tint colore-risorsa, ma con bug
`window.RESOURCES_SEED` che ha richiesto α.39 per essere visibile),
bulk-edit con orario assoluto + nuova data, filtro orario nei filtri.

**v3.5.0-alpha.37** — 6 maggio 2026 — Fix ROI: tasto S + selezione precisa per riga

α.36 ha portato l'overlay-div funzionante; due bug emersi al test live
chiusi: tasto S inerte (sostituita guardia ACTIVE_VIEW con check classe
`.active` su `#view-timeline`) e selezione che includeva righe
sottostanti (rimossa logica group-set buggata, sostituita con check
DOM rect per ogni item via `tlInstance.itemSet.items[id].dom.box`).

**v3.5.0-alpha.36** — 6 maggio 2026 — ROI overlay-based + scorciatoia tastiera "S"

Riscrittura totale del ROI dopo che α.35 non funzionava: vis-timeline
7.x usa Hammer.js su PointerEvents, mousedown capture-phase non basta.
Approccio definitivo: overlay-div trasparente sopra l'host. Aggiunta
scorciatoia tastiera `S`. Funzionante ma con due bug emersi al test
live (chiusi in α.37): tasto S inerte e selezione che includeva righe
sottostanti.

**v3.5.0-alpha.35** — 6 maggio 2026 — ROI rubber-band riabilitato + funzione sotto nome operatore

Primo tentativo di riabilitazione ROI (handler in-line + Alt-drag +
toggle persist-mode). Non funzionava per Matteo: vis-timeline/Hammer.js
intercettava i mouse events. Sostituito da α.36 con approccio overlay-div.
Resta valida la parte "funzione (role) sotto nome operatore" nelle
foglie risorsa della timeline (RESOURCES_SEED esteso + render
`tl-res-name` + `tl-res-role` font 10.5px italic muted).

**v3.5.0-alpha.34** — 6 maggio 2026 — Admin Export/Import dati

Tool admin per export/import completo (DB + memorie Claude + Excel
human-readable). Risolve sync PC↔Mac (memorie vivono fuori dal repo) +
funziona come backup/restore generico. Pagina dedicata in `/settings`,
solo admin.

**Chiuso α.34:**
- ✅ `app/services/data_export.py`: `build_export_zip()` con DB + metadata +
  README + Excel multi-sheet (listino/quotazioni) + memorie Claude (path
  mangled cross-OS), opt-in env/uploads/trash, AES-256 password via pyzipper
- ✅ `app/services/data_import.py`: `restore_from_zip()` con check major
  version, DB swap atomico (backup auto + rollback su errore), memorie
  ricalcola path mangled per macchina locale (non riusa quello sorgente)
- ✅ `app/routers/admin_data.py`: 4 endpoint sotto `/settings/admin/data/*`
  con dependency `_require_admin` (RBAC `is_admin`)
- ✅ Tab "Dati" in `/settings` (icona Lucide `database`), visibile solo se
  `is_admin(user)`. Card Export con 4 checkbox + password. Card Import con
  file upload + password + 3 restore flag + warning rosso
- ✅ JS `adminExportZip()` (window.location download) e `adminImportZip()`
  (confirm + summary actions/warnings)
- ✅ Dependency: `pyzipper>=0.3.6` aggiunto a requirements.txt

**Verifica live richiesta a Matteo:**
- Apri `/settings` come admin, vedi la nuova tab "Dati"
- Click "Scarica ZIP completo" senza opzioni opt-in: arriva ZIP base
  (~MB con DB + Excel + memorie)
- Click "Solo Excel listino" / "Solo Excel quotazioni": file `.xlsx`
- Su altra macchina (Mac): tab Dati → Import → carica lo ZIP →
  conferma → vedi summary con "DB ripristinato" e "Memorie Claude
  ripristinate (N file) in /Users/.../memory"
- Riavvia il server dopo restore

**Note operative**:
- Password ZIP cifra con AES-256 standard (apribile anche da 7zip/WinZip
  con la password — utile se vuoi consultare il contenuto manualmente)
- Backup DB precedente sopravvive: `mediaflow.db.backup-<timestamp>` in
  cartella progetto. Cancellabile a mano una volta verificato il restore
- Major version mismatch rifiutato: export α.34 in app α.34/35/36 ok,
  in app v4.x rifiuta (schema potrebbe essere cambiato)
- `.env` opt-in: di default NO. Se attivo, l'export contiene secrets
  (API keys, JWT secret, AI_KEY_ENCRYPTION_KEY) — non condividere

**v3.5.0-alpha.33** — 6 maggio 2026 — Capability copilot `propose_resource`

Nuova capability AI per creare risorse via copilot. Pattern coerente con
le altre 9 mutation: AI propone, utente conferma in drawer. Renderer
human-readable per la card.

**Chiuso α.33:**
- ✅ `ai_tools.py`: tool definition `propose_resource` (name+type required,
  6 ResourceType ammessi, dept_id|dept_name, role, tariffe, contatti)
- ✅ `ai_assistant.py`: handler `_h_propose_resource` con validazioni +
  resolve dept (id/name) + `_opt_num` per tariffe (0/None → NULL DB) +
  color sanitization
- ✅ Registrato in `_ACTION_HANDLERS` e `VALID_ACTION_TYPES` (recuperato
  anche `propose_booking` che mancava lì da α.20)
- ✅ `ASSISTANT_SYSTEM_PROMPT` aggiornato con schema della nuova capability
- ✅ `copilot.js`: label "Risorsa (nuova)", `summaryResource` + `summaryBooking`
  (anche quest'ultimo mancava — cadeva nel fallback "Nessun renderer")
- ✅ Cache-buster `copilot.js?v=3.5.0-alpha.33` in `components/copilot.html`

**Verifica live richiesta a Matteo:**
- Apri il copilot (FAB ⓘ in basso a destra) e chiedi: "Crea una risorsa
  freelance Mario Rossi colorist nel reparto DI"
- L'AI dovrebbe rispondere con un blocco action `propose_resource`
- La card di conferma dovrebbe mostrare riassunto leggibile (non JSON grezzo)
- Click "Applica" → la risorsa appare in `/resources` con i campi corretti
- Tariffe non specificate → restano vuote (non 0)

**Niente migrate**: solo codice di servizio.

**In coda Round 12**:
- 🔜 **Multiselect/multidrag** — desiderata forte (memoria
  `feedback_multiselect_multidrag.md`)
- 🔜 Test Mac+Chrome del branch `experiment/timeline-audit` (performance)
  → se OK merge in main come α.34

**v3.5.0-alpha.32** — 6 maggio 2026 — Cross-department: warning + badge persistente

Fix di un bug latente da α.23 (24 aprile): il warning cross-department
era silenziato da un TDZ JavaScript dentro un `try/catch(_) {}`. Aggiunto
in più il badge persistente ⚠ sull'item con bordo amber, così il mismatch
risorsa/task è visibile anche post-drop e tra sessioni.

**Chiuso α.32:**
- ✅ Backend `_booking_task_department_id(b)` + `_dept_mismatch_payload(...)`
  helpers in `app/routers/planning.py`
- ✅ Serializer `list_bookings` espone `cross_department: bool` per ogni
  assignment (calcolato server-side dal join cost_line.price_item.dept_id)
- ✅ Endpoint `PUT /api/booking-assignments/{id}` include
  `cross_department: {task/resource dept id+name}` nel response (informativo)
- ✅ Frontend fix bug TDZ in `onMove`: `orig`/`origBooking`/`assignmentId`
  spostati prima del check, `try/catch(_) {}` swallowing rimosso
- ✅ `tlBookingToItem()` aggiunge classe `tl-cross-dept` se mismatch +
  tooltip `⚠ Reparto risorsa (X) ≠ reparto task (Y)`
- ✅ `onMoving()` applica classe live durante drag preview (cleanup ad ogni
  frame per evitare stale state)
- ✅ CSS `.vis-item.tl-cross-dept`: bordo amber inset 4px + glow + ⚠ in
  alto a destra. Combinabile con tl-conflict / tl-tentative / tl-exec-*

**Architettura cross-department** (decisione 6/5/2026):
- A1 derivato (no schema change): `task_dept = cost_line.price_item.department_id`
- B2 + B3: confirm al gesto + badge persistente (visione d'insieme)
- C1 singolo dept per Resource (no multi-dept; rivalutare se emergono
  persone tuttofare nel team — Matteo confermato "no")

**Verifica live richiesta a Matteo:**
- Spostare un booking di Sara Conti (DI) su Davide Moretti (Audio):
  durante il drag dovrebbe apparire bordo amber + ⚠ live
- Al drop: confirm "Risorsa di reparto diverso dal task. Task → DI ·
  Risorsa target → Audio. Procedere comunque?"
- Al rifiuto: torna alla posizione originale
- All'accettazione: il booking si sposta e MANTIENE il badge ⚠ persistente.
  Refresh pagina → badge sempre lì
- Hover sul booking: tooltip include riga `⚠ Reparto risorsa ≠ reparto task`

**Niente migrate**: il dato `department_id` esisteva già su PriceItem e
Resource; il flag è derivato server-side al GET.

**Note operative**:
- α.31 saltata: branch isolato (`experiment/timeline-audit`) non mergato
  in main. Teniamo separato per il test performance Mac+Chrome
- Il branch audit ha fix performance (onMoving index, .tl-dragging CSS)
  NON ancora in main: se test Mac va bene, merge come α.33

**In coda Round 12** (priorità):
- 🔜 **Multiselect/multidrag** — desiderata forte di Matteo (vedi memoria
  `feedback_multiselect_multidrag.md`). Da affrontare strutturalmente
- 🔜 Capability copilot "crea risorsa"

Cache-buster `v=3.5.0-alpha.30` invariato (modifiche solo a planning.html
template + planning.py router; niente static asset toccato).

**v3.5.0-alpha.29** — 6 maggio 2026 — Round 11 (4/6): suoni soft

Suoni discreti via WebAudio (sintetizzati, zero file MP3). Toggle in
`/settings` → Aspetto. Default: notifiche ON, AI OFF (meno invasivo).

**Chiuso α.29 (4/6):**
- ✅ `playSound(name)` in global.js con WebAudio: `notify` due note sine
  880→1320Hz (stile macOS Tink, ~200ms), `ai_done` bell 660Hz + 3a armonica
  (~600ms)
- ✅ Throttle 800ms anti-spam, AudioContext lazy + auto-resume
- ✅ `toast()` invoca notify per type ≠ 'info'
- ✅ Copilot drawer invoca ai_done a risposta completa
- ✅ Card "🔔 Suoni" in `/settings` Aspetto con toggle + bottoni test
- ✅ Smoke test boot OK

**In coda Round 11 (2/6):**
- 🔜 α.30 — Migrazione completa icone Lucide
- 🔜 branch `experiment/timeline-audit`

Cache-buster `v=3.5.0-alpha.29` (global.js + copilot.js).

**v3.5.0-alpha.28** — 6 maggio 2026 — Round 11 (3/6): filmografia dedicata + campi estesi

La filmografia esce dalla scheda cliente. Pagina dedicata
`/clients/{id}/works` con vista a griglia di card e modal edit a 6
sezioni. `ClientWork` esteso con 6 nuovi campi.

**Chiuso α.28 (3/6):**
- ✅ Modello `ClientWork` esteso: synopsis, release_date, funding_public,
  cast_crew, external_links, awards (auto-migrate)
- ✅ Backend `_work_dict()` + PUT endpoint estesi con i nuovi campi (con
  sentinel di clearing)
- ✅ Nuovo route HTML `GET /clients/{client_id}/works`
- ✅ Nuovo template `client_works.html` con grid responsive di card +
  modal edit a sezioni + filtri live (testo/tipo/anno)
- ✅ Modal cliente pulito: tab Filmografia rimossa, ~268 righe di JS
  legacy cancellate, bottone "🎬 Filmografia" in footer linka alla pagina
- ✅ Smoke test boot: tutte e 6 le colonne presenti, app starts correctly

**Limiti noti α.28:**
- L'AI search ancora restituisce solo i campi base (title/year/kind/role/
  director/country). I 6 campi nuovi vanno compilati a mano post-import,
  oppure tramite un'estensione futura del prompt AI. Decisione: lasciare
  fuori dal cantiere α.28 per non gonfiarlo, valutare con Matteo se
  serve.

**Verifica live richiesta a Matteo:**
- Aprire una scheda cliente, cliccare "🎬 Filmografia" → si apre la
  nuova pagina con eventuali opere già presenti
- Aggiungere/modificare un'opera con i campi estesi (sinossi, cast & crew,
  finanziamenti, link, premi)
- Filtri (testo/tipo/anno) sulla griglia
- Verificare che la scheda cliente non abbia più la tab Filmografia

**In coda Round 11 (3/6):**
- 🔜 α.29 — Suoni soft notifiche + AI
- 🔜 α.30 — Migrazione completa icone Lucide
- 🔜 branch `experiment/timeline-audit`

Cache-buster `v=3.5.0-alpha.28`. Auto-migrate: 6 nuove colonne in
`client_works`.

**v3.5.0-alpha.27** — 6 maggio 2026 — Round 11 (2/6): optional + sezioni quote

Voci "opzionali" + etichette di sezione intra-categoria su `QuoteLine`.
Risolve due scenari del feedback Matteo: voci proposte ma non incluse nel
totale, e raggruppamento di deliverable per portale (SKY/NBCU/Beta Film…)
dentro la stessa categoria.

**Chiuso α.27 (2/6):**
- ✅ Modello `QuoteLine.is_optional` + `QuoteLine.section_label` con
  auto-migrate
- ✅ Backend `_recalc_quote()` esclude opzionali da subtotali; POST/PUT
  endpoint accettano i nuovi campi; GET espone `subtotal_optional`
- ✅ UI: badge "Opzionale" + bottoni `🏷` (sezione) e `○` (toggle opt)
  inline su ogni riga; section header + subtotale di sezione quando
  `section_label` cambia; blocco "Optional aggiuntivi" in fondo ai totali
- ✅ PDF: tabella principale solo billabili; tabella separata "OPTIONAL
  AGGIUNTIVI — non inclusi nel totale" amber-styled
- ✅ Bug-fix laterale: `_auto_migrate_columns()` print con `→` Unicode
  crashava su Windows charmap codec → sostituito `->` ASCII (latente da
  v3.4.27.1)
- ✅ Smoke test boot: lifespan + migrate OK, ambo le colonne presenti

**Verifica live richiesta a Matteo:**
- Aprire una quote esistente, marcare 1-2 righe come opzionali col bottone
  `○`, vedere il blocco "Optional aggiuntivi" sotto i totali
- Su righe della stessa categoria, settare `section_label` (es. "SKY",
  "NBCU") tramite bottone `🏷` → vedere mini-header + subtotale di sezione
- Esportare PDF → verificare tabella optional separata in fondo

**In coda Round 11 (4/6):**
- 🔜 α.28 — Pagina filmografia dedicata + campi estesi
- 🔜 α.29 — Suoni soft notifiche + AI
- 🔜 α.30 — Migrazione completa icone Lucide
- 🔜 branch `experiment/timeline-audit`

Cache-buster `v=3.5.0-alpha.27`. Auto-migrate: 2 nuove colonne in `quote_lines`.

**v3.5.0-alpha.26** — 6 maggio 2026 — Round 11 (1/6): rimozione matrice + kanban

Apertura Round 11 sui feedback Matteo del 6 maggio. 6 voci totali divise
per scope. Prima voce chiusa: l'area `/assignments` (matrice + kanban)
sparisce. Le assegnazioni si gestiscono solo da scheda progetto + timeline
planning. La matrice non convinceva e duplicava la gestione.

**Chiuso α.26 (1/6):**
- ✅ Cancellato `app/routers/assignments.py` + template + nav-item sidebar
- ✅ Modello `JobResourceAssignment` preservato (usato in scheda progetto)
- ✅ RBAC middleware aggiornato (`/assignments` rimosso da blocked prefixes)
- ✅ Smoke test import: `from app import main` OK con v3.5.0-alpha.26

**In coda Round 11 (5/6):**
- 🔜 α.27 — `is_optional` + `section_label` su QuoteLine (raggruppamento
  per deliverable: SKY/NBCU/Beta Film + voci opzionali fuori totale)
- 🔜 α.28 — Pagina filmografia dedicata `/clients/{id}/works` con campi
  estesi (funding pubblico, cast/crew, link esterni, sinossi, premi).
  Tab filmografia rimossa dalla scheda cliente.
- 🔜 α.29 — Suoni soft notifiche + AI risposta (royalty-free Pixabay,
  toggle in `/settings`)
- 🔜 α.30 — Migrazione completa icone Lucide (sostituzione emoji →
  SVG inline via macro Jinja, stroke 1.5px, currentColor)
- 🔜 branch `experiment/timeline-audit` — profiling vis-timeline + nostro
  codice. Sintomo Matteo: "lento già con pochi booking su 2 risorse".
  Probabile bottleneck nel custom JS (heatmap re-render, listener accumulo,
  force-redraw eccessivo). Se confermato → ottimizziamo gratis. Altrimenti
  porting su DHTMLX Scheduler GPL (free per uso interno) o Bryntum Scheduler
  Pro ($900) come ultima istanza.

Cache-buster `v=3.5.0-alpha.26`. Niente migrazione DB.

**v3.5.0-alpha.25** — 5 maggio 2026 notte tardi — Round 10 chiuso (7/7)

Chiuso anche il 7° punto: scheda cliente con filmografia AI, fonti pubbliche
italiane + IMDB/MyMovies, workflow propone+conferma, idempotente.

**Cantiere completato:**
- ✅ Modello `ClientWork` (tabella `client_works`, auto-create al boot)
- ✅ Service `app/services/filmography.py` con Tavily `include_domains` ristretto
- ✅ 5 endpoint CRUD + AI search (no scrittura DB nell'AI search, propone solo)
- ✅ Tab Filmografia nella scheda cliente con AI search + lista cards
- ✅ Modal candidati AI con checkbox, fonti cliccabili, badge confidence
- ✅ Modal edit opera con form completo + delete
- ✅ Idempotency su (title, year) — re-import safe

**Smoke test live:** ricerca su "RAI Documentari" → 14 fonti consultate, 6
opere proposte con confidence/source URLs valide.

Cache-buster `v=3.5.0-alpha.25`. Tabella `client_works` auto-creata.

**v3.5.0-alpha.24** — 5 maggio 2026 notte tardi — Round 10: planning UX refinement (6/7)

Terza tornata feedback Matteo post-test alpha.23. Chiusi 6 punti su 7. Il
7° (scheda cliente con filmografia AI) è in attesa di conferma piano:
proposta = `ClientWork` model + tab "🎬 Filmografia" + endpoint AI con
tool-use puntato a filmitalia.org / cinema.cultura.gov.it / IMDB / MyMovies.

**Chiusi:**
- ✅ Risorse duplicate sui booking: dedupe per `(booking_id, resource_id)`,
  badge "+N segmenti" nelle card, riga aggregata nel detail modal.
- ✅ Ferie/malattia/festività look uniforme (alpha 0.12, palette indigo
  MediaFlow).
- ✅ Hover ferie/malattia/festività: tooltip arricchito con periodo, durata
  giorni, risorsa, motivo, status.
- ✅ Hover job: aggiunti orari inizio/fine + icona semaforo priorità.
- ✅ Semaforo priorità più grande/distanziato in "Le mie" e "Per progetto".
- ✅ Pannello selezione "stile filtri" con 4 dropdown + glow animato sui
  selezionati (`tl-pulse-glow` ease-in-out infinite).

**In attesa conferma Matteo:**
- 🔜 Scheda cliente AI con filmografia (cantiere grosso). Proposta:
  - Modello `ClientWork(client_id, title, year, kind, our_role, director, sources_json)` — o JSON `clients.filmography`
  - Tab "🎬 Filmografia" in scheda cliente con bottone "🔍 Cerca con AI"
  - Endpoint `POST /clients/api/{id}/search-filmography` con AI tool-use
    + `web_search` (Tavily) puntato a filmitalia.org, cinema.cultura.gov.it,
    IMDB, MyMovies
  - Workflow "AI propone, utente conferma" — match candidati in cards di
    anteprima, utente seleziona quali importare
  - Import idempotente su (title, year)

Cache-buster `v=3.5.0-alpha.24`. Niente migrazione DB.

**v3.5.0-alpha.23** — 5 maggio 2026 notte — Round 9 chiuso (17/17 punti)

Round 9 sulla seconda lista feedback Matteo del 5 maggio chiuso interamente.
Push include `db_snapshots/snapshot-3.5.0-alpha.23.db` per porting test.

**Drag & drop timeline (5):**
- ✅ Cross-resource drag aggiorna cache locale + force re-render server-of-truth
- ✅ Multi-select drag — applica shift a tutti i selezionati con conferma
- ✅ Block drop su risorsa di reparto incompatibile (prompt conferma esplicita)
- ✅ Split-pause unit drag — sibling assignments shiftati insieme
- ✅ Shift+drag area vuota → modal nuovo booking pre-compilato (overlay verde con durata live)

**Settings (1):**
- ✅ Toggle "Mostra timbrature (ombra leggera)" in popover ⚙ Look timeline. Stile più sottile (10%/20% alpha).

**DB (1):**
- ✅ Snapshot DB committato in `db_snapshots/snapshot-3.5.0-alpha.23.db` per porting test su altra macchina. README istruzioni restore.

**In coda dopo test Matteo:**
- Test E2E della pausa pranzo + split overtime su edge cases
- Test del semaforo priorità in tutte le viste
- Verifica DB snapshot su Mac (porting effettivo)

Cache-buster `v=3.5.0-alpha.23`. Niente migrazione nuova.

**v3.5.0-alpha.22** — 5 maggio 2026 sera — Round 9 (parte 1/3)

Round 9 aperto sulla seconda lista feedback Matteo (5 maggio sera, 17 punti
totali). Diviso in 3 sotto-round per scope-bound. Questo bump chiude 9 punti.

**HR (3):**
- ✅ Ferie/malattia ora visibili in lista timbrature (default range = mese
  corrente sul page load `/hr` per popolare l'endpoint timeline)
- ✅ Block timbratura su giorno con ferie/malattia approvata + viceversa (409)
- ✅ Pausa pranzo opzionale in timbratura (default 60 min, opzioni 0..240 step
  15). Nuova colonna `time_punches.break_minutes` auto-migrate. Sottratta
  dalla durata e dall'engine `compute_overtime`/`compute_punch_breakdown`.

**Timeline UX (5):**
- ✅ Doppio click su item → apre modal edit booking
- ✅ Tooltip hover esteso con durata booking + ore lavorazione (totali/done)
- ✅ Priorità "semaforo" 3-dot in card "Le mie" / Per progetto + nel modal
  create/edit booking
- ✅ Booking detail arricchito (cliente, dipartimento per risorsa, ore done
  cumulato, audit count, last-edit)
- ✅ Sort priorità desc + data asc in "Le mie" e "Per progetto"

**Selezione & UX (1):**
- ✅ ROI Alt/Shift+drag disabilitato (UX confusa). Solo dropdown
  `☑ Seleziona ▾` resta attivo.

**Storyboard (1):**
- ✅ Opzione densità storyboard spostata dalla popover globale al toolbar
  della vista Storyboard.

**In coda (Round 9 part 2/3):**
- 🔜 Click+drag area vuota → modal nuovo booking pre-compilato con durata
- 🔜 Drag&move conflitti backend (cross-resource non riflesso al refresh)
- 🔜 Multi-select drag su altra risorsa
- 🔜 Block drop su risorsa di reparto incompatibile
- 🔜 Split-pause unit drag (entrambi i segmenti)
- 🔜 Settings toggle visualizzazione timbrature come ombra leggera in timeline
- 🔜 Push DB nel bundle

Cache-buster `v=3.5.0-alpha.22`. Migrazione DB auto: aggiunge colonna
`time_punches.break_minutes` al boot.

**v3.5.0-alpha.21** — 5 maggio 2026 — Round 8 (parziale)

Round 8 aperto su feedback Matteo dal test su altra macchina. 8/9 punti chiusi.

**Bug critici (8A):**
- ✅ Salvataggio Orari lavorativi: auto-create policy default al primo GET (`_ensure_default_policy`)
- ✅ Bulk modify lookup booking_id (campo a top-level non in extendedProps)
- ✅ ROI selezione area: aggiunto menu dropdown affidabile alternativo
  (Tutti visibili / Per Job / Per Risorsa / Per Date / Deseleziona)
- ✅ Permesso deprecato `edit_cost_actuals` rimosso
- ✅ RBAC orari: split `view_settings_global` (tutti) vs `manage_settings_global`
  (admin/manager). User vede ma non modifica.
- ✅ Matrice assegnazioni: banner istruzioni inline + legenda colori

**Feature (8B):**
- ✅ ProjectMilestone modello + CRUD + UI tab in /projects/{id}
- ✅ Timeline planning vista "Per progetto" (toggle in toolbar)
- 🔜 Form KDM in DAM (rinviato, cantiere medio)

**Tecnici:**
- `create_tables()` ora forza import app.models per registrare tutti i modelli
- Backend `/planning/api/bookings` espone `project_id/project_title/project_code/job_code/job_title`

Cache-buster `v=3.5.0-alpha.21`. Tabella `project_milestones` creata auto al boot.

**v3.5.0-alpha.20** — 5 maggio 2026 — Round 7D.2 + 7D.3: matrice assegnazioni + pagina Team

**Round 7 chiuso completamente** (12 punti su 12 del feedback Matteo del 5 maggio).
Sequenza alpha.16 → alpha.20 (5 versioni):
- alpha.16 → 7A (HR breakdown per-punch + ROI)
- alpha.17 → 7B (cost report lista + quote ricerca + export rendiconto/CSV/XLSX)
- alpha.18 → 7C (undo/redo planning + bulk-edit booking)
- alpha.19 → 7D.1 (AI settings registry + 3 tool generici)
- alpha.20 → 7D.2 (matrice assegnazioni scalabile) + 7D.3 (pagina /team unificata)

Sotto-round 7D.2 chiuso:
- `GET /assignments/api/matrix` server-filtered + client-filtered (ricerca live).
- Tabella matrice Risorsa × Job sticky-header + sticky-first-column.
- Cella verde = assegnata, arancione = ore booking ma no assignment (drift).
- Modal upsert con planned days/hours + role + tariffe.
- Toggle topbar Matrice/Kanban (kanban legacy preservata).

Sotto-round 7D.3 chiuso:
- Pagina `/team` con sidebar reparti drill-down (count + Senza reparto + Tutte).
- Main pane: griglia card auto-fill, ricerca live + filtri tipo/stato.
- Voce sidebar `/resources` → `/team`. Pagine `/resources` e `/departments`
  restano accessibili (link in topbar di /team).

Cache-buster `v=3.5.0-alpha.20`. Niente migrazione DB.

**v3.5.0-alpha.19** — 5 maggio 2026 — Round 7D.1: AI settings registry + tool generico

Sotto-round 7D.1 chiuso (cantiere architetturale "AI integrazione GUI/settings"
proposta A2). Discovery dinamica + patch generica → estendibile a tutto il
software senza nuove capability AI.

- `app/services/settings_registry.py`: `SettingsSchema` con read/write handlers,
  validation/coercion, RBAC. 2 schemi iniziali (`working_hours`, `tenant_settings`).
- 3 tool AI: `list_settings_schemas` + `read_setting` + `update_setting`.
- `apply_action` + `_exec_readonly` con iniezione opzionale di `user` via
  inspect.signature → handler che lo richiedono lo ricevono.
- Card mutation `update_setting` nel copilot con summary leggibile (area + diff).
- System prompt aggiornato con sezione "Settings".

Cache-buster `v=3.5.0-alpha.19`. Niente migrazione DB.

**v3.5.0-alpha.18** — 5 maggio 2026 — Round 7C: undo/redo planning + bulk-edit booking

Sotto-round 7C chiuso (2 punti):
1. **Undo/redo planning timeline**: stack max 50 + Ctrl+Y/Ctrl+Shift+Z per redo,
   2 bottoni toolbar persistenti `↶ Undo` / `↷ Redo`, undo per `remove_assignment`
   ora funziona via nuovo endpoint `POST /planning/api/bookings/{id}/assignments`.
2. **Bulk-edit booking**: bottone `✏ Bulk` toolbar (visibile su selezione ≥1),
   modal con shift orario (minuti) + cambio stato esecuzione, endpoint
   `PUT /planning/api/bookings/{id}/bulk-edit`. Snapshot pre-modifica per undo.

Cache-buster `v=3.5.0-alpha.18`. Niente migrazione DB.

**v3.5.0-alpha.17** — 5 maggio 2026 — Round 7B: cost report lista + ricerca + export

Sotto-round 7B chiuso (3 punti):
1. **Cost report da dropdown a lista filtrabile** (pattern come `/quotes`):
   nuovo `GET /cost-report/api/list` + ricerca live + 3 filtri (cliente, stato,
   margine over/under). Click riga apre dettaglio in toolbar; bottone "← Lista".
2. **Quote ricerca + filtri**: refactor `loadQuotes` in fetch+render filtrato,
   ricerca live + 3 filtri (cliente, stato, con/senza job) + counter.
3. **Export cost report cliente esteso**:
   - PDF con `?rendiconto=1` mostra Quotato/Maturato/Stimato + Over/Under per
     riga + totale finale (verde/rosso). Modalità stato storica resta default.
   - 2 endpoint nuovi: `client-csv` (UTF-8 BOM, `;` separatore) e `client-xlsx`
     (openpyxl, header indaco). Helper `_client_export_rows` condiviso.
   - Toggle "Modalità rendiconto" nella toolbar dettaglio cost report.

Cache-buster `v=3.5.0-alpha.17`. Niente migrazione DB.

**v3.5.0-alpha.16** — 5 maggio 2026 — Round 7A: HR breakdown per-punch + ROI riscritto

Aperto Round 7 su lista feedback Matteo del 5 maggio (12 punti, suddivisi in
sotto-round 7A bug puri / 7B-C feature medie / 7D cantieri di design).

Sotto-round 7A chiuso (4 punti):

1. **Straordinari per singola timbratura + nei totali** — nuovo servizio
   `compute_punch_breakdown` che distribuisce l'overtime giornaliero sui punch
   del giorno (last-in-first-out: le ore "in coda" diventano straordinario).
   Tabella `/hr` mostra colonna "Breakdown" con badge inline. Totali header
   ricalcolati sulle 9 categorie del rendiconto.
2. **Filtro Tipo in Le mie ore funzionante** — dropdown ora propone le 9
   categorie del breakdown (Regolari/Straordinari/Notturne/Festivo/Domenicali/
   Pausa/Ferie/Malattia/Permesso) invece dei raw `PunchKind` (che erano solo 6
   e non riflettevano il breakdown overtime). Filtro applicato uniformemente a
   tabella + totali via parametro `category` su `/api/timeline`.
3. **Ferie/malattia in tabella timbrature** — nuovo endpoint unificato
   `/hr/api/timeline` che fonde TimePunch + ResourceUnavailability approvate.
   1 riga sintetica per giorno per ogni record di unavailability, con bg
   colorato e durata = `daily_hours_threshold` della policy.
4. **ROI multiselect riscritto** — diagnosi: Hammer.js (vis-timeline) bypassa
   `stopPropagation` su capture-phase. Fix: `setOptions({moveable:false, zoomable:false})`
   durante il drag, trigger keys allargati a **Alt+drag** (default) +
   **Shift+drag** + toggle toolbar **"📦 Selezione area"** persistente.
   Rilevazione gruppi via scansione `.vis-label` invece di `[data-group-id]`.

Cache-buster `v=3.5.0-alpha.16`. Niente migrazione DB.

**v3.5.0-alpha.15** — 5 maggio 2026 — Round 6: ore festivo + ROI multiselect timeline

Chiusura dei 3 punti rimasti dal Round 5:
1. **Ore festivo/domenicali nel riepilogo "Le mie ore"** — aggiunte card "Festivo" (rosso) e "Domenicali" (arancione) accanto a Regolari/Straordinari/Notturne. Engine calcolava già `holiday_hours` + `sunday_hours` con multiplier dedicati ma la UI non li mostrava → 1 maggio restava "non riportato".
2. **Shift+drag ROI multiselect timeline** — implementazione custom (vis-timeline non supporta rect selection nativa). Capture-phase mousedown+Shift su area vuota traccia overlay floating, mouseup calcola intersezione [time, group]×items, `setSelection(ids)`. Si combina col bulk-delete di alpha.14.
3. **Formato data dd/mm/yyyy** — verifica: già di default via `fmtDate('it-IT')`. UI selezione formato in `/settings` rinviata.

Tasks 19-30 chiusi. 7 commit alpha sopra origin/main (alpha.9 → alpha.15).

**v3.5.0-alpha.14** — 5 maggio 2026 — Round 5: timezone timbratura + revert click + bulk cascade + UX

9 fix:
1. Timbratura timezone (9:00 → 7:00): toISOString rimosso, send raw local datetime-local.
2. Timbratura overlap: 409 se sovrapposta.
3. Timbratura ordine: ASC (calendario).
4. REVERT auto-open detail su timeline select (era v3.5.0-alpha.13 ma confliggeva).
5. Bulk delete cascade su tutti assignments del booking.
6. Cleanup aggressivo timeline pre-render (timeline duplicata post bulk delete).
7. CSS Stesso orario non copre risorsa #1.
8. Lista quote larghezza colonne min.
9. AI capability `update_quote` (modifica metadata quote esistente).

**Restano in coda (Round 6 prossimo)**:
- Shift+drag ROI multiselect timeline (custom rectangle selection — vis-timeline non supporta nativo)
- Ore straordinario 1° maggio non riportate (verifica holiday detection)
- Formato data globale dd/mm/yyyy + setting

**v3.5.0-alpha.13** — 4 maggio 2026 — Round 4: 3 bug critici + UX planning realtime + multiselect timeline

3 bug critici risolti:
1. Maturato fantasma su unità non-time (pc/lump/fix/lot/...): recompute_cost_line_actual ora setta `quantity_actual = len(bookings_done)`. + auto-reconcile silenzioso al load di /cost-report (fix retroattivo drift storici).
2. Timbratura: input fine turno non più cancellato durante digitazione (parseValue mfWrapDateTimeLocal non sovrascrive subs se hidden empty).
3. Filtro pianificazione "Per progetto" ora rispetta f-resource (project_bookings endpoint accetta resource_id csv).

5 feature UX:
- todoSetExec/Extend/Priority refresh la view attiva (refreshActiveView helper) — Fatto/Iniziato/etc. immediato qualunque sia la tab.
- Topbar planning: bottone "+ Booking" globale (visibile da tutte le viste).
- Click su booking apre il modal dettaglio in agenda + calendar + timeline (1 item) — uniforme con todo/project/storyboard.
- Timeline multiselect (Ctrl/Shift+click) + Delete/Backspace key per bulk-delete con conferma.
- Lista /quotes e cost report job-select mostrano titolo quote + titolo progetto.

1 quick win realtime:
- copilotApply dispatcha `mf:ai-action-applied` event → quotes.html ricarica la lista o l'editor automaticamente quando il copilot crea una quote.

**Lasciato fuori scope (chiarimento)**:
- "Suddivisione risorse per reparto" in pianificazione: la timeline già raggruppa per reparto via DEPARTMENTS_SEED. Servirebbe vista alternativa? Decidi cosa.
- "Caricamento documenti al copilot": cantiere grande (file picker + upload + parser AI per capitolato/post-prod schedule). Rimandato a session futura.

**v3.5.0-alpha.12** — 4 maggio 2026 — Round 3 chiuso: cost report popup booking + hardcost

Ultimi 2 issue di Round 3 chiusi.

1. Cost report: popup booking-detail su click riga (porting di `openLineDetail` da `job_detail.html`). Endpoint riusato `/jobs/api/{job_id}/cost-lines/{line_id}/detail`.
2. Hardcost dettagliato: `QuoteLine.hardcosts` esposto via detail endpoint (`hardcosts_unit`, `hardcosts_total`); blocco viola "Hardcost (materiali / spese vive)" nel popup, visibile solo se >0 e gated dietro `CAN_VIEW_FINANCE` in `job_detail.html`.

Round 1+2+3 chiusi (alpha.9 → alpha.12). 4 commit pronti dopo l'ultimo push: `2728c01` alpha.9, `eeb8189` alpha.10, `7e855ce` alpha.11, alpha.12 (in arrivo).

**v3.5.0-alpha.11** — 4 maggio 2026 — Round 3 (parziale): quote subtotali live + booking timeline UX

Sei fix raggruppati:
1. Quote `/quotes` editor: subtotale/sconto/netto per categoria live al save (prima freezing); nuova riga "Totale categoria al netto" verde se sconto > 0.
2. Resource→Project sync: hook `ensure_resources_assigned_to_job` aggiunto su `PUT /api/bookings/{id}` (replace-all assignments) e `PUT /api/booking-assignments/{id}` (reassign). Prima copriva solo il CREATE.
3. Booking done propagation: `todoSetExec` ora richiama `renderTimeline(true)` se la timeline è la view attiva. Toast: "completato (tutte le risorse del booking)".
4. Timeline highlight cross-resource: select su un item multi-risorsa applica `tl-link-highlight` (outline indaco) a tutti gli items con stesso `booking_id`.
5. Timeline copia multi-risorsa: `_tlDoDuplicate` riscritto — clona TUTTI gli assignments della sorgente (era 1 sola). Calcola offset temporale dal click point e shifta tutti.
6. Timeline drag overlay: floating box segue il cursore con start→end, durata, warning ferie/festivo. Si nasconde su drop / mouseup / Escape.

Cache-buster `base.html` → `global.js?v=3.5.0-alpha.11`. Niente migrazione DB.

**Restano in Round 3 (in coda)**:
- Cost report row → popup booking-detail (porting di `openLineDetail` da `job_detail.html` a `cost_report.html`)
- Cost report: hardcost dettagliati nel breakdown

**v3.5.0-alpha.10** — 4 maggio 2026 — Round 2: RBAC editor + ore lavorate sempre da booking

Decisione architetturale (Matteo, 4 maggio): le ore lavorate (`JobCostLine.quantity_actual`) corrispondono SEMPRE alle ore dei booking marcati `done`. Niente più override manuale dal cost line edit. La fatturazione di extra/scontistica/banca-ore forfait passerà dal flusso fatturazione dedicato (in roadmap), non da qui.

Backend rifiuta `quantity_actual` con 422 in `PUT /jobs/api/{id}/cost-lines/{lid}` e `PUT /cost-report/api/job/{id}/cost-lines/{lid}`. Permesso `edit_cost_actuals` marcato deprecato + rimosso da preset manager/accounting.

UI: campo `quantity_actual` editor sostituito da display read-only ("🔒 Derivate da booking done").

**RBAC editor (Luca Bianchi / operator)**: nuovo helper `can_create_booking` (= `edit_planning_all` OR `assign_resources`). Editor → false. Gate su `POST /planning/api/bookings` (redirige tlbSubmit lato client a richiesta) + nuovo endpoint `POST /planning/api/booking-requests` (chiunque autenticato → notifica `booking_request` action_required a producer/manager via `notify_permission("assign_resources")`).

Gate frontend in `planning.html` + `job_detail.html`: budget/costi/margine/€unitario/tot.previsto nascosti a chi non ha `view_finance`. Modal create booking → titolo "📩 Richiedi booking" / submit "Invia richiesta" per editor.

Gate `POST /cost-report/api/job/{id}/assign-resource` (e DELETE) con `can_assign_resources`. Editor → 403.

NotificationKind nuovo: `booking_request`.

Niente migrazione DB.

**v3.5.0-alpha.9** — 4 maggio 2026 — Round 1 fix post-test estensivo Matteo

Sei fix raggruppati emersi dal test del 3 maggio:
1. Cost report — `recompute_for_booking` agganciato a `DELETE booking`, `DELETE assignment`, `PUT booking (replace assignments)`, `PUT assignment` (drag/resize). Risolve il maturato fantasma post-eliminazione.
2. HR `/api/overtime` — degradazione graceful con 200+warning quando manca `WorkingHoursPolicy` default (era 400 e rompeva `/hr/`, side-effect: blocco UI timbratura).
3. Timepicker quick options — da 8 a 27 orari (07→23 + 00:00, mezz'ora sui passaggi giornata).
4. `openModal()` helper — refresh `mfApplySearchable` + `mfApplyTimePickers` sui figli del modal (fix generico al sintomo "campo non si vede" dopo `select.value=`; risolve il reparto mancante nel modal risorsa).
5. Pagina 403 + scheda pubblica error — centratura corretta (body globale ha `display:flex` per sidebar, override con `display:block` + `width:100%`).
6. `propose_quote.lines` accetta `price_item_id` (eredità dal listino) — già in alpha.4, non tocco.

Cache-buster `base.html` → `global.js?v=3.5.0-alpha.9`.

**Versioni intermedie 3.5.0-alpha.x** (3-4 maggio 2026):
- alpha.1: AI tool-use nativo Anthropic — Slice 1 foundation
- alpha.2: hotfix persistenza storia conversazione
- alpha.3: hotfix errore Apply visibile + ordine azioni AI
- alpha.4: `propose_quote.lines` con price_item_id
- alpha.5: riordino sezioni sidebar (drag&drop ⠿ header)
- alpha.6: hotfix tool_use orfani + sanitizer difensivo
- alpha.7: cestino quote (Slice 1+2+3)
  - alpha.7.1-7.5: hotfix vari
- alpha.8: cestino Project + retention auto (Slice 4+5)
- **alpha.9: Round 1 fix post-test (questa versione)**

**v3.5.0-alpha.8** — 3 maggio 2026 — Cestino Project (Slice 4) + Retention auto (Slice 5)

Cantiere "cestino" chiuso completamente. Soft-delete framework esteso da Quote a Project con stesso pattern (`_SOFT_DELETE_MODELS` + filter automatico via SQLAlchemy event listener). Retention configurabile (`trash_retention_days`, default 30, env `TRASH_RETENTION_DAYS`); 0 = disabilitato. Bottone "⏱ Purga scaduti" in `/admin/cestino` (solo admin).

**Versioni intermedie 3.5.0-alpha.x** (tutte 3 maggio 2026):
- alpha.1: AI tool-use nativo Anthropic — Slice 1 foundation (loop tool_use, mutation gated da Apply, readonly inline)
- alpha.2: hotfix persistenza storia conversazione (tool_state non azzerato a ogni end_turn)
- alpha.3: hotfix errore Apply visibile (api() helper cerca `detail`) + ordine azioni AI
- alpha.4: `propose_quote.lines` accetta `price_item_id` (eredità da listino)
- alpha.5: riordino sezioni sidebar (drag&drop maniglia ⠿ sull'header)
- alpha.6: hotfix tool_use orfani + sanitizer difensivo (`_sanitize_messages`)
- alpha.7: cestino quote Slice 1+2+3 (soft-delete framework, UI quotes, admin trash)
  - alpha.7.1: hotfix SyntaxError JS in /quotes (no JSON.stringify in onclick)
  - alpha.7.2: hotfix escapeHtml not defined (script in `block scripts` non `block content`)
  - alpha.7.3: hotfix collisione numero quote dopo soft-delete (bypass UNIQUE)
  - alpha.7.4: tool result più espliciti (created/message) per evitare allucinazioni AI
  - alpha.7.5: rinomina inline di title e number quote nell'editor
- alpha.8: cestino Project + retention auto (Slice 4+5)

Da testare sul Mac: copilot end-to-end con Sonnet (Cattleya/Gomorra/ISIDE flow); cestino quote con HARD-BLOCK booking; cestino progetto con HARD-BLOCK quote attive; pulizia totale admin per quote e progetti; retention banner in /admin/cestino.

Avviato il refactor del copilot da blocchi markdown ```action``` a **tool-use nativo** dei provider AI. Cantiere "feedback non torna al modello": Tavily girava ma i risultati restavano in UI senza rientrare nel modello → l'AI non poteva proseguire dopo le azioni applicate.

**Decisione architetturale (Matteo)**: Anthropic + OpenAI + Gemini con tool-use nativo (Slice 1+4); Ollama + Perplexity restano sul path legacy markdown. Tool readonly per DB lookup in Slice 5. Streaming in Slice 6.

**Slice 1 chiusa in questo bump** (solo Claude end-to-end):
- `app/services/ai_tools.py` nuovo — registry 9 capability con JSON Schema canonico + converter per i 3 formati provider
- `AIProvider.chat_with_tools()` astratto + implementato su `ClaudeProvider` (Messages API tool_use)
- `app/services/ai_loop.py` nuovo — `advance_loop()` (mutation gated da Apply, readonly eseguite inline) + `resume_after_action()` (riprende dopo Apply/Reject)
- `AIConversation.tool_state` + `AIAction.tool_use_id` (auto-migrate)
- Router `/api/chat`, `/apply`, `/reject` cabolati al nuovo loop con fallback legacy
- Frontend: `copilotApply` mostra la `continuation` come nuova bubble assistant

**Slice rimanenti**: 2 (test E2E), 3 (rifinitura UI), 4 (OpenAI + Gemini), 5 (readonly DB tools), 6 (streaming), 7 (cleanup legacy).

**v3.4.56** — 3 maggio 2026 — Conferma assegnazione risorse + warning quote approved senza risorse + workflow docs

Completati i 2 TODO della v3.4.55:
1. **Pre-save confirm** in modal booking: prima del save, GET `/planning/api/jobs/{id}/resource-coverage` → se ci sono risorse non ancora in `JobResourceAssignment`, dialog di conferma. Cancel = abort.
2. **Notify `quote_approved_no_resources`** (non bloccante): hook in PUT status → approved, se job ha 0 assignment notify a `assign_resources` (admin/manager/producer).

Aggiunti **3 documenti workflow** in `docs/`:
- `workflow.md` — 5 diagrammi Mermaid (state Quote, state Booking, flow forward/reverse/phantom, fonti Maturato, vincoli HARD-BLOCK)
- `data-model.md` — erDiagram entità + classDiagram con flag/stati + tabella decisioni
- `permissions-matrix.md` — matrice permesso × ruolo + permessi gate-keeper

Niente migrazione DB.

**v3.4.55** — 3 maggio 2026 — Fix sistemico: integrità Quote↔JobCostLine↔Booking, vista lavorazione read-only, auto-assignment risorse, allineamento man-hours

Cambio strutturale dopo 5 paradossi segnalati da Matteo. Sintesi:
1. **HARD-BLOCK** sulla delete di QuoteLine/JobCostLine se booking attivi (no più soft-detach silenzioso che produceva booking orfani senza lavorazione)
2. **Vista lavorazione read-only** (`modal-line-detail` + `GET .../detail`): KPI Quotato/Maturato + Origine quote + Risorse + Booking. Bottone "Modifica" solo per `view_finance`.
3. **Auto-assignment Resource → Job** via hook in POST booking (`app/services/resource_assignment_sync.py`, idempotente)
4. **Man-hours canonico**: `cost_line_sync._booking_hours` ora somma durate assignments (era shell-duration), allineato con `reverse_quote`. Fix maturato sottostimato per booking multi-risorsa.
5. Mantenuto lock `quantity_actual` per non `edit_cost_actuals` (v3.4.54).

Niente migrazione DB.

**v3.4.54** — 3 maggio 2026 — Project filter nel booking + cost-line RBAC (no override maturato per editor)

Due fix critici post-test v3.4.53:
1. **Project filter prima della Quote** nel modal booking (restringe ambito, evita ambiguità nomi). Picker progetto sopra il picker quote, filtro automatico QUOTES_SEED.
2. **Cost-line RBAC + lock del maturato**: editor non può più modificare `quantity_actual` (sballava cost report). Permesso nuovo `edit_cost_actuals` (admin/manager/accounting; producer/operator NO). Backend gate POST/PUT/DELETE cost-lines su `view_finance`; PUT extra-gate su `edit_cost_actuals` per `quantity_actual`. Frontend job_detail.html: input read-only + badge se non autorizzato; bottone "Aggiungi extra" nascosto a non-finance.

Maturato canonico = sync dai booking `done` (cost_line_sync v3.4.41). Override manuale è eccezione gestita da finance, non default.

**v3.4.53** — 3 maggio 2026 — Booking parla quote+lavorazione (Job nascosto), filtro reparto risorse

Modal booking riscritto: il campo "Job" diventa "Quotazione" (autocomplete `QUOTES_SEED` con stati draft|sent|approved). La lavorazione è obbligatoria e filtrata per dipartimento delle risorse selezionate (ricarico automatico al cambio risorse). Job resta nel DB ma invisibile.

Backend: `GET /quotes/api/{id}/booking-lines?dept_ids=...` (cost_line per approved, quote_line per pending) + `POST /quotes/api/{id}/promote-line-to-cost-line` (approva implicit + ensure Job + crea JobCostLine, idempotente, notifica AM). `tlbSubmit` lato client: se kind=quote_line, promuove prima del save booking.

Caso d'uso target: emergenza cliente con quote in trattativa → bookings attaccano lavorazioni alla quote draft/sent con approvazione implicita.

**v3.4.52** — 3 maggio 2026 — Reverse-flow v2: booking → QuoteLine + approvazione implicita / phantom quote

Riformulazione architetturale dopo discussione con Matteo. Il driver canonico è la **Quote**, non il Job. Reverse: booking su progetto senza quote attiva → 2 modalità: (1) **attach_existing** alla quote draft/sent con approvazione implicita + notifica account managers (`edit_quotes`); (2) **create_phantom** = nuova `Quote(is_phantom=True, status=approved)`. In entrambi i casi il forward-flow standard `_create_job_from_quote` crea il Job. Niente più qty/prezzo manuali: tutto da `booking_hours` + voce listino.

Aggiunto `Quote.is_phantom` (auto-migrate). Nuovo `NotificationKind.quote_reverse_approval`. Service `app/services/reverse_quote.py`. Endpoint `POST /quotes/api/reverse-attach`. `GET /projects/api/{id}/job-context` esteso (approved/pending/phantom quotes + suggested_flow). Sub-modal `modal-tlb-reverse-quote` con anteprima riga calcolata. Eliminati: `app/services/job_extras.py` + `POST /jobs/api/reverse-extra` (defunti dalla v3.4.51).

**v3.4.51** — 3 maggio 2026 — Reverse-flow: job extra da booking su progetto senza quote

Cambio architetturale: un Job non nasce mai dal nulla con valore commerciale arbitrario. Forward (Quote.approved → Job) o Reverse (Booking su progetto senza quote → modal blocking → Job extra creato/riusato + JobCostLine extra + price_item). Service `app/services/job_extras.py`. Endpoint `GET /projects/api/{id}/job-context` + `POST /jobs/api/reverse-extra`. Sub-modal `modal-tlb-extra-job` in /planning con CTA in fondo al job-search. ProjectType `internal` come label. Bonifica seed: rimosso Job Sky orfano con budget arbitrario. Niente migrazione DB.

**v3.4.50.3** — 2 maggio 2026 — Elimina progetto (solo se senza quotazioni)

Tasto 🗑 in colonna azioni `/projects` accanto a "Apri →". Visibile a `can_view_finance`. Disabilitato + tooltip se `quotes_count > 0`. Backend `DELETE /projects/api/{id}` ora richiede permesso e blocca se `p.quotes` (oltre al pre-esistente check su `p.jobs`).

**v3.4.50.2** — 2 maggio 2026 — Modal scrollabile con header/footer fissi

Fix UX globale: i `.modal` ora si capano all'altezza viewport (`max-height: calc(100vh - 40px)` + flex column), header/footer fissi, body interno scrollabile. Risolve scheda cliente troppo alta (anagrafica+dati fiscali+sede+referente+note+filmografia+progetti+fonti AI) e tutti i modal con tanti campi. Approccio generico — niente toppe per-pagina.

**v3.4.50.1** — 2 maggio 2026 — Audit pre-push: 3 micro-fix

Bug fix emersi durante audit completo: (1) `seed_demo` tenant idempotente (`reset_business_data` preserva tenants → seed_demo doveva fare upsert); (2) `seed_demo` Booking ora crea `Booking + BookingAssignment` coerenti col modello multi-risorsa v3.4.16+; (3) `new_version_quote` ora pulisce suffisso `-vN` finale dal root number (no più `-v1-v2`).

**v3.4.50** — 2 maggio 2026 — Resource presets + sync orario tra risorse

Modal multi-risorsa booking: (1) preset di selezione `ResourcePreset(name, resource_ids JSON, …)` — CRUD su `/planning/api/resource-presets`, dropdown "📁 Carica preset…" + bottone "💾 Salva preset" (nome via prompt), apply con dedup + riempimento righe vuote + ereditarietà start/end dalla 1ª riga; (2) checkbox "🔗 Stesso orario per tutte le risorse" — propaga start/end della 1ª riga alle altre, preferenza in localStorage `mf_tlb_sync_times`. Tabella `resource_presets` auto-creata al boot.

**v3.4.49** — 2 maggio 2026 — Reset business data script

Nuovo `scripts/reset_business_data.py` (voce `[O]` su strumenti). Cancella tutte le entità "business" (clienti/progetti/quote/job/booking/risorse/timbrature/fatture/asset/notifiche/AI conversazioni) preservando configurazione (utenti/ruoli/reparti/listino/policy/AI settings/tenant/delivery_templates/tags). Idempotente in transazione, reset sqlite_sequence. Per il giro di test cumulativo del setup aziendale da scratch.

**v3.4.48.2** — 2 maggio 2026 — Look timeline: famiglia font + colore testo

Pannello ⚙ esteso: "Famiglia font" (auto/DM Sans/Inter/System/Serif/Mono) e "Colore testo" (auto/white/soft/amber/dark/indigo). Apply via `data-font-family` e `data-text-color` su `#tl-host` su items+label+time-axis. Auto eredita dal tema globale o dal bg variant.

**v3.4.48.1** — 2 maggio 2026 — Hotfix colore sfondo timeline

`data-bg` ora applicato a `.vis-timeline` (figlio dell'host) per superare il gradient hardcoded della libreria. Reset trasparente su `.vis-panel/.vis-foreground/.vis-background`. Variant "paper" con palette chiara (testo/grid/label invertiti).

**v3.4.48** — 2 maggio 2026 — Look timeline tweaks (bg + 3D items + dept fix)

Pannello ⚙: rimossa "Densità", aggiunta "Colore sfondo" (7 preset: default/dark/darker/warm/cool/forest/paper). Items: radius 7→9 + box-shadow multi-layer per effetto 3D bevel (inset highlight top + inset depth bottom + drop close+ambient). Fix accent "Per reparto": `DEPARTMENTS_SEED` ora include `color`, `tlBuildGroups` aggiunge className `tl-dept-{id}`, `tlPrefsApply` genera CSS dinamico per ogni reparto (gradient + border + filter brightness). Helper `_hexToRgba`.

**v3.4.47** — 2 maggio 2026 — Filtri planning multi-select

I 4 filtri autocomplete (Cliente, Progetto, Job, Risorsa) ora multi-tag con chips. Hidden value `comma-separated` ids. Backend helper `_parse_id_list` su `/planning/api/jobs|bookings|unavailabilities` accetta single, comma-separated, list. Active filters bar: "N selezionati" se >1. Backspace su input vuoto rimuove l'ultimo chip.

**v3.4.46** — 2 maggio 2026 — Look timeline customization (preferenze locali)

Pannello ⚙ in topbar `/planning?view=timeline`. Settings: densità (compact/normal/comfort), font items (11/11.5/12/13), accent reparto (indigo/mono/dept), storyboard density, toggle animazioni/heatmap/today-glow/weekend-bg. Persisted in `localStorage` `mf_tl_prefs`. Applicati via `data-*` su `#tl-host` + CSS reactive + `<style id="tl-prefs-dynamic">` per font-size. Niente backend, niente migrazione.

**v3.4.45.1** — 2 maggio 2026 — Hotfix `/planning` 500 (UserRole.code)

Fix critico: `cur_user.role.code` non esisteva (User.role è l'enum legacy UserRole). Sostituito con `is_producer(user)` da `app.services.rbac` in `planning_hub` e `project_bookings`. /planning/ ora 200.

**v3.4.45** — 2 maggio 2026 — Look timeline: deep restyle + Storyboard view

C4a: pass CSS su vis-timeline (time axis tipografato, items radius/padding/glow, drag handles fade-in, today line con dot+glow, group nesting più contrastato, heatmap container con radius). C4b: nuova tab `🎬 Storyboard` settimanale, 7 colonne giorno (Lun→Dom), navigazione settimana, cards booking ordinate per ora con badge risorsa colorato, click → modal dettaglio. Responsive (1100px → 4 col, 720px → 1 col).

**v3.4.44** — 2 maggio 2026 — Ore lavorate + drilldown + view per progetto

#6: indicatori execution_status sui booking timeline (in_progress=pulse arancione, done=bordo verde+✓, not_done=tratteggiato rosso) via classi `tl-exec-*` in `tlBookingToItem`. #7a: cell ore in `/planning?view=jobs` cliccabile → modal drilldown con lista prenotazioni del job. #7b: tab "📂 Per progetto" in `/planning` visibile a admin/manager/producer/edit_planning, dropdown progetti + cards "Le mie" raggruppate per risorsa. Endpoint `GET /planning/api/project-bookings?project_id=X`.

**v3.4.43** — 2 maggio 2026 — Duplica quote con scelta progetto + Sposta progetto

#4: `POST /quotes/api/{id}/duplicate` accetta `project_id` opzionale (riallinea client_id al progetto target). UI: modal `Duplica quotazione` con dropdown searchable progetti (vuoto = stesso progetto). Nuovo endpoint `PUT /quotes/api/{id}/move-to-project` per spostare una quote `draft` senza job a un altro progetto. Bottone "🚚 Sposta" nell'editor, visibile solo per draft.

**v3.4.42** — 2 maggio 2026 — Undo paste timeline + Le mie con dettaglio booking + note

#1: `tlPasteAt` ora pusha undo `paste_batch` con gli id dei booking creati → annullamento bulk via DELETE. #8: card "Le mie" e dashboard "I miei booking di oggi" cliccabili (su title/meta) → modal `Dettaglio booking` con Quando/Job/Lavorazione/Stato/Risorse/Note/Motivazione. Note del booking ora visibili inline sulla card. Endpoint nuovo `GET /planning/api/bookings/{id}/detail`.

**v3.4.41** — 2 maggio 2026 — Bug fix triplo (paste su ferie + Chrome timbratura + cost report ore done)

#2: paste timeline planning ora hard-block su risorse in ferie/malattia (toast con counter bloccati). #3: Chrome `::-webkit-calendar-picker-indicator` soppresso su input time non-opt-out + `.mf-dt` grid con `minmax(0, …)` per layout robusto in modali stretti. #5: nuovo servizio `cost_line_sync.py` aggancia `JobCostLine.quantity_actual` + `total_accrued` ai booking `done` (hook in execution/extend + endpoint `POST /cost-report/api/job/{id}/reconcile-actuals` per fix retroattivo).

**v3.4.40** — 2 maggio 2026 — Searchable dropdowns + Time picker popup

Helper trasversali in `global.js`: ogni `<select>` non-multiple e senza `data-no-search` viene trasformato in combobox cercabile (input ricerca + dropdown filtrabile, keyboard ↑↓EnterEsc, sync programmatico via `select._mfSsRefresh()`). Ogni `<input type="time">` riceve popup HH:MM step 15min con quick-pick row. Ogni `<input type="datetime-local">` viene splittato in due input affiancati (date + time) con il time-picker custom applicato al sub-time. Stile coerente con palette indigo. Cache-buster `?v=3.4.40`.

**v3.4.39** — 2 maggio 2026 — Quote: duplica + versioning + Floating Jobs

Due funzioni distinte: (1) `📋 Duplica` semplice (clone indipendente, scenari/template), (2) `📐 Versione` (legata via `parent_quote_id`, numero `-v2`/`-v3`, eredità righe via `QuoteLine.parent_line_id`). Endpoint `migrate-job` per migrazione del Job tra versioni con preview righe orfane/sforamenti e scelta `orphan_strategy` (`keep_as_extra` o `floating_job`). Nuovo enum `QuoteStatus.superseded`. Sezione "⚠ Anomalie" in `/finance` con 3 card (Job orfani, Sforamenti, Extra) + badge counter sulla tab. Migrazione `[N]` idempotente, auto-applicata al boot.

**v3.4.38** — 1 maggio 2026 notte profonda — Round 3 Audit: hardening logico (3 round completati)

Audit logico completo (R1+R2+R3). R3.1 invariante count_in_costs↔execution_status. R3.2 RBAC edit_quotes su update_quote. R3.3 reset original_end_datetime su shortening (booking accorciato sotto soglia → overtime_status=none). R3.4 FSM transizioni JobStatus con matrice esplicita. R3.5 cleanup Timesheet legacy nel cost report (rimossi hours_cost/hours_cost_legacy_timesheet/timesheet_summary, fonte canonica = Booking).

**v3.4.37** — 1 maggio 2026 notte profonda — Round 2 Audit: barra avanzamento job

Round 2 di 3 dell'audit. Endpoint `/planning/api/jobs/{id}/progress` + flag `?include_progress=true` su lista jobs. Colonna "Avanzamento" in `/planning?view=jobs` con barra CSS color-coded. Algoritmo: ore booking `done` / ore booking totali (esclusi cancelled e pool not_done).

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

**Sessione 5 maggio — Round 7 aperto su lista feedback Matteo (12 punti).**

Lista feedback ricevuta:

**Round 7A (chiuso in alpha.16 — 4 bug puri):**
- ✅ Straordinari nella lista timbrature per singola riga + nel totale
- ✅ Filtro Tipo in "Le mie ore" funzionante (categorie breakdown invece di raw kinds)
- ✅ Ferie/malattia visibili nella tabella timbrature
- ✅ Shift+drag ROI riscritto + Alt+drag + toggle "Selezione area" toolbar

**Round 7B (chiuso in alpha.17):**
- ✅ Cost report: dropdown → searchable + filtri + lista default (pattern come `/quotes`)
- ✅ Quote ricerca + filtri simmetrici al cost report
- ✅ Cost report cliente PDF: opzione "rendiconto" (quotato/maturato/stimato + over/under) + export CSV/XLSX

**Round 7C (chiuso in alpha.18):**
- ✅ Undo/redo planning timeline (stack max 50 + bottoni toolbar persistenti + undo per `remove_assignment`)
- ✅ Bulk modify bookings (modal con shift orario + cambio stato esecuzione, endpoint `bulk-edit`)

**Round 7D (chiuso):**
- ✅ 7D.1 — AI integrazione GUI/settings (alpha.19): registry `settings_registry.py`
  + 3 tool AI generici (list/read/update). 2 schemi iniziali (working_hours,
  tenant_settings). Estendibile a tutto il software via add di nuovi schemi.
- ✅ 7D.2 — Menu assegnazioni risorse a 200 progetti (alpha.20): vista Matrice
  Risorsa × Job + filtri server-side + ricerca client-side + modal upsert cella.
  Toggle Matrice/Kanban (kanban legacy preservata).
- ✅ 7D.3 — Risorse + reparti a 500/30 (alpha.20): pagina `/team` con sidebar
  reparti drill-down + griglia card. Voce sidebar `/resources` → `/team`.

**Sessione 4 maggio chiusa — Round 1 fix post-test del 3 maggio chiuso (v3.5.0-alpha.9).** Working tree pulito dopo commit alpha.9. Round 2 e Round 3 in attesa di green-light Matteo + riapertura.

### Issue identificati nel test estensivo Matteo del 3 maggio

**Round 1 (chiuso in alpha.9)** — fix integrità + UX bloccante:
- ✅ Cost report maturato fantasma post-delete booking/assignment
- ✅ HR overtime 400 → 200+warning (sblocca pagina /hr e modal timbratura)
- ✅ Timepicker quick options estese (07→23, mezz'ora)
- ✅ openModal refresh searchable wrappers (fix dept mancante in modal risorsa)
- ✅ Pagina Accesso Negato centrata

**Round 2 — RBAC editor (chiuso in alpha.10)**:
- ✅ Editor non vede prezzi/budget in `/jobs/{id}` + tabella jobs di `/planning` + modal job-detail
- ✅ Editor non può creare booking direttamente — modal create diventa "📩 Richiedi booking" → POST `/api/booking-requests` → notifica `booking_request` a producer/manager
- ✅ Editor non può assegnare risorse a progetto/job (`POST /cost-report/api/job/{id}/assign-resource` gated)
- ✅ Override manuale `quantity_actual` rimosso dovunque (decisione: ore = booking done, sempre)

**Round 3 — UX/feature (chiuso: 9/9 in alpha.11+alpha.12)**:
- ✅ Quote editor: subtotali categoria live + nuova riga "Totale categoria al netto" sotto lo sconto (alpha.11)
- ✅ Add resource a booking esistente / job esistente → auto-assign al progetto (hook esteso a PUT booking + PUT assignment, alpha.11)
- ✅ Booking done propaga a tutte le risorse (refresh timeline su todoSetExec, alpha.11)
- ✅ Timeline highlight cross-resource su click di un booking multi-risorsa (alpha.11)
- ✅ Timeline overlay con orario corrente durante drag/resize (alpha.11)
- ✅ Timeline copy multi-risorsa (era singolo, alpha.11)
- ✅ UX `quantity_actual` lavorazione: rimosso edit completo (Matteo decisione 4 maggio, alpha.10)
- ✅ Cost report row: popup booking-detail (porting di `openLineDetail` da `job_detail.html`, alpha.12)
- ✅ Cost report: hardcost (`QuoteLine.hardcosts`) esposti nel popup detail come blocco "Hardcost (materiali / spese vive)" (alpha.12)

### Domande aperte chiuse in questa sessione

- ✅ Override manuale `quantity_actual` → Matteo: rimuovi completamente. Fatto in alpha.10.
- 🟡 Modifica nome lavorazione: oggi richiede `view_finance`. Restringere a `edit_quotes` (più stretto)? — non ancora deciso.

### Cantieri chiusi nella sessione del 3 maggio

1. ✅ **Reverse-flow v1** — job extra da booking su progetto senza quote (v3.4.51)
2. ✅ **Reverse-flow v2** — booking → QuoteLine + approvazione implicita / phantom quote (v3.4.52)
3. ✅ **Booking parla quote+lavorazione** (Job nascosto), filtro reparto risorse (v3.4.53)
4. ✅ **Project filter nel booking** + cost-line RBAC (`edit_cost_actuals`, lock `quantity_actual` per non finance) (v3.4.54)
5. ✅ **Fix sistemico integrità Quote↔Job↔Booking** — HARD-BLOCK delete con booking attivi, vista lavorazione read-only, auto-assignment Resource→Job, man-hours canonico (v3.4.55)
6. ✅ **Conferma assegnazione risorse + warning quote approved senza risorse** + 3 docs Mermaid `workflow.md`/`data-model.md`/`permissions-matrix.md` (v3.4.56)

**Sessione 3 maggio chiusa — 6 commit (v3.4.51 → v3.4.56) NON ancora pushati su origin/main** (8 commit ahead totali). Working tree pulito.

### Cantieri chiusi nella sessione

1. ✅ **Reverse-flow v1** — job extra da booking su progetto senza quote (v3.4.51)
2. ✅ **Reverse-flow v2** — booking → QuoteLine + approvazione implicita / phantom quote (v3.4.52)
3. ✅ **Booking parla quote+lavorazione** (Job nascosto), filtro reparto risorse (v3.4.53)
4. ✅ **Project filter nel booking** + cost-line RBAC (`edit_cost_actuals`, lock `quantity_actual` per non finance) (v3.4.54)
5. ✅ **Fix sistemico integrità Quote↔Job↔Booking** — HARD-BLOCK delete con booking attivi, vista lavorazione read-only, auto-assignment Resource→Job, man-hours canonico (v3.4.55)
6. ✅ **Conferma assegnazione risorse + warning quote approved senza risorse** + 3 docs Mermaid `workflow.md`/`data-model.md`/`permissions-matrix.md` (v3.4.56)

### Da testare sul Mac (priorità sessione 3 maggio)

1. **Reverse-attach quote draft/sent**: booking su progetto con quote in trattativa → modal `modal-tlb-reverse-quote` → sceglie attach_existing → quote diventa `approved` (implicit), job creato, `JobCostLine` allineata, AM riceve notifica `quote_reverse_approval`
2. **Phantom quote**: booking su progetto senza quote → modal → sceglie `create_phantom` → nuova `Quote(is_phantom=True, status=approved)` + job + JobCostLine
3. **Booking parla quote+lavorazione**: modal mostra "Quotazione" non "Job"; ricerca filtra per departments delle risorse; promote-line-to-cost-line transparent al save
4. **HARD-BLOCK delete QuoteLine**: prova a cancellare riga con booking attivo → 409 con elenco; cancella i booking, poi riprova → 204
5. **Vista lavorazione read-only**: editor/operator clicca riga in `/jobs/{id}` → vede KPI + booking + risorse, nessun bottone Modifica. Con view_finance vede bottone.
6. **Auto-assignment**: crea booking di una risorsa nuova su un job → `JobResourceAssignment` apparso (controlla in `/jobs/{id}` tab risorse); pre-save dialog conferma se ci sono missing.
7. **Man-hours**: 2 colorist × 8h booking done → JobCostLine.quantity_actual = 2 (giornate-colorist), non 1.
8. **Cost-line RBAC**: editor/operator entra in PUT cost-line → `quantity_actual` read-only badge "richiede edit_cost_actuals"; admin/manager/accounting può editare.
9. **Notifica quote_approved_no_resources**: approva quote senza assignment → admin/manager/producer ricevono notifica `severity=action_required`.
10. **Workflow docs**: apri `docs/workflow.md` su GitHub o IDE con preview Mermaid → 5 diagrammi renderizzati (state Quote, state Booking, flow forward/reverse/phantom, fonti Maturato, vincoli HARD-BLOCK).

### Da testare sul Mac (priorità)

Setup pulito con `[O] reset_business_data`:
1. Crea clienti, progetti, risorse, listino già pronto (preservato)
2. Quote → cambio progetto / duplica con progetto / nuova versione / migrate-job
3. Booking multi-risorsa con preset + sync orario
4. Booking done → cost report mostra ore maturate
5. Filtri multi (cliente/progetto/job/risorsa) sulla timeline
6. Storyboard week view
7. Pannello ⚙ look timeline (bg/font/colore testo/accent reparto)
8. Anomalie in /finance (job orfani / sforamenti / extra)
9. Le mie + dettaglio booking
10. Tab "Per progetto" (manager+)

### Riapertura

Parola chiave: **"Riprendi da v3.5.0-alpha.8 — apri con il tuo ultimo commento"**.

### Sessione 3 maggio 2026 — push completato

21 commit ahead origin/main → push eseguito su richiesta esplicita di Matteo.
Sequenze:
- Mattino: v3.4.51→v3.4.56 (reverse-flow, invarianti integrità Quote↔Job↔Booking, workflow docs Mermaid)
- Pomeriggio/sera: v3.5.0-alpha.1→alpha.8 (AI tool-use nativo Anthropic + Cestino quote+project con retention auto)

### Carry-over sessione 2 maggio (test ancora non eseguiti)

Setup pulito con `[O] reset_business_data` e batteria test descritta nelle versioni v3.4.39→v3.4.50.1 (vedi storico più sotto).

### Cantieri proposti, non avviati (backlog)

Da testare per **v3.4.40**:
- Ogni `<select>` non-multiple → click apre dropdown con input "Cerca…" + lista filtrabile. ↑↓ Enter Esc.
- Modali (es. nuova fattura, nuovo booking, nuova quote, modifica utente) con select popolati async → display deve aggiornarsi al value (auto-refresh su click `[onclick*="openModal"]` con setTimeout 80ms).
- `<input type="time">` (es. /settings#hours, modal multi-risorsa /planning) → click apre popup grid HH:MM con quick-pick.
- `<input type="datetime-local">` (es. nuova timbratura /hr) → splittato in `[date] [time]` affiancati. Il time apre il popup custom. Submit deve continuare a inviare il datetime composto.
- Nessun layout shift / regressione su select esistenti.

Da testare per **v3.4.39**:
- Migrazione `[N]` (auto al boot, opzione strumenti per fallback esplicito)
- `/quotes` lista: bottoni `📋` e `📐` accanto a "Job ✓"
- Editor: "📋 Duplica" e "📐 Versione" in topbar; sezione "Versioni" appare quando catena > 1
- Crea V2 di una quote approvata con job → vai su V2, modificala (rimuovi una riga, modifica una quantità sotto consuntivo) → "↪ Migra Job a questa versione"
- Preview deve elencare orfane con badge ⚠ (se hanno quantity_actual), sforamenti, fresh
- Conferma con `keep_as_extra` → vecchia diventa "superseded", nuova "approved", job ribindato. JobCostLine orfane diventano extra.
- Conferma con `floating_job` → job.quote_id=NULL → appare in `/finance > Anomalie > Job orfani`
- `/finance` tab "⚠ Anomalie": 3 card popolate, badge rosso sulla tab

**Sessione 1 maggio notte profonda chiusa — 17 versioni v3.4.32→v3.4.38 + push su origin/main `60b2e09..e735495`.** Working tree pulito, audit logico completo (3 round).

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

**Sessione 3 maggio**: chiusi tutti gli invarianti d'integrità (v3.4.55) + i 2 TODO + workflow docs (v3.4.56). 8 commit ahead di origin/main.

Le opzioni naturali per la prossima sessione, in ordine di valore:

1. **Test estensivo sul Mac** sulla batteria sopra elencata (sessione 3 maggio + carry-over sessione 2 maggio). Se Matteo trova bug, hotfix.
2. **Push su origin/main** dopo green light dei test (criterio: push solo a major bump per memoria, ma 8 commit con cambio strutturale può giustificare un v3.5.0 se i test passano).
3. **Cantieri ancora rinviati** (in ordine di backlog):
   - Cost report doppio (interno con rate × ore + hardcost; esterno cliente con solo ore + extra + bottone "→ Genera quote v2")
   - Overlay "prenotato vs effettivo" (booking vs TimePunch) + report delta producer
   - E5 booking ricorrenti + tentative bookings (legati a quote draft/sent → committed quando approved) + audit log
   - E6 capability AI `propose_booking` (skill match + availability + storico)
   - Multi-valuta con cambio automatico ECB
   - Cestino per-tenant con retention configurabile

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

*Ultimo aggiornamento: 3 maggio 2026 — chiusa v3.4.56 (conferma assegnazione + warning quote-no-resources + 3 docs Mermaid). Sessione 3 maggio: 6 commit (v3.4.51→v3.4.56). 8 commit ahead origin/main, push solo dopo green light test sul Mac (eventuale v3.5.0).*

**v3.4.55+v3.4.56**: chiusi 5 invarianti sistemici (eliminazione HARD-BLOCK con booking attivi, vista lavorazione read-only, auto-assignment Resource→Job, man-hours canonico, Job nascosto in booking) + 2 TODO (pre-save confirm risorse non assegnate, notifica `quote_approved_no_resources`). Aggiunti `app/services/resource_assignment_sync.py` + 3 docs Mermaid in `docs/` (workflow / data-model / permissions-matrix). Niente migrazione DB.

**v3.4.51→v3.4.54**: cantiere reverse-flow (job extra da booking su progetto senza quote → reverse v2 con QuoteLine + approvazione implicita / phantom quote → booking parla quote+lavorazione con Job nascosto → project filter + cost-line RBAC con permesso `edit_cost_actuals`).

---

*Versione precedente: 1 maggio 2026 sera — chiusa v3.4.32 (Booking esecutivo). 37 commit ahead origin/main. Push da concordare.

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
