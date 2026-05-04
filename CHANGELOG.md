# MediaFlow — Changelog

## v3.5.0-alpha.10 — Round 2: RBAC editor + ore lavorate sempre da booking (4 maggio 2026)

Round 2 dei fix post-test 3 maggio. Restringe i permessi di editor (operator role) e fissa architetturalmente la regola "ore lavorate ≡ booking done" decisa con Matteo il 4 maggio.

**Decisione architetturale: niente più override manuale di `quantity_actual`**

Le ore lavorate sul cost line corrispondono SEMPRE alle ore dei booking marcati `done`. La modifica manuale era un escape hatch (perm `edit_cost_actuals` per admin/manager/accounting), ma in pratica è un caso eccezionale che squilibra il cost report. La gestione di scontistiche / banca ore forfait / extra fattura passerà dal flusso fatturazione dedicato (in roadmap), non dall'editing del cost line.

Backend
- `PUT /jobs/api/{id}/cost-lines/{lid}` e `PUT /cost-report/api/job/{id}/cost-lines/{lid}`: rifiutano `quantity_actual` (e `total_accrued`) con HTTP 422 + messaggio chiaro. Restano editabili description, quantity_quoted, unit, unit_price, is_extra, is_billable, total_expected, notes.
- `edit_cost_actuals` permesso marcato `[DEPRECATO]`, rimosso da `manager` e `accounting` preset. Solo admin lo eredita (admin = tutti i permessi) ma il backend ignora comunque.

UI
- `job_detail.html` modal "Modifica lavorazione": campo "Ore lavorate" → display read-only con suffix unità + nota "🔒 Derivate da booking done".
- `cost_report.html` modal "Aggiorna riga costo": rimossi "Quantità effettiva" e "Totale maturato"; aggiunto "Ore lavorate" read-only display. Restano editabili "Totale stimato a finire" + "Note".

**RBAC editor (Luca Bianchi / operator role)**

Editor ha solo `view_planning` + `edit_planning_own` + `view_punches_own` + `edit_punches_own` + `view_projects`. NON ha `view_finance` né `assign_resources` né `edit_planning_all`. I bug emersi nel test:
1. Vede "Budget quotato" job-meta-card e colonne "€ unitario" / "Tot. previsto" in `/jobs/{id}` — non dovrebbe.
2. Vede "Budget", "Costi", "Margine" nel modal job-detail di `/planning` — non dovrebbe.
3. Vede colonna "Budget" nella tabella jobs di `/planning?view=jobs` — non dovrebbe.
4. Può creare booking propri tramite il modal del planning — non dovrebbe (Matteo: "solo richiesta booking al producer").
5. Può assegnare risorse a job tramite endpoint cost-report — non dovrebbe.

Fix:
- **Nuovo helper RBAC `can_create_booking(user)`** = ha `edit_planning_all` O `assign_resources` (admin/manager/producer). Editor → false.
- **Backend gate** su `POST /planning/api/bookings` con `can_create_booking`. Editor riceve 403 con messaggio "Usa il flusso 'Richiedi booking'".
- **Backend gate** su `POST /cost-report/api/job/{id}/assign-resource` (e DELETE) con `can_assign_resources`. Editor riceve 403.
- **Nuovo endpoint `POST /planning/api/booking-requests`**: chiunque autenticato può inviare una richiesta di booking (start, end, resource, quote, lavorazione, motivazione obbligatoria) — il backend non crea il Booking, crea una notifica `booking_request` (action_required) ai producer/manager via `notify_permission(permission="assign_resources")`. Il producer poi crea il booking dalla pagina /planning.
- **Frontend planning.html**: aggiunto `CAN_VIEW_FINANCE` / `CAN_CREATE_BOOKING` / `CAN_ASSIGN_RESOURCES` flag dal server.
  - Tabella jobs: colonna "Budget" condizionale.
  - Modal `showJobDetail`: blocco Budget/Costi/Margine condizionale + chiamata `/finance/api/...` saltata se editor.
  - Modal `tlb-booking`: titolo dinamico "Nuovo booking" vs "📩 Richiedi booking", bottone submit "Crea booking" vs "Invia richiesta".
  - `tlbSubmit`: se non editing e non `CAN_CREATE_BOOKING`, redirige il payload a `/api/booking-requests`.
- **Frontend job_detail.html**: server-side `{% if can_view_finance %}` su "Budget quotato" job-meta-card + colonne "€ unitario" / "Tot. previsto" della tabella lavorazioni. JS `renderLines` salta le celle € se non `CAN_VIEW_FINANCE`. `openLineDetail` mostra KPI senza prezzi (solo ore) per editor.
- **NotificationKind nuovo**: `booking_request` → can_create_booking (admin/manager/producer).

Cache-buster `base.html` → `global.js?v=3.5.0-alpha.10`.

Niente migrazione DB.

---

## v3.5.0-alpha.9 — Round 1 fix post-test estensivo Matteo (4 maggio 2026)

Bug fix focalizzato emerso dal test estensivo del 3 maggio. Tagliato il primo round di issue prioritari prima dei cantieri più grossi (RBAC editor, quote editor live, timeline UX).

**Cost report — maturato fantasma post-eliminazione (HIGH IMPACT)**

I `DELETE /api/bookings/{id}` e `DELETE /api/booking-assignments/{id}` non triggeravano `cost_line_sync.recompute_for_booking`. Risultato: il `JobCostLine.quantity_actual` restava congelato dopo la cancellazione e il cost report continuava a mostrare il maturato come se il booking esistesse ancora.

Fix in `app/routers/planning.py`:
- `delete_assignment`: dopo lo `db.delete(a)` e refresh booking, chiamo `recompute_for_booking(db, booking)`. Aggiorna man-hours (-1 risorsa) o pulisce tutto se ultima.
- `delete_booking`: dopo `b.status = cancelled`, chiamo `recompute_for_booking(db, b)`. La query in `recompute_cost_line_actual` filtra `status != cancelled` quindi il booking appena cancellato esce dal totale.
- `update_booking` (PUT replace-all assignments) e `update_assignment` (PUT singolo drag/resize): recompute aggiunto se booking è done (cambia man-hours).

Tutti i fix sono try/except con log per non rompere la transazione principale (idempotente, fail-safe).

**HR overtime endpoint — degradazione graceful invece di 400**

`/hr/api/overtime` ritornava 400 se mancava la `WorkingHoursPolicy(is_default=True)` del tenant, rompendo il rendering della pagina `/hr` (la dashboard "Le mie ore" chiama l'endpoint al load). Il sintomo collaterale era anche l'impossibilità di chiudere una timbratura aperta — il modal usa l'API ma la pagina era in stato semi-bloccato.

Fix in `app/routers/hr.py`:
- Se la policy manca, l'endpoint ritorna 200 con `breakdown` calcolato come somma flat delle ore (no split regular/overtime/notturno) + warning testuale `"Nessuna WorkingHoursPolicy default configurata. Vai in /settings#hours…"`. Lasciamo all'utente la scelta di configurarla.

**Timepicker — quick options estese**

`_MF_TP_QUICK` in `app/static/js/global.js` aveva solo 8 orari (08/09/12/13/14/17/18/20). Aggiunti tutti i passaggi orari standard (07:00 → 23:00 + 00:00) con granularità mezz'ora sui passaggi giornata (08:30, 09:30, 12:30, 13:30, 14:30, 17:30, 18:30, 19:30). 27 quick-pick totali. La griglia HH:MM completa ogni 15min resta sotto.

**openModal helper — refresh searchables/timepickers (fix sintomo "campo non si vede nel modal")**

`document.getElementById('rs-dept').value = r.department_id` non aggiornava il display del wrapper `mf-ss` perché impostava solo `select.value` senza rinfrescare il bottone display custom. Sintomo: nel modal modifica risorsa il reparto risultava vuoto anche se la risorsa lo aveva.

Fix in `app/static/js/global.js` su `openModal()`: dopo aver aperto il modal chiama `mfApplySearchable(modalEl)` + `mfApplyTimePickers(modalEl)` con setTimeout 0 (per consentire al codice chiamante di settare i value nello stesso turno sincrono). Idempotente. Generalizzato a tutti i modal — risolve potenzialmente altri sintomi simili.

**Pagina Accesso Negato — centratura corretta**

Il `body` globale (`main.css`) ha `display: flex; min-height: 100vh;` per il layout sidebar+content. Il pannello 403 stand-alone ereditava questa flex-row, lasciando il contenuto inerte a sinistra anche con `justify-content: center` sull'inner div.

Fix in `app/main.py` `_forbidden()` e in `templates/pages/tech_sheet_public_error.html`: aggiunto `style="display:block;"` sul body delle pagine stand-alone + `width:100%; box-sizing:border-box` sul container.

**Cache-buster**

`base.html`: `global.js?v=3.5.0-alpha.9`.

---

## v3.5.0-alpha.8 — Cestino Project (Slice 4) + Retention auto (Slice 5) (3 maggio 2026)

Estende il framework soft-delete da Quote a Project + aggiunge retention configurabile con purge cascade dei record scaduti.

**Slice 4 — Project soft-delete**

Backend
- `Project.deleted_at` + `Project.deleted_by_user_id` (auto-migrate idempotente, generalizzato il loop per applicare lo stesso schema a quotes+projects).
- `Project` aggiunto a `_SOFT_DELETE_MODELS` → filter automatico via event listener (le query default vedono solo progetti vivi; bypass con `execution_options(include_deleted=True)`).
- `app/services/soft_delete.py`: `soft_delete_project(force)`, `restore_project()`, `fetch_project_including_trash()`. Regole:
  - Quote ATTIVE (non in cestino) sul progetto → HARD-BLOCK 409 con elenco bloccanti. Quote già cestinate non bloccano (puoi cestinare il progetto sopra).
  - `force=True` (perm `purge_total`): cascade hard-delete su Project + Quote + Job + JobCostLine + Booking + assignments + JobResourceAssignment.
- `DELETE /projects/api/{id}?force=` riscritto sulla nuova logica (sostituisce il vecchio HARD-BLOCK 400 grezzo). Permesso `delete_projects`.
- `POST /projects/api/{id}/restore` (perm `restore_trash`).
- `/admin/api/trash` esteso con sezione `project`. `/admin/api/trash/{type}/{id}/restore|delete` supporta `entity_type=project`.

RBAC nuovo permesso `delete_projects` → admin/manager/producer.

UI
- `/projects` lista: tasto 🗑 sempre attivo (era disabilitato se quotes_count>0). Backend gestisce il 409 con elenco quote bloccanti + bottone "Pulizia totale" se admin.
- `/admin/cestino`: tab "Progetti" accanto a "Quotazioni", count counter, card con badge cliente/status/quotes_count, bottoni Ripristina/Elimina definitivamente.

**Slice 5 — Retention configurabile + purge auto**

- `app/config.py`: setting nuovo `trash_retention_days` (default 30, da `.env` `TRASH_RETENTION_DAYS`). 0 = disabilitato (cestino infinito, gestione manuale).
- `app/services/soft_delete.py`: `purge_expired_trash(dry_run, retention_days)` cancella cascade i record con `deleted_at < now - N giorni`. Per ciascun record applica la stessa logica di `soft_delete_*(force=True)` (cascade aggressivo).
- Endpoints admin (perm `view_trash` per info, `purge_total` per esecuzione):
  - `GET /admin/api/trash/expiry-info`: dry-run con elenco record che verrebbero purgati + retention_days configurato.
  - `POST /admin/api/trash/purge-expired`: esegue il purge.
- UI `/admin/cestino`: banner header con stato retention + count scaduti + bottone "⏱ Purga scaduti" (solo admin con `purge_total`). Dialog di conferma con preview dei numeri.

Niente cron al boot per ora: il purge resta manuale via bottone admin. Hook al boot opzionale è banale da aggiungere se serve (call diretta a `purge_expired_trash` in `lifespan`); non lo mettiamo di default per non sorprendere l'utente al primo avvio.

Smoke test verde: project soft-delete cascade quote, filter ON nasconde progetto cestinato, restore ripristina, dry-run retention 30gg ritorna 0 record (giusto, niente di vecchio in DB di test).

## v3.5.0-alpha.7.5 — Rinomina inline di title e number quote (3 maggio 2026)

Editor `/quotes`: header (riga 1 della topbar) ora inline-editable.

**Backend** (`PUT /quotes/api/{quote_id}`):
- Accetta `title` (Form, opzionale): libero in qualsiasi stato.
- Accetta `number` (Form, opzionale): permesso SOLO se `status=draft`. Una quote `sent`/`approved` ha già un numero ufficiale comunicato al cliente, non si tocca → 409 con messaggio. Pre-check unicità con bypass soft-delete (le quote in cestino occupano il number, vincolo UNIQUE su DB).
- Permesso `edit_quotes` per entrambi (invariato).
- Response include ora `number` e `title` per refresh UI.

**UI**:
- Header dell'editor ora due `contenteditable` separati: `<span id="editor-number">` e `<span id="editor-title">`. Click → input + selezione testo, Enter salva, Esc annulla, blur salva.
- Stato `draft` → entrambi editabili. Altri stati → number diventa read-only con opacity 0.7 e tooltip esplicativo, title rimane editabile.
- Border-bottom dashed in hover per scoprire l'editabilità.
- Toast "Numero aggiornato a Q-..." / "Titolo aggiornato" + reload lista.
- Errori (409 not draft, 409 collisione) mostrati come toast e ripristino del valore originale.

Smoke test: rename verde su draft (number + title), bloccato su approved.

## v3.5.0-alpha.7.4 — Tool result più espliciti per evitare allucinazioni AI (3 maggio 2026)

Bug osservato (Matteo, ISIDE): dopo `propose_project ISIDE` con status=applied (creato OK con id=5), Sonnet nel turno successivo ha detto "Il progetto ISIDE esiste già in DB". Lettura sbagliata del tool_result, che era solo `{project_id: 5, code: "ISIDE", title: "ISIDE", client: "Cattleya"}` — ambiguo: poteva essere un record creato O trovato.

Fix: i 5 handler mutation principali ora ritornano un payload più esplicito:
- `created: true` come flag chiaro
- `message: "..."` con frase descrittiva in italiano

Handler aggiornati:
- `_h_propose_client` → `"Cliente 'X' creato con id=N."`
- `_h_propose_project` → `"Progetto 'CODE' (Title) creato con id=N per cliente Y."`
- `_h_propose_price_item` → `"Voce listino 'X' creata con id=N (categoria, unit, €price)."`
- `_h_propose_quote` → `"Quotazione Q-... creata con id=N per progetto CODE (M righe, totale netto €X)."`
- `_h_propose_quote_line` → `"Riga aggiunta alla quote #N: descrizione, qty K unit, total €X."`
- `_h_propose_new_item_and_line` → idem.

L'AI ora riceve un tool_result inequivocabile e produce text response coerente.

**Memoria di sistema** (per chiarezza): il purge totale di una Quote (`?force=true`) cancella SOLO `Quote + Job + JobCostLine + Booking + assignments`. NON tocca `Project`, `Client`, `PriceItem` (anagrafica). Per resettare l'anagrafica usare `[O] reset_business_data` da `strumenti.bat`. By design: cestino è per quote/lavorazioni, non per anagrafica (memoria `project_costreport_vs_timesheet.md`).

## v3.5.0-alpha.7.3 — Hotfix: collisione numero quote dopo soft-delete (3 maggio 2026)

> propose_quote → 500 Internal Server Error
> sqlalchemy.exc.IntegrityError: UNIQUE constraint failed: quotes.number — Q-2026-001

Bug architetturale del cestino: `_next_quote_number` cerca il prossimo progressivo via `Quote.number LIKE 'Q-2026-%'`, ma il filter automatico soft-delete esclude le quote con `deleted_at IS NOT NULL`. Le quote in cestino occupano comunque il `number` (vincolo UNIQUE su DB) → progressivo collidente → INSERT fallisce.

Il filter è "user-facing" (UI nasconde le cestinate), ma per le query di sistema che dipendono da unicità DB devo bypassarlo con `execution_options(include_deleted=True)`.

Fix in 4 punti:
1. `ai_assistant._next_quote_number` (auto-numero per `propose_quote` AI)
2. `ai_assistant._h_propose_quote` (controllo unicità prima di INSERT)
3. `quotes._next_quote_number_progressive` (auto-numero da UI)
4. `quotes new-version` (controllo unicità new_number)

Smoke test: dopo aver cestinato Q-2026-001 (visibile in cestino), `propose_quote` ora genera Q-2026-002 correttamente.

**Lezione architetturale memorizzata**: con soft-delete, ogni vincolo UNIQUE/progressivo deve esplicitamente decidere se considerare i record cestinati. Pattern `execution_options(include_deleted=True)` per le query di sistema. Per le query user-facing (lookup, validazione semantica) lasciare il filter di default.

## v3.5.0-alpha.7.2 — Hotfix: escapeHtml is not defined in /admin/cestino (3 maggio 2026)

> Uncaught ReferenceError: escapeHtml is not defined — cestino:206

`admin_trash.html`: avevo messo lo `<script>` dentro `{% block content %}` che è renderizzato a metà di `base.html` (riga 160), ma `global.js` (dove vive `escapeHtml`) viene caricato a fine pagina (riga 177). Quindi al primo run dello script `escapeHtml` non esiste ancora.

Pattern corretto in tutte le altre pagine: `{% block scripts %}` viene piazzato DOPO `global.js` da `base.html`. Spostato lo script lì.

Memoria `feedback_global_helpers_centralizzati.md` ricorda proprio questo: ridefinire helper localmente è anti-pattern, ma usarli prima del caricamento di global.js produce lo stesso sintomo.

## v3.5.0-alpha.7.1 — Hotfix: SyntaxError JS in /quotes (3 maggio 2026)

> Uncaught SyntaxError: expected expression, got '}' quotes:2:1

Bug introdotto in alpha.7: avevo usato `JSON.stringify(q.number)` come argomento di un `onclick="..."` HTML attribute. Quando il numero contiene `"` (e JSON.stringify ne aggiunge sempre), l'attributo HTML si chiude prematuramente:

```html
<button onclick="...deleteQuoteFromList(123, "Q-2026-001");">  ← rotto
```

Memoria `feedback_no_jsonstringify_in_onclick.md` mi aveva avvertito di questo antipattern. Pattern corretto in altri 3 file del progetto: `.replace(/"/g, '&quot;')` su `JSON.stringify(...)`.

Fix: passo solo `id` come argomento, recupero label dai dati locali (`_quotesIndex` in quotes.html, `trashData[type].find()` in admin_trash.html). Pattern più robusto che non richiede escape.

## v3.5.0-alpha.7 — Cestino quote (Slice 1+2+3) (3 maggio 2026)

Soft-delete framework + cestino UI per le quotazioni. Risolve il caso "Non posso più eliminare i preventivi" (l'endpoint DELETE intera quote non era mai esistito).

**Decisioni di design** (concordate con Matteo):
- Quotazione attiva con booking → HARD-BLOCK delete; serve cancellare prima i booking.
- Solo admin con permesso nuovo `purge_total` può fare "Pulizia totale": hard-delete cascade su Quote + Job + JobCostLine + Booking + assignments. Bypassa il cestino, irreversibile.
- Soft-delete normale → record nel cestino (`deleted_at IS NOT NULL`), ripristinabile da chi ha `restore_trash`.

**Backend**
- `app/services/soft_delete.py` nuovo: framework generico, registra event listener SQLAlchemy `do_orm_execute` con `with_loader_criteria` per filtrare automaticamente `deleted_at IS NULL` su tutte le SELECT (bypass via `execution_options(include_deleted=True)`). Service `soft_delete_quote(force)` con regole HARD-BLOCK + cascade. `restore_quote()`. Eccezione tipata `DeleteBlocked` per il 409 strutturato.
- `Quote` model: aggiunti `deleted_at`, `deleted_by_user_id` (auto-migrate idempotente).
- `app/routers/quotes.py`:
  - `DELETE /api/{quote_id}?force=false|true` → 200 (soft) | 409 con `{detail, blocking, can_force}`. Permesso `delete_quotes`. `force=true` richiede `purge_total`.
  - `POST /api/{quote_id}/restore` → ripristina dal cestino. Permesso `restore_trash`.
- `app/routers/admin.py`:
  - `GET /admin/cestino` (HTML page) — permesso `view_trash`.
  - `GET /admin/api/trash` — lista record nel cestino con metadata + count "danno collaterale".
  - `POST /admin/api/trash/{type}/{id}/restore` — ripristina.
  - `DELETE /admin/api/trash/{type}/{id}` — purge definitivo (perm `purge_total`).

**RBAC nuovi permessi** (categoria "Cestino / Pulizia"):
- `delete_quotes` → admin/manager/producer/accounting
- `view_trash` → admin/manager
- `restore_trash` → admin/manager
- `purge_total` → SOLO admin

**UI**
- `/quotes` lista: bottone 🗑 per riga (soft-delete con dialog di conferma).
- Editor quote: bottone "🗑 Elimina" in topbar accanto a Duplica/Versione.
- Su 409 con `can_force=true` (admin): secondo dialog "Pulizia totale" con conferma esplicita IRREVERSIBILE.
- Su 409 con `can_force=false`: alert con elenco booking ostativi e suggerimento.
- `/admin/cestino` nuovo: tabs per entity-type (per ora solo Quote), card con metadata + bottoni "↩ Ripristina" e "🗑 Elimina definitivamente".
- Sidebar: voce "🗑 Cestino" sotto Amministrazione, solo per chi ha `view_trash`.

**Smoke test eseguito**: soft-delete + filter automatico verde (quote scompare con filter ON, visibile con `execution_options(include_deleted=True)`, restore la rimette). HARD-BLOCK testato con `_collect_blocking_bookings`.

**Cosa rimane** (slice successive):
- Slice 4: estendere il pattern a `Project` (con regole simmetriche: blocco se ha quote attive, pulizia totale admin per tutto il progetto).
- Slice 5: setting `trash_retention_days` + purge automatico al boot.

## v3.5.0-alpha.6 — Hotfix: tool_use orphans + sanitizer difensivo (3 maggio 2026)

Errore Anthropic 400 emerso al test Gomorra:
> messages.4: tool_use ids were found without tool_result blocks immediately after: toolu_011Ud34A...

**Causa**: Anthropic richiede strict che ogni `tool_use` in un assistant message sia seguito da un `tool_result` nel turno user successivo. Quando l'utente scriveva un nuovo messaggio MENTRE il loop era sospeso (con AIAction `proposed` non ancora applicate/rifiutate), il server appendeva un `user{role,content:text}` direttamente, lasciando i tool_use orfani.

**Fix**:

1. **`advance_loop` con pending non vuoti + nuovo user_message**: ora costruisce un user block misto `[tool_result × N, text]`. Le AIAction pending vengono marcate `rejected` con `result.abandoned=True, reason="user_changed_direction"` (helper nuova `_abandon_pending`).

2. **Sanitizer difensivo `_sanitize_messages`**: chiamato prima di ogni `provider.chat_with_tools()`, ripara la storia messages se trova assistant blocks con tool_use non seguiti da tool_result. Strategie:
   - Next è user → fonde `tool_result` placeholder all'inizio del content (no due user consecutivi)
   - Next è assistant o end → inserisce un user block dedicato
   - Placeholder content = `{"status": "context_lost"}` con `is_error: true`
   Permette il recupero anche delle conversazioni già "avvelenate" da bug precedenti.

3. Smoke test 3 scenari (string user, no repair, next assistant) tutti verdi.

## v3.5.0-alpha.5 — Riordino delle sezioni della sidebar (3 maggio 2026)

`/settings#sidebar` ora consente di spostare anche i blocchi-sezione (es. mettere "Operativo" sopra "Anagrafica"), oltre al riordino delle voci dentro ciascuna sezione che esisteva già.

**Cambiamenti**:
- `app/static/js/global.js` `applySidebarOrder()`: ora ha due step. (1) Legge `mf_sidebar_section_order` (lista nomi sezione) e riordina i `.nav-section` dentro `.sidebar-nav`; sezioni nuove non in lista restano in coda nell'ordine sorgente di `base.html`. (2) Riordino voci per sezione come prima (`mf_sidebar_order` invariato, retrocompat completa).
- `app/templates/pages/settings.html`:
  - Pannello "Ordine sidebar" rinominato (era "Ordine voci sidebar").
  - Maniglia ⠿ aggiunta sull'header di ogni blocco sezione.
  - Secondo Sortable applicato al container `nav-reorder-list` (handle: `.section-handle`) → drag delle sezioni.
  - I Sortable interni delle voci ora usano `handle: '.handle'` esplicito così la maniglia sezione non li attiva per errore.
  - `persistSidebarSectionOrder()` nuovo: salva l'ordine sezioni e re-applica subito.
  - `resetSidebarOrder()` ora pulisce ENTRAMBE le chiavi e ricarica la pagina (modo affidabile per ricostruire l'ordine default sezioni server-side).
  - CSS: section-handle visibile con cursor grab + hover bg, blocchi sezione con bordo dashed in hover.
- Cache-buster `global.js` bumpato a `3.5.0-alpha.5`.

Niente migrazione DB. Le preferenze restano client-side in `localStorage` come tutte le altre customizzazioni di look.

## v3.5.0-alpha.4 — propose_quote.lines con price_item_id (3 maggio 2026)

`propose_quote` ora accetta `price_item_id` per ogni riga in `lines`, eredità completa dal listino come già faceva `propose_quote_line`. Sblocca il flusso "voci nuove + quote nuova":
1. AI propone `propose_price_item` per ogni voce mancante (una alla volta, Apply utente)
2. Tool result restituisce il `price_item_id` di ciascuna voce
3. AI propone `propose_quote` con `lines: [{price_item_id: N, quantity: K}, ...]` per tutte le righe — incluse sia voci esistenti dal context "VOCI LISTINO ATTIVE" sia voci appena create.

Cambiamenti:
- `ai_tools.py`: schema `propose_quote.lines.items` ha ora `price_item_id` (integer opzionale). Required ridotto a `["quantity"]`: con `price_item_id` valorizzato, description/unit/unit_price si ereditano dal listino come in `propose_quote_line`.
- `ai_assistant._h_propose_quote`: risolve `price_item_id` per riga, eredità da `pi.name`/`pi.unit`/`pi.price_list`, salva `QuoteLine.price_item_id`.
- System prompt rinforzato: "Per ogni riga, usa `price_item_id` se la voce è in listino — qty basta, gli altri campi vengono ereditati."
- Aggiornato anche legacy markdown action prompt (path Ollama/Perplexity) per coerenza schema.

Mantiene invariante v3.4.55: le righe quote restano legate al listino (non più orfane), così cost report e man-hours funzionano correttamente.

## v3.5.0-alpha.3 — Hotfix: errore vero visibile su Apply fallito + ordine azioni AI (3 maggio 2026)

Due fix dopo test reale Matteo (conversazione Gomorra):

**1) "Errore sconosciuto" mascherava il vero errore**
- L'AI proponeva `propose_new_item_and_line` per voce listino + riga in nuova quote, ma la quote per Gomorra non esisteva ancora → handler sollevava `ValueError("Quote non trovata (quote_id=None, quote_number=None)")`.
- Il vero errore era salvato in `AIAction.result`, ma il frontend lo mostrava come "Errore sconosciuto".
- Causa: il router `/apply` rispondeva HTTP 400 con body `{"error": ...}`, ma `api()` helper in `global.js` cerca `err.detail` (convenzione FastAPI). Default fallback "Errore sconosciuto".
- Fix: il router ora ritorna sempre 200 OK con envelope `{ok, error?, result?, continuation}`. Un Apply fallito è un risultato applicativo, non un errore HTTP. Il frontend `copilotApply` controlla `res.ok === false` e mostra `res.error` reale.

**2) System prompt: ordine delle azioni quando la quote non esiste**
- Aggiunta sezione "Ordine delle azioni quando si lavora su una quote nuova":
  (a) `propose_price_item` per voci listino mancanti, una alla volta, attendendo Apply
  (b) `propose_quote` con `lines` inline (incluse voci nuove appena create, di cui ora si conosce `price_item_id`)
  (c) `propose_quote_line` solo dopo che la quote esiste
- Esplicitato il divieto: NON proporre `propose_new_item_and_line` se la quote non esiste, perché fallisce sul `_resolve_quote`.

Cache-buster bumpato a `3.5.0-alpha.3`.

## v3.5.0-alpha.2 — Hotfix: persistenza storia conversazione fra turni (3 maggio 2026)

Bug critico in v3.5.0-alpha.1 emerso al primo test reale (Matteo, conversazione su quote Gomorra):

**Sintomo**: turno 1 il copilot risponde con tabella matching listino + 5 domande. Turno 2 l'utente risponde "1. ... 2. ... 3. OK 4. ... 5. ...". Turno 3 il copilot dice "Non ho conversazioni precedenti da cui recuperare il contesto — questa è la prima interazione della sessione".

**Causa**: `ai_loop._save_state(conv, None)` veniva chiamato a ogni `end_turn` e azzerava completamente il `tool_state`, perdendo la storia messages. Il prossimo turno il modello vedeva solo l'ultimo user message senza il contesto.

**Errore di design mio**: avevo conflato due concetti distinti:
- "loop tool_use sospeso vs concluso" (= presenza di pending_results)
- "storia conversazione presente vs assente" (= esistenza dello stato)

**Fix**: `tool_state` ora resta sempre popolato con la storia messages canonica. Il flag "loop sospeso in attesa di Apply" è la presenza di `pending_results` non vuoti. Lo stato si svuota solo quando l'utente apre una nuova conversazione (nuova row AIConversation).

- Modificato `_save_state(conv, state: dict)`: non accetta più None, salva sempre.
- Tutti i 4 punti di "loop concluso" in `advance_loop` ora salvano `{messages, pending_results: []}` invece di None.
- `resume_after_action` con stato incoerente conserva la storia, non la cancella.

Niente migrazione DB. `tool_state` esistenti vecchio formato sono backward-compatible (chiavi mancanti default a vuote in `_load_state`).

## v3.5.0-alpha.1 — AI tool-use nativo (Anthropic) — Slice 1 foundation (3 maggio 2026)

Avviato il refactor strutturale del copilot da blocchi markdown ```action``` a tool-use nativo dei provider AI. Cantiere "feedback non torna al modello": dopo che l'utente clicca Applica su una proposta, il risultato (ad es. i risultati di Tavily, l'`id` di un cliente creato) deve rientrare nella conversazione perché il modello possa proseguire — cosa che il vecchio path non faceva (Slice 1 risolve esattamente questo).

**Decisione architetturale (Matteo, 3 mag 2026)**:
1. Provider in v1: Anthropic + OpenAI + Gemini (tool-use nativo). Ollama + Perplexity restano sul path legacy `action` markdown.
2. Tool readonly per DB (lookup_clients, lookup_pricelist, lookup_projects) — Slice 5.
3. Streaming risposte — Slice 6.

**Slice 1 (questo bump)**: Foundation Anthropic — il loop completo end-to-end con il solo provider Claude.

**Backend**
- `app/services/ai_tools.py` nuovo: registry centralizzato delle 9 capability AI con JSON Schema canonico (formato Anthropic), categoria `readonly` vs `mutation`, e converter per OpenAI / Gemini. Nuovo system prompt slim `ASSISTANT_SYSTEM_PROMPT_TOOLS` (no schema action inline — lo fanno i tool descriptors).
- `app/services/ai_provider.py`: nuova astrazione `AIProvider.chat_with_tools(messages, system, tools) → ToolUseResponse` (text + tool_uses + stop_reason + raw_assistant_message). `supports_tools()` dichiara la capability. `ClaudeProvider` la implementa via Anthropic Messages API tool_use; gli altri provider la sollevano `NotImplementedError` per ora.
- `app/services/ai_loop.py` nuovo:
  - `advance_loop(db, conv, provider, system, user_message)`: itera fino a end_turn o mutation. Tool readonly eseguite inline e tool_result re-injectato nel modello. Tool mutation salvate come `AIAction` e loop sospeso.
  - `resume_after_action(db, conv, provider, system, action)`: chiamato dal /apply o /reject; sostituisce il placeholder tool_result della mutation con il risultato vero, e se tutte le mutation della batch sono state gestite, riprende il loop.
  - Cap di sicurezza `MAX_LOOP_ITERATIONS = 10`.
- `app/routers/ai.py`:
  - `POST /api/chat` ora dirotta al loop tool-use se `provider.supports_tools()` (Claude). Altrimenti fallback al path legacy `chat_with_assistant` (Ollama/Perplexity/Gemini/OpenAI per ora — questi ultimi due passano al tool-use in Slice 4).
  - `POST /api/actions/{id}/apply` e `/reject` ritornano una `continuation` (`{text, actions, done, still_pending}`) costruita riprendendo il loop dopo l'azione utente. UI la mostra come bubble assistant aggiuntiva.
- `app/services/ai_assistant.py`: nuovo helper `build_system_prompt(use_tools=…)` per condividere la logica del contesto fra i due path.

**Modelli**
- `AIConversation.tool_state` (Text, nullable): JSON con la storia messages canonica + i tool_result pending. Persistito SOLO mentre il loop è sospeso in attesa di Apply utente.
- `AIAction.tool_use_id` (String, nullable): id del tool_use Anthropic/OpenAI/Gemini, necessario per costruire il tool_result corretto al resume.
- Auto-migrate al boot in `_auto_migrate_columns()` (idempotente).

**Frontend**
- `app/static/js/copilot.js`: `copilotApply` e `copilotReject` ora gestiscono `res.continuation` mostrandola come nuova bubble assistant (testo + eventuali nuove card mutation).
- Cache-buster bumpato a `3.5.0-alpha.1`.

**Cosa funziona ora**: con un provider Claude attivo (Anthropic API key in `/settings#ai`), il caso "aggiungi cliente Cattleya, cerca info online" deve girare end-to-end:
1. user → Claude
2. Claude `tool_use(web_search, query='Cattleya …')` → loop esegue Tavily inline → `tool_result` rientra nel modello
3. Claude legge i risultati → `tool_use(propose_client, name='Cattleya', vat_number='IT07330331004', …)` → loop ferma, UI mostra card di conferma popolata
4. user clicca Applica → backend crea il cliente → continuation con eventuale testo di chiusura di Claude

**Cosa NON funziona ancora** (slice successive):
- OpenAI e Gemini ancora sul path legacy markdown (Slice 4).
- Tool readonly per DB lookup (Slice 5).
- Streaming (Slice 6).
- Cleanup definitivo del path legacy (Slice 7, opzionale).

## v3.4.56 — Conferma assegnazione risorse + warning quote approved senza risorse + workflow docs (3 maggio 2026)

Completati i due TODO non risolti in v3.4.55 + 3 documenti di mappatura processi.

**1) Pre-save confirm per risorse non ancora assegnate** (booking modal)
- Nuovo endpoint `GET /planning/api/jobs/{job_id}/resource-coverage?resource_ids=1,2` ritorna `{covered, missing}`.
- `tlbSubmit`: dopo aver risolto `job_id` (forward o reverse), se ci sono `missing` mostra `confirm()` con elenco "le seguenti risorse non sono ancora assegnate al progetto e verranno aggiunte automaticamente". Cancel → abort save.
- L'auto-assignment server-side (v3.4.55 hook in POST booking) è confermato; il client aggiunge solo lo step di conferma esplicita richiesto da Matteo.

**2) Notifica `quote_approved_no_resources` (non bloccante)**
- Nuovo `NotificationKind.quote_approved_no_resources`.
- Hook in `PUT /quotes/api/{id}/status` quando `status → approved`: dopo `_create_job_from_quote`, se il job ha 0 `JobResourceAssignment`, notify a chi ha permesso `assign_resources` (admin/manager/producer) con severity `action_required`.
- Body: "Quote {N} approvata, ma nessuna risorsa assegnata al progetto. Aggiungile manualmente in /projects/{id} oppure scattano in automatico al primo booking (con richiesta di conferma)."
- Non bloccante: la quote è approvata regolarmente, è solo un alert.

**3) Workflow docs** (`docs/workflow.md`, `docs/data-model.md`, `docs/permissions-matrix.md`)
- `workflow.md`: 5 diagrammi Mermaid (state Quote, state Booking, flow Booking→Job forward+reverse+phantom, fonti Maturato cost report, vincoli HARD-BLOCK)
- `data-model.md`: erDiagram entità chiave + classDiagram con flag/stati + tabella decisioni architetturali fissate
- `permissions-matrix.md`: matrice permesso × ruolo built-in (per ogni categoria) + tabella permessi gate-keeper per azioni critiche
- Mermaid renderizza nativamente in GitHub. Per export: `npx -p @mermaid-js/mermaid-cli mmdc`.
- Non sono "fonte di verità", sono snapshot del codice. La fonte resta `app/services/rbac.py` + `app/models/models.py`.

Niente migrazione DB. Cache-buster bumpato a `3.4.56`.

## v3.4.55 — Fix sistemico: integrità Quote↔JobCostLine↔Booking, vista lavorazione read-only, auto-assignment risorse, allineamento man-hours (3 maggio 2026)

Cambio strutturale dopo 5 problemi gravi segnalati da Matteo:

**1) DELETE QuoteLine/JobCostLine con booking attivi → HARD-BLOCK (no più soft-detach)**
Bug paradossale: cancellando una voce di quotazione, il sistema (v3.4.36) faceva soft-detach `Booking.job_cost_line_id → NULL`, lasciando booking orfani senza lavorazione. Risultato: cost report vuoto pur essendoci booking nel planning. Ora:
- `DELETE /quotes/api/{id}/lines/{line_id}` rifiuta con HTTP 409 se ci sono booking attivi (status != cancelled). Elenco booking ostativi nel messaggio.
- `DELETE /jobs/api/{job_id}/cost-lines/{line_id}` stessa policy. Soft-detach abolito.
- Modifica resta consentita (la riga si può sempre rinominare/correggere). Solo eliminazione bloccata.
- TimePunch (HR, separato): soft-detach OK perché non impatta cost report.

**2) Vista lavorazione read-only (`modal-line-detail`)**
Editor che cliccava su una riga si trovava modal di edit con prezzi/ore lavorate modificabili (sballava cost report). Ora click → modal informativo con:
- KPI Quotato vs Maturato (entrambi con qty × unit_price = total)
- Origine quote line (descrizione, posizione, link)
- Risorse coinvolte dedotte dai booking
- Booking attivi (ID, data, status execution, risorse + durata per assignment)
- Bottone "Modifica" appare in footer SOLO se `view_finance`. Altrimenti solo Chiudi.
- Endpoint nuovo `GET /jobs/api/{job_id}/cost-lines/{line_id}/detail`.

**3) Auto-assignment Resource → Job al booking save**
Bookings creavano linkati al job ma le risorse non finivano in `JobResourceAssignment` → impossibile generare report ore-per-risorsa-su-progetto. Ora:
- Service nuovo `app/services/resource_assignment_sync.py` con `ensure_resources_assigned_to_job()` (idempotente, eredita role/rate da `Resource`).
- Hook in `POST /planning/api/bookings` (sia singolo che ricorrente): dopo creazione booking, garantisce assignment per tutte le risorse coinvolte se il booking ha `job_id`.
- Reverse-flow + promote-line: il booking viene creato DOPO il promote, quindi l'hook copre anche quei casi (non serve duplicare).

**4) Allineamento giorni/ore (man-hours canonico)**
Bug subdolo: `cost_line_sync._booking_hours` usava shell-duration (start→end del booking), `reverse_quote.compute_quantity_from_hours` usava man-hours (somma assignments). Risultato: per booking multi-risorsa il maturato era sottostimato. Es. 2 colorist × 8h → reverse quotava 2 giornate, sync maturava 1 giornata → cost report sballato. Ora:
- `_booking_hours(b)` ritorna `sum(assignments durations)` (man-hours) coerente con il flusso reverse.
- Fallback a shell-duration solo se assignments non caricati.

**5) Vincolo ribadito** (già v3.4.54): editor non può modificare `quantity_actual`. Mantenuto.

### TODO non risolti in questa versione
- Notifica "quote approved senza risorse assegnate" al producer (warning attivo): rimandato (pattern complesso, vale la pena chiarire UX prima).
- Multi-risorsa shell-vs-man-hours: assunto man-hours come canonico — se Matteo vuole shell-hours per alcune voci (es. "una giornata di Color HDR" indipendente da quanti operatori), si aggiunge un flag `PriceItem.aggregate_hours_per_resource: bool` in futuro.

Niente migrazione DB. Cache-buster bumpato a `3.4.55`.

## v3.4.54 — Project filter nel booking + cost-line RBAC (no override maturato per editor) (3 maggio 2026)

Due fix critici emersi dal test di Matteo sulla v3.4.53:

**1) Project filter prima della Quote (modal booking)**: in caso di nomi quote ambigui o omonimie tra progetti, il producer non aveva modo di restringere l'ambito. Aggiunto un picker progetto **sopra** la quote (`tlb-project-search`/`tlb-project-id`). Il picker quote ora filtra `QUOTES_SEED` per `project_id` selezionato. Cambio progetto → reset automatico di quote+lavorazione se non appartiene al nuovo. Edit di booking esistente: pre-popola anche progetto da `/jobs/api/{id}.project`. Sub-modal phantom: pre-popola progetto coerente.

**2) Cost-line RBAC + lock del maturato manuale**: bug strutturale grave segnalato da Matteo — un utente editor (non finance) poteva aprire `/jobs/{id}` e modificare `quantity_actual` (ore lavorate) di una lavorazione, sballando il cost report (es. "100 ore conforming a 900€/h = €90.000 inventati nel maturato"). Il maturato deve **derivare dai booking marcati `done`** (cost_line_sync v3.4.41), non da input manuale. Override consentito solo a manager/accounting in fase di verifica.

Soluzione:
- Nuovo permesso `edit_cost_actuals` (preset admin/manager/accounting). **Producer e operator NO**.
- `POST/PUT/DELETE /jobs/api/{id}/cost-lines[/{line_id}]` ora gate su `view_finance` (era pubblico). 403 per chi non ha il permesso.
- `PUT cost-lines`: se passato `quantity_actual`, gate aggiuntivo su `edit_cost_actuals` con messaggio esplicito ("default deriva dai booking done").
- Frontend `/jobs/{id}`:
  - Bottone "+ Aggiungi lavorazione extra" nascosto a non-finance
  - Click su riga lavorazione → modal aperto solo se `view_finance`, altrimenti toast "permesso negato"
  - Modal edit: `quantity_actual` input `disabled` se non `edit_cost_actuals`, badge "(read-only — deriva dai booking ✓)" + helper text spiegativo
  - `saveLine()` non invia `quantity_actual` se l'utente non ha permesso (evita 403 che perderebbe le altre modifiche)
- `Jinja globals`: aggiunto `can_edit_cost_actuals` accessibile dai template

Niente migrazione DB. Cache-buster bumpato a `3.4.54`.

## v3.4.53 — Booking parla quote+lavorazione (Job nascosto), filtro reparto risorse (3 maggio 2026)

UX critica del modal booking ricostruita su feedback Matteo: "non voglio scegliere il job, voglio scegliere la quotazione e la lavorazione filtrata per reparto delle risorse". Il Job resta nel DB come puntatore interno, ma sparisce dall'UI booking.

**Cambio campo `tlb-job-search`**: ora autocompleta sulle Quote (status `draft|sent|approved`), non più sui Job. La label diventa "Quotazione". Badge stato colorato (approved verde / sent giallo / draft indigo) + badge PHANTOM. Il `tlb-job-id` hidden ora contiene `quote_id` (semantica cambiata).

**Lavorazione obbligatoria** per `kind=project` (era opzionale). Filtrata per dipartimento delle risorse selezionate: ogni risorsa ha `Resource.department_id`, ogni voce di listino ha `PriceItem.department_id`. Il dropdown ricarica automaticamente al cambio risorse (hook su `tlbAssOnChange`).

**Backend**:
- `GET /quotes/api/{quote_id}/booking-lines?dept_ids=1,2` — ritorna lavorazioni della quote filtrate per reparto. Per quote `approved`: `JobCostLine` (kind=cost_line). Per `draft|sent`: `QuoteLine` (kind=quote_line). Linee senza price_item.department_id sono sempre incluse (voci generiche).
- `POST /quotes/api/{quote_id}/promote-line-to-cost-line` — al volo: approva implicitamente quote `draft|sent` + ensure Job (forward standard) + crea JobCostLine corrispondente alla QuoteLine. Idempotente. Notifica account managers (`edit_quotes`).
- `planning.py`: query nuova `quotes` (status in draft|sent|approved) passata al template.

**Flusso save booking** (`tlbSubmit`):
1. Valida quote + lavorazione obbligatorie
2. Se `lineKind=quote_line` → POST promote → ottiene `cost_line_id` + `job_id`
3. Se `lineKind=cost_line` → legge `job_id` dal context cached
4. POST `/planning/api/bookings` con `job_id` + `job_cost_line_id` (invariato dal backend booking)

**UI** in `/planning`:
- Field "Job" → "Quotazione" con autocomplete QUOTES_SEED
- Field "Lavorazione" obbligatoria, opzioni `descrizione · Reparto [extra]`
- Meta sotto la lavorazione: "N lavorazioni disponibili (filtrate per reparto risorse)" oppure warning "⚠ Quote in stato draft: salvando il booking, verrà approvata implicitamente"
- Cambio risorse → ricarica lavorazioni con nuovo filtro reparto
- CTA "+ Genera **phantom quote** da questo booking" (già da v3.4.52) — ora più chiara per il caso "progetto senza quote"
- Sub-modal phantom (v3.4.52) auto-pusha la nuova quote in QUOTES_SEED + auto-seleziona

Caso d'uso: progetto in emergenza con quote in trattativa (draft/sent) → producer pianifica i booking → ogni booking attacca una linea alla quote esistente con approvazione implicita → l'account manager riceve notifica `quote_reverse_approval` per coordinare la trattativa.

Niente migrazione DB. Cache-buster bumpato a `3.4.53`.

## v3.4.52 — Reverse-flow v2: booking → QuoteLine + approvazione implicita / phantom quote (3 maggio 2026)

Riformulazione completa del reverse-flow di v3.4.51 dopo discussione con Matteo. Il flusso "extra job + JobCostLine manuale" è scartato: il **driver canonico è la Quote**, non il Job. Niente più qty/unit/prezzo da digitare a mano: tutto deriva dalla durata del booking + voce listino.

**Modello concettuale (definitivo)**:
- **Forward (canonica)**: `Quote.approved → Job` (esistente)
- **Reverse (eccezione, v3.4.52)**: booking su progetto senza quote attiva → modal blocking → due strade:
  - **`attach_existing`**: esiste una quote in `draft|sent` → si aggiunge la riga, la quote viene **approvata implicitamente**, il Job viene auto-creato col flusso forward standard, **gli account manager** (`edit_quotes`) ricevono notifica `quote_reverse_approval` (severity `action_required`) per attivare eventualmente migrate-job/versioning standard.
  - **`create_phantom`**: nessuna quote esiste → si crea una `Quote(is_phantom=True, status=approved)` con la nuova riga, il Job viene auto-creato. Phantom = mai inviata al cliente, visibile in `/finance` come anomalia, promuovibile a quote di riferimento (toggle `is_phantom=False`).

**Modello DB**:
- `Quote.is_phantom: Boolean default False` — auto-migrate al boot (`ALTER TABLE quotes ADD COLUMN is_phantom`).
- `NotificationKind.quote_reverse_approval` — nuovo kind per gli alert agli account manager.

**Backend**:
- `app/services/reverse_quote.py` — `compute_quantity_from_hours(hours, unit)` (8h/giorno per `day`, 1:1 per `hour`, 1.0 altrimenti), `add_line_from_price_item`, `attach_to_pending_quote` (transazione: add line → approve → ensure Job → notify), `create_phantom_quote_with_line` (crea Quote phantom + line + Job + notify).
- `POST /quotes/api/reverse-attach` — accetta `mode=attach_existing|create_phantom`, `target_quote_id`, `price_item_id`, `booking_hours`, `quantity_override` opzionale, `phantom_title` opzionale. Riusa `_create_job_from_quote` (forward standard) per la promozione a Job.
- `GET /projects/api/{id}/job-context` esteso: ritorna `approved_quotes`, `pending_quotes`, `phantom_quotes`, `jobs_with_quote`, `jobs_without_quote`, `suggested_flow` per guidare il client.

**UI** in `/planning` modal booking:
- CTA arancione "+ Genera **quote+job** da questo booking (progetto senza quote attiva)…" sempre in fondo a `tlb-job-suggestions`
- Nuovo sub-modal `modal-tlb-reverse-quote` (rinominato da `modal-tlb-extra-job`):
  - Project select → caricamento context con badge: "✓ interno", "⚠ N quote APPROVATE — usa autocomplete", "N pending attaccabili", "N phantom esistenti", "Nessuna quote — verrà creata phantom"
  - Radio `attach_existing` (disabilitata se nessuna pending) / `create_phantom` (default se no pending)
  - Picker quote pending / titolo phantom in base alla scelta
  - Listino voce (autocomplete con cache lazy `/pricelist/api/items`)
  - **Anteprima riga**: `qty unit × € price = € total` derivata da `booking_hours` (somma assignments correnti) + `price_item.unit`
- Salva → reverse-attach endpoint → push del nuovo job in `JOBS_SEED` → auto-select job + cost line nel modal booking principale → utente clicca Salva del booking normale

**Removed**:
- `app/services/job_extras.py` (defunto: il modello "extra job senza quote" è scartato)
- `POST /jobs/api/reverse-extra` (sostituito da `/quotes/api/reverse-attach`)

Cache-buster bumpato a `3.4.52`. Auto-migrate `quotes.is_phantom` al boot, no script manuale richiesto.

## v3.4.51 — Reverse-flow: job extra da booking su progetto senza quote (3 maggio 2026)

Cambio architetturale richiesto da Matteo dopo audit del job orfano "Spot istituzionale Sky" con `budget_quoted=18000` arbitrario nel seed.

**Principio fissato**: un Job non nasce mai dal nulla con un valore commerciale arbitrario. Solo due genesi legittime:
- **Forward (canonica)**: Quote.approved → Job auto-creato, `budget_quoted` = totale quote, `JobCostLine` da `QuoteLine`
- **Reverse (eccezione)**: booking su progetto senza quote → modal blocking → utente sceglie "Nuovo job extra" o "Aggiungi al job extra esistente" + voce listino + qty/prezzo. Job nasce con `budget_quoted=0`; ogni `JobCostLine(is_extra=True)` ricalcola `budget_quoted = sum(extras.total_expected)`. Job appare in `/finance > Anomalie > Job orfani` finché non viene gestito.

Casi d'uso target: progetti interni di manutenzione/test/R&D, lavorazioni straordinarie su progetti normalmente non quotati (es. sale-rooms ricorrenti con job per "manutenzione ordinaria mese N" + job a parte per "manutenzione straordinaria").

**Cosa è stato aggiunto**:
- `app/services/job_extras.py` — helpers `next_job_code`, `recompute_budget_from_extras`, `create_extra_job_for_project`, `add_extra_cost_line`, `hydrate_from_price_item`. `recompute_budget_from_extras` è no-op se il job ha `quote_id` (intoccabile per job quote-driven).
- `GET /projects/api/{id}/job-context` — ritorna `has_active_quote`, `is_internal`, `extra_jobs`, `quoted_jobs`. Usato dal client per popolare il sub-modal.
- `POST /jobs/api/reverse-extra` — accetta `mode=new|existing`, crea/riusa Job + JobCostLine extra in singola transazione. `mode=existing` richiede che il job target sia reverse-flow (no `quote_id`); altrimenti errore esplicito ("usa l'editor della quote").
- `ProjectType` "Interno (test/manutenzione/R&D) — niente quote" come label esplicita nel form `/projects` + filter. Resta una convenzione (qualsiasi progetto senza quote può accedere al reverse-flow), il tipo `internal` serve solo a etichettare.

**UI** in `/planning` modal booking:
- CTA persistente "+ Crea **job extra** (progetto senza quotazione)…" sempre in fondo a `tlb-job-suggestions` (anche se ci sono già match)
- Sub-modal `modal-tlb-extra-job` con form: progetto + modalità (new/existing) + titolo job + voce listino (autocomplete con cache `_exjPriceItems` lazy-loaded da `/pricelist/api/items`) + qty + unità + prezzo + note
- Warning arancione automatico se il progetto scelto ha quote attive ("usa l'editor della quote piuttosto")
- Disabilita radio "existing" se il progetto non ha già job extra
- Salva → push del nuovo job in `JOBS_SEED` (senza reload pagina) + auto-seleziona job + cost line nel modal booking principale

**Bonifica seed** (`scripts/seed_demo.py`):
- Rimosso Job 2024-0042 "Spot istituzionale Sky" con `budget_quoted=18000` arbitrario. Il progetto Sky resta deliberatamente senza Job per testare il reverse-flow.
- `print` finale aggiornato: "1 quotazione approvata, 1 job (Mare Nostrum)".

Cache-buster bumpato a `3.4.51`. Niente migrazione DB necessaria (no nuove colonne).

## v3.4.50.3 — Elimina progetto (solo se senza quotazioni) (2 maggio 2026)

Tasto 🗑 nella riga progetto in `/projects` (colonna azioni, accanto a "Apri →"). Visibile solo a chi ha `can_view_finance` (admin/manager/producer/accounting).

Stato del bottone deciso lato client da `quotes_count`:
- `0 quote` → bottone attivo rosso, conferma + DELETE
- `>0 quote` → bottone disabilitato grigio con tooltip "Non eliminabile: N quotazioni collegate"

Backend `DELETE /projects/api/{id}` rinforzato:
- Permesso negato se non `can_view_finance` (era pubblico)
- Block se `p.quotes` con messaggio chiaro (era solo `p.jobs`)
- Block conservato anche su `p.jobs` come safety net (un progetto senza quote non può avere job, ma se la catena è incoerente per qualche motivo blocchiamo lo stesso)

Pattern `data-pid` + `data-plabel` invece di interpolazione complessa nell'`onclick` (memory `feedback_no_jsonstringify_in_onclick.md`). Cache-buster bumpato a `3.4.50.3`.

## v3.4.50.2 — Modal scrollabile con header/footer fissi (2 maggio 2026)

Fix UX globale: i modal (es. dettaglio cliente con molti campi) ora si capano all'altezza viewport (`max-height: calc(100vh - 40px)`), header e footer restano fissi e visibili, body scorre internamente (`overflow-y: auto`). Risolve l'issue Matteo "le schede clienti non si aprono completamente" su schermi piccoli o quando la scheda è molto piena (anagrafica + dati fiscali + sede + referente + note + filmografia + progetti collegati + fonti AI). Approccio generico: vale per tutti i modal del progetto, niente toppe per-pagina.

## v3.4.50.1 — Audit pre-push: 3 micro-fix (2 maggio 2026)

Bug fix emersi durante audit completo prima del push:

1. **`seed_demo.py` tenant idempotente** — il seed prova a inserire `Tenant(id=1)` con violazione UNIQUE se la tabella esiste già (caso post `reset_business_data` opzione [O]). Sostituito con `db.query(Tenant).filter(id==1).first()` + insert solo se mancante.

2. **`seed_demo.py` Booking ↔ BookingAssignment** — il seed creava `Booking(resource_id=...)` ma da v3.4.16 i booking hanno solo l'envelope (`start/end`) e la risorsa è in `BookingAssignment`. Aggiornato `bk()` helper per creare entrambi.

3. **Numero versione quote `-v1-v2` duplicato** — `new_version_quote` concatenava `-v{N}` al `root.number` senza pulire eventuali suffissi `-vN` preesistenti. Aggiunto `re.sub(r"-v\d+$", "", root.number)` prima della concat. Risultato: `Q-P-2024-001-v1` → versione successiva = `Q-P-2024-001-v2` (non più `-v1-v2`).

## v3.4.50 — Resource presets + sync orario tra risorse (2 maggio 2026)

Due quick-win UX nel modal multi-risorsa booking timeline.

### Resource presets (selezioni multiple ricorrenti)

Nuovo modello `ResourcePreset(id, tenant_id, name, description, resource_ids JSON, created_by, created_at)`. Tabella creata automaticamente al boot via `Base.metadata.create_all()`.

API CRUD:
- `GET /planning/api/resource-presets` — lista (include `valid_count` per evidenziare risorse non più attive)
- `POST /planning/api/resource-presets` — crea (RBAC: tutti gli autenticati)
- `PUT /planning/api/resource-presets/{id}` — modifica (creatore o admin/manager)
- `DELETE /planning/api/resource-presets/{id}` — elimina (creatore o admin/manager)

UI nel modal "Nuovo/Edit booking":
- Dropdown "📁 Carica preset…" con nome + counter risorse + warning ⚠ se preset contiene risorse non più attive
- Bottone "💾 Salva preset" (chiede nome via prompt)
- Apply: aggiunge le risorse del preset alle righe esistenti, riempie le righe vuote prima di crearne di nuove, evita duplicati. Eredita start/end dalla prima riga corrente.

### Sync orario tra risorse

Spunta `🔗 Stesso orario per tutte le risorse` sopra le righe assignment. Quando ON:
- Cambio start/end della 1ª riga → propaga alle altre (data + ora)
- Toggle ON con righe già presenti → allineamento immediato + toast info
- Preferenza salvata in `localStorage` (`mf_tlb_sync_times`), ricaricata all'apertura del modal

---

## v3.4.49 — Reset business data script (2 maggio 2026)

Nuovo script `scripts/reset_business_data.py` per ripartire con setup pulito mantenendo solo dati di configurazione.

### Cancella

clienti, progetti, quotazioni (+ righe), job (+ cost lines + assegnazioni), booking (+ assignments + audit log), risorse (+ ferie/malattia), timbrature, timesheet, fatture (+ righe), asset (+ tag), notifiche, conversazioni AI (+ messaggi), AI actions, project tech sheets, expenses.

### Preserva

users, roles, tenants, departments, price_categories, price_items, delivery_templates, working_hours_policies, user_ai_settings, tags.

### Comportamento

- Idempotente, in transazione (rollback su errore)
- Reset `sqlite_sequence` per le tabelle pulite (ID ripartono da 1)
- Counter prima/dopo stampati a video
- Conferma esplicita richiesta da CLI (`--yes` / `-y` per skip su strumenti)
- Voce `[O]` su `strumenti.bat` e `strumenti.sh`
- Non rimuove le tabelle (solo le righe), nessuna migrazione necessaria

### Uso

```
./strumenti.sh → o
# oppure
python scripts/reset_business_data.py
```

---

## v3.4.48.2 — Look timeline: famiglia font + colore testo (2 maggio 2026)

Pannello ⚙ esteso con due nuovi controlli per coerenza visiva con bg/tema:

- **Famiglia font** — Auto (tema globale) / DM Sans / Inter / System UI / Serif / Monospace
- **Colore testo** — Auto (segue bg) / Bianco / Bianco soft / Ambra / Nero / Indigo

Apply via `data-font-family` e `data-text-color` su `#tl-host`, override su `.vis-item`, `.vis-labelset .vis-label`, `.vis-time-axis .vis-text`. Default "auto" = nessuna regola (eredita dal bg variant o dal tema globale).

## v3.4.48.1 — Hotfix colore sfondo timeline (2 maggio 2026)

Il `data-bg` su `#tl-host` non aveva effetto perché `.vis-timeline` (figlio diretto, libreria) ha background hardcoded `linear-gradient(...) + var(--bg-elev)` che sovrasta l'host. Spostato il selettore: `#tl-host[data-bg="..."] .vis-timeline { background: ... !important }`. Aggiunto reset trasparente su `.vis-panel/.vis-foreground/.vis-background` interni per evitare overlay residui. Variant "paper" (chiaro) ora inverte testo/grid/label per leggibilità.

## v3.4.48 — Look timeline tweaks: bg + 3D items + dept fix (2 maggio 2026)

### Pannello ⚙

- **Rimossa**: opzione "Densità" (poco utile in pratica, padding default ok)
- **Aggiunta**: opzione "Colore sfondo" con 7 preset:
  - Default (tema), Scuro, Molto scuro, Caldo (seppia), Freddo (notte), Verde foresta, Carta (chiaro)
  - Apply via `[data-bg="..."]` su `#tl-host`

### Items 3D

- Border-radius 7 → **9px** (spigoli più morbidi)
- Box-shadow multi-layer per effetto bevel:
  - `inset 0 1px 0 rgba(255,255,255,.22)` (highlight superiore)
  - `inset 0 -2px 3px rgba(0,0,0,.20)` (depth inferiore)
  - `0 1px 2px + 0 4px 10px` (drop close + ambient)
- Hover: shadow rinforzata + glow leggero
- Selected: stessi inset + ring bianco esterno

### Fix accent "Per reparto"

Prima il selettore CSS usava una `--dept-accent` non valorizzata → fallback indigo (visivamente identico al default). **Ora funziona davvero**:

- `Department.color` esposto in `DEPARTMENTS_SEED` (template + JS)
- `tlBuildGroups` aggiunge `className: 'tl-dept-{id}'` ai gruppi reparto
- `tlPrefsApply` genera CSS dinamico (`<style id="tl-prefs-dynamic">`) con una regola per ogni reparto:
  ```
  #tl-host[data-accent="dept"] .tl-dept-3.vis-nesting-group {
    background: linear-gradient(90deg, rgba(R,G,B,.25) 0%, rgba(R,G,B,.05) 70%, transparent);
    border-left-color: <color>;
    color: <color>; filter: brightness(1.25);
  }
  ```
- Helper `_hexToRgba(hex, alpha)` per derivare il wash semitrasparente.

---

## v3.4.47 — Filtri planning multi-select (2 maggio 2026)

I 4 filtri autocomplete della sidebar `/planning` (Cliente, Progetto, Job, Risorsa) ora sono multi-select via chip.

### UI

- Wrapper `.fa-multi` (chips inline + input ricerca al fondo, focus-within highlight indigo).
- Click su un risultato dell'autocomplete → aggiunge una `fa-chip` (background indigo, ✕ per rimuovere).
- Backspace su input vuoto rimuove l'ultimo chip.
- Risultati già selezionati non riappaiono nei suggerimenti.
- "Reset filtri" pulisce tutti i chips.

### Hidden value

`#f-{client,project,job,resource}` ora contiene comma-separated ids (es. `1,5,7`). `getFilterParams()` lo passa intatto al backend (stesso campo `client_id`/`project_id`/`job_id`/`resource_id`).

### Backend

Helper `_parse_id_list(value)` in `app/routers/planning.py` accetta `None`, `int`, stringa singola, comma-separated, o lista. Endpoint aggiornati:

- `GET /planning/api/jobs` — `client_id`, `project_id`, `department_id` multi
- `GET /planning/api/bookings` — `job_id`, `resource_id`, `client_id`, `project_id`, `department_id` multi
- `GET /planning/api/unavailabilities` — `resource_id` multi

Tutti applicano `IN(...)` quando comma-separated. Compatibile con single-id pre-multi (un solo valore funziona come prima). Type hints da `Optional[int]` a `Optional[str]`.

### Active filters bar

Quando un filtro multi ha N>1 selezioni, mostra `Cliente: 3 selezionati` invece del display singolo.

---

## v3.4.46 — Look timeline customization (preferenze locali) (2 maggio 2026)

Pannello ⚙ in topbar `/planning?view=timeline` per personalizzare il look senza toccare il tema globale. Settings persistite in `localStorage` (`mf_tl_prefs`), per-utente per-browser, immediate.

### Settings disponibili

- **Densità**: Compatta / Normale / Comoda → cambia padding e radius items (`data-density="..."` su `#tl-host`)
- **Font items**: 11 / 11.5 / 12 / 13 → override `font-size` via `<style id="tl-prefs-dynamic">` dinamico
- **Accent reparto**: Indigo (default) / Mono (grigio) / Per reparto (CSS variable `--dept-accent` riservato a estensione futura)
- **Storyboard density**: Compatta / Normale → cards più ridotte
- **Toggle**: Animazioni / Heatmap capacity / Linea oggi con glow / Sfondo weekend

### Come funziona

- `tlPrefsLoad()` legge `localStorage`, fallback a `TL_PREFS_DEFAULTS`.
- `tlPrefsApply(p)` setta `data-*` su `#tl-host` + inietta `<style id="tl-prefs-dynamic">` per override dinamici (font-size).
- CSS reactive con selettori `#tl-host[data-density="compact"] .vis-item { ... }` ecc.
- Auto-apply al load. Bottone ⚙ apre/chiude popover (chiusura su click esterno). Bottone "↺ Ripristina default" resetta.

Nessun cambio backend. Nessuna migrazione. Nessuna dipendenza nuova.

---

## v3.4.45.1 — Hotfix /planning 500 (`UserRole.code`) (2 maggio 2026)

`/planning/` e `/planning/api/project-bookings` rompevano con `AttributeError: 'UserRole' object has no attribute 'code'`. La detection del producer era stata scritta accedendo a `cur_user.role.code` ma `User.role` è l'enum legacy `UserRole` (non il modello `Role` configurabile, che vive su `User.role_obj`). Sostituito con `is_producer(user)` da `app.services.rbac` che usa correttamente `_resolve_role_code()` (priorità a `role_obj` se presente, fallback a enum). Stessa fix in entrambi i punti (`planning_hub` + `project_bookings`).

## v3.4.45 — Look timeline: deep restyle + Storyboard view (2 maggio 2026)

### C4a — Deep restyle vis-timeline

Pass mirato di CSS sul planning timeline (zero cambi logici):

- **Time axis**: gradient indigo accentuato, separatore inferiore, major label pill-style (color `#cdd5ff`, font-weight 700, letter-spacing 0.6px).
- **Items**: radius 5→7, padding 2/6→3/8, font-size 11→11.5 + weight 500, ombra più sostenuta, glow indigo su hover, transition curate.
- **Drag handles**: opacity 0 di base → 1 su hover (clean), gradient più contrastato.
- **Linea oggi**: color glow arancione + dot in cima.
- **Group nesting (reparto)**: gradient più scuro, border-left 3→4px, color `#c0c8ff` (più contrastato).
- **Heatmap capacity label**: container con radius + bg subtle, hover preview.
- **Weekend** evidenziato anche sul foreground (non solo nell'axis), `vis-today` con sfondo arancione lieve.

### C4b — Storyboard view

Nuova tab `🎬 Storyboard` in `/planning`. Vista settimanale a 7 colonne (Lun→Dom):

- Navigazione: `← Settimana` / `Oggi` / `Settimana →`.
- Ogni colonna giorno mostra header (giorno + numero) + totale ore + cards booking ordinate per ora.
- Card storyboard: time slot mono, titolo, voce, badge risorsa colorato. Stato esecuzione: bordo verde (done), arancione pulse (in_progress), tratteggiato rosso (not_done).
- Click card → modal `todoOpenDetail` (riusato).
- Header settimana con totale ore + counter booking. Filtri trasversali applicati (incluso `from`/`to` derivati dalla settimana).
- Responsive: 7 colonne ≥1100px, 4 colonne ≥720px, 1 colonna mobile.

`VALID_VIEWS` esteso con `'storyboard'` (sia template che router).

---

## v3.4.44 — Ore lavorate + drilldown + view per progetto (2 maggio 2026)

### #6 — Indicatori execution_status sui booking timeline

Ogni item booking della timeline planning ora ha indicatore visuale dello stato esecuzione:
- **planned**: standard
- **in_progress**: bordo arancione pulsante (animation `tl-pulse`)
- **done**: bordo verde + icona `✓` a destra dell'item, opacity ridotta
- **not_done**: pattern tratteggiato rosso, opacity 0.55

Tooltip arricchito con `· {execution_status}`. Le classi CSS `tl-exec-*` sono applicate via `tlBookingToItem`.

### #7a — Drilldown ore pianificate

Nella tabella `/planning?view=jobs` la cella ore (es. `5h / 80h`) è ora un link che apre un modal con la lista delle prenotazioni del job: data/ora, durata, voce, stato esecuzione, link al dettaglio booking.

Il modal riusa `modal-todo-detail` con titolo dinamico `📅 Prenotazioni job (N)`. Lista ordinata per `start`. Header con totale `done h / total h`.

### #7b — Vista "Per progetto" (manager+)

Nuova tab `📂 Per progetto` in `/planning` visibile solo a admin/manager/producer (o utenti con permesso `edit_planning`). Dropdown searchable progetti → mostra le card stile "Le mie" raggruppate per risorsa, ognuna con badge colorato.

Endpoint nuovo: `GET /planning/api/project-bookings?project_id=X`. RBAC: 403 se non admin/manager/producer/edit_planning.

UI lato server: `user_is_elevated` passato al template per gating della tab. `VALID_VIEWS` esteso con `'project'`.

---

## v3.4.43 — Duplica quote con scelta progetto + Sposta progetto (2 maggio 2026)

### #4 — Duplica con scelta progetto

`POST /quotes/api/{id}/duplicate` ora accetta `project_id` opzionale (Form). Se valorizzato, la copia viene associata al progetto target e il `client_id` viene riallineato al cliente del progetto.

UI: il bottone "📋 Duplica" (lista + editor) ora apre un modal `Duplica quotazione` con dropdown searchable progetti. Dropdown vuoto = stesso progetto sorgente.

### #4 — Sposta quote a un altro progetto

Nuovo endpoint `PUT /quotes/api/{id}/move-to-project` con due vincoli rigidi:
- Stato deve essere `draft` (cambio scope su quote sent/approved/etc è incoerente).
- La quote NON deve avere un Job collegato (incoerenza grave: il job si lega al progetto via la quote).

UI: bottone "🚚 Sposta" nell'editor, visibile solo se quote in `draft`. Apre modal `Sposta quotazione` con dropdown progetti. RBAC `edit_quotes`.

---

## v3.4.42 — Undo paste + Le mie con dettaglio booking + note (2 maggio 2026)

### #1 — Undo per copy/paste timeline planning

`tlPasteAt` ora ritorna gli id dei booking creati e fa push undo con `type='paste_batch'`. Il toast undo standard (5s) annulla in batch tutti i booking incollati con DELETE successivi. Coerente col pattern undo esistente per drag/resize/delete/create/duplicate.

### #8 — Le mie / Dashboard: dettaglio booking + note

- **Card cliccabili** in `/planning?view=todo` e nella card "I miei booking di oggi" della Dashboard. Click su title o meta apre modal `📋 Dettaglio booking`.
- **Note inline** sulla card: se `Booking.notes` è valorizzato, viene mostrato in un blocco discreto (sfondo indigo lieve, simile alla `not-done-reason`).
- **Modal dettaglio**: mostra Quando, Job (con link "→ Apri job"), Lavorazione (con `quantity_actual/quantity_quoted`), Stato (priorità + esecuzione + overtime badge), Risorse (se multi-risorsa), Note, Motivazione "non fatto".

Endpoint nuovo: `GET /planning/api/bookings/{booking_id}/detail` — dati estesi del booking per il modal.

---

## v3.4.41 — Bug fix triplo (2 maggio 2026)

### #2 — Hard block paste timeline su ferie/malattia

`tlPasteAt` ora verifica `_tlUnavailabilities` per la risorsa target prima di creare il booking. Se la risorsa è in `vacation`/`sick` nel range di destinazione, il paste viene saltato e contato come bloccato. Toast: "N incollati, M bloccati (ferie/malattia), K errori".

Coerente con il drag block: ferie/malattia sono `_blocking_hard`, festività restano `_blocking_soft` (workflow overtime).

### #3 — Chrome: layout timbratura + clock icon nativa

Due fix CSS in `main.css`:

- `.mf-dt` ora usa `grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr)` invece di `1.5fr 1fr` → previene overflow e shrinking errato in modali stretti (Chrome era più aggressivo nel layout).
- `input[type="time"]:not([data-no-time-picker="true"])::-webkit-calendar-picker-indicator { display: none; }` → sopprime l'icona clock nativa Chrome (apriva un secondo popup oltre al nostro custom).

### #5 — Cost report: ore done ora maturate

Bug: `JobCostLine.quantity_actual` e `total_accrued` non venivano aggiornati quando un booking veniva marcato `execution_status=done`. Risultato: il consuntivo restava a 0 nel cost report anche se gli operatori segnavano "fatto" nelle card "Le mie".

Nuovo servizio `app/services/cost_line_sync.py`:
- `recompute_cost_line_actual(db, jcl)`: aggrega tutti i booking `done` della cost line, calcola ore totali, converte all'unità della cost line (`hr`/`day` → conversione automatica con HOURS_PER_DAY=8) e aggiorna `quantity_actual` + `total_accrued`. Idempotente.
- `recompute_for_booking(db, b)`: helper per gli hook negli endpoint planning.
- `recompute_for_job(db, job_id)`: ricomputa tutte le cost lines di un job (per riconciliazione retroattiva).

Hook in:
- `PATCH /planning/api/bookings/{id}/execution` — su ogni cambio stato (done/not_done/planned/in_progress)
- `PATCH /planning/api/bookings/{id}/extend` — su estensione durata di booking già done

Endpoint nuovo: `POST /cost-report/api/job/{id}/reconcile-actuals` per fix retroattivo via UI o curl. Necessario su DB esistenti dove i booking erano stati marcati `done` prima di questa fix.

Unità non temporali (`fix`, `lot`, ecc.): non aggiornate automaticamente, vanno editate manualmente.

---

## v3.4.40 — Searchable dropdowns + Time picker popup (2 maggio 2026)

Trasversale UI: ogni `<select>` diventa cercabile, ogni `<input type="time">` (e ogni `datetime-local`) ha un popup HH:MM con quick-pick.

### Searchable select (autocomplete)

Helper `mfMakeSearchableSelect(selectEl)` in `global.js`. Trasforma un `<select>` in combobox con input ricerca + dropdown filtrabile. Il `<select>` originale resta nel DOM (hidden, classe `.mf-ss-native`) per submit/api.

- **Auto-attach**: `DOMContentLoaded` → `mfApplySearchable(document)`. Esclude `multiple` e `data-no-search="true"`.
- **Re-attach**: delegato su click `[onclick*="openModal"]` (modali con select popolati async).
- **Sync programmatico**: `select._mfSsRefresh()` per ri-allineare il display dopo `select.value = X` senza dispatch change.
- **Keyboard**: ↑↓ Enter Esc.
- **Posizionamento**: apertura sopra se non c'è spazio sotto.

### Time picker popup

Helper `mfAttachTimePicker(input)` in `global.js`. Popup grid HH:MM step 15min default (override `data-time-step`). Quick-pick row con orari frequenti (08:00, 09:00, 12:00, 13:00, 14:00, 17:00, 18:00, 20:00). Coesiste con il typing manuale e con il picker nativo.

### Datetime-local splittato

Helper `mfWrapDateTimeLocal(input)` automatico su tutti gli `<input type="datetime-local">`. Splitta in due input affiancati `<date> <time>` e nasconde l'originale (resta come "verità" sincronizzata via change/input). Il time picker custom si applica al sub-time.

Reason: il widget nativo `datetime-local` non si presta a un popup orario custom; lo splittiamo per uniformare l'UX dei due cantieri (timbratura, booking).

### CSS

`.mf-ss`, `.mf-ss-display`, `.mf-ss-dropdown`, `.mf-ss-list`, `.mf-ss-item`, `.mf-tp-popup`, `.mf-tp-grid`, `.mf-tp-cell`, `.mf-dt` in `main.css`. Coerenza palette indigo (CSS variables esistenti).

### Cache buster

`base.html` → `?v=3.4.40` su `main.css` e `global.js` (lezione `feedback_cache_buster_static.md`).

---

## v3.4.39 — Quote: duplica + versioning + Floating Jobs (2 maggio 2026)

Due funzioni distinte per gestire varianti della stessa quotazione + sezione anomalie in /finance.

### Duplicazione semplice — `POST /quotes/api/{id}/duplicate`

Bottone "📋 Duplica" in lista `/quotes` e nell'editor. Crea una copia INDIPENDENTE con numero auto-progressivo `Q-{anno}-NNN`, status=draft, righe + sconti + category_order copiati, project/client uguali. **Nessun parent_quote_id.** Use case: scenario alternativo, template per nuovo progetto.

### Versioning — `POST /quotes/api/{id}/new-version`

Bottone "📐 Versione" in lista e nell'editor. Crea V_n+1 con `parent_quote_id` valorizzato, numero `{root}-v{N}` (es. `Q-2026-007-v2`), `version` monotonamente crescente nella catena. Le righe ereditano `QuoteLine.parent_line_id` per re-bind preciso al migrate-job.

### Sezione "Versioni" nell'editor

Visibile quando la quote ha parent o figli. Mostra la catena completa con stato di ognuna, badge Job ✓ se collegata, link cliccabili. La versione corrente è evidenziata in indigo.

### Migrazione Job — `POST /quotes/api/{new_id}/migrate-job`

Bottone "↪ Migra Job a questa versione" appare quando la V_new è draft/sent e la V_old (parent) ha un Job. Workflow:

1. **Preview** (`GET /migrate-preview`): elenca righe ereditate, nuove (presenti solo in V_new), orfane (presenti solo in V_old, evidenziate in rosso se hanno `quantity_actual > 0`), sforamenti (V_new pianifica meno di quanto già lavorato).
2. **Apply**: V_new.status=approved + V_old.status=`superseded` + V_old.superseded_by_id=V_new. JobCostLine ribindate via `parent_line_id`. Righe nuove → JobCostLine creati. Per le orfane scelta `orphan_strategy`:
   - `keep_as_extra` (default): JobCostLine resta sul job marcato `is_extra=True` (lavoro tracciato, evidenziato in /finance > Anomalie).
   - `floating_job`: il Job viene scollegato (`quote_id=NULL`) → entra nella sezione "Job orfani" di /finance per riassegnazione manuale.

Nuovo enum `QuoteStatus.superseded` (distinto da `rejected`: la quote non è stata rifiutata, è stata sostituita).

### `/finance` → tab "⚠ Anomalie" (nuova)

Tre card:
- **Job orfani**: lista job con `quote_id IS NULL` (da migrazione `floating_job` o cancellazioni). Mostra budget, consuntivo, link al job.
- **Sforamenti**: JobCostLine con `quantity_actual > quantity_quoted` (non extra). Δ + valore extra in mono.
- **Extra**: JobCostLine con `is_extra=True` (lavorazioni fuori quote).

Endpoint:
- `GET /finance/api/anomalies/floating-jobs`
- `GET /finance/api/anomalies/discrepancies`
- `GET /finance/api/anomalies/summary` (counter aggregato per badge topbar)

Badge rosso sulla tab quando ci sono job orfani o extra.

### Modello

```python
Quote:
  parent_quote_id: FK quotes.id NULL          # catena versioni
  superseded_by_id: FK quotes.id NULL         # successore approvato

QuoteLine:
  parent_line_id: FK quote_lines.id NULL      # eredità riga in V_n+1

QuoteStatus.superseded                         # nuovo enum value

NotificationKind.job_floating_alert           # → admin/accounting
NotificationKind.quote_discrepancy_alert      # (riservato per cantieri futuri)
```

### Migrazione

Script `scripts/migrate_quote_versioning.py` (opzione `[N]` su `strumenti.bat/sh`). Auto-applicata anche al boot via `_auto_migrate_columns()`. Idempotente.

### Permessi

`duplicate`, `new-version`, `migrate-job` richiedono permesso `edit_quotes`.

---

## v3.4.38 — Round 3 Audit: hardening logico (1 maggio 2026 notte profonda)

Round 3 di 3 dell'audit logico. Cinque fix di robustezza.

### R3.1 — Invariante `count_in_costs` ↔ `execution_status`

`count_in_costs=True` ha senso SOLO con `execution_status=not_done` (pool ore non maturate ma da contare comunque).

- `PATCH /planning/api/bookings/{id}/execution`: se nuovo stato ≠ `not_done`, force `count_in_costs=False`.
- `PATCH /planning/api/bookings/{id}/count-in-costs`: rifiuta con 400 se `execution_status ≠ not_done` (messaggio chiaro: "Cambia prima lo stato esecuzione").

Elimina lo stato incoerente "booking done con count_in_costs=True" che potrebbe confondere il calcolo del cost report.

### R3.2 — RBAC guard su `update_quote`

`PUT /quotes/api/{quote_id}` ora richiede permesso `edit_quotes` esplicito (`app/routers/quotes.py:322`). Prima qualunque utente autenticato poteva modificare i totali della quotazione.

### R3.3 — Reset `original_end_datetime` su shortening

`PUT /api/booking-assignments/{id}` ora controlla post-update: se il booking aveva `overtime_status=approved` e il nuovo end-time riporta tutti gli assignment dentro la fascia regolare, `overtime_status` torna a `none` e `original_end_datetime` torna a `NULL`. Audit log con kind `overtime_revert`.

Edge case: l'admin/manager accorcia un booking precedentemente approvato come straordinario → il sistema rileva che non è più overtime e azzera lo status (no più "approved" residuo che non corrisponde alla realtà delle ore).

### R3.4 — FSM transizioni `JobStatus`

Matrice esplicita `JOB_STATUS_TRANSITIONS` in `planning.py`:

| Da | A consentite |
|---|---|
| `draft` | quoting, approved, cancelled |
| `quoting` | draft, approved, cancelled |
| `approved` | active, on_hold, cancelled, completed |
| `active` | on_hold, completed, cancelled |
| `on_hold` | active, cancelled, completed |
| `completed` | invoiced, active (riapertura) |
| `invoiced` | (terminale, solo via DB op) |
| `cancelled` | approved (riapertura legacy) |

`PUT /api/jobs/{id}/status` valida e rifiuta con 400 + messaggio chiaro se la transizione non è ammessa. Log della transizione su stdout (poi audit-loggato in iter successiva).

### R3.5 — Cleanup Timesheet legacy nel cost report

Memoria architetturale: cost report = quote+booking+hardcost (cliente/finance), Timesheet/TimePunch = HR (consulente lavoro). Il cost report continuava a esporre `summary.hours_cost`, `summary.hours_cost_legacy_timesheet`, `timesheet_summary` da Timesheet — confondendo le due fonti.

Rimossi dal response:
- `summary.hours_cost` e `summary.hours_cost_legacy_timesheet`
- `timesheet_summary` (lista per-user)

Rimossa anche la query `Timesheet` dal router cost_report e l'import non più necessario. UI `renderTimesheets()` ora mostra un banner che rimanda alla sezione "⏱ Ore booking per fascia".

### Limiti riconosciuti

- FSM Job non controlla i side-effect (es. transizione `completed → active` non riapre i booking cancellati, non ricrea cost lines): gestione side-effect rimandata a v3.5+ se servirà.
- RBAC guard su `update_quote_line`/`delete_quote_line`/`add_quote_line` (lifecycle Quote) non ancora aggiunto in Round 3 — prossima iterazione.
- Cleanup ulteriori (ProjectTechSheet.data Pydantic, Notification.payload schema, Asset acycity, dead CSS .side-pl-*) restano in backlog.

---

## v3.4.37 — Round 2 Audit: barra avanzamento job (1 maggio 2026 notte profonda)

Risposta alla richiesta diretta di Matteo: "barra progressi nei job in pianificazione in base a quanto è stato svolto nei booking".

### Algoritmo

`_compute_job_progress(db, job_id)` in `app/routers/planning.py`:
- Itera su `BookingAssignment` join `Booking` con `Booking.job_id == job_id` e `status != cancelled`.
- Calcola ore per assignment: `(end - start) / 3600`.
- Esclude pool `not_done` non maturato (`execution_status=not_done` AND `count_in_costs=False`).
- Somma `total_hours` (tutti i validi) e `done_hours` (solo `execution_status=done`).
- `progress_pct = done_hours / total_hours * 100` (0 se nessun booking).

### Endpoint

- `GET /planning/api/jobs/{job_id}/progress` → `{progress_pct, done_hours, total_hours}`
- `GET /planning/api/jobs?include_progress=true` aggiunge i 3 campi a ogni riga della lista (più lento, opt-in).

### UI

Tabella `/planning?view=jobs` ha nuova colonna **"Avanzamento"** tra "Stato" e "Apri":
- Per ogni job, etichetta `pct%` + dettaglio `done_h / total_h`
- Barra CSS larga `pct%`, color-coded: ≥100% verde, ≥50% indigo, >0 ambra, =0 grigio
- Se nessun booking valido (total_hours=0), mostra "—"

### Limitazioni note (Round 2)

- Job con cost_lines orfane pre-v3.4.36 potrebbero dare progresso falso. Ora che v3.4.36 ha sistemato il lifecycle e v3.4.36 cleanup `[M]` è stato eseguito, il calcolo è coerente con i booking realmente attivi.
- Il calcolo è **on-the-fly** (no cache). Per liste con molti job potrebbe essere lento — il flag `include_progress` è opt-in proprio per non rallentare la lista quando non serve.

---

## v3.4.36 — Round 1 Audit: lifecycle Quote↔Job sano (1 maggio 2026 notte profonda)

Risposta all'audit logico richiesto: il primo dei 3 round chiude i bug critici sul ciclo di vita Quote→Job→JobCostLine→Booking. Prima di questo bump, cancellare/modificare/aggiungere righe quote dopo l'approvazione del job lasciava JobCostLine orfani o disallineati. Ora il sync è automatico, con guardrail per job in stato terminale.

### B1 — DELETE QuoteLine ora cascata a JobCostLine (+ soft-detach Booking/TimePunch)

`DELETE /quotes/api/{quote_id}/lines/{line_id}` (`app/routers/quotes.py:514`):
1. Trova tutte le `JobCostLine` con `quote_line_id=line_id`.
2. Per ogni JobCostLine, blocca con 409 se `job.status` è `completed` o `invoiced` (no retroattive su lavorazioni consuntivate).
3. Soft-detach: `Booking.job_cost_line_id` e `TimePunch.job_cost_line_id` → `NULL` (no FK rotti).
4. Cancella la JobCostLine.
5. Cancella la QuoteLine.

`DELETE /jobs/api/{job_id}/cost-lines/{line_id}` (`app/routers/jobs.py:316`): stesso soft-detach Booking/TimePunch prima della cancellazione.

### B3 — Auto-create JobCostLine su add QuoteLine post-Job

`POST /quotes/api/{quote_id}/lines` (`app/routers/quotes.py:424`): dopo aver creato la nuova QuoteLine, se la quote ha `q.job` valorizzato e il job è in stato non terminale (`approved/active/on_hold/draft/quoting`), crea automaticamente la JobCostLine corrispondente con `quote_line_id=line.id`, `is_extra=False`, qty/unit/price clonati. Idempotente (skip se esiste già). Risposta arricchita con `job_cost_line_created: bool`.

### B4 — Auto-sync update QuoteLine → JobCostLine

`PUT /quotes/api/{quote_id}/lines/{line_id}` (`app/routers/quotes.py:502`): dopo recalc quote, se esiste JobCostLine collegata e job in stato non terminale, aggiorna `description`, `quantity_quoted`, `unit`, `unit_price`, `total_quoted`. Se job è `completed/invoiced/cancelled`, blocca con 409 + messaggio chiaro. `total_expected` NON viene sovrascritto (può essere stato modificato manualmente per stima a finire più aggressiva).

### C2 — Margin cost report dinamico

`cost_report.py`: il margine era già calcolato come `total_quoted - estimated_cost` (corretto), ma c'era confusione tra `Job.budget_quoted` (snapshot all'approvazione, statico) e il `total_quoted` vivo. Aggiornato il commento esplicativo nel codice e la sub-label UI: "Σ quotato vivo − (costo ore + spese)".

### Migrazione cleanup `[M]`

`scripts/migrate_lifecycle_cleanup.py`: pulizia orfani esistenti pre-v3.4.36 in 3 step idempotenti:
1. JobCostLine con `quote_line_id` che punta a riga inesistente → cancellate (skip se `is_extra=True`).
2. Booking con `job_cost_line_id` orfano → `NULL`.
3. TimePunch con `job_cost_line_id` orfano → `NULL`.

Voce `[M]` aggiunta a `strumenti.bat` e `strumenti.sh`.

### B5 — Out of scope (sufficientemente coperto)

L'altra strategia (FK `ondelete` SQL fisici) richiederebbe ricreazione tabelle SQLite. Lasciata per Round 3 (M1) se serve hardening DB-level. La logica applicativa attuale copre già tutti i casi noti.

### Note edge case

- **Round trip**: cancello QuoteLine → JobCostLine cancellata → Booking che la puntava ha `job_cost_line_id=NULL` ma `job_id` resta. Il booking è ancora valido come "ore generiche del job". Il cost report `_bookings_hours_cost` aggrega sempre dal `Booking.job_id`, quindi le ore continuano a contare.
- **Aggiungo poi modifico**: aggiungo riga quote → JobCostLine creata (qty=X). Modifico la riga → JobCostLine aggiornata. Cancello → tutto pulito.
- **Job in `completed`**: tentativi di modifica/cancellazione bloccati con 409. L'admin può duplicare il job o riaprirlo (rimanendo in `cancelled` → `approved` flow esistente in `quotes.py:40`).

---

## v3.4.35 — Undo stack + Salva su /quotes editor (1 maggio 2026 notte tarda)

Rete di sicurezza per le modifiche alla quotazione. L'auto-save al blur resta attivo, ma ora c'è un sistema undo + bottone Salva esplicito.

### Stack undo client-side

`window._quoteUndoStack` (max 20 op). Ogni operazione tracciabile è invertibile:
- `line_add` (drag&drop o "Aggiungi alla quotazione" nel pannello listino) → undo = `DELETE` riga
- `line_delete` (cancellazione voce con conferma) → undo = `POST` ricreazione con stessi dati (snapshot prima del delete)
- `lines_reorder` (drag voci entro/tra categorie) → undo = `PUT lines-reorder` con previous_order
- `category_reorder` (drag handle ⋮⋮ su header categoria) → undo = `PUT category-order` con previous_order

Lo stack si resetta quando si apre una quote diversa (`openEditor` clear).

### UI

- Bottone **"↺ Annulla"** in topbar editor accanto a "← Lista". Disabilitato quando lo stack è vuoto. Tooltip mostra l'ultima operazione annullabile.
- **Toast post-azione** con bottone "↺ Annulla" cliccabile (timeout 5s). Posizionato in basso al centro, bordo indigo. Pattern riusato da timeline planning v3.4.14 (`tlPushUndo`).
- Bottone **"💾 Salva"** in topbar: l'auto-save è già attivo, ma il bottone forza `blur()` su tutti gli input/textarea pending e mostra toast "✓ Tutto salvato" — reassurance UX, non strettamente necessario.

### Modello

Nessuna modifica al backend: gli endpoint esistenti (`POST/DELETE/PUT lines`, `PUT lines-reorder`, `PUT category-order`) sono già idempotenti e supportano l'undo riapplicando inversa. Lo stack è solo client-side: si perde se la pagina viene ricaricata.

---

## v3.4.34.5 — Fix drag&drop listino → voci (1 maggio 2026 notte tarda)

Bug introdotto in v3.4.34 (refactor multi-tbody categorie): gli handler `onLinesDragOver`/`onLinesDragLeave`/`onLinesDrop` cercavano ancora `document.getElementById('lines-body')`, che non esisteva più dopo che il tbody era stato rinominato in `lines-tbody-empty` e sostituito con tbody dinamici per categoria.

Fix: target unificato su `#lines-card` (la card sempre presente). Aggiunte le classi `.drop-active` e `.drop-hint` lì. Aggiornato CSS `#lines-card.drop-active` (era `#lines-body.drop-active`).

---

## v3.4.34.4 — Listino allargato +35% (1 maggio 2026 notte tarda)

`.al-side`: width 480→650px (>1400) e 440→600px (1024–1400). `#quote-editor.with-pricelist` padding-right 500→670px e 460→620px in proporzione. Più spazio per i risultati listino con drag handle e meta tags.

---

## v3.4.34.3 — Critical Assumptions reagisce al toggle Listino (1 maggio 2026 notte tarda)

Fix: la topbar editor (con Critical Assumptions inline) non si stringeva quando il pannello Listino flottante veniva aperto, sovrapponendosi visualmente al pannello.

Soluzione: la classe `.with-pricelist` ora è applicata anche al wrapper `#quote-editor` (non solo a `#quote-editor-body`). Il CSS `#quote-editor.with-pricelist { padding-right: 500px }` (460 a <1400, 0 a <1024) riserva spazio per l'intero blocco editor — topbar inclusa.

JS: `openSideAddLine()` e `closeSideAddLine()` aggiungono/rimuovono la classe su entrambi gli elementi.

---

## v3.4.34.2 — Listino flottante + same-height top row + IVA in Riepilogo (1 maggio 2026 notte tarda)

3 fix di precisazione layout v3.4.34.1.

### 1. Listino flottante (`position:fixed`)
La v3.4.34.1 usava `position:sticky` che funziona solo finché il parent ha scroll. Quando il content sotto si esauriva, il pannello scrollava fuori vista. Ora `.al-side` è `position:fixed; top:80px; right:20px; width:480px; max-height:calc(100vh-100px)`: rimane SEMPRE visibile alla stessa altezza viewport durante qualsiasi scroll della pagina. Solo scroll interno alla lista risultati (`.al-results { overflow-y:auto }`).

Layout: con pannello aperto, `#quote-editor-body.with-pricelist` aggiunge `padding-right:500px` (460px a <1400) per riservare spazio. Sotto 1024px (mobile) il pannello torna a `position:static` in colonna naturale.

### 2. Riepilogo + Stato stessa altezza
`.quote-top-row` ora ha `align-items:stretch` + `height:100%` su entrambe le card. Le card hanno `display:flex; flex-direction:column` per distribuire il contenuto verticalmente.

### 3. IVA in Riepilogo (rimossa da Stato)
L'`<input id="q-vat">` è ora dentro `#totals-panel` (rigenerato da `renderTotals()`) come campo editabile inline accanto alla riga "IVA". Stato & azioni perde il campo IVA, guadagnando spazio per i textarea di Note e Termini di pagamento, ridotti a `rows="1"` con classe `.qe-compact-ta` che espande min-height al focus (28→60px).

---

## v3.4.34.1 — Layout editor /quotes: Stato a sinistra, Listino sticky (1 maggio 2026 notte tarda)

Correzione layout v3.4.34 su richiesta:

1. **"Stato & azioni" spostato nella colonna sinistra**, in cima accanto a "Riepilogo economico" (grid 2 colonne `.quote-top-row`, su mobile collassa in singola colonna a `<900px`). "Voci preventivo" sotto a tutta larghezza.

2. **Colonna destra = solo pannello Listino** (`.quote-side-col`). Quando il listino si chiude, la colonna sinistra si riespande naturalmente perché `#quote-editor-body` torna a `grid-template-columns: 1fr`.

3. **Listino sticky**: il pannello `.al-side` è già `position:sticky; top:80px; max-height: calc(100vh - 100px); overflow:hidden` (da v3.4.33.1). Quando l'utente scrolla la pagina, il pannello rimane visibile alla stessa altezza viewport. Lo scroll interno alla lista risultati funziona via `.al-results { overflow-y:auto }`.

CSS aggiunti: `.quote-top-row` (grid 2 colonne con responsive), `.quote-side-col` (wrapper colonna destra, no transformazioni).

---

## v3.4.34 — Refactor layout editor /quotes (1 maggio 2026 notte tarda)

Riorganizzazione editor quotazione su richiesta UX di Matteo. 6 punti.

### 1. Critical Assumptions compatto in topbar
Il blocco "Critical Assumptions" non è più una card a tutta larghezza nella colonna sinistra. È ora una **bar inline compatta** tra il titolo e il body editor: 4 input affiancati (`Material / Delivery / min / FPS`) con sfondo indigo-bg, label uppercase laterale. Riduce drasticamente lo spazio verticale occupato.

### 2. Bottone "+ Aggiungi voce" rimosso
Tolto dalla card "Voci preventivo". Ora c'è un'unica entrypoint per aggiungere voci: il toggle **"📋 Listino"** in topbar che apre il pannello laterale persistente.

### 3. Riepilogo economico SOPRA Voci preventivo
Nella colonna sinistra (editor), il "Riepilogo economico" è ora la prima card, sopra a "Voci preventivo". Visibilità immediata dei totali appena entri.

### 4. Listino allineato alle Voci preventivo
Il pannello "Listino & aggiungi voce" è spostato dentro la **colonna destra** (era 3a colonna del grid). La colonna destra contiene "Stato & azioni" sopra al pannello listino. Il top del pannello è naturalmente allineato al top di "Voci preventivo" (entrambe le colonne partono da `align-items: start`).

### 5. Stato & azioni sopra il Listino
Spostata sopra al pannello listino nella colonna destra. Il bottone "✓ Approva quote → Job" è stato spostato qui (era in topbar).

### 6. Riordino categorie via drag&drop
Le voci preventivo sono ora renderizzate in **multi-tbody** dentro la stessa `<table>` (un `<tbody class="ql-cat-tbody">` per categoria). Header categoria ha maniglia ⋮⋮ a sinistra: SortableJS sul livello tbody permette di trascinare un intero blocco categoria sopra/sotto un altro.

L'ordine è persistito in `Quote.category_order` (JSON nullable, auto-migrate al boot). Endpoint `PUT /quotes/api/{id}/category-order` body JSON `{order: ["PICTURE","SOUND",...]}`. Categorie non listate appaiono dopo nell'ordine naturale.

Drag voci dentro/tra categorie funziona ancora (gruppo `quote-lines` su SortableJS).

### Layout grid

```
#quote-editor-body                  → 1fr (singola, no listino)
#quote-editor-body.with-pricelist  → 1fr 480px (editor + col destra)
< 1400px                          → 1fr 440px
< 1024px                          → 1 colonna (mobile, listino in fondo)
```

### Modello

`Quote.category_order: Mapped[Optional[list]]` JSON nullable. Auto-migrate al boot aggiunge `quotes.category_order TEXT NULL` se mancante.

---

## v3.4.33.1 — Pannello "Aggiungi voce" laterale persistente (1 maggio 2026 notte tarda)

Patch di v3.4.33 per chiarimento UX listino in /quotes. La richiesta di Matteo era: il **modal "Aggiungi voce"** (con sidebar categorie + ricerca + risultati grandi) deve diventare un **pannello laterale persistente** con drag&drop, NON un mini-pannello compatto.

### Cambio strutturale

- **Rimosso** il `#modal-add-line` (overlay centrale modal-style) e il `#side-pricelist` mini introdotto in v3.4.29.
- **Aggiunto** il pannello `#side-add-line` (`<aside class="al-side">`) che riusa la GUI ricca del vecchio modal (`al-searchbar` + `al-main` con `al-cat-sidebar` + `al-results` + `al-selpanel`) ma è persistente (non overlay, no backdrop) e resta aperto fino al click ✕.
- **Larghezza** colonna pannello: 480px (era 340px del mini), responsive con breakpoint a 1400/1200/1024px.
- **Drag handle** sui `.al-result`: ogni voce ha `draggable="true"` + `ondragstart="onSpDragStart()"`. Hint visibile in hover ("⋮⋮ trascina"). Drop su `#lines-card` (handler già esistente da v3.4.29).
- **Click su una voce** → la seleziona e attiva il pannello editor (`al-selpanel`) con descrizione/qty/unit/prezzo modificabili. Bottone "Aggiungi alla quotazione" aggiunge la voce e **resetta la selezione**: il pannello resta aperto pronto per la prossima.
- **Toggle "📋 Listino"** e click "+ Aggiungi voce" aprono entrambi lo stesso pannello (deduplicato).
- **Default aperto** all'apertura dell'editor di una quote (preserva il default introdotto in v3.4.33). Click ✕ chiude e memorizza in localStorage `mf_side_pricelist_open='0'`.

### Layout grid

```
#quote-editor-body                 → 1fr + 320px (editor + meta)
#quote-editor-body.with-pricelist  → 1fr + 280px + 480px (editor + meta + pannello)
< 1200px                          → 1fr + 420px (meta nascosta)
< 1024px                          → 1 colonna (mobile)
```

### CSS / JS rimossi (deprecati)

- Funzioni `openSidePricelist`, `closeSidePricelist`, `renderSidePricelist`: il mini-pannello v3.4.29 non esiste più.
- Selettori `.side-pl-*`: dead code (lasciato in CSS per ora, ripulibile in cleanup).

### Funzioni nuove

- `openSideAddLine(resetSearch)` — apre il pannello, focus sulla ricerca; se `resetSearch=true` (chiamato da "+ Aggiungi voce") svuota search e selezione, altrimenti (chiamato da toggle "📋") preserva lo stato.
- `closeSideAddLine()` — chiude e salva preferenza.
- `toggleSidePricelist()` — alias di toggle sul nuovo pannello (mantenuto per back-compat con il bottone in topbar).

---

## v3.4.33 — Cost report v2 (fonte ore = Booking) + PDF cliente + listino /quotes default open (1 maggio 2026 notte)

Cantiere "Cost Report doppio" sospeso da v3.4.21 ora avviato. Step A+B+C consegnati; "Genera quote v2 dagli scostamenti" (Step D) volutamente fuori scope, ribadito.

### Step A — Refactor `/cost-report/api/job/{id}` con fonte ore = Booking

Coerente con la decisione architetturale "cost report (quote+booking+hardcost) ≠ timesheet (HR/buste paga)" salvata in memoria.

**Calcolo nuovo**: `_bookings_hours_cost(job_id, db)` aggrega gli `BookingAssignment` del job tramite `compute_assignment_breakdown()` (engine v3.4.32) e li pesa con il `rate_per_hour` derivato da `Resource.hourly_rate` (fallback `daily_rate / 8`). Ritorna `total_hours`, `total_cost`, `breakdown_total` (regular/overtime/night/sunday/holiday/pending/pool), `by_resource` (lista per-risorsa con costo stimato).

**Nuovi campi del response `summary`** (canonici v3.4.33):
- `bookings_hours` — ore totali pianificate dai booking
- `bookings_hours_cost` — costo equivalente delle ore (weighted_factor × rate)
- `estimated_cost` — booking_cost + total_expenses
- `margin` — quotato − estimated_cost

**Campi legacy** (deprecati, mantenuti per back-compat):
- `hours_cost_legacy_timesheet` — vecchio calcolo da Timesheet
- `hours_cost` — alias storico (= legacy_timesheet, NON usato nel calcolo cost report)

**Nuove sezioni del response**:
- `bookings_breakdown` — breakdown totale ore per fascia
- `bookings_by_resource` — array per-risorsa con rate, breakdown, cost_estimated

### Step B — PDF cliente

Nuovo endpoint `GET /cost-report/api/job/{id}/client-pdf` ritorna un PDF ReportLab della **rendicontazione cliente** che include:
- Header con job code/title/cliente/periodo
- **Lavorazioni preventivate**: descrizione, unità, q.tà preventivo→consuntivo, stato (Da fare/In corso/Completata/Sforamento)
- **Lavorazioni extra** (is_extra=True): descrizione, unità, q.tà — header arancione per distinguere
- **Riepilogo ore lavorate**: regolari + straordinarie + notturne + dom + festive + totale (ottenute dal breakdown booking)

Esplicitamente **escluse**: hardcost, rate risorsa, costi-margine, fatturato/pagato. Il documento è di rendicontazione, non fatturazione.

Funzione `app/services/pdf_export.py::generate_client_cost_report_pdf(report, company)` riusa pattern di `generate_invoice_pdf` (header, palette, font Helvetica, A4).

### Step C — UI bottone export + KPI estesi

Pagina `/cost-report`:
- Nuovo bottone "📄 Esporta PDF cliente" accanto al selettore job (link diretto, target=_blank).
- Stat-grid esteso a 8 KPI: aggiunte card **"Costo ore (booking)"** e **"Margine stimato"** (margine = quotato − costo_booking − spese, verde/rosso).

### Bug fix correlati

- `JobCostLine` mancava la relationship `price_item` esplicita: il `joinedload(JobCostLine.price_item)` falliva con `AttributeError` in SQLAlchemy 2.0. Aggiunta relationship lazy nel modello.

### Listino /quotes default aperto

Pannello laterale "📋 Listino" in `/quotes` ora **aperto di default** (prima era nascosto fino al primo click toggle). `localStorage.getItem('mf_side_pricelist_open')` interpretato così: `'0'` = chiuso (chiusura esplicita utente), qualsiasi altro valore o assente = aperto. La X del pannello memorizza la chiusura.

Modal "Aggiungi voce" con ricerca listino + sidebar categorie + click-to-select era già presente (`#al-search` / `#al-cat-sidebar` / `#al-results` / pannello selezione editabile + bottone "voce libera"): nessun cambio richiesto, la (D) era già implementata.

### Limiti riconosciuti / cantieri seguenti

- **Brand & PDF customization** segnato come cantiere a parte (capitolo "configurabilità PDF" — nuova entità `BrandSettings` per-tenant con logo/legal/colors/font).
- **Step D — "Genera quote v2 dagli scostamenti"** fuori scope confermato.
- Il cost report attuale assume rate orario costante per risorsa. La gestione di **rate diversi per progetto** (vedi `JobResourceAssignment.agreed_hourly_rate`) non è ancora applicata al calcolo booking_cost.
- **Capability AI `propose_working_hours_policy`** per popolare i preset CCNL Cinema (Distribuzione/Doppiaggio/Teatri di posa) restano da implementare. La struttura dati è già pronta da v3.4.32.2.

---

## v3.4.32.2 — Patch v3.4.32.1: timeline align + paste GUI + governance overtime + scaglioni CCNL (1 maggio 2026 notte)

Patch dopo test locale di v3.4.32.1. 4 fix raggruppati.

### Fix #1 — Allineamento timeline label↔group ripristinato
La v3.4.32.1 aveva aggiunto `min-height: 38px` sulla label foglia E `min-height: 38px` sui group foreground separatamente. Ma vis-timeline calcola le altezze dei due in coppia runtime e fissarle da CSS rompe l'allineamento. Tolti tutti i `min-height/max-height` su `.vis-label` e `.vis-foreground .vis-group`. Lasciato solo padding+font-size per la leggibilità.

### Fix #2 — Paste GUI: click-to-paste + right-click "Incolla qui"
Sostituito il vecchio Ctrl+V che incollava sempre "ad oggi alla stessa ora".

- **Ctrl+C** → copia (come prima)
- **Ctrl+V** → entra in **paste mode**: barra arancione fissa in basso ("Modalità incolla — Click sulla timeline per incollare N booking · Esc per annullare"), cursor `copy`, outline tratteggiato sulla timeline. Il prossimo click su area vuota incolla con il primo booking che atterra alla posizione cliccata, gli altri shiftati di pari offset preservando la spaziatura. Se clicchi su una risorsa diversa, il primo booking va sulla nuova risorsa, gli altri restano sulle proprie.
- **Right-click su area vuota** → menu con voce "📋 Incolla qui (N)" se clipboard non vuoto.
- **Esc** → esce da paste mode.

Snap automatico al passo zoom (15min day, 30min week/month, 60min quarter).

### Fix #3 — Governance overtime: auto-approve solo manager+admin
Decisione strategica: "approvazione straordinari deve darla il manager, non l'operatore. Se non è possibile, manager/producer deve ricevere notifica."

- **Auto-approve self** ammesso ora **solo per manager+admin** (NON producer). Producer ha ancora `approve_overtime` ma estendendo va sempre in pending → dev'essere il manager a confermare esplicitamente.
- Quando manager/admin auto-approva, **gli ALTRI manager+admin ricevono notifica** kind=`booking_overtime_resolved` severity=`info` (no action_required, solo audit/awareness).
- Logica replicata sia in `/extend` (estensione adattiva) sia in `_maybe_flag_overtime_on_assignment_change` (drop su festivo/notturno via PUT assignment).

### Fix #4 — Scaglioni overtime configurabili (preparazione CCNL)
Aggiunti due campi a `WorkingHoursPolicy`:
- `overtime_brackets` JSON nullable: lista `[{"from_hour": float, "multiplier": float}, ...]` per gestire CCNL con maggiorazioni a fasce (es. CCNL Cinema · Doppiaggio: prime 2h al +30%, dalla 2ª al +60%).
- `ccnl_label` String(120) nullable: etichetta libera del preset (es. "CCNL Cinema · Doppiaggio").

**Engine** `compute_assignment_breakdown`: se `overtime_brackets` valorizzato, le ore overtime non-night vengono distribuite negli scaglioni e pesate; altrimenti fallback al singolo `overtime_multiplier` (back-compat completa). Le ore notturne mantengono `night_multiplier` come prima.

**UI** `/settings#hours`: nuova sezione "Scaglioni overtime" con righe editabili (`from_hour` + `multiplier` + ✕), bottoni "+ Aggiungi scaglione" e "Rimuovi tutti". Campo `ccnl_label` come testo libero in alto. La compilazione manuale resta a carico dell'amministrazione; iter successiva: capability AI `propose_working_hours_policy` per popolare i preset CCNL via copilot.

Auto-migrate al boot per le 2 colonne nuove (`overtime_brackets TEXT`, `ccnl_label VARCHAR(120)`).

---

## v3.4.32.1 — Fix multi-risorsa + workflow overtime su drop + look timeline + temi/font (1 maggio 2026 sera)

Patch dopo test locale di v3.4.32. 6 fix raggruppati in un singolo bump.

### Fix #1 — Permessi multi-risorsa: override ben definito
L'operatore membro di un booking multi-risorsa ora può modificare il booking. `_enforce_planning_scope` riconosce il caso "operatore in `b.assignments`": permette la modifica e il cascade è ristretto alla SUA risorsa (non spinge i booking dei colleghi). Se il cascade ristretto produce conflitti su altre risorse, reject chiaro: "L'altra risorsa coinvolta ha un booking confliggente in quell'ora. Chiedi al manager/producer di gestire la modifica."

`extend_booking_adaptive` accetta nuovo parametro `restrict_cascade_to_resource_id`. Manager/producer/admin: cascade completo (come prima). Operatore singolo: cascade limitato.

### Fix #2 — Bottoni durata: 4 step ±15/±30
Card "Le mie" e dashboard "I miei booking di oggi": bottoni in ordine `−30 / −15 / +15 / +30`. Rimosso `+60` (richiesta esplicita).

### Fix #3 — Notifiche overtime: auto-approve self + diagnostiche client
Se chi estende ha già il permesso `approve_overtime`, l'overtime risultante viene auto-approvato (no self-notify spurious). Endpoint `/extend` ritorna `overtime_auto_approved_ids` e `overtime_notified_count`. Toast nella UI specifica esito: "auto-approvato (sei abilitato)" / "N approvatore/i notificati" / "in attesa (nessun altro approvatore)".

Aggiunte 3 icone al drawer notifiche: `🎬 booking_status_changed`, `🌙 booking_overtime_pending`, `🔔 booking_overtime_resolved`.

### Fix #4 — Drop su festivo → workflow overtime invece di hard block
Distinzione netta nel `bgItems` della timeline:
- **Hard block** (resta): `vacation` (ferie) + `sick` (malattia) → operatore non disponibile, drop rifiutato.
- **Soft block festività** (nuovo): `holiday` → drop ammesso con conferma. Visual: bordo arancione (classe `tl-conflict-overtime`). Confirm dialog: "Questo periodo cade in un giorno festivo. Il booking richiederà approvazione straordinario e sarà conteggiato con maggiorazione festiva. Procedere?".

Nuova logica server: `PUT /api/booking-assignments/{id}` dopo modifica chiama `_maybe_flag_overtime_on_assignment_change()`. Se l'assignment ora cade in fascia overtime / sabato / domenica / festivo, il booking riceve `overtime_status=pending` automaticamente + notifica agli approvatori. Idempotente: non ri-flagga se già pending/approved. Auto-approve se l'utente ha permesso `approve_overtime`.

### Fix #5 — Look timeline più ordinato
Vis-timeline options:
- `margin: {item: {horizontal: 0, vertical: 3}, axis: 6}` — overlap orizzontale completo (job consecutivi affiancati senza gap), spacing verticale ridotto.
- `groupHeightMode: 'fixed'` + `min-height: 38px` su `.vis-label` foglia + `28px` su `vis-nesting-group` → altezza riga uniforme indipendente dal contenuto, eliminata la "barra alta in testa".
- Font label risorse: `13.5px` (era 12.5), color `#f5f5f5`, `font-weight: 500`, allineamento verticale center via `display: flex; align-items: center`.

### Fix #6 — Aspetto: 5 temi nuovi + 6 varianti font
Temi colori (totale 9): aggiunti **Midnight** (blu profondo), **Copper** (rame caldo), **Plum** (viola creativo), **Teal** (verde acqua), **Mono** (grigi neutri B/N).

Tipografia (nuovo): variabili CSS `--font-body` / `--font-mono` con override per classe `.font-X` su `<html>`. 6 preset: **DM Sans** (default), **Inter**, **Roboto**, **IBM Plex**, **Source Sans**, **System UI**. Persistenza in `localStorage` (`mf_font`). Pannello "🎨 Aspetto" → sezione "Tipografia" con preview live di ogni font.

Tutti gli usi diretti di `font-family: 'DM Mono', monospace` in `main.css` sostituiti con `var(--font-mono)` per propagare la scelta a numeri/codici.

---

## v3.4.32 — Booking esecutivo: priorità + stato esecuzione + workflow overtime + pozzo not_done (1 maggio 2026)

Cantiere "booking come unità operativa". Trasforma il booking da pura intenzione di pianificazione a oggetto governabile dall'operatore: priorità visibile per colore, ciclo di vita planned→in_progress→done|not_done con motivazione, modifica durata adattiva con cascade intra-day, workflow approvazione straordinari basato su `WorkingHoursPolicy`, sezione cost report dedicata + pozzo ore non maturate.

> **Distinzione strategica chiarita** (memoria `project_costreport_vs_timesheet.md`): cost report = quotazioni + booking + hardcost (lente cliente/finance/fatturazione). Timesheet/TimePunch = HR + amministrazione (lente consulente del lavoro/buste paga). Due binari separati comunicanti solo nel planning per disponibilità risorse. v3.4.32 è il primo passo del rifacimento del cost report verso questa visione.

### Modello — 5 colonne nuove su `bookings`

```
priority               ENUM (low|normal|high)         default 'normal'
execution_status       ENUM (planned|in_progress|     default 'planned'
                              done|not_done)
not_done_reason        TEXT NULL
count_in_costs         BOOLEAN                        default 0
overtime_status        ENUM (none|pending|            default 'none'
                              approved|rejected)
original_end_datetime  DATETIME NULL    (snapshot per supportare split overtime)
```

`execution_status` è **ortogonale** a `status` (tentative/confirmed/cancelled/completed): il primo è la lente operatore, il secondo l'intenzione di pianificazione.

### NotificationKind nuovi

- `booking_status_changed` → producer/manager/admin quando un operatore marca `done` (info) o `not_done` (action_required, motivazione nel body)
- `booking_overtime_pending` → chi ha permesso `approve_overtime` quando un cascade extend porta booking in fascia overtime
- `booking_overtime_resolved` → operatore (autori del booking) quando il manager approva/rifiuta lo straordinario

### Permesso nuovo: `approve_overtime`

Mappato sui ruoli built-in admin/manager/producer (operator/viewer no). Configurabile in `/admin/roles` come tutti gli altri permessi. La migrazione idempotente `[L]` aggiunge il permesso ai 3 ruoli esistenti senza toccare i ruoli custom.

### Servizi nuovi

**`app/services/booking_cost.py`** — engine costo per booking. Contrariamente a `overtime.py` (che opera sui TimePunch HR e usa la soglia giornaliera), qui l'overtime è basato sulla **fascia oraria** della policy: ore fuori da `morning_start..morning_end` + `afternoon_start..afternoon_end` sono overtime indipendentemente dal totale giornaliero. Più adatto al booking: l'operatore sa subito se sta lavorando in straordinario in base all'orario.

`compute_assignment_breakdown(assignment, policy, holidays_set, booking)` ritorna `BookingBreakdown` con: `regular_hours`, `overtime_hours`, `night_hours` (sotto-quota di overtime), `sunday_hours`, `holiday_hours`, `pending_overtime_hours` (mostrate ma non pesate finché approved), `not_done_pool_hours` (escluse dal weighted), `weighted_factor` (ore equivalenti dopo coefficienti CCNL).

Helper: `has_overtime_window(start, end, policy)`, `working_day_end(date, policy)`, `absolute_day_limit(date, policy)` (=`night_end` del giorno dopo, default 06:00 — D2=c).

**`app/services/booking_cascade.py`** — cascade adattivo intra-day.
- `extend_booking_adaptive(booking, delta_min, db)`: estende `booking.assignments` di Δ. Per ogni risorsa coinvolta, sposta in avanti i booking adiacenti dello stesso giorno (start ≥ vecchio_end). Mai slittamento al giorno successivo (D3). Se il cascade fa entrare uno o più booking in fascia overtime → `overtime_status=pending` automatico + audit log. Limite assoluto: nessun booking sfora `absolute_day_limit` (= `night_end` giorno dopo) → reject con messaggio.
- `split_overtime_to_next_day(booking, db)`: usato su rifiuto overtime. La parte regolare (≤ `working_day_end`) resta sul giorno corrente, la coda overtime diventa nuovo Booking il giorno successivo da `morning_start` (D1).

### Endpoint API

- `PATCH /planning/api/bookings/{id}/priority` Form `priority` (low|normal|high)
- `PATCH /planning/api/bookings/{id}/execution` Form `execution_status` + opzionale `not_done_reason` (obbligatoria se → not_done). Notifica producer/manager/admin sui passaggi → done | not_done. → in_progress: silenzioso.
- `PATCH /planning/api/bookings/{id}/extend` Form `delta_minutes` (max ±1440). Ritorna `CascadeResult` con `moved_assignments`, `overtime_pending_booking_ids`, `rejected`, `reject_reason`. Notifica gli approvatori overtime per ogni booking entrato in pending.
- `POST /planning/api/bookings/{id}/overtime` Form `decision` (approved|rejected) + opzionale `reason`. Approvato → ore conteggiate con `overtime_multiplier`. Rifiutato → split + nuovo booking giorno successivo. Notifica operatore con esito.
- `PATCH /planning/api/bookings/{id}/count-in-costs` Form bool. Manager/producer flag pool not_done → True per recuperare le ore nei costi.
- `GET /planning/api/my-bookings` (`today_only=true|false`) — endpoint dedicato per la card "Le mie" + dashboard "I miei booking di oggi". Arricchito con priority/execution_status/overtime_status/duration_minutes/job_code/cost_line_description.

`GET /planning/api/bookings` (esistente) ora include `priority`, `execution_status`, `overtime_status`, `not_done_reason`, `count_in_costs` in `extendedProps`.

### UI

**`/planning` tab "Le mie"** — completamente riscritta. Card con bordo sinistro per priorità (grigio/blu/rosso), badge stato esecuzione, badge straordinario pending (bordo arancione pulsato), riga durata con bottoni `−30 / +30 / +60` (drag handle ± richiesto), select priorità inline, bottoni azione `▶ Inizia / ✓ Fatto / ✗ Non fatto / ↺ Riapri`. Modal motivazione su "Non fatto". Stati `done/not_done` mostrano opacità ridotta + lock azioni di cambio durata.

**Dashboard `/`** — nuova card "I miei booking di oggi" sopra la tabella generica, visibile solo se utente ha `Resource` collegata. Stesse azioni di "Le mie". Tabella generica "Booking di oggi · tutti" estesa con colonne **Priorità**, **Esecuzione**, **Straord.** (richiesta esplicita: "Mostra gli stati di tutti i bookings nella dashboard dei manager").

**Cost report `/cost-report` → sezione progetto** — due card nuove sotto i KPI:
- **"⏱ Ore booking per fascia"** — KPI cards (Regolari, Straordinario approvato, Pending, Notturno, Domenica, Festivo, Ore equivalenti dopo coefficienti). Tabella per risorsa con costo stimato.
- **"⏳ Pozzo ore non maturate"** — elenca booking `not_done` con `count_in_costs=False`. Per riga: "✓ Maturate" (flag count_in_costs=True → entra nei costi) / "🗑 Scarta" (booking → cancelled, ore mai conteggiate).

Endpoint cost report: `GET /cost-report/api/job/{id}/booking-summary`, `POST /cost-report/api/job/{id}/not-done-pool/{bid}/discard`.

### Migrazione `[L]` (idempotente)

`scripts/migrate_booking_executive.py` aggiunge le 6 colonne via ALTER TABLE + mappa `approve_overtime` ai ruoli built-in admin/manager/producer (additivo, non sovrascrive). Voce `[L]` in `strumenti.bat`/`.sh`.

Auto-migrate al boot: `_auto_migrate_columns()` in `main.py` controlla la presenza delle 6 colonne e le aggiunge se mancanti (lezione v3.4.25.1 — evita crash se utente fa pull senza lanciare migration). Nota: il default su SQLite richiede valori espliciti per le colonne enum (`'normal'`, `'planned'`, `'none'`).

### Comportamento atteso

| Azione operatore | Notifica | Audit log |
|---|---|---|
| Cambia priorità | nessuna | priority |
| → in_progress | nessuna (rumore evitato) | execution |
| → done | producer+manager+admin (info) | execution |
| → not_done | producer+manager+admin (action_required, motivazione) | execution |
| Estende +Δmin → cascade entra in overtime | approvatori overtime (action_required) | adaptive_extend + overtime_pending |
| Estende +Δmin → sforerebbe night_end+1d | rifiutato 409 | nessun cambio |
| Producer/Manager approva overtime | operatore (info) | overtime_approved |
| Producer/Manager rifiuta overtime | operatore (info, +new_booking_id) | overtime_rejected + overtime_split |

### Limiti riconosciuti / cantieri seguenti

- Cost report `legacy` `/cost-report/api/job/{id}` ancora basato su `Timesheet` per le ore. Coabita con `/booking-summary`. Rifacimento completo del cost report (tutto da `Booking` + `Expense`) è cantiere a sé, da pianificare.
- Coefficienti CCNL: oggi `WorkingHoursPolicy` ha valori "tipici Italia" (overtime 1.25, notte/dom 1.50, festivo 2.00). I CCNL specifici post-prod (Cinema, Pubblicità, ecc.) saranno seedabili come preset di policy in iterazione successiva. Memoria `project_normativa_ccnl.md` salvata.
- Cascade: solo "stessa risorsa". Booking multi-risorsa con assignment di durata diversa: il cascade processa ogni assignment singolarmente. Conflitti tra risorse non gestiti (mantenuto comportamento esistente di `extend` che non fa conflict-check tra adjacenti già esistenti).
- Pool not_done azione "↻ Riprogramma" non implementata in v3.4.32 (creazione nuovo booking sostitutivo). Per ora "Maturate" (count nei costi) o "Scarta" (cancellato).

---

## v3.4.31 — Scheda tecnica progetto + link pubblico (1 maggio 2026)

Cantiere "scheda tecnica" (G nel backlog). Workflow sheet di un progetto: catena di lavorazione (camere, audio, look, storage, dailies, crew, process). Schema flessibile JSON per varianti tra case di post diverse.

> **Distinzione netta** dal modello esistente `DeliveryTemplate`: il `ProjectTechSheet` descrive la *catena di produzione* (3 PDF di esempio in `docs/workflow_esempio/`: ISIDE, Gomorra, FUME). Il `DeliveryTemplate` resta per le *specs di consegna* (Netflix, A24, Vision…). Il primo può linkare al secondo via `delivery_template_id` opzionale.

### Modello `ProjectTechSheet` (1:1 con Project)

```
id, tenant_id, project_id (UNIQUE), delivery_template_id (FK opt)
version (str), status (draft|preview|approved)
approved_by_user_id, approved_at
public_token (UUID-safe nullable), is_public_enabled, expires_at, published_at
data (JSON) ─ sezioni: general, cameras[], audio, looks[], storage, dailies,
             folder_struct, contacts[], process, notes
created_at, updated_at
```

Tabella creata automaticamente da `Base.metadata.create_all()` al boot (no migration script).

### Endpoint

- `GET /projects/api/{pid}/tech-sheet` — auto-crea draft se manca (auth: `view_projects` o `edit_projects`)
- `PUT /projects/api/{pid}/tech-sheet` — accetta JSON body `{version, status, delivery_template_id, data}` (auth: `edit_projects`)
- `POST /projects/api/{pid}/tech-sheet/publish` — Form `expires_days` (default 90, 0=senza scadenza), `rotate_token` (bool)
- `DELETE /projects/api/{pid}/tech-sheet/public` — disattiva link
- `GET /public/tech-sheet/{token}` — vista readonly **no auth**, ritorna 410 Gone se scaduto, 404 se token revocato

`PUBLIC_PATHS` in `main.py` esteso con `/public/` per saltare auth guard.

### UI editor — tab "🛠 Scheda tecnica" in `/projects/{id}`

- Sub-tabs: Generale · Camere · Audio · Look · Storage · Dailies · Crew · Process · Note.
- **Camere come array**: aggiungi/rimuovi camere (A/B/C/D…) con specs indipendenti (FUME-style: A≠B). Ottiche come lista per camera.
- **Look multipli**: array di LUT/LMT con scope (main/flashback/etc), tipo (ASC-CDL/Powergrade), 3DLUT size, range transform.
- **Crew**: lista contatti free-form (ruolo + nome + email + telefono). Resource link rinviato a iter successiva (per ora `name_text`).
- Lista campi (burnins, report recipients, notify emails) come textarea "uno per riga" → array.
- Toolbar: version + status + delivery_template dropdown + bottone "🔗 Link pubblico". Indicatore dirty/saved.
- Salvataggio esplicito tramite "💾 Salva modifiche" (non auto-save).

### Vista pubblica `/public/tech-sheet/{token}`

- Template `pages/tech_sheet_public.html` standalone (no sidebar, no topbar).
- Layout pulito: header con titolo/codice/regista + sezioni espanse con tutti i campi compilati.
- Pagina errore `tech_sheet_public_error.html` per token scaduto/revocato.
- Footer con data ultima modifica + scadenza link.

### Pubblicazione

- Modal con dropdown scadenza (30/60/90/180/365 giorni o senza scadenza).
- Bottone "Rigenera token" per invalidare il link precedente (security best practice).
- Display URL completa con copy-to-clipboard.
- Bottone "Disattiva link" dal modal stesso se già pubblicato.

### Estensione `api()` in `global.js`

`api(method, url, body, options)` ora accetta opzioni: `{json: true}` invia il body come JSON (`Content-Type: application/json`). Compatibile con tutte le chiamate esistenti FormData/urlencoded. Cache-buster `?v=3.4.31`.

### Cosa è esplicitamente fuori da questa versione

- Import auto-popolazione campi da capitolato (Netflix Specs / A24 / ecc.) via AI: cantiere a sé per v3.4.32+.
- Crew come FK Resource (oggi solo `name_text`): rinviato a quando serve query incrociate.
- Storage policy come oggetto separato riusabile: oggi inline, da estrarre se ricorrenza concreta.
- Datarate auto-calcolato da camera+formato+fps: oggi manuale.

File toccati: `app/models/models.py`, `app/models/__init__.py`, `app/routers/tech_sheets.py` (nuovo), `app/main.py`, `app/static/js/global.js`, `app/templates/pages/project_detail.html`, `app/templates/pages/tech_sheet_public.html` (nuovo), `app/templates/pages/tech_sheet_public_error.html` (nuovo), `app/templates/base.html`.

## v3.4.30 — Vista calendario complessiva in /hr (1 maggio 2026)

In `/hr` toggle "📋 Tabella timbrature | 📅 Calendario complessivo". Vista calendario mensile con sommario per categoria, ferie/malattia/permessi inclusi.

### Backend

- Endpoint **`GET /hr/api/calendar?from_date&to_date&resource_id`**:
  - Per ogni giorno restituisce `{date, regular_h, overtime_h, night_h, vacation_h, sick_h, other_h, total_h, resource_count, unav_kinds}`.
  - **Single-resource**: usa `compute_overtime` con la policy della risorsa per il breakdown preciso (regolari/overtime/notturne).
  - **All-resources**: somma cross-tenant le timbrature shift+overtime e raggruppa per giorno (no split per policy diverse).
  - **Ferie/malattia/permessi** da `ResourceUnavailability.status=approved` → ore = `daily_hours_threshold` × giorni nel range, attribuiti per `kind`.
  - Rispetta `_enforce_scope`: staff vede solo le proprie ore, manager vedono tutto.
  - Restituisce anche `totals` aggregati di periodo per i KPI cards.

### UI

- Toggle `Tabella | Calendario` sopra i filtri (preferenza salvata in `localStorage` → `mf_hr_view`).
- Vista calendario:
  - Toolbar con navigazione mese (prev/next/oggi) + label "Maggio 2026".
  - 7 KPI compatti: Regolari · Straordinari · Notturne · Ferie · Malattia · Permessi · Totale.
  - Griglia 7×6 (Lun-Dom × 6 settimane) con celle giorno mostranti barre per categoria > 0.
  - Evidenziazioni: oggi (bordo indaco), weekend (sfondo tenue), giorni con ferie (sfondo viola), malattia (sfondo rosso), giorni di altri mesi opacizzati.
  - **Click su giorno** → switch a vista Tabella con filtro `from=to=quel giorno` per dettaglio.
- Cambio del filtro Risorsa nei filtri principali aggiorna anche il calendario se aperto.

File toccati: `app/routers/hr.py` (nuovo endpoint), `app/templates/pages/hr.html` (CSS + UI + JS).

## v3.4.29 — Listino laterale + drag&drop in editor quote (1 maggio 2026)

In `/quotes` editor: bottone "📋 Listino" in topbar apre/chiude un pannello laterale destro fisso accanto al riepilogo economico. Le voci di listino sono draggable e si possono trascinare direttamente nella tabella "Voci preventivo" per aggiungerle alla quote.

- **Toggle pannello** persistito in `localStorage` (`mf_side_pricelist_open`): se l'avevi attivato, riapre automaticamente alla prossima quote.
- **Layout grid**: 2 colonne default (editor + riepilogo) → 3 colonne con listino aperto. Responsive: collassa in stack su <1024px.
- **Ricerca**: stesso match di `alMatchesText` (nome, descrizione, categoria, reparto, keywords). Limite render 80 voci per fluidità.
- **Drag&drop**: HTML5 native API con MIME custom `application/x-mf-priceitem`. Drop target = tutta la card "Voci preventivo" (`#lines-card`), evidenziata con bordo indaco durante hover.
- **Drop = POST** `/quotes/api/{id}/lines` con `price_item_id` + `quantity=1`, prezzo/unità ereditati dal listino, descrizione = `name`. Reload quote per vedere subtotali/sconti aggiornati.
- Modal "+ Aggiungi voce" mantenuto come alternativa (utile per voce libera o input rapido tastiera-only).

File toccati: `app/templates/pages/quotes.html`. Nessun cambio backend (riusa endpoint esistenti).

## v3.4.28 — Fix sidebar + engine notifica job_deadline_approaching (1 maggio 2026)

Due cantieri in una versione.

### A — Fix riordino sidebar (auto-discovery + per-sezione)

Sintomo: dopo aver toccato il drag&drop in `/settings#sidebar`, la sidebar nelle altre pagine veniva "compromessa" — voci impilate senza separatori, con voci come `hr`, `assignments`, `admin_users`, `admin_roles` che apparivano in fondo o sparivano dall'elenco di riordino.

Causa doppia:
1. `NAV_ITEMS_DEF` in `settings.html` era una lista hardcoded di 12 voci, mentre `base.html` ne ha 14 (più condizionali per ruolo). Le voci mancanti non comparivano nel pannello di riordino e venivano relegate in coda dall'`applySidebarOrder`.
2. `applySidebarOrder()` faceva flatten di tutte le sezioni in un unico container `.nav-section nav-section-custom`, perdendo le label "Anagrafica", "Operativo", … e l'identità visiva dei raggruppamenti.

Fix generico (no patchwork):
- **Auto-discovery**: il pannello di `/settings#sidebar` ora legge la sidebar reale dal DOM (`.sidebar-nav .nav-item[data-nav-id]` raggruppati per `.nav-section`). Niente più liste duplicate da mantenere — quando si aggiunge una voce in `base.html` appare automaticamente.
- **Riordino per-sezione**: drag&drop opera dentro ciascun gruppo (Principale, Anagrafica, Operativo, Preventivi, Finanza, Media, Configurazione, Amministrazione). Le label di sezione restano intatte.
- **Format salvato**: object `{sectionName: [navId, …]}` invece di array piatto. Il vecchio formato viene ignorato silenziosamente (default torna ad applicarsi).
- Reset disponibile via "Ripristina ordine default".

File toccati: `app/templates/pages/settings.html`, `app/static/js/global.js`. Cache-buster `?v=3.4.28` su `base.html`.

### B — Engine notifica `job_deadline_approaching`

Cantiere riusabile dal pattern v3.4.27 (sistema notifiche). Emette `kind=job_deadline_approaching` quando un Job ha `end_date` imminente.

- **Servizio** `app/services/job_deadline_check.py` — `check_job_deadlines(db)`:
  - Soglie: 1 giorno (`action_required`), 3 giorni (`action_required`), 7 giorni (`info`).
  - Esclude job in stati `completed`, `cancelled`, `invoiced`.
  - **Idempotente**: prima di emettere verifica `Notification.payload->>'job_id'+'threshold_days'` nelle ultime 14 giorni; se già emesso skippa.
  - Notifica via `notify_permission("assign_resources")` → producer/manager/admin/operator (chi gestisce davvero pianificazione job).
  - Payload contiene `job_id`, `job_code`, `end_date`, `days_left`, `threshold_days` per dedup e link.
- **Lifespan startup** in `main.py`: chiama `check_job_deadlines()` al boot. Riavvio server = check immediato, zero-config.
- **Endpoint trigger** `POST /admin/api/check-deadlines` (richiede `manage_settings_global`) per eseguire on-demand.
- **Job di test**: `scripts/seed_test_deadline.py` (idempotente) crea/aggiorna `JOB-TEST-DEADLINE` con `end_date = today + 2`. Voce `[T]` aggiunta a `strumenti.bat`/`strumenti.sh`.

Estendibilità: futuri eventi periodici (cron via /schedule) chiamano `check_job_deadlines()` o servizi simili. Gli stessi pattern di soglie + dedup-by-payload sono riusabili per `quote_status_changed`, `booking_conflict`, ecc.

## v3.4.27 — Sistema notifiche generico + UI approvazione ferie (30 aprile 2026 notte tarda)

Cantiere generico riusabile per qualsiasi futura notifica (workflow ferie, conflitti booking, deadline, alert sistema, ecc.). Pattern AI propone / utente dispone esteso a "sistema notifica / utente apre".

### Modello

- `Notification(id, tenant_id, user_id, actor_user_id, kind, severity, title, body, link, payload JSON, is_read, is_archived, created_at, read_at)`
- Pattern una-row-per-destinatario (multi-recipient = N rows). Più semplice per `unread_count` e `mark_read` per-utente.
- Enum `NotificationKind` con 7 valori iniziali (3 per workflow ferie + 4 riservati per cantieri futuri: booking_conflict, quote_status_changed, job_deadline_approaching, custom).
- Enum `NotificationSeverity`: info / action_required / alert.
- Indici su `(user_id, is_read, created_at desc)` per query veloci sul polling.

### Servizio centrale (`app/services/notifications.py`)

Single point per emit:
- `notify(db, user_ids=[...], kind, title, severity, body, link, payload, actor)` — base
- `notify_permission(db, permission="approve_unavailability", ...)` — broadcast a chi ha quel permesso
- `notify_role(db, role_codes=[...], ...)` — broadcast a ruoli
- `mark_read(db, user, ids)` / `mark_all_read(db, user)`
- `unread_count(db, user) → {total, action_required}`
- `list_for_user(db, user, only_unread, include_archived, limit, offset)`
- `archive(db, user, id)` (soft)
- `cleanup_old(db, days=90)` — soft-archive notifiche lette > 90gg

### Endpoint REST (`/notifications/api/*`)

- `GET /unread-count` — lightweight per polling 30s (ritorna `{total, action_required}`)
- `GET /list?only_unread=&include_archived=&limit=&offset=`
- `POST /{id}/read`
- `POST /mark-all-read`
- `DELETE /{id}` (soft archive)

### Hook iniziali (workflow ferie/malattia)

| Evento | Destinatari | Severity |
|---|---|---|
| `create_unavailability(status=pending)` | tutti con `approve_unavailability` (escluso il richiedente) | action_required |
| `approve_unavailability` | richiedente | info |
| `reject_unavailability` | richiedente (con `rejection_reason` nel body) | action_required |

### UI

- **Topbar campanella 🔔** in `base.html` (sempre visibile per utenti loggati): badge counter rosso (giallo se ci sono `action_required`).
- **Drawer notifiche** laterale destra (`components/notifications.html`): lista con icona-per-kind, titolo, body, tempo relativo (Ora / N min fa / Nh fa / data). Click su notifica = mark_read + redirect al `link`.
- **Polling 30s** automatico su `/unread-count` (basso costo).
- **Bottone "Tutte lette"** in header drawer.
- **Card "🔔 Richieste in attesa"** in `/hr/` per chi ha `approve_unavailability`: lista pending con bottoni Approva / Rifiuta (con motivo opzionale via prompt). Auto-refresh post-azione + ping `notifFetchUnread()`.

### Conseguenze e interazioni

- **Multi-tenant hard (Fase 7)**: `tenant_id` già pronto.
- **Portale cliente futuro**: stesso modello, basta filtrare per `client_id` (richiederà piccola estensione).
- **Cantieri futuri**: emit di `booking_conflict` quando si crea un booking sovrapposto, `job_deadline_approaching` come cron (cantiere /schedule), `quote_status_changed` quando il client accetta/rifiuta. Tutti già supportati lato modello.
- **Audit**: ogni notification è una traccia di chi-quando-cosa, utile per workflow di approvazione.

### Migrazione

Nessuno script: la tabella `notifications` viene creata automaticamente da `Base.metadata.create_all()` al boot tramite `create_tables()`. Idempotente.

## v3.4.26 — Spostamento richiesta ferie da planning a /hr ("Le mie ore") (30 aprile 2026 notte)

In v3.4.24 avevo messo la card richiesta ferie + riepilogo ore nel tab "✓ Le mie" del planning. Matteo: la voce sidebar "Le mie ore" è la pagina `/hr/`, non quella → spostato lì.

- `/hr/` ora mostra (solo per utenti con Resource collegata):
  - **Riepilogo ore** del periodo filtrato (regolari · straordinari · notturne · ferie · malattia · totale)
  - **Form richiesta ferie/malattia/permesso** + lista delle proprie con stato pending/approved/rejected
- `/planning/` tab "✓ Le mie" torna a contenere SOLO la lista attività programmate, con un piccolo banner che linka a `/hr/`
- Modal timbratura: helper text aggiornato ("→ sezione qui sotto" invece di "→ planning").

## v3.4.25.1 — Hotfix auto-bootstrap users.extra_permissions (30 aprile 2026 notte)

In v3.4.25 ho aggiunto la colonna `users.extra_permissions` ma se l'utente fa pull e riavvia il server senza lanciare la migrazione `[K]`, il login crasha con `OperationalError: no such column: users.extra_permissions`.

- Aggiunto `_auto_migrate_columns()` nel lifespan di `app/main.py`: al boot fa `ALTER TABLE users ADD COLUMN extra_permissions TEXT NULL` se la colonna manca. Idempotente.
- Lo script `scripts/migrate_user_extra_permissions.py` resta utile (esplicito + visibile nei log), ma non è più strettamente obbligatorio per single-user dev DB.

## v3.4.25 — Permessi extra per-utente (30 aprile 2026 notte)

Permessi del singolo utente ora = permessi del ruolo + extra individuali (additivi).

### Modello

- Nuova colonna `users.extra_permissions: JSON NULL` (lista di chiavi `PERMISSIONS`).
- `_user_permissions(user)` in `rbac.py` ora unisce: ruolo + `extra_permissions`.
- Solo additivi: non è possibile sottrarre permessi del ruolo dal singolo utente. Per sottrazioni serve un ruolo custom dedicato.

### API

- Nuovo `PUT /admin/api/users/{id}/permissions` con form `extra_permissions=csv`.
- Validazione: solo chiavi presenti in `ALL_PERMISSION_KEYS`.
- Pulizia automatica: chiavi già coperte dal ruolo vengono scartate per evitare ridondanza.

### UI modal `/admin/users` (edit mode)

- Sezione "Permessi extra" sotto l'anteprima del ruolo.
- Matrix per categoria: i permessi del ruolo appaiono già checked + disabled (etichetta "(da ruolo)" + grigio), gli altri sono toggle attivabili.
- Counter "N attivi" live.
- Salvataggio integrato nel flusso `Salva utente`.

### Migrazione

- `scripts/migrate_user_extra_permissions.py` — opzione `[K]` su `strumenti.bat/sh`. Idempotente.

## v3.4.24.1 — Hotfix cache-buster global.js (30 aprile 2026 notte)

In v3.4.24 ho aggiunto `escapeHtml` a `app/static/js/global.js` ma ho dimenticato di bumpare il querystring `?v=` in `base.html`. Il browser continuava a servire la versione cached (`?v=3.2.1`) → bug `escapeHtml is not defined` persisteva su `/admin/users`, `/admin/roles`, `/hr`, ecc.

- `base.html`: `global.js?v=3.2.1` → `?v=3.4.24.1`.
- **Regola**: ogni volta che modifico `static/js/global.js` o `static/css/main.css`, devo bumpare il cache-buster nel template che li include.

## v3.4.24 — UX feedback Matteo: bug escapeHtml + ferie/malattia in Le mie ore + cleanup overtime (30 aprile 2026)

Bump dedicato ai 4 punti emersi nei test sul Mac di v3.4.23.

### Bug fix critico — `escapeHtml` non definito globalmente

`/admin/users` e `/admin/roles` crashavano al caricamento con `ReferenceError: escapeHtml is not defined`. La funzione era ridefinita localmente in 5 template ma non in `global.js`, e i due template admin nuovi non avevano la copia locale.

- Aggiunto `escapeHtml(s)` in `app/static/js/global.js` (helper globale).
- Rimosse le 4 definizioni locali ridondanti (resources, hr, planning, job_detail).
- **Conseguenza**: l'auto-User da Resource funzionava già correttamente (l'utente *veniva* creato), ma la pagina `/admin/users` crashava su `loadUsers()` e l'utente sembrava sparito. Stesso bug anche su `/admin/roles`.

### Modal timbratura — rimossa scelta manuale "Straordinario"

Lo straordinario è un calcolo deterministico (no AI) basato su `WorkingHoursPolicy` + `compute_overtime()`. La voce `overtime` nel dropdown del modal timbratura era ridondante e fuorviante.

- `hr.html` modal punch: solo **Turno** e **Pausa** come opzioni manuali.
- Aggiunto helper text esplicito: "Lo straordinario viene calcolato automaticamente in base alla policy oraria".
- Edit di record storici con `kind=overtime`: vengono aperti come `shift` (mini-migrazione opportunistica al primo salvataggio).

### Ferie/malattia in "Le mie ore" + conteggio rendicontazione

La vista `/planning/` tab "✓ Le mie" ora include 3 sezioni:

1. **Riepilogo ore** del mese corrente (o periodo filtrato): regolari · straordinari · notturne · ferie · malattia · **totale**. Card a 6 KPI con colori distinti.
2. **Le mie ferie e malattie**: form richiesta inline (kind, da/al, motivo) + lista delle proprie richieste con stato (⏳ in attesa / ✅ approvata / ❌ rifiutata) + bottone annulla per richieste pending.
3. **Attività programmate** (booking + timbrature): comportamento precedente, invariato.

Endpoint nuovi/estesi:
- `GET /planning/api/my-unavailabilities` — lista delle proprie richieste con tutti gli status (vs `/api/unavailabilities` che ritorna solo approvate per la timeline).
- `GET /hr/api/overtime` esteso con campi `unavailability` (vacation_days/hours, sick_days/hours, other_days/hours) e `grand_total_hours` (lavorate + ferie + malattia + altro). Conversione giorni→ore con `daily_hours_threshold` della policy.

### Anteprima permessi nel modal utente

Sotto la dropdown Ruolo in `/admin/users`, badge dei permessi inclusi nel ruolo selezionato, raggruppati per categoria. Aggiornato live al cambio di selezione e mostrato in apertura modal (sia create che edit). Link "Modifica permessi →" punta a `/admin/roles`.

---

## v3.4.23 — Permessi configurabili + pannello admin utenti/ruoli + auto-User da Resource (30 aprile 2026)

Sistema RBAC v2: 6 preset built-in + ruoli custom configurabili dall'admin.

### Modello

- Nuovo modello `Role` (tabella `roles`):
  - `code`, `name`, `description`
  - `permissions: JSON` lista di stringhe (chiavi granulari)
  - `is_system: bool` (preset built-in non eliminabili)
  - `is_active`
- `User.role_id` FK opzionale a `roles` (legacy enum `User.role` mantenuto per back-compat)
- 6 **preset built-in** creati automaticamente al boot via `ensure_built_in_roles()`:
  - **admin**: tutti i 23 permessi (matrice non modificabile)
  - **manager**: tutto tranne `manage_users`/`manage_roles`/`manage_settings_global`
  - **producer**: full progetto + finanza view, no editing listino, no fatture
  - **accounting**: solo view finanziaria + fatturazione
  - **operator**: scope auto su Resource (planning/punches own), info tecniche progetti
  - **viewer**: sola lettura

### Permessi

23 chiavi granulari in 6 categorie (Anagrafica, Pianificazione, HR/Timbrature, Finanza, Risorse, Configurazione). Aggiungerne uno in `app/services/rbac.py:PERMISSIONS` lo rende automaticamente disponibile nella UI matrix.

### Pannello admin

- **`/admin/users`**: lista utenti, edit ruolo, attiva/disattiva, reset password con credenziali one-shot, soft-delete. Solo `manage_users`.
- **`/admin/roles`**: split-pane lista ruoli + editor permessi a checkbox per categoria. CRUD ruoli custom (clone da preset). Built-in non eliminabili. Admin role permessi non modificabili. Solo `manage_roles`.
- Voce sidebar "Amministrazione" con icone 👤 Utenti / 🔐 Ruoli e permessi.

### Auto-User da Resource personale

- Modal `/resources` person_internal/freelance: toggle "Crea utenza con accesso al sistema"
- Quando attivo: email obbligatoria, password temp generata (12 char alfanumerici readable), ruolo iniziale scelto da dropdown (default operator), User collegato via `Resource.user_id`
- Credenziali mostrate UNA SOLA VOLTA dopo creazione

### rbac.py riscritto

- `has_permission(user, "key") -> bool` legge da `User.role_obj.permissions` (JSON), fallback a preset enum legacy
- Tutti i `can_*` legacy (can_view_finance, can_edit_settings, …) ora chiamano `has_permission`
- Nuovo `requires_permission(*perms)` dependency per protezione fine
- Eager-load `User.role_obj` in `_resolve_user_from_token` (auth_guard) per evitare DetachedInstanceError nei template

### Bug fix

- **`/hr/` 500**: conflitto context Jinja `is_elevated` (chiave bool) shadowsa il global function. Rinominato a `user_is_elevated`
- **Drag inerziale timeline**: `transition: transform .12s` su `.vis-item` faceva scivolare gli item durante drag. Rimosso `transform` dalla transition (resta solo box-shadow + filter per hover)
- **"Nuovo progetto"** hidden a staff/operator (sia bottone UI che endpoint POST `/projects/api`)

### Migrazione

`scripts/migrate_roles_v2.py` (opzione `[J]` su `strumenti.bat/sh`):
- CREATE TABLE `roles` via Base.metadata
- ALTER TABLE users ADD COLUMN role_id
- Bootstrap 6 preset
- Mappa utenti esistenti dall'enum legacy (`admin`→admin, `staff`→operator, ecc.)

## v3.4.22 — RBAC + workflow ferie + timbratura semplificata + UX (30 aprile 2026)

Sessione lunga: 6 cantieri E/D/C/B/A/F in una passata.

### E — RBAC ruoli e permessi

- Nuovo ruolo **`producer`** (oltre admin/manager/staff/viewer)
- `app/services/rbac.py`: helpers `is_admin/manager/producer/staff/elevated`, `can_view_finance`, `can_edit_settings`, `can_assign_resources`, `can_approve_unavailability`, dependency `current_user(request)`, `requires_role(*roles)`, `scope_resource_id(db, user)` (link User↔Resource via `Resource.user_id`)
- Helpers esposti come globals Jinja per condizionali UI (`{% if can_view_finance(user) %}`)
- **Auth guard** middleware esteso con blacklist path/role:
  - Staff/viewer: niente `/quotes`, `/cost-report`, `/finance`, `/pricelist`, `/clients`, `/assignments`, `/resources`
  - Solo admin: `/departments`, `/settings/api/working-hours`, `/settings/api/ai`
  - 403 con pagina HTML pulita (no JSON crudo)
- **Sidebar conditional**: nasconde Quotazioni/Cost Report/Fatturazione/Listino/Reparti/Impostazioni a non-elevated; mostra "Le mie ore" invece di "Ore lavoro" per staff
- **HR scope auto** (`/hr/*`): staff vede e modifica solo le proprie timbrature. Helper `_enforce_scope(request, db, requested_resource_id)` usato in tutti gli endpoint API
- **Planning scope** (`/planning/api/bookings`, `/planning/api/booking-assignments`): staff può creare/modificare/cancellare booking solo per la propria risorsa
- **Project detail**: tab Quotazioni nascosto a staff, colonna Budget rimossa nei job, bottone "+ Nuova quotazione" hidden
- Robustezza JS: `getElementById` null-safe per evitare errori sulle sezioni nascoste

### D — Workflow approvazione ferie/malattia/permessi

- `ResourceUnavailability` esteso con: `status` (pending/approved/rejected), `requested_by_user_id`, `approved_by_user_id`, `approved_at`, `rejection_reason`, `created_at`
- Nuovo enum `UnavailabilityStatus`
- **POST `/api/unavailabilities`**: staff → status=pending (richiesta), elevated → status=approved (azione diretta)
- **GET `/api/unavailabilities/pending`**: lista richieste in attesa (solo elevated)
- **POST `/api/unavailabilities/{id}/approve`** + **`/reject`** (elevated only)
- **DELETE `/api/unavailabilities/{id}`**: staff può cancellare solo le proprie richieste pending
- Solo `status=approved` blocca planning (smart split, suggest-resources, timeline overlay)
- Migrazione `[I]` `migrate_unavailability_approval.py` (idempotente, backfill record esistenti come 'approved' per back-compat)

### C — Timbrature semplificate + visibility timeline

- Modal `/hr` Nuova timbratura:
  - Job/lavorazione **rimossi** per staff (legame inferito dai booking pianificati)
  - Job opzionale solo per elevated (manager/producer/admin) per ricostruzioni manuali
  - Per staff: solo `kind` shift/overtime/break — ferie/malattia vanno via richiesta approvazione
  - Box durata live con preview overtime (`>8h` → highlight arancione)
- **Overlay timbrature in `/planning` Resource Timeline**:
  - Background items `tl-bg-punch` con bordo verde (shift) / arancio (overtime) / giallo (break) / rosso (sick) / lavanda (leave) / grigio (idle)
  - Tooltip con data, durata, kind label
  - Solo timbrature chiuse (con `end_datetime`) visualizzate
  - Nessun drag/resize sugli overlay (skip in `onMoving`)

### B — Bug fix booking modal

- **Popup ore (tooltip durata) ripristinato** durante drag/resize di un item: titolo dinamico in onMoving con `start → end` + durata formattata (h o gg+h)
- **"+ Aggiungi risorsa"** ora copia data/orari della prima riga (nuovo `tlbAddAssignmentRowFromFirst()`) — la risorsa va comunque scelta dall'utente

### A — Login centrato

- Fix `.login-page`: `body` è `display:flex` (per app-shell), prima la card finiva a sinistra
- Aggiunto `width:100%; flex:1` per espandere il container al viewport
- Background con radial gradient indaco subtle (estetica)

### F — Look refined timeline risorse

- `/planning` Resource Timeline polish CSS:
  - Container con shadow elevata + inset highlight + radius
  - Time axis: maiuscolo letter-spacing, gradient header, weekend tint indaco
  - Labels: zebra simmetrica, transition .12s, hover indaco
  - Reparti header: gradient orizzontale + bordo sx 3px indaco + uppercase 700
  - Items: shape morbida con shadow + inset highlight, hover lift e brightness +8%, selected con doppio glow indaco
  - Drag handles: gradient rampa che si rivela in hover
  - Punch overlay: opacity 0.85 → 1 in hover, no border/shadow per non disturbare booking sopra

## v3.4.21.1 — Auth guard + UX login (30 aprile 2026)

Pagina login esisteva già ma non proteggeva niente: si entrava in `/dashboard` anche
senza cookie. Patch UX per testare il flusso punch in/out come Luca Bianchi.

### Auth guard middleware

- Nuovo middleware `auth_guard` in `app/main.py`
- Cookie `access_token` mancante o JWT invalido su path protetto → redirect 303 a `/auth/login?next=<path>`
- Whitelist: `/auth/*`, `/static/*`, `/health`, `/docs`, `/openapi.json`, `/favicon.ico`, `/redoc`
- API (path con `/api/`) ricevono 401 JSON invece di redirect
- `request.state.current_user` popolato a ogni request con l'oggetto User (hit DB minimo)

### UX login

- POST `/auth/login` con credenziali sbagliate ora **rerender** il template con `{{ error }}` (era 401 JSON crudo)
- Email pre-compilata se sbagli password (UX)
- Hidden input `next` nel form per redirect smart post-login (lettura via `request.form()` per evitare collision col builtin Python `next`)
- Card "Account demo" in fondo al login con credenziali pre-popolate per i 2 utenti seed (`admin@mediaflow.it` / `editor@mediaflow.it`)

### Topbar utente loggato

- Badge `topbar-user` con nome + ruolo + bottone logout veloce
- Visibile su tutte le pagine via `base.html`
- CSS dedicato in `main.css`: surface elevata, role uppercase 10px, logout hover rosa

## v3.4.21 — Soglie e moltiplicatori straordinari (30 aprile 2026)

Fondamenta del cost report doppio: la `WorkingHoursPolicy` impara a distinguere
ore regolari da overtime e applicare maggiorazioni economiche. Senza questo
livello le ore TimePunch finiscono nel cost report tutte allo stesso peso e i
numeri sulle risorse interne sono sballati.

### Modello

`WorkingHoursPolicy` esteso con 8 campi nuovi:
- `daily_hours_threshold` — default 8.0 (oltre = overtime giornaliero)
- `weekly_hours_threshold` — default 40.0 (oltre = overtime settimanale, no doppio conteggio col daily)
- `overtime_multiplier` — default 1.25 (+25%)
- `night_multiplier` — default 1.50 (+50%, fascia 22-06)
- `sunday_multiplier` — default 1.50
- `holiday_multiplier` — default 2.00
- `night_start` / `night_end` — default 22:00 / 06:00

### Engine

Nuovo `app/services/overtime.py` con `compute_overtime(punches, policy) → OvertimeBreakdown`:
- Considera solo `kind` shift + overtime; ferie/malattia/pausa/idle escluse
- Splitta TimePunch che attraversano mezzanotte
- Calcola per giorno: total, night overlap, is_sunday, is_holiday
- Aggrega per settimana ISO per overtime settimanale
- Applica priorità MAX moltiplicatore (no cumulo): festivo > domenica > overtime > notturno > regolare
- Output: `regular_hours`, `overtime_daily_hours`, `overtime_weekly_hours`, `night_hours`, `sunday_hours`, `holiday_hours`, `weighted_factor` (ore equivalenti per costo), `total_hours`, `daily` dettaglio

### Endpoint

- `GET /hr/api/overtime?resource_id=X&from_date=Y&to_date=Z` ritorna breakdown completo + policy applicata
- Override per-risorsa onorato: `Resource.working_hours_policy_id` ha precedenza, fallback su default tenant

### UI

- `/settings` tab "Orari lavorativi" → nuova sezione "Straordinari · soglie e maggiorazioni" con 8 input (soglie giornaliera/settimanale, 4 moltiplicatori, fascia notturna start/end)
- Validazione: soglie > 0, moltiplicatori ≥ 1.0
- Caricamento e salvataggio integrati al form esistente

### Migrazione

`scripts/migrate_overtime_thresholds.py` (opzione `[H]` su `strumenti.bat/sh`):
- ALTER TABLE working_hours_policies con 8 colonne nuove (idempotente)
- Default backfill per `night_start=22:00` / `night_end=06:00` su policy esistenti

### Cosa NON fa ancora

- Niente UI per visualizzare il breakdown su `/hr` (arriverà nel cost report v3.4.22)
- Niente cost report `/jobs/{id}/cost-report` (prossimo step)
- Niente banca ore / quadratura mensile / export cedolino

## v3.4.20.4 — Form ferie/malattia + override policy nel modal risorsa (29 aprile 2026)

Modal `/resources` esteso con due nuove sezioni di gestione disponibilità.

### Override policy orari per-risorsa

- **Dropdown "Orario lavorativo"** sotto le note
- Vuoto = usa default tenant (la "Italia standard")
- Lista popolata da `wh_policies` (passati al template dal router)
- Salva via `working_hours_policy_id` su `PUT /resources/api/{id}` (campo aggiunto già al backend)

### Sezione ferie/malattie (solo in edit mode)

- **Lista esistenti** in scroll-y (max-height 160px) con dot color, kind label, range date, eventuale note, bottone × per eliminare
- **Form aggiungi** inline: Dal / Al / Tipo (Ferie/Malattia/Altro) / Note + bottone "+ Aggiungi"
- Counter `(N)` accanto al titolo
- Hidden in create mode (serve prima salvare la risorsa)

### Backend

Nuovi endpoint in `app/routers/resources.py`:
- `GET /resources/api/{id}/unavailabilities` — lista ferie esistenti per risorsa
- `POST /resources/api/{id}/unavailability` — esteso con `kind` (vacation/sick/holiday/other)
- `DELETE /resources/api/unavailability/{u_id}` — soft delete (hard delete sul DB)
- `PUT /resources/api/{id}` accetta `working_hours_policy_id`
- `GET /resources/api/{id}` ritorna anche `working_hours_policy_id`

### Integrazione downstream

Le ferie aggiunte qui appaiono **automaticamente** sulla timeline `/planning/?view=timeline` come fasce striate indaco/rosse (logica già implementata in v3.4.17). Smart split rispetta queste date. Hard block drag su ferie attivo.

### File toccati

- `app/main.py` — version 3.4.20.4
- `app/routers/resources.py` — `wh_policies` nel context, GET/POST/DELETE unavailabilities, PUT con policy_id, GET con policy_id
- `app/templates/pages/resources.html`:
  - Modal: dropdown policy + sezione ferie collapsible
  - JS: `rsUnavLoad`, `rsUnavAdd`, `rsUnavDelete`, integrate in `editResource`/`openNewResource`
  - `saveResource` invia `working_hours_policy_id`

### Smoke

- `/resources/` 200, contiene `rs-wh-policy`, `rs-unav-list`, `rsUnavLoad`, `rsUnavAdd`
- `GET /resources/api/1/unavailabilities` 200

### Test sul Mac

1. `/resources/` → click su una risorsa
2. Modal mostra dropdown policy + sezione "Ferie e malattie"
3. Aggiungi periodo Vac/Mal/Altro con date e note
4. Verifica che timeline (`/planning/?view=timeline`) mostri lo strip nei giorni
5. Drag booking sopra ferie → hard block

---

## v3.4.20.3 — UI settings: tab "Orari lavorativi" (29 aprile 2026)

Nuova tab in `/settings` per modificare la `WorkingHoursPolicy` default senza dover passare per le API.

### Form

- **Nome policy**
- **Mattina · Inizio / Fine** (input `time` step 15min)
- **Pomeriggio · Inizio / Fine** (opzionali — vuoto = orario continuato senza pausa)
- **Giorni lavorativi**: 7 checkbox (Lun-Dom)
- **Festività nazionali**: select country code (IT default + 5 altri paesi comuni, "—" disabilita auto-import)
- **Salva** chiama `PUT /settings/api/working-hours/{id}` esistente
- **Annulla modifiche**: ricarica via GET

`showPane('hours')` triggera auto-load della policy default.

### File toccati

- `app/main.py` — version 3.4.20.3
- `app/templates/pages/settings.html`:
  - Nuova tab "🕐 Orari lavorativi"
  - Pannello `pane-hours` con form completo
  - Funzioni `whReload()`, `whSave()` (working_days bitmask)
  - `showPane` chiama `whReload()` quando si apre il tab

### Smoke

- `/settings/` 200, contiene `pane-hours`, `whReload`, `whSave`, `wh-morning-start`
- `GET /settings/api/working-hours` 200

---

## v3.4.20.2 — Modal multi-row leggibilità + cambio status veloce (29 aprile 2026)

### Modal multi-row (fix leggibilità >5 righe)

- Container `#tlb-assignments` ora ha **`max-height: 380px` + `overflow-y: auto`** → con molte risorse appare scrollbar interno
- Scrollbar custom indaco (Chromium)
- **Badge `Risorsa #N`** posizionato in alto-sinistra di ogni riga (negative top, rounded pill)
- **Counter `(N)`** indaco vicino al titolo "Risorse" si aggiorna a ogni add/remove
- Funzione `_tlbUpdateRemoveButtons` estesa per renumerare automaticamente le righe rimanenti dopo remove

### Cambio status veloce dal right-click

Voce dinamica nel context menu su item:
- Se booking è `tentative` → **`✓ Conferma booking`** (chiama PUT con status=confirmed)
- Se booking è `confirmed` → **`⏳ Rendi tentative`** (PUT con status=tentative)

Riusa endpoint `PUT /api/bookings/{id}` esistente (passa solo `status`). Toast feedback. Refresh timeline. Timeline visivamente aggiorna il bordo (tratteggiato/solido) automaticamente.

### File toccati

- `app/main.py` — version 3.4.20.2
- `app/templates/pages/planning.html`:
  - CSS: `#tlb-assignments { max-height/overflow }`, scrollbar custom, `.ass-num` pill
  - HTML: `<span class="ass-num">` in row template, counter in label
  - JS: `_tlbUpdateRemoveButtons` rinumera + counter, voce status nel context menu

### Smoke

- HTML contiene `ass-num`, `tlb-ass-counter`, `Conferma booking`, `Rendi tentative`, `max-height: 380px`

---

## v3.4.20.1 — Filtri sidebar con autocomplete (29 aprile 2026)

I 4 filtri "lunghi" della sidebar pianificazione (Cliente / Progetto / Job / Risorsa) erano `<select>` lunghi e poco scalabili. Ora sono **input search con dropdown autocomplete**, stesso pattern del modal "Nuovo booking".

### Pattern uniforme

- Helper riusabile **`FA_CONFIG`**: oggetto `{client, project, job, resource}` con `data` (seed), `search` (predicato match), `display` (testo input), `render` (HTML suggestion).
- Per ogni filtro:
  - Input testuale `<input data-fa="...">` per la ricerca live
  - Hidden `<input id="f-{key}">` per il valore (id) compatibile col flow esistente (`getFilterParams`, URL state)
  - Bottone `✕` per cancellare la selezione
  - Dropdown `.fa-suggestions` posizionato sotto l'input
- Click su suggestion → riempie input visibile + setta hidden + triggera `onFilterChange()`.

### Filtri specifici

| Filtro | Cerca su | Suggestion |
|---|---|---|
| **Cliente** | `name` | nome cliente |
| **Progetto** | `code`, `title`, `client_name` | `[CODE] title` + cliente come meta |
| **Job** | `code`, `title`, `client`, `project_code`, `project_title` | `[CODE] title` + cliente · progetto |
| **Risorsa** | `name` | dot color + nome + reparto come meta |

Reparto, Stato, Tipo restano `<select>` (pochi valori, fissi).

### Seed JSON aggiunti

- `CLIENTS_SEED`: `{id, name}`
- `PROJECTS_SEED`: `{id, code, title, client_name}`
- (`JOBS_SEED` e `RESOURCES_SEED` già presenti dal modal)

### Compatibilità

- URL state (`?client=N`): all'`readFiltersFromURL` ricarica display dall'id via `_faSetFromId`
- `renderActiveFiltersBar`: per gli autocomplete usa `FA_CONFIG[k].display(item)` invece del valore raw
- `resetFilters`: reset display + classe `has-value` + bottoni clear
- Niente cambi backend, solo riformattazione frontend dei filtri esistenti

### CSS

- `.fa-suggestions` dropdown indaco, hover indaco
- `.fa-input.has-value` sfondo leggermente indaco per indicare filtro attivo
- `.fa-meta` per riga secondaria (cliente/reparto)

### File toccati

- `app/main.py` — version 3.4.20.1
- `app/templates/pages/planning.html`:
  - HTML: 4 filtri convertiti in input + hidden + dropdown
  - JS: `FA_CONFIG`, `_faSearch`, `_faSetVisible`, `_faClear`, `_faSetFromId`, listener init
  - CSS: `.fa-suggestions`, `.fa-item`, `.fa-input.has-value`
  - Seed `CLIENTS_SEED`, `PROJECTS_SEED`
  - `readFiltersFromURL`, `renderActiveFiltersBar`, `resetFilters` aggiornati

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `FA_CONFIG`, `CLIENTS_SEED`, `PROJECTS_SEED`, `data-fa`, `fa-suggestions`

### Test sul Mac

1. Click su input "Cliente" → vedi tutti i clienti
2. Digita "TPR" → filtra
3. Click suggestion → riempie input + filtri timeline aggiornati
4. ✕ → cancella
5. Stesso flow per Progetto, Job (cross-search), Risorsa
6. URL `?client=3` → display popolato in input

---

## v3.4.20 — E6: AI propose_booking + suggest-resources (29 aprile 2026)

Sesta e ultima fase del piano core-planning. AI può ora proporre booking direttamente.

### Capability AI `propose_booking`

Aggiunta a `app/services/ai_assistant.py`:

```json
{
  "action": "propose_booking",
  "data": {
    "job_id": 42,           // oppure "job_code": "J-2026-001"
    "kind": "project",      // o internal_*
    "job_cost_line_id": 7,  // opzionale
    "notes": "Sessione color HDR",
    "assignments": [
      {"resource_id": 3, "start_datetime": "2026-05-04T09:00", "end_datetime": "2026-05-04T13:00"},
      {"resource_name": "Luca Bianchi", "start_datetime": "2026-05-04T10:00", "end_datetime": "2026-05-04T18:00"}
    ]
  }
}
```

- Risolve `job_code` → `job_id` se necessario
- Risolve `resource_name` → `resource_id` (case-insensitive)
- Conflict check per ogni assignment vs altri booking attivi
- Crea Booking + N BookingAssignment in singola transazione
- Status default `tentative`

System prompt aggiornato con la doc capability.

### Endpoint `GET /planning/api/suggest-resources`

Nuovo endpoint per AI auto-suggest e UI futura:
- `from_datetime`, `to_datetime`, `department_id?`, `type?`
- Per ogni risorsa attiva del tenant, ritorna due liste:
  - `available`: nessun conflitto in quel range
  - `busy`: con `conflict_assignment_id` o `unavailability_kind`
- Permette al copilot di rispondere "chi è libero il X" e proporre `propose_booking`

### File toccati

- `app/main.py` — version 3.4.20
- `app/services/ai_assistant.py` — `_h_propose_booking` handler, registrato in `_ACTION_HANDLERS`, doc nel system prompt
- `app/routers/planning.py` — `GET /api/suggest-resources`

### Smoke

- `GET /api/suggest-resources` con range 2026-05-04 09:00-13:00 dept=1 → 2 disponibili, 0 occupate
- `propose_booking` capability registrata in `_ACTION_HANDLERS`

### Esempio uso copilot (dopo questa versione)

> Utente: "Chi è libero giovedì 7 maggio dalle 14 per fare audio mix?"
> AI: chiama internamente `suggest-resources` (o riusa context), risponde:
> "Sono libere: **Mario Rossi** (Audio mixer, dept Audio) e **Luca Verdi** (Audio engineer). Vuoi assegnare uno?"
>
> Utente: "Sì, Mario, 14-18 sul job J-2026-005"
> AI:
> ```action
> {"action": "propose_booking", "data": {
>   "job_code": "J-2026-005",
>   "assignments": [{"resource_name": "Mario Rossi",
>     "start_datetime": "2026-05-07T14:00", "end_datetime": "2026-05-07T18:00"}]
> }}
> ```
> User clicca "Applica" → booking creato.

### Roadmap completata

E1→E6 di "Core planning" tutte chiuse:

| Fase | Versione | Tema |
|---|---|---|
| E1 | v3.4.14 | Editing diretto (drag/resize/delete) |
| E2 | v3.4.15 | Click&drag create + capacity heatmap + menu contestuale |
| E3 | v3.4.17 | Working hours + ferie/festività + smart split |
| E4 | v3.4.18 | Multi-select + keyboard + bulk paste |
| E5 | v3.4.19 | Ricorrenti + tentative + audit log |
| E6 | v3.4.20 | AI propose_booking + suggest-resources |

E2 ha incluso anche multi-resource (v3.4.16/16.1).

### Restano (backlog)

- v3.4.20.1 UI settings working hours editabile
- v3.4.20.2 Multi-row >5 leggibilità (collapse, scroll)
- v3.4.20.3 Snap line visiva durante drag
- v3.4.20.4 Endpoint POST/PUT cambio status tentative↔confirmed dal modal

---

## v3.4.19 — E5: ricorrenti + tentative visivo + audit log (29 aprile 2026)

### Booking ricorrenti

POST `/planning/api/bookings` ora accetta `recurrence_rule` + `recurrence_until`:

| Rule | Significato |
|---|---|
| `DAILY` | Tutti i giorni |
| `WEEKDAYS` | Lun-Ven |
| `WEEKENDS` | Sab-Dom |
| `MON` / `TUE` / `WED` / `THU` / `FRI` / `SAT` / `SUN` | Singolo giorno |
| `MON,WED,FRI` (CSV) | Combinazione custom |

Server espande in **N booking distinti**, uno per occorrenza, mantenendo orari + risorse + job. Conflict check su ogni occorrenza. Esempio: MON/WED/FRI dal 4 al 22 mag = **9 booking** creati.

UI nel modal: checkbox "Ricorri" → dropdown regola + date "fino al". Disabilitato in edit mode.

### Tentative bookings (visivo)

- `Booking.status` esistente già supportava `tentative` / `confirmed` / `cancelled`. Aggiunta solo viz.
- CSS `.vis-item.tl-tentative`: bordo tratteggiato 2px, opacità 70%
- Tooltip include " (tentative)"
- `tlBookingToItem` setta classe in base a `status === 'tentative'`

### Audit log (`booking_changes` table)

- **Nuovo modello `BookingChange`**: `id, booking_id, user_id, kind, summary, payload (JSON), created_at`
- Hook `_log_change(db, booking_id, kind, summary, payload)` chiamato in:
  - POST create (1 entry per ogni booking creato, anche in caso di ricorrenza)
  - PUT update
  - DELETE (soft → kind=delete)
  - POST restore
- **Nuovo endpoint `GET /planning/api/bookings/{id}/audit`** ritorna cronologia ordinata desc
- Nessuna migration esplicita (Base.metadata.create_all crea la tabella al boot)

### File toccati

- `app/main.py` — version 3.4.19
- `app/models/models.py` — `BookingChange`
- `app/models/__init__.py` — export
- `app/routers/planning.py` — `_log_change`, `_expand_recurrence`, parametri POST, audit hooks su update/delete/restore, endpoint audit GET
- `app/templates/pages/planning.html` — CSS `tl-tentative`, classe in `tlBookingToItem`, modal sezione "Ricorri" con dropdown + date until, reset/submit aggiornati

### Smoke E2E

- POST recurrence MON/WED/FRI 04→22 mag → 9 booking, audit log scritto
- GET audit log → entries con summary "Booking ricorrente MON,WED,FRI (occ 2026-05-04)"

### Da testare sul Mac

1. Modal nuovo → spunta "Ricorri" → dropdown "Lun/Mer/Ven" + data fine → crea
2. Verifica N booking creati nei giorni giusti
3. Booking con `status=tentative` (default in alcuni flussi) appare tratteggiato
4. `GET /planning/api/bookings/{id}/audit` ritorna cronologia

### Restano

- v3.4.19.1 endpoint POST/PUT change tentative↔confirmed dal modal
- v3.4.20 E6 AI auto-suggest assegnazione

---

## v3.4.18 — E4: Multi-select + keyboard shortcuts + bulk paste (29 aprile 2026)

Quarta fase del piano core-planning. Polish power-user senza nuove dipendenze backend.

### Multi-select

- vis-timeline `multiselect: true`, `multiselectPerGroup: false`
- **Ctrl+click** (Cmd su Mac) aggiunge/rimuove item dalla selezione
- **Shift+click** seleziona range (nativo vis-timeline)
- Items selezionati restano evidenziati col bordo bianco standard

### Keyboard shortcuts su timeline

Listener `keydown` globale, attivo solo se vista timeline è la corrente e nessun input ha focus.

| Tasto | Azione |
|---|---|
| **Ctrl+Z** | Undo dell'ultima azione (riusa stack già esistente) |
| **Ctrl+C** | Copia gli items selezionati nel clipboard interno (`window._tlClipboard`). Toast `Copiati N booking…` |
| **Ctrl+V** | Incolla il clipboard ad oggi (preserva offset relativo dal primo) |
| **Delete** | Bulk delete di TUTTI gli items selezionati. Conferma `Eliminare N assegnazioni?`. Mostra contatore success/fail. |
| **←  / →** | Nudge ±15min di un singolo item selezionato (PUT su assignment singolo, undo abilitato) |
| **Esc** | Pulisce la selezione |

Skip su background items (ferie/festa, id `u-*`).

### Bulk paste

- `tlBulkPaste()`: per ogni item nel clipboard, calcola offset rispetto al primo
- Crea N nuovi booking (1 assignment ognuno) ad oggi alla stessa ora
- Toast finale `N incollati a oggi` o warning se errori (es. conflitti)
- Conserva job_id, kind, cost_line_id, notes dell'originale

### Hint UI

`Drag = pan · Drag item = sposta · Bordi = durata · Alt+drag = duplica · Ctrl+click = multi-select · Canc/←→/⌘C/V/⌘Z · doppio click vuoto = nuovo`

### File toccati

- `app/main.py` — version 3.4.18
- `app/templates/pages/planning.html`:
  - Opzioni `multiselect: true` + `multiselectPerGroup: false`
  - Listener `keydown` con shortcuts
  - Funzione `tlBulkPaste`
  - `window._tlClipboard` state
  - Hint UI aggiornato

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `multiselect`, `_tlClipboard`, `tlBulkPaste`, `ArrowLeft/Right`

### Da testare sul Mac

1. Ctrl+click su 2 items diversi → entrambi selezionati
2. Ctrl+C → toast `Copiati 2 booking`
3. Ctrl+V → 2 booking creati ad oggi alla stessa ora dell'originale
4. Selezione + Canc → conferma + bulk delete
5. Selezione singola + freccia ← / → → nudge ±15min
6. Esc → pulisce selezione
7. Ctrl+Z → undo dopo nudge

### Restano (E5/E6)

- v3.4.18.1: snap line visiva durante drag, multi-row >5 leggibilità
- v3.4.19 E5: ricorrenti + tentative bookings + audit log
- v3.4.20 E6: AI auto-suggest assegnazione

---

## v3.4.17 — E3: Working hours policy + ferie/festività bloccanti + smart split (29 aprile 2026)

Terza fase del piano core-planning. Tre feature integrate:

### 1. Modello WorkingHoursPolicy

- **Nuova tabella `working_hours_policies`** con: `name`, `is_default`, `morning_start/end`, `afternoon_start/end` (NULL = orario continuato), `working_days` (bitmask lun=bit0..dom=bit6, default 31=lun-ven), `holidays_country` (ISO, default "IT").
- **Resource.working_hours_policy_id** override opzionale per risorsa.
- **Default tenant**: "Italia standard" 09:00-13:00 / 14:00-18:00 lun-ven, festività `IT`.
- **ResourceUnavailability.kind** enum (`vacation` / `sick` / `holiday` / `other`).
- Migration `scripts/migrate_working_hours.py` idempotente, voce `[G]` su strumenti.

### 2. Engine `split_booking_smart` (`app/services/working_hours.py`)

- Dato `(start, end, policy, unavailabilities)` ritorna lista `TimeSlot` ritagliati su:
  - giorni lavorativi (skip weekend)
  - mattina + pomeriggio (split su pausa pranzo)
  - festività nazionali (libreria Python `holidays` — `holidays.IT(years=...)`)
  - ferie/malattia (date escluse)
- Esempio: lun 4 mag 08:00 → mer 6 mag 22:00 → 6 slot (mat+pom × 3gg).

### 3. Backend planning API

- **`GET /planning/api/unavailabilities`**: ritorna ferie/malattia espliciti + festività auto + weekend (opzionali) per il range. Aggregazione run consecutivi per ridurre payload. `resource_id` opzionale.
- **`POST /planning/api/unavailabilities`**: crea ferie/malattia (validazione date).
- **`DELETE /planning/api/unavailabilities/{id}`**: cancellazione.
- **`POST /planning/api/bookings`** ora accetta flag `smart_split=true`: server espande gli assignments con l'engine prima di salvare.
- **`GET /settings/api/working-hours`** + **`PUT /settings/api/working-hours/{id}`** per gestione policy (UI dedicata in v3.4.17.1).

### 4. Frontend timeline

- **Background items** per ferie/malattia/festività: pattern striato indaco (vacation), rosso (sick), arancio (holiday). Render via vis-timeline `type: 'background'`, classe `tl-bg-{kind}`.
- **Hard block durante drag**: `onMoving` rileva overlap con item bloccante (`vacation`/`sick`/`holiday`), applica classe `tl-conflict-hard` (sfondo rosso scuro pieno + animazione shake). `onMove` rifiuta drop con toast `Risorsa non disponibile in questo periodo (ferie/festività)`.
- **Skip drag su background items**: i bg-items non sono trascinabili.

### 5. Modal smart split

- **Checkbox "Smart split"** sotto le note (sfondo verde). Default off.
- Quando attivo (e non in edit mode), invia `smart_split=true` al POST. Server splitta ogni assignment del payload in N sub-slot rispettando policy + unavailabilities della risorsa.
- In edit mode il toggle è disabilitato (replace-all assignments diretti).

### File toccati

- `app/main.py` — version 3.4.17
- `app/models/models.py` — `UnavailabilityKind`, `WorkingHoursPolicy`, `Resource.working_hours_policy_id`, `ResourceUnavailability.kind`
- `app/models/__init__.py` — export
- `scripts/migrate_working_hours.py` — nuovo
- `app/services/working_hours.py` — nuovo (engine split)
- `app/routers/planning.py` — endpoint unavailabilities CRUD, smart_split flag su POST, helper `_resolve_policy_for_resource` e `_expand_assignments_smart`
- `app/routers/settings.py` — endpoint policy GET/PUT
- `app/templates/pages/planning.html` — fetch unavailabilities, render bg-items, hard block onMoving/onMove, checkbox smart split, CSS `tl-bg-*` e `tl-conflict-hard`
- `requirements.txt` — `holidays>=0.60`
- `strumenti.bat` / `strumenti.sh` — voce `[G]`

### Smoke E2E

- `/health` 200
- `GET /planning/api/unavailabilities` ritorna festività italiane (25 apr Liberazione, 1 mag Lavoratori) + weekend riconosciuti
- `POST /planning/api/bookings` con `smart_split=true` su range lun-mer 8-22 → 6 assignments (mat/pom × 3gg, 9-13 + 14-18)
- `GET /settings/api/working-hours` ritorna policy default

### Da testare sul Mac

1. `[G]` su strumenti per migrare DB
2. Su timeline: weekend e festività italiane (es. 25 apr) appaiono striati
3. Drag booking sopra una festività → bordo rosso animato + drop rifiutato
4. Modal nuovo booking → checkbox "Smart split" → range multi-day → 1 booking ma con N assignments rispettosi di pausa/weekend/festa
5. `pip install -r requirements.txt --upgrade` per ottenere `holidays`

### Restano per v3.4.17.1

- UI settings page con form policy modificabile
- Override policy per-risorsa (UI in `/resources` page)
- Form ferie/malattia in `/resources/{id}` (oggi solo via API)

---

## v3.4.16.1 — Multi-resource UI completa (modal multi-row + edit) (29 aprile 2026)

Frontend completo per multi-resource. Modal "Nuovo/Modifica booking" ora supporta **N risorse con orari distinti** in un unica operazione.

### Modal multi-row

- **Sezione "Risorse"** sostituisce la vecchia "Orari + Risorsa" globale
- **Bottone `+ Aggiungi risorsa`** in alto a destra: aggiunge una nuova riga
- Ogni riga assignment contiene:
  - **Select risorsa** raggruppato per reparto (`<optgroup>` per ogni Department + "Senza reparto")
  - **Inizio**: data + ora separati (input nativi + step 15min)
  - **Fine**: data + ora separati
  - **Display durata** live (`Xh` / `Yg Zh`, rosso se invalida)
  - **Preset rapidi**: 1h, 2h, 4h, 8h, 2gg, 1sett (applicati alla SOLA riga del bottone)
  - **Bottone × Rimuovi** (disabilitato se è l'unica riga, almeno 1 sempre richiesta)
- Container `#tlb-assignments` popolato dinamicamente da `tlbAddAssignmentRow(preset)`
- Helper `_readRow(row)`, `_setRow(row, data)`, `_tlbCollectAssignments()` per raccolta + validazione

### Edit mode (nuova feature)

- Right-click su booking → **"Modifica…"** ora chiama `tlbOpenEdit(bookingId)` invece di aprire modal con range singolo
- `tlbOpenEdit`:
  1. Reset modal, set `tlb-editing-booking-id`, cambia titolo a `Modifica booking #N`, bottone a `Aggiorna`
  2. Filtra `window._tlBookings` per booking_id selezionato → array di items (1 per assignment)
  3. Pre-popola metadata (kind, job, lavorazione, notes) dal primo item
  4. Crea **N righe**, una per ogni assignment esistente
- Submit fa **PUT `/api/bookings/{id}`** (replace-all assignments) invece di POST nuovo

### tlbSubmit unificato

- Detect editing via hidden `tlb-editing-booking-id`
- `_tlbCollectAssignments()` valida ogni riga (resource_id, start, end, end > start)
- Form data invia `assignments` JSON, kind, job_id, line_id, notes
- POST se nuovo, PUT se editing
- Toast "Booking creato" o "Booking aggiornato"

### File toccati

- `app/main.py` — version 3.4.16.1
- `app/templates/pages/planning.html`:
  - Modal HTML rifatto (sezione Risorse multi-row)
  - CSS `.tlb-ass-row`, `.ass-grid`, `.ass-labels`, `.ass-footer`
  - Funzioni JS: `_resourceOptionsHTML`, `tlbAddAssignmentRow`, `tlbRemoveAssignmentRow`, `_tlbUpdateRemoveButtons`, `tlbAssOnChange`, `_readRow`, `_setRow`, `tlbAssUpdateDuration`, `tlbAssSetDur`, `tlbAssSetDurDays`, `_tlbCollectAssignments`, `tlbOpenEdit`
  - Refactor `tlbOpen` / `tlbOpenWithRange` (creano 1 riga preset)
  - Refactor `tlbSubmit` (POST vs PUT in base a edit mode)
  - Rimosse funzioni obsolete `tlbSetDuration`, `tlbSetDurationDays`, `tlbUpdateDurationDisplay`, `_setDtFields`, `_readDtFields`, `tlbSyncStart`, `tlbSyncEnd`
  - Right-click "Modifica…" usa `tlbOpenEdit(bookingId)`
  - `window._tlBookings = bookings` esposto per edit mode

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `tlbAddAssignmentRow`, `tlbOpenEdit`, `_tlbCollectAssignments`, `tlb-assignments` container, `tlb-editing-booking-id` hidden

### Da testare sul Mac

1. Doppio click su area vuota → modal con 1 riga preset
2. Click `+ Aggiungi risorsa` → seconda riga
3. Cambia risorsa, orari (data + ora separati), preset durata
4. Submit → booking creato con 2 assignments
5. Right-click su un booking esistente → `Modifica…` → modal precaricato con tutte le risorse del booking
6. Modifica una riga, aggiungi una risorsa, salva → PUT funziona, timeline aggiornata
7. Bottone × disabilitato se 1 sola riga; toast "Almeno 1 risorsa richiesta" se provi a rimuovere l'ultima

### Restano per dopo

- Warning visivo booking senza assignments (improbabile in UI normale, backend rifiuta già)
- Undo cancellazione assignment singolo (richiede soft-delete o redux pattern)
- Raggruppamento visivo timeline degli assignments dello stesso booking (collega visibilmente con linea/badge)

---

## v3.4.16 — Multi-resource booking (parte 1: backend + adattamento frontend) (29 aprile 2026)

Cambio architetturale: un Booking può avere **N risorse**, ognuna con il proprio intervallo (anche differenti tra loro). Riferimento: cinema/post-production dove uno stesso turno può vedere colorist + assistant + producer presenti con orari diversi.

### Modello

- **Nuova tabella `booking_assignments`** — `id, booking_id, resource_id, start_datetime, end_datetime`. Cascade delete dal booking padre.
- **Rimosso `Booking.resource_id`**: Booking ora è un contenitore puro.
- **`Booking.start_datetime` / `end_datetime` diventano envelope** auto-calcolati come `min/max` degli `assignments`.
- **Relazione**: `Booking.assignments` ↔ `BookingAssignment.booking`. `Resource.booking_assignments` (era `Resource.bookings`).

### Migration `scripts/migrate_multi_resource.py`

1. Crea tabella `booking_assignments`
2. Per ogni Booking esistente → 1 assignment con `(resource_id, start, end)` (1:1 con il vecchio comportamento)
3. Drop column `bookings.resource_id` via recreate-table dance SQLite (idempotente)
4. Disponibile dal menu strumenti `[F]` (.bat e .sh)

### Backend (`app/routers/planning.py`)

- **GET `/api/bookings`** — restituisce **1 item per assignment** (non più 1 per booking). Item id `a{N}`. ExtendedProps include `group_size`, `group_position` per badge "1/3".
- **POST `/api/bookings`** — accetta `assignments` come stringa JSON (lista di `{resource_id, start_datetime, end_datetime}`). Almeno 1 assignment richiesto. Conflict check su tutti.
- **PUT `/api/bookings/{id}`** — aggiorna metadata (kind/job/status/notes) + opzionale replace-all `assignments`.
- **NUOVO `PUT /api/booking-assignments/{aid}`** — aggiorna un singolo assignment (drag/resize/reassign del singolo item timeline).
- **NUOVO `DELETE /api/booking-assignments/{aid}`** — cancella singolo assignment. Se è l'ultimo del booking → cancella (soft) il booking intero.
- **POST `/api/bookings/{id}/restore`** — conflict check ora su tutti gli assignments del booking.
- Helper riusabili: `_check_assignment_conflict`, `_recalc_booking_envelope`, `_validate_kind_job`.

### Refactor downstream

- `app/routers/jobs.py` — `_aggregate_planned_hours` e `_aggregate_unassigned` ora aggregano `BookingAssignment` invece di `Booking` (un booking N risorse = somma per assignment, non envelope).

### Frontend (planning.html, adattamenti minimi)

- **`tlBookingToItem`** — usa `id="a{N}"` dal backend, badge "N/M" se booking multi-risorsa.
- **`onMove`** — chiama `PUT /api/booking-assignments/{aid}` (singolo assignment) invece di PUT booking.
- **`onRemove`** — chiama `DELETE /api/booking-assignments/{aid}`.
- **Right-click "Elimina"** — etichetta "Elimina assegnazione" + endpoint assignment.
- **`_tlDoMove` / `_tlDoDuplicate`** — sui nuovi endpoint. Duplica crea sempre 1 nuovo Booking con 1 assignment.
- **`tlbSubmit` (modal "Nuovo")** — invia `assignments=[{resource_id,start,end}]` come JSON nel form. UI mono-row per ora (multi-row in v3.4.16.1).
- **`tlPerformUndo`** — gestisce `update_assignment` e `remove_assignment` types.

### Smoke E2E backend

- GET `/api/bookings` → 9 items, formato `a{N}`, `group_size=1`, `group_position=1`
- POST con 2 assignments → booking con env start=09:00, end=18:00, 2 assignments distinti
- PUT singolo assignment → start/end aggiornati, envelope ricalcolato
- DELETE 1 assignment di booking con 2 → booking_cancelled=false
- DELETE ultimo assignment → booking_cancelled=true

### Restano per v3.4.16.1

- **Modal multi-resource UI**: righe dinamiche (`+ Aggiungi risorsa`), ognuna con resource select + start + end + remove
- **Warning visivo** booking senza risorse
- **Cancel-fissaggio**: undo per assignment cancellato (richiede `POST /restore-assignment` o approach diverso)

### File toccati

- `app/main.py` — version 3.4.16
- `app/models/models.py` — `BookingAssignment`, rimosso `Booking.resource_id`, `Resource.booking_assignments`
- `app/models/__init__.py` — export `BookingAssignment`
- `scripts/migrate_multi_resource.py` — nuovo
- `strumenti.bat` / `strumenti.sh` — voce `[F]` migrazione
- `app/routers/planning.py` — refactor completo endpoint booking
- `app/routers/jobs.py` — aggregazioni via assignments
- `app/templates/pages/planning.html` — adattamento item id, helpers, modal submit, undo

### Da testare sul Mac

1. `./strumenti.sh` → `[f]` per migrare DB
2. Verificare che nessun booking esistente sia "perso" (dovrebbero apparire tutti)
3. Drag/resize/delete su timeline (ora opera su singolo assignment)
4. Modal nuovo booking → crea
5. Multi-row assignment ancora **non disponibile** in UI (backend lo supporta, UI in v3.4.16.1)

---

## v3.4.15.6 — Rimosso Shift + time picker custom (29 aprile 2026)

### Shift+drag rimosso

Dopo 3 tentativi di stabilizzazione (capture phase, setOptions toggle, sync da event), Shift+drag continuava a essere instabile (cursor crosshair "appendeva", il drag non sempre catturato). Tolto del tutto. Tutti i listener `_tlSetShiftMode`/`_tlSyncShiftFromEvent`/`tlCreateMouseDown` rimossi insieme alle ghost rectangle handlers e mouseup globali.

**Metodi nuovo booking residui** (entrambi affidabili):
- **Doppio click** su area vuota timeline
- **Click destro** su area vuota → "Nuovo booking qui"

Hint UI aggiornato: `Drag = pan · Drag item = sposta · Bordi item = durata · Alt+drag = duplica · click destro = menu · doppio click vuoto = nuovo`.

### Time picker custom

`<input type="time">` browser nativo era poco preciso/incoerente tra browser. Sostituito con:

- **Trigger button** `<button class="tlb-tp-trigger">` mostra `HH:MM`, click apre popup
- **Popup** `#tlb-tp-popup` (riusabile per entrambi i campi inizio/fine) con due colonne scrollabili:
  - Ore: 00–23 (24 celle)
  - Minuti: 00, 15, 30, 45 (4 celle)
- Click su cella → setta valore, evidenzia selezione, sync hidden + duration display
- Auto-scroll alla selezione corrente all'apertura
- Click fuori chiude popup, riposiziona se sfora viewport
- Hidden `<input type="hidden" id="tlb-start-time">` mantiene formato `HH:MM` per submit

CSS coerente con palette indaco MediaFlow (selected = `#6272f5` background + bianco bold).

### File toccati

- `app/main.py` — version 3.4.15.6
- `app/templates/pages/planning.html` — rimossi listener Shift e ghost rectangle, rimosso `tlCreateMouseDown`, sostituito `<input type="time">` con trigger + popup, aggiunte `_initTimePicker`, `tlbOpenTimePicker`, `_tlbTpOutside`, `tlbSetTimePart`, `_setDtFields` aggiornato per scrivere su trigger + hidden, `_tlbReset` chiude eventuale popup, hint UI aggiornato

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `_initTimePicker`, `tlbOpenTimePicker`, `tlb-tp-trigger`, `tlb-tp-popup`. Niente residui `_tlShiftDown`/`_tlSetShiftMode`.

---

## v3.4.15.5 — Hotfix: Shift robusto + split data/ora nel modal (29 aprile 2026)

### Bug 1 — Shift sticky

Lo stato `_tlShiftDown` poteva restare bloccato a `true` quando keyup non scattava (es. apertura modal cambia focus, switch tab, alt-tab).

**Fix multipli ridondanti**:
- Funzione `_tlSetShiftMode(on)` centralizzata
- `_tlSyncShiftFromEvent(e)` riallinea stato con `e.shiftKey` reale a OGNI mousemove e mouseup
- Reset esplicito su `blur`, `visibilitychange` (tab nascosta), e all'apertura del modal (`tlbOpen`/`tlbOpenWithRange`)

In pratica: anche se keyup non scatta, alla prima `mousemove` post-modal lo stato si auto-corregge dal valore di `e.shiftKey`.

### Bug 2 — Orari poco precisi nel pop-up

`<input type="datetime-local">` mostra un picker che varia molto tra browser e talvolta non espone bene l'ora. Soluzione: **split in 4 input**.

- `<input type="date" id="tlb-start-date">` + `<input type="time" id="tlb-start-time" step="900">`
- Stesso per fine
- Hidden `tlb-start` / `tlb-end` combinano i due in `yyyy-MM-ddTHH:mm` per il submit
- Helper `_setDtFields(prefix, date)` / `_readDtFields(prefix)` per scrittura/lettura
- Sync automatico via `oninput="tlbSyncStart(); tlbUpdateDurationDisplay()"` su entrambi i sub-input
- `tlbSubmit` fa sync esplicito + guard "Compila inizio e fine"
- Preset durata e display durata aggiornati per usare i nuovi helper

UX: ora data e ora sono input separati e visibili, picker browser nativo per ognuno è più affidabile, time input ha step 15min esplicito.

### File toccati

- `app/main.py` — version 3.4.15.5
- `app/templates/pages/planning.html` — `_tlSetShiftMode`, `_tlSyncShiftFromEvent`, listener `mousemove/mouseup/visibilitychange`, modal HTML rifatto con 4 sub-input + 2 hidden, `_setDtFields`/`_readDtFields`/`tlbSyncStart`/`tlbSyncEnd`, refactor `tlbOpen`, `tlbOpenWithRange`, `tlbSetDuration`, `tlbSetDurationDays`, `tlbUpdateDurationDisplay`, `tlbSubmit`

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `_tlSetShiftMode`, `_tlSyncShiftFromEvent`, `visibilitychange`, `tlb-start-date`, `tlb-start-time`, `tlbSyncStart`

---

## v3.4.15.4 — Hotfix Shift via toggle moveable + modal "Nuovo booking" espanso (29 aprile 2026)

### Fix Shift+drag definitivo

Il listener su document capture fase non bastava: vis-timeline cattura mousedown sui suoi sub-elementi prima di rilasciare il bubble. Approccio invertito: invece di intercettare l'evento, **disabilito `moveable` quando Shift è premuto**.

- `keydown` Shift → `tlInstance.setOptions({moveable: false})` + cursor `crosshair`
- `keyup` Shift / blur → `tlInstance.setOptions({moveable: true})` + cursor reset
- `tlInstance` esposto come `window._tlInstance` per accesso dai listener globali
- Con `moveable: false` durante shift, vis-timeline non intercetta più mousedown per pan, e il listener custom su `document` capture parte regolarmente

### Modal "Nuovo booking" espanso

**Sezione Orari evidenziata** (sfondo indaco):
- Input `datetime-local` con `step="900"` (15 minuti precisione)
- Display "Durata: Xh / Yg Zh" calcolato live, color indaco se valido / rosso se fine ≤ inizio
- **Preset durata rapidi**: bottoni `1h / 2h / 4h / 8h (giornata) / 2 giorni / 1 settimana` — click setta `end = start + N`

**Job search autocomplete cross-progetto**:
- Input testuale con dropdown suggerimenti sotto (max 12 risultati)
- Filtro su 5 campi: code, title, client, project_code, project_title
- Suggestion mostra: `[CODE] Title — Cliente · Progetto-code Progetto-title`
- Click suggestion → riempie input visibile, popola `tlb-job-id` (hidden), carica lavorazioni del job
- Click outside o focus loss → chiude dropdown
- Seed `JOBS_SEED` aggiunto al template con campi arricchiti (project + client tramite joinedload già presente)

**Note → textarea** (resize verticale, 3 righe iniziali, font monospace come i campi).

**Modal width** allargato 560 → 640px per il nuovo contenuto.

### File toccati

- `app/main.py` — version 3.4.15.4
- `app/templates/pages/planning.html` — `_tlShiftDown` + setOptions toggle, `JOBS_SEED` seed, modal HTML rifatto, `tlbJobSearch`, `tlbSelectJob`, `tlbSetDuration`, `tlbSetDurationDays`, `tlbUpdateDurationDisplay`, `_tlbReset`, `tlbSubmit` aggiornato per `tlb-job-id` hidden, click-outside per dropdown, CSS `.tlb-job-item:hover`

### Smoke

- `/planning/?view=timeline` 200, HTML contiene `JOBS_SEED`, `tlbJobSearch`, `tlbSetDuration`, `_tlShiftDown`, `window._tlInstance`

### Da testare sul Mac

- Tieni premuto Shift mentre sei sulla timeline → cursor diventa crosshair
- Shift+drag su area vuota di una risorsa → ghost rectangle + tooltip durata → modal pre-popolato
- Modal: digita "ma" → vedi job che matchano, click → si compila tutto, lavorazioni popolate
- Click presets durata → end aggiornato, display sotto si aggiorna

---

## v3.4.15.3 — Hotfix: Shift+drag affidabile + preserve window (29 aprile 2026)

Due bug:

### Bug 1 — Shift+drag non scattava

vis-timeline catturava `mousedown` sui suoi sub-elementi prima del listener su `host` (anche con capture phase). Risultato: lo shift+drag non avviava la creazione.

**Fix**: listener spostato su `document` in capture phase. Filtro per `host.contains(e.target)` per limitare alla timeline corrente. Aggiunto `e.stopImmediatePropagation()` oltre a `stopPropagation()` per fermare definitivamente vis-timeline. Cleanup del listener precedente via `window._tlCreateHandler` riferimento globale per evitare doppi handler dopo re-render.

### Bug 2 — Refresh tornava a oggi

Dopo creazione/modifica/elimina un booking, `renderTimeline()` veniva chiamato per refresh. Re-buildava la finestra a `tlWindowFor(tlZoom, new Date())` = "oggi → +N giorni". Se l'utente stava lavorando su una settimana futura, la vista saltava indietro.

**Fix**: `renderTimeline(preserveWindow=false)` accetta un flag. Se true, `tlInstance.getWindow()` viene salvato prima del destroy e usato come `win` nel re-render. Tutte le chiamate post-action (`tlbSubmit`, undo, onMove duplicate, right-click duplicate/reassign/delete) passano `true`. Solo le chiamate di prima inizializzazione (setView, init) restano default.

### File toccati

- `app/main.py` — version 3.4.15.3
- `app/templates/pages/planning.html` — `tlCreateMouseDown` su document capture, `renderTimeline(preserveWindow)` con savedWin, 6 chiamate aggiornate a `renderTimeline(true)`

### Smoke

- HTML contiene `tlCreateMouseDown`, `preserveWindow`, `savedWin`, `renderTimeline(true)`
- `/planning/?view=timeline` 200

---

## v3.4.15.2 — Hotfix: blocca drop booking su gruppo reparto (29 aprile 2026)

Bug: era possibile droppare un booking su un'intestazione di reparto (DI/Video, Audio, ...) invece che su una risorsa specifica. I reparti sono `nestedGroups` con `id` stringa (`'d1'`, `'d2'`, `'d0'`), le risorse foglia hanno `id` numerico.

### Fix doppia protezione

1. **`onMoving` live**: durante il drag, se `typeof item.group !== 'number'` (cioè si trascina sopra un'intestazione reparto), forzo `item.group` indietro al group originale → l'item visivamente non si sposta sul reparto.
2. **`onMove` al drop**: guard finale che rifiuta il commit con `callback(null)` + toast warning `Sposta su una risorsa, non su un reparto`.

### File toccati

- `app/main.py` — version 3.4.15.2
- `app/templates/pages/planning.html` — guard in `onMoving` + `onMove`

---

## v3.4.15.1 — Hotfix E2: drag pan + Shift+drag create + right-click menu (29 aprile 2026)

Feedback Matteo: "Non funzionano i punti da 1 a 6. Scoll wheel funziona ma preferivo il trascinamento. Inserisci menù tramite click mouse destro per operazioni su task."

### Cosa cambia rispetto a v3.4.15

- **`moveable: true` ripristinato**: drag pan funziona di nuovo (preferenza utente). Era stato disabilitato in v3.4.15 per liberare drag su background. Trade-off invertito.
- **Click&drag create → Shift+drag**: per non interferire col drag pan, l'attivazione del nuovo booking è ora `Shift+drag` (modifier convenzione standard). Listener registrato in fase di **capture** (`useCapture: true`) per anticipare vis-timeline.
- **Right-click context menu** introdotto:
  - Su un **booking esistente**: `Modifica… / Duplica qui / Sposta su altra risorsa… / Elimina / Annulla`. "Sposta" apre sub-menu con elenco risorse.
  - Su **area vuota**: `+ Nuovo booking qui… / Annulla`.
  - Listener `tlInstance.on('contextmenu')` con `event.preventDefault()` per sopprimere menu nativo browser.

### Heatmap robustezza

- Bug potenziale fix: `groupsDS.clear() + add()` veniva chiamato su `rangechanged` e poteva rompere `nestedGroups` dei reparti. Ora aggiorna **solo le foglie risorsa** (`id` numerico) via `groupsDS.update(g)`, preserva la gerarchia.
- CSS espliciti per visibilità heatmap dentro le label vis-timeline (`width`, `height`, `display:flex`, padding-bottom su label foglia).
- Guard su `props.start || tlInstance.getWindow().start`.

### Hint UI

`Drag = pan · Shift+drag su vuoto = nuovo · Drag item = sposta (menu cross-resource) · Bordi item = durata · Alt+drag = duplica · click destro = menu`

### File toccati

- `app/main.py` — version 3.4.15.1
- `app/templates/pages/planning.html` — `moveable: true`, `e.shiftKey` guard nel mousedown create + capture, `tlInstance.on('contextmenu')` con submenu per Sposta, `groupsDS.update(g)` per heatmap, CSS visibilità heatmap

### Smoke

- HTML contiene: `moveable: true`, `e.shiftKey`, `tlInstance.on('contextmenu')`, `tl-heat` CSS
- `/planning/?view=timeline` 200

### Da testare sul Mac

- Drag normale → pan finestra (come scroll wheel ma più fluido)
- Shift+drag su vuoto → ghost item + tooltip + modal
- Click destro su booking → menu Modifica/Duplica/Sposta/Elimina
- Click destro su vuoto → "Nuovo booking qui"
- Heatmap visibile sotto ogni nome risorsa
- Cambio zoom → heatmap si aggiorna senza rompere nesting reparti

---

## v3.4.15 — E2 — Click&drag create + capacity heatmap + menu contestuale (29 aprile 2026)

Seconda fase del piano "core planning". Tre feature in una versione.

### Click&drag su area vuota crea booking

- Mousedown su background o group-label → tracking → mouseup
- **Ghost rectangle** floating sopra il cursore, semitrasparente con bordo dashed indaco
- **Tooltip live durata** dentro il ghost: `Lun 4 mag · 09:00 → 13:00 · 4h` (single-day) o `Lun 4 mag 09:00 → Mer 6 mag 18:00 · …` (multi-day)
- Snap adattivo già attivo (15/30/60min)
- Mouseup → modal pre-popolato con risorsa locked + start/end calcolati. Funzione nuova `tlbOpenWithRange(resourceId, startDate, endDate)` parallela a `tlbOpen`.
- Soglia minima drag 5px per evitare ghost spurio su click puro; durata minima 1 minuto per scartare click accidentali.
- **Disabilitato pan via drag** (`moveable: false`) per liberare il drag sul background. Pan resta via bottoni ◀/Oggi/▶ + scroll wheel + selettore Vai a.

### Capacity heatmap sotto nome risorsa

- Calcolo client-side dai booking attivi nella finestra visibile.
- Per ogni risorsa, una **barra orizzontale** sotto il nome con un segmento per ogni giorno del range.
- Colorazione per ratio occupazione (8h = piena giornata):
  - 0% → trasparente
  - 0-50% → verde chiaro `rgba(34,197,94,.45)`
  - 50-100% → verde pieno
  - 100-150% → arancio `#fb923c`
  - 150%+ → rosso `#dc2626`
- Tooltip nativo per cella: `Lun 4 mag · 6.5h`.
- Skip render se range > 100 giorni (zoom Trimestre con span estesi).
- **Live update** su `rangechanged` (debounced 150ms): cambia zoom o sposta finestra → heatmap si ricalcola e si ridisegna.

### Menu contestuale al drop cross-resource

- Drag entro stessa risorsa = move silente (PUT diretto).
- Drag su altra risorsa **senza** Alt = popover fluttuante con 3 voci:
  - `↪  Sposta su altra risorsa` (default azione)
  - `⊕  Duplica su altra risorsa` (POST nuovo, originale resta)
  - `✕  Annulla` (callback null, item torna in posizione)
- Posizionamento del menu: ultime coordinate mouse tracciate via `mousemove` su host, riposizionato se sfora viewport.
- Chiusura: click outside, Escape, o scelta. Implementato come Promise.
- Alt+drag (cross-resource o stessa risorsa) = scorciatoia diretta a duplica senza menu — preserva pattern E1 per power user.
- Refactor `_tlDoMove(item, orig, id)` e `_tlDoDuplicate(item, origBooking)` come helper riutilizzabili.

### File toccati

- `app/main.py` — version 3.4.15
- `app/templates/pages/planning.html` — `tlContextMenu`, `_tlDoMove`, `_tlDoDuplicate`, `tlComputeHeatmap`, `tlHeatmapHTML`, `tlBuildGroups(bookings, rangeStart, rangeEnd)`, `tlbOpenWithRange`, mousedown/move/up handlers per click&drag create, listener rangechanged con debounce per rebuild heatmap, `moveable: false` + `horizontalScroll: true`, hint UI aggiornato.

### Smoke test

- `/planning/?view=timeline` 200
- HTML contiene: `tlComputeHeatmap`, `tlContextMenu`, `tlbOpenWithRange`, `tl-ghost-create`, `moveable: false`

### Da testare sul Mac

- Click&drag su area vuota → ghost item con tooltip durata → modal pre-popolato
- Trim drag (<5px) o durata <1min → scartato
- Heatmap visibile sotto ogni risorsa, colori coerenti con carico
- Cambio zoom → heatmap si aggiorna
- Drag booking su altra risorsa → menu Sposta/Duplica/Annulla
- Alt+drag su altra risorsa → duplica diretto (no menu)
- Scroll wheel → pan orizzontale (sostituisce drag pan disabilitato)

### Prossimo step

- v3.4.16 — E3 — WorkingHoursPolicy globale+override + split smart + pausa rigida + ferie/malattia bloccanti + holiday Italia auto

---

## v3.4.14 — E1 — Editing diretto sulla timeline (29 aprile 2026)

Prima fase del piano "core planning" in 6 step. Drag/resize/delete dei booking direttamente sulla Resource Timeline, con undo + conflict viz live + duplica via Alt+drag.

### Backend

- **Nuovo `PUT /planning/api/bookings/{id}`** con conflict check che esclude se stesso. Tutti i campi opzionali, semantica PATCH ma metodo PUT (coerenza form-based con il resto dei router). Validazioni: `kind=project` richiede `job_id`, `kind=internal_*` azzera job/cost_line.
- **Nuovo `POST /planning/api/bookings/{id}/restore`** per undo di cancellazioni. Conflict check sul ripristino (può fallire se nel frattempo è stato creato un booking sopra).
- **Fix `GET /planning/api/bookings`**: di default ora esclude `status=cancelled` (bug pre-esistente che mostrava cancellati nelle viste). Il filtro esplicito `?status=cancelled` continua a funzionare.

### Frontend (vis-timeline)

- `editable: {updateTime, updateGroup, remove, overrideItems}` attivi.
- **Snap adattivo allo zoom**: 15min in Giorno, 30min in Settimana, 60min in Mese/Trimestre. Funzione `tlSnap(date, scale, step)`.
- **Drag**: sposta booking nello stesso giorno o su altra risorsa (cross-group). Bordo aggiornato live, snap durante il drag.
- **Resize**: handle laterali sui bordi, cursor `ew-resize`. Ghost durante resize.
- **Conflict viz live**: durante drag/resize, se l'item collide con un altro stesso resource → classe `.tl-conflict` (sfondo rosso `#dc2626`, ring `rgba(220,38,38,.4)`). Solo viz, drop comunque permesso → backend fa il vero check.
- **Alt+drag = duplica**: se Alt è premuto durante il drag, al drop viene fatto POST di nuovo booking (con stessa risorsa/job/cost_line ma posizione nuova) invece di PUT update. L'originale resta dov'era. Tracking `window._tlAltDown` via keydown/keyup globali.
- **Delete**: tasto Canc su item selezionato. vis-timeline `editable.remove: true` gestisce il prompt nativo, callback chiama DELETE.
- **Doppio click su area vuota**: apre modal "Nuovo booking" pre-popolato (era click in v3.4.13.1, andava in conflitto con drag pan). Click singolo su area vuota = niente, drag pan funziona normalmente.
- **Hint UI**: riga sotto il label settimana con `Drag = sposta · Bordo = durata · Alt+drag = duplica · Canc = elimina · doppio-click su vuoto = nuovo`.

### Undo toast (5s)

- Stack `window._tlUndoStack` (max 20 elementi).
- Dopo update/delete/duplica: toast custom in basso al centro `Booking aggiornato | [Annulla] | 5s` con countdown live.
- Clic Annulla → ripristino: per `update` chiama PUT con valori precedenti, per `remove` chiama POST `/restore`, per `create` chiama DELETE.
- Errore ripristino → toast errore.

### CSS

- `.tl-conflict` rosso pieno con shadow ring durante drag.
- `.vis-drag-left` / `.vis-drag-right` (handle resize) leggermente più visibili su hover.
- `.vis-item.vis-editable { cursor: move; }`.

### File toccati

- `app/main.py` — version 3.4.14
- `app/routers/planning.py` — `update_booking`, `restore_booking`, fix list cancelled
- `app/templates/pages/planning.html` — `tlSnap`, `tlPushUndo/Show/Dismiss/Perform`, `tlHasConflict`, editable + onMoving + onMove + onRemove, doubleClick handler, Alt tracking, hint UI

### Smoke test

- `/planning/api/bookings/{id}` PUT con start/end → response OK con valori aggiornati
- DELETE poi GET → cancellato non più in lista
- POST restore → ok, ricompare in lista
- Conflict check escludendo self funziona
- HTML contiene `tlSnap`, `tlPushUndo`, `_tlAltDown`, `tl-conflict`

### Da testare sul Mac

- Drag booking su altra risorsa → riassegnato
- Drag con Alt premuto → originale resta + nuovo creato
- Resize bordo → durata cambia con snap
- Bordo rosso live durante drag su collisione
- Tasto Canc su selezione → cancella + toast Undo
- Click Undo entro 5s → ripristina
- Doppio click su area vuota → modal nuovo booking

### Prossimo step

- v3.4.15 — E2 — Click&drag su vuoto crea booking con ghost + tooltip durata + capacity heatmap (anticipata da E4)

---

## v3.4.13.1 — Hotfix: filtri + click-to-add timeline (29 aprile 2026)

### Bug fix: nascondi filtri rompeva il layout

Il refactor in v3.4.13 usava `grid-template-columns: 0 1fr` per collassare la sidebar. Il `1fr` con vis-timeline dentro non si comportava in modo prevedibile (probabilmente `min-content` del widget forzava overflow).

**Fix**: passato a `display: flex` con `flex: 1 1 auto; min-width: 0` sul main item. Più robusto: il flex item può ora effettivamente comprimersi sotto la sua content-width, e vis-timeline ha sempre la larghezza giusta sia con sidebar aperta che chiusa.

### Click su timeline → modal nuovo booking pre-popolato

Click su area vuota della Resource Timeline (background, group-label o asse) apre un modal "Nuovo booking" con:
- **Risorsa locked** (è la riga cliccata)
- **Inizio** = ora cliccata, arrotondata all'ora (minuti=0)
- **Fine** = inizio + 1h (default editabile)
- **Tipo** dropdown (project / internal_*)
- **Job** dropdown (visibile solo se kind=project, popolato da `jobs` template-side)
- **Lavorazione** dropdown opzionale (popolato dinamicamente da `GET /jobs/api/{job_id}` quando il job viene scelto)
- **Note** libere

Submit → `POST /planning/api/bookings` (endpoint esistente, validazione conflitti già lì) → toast success → refresh timeline.

### File toccati

- `app/main.py` — version 3.4.13.1
- `app/templates/pages/planning.html` — refactor pl-shell a flex, modal `#modal-tl-booking`, handlers `tlbOpen/tlbOnKindChange/tlbOnJobChange/tlbSubmit`, listener `click` su `tlInstance`

### Smoke

- `/planning/?view=timeline` 200, contiene `pl-main`, `min-width: 0`, `modal-tl-booking`, `tlbOpen`

### Da verificare sul Mac

- Click su area vuota di una riga risorsa apre il modal
- Inizio = ora cliccata arrotondata
- Cambio kind nasconde job/lavorazione
- Selezione job popola lavorazione
- Submit crea booking + appare in timeline

---

## v3.4.13 — Pulizia UX hub Pianificazione (29 aprile 2026)

Iterazione di rifinitura su `/planning/` dopo feedback uso reale della Resource Timeline.

### Timeline risorse — controlli più chiari

- **Tasto "Oggi"**: ora la finestra parte da OGGI (oggi → fine periodo selezionato). Non centra più la settimana corrente.
- **Selettore data + bottone "Vai a"**: input `<date>` per saltare a una data precisa. La finestra si estende per N giorni dopo quella data secondo lo zoom corrente (1/7/30/90).
- **Etichetta sopra la timeline**: `Settimana N — Mese Anno` calcolata sul punto medio della finestra. ISO week numbering.
- **Linea "ora"** più visibile (arancio `#fb923c`, 2px).

### Timeline — visualizzazione risorse più curata

- **Zebra rows** alternate (sfondo `rgba(255,255,255,.015)`) sia nelle label sia nel foreground.
- **Reparto padre** = grassetto, uppercase, color indaco `#6272f5` con sfondo accent.
- **Risorsa figlia** = padding-left 18px per gerarchia chiara, peso normale.
- **Hover row** highlight indaco.
- Items con border-radius 4px e ombra sottile, padding interno.

### Filtri collassabili

- Bottone "Nascondi filtri / Mostra filtri" sopra le tab. Stato persistito in `localStorage['pl-filters-collapsed']`.
- Sidebar collassa a `0` con grid-template-columns animato (transizione 180ms). Main area si espande full-width.
- **Badge contatore** sul bottone toggle: numero di filtri attivi visibile anche a sidebar chiusa.
- Su collapse/expand, vis-timeline `redraw()` e FullCalendar `updateSize()` per riadattarsi.

### Pulizia ridondanze

- **Vista Trimestre rimossa** dall'hub (poco utile coi filtri trasversali, copre già il mese × 3 mesi). Codice + CSS + JS rimossi. View parameter `trimester` cade su `jobs` default.
- **Voce sidebar "Calendario" rimossa** (`base.html`, `settings.html` config). Calendario ora accessibile solo dentro `/planning/?view=calendar`. Redirect `/planning/calendar` mantenuto per backward compat.
- Template `pages/calendar.html` legacy eliminato (dead code, nessun router lo serviva più).
- Link "Vai al calendario" della dashboard puntano ora a `/planning/?view=calendar`.

### File toccati

- `app/main.py` — version 3.4.13
- `app/routers/planning.py` — `VALID_VIEWS` senza `trimester`
- `app/templates/base.html` — rimossa voce sidebar Calendario
- `app/templates/pages/dashboard.html` — link al calendario aggiornato
- `app/templates/pages/settings.html` — rimosso `calendar` da `NAV_ITEMS_DEF`
- `app/templates/pages/planning.html` — toggle filtri, controlli timeline (Oggi/Vai-a/label), zebra+radius+hover, drop renderTrimester
- `app/templates/pages/calendar.html` — eliminato

### Smoke test

- `/health` 200 v3.4.13
- `/planning/?view=timeline` 200, contiene `pl-toggle-filters`, `tl-week-label`, `tl-goto-date`, `isoWeekNum`, `filters-collapsed`
- `/planning/calendar` 302 → redirect compat
- Nessun riferimento `trimester` residuo nell'HTML

### Prossimi step

- v3.4.14 — Booking editabili (drag/resize/delete + PUT API)
- v3.4.15 — Overlay prenotato vs effettivo + funzione "adeguamento" + report delta per producer

---

## v3.4.12 — Resource Timeline (vis-timeline) (29 aprile 2026)

Sesta vista dell'hub `/planning/`: **🧭 Timeline risorse** basata su vis-timeline 7.7.3 (CSS+JS già caricati dal v3.4.11).

### Cosa fa

- **Righe verticali** = risorse, raggruppate per **reparto** (nested groups, padre = nome reparto in grassetto, figli = risorse). Risorse senza reparto in gruppo "Senza reparto".
- **Tempo orizzontale** con zoom **Giorno / Settimana / Mese / Trimestre** (default settimana corrente, lunedì → domenica).
- Bottoni **◀ / Oggi / ▶** per spostarsi avanti-indietro di una finestra alla volta.
- Etichetta range visibile in alto a destra (es. `28 apr 2026 → 5 mag 2026`).

### Dati e filtri

- Riusa endpoint `GET /planning/api/bookings` (già supporta tutti i 9 filtri trasversali). Zero nuovi endpoint server-side.
- Filtri client-side anche sui groups: filtro **reparto** nasconde gli altri reparti, filtro **risorsa** mostra solo quella riga.
- Items vis-timeline: id `b{booking_id}`, group = `resource_id`, colore = `resource.color`, classe `kind-internal` (grigio) per booking interni (manutenzione/R&D/formazione).
- Tooltip nativo vis-timeline su hover, click su item → toast con titolo + range orario formattato.

### Tema dark

- Override CSS coerenti con palette indaco MediaFlow (`#6272f5`): bordi `var(--border)`, sfondo `var(--bg-elev)`, testo `var(--text)`. Item interni colore `#6b7280` (grigio neutro).

### File toccati

- `app/routers/planning.py` — `VALID_VIEWS` esteso con `"timeline"`
- `app/templates/pages/planning.html` — tab #6, container `#tl-host`, barra zoom/nav, seed JSON `RESOURCES_SEED`/`DEPARTMENTS_SEED`, ~150 righe JS (`renderTimeline`, `tlBuildGroups`, `tlBookingToItem`, `tlWindowFor`, `tlMove`, `tlUpdateRangeLabel`)

### Smoke test

- `/health` 200 v3.4.12
- `/planning/?view=timeline` 200, HTML contiene markup atteso e seed JSON ben formato

### Prossimi step

- v3.4.12.1 — **Kanban per stato job** (SortableJS già in uso)
- v3.4.12.2 — **Gantt per job** dentro `/jobs/{id}` (Frappe Gantt MIT)

---

## v3.4.11 — Hub Pianificazione con 5 viste + filtri trasversali (28 aprile 2026)

`/planning/` diventa un hub con **5 viste** selezionabili da tab e **9 filtri trasversali** applicabili a tutte. Architettura C: una sola entry sidebar, switcher in topbar dell'area main. URL-state (`?view=…&filtro=…`) bookmarkable.

Risponde alla richiesta di flessibilità nelle visualizzazioni del calendario e di poter vedere fino al trimestre.

### Viste implementate (parte 1/2 — top 6 split)

1. **📋 Tabella** — la vecchia lista job, ora filtrata server-side via API
2. **📅 Calendario** — FullCalendar timeGridWeek/dayGridMonth/timeGridDay (era `/planning/calendar`, ora hostato qui)
3. **🗓️ Trimestre** — `multiMonthYear` con `multiMonthMaxColumns: 3`, mostra 3 mesi affiancati
4. **📑 Agenda** — lista cronologica raggruppata per giorno, con badge sorgente (Booking / Timbratura)
5. **✓ Le mie attività** — filtrata sulla resource collegata al `current_user`. Card con label "In ritardo" / "Oggi" / "[giorno]" colorate

Top 6 priorità — viste rinviate a v3.4.12: **Resource Timeline (vis-timeline)**, **Kanban stato job**, **Gantt per job**.

### Filtri trasversali (sidebar fissa)

9 filtri applicati su **tutte** le viste live, server-side:
- search testuale (`q` su code/title)
- reparto (`department_id` — su jobs filtra via cost_lines, su booking via resource)
- cliente (`client_id`)
- progetto (`project_id`)
- job (`job_id`)
- risorsa (`resource_id`)
- stato job (`status`)
- tipo booking (`kind` — project / internal_*)
- periodo da/a (`from_date` / `to_date`)

Ogni filtro è riflesso nella query string → URL bookmarkable. Pulsante "Reset filtri" pulisce tutti.

### Backend

`/planning/api/jobs` esteso: `project_id`, `department_id` (subquery EXISTS via JobCostLine.price_item.department), `q` (LIKE su code/title), `from_date`/`to_date`. Response include `client_id`, `project_id`, `project_code`.

`/planning/api/bookings` esteso: `kind`, `client_id` (join Job), `project_id` (join Job), `department_id` (join Resource), `status`.

`/hr/api/punches` esteso: `client_id`, `project_id`, `department_id` (join analoghi).

### Backward-compat

`/planning/calendar` redirige 302 → `/planning/?view=calendar`. Vecchio template `pages/calendar.html` resta on-disk ma non più routato (rimovibile in futuro).

### Dipendenze

`vis-timeline@7.7.3` caricato via CDN nel template (preparazione v3.4.12 — Resource Timeline). FullCalendar 6.1.11 già caricato include `multiMonth` plugin in core.

### Smoke test E2E

- AST OK
- HTTP 200 su tutte le 5 viste: `?view=jobs|calendar|trimester|agenda|todo`
- `/planning/calendar` → 302 → 200 (redirect)
- Filtri API: `?status=approved` → 1 job, `?client_id=1` → 2 job, `?q=mare` → match Mare Nostrum, `?kind=project` → 7 booking

### File toccati

- `app/main.py` — bump 3.4.10 → 3.4.11
- `app/routers/planning.py` — `/` riscritto come hub con `?view=`, filtri estesi su `/api/jobs` e `/api/bookings`, `_resolve_current_user` aggiunto, `/calendar` → redirect
- `app/routers/hr.py` — `/api/punches` esteso con `client_id`/`project_id`/`department_id`
- `app/templates/pages/planning.html` — riscritto come hub con sidebar filtri + 5 viste tab + URL-state JS

### Limitazioni note

- "Le mie attività" è vuota se l'utente loggato non ha `Resource.user_id` collegato → mostra messaggio guida
- Il `/planning/api/jobs` filtro `from_date`/`to_date` è permissivo (job con date NULL passano sempre): è il comportamento desiderato per non perdere job senza scadenza
- Il vecchio `pages/calendar.html` resta on-disk; rimovibile dopo verifica sul Mac

---

## v3.4.10 — Booking legati a lavorazione + booking interni (28 aprile 2026)

Terzo step del re-design del flusso operativo. Il calendario diventa granulare: pianifico "Sara · Color HDR · Mare Nostrum" invece di "Sara · Mare Nostrum". Aggregazione ore pianificate/lavorate **per singola lavorazione**, non più solo a livello job.

Inoltre apre la categoria "booking interni" (manutenzione, R&D, formazione): ore senza job, generano costo senza profitto, traceabili nel cost report interno.

### Modello

**`BookingKind`** enum nuovo:
- `project` (default, comportamento storico): job_id richiesto, job_cost_line_id opzionale
- `internal_maintenance` / `internal_research` / `internal_training`: senza job, senza lavorazione

**`Booking`**:
- `kind: BookingKind` default `project`
- `job_cost_line_id: int?` FK opzionale a `job_cost_lines.id` (indicizzato): pianifica una lavorazione specifica
- `job_id` ora **nullable** (era NOT NULL): richiede recreate-table su SQLite
- Relationship `Booking.cost_line`

**`TimePunch`**:
- `job_cost_line_id: int?` FK opzionale: consuntiva ore reali contro il monte ore di una specifica lavorazione (calcolo extra per riga)
- Relationship `TimePunch.cost_line`

### Migrazione

`scripts/migrate_booking_cost_line_kind.py` (idempotente): 4 step distinti
1. ALTER ADD `bookings.kind TEXT DEFAULT 'project'`
2. ALTER ADD `bookings.job_cost_line_id INTEGER NULL`
3. ALTER ADD `time_punches.job_cost_line_id INTEGER NULL`
4. **Recreate-table dance** per rilassare `bookings.job_id` da NOT NULL → NULL (SQLite non supporta ALTER COLUMN per nullabilità). Disabilita FK durante, ricrea schema, copia dati con intersezione colonne, ricrea indici.

Voce **[E]/[e]** in `strumenti.bat` / `strumenti.sh`.

### Router /planning

`POST /api/bookings`: nuova firma con validazione coerenza:
- `kind=project`: `job_id` obbligatorio (errore 400 altrimenti); `job_cost_line_id` deve appartenere al job (errore 400 altrimenti)
- `kind=internal_*`: `job_id` e `job_cost_line_id` forzati a NULL
- Helper `_booking_title(b)` produce titolo umano: "Job · Lavorazione · Risorsa" per `project`, "[Tipo] · Risorsa" per interni

`GET /api/bookings`: response include ora `kind`, `job_cost_line_id`, `cost_line_description` in `extendedProps`. Source marker `"source": "booking"`.

### Router /hr

`POST/PUT /api/punches` accetta `job_cost_line_id`. Validazione: la lavorazione deve esistere, e se `job_id` è valorizzato deve appartenere allo stesso job. Se non c'è `job_id` ma c'è `job_cost_line_id`, il `job_id` viene dedotto dalla riga.

Sentinel `clear_cost_line=true` per cancellare l'associazione su PUT (analogo a `clear_end`/`clear_job` esistenti).

### Router /jobs (aggregazione per riga)

- `_aggregate_planned_hours(db, job_id, cost_line_id=None)` ora opzionalmente filtra su riga
- `_aggregate_actual_hours(db, job_id, cost_line_id=None)` idem
- Nuovo `_aggregate_unassigned(db, job_id)`: ore registrate sul job ma con `job_cost_line_id IS NULL` — esposte come `unassigned_planned_hours` / `unassigned_actual_hours` nei totali, mostrate come avviso UI ("⚠ Da assegnare manualmente")
- `_line_dict(line, db=...)` ora include `planned_hours` e `actual_hours` per riga

### UI /jobs/{id}

Tabella lavorazioni: 2 colonne nuove tra "Quotate" e "Extra":
- **Pian.** (ore pianificate via Booking legati a questa riga)
- **Lavor.** (ore lavorate via TimePunch legati a questa riga)

Avviso sotto la tabella se ci sono ore non assegnate a una lavorazione specifica (backward compat per booking/punch creati prima di v3.4.10).

### Smoke test E2E

- AST OK su tutti i file modificati
- T1 GET payload con `planned_hours`/`actual_hours` per riga (default 0 prima di test)
- T2 POST `kind=project` + `job_cost_line_id=15` → ok, booking #7
- T3 POST `kind=internal_maintenance` senza job → ok, `job_id=null`, `job_cost_line_id=null`
- T4 POST `kind=project` senza `job_id` → 400 "Per kind=project serve job_id"
- T5 POST `kind=project` con cost_line di altro job → 400 "non appartiene al job"
- T6 GET dopo T2: line 15 `planned_hours=4`, `unassigned=0`
- T7 POST punch su line 15 + 5h → response include `cost_line_description`
- T8 GET dopo T7: line 15 `planned=4 actual=5`

### File toccati

- `app/main.py` — bump 3.4.9.1 → 3.4.10
- `app/models/models.py` — `BookingKind` enum, `Booking.kind/job_cost_line_id/cost_line`, `Booking.job_id` nullable, `TimePunch.job_cost_line_id/cost_line`
- `app/models/__init__.py` — export `BookingKind`
- `app/routers/planning.py` — POST/GET bookings con validazione kind, helper `_booking_title`
- `app/routers/hr.py` — POST/PUT punches con `job_cost_line_id` + sentinel `clear_cost_line`
- `app/routers/jobs.py` — aggregazione per riga + unassigned, `_line_dict` con planned/actual_hours
- `app/templates/pages/job_detail.html` — colonne Pian./Lavor., avviso unassigned
- `scripts/migrate_booking_cost_line_kind.py` — nuovo (4 step idempotenti + SQLite recreate-table)
- `strumenti.bat` / `strumenti.sh` — voce E

### Limitazioni note (deferite a v3.4.11)

- UI calendario non ha ancora modal aggiornato per scegliere `kind` o `job_cost_line_id` (Matteo: "calendario è davvero brutto, ci lavoriamo poi"). Per ora la creazione di booking interni o legati a lavorazione passa solo da API. Il calendario li **mostra** correttamente con il titolo distinto, ma il modal "+ Booking" mostra il vecchio form con `job_id` obbligatorio.
- L'aggregazione cost-line specifica funziona solo per booking/punch creati con `job_cost_line_id`. I record storici senza il riferimento appaiono nel totale "unassigned" (avviso UI).

---

## v3.4.9.1 — Hotfix: stesso bug `j.budget` in finance service (28 aprile 2026)

Stesso pattern del bug v3.4.8 ma in un altro file. Il modal "dettaglio job" in `/planning` fa due chiamate in parallelo: `/planning/api/jobs/{id}` (fixato in v3.4.8) e `/finance/api/report/job/{id}` (questo). Il secondo restituiva 500 → modal vuoto/rotto → bottone "→ Vai al dettaglio job" mai visibile.

`app/services/finance.py:46,51,59` mappava `job.budget` ma il modello ha `budget_quoted`. Tre occorrenze sostituite tutte insieme.

Fix verificato: `GET /finance/api/report/job/1` ora 200 con `{"budget":64917.0,"margin":61917.0,"margin_pct":95.4,...}`.

---

## v3.4.9 — Lavorazioni come prima class + extra (28 aprile 2026)

Secondo step del re-design del flusso operativo. Le `JobCostLine` (lavorazioni) ora hanno una vita propria nella pagina dettaglio job: ore quotate, lavorate, extra calcolate per riga, con possibilità di aggiungere lavorazioni "extra puro" post-approvazione (caso "il cliente chiede un upres in più").

### Modello

- `JobCostLine.is_extra: bool = False` — marca lavorazioni aggiunte dopo l'approvazione della quote (`quote_line_id` solitamente NULL). Distinto dallo "sforamento monte ore" su lavorazione standard, che si calcola come `quantity_actual > quantity_quoted`.
- Migrazione idempotente `scripts/migrate_jobcostline_extra.py`, voce **[D]/[d]** in `strumenti.bat` / `strumenti.sh`.

### Router /jobs (nuovo)

- `GET /jobs/{id}` — pagina dettaglio
- `GET /jobs/api/{id}` — payload completo con lavorazioni + aggregazioni:
  - `quoted_hours_lines` somma `quantity_quoted` (escluse extra)
  - `actual_hours_lines` somma `quantity_actual` (tutte)
  - `extra_hours_lines` somma per riga: `quantity_actual` se `is_extra`, oppure `max(0, actual - quoted)` per riga standard sforata
  - `planned_hours_calendar` somma durate Booking attivi sul job
  - `actual_hours_punch` somma durate TimePunch chiusi sul job
- `POST /jobs/api/{id}/cost-lines` — crea lavorazione (default `is_extra=true`)
- `PUT /jobs/api/{id}/cost-lines/{line_id}` — modifica con ricalcolo automatico totali
- `DELETE /jobs/api/{id}/cost-lines/{line_id}` — solo se `is_extra=true`. Le lavorazioni ereditate dalla quote possono essere solo modificate (o marcate non-fatturabili)

Helper interni: `_aggregate_planned_hours`, `_aggregate_actual_hours`, `_line_dict`, `_job_payload`.

### Pagina /jobs/{id}

- Header con meta (cliente, progetto, quote, stato, budget quotato)
- 4 cards riepilogo ore: Quotate (indaco), Pianificate calendario (verde menta), Lavorate timbrature (lime), Extra (arancione, sfondo evidenziato)
- Tabella lavorazioni con colonne: descrizione + badge `EXTRA` se applicabile, unità, € unitario, ore quotate (con barra progresso `actual/quoted` arancione se sfora 100%), ore lavorate (in arancione se > quotate), ore extra, totale previsto
- Click riga → modal modifica (per le ereditate, `quantity_quoted` non editabile; bottone elimina visibile solo per extra)
- Bottone topbar "+ Aggiungi lavorazione extra" → modal con descrizione, qty, unit, prezzo, note, fatturabile

### Link da /planning

Modal dettaglio job ora ha bottone "→ Vai al dettaglio job (lavorazioni e ore)" che linka a `/jobs/{id}`.

### Smoke test E2E

- AST OK su tutti i file modificati
- T1 GET `/jobs/api/3` ritorna 4 lavorazioni Gomorra (Conforming, Color HDR, QC, Deliverables) con `quoted_hours_lines=72`
- T2 POST extra "Upres 2K → 4K episodio 5" 8h × €120: id 23, `is_extra=true`, `quoted=0`, `total_expected=960`
- T3 PUT line 15 (Conforming, quoted 30h) con `actual=35` → `extra=5` calcolato, `total_expected=8750` (35×250)
- T4 totali job aggiornati: `actual_hours_lines=35`, `extra_hours_lines=5`
- T5 DELETE riga non-extra (Color HDR) → 400 con messaggio "Le lavorazioni ereditate non possono essere eliminate"
- T6 DELETE riga extra (id 23) → ok
- T7 GET `/jobs/3` HTML → 200

### File toccati

- `app/main.py` — bump 3.4.8.1 → 3.4.9, registrato router `jobs`
- `app/models/models.py` — `JobCostLine.is_extra`
- `app/routers/jobs.py` — nuovo, ~250 righe
- `app/templates/pages/job_detail.html` — nuovo
- `app/templates/pages/planning.html` — link "→ Vai al dettaglio job"
- `scripts/migrate_jobcostline_extra.py` — nuovo
- `strumenti.bat` / `strumenti.sh` — voce D

### Limitazioni note (deferite a v3.4.10)

- Ore pianificate/lavorate sono aggregate **al livello job**, non per singola lavorazione. Per granularità per-lavorazione serve `Booking.job_cost_line_id` (FK opzionale, in v3.4.10) e `TimePunch.job_cost_line_id` (analogo).
- La modifica di una quote dopo l'approvazione non si propaga al job: serve una "sync" esplicita (UI in v3.4.10 o v3.4.11).

---

## v3.4.8.1 — Hotfix: STATUS_LABEL redeclaration + FullCalendar CSS 404 (28 aprile 2026)

Due bug front-end che bloccavano `/planning` e generavano warning console: la pagina mostrava "nulla" anche dopo il fix v3.4.8 perché lo script JS falliva alla prima riga di parsing.

### Bug 1 — `SyntaxError: redeclaration of const STATUS_LABEL`

`/static/js/global.js` dichiara `const STATUS_LABEL` come globale (caricato in `base.html`). Le pagine `planning.html` e `calendar.html` lo ri-dichiaravano localmente con `const`, causando SyntaxError → l'intero script di pagina non veniva mai parsato → `loadJobs()` mai chiamata → tabella job vuota.

Fix: rimosse le ridichiarazioni locali. Il `STATUS_LABEL` globale ha già tutti i valori necessari (`tentative`, `confirmed`, `cancelled`, `completed`, ecc.).

### Bug 2 — FullCalendar CSS 404 → MIME type block

`base.html` linkava `https://cdnjs.cloudflare.com/ajax/libs/fullcalendar/6.1.11/main.min.css`. Quel file non esiste in FullCalendar 6.x: il CDN restituiva una pagina HTML 404 con `Content-Type: text/html`, e il browser bloccava il caricamento per `X-Content-Type-Options: nosniff` su tutte le pagine. In v6 lo stylesheet è incorporato in `index.global.min.js`, niente CSS separato.

Fix: rimosso il `<link rel="stylesheet">` da `base.html`.

### File toccati

- `app/main.py` — bump 3.4.8 → 3.4.8.1
- `app/templates/base.html` — rimosso link `fullcalendar/main.min.css`
- `app/templates/pages/planning.html` — rimossa redeclaration `STATUS_LABEL`
- `app/templates/pages/calendar.html` — rimossa redeclaration `STATUS_LABEL`

---

## v3.4.8 — Quote → Job automatico + bug "non vedo nessun job" (28 aprile 2026)

Primo passo del re-design del flusso operativo discusso con Matteo. Cambia la natura del Job: non è più un'entità da creare a mano, è la materializzazione operativa automatica di una quote approvata. Eredita identità dal progetto.

### Bug fix critico

`/planning/api/jobs` restituiva 500 (`AttributeError: 'Job' object has no attribute 'budget'`). Il codice mappava `j.budget` ma il modello ha `budget_quoted`. Effetto: l'app non mostrava nessun job, anche se in DB c'erano. Una riga di fix in `routers/planning.py:81`.

### Auto-promote Quote → Job

Riscritto `PUT /quotes/api/{id}/status` con side-effect deterministici:

- **draft|sent → approved**: crea il `Job` collegato + `JobCostLine` da ogni `QuoteLine`. Idempotente: se il job esiste già lo ritorna così com'è. Se esiste ma è `cancelled` (riapprovazione dopo rollback), lo ri-attiva senza duplicare lavorazioni.
- **approved → altro**: cancella il job (status=`cancelled`, preserva storico) se non ha attività operative; **blocca con 400** se ci sono booking non-cancelled o TimePunch sul job.
- Codice job auto-generato `{project.code}-J{N}` (es. `MARE-J1`, `MARE-J2`). Decisione: leggibile + chiaro a colpo d'occhio quale progetto + nessun registro globale di numerazione.
- Titolo job ereditato da `project.title` (non da `quote.title` come prima — il riferimento canonico è il progetto).
- Helper `_create_job_from_quote()` + `_job_has_activity()` + `_next_job_code()` esposti per riuso (anche AI capability futura).

Risposta API arricchita: `{"id", "status", "job_created": {id, code, title, lines_count}}` su approve, `{..., "job_cancelled_id"}` su rollback.

### Nuovo stato `JobStatus.cancelled`

Aggiunto valore `cancelled` all'enum `JobStatus`. SQLAlchemy `SAEnum` su SQLite non crea constraint a livello DB → niente migrazione struttura necessaria. Per Postgres in futuro servirà un ALTER TYPE.

### Rimossa creazione job manuale

- Bottone "+ Nuovo job" rimosso da `/planning` (sostituito da link "→ Vai a quotazioni")
- Modal "Nuovo job" rimosso, funzione `createJob()` JS rimossa
- Bottone "▶ Converti in Job" nell'editor quote sostituito con "✓ Approva quote → Job" che fa direttamente `PUT /status?status=approved` con conferma → toast con codice job → redirect `/planning`
- Modal "modal-convert" rimosso, funzione `convertToJob()` rimpiazzata da `approveAndCreateJob()`
- Endpoint `POST /quotes/api/{id}/convert-to-job` marcato deprecated, ora ignora `job_code`/`start_date`/`end_date` e delega a `_create_job_from_quote`
- Endpoint `POST /planning/api/jobs` marcato deprecated (mantenuto per scenari import/migrazione legacy)

### Smoke test E2E

- AST OK su `quotes.py`, `planning.py`, `models.py`
- T1 — `/planning/api/jobs` ora 200, ritorna 4 job esistenti con `budget` corretto
- T2 — PUT quote 2 (draft, project_code="sada") → approved: crea Job 5 `sada-J1` con `title="awdad"` (da project.title), 2 lavorazioni, `budget=2180.8`
- T3 — PUT quote 2 → draft: Job 5 → cancelled (nessuna attività)
- T4 — PUT quote 2 → approved (di nuovo): Job 5 ri-attivato (no duplicazione)
- T5 — POST booking su job 5 + PUT quote 2 → draft: 400 con messaggio "il job sada-J1 ha attività…"

### File toccati

- `app/main.py` — bump 3.4.7 → 3.4.8 (FastAPI + /health hardcoded)
- `app/models/models.py` — `JobStatus.cancelled`
- `app/routers/quotes.py` — `_next_job_code` + `_create_job_from_quote` + `_job_has_activity` helper, `update_quote_status` riscritto, `convert_to_job` deprecato
- `app/routers/planning.py` — fix bug budget, `POST /api/jobs` deprecated
- `app/templates/pages/quotes.html` — bottone "Approva → Job" + modal-convert rimosso + `approveAndCreateJob()`
- `app/templates/pages/planning.html` — modal nuovo job rimosso + bottone topbar sostituito + `createJob()` JS rimossa

### Decisioni non prese (deferite a v3.4.9+)

- Modifica quote dopo approvazione: oggi NON propaga al job. Serve un meccanismo "ricarica monte ore" o richiesta esplicita di ri-sincronizzazione (in v3.4.9 con la pagina dettaglio job)
- `JobCostLine.is_extra` flag per nuove lavorazioni post-quote (v3.4.9)
- `Booking.job_cost_line_id` FK opzionale per legare booking a lavorazione specifica (v3.4.10)
- `BookingKind` per booking interni senza job (manutenzione/training/research) (v3.4.10)

---

## v3.4.7 — Sezione HR e timbrature (28 aprile 2026)

Apre il dominio amministrativo/HR per la rendicontazione delle ore di lavoro. Tutte le risorse umane (interne + freelance) rendicontano qui — i freelance senza login possono essere "timbrati" da un manager.

Step "timbrature/idle" del cantiere calendario, scelta architetturale: **Opzione 2 — modello `TimePunch` separato**. Booking resta dominio della pianificazione (intenzione: chi sarà su quale job e quando), TimePunch è il consuntivo di presenza (chi è stato a lavoro e per quanto). Niente over-loading del modello Booking.

### Modello

- `TimePunch(tenant_id, resource_id, job_id?, start_datetime, end_datetime?, kind, notes, created_by_user_id?)`
- `end_datetime` nullable = "in corso" (ingresso senza ancora uscita)
- `job_id` nullable = ore non legate a progetto specifico
- `created_by_user_id` nullable = chi ha registrato (manager/HR per freelance senza login)
- Enum `PunchKind`: `shift` (turno, con o senza job), `idle` (presente non allocato), `leave` (ferie/permesso), `sick` (malattia), `break_` (pausa), `overtime` (straordinario)
- Relationship: `Resource.time_punches` (back_populates)

### Router `/hr`

- `GET /hr` — pagina HR: filtri (risorsa, periodo, tipo) + tabella + footer totali
- `GET /hr/api/punches` con filtri `resource_id`, `job_id`, `kind`, `from_date`, `to_date`, `format=json|fullcalendar`
- `POST /hr/api/punches` — crea (validazione: risorsa esistente + tipo person, end > start, job esiste se presente)
- `PUT /hr/api/punches/{id}` — modifica (sentinel `clear_end=true` / `clear_job=true` per cancellare; `Form(None)` non distinguibile da assente)
- `DELETE /hr/api/punches/{id}` — elimina (hard delete, non soft — le timbrature errate vanno tolte)
- `GET /hr/api/summary` — totali ore per kind nel periodo (esclude le in-progress); ritorna `totals`, `grand_total`, `labels`, `colors`

### UI sezione HR `/hr`

- Filtri: dropdown risorse persona, range date (con shortcut "settimana corrente" / "mese corrente"), kind, reset
- Cards totali in alto con accent-color per kind + card grand-total indaco
- Tabella: data, risorsa (con dot colore), inizio/fine (in corso → tag indaco), durata (h), kind (badge col bordo colore kind), job (codice + titolo), note
- Click riga → modal modifica con bottone Elimina; "+ Nuova timbratura" in topbar
- Modal: risorsa, kind, datetime-local start/end (vuoto = in corso), job opzionale, note

### Integrazione calendario

- `/planning/calendar` ora ha **2 eventSources** (FullCalendar): bookings + punches (`format=fullcalendar`)
- Legenda riorganizzata: sezione "Sorgenti" (toggle bookings/punches) + sezione "Risorse" (toggle per risorsa)
- Filtri ora **funzionanti server-side via render-time hide** (`eventDidMount` setProp display:none) — prima il filtro risorsa era no-op
- Eventi punch hanno colore per kind (idle grigio, leave lavanda, sick rosso, break giallo, overtime arancione, shift = colore risorsa)
- Click su punch mostra durata + "in corso" se end null

### Sidebar

Voce **🕐 Ore lavoro** sotto Operativo (dopo Assegnazioni, prima della sezione Preventivi).

### Migrazione

- `scripts/migrate_time_punches.py` — crea tabella `time_punches` via `Base.metadata.create_all` (idempotente: skip se già esiste)
- Voce **[C]/[c]** in `strumenti.bat` / `strumenti.sh`

### Smoke test E2E

- AST OK su `models.py`, `routers/hr.py`, `main.py`, migration script
- Migration: tabella creata, re-run idempotente
- `/health` 3.4.7, `/hr/` 200, `/hr/api/punches` 200, `/hr/api/summary` 200, `/planning/calendar` 200
- POST punch chiusa: durata 9.00h calcolata, kind=shift colore risorsa
- POST punch in-progress (end null): duration_h null, summary lo esclude correttamente
- PUT chiude la in-progress: end aggiornato, duration ricalcolata 1.5h
- DELETE: hard delete, lista finale vuota
- Format `fullcalendar`: title `risorsa · kind`, colore per kind, extendedProps con `source=punch`

### File toccati

- `app/main.py` — bump 3.4.6 → 3.4.7, registrazione router `hr`
- `app/models/models.py` — `PunchKind` enum, `TimePunch` class, `Resource.time_punches` relationship
- `app/models/__init__.py` — export `TimePunch`, `PunchKind`
- `app/routers/hr.py` — nuovo, ~280 righe
- `app/templates/pages/hr.html` — nuovo
- `app/templates/pages/calendar.html` — secondo eventSource, legenda sorgenti, filtro client-side via `eventDidMount`
- `app/templates/base.html` — voce sidebar 🕐
- `scripts/migrate_time_punches.py` — nuovo
- `strumenti.bat` / `strumenti.sh` — voce C

### Promemoria backlog

- **Aggregazioni HR avanzate** (rinviate): report ore lavorate per progetto e per risorsa nel mese, costo orario × ore in cost report, esportazione CSV/PDF cedolino, integrazione con `JobCostLine` consuntivo
- **Auto-timbratura per utenti con login**: bottone "🟢 Inizio turno" / "🔴 Fine turno" nella topbar per chi è collegato (oggi: solo creazione manuale via modal)
- **Mancano gli orari standard** per tipo risorsa (full-time / part-time / freelance senza vincolo) per calcolare straordinari automaticamente

---

## v3.4.6 — Booking multi-tenant (28 aprile 2026)

Fix di coerenza con la convenzione Fase 1-bis: il modello `Booking` era l'unica entità di business senza `tenant_id`. Tutti i restanti modelli (Resource, PriceItem, Client, Project, Department…) lo avevano già da v3.0.

Primo passo del cantiere "calendario e pianificazione" — propedeutico a tutto il resto (UX calendario, ferie/indisponibilità, riconciliazione assignment↔booking, capability AI, timbrature/idle).

### Modello

- `Booking.tenant_id` (FK `tenants.id`, default 1, indicizzato)
- Convenzione: ogni query nel router parte con `Booking.tenant_id == CURRENT_TENANT`

### Router `/planning`

- `CURRENT_TENANT = 1` in cima al file (pattern allineato a `resources.py` / `pricelist.py`)
- `GET /api/bookings` filtra per tenant
- `POST /api/bookings` imposta `tenant_id=CURRENT_TENANT` sul nuovo record + il check di conflitto risorsa è anch'esso tenant-scoped (in multi-tenant hard, due tenant possono avere booking sovrapposti senza falsi conflitti)
- `DELETE /api/bookings/{id}` filtra per tenant prima del soft-cancel

### Migrazione

- `scripts/migrate_booking_tenant.py` (idempotente): `ALTER TABLE bookings ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1`. Tutti i booking esistenti vengono backfillati a `tenant_id=1`.
- Voce **[B]/[b]** in `strumenti.bat` / `strumenti.sh`.

### Smoke test

- AST OK su `models.py`, `routers/planning.py`, script di migrazione
- Migrazione applicata sul DB locale: 5 booking esistenti backfillati a tenant 1
- Re-run idempotente (`tenant_id già presente`)
- `/health` 200 v3.4.6
- `/planning/calendar` 200, `/planning/api/bookings` 200 con i 5 booking seed visibili
- `POST /planning/api/bookings` validazione corretta (422 sui campi obbligatori mancanti)

### File toccati

- `app/main.py` — bump 3.4.5 → 3.4.6 (FastAPI version + `/health` hardcoded)
- `app/models/models.py` — `Booking.tenant_id`
- `app/routers/planning.py` — `CURRENT_TENANT` + filtri/set tenant
- `scripts/migrate_booking_tenant.py` — nuovo
- `strumenti.bat` / `strumenti.sh` — voce B

---

## v3.4.5 — Modal "Aggiungi voce" ridisegnato (28 aprile 2026)

Il modal di selezione voce nella quotazione era confuso: form sempre visibile con i campi vuoti prima della scelta, sidebar piatta senza raggruppamento, risultati con metadata scarna e separatore "·" poco leggibile.

### Modal redesign

- **Sidebar categorie raggruppate per reparto**, con dot colorato nel colore reparto e label maiuscoletto. La voce attiva ha bordo sinistro nel colore reparto. "Tutte le voci" e "+ voce libera" stanno in cima come scorciatoie sticky.
- **Risultati listino più leggibili**: card con striscia colorata reparto a sinistra, nome + prezzo in cima, badge categoria (indaco) + badge reparto (nel colore reparto), descrizione e keyword sotto. Hover e selected hanno feedback visivo distinto.
- **Pannello selezione condizionale**: prima di scegliere si vede solo il messaggio _"Seleziona una voce dal listino, oppure crea voce libera"_. Dopo la scelta appare un header con nome + tag categoria/reparto + prezzo listino di riferimento, poi i campi qty/unità/prezzo/descrizione/dettaglio in una griglia 8-col.
- **Voce libera** richiamabile sia dalla sidebar (bottone tratteggiato) che dall'empty state che dal "no results" → riusa lo stesso pannello con etichetta `✏️ Voce libera (non in listino)`.
- **Conteggio risultati** in alto a destra (`X di Y voci` se troncato a 80, altrimenti totale). La sidebar conta voci sul filtro testo, indipendentemente dalla categoria attiva (così si vede dove "vivono" i match in altre categorie).
- Search input più grande (14px), modal a 1080px, layout flex column con altezze gestite (sidebar+lista 48vh, pannello selezione flex-shrink:0).

### File toccati

- `app/templates/pages/quotes.html` — sostituiti markup modal-add-line, blocco `<style>` dedicato, funzioni JS `openAddLine`, `renderAlSidebar`, `setAlCat`, `filterPricelist`, `pickPriceItem`. Aggiunte `clearSelection`, `enableFreeLine`, helper `alEscape` / `alMatchesText`.
- Nessuna modifica a `addLine()` (gli id `al-desc/-detail/-qty/-unit/-price/-price-item-id/-base-unit/-base-price` sono preservati) né alle API backend.

---

## v3.4.4 — AI search-first nel listino + scenario C (27 aprile 2026, sera tardi)

Risponde alla nota originale **#5** di Matteo e al bug **#6** (copilot non aggiunge righe a quote esistente). Tre cambi sostanziali al copilot AI.

### A. Voci listino nel context AI
`build_context()` ora include un blocco `VOCI LISTINO ATTIVE (id | name | category | unit | €list | keywords)` con tutte le voci attive (limite 200, oggi 75 voci × ~2KB = trascurabile sui token). Senza questo blocco il modello non aveva modo di sapere quali voci esistono → spiegava perché le righe AI venivano sempre messe come "voci libere" con `unit_price=0`. Il blocco viene rigenerato live ad ogni turno (nessuna cache, niente da invalidare).

### B. `propose_quote_line` esteso con `price_item_id`
Schema accetta nuovo campo opzionale `price_item_id` (numero PK voce listino). Quando passato:
- la riga viene legata al listino (`QuoteLine.price_item_id` valorizzato)
- `unit_price`, `unit`, `description` vengono ereditati dalla voce listino se non specificati esplicitamente dall'AI
- in v3.4.3 le righe AI erano sempre "voci libere" → ora possono essere "voci dal listino"

### C. Nuova capability `propose_new_item_and_line` (scenario C)
Quando l'utente conferma "non c'è in listino, creala", l'AI propone questa azione che in **singola transazione**:
1. Crea la `PriceItem` (richiede `category_name`, `name`, `unit`, `price_list`)
2. Crea la `QuoteLine` collegata (con `quantity` e prezzo del listino appena creato)

Una sola conferma utente, niente "doppio click" come scenario B. Categoria autocreata se nuova.

### D. System prompt: REGOLA SEARCH-FIRST
Nuova sezione esplicita prima di "FORMATO JSON OBBLIGATORIO". Cascata su 3 livelli per ogni richiesta di aggiunta voce a quote:

| Caso | Comportamento atteso AI |
|---|---|
| **1 match chiaro** in listino | `propose_quote_line` con `price_item_id` (basta `quantity`) |
| **2-4 match plausibili** | NON azione, risposta in **markdown numerato** che chiede quale scegliere |
| **0 match** | Markdown con due opzioni: (a) voce libera o (b) scenario C, e attesa risposta |
| **Voce esplicitamente nuova** | `propose_new_item_and_line` direttamente |

Esempio nel prompt: utente "5 giorni di Color HDR", listino ha `12 | Color HDR | Color | day | €1200` → AI propone `{"price_item_id": 12, "quantity": 5}`, e il backend completa con `unit_price=1200`, `unit="day"`, `description="Color HDR"`.

### E. UI copilot
- `actionTypeLabel` e `renderActionSummary` aggiornati per il nuovo type
- `summaryQuoteLine` ora mostra `✓ legata a voce listino #N` o `⚠ voce libera (non legata al listino)` per dare feedback visivo immediato
- Nuovo `summaryNewItemAndLine` con anteprima totale (`qty × price = subtotale`)

### Smoke test
- Sintassi Python OK, copilot.js 162/347 braces/parens matched, HTTP 200
- `/health` → 3.4.4 ✓
- 8 capability totali registrate (era 7)
- `build_context()` include 75 voci listino, ~2140 token totali (era ~600)
- Test E2E con prompt reali: rinviato a Matteo (richiede provider AI attivo). Suggeriti:
  - `"aggiungi a Q-2026-001 due giorni di Color HDR"` → match chiaro, `propose_quote_line` con `price_item_id`
  - `"aggiungi del color"` → match multipli, AI elenca opzioni in markdown
  - `"aggiungi a Q-2026-001 una nuova voce Foley editing, listino 350/giorno categoria Audio"` → `propose_new_item_and_line`

### Promemoria backlog
- Aggiornamento context al cambio listino: oggi è già live (rigenerato ad ogni turno). Se in futuro le voci listino superano ~500 e il context diventa pesante, valutare cache + invalidazione su create/update/delete `PriceItem`.

### File toccati
- `app/services/ai_assistant.py` — context esteso + REGOLA SEARCH-FIRST + nuovo handler + dispatch + schema in prompt
- `app/static/js/copilot.js` — label e renderer per `propose_new_item_and_line`, `summaryQuoteLine` riscritto con feedback listino
- `app/main.py` — bump 3.4.3 → 3.4.4

---

## v3.4.3 — Card copilot human-readable (27 aprile 2026, sera tardi)

Refactor UX delle card di proposta AI nel drawer copilot. Prima si vedeva solo il payload JSON crudo escapato, ora ogni `action_type` ha un renderer dedicato che mostra solo i campi rilevanti in formato leggibile, con un toggle `</> Mostra dati grezzi` per chi vuole vedere il JSON completo (utile per debug).

### Renderer per type
- **propose_client** → nome (bold) + forma giuridica · industry + città/paese + P.IVA + email
- **propose_project** → codice (bold) · titolo + cliente + minuti/material/fps
- **propose_project_metadata** → coppie `chiave: valore` per ogni campo passato
- **propose_quote** → numero · titolo · date/IVA + tabella mini con righe (descrizione, q.tà, unità, €), tronca dopo 8 righe con "+N altre"
- **propose_quote_line** → descrizione (bold) + quantità × prezzo + riferimenti (quote#, listino#, categoria override)
- **propose_price_item** → descrizione (bold) + categoria · unità + 3 livelli prezzo + keywords
- **web_search** → "Cerca: <query>"
- **fallback** → messaggio "Nessun renderer per questo tipo. Apri 'dati grezzi'."

### Toggle JSON
Bottone `</> Mostra dati grezzi` sotto la card; al click rivela un `<pre>` con il JSON completo della `data` (con scroll, max-height 200px). Stato chiuso di default.

### Stile
Box summary con bordo sinistro indaco e sfondo semi-trasparente (lo stesso accento del resto dell'app). Mini-tabelle con header maiuscoletto, valori monospace allineati a destra. Niente impatto sulle `applied/rejected/failed` card storiche: il summary si genera dal `data` salvato come al solito.

### File toccati
- `app/static/js/copilot.js` — `renderActionCard` riscritta, nuove `renderActionSummary` + 6 funzioni `summary*` + helper `fmtCur` + `copilotToggleJSON`
- `app/templates/components/copilot.html` — CSS per `.cp-action-summary`, `.cp-mini-table`, `.cp-debug-toggle`, `.cp-muted`
- `app/main.py` — bump 3.4.2 → 3.4.3

### Smoke test
- `/health` → 3.4.3 ✓
- copilot.js: 148 braces matched, 319 parens matched, HTTP 200 ✓
- `/quotes/`, `/assignments/` → 200 ✓
- Test E2E browser: rinviato a Matteo (richiede provider AI attivo per generare card)

---

## v3.4.2 — Quick wins copilot + categoria libera quote (27 aprile 2026, sera tardi)

Quattro micro-feature richieste in batch dopo il test del copilot.

### #21 + #22 — Textarea + a capo + stop thinking (copilot)
- Drawer copilot: input convertito da `<input>` a `<textarea>` auto-resize. Nuova convenzione tasti: **Enter = a capo**, **Ctrl/⌘+Enter = invia**.
- Bottone Invia diventa "✕ Stop" durante la generazione: click annulla la fetch lato client via `AbortController`. La generazione lato server (Ollama/Claude) prosegue fino a fine, ma il client non aspetta più la risposta — sufficiente per evitare sovraccarico richieste e UX bloccata.

### #23 — Categoria libera in quotazione (override per riga)
**Modello**: nuova colonna `quote_lines.category_override TEXT NULL`. Se valorizzata, prevale su `price_item.category` nei raggruppamenti (editor / PDF / CSV / XLSX). Permette di:
- spostare voci tra categorie senza cambiare la voce listino
- dare una categoria a "voci libere" (senza `price_item_id`)
- creare categorie ad hoc per la singola quotazione

**UI editor quote**: nuovo bottone 📁 sulla riga (vicino al ✕). Apre un prompt con elenco numerato di tutte le categorie note (dalle voci della quote + dal listino) + opzione "+ Nuova categoria…" + "0. Ripristina categoria del listino" se override attivo. Si può anche scrivere un nome libero. Niente layout cambiato: il bottone si infila accanto al ✕.

**Backend**:
- `POST /quotes/api/{id}/lines` accetta `category_override: Form(Optional[str])`
- `PUT /quotes/api/{id}/lines/{line_id}` idem; per **cancellare** un override usa il sentinel `__CLEAR__` (FastAPI con `Form(None)` parsa la stringa vuota come `None`, indistinguibile da "non passato")
- `GET /quotes/api/{id}` espone `category_override` nella response per ogni line
- helper `_line_category` centralizza la logica → editor JS, CSV, XLSX, PDF rispettano automaticamente l'override

**Migrazione**: `scripts/migrate_quote_category_override.py` (idempotente). Aggiunta voce **[9]** in `strumenti.bat`/`strumenti.sh` (la voce "uploads" si è spostata su `[A]` / `[a]`).

### #24 — Parser AI tollera commenti Python (`#`)
Già rilasciato in v3.4.1: `_strip_json_comments_and_trailing_commas` riconosce `// …`, `/* … */` E `# …` a fine riga, rispettando stringhe ed escape. Documentato qui per completezza del giro.

### Smoke test E2E (live)
- Migrazione applicata su `mediaflow.db` (colonna aggiunta)
- `PUT /lines/{id}` con `category_override="Color"` → riga 18 ora in gruppo "Color"
- `PUT` con sentinel `__CLEAR__` → override cancellato, riga torna in "Altro"
- `POST /lines` con `category_override="Servizi extra"` → nuovo gruppo creato
- `GET /quotes/api/3/export.csv` → tre gruppi distinti con subtotali separati ✓
- `GET /quotes/api/3/export.xlsx` → 6.2 KB validato
- `GET /quotes/api/3/pdf` → 4.4 KB, magic `%PDF-1.4`, raggruppamento corretto

### File toccati
- `app/main.py` — bump 3.4.1 → 3.4.2
- `app/models/models.py` — colonna `QuoteLine.category_override` (già in 3.4.1)
- `app/routers/quotes.py` — helper `_line_category` con override, GET espone override, POST/PUT line accettano `category_override` con sentinel `__CLEAR__`
- `app/services/quote_pdf.py` — `_line_category` allineata
- `app/templates/pages/quotes.html` — bottone 📁 sulla riga, funzione `changeLineCategory(lineId)`
- `app/templates/components/copilot.html` — `<textarea>` auto-resize (già in 3.4.1)
- `app/static/js/copilot.js` — `AbortController` + bottone stop (già in 3.4.1)
- `app/services/ai_provider.py` + `ai_assistant.py` — parser JSON lenient (già in 3.4.1)
- `scripts/migrate_quote_category_override.py` — nuovo
- `strumenti.bat` + `strumenti.sh` — voce [9] migrazione, `[A]`/`[a]` per uploads

---

## v3.4.1 — Bugfix copilot: JSON con commenti (27 aprile 2026, sera)

**Sintomo riportato**: il copilot non aggiunge la quotazione richiesta; il drawer non mostra la card di conferma. Log AI: l'azione viene generata correttamente (`type: propose_quote`, `lines` complete) ma silenziosamente scartata.

**Root cause**: il modello attivo (Ollama llama3.1:8b) infila commenti JavaScript dentro il JSON dell'azione:
```json
"number": null, // verrà generato automaticamente
"issue_date": "2026-04-27", // data corrente
"vat_rate": 22, // aliquota IVA predefinita
```
JSON è strict: `json.loads()` solleva `JSONDecodeError`, `safe_json_parse` ritorna None, l'azione non viene salvata come `AIAction` e non torna in risposta. Niente errore visibile, solo silenzio.

**Fix**:
1. `safe_json_parse` ora esegue tre tentativi in cascata: (a) parse strict → (b) strip di `// ...`, `/* ... */` e trailing commas state-aware (rispetta stringhe ed escape, non tocca URL `https://...`) → (c) regex sul primo blocco `{...}`.
2. System prompt rinforzato con sezione **"FORMATO JSON OBBLIGATORIO"**: zero commenti, zero virgole finali, zero apici singoli, numeri non quotati, omettere campi invece di metterli a `null`.
3. `extract_proposed_actions` logga ora i casi di `parse fallito` o `type non valido` con i primi 200 char del payload — niente più silenzio se in futuro si presenta un altro pattern di output deviante.

**Smoke test**: payload reale dal log `Aggiungi una quotazione per il prog.txt` (con 4 commenti `//` + 1 trailing comma) → `safe_json_parse` ora estrae `type=propose_quote, data.project_id=6, lines=1` correttamente. Prima falliva al char 135.

### File toccati
- `app/services/ai_provider.py` — nuova `_strip_json_comments_and_trailing_commas`, cascata in `safe_json_parse`
- `app/services/ai_assistant.py` — sezione "FORMATO JSON OBBLIGATORIO" in `ASSISTANT_SYSTEM_PROMPT`, regola 6 aggiornata ("OMETTI il campo invece di null"), warning log in `extract_proposed_actions`

---

## v3.4 — Export tabellari + PDF italiano + categorie editabili (27 aprile 2026)

### Export listino e quotazioni in CSV / Excel

Nuovi endpoint, scaricabili da menu dropdown "⬇ Esporta" sia in `/pricelist` (topbar) sia nell'editor quotazione:

- `GET /pricelist/api/export.csv` — UTF-8 con BOM (apre dritto in Excel/Numbers), separatore `;`, colonne: Categoria · Reparto · Nome · Descrizione · Unità pre · Unità · Prezzo · Prezzo medio · Prezzo basso · Hardcosts · Keywords · Attivo
- `GET /pricelist/api/export.xlsx` — Excel nativo con header brand indigo, larghezze auto, freeze pane prima riga
- `GET /quotes/api/{id}/export.csv` — quote con righe raggruppate per categoria, **subtotali**, sconti categoria, totals footer
- `GET /quotes/api/{id}/export.xlsx` — stessa struttura ma con styling: header brand, righe categoria evidenziate, riga "TOTALE IVA inclusa" su sfondo indigo, format numerico `#,##0.00`

L'export JSON pre-esistente resta come "backup completo" reimportabile.

### Subtotali per categoria

Aggiunta riga subtotale **prima** dello sconto categoria, sia nell'editor live (UI quote) sia nel PDF e negli export tabellari. Permette di leggere a colpo d'occhio quanto pesa ciascun gruppo.

### PDF quotazione: redesign in italiano

`quote_pdf.py` riscritto:

- Header con dati tenant (nome, indirizzo, P.IVA, contatti) letti dalla tabella `tenants`
- Blocco cliente strutturato con righe etichettate (Cliente, Titolo, Data, Validità) e separatori sottili
- Sezione "PREMESSE TECNICHE" con materiale, durata, fps, formato consegna
- Tabella righe con righe alternate (`ROWBACKGROUNDS`), header indigo, header categoria su banda BAND (`#eef1ff`), riga subtotale su grigio chiaro
- Box totali a destra (62mm + 38mm) con riquadro grigio chiaro, riga finale "TOTALE (IVA inclusa)" su sfondo indigo
- Etichette tutte in italiano: "QUOTAZIONE", "Q.tà", "Sconto %", "Totale lordo", "Subtotale", "TERMINI DI PAGAMENTO", "NOTE", footer con "Si applicano le nostre Condizioni Generali di Vendita"
- Date formattate `dd/mm/yyyy` (helper `_fmt_date`)

### UI editing categorie listino

Sidebar categorie in `/pricelist`: pulsante ✏️ accanto a ogni categoria → modal di modifica con nome, descrizione, ordine + bottone "Elimina" (visibile solo se la categoria non ha voci collegate). Endpoint `PUT/DELETE /pricelist/api/categories/{id}` esistevano già — solo cablaggio UI.

### File toccati

- `app/routers/pricelist.py` — `_pricelist_rows_for_export`, `/api/export.csv`, `/api/export.xlsx`
- `app/routers/quotes.py` — `_quote_export_rows`, `/api/{id}/export.csv`, `/api/{id}/export.xlsx`
- `app/services/quote_pdf.py` — riscritto in italiano, header tenant, subtotali, box totali laterale
- `app/templates/pages/pricelist.html` — dropdown export, modal `modal-edit-cat`, funzioni `editCategory`/`saveCategoryEdit`/`deleteCategoryFromEdit`
- `app/templates/pages/quotes.html` — dropdown export nell'editor, riga subtotale per categoria, stile `.ql-cat-sub-row`
- `app/main.py` — version `3.3.0` → `3.4.0`

### Smoke test live
- `/pricelist/api/export.csv` → 200 (12.9 KB)
- `/pricelist/api/export.xlsx` → 200 (12.8 KB)
- `/quotes/api/2/export.csv` → 200
- `/quotes/api/2/export.xlsx` → 200, struttura verificata via `openpyxl.load_workbook`: header riga 5, riga categoria, riga voce con format numerico
- `/quotes/api/2/pdf` → 200 magic bytes `%PDF-1.4`, 4.3 KB con tutte le sezioni nuove

### Bug risolto in corso d'opera

`MergedCell.column_letter` non esiste — colpiva l'export xlsx delle quote (header riga 1 mergiato). Sostituito `ws.cell(row=1, column=i).column_letter` con `openpyxl.utils.get_column_letter(i)`. Stesso pattern preventivamente sistemato in pricelist.

---

## v3.3 — Fase 4 step F1: interazioni immediate (27 aprile 2026)

### Click-to-open su tutte le tabelle

Sostituiti i bottoni "Apri" con click sull'intera riga. Pattern già presente in `/projects` esteso a:
- **Clienti** — `<tr onclick="openClientDetail(id)">`
- **Listino** — riga apre l'editor; bottone ✏️ rimosso (ridondante), 🗑️ resta con `event.stopPropagation()`
- **Quotazioni** — riga apre l'editor; rimosso link cliccabile sul project_title interno (apriva il progetto, conflitto con click di riga)
- **Reparti** — riga apre il modal di modifica; 🗑️ resta isolato
- **Risorse** — già click-to-open dal precedente refactor

### Drag&drop assegnazione risorse → job

Due viste diverse, stessa meccanica (SortableJS):

1. **Pagina progetto** (`/projects/{id}` → tab "Risorse")
   - Colonna sinistra: lista risorse attive del tenant con search live
   - Colonna destra: card per ogni job del progetto con drop target
   - Drag risorsa nella card del job → POST `/projects/api/{id}/assignments` con job_id+resource_id (idempotente)
   - Click ✕ sul chip → DELETE assignment
   - Default intelligenti: `agreed_daily_rate`/`agreed_hourly_rate`/`role_in_project` ereditati dalla risorsa

2. **Pagina kanban** (`/assignments`)
   - Colonna sinistra fissa: tutte le risorse attive con filtro reparto + search
   - Colonne orizzontali scroll: tutti i job in stato `draft|quoting|approved|active|on_hold` del tenant
   - Drag tra colonne sposta l'assegnazione (DELETE+POST atomicità lato client)
   - Voce sidebar 🧩 Assegnazioni

### File toccati

- `app/routers/projects.py` — endpoint `GET/POST/PUT/DELETE /projects/api/{id}/assignments[/{aid}]` con tenant filter implicito (project_id) + lista risorse disponibili nello stesso payload del GET
- `app/routers/assignments.py` (nuovo) — kanban globale: `GET /assignments/api/board`, `POST /assignments/api/move`, `DELETE /assignments/api/{aid}`
- `app/templates/pages/assignments.html` (nuovo) — vista kanban con SortableJS CDN
- `app/templates/pages/project_detail.html` — tab "Risorse" + drag&drop + style chip/drop
- `app/templates/pages/clients.html`, `pricelist.html`, `quotes.html`, `departments.html` — click-to-open
- `app/templates/base.html` — voce sidebar 🧩 Assegnazioni
- `app/main.py` — registrato router `assignments`

### Smoke test
- `/assignments/api/board` → 200, jobs+risorse caricate
- `POST /assignments/api/move` su risorsa già assegnata → `{duplicate:true}` correttamente
- `/projects/api/1/assignments` → 200 con jobs e available_resources nel payload
- `/assignments/` (HTML) → 200

---

## v3.2.1 — Patch capability AI + fix tenant clienti (26 aprile 2026, sera)

### Capability AI completate / aggiunte

- **`propose_quote` end-to-end**: la capability era esposta nel system prompt ma il primo test live (`Crea quotazione per "Una storia inquinata"…`) falliva con `Stato: failed · Manca 'number'`. Sistemato:
  - `number` auto-generato `Q-{anno}-NNN` se non specificato (progressivo basato sulle quote esistenti).
  - `title` ← titolo del progetto se mancante.
  - `issue_date` default oggi, `valid_until` default +30gg, override se l'AI mette date allucinate (es. 2023 quando siamo nel 2026).
  - `lines` opzionali: se presenti, quote+righe vengono create in **singola transazione** (un solo Apply nel drawer copilot). Rollback completo se anche una sola riga è invalida.
- **`propose_project`** (nuova capability): crea un progetto con `code` + `title` + `client_id` (PK) o `client_name` (lookup esatto). Errore esplicito se il cliente non esiste, invece di indovinare.
- System prompt rinforzato con tre regole critiche: `id` ≠ `code`, no date passate inventate, una sola azione per turno.

Totale capability disponibili: **7** (`propose_client`, `propose_project`, `propose_project_metadata`, `propose_quote`, `propose_quote_line`, `propose_price_item`, `web_search`).

### `/clients` — bottone "Crea + popola con AI"

Nel modal "Nuovo cliente", oltre a "Crea cliente" è disponibile **"✨ Crea + popola con AI"**: crea il cliente con i dati inseriti dall'utente e poi chiama subito `/clients/api/{id}/enrich` per popolare metadati mancanti (P.IVA, sede, sito, filmografia recente). Se l'arricchimento fallisce, il cliente resta comunque creato e l'utente è avvisato. Il bottone appare solo quando un provider AI è configurato per l'utente.

### Fix `clients.py`

- Tutte le query by-id (`get_client`, `update_client`, `delete_client`, `enrich_client_api`) ora filtrano per `tenant_id == CURRENT_TENANT`. Convenzione Fase 1-bis allineata con `pricelist.py` / `resources.py`.
- `search_and_create` (`/clients/api/search-enrich`) ora imposta `tenant_id=CURRENT_TENANT` sul nuovo cliente e tenant-filtra la verifica duplicati.
- Migrazione dal legacy `get_provider()` (singleton globale `.env`) a `get_provider_for_user(user_id, db)` con risoluzione utente da cookie JWT. Risolve il caso in cui un utente con provider configurato in DB non vedeva i bottoni AI perché `.env` non aveva `AI_PROVIDER`.
- `enrich_client(name, known_info, provider=None)`: accetta provider iniettato dal router; fallback al legacy globale per retrocompat.

### Enrichment AI multi-step (sera tardi)

- **Web search nativo Anthropic**: nuovo metodo `extract_json_with_web_search()` su `AIProvider` (default no-op) implementato in `ClaudeProvider` con il tool server-side `web_search_20250305`. Il modello decide autonomamente quante query fare (cap 5), legge i risultati lato Anthropic, segue link, produce JSON strutturato in singola chiamata. Costo ~$10/1000 ricerche oltre ai token.
- **Cascata in `enrich_client`**: priorità (1) provider con web_search nativo (Claude), (2) Tavily se configurato, (3) AI knowledge only. Ogni path gestito da una funzione separata (`_try_native_web_search`, `_try_tavily`, `_try_noweb`); se uno fallisce, il successivo viene tentato. La response API include sempre `web_search_used` per il toast UI.
- Effetto pratico: con Claude attivo, "Mad Entertainment" ora ricerca davvero il sito ufficiale, sede, filmografia recente — niente più dipendenza da Tavily.

### Bugfix `/clients` (sera tardi)

- **Tasto "Elimina" non funzionava**: il render del footer faceva `onclick="deleteClient(${id}, ${JSON.stringify(c.name)}, ...)"`. Le virgolette doppie del JSON dentro un attributo HTML che usa esso stesso virgolette doppie come delimitatore rompevano il parsing → l'handler onclick non veniva mai chiamato. Fix: passaggio via `data-client-id` / `data-has-projects` sul bottone e `data-client-name` sul modal, lette dentro la funzione. Niente più escaping pasticciato in template literal.
- **Tasto "Arricchisci con AI" → 500**: `enrich_client()` dipendeva da Tavily come unica fonte; senza `TAVILY_API_KEY` ritornava None → 500 generico. Fix: fallback a "AI knowledge only" (l'AI usa il proprio training, segnando `notes` con un disclaimer esplicito). Il response include ora `web_search_used: bool` così il toast UI può distinguere "Cliente arricchito con AI" da "Cliente arricchito (senza ricerca web — fonti AI)". Tavily resta opzionale ma non più bloccante.
- `aiEnrich(id, btn)`: passaggio esplicito di `this` invece di `event.target` (più robusto, restore dello stato originale del bottone in caso di errore).
- **Audit preventivo template**: `quotes.html:714` (sidebar categorie listino in editor quotazione) escapava solo `'` ma non `"`/`&`/`<`. Sostituito con `data-cat` attribute + escape HTML completo + lettura via `this.dataset.cat`. Nessun bug attivo — fix preventivo per categorie listino con caratteri speciali.

### File toccati

- `app/main.py` — versione `3.2.0` → `3.2.1`
- `app/services/ai_assistant.py` — handler `propose_quote`, `propose_project`, `_next_quote_number`, prompt aggiornato
- `app/routers/clients.py` — tenant filter + per-user provider + cookie resolution + `web_search_used` in response enrich
- `app/services/ai_provider.py` — `supports_web_search()` su base class + `ClaudeProvider.extract_json_with_web_search()` con tool `web_search_20250305`
- `app/services/client_enrichment.py` — `provider` parameter, fallback no-web (`ENRICHMENT_SYSTEM_PROMPT_NOWEB`), cascata `_try_native_web_search` → `_try_tavily` → `_try_noweb`
- `app/templates/pages/clients.html` — bottone "Crea + popola con AI", helper `_newClientFormData()`, fix delete + aiEnrich

---

## v3.2 — AI per-utente + copilot context-aware (26 aprile 2026)

### Configurazione AI per-utente

Ogni utente configura i propri provider AI in `Impostazioni → tab 🤖 AI`. Le api_key sono salvate cifrate nel DB (Fernet, chiave dedicata `AI_KEY_ENCRYPTION_KEY` separata da `SECRET_KEY` per disaccoppiare la rotazione di JWT e la cifratura segreti).

Provider supportati:
- **Anthropic Claude** (Opus 4.7 / Sonnet 4.6 / Haiku 4.5)
- **OpenAI** (GPT-4o / o1 / o3-mini)
- **Google Gemini** (2.0 Flash / Flash Thinking / 1.5 Pro)
- **Perplexity** (Sonar Pro / Sonar / Sonar Reasoning)
- **Ollama** (locale, base URL configurabile)

Per ogni provider: salva, test connessione (ping minimale che valida auth), attiva. Solo il provider attivo viene usato dal copilot. Niente lock-in.

### Copilot context-aware

Pulsante 💬 fisso in basso a destra, presente su tutte le pagine. Drawer laterale con:
- storia conversazioni cliccabile
- context auto-detection da URL (progetto, quote, job)
- pattern "AI propone, utente dispone": ogni azione concreta restituita dall'AI come blocco strutturato `action`, mostrata come card di conferma con bottoni Applica/Rifiuta. Nessuna esecuzione senza click esplicito.

Capability primo push (delimitate per controllo):
- `propose_price_item` — proporre nuova voce di listino
- `propose_client` — proporre creazione cliente
- `propose_quote_line` — proporre riga su quote attiva
- `propose_project_metadata` — aggiornare metadata progetto (durata, fps, formato)
- `web_search` — ricerca read-only via Tavily

Tutte le azioni vengono salvate in tabella `ai_actions` con stato `proposed → applied | rejected | failed` per audit completo.

### Migrazione

Script non distruttivo: `scripts/migrate_ai_per_user.py` (opzione `[8]` su `strumenti.sh/.bat`). Crea `user_ai_settings`, `ai_actions`, aggiunge `users.active_ai_provider` e genera `AI_KEY_ENCRYPTION_KEY` in `.env` se mancante.

### Dipendenze

Aggiunte: `google-generativeai>=0.8.3`, `cryptography>=43.0.0`. Perplexity chiamata via `httpx` raw (no SDK ufficiale stabile).

---

## v3.1 — Quotazioni UX + listino generico (25 aprile 2026)

### Quotazioni — sconti multilivello e UX rifatta

- Nuovo modello dati: `QuoteLine.line_discount_pct`, `Quote.subtotal_gross`, `Quote.category_discounts` (JSON)
- Cascata sconti: voce → categoria dinamica (per `PriceItem.category`) → pacchetto → IVA. Convenzione UI: tutti gli sconti sono percentuali positive (es. 15% = riduzione 15%); il `package_discount` resta negativo internamente per retrocompat.
- Editor quotazione rifatto: voci raggruppate dinamicamente per categoria, edit inline su qualsiasi campo con auto-save al blur, drag-and-drop righe via SortableJS (CDN), riga "Sconto categoria %" sotto ogni gruppo, sconto pacchetto editabile inline accanto al totale.
- Riepilogo economico mostra: totale lordo (no sconti) per visibilità cliente, sconti voci+categoria, subtotale, sconto pacchetto, totale netto base IVA, IVA, totale finale.
- Modal "Aggiungi voce" rifatto con ricerca live nel listino (nome/descrizione/keywords/categoria).
- PDF aggiornato: raggruppamento per categoria, colonna sconto riga, sconti categoria mostrati per gruppo, breakdown completo dei totali.
- Endpoint nuovi: `PUT /quotes/api/{id}/category-discount`, `PUT /quotes/api/{id}/lines-reorder`.
- Migrazione non distruttiva: `scripts/migrate_quote_discounts.py` (opzione `[7]` su `strumenti.sh/.bat`).

### Listino — generico mercato italiano + export/import

- **Reset completo** del listino. Sostituite le 76 voci di esempio TPR Berlin con 75 voci generiche da workflow standard di post-produzione + pattern ricorrenti dei capitolati reali (A24, Vision, Fremantle, Sky, NBCU TechOps).
- 12 nuove categorie: DAILIES, PICTURE / DI, MASTERING DCP / DCDM, DELIVERABLES VIDEO, ARCHIVE / TRANSFER, VFX, SOUND EDIT, MIX, DELIVERABLES SOUND, LOCALIZATION, QC / METADATA, PROJECT MANAGEMENT.
- Prezzi orientativi mercato italiano 2026 (modificabili). Keywords AI inline per matching capitolato → voce.
- **Schema collassato**: solo `price_list` (rinominato "Prezzo €" in UI). I campi `price_average`/`price_low` restano in DB per retrocompat ma non sono più editati. La cascata sconti sostituisce i tre livelli storici.
- Toggle UI **Giorno ↔ Ora** sul listino (1 turno = 8h): converte la visualizzazione senza modificare il prezzo memorizzato.
- Conversione automatica day↔hour anche in editor quotazione: cambiando l'unità di una voce, il prezzo si ricalcola.
- Export/import listino: `GET /pricelist/api/export` (download JSON portabile), `POST /pricelist/api/import` con modalità `merge` (aggiorna voci esistenti, aggiunge nuove) o `replace` (cancella tutto, ricarica). UI con due bottoni in topbar `/pricelist`. Backup pre-reset salvato in `docs/listino_attuale.json`.
- Capitolati di riferimento estratti in testo in `docs/capitolati_text/` (9 documenti su 17 leggibili: PDF, DOCX). Veterans .doc e BETA Film PDF non estraibili — da convertire manualmente per Fase 2.

## v3.0.1 — Transizione a Claude Code (25 aprile 2026)

### Diagnosi all'apertura del progetto

Trasferimento da chat web a Claude Code. Audit del codice ha rivelato gap rispetto alla documentazione:

- Servizi AI (`ai_provider.py`, `ai_assistant.py`, `client_enrichment.py`, `web_search.py`, `deliverables_parser.py`, `routers/ai.py`) presenti come scaffolding ma mai integrati end-to-end. Default `AI_PROVIDER=disabled`.
- Listino generico estratto da capitolati: NON fatto. `LISTINO_ESEMPIO` ancora basato su esempio TPR.
- 17 capitolati reali disponibili in `docs/capitolati_esempio/` (RAI, Sky, Netflix, Amazon, A24, MUBI, NBCU, Vision, BETA, FREMANTLE, IRDA, Veterans, ContentArmor) — non ancora analizzati.

### Fix

- **`/resources/` 500 error** — `resources.html` referenziava `TYPE_LABEL` (costante JS) dentro Jinja `{{ ... }}`. Iniettato dict equivalente server-side da `routers/resources.py`.
- **Modello AI default** — `config.py` e `.env.example` aggiornati da `claude-sonnet-4-5` a `claude-sonnet-4-6`. Aggiunto commento con i modelli disponibili (Opus 4.7, Sonnet 4.6, Haiku 4.5).

### Roadmap aggiornata

Prima di completare la Fase 2, refactor UX urgente su Quotazioni e Listino (gap rispetto a uso reale Matteo):
- Quotazioni: raggruppamento per categoria, edit voci inline, drag-and-drop, sconto inline
- Listino: nuovo seed da capitolati reali, ricerca migliorata, menu selezione voci dentro quotazione più efficace

Poi Fase 2 vera (UI Impostazioni AI, upload capitolato → DeliveryTemplate, test E2E).

---

## v3.0.0 — Fase 1-bis: fondamenta multi-tenant e reparti (Aprile 2026)

### Visione strategica

Pivot importante: MediaFlow non è più pensato come gestionale per una singola casa di post-produzione, ma come **piattaforma flessibile e adattabile**. Il listino di TPR Berlin diventa esempio iniziale, non standard. Architettura multi-tenant pronta dal primo giorno (per ora in modalità "soft", tutto a tenant_id=1).

### Cosa è cambiato — Modelli dati

- **Tenant** (nuovo modello) — Rappresenta l'azienda che usa il sistema. Per ora ne esiste uno solo "default", ma l'architettura è già predisposta per il multi-azienda futuro.
- **Department** (nuovo modello) — Reparti trasversali (DI/Video, VFX, Audio, Commercial). Ogni risorsa e ogni voce listino appartiene a un reparto. Il reparto è l'unità di responsabilità finanziaria.
- **DeliveryTemplate** (nuovo modello) — Template strutturati per capitolati di consegna (A24, Netflix, Sky, RAI…). Contiene 8 blocchi JSON: video_specs, audio_specs, text_specs, head_format, textless_format, naming_convention, archive_specs, metadata_requirements. Verranno popolati nella Fase 2 tramite import AI dai capitolati reali.
- **PriceItem** — Aggiunti `department_id` e `keywords`. Le keywords sono usate per il matching AI testo-libero → voce listino.
- **Resource** — Aggiunti `department_id`, `role`, `email`, `phone`, `internal_phone`. Esteso ResourceType con `person_internal`, `person_freelance`, `software` (mantenuto `person` per retrocompatibilità).
- **Client / Project / PriceCategory** — Aggiunto `tenant_id` (default=1) per coerenza multi-tenant.

### Cosa è cambiato — Interfaccia

- **Nuova pagina /departments** con CRUD completo dei reparti (creazione, modifica, eliminazione protetta).
- **Pagina Risorse** rivista: filtro per reparto, tab esteso (interno, freelance, studio, attrezzatura, software, veicolo), modal con tutti i nuovi campi (ruolo, email, telefono, interno).
- **Pagina Listino** rivista: filtro per reparto, ricerca anche su keywords, modal di voce con campo keywords editabile.
- Listino di esempio ripulito: descrizioni neutre, nessun riferimento a marchi specifici (FilmMaster, Nucoda, Barco, Euphonix sono stati sostituiti da descrizioni generiche).

### Migrazione

Per database esistenti è stato creato `scripts/migrate_phase1bis.py`. È **non distruttivo**: aggiunge le colonne mancanti via ALTER TABLE, crea il tenant default, i 4 reparti predefiniti, mappa le voci sul reparto corrispondente e popola le keywords delle 76 voci di esempio.

```
python scripts/migrate_phase1bis.py
```

Per database nuovi è sufficiente `python scripts/seed_demo.py` come al solito.

### Roadmap successiva

- **Fase 2** — AI Provider configurabile (Claude / GPT / Ollama) + import capitolati che popolano i DeliveryTemplate
- **Fase 3** — Arricchimento dati clienti/progetti via web (Tavily, Film Italia, IMDB Pro, LinkedIn)
- **Fase 4** — AI co-pilot contestuale + notifiche proattive deterministiche
- **Fase 5** — Import capitolato con matching automatico sulle voci di listino
- **Fase 6** — Reporting AI-assisted con narrative reports
- **Fase 7** — Multi-tenant completo (opzionale, per commercializzazione)

---



### Cosa cambia

Le dipendenze sono state aggiornate per funzionare su Python 3.14 (oltre che 3.11, 3.12, 3.13). Le versioni precedenti di alcune librerie — tipicamente Pillow 10.x, python-jose, passlib — non avevano ancora wheel precompilate per Python 3.14 e la loro installazione falliva con errori di build.

### Dettagli tecnici

- Sostituito `python-jose` con `PyJWT` (più leggero, wheel universali)
- Sostituito `passlib[bcrypt]` con `bcrypt` diretto (passlib non è aggiornato per 3.14)
- Aggiornati tutti i pacchetti alle versioni più recenti con wheel per Python 3.14
- Il modulo `app/services/auth.py` è stato riscritto per usare le nuove librerie — API pubblica invariata

### Per utenti esistenti

Se hai già un venv creato con la versione precedente, cancellalo e ricrealo:

- **Windows:** chiudi l'app, elimina la cartella `.venv`, poi doppio clic su `avvia.bat`
- **Mac/Linux:** `rm -rf .venv` e poi `./avvia.sh`

Il database e i dati esistenti non vengono toccati.

### Aggiunto script avvio Mac/Linux

Nuovo file `avvia.sh` per utenti macOS e Linux (in aggiunta a `avvia.bat` per Windows). Usa `./avvia.sh` dal terminale dopo averlo reso eseguibile con `chmod +x avvia.sh`.

---

## v2.1 — Fase 1: Struttura Progetti (Aprile 2026)

### Cosa cambia nella struttura dati

Prima la gerarchia era lineare: `Cliente → Quotazione → Job`. Questo costringeva a duplicare i dati tecnici (durata, formati, crew) su ogni quotazione anche quando riguardavano lo stesso film o la stessa serie.

Adesso la gerarchia riflette il mondo reale della produzione audiovisiva:

    Cliente → Progetto → Quotazione → Job
                      └→ Altre quotazioni (v2, v3...)
                      └→ Altri job

Un cliente (es. Cattleya) ha più progetti (Romanzo Criminale, Suburra, ACAB), ogni progetto può avere più quotazioni iterative (v1 rifiutata, v2 rivista, v3 approvata), e quando una quotazione viene approvata diventa un job operativo collegato allo stesso progetto.

### Nuove pagine

- **Clienti** (`/clients`) — anagrafica completa con contatti e P.IVA
- **Progetti** (`/projects`) — lista filtrata per cliente, tipo (lungometraggio, serie, spot, doc…), stato, con dashboard per progetto
- **Dettaglio progetto** (`/projects/{id}`) — hub centrale con tabs: tutte le quotazioni del progetto, tutti i job derivati, specifiche tecniche e crew

### Cambiamenti nelle pagine esistenti

- **Quotazioni** — la creazione ora richiede la selezione di un progetto. I campi durata, FPS e formato consegna vengono auto-compilati dai dati del progetto. Se il progetto non esiste, va creato prima dalla pagina Progetti.
- **Sidebar** — nuova sezione "Anagrafica" con Clienti e Progetti sopra la sezione Operativo.

### Come aggiornare un database esistente

Se hai già dati nel database da una versione precedente, usa lo script di migrazione **non-distruttivo**. Su Windows:

1. Apri `strumenti.bat`
2. Scegli opzione **[5] Migra database esistente**
3. Conferma con `s`

Lo script:
- Aggiunge la tabella `projects` e le colonne `project_id` a `quotes` e `jobs`
- Per ogni quotazione/job senza progetto, crea automaticamente un progetto "legacy" basato sui dati esistenti
- Collega tutto correttamente preservando i dati originali

Oppure da riga di comando:
```
python scripts\migrate_to_projects.py
```

### Resettare con i nuovi dati demo

Se preferisci ripartire da zero con i nuovi dati demo (che include 3 progetti: Mare Nostrum, Spot Sky, Città d'Arte):

1. `strumenti.bat` → opzione **[2] Resetta database**

### Cosa arriva nella Fase 2

Provider AI configurabile (Claude / GPT / Ollama locale) con pagina Impostazioni dedicata, test di connessione e selezione modello.

### Cosa arriva nella Fase 3

Arricchimento automatico delle schede cliente via AI + ricerca web (Tavily). Digiti "Cattleya srl" → l'AI compila P.IVA, sede, filmografia, contatti di produzione.

### Cosa arriva nella Fase 4

Assistente AI contestuale (chat laterale sempre accessibile) che conosce il listino e il progetto corrente.

### Cosa arriva nella Fase 5

Importazione capitolato di consegne (PDF, Word, Excel, testo libero) con matching AI contro il listino e conferma interattiva riga per riga prima di generare la bozza di quotazione.
