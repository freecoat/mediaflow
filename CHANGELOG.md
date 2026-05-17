# MediaFlow — Changelog

## v3.5.0-alpha.162 — Timeline planning: fix conflitto zoom+scroll su wheel (17 mag 2026 notte)

Bug: in /planning timeline risorse, rotella mouse triggerava ZOOM (asse tempo) E SCROLL (orizzontale) contemporaneamente — comportamento illeggibile.

ROOT CAUSE: vis-timeline config aveva `zoomable: true` + `horizontalScroll: true` senza `zoomKey`. Wheel default → entrambi reagivano.

Fix: `zoomKey: 'ctrlKey'` aggiunto. Pattern standard.

**Comportamento ora**:
- Wheel solo → scroll orizzontale naturale (pan timeline)
- Ctrl+Wheel → zoom asse tempo
- Shift+Wheel → scroll verticale gruppi (preesistente)

---

## v3.5.0-alpha.161 — Colonna Fatturato include acconto pagato (billed_total unificato) (17 mag 2026 notte)

Risposta domanda Matteo: "perché non vedo l'acconto nella cifra fatturata?".

Pre-α.161: colonna "Fatturato" per JCL = `billed_locked` (Σ JCLBilledSlice, solo slice batch). Acconto pagato + allocato NON contribuiva. Architettura distingueva slice (work effettivo) da acconto (cassa anticipata) — corretta semanticamente ma UX confusa.

Fix:

**Backend** `job_cost_report` JCL response:
- `billed_total = billed_locked + advance_paid_coverage` (cassa effettivamente incassata su JCL).
- `billed_from_slice` = quota da batch (slice immutable).
- `billed_from_advance` = quota da acconto pagato allocato.

**UI cost report**:
- `billedLocked` alias retro-compat ora legge `billed_total`.
- Colonna "Fatturato" mostra billed_total con icona 💰 se billed_from_advance > 0.
- Tooltip: "Slice batch: €X · Acconto pagato: €Y" (se misto).

**Esempio**:
- JCL Re-recording mix: slice = 19'246, acconto allocato pagato = 0 → billed_total = 19'246 ✓
- JCL X: slice = 0, acconto allocato 100% pagato = 5'000 → billed_total = 5'000 ✓ (era 0 pre-α.161)
- JCL Y: slice = 3'000, acconto pagato = 2'000 → billed_total = 5'000 (tooltip mostra split)

**Backlog α.162**:
- Sum billed_total a livello job summary (KPI card "Fatturato chiuso")
- Eventuali aggiustamenti `accrued_post_period`/over_under con effective_billed
- F29 round 6 modal/form granulare

---

## v3.5.0-alpha.160.1 — HOTFIX: variable shadowing `paid` in cost_report.py (17 mag 2026 notte)

Bug introdotto α.160: nel for loop `paid_rows` ho usato `paid` come loop var, shadowing variabile esterna omonima (`paid = Σ Invoice.total status=paid`).

Dopo il for, se l'ultima riga aveva `amount_paid=None`, `paid` restava None → `round(paid, 2)` line 776 → `TypeError: type NoneType doesn't define __round__ method`.

Fix: rinomino loop var con suffix `_` (`jcl_id_`, `alloc_amt_`, `ap_amt_`, `paid_amt_`).

Smoke job 45 P-2024-0035-J-2026-002 (precedentemente broken): `paid=0` ✓.

**Lezione**: var shadowing in scope esterno è bug subdolo. Python non avvisa. Loop var con underscore suffix per evitare.

---

## v3.5.0-alpha.160 — JCL advance_paid_coverage: acconto pagato visibile in lavorazioni (17 mag 2026 notte)

Risposta domanda Matteo: "non vedo il pagato nelle voci lavorazione come fatturato".

Pre-α.160: badge `💰 Coperto da acconto` su JCL mostrava solo `advance_coverage` (Σ allocation.amount), indipendentemente da pagamento. Se acconto NON ancora pagato, mostrava comunque coverage piena → fuorviante.

Fix:

**Backend** `job_cost_report`:
- Pre-fetch `advance_paid_coverage_by_jcl`: per ogni JCL, Σ `allocation.amount × (invoice.amount_paid / AP.amount)`.
- Ratio limitato a [0, 1] (cap a 100%).
- JCL response include `advance_paid_coverage` campo nuovo.
- Formula: quota effettiva incassata dal cliente sulla porzione di acconto allocata a questa JCL.

**UI cost report**:
- Badge per JCL ora mostra: `💰 €X · ✓ €Y` dove X = allocato totale, Y = effettivamente pagato.
- Tooltip: "Coperto da acconto: €X allocato (pagato €Y) · drift/in linea".
- Se acconto NON pagato: badge mostra solo allocato + tooltip "(acconto non ancora pagato)".
- Colore badge: verde (paid coverage > 0) o indigo (solo allocato).

**Semantica chiarita**:
- `advance_coverage` (α.146) = Σ allocation per JCL (ledger, indipendente da pagamento)
- `advance_paid_coverage` (α.160) = quota effettivamente incassata
- Se acconto €10k allocato 100% a JCL X + invoice acconto pagata 60% (€6k) → JCL X ha paid_coverage = €6k.

**Backlog α.161**:
- Eventualmente: sommare advance_paid_coverage in "Fatturato totale" del job summary (oggi solo billed_locked)
- Warning UI se acconto pagato ma JCL non lavorata (work=0 ma paid>0 = anticipato senza work)

---

## v3.5.0-alpha.159 — Acconti UX: totale% summary + Invoice project + CR Scomputato vs Pagato (17 mag 2026 notte)

3 fix post-test Matteo.

**#1 Modal "Gestisci acconto" — Summary live totale + percentuale**:
- Sotto picker JCL: riepilogo dinamico "N voci · quotato selezionato €X = Y% del totale progetto €Z".
- Aggiorna onchange checkbox + oninput pct.
- Warning amber se Σ pct allocazioni > 100% (overflow).
- Replica pattern modal termini quote (α.139 summary).

**#2 Lista fatture — Acconto progetto-level non mostrava progetto**:
- ROOT CAUSE: `list_invoices` cercava `inv.job.project`, ma acconti α.143+ hanno `project_id` diretto e `job_id=None`. → cella "Progetto" mostrava "—".
- Fix backend:
  - Pre-fetch direct project map per Invoice senza job_id (`{i.project_id}` set).
  - Response builder: fallback `inv.project_id` se `inv.job.project` missing.
  - Filter `project_id=X` query param: usa `OR` (job.project_id OR Invoice.project_id) per includere acconti project-level.

**#3 CR card "Acconti del progetto" — distinguere Scomputato vs Pagato**:
- ROOT CAUSE: una sola colonna "Già scomputato" confondeva `consumption.amount_consumed` (uso contabile in fatture SAL successive) con `invoice.amount_paid` (cassa incassata).
- Fix backend `list_project_advances`: aggiunge campo `paid` ai totals = Σ Invoice.amount_paid degli AP non-cancelled.
- Fix UI: 4 stat-card (era 3):
  - "Totale acconti" (Σ amount emesso, indigo)
  - "Pagato (cassa)" (Σ invoice.amount_paid, verde) — tooltip: "cassa effettivamente incassata"
  - "Scomputato in fatture SAL" (Σ consumption.amount_consumed, viola) — tooltip: "quota ledger consumata nelle fatture batch successive, NON cassa"
  - "Residuo aperto" (Σ balance_remaining, ambra)
- Grid template forzato a 4 colonne.

**Semantica chiarita**:
- **Pagato** = cash flow incassato (Invoice.amount_paid)
- **Scomputato** = uso contabile del ledger acconto in fatture successive (consumption)
- Sono indipendenti: un acconto può essere pagato ma non scomputato (cliente ha pagato ma SAL non ancora emessi), o scomputato non pagato (caso anomalo: si è scomputato in SAL prima che cliente pagasse l'acconto).

**Backlog α.160**:
- UI modal Emit acconto: preview allocazioni read-only
- CR: includere fatture project-level (no job_id) nei totali invoiced_net del job (oggi solo Invoice.job_id == j.id)
- Warning UI over-billing (billed >> accrued)

---

## v3.5.0-alpha.158 — Acconti: gestione allocazioni completa (add/remove/modify) (17 mag 2026 notte)

Fix gestione allocazioni acconti in /finance "Bozze acconti".

**Bug pre-α.158**:
- Modal "Gestisci acconto" mostrava SOLO le allocations già esistenti su AP.
- Impossibile aggiungere allocazioni a JCL non già allocate.
- Impossibile rimuovere allocazioni esistenti.
- Per AP creati manualmente α.136 (senza schedule origine) il picker era vuoto.

**Fix**:

Backend nuovi:
- `GET /finance/api/advances/{id}/jcls-available` — ritorna TUTTE le JCL del progetto associato all'AP, con flag `allocated` + `alloc_pct` + `alloc_amount` correnti.
- Response per JCL: jcl_id, job_id, job_code, description, unit, total_quoted, total_accrued, billing_status, allocated, alloc_id, alloc_pct, alloc_amount.

Backend `confirm_advance_payment` esteso:
- Param nuovo `allocations_set` (CSV "jcl_id:pct,...") — sostituzione TOTALE: drop tutte le allocations esistenti + crea nuove dal CSV.
- Validazione: pct ∈ (0,1], JCL deve appartenere al progetto dell'AP.
- Distinto da `allocations_update` (legacy α.145, modifica pct esistenti per alloc_id).

UI modal "Gestisci acconto":
- `openAdvConfirmModal` ora async: fetch `/jcls-available` + popola picker completo.
- Lista JCL raggruppate per Job (header "JOB_CODE — N voci").
- Per ogni JCL: checkbox (allocato sì/no) + input % (disabled se unchecked).
- Description JCL + total_quoted visualizzati.
- Submit usa `_collectAllocSet()` → CSV jcl_id:pct → backend `allocations_set` (sostituzione totale).

**Project_id propagation verificata**:
- AP.project_id impostato sia in create_advance_payment (α.136) sia in materialize_schedules (α.144).
- Invoice.project_id impostato in emit_invoice_from_advance (α.145, line 878: `project_id=ap.project_id`).
- Stato OK, no fix necessario.

**Smoke**: endpoint `/jcls-available` registrato (468 routes totali).

**Backlog α.159**:
- UI modal emit con preview allocazioni read-only + bottone "modifica" che apre confirm
- Cost Report: includere Invoice project-level (no job_id) nei totali invoiced_net (oggi solo Invoice.job_id == j.id, le acconti project-level non si vedono per job)
- Warning UI quando billed >> accrued (over-billing storico, simile Vento Aperto Ep. 3)

---

## v3.5.0-alpha.157 — Cost report OU usa max(accrued, billed) — fix logico (17 mag 2026 sera tarda)

Fix logico richiesto Matteo dopo α.156. OU = `effective_accrued - quoted` dove `effective_accrued = max(JCL.total_accrued, billed_locked)`.

**Bug pre-α.157**: OU usava solo `total_accrued` (work effettivo da booking done), ignorando `billed_locked` > accrued (over-billing storico). Interpretazione corretta: quando fatturato > work, il fatturato conta come "maturato finanziario" — cassa già passata, conta per il bilancio quote vs fatturato.

**Esempio Vento Aperto Ep. 3 / Re-recording mix Dolby Atmos**:
- quoted = €57'120
- total_accrued = €4'200 (work effettivo)
- billed_locked = €19'246 (slice immutable)
- Pre-α.157: OU_now = 4'200 - 57'120 = **-52'920** (fuorviante)
- Post-α.157: OU_now = max(4'200, 19'246) - 57'120 = **-37'874** ✓ (= interpretazione Matteo)

**Fix in 3 punti** (`cost_report.py`):
1. `list_cost_reports` (job level): `effective_accrued = max(total_accrued, billed_locked)` + `effective_expected = max(total_expected, billed_locked)`.
2. `job_cost_report` summary (job level): `max(total_accrued, sum_billed_locked) - total_quoted`.
3. JCL response per riga: `max(l.total_accrued, billed_map[l.id]) - l.total_quoted`.

**Smoke**: Vento Aperto Ep. 3 / Re-recording mix → OU_now = -37'874 ✓ match interpretazione Matteo.

**Semantica chiarita**:
- `total_accrued` = work effettivo (ore done × prezzo) — quanto HAI lavorato
- `billed_locked` = slice fatturate — quanto HAI EMESSO fattura
- `effective_accrued = max(...)` = quanto vale "contabilmente come maturato" (work O fatturato, il maggiore)
- OU = effective_accrued - quoted = sforamento finanziario reale

**Backlog α.158**:
- Colonna esplicita "Maturato JCL" + "Effective" in CR dettaglio
- Warning UI quando billed_locked >> total_accrued (over-billing)
- F29 round 6 granulare modal/form

---

## v3.5.0-alpha.156 — Dashboard layout + i18n sidebar admin + quotes nasconde superseded + CR tooltip aritmetica (17 mag 2026 sera tarda)

4 fix dopo test Matteo.

**Dashboard riordino**:
- Row 3: "Job recenti | Prossime scadenze" (vista operativa).
- Row 5: "Margine per reparto | P&L" (vista finanza accorpata).
- Era: row 3 Job+P&L, row 5 Scadenze+Margine. Ora insieme i 2 finanziari + i 2 operativi.

**i18n sidebar Amministrazione**:
- 4 voci ancora in italiano hard-coded: "Amministrazione" sezione + Utenti / Ruoli e permessi / Cestino / Audit TPN / Logout footer.
- Fix: `data-i18n` aggiunto (chiavi già esistenti nel dictionary α.133+).

**Lista quotazioni nasconde superseded**:
- `GET /quotes/api` default filtra `Quote.superseded_by_id IS NULL` (solo ultime versioni).
- Nuovo param `?include_superseded=true` per drill versioning storico.

**Cost Report tooltip aritmetica**:
- Caso reale Matteo: JCL "Re-recording mix Dolby Atmos" mostrava billed=€19'246, cost=€734, margin=€3'465 → apparente impossibilità.
- ROOT CAUSE: `JCL.total_accrued` (DB) = €4'200 (ore done × prezzo, work effettivo). billed_locked = €19'246 (Σ slice fatturate in passato, immutable). Quando billed > total_accrued → over-billing storico (slice fatturate per più del lavoro effettivo).
- `real_margin = total_accrued (4'200) - cost_accrued (734) = 3'465` ✓
- Fix UI: tooltip estesi su Fatturato/Maturato post/Over-Under/Margine reale che spiegano formula esatta + caso over-billing storico.

**Backlog α.157**:
- Colonna esplicita "Maturato JCL" (= total_accrued) nel cost report dettaglio per evitare confusione billed vs maturato.
- F29 round 6: data-i18n granulare su modal/form per ogni template.

---

## v3.5.0-alpha.155 — Automazione portali consegne: foundation + plugin architecture (17 mag 2026 sera tarda)

Foundation per automazione upload ai portali broadcaster (Netflix/Amazon/A24/Sky/...). UI + endpoint + plugin specifici in versioni successive.

**Modelli nuovi**:

`DeliveryPortal` — configurazione portale per tenant:
- `code` (unique per tenant), `name`, `broadcaster`, `api_type` (api/web/manual), `base_url`, `auth_config_enc` (Fernet cifrato), `plugin_key`, `is_active`.

`DeliveryUpload` — tracking upload singolo:
- `portal_id`, `project_id`, `job_deliverable_id`, `asset_id`, `physical_asset_id`, `file_path`, `upload_url`, `status` (pending/uploading/done/failed/cancelled), `progress_pct`, `error_message`, `submitted_by_user_id`, `completed_at`.

`DeliveryPortalApiType` + `DeliveryUploadStatus` enums.

**Servizio `app/services/delivery_portals.py`** plugin architecture:

- `DeliveryPortalPlugin` base class con metodi `validate_auth()`, `upload_file(portal, file_path, metadata)`.
- `ManualPortalPlugin` — no-op, MediaFlow traccia solo lo stato (broadcaster con UI manuale).
- `GenericHttpPortalPlugin` — POST multipart + bearer token (auth_config: `{endpoint, token}`).
- `_PROVIDERS` dict registrabile + `get_plugin(key)` + `list_plugin_keys()`.
- `encrypt_auth_config` / `decrypt_auth_config` via Fernet AI_KEY_ENCRYPTION_KEY (riuso α.137).
- `execute_upload(db, upload)` — flow stateful: pending → uploading → done|failed con commit progressivo. Idempotente.

**Plugin futuri TODO**:
- `netflix_aspera` (Aspera fasp)
- `amazon_s3` (S3 + signed URLs)
- `sky_signiant` (Media Shuttle)
- `a24_box` (Box.com API)

**Smoke**: 2 tabelle create + 2 plugin built-in registrati ✓.

**Backlog α.156+**:
- Router CRUD portali + upload trigger
- UI tab "Portali consegne" in /settings (config + auth)
- UI upload da page deliverables (selezione portale + file)
- Plugin broadcaster-specific (Netflix/Amazon prima priorità)
- Background queue (Celery/RQ) per upload async di grandi file

---

## v3.5.0-alpha.154 — Parse batch capitolati pendenti (17 mag 2026 sera)

Endpoint nuovo per parse batch del corpus capitolati esempio (17 file in `docs/capitolati_esempio/`).

**`POST /delivery-templates/api/parse-batch-pending`**:
- Param `auto_save` (bool, default False) — dry-run vs persistenza.
- Itera `docs/capitolati_esempio/`, skippa file già parsati (matching su `source_document_name`).
- Per ogni file pending: extract_text + parse_delivery_template (AI provider).
- Se auto_save=True: crea DeliveryTemplate inline (code skip se già esistente).
- Idempotente: re-run skippa già processati.

**Response**:
- `processed[]`: file + template_id (se saved) + code/name + confidence
- `skipped[]`: file + reason ("già parsato" o "code esistente")
- `errors[]`: file + error (extract/parse/save fail)
- `summary` stringa "{n} processati, {s} skip, {e} errori"

**Uso**:
- Dry-run: `POST /delivery-templates/api/parse-batch-pending` (default)
- Salva: `POST /delivery-templates/api/parse-batch-pending?auto_save=true`

Nota: richiede AI provider attivo (config /settings#ai). Senza AI configurata, gli errori riportano "parser AI ritornato vuoto".

**Backlog α.155+**:
- UI bottone "🤖 Parse tutti pendenti" in /delivery-templates con progress + summary
- Automazione portali consegne
- UI tab Integrazioni OAuth /settings

---

## v3.5.0-alpha.153 — Cross-currency cost-report aggregati (17 mag 2026 sera)

Foundation per aggregati cross-currency in cost-report. Pre-α.153, totali progetto con quote in USD non erano sommabili a base EUR (mostrava valori "raw" senza conversione).

**Cost report list endpoint esteso**:
- Pre-fetch `Tenant.default_currency` (base).
- Per ogni job:
  - `quote_currency` (default 'EUR' se no quote)
  - `quote_fx_rate_to_base` (snapshot da Quote, 1.0 se mancante)
  - `base_currency` (= tenant base)
  - `total_quoted_base` = total_quoted × fx_rate
  - `total_accrued_base` = total_accrued × fx_rate

UI può aggregare `*_base` sicuro per dashboard/totali cross-quote.

**Smoke**: 44 jobs listati. Demo DB tutti EUR (fx=1.0, no conversion).

**Backlog α.154+**:
- UI dashboard/cost-report aggregati: usare `*_base` per Σ totali corretti
- Cashflow aggregati cross-currency (invoice ha currency? Necessita propagazione da Quote)
- Test parse 14 capitolati restanti
- Automazione portali consegne
- UI tab "Integrazioni" /settings OAuth

---

## v3.5.0-alpha.152 — OAuth scaffold: Google (Gmail+Drive) + Microsoft (Outlook+OneDrive) (17 mag 2026 sera)

Foundation OAuth 2 Authorization Code flow per integrazione email + cloud storage. UI Settings + send/upload features in versioni successive.

**Modello `UserOAuthToken`**:
- `user_id`, `provider` (google/microsoft), `access_token`, `refresh_token_enc` (Fernet cifrato), `expires_at`, `scopes`, `account_email`.
- UniqueConstraint coppia (user_id, provider) — 1 token per coppia.

**Servizio `app/services/oauth_providers.py`**:
- Dict `PROVIDERS` con auth_url, token_url, userinfo_url, scopes default, env var names per ogni provider.
- `authorization_url(provider, state)` — costruisce URL OAuth flow.
- `exchange_code_for_token(provider, code)` — POST a token endpoint del provider.
- `fetch_userinfo(provider, access_token)` — GET userinfo per `account_email`.
- `save_token` / `get_token` / `revoke_token` — DB helpers.
- Refresh token cifrato via Fernet `AI_KEY_ENCRYPTION_KEY` (riuso α.137).
- urllib stdlib (no deps esterne).

**Router `app/routers/oauth.py`**:
- `GET /auth/oauth/status` — JSON stato providers + connessioni utente corrente
- `GET /auth/oauth/{provider}/start` — redirect a authorization URL (genera state CSRF)
- `GET /auth/oauth/{provider}/callback` — scambio code→token + save + HTML success page con redirect a /settings
- `POST /auth/oauth/{provider}/disconnect` — revoca token locale

**Scope di default**:
- Google: `openid email profile gmail.send drive.file`
- Microsoft: `openid email profile offline_access User.Read Mail.Send Files.ReadWrite`

**Env vars necessarie** (`.env`):
```
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
MICROSOFT_OAUTH_CLIENT_ID=...
MICROSOFT_OAUTH_CLIENT_SECRET=...
OAUTH_REDIRECT_BASE_URL=http://localhost:8000  # production: il tuo dominio
```

Setup Google: console.cloud.google.com → APIs & Services → OAuth consent screen + Credentials → OAuth 2.0 Client ID (Web app) → redirect URI: `{base}/auth/oauth/google/callback`.

Setup Microsoft: portal.azure.com → Entra ID → App registrations → New + Web platform → redirect URI: `{base}/auth/oauth/microsoft/callback`.

**Backlog α.153+**:
- UI tab "Integrazioni" in /settings con stato connesso + bottoni Collega/Scollega
- Servizi feature: `send_email(google)`, `send_email(microsoft)`, `list_drive_files`, `upload_to_drive`, etc.
- Token refresh auto via refresh_token
- AI capability `propose_send_email_oauth` (alternativa a SMTP)

---

## v3.5.0-alpha.151 — F29 i18n round 5: modal/form/JS dinamico — chiusura sweep (17 mag 2026 sera)

Sweep i18n round 5 finale: chiavi modal/form/toast/badge per coverage UI completa.

Dictionary MF_I18N estesa con ~50 chiavi nuove (cumulata ~300):

**Modal commons** (4): new, edit, confirm_delete, required_fields.

**Form labels riusabili** (22): name, email, phone, address, city, country, zip, province, vat_number, tax_code, notes, description, title, start_date, end_date, date, amount, quantity, unit, unit_price, discount, vat_rate, required_mark.

**Toast messages** (11): saved, deleted, created, updated, error, error_loading, error_save, required_fields, access_denied, not_found, unsaved_changes.

**Status badge dinamici** (5): not_billed, in_batch, billed, paid, lost.

**Generic UI** (12): yes, no, all, none, optional, required, total, subtotal, from, to, show, hide.

Template data-i18n esempio applicato clients modal (modal-header + 4 form-label) come pattern dimostrativo. Estensione granulare a tutti i modal/form prosegue on-demand.

`mfT(key)` helper esposto su `window.mfT`. Usabile da render JS per toast/badge dinamici:
```js
toast(mfT('toast.saved'), 'success');
badge.textContent = mfT('badge.paid');
```

Cache buster i18n.js?v=3.5.0-alpha.151.

**F29 sweep foundation CHIUSO**: 5 round (α.133 + α.147→α.151) — ~300 chiavi × 4 lingue = **~1200 traduzioni** totali. Coverage: sidebar + topbar + login + dashboard + 10 template principali (titoli, tab, bottoni, table headers, modal headers, form labels comuni, status badge, toast messages).

**Round successivi (on-demand)**:
- Granularità fine: ogni modal/form di ogni template (specifico per campo)
- Refactor JS render dinamici via mfT()
- Pluralizzazione (es. "1 cliente" / "5 clienti")
- Date/numeri locale-aware (Intl API)

---

## v3.5.0-alpha.150 — F29 i18n round 4 (chiude foundation): suppliers + resources + departments + settings (17 mag 2026 sera)

Sweep i18n round 4 (foundation completa). ~40 chiavi nuove.

Dictionary MF_I18N:
- Suppliers 9: title, new, search, col (vat/contact/invoices/outstanding), invoices.title, new_invoice
- Resources 12: title, new, search, 4 tab (all/people/studios/equipment), 4 col (type/role/dept/rate), show_inactive
- Departments 6: title, new, col (name/head/budget/resources)
- Settings 13: title, 7 tab (company/ai/numbering/security/data/brand/policies), fiscal_info, base_currency, vat_default, save

Template data-i18n:
- suppliers.html: bottoni topbar (+ Fornitore, + Fattura passiva)
- resources.html: bottone "+ Nuova risorsa"
- departments.html: bottone "+ Nuovo reparto"
- settings.html: label "Valuta base (ISO 4217)"

Cache buster i18n.js?v=3.5.0-alpha.150.

**Tot dictionary cumulata: ~250 chiavi** (4 lingue × 250 = 1000 traduzioni).

**Foundation F29 completa** sui template principali (10 pagine: dashboard, clients, projects, quotes, planning, finance, cost-report, suppliers, resources, departments, settings).

**Backlog F29 successivi**:
- JS dinamico mfT() per toast/render dinamici (round finale, refactor on-demand)
- Estendere data-i18n alle modal e ai form (granularità più fine)

---

## v3.5.0-alpha.149 — F29 i18n round 3: planning + finance + cost-report (17 mag 2026 sera)

Sweep i18n round 3: ~50 chiavi nuove.

Dictionary MF_I18N estesa:
- Planning 17: title, 6 tab (calendar/timeline/gantt/kanban/list/todo), new_booking, 5 filtri (resource/job/status/from/to), 4 booking status (tentative/confirmed/done/not_done)
- Finance 16: title, 4 tab (invoices/batches/anomalies/advances_drafts), new_invoice, compose_invoice, 6 col (invoice_number/issue_date/due_date/total/paid/outstanding), legend anomalies, adv.open/drafts titoli card
- Cost Report 17: title, search, view_mode + 2 viste (now/forecast), 8 summary KPI (budget/billed_locked/accrued_post/forecast/margin/invoiced_total/advances), 8 col tabella (unit/quoted/billed/accrued_post/forecast/over_under/real_cost/real_margin)

Template data-i18n:
- finance.html: 4 tab + bottone "+ Nuova fattura" + card titoli (Acconti aperti, Acconti bozze, Legenda anomalie)
- cost_report.html: table headers lista + loading
- planning.html: bottone "+ Booking"

Cache buster i18n.js?v=3.5.0-alpha.149.

Tot dictionary cumulata: ~210 chiavi.

Backlog F29 round 4 (α.150): suppliers + resources + departments + settings + JS dinamico mfT() per toast/render.

---

## v3.5.0-alpha.148 — F29 i18n round 2: clients + projects + quotes (17 mag 2026 sera)

Sweep i18n round 2: ~40 chiavi nuove per pagine clients/projects/quotes.

**Dictionary MF_I18N estesa**:
- Clients (11 chiavi): title, new, col.name/vat/email/phone/projects/industry, search placeholder, ai_enrich, empty.
- Projects (11 chiavi): title, new, search, col.start/end/budget, 4 status (active/on_hold/completed/cancelled), empty.
- Quotes (19 chiavi): title, new, search, col.number/version/total/issue_date/valid_until, sezioni (economic_summary, conditions, advance_terms, items, actions, versions), totali (subtotal, total_net, total_final, vat), bottoni (add_installment, payment_terms, billing_frequency).

**Template data-i18n applicati**:
- `clients.html`: bottone "+ Nuovo cliente", search placeholder, table headers, loading.
- `projects.html`: bottone "+ Nuovo progetto", search placeholder, table headers (Codice/Titolo/Cliente/Stato), loading.
- `quotes.html`: card titoli "Riepilogo economico" / "Condizioni economiche & scadenze" / "Termini di acconto strutturati" + bottone "+ Aggiungi rata".

Cache buster `i18n.js?v=3.5.0-alpha.148`.

**Tot dictionary**: ~160 chiavi cumulate.

**Backlog F29 round 3** (α.149): planning + finance + cost-report.

---

## v3.5.0-alpha.147 — F29 i18n round 1: dashboard + common keys (17 mag 2026 sera)

Inizio sweep i18n completo (F29 backlog α.132). Round 1: dashboard + chiavi comuni riusabili.

**Dictionary `MF_I18N` esteso** (`app/static/js/i18n.js`):
- **Dashboard** (20 chiavi): stat cards + sub-labels, card titoli (capacity_week, recent_jobs, my_bookings, upcoming, margin_dept, today_bookings), bottoni (see_all, detail, go_my_tasks, etc).
- **Column headers comuni** (12 chiavi): col.code/title/client/status/time/amount/date/project/job/description/actions/notes.
- **Common buttons** (14 chiavi): btn.save/cancel/delete/edit/new/add/confirm/close/search/export/import/filter/reset/refresh/loading.
- **Status commons** (11 chiavi): status.active/inactive/draft/sent/approved/rejected/expired/cancelled/paid/overdue/completed.
- **Misc** (2 chiavi): misc.no_data, misc.loading.

**Template dashboard.html**:
- `data-i18n` su tutte stat cards + card titoli + table headers + "Caricamento…" placeholders.
- Preserva markup misto (span figli per icone) via primo text node logic.

**Cache buster**: `i18n.js?v=3.5.0-alpha.147` in base.html + login.html.

**Coverage**: ~60 chiavi nuove. Tot dictionary ora ~120 chiavi (incluse sidebar α.133 + dashboard + common).

**Backlog F29 successivi**:
- Round 2 (α.148): clients + projects + quotes
- Round 3 (α.149): planning + finance + cost-report
- Round 4 (α.150): suppliers + resources + departments + settings
- JS dinamico via `mfT()` helper (toast/render dinamici) — round finale

---

## v3.5.0-alpha.146 — Workflow acconti Step 4/4: CR fill mode + badge JCL (17 mag 2026 pomeriggio tarda)

Chiusura ciclo acconti. Cost report mostra ora copertura acconti per JCL.

**Backend cost_report job endpoint**:
- Pre-fetch `advance_coverage_by_jcl`: `SELECT SUM(AdvancePaymentAllocation.amount) GROUP BY job_cost_line_id` filtrato AP non-cancelled.
- Per ogni JCL nel response cost_lines:
  - `advance_coverage` = Σ AP_alloc.amount per JCL
  - `advance_drift` = total_accrued − advance_coverage (negativo = scoperto, positivo = lavoro extra)
  - `advance_overflow` = bool(advance_coverage > total_quoted * 1.05)

**UI cost report**:
- Badge inline per JCL coperta: `💰 €X · scoperto Y` / `· lavoro extra Y` / `· in linea`.
- Bordo rosso se overflow (> 105% quote).
- Tooltip dettagliato.

**Smoke**: job 2024-0001 JCL 1 coverage €28k drift -€28k overflow True ✓.

**Backlog α.147+**:
- F29 i18n sweep TUTTA UI (round 1: dashboard + sidebar + topbar)
- OAuth integrazioni
- Cross-currency cost-report aggregati

---

## v3.5.0-alpha.145 — Workflow acconti Step 3/4: UI /finance Bozze + confirm + emit (17 mag 2026 pomeriggio tarda)

Step 3/4 della revisione architetturale acconti (piano α.139). UI completa per gestione bozze acconti in /finance + workflow conferma → emit fattura. Deprecato modal "Crea acconto" da /cost-report (workflow ora in /finance).

**Endpoint nuovi** (`/finance/api/...`):

- `GET /advances/pending-draft` — lista AP tenant-wide in stato pending/draft/confirmed con joinedload allocations+job_cost_line. Ordinato per scheduled_due_date ASC nulls last.
- `POST /advances/{id}/confirm` — update label/notes/amount/allocations_update (CSV "id:pct") + transition pending→draft|confirmed. 409 se status >= invoiced.
- `POST /advances/{id}/emit-invoice` — crea Invoice(kind=advance, doc_type=TD01) con snapshot fiscali completi + InvoiceLine descrittiva + lega AP.invoice_id + status=invoiced. Numero auto (`_next_invoice_number_for_advance`) se non fornito.

**UI /finance**:
- Nuova tab "💰 Bozze acconti" con badge count (giallo).
- Sezione `#section-advances-drafts` con lista compatta:
  - status badge colorato (pending=rosso, draft=giallo, confirmed=verde)
  - project code+title, label, scheduled_due_date, count JCL allocate
  - importo + bottoni "🛠 Gestisci" / "💶 Emetti"
- Modal `#modal-advance-confirm`: label, amount, notes, dropdown allocation pct per ogni JCL, 3 azioni (Salva bozza / Conferma / Emetti subito).
- Modal `#modal-advance-emit`: numero auto, data emissione, scadenza, IVA, descrizione riga. Submit → POST emit-invoice.

**Deprecazione /cost-report**:
- Bottone "+ Crea acconto" rimosso dalla card "Acconti del progetto".
- Sostituito con link `→ Gestisci in /finance` che porta a `/finance#section-advances-drafts`.
- Card resta sola lettura per visualizzazione totali progetto.

**Smoke E2E**:
- Quote 47 + schedule 20% pct → materialize → AP pending ✓
- list_pending_draft conta 1 ✓
- confirm: pending → confirmed (label+notes update) ✓
- emit-invoice: crea Invoice 2026-00112 €43k + 1 line + lega AP, status→invoiced ✓
- Verify: AP final status=invoiced invoice_id=118 ✓
- Cleanup ✓

**Backlog α.146**:
- CR fill mode (Coperto/Maturato/Drift per JCL coperta via AdvancePaymentAllocation)
- Warning sforamento (Σ AP + maturato > quote)
- F29 i18n sweep TUTTA UI
- OAuth, cross-currency aggregati

---

## v3.5.0-alpha.144 — Workflow acconti: hook converti quote→job auto-create AP(pending) (17 mag 2026 pomeriggio tarda)

Step 2/4 della revisione architetturale acconti (piano α.139). Hook al converti quote→job materializza QuoteAdvanceSchedule → AdvancePayment(pending) + AdvancePaymentAllocation (mappa QuoteLine→JCL) + Notification admin/manager.

**Modello nuovo `AdvancePaymentAllocation`** (M:N AP↔JCL):
- `advance_payment_id`, `job_cost_line_id`, `pct` (0..1), `amount` (snapshot).
- UniqueConstraint coppia.
- Foundation per α.145 CR "fill mode" (Coperto/Maturato/Drift per JCL).

**`AdvancePayment` esteso**:
- `invoice_id` ora NULLABLE (AP pending nasce senza fattura). SQLite rebuild table runtime in `_auto_migrate_columns` (CREATE _ap_new + COPY + DROP+RENAME).
- `quote_advance_schedule_id` (FK origine, NULL per AP α.136 manuali).
- `scheduled_due_date` (date, computata da anchor+offset).
- `label` (snapshot da schedule).
- Relationship `allocations` con cascade delete.

**Servizio `app/services/advance_schedule_to_payment.py`**:
- `materialize_schedules(db, quote, job, user_id, tenant_id)`:
  - Per ogni QuoteAdvanceSchedule della quote → AP(pending) idempotente (skip se `quote_advance_schedule_id` già esiste).
  - Amount: `amount_fixed` prevale su `pct × quote_total_after_discount`.
  - Due date computata da `due_anchor` (4 opzioni):
    - quote_approved → today + offset
    - project_start → job.start_date + offset (fallback today)
    - specific_date → schedule.due_date
    - milestone → None (futuro)
  - AdvancePaymentAllocation: risolve QuoteAdvanceAllocation.quote_line_id → JCL.id via `JCL.quote_line_id`.
  - Notification a admin/manager con body composto: quote+job+lista rate+due+importi+link `/finance#section-invoices`.
- Fail-soft: errori loggati ma non bloccano conversione quote→job.

**Hook `_create_job_from_quote`** (quotes.py):
- Parametro nuovo `user_id` opzionale.
- Dopo job+JCL creati + db.flush, chiama `materialize_schedules`.
- Try/except fail-soft.
- Anche su re-converti (job già esistente): re-invoca materialize (idempotente skippa).

**Smoke E2E**:
- Quote 47 Q-2024-0018 (total €143'377) + 1 schedule 30% pct + 2 allocations 50% su 2 QuoteLine
- materialize → 2 AP pending (€43'013 cad.) + 2 allocations cad. + 4 utenti admin/manager notificati ✓
- Re-run idempotente: created 0, skipped 2 ✓
- Cleanup ✓

**Backlog α.145+**:
- UI /finance "Bozze acconti" + workflow conferma + emit invoice acconto (deprecazione modal /cost-report)
- CR fill mode: per JCL coperta mostra "Coperto da acconto: €X · Maturato: €Y · Drift: €Z" + warning sforamento
- F29 i18n sweep TUTTA UI
- OAuth integrazioni
- Cross-currency cost-report aggregati

---

## v3.5.0-alpha.143.1 — HOTFIX cashflow filtri + anni dup (17 mag 2026 pomeriggio tarda)

Matteo segnala 4 problemi non risolti da α.142 + 1 nuovo bug introdotto.

**#1 BUG α.142: anni duplicati in select anno**:
- ROOT CAUSE: `initYearSelect()` chiamato 2 volte (preesistente line 753 + mia aggiunta α.142 line 761). 2 iterazioni for → 10 anni duplicati.
- Fix: rimozione doppia chiamata + guard idempotente `while (sel.firstChild) sel.removeChild(...)` prima di popolare.

**#2 Filtri cliente/progetto cashflow non funzionanti**:
- ROOT CAUSE: MFAutocomplete (multi) usato per filtri singoli. `hidden.value` CSV ok backend ma onChange triggera reload incoerente. UI dropdown non rispondevano live.
- Fix: sostituito `<div class="mf-ac">` + `<input hidden>` con `<select>` nativo single-choice. Auto-filter progetti per cliente selezionato. `onCfClientChange()` triggera reload diretto.
- `loadFilters()` popola `<option>` ordinati alfabeticamente.
- `_renderCfProjectOptions()` filtra progetti per cliente + preserva selezione se valida.

**#3 Cashflow non si aggiorna su anno selezionato**:
- Aggiunto `addEventListener('change')` esplicito su `cf-year` con log console (oltre all'onchange attributo HTML).

**#4 BUG α.143: `/jobs/api` inesistente**:
- ROOT CAUSE: modal nuova fattura usava endpoint `/jobs/api` che non esiste. Endpoint corretto: `/planning/api/jobs`. Cascade job→JCL non funzionava.
- Fix: sostituito endpoint.

**#5 NC senza data permane banner**:
- DB check: 0 invoice attualmente senza issue_date nel DB demo. Banner non appare a meno che count > 0.
- Banner reso più dettagliato: lista primi 10 IDs + link cliccabile `/finance#section-invoices` per correggere direttamente.

**Smoke**: render cashflow.html, endpoint `/planning/api/jobs` esiste in routes.

---

## v3.5.0-alpha.143 — Fatturazione: crea fattura ampliato + acconti visibili (17 mag 2026 pomeriggio)

**Crea fattura modal**: ampliato con dropdown cliente/progetto/quotazione/job/JCL (cascade).

Frontend:
- Modal `#modal-new-invoice` esteso con 4 select aggiuntivi: progetto, quote, job, JCL.
- Cache `_invAllProjects/_invAllQuotes/_invAllJobs` + per-job `_invAllJcls`.
- Cascade auto-populate: cliente → filtra progetti; progetto → filtra quote+job; quote → auto-set progetto; job → fetch JCL via `/cost-report/api/job/{id}`.
- Bidirezionale: scegliendo quote auto-popola progetto e cliente.
- Force checkbox: visibile solo se né progetto né quote selezionati. Conferma "fattura senza link strutturato sconsigliata".
- `openNewInvoiceModal()` wrapper sostituisce `openModal()` diretto per pre-caricamento cache.

Backend `POST /finance/api/invoices` esteso:
- Form params: `project_id`, `quote_id`, `job_id`, `jcl_id`, `force`.
- Validazione: senza project E quote → 400 a meno che `force=true`.
- `jcl_id` appendito in notes (no colonna FK dedicata per ora).

**Acconti visibili**: nuova card "💰 Acconti aperti" in tab Fatture.

Backend:
- Nuovo `GET /finance/api/advances/open` ritorna AP status=open balance>0 tenant-wide con joinedload invoice/project/consumptions.
- Response: rows con invoice_number/status/total/amount_paid + project_code/title + amount/consumed/balance.

Frontend:
- Card collassabile sopra widget F25 (Quotato vs Fatturato).
- Lista compatta: numero fattura · progetto · status badge (paid/da-scomputare) · importi (totale · scomputato · residuo) · bottone "Apri" → `/projects/X`.
- Summary: "N acconti aperti · residuo totale €X".
- Caricato in `init()` via `loadOpenAdvances()`.

**Smoke render**: finance.html 156384 chars con inv-project/quote/jcl, open-advances-card, loadOpenAdvances presenti ✓. Endpoint `/finance/api/advances/open` registrato (459 routes totale).

**Backlog α.144+** (workflow acconti):
- Hook converti quote→job: auto-create AdvancePayment(pending) da QuoteAdvanceSchedule + Notification admin
- UI /finance "Bozze acconti" + workflow conferma/emit
- CR fill mode (Coperto/Maturato/Drift per JCL coperta)
- F29 i18n sweep TUTTA UI
- Conversione cross-currency in cost-report aggregati

---

## v3.5.0-alpha.142 — Cashflow: 3 fix (17 mag 2026 pomeriggio)

**#1 Year dropdown vuoto in apertura**:
- `initYearSelect()` non veniva mai chiamato → dropdown vuoto → utente non vedeva l'anno default selezionato (i dati caricavano comunque via `_curYear` fallback).
- Fix: chiamata aggiunta PRIMA di `loadFilters()`.

**#2 Filtri cliente/progetto non funzionanti**:
- ROOT CAUSE: MFAutocomplete usa multi-select → `cf-client.value` è CSV `"1,2,3"` → FastAPI rifiutava parse `int` → 422 silenzioso → cashflow non si aggiornava.
- Fix backend `cashflow_year` endpoint:
  - `project_id`/`client_id` ora `Optional[str]` (era `Optional[int]`)
  - Helper `_parse_csv_ids` parsa CSV → lista
- Fix `cashflow_year_sync` accetta sia int singolo (back-compat) sia lista:
  - `_to_id_list()` normalizza input
  - 5 filtri SQL convertiti da `== id` a `.in_(ids)`:
    - Invoice.client_id, Job.project_id (revenue)
    - SupplierInvoice.project_id, Project.client_id (cost)
    - OverheadCost.source_project_id (capex)
- `yearly_forecast` passa primo id (no multi support, low-impact).

**#3 NC/storno senza data permane in cashflow**:
- ROOT CAUSE: Invoice con `issue_date=None` finivano nel bucket gennaio (fallback `if inv.issue_date else 1`).
- Fix backend: skip Invoice senza issue_date dal bucket (no più fallback fuorviante).
- Tracciamento: lista `invoices_missing_date` esposta nel response.
- UI banner amber: "⚠ N fattura/e senza data esclusa/e dal cashflow. Vai a /finance#invoices per correggere."

**Smoke**: `cashflow_year(2026, project_id='12,8')` → 12 months + 0 missing_date ✓. CSV `client_id='1'` → 12 months ✓.

**Backlog α.143**:
- Crea fattura ampliato (cliente/progetto/quote/job/lavorazione + force se senza link)
- Acconti visibili in fatturazione (lista pending/draft AP)

---

## v3.5.0-alpha.141 — Anomalie: 7 fix UX/workflow (17 mag 2026 mattina)

Feedback Matteo: lista anomalie + azioni vanno migliorate. 7 punti chiusi.

**#1 Lista mostra Progetto code + title insieme**:
- Cell progetto: `{code} — {title}` invece di solo code. Tooltip su title completo.

**#2 Azioni dropdown invece di input numerico + rinomina "Pozzo costi" → "Dirotta su spese aziendali"**:
- `openAnomActionPopover` refactor: rimosso `prompt()` numerico, sostituito con modal `#modal-anom-handle`.
- Select dropdown 4 azioni con label aggiornati. ACTION_LBL `overhead_cost` → "📦 Dirotta su spese aziendali".
- Bulk dropdown stesso aggiornamento.

**#3 Tooltip side-effects azione**:
- Nuovo dict `ACTION_EFFECTS` con `title`, `effect`, `target_role` per ogni azione.
- Box info nel modal con `#an-handle-effect` aggiornato live su change azione.
- Title HTML sui `<option>` dropdown bulk con descrizione side-effect.

**#4 rimanda_commerciale + rivaluta_producer chiedono target user + msg + next_action**:
- Backend `_handle_single` esteso con `target_user_id` + `next_action_label`.
- Se azione = rimanda/rivaluta + target_user_id fornito → crea `Notification` (kind=custom, severity=action_required, link a progetto/anomalies, title "[{azione}] Anomalia #N", body composto con tipo + progetto + importo + msg + next_action).
- UI modal mostra dropdown user (`/auth/api/users`) + select next_action_label (6 preset + libero) condizionali per le 2 azioni.

**#5 Auto-rilevamento extra post-fattura**:
- Checkbox "auto-rileva" in toolbar anomalies: `toggleAnomAutoDetect()` triggera `setInterval(detect, 10min)` mentre la pagina è aperta. Idempotente (detector è idempotente, no dup).

**#6 Legenda funzioni tipo voci**:
- `<details>` collassabile in header tab anomalies con 2 tabelle:
  - Tipi anomalie (6 voci): descrizione + esempio + colore badge
  - Azioni (5 voci, include Dismiss): conseguenze concrete + DB write side-effects

**#7 Filtri dipartimento**:
- Backend `list_anomalies` esteso `department_id` filter via subquery JCL→price_item.department_id. Applica SOLO a anomalie source_kind='jcl' (altre source non hanno reparto diretto → escluse).
- UI dropdown `#an-dept-filter` in toolbar caricato al init da `/departments/api`.

**Files toccati**:
- `app/routers/anomalies.py` — list filter + handle params target_user_id/next_action_label + Notification emit
- `app/templates/pages/finance.html` — legenda, filtri dept, auto-detect, modal handle, refactor lista

**Smoke**: render finance.html 144708 chars con modal-anom-handle/an-dept-filter/Legenda/Dirotta presenti. Endpoint `/auth/api/users` + `/departments/api` esistenti.

**Backlog α.142+**:
- α.142 Cashflow (3 fix: auto-load anno, filtri cli/proj, NC senza data)
- α.143 Crea fattura ampliato + acconti visibili
- Workflow acconti (α.144+) con auto-create AP pending al converti quote→job

---

## v3.5.0-alpha.140.1 — HOTFIX: loadQuote → reloadQuote (17 mag 2026 mattina)

**Bug**: aggiunta/cancellazione/modifica rata acconto + cambio valuta non aggiornavano visualizzazione.

**Root cause**: introdotto α.137 + α.139, chiamate a `loadQuote(currentQuote.id)` — funzione INESISTENTE nel template. Nome corretto è `reloadQuote()` (no arg, usa `currentQuoteId` globale). Errori JS silenti in console.

**Fix**: replace 4 occorrenze in:
- `changeQuoteCurrency` (α.137)
- `refreshQuoteFx` (α.137)
- `submitAdvanceSchedule` (α.139)
- `deleteAdvanceSchedule` (α.139)

**Smoke backend** (pre-fix): GET quote `_get_schedules_serialized` ritornava schedules corretti. POST/DELETE schedule funzionavano. Bug era SOLO refresh UI post-azione.

---

## v3.5.0-alpha.140 — UX quote: accorpamento condizioni + modal rata bidirezionale + cards collassabili (17 mag 2026 mattina)

Feedback Matteo post-α.139 prima di procedere con hook auto-create AP. 5 fix UX:

**q1 — Accorpamento card "Condizioni economiche & scadenze"**:
- Card "Termini di acconto" separata α.139 RIMOSSA.
- Sezione spostata DENTRO card esistente "Condizioni economiche & scadenze" con separator dashed.
- Logica: periodicità fatturazione + termini acconto sono strettamente collegati, vivono insieme.
- Note in periodicità rimanda esplicitamente ai termini sotto.

**q2 — Modal rata: bidirezionale pct ↔ amount + display selezione voci**:
- `oninput` su pct → ricalcola amount = pct% × quote_total e mostra "= €X CCY".
- `oninput` su amount → ricalcola pct e mostra "(X% del quote €Y CCY)".
- `refreshAdvanceAllocationSummary()` su checkbox/input alloc: riepilogo live "N voci · totale €X CCY = Y% del preventivo".
- Warning ⚠ se pct manuale ≠ pct allocato (>0.5% delta) — colore amber.
- Trigger init dei display al openModal (sia nuova sia edit).

**q3 — Rata salvata visibile**:
- Verificato: submitAdvanceSchedule chiama loadQuote post-save → GET include `advance_schedules` → renderAdvanceSchedules invocato. No bug.

**q4 — Cards collassabili con persistenza**:
- Helper `initCollapsibles()` scansiona `[data-collapsible="key"]` + aggiunge toggle button nel card-title.
- Stato salvato in `localStorage["mfQuoteCollapse_<key>"]`.
- Body collassabile auto-wrappato (siblings post-title).
- Idempotente (doppia init no-op via `data-collapsible-init`).
- Cards taggate: quote-summary, quote-actions, quote-versions, quote-conditions, quote-lines (5).
- Esteso anche al card meta principale via data-collapsible (totale 6 cards).

**q5 — Audit cambio valuta**:
- `_recalc_quote` NON usa `fx_rate`/`currency`. Verificato source: solo qty/price/sconti.
- `quote_pdf.py` NON usa `fx_rate`/`currency`. Verificato grep no-match.
- `changeQuoteCurrency` aggiorna solo `Quote.currency` + `fx_rate_to_base` snapshot, NON tocca line.total né subtotal/total/PDF.
- Aggiunto tooltip esplicativo sul card valuta editor: "Cambio valuta: NON converte voci/totali/PDF".
- No fix backend necessario, comportamento atteso confermato.

**Smoke render**:
- quotes.html parse 199071 chars ✓
- 6 cards con data-collapsible ✓
- initCollapsibles + onAdvancePctInput + refreshAdvanceAllocationSummary presenti ✓
- advance-schedules-card OUT (refactor q1) ✓

**Backlog α.141+**:
- α.141: hook converti quote→job auto-create AP(pending) + notifica admin (era piano originale α.140, ora slittato)
- α.142: UI /finance "Bozze acconti" + workflow conferma + emit invoice acconto (deprecazione modal CR)
- α.143: CR fill mode (Coperto/Maturato/Drift per JCL coperta)
- F29 i18n sweep TUTTA UI
- OAuth integrazioni

---

## v3.5.0-alpha.139 — Revisione architetturale acconti: termini in quote (QuoteAdvanceSchedule) + workflow stateful (17 mag 2026 mattina)

Revisione architettonica acconti su feedback Matteo post-α.138: "L'acconto va emesso dalla fatturazione (sostituisce manuale) e deve essere associato a lavorazioni con %, definito in quotazione con scadenze configurabili per periodo, notifica admin e template precompilato. Workflow: quote (definisci) → finance (notifica+bozza+conferma+emit) → CR (visualizza fill maturato/drift)".

**Piano** (4 versioni α.139-142):
- **α.139** (questa): foundation termini in quote (modelli + endpoint + UI)
- **α.140**: auto-create AdvancePayment(pending) al converti quote→job + notifica admin
- **α.141**: UI /finance "Bozze acconti" + workflow conferma/assign-JCL + emit invoice acconto
- **α.142**: CR fill mode (Coperto/Maturato/Drift per JCL coperta)

**α.139 deliverables**:

**Modelli nuovi**:
- `QuoteAdvanceSchedule(quote_id, label, pct, amount_fixed, due_anchor, due_offset_days, due_date, milestone_label, sort_order, notes)`. pct OR amount_fixed; due_anchor enum (quote_approved/project_start/specific_date/milestone).
- `QuoteAdvanceAllocation(schedule_id, quote_line_id, pct)` M:N con UniqueConstraint coppia. Opzionale: se assente → acconto copre intero progetto.
- `AdvanceDueAnchor` enum (4 valori).
- **`AdvancePaymentStatus` esteso** con workflow stateful: `pending` (auto α.140) → `draft` → `confirmed` → `invoiced` → `paid` → `consumed`. `open` legacy mantenuto come alias di `invoiced`.

**Auto-migrate**: `create_all()` crea le 2 nuove tabelle. Nessun ALTER (le tabelle sono nuove).

**Endpoint** (`/quotes/api/...`):
- `GET /{quote_id}/advance-schedules` — lista schedule + allocations.
- `POST /{quote_id}/advance-schedules` — crea con validazione (pct 0-1, amount ≥ 0, anchor enum) + allocations CSV `"line_id:pct,line_id:pct"`.
- `PUT /advance-schedules/{id}` — update parziale (label/pct/amount/anchor/offset/date/milestone/notes/sort).
- `DELETE /advance-schedules/{id}` — cascade su allocations.
- GET quote esposto `advance_schedules: [...]` nella response.

**UI Quote editor**:
- Nuova card "💰 Termini di acconto" tra meta-blocco e voci preventivo.
- Lista rate con label/pct/scadenza/allocations count/importo calcolato + bottoni ✎/✕.
- Riepilogo totale rate (% + fissi + €) con warning se > 100% quote.
- Modal "Aggiungi/Modifica rata": label, pct OR amount, ancora scadenza (4 opzioni), offset/data/milestone (UI condizionale), note, allocazione opzionale a QuoteLine via checkbox + input % per riga.
- DOM via createElement/textContent (no XSS surface).

**Compat**:
- α.136-138 ledger AdvancePayment + scomputi consumption rimangono attivi e usati da emit_invoice batch.
- α.141 prevede deprecazione "Crea acconto" manuale da /cost-report (verrà rimosso quando workflow nuovo è completo).

**Smoke E2E**:
- Create schedule "Acconto 30%" (pct=0.30, anchor=project_start, offset=15gg) + 2 allocations (line 66:50%, line 67:50%) ✓
- LIST quote ritorna 2 schedule (esistente + nuova) ✓
- UPDATE pct 0.30 → 0.35 ✓
- _get_schedules_serialized via GET quote → allocations preservate ✓
- DELETE cascade su allocations ✓

**Backlog α.140**:
- Hook converti quote→job: per ogni schedule auto-crea AdvancePayment(status=pending, project_id, scheduled_due_date computato da anchor+offset) + copia QuoteAdvanceAllocation → AdvancePaymentAllocation
- Notifica admin: NotificationKind nuovo `advance_pending` (severity=warning) con link a `/finance#advances-draft`
- Endpoint `/finance/api/advances/pending` (lista bozze tenant) per α.141 UI

---

## v3.5.0-alpha.138 — Acconti Step 2: scomputo automatico in batch + auto-scompute closing + CR aggregati (17 mag 2026 mattina)

Chiude il ciclo acconti aperto in α.136. Pattern B completo end-to-end:
acconto emesso → scomputato nelle fatture batch successive → residuo auto-scomputato nella closing.

**Helper backend** (`billing.py`):
- `_parse_advance_consumptions_csv("id:amt,id:amt")` → lista (id, amt). Solleva 400 su parse/negativo.
- `_apply_advance_consumptions(db, invoice, project_id, consumptions, billing_batch_id, vat_rate)`:
  - Valida: AP esiste, project match, status=open, amount ≤ balance_remaining.
  - Crea InvoiceLine negativa "Scomputo acconto {invoice_num}" (total=-amt).
  - Crea AdvancePaymentConsumption (ledger).
  - Riduce balance_remaining; se ≤ 0.005 → status=consumed.
  - Aggiusta invoice.subtotal -= total_consumed e invoice.total proporzionalmente.
  - Solleva 409 su tutte le violazioni.

**Endpoint estesi**:
- `POST /billing/{batch_id}/invoice` accetta `advance_consumptions` Form CSV. Scomputa dopo aver creato InvoiceLine normali. Risponde con `advance_consumptions: {applied, total_consumed}`. Link `invoice.project_id` automatico.
- `POST /billing/compose-invoice` (aggregato batch): stesso pattern.
- `POST /billing/closing-invoice/{project_id}`: **auto-scompute FIFO** di tutti gli AP open del progetto fino a esaurire il subtotal della closing. Ritorna `advance_consumptions` + `advance_overflow_open` (residuo non scomputabile = warning per manager, risolve via NC TD04 manuale).

**Cost Report endpoints estesi** (Σ aggregati per project):
- `list_cost_reports`: pre-fetch `advance_amount` (Σ AP.amount), `advance_consumed` (Σ APC.amount_consumed), `advance_balance` (Σ AP.balance_remaining). Esposti per ogni job.
- `job_cost_report`: stessi campi nel summary + `advance_overflow_flag` (true se billed_locked + advance_amount > quote * 1.05).

**UI modal "Emetti fattura da batch"** (`/finance` template):
- Nuova sezione "💰 Scomputo acconti aperti del progetto" caricata via `_loadAdvancesForEmit(projectId)`.
- Lista checkbox + input importo per ogni AP open. Auto-suggest = min(balance, batch_subtotal_residuo).
- Recalc live dei totali: Imponibile lordo / Scomputo (verde) / Imponibile netto / IVA / Totale.
- Submit invia `advance_consumptions` CSV. Toast estesa con "Scomputo acconti −€X".
- DOM via createElement/textContent (no XSS surface).

**UI Cost Report card "Acconti del progetto"** (preesistente α.136):
- I 3 stat-card (Totale acconti / Già scomputato / Residuo aperto) si aggiornano automaticamente con i nuovi consumi.

**Smoke E2E** (job 9 Shadow Stagione 3, project 12):
- 2 AP creati (€3000 + €2000) ✓
- Scomputo €1500 da AP1 + €500 da AP2 su invoice test (subtotal 5000 → 3000) ✓
- AP1 balance 3000 → 1500 (open) ✓
- AP2 balance 2000 → 1500 (open) ✓
- Full consume AP2 1500 → 0 → status=consumed ✓
- Over-consume €99999 → 409 reject ✓
- Cleanup ✓

**Backlog α.139+**:
- F29 i18n sweep TUTTA UI (~500-1000 chiavi IT/EN/FR/DE)
- Conversione cross-currency in cost-report aggregati (project con quote USD vs base EUR)
- OAuth Gmail/Outlook/Drive/OneDrive
- Test parse 14 capitolati restanti
- Automazione portali consegne

---

## v3.5.0-alpha.137 — Multi-currency Quote + Settings valuta base + FX rate live (17 mag 2026 mattina)

Richiesta diretta Matteo post α.136: "Prevedi anche nelle impostazioni la valuta base. Inoltre prevedi di emettere quotazioni in dollari (strumento di conversione automatica sulla base del prezzo attuale del dollaro da implementare in quotazione in tempo reale)".

**Modelli nuovi**:
- `FXRate(from_currency, to_currency, rate, fetched_at, provider)` con UniqueConstraint coppia.
- Cache 1h TTL configurabile, refresh on-demand.
- Single row per coppia, update in place al refresh.

**Quote estesa**:
- `currency` (ISO 4217, default 'EUR') + `fx_rate_to_base` (snapshot al momento creazione) + `fx_rate_fixed_at` (timestamp).
- Subtotal/total memorizzati nella `currency` della quote (NON convertiti). Conversione a base on-the-fly per report aggregati.

**Tenant estesa** (campo già esistente, ora esposto in UI):
- `default_currency` (ISO 4217, default 'EUR').

**Servizio FX** (`app/services/fx.py`):
- Provider: **Frankfurter** (api.frankfurter.app, BCE-based, **free, no API key**).
- `get_fx_rate(db, from, to, max_age_minutes=60)` — cache+refresh.
- `refresh_fx_rate(db, from, to)` — forza refresh.
- `convert(amount, from, to, db)` — converte importo.
- Fail-soft: stale fallback se provider down + cache presente, None se entrambi mancano.
- Same-currency shortcut (rate=1.0).

**Auto-migrate al boot**:
- Tabella `fx_rates` creata da `create_all()`.
- ALTER `quotes` ADD `currency`/`fx_rate_to_base`/`fx_rate_fixed_at`.
- Idempotente.

**Endpoint** (`/finance/api/...`):
- `GET /fx/{from}/{to}?refresh=true` — rate cached (default) o force refresh. 503 se provider down + no cache.

**Quote API estesa**:
- `POST /quotes/api/quotes` accetta `currency` (Form, default = tenant.default_currency). Setup automatico fx_rate da Frankfurter (snapshot immutabile).
- `PUT /quotes/api/{id}` accetta `currency` + `refresh_fx=true`. Cambio valuta o refresh tasso **bloccato post-emissione** (solo draft). Refresh forza pull dal provider.
- `GET /quotes/api/{id}` espone `currency`, `fx_rate_to_base`, `fx_rate_fixed_at`.

**UI Settings** (tab Azienda):
- Dropdown "Valuta base" (8 valute: EUR/USD/GBP/CHF/JPY/CAD/AUD/CNY).
- Salvato via `default_currency` Form param in PUT /api/company.

**UI Quote** (editor):
- Nuova card "Valuta" sopra Riepilogo economico.
- Draft: dropdown valuta + info tasso (live "1 USD = 0.8599 base · snapshot 17/05/2026 10:30") + bottone 🔄 refresh.
- Post-emissione (sent/approved/...): badge readonly "(immutabile post-emissione)".
- DOM via createElement/textContent (no innerHTML su dati esterni) → no XSS surface.

**Smoke FX provider live**:
- USD→EUR 0.85999, EUR→USD 1.1628, GBP→EUR 1.1488, EUR→EUR 1.0 ✓
- Convert 1000 USD = €859.99 / 1000 EUR = $1162.80 ✓
- Cache hit dopo prima fetch ✓
- Endpoint `/finance/api/fx/USD/EUR` ritorna `{rate: 0.85999, fetched_at: ..., provider: frankfurter, same_currency: false}` ✓

**Smoke template**: quotes.html parse 175984 chars con `quote-currency-host` + `changeQuoteCurrency` presenti ✓.

**Backlog α.138+**:
- Acconti Step 2 (scomputo automatico nelle fatture batch successive + closing auto-scompute)
- F29 i18n sweep TUTTA UI (~500-1000 chiavi)
- Conversione importi cross-currency in cost-report aggregati (project con quote USD vs base EUR)
- OAuth integrazioni
- Test parse 14 capitolati restanti

---

## v3.5.0-alpha.136 — Acconti progetto Step 1 (Pattern B ledger AdvancePayment) (17 mag 2026 mattina)

Risposta strutturata al gap evidenziato da Matteo dopo α.135: "fattura manuale non si lega a progetto/lavorazione. Serve modalità pagamento anticipato in CR, lavoro futuro copre la cifra emessa". Pattern B — ledger separato — implementato in Step 1.

**Modelli nuovi**:
- `AdvancePayment(tenant_id, project_id, invoice_id UNIQUE, amount, balance_remaining, status, notes, created_by_user_id, created_at)`
- `AdvancePaymentConsumption(tenant_id, advance_payment_id, invoice_id, billing_batch_id, amount_consumed, notes, created_at)` (cascade da AdvancePayment)
- `InvoiceKind` enum: `regular | advance | balance` (semantica funzionale, ortogonale a doc_type SDI)
- `AdvancePaymentStatus` enum: `open | consumed | cancelled`

**Invoice estesa**:
- `kind` (default regular) + `project_id` (nullable, link diretto a progetto per fatture multi-job o project-level come acconti).

**Migrazione auto al boot**:
- `Base.metadata.create_all()` crea le 2 nuove tabelle (advance_payments, advance_payment_consumptions).
- `_auto_migrate_columns` aggiunge `invoices.kind` (default 'regular') + `invoices.project_id` (nullable FK).
- Idempotente. Compatibile con DB esistenti.

**Endpoint** (`/finance/api/...`):
- `POST /projects/{id}/advances` — crea Invoice(kind=advance, project_id=X, doc_type=TD01) + 1 InvoiceLine descrittiva + apre AdvancePayment(balance=full, status=open). Snapshot fiscali completi (immutabilità post-emissione). Auto-numero `{anno}-{NNNNN}` se non fornito.
- `GET /projects/{id}/advances` — lista acconti + totali (amount/consumed/balance_remaining). Per UI card.
- `POST /advances/{id}/cancel` — annulla acconto (consentito SOLO se balance==amount, nessun consumo). L'invoice resta — NC TD04 a parte se serve stornare.

**UI Cost Report dettaglio**:
- Nuova card "💰 Acconti del progetto" sopra il widget Fatturazione (visibile solo se job ha project_id).
- 3 stat-card: Totale acconti / Già scomputato / Residuo aperto.
- Lista acconti con badge stato (Aperto/Consumato/Annullato), numero fattura, data emissione, note, importi (importo · −scomputato · residuo), bottone "✕ Annulla" solo se open + no consumi.
- Modal "💰 Crea acconto": importo imponibile, IVA, descrizione riga, data emissione, scadenza, numero (auto), note.
- Toaster + refresh auto card dopo create/cancel.
- Tutti i contenuti dinamici via textContent/createElement (no innerHTML su dati esterni) → no XSS surface.

**Smoke E2E** (job 9 = Shadow Stagione 3, progetto 12):
- Create acconto €5'000 + 22% IVA → invoice 2026-00112 + AdvancePayment id=1 ✓
- List → 1 row, totals (amount 5000, consumed 0, balance 5000) ✓
- Cancel → status=cancelled ✓
- Cleanup invoice ✓

**Step 2 (α.137+) — scomputo nelle fatture batch successive**:
- Estensione `emit_invoice` (batch): dropdown "scompute acconti aperti?" + InvoiceLine "Scomputo acconto" auto-generata negativa + AdvancePaymentConsumption registrata.
- Closing invoice auto-scompute residuo aperto del progetto.
- Cost Report: colonna "Coperto da acconto" per JCL.
- Warning UI se Σ batch + Σ acconti > quote_total.

**Backlog α.137**:
- Step 2 acconti (scomputo automatico)
- Settings valuta base (Tenant.base_currency)
- Quote multi-currency + FX rate live (Frankfurter BCE, free, no key)

**Backlog α.138+**:
- F29 i18n sweep completo tutta UI (~500-1000 chiavi, IT/EN/FR/DE)
- Test parse 14 capitolati restanti
- OAuth integrazioni
- Automazione portali consegne

---

## v3.5.0-alpha.135 — F26/F27/F30 coerenza CR↔Fatturazione (pattern B) + F28 root cause (17 mag 2026 mattina)

Chiusura bundle anomalie architetturali emerse α.134 su Shadow Stagione 3. Pattern B: trasparenza UI senza riarchitettura. Visibilità immediata in /cost-report lista + dettaglio.

**F28 — Root cause mismatch slice vs invoice line (DEBUG, no code change)**

Investigazione DB Shadow: inv 22 subtotal €7'358 con 1 line "Acconto 20%" + Σ slice €6'110 (7 slice da batch BB-2026-0002 €6'110). Disaccoppiamento totale.

Causa: `seed_stress.py` STAGE 9 genera Invoice "manuali" (1 line "Acconto/SAL/Saldo" con pct random del quote) PRIMA dello STAGE 14 che crea BillingBatch + JCLBilledSlice independentemente, pickando random un'invoice esistente per `slice.invoice_id`. By-seed-design — NON bug production.

In produzione reale, l'unico flow che lo riproduce è: `POST /finance/api/invoices` (creazione manuale acconto) + `POST /billing/batch/{id}/emit-invoice` (emit batch su altra fattura periodo successivo). I 2 stream sono entrambi validi ma disaccoppiati dal punto di vista contabile.

Conclusione: Pattern B (visibilità split) è la risposta giusta. No riarchitettura. Salvato in memoria `project_alpha134_findings.md`.

**F26 — Split fatturato linked-to-JCL vs amministrativo**

Backend `/cost-report/api/list` + `/cost-report/api/job/{id}`:
- `invoiced_net` = Σ Invoice.subtotal (imponibile, no draft/cancelled, TD04 sottratto con sign -1)
- `billed_admin_net` = invoiced_net − billed_locked (Σ slice) = fatturato senza link a JCL
- `admin_flag` = bool(|billed_admin_net| > 5% del quotato)

UI lista CR: badge inline `⚠ admin ±€X` nella riga del job (tooltip dettagliato).
UI dettaglio CR: nuova KPI card "Fatturato totale" con sub "di cui amministrativo: ±€X". Bordo amber quando admin_flag.

**F27 — Warning JCL billed/paid && total_accrued=0 (fake billing)**

Backend:
- Job level: `fake_billing_count` = N JCL con billing_status billed/paid e total_accrued=0
- Line level: `fake_billing` boolean per ogni JCL del job

UI lista: badge `⚠ fake-bill N` nella riga del job (rosso).
UI dettaglio: card KPI dedicata `⚠ Fake billing` con bordo rosso (solo se count > 0). Badge `⚠ no-work` nella riga di ogni voce di costo fake.

**F30 — Voci fatturazione CR non corrette**

Generalizzazione F26+F27 — già risolta dalle stesse modifiche. Il dettaglio CR ora mostra contemporaneamente:
- Fatturato chiuso (Σ slice, linked-to-JCL) — pre-esistente
- Fatturato totale (Σ Invoice, include amministrativo) — F26 nuovo
- Delta admin esplicito + warning visivo

Smoke E2E su Shadow Stagione 3 (job 9):
- budget_quoted €36'794,81 ✓
- billed_locked €11'975,29 (Σ slice) ✓
- invoiced_net €36'794,81 (Σ Invoice) ✓
- billed_admin_net €24'819,52 (fantasma 67%) ✓ admin_flag=True
- fake_billing_count 7/7 JCL paid senza ore ✓

**Backlog α.136+**: F29 i18n sweep completo (~500-1000 chiavi), test parse 14 capitolati restanti, OAuth integrazioni, automazione portali consegne.

---

## v3.5.0-alpha.134 — F25 widget Quotato vs Fatturato per progetto + analisi anomalie Shadow (16 mag 2026 notte tarda)

Finding emerso da Matteo uso reale 16 mag tarda: incongruenza Cost Report vs Fatturazione su progetto Shadow Stagione 3. Investigato + soluzione immediata F25 + documentazione anomalie architetturali per α.135+.

**Analisi Shadow Stagione 3 (project 12)**

Setup: Quote €44'889 (€36'795 imponibile) → 3 fatture paid (€44'889 incassati) → BUT:
- JCL.total_accrued = €0 (zero ore maturate)
- Bookings done = 0/14 (nessun booking executed)
- Σ JCLBilledSlice.billed_amount = €11'975 (solo 14 slice da 2 batch)
- "Fatturato fantasma" (€36'795 - €11'975 = €24'820, 67% del quotato) non agganciato a JCL via slice

Pattern: fatture create con line manuali "Acconto 20%", "SAL 2/3", "Saldo finale" disaccoppiate dalle slice batch-generate.

**F25 — Widget "Quotato vs Fatturato per progetto" in /finance#invoices**

Card collassabile (default chiusa) sopra la tabella fatture. Click sul header espande + carica.

Backend `GET /finance/api/project-billing-summary`:
- Quote totals per project (Quote.total_with_vat, status approved/sent/superseded)
- Invoice totals via Job (subtotal/total/amount_paid, NC TD04 sottrae con sign -1)
- Σ JCLBilledSlice.billed_amount per project (solo non voided)
- Calcola `admin_net = invoiced_net - slice_linked_net` (= fatturato amministrativo extra-JCL)
- `delta_vat = invoiced_vat - quoted_vat` (over/under-billing)
- Ordinato per quoted_vat desc

UI: tabella 8 colonne (Progetto · Quotato IVA · Fatturato IVA · Pagato · Aperto · Slice-linked · Admin · Δ vs Quote).

**Evidenze visive**:
- **Admin** in arancione `#f59e0b` se > 5% del quotato → "potenziale incongruenza Cost Report"
- **Δ vs Quote** in rosso se positivo (over-billed), grigio se negativo (sotto-fatturato), verde se zero
- **Pagato** sempre verde, **Aperto** ambra se > 0

**Smoke**: 43 progetti listati con fatture. Shadow Stagione 3 confermato: admin_net €24'819 (67% del quotato), warning arancione.

**Anomalie architetturali documentate** (decision design α.135+):

Findings salvati in memoria `project_alpha134_findings.md`:
- **F26**: disaccoppiamento `Invoice.lines` vs `JCLBilledSlice` (3 soluzioni candidate, raccomandato pattern B = visibilità UI senza riarchitettura)
- **F27**: bookings 0 done + JCL `billing_status='paid'` → semantica fuorviante. Distinguere billing_status da execution_status.
- **F28**: mismatch slice billed_amount vs Invoice.subtotal quando emit usa line manuale invece di derivare dalle slice. Investigare flow batch → invoice.

**File toccati**:
- `app/routers/finance.py` (endpoint `project-billing-summary` + import `case`)
- `app/templates/pages/finance.html` (card riepilogo + `pbsToggle` + `pbsLoad`)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md + memory `project_alpha134_findings.md`

## v3.5.0-alpha.133 — i18n GUI base (IT/EN/FR/DE) — switcher topbar (16 mag 2026 notte tarda)

Sistema i18n GUI client-side per supporto multilingua. Lingue iniziali: IT (sorgente), EN, FR, DE. Espandibile via dictionary + `data-i18n` attributes.

**Architettura**

- `app/static/js/i18n.js` (NEW, ~12 KB): dictionary `window.MF_I18N = {key: {it, en, fr, de}}` + `applyI18n()` DOM scanner + `mfSetLang(lang)` switcher + popover handler.
- Persistenza: `localStorage.mf_lang`. Default `'it'`. Fallback per key mancante: `it` → key letterale.
- Markup: `data-i18n="key"` su elementi da tradurre. Opzionalmente `data-i18n-attr="placeholder|title|aria-label"` per attributi invece di textContent.
- I18n preserva figli (es. `<span class="nav-icon">` interno a nav link): modifica solo il primo text node trovato. Fallback `textContent` se nessun text node esiste.

**Switcher topbar**

Nuovo bottone bandiera 🇮🇹/🇬🇧/🇫🇷/🇩🇪 (current lang) accanto a theme picker + bell. Click → popover sticky toggle con 4 celle (flag + nome lingua). Selezione cella → `mfSetLang` + applyI18n + toast + close popover. Click outside chiude. Pattern identico a F4 theme picker (α.121).

**CSS**: `.topbar-lang-wrap`, `.topbar-lang-pop`, `.tl-cell`, `.tl-flag`, `.tl-lbl` in `main.css`.

**Scope α.133**

Subset stringhe tradotte (~50 chiavi): sidebar nav (sezioni + voci) + topbar (theme, notifications, logout, language) + login page (title, email, password, submit, invalid).

Resto della UI continua in italiano (hardcoded nei template). Espansione futura: marcare con `data-i18n` + aggiungere chiave al dictionary.

**Cache buster**: bump `?v=3.5.0-alpha.133` su `global.js`, `main.css`, `i18n.js`.

**Smoke**:
- `/static/js/i18n.js` servito (12 KB, HTTP 200)
- Dashboard render: 37 elementi con `data-i18n` (sidebar + topbar)
- Switcher topbar presente
- Script tag i18n.js incluso in base.html + login.html

**Backlog α.134+**:
- Estensione i18n: dashboard, login messaggi server-side, copilot prompt
- Server-side i18n per messaggi error/toast da backend (oggi sono in italiano hardcoded)
- Date/numeri locale-aware (Intl API)
- Parse batch UI capitolati
- OAuth integrazioni vere

**File toccati**:
- `app/static/js/i18n.js` (NEW: dictionary + switcher + DOM scanner)
- `app/static/css/main.css` (CSS popover lingua + cache buster bump)
- `app/templates/base.html` (sidebar nav data-i18n + topbar lang switcher + script tag + cache buster)
- `app/templates/pages/login.html` (data-i18n form auth)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.132 — DeliveryTemplate export JSON + duplica (16 mag 2026 notte tarda)

QoL su `/delivery-templates`: 2 nuove operazioni per ogni template salvato.

**`GET /delivery-templates/api/{id}/export-json`**

Scarica template come JSON file (8 blocchi + metadata). Use case: backup, share con altre installazioni MediaFlow, audit human-readable, importazione manuale altrove. Content-Disposition `attachment; filename="{code}.json"`. JSON indented + ensure_ascii=False per leggibilità caratteri italiani.

**`POST /delivery-templates/api/{id}/duplicate`** (RequireEditSettings)

Duplica template esistente come nuova bozza modificabile. Comportamento:
- Deepcopy degli 8 blocchi JSON + suggested_items
- `code += '-copy'`, `name += ' (copia)'`
- `ai_generated=False`, `ai_confidence=None`, `source_document_name=None` (è manipolazione manuale, non più collegato al doc sorgente)
- `is_active=True`

Use case: partire da un template AI-generated, ritoccarlo per esigenze specifiche cliente senza intaccare l'originale.

**UI nella tabella template**

Aggiunti 2 bottoni accanto a `👁` (detail) e `🗑` (cestina):
- `⬇` link a `/api/{id}/export-json` (download diretto)
- `📋` chiama `duplicateTemplate(id, code)` con conferma + reload page

Handler JS `duplicateTemplate(tid, code)`: confirm → POST duplicate → toast con nuovo code+id → reload.

**Smoke**: endpoint 404 corretti per template inesistente. Routes count `/delivery-templates/api/{template_id}/duplicate` e `/export-json` registrate.

**Backlog α.133+**:
- Parse batch UI 1-by-1 (manual da utente)
- OAuth Gmail/Outlook + Drive/OneDrive
- Automazione portali consegne

**File toccati**:
- `app/routers/delivery_templates.py` (endpoint export-json + duplicate)
- `app/templates/pages/delivery_templates.html` (bottoni ⬇📋 + `duplicateTemplate`)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.131 — Fase 5 corpus diagnostica capitolati + parse on-demand (16 mag 2026 notte tarda)

Diagnostica corpus capitolati con UI tabella status + bottone parse on-demand per ogni capitolato. Permette di vedere a colpo d'occhio quali capitolati del corpus sono già parsati come `DeliveryTemplate` e quali no.

**Endpoint `GET /delivery-templates/api/samples-status`**

Report status corpus capitolati. Per ogni file in `docs/capitolati_esempio/` (extension whitelist + size > 0):
- `filename`, `size`, `size_human`, `ext`
- `parsed`: bool (match per `DeliveryTemplate.source_document_name` case-insensitive)
- `template_id`, `template_name`, `template_broadcaster` (se parsato)

Stats aggregato: `{total, parsed, pending}`.

**UI tabella corpus in `/delivery-templates`**

Card "📚 Corpus capitolati di riferimento" sotto la tabella template attivi. 6 colonne:
- File (mono, truncate 55 char + tooltip)
- Size (human-readable)
- Ext (.pdf/.docx/.xlsx/etc)
- Status (badge ✓ Parsato verde / ⏳ Non parsato muted)
- Template (link al detail se parsato)
- Azione (bottone `✨ Parse` se non ancora parsato)

`dtParseSample(filename)`: chiama `/api/parse-sample` (α.128) + auto-save via `/api/save` (α.95) → toast con AI confidence + reload page. Conferma user prima del run AI (costo 15-40s).

**Smoke**: stats endpoint ritorna 15 sample, 0 parsed, 15 pending (DB demo vuoto di template).

**Backlog α.132+**:
- Esecuzione parse batch (utente runs UI 1-by-1 per controllare AI cost)
- OAuth integrazioni vere (Gmail/Outlook ricezione+reply, Drive/OneDrive)
- Automazione portali consegne

**File toccati**:
- `app/routers/delivery_templates.py` (endpoint `/api/samples-status`)
- `app/templates/pages/delivery_templates.html` (card corpus + `dtLoadSamplesStatus` + `dtParseSample`)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.130 — AI capability propose_send_invoice_email + refactor invoice email helper (16 mag 2026 notte tarda)

Seconda capability AI estesa: invio fattura via email da copilot. Niente OAuth — riusa l'infrastruttura SMTP α.127 (provider-agnostic via .env).

**Refactor invoice email helper**

Estratta la logica SMTP in `app/services/invoice_email.py`:
- `send_invoice_via_smtp(db, invoice_id, recipient_override=None) → dict`
- `InvoiceEmailError(code, message)` exception per error propagation strutturata
- Riusato sia dall'endpoint HTTP `POST /finance/api/invoices/{id}/send-email` (era 70+ righe inline) che dal handler AI capability
- ~100 righe deduplicate, zero regressione: endpoint HTTP riritorna stesso shape `{ok, invoice_id, invoice_number, recipient, subject}`

**AI capability `propose_send_invoice_email`** (mutation, conferma utente Apply):

Args:
- `invoice_id` (preferito)
- `invoice_number` (fallback: lookup per number se ID ignoto)
- `recipient_override` (opzionale: email diverso dall'admin_email cliente)

Pattern uso copilot:
- "Invia fattura 2026-00042 al cliente" → AI invoca `propose_send_invoice_email({invoice_number:'2026-00042'})` → AIAction proposed → user click Apply → send SMTP
- "Manda la NC TD04 a admin@horizon.it" → `{invoice_number:'NC-...', recipient_override:'admin@horizon.it'}`
- Errori SMTP propagati come `ValueError("[503] SMTP non configurato.")` per integration con `apply_action` exception handling.

Tool descriptor in `ai_tools.py` con input_schema completo. Category `mutation` → confirmation flow standard (Apply/Reject card nel drawer copilot).

**Smoke E2E (3 casi)**:

1. Handler senza invoice_id/invoice_number → `ValueError("Manca invoice_id o invoice_number")` ✓
2. Lookup invoice_number 'INVALID-XXX' → `ValueError("Fattura non trovata")` ✓
3. invoice_id valid 113 + no SMTP env → `ValueError("[503] SMTP non configurato")` ✓
4. Endpoint HTTP refactored: stesso shape error 503 ✓

**Capabilities totali ora 33** (era 32 in α.129, +1).

**Backlog α.131+**:
- AI capability email integrazione OAuth (Gmail/Outlook) per ricezione email + reply
- AI capability Drive/OneDrive (OAuth) per upload/download asset
- Automazione portali consegne (per portale)
- Test sistematico 14 capitolati restanti

**File toccati**:
- `app/services/invoice_email.py` (NEW: helper SMTP estratto + InvoiceEmailError)
- `app/services/ai_assistant.py` (handler `_h_propose_send_invoice_email`)
- `app/services/ai_tools.py` (tool descriptor `propose_send_invoice_email`)
- `app/routers/finance.py` (endpoint refactored a usare helper)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.129 — AI capability query_filesystem (asset library locale) (16 mag 2026 notte tarda)

Prima capability AI estesa "filesystem". Permette al copilot AI di leggere file/cartelle in path locali autorizzati (asset library mounted, deposito disco cliente, archivi LTO digitali).

**Capability `query_filesystem`** (readonly, esecuzione immediata):

Argomenti:
- `path` (richiesto): path assoluto da listare
- `glob_pattern` (opzionale): es. `*.mov`, `*.xml`, `dolby_*.xml`
- `max_depth` (default 4, max 8): profondità ricorsione
- `max_results` (default 100, max 500): limite risultati

Risposta: `{count, files: [{name, relative_path, is_dir, size, size_human, mtime, mime_type}], base_path, glob_pattern, truncated}`.

**Sicurezza multi-strato**:

1. **Whitelist tenant-level** (`Tenant.fs_scan_allowed_paths`, JSON list): senza configurazione → reject con istruzioni `/settings → fs-scan-paths`.
2. **Path traversal protection**: `Path.resolve(strict=False)` + `relative_to()` check. Fallback case-insensitive prefix match per Windows (resolve può differire da prefix originale).
3. **Limit hard cap**: max_depth ≤ 8, max_results ≤ 500 per evitare scan invasivi su volumi grandi.
4. **Permission errors silenti**: directory non leggibili skippate senza crash.

**Pattern uso AI**:

User chiede al copilot: "cosa c'è in `/mnt/asset_library/PROJ-2024-0001/`?" → AI invoca `query_filesystem({path:'/mnt/asset_library/PROJ-2024-0001/'})` → ritorna lista deliverable. Filtraggio: "elenca i .mov consegnati" → `glob_pattern: '*.mov'`. Profondità: "cerca .xml in sottocartelle" → `max_depth: 6`.

Tool registrato in `ai_tools.py:TOOLS` con category `readonly`, descrizione esplicita degli use case (asset library, deliverable check). Capability descriptor schema completo (input_schema + handler).

**Smoke E2E**:

1. No whitelist tenant → error "Configura whitelist in /settings → fs-scan-paths" + lista vuota ✓
2. Path autorizzato `docs/capitolati_esempio/` → 15 file listati con metadata ✓
3. Glob `*.pdf` → 6 file PDF filtrati correttamente ✓
4. Path fuori whitelist `C:/Windows` → reject con messaggio + lista vuota ✓

**Helper `_human_size`** (interno): formatta byte in B/KB/MB/GB/TB human-readable.

**Capabilities totali ora 32** (era 31 in α.128, +1).

**Backlog α.130+**:
- AI capability: integrazione email (OAuth Gmail/Outlook) — design provider preliminare
- AI capability: integrazione Drive/OneDrive — OAuth
- Automazione portali consegne (per portale + per cliente)
- Test sistematico 14 capitolati restanti

**File toccati**:
- `app/services/ai_assistant.py` (handler `_h_query_filesystem` + helper `_human_size`)
- `app/services/ai_tools.py` (tool descriptor `query_filesystem` con input_schema)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.128 — Fase 5 capitolati: quick-load esempi nel wizard import (16 mag 2026 notte tarda)

Audit Fase 5 (capitolati F14/F15). Codice scaffolded già presente:
- `app/services/deliverables_parser.py` (287 LOC): parser AI 8 blocchi DeliveryTemplate
- `app/routers/delivery_templates.py` (566 LOC): CRUD + parse + match-listino + create-quote
- `app/templates/pages/capitolati_import.html` (392 LOC): wizard 3-step UI
- 15 capitolati reali (su 17 totali, 2 vuoti) in `docs/capitolati_esempio/`

Smoke E2E parser AI: parse di "A24 Queer Delivery Schedule" (DOCX 2.1MB) → AI confidence 0.88, 8 blocchi popolati correttamente (video_specs 19 keys, audio_specs 10, text_specs 4, head_format 13, textless 10, naming 3 con patterns DCNC e UHD HDR/SDR, archive 11 con LTO7/8, metadata 9 con Dolby Vision XML).

Bundle aggiunte α.128:

**Endpoint `GET /delivery-templates/api/sample-files`**

Lista i capitolati di esempio del repo (`docs/capitolati_esempio/`) filtrati per:
- estensione supportata (.pdf, .docx, .doc, .xlsx, .xls, .txt, .md)
- size > 0 (esclude file vuoti — Netflix + Amazon erano vuoti)
- formato result: `{filename, size, size_human (KB/MB), ext}`
- Ordinato alfabeticamente.

**Endpoint `POST /delivery-templates/api/parse-sample`**

Parse di un capitolato dalla directory esempi senza upload manuale. Param `filename` form. Sicurezza:
- Reject path traversal (`/`, `\\`, `..` nel filename)
- Verifica path resolved è dentro `samples_dir` (no escape)
- 400 se file vuoto, 404 se non esistente, 500 se parser AI fallisce
- Risposta identica a `/api/parse` (8 blocchi DeliveryTemplate)

**Path conflict fix**

`@router.get("/api/{template_id}")` (in get_template) catturava la stringa `"sample-files"` come template_id integer → 422 parsing error. Riordinato: `/api/list` + `/api/sample-files` + `/api/parse-sample` PRIMA di `/api/{template_id}`. Pattern FastAPI standard (specific paths before parameterized).

**UI Wizard `/delivery-templates/import`**

Card nuova "Capitolati di esempio" sotto lo step upload manuale. Pill cliccabili per ognuno dei 15 capitolati disponibili. Click → conferma → `parseCapitolatoSample(filename)` chiama `/api/parse-sample` → riusa flow `showPreview()` per visualizzazione. Truncate nome a 40 char, tooltip con full filename + size.

**Note Fase 5 progressi**:
- F14 (upload → parser → preview → save) era già completo pre-α.128
- F15 (test 17 capitolati): smoke E2E A24 PASS, restanti 14 testabili via quick-load
- Tabella `delivery_templates` ancora vuota nel DB demo: nessun template seedato
- `parse-and-match` (capitolato → matching listino → quote bozza) già funzionante via wizard

**Backlog α.129+**:
- Test sistematico parse dei 15 capitolati restanti
- Seed batch DeliveryTemplate dai capitolati corpus (opzionale, costo AI)
- Capability AI estese (email/Drive/Office OAuth, filesystem Asset Library)

**File toccati**:
- `app/routers/delivery_templates.py` (sample-files + parse-sample + reorder routes)
- `app/templates/pages/capitolati_import.html` (card esempi + ciLoadSamples + parseCapitolatoSample)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.127 — P2.C F11 supplier↔resource flusso inverso + F6 invio email SMTP (16 mag 2026 notte tarda)

Gruppo P2.C del backlog α.120. Chiusura backlog architetturale.

**F11 — Flusso inverso supplier↔resource**

Pre-fix: bottone "+ Crea risorsa" nel modal supplier (α.114 A13) generava una Resource freelance dai dati supplier. Matteo F11: "Mantenere link SOLO con risorse esterne (freelance) e togliere Crea Risorsa. Il meccanismo è inverso: è il fornitore che viene creato dal menu risorsa, non il contrario".

Fix:
- Rimosso `<button id="ms-create-resource-btn">` dal modal supplier.
- Dropdown `#ms-resource` filtra ora SOLO `r.type === 'person_freelance'` (no internal/studio/equipment/etc) — la semantica supplier appartiene a freelance esterni.
- Nuovo endpoint `POST /resources/api/{resource_id}/generate-supplier` (dependencies RequireEditResources):
  - 400 se `r.type != person_freelance` (semantica deny)
  - 200 + `already_linked=true` se `r.supplier_id` valido (idempotente)
  - 200 + `already_linked=false` se nuovo: crea `Supplier(name, contact_email, contact_phone)` pre-popolato da resource + setta `r.supplier_id` bidirezionale + notes "Generato da risorsa freelance #X (name)"
- UI `/resources` modal: nuovo bottone footer `🏢 Genera fornitore collegato` (`#rs-gen-supplier-btn`) visibile solo per resource freelance già salvata (no create mode, no altri tipi). Conferma user prima della creazione.

Smoke E2E:
- POST /resources/api/1/generate-supplier (person_internal Vittorio Bruno) → 400 deny ✓
- POST /resources/api/26/generate-supplier (freelance Francesca Ferrari) → 200, supplier #11 creato con contact_email da resource, resource.supplier_id=11 bidirezionale ✓
- Re-run: already_linked=true ✓

**F6 — Invio fattura via email cliente (SMTP provider-agnostic)**

Pre-fix: campo `Client.admin_email` (α.113 Q3) usato per snapshot intestazione PDF "Att.ne Amministrazione". Matteo F6: "intendevo di usare l'email per inviare direttamente la fattura, e non per l'intestazione". Mantenuta intestazione PDF (legittima); aggiunta funzionalità send via email.

Backend `POST /finance/api/invoices/{id}/send-email` (RequireEditInvoices):
- Risolve destinatario: `client_admin_email_snap > Client.admin_email > Client.contact_email`. 400 se nessuno presente.
- Genera PDF via `generate_invoice_pdf(invoice, tenant, client, project)` (riusa banner project F15 + righe NC aggregate).
- SMTP send via stdlib `smtplib` + `email.message.EmailMessage`. Provider-agnostic, .env config:
  - `SMTP_HOST` (richiesto, 503 se mancante)
  - `SMTP_PORT` (default 587)
  - `SMTP_USER`, `SMTP_PASS` (opzionali per server no-auth)
  - `SMTP_FROM` (default = SMTP_USER)
  - `SMTP_USE_TLS` (default "1" → STARTTLS; "0" → SMTP_SSL diretto su 465)
- Compatibile con qualsiasi provider standard: Gmail (app-pass), Microsoft 365, AWS SES, Mailgun, SendGrid, Postmark, etc.
- Subject: "Fattura {number} — {tenant_name}" (NC se TD04 → "Nota di credito").
- Body plain text con numero, data emissione, cliente, progetto, imponibile, totale IVA inclusa.
- Attachment: PDF formale standard.
- 409 se fattura cancelled, 502 se SMTP fallisce, 503 se non configurato.

UI:
- Lista fatture in /finance#invoices: bottone `✉` accanto a `📥` (solo per fatture non-draft non-cancelled).
- Modal detail F18: bottone `✉ Invia email` accanto a `📥 Scarica PDF` nel footer.
- `sendInvoiceEmail(id)` con confirm + toast risultato (mostra recipient + subject).

Smoke: SMTP non configurato → 503 con messaggio "Imposta SMTP_HOST/PORT/USER/PASS/FROM in .env".

**Backlog P2 — CHIUSO**

24 finding totali raccolti il 16 mag, ora tutti chiusi nei round α.119 → α.127.

Backlog rimanente per α.128+:
- Test UI Matteo dei fix accumulati
- Bug emersi da uso reale

**Side-effect DB test α.127** (informativi):
- Supplier #11 "Francesca Ferrari" creato + linked a Resource #26 (test E2E generate-supplier).

**File toccati**:
- `app/routers/finance.py` (endpoint send-email + import Tenant)
- `app/routers/resources.py` (endpoint generate-supplier)
- `app/templates/pages/finance.html` (bottone ✉ lista + detail modal + sendInvoiceEmail)
- `app/templates/pages/resources.html` (bottone "Genera fornitore" footer modal + rsGenerateSupplierFromResource + toggle in rsToggleCreateUserSection)
- `app/templates/pages/suppliers.html` (rimosso bottone "+ Crea risorsa" + filtro freelance dropdown)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.126 — P2.E revamp /team /resources /departments + filtri (16 mag 2026 notte tardi)

Gruppo P2.E del backlog α.120. Matteo F21: "non mi piace come funziona /team vs /resources. Rendi più chiara la struttura. Elabora impaginazione più chiara fra le tre pagine e metti i filtri per la lista risorse".

**Chiarezza purpose delle 3 pagine**

Titoli topbar aggiornati con sub-title esplicativo:
- `/resources` → "Risorse · Lista" (lista flat tutte le risorse)
- `/team` → "Team · Vista per reparto" (raggruppamento visuale)
- `/departments` → "Reparti · Configurazione"

Banner header esplicativo su /resources e /team (info ribbon indaco) descrive lo scope e linka le altre due pagine. /departments aveva già banner descrittivo invariato.

**Navigazione bidirezionale fra le 3 pagine**

Topbar di ogni pagina ora contiene link alle altre due:
- /resources topbar: `👥 Vista per reparto` + `🗂 Reparti`
- /team topbar: `📋 Lista risorse` + `🗂 Reparti` (testi rinominati da "Lista (legacy)")
- /departments topbar (nuovo): `👥 Team` + `📋 Lista risorse`

**Filtri estesi /resources**

Aggiunti i filtri richiesti:
- **Search live** (`#filter-q`): input testuale, filter client-side della tabella già renderizzata (no reload). Match su tutto il contenuto della riga (nome, ruolo, reparto, contatti). Count aggiornato dinamicamente "X su Y (filtrate da ricerca)".
- **Toggle "Mostra inattive"** (`#filter-inactive`): checkbox che ricarica server-side con param `include_inactive=1`. Pre-popolato dal context.
- Filtri esistenti (reparto, tab tipo) preservati.

**Backend `/resources` GET**

- Nuovo param `include_inactive: int = 0`. Se truthy, filtro `is_active == True` non applicato → mostra anche risorse soft-deleted/disabilitate.
- Template context passa `include_inactive` per pre-popolare checkbox.

**JS refactor**

- `applyFilters()` → client-side filter testuale (no reload, performance).
- `applyFiltersServer()` → reload con querystring (dept + include_inactive). Chiamata da onchange su filter-dept e filter-inactive.

**Backlog P2 rimanente per α.127+**:
- P2.C: F11 supplier↔resource flusso inverso + F6 admin_email SMTP (provider scelto?)

**File toccati**:
- `app/routers/resources.py` (param include_inactive)
- `app/templates/pages/resources.html` (topbar + banner + filter-q + filter-inactive + JS split client/server)
- `app/templates/pages/team.html` (topbar testi + banner purpose)
- `app/templates/pages/departments.html` (topbar bidirezionale)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.125 — P2.A.2 sweep fallback id assets + F19 ratio_net precision (16 mag 2026 notte tardi)

Bundle leggero: chiusura P2.A.2 (audit `#${id}` user-facing residui) + precisione query ratio_net su endpoint by-department.

**P2.A.2 — Fallback descrittivo invece di `#${id}` numerico**

In `/assets/inout` per la lista asset (fisici + digitali), quando l'asset non aveva `label`/`original_name`/`filename`, il fallback era `#${a.id}` (id DB numerico). Sostituito con fallback descrittivo:
- Asset fisici: `a.label || a.serial_number || a.barcode || '(asset senza nome)'`
- Asset digitali: `a.original_name || a.filename || '(file senza nome)'`

`planning.html:5941` (lista booking falliti dopo bulk operation) lascia `#${id}` perché è ID booking necessario per debug/identificazione del record che ha fallito — utile contesto pratico. Skip cosciente.

**F19 — Revenue net query precisa (no più /1.22)**

In `cashflow_by_department`, il `revenue_net` era calcolato `revenue_total / 1.22` (IVA standard 22%). Errato per fatture con vat_rate diverso (es. forfettario esente, IVA ridotta 10%, esportazione 0%).

Fix: espressione SQL `CASE WHEN invoice.total > 0 THEN slice.billed_amount × invoice.subtotal / invoice.total ELSE slice.billed_amount / 1.22 END` aggregata via `SUM`. Calcolo preciso per ogni slice usando il ratio reale dell'invoice associata. Fallback `/1.22` solo per invoice con total=0 (caso degenerato).

Smoke su DB attuale: risultati identici al pre-fix perché tutte le fatture demo hanno vat 22% esatto, ma la query ora è corretta anche per vat diversi. Nessuna regressione.

**Backlog P2 rimanente per α.126+** (gruppi richiedono design discussion):
- P2.C: F11 supplier↔resource flusso inverso + F6 admin_email send SMTP (provider scelto?)
- P2.E: revamp /team /resources /departments (F21)

**File toccati**:
- `app/routers/finance.py` (cashflow_by_department case-when precision)
- `app/templates/pages/assets_inout.html` (fallback label asset fisici + digitali)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.124 — F7a/F7b naming builder: modal centrato + editor inline (16 mag 2026 notte tardi)

Gruppo P2.D del backlog α.120. Refactor builder naming conventions in `/settings#numbering`.

**F7a — Builder modal centrato (no più drawer sinistra)**

- Pre-fix (α.114 A14): drawer fisso a sinistra flush con sidebar (`position:fixed; left:var(--sidebar-w); height:100vh; border-radius:0`). Matteo: "non avevamo detto a destra? Puoi anche metterlo al centro per me in stile pop-up".
- Fix: rimosso CSS `position:fixed`, drawer ora usa CSS default `.modal` (centrato in viewport, max-width 560px, max-height 88vh, border-radius standard). Modal-overlay style standard (no più background rgba(0,0,0,0.45) override).

**F7b — Editor inline + palette click-to-insert (no più drag&drop)**

- Pre-fix: builder con "Blocchi attivi" drag&drop riordinabili + "Variabili disponibili" che spinge alla fine + input separato "Inserisci testo/separatore custom" con bottone "+ Aggiungi". Matteo: "macchinoso il metodo di inserimento dei caratteri aggiuntivi. Forse si poteva digitare direttamente nel riquadro blocchi attivi".
- Fix: input text raw editabile direttamente (`<input id="nmb-pattern-input">`). Click su una variabile della palette la inserisce **nella posizione del cursore** (via `selectionStart/selectionEnd` + setSelectionRange). Preview server `_nmbServerPreview()` debounced (250ms) chiamato a ogni input.
- Palette `nmb-blocks-palette` mantenuta con greys-out per variabili non supportate per doc_type (α.116 — `supported_vars` filter).
- Dead code rimosso: `_nmbBlocks` state, `_nmbTokenize()`, `_nmbRenderBuilder()`, `nmbAddCustom()`, sezione "Blocchi attivi" + "Inserisci testo custom".
- `nmbSaveFromBuilder()` legge ora `nmb-pattern-input.value` invece di `_nmbBlocks.join('')`.

Comportamento utente:
1. Click su una regola → modal centrato si apre con input pre-popolato dal `format_pattern` salvato.
2. Edit raw oppure click variabili → testo inserito al cursore.
3. Preview live mostra il prossimo codice emesso a ogni keystroke.
4. Save invia il pattern raw al backend (validazione `validate_pattern` α.116 + quote progressivo finale α.118 invariata).

**Smoke**:
- `/settings` page: 0 occorrenze `nmb-blocks-active`, 0 di `nmb-custom-text`, 5 di `nmb-pattern-input`, 3 di `nmbOnPatternInput`.
- Boot α.124 OK.

**Backlog P2 rimanente per α.125+**:
- P2.A.2: audit globale fallback `#${id}` user-facing
- P2.C: F11 supplier↔resource inverso + F6 admin_email SMTP send
- P2.E: revamp /team /resources /departments (F21)
- F19 ratio_net precision

**File toccati**:
- `app/templates/pages/settings.html` (markup builder + JS refactor)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.123 — F16 IVA toggle + F19 split cashflow per reparto (16 mag 2026 notte tardi)

Gruppo P2.B del backlog α.120. Implementati F16 (totali fatture+cashflow SENZA IVA di default + toggle) e F19 (breakdown cashflow per Department).

**F16 — Totali fatture/cashflow SENZA IVA di default + toggle Mostra IVA**

Backend `cashflow_year_sync` ora ritorna campi paralleli `*_net` (imponibile) accanto a quelli con IVA inclusa:
- `invoiced_net` = Σ Invoice.subtotal (con segno -1 per NC TD04)
- `paid_net` = Σ InvoicePayment.amount × (subtotal/total) dell'invoice associata (fallback 1/1.22 se invoice non trovata)
- `outstanding_net` = (total − paid) × ratio_net dell'invoice
- `supplier_billed_net` = Σ SupplierInvoice.amount_net
- `supplier_paid_net` = Σ SupplierInvoicePayment.amount × ratio_net del supplier_invoice
- `supplier_due_net` = residuo × ratio_net
- `net_cashflow_net` = paid_net − supplier_paid_net − overhead_paid − capex_paid

UI cashflow: nuovo toggle "Mostra IVA" in topbar filtri, persistente in `localStorage.mf_cf_show_vat`. Default OFF → mostra imponibile. Se OFF, `months` vengono sovrascritti coi valori `_net` prima del render (chart + tabella + stat cards). Coerenza garantita: nessuna funzione downstream vede valori con IVA quando toggle è OFF.

**F19 — Split cashflow per reparto**

Nuovo endpoint `GET /finance/api/cashflow/{year}/by-department` che aggrega annuale per Department:
- **Revenue side**: Invoice → JCLBilledSlice → JobCostLine → PriceItem.department_id. Considera solo slice non voided (post-storno NC) di fatture non draft.
- **Cost side**: SupplierInvoice → Resource → Resource.department_id. Esclude cancelled/deleted.
- **Margine**: revenue − supplier per department.
- **`_net` ratio**: per α.123 approssimato a `total / 1.22` (IVA standard). Calcolo preciso ratio per ogni invoice richiede join supplementare costoso, rinviato a α.124+.

UI cashflow: nuovo card "Split per reparto (anno)" sotto il chart timeline, prima del dettaglio mensile. Tabella con 5 colonne (Reparto, Revenue, Outflow fornitori, Margine, % margine). Riga TOTALE finale con bordo top spesso. Margine colorato verde/rosso secondo segno. `loadDeptBreakdown(year, showVat)` chiamata da `loadCashflow()` parallel al chart, riusa il toggle IVA per scegliere campi.

**Smoke E2E**:
- `/finance/api/cashflow/2026` con `_net` fields: invoiced 254911 → net 208943, paid 342621 → net 280837, supplier_paid 10663 → net 8741, net_cashflow 331957 → net_cashflow_net 272096. Ratio coerente (~82%).
- `/finance/api/cashflow/2026/by-department`: 4 reparti ordinati per revenue_net desc. Audio €16'892 net rev (con €1'898 outflow), VFX €9'883, DI/Video €8'112, Commercial €2'199. Margine coerente con ratio applicato.

**Backlog P2 rimanente per α.124+**:
- P2.A.2: audit globale fallback `#${id}` user-facing
- P2.C: F11 supplier↔resource flusso inverso + F6 admin_email send SMTP (richiede design provider scelto)
- P2.D: naming drawer (F7a center popup, F7b inserimento blocchi inline)
- P2.E: revamp /team /resources /departments (F21)
- F19 precision ratio_net: join per invoice/supplier-invoice per calcolare ratio_net esatto invece di /1.22

**File toccati**:
- `app/routers/finance.py` (cashflow_year_sync `_net` fields + nuovo endpoint by-department + import current_tenant_id)
- `app/templates/pages/cashflow.html` (toggle IVA + card dept breakdown + loadDeptBreakdown)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.122 — F17/F24 sweep terminologia JCL→Lavorazione + nascondi id interni (16 mag 2026 notte)

Primo step del backlog P2 architetturale (gruppo A "Visualizzazione globale" da α.120 backlog). Focus su sweep terminologia e codici DB visibili user. Sweep parziale sui punti più impattanti — F24/F9 audit globale completo richiede passi successivi (P2.A.2).

**F17 — Terminologia "JCL" → "Lavorazione" UI globale (parziale)**

Audit `app/templates/`: 64 occorrenze di "JCL", "jcl_id", "JobCostLine" in 8 template, la maggior parte in commenti JS o param interni. User-facing visibili rinominati:

- `assets_inout.html`: header tabella `<th>JCL</th>` → `<th>Lavorazione</th>`
- `cost_report.html`: tooltip "Σ JCL.total_accrued" → "Σ lavorazioni maturate"
- `manuale.html`: passaggio narrativo "JCL Spedizione standard" → "Lavorazione Spedizione standard" (2 occorrenze stesso paragrafo)
- `quotes.html`: badge `↪ Da JCL #X` → `↪ Da lavorazione` (F24: id numerico DB rimosso). Toast errore "JCL #X senza job" → "Lavorazione senza job"

Convenzione confermata: "Lavorazione" è il termine UI italiano canonico per JobCostLine. "Voce di costo" rimane sinonimo accettabile (usato già in suppliers.html label α.121). Commenti JS interni mantengono "JCL" per brevità (no user-facing).

**F24/F9 — Sweep codici DB visibili (parziale)**

Rimosso `#${id}` numerico interno DB dai punti più visibili (badges, toast). Resta auditing globale per fallback id (es. `#${asset.id}` quando label è null, planning fallback `#${f.id}`) — sono fallback "graceful degrade" e probabilmente accettabili come internal ref. Decisione definitiva su questi rinviata a P2.A.2.

**Backlog P2 rimanente per α.123+**:
- P2.A.2: audit globale ID interni visibili (fallback `#${id}` in assets_inout, planning)
- P2.B: cashflow architettura (F16 IVA default off + toggle, F19 split reparti)
- P2.C: flusso resource/supplier (F11 inverse, F6 admin_email send + SMTP)
- P2.D: naming drawer (F7a center popup, F7b inserimento blocchi inline)
- P2.E: revamp /team /resources /departments (F21)

**File toccati**:
- `app/templates/pages/assets_inout.html`
- `app/templates/pages/cost_report.html`
- `app/templates/pages/manuale.html`
- `app/templates/pages/quotes.html`
- `app/main.py`
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.121 — 7 fix UX P1 da backlog α.120 (16 mag 2026 tarda notte)

Round P1 dal backlog α.120 (24 finding totali). Chiusi 7 dei 8 P1 UX bug:
F4 + F5 + F7c + F8 + F18 + F20 + F10/F23. Restano P2 architetturali per
α.122+ (10 finding: F6, F7a, F7b, F11, F16, F17, F19, F21, F24/F9 +
discussion). B5 (chip drift sempre visibile) verificato già funzionante,
no actionable change.

**F4 — Palette tema sticky toggle (no hover)**
- Pre-fix: popover swatches apriva su mouseenter del wrapper e si chiudeva
  immediatamente su mouseleave. Forzava click rapidissimo per selezionare.
- Fix: rimossa regola CSS `.topbar-theme-wrap:hover` e `:focus-within`.
  Aggiunta classe `.is-open` togglata via JS `topbarThemeToggleOpen(event)`.
  Click outside chiude (one-shot document listener). Selezione tema da
  cella chiude pure (setTheme + remove classe).
- onclick handler aggiornato in base.html da `topbarThemeCycle()` a
  `topbarThemeToggleOpen(event)`. Title aggiornato "Apri palette tema".
- Cache-buster bump `?v=3.5.0-alpha.121` per global.js + main.css.

**F5 — Chip filtro cliente in /projects?client_id=N**
- Pre-fix: filtro applicato (lista filtrata) ma riquadro filtri non
  mostrava chiaramente che il filtro cliente era attivo. La select
  `#filter-client` settava `sel.value = clientFilter` ma visivamente
  non risaltava — utente non capiva.
- Fix: aggiunta `<span id="filter-client-chip">` accanto alla select.
  Quando filtro attivo via querystring, JS popola label "Cliente: <nome>"
  + link × a `/projects` per rimuovere filtro. Visivamente pill indaco
  pronunciata. Display none di default; inline-flex quando attivo.

**F7c — Naming pattern attivo riflesso UI Quotes**
- Pre-fix: modal "Nuova quotazione" placeholder hardcoded "Q-2025-0001-v1"
  senza riferimento al pattern realmente configurato in /settings#numbering.
- Fix: wrapper `openNewQuoteModal()` chiama `POST /settings/api/numbering/
  quote/preview`, popola hint `#nq-number-hint` con "Pattern attivo: <fmt>
  (esempio: <preview>)". Silente in caso errore. Bottone "+ Nuova
  quotazione" cambiato da `onclick="openModal('modal-new-quote')"` a
  `onclick="openNewQuoteModal()"`.
- Limite scope: solo /quotes per α.121. Estensione ad altri modal (jobs,
  fatture, batch, ddt, overhead) in round successivo.

**F8 — Overhead write-off mismatch lista vs drawer**
- Pre-fix: card "Write-off (LossEntry)" mostrava total > 0 (es. €33'895)
  da `s.write_off_total`. Cliccando per drawer detail: "0 voci · Nessuna
  voce nella categoria nel periodo". Root cause: drawer filtrava
  `_ohList.filter(o => o.category === cat)` su OverheadCost, ma write-off
  vive in LossEntry (single source of truth), non in OverheadCost.
- Fix backend: nuovo endpoint `GET /overhead/api/losses` ritorna LossEntry
  del tenant in formato compatibile UI drawer (code=LOSS-id, title,
  cost_date, amount_net/total, category='write_off', _is_loss=true).
  Filtri opzionali from_date/to_date.
- Fix UI: branch in `ohOpenCategoryDetail()` per `cat === 'write_off'`
  che fetcha l'endpoint dedicato invece di filtrare la lista OverheadCost.

**F18 — Lista fatture: detail on click + hide select status se terminale**
- Pre-fix: lista finance#invoices senza drilldown drawer. Drillanto solo
  via PDF. Select cambio stato sempre presente, anche per fatture paid o
  cancelled (entrambi stati terminal). Cambio status che falliva con 409
  visibile solo come toast errore tardivo.
- Fix backend: nuovo `GET /finance/api/invoices/{id}` ritorna detail
  invoice + lines + payments + allowed_transitions + is_terminal flag.
  Allowed transitions calcolati da state machine (mirror update_status):
  draft→sent/cancelled, sent→paid/overdue/cancelled, overdue→paid/
  cancelled, paid+cancelled→[] terminal.
- Fix UI:
  - Row click apre modal con righe + meta (cliente, progetto, totali,
    payments). DOM API (no innerHTML user-injected) per evitare XSS.
  - Select cambio stato hide se status terminal (mostra "—" col tooltip
    "Stato terminale: nessuna transizione consentita"). Allowed
    transitions inserite dinamicamente come opzioni.
  - Bottone PDF disabled se cancelled (già fixato in F14 α.120).
  - Bottone storno hide se cancelled.

**F20 — Componi fattura: tasto aggrega batch sparisce dopo close popup**
- Pre-fix: aggregazione N batch → 1 fattura era accessibile solo dal
  modal compose-invoice top-level. Da batch detail (single batch),
  l'utente non vedeva opzione "aggrega con altri batch dello stesso
  progetto" anche se i batch composable erano > 1.
- Fix: in `openBatchDetail()` aggiunto fetch `composable-batches` per
  contare quanti batch approvati del progetto sono in cassetto. Salvato
  in `b._composableCount`. In `renderBatchFooter()`, per status='approved'
  e composableCount > 1, aggiunto bottone "🔗 Aggrega con altri batch
  (N composable)" che apre `openComposeInvoiceModalForProject(pid)` —
  wrapper che pre-popola compose-invoice col progetto del batch corrente.

**F10/F23 — Fattura passiva: dropdown Lavorazione (JCL) cascata**
- Pre-fix: modal nuova/edit fattura passiva aveva cascata Project→Job ma
  senza link JCL. cost_external veniva attribuito a tutte le JCL del job
  con resource matching (anche con priority ranking α.119, era distribuzione
  pro-quota, meno preciso del link diretto).
- Fix UI:
  - Nuovo dropdown `#mi-jcl` "Lavorazione" sotto la riga Project/Job in
    modal supplier invoice. Hint esplicito: "Selezionando una lavorazione,
    la fattura passiva sarà attribuita esclusivamente a quella riga del
    cost report. Lasciando vuoto, l'importo viene distribuito pro-quota."
  - `_populateJclSelect()` async: fetch `GET /cost-report/api/job/{id}`
    e popola con cost_lines del job selezionato (description + qty + unit).
  - Cascata: `_populateJobSelect().onchange` triggera populate JCL +
    populate resource.
  - `editInvoice(id)` ora async: pre-popola JCL select da `i.job_cost_line_id`.
  - `saveInvoice()`: append `job_cost_line_id` al FormData se valued.
- Smoke endpoint backend: GET `/finance/api/invoices/113` ritorna lines
  + allowed_transitions OK, GET `/overhead/api/losses` ritorna 458+ LossEntry.

**Architettura — backlog rimanente**: 10 finding P2 architetturali
preservati per α.122+ (design discussion: F6 admin_email send semantica,
F7a drawer center popup, F7b inserimento blocchi inline, F11 supplier↔
resource flusso inverso, F16 IVA default off, F17 terminologia JCL→
lavorazione globale, F19 cashflow split reparti, F21 UX revamp team/
resources/departments, F24/F9 sweep codici DB).

**File toccati**:
- `app/routers/finance.py` (F18 endpoint dettaglio invoice)
- `app/routers/overhead.py` (F8 endpoint losses)
- `app/templates/pages/finance.html` (F18 row click + status select hide + batch detail F20 aggrega)
- `app/templates/pages/projects.html` (F5 chip filtro cliente)
- `app/templates/pages/quotes.html` (F7c openNewQuoteModal con preview pattern)
- `app/templates/pages/overhead.html` (F8 branch write_off in drawer)
- `app/templates/pages/suppliers.html` (F10/F23 dropdown JCL cascata)
- `app/templates/base.html` (F4 onclick + cache-buster v=alpha.121)
- `app/static/js/global.js` (F4 topbarThemeToggleOpen + cell click close)
- `app/static/css/main.css` (F4 sticky .is-open vs hover)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.120 — 6 fix bloccanti P0 da checklist post-audit α.114-118 (16 mag 2026 tarda sera)

Sessione test UI Matteo completa (60+ punti). 24 finding raccolti, classificati P0/P1/P2. Questo round chiude i 6 bloccanti P0. P1 (8 UX bug) → α.121. P2 (10 architetturali, design discussion) → α.122+.

**F3 — CR lista mostra valori falsi al primo render**
- Sintomo: lista cost report apre con maturato/fatturato palesemente sbagliati. Solo aprire detail + back rinfresca i valori. Esempio Voice of Tide Ep. 3: pre-apertura maturato €117'690, post-apertura €2'875 (drift −98%).
- Root cause: `POST /cost-report/api/reconcile-all` filtrava `accrued_stale==True`. Le JCL mai flagged stale (modifiche pre-α.115, path indiretti, drift propagation) restavano stale all'infinito. Il poll background detectava `stale_count=0` e NON triggera refresh lista.
- Fix backend: param `force=1` aggiunto a reconcile-all. Ricomputa tutte le JCL dei Job in stato attivo (active/approved/draft/completed), escludendo cancelled/archived per non degradare su 80k JCL storici.
- Fix frontend: al primo sync della sessione (`window._crFirstSyncDone` flag) usa `force=1`. Sync successivi restano lazy. Refresh lista incondizionato dopo reconcile, anche se `stale_count=0`.
- Smoke: force=1 su DB di test → 350 su 484 JCL aggiornate (= 72% erano stale). Voice of Tide Ep. 3 lista pre-render ora corretto.

**F12 — Cashflow NC TD04 ignorata**
- Sintomo: emit fattura gennaio, storno NC marzo → cashflow segna ancora invoiced gen + outstanding ancora aperto. Saldo annuale errato.
- Root cause: `storno_invoice` creava la NC con `status=draft`. `cashflow_year_sync` filtra `status != draft` → NC mai conteggiata come storno.
- Fix: NC TD04 nasce `status=sent` (è uno strumento contabile ufficiale, mai bozza). Cashflow vede correttamente il segno negativo nel mese di emissione NC.

**F13 — Cashflow non aggiorna outstanding dopo cambio status sent → paid**
- Sintomo: cambio status fattura via dropdown UI non riflette il pagamento nel cashflow (outstanding resta aperto).
- Root cause: `update_invoice_status` cambiava solo `Invoice.status` senza toccare `amount_paid`. Il cashflow calcola `outstanding = total - amount_paid` con guard `status != paid`, ma se `amount_paid=0` il guard non basta a evitare l'inflazione su altre query.
- Fix: in `update_invoice_status`, quando si passa a `paid` senza payment record esplicito, auto-imposta `amount_paid = total`. Idempotente: se l'utente registra InvoicePayment in seguito, il recalc sovrascrive.

**F14 — PDF fattura cancelled stampabile (regola sbagliata)**
- Sintomo: una fattura `cancelled` (es. post-storno NC) era stampabile via lista finance.
- Fix backend: entrambi gli endpoint `/finance/api/invoices/{id}/pdf` e `/finance/api/billing/invoice/{id}/pdf` ritornano 409 con messaggio esplicito se status=cancelled.
- Fix UI: in `finance.html` riga 1196, bottone `📥` PDF mostrato disabled (opacity 0.4, cursor:not-allowed) con tooltip "Fattura annullata: non stampabile" quando `i.status === 'cancelled'`.

**F15 — PDF NC mancava intestazione progetto + duplicava voci con [Storno]**
- Sintomo (Matteo): "la nota di credito riporta tutte le voci di quotazione sul progetto con [Storno], ma non c'è informazione sul nome progetto".
- Fix 1: `invoice_pdf.py` accetta nuovo param `project=None`. Banner "PROGETTO: <code> · <title>" stampato dopo il box destinatario per qualsiasi tipo di fattura quando il progetto è collegato (via `invoice.job.project`).
- Fix 2: per `doc_type=TD04` le righe vengono aggregate in UNA sola "Storno integrale fattura X del Y" + totale netto + IVA per aliquota. Estrazione del riferimento source via regex su `invoice.notes` (pattern α.111 storno_invoice).
- Caller: `billing.py:_invoice_pdf_response` prefetcha project da invoice.job_id → invoice.job.project e lo passa al generator.

**F22 — Resource.supplier_id delink non funziona via PUT form vuoto**
- Sintomo: cambio risorsa nel modal supplier non scollega la risorsa precedente. Pattern frontend `PUT /resources/api/{prev}` con `supplier_id=''` veniva silently ignorato.
- Root cause: `supplier_id: Optional[int] = Form(None)` convertiva la stringa vuota a None. Il check `if supplier_id is not None` saltava → resource resta linked.
- Fix: `request: Request` come dependency + `await request.form()` raw. Check `"supplier_id" in form` distingue "key non passata" da "key vuota". Comportamento:
  - missing → no change
  - '' → clear esplicito (set NULL)
  - 'N' → set int (validazione 400 se non parseable)
  - tenant scope su FK supplier (400 se cross-tenant)
- Smoke E2E: tutti 5 casi pass (clear, set, unchanged, invalid, tenant scope).

**Architettura — finding accumulati α.120 backlog**: 24 finding (F3-F24 + B5 nota) salvati in memoria progetto. P1 da affrontare in α.121 (8 UX bug). P2 in α.122+ (10 architetturali, richiedono design discussion: F6 admin_email semantica, F16 IVA default, F17 terminologia "lavorazione", F21 UX team/resources/departments, F24 sweep visualizzazione codici DB).

**File toccati**:
- `app/routers/resources.py` (F22)
- `app/routers/finance.py` (F13 + F14 parte 1)
- `app/routers/billing.py` (F12 + F14 parte 2 + F15 prefetch project)
- `app/routers/cost_report.py` (F3 backend `force=1`)
- `app/services/invoice_pdf.py` (F15 project banner + NC aggregata)
- `app/templates/pages/cost_report.html` (F3 frontend force first sync)
- `app/templates/pages/finance.html` (F14 UI hide bottone)
- `app/main.py` (version bump)
- CHANGELOG.md + docs/STATO.md

## v3.5.0-alpha.119 — Cost_external priority ranking + auto-dismiss drift self-healed (16 mag 2026)

Smoke E2E server-side post-α.118 ha individuato 2 finding sui meccanismi α.115–α.117 (Q11 cost_external + cost_drift detector). Entrambi risolti in questo round.

**Finding 1 — Double-count `total_cost_external` su JCL multiple dello stesso job**

- Pre-fix: `cost_line_sync._recompute_actuals_for` filtrava le SupplierInvoice in OR-soup `(jcl OR job OR project)`. Una fattura passiva linkata esplicitamente a una JCL veniva sommata anche su tutte le altre JCL dello stesso job che avessero resource matching → cost_external job-level raddoppiato/triplicato. Aggravato dal cost_drift detector che emetteva una anomaly per ciascuna JCL contaminata invece di una sola.
- Fix: priority ranking con esclusività.
  - Livello 1 (jcl): `SupplierInvoice.job_cost_line_id IS NOT NULL` → attribuita esclusivamente a quella JCL.
  - Livello 2 (job): solo `job_id` → distribuita pro-quota su JCL del job con resource_id matching.
  - Livello 3 (project): solo `project_id` → distribuita pro-quota su JCL del progetto con resource_id matching.
- Garanzia: la somma dei contributi su tutte le JCL del job/project resta sempre = total fattura. Nessun double-count.
- Helper interno `_count_jcl_matching_resources()` calcola il denominatore della pro-quota.

**Finding 2 — Auto-dismiss anomalie `cost_estimate_vs_real_drift` self-healed**

- Pre-fix: il detector emetteva nuove entry idempotenti (via `dedup_key`) ma non chiudeva mai quelle vecchie. Se la causa veniva rimossa (fattura cestinata, drift rientrato sotto soglia 15%), le entry restavano `status=open` come zombie finché l'operatore non le gestiva manualmente.
- Fix: `detect_cost_estimate_vs_real_drift` ora marca le entry open NON ri-emesse in questo round come `status=dismissed` + `handled_action=auto_resolved` + nota "[auto-resolved alpha.119]". Idempotente: re-run non riapre.
- Nuovo enum: `AnomalyAction.auto_resolved` (per distinguere chiusure detector vs azioni operatore).
- Pattern resta stateful per gli altri 5 tipi: nessuna self-resolution per `sforamento_monte_ore`, `over_budget`, `mancato_recupero`, `quote_discrepancy`, `extra_after_billed` (azione manager sempre richiesta).

**Smoke E2E post-fix**:

1. Crea SupplierInvoice linked a JCL 422 (job 37, resource Paola Fontana).
2. Reconcile-actuals job 37: JCL 422 ext = €12'200 (= €10'000 + IVA 22%), JCL 425 (extra stesso job) ext = €0. **No double-count.**
3. Detect: `cost_estimate_vs_real_drift = 1` (era 2 in α.118).
4. Entry zombie JCL 425 (residuo del test α.118): auto-dismissed `auto_resolved`.
5. Delete SupplierInvoice + re-detect: drift=0, entry JCL 422 auto-dismissed `auto_resolved`.

**File toccati**:
- `app/services/cost_line_sync.py` — priority ranking + helper `_count_jcl_matching_resources`.
- `app/services/anomaly_detector.py` — auto-dismiss block in `detect_cost_estimate_vs_real_drift`.
- `app/models/models.py` — `AnomalyAction.auto_resolved` aggiunto.

## v3.5.0-alpha.118 — Audit M-finding chiusi: delete supplier hook + preview placeholder + quote pattern guard (15 mag 2026 tardi notte)

**Delete SupplierInvoice → recompute cost_external**:
- `delete_supplier_invoice` non triggerava `_mark_jcl_stale_for_supplier_invoice`.
  Risultato: dopo soft-delete della fattura passiva, JCL.total_cost_external
  restava col valore sporco (sommava ancora la fattura cestinata).
- Fix: snapshot link prima del soft-delete, trigger recompute usando stub
  SimpleNamespace. La query cost_external filtra `deleted_at.is_(None)`
  quindi dopo recompute il valore si riduce correttamente.

**Audit M3 — Preview placeholder fake**:
- Pre-fix: `/settings/api/numbering/{doc_type}/preview` sostituiva
  PROJECT_CODE/CLIENT_CODE mancanti con literal "PRJCODE"/"CLI" senza
  segnalazione → user pensava fosse parte del format.
- Fix: placeholder ora `«PROJ»`/`«CLI»` con guillemets per visivo. Response
  include `uses_placeholder: bool` + `placeholder_note` esplicita.
- UI builder: nota italic sotto preview "I valori «PROJ»/«CLI» sono
  placeholder esempio: al momento della creazione del documento saranno
  sostituiti dai codici reali progetto/cliente.".

**Audit M4 — Quote pattern guard versioning**:
- Pre-fix: `next_progressive_code` parsa tail `rsplit("-",1)[1]` per skip
  `-v2`/`-v3` suffix. Format custom es. `Q-{PROJECT_CODE}` (no NNN finale)
  → ValueError → fallback n=1 → tutte le quote nuove con `Q-MEDUSA-001`.
- Fix: backend validate_pattern rifiuta 400 se doc_type="quote" e pattern
  NON termina con `{NNN}`/`{NN}`/`{NNNN}`. Errore esplicito.
- Esempio valido: `Q-{PROJECT_CODE}-{YYYY}-{NNN}`. Non valido:
  `Q-{PROJECT_CODE}` o `{YYYY}-Q-{PROJECT_CODE}`.

## v3.5.0-alpha.117 — Anomaly cost_drift + UI background reconcile (15 mag 2026 tarda notte)

Chiusi gli ultimi 2 pendenti roadmap.

**Anomaly cost_estimate_vs_real_drift**:
- Nuovo `AnomalyType.cost_estimate_vs_real_drift` (6° tipo, prima 5).
- Detector `detect_cost_estimate_vs_real_drift(threshold_pct=15.0)`:
  - Filtra JCL con `total_cost_external > 0` (esistono fatture passive
    linkate via SupplierInvoice.resource_id).
  - Calcola drift_pct = |external − accrued| / max(accrued, external).
  - Se drift >= threshold → emit anomaly con descrizione esplicita
    "stimato €X vs reale €Y (+€Z, W% off)".
- Integrato in `detect_all()` (incluso in scan periodic + manuale).
- UI finance#anomalies:
  - Nuovo chip filtro "⚖ Drift costo"
  - Label `TYPE_LBL.cost_estimate_vs_real_drift = '⚖ Drift costo'`
  - Color `#f59e0b` (giallo, severity media)
  - Voce in summary "Drift costo (Q11)"

Esempio: JCL "Color 5gg" — booking Marco rate €50/h × 40h = €2000 stimato.
Marco fattura €2500. Drift 25% → anomaly emessa. Producer rivede rate o
chiede sconto. Manager passa azione: `rivaluta_producer` (rivedi rate)
o `write_off_loss` (assorbi delta).

**UI background reconcile (Strategy C)**:
- `loadCrList()` ora trigger `_crStartBackgroundSync()` non-blocking.
  Page load CR immediato con valori stored (anche stale).
- Background polling `/api/reconcile-status` ogni 2 sec finché
  stale_count > 0.
- UI indicator fixed top-right: "🔄 Sincronizzazione cost report (N righe)"
  con spinner animato (CSS @keyframes inject lazy).
- Auto-refresh lista quando stale=0 (solo se utente è ancora in vista
  lista, no se ha aperto dettaglio).
- Strategy A (dirty flag α.115) + Strategy C (UI async) combinati =
  no più freeze stress DB. Page load <100ms, sync visibile in
  background.

Auto-migrate al boot: nessuna (solo enum value Python aggiunto).

## v3.5.0-alpha.116 — NumberingConfig cabling completato (Job/OverheadCost/IngestBatch/DDT) + UI vars validation (15 mag 2026 notte)

Completato il cabling NumberingConfig per tutti i 4 generator residui +
validation lato server e UI greying-out variabili non supportate.

**Nuovi doc_type supportati**:
- `overhead_cost` — Spese aziendali (default OH-{YYYY}-{NNNN})
- `ingest_batch` — Batch ingest fisico (default BATCH-{YYYY}-{NNN})
- `ddt` — DDT spedizione (default DDT-{YYYY}-{NNN})
- `job` — già supportato in α.115, ora wired

Aggiunti a `NUMBERING_DOC_TYPES` (UI /settings#numbering) + a
`_DOC_VARS_SUPPORTED` / `_DOC_DEFAULTS` in `numbering.py`.

**Cabling per generator**:
- `_next_job_code` (quotes.py): prova `gen_doc_code("job")`, fallback
  al while-loop legacy su collision con job esistente.
- `_next_code` (overhead.py): prova `gen_doc_code("overhead_cost")`,
  fallback order_by id desc legacy se config assente/collision.
- `_next_batch_code` (physical_assets.py): prova `gen_doc_code("ingest_batch")`,
  fallback BATCH-YYYY-NNN legacy.
- `_next_ddt_number` (physical_assets.py): prova `gen_doc_code("ddt")`,
  fallback DDT-YYYY-NNN legacy.

**Variabili supportate per doc_type**:
- `overhead_cost`: solo date+seq (no project/client)
- `ingest_batch` / `ddt`: date+seq+PROJECT_CODE
- `job`: date+seq+PROJECT_CODE (sempre disponibile)

**UI validation**:
- `/settings/api/numbering` ritorna ora `supported_vars` per ogni doc_type.
- Builder drag&drop: variabili non supportate per il doc_type aperto
  vengono mostrate **greyed-out + disabled + tooltip esplicativo**.
- `PUT /settings/api/numbering/{doc_type}`: backend valida pattern via
  `validate_pattern()`. Rifiuta 400 con messaggio chiaro se variabile
  fuori supportate (es. `{PROJECT_CODE}` in pattern di `overhead_cost`).

**Pattern collision safety**:
- Tutti i generator verificano uniqueness pre-INSERT. Se NumberingConfig
  produce un codice già usato, fallback automatico a logica legacy. Zero
  rischio crash da config mal configurata.

## v3.5.0-alpha.115 — Q11 cost-side + NumberingConfig cabling + reconcile-all perf (15 mag 2026 notte)

3 punti pesanti dall'audit deep-dive.

**Q11 — Cost-side aggregation (vista stimato vs reale)**:
- Nuovo `JobCostLine.total_cost_external` = Σ SupplierInvoice.amount_total
  delle fatture passive linkate a risorse con booking sulla JCL.
- Match scope: SupplierInvoice deve essere linkata a (jcl O job O project)
  E avere `resource_id` ∈ risorse dei booking della JCL.
- Recompute hook in `cost_line_sync.recompute_cost_line_actual` aggrega
  cost_external accanto a cost_accrued (stima).
- Trigger: salvataggio/update SupplierInvoice marca JCL coinvolte stale +
  recompute immediato delle JCL direttamente linkate via
  `_mark_jcl_stale_for_supplier_invoice`.
- API response cost_report:
  - List view: `total_cost_external`, `cost_drift`, `real_margin_effective`
  - Detail view: same + per-line `total_cost_external` + `cost_drift`
- UI dettaglio CR: aggiunta stat card "Costo reale (fatture)" accanto a
  "Costo stimato risorse" con Δ delta vs stima.
- Vista cliente NON tocca cost_external (resta business logic interna).

**NumberingConfig cabling**:
- Helper `expand_pattern(fmt, seq, project_code, client_code, today)`
  estratto in `numbering.py` — sostituisce logica inline duplicata.
- Helper `gen_doc_code(db, doc_type, tenant_id, ...)` legge NumberingConfig
  + incrementa `current_seq` atomico + reset annuale.
- Cablato Quote.number e BillingBatch.code:
  - Genera con `gen_doc_code` se config presente.
  - Verifica uniqueness vs DB (con soft-delete).
  - Fallback automatico a `next_year_progressive` su collision o errore.
- `supported_vars` dict per ogni doc_type. `validate_pattern()` returna la
  prima variabile non supportata (per UI validation).
- Storico NON rinumerato (back-compat assoluta).
- Pendente: cabling Job/OverheadCost/IngestBatch/DDT (low priority — quei
  generator hanno logica custom diversa).

**Reconcile-all perf (dirty flag + lazy)**:
- Nuovo `JobCostLine.accrued_stale` boolean (default False).
- `recompute_cost_line_actual` resetta a False al completamento.
- `mark_jcl_stale()` / `mark_booking_jcl_stale()` helper compatti per
  marcare stale senza ricomputare (pattern lazy).
- `/cost-report/api/reconcile-all` ora WHERE accrued_stale=True →
  performance costante invece di O(jobs × JCL).
- Nuovo `/cost-report/api/reconcile-status` per UI polling background.
- Pre-115 su stress DB 80k JCL: 15-30 sec freeze.
- Post-115: ~50ms se 0 stale, lineare con N stale (tipicamente <100).

Auto-migrate al boot: 3 nuove colonne JCL (`total_cost_external`,
`accrued_stale`, fix `total_cost_accrued` IF NOT EXISTS). Idempotente.

## v3.5.0-alpha.114 — Audit deep-dive: 16 fix bug+architettura (15 maggio 2026 sera)

Round bug fixes da audit multi-agent in-depth su billing/CR/UI workflow.
Decisioni di prodotto da Matteo recepite:
- **Fatture immutabili**: una volta uscite da draft NON modificabili. Solo
  storno via NC TD04 le tocca. AI no touch invoice emesse.
- **Cashflow**: TD01 cancelled + NC TD04 incluse con segno (storno storico
  preservato nel mese di emissione).

**A1 — Card alignment quote**:
- `.card + .card { margin-top: 14px }` regola globale rompeva grid layouts
  (es. `.quote-top-row` Riepilogo↔Stato&azioni). Override scoped: no
  margin-top dentro flex/grid/quote-top-row/stat-grid/modal-body.

**A2 — PDF drift READ-ONLY**:
- Rimosso auto-commit `Invoice.subtotal/total` da `download_invoice_pdf`.
  Decisione Matteo: fatture immutabili. Drift = solo log warning.
- Aggiunto badge UI `⚠ drift` in lista fatture con tooltip esplicativo
  "Fattura non modificabile post-emissione. Storna via NC + riemetti".
- Backend `list_invoices` ritorna `lines_sum` + `has_drift` boolean.

**A3 — Invoice immutability guard**:
- Helper `_enforce_invoice_mutable()` blocca PUT su Invoice/InvoiceLine
  se status != draft (409 con messaggio chiaro).
- Transizioni stato consentite mapped: draft→{sent,cancelled};
  sent→{paid,overdue,cancelled}; overdue→{paid,cancelled}; paid/cancelled
  terminali (solo storno NC le riapre).

**A4 — Cashflow include storno NC**:
- Query include TD01 cancelled (storia contabile nel mese emissione).
- Esclude solo draft (mai emesse).
- NC TD04 sommata con segno NEGATIVO nel mese del NC.
- Esempio: gennaio TD01 +1000 + marzo NC TD04 -1000 = saldo 0 netto.
- Pre-fix: gennaio cancellato sparito + NC TD04 +1000 = saldo errato.
- outstanding non più sporcato da NC (era credito, non debito da incassare).

**A5 — Q5 root cause vero**:
- `planning.py:2301 bulk_edit_bookings`: shift temporale su booking già
  `done` NON chiamava `recompute_for_booking` (era gated solo su
  state==done target). Causa Q5 reported Matteo (CR list maturato stale
  finché si apre dettaglio).
- Fix: dopo applicazione shift temporale, se booking è already done,
  chiama recompute. Patch alpha.113 (reconcile-all su page load) ora è
  fallback, root cause risolto.

**A6 — Storno NC closing reset JCL lost**:
- Storno NC TD04 di closing invoice riapriva Project a `active` ma le
  JCL marcate `lost` con `billed_amount=0` durante closing (zero-approved
  in batch) restavano `lost` permanente.
- Fix: dopo reset Project.finance_status, query JCL lost+billed_amount=0
  → reset a `not_billed`.

**A7 — Double-close race lock**:
- `emit_closing_invoice`: `with_for_update()` su Project precheck per
  prevenire 2 admin concorrenti che emettono 2 closing per stesso
  progetto. No-op su SQLite WAL (writer serializzato) ma forward-compat
  PostgreSQL.

**A8 — OverheadCost code COUNT bug**:
- `overhead._next_code` usava `func.count()` filtrato da soft-delete
  listener → record cestinati invisibili ma codice UNIQUE già usato →
  collision al next INSERT (pattern feedback_soft_delete_unique_bypass).
- Fix: `order_by id desc` + `execution_options(include_deleted=True)`.
- `anomalies.py` duplicato → delego al generatore canonico.

**A9 — update_booking JCL re-assign recompute**:
- PUT /api/bookings/{id} con cambio `job_cost_line_id` SENZA touch
  assignments saltava recompute (gate solo su `assignments is not None`).
- Fix: traccia `_old_jcl_id_for_resync` prima del cambio. Se booking
  done E (assignments OR JCL changed), ricomputa vecchia + nuova.

**A10 — Resource delink supplier save**:
- Cambiare risorsa associata a fornitore lasciava la precedente con
  `supplier_id` puntato (dirty link).
- Fix: traccia `_prevLinkedResourceId` in editSupplier. Su save, se
  diversa da nuova, PUT Resource precedente con supplier_id vuoto.

**A11 — job_id senza project_id**:
- Modal fattura passiva: clearare progetto lasciava job select valued →
  submit inviava `job_id` orfano (no project).
- Fix: progetto onchange resetta job select. saveInvoice append job_id
  solo se project_id presente.

**A12 — /projects?client_id sconosciuto**:
- Se filter-client option non esiste (cliente cestinato, cross-tenant),
  `sel.value = X` silent no-op → mostrava tutti i progetti senza warning.
- Fix: confronta sel.value !== clientFilter → toast warning.

**A13 — + Crea risorsa deferred new supplier**:
- Bottone "+ Crea risorsa" era sempre enabled ma `msCreateResourceFromSupplier`
  bloccava con toast se supplier_id mancante (UX dead-end).
- Fix: disabilitato + opacity 0.5 + tooltip esplicativo finché fornitore
  non salvato. Si abilita auto in editSupplier() e dopo save.

**A14 — Drawer naming flush right sidebar**:
- Drawer naming builder aveva `left:0` → copriva sidebar.
- Fix: `left: var(--sidebar-w)`.

**A15 — Tenant scope sweep nuovi FK**:
- `SupplierInvoice.resource_id/project_id/job_id`: validate tenant in
  POST + PUT (era cross-tenant bypass).
- `Resource.supplier_id`: validate tenant in CREATE + UPDATE.
- Closing precheck/emit + NumberingConfig + Client.admin_email: già
  tenant-safe via filtri esistenti.

**A16 — Zero-accrued JCL precheck closing**:
- Closing precheck ora ritorna `zero_accrued_count`, `zero_accrued_total_quoted`,
  `zero_accrued_sample`: JCL con `not_billed` + `total_quoted>0` +
  `total_accrued=0` (preventivate ma mai eseguite).
- UI mostra banner ⚠ "X voci preventivate ma non eseguite" con confronto
  quotato vs maturato (0) per double-check pre-chiusura. Non bloccano.
- Decisione Matteo: vanno comparate con quotazione prima di lost.

## v3.5.0-alpha.113 — Round revisione Matteo 15 mag pomeriggio (11 punti Q1-Q11) (15 maggio 2026)

Continuazione audit. 11 nuovi punti Q1-Q11.

**Hotfix critico nel commit (regressione α.112)**:
- `base.html:347`: `<script src=".../global.js?v=...">` MANCAVA `</script>`
  chiusura → tag script aperto rompeva tutto il JS sotto in alcuni
  browser. Fixato.

**Q1 — Header look temi chiari**:
- `.topbar-bell`, `.topbar-sidebar-toggle`: color `var(--text)` invece
  di `--text2` (contrasto pieno cross-theme). Hover usa `var(--indigo)`
  come accent invece di solo bg-flip.
- `.topbar-user-role` bg `var(--bg3)` invece di `var(--bg)` (su temi
  chiari `--bg` era quasi white = badge invisibile).
- `.topbar-user-logout` color `var(--text)`.
- `.topbar svg { color: inherit; }` per forzare cascade currentColor.

**Q2 — Vedi Progetti con filtro cliente**:
- `/projects` legge `?client_id=N` da QS → preseleziona filtro +
  esegue filterProjects(). Bottone "Vedi progetti" da scheda cliente
  ora landa con filtro attivo.

**Q3 — Email amministrazione cliente per intestazione fattura**:
- Nuovo `Client.admin_email` + UI modal cliente (campo separato).
- Nuovo `Invoice.client_admin_email_snap` (snapshot all'emissione).
- PDF intestazione include "Att.ne Amministrazione · <email>".
- Storno NC propaga il snap dalla fattura sorgente.

**Q4 — Naming conventions (rename + builder)**:
- Tab `/settings#numbering` rinominato `Naming conventions`.
- Click su regola → drawer LEFT-SIDE 520px con builder drag&drop:
  blocchi chips draggable (variabili + testo custom). Click variabile
  in palette → aggiunge al pattern. ✕ rimuove. Drag riordina.
- Preview live "→ Prossimo emesso" dal server.
- Toggle "Reset progressivo a inizio anno".

**Q5 — CR list maturato stale**:
- Nuovo endpoint `POST /cost-report/api/reconcile-all` (bulk).
- `loadCrList()` chiama reconcile-all PRIMA del GET list → cifre lista
  allineate dal primo render (no più gap "apri dettaglio per allineare").

**Q6 — Dettaglio voce categoria spese**:
- Click su card categoria in /overhead → drawer con tabella voci
  che la compongono (codice/titolo/data/netto/totale) + riga Σ totale.
- Click riga → apre modal edit della voce.

**Q7 — Fatture passive senza progetto in spese aziendali**:
- `overhead_summary` include SupplierInvoice con project_id NULL come
  categoria virtuale `supplier_no_project` nel KPI totale + breakdown.
- Click sulla card → drawer fetch live `/suppliers/api/invoices` filtrate
  no-project. Click riga → naviga a /suppliers.

**Q8 — Lista fatturazione mostra titolo progetto**:
- Cella progetto ora 2 righe: codice mono + titolo text-muted.

**Q9 — Lista fornitori mostra progetto codice+titolo**:
- Backend `_invoice_to_dict` ora restituisce project dict + job dict.
- Eager load `Project`/`Job` nella query list_supplier_invoices.
- UI tabella suppliers: nuova colonna "Progetto" stessa convenzione.

**Q10 — Job select fattura passiva non popolato**:
- Bug: `loadAuxLists()` chiamava `/jobs/api` (404, endpoint inesistente)
  → _jobs=[] → select vuota.
- Fix: usa `/planning/api/jobs` (endpoint corretto).
- BONUS: filtro job per progetto selezionato (cambio mi-project
  filtra mi-job).

**Q11 — Match fattura ↔ risorsa esterna + supplier↔resource link**:
- Nuovo `SupplierInvoice.resource_id` (link opzionale a Resource).
- Nuovo `Resource.supplier_id` (link inverso 1:1).
- Modal fattura passiva: campo "Risorsa esterna associata" (select).
  Permette di marcare la fattura come costo specifico di una risorsa
  che ha booking nel job. Foundation per match preventivo↔consuntivo.
- Modal fornitore: campo "Risorsa associata" + bottone "+ Crea risorsa"
  che genera Resource tipo `person_freelance` pre-popolata da dati
  fornitore (nome/email/phone) + supplier_id già impostato.
- Salvataggio fornitore propaga link inverso a Resource.supplier_id.

Auto-migrate al boot: 4 nuove colonne (clients.admin_email,
invoices.client_admin_email_snap, supplier_invoices.resource_id,
resources.supplier_id). Idempotente.

## v3.5.0-alpha.112 — Round revisione Matteo 15 maggio (12 punti) (15 maggio 2026)

Maratona bug + feature dopo revisione Matteo. 12 punti dal log mattutino.

**P3 — /hr 500 fix critico**
- `hr.html:1227` aveva tag `{% if scoped_resource_id %}` letterale dentro
  commento `//` JS — Jinja non sa che è JS comment, parsava come tag
  aperto → mismatch endif/endblock → 500 al rendering template.
- Fix: riscritto commento per non contenere sintassi Jinja.

**P4 — Modal Trasmetti a fatturazione**
- Larghezza 980px (era 520px default illeggibile con tabella interna).
- Bug totale iniziale: server invia `total_proposed` = somma TUTTE
  candidate, ma α.111.25 imposta voci UNDER unchecked di default →
  totale mostrato includeva voci non spuntate finché user non toggla.
  Fix: chiama `updateTransmitSubtotal()` subito dopo render.

**P8 — Ricerca per numero fattura**
- Backend: `/finance/api/invoices?number=...` (ilike).
- UI: input `🔍 N. fattura…` accanto ai filtri esistenti, debounce 250ms.

**P10 — Filtro stato job CR allineato a enum**
- Filtro CR aveva valori inventati (open/in_progress) ≠ JobStatus reale.
- Aggiunti tutti i valori dell'enum: draft/quoting/approved/active/
  on_hold/completed/invoiced/cancelled.

**P1 — Look mancanti in /settings#aspect**
- Topbar palette mostrava 13 temi; settings.html ne mostrava 10.
- Aggiunti paper, linen, sage al `THEMES` di settings.

**P2 — Header leggibile su temi chiari E scuri**
- `.topbar-bell` non aveva `color` → SVG stroke=currentColor ereditava
  nero browser default → invisibile su sfondi scuri.
- Fix: `color: var(--text2)` su button, hover `var(--bg3)` invece di
  rgba(255,255,255,.06) hardcoded.

**P6 — Stampa fattura immediata post-emit**
- Dopo emit batch→fattura, `window.open(/pdf, '_blank')` subito.

**P11 — Stati CR chiariti**
- Header "Mat. post" in detail → tooltip esplicito: "Maturato non
  ancora fatturato. Nella lista CR la colonna Maturato è il TOTALE".
- Header "Maturato" in list → tooltip simmetrico.
- Modal trasmissione: banner esclusioni "X righe in approvazione, Y già
  fatturate escluse automaticamente" per ridurre confusione stato.

**P7 — Fattura PDF ≠ Report**
- PDF: ricomputa `subtotal = Σ lines.total` invece di trustare
  `invoice.subtotal` stored (drift recovery).
- `download_invoice_pdf` aggiunge drift-detection: se stored differisce
  da Σ lines più di 0.01 → log warning + auto-update ORM per allineare
  lista/report al PDF.

**P5 — Multi-batch progetto**
- Modal "Emetti fattura": banner se ci sono altri batch approved aperti
  per lo stesso progetto + bottone "↪ Aggrega tutti in fattura unica"
  che apre compose-invoice pre-popolato.

**P12 — Regole nomenclatura in Impostazioni** (scaffolding)
- Nuovo modello `NumberingConfig` (tenant_id + doc_type + format_pattern
  + reset_yearly + current_seq + current_year).
- Nuovo tab `Numerazione` in /settings (admin) con form per ogni doc
  type (quote, billing_batch, invoice, invoice_closing,
  invoice_credit_note, job, cost_report_export, supplier_invoice).
- Variabili supportate nel format: {YYYY}, {YY}, {MM}, {DD}, {YYYYMMDD},
  {NNN}, {NN}, {NNNN}, {PROJECT_CODE}, {CLIENT_CODE}.
- Endpoint GET/PUT/preview funzionanti. Storico NON viene rinumerato:
  le regole valgono solo per emissioni future. **Cabling nel numbering
  service in iterazione successiva** (per ora MVP UI + persistenza).

**P9 — Fattura di chiusura progetto**
- Nuovo `Project.finance_status` ('active' | 'closed') + `finance_closed_at`
  + `finance_closing_invoice_id`. Indipendente da `Job.status` operativo.
- Nuovo `Invoice.is_closing` boolean + `closing_project_id` FK.
- Endpoint `GET /finance/api/billing/closing-precheck/{project_id}`:
  verifica che tutte le JCL siano billed/paid/lost (no `not_billed` o
  `in_batch`). Ritorna riepilogo fatture esistenti del progetto.
- Endpoint `POST /finance/api/billing/closing-invoice/{project_id}`:
  emette la fattura finale aggregando i batch ancora aperti come
  ultima emissione REALE (non €0). Marca `finance_status='closed'`.
- PDF: sezione "FATTURA DI CHIUSURA PROGETTO {CODICE}" con tabella
  riepilogativa di tutte le fatture precedenti (numero/data/tipo/stato/
  totale/pagato) + totali Σ in fondo.
- Storno NC TD04 sulla closing → `Project.finance_status` torna
  ad `active` automaticamente.
- UI: nuovo bottone topbar `🏁 Fattura chiusura` apre modal con
  precheck progetto + form numero/date/IVA, submit disabilitato finché
  precheck non OK.

Note migrazione:
- 2 nuovi modelli `NumberingConfig` + 5 nuove colonne via auto-migrate
  al boot (idempotente). DB esistenti supportati automaticamente.

## v3.5.0-alpha.111.19 — Permit multiplier ROL ore permesso (14 maggio 2026)

**Richiesta Matteo**: ore di permesso (ROL) calcolate nelle timbrature
possono avere moltiplicatore opzionale (standard italiano 1.33 = TFR +
13ª/14ª + ferie accrual). Solo per report HR consulente lavoro, NON
tocca cost report né billing.

Implementazione:
- `WorkingHoursPolicy.permit_multiplier` Float default 1.0 (neutro).
- Migrazione auto-boot ALTER TABLE working_hours_policies.
- `/hr/api/overtime` ritorna `unavailability.permit_hours_weighted` +
  `permit_multiplier`. Calcolato come `other_hours * permit_multiplier`.
- UI HR pagina `/hr` riepilogo: card "Permessi" mostra ore ponderate
  + ore reali (sub-label) quando mult != 1.0. Quando 1.0 mostra solo
  ore reali (back-compat).
- UI `/settings#hours` form aggiunto campo "Moltiplicatore ore
  permesso (ROL)" con descrizione.

Casi d'uso:
- Contratti CCNL Cinema con ROL 1.33 → settare nel preset.
- Contratti senza ROL retribuito → lasciare 1.0.
- Freelance/co.co.co. → 1.0 (nessun ROL).

## v3.5.0-alpha.111.18 — Propaga Invoice paid → JCL.billing_status (14 maggio 2026)

Diagnosi user: cost report mostrava "Da fatturare" mentre fatture
"pagate". Gap: JCLBillingStatus.paid esisteva ma mai transito.

Fix 2 parti:
1) finance.py _refresh_invoice_payment_state propaga transizione
   Invoice.status → JCL.billing_status via JCLBilledSlice.
2) Backfill one-shot lifespan boot per DB esistente (marker
   uploads/.jcl_status_backfilled_v1).

## v3.5.0-alpha.111.17 — Timeline day/hour separator + quote versions extracted (14 maggio 2026)

Separatore giorno (vis-major) 2px indigo contrastato vs separatore
ora (vis-minor) 1px tenue. Su axis + foreground body.
Quote editor: sezione Versioni estratta fuori da quote-top-row.

## v3.5.0-alpha.111.13 → 111.16 — Cycle timeline fix density + heatmap + shift (14 maggio 2026)

Rimozione density compact/spacious (rotti). Heatmap rimossa
completamente (overlay sovrapposto al testo). Revert α.111.15
pointerdown (rompeva multi-select). Shift+drag (create) e
shift+wheel restano da fixare (bug strutturale, task #8).

## v3.5.0-alpha.111.12 — Density compact/spacious rimossi + heatmap su label (14 maggio 2026)

**Density Compact + Spacious rimossi**:
- Matteo: "non funzionano. Direi di toglierle a questo punto".
- Buttons UI `⠿` `☰` rimossi da toolbar (resta solo Comfortable, ora
  default implicito senza bottoni).
- CSS density rules rimosse (inline planning.html + planning.css).
- `tlSetDensity()` reso no-op idempotente (sempre 'comfortable').
- `tlInitDensity()` semplificato (no event binding).

**Heatmap spostata da background items a overlay su label**:
- α.111.10 metteva heatmap come `type:background` items in foreground.
  Interferiva con hover items (vis-timeline triggava itemover su bg).
  Matteo: "doveva apparire sulla risorsa, non sulla timeline".
- α.99 l'aveva originariamente rimossa da label perché +7px content
  sopra il flow rompeva sync con foreground.
- Soluzione α.111.12: `position: absolute; bottom: 0; left:0; right:0`
  inside `.tl-res-cell` (con `position: relative` su wrapper). No
  impatto altezza label → problema α.99 evitato.
- 1 cell per giorno nel range visibile, colore = ore/8 ratio
  (verde<50% / verde<100% / arancio<150% / rosso>150%).
- Skip se days.length > 120 (perf guard).
- CSS `.tl-heat-overlay` height 5px, `data-heatmap="off"` nasconde.

Cache-bust planning.css?v=3.5.0-alpha.111.12.

## v3.5.0-alpha.111.11 — Fix min-height density Compact + Spacious + nesting (14 maggio 2026)

Tentativo (poi obsoleto da α.111.12 che rimuove i due density).
Bump min-height compact 34→42, spacious 62→72 + parent nesting fix.

## v3.5.0-alpha.111.10 — Fix hover tooltip + reintroduzione heatmap (14 maggio 2026)

**Tooltip hover item — fix bug invisibile da α.83**:
- `tlTooltipShow()` line 3129 referenziava `bookings` (variabile
  non globale). `bookings` esiste come `let` locale dentro `tlRender()`
  ma NON su window (solo `window._tlBookings`).
- `typeof bookings === 'undefined'` → early return silenzioso →
  tooltip MAI mostrato.
- Fix: usa `window._tlBookings` esplicitamente. Skip background items
  inclusi `hm-` (heatmap nuovi).

**Heatmap reintrodotta come background items**:
- α.99 aveva rimosso heatmap da label cell (causava mismatch label↔
  group height). Toggle restava no-op.
- Reintroduzione architetturalmente corretta: 1 background item per
  giorno per risorsa nel range visibile. Colore = ore/8 ratio
  (verde<50%, verde scuro<100%, arancio<150%, rosso>150%).
- Vis-timeline renderizza background items dietro items normali
  senza alterare row height (problema risolto).
- `tlToggleHeatmap()` ora chiama `renderTimeline(true)` per ricaricare
  dataset con/senza heatmap items.
- Skip filters `hm-` aggiunti in onMoving, doubleClick, tlTooltipShow.
- CSS `.vis-item.tl-bg-heat`: no border, no shadow, opacity 0.65.

**Visualizzazione compatta/spaziosa**: ancora con bug visivi (Matteo
si accontenta della "normale"). Da riaffrontare se necessario.

Cache-bust planning.css?v=3.5.0-alpha.111.10.

## v3.5.0-alpha.111.9 — Min-height leaf-only via className custom (14 maggio 2026)

vis-timeline aggiunge `.vis-nesting-group` SOLO al label set, NON
al foreground group corrispondente. Filtro su entrambi lati
impossibile. Target foreground leaf-only via `[class*="tl-res-"]` /
`[class*="tl-project-"]`. Parents `tl-dept-*` lasciati a natural
height (~35px). User: "visualizzazione normale ora funziona".

## v3.5.0-alpha.111.8 — Debug: tlDebugAlign() dump className (14 maggio 2026)

Esteso dump per verificare DOM. Output rivelava:
- labelCls parent: `vis-label vis-nesting-group expanded`
- groupCls parent: `vis-group tl-dept-1` (no nesting-group class)
- Drift cumulativo +13 per header attraversato.

## v3.5.0-alpha.111.7 — Min-height leaf-only anche su foreground groups (14 maggio 2026)

Tentativo fallito. Assumeva vis-timeline aggiunge `.vis-nesting-group`
anche a foreground. Sbagliato.

## v3.5.0-alpha.111.6 — Timeline min-height uniforme cross-row (14 maggio 2026)

**Sintomo Matteo (post α.111.3)**:
- Modalità Spacious: "Online Editor" (role text) di Luca Bianchi
  sovrapposto a linea bianca di demarcazione timeline.
- Modalità Compact: testi label troncati.
- Modalità Comfortable: parziale overlap.
- Specifico per Luca Bianchi → unica risorsa senza items nel DB lean.

**Causa**:
- `tlDebugAlign()` confermava diff=0.0 label↔group (allineamento coord
  OK). Ma labelH variava per row: Luca=56px, Sara/Davide/Studio=69px.
- vis-timeline calcola row height = `max(items_h, label_h)` PER GRUPPO.
  Risorse senza items → row collassa su intrinsic label height.
  Risorse con items → row più alta perché items+margin pushano.
- `groupHeightMode: 'fixed'` è naming ambiguo vis-timeline: "fissa nel
  tempo", non "uniforma fra groups". Tra groups le altezze divergono.
- Label content in Spacious (~58px) > row Luca (56px) → overflow.

**Fix `planning.css`** — min-height APPLICATO SIMULTANEAMENTE a label
leaf E foreground group, per ogni density:
- compact: 34px
- comfortable (default): 48px
- spacious: 62px

Storia α.32.2 sconsigliava min-height SOLO su label (rompeva sync). Qui
applicato a entrambi lati: vis allinea perché entrambi vincolati.

**Cache-bust** `planning.css?v=3.5.0-alpha.111.6` in `planning.html:17`.

## v3.5.0-alpha.111.5 — Debug: tlDebugItems() per dump items + group dataset (14 maggio 2026)

Helper console esposto su `window.tlDebugItems()`: dump per ogni item
DOM Y, visualGroup (in che row ricade), dsGroup (group ID dataset),
dsGroupName (nome group). Confronto rivela mismatch items↔row.
Test Matteo: 5 items tutti in row corretto (Sara/Davide/Studio A).
Bug era altrove (min-height row cross-group, vedi α.111.6).

## v3.5.0-alpha.111.4 — Debug: tlDebugAlign() per diagnosi allineamento (14 maggio 2026)

Helper console esposto su `window.tlDebugAlign()`: dump per row labelTop,
labelH, groupTop, groupH, diff. Paste snippet in DevTools mangiava
spazi Chrome → workaround via funzione server-side.
Test Matteo: diff=0.0 ovunque (coord allineate); labelH variabile fra
row (56-69px) → indizio min-height bug (α.111.6).

## v3.5.0-alpha.111.3 — Fix allineamento timeline planning (14 maggio 2026)

**Timeline planning — labels disallineate / righe ammucchiate in fondo**:
- Sintomo Matteo (3 screenshot): con DB lean (poche risorse) le righe
  label+items si schiacciavano nel fondo del pannello, lasciando area
  vuota grande sopra. Visibile su Chrome Mac retina, stato post-load.
- Causa: `orientation: {axis: 'top'}` settava solo asse. Default
  vis-timeline 7.x `orientation.item = 'bottom'` → groups ancorati al
  fondo del pannello quando height totale groups < panel height.
- Fix `app/templates/pages/planning.html:4853`:
  `orientation: {axis: 'top', item: 'top'}` esplicito.
- Spiega anche perché in passato con tanti bookings il bug era invisibile
  (rows riempivano il panel, item:bottom innocuo).

**Heatmap toggle no-op — non risolto, da fare**:
- α.99 ha rimosso il render heatmap dalla label cell (causava mismatch
  altezze label↔foreground). Commento esplicito a planning.html:3415-3420
  `(legacy heatmap toggle prefs.heatmap resta no-op finché ridisegnata)`.
- CSS `.tl-heat` (planning.css:427-441) orfano. Bottone toolbar e
  pref checkbox restano vivi ma non producono rendering.
- Da reintrodurre come overlay assoluto sul foreground (vedi sessione
  successiva).

## v3.5.0-alpha.111.2 — Rollback timeline α.111 + riallineamento quadranti quotazione + seed lean + simulazione CR→billing (14 maggio 2026)

Post-feedback Matteo:

**Quote editor — riallineamento quadranti Riepilogo/Stato&azioni**:
- Le 5 form-group meta (Note, Termini pagamento, Spedizioni %, Scadenza gg DF, Periodicità) erano DENTRO la card "Stato & azioni"
  rendendo la card destra molto più alta della sinistra "Riepilogo
  economico" → disallineamento visivo.
- Estratte in nuova card "Condizioni economiche & scadenze" sotto al
  `quote-top-row`, layout grid 2-col. Le 2 card top restano snelle e
  allineate.

**Anomalies detect 500 fix** (bug pre-α.111):
- `anomaly_detector.detect_mancato_recupero`: `Invoice.tenant_id`
  non esiste → scope via JOIN `Client.tenant_id`.
- `detect_quote_discrepancy`: `JobStatus.in_progress` non esiste
  → `active/completed/invoiced`.
- Test: detect_all → 3983 anomalie rilevate, no errori.

**Rollback timeline α.111** (regressioni Matteo):
- `app/templates/pages/planning.html` + `app/static/css/planning.css`
  ripristinati a stato α.110: horizontalScroll:true, stack:!_lightMode,
  heatmap toggle visibile, drag handles, comportamento adattivo.

**Seed lean**:
- `scripts/seed_stress.py --scale FLOAT` (default 1.0). `--scale 0.3`
  ridimensiona linearmente: ~30 clienti, ~300 progetti, ~150 risorse,
  ~45 internal users, ~900 physical assets, ~1500 asset digitali.
- Test: DB lean creato in 34s. Backfill JobResourceAssignment auto al
  boot, anomaly index creato.

**Simulazione CR → Fatturazione**:
- `scripts/simulate_cr_to_billing.py [--n N] [--storno M]`
- Per N progetti random eligible (JCL not_billed > 0): preview →
  transmit → approve → emit invoice. Su M sottoinsieme: storna TD04
  (NC + void slice + riapri batch).
- Test: 15/15 progetti emessi (BB-2026-034 → BB-2026-048), 3 NC TD04
  stornate. DB finale: 116 batch (113 invoiced + 3 riaperti post-NC),
  614 invoices (3 TD04).

**Modifiche α.111 mantenute** (non regressioni): billing UX cleanup,
storno endpoint, quote scadenze, cost report mf-sortable, backfill
JobResourceAssignment.

## v3.5.0-alpha.111 — Billing UX cleanup + storno NC TD04 + scadenze Quote→Project + timeline polish (13 maggio 2026)

Round chiuso a 13 issue Matteo. 5 fronti:

**Billing / Fattura (8 fix)**
- Tab `Timesheet` e `Report P&L` rimossi da `/finance` (obsoleti)
- Endpoint nuovo `GET /finance/api/billing/invoice/{invoice_id}/pdf`: PDF
  diretto via invoice_id (snapshot fiscali immutabili), bypassa il
  vincolo `batch.invoice_id`
- `GET /finance/api/billing/{batch_id}/invoice-pdf` con fallback via
  `JCLBilledSlice.invoice_id` (recupera la fattura se `batch.invoice_id`
  è NULL per rollback parziale) + errore descrittivo se davvero assente
- Batch list: "Mostra anche fatturati" toggle (default OFF nasconde),
  data emissione fattura accanto al numero, link "Vai alla fattura"
  filtra alla singola fattura nel tab Fatture (focus-bar con × per reset)
- "Componi fattura periodo" → "Componi fattura" con **mode**:
  `per progetto` (tutti i batch aperti, default) | `per periodo`
  (sovrapposizione intervallo, non più containment stretto)
- Invoice line description ora include `[period_start → period_end]` per
  riportare il periodo validità lavorazioni in fattura
- **Storno fattura (nota di credito TD04)**: nuovo endpoint
  `POST /finance/api/billing/invoice/{id}/storno`. Crea Invoice TD04 con
  stessi snapshot/righe, annulla la sorgente, **void** delle
  `JCLBilledSlice` (`voided_at` + `voided_by_invoice_id`), JCL torna
  `not_billed` se senza slice attive residue, batch collegati riaperti
  in `approved`. Modal UI in `/finance` con motivo opzionale
- `due_date` auto-calcolata da `Project.billing_terms_days` quando omessa
  in compose-invoice
- Bottoni storno (📉) + scarica PDF (📥) per riga in lista fatture

**Quote → Project: scadenze fatturazione (1 feat)**
- `Quote.billing_frequency` + `Quote.billing_terms_days` (auto-migrate)
- `Project.billing_terms_days` (auto-migrate)
- UI editor quote: dropdown "Periodicità fatturazione" (mensile/
  trimestrale/milestone/on_completion/custom) + input "Scadenza gg DF"
- Propagation: all'approve della quote → valori finiscono su Project se
  non già impostati (auto-merge soft)

**Timeline (4 fix)**
- `horizontalScroll: false` — side scroll rimosso (creava conflitti col
  drag pan; Matteo: "non funzionava")
- Drag bordo (resize handle) RIMOSSO via CSS `display:none` su
  `.vis-drag-left/.vis-drag-right` — move resta attivo, resize formale
  via modal edit
- Sovrapposizione righe FIX: `stack: false` e `stackSubgroups: false` di
  default (anche su comfortable) → righe altezze uniformi, niente
  expand su overlap
- Heatmap toggle button + pref popover RIMOSSI (era no-op da α.99 dopo
  rimozione dal label cell). Da reintrodurre come overlay assoluto sul
  foreground in futuro
- Shift+wheel scroll verticale: target multipli + pre-check
  `scrollHeight > clientHeight` (vis-timeline 7.x scroll quirks)

**Cost report (2 fix)**
- Backfill automatico `JobResourceAssignment` da booking storici al boot
  (`_backfill_resource_assignments` in lifespan): risolve il caso
  Matteo "molte risorse nei booking ma poche assegnate al progetto"
  per dati creati prima dell'introduzione dell'auto-assignment (α.55)
- Tabelle "Voci di costo" e "Ore booking per fascia" rese `mf-sortable`:
  click su header → ordina (asc/desc) per qualsiasi colonna

**Schema (auto-migrate al boot)**
- `jcl_billed_slices.voided_at` (DATETIME) + `voided_by_invoice_id` (FK)
- `quotes.billing_frequency` + `quotes.billing_terms_days`
- `projects.billing_terms_days`
- `billing_slice_guard._find_slice_for_jcl_period` ora filtra
  `voided_at IS NULL` → slice stornate non bloccano più booking nel periodo
- `billed_locked_for_jcl/bulk` esclude slice voided dai totali

**Da testare** sul Mac di Matteo:
1. `/finance` — tab Timesheet/P&L spariti, ne restano 3
2. Batch list — fatturati nascosti di default, toggle "Mostra anche
   fatturati" li riattiva. Numero+data fattura per ogni batch
   fatturato. "Vai alla fattura" filtra alla riga
3. "Componi fattura" — mode "per progetto" mostra tutti i batch aperti
4. Fattura riga: descrizione include `[YYYY-MM-DD → YYYY-MM-DD]`
5. Bottone "📉 Storna" su fattura → NC TD04 emessa. Source diventa
   cancelled, slice voided, batch torna approved (visibile rimuovendo
   "Mostra fatturati"). Booking del periodo tornano editabili
6. Quote editor: sezione "Periodicità fatturazione" + "Scadenza gg DF".
   All'approve → Project mostra gli stessi valori
7. Planning timeline: niente più scroll laterale, niente drag bordo,
   righe uniformi, niente bottone Heatmap

## v3.5.0-alpha.110 — Storage adapter S3 + TPN strong isolation audit (13 maggio 2026)

Chiusi gli ultimi 2 cantieri backlog del piano Multi-tenant/TPN.

**Storage adapter S3-compatible**:
- `boto3 1.43.6` installato
- `app/services/storage/{__init__,base,local_fs,s3,factory}.py`
- Pattern: `StorageBackend` ABC con `upload/download/delete/exists/
  stat/list/presigned_url/resolve_path`
- `LocalFSBackend`: filesystem locale con path-traversal guard
- `S3Backend`: boto3 client S3-compatible (AWS/MinIO/R2/Wasabi),
  signature v4, presigned URL TTL configurabile da
  `settings.aws_s3_presigned_ttl`
- `factory.get_storage_for_project(project)`:
  - storage_backend=`s3*` + bucket → S3Backend con credenziali ENV
  - else → LocalFSBackend per-project (`uploads/t{tid}/p{pid}/`) o tenant
- `/dam/download/{id}` esteso: se `Asset.file_path` inizia con `s3://`
  → redirect 302 a presigned URL via storage factory
- Lazy migration: file legacy locali restano leggibili invariati

**TPN strong isolation audit (scope mutator critici)**:
- `/dam/api/assets/{id}/assign-project`: check
  `user_can_access_project(user, target)` + fix `db.commit()` mancante
- `/dam/api/assets/upload`: check accesso al `project_id` target prima
  di salvare Asset
- `/dam/api/fs-import`: check accesso al `project_id` target
- `/physical-assets/api/shipments` con `shipping_payer=charged_to_client`:
  check accesso a `billable_to_project_id`
- Skip per `is_admin(user)` (super-admin bypass coerente)

## v3.5.0-alpha.109 — Fix UI departments indirizzo + bootstrap platform admin idempotente (13 maggio 2026)

1. **UI Department.shipping_address/contact MANCAVA** (era solo modello α.106):
   - Router `/departments` accetta+ritorna i nuovi field
   - `departments.html` modal new + edit con fieldset
     "📍 Indirizzo spedizioni (opz.)"
   - `editDept()` esteso con shipAddr+shipContact, call Jinja aggiornata

2. **Bootstrap platform admin idempotente**:
   - α.104 UPDATE eseguito solo dentro `if column not in cols`. DB
     importato da export ZIP α.107+ aveva già colonna, UPDATE saltato.
   - α.109: blocco SEMPRE eseguito (idempotente). Print "promoted N
     admin(s)" nei log.
   - Allargato a TUTTI admin tenant=1 (non solo email hardcoded).

3. **Script CLI `scripts/grant_platform_admin.py`**:
   - `--email X` promuove · `--revoke` revoca · `--list` lista

## v3.5.0-alpha.108 — About modal su click logo MediaFlow (13 maggio 2026)

Click su logo "MF MediaFlow" sidebar → modal About con:
- Versione corrente (da `/health`)
- App name + AI provider configurato
- User loggato + tenant_id + flag is_platform_admin
- Link rapidi: `/manuale` + GitHub repo

Risolve confusione su versione attiva quando codice locale Mac obsoleto
vs DB importato da export ZIP più recente.

## v3.5.0-alpha.107 — Timeline: legenda aggiornata + density attiva stack + scroll keyboard (13 maggio 2026)

Risposta screenshot Matteo su righe altezze diverse 138/50/69/54px.

**Root cause confermato**: vis-timeline 7.x con `stack:true` espande
righe quando item temporali si sovrappongono. Memory
`[[feedback-vis-timeline-quirks]]` cita questo come limite strutturale
della libreria (sostituzione = backlog R12 cantiere grande).

**Fix mirato α.107** senza sostituire libreria:

**1. Density toggle ora cambia anche stack mode** (`planning.html`):
- `compact` / `spacious` → `stack: false` (overlay items, altezze
  righe uniformi)
- `comfortable` → `stack: true` (default, expand su overlap)
- Chiamato `inst.setOptions()` + `redraw()` per applicare a runtime
- Risolve disallineamenti label↔foreground visti negli screenshot

**2. Scroll keyboard + Shift+wheel** (`planning.html`):
- `tlBindKeyboardScroll()` registra handler:
  - `↑/↓` step 60px (≈1 riga)
  - `PageUp/PageDown` step `clientHeight - 80px`
  - `Home/End` jump inizio/fine
  - `Shift + wheel mouse` scroll verticale (default wheel resta zoom
    timeline standard, no perdita)
- Skip se focus su input/textarea/select
- Skip se vista timeline non visibile (storyboard/agenda)

**3. Legenda aggiornata** (`planning.html`):
- Vecchia: "Drag = pan · ... Canc/⌘C/V/⌘Z" (obsoleta, Drag pan rimosso)
- Nuova: Drag item / Drag bordo resize / Shift+drag crea / dblclick
  modifica / Alt+drag duplica / `S` area-select / Shift+click multi /
  Ctrl+click toggle / Canc / Ctrl+Z / ↑↓ scroll / PgUp/PgDn fast.
- Anche `<kbd>` style usa `var(--tint-soft)` (theme-aware).

**Su "ripensare GUI timeline dalle basi"**:
- vis-timeline 7.x ha limiti strutturali documentati (stack O(N²),
  sanitization HTML annidato, mismatch label↔foreground, wheel-zoom-only).
- Sostituzione candidate: Bryntum Scheduler (commerciale), DHTMLX
  (commerciale), Frappe Gantt (limited), custom canvas-based.
- Tempo stimato cantiere R12: 2-3 settimane.
- Per ora: fix mirati incrementali. Density toggle stack:false è il
  workaround pulito per disallineamenti.

## v3.5.0-alpha.106 — Spedizioni dettaglio+autocomplete · Reparti indirizzo · Quote markup · Bug AI fix (13 maggio 2026)

7 fronti chiusi insieme per feedback Matteo:

**1. Bug AI 500 /settings/api/ai/save** (`settings.py`, `global.js`):
- Encryption fallback: ora `try/except` su `encrypt_secret()` ritorna
  503 con messaggio chiaro invece di 500 generico (es. quando
  `AI_KEY_ENCRYPTION_KEY` manca nel .env).
- Fix `global.js:1173` TypeError "not of type IdleRequestOptions":
  `requestIdleCallback(fn, 80)` era sbagliato (vuole options object).
  Wrapper unificato `schedule(fn)` con `{ timeout: 80 }`.

**2. Spedizioni: dettaglio batch + storico contenuti**
(`physical_assets.py`, `assets_inout.html`):
- Endpoint nuovo `GET /api/ingest-batches/{id}` con:
  - meta batch (carrier, costo, payer, JCL ricarico)
  - lista physical_assets con `contents_at_shipment[]` (snapshot
    `AssetMembership` AT `batch.batch_date` → "cosa c'era sul disco
    quando è stato spedito 10/04/2025")
  - lista digital_assets
- UI click row su tab Spedizioni → drawer laterale 520px con tutti
  i dettagli + link "→ Asset fisico" su ogni physical.

**3. Spedizioni: indirizzi default + ricerca DB**
(`physical_assets.py`, `assets_inout.html`):
- Endpoint nuovo `GET /api/shipping-parties?q=&include_*` →
  autocomplete unificato tenant + departments (con shipping_address) +
  clients + suppliers (opt). Ogni party ritorna address+contact.
- Form modal "Nuova spedizione" rifatto: fieldset 📍 Mittente +
  🎯 Destinatario, ognuno con autocomplete via `<datalist>`. Selezione
  party → popola automaticamente address+contact.
- Endpoint `POST /shipments` accetta ora `from_address/contact` +
  `to_address/contact` (oltre `from_party/to_party` esistenti).

**4. Department: shipping_address + shipping_contact**
(`models.py`, `main.py` auto-migrate):
- Nuovo `Department.shipping_address` + `shipping_contact` per casi
  in cui un reparto ha sede diversa dal tenant principale (es. sala
  VFX in altra città). Visibili in autocomplete `/shipping-parties`.

**5. Quote: clausola ricarico spedizioni**
(`models.py`, `quotes.py`, `quotes.html`, auto-migrate):
- `Quote.shipping_markup_pct` (default 15.0, editable per quote).
  Riflette ma sovrascrive `Project.shipping_markup_pct`.
- UI card "Stato & azioni" → nuovo input "Ricarico spedizioni %"
  con help text esplicativo. Salvato via `saveQuoteMeta()`.
- `GET /quotes/api/{id}` espone il nuovo field.
- `PUT /quotes/api/{id}` accetta `shipping_markup_pct` (clamp 0–100).
- (TODO α.107: explicit clausola nel PDF + serializzazione fattura SDI)

**6. UI audit disallineamento card Quote**:
- Verificato CSS `.quote-top-row { grid + align:stretch +
  height:100% }`. Allineamento corretto strutturalmente. Eventuali
  disallineamenti residui sono content-driven (versioning area
  cresce). Acceptable.

**Backlog roadmap α.107+ ESPLICITI**:
- **Storage adapter S3** (~1 settimana): `services/storage/{base,
  local_fs,s3,factory}.py`, upload/download routing per project, presigned
  URL S3, scan bucket. Modello + ENV già pronti (α.105).
- **TPN strong isolation audit** (~3-5gg): audit ogni endpoint Asset
  mutator → filter `project_id in accessible_project_ids(user)`.
  Sweep manuale dei ~30 endpoint DAM/physical_assets/shipments.
- **PDF/SDI clausola ricarico esplicita**: append nelle condizioni
  economiche del PDF quando `shipping_markup_pct > 0`.

## v3.5.0-alpha.105 — Storage multidomain per progetto + ENV S3 + UI multipath FS scan (13 maggio 2026)

Preparazione storage S3-compatible + compartimentazione TPN per progetto.
Decisioni Matteo:
1. S3 + S3-compatible (MinIO/R2/Wasabi) via stesso adapter boto3
2. Storage per-progetto (granularità fine TPN)
3. Credenziali via ENV (no DB) per sicurezza
4. Legacy locale sempre leggibile (lazy migration)
5. FS scan tenant-level + override per-progetto

**Modello esteso `Project`** (`models.py` + auto-migrate):
- `storage_backend: str` (`local` | `s3` | `s3_minio` | `s3_r2` | `s3_wasabi`)
- `storage_root: str` (path locale o S3 prefix)
- `s3_bucket: str` (per backend S3-compatible)
- `fs_scan_paths: JSON list` (whitelist FS scan per-progetto, override tenant)

**Settings ENV** (`config.py`):
- `aws_access_key_id`, `aws_secret_access_key`
- `aws_s3_endpoint` (vuoto = AWS standard; valorizzato per MinIO/R2/Wasabi)
- `aws_s3_region`, `aws_s3_use_ssl`
- `aws_s3_default_bucket` fallback
- `aws_s3_presigned_ttl` (default 3600s)

**Endpoint nuovi** (`settings.py`):
- `GET /settings/api/fs-scan-paths` lista paths tenant
- `PUT /settings/api/fs-scan-paths` aggiorna lista (validation no `..`)

**Endpoint esteso** `PUT /projects/api/{id}`:
- Accetta `storage_backend`, `storage_root`, `s3_bucket`, `fs_scan_paths_json`
- Validazione storage_backend whitelist
- `GET /projects/api/{id}` espone i nuovi campi

**FS scan compartimentato** (`dam.py`):
- `POST /dam/api/fs-scan` accetta nuovo `project_id` opzionale.
- TPN strict: se `Project.fs_scan_paths` valorizzato → USA SOLO QUELLA
  whitelist (no fallback tenant). Se vuota → fallback tenant-level.
- Path-traversal check resta attivo.

**UI** (`settings.html`):
- Nuovo tab "💾 Storage" (solo admin) con:
  - Card "Filesystem scan — Percorsi autorizzati (tenant-level)" con
    lista corrente, add/remove paths, validation client-side `..`.
  - Card "Storage S3 — Stato configurazione" con istruzioni ENV +
    workflow per attivare un Project su S3.

**E2E test**: `PUT fs-scan-paths` con 2 paths → `GET` ritorna stessi.
`PUT /projects/api/1 storage_backend=s3 s3_bucket=X` → riflette in `GET`.
`POST fs-scan project_id=X path=Y` valida contro project paths (TPN strict)
con fallback tenant.

**Aperti α.106** (storage adapter pattern):
- `app/services/storage/{base,local_fs,s3,factory}.py`
- Asset upload/download routing via factory(project)
- Presigned URL S3 per download diretto
- Scan bucket S3 (`storage.walk(prefix)`)
- Test E2E con MinIO container

**Aperti α.107** (TPN strong isolation):
- Audit endpoint mutator: ogni read/write Asset filtra
  `project_id in accessible_project_ids(user)`
- Path traversal guard cross-project per filesystem locale

## v3.5.0-alpha.104 — Super-admin GUI tenant management + manuale aggiornato (13 maggio 2026)

Console super-admin platform per gestione cross-tenant da GUI.
Sostituisce/affianca il CLI `scripts/create_tenant.py` (resta usabile).

**Modello** (`models.py` + `main.py` auto-migrate):
- `User.is_platform_admin` Boolean default=False, indexed.
- Auto-migrate ADD COLUMN + UPDATE bootstrap: admin@mediaflow.it +
  matteo@mediaflow.it (tenant=1) → is_platform_admin=True.

**Router nuovo** `app/routers/platform.py` prefix `/platform`:
- `GET /platform/tenants` HTML page (gated `_require_platform_admin`)
- `GET /platform/api/tenants` lista cross-tenant con KPI users/projects/clients
- `POST /platform/api/tenants` crea Tenant + admin User + 4 Department +
  cartella uploads/t{id}/ (logica identica a CLI)
- `PATCH /platform/api/tenants/{id}` rinomina slug/name/legal/email
- `POST /platform/api/tenants/{id}/revoke` + `/reactivate`
  (tenant Default non revocabile)
- `GET /platform/api/tenants/{id}/users` lista users del tenant
- `POST /platform/api/tenants/{id}/admin-user` aggiungi admin a tenant
  esistente (password random 12-char se non specificata)

**UI** `app/templates/pages/platform_tenants.html`:
- Tabella sortable con badge stato + KPI counters per tenant
- Modal crea tenant (slug + nome + admin email/nome/password)
- Modal credenziali post-creazione (copy/paste prima di chiudere)
- Modal edit (slug, name, legal, email)
- Modal Users con tabella + form aggiungi admin
- Toggle sospendi/riattiva (icona 🔒/🔓, non per tenant 1)

**Sidebar** (`base.html`): nuova sezione "Platform" con link Tenants,
visibile SOLO se `request.state.current_user.is_platform_admin == True`.

**Bypass tenant filter**: gli endpoint platform usano query dirette
(no `current_tenant_id()`) → vista cross-tenant. Auth gate via
`_require_platform_admin(request)` controlla flag → 403 se non super-admin.

**Manuale aggiornato** (`pages/manuale.html`): aggiunte 5 sezioni nuove
+ relativi link TOC:
- Capitolati → Quote bozza (wizard 3-step, α.95)
- Spedizioni asset (payer/pickup/markup ricarico, α.93–α.94)
- Asset Extra (FS scan whitelist, Cross-check IMDB/Boxoffice, α.96)
- Portale Cliente (magic-link, scope progetti, α.97)
- Multi-tenant (concetti, console super-admin, login subdomain,
  α.101–α.104)

**Test post-deploy**:
- admin@mediaflow.it login → vede "Platform · Tenants" in sidebar
- `/platform/tenants` → lista 2 tenant (Default + acme di test)
- Crea nuovo tenant da modal → vede credenziali post-create
- Sospendi tenant acme → status badge "Sospeso", login bloccato

## v3.5.0-alpha.103 — Multi-tenant HARD R-MT3+R-MT4: onboarding + uploads isolation + test cross-tenant (13 maggio 2026)

Chiusi 2 sprint del piano Multi-tenant HARD (#6 roadmap, 4 sprint totali):

**R-MT3 — Onboarding + uploads isolation** (`scripts/create_tenant.py`,
`app/services/dam.py`):
- CLI script `scripts/create_tenant.py`: crea Tenant + admin User +
  4 Department default + cartella `uploads/t{id}/` isolata.
  Listino vuoto (decisione Matteo). Password admin random 12-char se
  non specificata (stampata per copy/paste).
- Usage:
  `python scripts/create_tenant.py --slug acme --name "Acme Post" --admin-email admin@acme.it --admin-name "Acme Admin"`
- Login URL dev: `http://acme.lvh.me:8000/auth/login` (lvh.me → 127.0.0.1)
- Login URL prod: `http://acme.mediaflow.it/auth/login` (quando DNS pronto)
- Fallback dev: `http://localhost:8000/auth/login?tenant=acme`
- `app/services/dam.py.save_upload` + `generate_thumbnail` ora usano
  `uploads/t{current_tenant_id()}/assets/` + `/thumbnails/` invece di
  `uploads/assets/` globale. Path file_path in Asset.file_path resta
  assoluto: file legacy `uploads/assets/...` di tenant 1 restano
  accessibili invariati.

**R-MT4 — Test cross-tenant leak + fix discoveries**
(`scripts/test_multitenant.py`, `app/routers/projects.py`):
- Test E2E `scripts/test_multitenant.py` con 8 check via HTTP urllib:
  - T1: login `admin@acme.it?tenant=acme` → 303 + JWT.tid=2
  - T2: login `admin@mediaflow.it?tenant=acme` → 401 (gate)
  - T3a: cookie tenant 1 senza header → 200 con lista clienti
  - T3b: cookie tenant 1 + header `X-Tenant-Slug: acme` → 303 (gate)
  - T4: GET `/clients/api` con cookie acme → 200 con `[]` (isolato)
  - T5: GET `/clients/api` con cookie tenant 1 → 200 con dati
  - T6: GET `/projects/api/1` con cookie acme → 404 (no leak)
- **RESULT: 8/8 PASS**.
- **Bug scoperto durante test**: `/projects/api/{id}` GET + altri 7
  endpoint in projects.py filtravano solo per `Project.id`, leak
  cross-tenant. Fix bulk: `.filter(Project.id == project_id)` →
  `.filter(Project.id == project_id, Project.tenant_id == current_tenant_id())`.
  8 occorrenze sistemate via regex script.
- `list_projects` (`GET /projects/api`) e `projects_page` (`GET /projects/`)
  ora filtrano per `current_tenant_id()`.

**Smoke test E2E completo**:
- Tenant `acme` (id=2) creato → admin@acme.it login OK
- Cross-tenant access bloccato (cookie reuse, header injection)
- Isolation perfetta tra acme e Default

**Aperti** (post-MT):
- Audit altri router con `.filter(X.id == y).first()` senza tenant filter
  (necessario sweep manuale, projects.py era il primo trovato)
- UI per gestione tenant (oggi solo CLI)
- Tenant onboarding completion (Tenant.onboarding_completed flag setting)
- Subdomain DNS wildcard + cert SSL (quando dominio scelto)

## v3.5.0-alpha.102 — Multi-tenant HARD R-MT2: 341 occorrenze CURRENT_TENANT → current_tenant_id() (13 maggio 2026)

Refactor bulk delle 24 router files: rimpiazza `CURRENT_TENANT = 1`
module-level con chiamata dinamica `current_tenant_id()` per-request.

**Strategia**:
- Sostituito `CURRENT_TENANT = 1` definizione module-level (snapshot al
  load) con import `from app.context import current_tenant_id` + chiamata
  funzione ad ogni uso (legge da contextvars settata dal middleware).
- Bulk replace via script Python: 341 occorrenze su 24 file.
- Auto-fix multi-line import breaks (4 file dove regex aveva inserito
  import dentro statement aperto).

**Files toccati** (replacements):
- physical_assets.py (54) · planning.py (47) · pricelist.py (34)
- suppliers.py (29) · billing.py (27) · clients.py (23)
- hr.py (16) · delivery_templates.py (14) · dam.py (13) · jobs.py (13)
- anomalies.py (9) · resources.py (9) · overhead.py (8)
- planning_unavailabilities.py (7) · portal.py (7) · projects.py (5)
- quotes.py (6) · departments.py (6) · cost_report.py (4)
- tech_sheets.py (4) · admin.py (2) · planning_diag.py (2)
- ai.py (1) · team.py (1)

**Conseguenze**:
- Ogni endpoint ora opera nello scope tenant resolved dal middleware
  per-request. Senza altre modifiche, comportamento single-tenant resta
  identico (DEFAULT_TENANT_ID=1).
- Cross-tenant attack via cookie reuse bloccato dal gate auth_guard
  (alpha.101): JWT.tid != resolved.tid → user invalidato.
- Performance: 1 chiamata funzione per query invece di lettura costante.
  Trascurabile (~ns).

**E2E test post-refactor**:
- Login admin@mediaflow.it → 303 OK, JWT con tid=1
- `/clients/api` → 200 con lista clienti (filtro tenant ok)
- `/finance/api/billing/composable-batches?project_id=1` → 200 con
  payload corretto (era il bug primario di α.92)

**Prossimo R-MT3**: onboarding flow CLI/UI per creare nuovi tenant +
`uploads/t{tenant_id}/` isolation + tenant settings.

## v3.5.0-alpha.101 — Multi-tenant HARD R-MT1: User.tenant_id + JWT scope + middleware (13 maggio 2026)

Primo sprint di 4 per Multi-tenant HARD (#6 roadmap). Decisioni semantiche
confermate Matteo 13 mag:
- Tenant resolution: **subdomain** (`acme.mediaflow.it`)
- Onboarding: **invito only** (admin platform crea tenant)
- Listino nuovo tenant: **vuoto**
- Uploads: **per-tenant** isolati (media veri passano per altri canali)
- Subscription/billing: **backlog**
- Tenant 1 = "Default" (admin platform)

**Modello** (`models.py`):
- `User.tenant_id` FK Tenant (default=1, indexed)
- `UniqueConstraint("tenant_id", "email")` sostituisce vecchio
  `unique=True` su email globale: stesso email su tenant diversi = 2 user
  distinti

**Auto-migrate** (`main.py`):
- `ALTER TABLE users ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1`
- `CREATE UNIQUE INDEX uq_user_tenant_email ON users(tenant_id, email)`
- DROP del vecchio autoindex `ix_users_email` (rilevato via sqlite_master
  query — SQLite tiene autoindex anche dopo `unique=True` rimosso dal
  modello)

**Context module** (`app/context.py`):
- Stub `current_tenant_id() → 1` sostituito con `contextvars.ContextVar`.
- `set_tenant_id(tid)` / `reset_tenant_id(token)` per middleware.
- `get_tenant_id()` FastAPI dependency, `current_tenant_id()` service.

**Middleware tenant_resolver** (`main.py`):
- Chain resolution: header `X-Tenant-Slug` → query `?tenant=X` →
  subdomain (`acme.mediaflow.it`/`acme.lvh.me`) → JWT.tid → DEFAULT=1.
- Setta `request.state.tenant_id` + popola contextvar.
- Dichiarato DOPO `auth_guard` (Starlette stack LIFO: ultima decoration
  = outermost = primo eseguito all'ingresso request).

**Cross-tenant gate in auth_guard** (`main.py`):
- Se `JWT.tid != request.state.tenant_id` → user invalidato (forzato
  re-login sul tenant corretto). Previene token leak cross-tenant.

**JWT scope** (`auth.py` service):
- `authenticate_user(db, email, password, tenant_id=None)` filtra per
  tenant se valorizzato.
- `get_current_user_from_token` legge `tid` dal payload, scope query.
- Token vecchi senza `tid` → fallback back-compat.

**Login flow** (`routers/auth.py`):
- `authenticate_user(... tenant_id=request.state.tenant_id)` → scope al
  tenant del host corrente.
- Token emesso con `{"sub": email, "tid": user.tenant_id}`.
- MFA pending token idem.

**E2E smoke test**:
- Login `admin@mediaflow.it/admin123` → 303 OK, JWT decoded:
  `{"sub":"admin@mediaflow.it","tid":1,"exp":...}`.
- Auto-migrate eseguito senza errori. Vecchio `ix_users_email` dropped.

**Prossimi sprint** (in fase di scoping):
- **R-MT2**: 376 occorrenze `CURRENT_TENANT = 1` in 25 router → calcolo
  per-request via `current_tenant_id()`.
- **R-MT3**: onboarding flow CLI/UI + uploads `t{tenant_id}/` scheme.
- **R-MT4**: test cross-tenant leak + security audit.

## v3.5.0-alpha.100 — Tint vars theme-aware per temi chiari (13 maggio 2026)

Audit hardcoded rgba(255,255,255,X) in planning.css (58 occorrenze).
Sui temi chiari Sand/Paper/Linen/Sage diventavano bianco-su-bianco =
bordi/separatori/zebra rows invisibili.

**Variabili nuove** (`main.css`):
- `--tint-faint` (.012) zebra row alternate
- `--tint-soft` (.04) bordi sottili, hover bg
- `--tint-medium` (.06) separatori, divider
- `--tint-strong` (.12) bg card elevata

Default `:root` indigo dark = `rgba(255,255,255,X)`. Override per
`.theme-sand, .theme-paper, .theme-linen, .theme-sage` ribaltato a
`rgba(0,0,0,X)`.

**planning.css**: sostituito 5 hardcoded più visibili con var():
- `.todo-card .duration-strip` background
- `.todo-card .act-btn:hover` background
- `.fa-suggestions .fa-item` border-bottom
- `.sb-col-head` border-bottom
- `.sb-card` border

I restanti 53 hardcoded rgba(255,255,255,X) restano (elementi vis-timeline
interni con regole specifiche per theme-broadcast; rischio breakage se
sostituiti troppo aggressivamente). Audit incrementale futuro.

## v3.5.0-alpha.99 — Timeline design fix: density preset funzionante + heatmap fuori da label (13 maggio 2026)

Screenshot Matteo 15.21-15.22 → "problema di design a monte" identificato.

**Bug a monte 1 — Density preset decorativo** (`planning.css`,
`planning.html`):
- Bottoni ⠿/≡/☰ (compact/comfortable/spacious) in `#tl-density` settavano
  `tl-host.dataset.density` MA `planning.css` aveva regole SOLO per
  `#sb-host[data-density="compact"]` (storyboard). Per `#tl-host` ZERO
  regole. Toggle decorativo → nessun effetto visivo. Diagnosi Matteo:
  "small/normal/large non cambiano di molto" = effetto realmente nullo,
  era variazione font dropdown 11→13 (solo .vis-item) percepita.
- Fix: aggiunte regole `#tl-host[data-density="compact|spacious"]` che
  scalano font tl-res-name (12/14/16px), tl-res-role (9.5/11/13px),
  padding label, vis-item font+padding+border-radius. Default
  comfortable = baseline esistente.
- `tlSetDensity()` ora chiama `_tlInstance.redraw()` per ricalcolare
  altezze righe vis-timeline (senza, layout resta sul font precedente).
- Rimosso `!important` da `.tl-res-name` / `.tl-res-role` per permettere
  override dal selettore density.

**Bug a monte 2 — Heatmap rompe sync label↔foreground**
(`planning.html`):
- Label cell aveva 3 elementi flex-column (name + role + heatmap).
  vis-timeline 7.x sincronizza altezza riga prendendo MAX tra label e
  foreground, ma con heatmap (7px extra) la label era più alta del
  foreground → mismatch verticale visibile come "item non allineati alla
  riga" (screenshot 15.22.20 con item arancione sfasato).
- Fix: heatmap RIMOSSA dalla label cell. Prefs `heatmap` ON resta no-op
  (toggle preservato per UI ma non riattiva). Reintroduzione futura come
  overlay assoluto sul foreground (NON dentro label) o come riga
  dedicata sopra timeline.
- Rimosso `color:#ffffff` hardcoded inline su nameEl che bypassava il
  fix theme-aware α.94.

Memory `[[feedback-vis-timeline-quirks]]` confermata: vis-timeline 7.x
pensato per label semplici 1-2 righe. Stuffing aumenta i mismatch.

## v3.5.0-alpha.98 — Timeline fix duplicati + label role leggibile (13 maggio 2026)

Risposta a screenshot Matteo 12.47/12.48/12.49 con sovrapposizioni labels.

**Bug 1 — Stefano Marini duplicato** (`scripts/dedup_resources.py`):
- Root cause: seed stress test ha creato 2 Resource record con stesso
  nome+role+department (id 232 + id 254 per "Stefano Marini"). Visivamente
  appaiono come 2 righe distinte sulla timeline (groups = resource_id).
- Script nuovo `dedup_resources.py`: dry-run di default, `--apply` per
  scrivere. Strategia: per ogni gruppo `(name, role, dept_id)` tiene il
  record con id minore, riassegna i `BookingAssignment` al keeper,
  soft-delete (is_active=False + name += " [DUP-of-X]") i duplicati.
- Eseguito sul DB: 1 gruppo deduplicato (Stefano Marini), 52 booking
  riassegnati. Le altre 8 nomi duplicati avevano role/dept diversi
  (omonimi legittimi) — non toccati.

**Bug 2 — Sub-text role illegibile** (`planning.css`, `planning.html`):
- `.tl-res-role` font era 9px uppercase letter-spacing 0.5px → screenshot
  12.47.47 mostra solo nome, role esiste ma non si vede.
- Bumpato a 11px line-height 1.2 no-uppercase letter-spacing 0.2px.
- Inline style hardcoded `color:#ffffff` in `planning.html` nameEl
  rimosso: ora eredita CSS `.tl-res-name` con `var(--text)` theme-aware
  (era invisibile su Sand/Paper/Linen/Sage anche dopo fix α.94).

**Bug 3 — Sale duplicate**: lo screenshot 12.49 mostra "Sala Color HDR
Dolby Vision #1" 2 volte ma il DB ne ha solo 1 record (id=271). Bug
visivo di vis-timeline 7.x con stack:true: quando 2 item temporalmente
overlappano sulla stessa risorsa, crea righe-virtuali per stacking che
ripetono la label. Non fixable senza rimpiazzare libreria timeline o
disabilitare stack:true (vedi memory [[feedback-vis-timeline-quirks]]).
Documentato come limitazione nota; backlog: valutare Bryntum/DHTMLX.

**+1 script seed cleanup**, **no DB migration**.

## v3.5.0-alpha.97 — Portale Cliente fase A: auth magic-link + dashboard read-only (13 maggio 2026)

Punto #10 della roadmap — fase A (auth + dashboard + scheda progetto).
Le fasi B (DAM read-only filtrato + storico fatture) e C (ticket leggero,
notifiche email) sono backlog separati.

**Modello** (`models.py`): `ClientPortalAccess` nuovo:
- `client_id` FK (cliente associato)
- `email`, `full_name` (identità)
- `token` (random 64-hex unique, magic link)
- `project_scope` JSON opt (lista project_id; null = tutti del client_id)
- `expires_at`, `is_active`, `revoked_at`, `last_seen_at`
- `created_by_user_id` (admin che ha generato il link)
SQLAlchemy crea tabella automaticamente; nessuna migration custom.

**Router nuovo** `app/routers/portal.py` prefix `/portal`:
- `POST /portal/api/access` (admin) — crea token + ritorna magic_link
  completo da copiare/inviare al cliente
- `GET /portal/api/access` (admin) — lista accessi attivi con scope
- `POST /portal/api/access/{id}/revoke` (admin)
- `GET /portal/login?token=X` — valida + setta cookie portal_token
  (httponly, samesite=lax, expire=token.expires_at) + redirect /portal/
- `POST /portal/logout`
- `GET /portal/` — dashboard cliente (lista progetti)
- `GET /portal/project/{id}` — scheda progetto (info + milestone + DAM)
- `GET /portal/api/me` — info access corrente (UI debug)

**Auth separata** (`main.py`):
- `PORTAL_PUBLIC_PATHS = ("/portal/login", "/portal/logout", "/portal/",
   "/portal/project/", "/portal/api/me")` — bypassano middleware admin.
- `/portal/api/access*` resta sotto auth admin (creazione/revoca link).
- Auth interna via cookie `portal_token` validato in
  `_resolve_portal_access(token, db)`. Sicurezza: token random 64-hex,
  expires_at check, is_active+revoked_at check.

**Layout pulito**: `portal_base.html` template separato (no sidebar admin,
no copilot, palette ridotta). Tre pagine:
- `portal_login.html`: messaggio chiaro "contatta il tuo referente".
- `portal_home.html`: card progetti del cliente con codice/stato/data.
- `portal_project.html`: scheda con info tecniche + milestone + tabella
  DAM con bottone Scarica per ogni asset.

**Permessi**:
- Cliente vede SOLO progetti del suo `client_id` (filter SQL hardcoded).
- Se `project_scope` valorizzato → ulteriormente ristretto.
- Niente endpoint mutator: portale è solo lettura.
- DAM download usa endpoint esistente `/dam/download/{id}` — il file_path
  è già protetto da TPN access ma il portale cliente bypassa il middleware
  admin... ATTENZIONE: per fase B serve gate su /dam/download/{id}
  che verifichi anche `portal_token` per asset di progetti accessibili.

**E2E test**: admin creato access per cliente "Media Path S.a.s." →
magic_link generato → curl GET portal/login?token=X → 200 con
portal_home renderizzato.

## v3.5.0-alpha.96 — Capability AI #9b filesystem scan + #9d web cross-check (13 maggio 2026)

Da scoping 13 mag punto #9: 2 capability AI di basso rischio + alto riuso
codice.

**#9b — Filesystem scan generico → Asset DAM import** (`dam.py`,
`fs_scan.html`, `models.py`, `main.py`):
- `Tenant.fs_scan_allowed_paths` JSON list — whitelist obbligatoria per
  sicurezza (no arbitrary FS access). Default vuoto. Auto-migrate idem.
- Endpoint `POST /dam/api/fs-scan`: valida path vs whitelist + chiama
  `walk_filesystem()` (servizio esistente α.75) + classifica file per
  asset_type via `resolve_asset_type(mime)`. NO DB write — preview JSON.
- Endpoint `POST /dam/api/fs-import`: registra Asset DAM per i file
  selezionati. **NON copia** il file (file_path punta al path originale,
  utile per NAS/dischi montati). Tenant scope + path-traversal check.
- Pagina nuova `/dam/fs-scan`: wizard 2-step (scan path → tabella file
  classificati per tipo con filter/search/checkbox → import bulk). KPI
  cards file_count/total_size/selected_count. Whitelist mostrata + alert
  rosso se vuota.
- Sidebar: subitem "Scan filesystem" sotto "Asset Library".

**#9d — Web cross-check progetti/clienti** (`web_crosscheck.py`,
`projects.py`, `clients.py`, `project_detail.html`, `clients.html`):
- Service nuovo `app/services/web_crosscheck.py`: funzioni
  `check_project(p_data)` e `check_client(c_data)` confrontano dati DB
  con info pubbliche (IMDB, BoxOffice, Variety, MyMovies per progetti;
  Cerved, LinkedIn, news per clienti). Strategia in cascata identica a
  client_enrichment: native web search → Tavily → knowledge-only.
- Output normalizzato: `{differences: [{field, current, suggested,
  confidence, source, rationale}], external_info: {imdb_url, awards,
  box_office_usd, distribution_countries, ...}, sources: [...]}`.
- Endpoint `POST /projects/api/{id}/cross-check` + `POST
  /clients/api/{id}/cross-check`. NO DB write — preview interattiva.
- UI: bottone "🔍 Cross-check" topbar `/projects/{id}` + footer modal
  cliente in `/clients`. Apre modal con lista differences (current vs
  suggested + confidence badge + rationale) + external_info pre-formattata.

**+1 colonna auto-migrate**. **+4 endpoint**. **+1 pagina HTML** (fs_scan).
**+1 service** (web_crosscheck).

## v3.5.0-alpha.95 — Fase 5 capitolato import + Fase 3 enrichment workflow approval (13 maggio 2026)

Cantiere "Fase 5 + Fase 3" da scoping 13 mag (chiusi simultaneamente).

**Fase 5 — Import capitolato → matching listino → Quote bozza**
(`delivery_templates.py`, `capitolati_import.html`, `base.html`):
- Endpoint nuovo `POST /delivery-templates/api/parse-and-match`: upload
  PDF/docx/xlsx → estrae testo → `parse_deliverables` (AI) →
  `parse_delivery_template` (8 blocchi opzionali, toggle) →
  `match_deliverables_to_pricelist` (AI confidence high/medium/low).
  Ritorna payload combinato: deliverables + match per indice + 8 blocchi +
  stats (matched/unmatched/high_conf). No DB write.
- Endpoint nuovo `POST /delivery-templates/api/create-quote-from-deliverables`:
  Quote.draft + N QuoteLine linkate ai price_item_id matchati. Numero
  auto `Q-{anno}-NNN`. Sezioni A/B/C dal parser. unit_price ereditato
  da PriceItem.price_list se non override. source_hint =
  "capitolato_ai_import".
- Pagina nuova `/delivery-templates/import`: wizard 3-step (upload →
  preview tabella matching con override qty/unit/price/section + filtro +
  checkbox include → genera quote bozza). Stat cards 4 KPI. Accordion
  blocchi DeliveryTemplate. Salva-solo-template alternativa.
- Sidebar: subitem "Import → Quote" sotto "Capitolati".
- E2E test su `CA_Tech_Meta_Cheat_Sheet.docx` reale → 200 OK in 64s
  (call AI inclusa), preview popolata correttamente.
- **Fix bug pre-esistente**: `requires_permission("edit_settings")` in
  delivery_templates.py usava permesso INESISTENTE nel catalogo
  (residuo pre-α.66.15.3). Tutti i POST `/api/parse`, `/api/save` ecc.
  erano silenziosamente broken con 403. Corretto a `manage_settings_global`.

**Fase 3 — Enrichment cliente workflow approval**
(`clients.py`, `clients.html`):
- Endpoint nuovo `POST /clients/api/{id}/enrich-preview`: chiama
  `enrich_client()` ma ritorna preview campo-per-campo (current vs
  proposed + differs flag) SENZA salvare.
- Endpoint nuovo `POST /clients/api/{id}/enrich-apply`: applica i campi
  selezionati. Accetta `fields_json` `{field: value, ...}`. Whitelist
  dei 15 campi cliente ammessi. Set `ai_enriched=True` + timestamp.
- `aiEnrich()` UI riscritto: prima chiamava `/enrich` (one-shot, applica
  tutto). Ora chiama `/enrich-preview` → mostra modal interattivo
  costruito al volo via DOM (no innerHTML, XSS-safe) con checkbox + input
  editable per ogni campo. L'utente può:
  - Vedere current vs proposed side-by-side
  - Deselezionare campi sbagliati (default checked se differs)
  - Modificare il valore proposto prima di applicare
  - Vedere fonte (🌐 web search vs 🧠 knowledge AI)
- Vecchio endpoint `/enrich` mantenuto back-compat (usato dal bottone
  "Crea + popola con AI" in flow create-and-enrich).

**No DB migration**. **+4 endpoint**. **+1 pagina HTML**.

## v3.5.0-alpha.94 — Timeline tema chiaro + spedizioni v2 (voce listino + markup) + vista lista batch (13 maggio 2026)

3 task da feedback Matteo post-α.93:

**Timeline tema chiaro** (`main.css`, `planning.css`):
- Bug root: `--bg-elev` usato in 10+ punti (planning.css cards, hr.html
  totalizzatori) ma MAI definito in nessun tema → fallback hardcoded
  `#1a1d29` (scuro) anche su Sand/Paper/Linen/Sage. Causa "rettangoli
  neri" visibili nello screenshot 10.50 di /hr su tema chiaro.
- Fix: `--bg-elev: var(--surface)` in `:root`. Tutti i temi ereditano.
- Audit color hardcoded in planning.css:
  - `.vis-labelset .vis-label color: #f5f5f5` → `var(--text)`
  - `.tl-res-name color: #ffffff` → `var(--text)`
  - `.tl-res-role color: #9aa0b8` → `var(--text2)`
  - `.vis-labelset .vis-label.vis-nesting-group color: #d4daff` →
    `var(--indigo)` (era azzurro chiaro invisibile su sfondo light)
  - `.vis-time-axis .vis-text.vis-major color: #cdd5ff` → `var(--indigo)`
  - `.vis-time-axis .vis-grid border-color` → `var(--border)`
  - `.vis-time-axis .vis-grid.vis-major border-color` → `var(--indigo-border)`

**Spedizioni v2 — voce listino + markup quote** (`models.py`,
`physical_assets.py`, `projects.py`, `assets_inout.html`, `main.py`):
- `Project.shipping_markup_pct` (default 15.0, server_default "15.0").
  Auto-migrate ALTER TABLE idempotente.
- Helper `_get_or_create_shipping_price_item(db)`: PriceCategory
  "Spedizioni" + PriceItem "Spedizione standard" auto-creati al primo
  use. La JCL auto-generata linka a questo `price_item_id`. Risultati:
  cost report raggruppa per categoria, BillingBatch eredita name in
  fattura SDI.
- Markup applicato in `create_shipment`: `unit_price = shipping_cost *
  (1 + markup/100)`. Description include nota "+15% ricarico". Notes
  JCL trasparenti: "Costo vettore €X; markup Y% → riaddebito €Z".
- UI modal Shipment: campo "Ricarico %" accanto al dropdown progetto.
  Pre-popolato leggendo `Project.shipping_markup_pct` (GET dettaglio
  project). Al submit, se diverso da originale, PUT su Project per
  persistere. `PUT /projects/api/{id}` accetta ora i nuovi field
  `billing_frequency` e `shipping_markup_pct`.
- `GET /projects/api/{id}` espone `shipping_markup_pct` e
  `billing_frequency` (mancavano).
- Smoke test: shipment con cost=100€ → JCL #8630 con unit_price=115€,
  description "[Spedizione] BATCH-2026-043 — DHL — TRK77 — +15% ricarico",
  linkata a PriceItem #44 (categoria PriceCategory #13 "Spedizioni").

**Vista lista IngestBatch / Spedizioni** (`physical_assets.py`,
`assets_inout.html`):
- Endpoint nuovo `GET /physical-assets/api/ingest-batches` con filtri
  direction / shipping_payer / project / client / period / has_cost.
  Ritorna `{items, total_cost, total_charged_to_client, count}` con
  totale riaddebitato calcolato applicando il markup per progetto.
- Tab "🚚 Spedizioni" affiancata a "📋 Movimenti" in /assets/inout.
  3 KPI cards (Spedizioni totali / Costo vettori / Riaddebitato cliente)
  + filtri direzione/payer + checkbox "Solo con costo > 0" + tabella
  sortable con badge direzione + payer + link a JCL (apre cost-report).
- Bottone "🚚 Nuova spedizione" anche nel tab Spedizioni (duplicato
  topbar per discovery).
- Fix route order (stesso bug T3 α.92): `/api/ingest-batches`
  spostata sopra `/api/{asset_id}` per evitare 422 int_parsing.

**+1 colonna auto-migrate**, **+1 endpoint** (`/ingest-batches` GET),
**+2 field opzionali** su PUT projects.

## v3.5.0-alpha.93 — Spedizioni con costi + ricarico cliente (13 maggio 2026)

Risposta a feature request Matteo 13 mag: le spedizioni vanno tracciate
come entità di prima classe con costo, payer (chi paga) e ricarico
automatico al cliente in fatturazione. Modal multi-asset per raggruppare
più colli in una sola spedizione.

**Modello** (`models.py`): esteso `IngestBatch` (era già il punto di
raggruppamento dei movimenti) con campi shipping:
- `carrier` / `tracking_number` / `shipping_cost` — vettore + costo a
  livello batch (non solo per-movement come prima)
- `shipping_payer` — `internal` (costo nostro, no riaddebito) /
  `client_direct` (cliente paga direttamente al vettore) /
  `charged_to_client` (anticipiamo, riaddebitiamo in fattura)
- `pickup_mode` — `we_ship` (noi spediamo) / `client_carrier_pickup`
  (cliente manda corriere a ritirare) / `client_in_person`
  (cliente ritira di persona)
- `billable_to_project_id` — FK Project per il riaddebito
- `auto_billed_jcl_id` — FK JobCostLine generata per back-reference

**Auto-migrate** (`main.py`): 7 ALTER TABLE idempotenti su `ingest_batches`
al boot. Test sul DB esistente OK.

**Endpoint nuovo** `POST /physical-assets/api/shipments`:
- Crea 1 IngestBatch + N AssetMovement (uno per asset selezionato,
  physical o digital) con stesso DDT/carrier/tracking
- Se `shipping_payer=charged_to_client` AND `billable_to_project_id` valido
  → crea JobCostLine sul primo Job attivo del project, categoria
  `[Spedizione]` nel description, `is_extra=True`, `billing_status=not_billed`.
  Tracciato in `IngestBatch.auto_billed_jcl_id`.
- Transazione singola: se la JCL fallisce (es. nessun Job nel project),
  l'intero batch viene ribaltato e ritorna 400 esplicito.
- 400 anche per `shipping_payer=charged_to_client` senza
  `billable_to_project_id` o `shipping_cost <= 0`.

**UI modal `🚚 Nuova spedizione`** (`assets_inout.html`):
- Bottone topbar in `/assets/inout` (ingest/outgest esistenti restano).
- Form a fieldset chiari: direzione + DDT, vettore+costo, pickup_mode
  radio, payer radio, dropdown progetto (visibile solo se charged_to_client).
- Asset selector: search bar + lista compatta con header per natura
  (fisici + digitali), checkbox toggle, badge tipo. Pool 300 fisici +
  200 digitali più recenti (limit param aggiunto a `/physical-assets/api`
  e `/dam/api/assets`).
- Counter "Selezionati: N" + submit disabilitato se 0.
- Toast successo include numero JCL generata quando ricarico attivo.

**Smoke test E2E**:
- Internal: `POST /shipments {payer=internal, 2 physical}` → batch 201,
  2 movimenti, no JCL.
- Charged: `POST /shipments {payer=charged_to_client, project_id=1, cost=80€}`
  → batch 202, 1 movimento, JCL #8629 `[Spedizione] BATCH-2026-042 — BRT
  — TRK888` total_accrued=80€, billing_status=not_billed, is_extra=True.

**Decisioni di default** (backlog evolutivo se serve):
1. Costo a livello batch (non split per asset). Edit movement singolo
   resta possibile via API esistente.
2. 1 shipment = 1 progetto per ricarico. Split pro-quota tra progetti
   diversi rimandato.
3. JCL category derivata dal description prefix `[Spedizione]` (no
   `category_override` su JCL, no price_item dedicato auto-creato).
4. JCL sul primo Job attivo del project (più recente per `created_at`).
   Se nessun Job → 400.

**393 routes** (+1 endpoint). **+7 colonne** auto-migrate.

## v3.5.0-alpha.92 — 6 task Matteo 13 mag (compose-invoice fix + drawer storico + light themes + sezioni quote) (13 maggio 2026)

Risposta a 6 punti aperti da Matteo: 1 fix bloccante + 5 enhancement.

**T3 compose-invoice "Errore sconosciuto" fix bloccante** (`billing.py`,
`global.js`, `base.html`):
- Causa: `@router.get("/{batch_id}")` (line 487) era definita PRIMA di
  `@router.get("/composable-batches")` (line 1086). FastAPI matcha le route
  per ordine di registrazione → `composable-batches` parsato come
  `batch_id="composable-batches"` → 422 `int_parsing`.
- Fix: spostata `composable-batches` SOPRA `/{batch_id}` (le route specifiche
  vanno prima delle catch-all). Audit altri router: nessun altro caso.
- Bonus: `global.js _parseError` ora gestisce array `detail` di Pydantic
  (422) — pre-α.92 cadeva in "Errore sconosciuto". Concatena
  `[loc] msg · …` per UI leggibile.

**T6 suppliers sort + filtro fatture scadute** (`suppliers.html`):
- `<table class="mf-sortable">` su tab Fatture e Anagrafica → click `<th>`
  ordina (auto-attivato da `mfEnableSortableTables` global).
- Chip `Solo scadute` (checkbox) filtra `due_date < today` AND
  `payment_status in (unpaid, partial)`. Reset incluso.

**T1 In/Out asset → drawer storico** (`assets_inout.html`,
`physical_assets.py`):
- Click su riga apre drawer laterale 420px (slide-right) con timeline
  verticale di TUTTI i movimenti di quell'asset (no limit della lista
  globale). Card per movimento: tipo, DDT, data, from→to, contenuto,
  tracking, stato confermato, link PDF.
- Endpoint nuovo `GET /physical-assets/api/movements/by-asset?
  physical_asset_id=&asset_id=` — accetta solo uno dei due (mutex).
- Link "→ Asset fisico" nel drawer rimanda a `/physical-assets#a-{id}`
  per il dettaglio supporto.
- ESC chiude drawer. `_movement_dict` ora include `asset_id` per UI.

**T2 PhysicalAsset Contents tab + seed simulato**
(`physical_assets.html`, `scripts/seed_asset_memberships.py`):
- Sezione "📦 Contenuti del supporto" nel modal Edit PhysicalAsset:
  tabella file presenti (`AssetMembership.removed_at IS NULL`) con
  path, dimensione, data aggiunta.
- Checkbox "Mostra anche storico rimosso" → mostra anche file passati
  (riga opacity 50% + data rimozione in rosso).
- Counter "N presenti · M rimossi" in summary.
- Endpoint pre-esistente `/api/{asset_id}/contents` (era già pronto
  da α.74). Solo UI nuova.
- Script seed `scripts/seed_asset_memberships.py` popola 40 PhysicalAsset
  con 3-10 file ciascuno, mix presente/rimosso 60/40. Path realistici
  per kind (LTO=/DPX_GRADED/, HDD=/DCP/, CRU=/RAW_DAILIES/, ecc.).
  Idempotente: salta asset già popolati salvo `--force`.

**T5 3 nuovi light themes + color-scheme fix** (`main.css`, `global.js`):
- Aggiunti `.theme-paper` (bianco neutro, accent slate), `.theme-linen`
  (off-white caldo, accent terracotta), `.theme-sage` (verde salvia tenue,
  accent verde scuro). Già esisteva `.theme-sand`.
- Bug fix: `color-scheme: dark` era hardcoded su `.form-input/.form-select`
  per TUTTI i temi → dropdown nativi neri su tema chiaro Sand (screenshot
  Matteo confermava). Ora override `color-scheme: light` per
  `.theme-sand/paper/linen/sage`. `option` background usa `var(--surface)`
  invece di fallback hardcoded.
- Aggiornati `MF_THEMES` array + `MF_THEME_META` swatches in topbar
  palette popover (cycle + selettore).

**T4 Quote sezioni: modal pulito + badge per riga** (`quotes.html`):
- `section_label` esisteva dal α.27 ma editing via `prompt()` browser
  nativo (poco scopribile). Sostituito con modal `modal-line-section`:
  - chip cliccabili con sezioni già presenti nella quote (suggerimenti)
  - input testo libero con `<datalist>` autocomplete
  - bottone "Rimuovi sezione" dedicato
- Badge `📦 Nome sezione` ora visibile su OGNI riga (era solo
  nell'header del gruppo). Click sul badge riapre il modal — ovvio.
- Funzione `editLineSection` ora apre modal invece di prompt.
  `saveLineSection` + `clearLineSection` con UX coerente.

**392 routes** invariato (T3 sposta, T1 aggiunge `by-asset`).
**+1 script seed** standalone.



Multi-audit lanciato pre-push (3 agent code-reviewer paralleli su α.88/89/90).
Risultati applicati:

**P0 forecast redirect drop fragment** (`finance.py`, `cashflow.html`):
- `/finance/forecast` ritornava `RedirectResponse(url=".../#forecast", 302)`.
  Browser strippano il fragment dal Location header (RFC 9110) → atterravano
  sempre sul tab Cassa. Ora redirect a `?tab=forecast` (query param sopravvive
  al 302), JS legge sia `?tab=forecast` che `#forecast` (back-compat).

**P0 AnomalyEntry dedup_key no UNIQUE** (`models.py`, `main.py`):
- Modello aveva `index=True` ma non `unique=True` né `UniqueConstraint`.
  Detect paralleli passavano il check `db.query().first()` e creavano duplicati.
- Aggiunto `__table_args__ = (UniqueConstraint("tenant_id", "dedup_key"),)`.
- Auto-migrate: CREATE UNIQUE INDEX su DB esistenti + DELETE duplicati
  pre-fix (mantiene riga MIN(id) per coppia tenant+dedup).

**P1 mancato_recupero project_id NULL** (`anomaly_detector.py`):
- `detect_mancato_recupero` settava sempre `project_id=None` (Invoice non
  ha project_id diretto). `_handle_single(write_off_loss)` richiede project_id
  → 400 garantito per ogni invoice scaduta.
- Ora deriva da `inv.job.project_id` quando job linked.

**P1 DAM tag CSV duplicate rows** (`dam.py`):
- `query.join(AssetTag).join(Tag).filter(in_(tag_names))` ritorna 1 riga per
  tag matching (asset con 2 tag richiesti → 2 righe). Refactor a
  `exists()` subquery: 1 riga per asset.

**P1 compose_invoice billed_amount accumulo** (`billing.py`):
- `jcl.billed_amount += bl.total_approved` (asimmetrico vs emit_invoice
  singolo che fa `=`). Storico cumulativo già vive in JCLBilledSlice;
  `billed_amount` deve essere snapshot ultimo. Ora overwrite.

**P1 compose_invoice race su Invoice.number** (`billing.py`):
- IntegrityError grezzo → 500. Ora wrap commit in try/except, restituisce
  409 dedicato.

**P2 lasciati per next iteration**:
- `todoEditBooking` synthetic items missing `id`/`assignment_id` (undo/copy
  rotti per quei item)
- `extra_after_billed` no `is_active=True` filter (soft-deleted JCL generano
  anomalie spurie)
- `reopen` non resetta `handled_target_id` (orphan LossEntry/OverheadCost
  se reopen+re-handle)
- `mfEnableSortableTables` no `stopPropagation` (può triggerare `<tr onclick>`
  parenti dopo il sort)

7 file. +1 UNIQUE constraint. 392 routes invariato.

## v3.5.0-alpha.90 — Accrual billing + 4 fix ticket Matteo 13 mag (13 maggio 2026)

Risposta a 4 ticket Matteo notte 12 mag.

**C1 — Lista fatture+batch cross-show progetto/cliente**
- `/finance/api/invoices` ora ritorna dict arricchito con `project` (via
  Job.project) e `job`. Era ORM raw, mancava il progetto in lista.
- Lista batch espone `client_id`/`client_name` (via Project.client).
- Tabelle UI estese con colonne corrispondenti.

**C2 — Accrual billing (richiesta strategica Matteo)**
Pre-α.90: 1 batch = 1 fattura. Producer trasmette batch → manager approve →
fattura emessa immediatamente.

α.90: batch approvati restano "in cassetto" finché amministrazione decide
di comporre fattura aggregata (mensile/trimestrale/custom).

- Modello: `Project.billing_frequency` (default `monthly`, valori
  monthly/quarterly/milestone/on_completion/custom). Auto-migrate.
- Endpoint nuovo `POST /finance/api/billing/compose-invoice`:
  prende project_id + periodo + invoice_number → trova tutti i batch
  approved del project nel periodo (o batch_ids esplicito) con
  invoice_id IS NULL → crea 1 Invoice unica con N InvoiceLine + N
  JCLBilledSlice + linka tutti i batch (status→invoiced).
- Endpoint nuovo `GET /finance/api/billing/composable-batches` anteprima
  batch in cassetto per UI prima della conferma.
- UI modal "📦 Componi fattura periodo" in /finance:
  select progetto, periodo, anteprima live, numero/data/IVA.
- Vecchio `POST /billing/{id}/invoice` (1-batch) resta per casi semplici.

**C3 — Cost report list sort fix**
- Refactor `mfEnableSortableTables` da listener per-TH a event delegation
  globale (`document.addEventListener('click')`). Risolve casi in cui
  l'ordine di init faceva perdere gli handler con tabelle innerHTML-replaced.
- Una sola registrazione listener globale via flag `window.__mfSortDelegated`.

**C4 — Cashflow filtri cliente/progetto invisibili**
- Filtri spostati dalla topbar (clippati a ≤1440px dal gap+theme+bell) a
  card dedicata sopra le tab. Width totale 730px+, sempre visibili.

**File toccati**: 8 (models.py, main.py, base.html, finance.py, billing.py,
finance.html, cashflow.html, global.js, CHANGELOG.md, STATO.md).
+1 colonna `projects.billing_frequency`. 392 routes (+2).

## v3.5.0-alpha.89 — Sprint S4 Workflow anomalie fatturazione (12 maggio 2026, notte)

Stateful workflow per anomalie fatturazione (era stateless, riemergeva a ogni
refresh senza track). Tassonomia confermata da ticket Matteo 12 mag.

**Modello nuovo `AnomalyEntry`** (`app/models/models.py`):
- `anomaly_type` enum 5 valori: extra_after_billed, sforamento_monte_ore,
  quote_discrepancy, mancato_recupero, over_budget
- `source_kind` polymorphic (jcl/job/invoice/supplier_invoice/billed_slice) + `source_id`
- `dedup_key` = `{type}:{kind}:{id}` univoca per tenant → idempotenza re-detect
- `status` open/handled/dismissed
- `handled_action` enum: rimanda_commerciale, rivaluta_producer, write_off_loss, overhead_cost
- `handled_target_kind/_id` per tracciare LossEntry o OverheadCost creati
- Denormalizzati: project_id/job_id/client_id/amount/description per query veloci

**Detector service** (`app/services/anomaly_detector.py`):
- 5 funzioni `detect_*` idempotenti (upsert per dedup_key)
- `detect_all()` esegue tutti + commit unico
- `extra_after_billed`: JCL con `quantity_actual` > Σ slice fatturate
- `sforamento_monte_ore`: JCL non-extra con actual > quoted
- `over_budget`: JCL is_extra=True (extra puri)
- `mancato_recupero`: Invoice due_date < oggi AND not paid/cancelled
- `quote_discrepancy`: Job con consuntivo vs budget oltre ±15%

**Router `/finance/api/anomalies/v2`** (`app/routers/anomalies.py`):
- `GET /v2` lista con filtri (status, type, project, client, period)
- `GET /v2/summary` KPI per tipo (open only)
- `POST /detect` re-scan idempotente
- `POST /{id}/handle` applica azione singola
- `POST /bulk-handle` multiselect (CSV ids + action + notes)
- `POST /{id}/dismiss` chiudi senza azione
- `POST /{id}/reopen` riapri handled/dismissed → open

**Azioni operative**:
- `rimanda_commerciale` / `rivaluta_producer`: solo cambio stato workflow + audit
- `write_off_loss`: crea LossEntry(amount, reason=written_off, project) + linka handled_target_id
- `overhead_cost`: crea OverheadCost(category=other, code OH-YYYY-NNNN) + linka handled_target_id

**RBAC**: 2 nuove permission `view_anomalies` + `handle_anomalies` in categoria
Finanza. Admin auto-resync via ALL_PERMISSION_KEYS.

**UI `/finance` tab Anomalie** (`finance.html`):
- Sostituita vista legacy (4 tabelle separate stateless) con tabella unica stateful
- 4 chip status (Open default / Handled / Dismissed / Tutte) + 6 chip type filter
- Bottone "🔄 Rileva" per re-scan on-demand
- Multiselect checkbox + bulk action bar (action select + notes inline)
- Per-riga: bottone azione singola (prompt-based per ora; in roadmap modal dedicato)
- Bottone "↺ Riapri" per anomalie chiuse
- Refactor da innerHTML → DOM helpers (security hook compliant)

**Migration**: zero ALTER. `create_tables()` crea `anomaly_entries` automaticamente
al primo boot (modello nuovo, no FK retroattive).

Endpoint legacy `/finance/api/anomalies/{floating-jobs,discrepancies,overdue-supplier,summary}`
restano attivi (back-compat); UI ora usa solo v2.

385+5 routes (+5 endpoint v2). 1 nuova tabella.

## v3.5.0-alpha.88 — Maratona feedback Matteo 12 mag (9 batch) (12 maggio 2026)

Risponde alla lista di 26 ticket UX/funzionali post-test Matteo. 9 batch eseguiti
in serie (B1→B9). Nessuna nuova feature di dominio: tutto consolidamento.

**B1 — Cost Report layout** (`cost_report.html` + `cost_report.py` + `main.css`)
- KPI compatti: nuova classe `.stat-grid-compact` (12 KPI in 1 riga su ≥1480px)
- Risorse assegnate al progetto MOSSE sopra il quadro economico
- Voci di costo FULL WIDTH (era 50% in `grid-2` → overlap orizzontale con Ore booking)
- Card "Ore lavorate (consuntivo)" RIMOSSA (era sempre vuota da α.66.66)
- Click risorsa in "Ore booking per fascia" → filtra solo job del progetto corrente
  (param `project_id` opzionale su `/cost-report/api/resource/{id}/jobs`)
- `currentReport.job.project_title` esposto per scope label drill

**B2 — Cashflow + Forecast accorpati** (`cashflow.html` + `finance.py` + `base.html`)
- Pagina `/finance/cashflow` con 2 tab: Cassa (default) + Forecast / Pipeline
- Filtri topbar condivisi (anno, granularità, cliente, progetto)
- Forecast lazy-load al primo switch tab; deep-link `#forecast`
- `/finance/forecast` → 302 redirect a `/finance/cashflow#forecast` (back-compat)
- Sidebar: voce "Forecast / Pipeline" rimossa (accorpata in "Cashflow & Forecast")
- Fix dropdown anni bianco-su-bianco: `color-scheme: dark` + option color esplicito

**B3 — Fatture filtro scadute** (`finance.py` + `finance.html`)
- Param `only_overdue: bool` su `/finance/api/invoices` — match dinamico
  (`due_date < today AND status NOT IN (paid, cancelled)`), più ampio del
  marker `overdue` esplicito
- Checkbox "Solo scadute (due_date passata)" affiancato al select stato

**B4 — Anomalie filtri working** (`finance.html`)
- 4 chip toggle (Job orfani / Sforamenti / Extra / Fatt. pass. scadute)
- Click = toggle visibilità card; doppio-click = isola quella categoria
- Bottone Reset; default all-on
- Hint chiarisce quando "Job orfani" compaiono (Job senza Quote linkato — rari)

**B5 — Asset Library/InOut/Fisici filtri** (`dam.html` + `dam.py` +
`physical_assets.html` + `physical_assets.py`)
- DAM: param `tag` accetta ora CSV (multi-select ANY-match)
- Modal "🎯 Filtri avanzati" con search box + lista tag scrollable + multi-select
  tipo asset; chip riepilogo tag attivi sotto i filtri principali
- Physical Assets: aggiunti filtri `client_id` (via owner OR project.client),
  `q` (search label/serial/barcode), `from_date`/`to_date` su `/physical-assets/api`
- UI Physical Assets: barra MFFilterBar (cliente/progetto/periodo) + search box

**B6 — Liste sort by header** (`global.js` + `main.css` + 11 templates)
- Helper `mfEnableSortableTables()` in global.js. Tabelle con classe
  `mf-sortable` ricevono click-to-sort su ogni `<th>` (toggle asc/desc).
  Auto-detect numerico/date/stringa. Override via `data-sort-value` su `<td>`,
  skip via `data-no-sort="true"` su `<th>`. MutationObserver per tabelle
  rese asincronamente.
- Indicatori visivi `▲▼⇅` (CSS `.mf-th-sortable` + `.sorted-asc/desc`)
- Applicata a: clients, projects, departments, overhead, pricelist,
  delivery_templates, cost_report list, physical_assets, assets_inout,
  finance.invoices/batches/timesheets/anomalies (4 tabelle)

**B7 — Booking edit popup** (`planning.html`)
- Bottone "✏ Modifica booking" nel popup `modal-todo-detail` (Storyboard /
  Per progetto / Le mie / Dashboard / drilldown job)
- Funzione `todoEditBooking()` sintetizza `window._tlBookings` items via
  `/planning/api/bookings/{id}/detail` se cache vuota, poi chiama
  `tlbOpenEdit(bookingId)`. Nascosto nel drilldown lista.

**B8 — Timeline perf + visioni + legenda + filtri** (`planning.html`)
- Legenda estesa: 🏖 Ferie / 🏥 Malattia / 🎉 Festività + 🛌 Weekend con pattern
  tratteggiato 45° illustrato; spiegazione "hard-block vs soft-block"
- Filtro "Nascondi non fatte" spostato in sezione "Opzioni" con divider HR,
  label allineata ai filtri sopra (era fuori griglia visiva)
- Drop multi-move: optimistic incremental `itemsDS.update(updates)` invece di
  full `renderTimeline(true)` — lag drag/drop da 5-6s a <100ms
- Light mode + heatmap dedup già esistenti per perf

**B9 — Hyperlink + bordi polish** (`main.css`)
- Anchor `:not(.btn)` dentro card/table-wrap: underline dotted + solid on hover
- Classe esplicita `.mf-link` per nomi cliccabili senza ambiguità
- Bordo doppio card+table evitato (table `border:0` dentro card)

**File toccati**: cost_report.html, cost_report.py, main.css, base.html, main.py,
finance.py, finance.html, cashflow.html, dam.html, dam.py, assets_inout.html,
physical_assets.html, physical_assets.py, planning.html, global.js, +6 list pages
con `mf-sortable`.

No DB migration. 385 routes (invariato).

## v3.5.0-alpha.87 — Sprint S8 Pozzo costi / Spese aziendali (OverheadCost) (12 maggio 2026)

Risponde a cluster D.2 ticket Matteo: "Pozzo costi generici = database costi
non fatturabili (esterno) — manutenzione, lavorazioni in perdita, licenze
software, piani investimenti, acquisizioni. Rientra nel quadro finanziario
globale."

Architettura: design B (modello standalone). Naming: `OverheadCost` (codice),
UI italiano "Spese aziendali". Write-off NON in OverheadCost — restano in
LossEntry (single source of truth). Reportistica aggrega via UNION.

**Modello nuovo `OverheadCost`** (app/models/models.py):
- `code` auto-num OH-YYYY-NNNN univoco
- `category`: enum 11 valori (maintenance, software_license, rent_utilities,
  staff_overhead, capex, training, marketing, legal_admin, bank_fees, tax,
  other)
- `amount_net` + `vat_rate` + `amount_vat` + `amount_total`
- `cost_date` per competenza
- **Ricorrenti**: `is_recurring`, `recurrence_interval` (monthly/quarterly/
  yearly), `next_due_date`, `parent_recurring_id` (template self-ref)
- **CAPEX**: `is_capex`, `useful_life_months`, `amortization_method`
  (linear/accelerated), `asset_acquisition_date`
- FK contestuali (tutte opzionali): department, supplier, supplier_invoice,
  booking, physical_asset, source_project — per auto-feed
- Soft-delete: `deleted_at`/`deleted_by_user_id`

**Tenant**: nuovo campo `capex_threshold_eur` (default 500€) — soglia
configurabile sotto cui PhysicalAsset acquisito non genera CAPEX automatico.

**RBAC**: 2 nuove permission `view_overhead` + `edit_overhead` in categoria
"Finanza". Preset admin (re-sync auto da ALL_PERMISSION_KEYS) + manager +
accounting hanno entrambe; producer ha solo view.

**Router `/overhead`** (app/routers/overhead.py):
- `GET /overhead/` HTML page
- `GET /api` lista con filtri (category/department/supplier/from_date/to_date/
  is_capex/is_recurring/q)
- `GET /api/summary` KPI aggregato per categoria + opex/capex/write_off
  (UNION LossEntry per quadro completo non-billable)
- `POST /api` create
- `PUT /api/{id}` update
- `DELETE /api/{id}` soft-delete
- `GET /api/categories` lista enum + label IT per dropdown

**UI page `/overhead/`** (app/templates/pages/overhead.html):
- Topbar "+ Nuova spesa" button
- MFFilterBar standard (categoria + periodo)
- KPI grid 5 card (Totale, OPEX, CAPEX, Write-off LossEntry, Ricorrenti)
- Breakdown per categoria (grid card colorate)
- Tabella sortable con flags CAPEX/recurring
- Modal create/edit con form completo (recurring + CAPEX conditional fields,
  recalc IVA live)
- Sidebar link "💸 Spese aziendali" in sezione Finanza

**Cashflow extension** (`/finance/api/cashflow/{year}`):
- Aggiunti `overhead_paid` + `capex_paid` per mese
- `net_cashflow` ora include anche overhead+capex come outflow

**Migration** `scripts/migrate_overhead_costs.py`:
- Crea tabella overhead_costs (idempotente)
- ALTER tenants ADD capex_threshold_eur
- Backfill opzionale `--backfill` da PhysicalAsset (> soglia tenant) + da
  SupplierInvoice senza project/job

**Cache-buster bump**: main.css + global.js ?v=3.5.0-alpha.87.

385 routes (+7). 1 nuova tabella, 1 colonna su tenants.

## Sprint S7 — Claude Code plugin ecosystem per workflow finanziario (12 maggio 2026, config-only)

NON tocca codice MediaFlow runtime. Configura ecosistema Claude Code per
accelerare sviluppo future feature finanziarie + sbloccare SDI/fatturapa.

**MCP server `mcp-fattura-elettronica-it`** (locale, no API esterna):
- 21 tool per ciclo XML FatturaPA v1.6.1 conforme SDI.
- Header (7): build_transmission_header, validate_cedente/cessionario, P.IVA
  checksum, generate_progressivo_invio, lookup_codice_destinatario, etc.
- Body (7): build_dati_generali, get_tipo_documento_codes, add_linea_dettaglio,
  compute_totali, get_natura_codes, build_dati_pagamento, add_allegato.
- Global (7): generate_fattura_xml, validate_fattura_xsd, parse_fattura_xml,
  export_to_json, validate_partita_iva_format, get_sdi_filename,
  check_ritenuta_acconto.
- Config: `.mcp.json` project-scoped + `.claude/settings.json` allowlist
  `enabledMcpjsonServers`.
- Launcher: `uvx mcp-fattura-elettronica-it` (uv 0.11.13 installato in
  Python 3.14 user site).

**VoltAgent subagent marketplace** (globale ~/.claude/settings.json):
- Marketplace `voltagent`: `VoltAgent/awesome-claude-code-subagents`.
- 4 plugin enabled: voltagent-lang, voltagent-qa-sec, voltagent-data-ai,
  voltagent-domains. ~60 subagent specializzati (python-pro, sql-pro,
  test-automator, payment-integration, data-engineer, fintech, etc.).

**3 custom skill** project-scoped in `.claude/skills/`:
- `mediaflow-finance-feature-dev`: checklist 13-step per feature finanziaria
  (tenant scope, RBAC, soft-delete, JCLBilledSlice, AI capability, migration,
  filter-bar, notification, test, cache-buster, commit). Encodes patterns
  consolidati α.66+.
- `italian-tax-compliance`: validazione P.IVA mod-10, CF, IBAN mod-97, codici
  RF01-RF19, TD01-TD28, N1-N7, SDI 7-char. Delega validation a MCP quando
  disponibile.
- `sdi-xml-builder`: pipeline 5-step da Invoice MediaFlow → XML FatturaPA
  via MCP tool chain. Defaults per casa post-prod (FPR12, RF01, TD01, MP05,
  TP02). Endpoint `/finance/api/invoices/{id}/sdi-xml` proposto per S8.

No bump versione app (config-only). No DB migration.

## v3.5.0-alpha.86 — Sprint S3 MFFilterBar + filtri standard 5 pagine (12 maggio 2026)

Risponde al cluster C dei ticket Matteo (12 mag): "filtri standard mancanti
in 8+ pagine — fatturazione, fornitori, cost-report, assets, movimenti".

**Helper nuovo `MFFilterBar` in `global.js`**:
- API: `MFFilterBar({host, filters: [spec, ...], onChange})`.
- Filter spec kinds: `autocomplete` (single+multi), `date`, `select`, `text`.
- Filter `dependsOn` per filtri concatenati (project_id rinfresca quando
  client_id cambia).
- Bottone Reset incluso.
- `buildQS()` produce QS pronto per fetch.

**Estensioni server-side (filtri opzionali su API esistenti):**
- `/finance/api/invoices`: +`project_id`, `from_date`, `to_date`.
- `/finance/api/timesheets`: +`client_id`, `project_id`, `from_date`, `to_date`.
- `/finance/api/billing`: +`client_id`, `from_date`, `to_date`.
- `/suppliers/api/invoices`: +`client_id`, `from_date`, `to_date`.
- `/dam/api/assets`: +`client_id`, `from_date`, `to_date`, `tech` (keyword grep).
- `/physical-assets/api/movements/all`: +`project_id`, `from_date`, `to_date`.
- `/cost-report/api/job/{id}/booking-summary`: +`from_date`, `to_date`, `resource_id`.

**Pagine UI aggiornate (S3.1-S3.5):**

**S3.1 — `/finance` (fatturazione)**:
- Barra filtri globale sopra le tab (cliente/progetto/periodo), applicata a
  TUTTI i tab (Fatture, Batch fatturazione, Timesheet, Report P&L, Anomalie).
- `buildFinQS()` helper centralizza query string.

**S3.2 — `/suppliers`**:
- Aggiunti filtri standard cliente/progetto/periodo sopra i filtri esistenti
  (search/fornitore/status).

**S3.3 — `/cost-report` (riordino + filtri ore booking)**:
- **Layout swap**: "Voci di costo: Quotazione vs Reale" + Risorse/Timesheet
  ora SOPRA "Ore booking per fascia" (era invertito, richiesto da Matteo).
- Filtri sezione "Ore booking" via toggle: periodo (from/to) + risorse del job
  (multi-select autocomplete). Filtraggio server-side.

**S3.4 — `/dam` (asset digital)**:
- Filtri standard cliente/progetto/periodo sopra search/type.
- **Filtri tecnici quick chips** (HDR/SDR/Dolby Vision/Atmos/2K/4K/UHD/24fps/
  25fps/ProRes/DCP/IMF): match keyword case-insensitive su `original_name +
  description` (Asset model non ha metadata strutturate; grep su filename).
  TODO futuro: estrarre metadata da `job_deliverable.spec_json` (alpha.66.9).

**S3.5 — `/physical-assets/inout` (movimenti)**:
- Filtri standard cliente/progetto/periodo (project_id filtra via IngestBatch).

**Cache-buster bump**: `main.css?v=3.5.0-alpha.86`, `global.js?v=3.5.0-alpha.86`.

No DB migration. Backwards-compatible: tutti i nuovi parametri sono opzionali.

## v3.5.0-alpha.85 — Sprint S2 MFAutocomplete (cashflow + forecast filters fix) (12 maggio 2026)

Risolve: "Filtro cashflow non mostra clienti e progetti dopo typo. Stessa cosa
in Forecast/Pipeline" — segnalato da Matteo dopo test su dataset stress
(100 clienti, 1000 progetti). Il `<select>` nativo gestito dal helper
`mfMakeSearchableSelect` (auto-attach) era operativo ma l'UX era opaca: nessun
chip visibile, search input non immediatamente focale, browser typeahead
saltava su match ambigui con 100+ opzioni.

**Helper nuovo `MFAutocomplete` in `app/static/js/global.js`**:
- Riutilizza il pattern FA_CONFIG già usato in /planning sidebar (chip+input+suggestions).
- API: `MFAutocomplete({host, hidden, data, search, display, render, placeholder, onChange, multi})`.
- Single OR multi-select via `multi` flag.
- DOM-safe: no `innerHTML` con interpolazione, solo `textContent` + `replaceChildren`.
- Hidden `<input type="hidden">` mantiene il valore (comma-separated per multi).

**CSS classi `mf-ac-*` + `fa-*` spostate in `main.css`** (erano in planning.css → solo
caricato sulla pagina planning). Ora disponibili globalmente.

**Applicato in `cashflow.html` + `finance_forecast.html`**:
- `<select id="cf-client">` → `<div id="cf-client-ac" class="mf-ac">` + hidden.
- `<select id="cf-project">` → idem (filtra dinamicamente per client selezionato).
- Granularità + anno restano `<select>` nativi (3-5 opzioni, OK).
- Cascade: cambiando cliente, autocomplete progetti si aggiorna istantaneamente.

**Cache-buster bump**: `main.css?v=3.5.0-alpha.85`, `global.js?v=3.5.0-alpha.85`.

No DB migration. No breaking change per chi non usa cashflow/forecast.

Planning.html mantiene la sua implementazione inline FA_CONFIG (funzionante) —
migrazione a MFAutocomplete è candidate per cleanup futuro, non urgente.

## v3.5.0-alpha.84 — Sprint S1 Performance planning (12 maggio 2026)

Hot-fix planning sotto carico stress (8.4k booking, 500 risorse). Pre α.84 le
3 viste visuali erano inutilizzabili: calendario impilava 1000+ event in stesse
celle orarie, timeline mostrava 500 row labels senza scroll, agenda caricava
tutto il DB in 1 mega innerHTML.

**S1.0 — Calendario (FullCalendar)**:
- `events:` callback ora passa `info.startStr`/`info.endStr` come
  `from_date`/`to_date` al server — fetch limitato alla finestra visibile.
- Aggiunto `dayMaxEvents: 5` + `slotEventOverlap: false` → overflow "+N altri"
  invece di stacking infinito.

**S1.1 — Agenda**:
- Default range oggi → +30gg se utente non ha specificato `f-from`/`f-to`.
- Render lazy via `IntersectionObserver`: primi 7 giorni eager, restanti come
  placeholder che si auto-hydrano entrando in viewport (rootMargin 300px).
- Sostituito `innerHTML` con DOM API tipata (event listener invece di `onclick`
  string interp).
- Banner informativo con counts.

**S1.2 — Timeline (vis-timeline)**:
- `tlBuildResourceGroups`: con >100 risorse senza filtro dept/risorsa,
  auto-filtra solo risorse con almeno 1 booking nel range (toast informativo).
  Override via `localStorage.setItem('tl_show_all_resources','1')`.
- `vis.Timeline` options: aggiunti `maxHeight` (= height) + `verticalScroll: true`
  per garantire scroll labels quando le risorse superano la viewport.

**S1.3 — Sidebar filtri auto-collapse**:
- `setView()` auto-collapse sidebar su tab `calendar`/`timeline` (viste visuali),
  auto-expand su `jobs`/`agenda`/`todo` (viste tabellari).
- Override: una volta che l'utente preme il toggle manuale, viene marcato
  `pl-filters-collapsed-user-set` in localStorage e la sua scelta vince.

No DB migration. Solo `app/templates/pages/planning.html` + bump versione.

Cantiere apertura ticket Matteo 12 mag (cluster B/C/D/E/F restanti):
- B) bug search dropdown cashflow/forecast (no clienti dopo typo)
- C) `<filter-bar>` riusabile + filtri standard fatturazione/fornitori/cost report
- D) workflow anomalie fatturazione (tassonomia + 3 azioni)
- E) cashflow+forecast merge (Combinato)
- F) asset hub roadmap (long-term, backlog)

## v3.5.0-alpha.78 — Reportistica YoY + proiezioni + export CSV/XLSX (11 maggio 2026)

Pattern QuickBooks/Pennylane/Salesforce Reports: anno-su-anno,
proiezione full-year, export Excel multi-sheet.

**Service nuovo** `financial_reports.py`:
- `year_over_year(year_a, year_b, granularity)`: confronto periodi
  con delta + %. Granularità: month|quarter|year.
- `ytd_projection(year)`: YTD actual + 2 proiezioni:
  - **Linear**: YTD avg × 12 (no seasonality).
  - **Realistic**: YTD + forecast pesato rimanente (combina actual + pipeline).
- `aggregate_quarters` / `aggregate_year` helpers.
- `export_csv` (UTF-8 BOM, separator ;).
- `export_xlsx` multi-sheet (Report + YTD Projection).

**Endpoint nuovi** `/finance/api/reports/*`:
- `GET /comparison?year_a&year_b&granularity` → YoY breakdown.
- `GET /projection/{year}` → YTD + linear + realistic.
- `GET /export.csv?year&granularity` → CSV scaricabile.
- `GET /export.xlsx?year&granularity` → Excel multi-sheet.

**Refactor**: `cashflow_year` → sync core `cashflow_year_sync` per
chiamata interna senza nested asyncio.

**Pagina nuova** `/finance/reports` ("📑 Report YoY + Export"):
- 4 KPI YTD: Incassato · Lineare · Realistic · Pipeline residua.
- Bar export: CSV + Excel.
- Tabella YoY comparison (paid_a vs paid_b + delta + %).
- Chart YoY incassato (2 barre per periodo).
- Tabella YTD Projection breakdown (15 metriche × 3 viste).

**Sidebar**: link "Report YoY + Export" sotto Forecast.

**File toccati** (5):
- `app/main.py` — VERSION
- `app/routers/finance.py` — 4 endpoint + sync refactor
- `app/services/financial_reports.py` — NUOVO
- `app/templates/pages/finance_reports.html` — NUOVO
- `app/templates/base.html` — sidebar link

378 routes (+5).

## v3.5.0-alpha.77.1 — Granularità mensile/trimestrale/annuale (11 maggio 2026)

Toggle topbar in `/finance/forecast` e `/finance/cashflow`:
- **Mensile** (default): 12 colonne (Gen→Dic).
- **Trimestrale**: 4 colonne (Q1/Q2/Q3/Q4), aggregato somma.
- **Annuale**: 1 colonna totale anno.

Aggregation client-side `aggregateBy()`: somma per stessi periodi.
Mark _is_current per trimestre/anno corrente.

Chart grid-template-columns dinamico (`repeat(N, 1fr)`).

**File toccati** (2):
- `app/main.py` — VERSION
- `app/templates/pages/finance_forecast.html` — toggle + aggregation
- `app/templates/pages/cashflow.html` — toggle + aggregation

## v3.5.0-alpha.77 — Financial model + sales pipeline forecast (11 maggio 2026)

Risponde a richiesta Matteo: forecast incassi da quote sent (soft) e
approved (committed), win/loss analysis, pipeline value, projected cash.

Pattern Salesforce/HubSpot/Pipedrive: ogni quote ha probability associata
allo stage, esposta come pipeline weighted.

**Modello Quote esteso** (2 colonne, auto-migrate):
- `win_probability_pct` Float NULL — override manuale.
- `expected_close_date` Date NULL — data attesa firma/incasso.

**Service nuovo** `quote_forecast.py`:
- DEFAULT_WIN_PROBABILITY mapping da status:
  draft=10 · sent=30 · approved=90 · expired=5 · rejected=0 · superseded=0.
- `quote_probability(q)` con override.
- `quote_weighted_value(q)` = total × probability/100.
- `yearly_forecast(year, project_id, client_id)` → breakdown mensile
  + stats annuali (pipeline_total, weighted_forecast, won_value,
  lost_value, win_rate_pct, average_deal_size).

**Endpoint cashflow esteso** `/finance/api/cashflow/{year}`:
Ogni mese ora include:
- `forecast_soft`: Σ quote sent × 30% (probability default).
- `forecast_committed`: Σ quote approved × 90%.
- `forecast_weighted`: pipeline pesata totale.
- `pipeline_total`: somma raw quote non chiuse.
- `quotes_sent` / `quotes_approved` / `quotes_rejected`: raw totals.
- `projected_cash`: paid + forecast_weighted − supplier_paid.
+ `forecast_totals` aggregati a livello anno.

**Endpoint nuovo** `/finance/api/forecast/{year}`: dedicated forecast
breakdown.

**Pagina nuova** `/finance/forecast` ("📊 Financial Model"):
- 6 KPI top: Pipeline totale · Forecast pesato · Vinte · Perse ·
  Win rate · Deal size medio.
- Chart cascata mensile: 4 barre (Incassato verde / Committed indigo /
  Soft lilla / Outflow rosso).
- Tabella breakdown mensile: Sent / Approved / Rejected / Forecast /
  Incassato / Outflow / Cassa proiettata.
- Win/Loss top 10 clienti con vinte/perse/pipeline/win-rate.

**Sidebar**: link "Forecast / Pipeline" sotto Cashflow.

**Confronto sistemi commerciali**:
- Salesforce CRM: Stage probability (analogo, ora MediaFlow uguaglia).
- HubSpot: Deal pipeline (analogo).
- Pipedrive: Revenue forecast (analogo).
- QuickBooks: Cashflow projection (analogo + abbiamo anche pipeline).
- Pennylane AI: forecast AI-driven (futuro α.77.1 con `propose_forecast`).

**File toccati** (5):
- `app/main.py` — VERSION + auto-migrate 2 colonne
- `app/models/models.py` — Quote.win_probability_pct + expected_close_date
- `app/routers/finance.py` — endpoint forecast + cashflow esteso
- `app/services/quote_forecast.py` — NUOVO
- `app/templates/pages/finance_forecast.html` — NUOVO
- `app/templates/base.html` — sidebar link

373 routes (+2).

## v3.5.0-alpha.76 — AI capability assets (11 maggio 2026)

3 nuove AI capability per copilot asset (riusa tutto stack α.72-α.75):

**`query_physical_assets`** (readonly): cerca asset fisici con filtri
kind/owner_type/client_id/logistics_status/q. Risponde a "trovami HDD X",
"asset del cliente Y in deposito", "LTO disponibili".

**`query_asset_contents`** (readonly): lista digital contenuti di
PhysicalAsset (cosa c'è sul disco). Include_removed opt per storico.
Risponde a "cosa c'è sul disco X?", "storico contenuti LTO 042".

**`propose_asset_movement`** (mutation): registra ingest/outgest per
PhysicalAsset, DDT auto. Risponde a "registra ritiro disco cliente",
"spedisco LTO 042 al lab Y". Conferma consegna separata user-side.

**File toccati** (3):
- `app/main.py` — VERSION
- `app/services/ai_assistant.py` — 3 handler
- `app/services/ai_tools.py` — 3 entry TOOLS (31 totali)
- `app/services/ai_legacy_parser.py` — 3 voci VALID

371 routes. 31 AI tools (era 28).

## v3.5.0-alpha.75 — AssetMembership + manifest + filesystem scan (11 maggio 2026)

Risponde direttamente alla richiesta Matteo: "storico di cosa è stato
messo dentro l'HDD cliente, sistema legge direttamente il disco e fa
index dei contenuti".

**Modello nuovo** `AssetMembership` (N:M con storico):
- Tabella `asset_memberships`: physical_asset_id, asset_id (digital),
  path_on_media (es. "/DCP/feature/"), checksum, file_size, notes,
  added_at + added_by_user_id, removed_at + removed_by (soft).
- removed_at NULL = ancora presente sul supporto.

**Endpoint contents**:
- `GET /api/{id}/contents?include_removed=0/1` — lista digital
  contenuti con hydrate Asset.
- `POST /api/{id}/contents/add` — link digital esistente.
- `POST /api/{id}/contents/{mid}/remove` — soft-remove.
- `POST /api/{id}/contents/manifest-import` — bulk CSV/JSON:
  per ogni entry lookup esistente (checksum/filename) o crea
  placeholder + AssetMembership.

**Service nuovo** `fs_scan.py` (v3.5.0-alpha.75):
- Dipendenza nuova `xxhash` (veloce, fallback md5).
- `walk_filesystem(root_path, compute_checksum, max_depth, skip_patterns,
  max_files)` → walk OS + skip __MACOSX/Thumbs.db/.DS_Store + xxhash64
  per file (opt) + mime guess.
- Output: lista file con rel_path/size/mtime/hash/mime/algo.

**Endpoint scan-content**:
- `POST /api/{id}/scan-content` (path + compute_checksum + auto_register):
  scansiona path filesystem, opt checksum, opt auto-register come
  Asset placeholder + AssetMembership.
- Sicurezza: path validato server-side (esiste + è directory). Per usare
  da remoto serve mount del filesystem sul server.

**Dipendenze nuove**:
- `xxhash>=3.0` (requirements.txt aggiornato).

**File toccati** (5):
- `app/main.py` — VERSION
- `app/models/models.py` — AssetMembership
- `app/models/__init__.py` — re-export
- `app/routers/physical_assets.py` — 4 endpoint nuovi + scan
- `app/services/fs_scan.py` — NUOVO
- `requirements.txt` — xxhash

371 routes (+5).

## v3.5.0-alpha.73 — Asset In/Out unificato + ingest digital + IngestBatch (11 maggio 2026)

Risponde all'audit Matteo: ripensare in/out come modal/page strutturato,
permettere creazione asset (fisici+digitali) dal flow, vista unificata.

**Modelli nuovi/estesi**:
- `IngestBatch` (tabella nuova): raggruppa N AssetMovement nello stesso
  DDT/operazione. Use case: cliente consegna 1 disco con 5 file digitali
  → 1 IngestBatch + movimenti correlati. Code auto BATCH-YYYY-NNN.
- `AssetMovement` esteso: `asset_id` (FK Asset digital opt) + `ingest_batch_id`
  (FK IngestBatch opt). `physical_asset_id` ora nullable (mutex con
  asset_id). Auto-migrate con detect rebuild se 0 righe.

**Endpoint nuovi** (`/physical-assets/api/*`):
- `GET /movements/all` — lista unificata cross-assets con filtri direction
  (ingest/outgest derivato), movement_type, client_id, supplier_id,
  only_pending. Hydrata asset_label/kind/nature (digital|physical) +
  file_size se digital.
- `POST /movements/digital` — multipart upload: file → crea Asset DAM +
  AssetMovement digital + auto-DDT. Use case: cliente invia DCP/mix.
- `POST /ingest-batches` — crea IngestBatch raggruppante.

**Pagina nuova** `/physical-assets/inout`:
- Vista unificata movimenti In/Out (digital + physical) ordinata per data.
- Filtri: direzione + tipo + stato (conferma).
- Badge natura (digital indigo / physical viola).
- Bottoni PDF DDT + Conferma per riga.
- Topbar: "📥 Ingest digitale" (modal upload) + "📥 Ingest fisico"
  (redirect a `/physical-assets` per flow esistente).

**Sidebar**: nuovo link "🚚 In/Out Asset" sopra "Asset Fisici".

**Bugfix routing**: `/api/movements-all` path collideva con
`/api/{asset_id}` (FastAPI matchava asset_id="movements-all" → 422).
Risolto con `/api/movements/all` (2 segmenti).

**File toccati** (5):
- `app/main.py` — VERSION + auto-migrate asset_movements rebuild
- `app/models/models.py` — IngestBatch + AssetMovement extension
- `app/models/__init__.py` — re-export IngestBatch
- `app/routers/physical_assets.py` — 3 endpoint + page /inout
- `app/services/...` — N/A (riusa DAM service per file upload)
- `app/templates/pages/assets_inout.html` — NUOVO
- `app/templates/base.html` — sidebar link

366 routes (+5).

## v3.5.0-alpha.72.1 — Fix etichetta + numerazione automatica + batch import (11 maggio 2026)

**Bug fix critico**: `/physical-assets/api/{id}/label.png` e `/scan/{token}`
crashavano per `joinedload()` vuoto (residuo refactor α.72.0). Sostituiti
con query senza relationship loading.

**Numerazione automatica** asset fisici (analisi vs CatDV/Iconik):
- Tenant.asset_numbering_config JSON (auto-migrate): `{kind: {prefix,
  counter, pad}}`. Esempio: `LTO-001`, `HDD-042`, `BD-0023`.
- Service `app/services/asset_numbering.py`: get_config (con default
  merge) + save_config + next_label + peek_label.
- POST `/physical-assets/api`: label=optional, auto-genera da config se
  vuoto. Counter avanzato ad ogni create.
- Fix SQLA: `flag_modified` per JSON mutation detection (mutation
  in-place non rilevata di default, prima 5 asset stesso label).

**Batch import** (acquisto in stock LTO/HDD):
- POST `/physical-assets/api/batch-import`: input kind + count (1..500)
  + campi comuni (manufacturer, capacity_gb, location, unit_cost,
  description). Crea N asset con label progressiva.

**API settings numerazione**:
- GET `/api/numbering/config` ritorna config con default merge
- PUT `/api/numbering/config` salva nuova config (gate `edit_settings`)
- GET `/api/numbering/peek?kind&offset` preview senza avanzare

**UI** `/physical-assets`:
- Topbar 2 bottoni nuovi: "📦 Batch import" + "🔢 Numerazione"
- Modal batch: preview labels live (first → last) + form campi comuni
- Modal numerazione: tabella editabile prefix/counter/pad per kind

**Confronto sistemi commerciali**:
- CatDV: numerazione fissa "bin id", no batch import
- Iconik: tagging metadata, no logistics
- Frame.io Vault: shelf id auto ma chiuso ($)
- MediaFlow ora supera entrambi sul side logistics + numerazione
  configurabile per tenant.

**File toccati** (5):
- `app/main.py` — VERSION + auto-migrate asset_numbering_config
- `app/models/models.py` — Tenant.asset_numbering_config
- `app/routers/physical_assets.py` — fix joinedload + 4 endpoint nuovi
- `app/services/asset_numbering.py` — NUOVO
- `app/templates/pages/physical_assets.html` — 2 modal nuovi + JS

361 routes (+3 dalla α.72.0).

## v3.5.0-alpha.72.0 — Asset fisici: ownership + movimenti + DDT + QR (11 maggio 2026)

Sistema logistico completo per asset fisici (LTO/HDD/CRU/Blu-Ray):
ingest/outgest con bolle DDT, conferma consegna, etichetta QR
stampabile, scan mobile.

**Modelli nuovi**:
- `AssetMovement` (tabella `asset_movements`): movimento append-only con
  delivery_note_number, movement_type enum (ingest/outgest/transfer/
  return_to_client/return_from_client), mittente/destinatario completi
  (party + address + contact), FK opt client_id/supplier_id, package_count
  + total_weight_kg + dimensions_lwh_cm, contents_description, carrier
  + tracking_number + shipping_cost, conferma (confirmed_at +
  confirmed_by_user_id + confirmed_by_name), attachment_path +
  signature_path, notes.
- `AssetMovementType` enum + `AssetOwnerType` enum (internal/client/
  supplier/third_party).

**PhysicalAsset esteso** (6 colonne, auto-migrate):
- `owner_type` enum (default internal)
- `owner_client_id` FK opt → Client
- `owner_supplier_id` FK opt → Supplier
- `owner_label` libero
- `qr_code_token` UUID hex univoco (auto-generato al create)
- `logistics_status` ("in_storage", "transit_out", "delivered_external")

**Service** `app/services/asset_qr.py` (NUOVO):
- `new_token()` UUID4 hex.
- `generate_qr_png(scan_url, size)` → PNG QR.
- `generate_label_png(...)` → PNG etichetta 60×40mm @ 300dpi default,
  QR a sinistra + asset_label/kind/serial/owner/id text a destra.
- `generate_delivery_note_pdf(...)` → PDF A5 con header mittente/
  destinatario, dettaglio collo, spedizione, firme, QR top-right.

**Router** `/physical-assets/*`:
- `POST /api` esteso con `owner_type` + `owner_client_id` + `owner_supplier_id`
  + `owner_label`. Auto-genera `qr_code_token`.
- `GET /api/{id}/movements` lista.
- `POST /api/{id}/movements` crea movimento (auto-DDT-number se omesso).
- `POST /api/movements/{id}/confirm` conferma consegna/ritiro.
- `GET /api/{id}/qr.png` QR standalone.
- `GET /api/{id}/label.png` etichetta stampabile.
- `GET /api/movements/{id}/ddt.pdf` PDF bolla A5.
- `GET /scan/{token}` HTML mobile-friendly lookup (no auth dura).

**UI** `/physical-assets`:
- Riga asset: bottoni "🏷 Etichetta QR" + "🚚 Movimenti" + edit.
- Modal Movimenti: lista DDT con tipo/data/da-a/colli/tracking/stato
  + bottoni PDF + Conferma per riga.
- Form "+ Nuovo movimento" con tutti i campi DDT.
- Auto-apre PDF DDT in nuova tab dopo create.

**Template** `pages/physical_asset_scan.html` (NUOVO):
- Layout mobile-friendly responsive.
- Banner ownership (cliente arancio / noleggio / interno indigo).
- Card asset (label/kind/status/serial/capacità/locazione).
- Card ultimo movimento (tipo/DDT/data/da/a/tracking/conferma).

**File toccati** (5):
- `app/main.py` — VERSION + auto-migrate 6 colonne + populate qr_code_token
- `app/models/models.py` — AssetMovement + AssetOwnerType + PhysicalAsset
- `app/models/__init__.py` — re-export
- `app/routers/physical_assets.py` — 7 endpoint nuovi
- `app/services/asset_qr.py` — NUOVO
- `app/templates/pages/physical_assets.html` — bottoni + modal movimenti
- `app/templates/pages/physical_asset_scan.html` — NUOVO

358 routes (+7).

## v3.5.0-alpha.71 — Supplier: parse PDF AI + 2 query AI capability (11 maggio 2026)

Estrae fattura passiva da file (PDF/docx/xlsx/txt), crea fornitore +
fattura in un colpo. AI query read-only su fornitori e fatture.

**Service nuovo** `app/services/supplier_invoice_parser.py`:
- `parse_supplier_invoice(text, user_id, db)` — AI extract con prompt
  che identifica CEDENTE (fornitore) vs cessionario. Restituisce
  supplier_name, vat_number, tax_code, address, iban, number, dates,
  amount_net/vat/total, currency, payment_terms_days, confidence,
  notes. Solo testo (no OCR per fatture scansionate, scope futuro).

**Endpoint nuovi** `/suppliers/api/invoices/*`:
- `POST /parse-upload` (multipart): extract + match supplier per
  vat_number o name. Ritorna preview JSON (NON salva).
- `POST /create-from-parsed`: riceve dati confermati. Trova o crea
  Supplier + crea SupplierInvoice. Pre-check unicità (supplier, number).

**AI capability readonly**:
- `query_suppliers` — lista con KPI outstanding + overdue count.
  Filtri: q (nome), only_with_outstanding.
- `query_supplier_invoices` — lista fatture con filtri supplier/status/
  only_overdue/project/job. Risponde a "fatture scadute?" "fatture
  del fornitore X" "fatture passive del progetto Y".

**UI** `/suppliers`:
- Bottone topbar "✨ Estrai da PDF" → modal 2-step.
- Step 1: upload file.
- Step 2: anteprima editable con badge confidence (high/medium/low) +
  sezione fornitore (auto-fill nuovo vs match esistente) + dati fattura
  editabili + recalc totale.
- Submit → crea (fornitore se nuovo) + fattura, refresh lista.

**File toccati** (5):
- `app/main.py` — VERSION
- `app/routers/suppliers.py` — 2 endpoint parse + create
- `app/services/supplier_invoice_parser.py` — NUOVO
- `app/services/ai_assistant.py` — 2 handler readonly
- `app/services/ai_tools.py` — 2 entry TOOLS (28 totali)
- `app/services/ai_legacy_parser.py` — 2 voci VALID
- `app/templates/pages/suppliers.html` — modal parse-pdf 2-step + JS

351 routes (+2). 28 AI tools (era 26).

## v3.5.0-alpha.70.4 — TPN: MFA TOTP completo (11 maggio 2026)

Chiude la roadmap TPN α.70.x. Multi-Factor Authentication TOTP
(Google Authenticator / Authy / Microsoft Authenticator / 1Password)
attivabile per user. Enforcement opzionale per progetti sensibili.

**Dipendenze nuove** (`requirements.txt`):
- `pyotp>=2.9.0`
- `qrcode>=8.0`

**Modello User esteso** (3 colonne, auto-migrate):
- `mfa_secret_encrypted` (Text, Fernet-encrypted con AI_KEY_ENCRYPTION_KEY)
- `mfa_enabled` Bool default False
- `mfa_enabled_at` DateTime

**Service** `app/services/mfa.py` (NUOVO):
- `setup_user_mfa(user)` → genera secret + QR PNG + URI provisioning.
- `verify_user_otp(user, code)` → check OTP (window=1 per drift).
- `confirm_setup(user, code)` → primo OTP per attivare.
- `disable_mfa(user, code)` → richiede OTP per disattivare.

**Auth flow esteso** (`/auth/login`):
- Password OK + `user.mfa_enabled=True` → emit cookie `mfa_pending`
  short-lived (10 min) + redirect a `/auth/mfa-challenge`.
- `/auth/mfa-challenge` HTML mostra form OTP a 6 cifre.
- `/auth/mfa-verify` POST verifica → se OK emit cookie access_token +
  delete pending. Se fail → re-render form con errore.

**Endpoint API user**:
- `GET /auth/api/mfa/status` — stato + has_pending_secret.
- `POST /auth/api/mfa/setup` — genera QR + secret + URI.
- `POST /auth/api/mfa/verify-setup` — conferma primo OTP, enable.
- `POST /auth/api/mfa/disable` — richiede OTP per disattivare.

**UI** `/settings` tab nuovo "🔒 MFA TOTP":
- Stato attuale (attivo verde / non attivo arancio).
- Setup: scansiona QR + inserisci primo codice OTP.
- Disable: input OTP + conferma esplicita.

**Enforcement progetto** (`check_project_mfa_required`):
- Se `Project.mfa_required=True` (campo α.70.3) e user senza MFA
  → 403 + log deny su DAM download (errore con hint per attivare).

**File toccati** (8):
- `app/main.py` — VERSION + auto-migrate 3 colonne
- `app/models/models.py` — User MFA fields
- `app/routers/auth.py` — login flow esteso + 6 endpoint MFA
- `app/routers/dam.py` — check_project_mfa_required
- `app/services/mfa.py` — NUOVO
- `app/services/project_access.py` — check_project_mfa_required
- `app/templates/pages/mfa_challenge.html` — NUOVO
- `app/templates/pages/settings.html` — pane MFA + JS
- `requirements.txt` — pyotp + qrcode

349 routes (+6 nuove).

## v3.5.0-alpha.70.3 — TPN: IP allowlist + security policy progetto (11 maggio 2026)

**Modello Project esteso** (3 campi nuovi, auto-migrate):
- `ip_allowlist` JSON: array CIDR/IP. Vuoto = no restrizione. Popolato:
  DAM download bloccato se IP request non matcha (log deny).
- `mfa_required` bool: placeholder per α.70.4 MFA TOTP (richiede pyotp).
- `min_role_for_access` String: placeholder per gating by role.

**Service** `project_access.py`:
- `check_project_ip_allowlist(project_id, request, db) → bool`
- `_ip_in_allowlist` con `ipaddress` stdlib (no deps).
- `_client_ip` da request (X-Forwarded-For aware).

**DAM**: `download_asset` ora check IP allowlist + log deny se mismatch.

**Router projects** `/api/{id}/security` GET/PUT — solo admin.
Validazione CIDR/IP server-side.

**Note MFA**: TOTP non implementato — richiede `pip install pyotp qrcode`.
Quando Matteo conferma deps, α.70.4 implementerà:
- `User.mfa_secret` Fernet-encrypted + `mfa_enabled`
- /auth/mfa/setup (QR) + /auth/mfa/verify
- Login flow: password OK → check mfa_enabled → richiedi OTP

343 routes (+2).

## v3.5.0-alpha.70.2 — TPN: watermark immagini + secure delete (11 maggio 2026)

**Service** `app/services/dam_security.py` (nuovo):
- `apply_watermark_image(path, user_email, ts, extra)` → bytes JPEG:
  overlay testuale bottom-right (user+ts+UTC+asset_id) + diagonal big
  semi-trasparente centrale (user email uppercase, rotate -30°).
  Font auto-detect (DejaVu/Arial fallback PIL default).
- `secure_delete_file(path, passes=3)` → bool: DOD-style overwrite con
  random bytes 3 pass + zero pass + truncate + unlink. fsync ad ogni
  round. Best-effort fallback su PermissionError.
- `is_image_mime(mime)` helper.

**DAM download**: `?watermark=1` (default) per immagini applica watermark
inline → bytes JPEG con filename `<orig>_wm.jpg`. Admin può `?watermark=0`
per esporto pulito. Video/audio/document non hanno watermark (richiede
ffmpeg/PDF libs, scope futuro).

**DAM delete**: `?secure=1` attiva DOD wipe. Più lento ma garantisce
no-recovery. Default `secure=0` (unlink standard).

**File toccati** (2):
- `app/services/dam_security.py` — NUOVO
- `app/routers/dam.py` — hook watermark + secure delete

## v3.5.0-alpha.70.1 — TPN UI: project access + audit log viewer (11 maggio 2026)

**UI Project Access Grants** (tab nuovo su `/projects/{id}/detail`):
- "🔒 Accessi TPN" tab con badge count `(grants_count + auto_grants)`.
- Sezione Grant espliciti: tabella user/ruolo/granted_by/data/note +
  bottone "+ Concedi accesso" → modal con dropdown user + role + notes.
  Bottone Revoca soft per riga.
- Sezione Auto-grant: lista risorse con assignment su job nel project
  (via `Resource.user_id`).

**Admin audit log viewer**:
- `/admin/audit-log` (link sidebar Admin, gate `manage_users`).
- Filtri user_id/asset_id/project_id/action.
- Tabella eventi con colore action (deny rosso, download verde, etc.)
  + IP + UA + extra info + timestamp.
- Endpoint `GET /admin/api/audit-log` con limit/offset.

341 routes (+2: pagina HTML + API list).

## v3.5.0-alpha.70.0 — TPN foundation: DAM access control (11 maggio 2026)

Prima tappa roadmap TPN compliance (α.70.0→α.70.3). Compartimentalizzazione
DAM per progetto con need-to-know principle.

**Modelli nuovi** (2 tabelle + 1 enum):
- `ProjectAccessGrant` (project_access_grants): grant esplicito user→
  project, soft-revoke via revoked_at + revoked_by_user_id, granted_by,
  notes, role_in_project informativo.
- `AssetAccessLog` (asset_access_logs): audit trail append-only.
  asset_id, user_id, action enum, project_id, ip, user_agent, ts, extra.
  Conservato indefinitamente per compliance TPN.
- `AssetAccessAction` enum: view|download|upload|delete|update|share|deny.

**Service** `app/services/project_access.py` (helpers centralizzati):
- `user_can_access_project(user, project_id, db) → bool`: 3 livelli
  (admin/manager bypass | ProjectAccessGrant attivo | JobResourceAssignment
  via Resource.user_id).
- `accessible_project_ids(user, db) → set[int]`.
- `user_can_access_asset(user, asset, db) → bool`: include logica
  internal queue (project_id=NULL ⇒ visibile solo a admin + uploader).
- `log_asset_access(...)` append-only con auto-IP + auto-UA capture.

**Router DAM** (`/dam/*`): tutti gli endpoint hardenati:
- `list_assets` filtra per `accessible_project_ids` (admin bypass).
  Nuovo query param `project_id` con check access. Nuovo `include_internal`
  per uploader queue.
- `upload_asset`: project_id auto-resolve da Job.project_id se omesso.
  Audit log upload.
- `download_asset`: check access + log download (deny→403 + log).
- `get_thumbnail`: check access silenzioso (no log per evitare spam).
- `delete_asset`: check access + log pre-delete (asset_id resta nel log).
- Nuovo `POST /api/assets/{id}/assign-project` per spostare da internal
  queue al progetto.

**Router Projects** (`/projects/api/{id}/access/*`): CRUD grants:
- GET list grants (esplicit + auto da JobResourceAssignment).
- POST crea grant.
- DELETE revoca grant (soft).

339 routes (+4 nuove). Tabelle auto-create al boot.

## v3.5.0-alpha.69.1 — Fix cashflow + filtri + drill-down risorsa (11 maggio 2026)

3 issue Matteo:

**1. Cashflow: aprile pagato non visibile**
- Root cause: Invoice marcata `paid` ma senza riga `InvoicePayment` (DB
  pre-α.66.20). Cashflow aggrega da `InvoicePayment.payment_date` → 0.
- Fix: backfill in `_auto_migrate_columns()` — per ogni Invoice
  status=paid con amount_paid=0 e 0 payments, crea InvoicePayment
  (amount=total, payment_date=issue_date, reference='BACKFILL_AUTOMIGRATE').
  Aggiorna anche amount_paid denormalizzato. Idempotente.

**2. Filtri progetto/cliente in cashflow**
- Backend `cashflow_year`: query params `project_id` + `client_id`
  opzionali. Filtra Invoice (via Invoice.client_id + Job.project_id) +
  InvoicePayment (restringe a invoice filtered) + SupplierInvoice
  (project_id direct o via job→project→client) + SupplierInvoicePayment.
- UI `/finance/cashflow` topbar: 2 dropdown nuovi (cliente, progetto).
  Cambio cliente filtra progetti; cambio progetto/cliente refresh dati.

**3. Cost report drill-down risorsa → job (reverse vista voci di costo)**
- Backend nuovo `GET /cost-report/api/resource/{rid}/jobs?period_start&period_end`:
  per una risorsa, lista job lavorati con breakdown ore (reg/OT/notturno/
  festivo) + bookings_count + first/last_date + cost stimato sell +
  cost interno (se configurato).
- UI cost-report: cliccando una riga della tabella "Ore booking per fascia"
  apre modal con elenco job ordinato per data recente, totali + click
  job riga = apri cost report del job.

**4. Templates capitolati seed**
- Tabella `delivery_templates` era vuota. Aggiunto `scripts/seed_delivery_templates.py`
  con 11 template base (A24, MUBI, Vision, IRDA, RAI, Sky, Netflix,
  Amazon MGM, BETA, Fremantle, NBCU TechOps). Solo scheletro (code/name/
  broadcaster/description). Idempotente. Esecuzione: `python scripts/seed_delivery_templates.py`.

**File toccati** (5):
- `app/main.py` — VERSION + backfill auto-migrate
- `app/routers/finance.py` — cashflow_year filtri
- `app/routers/cost_report.py` — resource/jobs drill endpoint
- `app/templates/pages/cashflow.html` — 2 dropdown topbar + loadFilters
- `app/templates/pages/cost_report.html` — modal drill + onclick risorsa
- `scripts/seed_delivery_templates.py` — NUOVO

335 routes (+1).

## v3.5.0-alpha.69 — Capitolati↔quote wizard PDF + AI (B+C) (11 maggio 2026)

Tappe **B** (wizard PDF→quote) + **C** (AI capability) della roadmap
capitolati→quotazioni. A era già in α.68.6.

**B — Wizard PDF capitolato → quote** (`/quotes`):
- Topbar nuovo bottone "✨ Crea da capitolato".
- Modal wizard 2 step:
  - Step 1: select progetto + numero quote + upload PDF/docx/xlsx/txt
    (o testo incollato) + hint opzionale per AI.
  - Step 2: anteprima deliverables estratti dall'AI, ogni voce con:
    - Checkbox include/skip (default ON)
    - Section editor (A-E)
    - Qty editor
    - Match price_item con badge confidence (high/medium/low/manual)
    - Bottone "cambia" per picker manuale (search nome/categoria)
    - Unit price editable
- Riusa endpoint backend AI esistenti orphan-da-α.66.20:
  `/ai/api/deliverables/parse` (parse_deliverables +
  match_deliverables_to_pricelist auto-integrati) e
  `/ai/api/deliverables/create-quote` (bulk-create Quote + QuoteLines).

**C — AI capability `propose_quote_from_template`**:
- Nuova capability (handler + tool schema + legacy parser).
- Input: `template_id` o `template_code` + `quote_id` o `quote_number`
  + `price_level` opzionale.
- Resolve template + quote, scorre suggested_items, bulk-add QuoteLines
  con stessa logica di `load-from-template`. Skip duplicati + mancanti.
- Esempio uso: utente in chat AI: "carica il template Netflix-IMF
  sulla quote Q-2026-12" → AI propone → utente Apply → righe aggiunte.

**File toccati** (5):
- `app/main.py` — VERSION
- `app/services/ai_assistant.py` — handler `_h_propose_quote_from_template`
- `app/services/ai_tools.py` — entry TOOLS (26 totali)
- `app/services/ai_legacy_parser.py` — voce VALID_ACTION_TYPES
- `app/templates/pages/quotes.html` — wizard modal + JS multi-step

334 routes. **No backend nuovo lato B**: i 2 endpoint AI erano già
implementati (alpha.66.20) ma orfani (nessuna UI li usava). Adesso
finalmente esposti via wizard.

## v3.5.0-alpha.68.6 — Capitolati↔quote foundation (A) (11 maggio 2026)

Prima tappa del lavoro estensivo capitolati→quotazioni (vedi roadmap
A/B/C). Foundation per le tappe successive: editor `suggested_items`
+ bulk-add in `/quotes`.

**Backend** (3 endpoint nuovi):
- `delivery_templates.PUT /api/{id}` ora accetta `suggested_items` JSON
  (lista `{price_item_id, qty_hint, section, notes}`).
- `delivery_templates.POST /api/save` idem in create.
- `delivery_templates.GET /api/{id}/suggested-hydrated` espande
  price_item per ogni item (name/unit/price_list/category) + flag
  `missing` per items orfani.
- `quotes.POST /api/{id}/load-from-template` bulk-insert `QuoteLine`
  da template.suggested_items. Skip duplicati (stesso price_item_id)
  + skip orfani. Idempotente. Ricalcola quote totals.

**UI**:
- `/delivery-templates` modal detail: nuovo editor "Voci listino
  suggerite" con tabella editabile (qty_hint, section A-E, notes),
  picker price_item con search (nome/categoria/keywords), salva
  pulsante in footer.
- `/quotes` editor: nuovo bottone "📋 Carica da template" sulla card
  Voci preventivo. Modal con dropdown template + preview hydrated
  (riga per riga con qty × prezzo + totale stimato) + conferma.

**File toccati** (4):
- `app/main.py` — VERSION
- `app/routers/delivery_templates.py` — 3 endpoint estesi/nuovi
- `app/routers/quotes.py` — `load-from-template`
- `app/templates/pages/delivery_templates.html` — editor suggested_items
- `app/templates/pages/quotes.html` — modal load + bottone

334 routes (+2). No DB migration (`suggested_items` JSON field già
nel modello da Fase 1-bis).

**Tappe successive** (roadmap A/B/C confermata):
- B — Wizard end-to-end PDF capitolato → quote+lines via AI
- C — AI capability propose_quote_from_template

## v3.5.0-alpha.68.5 — AI capability supplier (11 maggio 2026)

Copilot AI può ora creare fornitori e registrare fatture passive
direttamente (con conferma utente via Apply, pattern propone/dispone).

**2 nuove capability** (handler + tool schema + legacy parser):
- `propose_supplier` — crea anagrafica fornitore. Solo `name`
  obbligatorio; tutti i dati fiscali opzionali.
- `propose_supplier_invoice` — registra fattura passiva. Risolve
  supplier per id o per name (no auto-create — usa propose_supplier
  prima). Calcola amount_vat + amount_total + due_date auto se
  default_payment_terms_days configurato. Pre-check unicità
  (supplier_id, number). FK opzionali a project/job/JCL.

**File toccati** (4):
- `app/main.py` — VERSION
- `app/services/ai_assistant.py` — 2 handler @ai_capability
- `app/services/ai_tools.py` — 2 entry in TOOLS (input_schema completo)
- `app/services/ai_legacy_parser.py` — 2 voci in VALID_ACTION_TYPES

25 tools totali (era 23). Action handlers registrati via decorator
auto-discovery — VALID_ACTION_TYPES sincronizzato a import-time.

## v3.5.0-alpha.68.4 — Anomalia fatture passive scadute (11 maggio 2026)

Aggiunge le fatture passive scadute alle anomalie finance. Visibilità
proattiva per il pagamento fornitori.

**Backend** (`finance.py`):
- `GET /finance/api/anomalies/overdue-supplier` — lista SupplierInvoice
  con due_date < oggi e payment_status in (unpaid, partial). Include
  `days_overdue` per priorità + amount_outstanding.
- `GET /finance/api/anomalies/summary` esteso con
  `overdue_supplier_invoices` count → badge topbar lo include nel totale.

**UI** `/finance` tab Anomalie:
- Nuova stat-card "Fatture pass. scadute" nel summary (rosso + €
  residuo).
- Nuova sezione "🧾 Fatture passive scadute" con tabella: numero,
  fornitore, scadenza, giorni ritardo (rosso), totale, pagato,
  residuo (rosso), stato.
- Badge anomalies in topbar finance ora conta anche overdue supplier.

**File toccati** (3):
- `app/main.py` — VERSION
- `app/routers/finance.py` — endpoint overdue + summary esteso
- `app/templates/pages/finance.html` — sezione + render JS

332 routes (+1).

## v3.5.0-alpha.68.3 — UI pagamenti supplier (11 maggio 2026)

Espone in UI il modello SupplierInvoicePayment di α.68.2. Senza UI
i pagamenti incrementali non erano gestibili da Matteo.

**UI** `/suppliers` modal fattura (solo in edit, non in create):
- Nuova sezione "Pagamenti registrati" sotto le note.
- Summary header: Pagato / Totale / Residuo colorato.
- Lista pagamenti (data, importo, metodo, riferimento, delete).
- Quick-add inline: importo + data + metodo + bottone Aggiungi.
- Auto-refresh amount_paid + payment_status + payment_date nel modal
  dopo add/delete (denormalizzati lato server).
- Auto-refresh KPI tenant + lista fatture in background.

**File toccati** (2):
- `app/main.py` — VERSION
- `app/templates/pages/suppliers.html` — sezione payments + 3 nuove
  funzioni JS (loadInvoicePayments, addPayment, deletePayment).

## v3.5.0-alpha.68.2 — SupplierInvoicePayment (11 maggio 2026)

Risolve il limite noto di α.68.1: pagamenti incrementali a fornitori
ora storicizzati (analogia con InvoicePayment per fatture attive).

**Modello nuovo**:
- `SupplierInvoicePayment` (tabella `supplier_invoice_payments`):
  tenant_id, supplier_invoice_id, amount, payment_date, method, notes,
  reference, recorded_by_user_id, created_at. Cascade delete on
  invoice.
- `SupplierInvoice.payments` relationship + `SupplierInvoice.payment_date`
  diventa "data ultimo saldo" (back-compat, derivato).
- `SupplierInvoice.amount_paid` resta denormalizzato per query veloci;
  fonte verità = Σ payments.amount.

**Router** `/suppliers/api/invoices/{id}/payments` (GET) + endpoint
esistente `/pay` (POST) ora crea riga SupplierInvoicePayment + aggiorna
denormalizzazione via `_refresh_supplier_invoice_payment_state()`.
Nuovo `DELETE /suppliers/api/sup-payments/{id}` per rollback.

**Cashflow** `/finance/api/cashflow/{year}`:
- `supplier_paid` ora aggrega da `SupplierInvoicePayment.payment_date`
  (fonte verità) invece di `SupplierInvoice.payment_date` (snapshot).
- Pagamenti incrementali distribuiti correttamente tra i mesi.

**File toccati** (4):
- `app/main.py` — VERSION
- `app/models/models.py` — SupplierInvoicePayment + relationship
- `app/models/__init__.py` — re-export
- `app/routers/suppliers.py` — list/create/delete payments + refresh
- `app/routers/finance.py` — cashflow_year query da payments table

Tabella auto-create al boot. 331 routes (+2 nuove).

## v3.5.0-alpha.68.1 — Cashflow ↔ supplier outflows (11 maggio 2026)

Integra le fatture passive nella timeline cashflow. Chiude il giro
"cassa effettiva" iniziato con α.66.20 (revenue-side) e α.68
(supplier model).

**Backend** (`/finance/api/cashflow/{year}`):
- 3 nuovi campi per mese:
  - `supplier_billed`: Σ amount_total fatture passive ricevute nel
    mese (issue_date), non cancelled
  - `supplier_paid`: Σ amount_paid per fatture con payment_date nel
    mese (limite: pagamenti incrementali non storicizzati nel modello
    attuale → future SupplierInvoicePayment table per analogia con
    InvoicePayment)
  - `supplier_due`: Σ residuo per fatture con due_date nel mese,
    ancora unpaid/partial
- Derivato: `net_cashflow` = `paid` (revenue) − `supplier_paid` (cost)
  = cassa netta effettiva del mese.

**UI** `/finance/cashflow`:
- 5 stat-card (era 4): aggiunti **Outflow fornitori** (rosso) e
  **Cassa netta** (verde/rosso da segno). Rimosso "% Incasso" headline
  (più importante avere cassa netta in alto).
- Chart: 4° barra rossa "Outflow fornitori" per mese. Tooltip
  esteso con tutti i 5 valori + cassa netta.
- Tabella dettaglio: 3 colonne nuove (Fatt. passive, Outflow, Cassa
  netta). Cassa netta colorata in base al segno. % Incasso ora in
  fondo riga.

**File toccati** (3):
- `app/main.py` — VERSION
- `app/routers/finance.py` — cashflow_year esteso
- `app/templates/pages/cashflow.html` — UI 5 card + 4 barre + 7 colonne

**Limite noto**: SupplierInvoice ha solo `payment_date` + `amount_paid`
denormalizzato, no tabella separata per pagamenti incrementali. Se
fattura X pagata 30% gennaio + 70% marzo, vediamo solo 100% nel mese
del payment_date corrente. Future: aggiungere SupplierInvoicePayment.

## v3.5.0-alpha.68 — Supplier / SupplierInvoice modulo (11 maggio 2026)

Modulo nuovo isolato per fatture passive. Punto 6 della roadmap
billing α.65+ chiusa. Sblocca cost-side esterno (cassa cost report
+ cashflow).

**Modelli nuovi** (2 tabelle + 1 enum):
- `Supplier` — anagrafica fornitore: name, vat_number, tax_code,
  contact_email/phone, address, iban, default_payment_terms_days,
  notes, is_active, deleted_at. Tenant scope. Soft delete.
- `SupplierInvoice` — fattura passiva: supplier_id, number, issue_date,
  due_date, payment_date, project_id/job_id/job_cost_line_id (FK
  opzionali per granularità), amount_net + vat_rate + amount_vat +
  amount_total (calcolati server-side), currency, payment_status enum,
  amount_paid (denormalizzato), attachment_path, notes, deleted_at.
- `SupplierInvoiceStatus` enum: unpaid|partial|paid|cancelled.

Tabelle create automaticamente al boot da `Base.metadata.create_all()`.
Zero migrazione manuale.

**Router** `app/routers/suppliers.py` (13 endpoint, prefix `/suppliers`):
- CRUD fornitori (`/api`, `/api/{id}` — list/create/update/delete soft)
- CRUD fatture (`/api/invoices*` — list con filtri supplier/project/
  job/status, get-by-id, create, update, delete soft, register-payment
  incrementale)
- Aggregati: `/api/summary/job/{id}` per cost-report, `/api/summary/tenant`
  per KPI dashboard.

Logica notevole:
- `_derive_status()` calcola payment_status canonico da amount_paid/
  amount_total. Rispetta `cancelled` se settato esplicitamente.
- `due_date` auto-fill da `default_payment_terms_days` del fornitore
  alla creazione fattura.
- Pre-check unicità `(supplier_id, number)` su create per evitare
  duplicati.
- Delete supplier bloccato se ha fatture attive (non cancelled).

**UI** `/suppliers` (template `suppliers.html`):
- 3 KPI card (fatture totali / outstanding / scaduto).
- 2 tab: Fatture passive (default) + Anagrafica fornitori.
- Tabelle filtrabili (ricerca + supplier + stato).
- Modal CRUD per fornitore + fattura. Modal fattura ha auto-recalc
  totale via JS.
- Badge stato pagamento colorato. Warning ⚠ su due_date scaduta.

**Sidebar**: link "Fornitori" in sezione Finanza (icona receipt).

**Cost-report integration** (`/cost-report/api/job/{id}`):
- Nuovo campo summary `total_supplier_invoices` (Σ amount_total fatture
  passive non cancelled linkate al job o project).
- Nuovo campo summary `real_margin_full` = `total_accrued −
  total_cost_accrued − total_supplier_invoices` (margine reale completo).
- UI cost-report (`renderKPIs`): 2 nuove KPI card (Fatture passive +
  Margine reale ⊕) accanto Margine reale.

**File toccati** (8):
- `app/models/models.py` — Supplier + SupplierInvoice + enum
- `app/models/__init__.py` — re-export
- `app/main.py` — VERSION + import router
- `app/routers/__init__.py` — N/A (import diretto in main.py)
- `app/routers/suppliers.py` — NUOVO (519 righe)
- `app/routers/cost_report.py` — aggregato supplier_invoices
- `app/templates/pages/suppliers.html` — NUOVO
- `app/templates/pages/cost_report.html` — KPI card supplier
- `app/templates/base.html` — sidebar link

**Smoke**: AST parse OK su tutti i file. Boot app OK, 329 routes, +13
nuove `/suppliers/*`. Tabelle create con tutti gli index attesi.

## v3.5.0-alpha.66.22 — UI cost-report real_margin (11 maggio 2026)

Completa la parte cliente dell'α.67 cost-side risorsa: i numeri sono
in DB ed esposti dal backend da α.66.21, ora visibili in UI.

**Cosa cambia in `/cost-report`**:

Vista lista (1 riga per job):
- Nuova colonna **Marg. reale** (verde se positivo, rosa se
  negativo, dash se nessun cost-rate configurato sulle risorse).

Vista dettaglio (singolo job):
- 2 nuove KPI card nel summary: **Costo reale risorse** + **Margine
  reale** (entrambe con fallback "—" + hint "attiva cost_type su
  /resources" se 0).
- 2 nuove colonne nella tabella voci di costo: **Costo reale** e
  **Margine reale** per riga JCL.

Tutto guarda i campi `total_cost_accrued` e `real_margin` già esposti
da α.66.21 in `/cost-report/api/list` e `/cost-report/api/job/{id}`.
Nessun cambio backend, nessuna migrazione.

**File toccati** (3):
- `app/main.py` — VERSION
- `app/templates/pages/cost_report.html` — KPI + colonne lista/detail
- `CHANGELOG.md` + `docs/STATO.md`

## v3.5.0-alpha.66.21 — UI cashflow + α.67 cost-side risorsa (11 maggio 2026)

Autopilot post "fai tutto in autonomia e push". 2 sviluppi:

**UI Cashflow** (`/finance/cashflow`):
- Pagina HTML che usa endpoint `GET /finance/api/cashflow/{year}` già esposto in α.66.20
- 4 stat-card totali anno (fatturato/incassato/aperto/% incasso)
- Grafico 12 mesi a colonne (3 barre per mese: invoiced indigo, paid
  green, outstanding amber) con scaling proporzionale
- Mese corrente highlighted con bordo cyan
- Tabella dettaglio sotto con valori + % incasso mensile
- Selector anno in topbar (range corrente-4..corrente+1)
- Sidebar link "Cashflow" in sezione Finanza

**α.67 cost-side risorsa**:
- Nuovo campo `JobCostLine.total_cost_accrued` (Float default 0)
- Auto-migrate boot: `ALTER TABLE job_cost_lines ADD COLUMN
  total_cost_accrued REAL NOT NULL DEFAULT 0`
- `recompute_cost_line_actual` (`cost_line_sync.py`) ora calcola
  anche `total_cost_accrued`: per ogni booking done, per ogni
  assignment, somma `(end-start) × Resource.internal_cost_hourly`
  (property già esistente, derivata da cost_type/monthly_gross/
  freelance_hourly_cost/studio_hourly_cost)
- Risorse con `cost_type=external` o senza configurazione →
  contributo 0 (no error)
- Esposto in `/cost-report/api/list` (livello job aggregato) +
  `/cost-report/api/job/{id}` (sia in `summary` che per ogni `line`)
- Campo derivato: `real_margin = total_accrued − total_cost_accrued`
  esposto entrambi i livelli (UI può mostrarlo accanto al margine
  contrattuale `over_under_now`)

**File toccati** (6):
- `app/main.py` — VERSION + auto-migrate total_cost_accrued
- `app/models/models.py` — JCL.total_cost_accrued
- `app/services/cost_line_sync.py` — compute cost_accrued nel
  recompute_cost_line_actual + return dict
- `app/routers/cost_report.py` — esposizione list + detail
- `app/routers/finance.py` — endpoint /cashflow HTML
- `app/templates/base.html` — sidebar link Cashflow
- `app/templates/pages/cashflow.html` — nuovo

**Cosa NON è incluso**:
- UI cost-report che mostra real_margin visivamente (badge/colonna)
- R7.x continuazione (planning_bookings 1500 righe — skipped in
  autopilota, troppo rischio refactor invasivo)
- F15 esecuzione reale (Matteo lancia script sul Mac)
- α.68 Supplier/SupplierInvoice (modulo nuovo, prossimo)
- Frontend polish (in caldo per esplicita richiesta)

**Smoke**: AST parse OK su 5 file. Auto-migrate idempotente.

## v3.5.0-alpha.66.20.1 — F15 script test corpus capitolati (11 maggio 2026)

Aggiunto `scripts/test_capitolati_corpus.py` per validare parser
DeliveryTemplate sui 17 capitolati reali in `docs/capitolati_esempio/`.

**Funzionalità**:
- Batch iterazione su tutti i file della directory
- Per ciascuno: estrazione testo + chiamata `parse_delivery_template` +
  conta blocchi popolati su 8 + ai_confidence + code/name/broadcaster
- Banner colorato ANSI (verde ≥7, giallo ≥4, rosso <4 blocchi)
- Report finale: stats aggregati + frequenza blocchi (% file con
  ciascun blocco compilato) + lista errori
- Output JSON opzionale (`--json out.json`) per analisi successiva
- Filtri: `--file <name>` (singolo), `--skip <glob>` (esclusioni),
  `--limit N` (primi N)
- Stima costo + tempo all'avvio (~$0.20-0.40 per run completo Sonnet 4.6)

**Uso tipico**:
```bash
# Sul Mac di Matteo, venv attivo, provider AI configurato in /settings:
python scripts/test_capitolati_corpus.py

# Singolo per debug:
python scripts/test_capitolati_corpus.py --file Netflix_Deliverables.txt

# Skip xlsx pesanti:
python scripts/test_capitolati_corpus.py --skip "*.xlsx"
```

Output atteso: tabella per file con `n_blocchi/8 + confidence% +
elapsed + code estratto`, riassunto finale con bar-chart frequenza
blocchi. Permette di vedere subito quali blocchi (es. `head_format`,
`textless_format`) sono spesso non menzionati nei capitolati e quali
sono universali (`video_specs`, `audio_specs`).

**Note**:
- Non eseguito qui (env Windows sandbox senza fastapi installato +
  no API key). Eseguibile sul Mac Matteo quando vuole validare.
- Costo medio per file: ~4k token input + 1-2k output = $0.02 con
  Sonnet 4.6 e cache attiva.

## v3.5.0-alpha.66.20 — α.66 InvoicePayment + R7.x extraction + Fase 2 step C Capitolati (11 maggio 2026)

Su richiesta Matteo "procedi con tutti e 4" (post recap roadmap).
α.65 saltato perché engine weighted hours già completo da prima
(`cost_line_sync._booking_hours_weighted` + `Job.weighted_revenue`).
Restano 3 sviluppi di sostanza + decisioni billing chiuse.

**3 decisioni semantiche billing chiuse con Matteo** (memoria
`project_billing_roadmap_alpha65plus`):
1. Overtime: solo APPROVED conta nei numeri maturati (pending in tooltip)
2. Day-unit: lineare hours_pesate / 8 (zero migrazione)
3. Booking interni (no JCL): esclusi dal weighted total

Engine attuale (`_booking_hours_weighted`) già rispetta #1 (commento
codice: "pending → ore overtime NON pesate"). Conferma utente
documentata, no codice da scrivere.

**α.66 InvoicePayment** (cashflow revenue-side, sblocca DSO/cassa):
- Modello `InvoicePayment` (tenant_id, invoice_id, amount, payment_date,
  method, reference, notes, recorded_by_user_id, created_at)
- `Invoice.amount_paid` denormalizzato (server_default 0)
- `Invoice.payments` relationship cascade delete
- Auto-migrate boot: `ALTER TABLE invoices ADD COLUMN amount_paid REAL`
- Endpoint:
  - `GET /finance/api/invoices/{id}/payments` (lista + remaining)
  - `POST /finance/api/invoices/{id}/payments` (registra, auto-status)
  - `DELETE /finance/api/payments/{id}` (rollback + ricomputa)
  - `GET /finance/api/cashflow/{year}` (serie 12 mesi: invoiced/paid/outstanding)
- Helper `_refresh_invoice_payment_state`: idempotente, auto-set
  status=paid quando cumulato ≥ totale (-0.01 tolleranza), revert
  a sent se rollback parziale

**R7.x extraction** (planning.py da 4296 → 3678 righe, -14%):
- `planning_diag.py` (217 righe): 3 endpoint `/planning/api/diag/*`
  (booking-raw, scan-duplicate-overlaps, cleanup-all). Helper
  `_detect_dup_overlap_pairs` duplicato (20 righe pure). Import lazy
  di `_recalc_booking_envelope` + `_log_change` per evitare circolari.
- `planning_unavailabilities.py` (366 righe): 7 endpoint
  (`/unavailabilities`, `/my-unavailabilities`, `/.../pending`,
  `/.../approve`, `/.../reject`, DELETE, POST). Helper `_u_dict`
  duplicato. Import lazy `_parse_id_list`.
- Path esterni invariati. Marker `_LEGACY_*_RELOCATED` in planning.py
  per grep storici. Mount in main.py dopo `planning.router`.

**Fase 2 step C — Capitolati (F14 cablato)**:
- Nuovo prompt `PARSE_TEMPLATE_SYSTEM_PROMPT` in deliverables_parser.py
  che estrae i 8 blocchi DeliveryTemplate (video/audio/text/head/
  textless/naming/archive/metadata) + metadata (code/name/broadcaster/
  description/ai_confidence)
- Funzione `parse_delivery_template(text) -> dict`
- Router `app/routers/delivery_templates.py`:
  - `GET /delivery-templates/` (pagina HTML)
  - `GET /delivery-templates/api/list`
  - `GET /delivery-templates/api/{id}`
  - `POST /delivery-templates/api/parse` (file upload + AI)
  - `POST /delivery-templates/api/save` (FormData, parse JSON blocchi)
  - `PUT /delivery-templates/api/{id}`
  - `DELETE /delivery-templates/api/{id}` (soft-delete)
- Template `pages/delivery_templates.html`: tabella + 2 modali (import
  con preview a 8 blocchi editabili + dettaglio JSON read-only)
- Sidebar: link "Capitolati" in sezione "Media"

**File toccati** (10):
- `app/main.py` — VERSION + auto-migrate amount_paid + 3 include_router
- `app/models/models.py` — InvoicePayment class + Invoice.amount_paid +
  Invoice.payments relationship
- `app/models/__init__.py` — export InvoicePayment
- `app/routers/finance.py` — import InvoicePayment + 4 endpoint
  payment + cashflow + helper _refresh
- `app/routers/planning.py` — 2 sezioni rimosse (~617 righe), marker
  relocated
- `app/routers/planning_diag.py` — nuovo (217 righe)
- `app/routers/planning_unavailabilities.py` — nuovo (366 righe)
- `app/routers/delivery_templates.py` — nuovo (~220 righe)
- `app/services/finance.py` — niente (già OK da α.66.19)
- `app/services/deliverables_parser.py` — +75 righe PARSE_TEMPLATE
- `app/templates/base.html` — link sidebar Capitolati
- `app/templates/pages/delivery_templates.html` — nuovo (~280 righe)

**Smoke**: AST parse OK su 10 file. Endpoint:
- 3 diag esposti su nuovo router
- 7 unavailabilities su nuovo router
- 4 payment + 1 cashflow su finance
- 7 delivery_templates su nuovo router
+22 endpoint totali, planning.py -617 righe.

**Cosa NON è incluso**:
- UI cashflow timeline (l'endpoint c'è, pagina HTML da fare)
- Test E2E sui 17 capitolati in `docs/capitolati_esempio/` (F15)
- Modulo Supplier/SupplierInvoice (α.68)
- Resource cost-side hourly_cost (α.67)
- Frontend polish (in caldo da richiesta utente)

## v3.5.0-alpha.66.19 — Frontend polish round 2: topbar theme switcher + dashboard widgets (11 maggio 2026)

Secondo giro dopo feedback "procedi con prossimi step". Aggiunti 4
miglioramenti, 3 frontend + 1 backend endpoint.

**Topbar theme switcher** (visibile su ogni pagina):
- Bottone palette in topbar (sx della campana notifiche)
- Click = cycle al tema successivo (toast con nome)
- Hover = popover 2-col con 10 swatch (Indigo/Slate/Forest/Sand/
  Midnight/Copper/Plum/Teal/Mono/Broadcast), click su swatch =
  switch immediato
- Stato `active` su tema corrente, persistito localStorage
  (riusa setTheme + applyTheme esistenti)

**Dashboard capacity-week strip** (sotto stat-grid):
- Card "Capacità settimana" con 7 celle giorno (lun-dom della
  settimana corrente)
- Per ogni giorno: nome (DOW), numero, ore booking totali,
  fill-bar % capacità (8h × N risorse interne)
- Colore per soglia: green ≤50%, indigo ≤80%, amber ≤100%, rose
  >100% (overbooked)
- Today highlighted con bordo cyan + indigo-bg; weekend opacity 0.7
- Tooltip con `ore / capacità (percent%)`

**Dashboard upcoming deadlines** (card sotto P&L):
- Top 5 job con end_date entro 14 giorni (status=active)
- Border-left urgenza: rosso ≤3gg, amber ≤7gg, indigo ≤14gg
- Click row = redirect a /jobs/{id}
- Empty state se nessun job in scadenza

**Dashboard margine per reparto** (card affianco a deadlines):
- Backend nuovo: `GET /finance/api/report/departments/{year}`
- Service: `departments_pl_summary(db, year)` aggrega
  JobCostLine.total_accrued per PriceItem.department_id, split
  ricavi (is_billable=True) vs costi (is_billable=False), filtro
  via Job.start_date OR Job.end_date intersezione anno
- Bucket "_unallocated" per JCL senza price_item
- Rows ordinati per volume desc, mostrano bar a doppia traccia
  (revenue verde 55%, cost rosso 55% blend), margine numerico
  pos/neg colorato

**File toccati**:
- `app/main.py` — VERSION
- `app/templates/base.html` — nuovo `topbar-theme-wrap` + cache-buster
- `app/static/js/global.js` — `MF_THEME_META`, `topbarThemeCycle()`,
  `_topbarThemeRender()`, hook su DOMContentLoaded + setTheme
- `app/static/css/main.css` — `.topbar-theme-pop` + `.tt-cell`
- `app/templates/pages/dashboard.html` — capacity card + deadlines
  card + dept-roi card + CSS (`.cw-*`, `.dl-*`, `.dr-*`) +
  `loadCapacityWeek()` + `renderUpcomingDeadlines()` + `loadDeptRoi()`
- `app/services/finance.py` — `departments_pl_summary()` + import
  Department/JobCostLine/PriceItem
- `app/routers/finance.py` — endpoint `/api/report/departments/{year}`

**Cosa NON è incluso (giro 3)**:
- Density preset "broadcast" come variante compatta separata
- Timeline item dept-icon inline
- Quick filter su capacity-week (click giorno → planning filter
  resource/date)

**Smoke**: topbar palette renderizzato, capacity-week con
heatmap+today bordo, deadlines popolate (se DB ha job in scadenza),
dept-roi tile fallback "non disponibile" se endpoint vuoto.

## v3.5.0-alpha.66.18 — Frontend polish: tema Broadcast + stat-card rich + timeline flat-mode (11 maggio 2026)

Su richiesta Matteo "rendere il frontend più sleek, sfruttare meglio
vis.js": primo giro di design system + planning timeline. Pattern
caveman: tutto incrementale, no rewrite, additivo via classi nuove.

**Tema `broadcast`** (DaVinci/Avid-style, 10° tema):
- Palette flat neutro freddo `#1c1c1f`, accento **cyan `#00d4ff`**
- Radius ridotti (4/6 px), shadow piatte, no glass, no gradient
  decorativo
- Override automatici scoped: sidebar (border-left cyan su active),
  card (no shadow), th (uppercase + letter-spacing), tabelle (hover
  cyan), vis-timeline (linea oggi cyan + glow, selected con outline
  cyan)
- Logo-mark con bordo cyan invece di pieno indigo
- Registrato in `MF_THEMES` global.js + entry `THEMES` settings.html

**Stat card variants** (`main.css`):
- `.stat-card-accent|green|amber|rose|purple` → border-left 3px del
  colore corrispondente (rhythm visivo sulla riga stat-grid)
- `.stat-trend.up|down|flat` → pill colorato per delta vs periodo prec.
- `.kpi-bar` → 5-cell mini-bar, classe `.on` per filled, `.warn`
  (>=70%), `.danger` (>=85%). Costruita via DOM (no innerHTML).
- Dashboard: 4 stat-cards usano i 4 colori + 2 kpi-bar (jobs
  attivi/totali, risorse interne/totali).

**Planning timeline broadcast scope** (`planning.css`):
- Quando html.theme-broadcast attivo: items flat (no bevel 3D, radius
  3px, shadow piatta), heatmap capacity più alta (9px) e contrasto
  rinforzato su sfondo nero `#0f0f12`
- Reparti label UPPERCASE 14px + letter-spacing 0.06em
- tab attivo + btn-group attivo in cyan
- `#tl-drag-overlay` restyled con bordo cyan + time cyan + dur verde

**File toccati**:
- `app/static/css/main.css` — +146 righe (tema broadcast + stat
  variants + kpi-bar)
- `app/static/css/planning.css` — +44 righe (override broadcast scoped)
- `app/static/js/global.js` — MF_THEMES +1
- `app/templates/pages/settings.html` — THEMES array +1
- `app/templates/pages/dashboard.html` — 4 stat-card classes + 2
  kpi-bar + renderKpiBar()
- `app/templates/base.html` — cache-buster main.css/global.js bumped
- `app/templates/pages/planning.html` — cache-buster planning.css

**Cosa NON è incluso** (giro successivo se Matteo apprezza):
- Dashboard rebuild profondo (capacity-week strip, dept ROI gauge,
  upcoming deadlines)
- Timeline item dept-icon inline (richiede rendering injection)
- Density preset "broadcast" come variante compatta separata
- Toggle in topbar per cambio tema rapido senza passare da /settings

**Smoke**: theme switch via `/settings → Aspetto → Broadcast` (cyan
accent persistito via localStorage), dashboard stat-card colorati +
kpi-bar disegnati al load.

## v3.5.0-alpha.66.17.3 — Sprint R7 MVP: deprecated POST clients duplicato (11 maggio 2026)

Audit consigliava la rimozione del CRUD duplicato di `clients` e `jobs`
in `planning.py` (già esistente in router dedicati). Verifica template
rivela però che `GET /planning/api/clients` e `GET /planning/api/jobs`
sono **attivamente usati** da finance.html / dashboard.html / dam.html /
planning.html per dropdown e multi-filter (snake-payload più snello).

**Decisione conservativa**: NON rimuovere; marcare deprecated solo i POST
duplicati (per disincentivare nuovo utilizzo).

**Modifiche**:
- `POST /planning/api/clients` → `deprecated=True` + docstring che
  rinvia a `POST /clients/api`. Subset di campi vs il completo
  (legal_form, sdi_code, pec, città).
- `POST /planning/api/jobs` già `deprecated=True` (R3 sweep precedente).
- `GET /planning/api/clients` + `GET /planning/api/jobs` + `PUT
  /api/jobs/{id}/status` + `GET /api/jobs/{id}` lasciati: usati da UI.

**Backlog R7.x**:
- Estrarre `app/routers/planning_diag.py` con i 3 endpoint `/diag/*`
  (booking-raw + scan-duplicate-overlaps + cleanup-all). ~200 righe.
- Estrarre `app/routers/planning_unavailabilities.py` (~500 righe).
- Estrazione bookings `app/routers/planning_bookings.py` (la grossa
  parte, ~1800 righe). Richiede gestione attenta delle helper condivise.

**Smoke**: 303 routes invariato, version 3.5.0-alpha.66.17.3.

---

## v3.5.0-alpha.66.17.2 — Sprint R6 Step 2: capability decorator registry (11 maggio 2026)

Continua R6. Chiude **audit pattern systemico N**: drift fra
`_ACTION_HANDLERS` (23 handler) e `VALID_ACTION_TYPES` (13 statici) →
**10 capability invisibili al parser legacy markdown** (path Ollama/
Perplexity).

**Nuovo `app/services/ai_capability_registry.py`** (108 righe):
- Decorator `@ai_capability("name", category=None)` registra handler
- `_REGISTRY: dict[name, (fn, category)]` interno
- `get_handlers()`, `get_action_types()`, `get_categories()`,
  `get_handler(name)`, `list_capabilities()` API pulita
- Categorie auto-inferite: `propose_*`/`update_*` → mutation;
  `analyze_*`/`find_*`/`query_*`/`read_*`/`list_*`/`web_search` → readonly

**Decoro 23 handler** in `ai_assistant.py` con `@ai_capability(...)`:
- Sostituzione automatica via script regex (1 commit clean)
- `_h_propose_client` → `@ai_capability("propose_client")\n_h_propose_client`
- ... per tutti i 23

**`_ACTION_HANDLERS` ora derivato dal registry**:
```python
_ACTION_HANDLERS = _registry_get_handlers()
```
API esterna invariata (resta dict `{name: fn}`); call site
`_ACTION_HANDLERS.get(...)` continuano a funzionare.

**`VALID_ACTION_TYPES` sincronizzato in-place** alla fine del module
import (`_sync_legacy_parser_action_types()`). Identità del set object
preservata: chi ha fatto `from ai_legacy_parser import VALID_ACTION_TYPES`
continua a vedere le 23 capability complete.

**Drift verificato chiuso**:
```
Handlers registered: 23
VALID_ACTION_TYPES count: 23
Drift check (handlers vs valid types): True ✓
```

**10 capability prima invisibili al parser legacy** ora supportate:
update_quote, propose_move_booking, propose_resize_booking,
propose_delete_booking, analyze_conflicts, find_free_slots,
propose_recurring_bookings, propose_bulk_move,
propose_transmit_to_billing, query_project_finance, list_settings_schemas,
read_setting, update_setting.

**Smoke**: 303 routes invariato, 23 handler decorati, drift chiuso,
version 3.5.0-alpha.66.17.2.

---

## v3.5.0-alpha.66.17.1 — Sprint R6 Step 1: estrai legacy parser (11 maggio 2026)

Continua R6 — Split ai_assistant.py 2287 → 1785 righe (-22% totale dopo
.17.0+.17.1).

**Nuovo `app/services/ai_legacy_parser.py`** (156 righe):
- `VALID_ACTION_TYPES` set (13 capability legali per parser legacy)
- `_balanced_json_at(text, start)` parser balanced-brace
- `extract_proposed_actions(reply_text)` regex + safe_json_parse + cleanup

**Path legacy**: usato SOLO da provider che non supportano tool_use nativo
(Ollama/Perplexity). Provider con tool_use (Claude/OpenAI/Gemini) usano
`ai_loop.advance_loop` che gestisce direttamente `tool_use` blocks.

**`ai_assistant.py`**: blocco 60-180 sostituito con re-export per compat
call site (router/ai.py importa `VALID_ACTION_TYPES` + `extract_proposed_actions`).

**Identità preservata**: `assert VALID_ACTION_TYPES is legacy_vat` ✓.

**Smoke**: parser estrae 1 azione da text test, 303 routes invariato,
version 3.5.0-alpha.66.17.1.

---

## v3.5.0-alpha.66.17.0 — Sprint R6 Step 0: estrai ai_context.py (11 maggio 2026)

Apre R6 — Split ai_assistant.py. Audit pattern systemico G "file giganti":
2287 righe mischiavano 4 responsabilità non correlate.

**Nuovo `app/services/ai_context.py`** (516 righe):
- `CURRENT_TENANT = 1` (constante modulare R1 stub)
- `ASSISTANT_SYSTEM_PROMPT` (110 righe markdown system prompt completo)
- `_short_money(v)` helper formato €
- `build_context(db, project_id, quote_id, job_id, page)` overview DB
- `_build_planning_context(db, project_id, job_id)` planning viva

Tutte le query già scoped tenant (R1 lavoro precedente preservato).

**`ai_assistant.py`**: 2339 → 1899 righe (-19%). Blocco righe 50-497
sostituito con re-export per compat (`build_system_prompt` continua
a importare `ASSISTANT_SYSTEM_PROMPT` + `build_context` come prima).

**Identità preservata**: `ASSISTANT_SYSTEM_PROMPT is ctx_prompt` ✓
e `build_context is ctx_build` ✓.

**Smoke**: 303 routes invariato, version 3.5.0-alpha.66.17.0.

---

## v3.5.0-alpha.66.16.4 — Sprint R10: AI token tracking + cost analytics (11 maggio 2026)

Apre R10 — AI token tracking + rate limit per-user. Step 0+1 in 1 versione.

**Nuovo modello `AIUsageLog`** (`app/models/models.py`):
- 1 riga per ogni call API a un provider
- Campi: tenant/user/conv/provider/model + token cold/cache_read/cache_create/output
  + `cost_usd` calcolato + `call_kind` + `stop_reason` + `duration_ms`
- Indici su `tenant_id`, `user_id`, `conversation_id`, `created_at`
- Tabella creata da `create_tables()` al boot (no ALTER necessario)

**Tabella prezzi `MODEL_PRICING_USD_PER_M_TOKENS`** (`app/services/ai_provider.py`):
- 14 modelli mappati: Claude 4.x, OpenAI (4o/o1/o3-mini), Gemini 2.0/1.5,
  Perplexity Sonar, Ollama (=$0)
- Prezzi maggio 2026 cold/output/cache_read/cache_create per 1M tokens
- Cache_read Anthropic = 0.1× cold (ricavato da pricing pubblico)

**Helper `compute_cost_usd(model, input, output, cache_read, cache_create)`**:
- Calcolo lineare. Modelli sconosciuti → 0.0 (no errore).
- Float precision sufficiente per analytics; Decimal solo per fatturazione.

**Helper `log_ai_usage(db, ...)`**:
- Persiste 1 riga AIUsageLog. NO commit (transazione del caller).
- Best-effort: errori loggati, mai re-raise (logging non blocca AI response).

**Hook in `ClaudeProvider.chat_with_tools`**:
- Aggiunti kwargs opzionali `usage_db`, `usage_user_id`,
  `usage_conversation_id`, `usage_tenant_id`.
- Se passati, registra automaticamente con tutti i token estratti da
  `resp.usage` (incluso cache_read/cache_create per cache hit ratio).
- `duration_ms` misurato con `time.time()`.

**Migrazione `ai_loop.advance_loop`**:
- Propaga db/user_id/conv_id/tenant_id alla chat_with_tools.
- Try/except `TypeError` per fallback compat su provider non-Anthropic
  (OpenAI/Ollama/Gemini chat_with_tools non ancora migrato — segue in R10.2).

**Nuovo endpoint `GET /ai/api/usage`**:
- Query params: `period_days` (1-365, default 30), `by` (user|model|day),
  `user_id` opzionale.
- RBAC: `view_finance` per vedere tutti i users; standard user vede
  solo i propri.
- Response: `totals` (token+cost+calls+cache_hit_ratio) + `breakdown`
  raggruppato.
- Tenant scope via `current_tenant_id()` (DI stub).

**Smoke E2E**:
- Tabella `ai_usage_logs` creata con 15 colonne ✓
- Cost claude-sonnet-4-6 5k input + 1k out → $0.030
- Cost claude-sonnet-4-6 500 cold + 4500 cached + 1k out → $0.0179 (40% saving)
- 303 routes (+1 nuovo `/ai/api/usage`), version 3.5.0-alpha.66.16.4

**Backlog R10.2** (futuro):
- Migrazione hook usage_* a OpenAI/Gemini/Ollama chat_with_tools
- Rate limit per-user (cap token/day) — aggiungere middleware su `/ai/api/chat`
- UI dashboard `/settings#ai-usage` con grafico daily cost

---

## v3.5.0-alpha.66.16.3 — Sprint R4 Step 2: migrate planning router a booking_mutate (11 maggio 2026)

Continua R4. Migra il router planning per centralizzare TUTTI i check
slice-lock attraverso `booking_mutate`.

**`_assert_no_blocking_slice`** (planning.py:45) — wrapper interno ora
delega a `booking_mutate.assert_slice_lock_safe`. API esterna identica:
mantiene tentative-bypass + 409 con `code=SLICE_LOCK_CONFIRM_REQUIRED`.
Tutti gli endpoint che lo usavano (PUT booking, delete_booking,
delete_assignment, update_state, update_execution) beneficiano
automaticamente del nuovo backend senza modifiche.

**Nuova `_assert_no_blocking_slice_for_dates`** (planning.py:84) —
wrapper analogo per check NEW dates (move/resize). Sostituisce 2 blocchi
inline ridondanti (update_assignment + multi-move) che richiamavano
`find_blocking_slice_for_dates` + manuale 409 mapping.

**Call site migrati esplicitamente**:
- `update_assignment` PUT (line 1979): 2 blocchi inline (~20 righe) → 2
  chiamate al wrapper.
- `multi_move` (line 2735): 2 blocchi inline (~30 righe) → 2 try/except
  con `assert_slice_lock_safe`. Pattern speciale `success:false + dict`
  mantenuto per compat client api() helper.

**Coverage R4 finale (Step 0+1+2)**: 7/7 call site SLICE_LOCK
centralizzati nel service `booking_mutate`. Pattern systemico O audit
chiuso completamente.

| Call site | Prima | Dopo |
|---|---|---|
| AI move (`_h_propose_move_booking`) | inline check + audit | `assert_mutation_safe` + `audit_booking_mutation` |
| AI resize (`_h_propose_resize_booking`) | inline check + audit | idem |
| router PUT booking | `_assert_no_blocking_slice` | wrapper → service |
| router PUT assignment | inline current+new | helper + helper-for-dates |
| router multi-move | inline loop con due check | service + try/except |
| router delete booking/assignment | `_assert_no_blocking_slice` | wrapper → service |
| router state/execution PATCH | `_assert_no_blocking_slice` | wrapper → service |

**Smoke**: import OK, 302 routes invariato, version 3.5.0-alpha.66.16.3.

---

## v3.5.0-alpha.66.16.2 — Sprint R4 Step 1: migrate AI handlers a booking_mutate (11 maggio 2026)

Continua R4. Migra i 2 AI handlers principali (`_h_propose_move_booking`,
`_h_propose_resize_booking`) per usare `booking_mutate.assert_mutation_safe`
al posto dei check inline duplicati.

**Cambio per ogni handler**:
- BEFORE: ~30 righe (conflict-check loop + slice-lock current/new
  inline + audit `db.add(BookingChange(...))` manuale)
- AFTER: 1 chiamata `assert_mutation_safe(db, b, new_values)` + 1
  chiamata `audit_booking_mutation(db, b, kind=, summary=, payload=)`

**Eccezioni gestite**:
- `BookingConflict` → `ValueError(f"Conflitto: ...")` (capability AI
  traduce in failure card UI)
- `SliceLocked` → `ValueError("Move/Resize bloccato: ...")` con stesso
  messaggio descrittivo di prima

**Bug-fix collaterale risize**: prima il check slice-lock era applicato
SOLO se `dm > 0` (resize allunga). Con `assert_mutation_safe` ora il
check è sempre applicato per coerenza. Edge case "resize accorcia ma
porta booking dentro slice" precedentemente non coperto.

**Smoke**: import AI handlers OK, 302 routes invariato,
version 3.5.0-alpha.66.16.2.

**Backlog R4.2+** (sprint successivi):
- Migrazione PUT /api/bookings/{id} in planning.py (~lines 1627+)
- Migrazione multi-move (~line 2704)
- Migrazione bulk-edit (~line 2336)
- Migrazione assignment update PUT (~line 1939)
- Migrazione delete + restore (~lines 2900, 3427)

---

## v3.5.0-alpha.66.16.1 — Sprint R4 Step 0: booking_mutate service (11 maggio 2026)

Apre R4 — Single mutation gate per Booking. Audit pattern systemico O:
SLICE_LOCK validato in 7+ posti diversi (router planning lines 64, 1955,
2380, 2723, 2732 + ai_assistant 1500, 2055) con copie inline divergenti.
Ogni nuovo mutator dimentica facilmente.

**Nuovo modulo `app/services/booking_mutate.py`** — 3 helper unificati:

1. **`assert_slice_lock_safe(db, b, *, new_dates=None, force_unlock=False)`**
   Single API per il check SLICE_LOCK in tutti i suoi 3 modi:
   - `new_dates=None` → check posizione CORRENTE (delete, state change)
   - `new_dates=(start,end)` → check NUOVA posizione (move/resize)
   - `force_unlock=True` → bypass (UI 409 confirm)
   Solleva `SliceLocked` con `payload` pronto per response 409.

2. **`assert_no_overlap_after(db, b, proposed_assignments)`**
   Verifica conflitti orari su altri assignment (esclusi quelli del
   booking corrente). Solleva `BookingConflict` con metadata.

3. **`audit_booking_mutation(db, b, *, kind, summary, payload, user_id)`**
   Crea `BookingChange` row con metadata standard. NON committa
   (transazione resta del caller — pattern E audit).

**Helper combinato `assert_mutation_safe`**: check completo
(slice-current + overlap + slice-new) in 1 chiamata. Per AI move/resize,
multi-move, bulk-edit.

**Eccezioni tipate**: `SliceLocked`, `BookingConflict`. Caller traduce
in HTTP 409 con codici standard (`SLICE_LOCK_CONFIRM_REQUIRED`,
`BOOKING_CONFLICT`).

**NB**: nessun call site migrato in questo step. R4.1 sostituirà i
check inline con chiamate al service nelle ~7 location (AI handlers
+ router planning + multi-move + bulk-edit).

**Smoke**: tutti gli import OK, 302 routes invariato,
version 3.5.0-alpha.66.16.1.

---

## v3.5.0-alpha.66.16.0 — Sprint R3: permission gate sweep cross-router (11 maggio 2026)

Chiude pattern systemico D dell'audit: 27 mutator senza permission gate
distribuiti su 6 router minori (oltre quote già fatto in α.66.14.5).
Censimento via subagent: 76 mutator totali → 49 già protetti (64%) → 27
da chiudere. Tutti coperti in questo sweep.

**Pattern applicato** (uniforme con quotes/finance):
```python
RequireXxx = Depends(requires_permission("perm_code"))

@router.post("/api/...", dependencies=[RequireXxx])
```

**Router protetti** (27 endpoint nuovi, 0 vecchi toccati):

### `finance.py` (5/5)
- `POST /api/timesheets` → `edit_planning_own`
- `POST /api/expenses` → `edit_invoices`
- `POST /api/invoices` → `edit_invoices`
- `POST /api/invoices/{id}/lines` → `edit_invoices`
- `PUT /api/invoices/{id}/status` → `edit_invoices`

### `pricelist.py` (7/7)
- `POST /api/categories` → `edit_pricelist`
- `PUT /api/categories/{cat_id}` → `edit_pricelist`
- `DELETE /api/categories/{cat_id}` → `edit_pricelist`
- `POST /api/items` → `edit_pricelist`
- `PUT /api/items/{item_id}` → `edit_pricelist`
- `DELETE /api/items/{item_id}` → `edit_pricelist`
- `POST /api/import` → `edit_pricelist`

### `resources.py` (5/5)
- `POST /api`, `PUT /api/{id}`, `DELETE /api/{id}` → `edit_resources`
- `POST /api/{id}/unavailability`, `DELETE /api/unavailability/{id}` → `edit_resources`
- **Closure leak salary** a viewer (audit MEDIUM): senza gate chiunque
  poteva mutare `monthly_gross_salary` via PUT.

### `dam.py` (2/2)
- `POST /api/assets/upload`, `DELETE /api/assets/{id}` → `edit_planning_all`
  (fallback in mancanza di `manage_assets` dedicato — da rivedere)

### `ai.py` (3/3)
- `POST /api/quotes/{id}/review` → `view_quotes` (read-AI)
- `POST /api/deliverables/parse` → `edit_quotes` (preludio creazione)
- `POST /api/deliverables/create-quote` → `edit_quotes` (CRITICO: scriveva
  Quote+QuoteLine senza alcun check)

### `planning.py` (4/6, 2 skip-by-design)
- `POST /api/clients` → `edit_clients`
- `POST /api/jobs` (deprecated) → `edit_planning_all`
- `PUT /api/jobs/{id}/status` → `edit_planning_all`
- `POST /api/bookings/{id}/restore` → `edit_planning_all`
- **Skip**: `POST /api/resource-presets` + `POST /api/booking-requests`
  → restano "autenticato basta" (semantica per design utente standard).

**Stato finale**: 76/76 mutator protetti (100%). Permission gate
sistemico chiuso.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.16.0.

---

## v3.5.0-alpha.66.15.4 — Sprint R2 Step 1: helper unique-aware + fix Project.code (11 maggio 2026)

Continua R2. Chiude **audit HIGH #2**: bug pre-check unicità non
bypassava soft-delete, causando IntegrityError 500 su INSERT con code
già usato in cestino.

**Nuovo helper** `app/services/soft_delete.py:is_unique_or_deleted_aware`:
- Signature: `(db, model, field, value, *, exclude_id=None, extra_filter=None) -> bool`
- Internamente fa `query(model).execution_options(include_deleted=True).filter(...)`
- Ritorna `True` se il valore è davvero unico (anche includendo cestino)
- Riusabile per Project/Quote/Job/Invoice/BillingBatch ovunque

**Fix concreto applicato**:
- `app/routers/projects.py:86` `create_project`: ora usa il helper.
  Errore 400 esplicito "anche se in cestino: ripristinalo o usa un altro
  codice" invece del 500 IntegrityError.

**Audit altri call site** (già a posto):
- `quotes.py:707` rename quote `number`: già con `include_deleted=True` ✓
- `quotes.py:1584` new-version quote: già con `include_deleted=True` ✓
- `billing.py:1067` reverse-quote new-version: già con `include_deleted=True` ✓
- `billing.py:768` Invoice.number unique: NON necessario (Invoice non è
  soft-deletable, è entità fiscale immutabile) ✓
- `billing.py` `_next_batch_code` + `quotes.py` `_next_quote_number_progressive`
  + `_next_job_code`: già migrati al numbering service α.66.14.8 con
  `include_deleted=True` ✓

**Smoke**: helper ritorna `True` per Project/Quote codes inesistenti su
DB reale Matteo, 302 routes invariato, version 3.5.0-alpha.66.15.4.

---

## v3.5.0-alpha.66.15.3 — Sprint R2 Step 0: soft-delete framework esteso (11 maggio 2026)

Apre R2 — Soft-delete framework completo. Audit pattern systemico B:
5 modelli avevano `deleted_at` come colonna ma solo 2 erano nel filter
auto → record cestinati visibili nelle query a default.

**`_SOFT_DELETE_MODELS` esteso** (`app/services/soft_delete.py:44`) da
`(Quote, Project)` a:
- Quote
- Project
- **PricelistSnapshot** (introdotta α.66.6)
- **PhysicalAsset** (introdotta α.66.9)
- **JobDeliverable** (introdotta α.66.9)

Effetto: ogni `db.query(PhysicalAsset)` (e altri 2) auto-applica
`WHERE deleted_at IS NULL`. Bypass via `execution_options(include_deleted=True)`
come da pattern esistente.

**Smoke**: `_install_soft_delete_filter()` registra il listener,
import resolve tutti i 5 modelli, 302 routes invariato.

**Cosa NON è ancora chiuso** (R2.1+):
- Pre-check unicità su Project.code/Quote.number rename → helper unique-aware
  (audit HIGH #2). Già fatto inline in `_next_quote_number_progressive`,
  manca per Project.
- Force-purge cascade incompleta su `JCLBilledSlice` / `BookingChange` /
  `JobResourceAssignment` orfani (audit MEDIUM services).

---

## v3.5.0-alpha.66.15.2 — Sprint R1 Step 2: tenant filter su query critiche (11 maggio 2026)

Continua R1. Applica `tenant_id == CURRENT_TENANT` alle query LIST + by-id
critiche dei 4 router maggiori per Quote/Job/JobCostLine/Asset. Chiude il
leak diretto cross-tenant (info disclosure su list); le query by-id nei
mutator restano scope-safe via PK + permission gate.

**File modificati**:
- `app/routers/quotes.py`: `quotes_page` + `list_quotes` filtrate. Costante
  modulare `CURRENT_TENANT = current_tenant_id()` (stub stile DI esistente).
- `app/routers/jobs.py`: `job_detail_page`, `get_job` + tutte le altre
  `db.query(Job).filter(Job.id == job_id)` ricevono il filter
  `Job.tenant_id == CURRENT_TENANT` via `replace_all`.
- `app/routers/cost_report.py`: `cost_report_page` + `list_cost_reports`
  filtrate; `CURRENT_TENANT` aggiunto al modulo.
- `app/routers/dam.py`: `dam_page`, `list_assets`, e tutte le by-id
  `Asset.id == asset_id` ricevono filter `Asset.tenant_id == CURRENT_TENANT`.

**Pattern adottato** (transitorio):
```python
from app.context import current_tenant_id
CURRENT_TENANT = current_tenant_id()  # stub R1.1: ritorna sempre 1
```
Importa lo stub a livello modulo; l'evoluzione futura sarà `Depends(get_tenant_id)`
per-endpoint, da fare quando il middleware popolerà `request.state.tenant_id`
(Fase 7 multi-tenant hard).

**NON è ancora coperto** (R1.3+):
- `app/services/cost_line_sync.py`, `services/billing_slice_guard.py`,
  `services/reverse_quote.py`, `services/data_export.py` ecc.
  Queste lavorano su entità già scoped via parent (Booking → tenant_id,
  Job → tenant_id) — il leak è indiretto. Sweep dedicato in R1.3 quando
  R1.2 sarà confermato dai test live.
- Router `billing.py`, `finance.py`, `hr.py`, `planning.py` (booking ce
  l'ha già, ma alcune query Job non lo applicano). R1.4.

**Smoke E2E**: 302 routes invariato. Query `Quote/Job/Asset filter
tenant_id=1` ritornano 0 record (DB Matteo vuoto). Nessun errore.
Version 3.5.0-alpha.66.15.2.

---

## v3.5.0-alpha.66.15.1 — Sprint R1 Step 1: app/context.py DI helper (11 maggio 2026)

Continua R1. Aggiunge il single source of truth per il tenant scope.

**Nuovo `app/context.py`**:
- `DEFAULT_TENANT_ID = 1` (costante)
- `current_tenant_id() -> int`: per service layer (no FastAPI). Stub
  ritorna 1.
- `get_tenant_id() -> int`: FastAPI dependency (`Depends(get_tenant_id)`).
  Stub ritorna 1.
- `get_optional_tenant_id() -> Optional[int]`: variante non-bloccante per
  endpoint pubblici.

In Fase 7 (multi-tenant hard) basta cambiare l'implementazione interna di
`current_tenant_id` (leggere da `contextvars` popolata da middleware auth)
senza toccare i call site. Tutti i router che useranno
`Depends(get_tenant_id)` saranno automaticamente future-ready.

**Smoke**: tutte le 3 funzioni ritornano 1 come da contract stub.
302 routes invariato, version 3.5.0-alpha.66.15.1.

**Prossimo (R1.2)**: applicare il filtro `tenant_id == current_tenant_id()`
alle query nei router per Quote/Job/JobCostLine/Asset (e Project che già
ce l'aveva ma in molti router non era filtrato).

---

## v3.5.0-alpha.66.15.0 — Sprint R1 Step 0: tenant_id ai modelli orfani (11 maggio 2026)

Apre il sprint **R1 — Tenant scope DI** del piano post-audit. Step 0:
aggiunge la colonna `tenant_id` ai 4 modelli orfani identificati
nell'audit HIGH #1 (Project l'aveva già). Comportamento runtime invariato
(default=1, backfill auto), preparazione per R1.1 (DI helper) e R1.2
(filtri nelle query).

**Modelli aggiornati**:
- `Quote.tenant_id`: `Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=1, index=True)`
- `Job.tenant_id`: idem
- `JobCostLine.tenant_id`: denormalized da `job.tenant_id` per scope cost-report efficiente
- `Asset.tenant_id`: denormalized da `project.tenant_id` per scope DAM senza JOIN

**Migrazione auto al boot** (`_auto_migrate_columns` in `main.py`):
- `quote_alter` esteso con `("tenant_id", "INTEGER NOT NULL DEFAULT 1")`
- Loop generico per `jobs`, `job_cost_lines`, `assets`: ALTER TABLE
  idempotente con default 1 (backfill automatico per record esistenti)

**UNIQUE constraints**: `Quote.number`, `Job.code` restano UNIQUE GLOBALI
per ora — saranno migrati a `UniqueConstraint(tenant_id, ...)` in R1.5
quando si attiverà multi-tenant hard. Memo: pattern identico a
Department/PriceCategory/DeliveryTemplate.

**Smoke E2E**:
- `_auto_migrate_columns()` su DB reale → 4 ALTER TABLE applicate
- `tenant_id present: True` su tutte e 4 le tabelle
- DB Matteo era vuoto (0 rows) → no backfill necessario
- 302 routes invariato, version 3.5.0-alpha.66.15.0

**Cosa NON è ancora attivo**:
- Le query nei router NON filtrano ancora su `tenant_id` per Quote/Job/
  JobCostLine/Asset → cross-tenant resta possibile finché non arriva R1.2.
- `app/context.py` con `current_tenant_id()` DI → R1.1 prossimo step.

---

## v3.5.0-alpha.66.14.9 — CSS extract da planning.html (11 maggio 2026)

Quick win post-audit #11. Apre il refactor "file giganti" iniziando dal
più gigante: `planning.html` da 7377 → 6747 righe (–9%, 1° passo PR1
del refactor planning suggerito dall'audit frontend).

**Nuovo file**: `app/static/css/planning.css` (682 righe, schema 1.0).
Selettori che vivono SOLO in /planning: `.pl-*`, `.tl-*`, `.tlb-*`,
`.sb-*`, `.fa-*` + override scoped vis-timeline.

**Modifica `planning.html`**:
- `<link rel="stylesheet" href="/static/css/planning.css?v=3.5.0-alpha.66.14.9">`
- Blocco `<style>` ridotto a 1 commento esplicativo + chiusura.

**Beneficio immediato**:
- Cache HTTP indipendente: una modifica CSS non invalida tutto l'HTML
  della pagina (era unico cache key).
- Hot-reload selettivo: editor live-reload solo del file CSS toccato.
- IDE indicizza meglio: 6747 righe HTML vs 7377 prima → completion JS
  più veloce.
- Diff git pulito: modifiche stilistiche separate da modifiche struttura.

**NON è in questa versione** (PR2/PR3 dell'audit):
- Spezzare `planning.html` in partial Jinja (modal booking, view tabs,
  filtri, bulk).
- Spezzare il blocco `<script>` JS in moduli `static/js/planning/*`.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.9. CSS path
`/static/css/planning.css` accessibile via StaticFiles mount esistente.

---

## v3.5.0-alpha.66.14.8 — Numbering service unificato + soft-delete bypass everywhere (11 maggio 2026)

Quick win post-audit #9+#10 (combinati). Chiude la mancanza di soft-delete
bypass nei progressivi `_next_*_code` e centralizza la logica in un service
unico (Pattern systemico C dell'audit).

**Nuovo `app/services/numbering.py`**:
- `next_progressive_code(db, model, prefix, *, code_field, include_deleted, extra_filter)`:
  ritorna `f"{prefix}{N:03d}"` libero. Default `include_deleted=True`
  → bypass del soft-delete event-listener. Tail `vNN` di versioning quote
  gestito (ricava base prima di incrementare).
- `next_year_progressive(db, model, *, base, ...)`: helper sopra il primo
  per pattern `{base}-{anno}-{NNN}`.
- `with_retry_on_unique(fn, retries=3)`: wrapper retry-on-IntegrityError
  per la race condition residua (TODO: migrazione a transazione pessimistica
  in sprint R4 — Booking mutation gate).

**Migrate**:
- `_next_quote_number_progressive` (`quotes.py`): 25 righe → 3.
  Comportamento identico (già aveva include_deleted=True, ora consolidato).
- `_next_job_code` (`quotes.py`): aggiunto `execution_options(include_deleted=True)`.
  **Bug fix**: prima i job in cestino liberavano il code → al ripristino
  collisione UNIQUE.
- `_next_batch_code` (`billing.py`): refactor + aggiunto include_deleted=True.
  Stesso bug (BB cestinati liberavano il code).

**Smoke E2E** sul DB reale Matteo:
- `next quote: Q-2026-001` (DB vuoto → primo numero ok)
- `next batch: BB-2026-003` (esistono 2 batch, tenant_id=1 filter ok)

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.8.

**Cosa NON è ancora fatto** (R4 sprint dedicato):
- Race condition: con 2 utenti concorrenti, SELECT max + INSERT non è
  atomico → IntegrityError visibile. `with_retry_on_unique` esiste ma
  non è ancora wrappato sui call site (richiede refactor signature).
- Project.code rename pre-check: ancora non bypassato (audit HIGH #2).
  Sarà chiuso in sprint R2 "Soft-delete framework completo".

---

## v3.5.0-alpha.66.14.7 — Anthropic prompt caching (11 maggio 2026)

Quick win post-audit #8 — quello con il ROI economico più alto. Riduce
il costo input ricorrente del copilot Claude **fino al 90%** (Anthropic
fattura le cache hit a 0.1× del prezzo cold).

**Modifica `ClaudeProvider.chat_with_tools`** (`ai_provider.py:257`):
- **System prompt**: se passato come stringa, wrap in
  `[{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}]`.
  Compatibile con call site esistenti (advance_loop passa stringa).
- **Tools**: l'ULTIMO tool dell'array tools riceve `cache_control` →
  Anthropic estende il cache fino a quel punto (system + tools cachato
  insieme, cumulativo).
- **Soglia minima 1024 tokens** (Claude 3.x+): sotto quella il marker
  viene ignorato senza errore. Il system prompt MediaFlow + tools schema
  sono ~3-5k tokens, ampiamente sopra soglia.

**Logging cache stats**: estraggo `cache_creation_input_tokens` e
`cache_read_input_tokens` dalla `resp.usage` Anthropic. Logga a INFO con
`hit_ratio` per ogni call con almeno una cache stat. Utile per misurare
saving reale; lasciare attivo finché confermato il vantaggio.

**Esempio risparmio realistico**:
- Copilot ~10 turni/sessione × 5k system+tools tokens × 30 utenti/giorno
- Cold: 30 × 10 × 5000 × $3/M = $4.50/giorno × 30gg = **$135/mese**
- Cached (90% hit): $4.50 × 0.1 + $4.50 × 0.1 (cache create) ≈ **$13.5/mese**
- Saving: **~90%** sui costi input ricorrenti

**Provider OpenAI/Gemini**: prompt caching ha logica diversa (OpenAI è
automatico ≥1024 tokens, Gemini Context Caching API è esplicita ma
overhead setup). Lasciato per follow-up dedicato.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.7. Lo smoke
puro non triggera la cache (richiede API key reale + 2 turni back-to-back),
verificare in produzione via logger INFO `[anthropic cache] read=N ...`.

---

## v3.5.0-alpha.66.14.6 — Slice-lock re-check su new dates AI move/resize (11 maggio 2026)

Quick win post-audit #7. Chiude bypass slice-lock via AI handlers
(audit HIGH services #5).

**Bug**: `_resolve_booking_for_planning` chiamava `find_blocking_slice(b)`
sulla posizione **OLD** del booking. Un booking che parte FUORI periodo
fatturato e viene mosso DENTRO nuova finestra, passava il check sulla
vecchia posizione e poi mutava DENTRO uno slice locked → invariante
α.66.5 aggirata via copilot.

**Fix `_h_propose_move_booking`**: dopo conflict-check sui new_values,
prima dell'apply, se `b.job_cost_line_id`:
- calcola `new_min_date / new_max_date` da `(ns, ne)` di tutti gli assignment
- chiama `find_blocking_slice_for_dates(jcl_id, new_min, new_max)`
- se ritorna slice → `ValueError("Move bloccato: ...")`

**Fix `_h_propose_resize_booking`**: se `dm > 0` (allunga) e
`new_max_date > old_max_date`:
- chiama `find_blocking_slice_for_dates(jcl_id, old_max, new_max)`
- se slice nuovo entrato in periodo billed → `ValueError("Resize bloccato: ...")`

**Delete**: già coperto dal check OLD-position in
`_resolve_booking_for_planning` (cancellare un booking dentro slice billed
era già rifiutato).

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.6.

**Verifica live (manuale, richiede setup)**:
1. Crea slice billed JCL X per periodo [10/06 → 20/06].
2. Crea booking JCL X per 5/06 → 7/06 (fuori slice). Nessun lock visivo.
3. Da copilot: "Sposta il booking #N di 7 giorni avanti". L'AI propone
   move shift_minutes=10080 → Apply → ora ValueError "Move bloccato:
   booking dentro periodo già fatturato [10/06 → 20/06]".
4. Idem per resize: "estendi il booking di 10 giorni" → bloccato.

---

## v3.5.0-alpha.66.14.5 — Permission gate mutator quote (11 maggio 2026)

Quick win post-audit #6. 11 mutator del router quotes erano sprovvisti di
permission check (audit HIGH #4). Solo 7 endpoint avevano `if not
has_permission(user, "edit_quotes")` inline; gli altri erano accessibili
a chiunque autenticato.

**Nuovo pattern**:
- Module-level `RequireEditQuotes = Depends(requires_permission("edit_quotes"))`
- Applicato come `dependencies=[RequireEditQuotes]` nel decoratore router.
- 403 automatico se permesso mancante, prima ancora che il body venga letto.

**11 endpoint protetti**:
- `POST /api/{quote_id}/promote-line-to-cost-line`
- `POST /api/reverse-attach`
- `POST /api` (create quote)
- `PUT /api/{quote_id}/status` (transizione stato — più impattante)
- `PUT /api/{quote_id}/category-discount`
- `PUT /api/{quote_id}/lines-reorder`
- `PUT /api/{quote_id}/category-order`
- `POST /api/{quote_id}/lines` (add line)
- `PUT /api/{quote_id}/lines/{line_id}` (update line)
- `DELETE /api/{quote_id}/lines/{line_id}`
- `POST /api/{quote_id}/convert-to-job` (legacy, marcato `deprecated=True`)

**Endpoint con check inline preesistente**: lasciati invariati (la
ridondanza dependency + check non rompe nulla, e il messaggio italiano
inline è più informativo del 403 generico).

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.5.

**Verifica live**: utente con ruolo `viewer` (no `edit_quotes`)
- POST `/quotes/api/{id}/lines` → 403 "Permesso negato" (prima passava)
- DELETE `/quotes/api/{id}/lines/{lid}` → 403 idem
- POST `/quotes/api/{id}/duplicate` → 403 (preesistente, identico)

---

## v3.5.0-alpha.66.14.4 — Upload copilot security (auth + magic-bytes + ownership) (11 maggio 2026)

Quick win post-audit #5. Chiude 3 buchi documentati nell'audit AI:
upload accettato senza auth, validazione MIME basata solo su estensione,
ownership file_id non verificata.

**Auth required** su `POST /ai/api/upload` (`app/routers/ai.py:42`):
- Cookie JWT obbligatorio. Senza → 401 "Autenticazione richiesta".
- In dev (default) il fallback "primo admin attivo" passa tramite
  `_resolve_current_user` (resta funzionale per demo).
- In prod con `AUTH_REQUIRED=true` (α.66.14.2) → fail-closed.

**Magic-bytes validation** (`copilot_attachments._validate_magic_bytes`):
- Verifica i primi byte del content prima di scrivere su disk.
- Tabella `MAGIC_BYTES`: `.pdf` (`%PDF-`), `.docx` (ZIP `PK\\x03\\x04`),
  `.png`, `.jpg/.jpeg`, `.gif`. `.webp` validato con check RIFF + offset 8-12.
- `.txt`/`.md` plain text → niente magic, lascia passare.
- Un `evil.pdf` contenente HTML/JS → `ValueError` 400 senza toccare il FS.

**Ownership file_id** (`copilot_attachments._ownership_ok`):
- Convenzione: `file_id = f"{user_id}-{uuid32}"` (sostituisce uuid puro).
- `_make_image_block_from_attachment(att, user_id=...)` rifiuta file_id
  che non iniziano con `{user_id}-`. Pattern non vincola persistence DB
  (manifest resta in-memory client) ma chiude il leak: chi conosce un
  UUID altrui non può linkarlo come allegato del proprio messaggio.
- `build_user_content_blocks(..., user_id=...)` passa user_id ai check.
- `/ai/api/chat` propaga `user_id` da `_resolve_current_user` esistente.

**API change**: `save_attachment(filename, content, *, user_id)` —
parametro `user_id` ora obbligatorio. Solleva `ValueError` se mancante.
Il client riceve `file_id` con prefisso utente (trasparente lato UI).

**Smoke E2E**:
- `_validate_magic_bytes('.pdf', b'NOTAPDF')` → ValueError ✓
- `_validate_magic_bytes('.pdf', b'%PDF-1.4 valid')` → OK ✓
- `_ownership_ok('1-abc', 1)` → True; `('1-abc', 2)` → False ✓
- 302 routes invariato, version 3.5.0-alpha.66.14.4.

---

## v3.5.0-alpha.66.14.3 — Tenant scope build_context AI (11 maggio 2026)

Quick win post-audit #4. Chiude il pattern "AI vede tutti i tenant"
documentato nell'audit AI/Copilot. `build_context` e
`_build_planning_context` ignoravano `tenant_id` su tutte le query
overview → cross-tenant data leak latente in Fase 7.

**Costante modulare** `CURRENT_TENANT = 1` in `app/services/ai_assistant.py`
(stesso pattern dei 13 router già scoped).

**Filtri aggiunti su entità con `tenant_id`**:
- `Client`, `PriceItem`, `PriceCategory`, `Department`, `Resource` in
  `build_context` (overview + lista clienti)
- `Booking` in `_build_planning_context` (booking 14gg + conflitti +
  carico settimana)
- `Resource` outerjoin in `_build_planning_context` per scope
  `ResourceUnavailability` (holiday rows con `resource_id` NULL passano)

**Modelli SENZA `tenant_id` (TODO R1)**: Project, Quote, Job, JobCostLine,
Asset. Restano cross-tenant nelle query overview con commento esplicito
`# TODO R1`. Saranno migrati nel sprint di consolidamento R1.

**Smoke E2E**: `build_context()` boot OK, ctx_len 8535 char, query
SQL visibili con `WHERE tenant_id = ?` per le 5 entità scoped.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.3.

---

## v3.5.0-alpha.66.14.2 — Auth fail-closed via env flag (11 maggio 2026)

Quick win post-audit #3. Chiude il pattern "fallback al primo admin
attivo" che esisteva in 5 router (ai/clients/settings/hr/planning) come
helper privato `_resolve_current_user`. In dev resta utile per il flusso
demo single-user, ma in produzione era un'auth bypass effettivo: cookie
JWT scaduto/assente → impersonificazione admin trasparente.

**Nuova settings flag** (`app/config.py:auth_required`):
- Default `False` (dev/demo: fallback comportamento storico)
- Set `AUTH_REQUIRED=true` in `.env` per produzione → fail-closed:
  token assente/invalido → `resolve_current_user` ritorna `None`,
  l'endpoint risponde 401 (o redirect login) come da gestione esistente

**Singleton `app/services/auth.py:resolve_current_user`**:
- Single source of truth della politica auth
- Sostituisce le 5 copie ad-hoc identiche nei router
- Ogni router ora importa via alias:
  `from app.services.auth import resolve_current_user as _resolve_current_user`
- Zero call site cambiato (~30 endpoint), API invariata

**Smoke**: 302 routes invariato, alias unificati cross-router, version
3.5.0-alpha.66.14.2.

**Per produzione**:
```bash
# .env
AUTH_REQUIRED=true
```
Senza questo flag il comportamento è identico a oggi (compatibilità).

---

## v3.5.0-alpha.66.14.1 — Light mode auto-on sopra soglia (11 maggio 2026)

Quick win post-audit #2. Risolve il rischio "freeze Chrome al primo
accesso utente nuovo con dataset reale". Il light mode esisteva già
(α.46.2) ma era OFF di default + visibile solo nella toolbar.

**Auto-on intelligente** (`planning.html:tlMaybeAutoEnableLight`):
- Soglia: items > 80 OR groups > 15
- Eseguito una sola volta per nuovo utente, prima del primo render
- Se l'utente ha mai toccato il toggle manualmente
  (`mf_tl_light_mode_user_set='1'`), la sua scelta è rispettata: chi
  vuole OFF non se lo vede riattivato all'apertura
- Toast informativo 6s che spiega cosa è e come riattivare i background
  via il bottone toolbar

**Logica**:
- Inserito subito dopo il calcolo di `groups` in `_doRenderTimeline`,
  prima del check `_hideBg = ... || tlIsLightMode()`
- Reordering: spostato `tlBuildGroups` PRIMA del calcolo `_hideBg`
  (era dopo) per avere `groups.length` disponibile

**`tlToggleLight` aggiornato**: setta sempre `mf_tl_light_mode_user_set='1'`
così future auto-attivazioni vengono saltate.

**Smoke**: nessuna modifica backend, version 3.5.0-alpha.66.14.1.

**Verifica live** (richiede dataset > soglia):
1. localStorage clear → riapri /planning con > 80 booking → toast giallo
   "Modalità leggera attiva (...)" + bottone toolbar evidenziato.
2. Premi 🪶 Light → off → toast "disattivato". Reload → resta off
   (user_set rispettato).
3. Premi di nuovo 🪶 Light → on → toast "attiva". Reload → resta on.

---

## v3.5.0-alpha.66.14 — Modal a11y completa (11 maggio 2026)

Apre il "cantiere consolidamento" post-audit profondo. Primo quick win:
accessibilità di tutti i ~30 modali in un colpo solo, una sola modifica
nel helper centrale `global.js`.

**`openModal/closeModal` riscritti** (`app/static/js/global.js:203-300`):
- Stack di modali aperti `MF_MODAL_STACK` (per gestire modali annidati
  tipo Booking → Resource picker).
- ARIA: `role="dialog"` + `aria-modal="true"` impostati al open, rimossi
  al close. `tabindex="-1"` sul container per renderlo focusabile.
- **Focus trap**: `Tab`/`Shift+Tab` ciclano tra i focusable dentro il
  modal in cima allo stack. Outside-of-modal salta al primo/ultimo.
- **Esc handler**: chiude SOLO il modal in cima (non tutti).
- **Restore focus**: al close, ritorna al focus precedente all'apertura
  (es. il bottone che ha aperto il modal). UX nativa.
- **Click outside**: chiude solo il modal in cima allo stack
  (prima chiudeva TUTTI i modali in DOM).
- **Auto-focus**: al open, sposta focus sul primo elemento focusabile
  dentro il modal (o sul container se vuoto).
- Listener globale `keydown` montato solo quando c'è almeno un modal
  aperto, smontato a stack vuoto.

**Compatibilità**: API invariata (`openModal('id')` / `closeModal('id')`).
Nessun template da toccare. I template che usano `class="modal-overlay"`
+ overlay click outside continuano a funzionare.

**Smoke**: 302 routes invariato, version 3.5.0-alpha.66.14.

**Verifica live** (hard-refresh per cache-buster):
1. Apri qualsiasi modal (es. `/resources` → ✏️) → focus va sul primo input.
2. Tab → cicla solo dentro il modal, non esce.
3. Esc → chiude il modal, focus torna al bottone che lo aveva aperto.
4. Apri un modal annidato (es. da modal Booking apri picker risorsa) →
   Esc chiude solo il picker, non anche il Booking modal.
5. Click sull'overlay esterno del modal annidato → chiude solo il top.

---

## v3.5.0-alpha.66.13 — Branding aziendale completo (10 maggio 2026)

Personalizzazione tool per azienda applicata a quote PDF, cost report
cliente PDF e fattura PDF: logo + tagline + colore primario + intestazione
documento + footer "powered by" toggleable per white-label completo.

**Modello esteso `Tenant`** (4 campi nuovi, ALTER TABLE auto al boot):
- `tagline` (claim/sottotitolo opzionale, max 255 char)
- `brand_color` (hex `#RRGGBB`, default `#6272f5`) — usato come accent
  nei PDF (titoli, separatori, label)
- `show_powered_by` (bool, default True) — toggle "Generato con MediaFlow"
  nel footer dei documenti
- `document_header` (text libero opzionale) — intestazione che appare
  sotto il logo, sopra il contenuto del documento (note legali, codice
  riservatezza, ecc.)

**Service nuovo** `app/services/branding.py`:
- `get_branding(db, tenant_id=1)` — single source of truth: prepara dict
  con name/short_name/tagline/info/info_html/logo_path (Path absolute)/
  brand_color/show_powered_by/document_header. Robusto a tenant=None.

**PDF aggiornati**:
- `quote_pdf.py` — logo nell'header (3 colonne se presente: logo + tenant
  info + quote meta), titolo "QUOTAZIONE" usa `brand_color`, tagline come
  sottotitolo, document_header opzionale sotto la HR, footer "Generato
  con MediaFlow" toggleable.
- `pdf_export.py` (cost report cliente) — accetta nuovo parametro
  `branding`. Logo + tagline + brand_color + document_header + footer.
- `invoice_pdf.py` — footer "Generato con MediaFlow" toggleable. Logo
  era già presente da v3.5.0-alpha.52.

**UI `/settings#company`**:
- Nuovo blocco "🎨 Branding documenti" con 4 campi:
  - Tagline (input text)
  - Colore primario PDF (color picker + hex input sincronizzati)
  - Intestazione documento (textarea)
  - Checkbox "Mostra 'Generato con MediaFlow' nel footer"

**Backend** `/settings/api/company` (PUT/GET):
- Esposti e accettati i 4 nuovi campi.
- `brand_color` validato come `#[0-9a-fA-F]{6}` (hex non validi droppati).
- `show_powered_by` ricevuto come `'true'`/`'false'` string.

**Smoke E2E**:
- ALTER TABLE applicate al boot (4 colonne).
- PUT branding con tagline + brand_color #a855f7 + show_powered_by=false +
  document_header → 200, tutti i 4 campi persistiti correttamente.
- get_branding helper restituisce dict completo.

**Smoke**: 302 routes invariato, version `3.5.0-alpha.66.13`.

**Verifica live**:
1. `/settings#company` → blocco "🎨 Branding documenti" → compila tagline
   + scegli colore con picker → spunta off "Generato con MediaFlow" →
   compila intestazione → "Salva dati aziendali".
2. `/quotes/{id}/pdf` → header con logo + tagline + titolo "QUOTAZIONE"
   nel colore scelto + intestazione documento.
3. `/cost-report/api/job/{id}/client-pdf` → idem (RENDICONTAZIONE).
4. Footer sui PDF: solo nome azienda, no "Generato con MediaFlow".
5. Cambio colore in `#22c55e` → ricarica PDF → nuovo accent verde.

---

## v3.5.0-alpha.66.12 — PhysicalAsset CRUD UI (10 maggio 2026)

UI per il modello `PhysicalAsset` introdotto in α.66.9. Nuova pagina
`/physical-assets` per gestire LTO/HDD/CRU/Blu-Ray/DVD/Case con tracking
archive interno + spedizione cliente + verifica integrità periodica.

**Nuova pagina** `/physical-assets`:
- Tabella con tipo (badge color-coded), etichetta, serial/barcode, capacità
  (GB→TB auto), location, condizione, flag archive/delivered, tracking
  consegna.
- Filtri: tipo (lto/hdd/cru/bluray/dvd/case/other), solo archivio interno,
  solo consegnati esternamente, mostra cestino.
- Modal "Nuovo asset fisico" / "Modifica" con tutti i campi:
  - Identità: kind + label + description + serial + manufacturer + barcode
  - Dimensioni: capacity_gb + used_gb (visualizzati in GB/TB auto)
  - Costo unitario (€) — usato come hardcost quando venduto al cliente
  - Condizione (new/verified/suspect/retired) + location fisica
  - Fieldset "Stato e consegna": flag is_internal_archive +
    is_delivered_external (ortogonali) + campi consegna che appaiono
    automaticamente quando "consegnato esternamente" è ON
  - Details collassabile "Verifica integrità (LTO/HDD)": MD5/xxHash +
    last_verified_at + next_verification_due
  - Note libere

**Nuovo router** `app/routers/physical_assets.py`:
- `GET /physical-assets/` (pagina)
- `GET /physical-assets/api` (lista con filtri kind/project/job/internal/delivered/include_deleted)
- `GET /physical-assets/api/{id}` (dettaglio)
- `POST /physical-assets/api` (crea)
- `PUT /physical-assets/api/{id}` (modifica)
- `DELETE /physical-assets/api/{id}?hard=bool` (soft o hard delete)
- `POST /physical-assets/api/{id}/restore` (ripristina dal cestino)
- Permessi: `edit_planning_all` o `assign_resources` per le mutation.

**Sidebar** in `base.html`: nuova voce "Asset Fisici" sotto "Asset Library"
nella sezione Media (icona `hard-drive`).

**Smoke E2E**:
- POST LTO con capacity 12TB usato 10.5TB, condizione verified, archivio interno: OK
- POST HDD consegnato a RAI con courier BRT + tracking number: OK
- List: 2 asset, filtro kind=lto → 1, filtro only_delivered → 1: OK
- Soft-delete + restore + hard-delete tutti funzionanti.

**Smoke**: 302 routes (+7), version `3.5.0-alpha.66.12`.

**Verifica live**:
1. Sidebar → "Asset Fisici" → pagina vuota.
2. "+ Nuovo asset fisico" → modal → kind=LTO → label "LTO 042" →
   capacità 12000 GB → location "Cassaforte" → Salva → vedi badge LTO blu
   con etichetta + 12TB.
3. Riapri → spunta "Consegnato esternamente" → appaiono campi consegna
   → compila courier+tracking → Salva → vedi 📦 + 📤.
4. Filtro "Solo consegnati esternamente" → mostra solo asset spediti.
5. Cestino: 🗑️ elimina → poi spunta "Mostra cestino" → vedi asset opacizzato.

---

## v3.5.0-alpha.66.11 — Cost report split cliente vs interno (10 maggio 2026)

Chiude il loop dell'hardcost α.66.9: le ore dei booking attribuiti a
deliverable non-time-based (DCP/ProRes/LTO/screener) sono ora "produzione
interna del file" → contano come **hardcost interno** nel cost report
finance, ma **non** vengono mostrate al cliente come monte ore fatturabili.
Le voci time-based (color grading day, mix day) continuano a fatturare ore.

**Helper centralizzato** in `app/services/cost_line_sync.py`:
- `is_time_based_unit(unit)` — True per `day/hr/h/ore`, False per
  `pc/min/TB/GB/shot/version/allow/lump/...`.

**`/cost-report/api/job/{id}` arricchito**:
- `summary.deliverable_hardcost_internal` — totale `Σ ore × Resource.internal_cost_hourly` per booking attribuiti a deliverable.
- `summary.deliverable_hours_internal` — ore totali deliverable.
- `summary.deliverable_count` — numero di JobDeliverable attivi del job.
- Per ogni `cost_lines[i]`:
  - `unit_is_time_based` flag
  - `deliverable_hardcost_internal` (€) per la riga
  - `deliverable_hours_internal` (h) per la riga
  - `deliverable_count` per la riga

**`_bookings_hours_cost(client_view=True)` nuovo flag**:
- Esclude i booking attribuiti a deliverable la cui JCL è **non-time-based**
  (o senza JCL = considerato non-billable).
- Vista interna (default `client_view=False`) include tutto come prima.

**`_client_filtered_report()` nuovo helper**:
- Riusa `job_cost_report` e ricalcola `bookings_hours` con `client_view=True`.
- Rimuove dal `summary` i campi internal-only (`deliverable_hardcost_internal`,
  `estimated_cost`, `margin`) per sicurezza.
- Riusato da `/client-pdf`, `/client-csv`, `/client-xlsx`.

**UI `/jobs/{id}`** (solo con permesso `view_finance`):
- Nuova card KPI viola "Hardcost ore deliverable INTERNO" con €+ore+count
  visibile solo se ci sono deliverable attivi. Tooltip esplicito:
  "Costo orario × ore booking attribuiti a deliverable. Cliente NON lo vede".

**Smoke E2E** (3 booking: 4h DCP + 2h orfano + 8h color):
- Vista interna: `bookings_hours=14h`, `deliverable_hardcost_internal=€165.06`
  (6h × €27.51 employee), per riga `Mastering DCP` hardcost €110.04 (4h × €27.51).
- Vista cliente: `bookings_hours=8h` (esclusi 4h DCP + 2h orfano).
- Client PDF generato (200, 3046 bytes).

**Smoke**: 295 routes invariato, version `3.5.0-alpha.66.11`.

**Verifica live**:
1. Setup: `/resources` → configura cost_type su una risorsa (Dipendente o Freelance).
2. Crea un deliverable in `/jobs/{id}` legato a JCL non-time (es. "Mastering DCP", unit pc).
3. Crea booking 4h attribuito al deliverable.
4. `/jobs/{id}` → nuova card "Hardcost ore deliverable INTERNO" mostra €+h.
5. Crea altro booking 8h attribuito a JCL time-based (color grading day).
6. Client PDF (`📄 Esporta PDF cliente`) → "Riepilogo ore lavorate" mostra
   solo 8h (no 4h DCP).
7. `/cost-report/api/job/{id}` da admin → `summary.bookings_hours=12h`,
   `deliverable_hardcost_internal=€110.04`.

---

## v3.5.0-alpha.66.10 — UI cost-rate Resource con live preview (10 maggio 2026)

UI per popolare i campi cost-rate introdotti in α.66.9 (modello DB).
Senza questa UI non era possibile testare l'hardcost dei deliverable.

**Modal `/resources` esteso** con sezione collassabile "💰 Costo interno":
- Dropdown `cost_type` (employee / freelance / studio interno / external).
- **Blocco condizionale per tipo**:
  - Employee: stipendio mensile lordo (€) + mensilità (default 13) +
    multiplier oneri (default 1.30) + ore annue (default 1720h).
  - Freelance: tariffa oraria pagata (€/h, separata dalla `hourly_rate` di
    vendita al cliente).
  - Studio: allocazione oraria struttura (€/h, tariffa fissa decisa dal
    manager — derivazione AI futura via visura amministrativa, vedi
    memoria `project_ai_cost_derivation`).
  - External: nessun campo (usa `hourly_rate` come fallback).
- **Live preview** del calcolo (es. `2800 × 13 × 1.30 / 1720h = €27.51/h`)
  che si aggiorna mentre l'utente digita.

**Backend `/resources/api/` esteso**:
- `POST` e `PUT` accettano: `cost_type`, `monthly_gross_salary`,
  `annual_bonus_months`, `cost_multiplier_oneri`, `annual_working_hours`,
  `freelance_hourly_cost`, `studio_hourly_cost`.
- `GET /resources/api/{id}` espone i nuovi campi + `internal_cost_hourly`
  calcolato (property della Resource).
- Update PUT restituisce `internal_cost_hourly` aggiornato → la UI può
  mostrare il valore confermato server-side.

**Smoke E2E**:
- POST employee €2800/mese 13 mesi × 1.30 / 1720h → €27.51/h ✓
- GET espone tutti i 7 nuovi campi + `internal_cost_hourly` ✓
- PUT switch employee → freelance €50/h → recalcolo €50/h ✓

**Smoke**: 295 routes invariato, version `3.5.0-alpha.66.10`.

**Verifica live**:
1. `/resources` → click matita su una risorsa → modal apre.
2. Sezione "💰 Costo interno" → dropdown "Dipendente" → compila stipendio
   mensile → preview live: `€27.51/h`.
3. Cambia tipo a "Freelance" → blocchi nascosti/mostrati correttamente.
4. Cambia tipo a "Studio interno" → "Allocazione oraria" appare.
5. Salva → ricarica `/resources` → riapri modal → valori persistiti.

---

## v3.5.0-alpha.66.9 — JobDeliverable + cost-rate Resource + DAM physical + naming helper (10 maggio 2026)

Substrato dati per il modello deliverable. Cantiere "Listino & Deliverable"
sezione architetturale. UI completa (kanban, copilot QC, cost report split)
nelle versioni successive (α.66.10+).

**4 nuovi enum** in `app/models/models.py`:
- `PhysicalAssetKind` (lto/hdd/cru/bluray/dvd/case/other)
- `DeliverableStatus` (planned → in_production → file_attached → qc_running →
  qc_passed | qc_failed → delivered → accepted | rejected)
- `DeliverableNature` (digital/physical, mutually exclusive)
- `ResourceCostType` (employee/freelance/studio/external)

**3 modelli** (2 nuovi + 2 estesi):

1. **`JobDeliverable`** (NUOVO, table `job_deliverables`) — nodo di produzione
   tra JobCostLine e Asset/PhysicalAsset:
   - identità: name, file_naming (libero), price_item_id, job_cost_line_id,
     delivery_template_id, spec_json (cristallizzato dal template)
   - produzione: primary_resource_id, estimated_hours
   - bridge: digital_asset_id (FK Asset) **OR** physical_asset_id (FK PhysicalAsset)
     — mutually exclusive a livello "file consegnato"
   - QC: qc_report_json, qc_run_at, qc_run_by_user_id
   - stato: status enum + target/delivered/accepted dates
   - soft-delete via deleted_at

2. **`PhysicalAsset`** (NUOVO, table `physical_assets`) — supporto fisico:
   LTO/HDD/CRU/Blu-Ray/DVD/Case con kind + label + serial + barcode +
   capacity_gb + condition + location + custodian + flag
   `is_internal_archive` + `is_delivered_external` (ortogonali) +
   delivered_at/courier/tracking_number per shipping + unit_cost (per
   hardcost quando venduto al cliente) + checksum_md5/xxhash + verifiche
   periodiche (last_verified_at, next_verification_due) per LTO. Soft-delete.

3. **`Asset` esteso** (DAM digitale) — aggiunti: job_deliverable_id (bridge),
   is_internal_archive, is_delivered_external, delivered_at, delivered_to,
   delivery_method, delivery_tracking. Pattern flag identico a PhysicalAsset
   per coerenza UI.

4. **`Booking` esteso** — aggiunto `job_deliverable_id` (FK opz). Le ore di
   booking attribuite contano come **hardcost interno** del deliverable
   (= ore × Resource.internal_cost_hourly). Cliente non lo vede.

5. **`Resource` esteso** — cost-rate interno separato dalle tariffe di vendita:
   - `cost_type` enum (employee/freelance/studio/external)
   - per employee: `monthly_gross_salary` × `annual_bonus_months` (default 13)
     × `cost_multiplier_oneri` (default 1.30) / `annual_working_hours`
     (default 1720) → `internal_cost_hourly` calcolato deterministicamente
   - per freelance: `freelance_hourly_cost` (≠ hourly_rate venduto)
   - per studio: `studio_hourly_cost` (allocazione struttura, tariffa fissa
     decisa dal manager — derivazione AI da visura amministrativa rinviata)
   - per external: fallback a hourly_rate
   - **Property** `internal_cost_hourly` su Resource che restituisce il valore
     corretto in base al cost_type. None se non configurato (graceful).

**Migrazione DB auto al boot**: tabelle nuove via `Base.metadata.create_all()`,
ALTER TABLE per le colonne aggiunte. Idempotente.

**Naming helper** (`app/services/naming_helper.py`) — token resolver basato
su Netflix Picture Archival + ISDCF DCP Naming Convention v9:
- **34 token** documentati in `TOKEN_HELP`: project/client/show/episode,
  format (resolution/framerate/audio_config/aspect/color_space/dynamic_range),
  language/territory (ISO 639-2 + ISO 3166-1), version/cut/revision,
  standard (IOP/SMPTE/IMF/DPP/AS-11), package_type (OV/VF/SUPP), date, facility,
  barcode (per asset fisico), deliverable_id.
- **9 preset template** built-in: ISDCF DCP (cinema), ISDCF DCP short,
  Netflix Picture Archival, Netflix IMF master, DPP/AS-11 broadcast,
  ProRes master, Screener H.264/H.265, LTO archive label, Custom (libero).
- `build_token_dict(...)` risolve dal contesto (JobDeliverable, Job, Project,
  Client, DeliveryTemplate, PhysicalAsset) + accetta `overrides` utente
  (UI invia mentre digita).
- `resolve_template(template, tokens)` → output + lista missing tokens
  (placeholder `__` visibile per token mancanti).

**8 endpoint nuovi** in `app/routers/jobs.py`:
- `GET /jobs/api/{job_id}/deliverables` (lista + actual_hours per riga)
- `POST /jobs/api/{job_id}/deliverables` (crea N con quantity 1-50, default 1;
  se N>1 crea deliverable separati con suffix "(i/N)")
- `GET /jobs/api/deliverables/{id}` (dettaglio + internal_hardcost calcolato)
- `PUT /jobs/api/deliverables/{id}` (update; status=delivered/accepted
  cristallizza date automaticamente)
- `DELETE /jobs/api/deliverables/{id}` (soft-delete)
- `POST /jobs/api/deliverables/{id}/restore` (recupera da cestino)
- `GET /jobs/api/naming/presets` (lista preset + token help)
- `POST /jobs/api/naming/preview` (resolve template con overrides → output)

**UI MVP** in `/jobs/{id}` — nuovo blocco "Consegne" sotto la tabella
lavorazioni:
- Lista deliverable con status badge color-coded + nature badge digital/physical
- Modal "+ Nuovo deliverable" con: nome, natura, quantity (1-50), legame
  a JobCostLine + voce listino, risorsa primaria, ore stimate, target date,
  naming preset dropdown + campo libero file_naming con **live preview**
  (debounced) mentre l'utente digita le specifiche tecniche → chiama
  `/naming/preview` e popola il campo.
- Sezione collassabile "Specifiche tecniche" (resolution/framerate/audio_config/
  lang_audio/lang_subs/territory) → spec_json salvato.

**Smoke test E2E** completo:
- Create qty=3 → 3 deliverable creati con suffix
- Booking attribuito → actual_hours=4.0 calcolate
- internal_hardcost = 4h × €27.51 = €110.04 (employee €2800/mese × 13 ×
  1.30 / 1720h)
- Update status planned → in_production OK
- Lista preset + token help OK (9 preset + 34 token)
- Preview ISDCF DCP: `MareNostrum_FTR-F_IT-it_51_2K_RAI_20260612_TPRBerlin_IOP_OV`

**Smoke**: 295 routes (+8), version `3.5.0-alpha.66.9`. Tabelle nuove +
ALTER TABLE applicate idempotentemente al boot.

**Cosa NON è in α.66.9** (apre α.66.10+):
- Kanban deliverable + drag tra colonne stato
- Modal completo edit con asset link da DAM (digital + physical)
- Modal CRUD PhysicalAsset (oggi solo modello DB, no UI dedicata)
- Copilot QC (`propose_qc_check` capability con ffprobe + LLM contro spec_json)
- Cost report split cliente vs interno con hardcost ore deliverable
- UI cost-rate in `/resources/{id}` con preview calcolo employee live
- Tool generazione nomi file completo (regole, validazione conflitti, batch rename)

**Verifica live** (al riavvio):
1. `/jobs/{id}` → blocco "Consegne" sotto Lavorazioni → "+ Nuovo deliverable"
   → modal con dropdown naming presets (9 opzioni) → seleziona ISDCF DCP →
   compila campi spec → live preview popola file_naming.
2. Crea con quantity=3 → 3 card in lista, naming generato uguale per tutti
   (l'utente li distinguerà dopo per territorio).
3. Click 🗑️ → soft-delete. La lista non lo mostra più.
4. POST `/jobs/api/naming/preview` con template `{film_name}_FTR-{aspect}_{audio_config}_{resolution}` e overrides `{film_name:"Test", aspect:"F", audio_config:"71", resolution:"4K"}` → output `Test_FTR-F_71_4K` no missing.

---

## v3.5.0-alpha.66.8 — Listino lean 2026-Q3 (79 → 43 voci, –46%) + nuovo seed_demo (10 maggio 2026)

Scrematura del listino base secondo mappatura concordata con Matteo:
accorpamento di varianti vicine in voci-padre con **descrizione modulare**.
Le specifiche tecniche scendono dalla voce di listino alla descrizione di
riga in quote, dove il PM le dettaglia per progetto. Il legacy 79 voci
resta disponibile come preset built-in `legacy_2026q2_full` (α.66.7) per
ripristino su richiesta.

**Mappatura applicata** (12 categorie invariate):

| Categoria | Da | A | Esempio accorpamento |
|---|---|---|---|
| DAILIES | 4 | 2 | sync+QC+upload+MHL → "Dailies workflow" |
| PICTURE / DI | 7 | 4 | 2K/4K conform → "Online conform"; HDR DV+trim pass → 1 |
| MASTERING DCP / DCDM | 8 | 3 | INTEROP+SMPTE+festival+KDM → "Mastering DCP standard" |
| DELIVERABLES VIDEO | 9 | 5 | ProRes 4444 HD/UHD/HDR → 1; H.264 clean/wm/burn → 1; **+IMF/DPP/AS-11 nuovo** |
| ARCHIVE / TRANSFER | 9 | 4 | 5 LTO → "LTO archive"; USB+CRU+shipping → "Drive consegna" |
| VFX | 6 | 4 | std+complex → "VFX comp"; roto+paint → "Roto/paint" |
| SOUND EDIT | 5 | 3 | dialogue+sfx+music edit → "Sound editorial day" |
| MIX | 4 | 3 | 5.1+7.1 → "Mix surround" |
| DELIVERABLES SOUND | 8 | 5 | Printmaster+M&E (5.1+7.1) → "Surround printmaster/M&E" |
| LOCALIZATION | 6 | 4 | EN→IT + IT→EN → "Subtitle translation"; SDH+CC+forced → "Caption authoring" |
| QC / METADATA | 5 | 3 | Manual HD+UHD → "Manual QC"; metadata+cue → 1 |
| PROJECT MGMT | 4 | 3 | PM+Coordinator → "Production management" |
| **TOTALE** | **79** | **43** | **–46%** |

**Pattern descrizione modulare**: ogni voce accorpata ha `description` con
placeholder che il PM completa nella riga di quote. Esempio per "Mastering
DCP standard":
```
"Mastering Digital Cinema Package con CPL/PKL/naming DCNC.
 Dettagliare: formato (INTEROP / SMPTE), risoluzione (2K ≈€700, 4K ≈€900),
 audio (5.1/7.1), encryption (KDM/DKDM), festival pass se richiesto."
```

**Nuovo file** `app/data/pricelist_presets/lean_2026q3_v1.json` (43 voci
schema 1.1) generato da `scripts/build_lean_preset.py` (single source of
truth per lean preset, ri-eseguibile dopo modifiche).

**`scripts/seed_demo.py` rifattorizzato**:
- Rimosso `LISTINO_GENERICO` letterale (228 righe).
- Carica direttamente da preset lean via `pricelist_snapshot.apply_snapshot_payload`.
- Quote demo (Mare Nostrum) aggiornata: voci legacy mappate a quelle lean
  con specifiche tecniche in `detail` di riga, secondo il nuovo pattern
  modulare.
- Smoke test su DB pulito: 4 dept + 12 cat + 43 items + 12 quote lines OK.

**Cosa NON è stato accorpato** (esplicito):
- Voci con prezzo molto diverso (HDR DV €2200/day vs SDR €1650/day vs
  trim €600/pc — accorpate trim+HDR perché complementari, ma SDR resta separato).
- Voci con unità diversa (day vs pc vs min vs TB): mai accorpate, sarebbero
  semanticamente sbagliate.
- Mix Atmos separato dal surround (sala diversa, prezzo +30%).
- Voci uniche per dominio (Foley, ADR, theater rental, DCDM): restano separate.

**Hardcost**: ridiscusse in α.66.9 contestualmente al modello cost-rate
Resource (employee/freelance/studio) e all'integrazione DAM ↔ JobDeliverable.
Per ora il lean ne preserva la struttura sulle voci dove c'erano (mix
surround €500, Atmos €800, drive €90, dubbing €200).

**Smoke**: 287 routes invariato, version `3.5.0-alpha.66.8`. Boot DB reale:
2 preset caricati (legacy 79 voci + lean 43 voci) come PricelistSnapshot
kind=preset, no auto-apply al listino corrente.

**Verifica live** (sul DB esistente di Matteo, listino corrente immutato):
1. `/pricelist` → bottone `📦 Snapshot` → "🎁 Preset built-in" → vedi
   2 preset disponibili (legacy 79 voci + lean 43 voci).
2. "Carica come snapshot" sul lean → snapshot creato e visibile in lista.
3. Per applicare il lean al listino corrente: tab Lista → Ripristina
   → modalità Replace (con auto-backup del listino legacy automatico).
4. Per nuove installazioni (re-seed con `[O] reset_business_data` o seed
   da zero): il listino di default è ora lean (43 voci).

---

## v3.5.0-alpha.66.7 — Preset listino legacy committato + bootstrap automatico (10 maggio 2026)

Step di sicurezza prima della scrematura α.66.8: il listino corrente
(79 voci, 12 categorie, 4 reparti — versione completa pre-scrematura)
viene **committato in repo** come preset built-in, così non potrà mai
andare perso indipendentemente dallo stato del DB di chiunque.

**Nuovo file**:
- `app/data/pricelist_presets/legacy_2026q2_full.json` — preset
  schema 1.1, 44KB, descrizione: "Listino MediaFlow legacy 2026-Q2 —
  79 voci complete, prima della scrematura α.66.8".

**Bootstrap loader nel `lifespan` di `app/main.py`**:
- Al boot, per ogni Tenant del DB, scansiona
  `app/data/pricelist_presets/*.json` e crea un `PricelistSnapshot`
  kind=preset per ogni file (idempotente: salta se esiste già con
  stesso name).
- I preset NON vengono mai applicati automaticamente al listino —
  rimangono solo "pronti all'uso" nella UI di
  `/pricelist → 📦 Snapshot → Preset built-in`.
- Doppio-boot test: 1 preset prima, 1 preset dopo (no duplicazione).

**Smoke**: 287 routes invariato, version `3.5.0-alpha.66.7`. Boot DB
reale: snapshot id=1 caricato, kind=preset, 79/12/4.

**Verifica live** (al riavvio):
1. `/pricelist` → bottone `📦 Snapshot` → modal vuoto → tab Lista
   mostra "Preset: legacy_2026q2_full" (badge viola).
2. Click "↺ Ripristina" su un DB vuoto/diverso → ricostruisce il
   listino legacy completo (mode replace consigliato).
3. `/pricelist/api/presets` → JSON con `legacy_2026q2_full.json`,
   counters, schema_version 1.1.

---

## v3.5.0-alpha.66.6 — Backup/restore listino con snapshot persistenti (10 maggio 2026)

Cantiere multi-versione "Listino & Deliverable" — versione **abilitante**
prima della scrematura del listino base e del modello `JobDeliverable`.

**Obiettivo**: non perdere mai il listino corrente prima di applicare
modifiche aggressive. Sostituisce il flusso "esporta JSON → conserva sul
disco → reimporta a mano" con uno storage persistente nel DB + UI dedicata.

**Modello nuovo**: `PricelistSnapshot` (table `pricelist_snapshots`)
con `id`, `tenant_id`, `name`, `description`, `kind` (manual/auto/preset),
counters denormalizzati (item/category/department), `schema_version`,
`source_app_version`, `payload_json`, `created_by_user_id`, `created_at`,
`deleted_at` (soft-delete). Tabella creata automaticamente al boot via
`Base.metadata.create_all()`, nessuna migrazione manuale richiesta.

**Service** `app/services/pricelist_snapshot.py`:
- `build_snapshot_payload(db, tenant_id)` — schema 1.1, include departments
  (mancanti nello schema 1.0 esistente), categories, items con keywords.
- `apply_snapshot_payload(db, tenant_id, payload, mode, auto_backup=True)` —
  applica un payload con `mode=merge` (aggiorna voci con stesso nome, aggiunge
  nuove, preserva esistenti) o `mode=replace` (DELETE all → import). In
  `replace` crea automaticamente un PricelistSnapshot di tipo `auto` PRIMA
  dell'overwrite per permettere rollback.
- `create_snapshot_record(...)`, `list_snapshots(...)`, `soft_delete_snapshot`,
  `restore_deleted_snapshot`, `hard_delete_snapshot`.
- `list_preset_files()` / `load_preset_payload(...)` — preset built-in
  caricabili da `app/data/pricelist_presets/*.json` (cartella creata in
  questo commit, popolata in α.66.7).

**Endpoint nuovi** in `app/routers/pricelist.py` (8 nuovi route, +permission
gate `edit_pricelist` su tutte le mutation):
- `GET /pricelist/api/snapshots` — lista
- `POST /pricelist/api/snapshots` — crea da listino corrente
- `GET /pricelist/api/snapshots/{id}` — dettaglio + payload
- `GET /pricelist/api/snapshots/{id}/download` — scarica .json
- `POST /pricelist/api/snapshots/{id}/restore` — ripristina (mode merge|replace)
- `DELETE /pricelist/api/snapshots/{id}?hard=bool` — soft o hard delete
- `POST /pricelist/api/snapshots/{id}/restore-deleted` — recupera dal cestino
- `POST /pricelist/api/snapshots/upload` — upload file .json come snapshot manuale
- `GET /pricelist/api/presets` — lista preset built-in
- `POST /pricelist/api/presets/load` — carica preset come snapshot (idempotente)

**UI listino** (`/pricelist`):
- Bottone toolbar `📦 Snapshot` (visibile solo con permesso `edit_pricelist`).
- Modal "Snapshot listino": tabella con tutti gli snapshot (kind badge
  color-coded), bottoni per riga Ripristina / Scarica / Elimina, opzione
  "Mostra cestino", import file `.json`, blocco "Preset built-in".
- Modal "Salva snapshot": nome (con default datestamp) + descrizione.
- Modal "Ripristina": scelta merge/replace con warning per replace.

**UI impostazioni** (`/settings#data`):
- Nuovo blocco "Listino — Snapshot dedicati" con shortcut
  "💾 Salva snapshot listino corrente" + link a `/pricelist#snapshots`
  + scarica .json + lista compatta degli ultimi 5 snapshot.
- Nuovo opt-in "Includi snapshot listino" nel pannello Export ZIP
  (default ON, esporta solo gli `manual` non cancellati come `.json`
  + `_index.json` di sintesi).

**Smoke test live**: 287 routes (+10), version `3.5.0-alpha.66.6`. Test
diretto del service: build payload schema 1.1 da listino reale (79 voci,
12 categorie, 4 reparti), create snapshot id=1, apply merge → 4 dept
updated, 12 cat updated, 79 items updated, 0 created, 0 skipped (idempotente).

**Verifica live** (hard-refresh):
1. `/pricelist` → bottone `📦 Snapshot` → modal lista vuota → "💾 Salva
   listino corrente" → snapshot in lista con counters corretti.
2. Modifica una voce → torna in modal Snapshot → "↺ Ripristina" merge
   → modifica annullata. Verifica auto-backup id presente nei stats di
   replace.
3. "⬇ Scarica .json" → file portabile schema 1.1 con departments.
4. "⬆ Importa file .json" → carica file scaricato → appare come snapshot
   manuale. Ripristina con mode=replace → DB sostituito + auto-backup
   visibile in lista.
5. `/settings#data` → blocco "Listino" → "💾 Salva snapshot listino
   corrente" → toast successo + lista aggiornata.
6. Export ZIP completo → cartella `listino-snapshots/` contiene un
   `.json` per ogni snapshot manuale + `_index.json`.

**Cantieri rimasti aperti** (in ordine):
- α.66.7 — Snapshot legacy del Mac di Matteo committato come preset
- α.66.8 — Semplificazione listino base (76 → ~38)
- α.66.9 — Modello `JobDeliverable` + cost-rate Resource (employee/freelance/studio)
- α.66.10+ — UI deliverable + asset library bridge + copilot QC + cost report split

---

## v3.5.0-alpha.66.5.1 — Audit completo post-refactor: bulk-edit + 5 mutator + UI legacy + AI (9 maggio 2026)

Audit con agente Explore ha rilevato 3 HIGH + multipli MEDIUM rimasti
disallineati dopo α.66.5. Tutti sistemati in questo commit.

**HIGH 1 — Bulk-edit completamente rotto** (`planning.html:1462` +
`planning.py:2241`):
- UI dichiarava valori `todo/started/done/not_done` che NON esistono
  nell'enum `BookingExecutionStatus` (`planned/in_progress/done/not_done`).
  Backend validava la stessa lista sbagliata. Al primo Apply: 400 silente.
- Fix UI: select rinominato `bulk-state`, 5 valori `BookingState` canonici
  (tentative/confirmed/in_progress/done/not_done) + motivazione obbligatoria
  inline per `not_done`.
- Fix backend: `bulk_edit_bookings` ora accetta `state` (Form) come canonico
  + `execution_status` come deprecated alias per back-compat. Usa
  `apply_state_to_booking` per sincronizzare atomicamente i 3 campi.
  Mappa anche i vecchi valori `todo/started/done/not_done` → BookingState
  per evitare regressioni a clienti API legacy.

**HIGH 2 — 5 mutator backend non sincronizzavano `state`**:
- `add_assignment_to_booking` (revive da cancelled): aggiunto `b.state = confirmed`.
- `delete_assignment` (booking diventa empty): aggiunto `b.state = cancelled`.
- `delete_booking` (soft-delete): aggiunto `b.state = cancelled`.
- `restore_booking`: aggiunto `b.state = tentative`.
- `_h_propose_delete_booking` AI: aggiunto `b.state = cancelled`.
- `create_booking` (POST): sincronizza `state` con `status` passato dal client
  (anche nel branch ricorrenza).
- AI recurring booking creator: aggiunto `state=BookingState.confirmed`
  esplicito (era desync permanente: status=confirmed, state=tentative default).

**MEDIUM — UI legacy migrate a /state**:
- `dashboard.html:mySetExec` migrata da `PATCH /execution` → `PATCH /state`.
  'planned' (legacy "Riapri") mappato a 'confirmed'.
- `planning.html:todoSetExec` migrata da `/execution` → `/state`.
- `planning.html:tlSelectPanelApply` filtra ora su `state` canonico
  (con fallback derivazione legacy se backend non lo espone). Filter UI
  `tlsp-status` allineato a 5 valori (aggiunto `confirmed` mancante).

**MEDIUM — AI prompt + tool schema**:
- `ai_assistant.py` system prompt: descrizione `propose_booking` aggiornata
  con BookingState (5 stati esclusivi).
- `ai_tools.py` schema `propose_booking`: description menziona BookingState
  invece di `Status`.

**LOW non toccati** (cost-report mostra `execution_status` direttamente,
labels "Da fare" in pdf_export): cosmetici, sincronizzati automaticamente
via apply_state_to_booking.

**Smoke**: 277 routes invariato, version 3.5.0-alpha.66.5.1. Mapping
state ↔ legacy verificato per tutti i 6 valori.

---

## v3.5.0-alpha.66.5 — Stato unificato BookingState (5 valori esclusivi, hard refactor enum DB) (9 maggio 2026)

Rifusione architetturale richiesta da Matteo: i 2 enum DB ortogonali
`BookingStatus` (tentative/confirmed/cancelled) + `BookingExecutionStatus`
(planned/in_progress/done/not_done) ora vivono come **una sola dimensione**
di 5 stati esclusivi nel ciclo di vita.

**Sequenza** (transizioni libere fra tutti i 5):
```
tentative → confirmed → in_progress → done | not_done
```
**Cancelled** è soft-delete (azione separata via "Elimina assegnazione" /
"Elimina booking"), non appare nel selettore UI.

**Modello** (`app/models/models.py`):
- Nuovo enum `BookingState` con 6 valori (i 5 + cancelled).
- Nuova colonna `Booking.state: BookingState = tentative` (canonica).
- Mapping `BOOKING_STATE_TO_LEGACY` + helper `compute_state_from_legacy`.
- Mantenuti `status` e `execution_status` come **campi derivati** per
  back-compat con slice-lock, billing-slice-guard, recompute_cost_line_actual,
  cost-report. Sincronizzati automaticamente via
  `app/services/booking_state.py:apply_state_to_booking()`.

**Migrazione DB** (`app/main.py`):
- ALTER TABLE bookings ADD COLUMN state (default tentative)
- UPDATE: popola state da (status, execution_status) per ogni riga
  esistente. Idempotente, eseguita al boot.

**Endpoint backend** (`app/routers/planning.py`):
- Nuovo `PATCH /api/bookings/{id}/state` (Form `state`, opt `not_done_reason`,
  opt `force_slice_unlock`). Sincronizza i 3 campi via
  `apply_state_to_booking`. Slice-lock check (skip tentative, conferma per
  confirmed e oltre). Notifiche selettive su `done`/`not_done`.
- API `/api/bookings` espone `extendedProps.state` (canonical).
- Vecchi endpoint `PUT /bookings/{id}` (status) e `PATCH /bookings/{id}/execution`
  ancora disponibili — sincronizzano automaticamente `state` quando
  cambiano i campi legacy (back-compat con AI, multi-move, ecc.).

**UI** (`app/templates/pages/planning.html`):
- Modal: rimossi i 2 campi separati (radio `tentative/confirmed` α.66.4 +
  submenu Marcature). Sostituiti da **1 unico select dropdown "Stato lavorazione"**
  con 5 valori. Campo motivazione mostrato solo per `not_done`.
- Context-menu: rimossi i 2 submenu separati. Sostituito da **1 unico submenu
  "🏷 Stato: <stato corrente> ▸"** con le 4 voci diverse dallo stato corrente.
- Timeline render: 1 sola icona inline per state (tentative ⏳, confirmed ✓,
  in_progress ▶, done ✅, not_done ✗) all'inizio del content. Tooltip mostra
  unica label IT. CSS `.tl-state-*` con classi unificate.
- Pre-fill in edit con fallback derivazione legacy se backend non espone
  ancora state.

**Smoke**: 277 routes (+1 endpoint), version 3.5.0-alpha.66.5. Mapping
state ↔ legacy verificato con tutti i 6 valori + edge case "tentative + done"
(status precede → tentative).

**Verifica live** (hard-refresh):
1. Pull → migrazione automatica al boot. Log: `[auto-migrate] bookings.state
   mancante -> ALTER TABLE + populate`. Booking esistenti mantengono lo
   stato corretto (tentative resta tentative, confirmed+done diventa done, ecc).
2. Click destro su booking → "🏷 Stato: <stato>" → submenu con 4 voci
   diverse dallo stato corrente. Click → toast + timeline aggiornata.
3. Doppio-click → modal con select "Stato lavorazione" pre-compilato.
   Cambia a "✗ Non fatto" → appare campo motivazione obbligatorio.
4. Booking tentative → ⏳ giallo + bordo dashed + banda gialla sx.
   Booking confirmed → ✓ verde discreto. In progress → ▶ + glow arancione.
   Done → ✅ + bordo verde + check ::after. Not done → ✗ + tratteggio rosso.
5. Slice-lock invariato: tentative passa, confirmed e oltre richiedono
   conferma + force_slice_unlock automatico via `api()` global.

**Cosa NON cambia in α.66.5**:
- Slice-lock, billing, cost-report, recompute leggono ancora `status` e
  `execution_status` legacy → sincronizzati automaticamente, niente regressione.
- Schema base (priority, kind, count_in_costs, overtime_status) invariato.
- Pattern submenu nativo (α.66.4) invariato.
- API response include sia `state` (nuovo) che `status`+`execution_status`
  (legacy) per back-compat client che non sono ancora migrati.

---

## v3.5.0-alpha.66.4 — Icone status più visibili + submenu inline + tentative nel modal (9 maggio 2026)

3 fix da feedback Matteo dopo α.66.3:

**1. Icona ⏳ tentative non visibile**
- CSS rinforzato: font-size 11→13px, font-weight 700, text-shadow nero,
  colore giallo (#fde68a) invece di grigio chiaro per stacco maggiore.
- Confirmed: opacity .85 invece di .7, sempre verde discreto.

**2. Submenu Marcature chiudeva il primo menu**
- Riscritto `tlContextMenu` con supporto **submenu nativi**:
  voci con `submenu: [...]` mostrano "▸" e aprono un sottomenu adiacente
  on hover/click. Il menu padre **resta visibile**. Hover su una voce
  senza submenu chiude l'eventuale submenu aperto. Esc chiude prima il
  submenu, poi il menu padre. Click-fuori sul menu padre o sub chiude tutto.
- Le voci execution_status raccolte in submenu nativo "🏷 Marcature".
- Nuova voce "⏳ Stato: Tentative" / "✓ Stato: Confermato" con submenu
  per il toggle BookingStatus → conferma/rendi tentative.
- Rimosso il workaround "secondo `tlContextMenu` esplicito" introdotto
  in α.66.3.

**3. Tentative/Confirmed mancanti nel modal edit booking**
- Nuovo gruppo radio nel modal `tlb-` (sotto Priorità):
  ⏳ Tentative / ✓ Confermato.
- Default tentative su create. Pre-fill in edit dal `extendedProps.status`.
- `tlbSubmit` invia sempre `status` (Form param) → backend aggiorna
  BookingStatus.

**Smoke**: 276 routes invariato, version 3.5.0-alpha.66.4.

**Verifica live** (hard-refresh forzato!):
1. Click destro su booking → menu con voce "🏷 Marcature ▸". Hover/click
   sulla voce → submenu si apre adiacente (a destra), il primo resta
   visibile. Hover su altra voce → submenu si chiude. Esc chiude solo
   il submenu se aperto, poi il menu padre.
2. Stessa logica per "⏳ Stato: Tentative" / "✓ Stato: Confermato" →
   submenu con toggle.
3. Booking tentative → ⏳ giallo visibile in timeline. Booking confirmed
   → ✓ verde discreto.
4. Doppio-click su booking → modal edit ha sezione "Stato booking" con
   2 radio. Pre-compilati con lo stato attuale. Submit aggiorna in DB.

---

## v3.5.0-alpha.66.3 — Submenu Marcature + icone status booking + slice-lock relax (9 maggio 2026)

Bundle 3 punti di feedback Matteo dopo conferma α.66.2 (fix doubleClick).

**P1 — Submenu Marcature nel context-menu booking**
Le voci ▶ Inizia / ✓ Fatto / ✗ Non fatto / ↺ Riapri introdotte in α.66
gonfiavano il menu principale. Ora raggruppate dietro "🏷 Marcature ▸"
che apre un secondo `tlContextMenu` adiacente con le voci condizionali
(filtra lo stato corrente). Click su Annulla del submenu = no-op.
- File: `app/templates/pages/planning.html` — sezione "contextmenu" del
  listener vis-timeline.

**P2 — Icone visibili per BookingStatus tentative + confirmed**
Pre-α.66.3 lo stato `tentative` aveva solo bordo dashed; `confirmed`
nessun marker visivo. Ora aggiunte icone inline (oltre alle classi CSS):
- ⏳ per tentative (grigio chiaro, accanto al titolo) → unisce al bordo
  dashed esistente per evidenza forte.
- ✓ per confirmed (verde discreto opacity .7) → operativo, non rumoroso.
- Legenda toolbar aggiornata: nuova riga "Confermato" con esempio.
- Icone `tl-status-icon`/`tl-status-tentative`/`tl-status-confirmed`
  precedono le icone execution_status (`tl-exec-icon` ▶/✓/✗) nel
  content. I due assi (BookingStatus vs execution_status) coesistono.

**P3 — Slice-lock relax: tentative liberi, confirmed con conferma**
Pre-α.66.3 `_assert_no_blocking_slice` bloccava qualunque modifica su
booking dentro periodo fatturato (HARD-BLOCK 409 cieco).

Nuova policy:
- **Tentative in periodo fatturato**: SKIP automatico del guard.
  Modificabili liberamente. Niente bordo viola 🔒 in timeline (filtro
  in `_lock_for_assignment` server-side).
- **Confirmed in periodo fatturato**: 409 con `code=SLICE_LOCK_CONFIRM_REQUIRED`
  (era `BOOKING_LOCKED_BY_SLICE`). Detail include `slice` + `hint` per il
  client.
- **`force_slice_unlock=true`** (Form/query param): bypass esplicito
  del guard, usato dopo conferma utente.

Backend: `_assert_no_blocking_slice(db, b, *, force=False)` con la nuova
policy; aggiunto `force_slice_unlock` Form/query param ai 5 endpoint
mutator: `update_booking`, `update_assignment`, `delete_assignment`,
`delete_booking`, `multi_move_assignments`, `update_booking_execution`.

Frontend: gestione automatica del code in `app/static/js/global.js` →
`api()` ora intercetta 409 con `code=SLICE_LOCK_CONFIRM_REQUIRED`,
mostra `confirm()` con dettagli (periodo + numero fattura), e se OK
re-invia automaticamente la richiesta con `force_slice_unlock=true`.
**Single retry**, no loop. Tutti i call site `api(...)` mutator del
planning beneficiano automaticamente — niente cabling puntuale.
- Cache-buster `global.js?v=` bumpato a `3.5.0-alpha.66.3`.
- Errori `Error.detail` (oggetto strutturato) e `Error.status` (HTTP
  code) ora esposti dal generico `api()` per intercettazione di code
  custom in futuro.

**Smoke**: 276 routes invariato, version 3.5.0-alpha.66.3.

**Verifica live**:
1. Hard-refresh (forza reload `global.js?v=3.5.0-alpha.66.3`).
2. Submenu Marcature: click destro su un booking → "🏷 Marcature ▸"
   → secondo menu con le voci condizionali. ▶ Inizia → toast "avviato".
3. Icone status: prendi un booking tentative → vedi ⏳ + bordo dashed.
   Confermalo (context-menu "✓ Conferma booking") → ⏳ → ✓ verde discreto.
4. Slice-lock relax: prendi un booking **tentative** dentro un periodo
   fatturato → drag-resize liberamente, nessun lucchetto 🔒, nessun
   blocco. Prendi un booking **confirmed** dentro un periodo fatturato
   → drag → confirm dialog "Stai modificando un booking CONFERMATO in
   periodo fatturato (data → data, fattura N). Confermi?". Click OK →
   modifica passa. Click Annulla → toast errore (originale 409).

**Cosa NON cambia in α.66.3**:
- Schema DB invariato.
- Cost-report calcola sempre da assignments effettivi (no override).
- La fattura emessa resta inalterata anche dopo override slice-unlock:
  `total_accrued` ricalcola, `billed_amount` (snapshot) resta.

---

## v3.5.0-alpha.66.2 — Fix root cause: vis-timeline doubleClick double-fire (9 maggio 2026)

Bug rilevato da Matteo: i booking nuovi nascevano con la stessa risorsa
"duplicata" anche quando il DB ne aveva una sola. Sintomo: doppio-click
sul booking → modal edit con 2 righe identiche.

**Root cause** (diagnosticata via logging client-side temporaneo):
**vis-timeline 7.x emette il `doubleClick` due volte** per ogni gesto:
1. Una dal recognizer Hammer.js interno (`e.recognize` → `tryEmit` → `emit`)
2. Una dal native DOM `ondblclick` (`p.dom.root.ondblclick`)

Il listener `tlInstance.on('doubleClick', ...)` invocava `tlbOpenEdit(bid)`
due volte. Essendo async (await su `/jobs/api/{id}` per quote/lavorazione),
il primo invocation era ancora in volo quando partiva il secondo:
ognuno faceva `_tlbReset()` (svuotava) e poi aggiungeva una riga →
modal con 2 righe per 1 assignment in DB. Stessa dinamica per il
modal "nuovo booking" su area vuota (`tlbOpen`).

**Fix in `app/templates/pages/planning.html`** (1 listener, 1 guard):
```js
let __tlLastDblClick = 0;
tlInstance.on('doubleClick', async (props) => {
  const now = Date.now();
  if (now - __tlLastDblClick < 350) return;  // 2° fire: ignora
  __tlLastDblClick = now;
  ...
});
```
Window 350ms (gap tipico dblclick è ~250ms, doppio-fire <10ms).

**Cosa NON era il bug**:
- Backend `create_booking` / `update_booking` corretti, guard
  `_check_intra_payload_overlaps` funzionante.
- Booking #61 con 4 assignments **non era duplicato**: 2 risorse × 2
  segmenti contigui da smart-split pausa pranzo (legittimo).
- 8 endpoint senza guard intra-payload trovati nell'audit (multi-move,
  extend-as-series, ecc.) sono comunque potenziali fragilità da
  hardenare in α.67, ma NON erano il bug del job 99.

**Strumento utile lasciato**: nuovo endpoint
`GET /planning/api/diag/booking-raw/{id}` (manager+) che dumpa il
record grezzo del booking + tutti i suoi assignments + audit changes.
Lo abbiamo usato per scartare l'ipotesi "bug server-side" sul #99.

**Memoria progetto aggiornata**:
`feedback_vis_timeline_quirks.md` — aggiunta 4ª trappola: doubleClick
double-fire (Hammer.js + DOM nativo).

**Smoke**: 274 routes (+1 endpoint diag), version 3.5.0-alpha.66.2.

---

## v3.5.0-alpha.66.1 — Hotfix: warning duplicate-overlap nel modal edit booking (9 maggio 2026)

Bug rilevato da Matteo via screenshot: il modal "Modifica booking #96" mostrava
2 righe risorsa con identico Luca Bianchi (overlap totale 09:00–13:00 stesso
giorno) **senza alcun warning**. Il pannello giallo "🧹 Rimuovi duplicati"
introdotto in α.63 era cablato solo nella todo-card detail (`todoOpenDetail`),
non nel modal edit (`tlbOpenEdit`). Dato sporco pre-α.63 invisibile a chi
apre il modal edit.

**Fix client-side** (no backend changes):
- `_tlbCheckDuplicateOverlaps()`: scorre le righe del modal, raggruppa per
  resource_id, per ogni gruppo con 2+ righe verifica overlap pairwise. Se
  trova duplicati, marca le righe coinvolte con classe
  `.tl-row-duplicate-overlap` (bordo rosso 4px sx + sfondo .10) e mostra
  pannello giallo `#tlb-duplicate-warning` con elenco risorse + bottone
  "🧹 Rimuovi duplicati".
- `tlbFixDuplicateOverlapsHere()`: chiama
  `POST /planning/api/bookings/{id}/cleanup-duplicate-overlaps` (endpoint
  α.63 esistente), poi ricarica il modal con i dati puliti.
- Cabling: `tlbOpenEdit()` chiama check all'apertura. `tlbAssOnChange()`
  ri-controlla live (cambio risorsa o orario) con throttle 80ms.
  `tlbRemoveAssignmentRow()` ri-controlla post-remove. `_tlbReset()` nasconde
  il warning quando si apre per nuovo booking.

**File: `app/templates/pages/planning.html`** — nuovo `#tlb-duplicate-warning`,
CSS `.tlb-ass-row.tl-row-duplicate-overlap`, 2 fn nuove.

**Smoke**: 273 routes invariato, version 3.5.0-alpha.66.1.

**Verifica live**: apri il modal edit del booking #96 → ora vedi il warning
giallo + le 2 righe Luca Bianchi con bordo rosso → click "🧹 Rimuovi duplicati"
→ il sistema cancella la 2ª riga (mantiene la prima per orario di inizio),
ricarica il modal pulito.

---

## v3.5.0-alpha.66 — Planning quick wins: paste immediato + fasce orarie + status visivo + cambio stato dal menu (9 maggio 2026)

Bundle 4 punti da feedback Matteo dopo α.65: tutti pertinenti al planning,
nessuna migrazione DB, niente nuovi endpoint backend (riusa quelli esistenti).

**1. Ctrl+V incolla SUBITO (era: paste-mode interattivo)**
- Pre-α.66: Ctrl+V entrava in "paste mode" e aspettava un click sulla
  timeline per scegliere il punto di atterraggio.
- α.66: **Ctrl+V** = incolla immediato a +1 giorno, stessa risorsa, stesso
  orario. Se conflict orario sul +1, ritenta automaticamente +2..+7.
  **Ctrl+Shift+V** = paste-mode legacy (per chi vuole scegliere il punto).
- Voci context-menu nuove: **📅 Duplica giorno dopo** e
  **📅 Duplica settimana dopo** (riusano `tlInstantPaste`).
- File: `app/templates/pages/planning.html` — nuova fn `tlInstantPaste()`,
  refactor handler `keydown` (riconosce shiftKey).

**2. Quick-pick fasce orarie nel modal booking**
- Aggiunti 3 bottoni preset sopra le righe assignment del modal toolbar:
  **🌅 Mattina**, **☀ Pomeriggio**, **📆 Tutto il giorno**. Click → applica
  gli orari della WorkingHoursPolicy default (`morning_start/_end` +
  `afternoon_start/_end`) a TUTTE le righe del modal, preservando la data
  corrente di ogni riga (default oggi se vuota).
- Lazy-load `/settings/api/working-hours` (cached in `window._tlPolicies`).
- Fallback hardcoded 09:00-13:00 / 14:00-18:00 / 09:00-18:00 se policy
  non disponibile.
- File: `planning.html` — nuovi bottoni nell'header risorse + fn
  `tlbApplyTimePreset(slot)` + `_tlbLoadPoliciesOnce()`.

**3. Status booking visivamente rinforzato + legenda**
- CSS done rinforzato: bordo verde 3px sx (era 2px solo inset), opacity
  .92 (era .82, troppo simile a planned), check ✓ più grande/contrastato.
- Nuovo bottone toolbar **🏷 Legenda** che apre popover con i 5 stati
  visivi (Planned / In corso / Fatto / Non fatto / Tentative) + 2 stati
  trasversali (Cross-dept, Slice-locked) e suggerimento sul context-menu.
- Pattern già esistenti per `in_progress` (glow arancione lampeggiante),
  `not_done` (tratteggio rosso 45°), `tentative` (bordo dashed): invariati.
- File: `planning.html` — nuovo `#tl-legend-pop`, fn `tlLegendToggle()`.

**4. Cambio stato lavorazione dal context-menu**
- Pre-α.66: il context-menu su un booking aveva solo `Modifica`,
  `Conferma/Tentative` (BookingStatus), `Duplica`, `Reassign`, `Elimina`.
  Per cambiare `execution_status` bisognava aprire le todo-card o il
  modal edit.
- α.66: aggiunte voci condizionali (filtra lo stato corrente):
  - **▶ Inizia (in corso)** — planned/done/not_done → in_progress
  - **✓ Marca come fatto** — qualsiasi → done
  - **✗ Marca come non fatto** — chiede `not_done_reason` via prompt
  - **↺ Riapri (planned)** — solo se done o not_done
- Riusa endpoint esistente `PATCH /planning/api/bookings/{id}/execution`
  (planning.py:3062). Nessun cambio backend.
- File: `planning.html` — refactor del menu in `tlInstance.on('contextmenu', ...)`.

**Smoke test boot**: 273 routes (invariato vs α.65, nessun nuovo endpoint),
version 3.5.0-alpha.66. Nessun errore di import.

**Verifica live richiesta a Matteo**:
1. Pull → app boot pulito (273 route, version 3.5.0-alpha.66). Nessuna
   migrazione DB.
2. **Ctrl+V immediato**: seleziona 1+ booking → Ctrl+C → Ctrl+V → si crea
   subito una replica +1 giorno con stesso orario+risorsa. Tooltip undo.
   Test conflict: due booking su giorni consecutivi → Ctrl+C+V → il
   secondo "scivola" a +2gg automaticamente (toast "1 spostato per
   conflitto"). Ctrl+Shift+V → comportamento vecchio (paste-mode).
3. **Voce context-menu duplica**: click destro su un booking → "📅
   Duplica giorno dopo" → replica immediata. Stessa cosa "settimana dopo".
4. **Fasce orarie**: apri modal "+ Nuovo booking" → click "🌅 Mattina"
   → tutte le righe ricevono start=09:00 end=13:00 (o quanto da policy).
   Stesso per "☀ Pomeriggio" e "📆 Tutto il giorno". Hint a destra mostra
   l'intervallo applicato per 4s.
5. **Legenda**: toolbar planning → click "🏷 Legenda" → popover con i
   5 stati visivi e descrizione. Confronta con un booking sulla
   timeline che ha il bordo dashed (tentative) o tratteggiato (not_done).
6. **Cambio stato dal menu**: click destro su un booking planned →
   menu mostra "▶ Inizia · ✓ Marca come fatto · ✗ Marca come non fatto"
   (manca "↺ Riapri" perché ancora non in done/not_done). Marca come
   "non fatto" → prompt motivo obbligatorio. Click destro su booking
   done → vede solo "↺ Riapri" + altre. La timeline si aggiorna subito
   (icona done verde, tratteggio rosso, ecc.).

**Cosa NON cambia in α.66**:
- Nessuna migrazione DB.
- Nessun nuovo endpoint backend (riusa quelli esistenti).
- Pattern visivi esistenti `tl-exec-in_progress`, `tl-exec-not_done`,
  `tl-tentative`, `tl-cross-dept`, `tl-slice-locked` invariati.
- Behavior pre-α.66 di paste-mode mantenuto su Ctrl+Shift+V.

**Prossimi step (post-test live)**:
- α.67 candidato (roadmap): Punto 5.b della roadmap billing
  (`InvoicePayment` + cashflow timeline revenue-only).
- (eventuali tweak feedback): se manca un bottone "Mattina+Pomeriggio
  spezzato" o quick-pick "ultime 8h" → aggiunta semplice.

---

## v3.5.0-alpha.65 — Pass-through OT al cliente (opt-in) + monte ore booking interni (9 maggio 2026)

Primo step della roadmap billing α.65+ (overtime weighted). Decisioni
semantiche prese con Matteo prima del codice (memoria
`project_billing_roadmap_alpha65plus`):
- **OT status**: solo APPROVED applica i moltiplicatori, PENDING resta lineare
  ma è esposto in tooltip "+€X pending" senza alterare i numeri certi.
- **Day-unit**: conversione lineare → 8-22 con 6h OT × 1.30 = 1.725 gg.
  Zero migrazione su JobCostLine.
- **Booking interni**: report HR-side separato (manutenzione/R&D/training),
  fuori dal cost-report cliente.
- **Scope weighted al maturato (revenue)**: opt-in per progetto via flag
  `Job.weighted_revenue` (default OFF). Il cost-side interno (`_bookings_hours_cost`)
  era già pesato a prescindere via `compute_assignment_breakdown`.

**1. Flag Job.weighted_revenue + auto-migrate**

- `app/models/models.py` `Job`: nuovo campo `weighted_revenue: bool = False`.
- `app/main.py` `_auto_migrate_columns`: ALTER TABLE jobs idempotente
  per aggiungere la colonna su DB esistenti (BOOLEAN NOT NULL DEFAULT 0).

**2. Engine weighted hours nel cost_line_sync (gated dal flag)**

- `app/services/cost_line_sync.py`:
  - Refactor `_booking_hours()` → due path:
    - `_booking_hours_linear(b)`: comportamento storico (somma man-hours).
    - `_booking_hours_weighted(db, b)`: usa
      `compute_assignment_breakdown.weighted_factor` per ogni assignment
      con la WorkingHoursPolicy della risorsa (override o default tenant).
      `Booking.overtime_status=pending` → ore OT NON pesate (decisione α.65).
  - `recompute_cost_line_actual()` risolve `Job.weighted_revenue` (1 query),
    passa `weighted=` ai `_booking_hours()` e include `weighted_revenue`
    nel response. JCL.qty diventa `weighted_factor / 8` per day-unit
    (1.725 gg lineare).
- L'engine `compute_assignment_breakdown` esisteva già in
  `app/services/booking_cost.py` (multipliers + brackets CCNL + pending
  gate); riuso senza creare nuovo file.

**3. UI toggle pass-through nel cost-report + tooltip pending OT**

- `app/routers/cost_report.py`:
  - `PUT /api/job/{id}/weighted-revenue` (Form `enabled: bool`): persiste
    il flag + trigger `recompute_for_job` automatico per allineare il
    maturato del job esistente. Idempotente.
  - `GET /api/job/{id}` espone `job.weighted_revenue` e per ciascuna
    cost-line: `pending_overtime_hours` + `pending_overtime_amount`
    (stima del delta maturato post-approvazione, > 0 solo se
    `weighted_revenue=True`).
- `app/templates/pages/cost_report.html`:
  - Toolbar dettaglio: nuova checkbox "Pass-through OT al cliente" con
    badge ATTIVO viola e conferma esplicita all'attivazione.
  - Riga JCL: badge giallo "⏳ Xh pending" con tooltip che mostra il
    delta € atteso se il pass-through è ON (informativa anche con OFF).

**4. Report HR booking interni (kind != project)**

- `app/routers/hr.py`:
  - `GET /api/internal-bookings-report?from_date&to_date`: aggrega
    booking con `kind ∈ {internal_maintenance, internal_research,
    internal_training}`. Ritorna totals + by_resource + by_kind con
    ore lineari e ore pesate (multipliers della policy della risorsa).
- `app/templates/pages/hr.html`:
  - Nuova tab "🛠 Booking interni" accanto a Tabella/Calendario.
  - Filtro periodo (da/a) + quick range settimana/mese/anno.
  - 4 KPI cards (booking count, ore lineari, ore pesate, delta multiplier).
  - Card "Per tipologia" (manutenzione/R&D/formazione) + tabella per risorsa.
  - Persistenza vista in localStorage (`mf_hr_view`).

**Smoke test boot**: 273 routes (+2 vs α.64), version 3.5.0-alpha.65.

**Verifica live richiesta a Matteo**:
1. Pull → app boot pulito (273 route, version 3.5.0-alpha.65). DB
   migrato in automatico al primo boot (log
   `[auto-migrate] jobs.weighted_revenue mancante -> ALTER TABLE`).
2. **Pass-through OT al cliente**: apri /cost-report → progetto con
   booking che hanno overtime/notte/dom/festivo APPROVATI → toolbar
   detail mostra checkbox "Pass-through OT al cliente" (default OFF
   → maturato lineare). Click ON → conferma + reload → badge ATTIVO
   viola, maturato JCL aumentato (es. 1 gg con 6h OT × 1.30 → 1.725 gg).
   Toggle OFF → torna lineare.
3. **Pending OT in tooltip**: progetto con almeno un booking
   `overtime_status=pending` → riga JCL mostra badge giallo
   "⏳ Xh pending". Hover → tooltip con stima `+€` SOLO se pass-through
   ON, altrimenti "non rifatturate al cliente con questa configurazione".
4. **Solo APPROVED conta**: rifiuta o lascia pending un OT su un job
   con weighted_revenue ON → maturato resta lineare per quelle ore
   (non pesate). Approva → al recompute (auto al toggle/edit booking
   o manuale via "Aggiorna ore") il maturato sale.
5. **Booking interni**: apri /hr → tab "🛠 Booking interni" → range mese
   corrente → vedi totale ore lineari + pesate + delta moltiplicatori +
   distribuzione per tipologia (manutenzione/R&D/formazione) + tabella
   per risorsa con breakdown per kind. Test: crea un booking
   `internal_maintenance` su una risorsa, ricarica → la risorsa appare
   con monte ore corrispondente.

**Cosa NON cambia in α.65**:
- Cost-side interno (`_bookings_hours_cost`): già pesato a prescindere
  da α.65, lasciato invariato.
- Default behavior: tutti i job esistenti restano `weighted_revenue=False`
  → maturato cliente lineare come prima dell'α.65 (back-compat 100%).
- Nessuna modifica al modello JCL (no nuova colonna `weighted_hours`).
- Cashflow completo (5.b InvoicePayment, 5.c cashflow timeline) e
  supplier invoice (punto 6): rimandati ad α.66+.

---

## v3.5.0-alpha.64 — Trasmissione granulare + refer-to-sales completo (8 maggio 2026)

Bundle "trasmissione & refer-to-sales completo" da feedback Matteo dopo α.63
(3 punti rilevati durante test live billing). Niente cashflow ancora — quello
è un altro round (α.65+) con decisioni semantiche da prendere.

**1. Link strutturale [EXTRA] → JCL d'origine**

Pre-α.64: la riga `[EXTRA]` generata da refer-to-sales (α.62) era pura
documentazione testuale. Nessun FK alla JCL d'origine → bisogna leggere
`detail` per capire da dove veniva. Matteo: "vedo una voce extra, a cosa
corrisponde?".

- **Migrazione DB**: `quote_lines.referred_from_jcl_id` (nullable FK a
  job_cost_lines, idempotente, ALTER TABLE in `_auto_migrate_columns`).
- `app/models/models.py` `QuoteLine`: nuovo campo + relationship
  `referred_from_jcl`.
- `app/routers/billing.py` `_refer_jcl_to_sales_impl()`: valorizza
  `referred_from_jcl_id=jcl.id` per la riga `[EXTRA]` creata, sia in
  mode `extend_existing` che `new_linked`.
- `app/routers/billing.py` 2 endpoint nuovi:
  - `GET /jcl/{id}/origin-info` → info compatte per UI quote (cost-report URL).
  - `GET /jcl/{id}/referrals` → lista quote-line che referenziano la JCL.
- `app/routers/quotes.py` `get_quote()`: espone `referred_from_jcl_id`
  per ogni line.
- `app/routers/cost_report.py` `job_cost_report()`: pre-fetch bulk dei
  referrals (1 query JOIN) e li espone in `cost_lines[i].referrals`.
- **UI quote** (`quotes.html` `renderLineRow`): badge viola "↪ Da JCL #X"
  cliccabile sulle righe con `referred_from_jcl_id`. JS
  `openOriginCostReport()` usa origin-info per aprire il cost-report del
  job in nuova tab.
- **UI cost-report** (`cost_report.html`): badge viola "↪ Q-NNN-NN v2"
  sulle righe JCL con `referrals` valorizzati, link a /quotes#{id}.

**2. Trasmissione granulare: scelta voce per voce**

Pre-α.64: `transmit` accettava solo `include_extras` (booleano globale).
Per escludere righe singole bisognava editare `is_billable=False` riga
per riga. Matteo: "dammi la possibilità di scegliere quali voci includere
o escludere".

- `app/routers/billing.py`:
  - `_transmit_core()`: nuovo parametro opzionale `jcl_ids: list[int]`.
    Se valorizzato, filtra le candidate a quella lista esplicita. Validazione:
    se nessun id intersecta le candidate normali (not_billed + accrued + billable)
    → ValueError chiaro.
  - `transmit_to_billing` endpoint: nuovo Form param `jcl_ids` (CSV stringa
    parsata a `list[int]`). Back-compat: se omesso, comportamento "tutte le
    candidate" come pre-α.64.
  - `preview_transmission`: ogni line in response include ora `job_id`,
    `job_code`, `job_title`, `overrun` (per evidenziare in UI le righe in
    sforamento).
- **UI cost-report** (`cost_report.html`):
  - La modal Trasmetti diventa **tabella editable** con checkbox per ogni
    JCL candidata (default tutte checked). Colonne: descrizione + badge
    `[extra]` + badge sforamento + job-code, qty, prezzo, maturato.
  - Bottoni "tutti / nessuno" sopra la tabella.
  - **Subtotale dinamico** aggiornato in tempo reale (`updateTransmitSubtotal()`
    su ogni `change` checkbox).
  - Bottone Trasmetti disabilitato se 0 selezionati.
  - `submitTransmit()`: raccoglie gli id checked → `jcl_ids` CSV nel POST.

**3. Refer-to-sales DA batch detail (chiusura cerchio α.62)**

Pre-α.64: il bottone `↪ Rimanda al commerciale` esisteva solo in cost-report.
Il manager in /finance non aveva un equivalente: poteva ridurre l'importo
(delta → LossEntry) o "Rimanda al consuntivo" (defer), ma non c'era un'opzione
per girare la riga al commerciale come addendum quote.

- `app/routers/billing.py`:
  - Refactor: estratto `_refer_jcl_to_sales_core()` + `_refer_jcl_to_sales_impl()`
    dal corpo dell'endpoint `/refer-to-sales` (α.62) per riuso. L'endpoint
    originale resta come wrapper che converte ValueError → HTTPException.
  - Nuovo endpoint `POST /finance/api/billing/{batch_id}/lines/{line_id}/refer-to-sales`:
    combina `defer` (rilascia JCL dal batch, BBL cancellata, batch ricalcolato)
    + `_refer_jcl_to_sales_core` (crea quote/versione con riga `[EXTRA]`).
    Atomico: se refer fallisce, rollback completo (la riga torna nel batch).
- **UI /finance** (`finance.html`):
  - Nuovo bottone `↪ AM` (viola) accanto a `↪ Rimanda` su righe batch in
    draft con `is_extra=True` o `over > 0`. Apre dialog inline (modal
    creato JS al volo) con scelta extend/new + textarea note.
  - On success: toast + `window.open(quote_url)` in nuova tab + reload
    batch detail (chiude se 0 righe rimaste).

**Cosa NON cambia in α.64**:
- Cashflow: **non toccato** — modello straordinari weighted-hours è
  pianificato per α.65 (richiede decisioni semantiche su solo-approved
  vs pending, day-unit vs hr-unit).
- Costi cost-side (Resource.hourly_cost): non aggiunti.
- InvoicePayment: non aggiunto (rimandato).
- Supplier invoice / commesse esterne: non toccate (modulo nuovo da pianificare).
- Slice lock α.59: invariato (i booking dentro slice fatturate restano
  immutabili anche con la nuova trasmissione granulare).
- Convenzione segno over_under: invariata.

**Smoke test boot**: 271 routes (+3 vs α.63), version 3.5.0-alpha.64.

Le 3 route nuove:
- `GET /finance/api/billing/jcl/{id}/origin-info`
- `GET /finance/api/billing/jcl/{id}/referrals`
- `POST /finance/api/billing/{batch_id}/lines/{line_id}/refer-to-sales`

## v3.5.0-alpha.63 — Bulk job-change + extend-as-series + dedup risorse (8 maggio 2026)

Round chiuso da feedback Matteo dopo α.62. 4 problemi distinti su pianificazione,
ognuno con una causa diversa, una soluzione mirata e niente abstractions
gratuite.

**1. Bulk-edit "Cambia lavorazione" (e job)**

Era assente: in bulk si poteva spostare/shiftare/cambiar stato ma non cambiare
la lavorazione di destinazione (= il job sul cost report).

- `app/routers/planning.py`:
  - `bulk_edit_bookings()`: nuovo parametro `job_cost_line_id`. Risolve la JCL
    + il job, valida appartenenza tenant, applica per booking. Re-sync
    `cost_line_actual` per VECCHIA + NUOVA cost_line se booking done. Auto-
    assignment risorse → nuovo job. Log change tracciato.
  - `GET /api/bookings/bulk-edit/eligible-cost-lines?ids=...`: ritorna le JCL
    candidate. Se i booking selezionati appartengono a progetti diversi,
    `same_project=False` e UI mostra warning. Cross-job dello stesso project
    OK (più job per progetto = scenario reale).
- `app/templates/pages/planning.html`:
  - Modal Bulk-edit: nuova sezione "📂 Lavorazione" con dropdown popolata via
    fetch. Help text dinamico (caricamento / progetti diversi / candidati).
  - `tlSubmitBulkEdit()`: invia `job_cost_line_id` + estende snapshot undo
    (memorizza vecchio `job_cost_line_id`, ripristino bulk in 1 chiamata).

**2. Stessa risorsa appariva 2 volte sul booking**

Sara Conti compariva 2x in dettaglio. Il dedup frontend (α.24) c'era già MA
copre solo la visualizzazione. La causa era a monte: nessun guard impediva
l'inserimento di 2 BookingAssignment con stessa risorsa CON OVERLAP.

- `app/routers/planning.py`:
  - `_check_intra_payload_overlaps()`: scan a coppie sul payload
    assignments di POST/PUT booking. Stessa risorsa con overlap → 400.
    Segmenti contigui (es. split pranzo) restano permessi.
  - `GET /api/bookings/{id}/detail`: aggiunto `has_duplicate_overlaps` +
    `duplicate_resource_ids` per UI warning sui dati storici.
  - `POST /api/bookings/{id}/cleanup-duplicate-overlaps`: rimuove duplicati
    storici (tiene il primo per start, cancella overlap successivi).
- `app/templates/pages/planning.html`:
  - `todoOpenDetail()`: pannello giallo "⚠ Anomalia" sopra Risorse + bottone
    "🧹 Rimuovi duplicati" che chiama l'endpoint cleanup con conferma.
  - `todoFixDuplicateOverlaps()` nuova funzione.

**3. Feedback chiaro su skip/conflict in bulk**

Pre-α.63 il toast diceva solo "ok N · falliti M" senza dettaglio.

- `app/routers/planning.py` `bulk_edit_bookings()`: response arricchita con
  `skipped_locked_count` (booking bloccati da slice fatturate, separati dai
  conflitti orari) + ogni elemento di `failed` ha ora `reason` umana ("Booking
  dentro periodo già fatturato (date → date, fattura N)" oppure "Conflitto
  orario: #ID → #IDcausante").
- `app/templates/pages/planning.html`:
  - Pannello `bulk-result-detail` dentro il modal: appare se failed>0 o
    skipped>0, lista per booking_id con motivo. Modal resta aperto se ci sono
    fail (utente vede subito chi è saltato e perché). Toast riassuntivo: "✓ N
    aggiornati · ⚠ M falliti · 🔒 K bloccati (fatturati)".

**4. Modifica booking creando nuova serie da quello → "aggiornato" ma niente nuovi booking**

Causa: il PUT /api/bookings/{id} ha sempre ignorato `recurrence_rule` /
`recurrence_until` (quei campi vivono solo nel POST). In edit mode l'utente
compilava i campi, ricarica, "aggiornato" → niente.

- `app/routers/planning.py`:
  - `POST /api/bookings/{id}/extend-as-series`: estende un booking esistente
    come pattern. Replica gli assignments shiftati al delta giornaliero per
    ogni occorrenza, esclude la data del pattern (già materializzato).
    Conflict check per occorrenza → quelle in conflitto vanno in `failed`,
    le ok vengono create. Auto-assignment risorse al job. Log change.
- `app/templates/pages/planning.html`:
  - In `tlbOpenEdit()`: la sezione ricorrenza cambia label in "Estendi come
    serie" + hint "crea booking aggiuntivi nelle date generate (questo
    booking resta come pattern)". `_tlbReset()` ripristina "Ricorri".
  - `tlbSubmit()`: in edit mode, se ricorrenza valorizzata, dopo il PUT
    fa POST a /extend-as-series con rule+until. Toast con N create + N
    saltati per conflitto. Alert dettagliato se 0 create.

**Cosa NON cambia in α.63**:
- Nessuna migrazione DB.
- Convenzione segno over_under, formule cost report, status flow: invariati.
- /finance batch detail: nessun cambiamento.
- Slice lock α.59: ovvio, sempre attivo (i booking dentro periodi fatturati
  restano immutabili anche da bulk-edit / extend-as-series).

**Smoke test boot**: 268 routes (+3 vs α.62), version 3.5.0-alpha.63.

Le 3 route nuove sono:
- `POST /api/bookings/{id}/extend-as-series`
- `POST /api/bookings/{id}/cleanup-duplicate-overlaps`
- `GET /api/bookings/bulk-edit/eligible-cost-lines`

## v3.5.0-alpha.62 — Rimanda al commerciale (8 maggio 2026)

Quinto e ultimo step della riarchitettura billing concordata l'8 maggio.
Quando emerge extra/sforamento su un progetto già fatturato, il finance
ora ha un bottone esplicito per riferire la voce al commerciale: o estendi
la quote esistente (versioning) o crea una nuova quote linkata. Chiude
il loop "Cost Report → Fatturazione → ricognizione extra → commerciale".

**Endpoint nuovo** `app/routers/billing.py`:
- `POST /finance/api/billing/refer-to-sales` (form: `jcl_id`, `mode`,
  `notes` opt). Manager+ richiesto.
- `mode=extend_existing`: crea nuova versione della quote del job (catena
  versioning, parent_quote_id valorizzato), copia righe esistenti via
  `_copy_quote_lines(track_parent=True)`, aggiunge una riga `[EXTRA]`
  con qty/prezzo derivati da JCL.accrued_post_period (fallback total_accrued).
- `mode=new_linked`: crea nuova Quote indipendente sullo stesso project
  (no parent), con la sola riga `[EXTRA]`. Per addendum negoziati a parte.
- Risposta `{quote_id, quote_number, quote_url, mode}`.

**UI cost report** (`app/templates/pages/cost_report.html`):
- Nuovo bottone `↪` accanto a `✎` su righe con `accrued_post_period > 0`
  o `is_extra=True && total_accrued > 0`.
- Modal: 2 radio (estendi vs nuova) + textarea note. On success → toast
  + open quote in nuova tab.

**Cosa NON cambia**:
- Nessuna nuova migrazione DB.
- Conversion-to-job, deletion quote, status flow: invariati.
- /finance batch detail: nessun cambiamento (il bottone è in cost report).
- Le notifiche EXTRA_AFTER_BILLED di α.61 continuano a girare; il
  bottone è la risposta operativa esplicita.

**Smoke**: 265 routes (+1), version 3.5.0-alpha.62.

## v3.5.0-alpha.61 — Notifica EXTRA_AFTER_BILLED (8 maggio 2026)

Quarto step della riarchitettura billing. Quando emerge maturato
post-fatturazione (booking done che fa salire `total_accrued` di una JCL
che ha già almeno una `JCLBilledSlice`), il sistema notifica
automaticamente accounting + producer + manager + admin: c'è del nuovo
lavoro che andrà ri-trasmesso o coordinato col commerciale.

**Modello** `app/models/models.py`:
- Nuovo `NotificationKind.extra_after_billed`. Nessuna migrazione
  (varchar enum sotto, valori sono stringhe).

**Service** `app/services/billing_slice_guard.py` esteso:
- `maybe_notify_extra_after_billed(db, jcl)` — emette notifica se la JCL
  ha almeno una slice E `total_accrued − billed_locked > 0`. Idempotente:
  skippa se esiste già una notifica `extra_after_billed` non archiviata
  per la stessa JCL (ri-notifica solo dopo cleanup_old o archive
  manuale). Severity `action_required`. Link a `/cost-report#job-{id}`.

**Hook** `app/services/cost_line_sync.recompute_for_booking`:
- Dopo `recompute_cost_line_actual`, chiama il notify-helper. Wrappato in
  try/except: notifica non bloccante (errore stampato ma non fa fallire
  il sync del booking, prioritario).

**Destinatari**: ruoli `admin`, `manager`, `producer`, `accounting`. La
nozione di "commerciale del progetto" specifico non c'è ancora come
relazione modello — i producer fungono da proxy.

**Cosa NON cambia**:
- Trigger solo dal recompute di booking. Se l'extra emerge per un edit
  diretto JCL (raro), niente notifica (può essere aggiunto in α.61.x se
  Matteo lo chiede).
- UI notifiche: invariata, riusa il rendering generico esistente.
- Nessuna nuova route, nessuna migrazione DB.

**Smoke**: 264 routes, version 3.5.0-alpha.61.

## v3.5.0-alpha.60 — Cost report 3 colonne slice-based (8 maggio 2026)

Terzo step della riarchitettura billing. Le `JCLBilledSlice` ora alimentano
una vista a 3 colonne nel cost report che separa il chiuso contabile dal
maturato non ancora fatturato dalla stima futuro. Permette al producer di
vedere a colpo d'occhio: "ho già fatturato X, ho Y maturato pronto da
trasmettere, mi aspetto altri Z di lavoro".

**Service** `app/services/billing_slice_guard.py` (esteso):
- `billed_locked_for_jcl(db, jcl_id)` → Σ slice.billed_amount per quella JCL.
- `billed_locked_bulk(db, jcl_ids)` → variante bulk, singola query
  group_by per evitare N+1 nel cost report.
- `three_column_view(jcl, billed_locked)` → dict {billed_locked,
  accrued_post_period, forecast_future}. Definizione:
  - `billed_locked` = Σ slice.billed_amount (immutabile, già fatturato).
  - `accrued_post_period` = max(0, total_accrued − billed_locked) (done
    ancora senza slice → prossimo candidato di trasmissione).
  - `forecast_future` = max(0, total_expected − total_accrued) (planned
    non done → ulteriori ore stimate).

**API `/cost-report/api/list` e `/api/job/{id}`**:
- Aggiunti `billed_locked` / `accrued_post_period` / `forecast_future` in
  summary (per-job) e per ogni cost_line.
- Le viste over_under (now/forecast) restano invariate per back-compat.
- Pre-fetch slice in singola query bulk (tipicamente 10-50 JCL per job).

**UI `/cost-report` detail view**:
- KPI grid: 3 nuove card (Fatturato chiuso / Maturato post-periodo /
  Stimato futuro) con tooltip esplicativo. Sostituiscono le card
  "Stimato a finire" / "Maturato" / "Costo ore" che ora sono in fondo
  con sub-label aggiornata. Margine stimato resta.
- Tabella cost lines: colonne Maturato + Stimato sostituite da
  Fatturato + Mat. post + Stim. fut. (3 colonne separate). Quotato,
  Over/Under, Stato fattura invariati. Colspan empty-row aggiornato.

**Cosa NON cambia**:
- Lista cost report (vista riassuntiva top): mostra ancora Quotato /
  Maturato / Stimato / Over-Under aggregati — i nuovi campi sono nel
  payload se servono in futuro.
- Convenzione segno over_under (positivo = OVER) e formule esistenti.
- Export PDF/CSV/XLSX: invariati (potrà essere esteso se Matteo lo chiede).
- Nessuna migrazione DB.

**Smoke**: 264 routes, version 3.5.0-alpha.60.

## v3.5.0-alpha.59 — HARD-BLOCK booking in periodo fatturato (8 maggio 2026)

Secondo step della riarchitettura billing. Le `JCLBilledSlice` introdotte
in α.58 ora sono attive come invariante: un Booking il cui envelope
ricade in un periodo già fatturato non è più modificabile né cancellabile.
Il guard è centralizzato in un servizio dedicato e applicato sia su tutti
gli endpoint planning sia sui tool_use AI.

**Servizio nuovo** `app/services/billing_slice_guard.py`:
- `find_blocking_slice(db, booking)` — ritorna la prima slice che si
  sovrappone all'envelope del booking, o None.
- `find_blocking_slice_for_dates(db, jcl_id, start, end)` — variante per
  controlli pre-save su nuove date proposte (drag/resize).
- `slice_lock_message(slice)` / `slice_lock_payload(slice)` — formattazione
  standard per ValueError / HTTPException(409).

**Hard-block 409 in planning.py**:
- Helper locale `_assert_no_blocking_slice(db, b)` solleva
  `HTTPException(409, detail={code: "BOOKING_LOCKED_BY_SLICE", message,
  slice})`. Applicato in:
  - `PUT /api/bookings/{id}` (update_booking)
  - `PUT /api/booking-assignments/{id}` (update_assignment, sia date attuali
    sia nuove date proposte — un drag NON può uscire da un periodo locked)
  - `DELETE /api/bookings/{id}` (delete_booking)
  - `DELETE /api/booking-assignments/{id}` (delete_assignment)
  - `PATCH /api/bookings/{id}/execution` (cambio stato done/not_done)
  - `PUT /api/bookings/{id}/bulk-edit` (skippa locked, continua restanti)
  - `POST /api/multi-move` (all-or-nothing: blocca tutta la transazione)

**Guard AI in `app/services/ai_assistant.py`**:
- `_assert_no_blocking_slice` solleva `ValueError` (handler AI traduce in
  failure card). Applicato in `_resolve_booking_for_planning` (copre
  move/resize/delete) e in `_h_propose_bulk_move` per ognuno dei booking.
- `_assert_jcl_not_locked` rifocalizzato: ora blocca solo `JCLBillingStatus
  == in_batch` (batch in approvazione, niente slice ancora). Per `billed`
  e `paid` il check granulare è quello slice-based, che permette nuovo
  lavoro su periodi successivi senza ripristinare la JCL al manager.

**API `/planning/api/bookings`**:
- Ogni assignment ora include `extendedProps.slice_lock = { slice_id,
  period_start, period_end, invoice_number }` se ricade in un periodo
  fatturato. Pre-fetch con singola query di tutte le slice della JCL
  (no N+1).

**UI planning timeline** (`app/templates/pages/planning.html`):
- Classe `.tl-slice-locked` su `.vis-item`: bordo viola spesso a sinistra
  + icona 🔒 nel content + tooltip esteso con periodo + numero fattura.
- I 409 dei mutator si vedono come toast standard via `api()` helper
  (detail.message contiene il messaggio leggibile).

**Cosa NON cambia in α.59 (per scelta)**:
- Endpoint dedicato di rettifica (per emettere nota credito + riaprire
  periodo) — sarà in α.59.x se Matteo lo chiede dopo il test live.
- UI cost report: invariata (le 3 colonne arrivano in α.60).
- Nessuna nuova migrazione DB (le slice sono già popolate da α.58).

**Smoke**: 264 routes, version 3.5.0-alpha.59. Sintassi OK.

## v3.5.0-alpha.58 — JCLBilledSlice (foundation) (8 maggio 2026)

Primo step della riarchitettura billing concordata con Matteo. Introduce
il modello `JCLBilledSlice` come fonte di verità della "porzione di una
JobCostLine fatturata in uno specifico periodo". Foundation only: il
binario `JCLBillingStatus` resta in vigore per back-compat, ma da ora in
poi ogni emissione fattura genera anche slice immutabili che α.59 e α.60
useranno per superarlo.

**Modello nuovo** `app/models/models.py`:
- `JCLBilledSlice(tenant_id, job_cost_line_id, billing_batch_line_id,
  invoice_id, period_start, period_end, billed_quantity, billed_amount,
  unit_price_snap, created_at)`. Indici su jcl_id, period_start, period_end,
  billing_batch_line_id, invoice_id.
- Una JCL → N slice (progetti pluri-mensili fatturati a tranche). Lo
  slice è snapshot immutabile creato in `emit_invoice`, mai modificato.

**Hooks**:
- `POST /finance/api/billing/{batch_id}/invoice` (router billing.py): per
  ogni `BillingBatchLine` con `total_approved > 0` crea anche uno slice
  con periodo del batch e snapshot quantità/importo della line. Il
  `JCLBillingStatus` viene comunque marcato `billed` per non rompere il
  resto del codice.

**Backfill al boot** (idempotente, marker `uploads/.billed_slices_backfilled_v1`):
- Per ogni `BillingBatch` in stato `invoiced` e ogni sua line con
  `total_approved > 0`, crea uno slice retroattivo con periodo del batch.
  Skip se esiste già uno slice per quella batch_line. Log num righe
  popolate.

**Cosa NON cambia in α.58** (per scelta — minimum viable):
- UI: nessun cambio.
- API: nessuna nuova route, nessun cambio response.
- Logica preview/transmit: invariata.
- `JCLBillingStatus` enum: invariato.
- Behaviour edit/cancel batch: invariato.

**Prossimi step (roadmap riarchitettura billing)**:
- α.59: invariante hard-block (409) su backedit booking dentro periodo già
  slice-ato. Endpoint dedicato di rettifica per modifiche formali.
- α.60: cost report 3 colonne (Fatturato chiuso = Σ slice / Maturato post
  ultimo period_end / Stimato futuro). Convenzione Over/Under aggiornata.
- α.61: notifica `EXTRA_AFTER_BILLED` (extra emerso su periodo già slice-ato).
- α.62: bottone "Rimanda al commerciale" da /finance.

## v3.5.0-alpha.57 — Fix periodo trasmissione (8 maggio 2026)

Bug segnalato da Matteo: il modulo "Trasmetti a fatturazione" mostra date
periodo sbagliate, dovrebbero coprire dalla *prima* alla *ultima* data
lavorata in quella tranche.

**Causa**: `cost_line_sync.recompute_cost_line_actual` salva su
`JobCostLine.work_date` solo il MAX delle date dei booking done (l'ultima
data lavorata per JCL). Il preview/transmit faceva poi `min/max` di
`work_date` *tra le JCL candidate*: il "min" risultante era la più precoce
delle *ultime date*, non la prima data effettivamente lavorata. Esempio:
JCL con booking 1 mar → 30 apr aveva `work_date=30 apr` e il 1 mar era
perso nel calcolo del periodo proposto.

**Fix**: nuovo helper `_period_from_bookings(db, jcl_ids)` in `billing.py`
che legge direttamente da `Booking` (status != cancelled, execution_status
== done) e ritorna `(min(start_datetime), max(end_datetime), source)`.
Fallback al mese corrente solo se nessuna JCL candidate ha booking done
(es. JCL extra senza booking). Usato in:
- `GET /finance/api/billing/preview` (preview modal Trasmetti)
- `_transmit_core` (auto-derive quando period_start/end omessi)

`cost_line_sync` resta invariato: `JCL.work_date` continua a salvare la
data dell'ultimo done, utile per altre viste; non viene più usato per
calcolare il periodo di fatturazione.

**Note**:
- Il filtro `c.work_date is None or (period_start <= c.work_date <= period_end)`
  in `_transmit_core` resta sulla `work_date` della JCL. Quando l'utente
  override-a il periodo manualmente per fatturare solo una porzione (es.
  solo marzo) JCL con `work_date` post-marzo vengono escluse anche se
  hanno booking marzo. Questo bug pre-esistente sarà chiuso in α.58 con
  l'introduzione degli slice (modello fattura per periodo).

**Roadmap concordata con Matteo (8 maggio 2026)** sul flow Cost Report ↔ Fatturazione:
- α.57 (questa): fix bug periodo isolato.
- α.58: modello `JCLBilledSlice` (o estensione `BillingBatchLine` come
  slice di fatto) + populate retroattivo. Una JCL può essere "fatturata
  fino al periodo X, libera dopo X" — supera il binario `JCLBillingStatus`.
- α.59: invariante hard-block (409) su backedit di booking dentro slice
  fatturato. Per correzioni serve passare da rettifica formale.
- α.60: cost report 3 colonne — Fatturato chiuso / Maturato post-periodo
  fatturabile / Stimato futuro. Convenzione Over/Under aggiornata.
- α.61: notifica `EXTRA_AFTER_BILLED` (extra emerso su progetto già
  fatturato in periodo X) → destinatari accounting + commerciale del progetto.
- α.62: bottone "Rimanda al commerciale" da /finance: scelta esplicita
  estendi quote esistente (versioning) vs nuova quote linkata al progetto.

---

## v3.5.0-alpha.56 — Pulizia non-fatte + visibilità Over in fatturazione (8 maggio 2026)

Quattro micro-feature richieste da Matteo che chiudono il loop operativo
"booking eseguiti → cost report → trasmissione → fatturazione":

**1. Cost report — Scarta tutte le non fatte in blocco.**
Il pozzo "ore non maturate" mostrava un bottone Scarta per ogni riga ma non
c'era una scorciatoia per svuotare l'intero pool. Ora c'è.
- Endpoint nuovo: `POST /cost-report/api/job/{job_id}/not-done-pool/discard-all`
  cancella tutti i booking con `execution_status=not_done` e
  `count_in_costs=False` del job (status=cancelled). Idempotente.
- UI: bottone "🗑 Scarta tutte" nell'header del card "Pozzo ore non maturate"
  (visibile solo se il pool ha almeno una riga). Conferma esplicita prima
  dell'azione (azione non reversibile dal cestino UI standard).

**2. Planning — Filtro "Nascondi non fatte".**
Toggle binario nella sidebar filtri che rimuove i booking
`execution_status=not_done` da tutte le viste lato client.
- Checkbox `f-hide-not-done` nuovo, persistito in URL (`?hide-not-done=1`)
  come gli altri filtri. Compatibile con `readFiltersFromURL`,
  `writeFiltersToURL`, `resetFilters`, `renderActiveFiltersBar`.
- Helper `filterBookingsHideNotDone(bookings)` riusabile, applicato in
  `renderTimeline`, `renderAgenda`, `renderCalendar` (via `events:` function
  source FullCalendar perché l'API URL non offre filtri post-fetch),
  `renderTodo` (top-level `execution_status` non in `extendedProps`),
  `renderStoryboard`. Chip in active-filters bar quando attivo.

**3. Cost report — Visibilità split quote/extra/sforamento nel preview Trasmetti.**
Il toggle "Includi extra" funzionava già (verificato traccia
`tm-include-extras` → `_transmit_core` → `q.filter(JobCostLine.is_extra == False)`)
ma il preview mostrava solo un totale aggregato, dando l'impressione che
"venisse mandato tutto in unica cifra". Ora il breakdown è esplicito.
- `/finance/api/billing/preview` ritorna anche `quote_count`, `quote_total`,
  `extra_count`, `extra_total`, `overrun_total` (= sforamento sul quotato
  per le righe non-extra). `total_quoted` esposto per riga.
- UI modal Trasmetti: pillola "Da quote · N · €X" + pillola "Extra · M · €Y"
  + pillola "Sforamento quote · €Z" (solo se >0). Il toggle "Includi extra"
  ora ha effetto visibile: spegnerlo fa scomparire la pillola Extra dal
  preview e ricalcola il totale.

**4. Fatturazione — Over per riga e "Rimanda al consuntivo finale".**
Nel batch detail di /finance ora si vedono per ogni riga: Quotato originale,
Over (sforamento sul quotato per non-extra), Proposto, Approvato, Perso.
Sopra il batch un riepilogo aggregato Over + Extra. Il manager può decidere
riga per riga se fatturare subito o rimandare.
- Endpoint nuovo: `POST /finance/api/billing/{batch_id}/lines/{line_id}/defer`
  rimuove la BillingBatchLine dal batch (solo draft), JCL collegata torna
  `not_billed`, eventuali LossEntry collegate cancellate (era loss
  ipotizzata, non realizzata). Manager+ richiesto. Reversibile (basta
  ri-trasmettere). Se il batch resta vuoto il manager può annullarlo
  manualmente — niente auto-cancellazione magica.
- `_batch_to_dict(with_lines=True)` ora arricchisce ogni line con
  `total_quoted` (lookup batch su JCL via `object_session(b)`) e
  `over = max(0, total_proposed − total_quoted)` (0 per le extra che sono
  per definizione fuori budget).
- UI batch detail: 2 colonne nuove nella tabella (Quotato, Over) + bottone
  "↪ Rimanda" per ogni riga in batch draft. Conferma esplicita. Card
  riassuntive Over e Extra a livello batch (visibili solo se non zero) +
  hint inline che spiega "fattura subito vs rimanda al consuntivo finale".

**File toccati:**
- `app/routers/cost_report.py` — endpoint discard-all.
- `app/routers/billing.py` — preview breakdown, `_batch_to_dict` arricchito,
  endpoint defer-line.
- `app/templates/pages/cost_report.html` — bottone Scarta tutte +
  preview breakdown nel modal Trasmetti.
- `app/templates/pages/planning.html` — checkbox hide-not-done +
  helper `filterBookingsHideNotDone` + integrazione 5 viste.
- `app/templates/pages/finance.html` — colonne Quotato/Over + bottone
  Rimanda + card aggregate Over/Extra.

Niente migrazioni DB (solo nuovi endpoint e UI sopra schema esistente).
Niente breaking change su API esistenti (preview/batch_to_dict aggiungono
campi, non li rimuovono). Helper retro-compatibili.

## v3.5.0-alpha.55 — Cost report Over/Under doppia vista (8 maggio 2026)

Fix bug: `total_expected` per riga non veniva mai aggiornato dai booking,
quindi Over/Under restava 0 a meno di edit manuale. Ora la stima è
allineata in tempo reale al pianificato e il cost report espone due viste
(Maturato / Stima) selezionabili da UI ed export.

**Backend:**
- `cost_line_sync.recompute_cost_line_actual` ora calcola anche
  `quantity_planned` (booking non cancellati, non solo done) e popola
  `total_expected = qty_planned × unit_price`. Default a `quantity_quoted`
  se non c'è ancora alcun booking. Già chiamato in tutti gli hook
  planning/AI esistenti, quindi nessuna nuova invocazione necessaria.
- `cost_report.py` espone su `/api/list` e `/api/job/{id}` due nuovi campi:
  - `over_under_now` = `total_accrued − total_quoted` (extracosto certo,
    base fatturazione)
  - `over_under_forecast` = `total_expected − total_quoted` (sforamento
    previsto su base pianificato, base report cliente)
  - Per ogni riga: stessi due campi + `quantity_planned` derivato.
  - Convenzione segno: positivo = OVER (sforamento), negativo = UNDER
    (sotto budget). Inversa rispetto a pre-α.55.
  - Alias `over_under` mantenuto come back-compat (= forecast).

**UI cost report:**
- Toggle vista "Maturato vs Quotato | Stima vs Quotato" nella toolbar
  dettaglio. Default Maturato (più rilevante per fatturazione).
- KPI grid aggiornata con label dinamico e "qty pianificata × prezzo"
  come hint sotto Stimato.
- Lista cost report: filtro Over/Under usa la vista corrente. Colonna
  Over/Under con segno e colori coerenti (rosso=over, verde=under).
- `_crViewMode()` helper + `onViewModeChange()` ricomputa list/KPI/righe
  + export quando l'utente cambia la vista.

**Export:**
- Endpoint `client-pdf`, `client-csv`, `client-xlsx` ora accettano
  `?vista=now|forecast`. La modalità rendiconto include la label
  esplicita ("Over/Under su Maturato vs Quotato" o "su Stima vs Quotato").
- `_client_export_rows(report, rendiconto, vista)` propaga la scelta
  fino al totale parziale Over/Under.
- `pdf_export.generate_client_cost_report_pdf(..., vista="now")` con
  segno positivo = rosso (OVER), negativo = verde (UNDER).

**Backfill al boot:**
- Marker `uploads/.total_expected_backfilled_v1`: alla prima accensione
  α.55 ricalcola `total_expected` per tutte le JCL esistenti (idempotente,
  one-shot). Senza il backfill i DB pre-α.55 vedrebbero la nuova vista
  vuota fino al primo nuovo booking.

**Smoke test:**
- App boot OK, 262 routes, version 3.5.0-alpha.55.

**Verifica live richiesta a Matteo:**
1. Pull → app parte. Al primo boot vedi log
   `[lifespan] backfill JCL.total_expected: N/M righe ricalcolate`.
2. /cost-report → apri un job con booking pianificati ma non ancora done
   → vedi Stimato a finire = pianificato × prezzo, Maturato = 0.
3. Vista Maturato → Over/Under = 0 (non c'è ancora extracosto certo).
4. Vista Stima → se planned ≠ quoted → Over/Under = differenza, segno
   positivo se sforamento (rosso), negativo se sotto budget (verde).
5. Marca un booking done → Maturato cresce → vista Maturato mostra
   over/under reale.
6. Export PDF in vista Maturato → totale Over/Under usa accrued.
7. Export PDF in vista Stima → totale Over/Under usa expected.

## v3.5.0-alpha.54 — Capability copilot avanzate + Financial Copilot (8 maggio 2026)

Step 4 chiuso. Sei nuove capability per il copilot: 4 sulla pianificazione
(analisi conflitti, ricerca slot liberi, ricorrenti, bulk move) + 2 sul
finance (stato finanziario progetto readonly, trasmissione a fatturazione).

**Backend — Planning avanzato (4 capability):**
- `analyze_conflicts(days?, project_id?, department_id?)` — READONLY.
  Trova overlap nei booking di un periodo (default 14gg), restituisce
  coppie con `overlap_minutes` + suggerimento di risoluzione (sposta,
  cambia risorsa, split). Cap 50 risultati. USA per "trova i conflitti
  della prossima settimana", "ci sono sovrapposizioni su Luca?".
- `find_free_slots(duration_minutes, resource_id|department_id, from_date?,
  days?, work_hours_start?, work_hours_end?)` — READONLY. Cerca slot liberi
  per una risorsa o tutto un reparto, salta sab/dom, rispetta orario
  lavorativo (default 09:00–18:00). Cap 30 slot. USA per "quando ho 4h
  libere su Marco?", "che slot ha il colorist senior questa settimana?".
- `propose_recurring_bookings(job_id, resource_id, rule, start_date,
  until_date, start_time, end_time, job_cost_line_id?, title?)` — MUTATION.
  Crea N booking ricorrenti (rule: DAILY | WEEKDAYS | WEEKENDS | CSV
  "MON,WED,FRI"). Conflict check per occorrenza, le date in conflitto
  vengono saltate (non bloccanti). Audit `booking_changes` kind
  `ai_create_recurring`. USA per "prenota Luca lun-ven 9-13 da domani al
  30 maggio".
- `propose_bulk_move(booking_ids[], shift_minutes)` — MUTATION. Sposta N
  booking di un delta uniforme. Conflict check cross-batch (escludendo gli
  stessi booking della transazione). Atomic: se uno fallisce, nessuno
  viene spostato. JCL fatturate (in_batch/billed/paid) bloccate via
  `_assert_jcl_not_locked`. Audit kind `ai_bulk_move`. Recompute
  `recompute_for_booking` per ognuno. USA per "sposta tutti i booking
  della prossima settimana di +1 giorno".

**Backend — Financial Copilot (2 capability):**
- `query_project_finance(project_id)` — READONLY. Aggrega per progetto:
  budget_quoted, total_quoted, total_accrued, total_expected, expenses,
  margin, over_under, billing_status_breakdown (not_billed/in_batch/billed/
  paid/lost), invoices (invoiced/paid/to_collect), top 5 job per
  scostamento. USA per "qual è il margine del progetto X?", "quanto è
  fatturato sul progetto Y?", "quanto resta da incassare?".
- `propose_transmit_to_billing(project_id, include_extras?, notes?)` —
  MUTATION. Trasmette il maturato del progetto come BillingBatch in stato
  draft. Periodo derivato auto da min/max work_date dei booking done
  (fallback al mese corrente). Estrae logica core da
  `billing.transmit_to_billing` in `_transmit_core` riusabile (endpoint
  HTTP riconverte ValueError in HTTPException). USA per "genera la
  fattura mensile del progetto Ligas", "trasmetti a fatturazione".

**Refactor:**
- `app/routers/billing.py`: `_transmit_core(db, *, project_id, period_start?,
  period_end?, notes?, include_extras=True, user_id?)` — funzione pura
  riusabile. Periodo auto-derivato se omesso. Solleva `ValueError` (l'API
  HTTP wrappa in HTTPException 400/404).

**System prompt copilot:**
- Sezione "PIANIFICAZIONE AVANZATA" con le 4 capability nuove + esempi
  d'uso.
- Sezione "FATTURAZIONE" con `query_project_finance` + `propose_transmit_to_billing`.
- Regola `ricorrenti`: ora "USA `propose_recurring_bookings` invece di
  20 booking singoli".
- Regola `JCL fatturate sono LOCKED`: avvisa l'AI che move/resize/delete/
  bulk_move falliranno se JCL `in_batch`/`billed`/`paid`.

**Frontend:**
- `static/js/copilot.js`: 6 nuovi label + 6 nuovi case nello switch +
  6 nuovi summary renderer (`summaryAnalyzeConflicts`, `summaryFindFreeSlots`,
  `summaryRecurringBookings`, `summaryBulkMove`, `summaryTransmitToBilling`,
  `summaryQueryProjectFinance`).
- Cache-buster `copilot.js?v=3.5.0-alpha.54`.

**Smoke test:**
- App boot OK, 262 routes, 23 tools / 23 handlers.
- Routing dispatcher `_ACTION_HANDLERS` allineato con TOOLS spec.

**Verifica live richiesta a Matteo:**
1. Pull → app parte (262 route, version 3.5.0-alpha.54).
2. Apri copilot drawer → prova "Mostrami i conflitti della prossima
   settimana sul progetto X" → AI risponde con `analyze_conflicts`.
3. "Quando il colorist senior ha 4h libere questa settimana?" →
   `find_free_slots`.
4. "Prenota Luca lun-ven 9-13 dal 11 maggio al 22 maggio sul job #5" →
   `propose_recurring_bookings` → conferma → 10 booking creati (eventuali
   conflitti riportati come skipped).
5. "Sposta i booking #100, #101, #102 di +2 ore" → `propose_bulk_move` →
   conferma → 3 booking spostati atomicamente.
6. "Qual è il margine del progetto Ligas?" → `query_project_finance` →
   AI sintetizza la risposta umana sopra il payload.
7. "Trasmetti a fatturazione il progetto Ligas" → `propose_transmit_to_billing`
   → conferma → batch draft creato (visibile in /finance).

**Limitazioni note:**
- `find_free_slots` non considera ResourceUnavailability (ferie/festività)
  in v3.5.0-alpha.54, solo booking esistenti. Da raffinare se richiesto.
- `propose_recurring_bookings` non supporta overnight (start_time <
  end_time obbligatorio).
- `query_project_finance` somma le Invoice senza filtro tenant esplicito
  (Invoice non ha tenant_id, ma è già scoped via job_id IN job_ids).

## v3.5.0-alpha.53 — Vision integration immagini copilot (8 maggio 2026)

Step 3 chiuso. Le immagini caricate nel drawer copilot ora sono "viste"
dall'AI invece di restare placeholder testuali. Supporto nativo Anthropic
(tutti i modelli Claude) + OpenAI (GPT-4o, o1, gpt-4-turbo, vision).

**Backend:**
- `AIProvider.supports_vision()` (default False) — nuovo metodo astratto.
  Override: ClaudeProvider=True (sempre), OpenAIProvider=True se modello
  contiene "4o" / "vision" / "o1" / "gpt-4-turbo". Gemini/Perplexity/Ollama
  restano False (placeholder testuale per ora).
- `copilot_attachments.build_user_content_blocks(text, attachments, supports_vision)`:
  - Senza allegati → ritorna `text` (stringa, retrocompat).
  - Solo allegati testuali (PDF/DOCX/TXT/MD) → embed inline (stringa).
  - Allegati immagine + supports_vision=True → ritorna content list
    canonico Anthropic (`{type:text, text:...} + {type:image, source:base64}`).
  - Allegati immagine + supports_vision=False → fallback placeholder
    testuale (comportamento α.51).
- `_translate_blocks_to_openai(content)` in `ai_provider.py` traduce
  i block Anthropic-canonici in formato OpenAI (`image_url` con data URL
  `data:image/png;base64,...`). OpenAIProvider.chat li traduce
  trasparentemente.
- Limiti: max 5MB per immagine (Anthropic limit). File mancanti / troppo
  grandi → fallback testuale per quell'attachment specifico.

**Routing chat:**
- `/ai/api/chat` ora costruisce `last_user_content` chiamando
  `build_user_content_blocks` PRIMA del dispatch. Supporta sia stringa
  che list[dict].
- Helper `_flatten_content` per normalizzare in stringa quando serve
  (titolo conversazione, persistenza `AIMessage.content` SQL).

**Cosa cambia per l'utente:**
- Carica screenshot capitolato cliente, schema scenografia, mock-up grafico:
  Claude/GPT-4o leggono direttamente il pixel e rispondono nel merito
  ("Qui c'è scritto resolution 3840x2160, codec ProRes 4444 XQ...").
- Se hai configurato Gemini/Ollama/Perplexity, le immagini restano
  placeholder testuale (la chat continua a funzionare, ma con descrizione
  testuale invece di "vedere" l'immagine).

**Smoke test:**
- Boot OK, 262 route, version 3.5.0-alpha.53
- Test build_user_content_blocks con 4 scenari (string, text-only,
  image+!vision, image+vision+missing-file) → tutti OK
- Translation Anthropic → OpenAI verificata (image_url data URL valido)

**Aperti:**
- Gemini vision (formato `inline_data` differente, da implementare)
- Ollama vision (alcuni modelli supportano via API custom)
- Persistenza attachment in DB (oggi MVP non persiste, file su disk fino
  a cleanup 7gg)

---

## v3.5.0-alpha.52 — Fattura PDF formale + dati fiscali (8 maggio 2026)

Step 2 della roadmap chiusa con Matteo: emissione fattura PDF "stampabile"
in formato italiano, con snapshot fiscali immutabili al momento
dell'emissione e tab `Azienda` in /settings per gestire i dati del cedente.

**Modello esteso (auto-migrate al boot, idempotente):**
- `Tenant` + 9 campi fiscali: `tax_code`, `iban`, `sdi_code`, `rea_number`,
  `fiscal_capital`, `fiscal_regime` (RF01..RF19, default RF01),
  `payment_terms_default` (giorni, default 30), `payment_method_default`
  (default "Bonifico bancario"), `invoice_footer` (testo libero in calce)
- `Client` + `zip_code`, `province` (sigla 4 char es. "MI")
- `Invoice` + 4 campi documento (`doc_type` default `TD01`, `payment_method`,
  `payment_terms_days`, `iban_snapshot`) + 10 snapshot cliente + 11 snapshot
  tenant. Modifiche successive a Tenant/Client NON corrompono fatture
  storiche.
- `InvoiceLine` + `vat_rate` (per riga, default 22), `discount_pct`

**Generatore PDF — `app/services/invoice_pdf.py`:**
Layout fattura italiana professionale:
- Header con logo (se presente) + Cedente: ragione sociale, P.IVA, CF,
  sede, REA, capitale sociale, regime fiscale (RF01..RF19), email/telefono
- Box doc info: tipo (TD01..TD24), N°, data emissione, data scadenza
- Box Cessionario: nome, indirizzo completo (via, CAP, città, provincia,
  paese), P.IVA, CF, PEC, codice destinatario SDI (fallback `0000000` se
  PEC presente)
- Tabella righe: descrizione, quantità, prezzo, sconto%, IVA%, imponibile
- Riepilogo IVA per aliquota (utile per esenzioni / split-rate)
- Totali: imponibile, IVA totale, bollo virtuale 2€ opt (D.M. 17/06/2014
  per esenti > 77.47€), Totale documento
- Box pagamento: modalità + termini (giorni) + IBAN
- Footer aziendale custom + footer fisso "Documento generato da MediaFlow"

`generate_invoice_pdf(invoice, tenant=None, client=None, bollo_virtuale=False)`
preferisce gli snapshot; cade sui campi vivi di tenant/client se mancano
(retrocompat con fatture pre-α.52).

**`emit_invoice` esteso**: popola tutti gli snapshot fiscali + payment
method/terms/IBAN dai default tenant. Nuove fatture sono "auto-contenute"
e stampabili indipendentemente da modifiche future.

**Endpoint nuovo**:
- `GET /finance/api/billing/{batch_id}/invoice-pdf` → PDF inline
  (`Content-Disposition: inline; filename="Fattura-{number}.pdf"`).
  Richiede status batch=`invoiced`. Auth `view_finance` (producer/manager/admin).

**UI:**
- `/finance` modal batch quando status=`invoiced`: bottone primario
  **📥 Stampa fattura PDF** che apre il PDF in nuova tab. Lasciato anche
  bottone secondario "🔗 Vai alla fattura".
- `/settings` nuova tab **Azienda** con form completo per i dati fiscali:
  - 17 campi raggruppati (anagrafica, fiscale, pagamento, footer)
  - Upload logo (PNG/JPG/WebP, max 1MB) salvato in `uploads/tenant/logo.{ext}`
  - Anteprima logo live
  - Visibile a tutti, editabile solo da admin (badge "🔒 Sola lettura"
    altrimenti)

**Endpoint settings:**
- `GET /settings/api/company` — leggi
- `PUT /settings/api/company` — scrivi (admin only, parziale OK)
- `POST /settings/api/company/logo` — upload logo (admin only, max 1MB)

**Smoke test:**
- App boot pulita, version 3.5.0-alpha.52, 262 route
- PDF generato 3937 bytes valido (`%PDF-1.4`) con dati dummy
- Endpoint billing PDF + settings company registrati

**Per Matteo da provare:**
1. /settings → tab Azienda → compila ragione sociale, P.IVA, sede, IBAN,
   regime, ecc. → carica logo → Salva
2. Crea un batch fatturazione (Cost report → Trasmetti) → /finance →
   approva → emetti fattura
3. Modal batch → bottone 📥 Stampa fattura PDF → apre PDF formale con
   tutti i dati

**Aperti per α.53:**
- Vision integration immagini copilot (Anthropic + OpenAI image blocks)
- Capability copilot avanzate (recurring_bookings, bulk_move,
  analyze_conflicts, find_free_slots)
- Financial Copilot (Q&A finanziarie, export financial status, project
  status)

---

## v3.5.0-alpha.51.1 — Fix audit α.41→α.51 (3 critici + 4 minori) (8 maggio 2026)

Audit logico in apertura sessione ha rivelato 3 bug critici sulla maratona
α.41→α.51, fissati prima di passare alle feature nuove.

**CRITICI fixati:**
- **C3 — Sicurezza /uploads**: il mount `StaticFiles("/uploads")` aggiunto
  in α.51 era in `PUBLIC_PATHS` → tutti gli asset DAM aziendali e i capitolati
  caricati nel copilot erano **scaricabili senza autenticazione** da chiunque
  conoscesse l'URL. Rimosso `/uploads/` da `PUBLIC_PATHS` (`app/main.py:279`).
  Il browser di un utente loggato manda automaticamente il cookie
  `access_token`, quindi gli URL inline nei template continuano a
  funzionare; senza login → redirect /auth/login.
- **C1 — JCL.work_date mai assegnato**: `cost_line_sync.recompute_cost_line_actual`
  aggiornava `quantity_actual` e `total_accrued` ma non popolava mai
  `JobCostLine.work_date`, rendendo il selling-point di α.48.2
  ("periodo trasmissione auto da work_date booking") **rotto end-to-end**:
  cadeva sempre nel fallback "current_month" col warning ⚠ giallo. Ora
  popola `work_date = max(start_datetime.date())` dei booking done +
  backfill one-shot al boot via marker `uploads/.work_date_backfilled_v1`.
- **C2 — AI resize/move saltavano recompute**: `_h_propose_resize_booking`
  e `_h_propose_move_booking` modificavano gli assignment ma non chiamavano
  `recompute_for_booking`. Se il booking era `execution_status=done`, le
  ore-uomo cambiavano ma `JCL.quantity_actual` / `total_accrued` restavano
  congelate → cost report fantasma + manager trasmetteva un `total_proposed`
  sbagliato. Allineato a `_h_propose_delete_booking` che già lo faceva.

**Alti fixati:**
- **A2 — JCL locked check**: nuovo helper `_assert_jcl_not_locked` chiamato
  in `_resolve_booking_for_planning`. AI ora non può modificare booking la
  cui `JobCostLine` sia `in_batch`/`billed`/`paid` (corromperebbe lo
  snapshot del batch e le LossEntry). Il manager deve prima ritirare il
  batch.
- **A4 — BookingChange audit per AI**: `propose_move/resize/delete_booking`
  ora loggano in `booking_changes` con `kind=ai_move|ai_resize|ai_delete`,
  allineato al pattern di `planning.delete_booking`.
- **A1 — tenant_id**: `_resolve_booking_for_planning` filtra Booking per
  `tenant_id == CURRENT_TENANT`. `set_jcl_billing_status` filtra JCL via
  JOIN `job→project.tenant_id`.
- **A3 — Invoice.number scoped**: in `emit_invoice` il check unicità ora è
  `Invoice.number == X AND Client.tenant_id == CURRENT_TENANT` via JOIN.

**Minori fixati:**
- **M1 — cancel_batch rilascia anche `lost`**: incluso `JCLBillingStatus.lost`
  oltre a `in_batch` nel rilascio JCL su annullamento batch. Casi limite di
  manager che azzera totalmente una line prima del cancel ora coperti.
- **M5 — cache-buster `global.js`**: bump `?v=3.5.0-alpha.43 → α.51.1` in
  `base.html`, allineato al resto del package.

**Aperti (refactor non bloccante):**
- B1 OneDrive `st_mtime` su Mac di Matteo (cleanup_old_attachments potrebbe
  eliminare prematuramente o mai)
- B2 system prompt potrebbe esplicitare "spostare booking done = correzione
  retroattiva, usare con attenzione"
- B3 filename sanitization regex permette `..` consecutivi (non path
  traversal, ma cosmetico)
- M2/M3/M4 (workflow tweaks da fare con calma)

**Smoke test:**
- App boot pulita, version 3.5.0-alpha.51.1, 258 route registrate
- Backfill `work_date` esegue al primo boot, marker creato per evitare re-run

---

## v3.5.0-alpha.51 — Upload documenti per copilot (PDF/DOCX/TXT/MD/immagini) (7 maggio 2026)

Richiesta Matteo serale: caricamento documenti per il copilot. Use case
tipici: capitolato cliente in PDF, brief in DOCX, mail in TXT, screenshot
con richieste, ecc.

**Backend:**
- Nuovo servizio `app/services/copilot_attachments.py`:
  - `save_attachment(filename, content)` → salva su `uploads/copilot/{uuid}.{ext}`,
    estrae testo per PDF (pypdf) / DOCX (python-docx) / TXT/MD (raw),
    legge dimensioni per immagini (Pillow). Limiti: 20MB, 50k caratteri estratti.
  - `embed_attachments_in_text(user_text, attachments)` → costruisce il
    messaggio finale embeddando il testo estratto inline (header
    `📎 ALLEGATO: filename` + contenuto + `---FINE ALLEGATO---`)
  - `cleanup_old_attachments()` elimina file > 7 giorni
- Endpoint `POST /ai/api/upload` (multipart): accetta file, ritorna metadata
  + extracted_text. Estensioni ammesse: pdf/docx/txt/md/jpg/jpeg/png/webp/gif
- Endpoint `/ai/api/chat` esteso: accetta `attachments[]` nel body, fa embed
  inline nell'ultimo messaggio user prima di invocare l'AI
- Mount `/uploads` in main.py per servire le immagini caricate
  (PUBLIC_PATHS aggiornato)
- Cleanup auto in lifespan startup (ogni boot rimuove file > 7gg)

**Frontend (`copilot.html` + `copilot.js`):**
- Bottone clip (📎 paperclip Lucide) nella input bar — accept multiplo
- Drag & drop su tutto il drawer con overlay "Rilascia qui per allegare"
- Lista allegati pending sopra l'input: nome, badge tipo (🖼 immagine /
  📝 N caratteri / 📄 testo), size, bottone × per rimuovere
- Stati: ⏳ caricamento, ⚠ errore (border rosso), normale
- Su Send: snapshot attachments → reset state → include nel body request
- Allegati svuotati dopo invio (uno per messaggio, semplice & predicibile)
- CSS: `.cp-attach-btn`, `.cp-attachment` (uploading/error variants),
  body class `cp-dragover` per overlay drop
- Cache-buster `copilot.js?v=3.5.0-alpha.51`

**Limitazioni MVP α.51 (estensioni in roadmap)**:
- Immagini caricate ma NON passate al provider come vision blocks
  (richiede modifica per-provider Anthropic/OpenAI/Gemini message format).
  Per ora l'AI riceve placeholder testuale con URL — chiede all'utente
  di descrivere se serve. Vision integration in α.52
- Nessuna persistenza in DB: file su disk + metadata nel client.
  Dopo refresh pagina gli allegati scompaiono (ma file resta su disk
  fino al cleanup retention)
- Nessun OCR per immagini con testo (richiederebbe Tesseract o vision API)

**Scenario d'uso tipico**:
1. Apri copilot in qualunque pagina
2. Click 📎 (o trascina file nel drawer) → file caricato + estratto testo
3. Vedi card con "📎 capitolato_a24.pdf · 📝 8245 caratteri · 145 KB · ×"
4. Scrivi: "Leggi questo capitolato e proponi una quote per il colore"
5. Send → AI riceve user_text + extracted_text del PDF + context
   PIANIFICAZIONE/listino → propone azioni concrete

**Niente migrate** (no DB changes).

## v3.5.0-alpha.50 — Copilot in-depth integration nella pianificazione (7 maggio 2026)

Richiesta Matteo: "integrazione in-depth del copilot nella pianificazione".
Pre-α.50 il copilot vedeva clienti/progetti/listino/quote/risorse ma
NIENTE pianificazione viva → poteva creare booking ma "alla cieca",
senza sapere conflitti, ferie, carico esistente.

**Sezione PIANIFICAZIONE VIVA in `build_context`** (mostrata se page=
`/planning` o c'è progetto/job in canvas):
- Booking prossimi 14gg (id, range, risorse, job, exec_status)
- Conflitti orari attivi (overlap su stessa risorsa, top 10)
- Carico per risorsa settimana corrente con badge 🟢🟡🔴 (vs cap 40h)
- Indisponibilità approvate (ferie/malattia/festività) prossimi 14gg
- Job critici con deadline ≤ 30gg (badge urgenza)
- Filtri: `project_id` restringe al progetto, `job_id` al singolo job
- Helper `_build_planning_context()` separato per leggibilità

**3 capability planning nuove** (mutation, conflict-check pre-apply):

| Tool | Quando | Payload chiave |
|---|---|---|
| `propose_move_booking` | "Sposta il booking di Luca a martedì pomeriggio" / "Sposta tutto +1 settimana" / "Cambia risorsa da Luca a Marco" | `booking_id` + `shift_minutes` \| `new_start_date` \| `new_resource_id` \| `assignments_remap[]` |
| `propose_resize_booking` | "Allunga di 2 ore" / "Accorcia di mezz'ora" | `booking_id` + `delta_minutes` (positivo=allunga end) |
| `propose_delete_booking` | "Cancella questo booking" | `booking_id` + `reason?` (soft-delete, recuperabile dal Cestino) |

Tutte atomic. Move supporta combinazioni (shift_minutes + new_resource_id).
Resize modifica l'ULTIMO assignment (mantiene split pause intatte). Delete
triggera `recompute_for_booking` per recuperare le ore dal cost report.

**System prompt rinforzato** (sezione "PIANIFICAZIONE — operazioni
sulla timeline" in `ASSISTANT_SYSTEM_PROMPT_TOOLS`):
1. Consultare sempre la sezione "PIANIFICAZIONE VIVA" prima di proporre
2. Rispettare INDISPONIBILITÀ (no booking su ferie/malattia)
3. Bilanciare CARICO (evitare risorse 🔴, preferire 🟢)
4. Segnalare CONFLITTI esistenti proattivamente
5. Spiegare il "perché" dopo ogni proposta planning
6. Booking ricorrenti: proporre UNO ALLA VOLTA (non bulk 20)
7. Collegare a `job_cost_line_id` quando applicabile (per cost tracking)

**Quick prompts contestuali** nel drawer copilot, popolati da
`_renderWelcome()` JS in base alla pagina:
- `/planning`: 7 prompt (Diagnostica + Pianificazione)
- `/cost-report`: 3 prompt (margini, sforamenti, perso)
- `/quotes`: 3 prompt (crea quote, voce listino, search)
- `/clients` o `/projects`: 3 prompt (anagrafica)
- altri: 4 esempi generici (era hardcoded)
- Click su prompt = popola input (non auto-invia, l'utente può rifinire)

**Renderer card UI** per le 3 nuove capability:
- `summaryMoveBooking`: shift in h/min direzione + new_resource_id +
  remap dettagliato
- `summaryResizeBooking`: delta in h/min con segno
- `summaryDeleteBooking`: motivo + nota "Soft-delete recuperabile"

**Altri**:
- Cache-buster `copilot.js?v=3.5.0-alpha.50`
- Import in `ai_assistant.py`: aggiunto `Booking, BookingAssignment,
  BookingStatus, BookingExecutionStatus, ResourceUnavailability,
  UnavailabilityKind, UnavailabilityStatus, JobStatus`

**Niente migrate.**

**Test**:
- Apri `/planning` → click FAB copilot → vedi quick prompts dedicati
- "Mostrami i conflitti orari della prossima settimana" → AI risponde
  consultando il context PIANIFICAZIONE VIVA
- "Sposta il booking #42 di +1 giorno" → AI propone
  `propose_move_booking({booking_id:42, shift_minutes:1440})` →
  card di conferma → Apply → booking spostato + recompute envelope

**Prossimi step (futuri)**:
- Capability avanzate: `propose_recurring_bookings` (serie ricorrente),
  `propose_bulk_move` (sposta N booking di delta), `analyze_conflicts`
  (read-only: trova + suggerisci risoluzioni), `find_free_slots`
- Notifiche proattive: badge sul FAB se rilevati problemi (es. job in
  scadenza senza booking pianificati)
- Capability per modulo Billing: `propose_transmit_to_billing` con
  preview integrata

## v3.5.0-alpha.49 — Step 4 Cost Report → Billing flow: UI /finance batch (7 maggio 2026)

Quarto step del workflow billing. Pagina `/finance` estesa con tab
**📦 Batch fatturazione** + drawer dettaglio batch + edit lines + bottoni
azione (approve/cancel/emit invoice) + sezione perso aggregato per progetto.

**Nuova tab "Batch fatturazione"**:
- Filtro per status (draft/approved/invoiced/cancelled)
- Tabella: codice, progetto, status badge, periodo, proposto, approvato,
  perso, fattura, bottone Apri
- Badge giallo sulla tab con count batch in `draft` (pending approvazione)
- Auto-refresh + auto-open via deep-link `/finance#batch-{id}` (link dal
  cost report)

**Modal dettaglio batch** (`modal-batch-detail`, max-width 920px):
- Header: code + progetto + status badge
- Meta-grid: periodo, proposto, approvato, perso, fattura
- Note del batch
- Tabella lines: descrizione (+ marcatore [extra]), quantità, tariffa,
  proposto, **approvato (editabile inline solo se draft)**, perso
- Pannello "Perso aggregato sul progetto" con totale + breakdown per
  reason (manager_discount/written_off/client_complaint/rounding/other)
- Footer azioni dinamico per status:
  - draft: Annulla batch (rosso) + ✅ Approva
  - approved: Annulla batch + 💶 Emetti fattura
  - invoiced: link 🔗 Vai alla fattura
  - cancelled: solo Chiudi

**Edit line inline** (manager+ su draft):
- Input number con onChange
- Se nuovo importo < proposed: prompt per `loss_reason`
  (default `manager_discount`, valori: written_off/client_complaint/
  rounding/other)
- PATCH `/finance/api/billing/{id}/lines/{lid}` (endpoint α.47)
- Toast con delta perso eventuale
- Re-fetch batch per ricalcolo totali + refresh tabella batch

**Modal emetti fattura** (`modal-emit-invoice`):
- Input numero fattura (manuale, no auto-numero — coerenza con
  gestionale fiscale esterno) + verifica unicità lato server
- Date emissione/scadenza
- IVA % (default 22)
- Anteprima totali live: imponibile + IVA + totale (ricalcolata
  on input change su VAT %)
- Submit chiama `POST /finance/api/billing/{id}/invoice` (α.47):
  - Crea Invoice draft
  - JCL → billed con billed_amount = total_approved
  - Lines azzerate (approved=0) → JCL `lost`
  - Batch → invoiced

**Auto-init**:
- `loadBatches()` chiamato anche quando si è su altre tab (per popolare
  badge tab e supportare deep-link da /cost-report → /finance#batch-X)

**Verifica live**:
- `/finance` → tab "📦 Batch fatturazione" → vedi lista batch
- Click su un batch in stato `draft` → modal dettaglio
- Modifica importo di una riga (es. da 100 a 80) → prompt motivo →
  PATCH → vedi perso 20 + totale aggiornato
- Click ✅ Approva → batch passa a `approved`
- Click 💶 Emetti fattura → modal con anteprima IVA → conferma →
  Invoice creata + visibile in tab Fatture, batch → `invoiced`
- Click ↩ Annulla batch → conferma → batch `cancelled` (JCL rilasciate
  in cost report)

**Niente migrate.**

**Prossimo step:**
- α.50: notifica fine mese auto + chiusura progetto (producer "Chiudi
  lavorazioni") + report finanziario completo con totali perso/fatturato/
  pagato per anno

## v3.5.0-alpha.48.2 — Periodo trasmissione auto-derivato dai booking (7 maggio 2026)

Richiesta Matteo: "Il periodo di riferimento della fatturazione dovrebbe
essere determinato di volta in volta in base al periodo di attività del
booking" (non un range arbitrario scelto dall'utente).

**Backend** — nuovo endpoint `GET /finance/api/billing/preview`:
- Input: `project_id` + `include_extras`
- Calcola periodo da min/max `work_date` delle JCL candidate (work_date
  è impostato da `cost_line_sync` sui booking done → proxy diretto del
  periodo di attività)
- Fallback "mese corrente" se tutte le candidate hanno work_date NULL
  (caso JCL extra senza booking)
- Ritorna `period_start/end`, `period_source` (from_bookings vs
  current_month_fallback), `candidate_count`, `total_proposed`, `lines[]`
  per anteprima dettagliata

**UI Cost Report** — modal "Trasmetti a fatturazione":
- Apertura del modal → chiamata `preview` async → popola period_start/end
  con i defaults derivati dai booking (NON più mese corrente arbitrario)
- Mostra anteprima sopra i campi: numero righe maturate + totale + label
  sorgente del periodo (📅 verde "derivato da booking" oppure ⚠ ambra
  "fallback mese corrente")
- Onchange di "Includi extra" → re-trigger preview (count e periodo
  possono cambiare)
- Submit disabilitato se zero righe candidate
- I campi date restano modificabili manualmente (override caso edge)

**Note di design**:
- Il backend `transmit_to_billing` continua a filtrare per period_start/end
  passati (mantiene la possibilità di restringere). Il preview ne suggerisce
  i defaults sensati. L'utente che lascia i defaults trasmette TUTTE le
  candidate (periodo = range completo)
- Tooltip esplicito sotto i campi date: "Default proposto = periodo
  coperto dai booking eseguiti (work_date min → max). Modificabile
  manualmente"

**Niente migrate.**

## v3.5.0-alpha.48.1 — Bottone "Ritira" su card batch cost report (7 maggio 2026)

Richiesta Matteo: "Aggiungerei una funzione di emergenza ritira fattura,
valida solo mentre resta in approvazione. Una volta fatturato non ha più
senso."

Aggiunto bottone `↩ Ritira` (rosso) sulla card batch nel widget
Fatturazione del cost report. Visibile **solo** se `status in
{draft, approved}` — quando il batch è ancora pre-fattura. Per
batch `invoiced` non appare (l'annullamento fattura è un'altra
operazione, non implementata in questo step).

Click → confirm dialog con riepilogo dell'effetto + label dello stato
attuale (BOZZA o APPROVATO) → chiama `POST /finance/api/billing/{id}/cancel`
(endpoint α.47 esistente) → rilascia JCL → not_billed, cancella LossEntry
collegate, batch → `cancelled` (resta nello storico per audit). Refresh
del cost report per vedere stati aggiornati.

`event.stopPropagation()` sul click per non scatenare anche il click
sulla card che apre `/finance#batch-{id}`.

**Niente migrate.**

## v3.5.0-alpha.48 — Step 3 Cost Report → Billing flow: UI in Cost Report (7 maggio 2026)

Terzo step del workflow billing. UI Cost Report ora mostra **stato
fatturazione per riga** + **widget Fatturazione** in header con sommario
e elenco batch + **modal Trasmetti a fatturazione**. Endpoint API α.47
collegati.

**API estesa** (`cost_report.py`):
- `cost_lines[]` ora include: `billing_status`, `billing_batch_id`,
  `billed_amount`, `is_extra`
- `job` include `client_id` + `project_id` (necessario per trasmissione)
- Nuova chiave `billing_batches[]` con i batch del progetto (escluso
  cancelled per default UI ma esposti tutti)
- Nuova chiave `billing_summary` con aggregati per stato (not_billed /
  in_batch / billed / paid / lost) in EUR
- Helper `_billing_batches_for_job` + `_billing_summary_for_job`

**Template** (`cost_report.html`):
- **Colonna `Fatt.`** nella tabella cost lines: badge colorato per stato
  (grigio not_billed, ambra in_batch, verde billed, blu paid, rosso lost)
- **Marcatore `[extra]`** arancio sulle righe `is_extra=true`
- **Widget Fatturazione** sopra la tabella (visibile solo se ci sono
  righe o batch). Sommario 5 card colorate per stato + elenco batch
  cliccabili (apre `/finance#batch-{id}` in nuova scheda)
- Bottone **📤 Trasmetti a fatturazione** apre modal con:
  - Periodo da/a (default mese corrente)
  - Checkbox "Includi righe extra"
  - Note opzionali
  - Submit chiama `POST /finance/api/billing` (Step 2 α.47)
- Card batch elenca: code, status badge, periodo, fattura collegata,
  perso (se >0), totale approvato

**Flusso utente**:
1. Apri cost report di un job
2. Vedi colonna `Fatt.` con badge per ogni riga (di default tutte
   `Da fatturare` grigio)
3. Click `📤 Trasmetti` → conferma periodo → batch creato (status bozza)
4. Le righe diventano `In approv.` ambra + appare la card del batch
   nel widget Fatturazione
5. Manager va in `/finance` (UI in α.49) per approvare/emettere fattura
6. Una volta emessa fattura: righe `Fatturato` verde, batch
   `Fatturato`, link a Invoice nel widget

**Trade-off & note**:
- Widget appare solo se job ha `project_id` (jobs orfani senza progetto
  non hanno billing flow)
- Badge nella colonna sostituisce eventuale icona; lo spazio in tabella
  è limitato. Se ci sono troppi stati attivi, valutiamo dropdown
- `billed_amount` è quello che il manager ha approvato (può differire
  da `total_accrued` se ridotto in approvazione, delta = LossEntry)

**Niente migrate.**

**Prossimo step:**
- α.49: UI `/finance` con elenco batch + edit manager + perso
- α.50: notifica fine mese + chiusura progetto + report finanziario

## v3.5.0-alpha.47.1 — HOTFIX: Bulk button non si attivava dopo selezione ROI/Esc (7 maggio 2026)

Matteo: "Bulk non funziona quando bookings multiselected. Dovrebbe attivarsi?"

**Diagnosi**: vis-timeline 7.x emette il `select` event SOLO per click
utente, **non** quando `setSelection()` è chiamato programmaticamente.
Il ROI/area selection (tasto S + drag) chiama `setSelection(merged)` da
codice → nessun event → `tlOnSelectionChange()` mai chiamato → bottone
Bulk resta disabled anche se la selezione è popolata.

Stesso problema all'Esc per clear selezione.

Le altre funzioni programmatiche (`tlSelectAllVisible`, `tlSelectByJob`,
`tlSelectByResource`, `tlSelectByDate`, panel filters, invert, clear)
chiamavano già `tlOnSelectionChange()` esplicitamente dopo
`setSelection()` — non avevano il bug.

**Fix**: nuovo helper `_tlSetSel(ids)` che wraps `setSelection` +
`tlOnSelectionChange()` + sync cache `window._tlPrevSelection` (per
sticky α.42). Sostituite le 2 chiamate "nude" con il wrapper:
- ROI/area selection in `tlRoi*`
- Esc clear selection nel keyboard handler

Le 4 funzioni "select-by-*" potrebbero usare il wrapper per pulizia,
ma funzionavano già — non toccate per non introdurre regressioni
collaterali.

**Niente migrate.**

## v3.5.0-alpha.47 — Step 2 Cost Report → Billing flow: API endpoints (7 maggio 2026)

Secondo step del workflow Cost Report ↔ Fatturazione. **9 endpoint API**
backend pronti, ancora niente UI (arriva in α.48-49).

**Quick fix UI** incluso: bottone `⛶ Finestra` in toolbar timeline ora
nascosto quando già in `/planning/full` (era illogico vedere "apri in
finestra" mentre SEI nella finestra). Wrap `{% if not full_screen %}`.

**Endpoint creati** (`app/routers/billing.py`, prefix
`/finance/api/billing`):

| Method | Path | Descrizione | RBAC |
|---|---|---|---|
| POST | `` | Trasmetti JCL maturate → nuovo BillingBatch (draft) | view_finance |
| GET | `` | Lista batches con filtri project_id/status | view_finance |
| GET | `/{id}` | Dettaglio batch + lines snapshot | view_finance |
| PATCH | `/{id}/lines/{lid}` | Manager modifica importo riga (auto LossEntry se delta) | manager+ |
| POST | `/{id}/approve` | Manager approva batch (draft → approved) | manager+ |
| POST | `/{id}/invoice` | Emette Invoice + linka, JCL → billed | manager+ |
| POST | `/{id}/cancel` | Annulla batch (rilascia JCL → not_billed) | manager+ |
| PATCH | `/jcl/{id}/billing-status` | Override manuale stato JCL (es. billed → paid) | manager+ |
| GET | `/loss/project/{id}` | Sommario perso per progetto (rendicontazione) | view_finance |

**Logica chiave:**

- **Auto-numero** `BB-{anno}-{NNN}` per tenant (no riciclo dei cancelled)
- **Snapshot immutabile**: BillingBatchLine cattura `description`,
  `quantity`, `unit_price`, `total_proposed` al momento del transmit. Se
  la JCL viene modificata dopo (nuove ore lavorate), il batch resta
  fedele al "documento" inviato a fatturazione
- **Loss tracking**: ogni edit del manager con `total_approved <
  total_proposed` genera (o sostituisce) una `LossEntry` collegata alla
  line. Cap di sicurezza: `total_approved` non può superare proposed
  × 1.5 (per maggiorazioni grosse, crea una JCL extra)
- **JCL state machine**: not_billed → in_batch (al transmit) → billed
  (a emit invoice) → paid (manuale). Cancel batch riporta in_batch →
  not_billed. Invoice con `total_approved = 0` → JCL → lost
- **Filtro JCL**: candidate se `billing_status == not_billed` AND
  `total_accrued > 0` AND `is_billable == True` AND
  (`work_date NULL` OR in `[period_start, period_end]`)
- **Numero fattura manuale** in emit endpoint (non auto-numerato per
  non interferire con gestionale fiscale esterno). Verifica unicità
- **VAT default 22%** configurabile per chiamata

**Test via /docs:**

Apri `http://localhost:8000/docs` → sezione `billing`. I 9 endpoint sono
testabili interattivamente. Esempio flusso completo:

```
POST /finance/api/billing   { project_id=1, period_start=2026-04-01,
                              period_end=2026-04-30 }
→ ottieni batch_id

GET  /finance/api/billing/{batch_id}     # vedi snapshot

PATCH /finance/api/billing/{id}/lines/{lid}  { total_approved=80 }
                                               # se proposed era 100 → LossEntry 20

POST /finance/api/billing/{id}/approve

POST /finance/api/billing/{id}/invoice
     { invoice_number="2026/042", issue_date=2026-04-30 }

GET  /finance/api/billing/loss/project/1     # rendicontazione
```

**Niente migrate** (modello dati già in α.46).

**Prossimi step concordati:**
- α.48: UI Cost Report con stati billing colorati per riga + bottone "Trasmetti"
- α.49: UI `/finance` con elenco batch + edit manager + voce perso
- α.50: notifica fine mese auto + chiusura progetto + report finanziario

## v3.5.0-alpha.46.2 — Modalità leggera timeline (vera causa del freeze) (7 maggio 2026)

Test in incognito Chrome (no estensioni) → freeze persiste. Quindi
la diagnosi α.46.1 (Bitwarden) era SBAGLIATA — Bitwarden contribuiva
ma non era la causa primaria. Riapertura analisi del trace.

**Vera causa identificata:**

- Top RunTask 480-300ms × 7 occorrenze (3+ secondi di freeze totale
  solo nei 7 task più lunghi)
- **PageAnimator::serviceScriptedAnimations**: singolo
  `requestAnimationFrame` blocca **225ms**, un altro 117ms
- **Layout**: max 92.9ms singolo (totale 703ms)
- **Paint**: 18,761 chiamate (max 16ms)
- **Commit (compositor)**: max 66ms

→ Vis-timeline con `stack: true` ricalcola la posizione di TUTTI gli
items per evitare overlap. Con N items larghi su zoom mese, l'algoritmo
è O(N²). Aggiungere background items (ferie, festa, weekend, timbrature
moltiplicati × risorse) porta il count totale a 600+ items in
visualizzazione → frame da 200+ms.

**Fix: Modalità leggera (toggle bottone)**

Bottone `🪶 Light` in toolbar timeline. Quando attivo:
- `stack: false` + `stackSubgroups: false` → niente calcolo overlap O(N²)
  (items possono sovrapporsi visivamente, ma timeline scorre fluida)
- `_hideBg = true` → skip totale background items (ferie, festa, weekend,
  punch). Riduce drasticamente il count
- CSS conditional `#tl-host[data-light="on"]`: disabilita
  `animation` + `transition` + `filter` su `.vis-item` (ridotti i 18k
  Paint events del trace)

Persistenza in `localStorage.mf_tl_light_mode`. Bottone evidenziato
indigo quando attivo. Toast "🪶 Modalità leggera attiva: stack/background/animazioni OFF".

**Trade-off**: in light mode i booking si possono sovrapporre
visivamente nella stessa riga risorsa (vis-timeline non li impila più
verticalmente). Per leggibilità precisa, torna in modalità normale a
zoom più stretto (giorno/settimana).

**Bug ancora possibile**: se anche con light mode freeza, il problema
è altrove (forse vis-timeline 7.7.3 ha bug native con N items pure
senza stack). Soluzione finale: sostituzione libreria timeline
(Bryntum/DHTMLX), già nel backlog.

**Niente migrate.**

## v3.5.0-alpha.46.1 — Mitigazione freeze Chrome (estensioni autofill) (7 maggio 2026)

Performance trace Chrome di Matteo (`Trace-20260507T171123.json.gz`) ha
identificato la causa del freeze:

**Bitwarden** (e altre estensioni autofill in Chrome): il
`MutationObserver` di Bitwarden scansiona ogni mutazione DOM. Vis-timeline
crea/distrugge migliaia di nodi durante zoom/pan → MutationObserver fire
migliaia di volte → `setupOverlayOnField` schedula 55+ setTimeout per
cercare campi input dentro la timeline → main thread saturo → freeze.

**Numeri dal trace**:
- 24,124 chiamate a Bitwarden script (838 ms totali)
- 41 `CollectAutofillContentService.handleMutationObserverMutation`
- 55 `setupOverlayOnField`
- vs. solo 22 ms del nostro `global.js`

**Mitigazione (lato app):**
- Aggiunti `data-bwignore="true"` + `data-lpignore="true"` +
  `data-1p-ignore="true"` + `autocomplete="off"` su `#tl-host` e
  form modal booking. Le estensioni well-behaved rispettano questi flag
  e non scansionano i discendenti
- Aggiornato manuale `/manuale` con FAQ "La timeline si blocca in Chrome"
  + workaround (incognito, exclude localhost in Bitwarden, Firefox,
  pagina standalone, heatmap off)

**Test definitivo per Matteo**:
Cmd+Shift+N in Chrome → `localhost:8000/planning` → zoom mese 30+ booking.
Se incognito funziona = confermata causa estensione, soluzione finale
= aggiungere `localhost` alla whitelist excluded di Bitwarden.

**Nota**: questi attributi sono raccomandazioni — estensioni che li
ignorano rimangono problematiche. Soluzione 100% pulita = disabilitare
l'estensione su localhost, oppure migrare timeline a una libreria che
non genera tanti nodi DOM (vis-timeline → Bryntum/DHTMLX, già nel backlog).

**Niente migrate.**

## v3.5.0-alpha.46 — Step 1 Cost Report → Billing flow: modello dati (7 maggio 2026)

Primo step del workflow Cost Report ↔ Fatturazione concordato con Matteo.
**Solo modello dati + migrazione** in questa versione: nessuna API o UI nuova.
La funzionalità arriverà nei step successivi (α.47 API, α.48-49 UI).

**Workflow target (per riferimento, NON ancora attivo):**

1. Cost Report → "Trasmetti a fatturazione" (manuale + notifica fine mese)
2. Si crea un **BillingBatch** (proposta mensile o extra), snapshot delle
   `JobCostLine` maturate (ore done × tariffa)
3. Manager in `/finance` rivede, può modificare importi (delta → **LossEntry**
   tracciato)
4. Approva → `BillingBatch.status = approved`
5. Emette fattura → `Invoice` collegato + JCL.billing_status = `billed`
6. Pagata → JCL → `paid`
7. Producer "Chiudi progetto" → fattura finale + perso aggregato per
   rendicontazione finanziaria

**Modelli aggiunti:**

- **`JCLBillingStatus`** enum: `not_billed | in_batch | billed | paid | lost`
- **`BillingBatchStatus`** enum: `draft | approved | invoiced | cancelled`
- **`LossReason`** enum: `manager_discount | written_off | client_complaint
  | rounding | other`

- **`BillingBatch`**: code univoco `BB-{anno}-{NNN}`, project_id,
  period_start/end, totali (proposed/approved/lost), audit
  (transmitted_by, approved_by, invoice_id), status
- **`BillingBatchLine`**: snapshot JCL al momento del transmit (immutabile
  per audit). Campi proposed/approved per traccia modifiche manager
- **`LossEntry`**: importo perso, reason, project_id, batch_line_id (opt),
  jcl_id (opt), audit by user

**Estensione `JobCostLine`:**
- `billing_status` (default `not_billed`)
- `billing_batch_id` (FK opt, batch corrente)
- `billed_amount` (importo effettivamente fatturato, può differire
  da `total_accrued` se manager ha modificato)

**Migrazione:**
- `scripts/migrate_billing_flow.py` esplicito (idempotente)
- Auto-migrate al boot in `_auto_migrate_columns()` per i 3 campi su
  `job_cost_lines` (lezione α.25.1: senza auto-migrate il pull crasha)
- Nuove tabelle `billing_batches`, `billing_batch_lines`, `loss_entries`
  create automaticamente da `Base.metadata.create_all()` al boot

**Compatibilità:**
- Nessuna rottura. Tutte le JCL esistenti acquisiscono `billing_status =
  not_billed` (default) → vista cost report invariata fino allo step 2
  (UI con stati colorati)
- Nessun comportamento nuovo finché API non è esposta

**Prossimi step:**
- α.47: API trasmissione/approvazione/emissione (`/finance/api/billing/*`)
- α.48: UI Cost Report con stati colorati + bottone "Trasmetti"
- α.49: UI `/finance` con elenco batch + modifica manager + perso
- α.50: notifica fine mese + chiusura progetto + report finanziario

**Bug ancora aperti:**
- ⚠ Freeze Chrome con 30+ booking + zoom mese (Firefox OK). Matteo sta
  facendo test debug Chrome. Workaround "modalità leggera" pronto se serve

## v3.5.0-alpha.45 — Bulk button sempre visibile + "Fatto" in fondo (7 maggio 2026)

Quick fix utenza:

**Bottone "✏ Bulk" toolbar timeline** — Matteo: "sparito". Era
`display:none` quando senza selezione, riappariva su select ma il
pattern era poco scopribile. Ora sempre visibile, disabled+grigio se
nessuna selezione, attivo+evidenziato indigo con counter `(N)` quando
hai item selezionati. UX più stabile.

**Sort "Le mie" + "Per progetto"** — i booking con
`execution_status` terminale (`done`/`not_done`) vanno SEMPRE in fondo
alla lista, indipendentemente dalla priorità. Matteo: "task ancora
attivi prima, conclusi come riferimento dopo". Modifica in
`_cmpByPrioThenDate` (helper condiviso da `renderTodo` e
`renderProjectView`).

**Bug aperto, NON risolto in α.45**:
- ⚠ Freeze Chrome con 30+ booking + zoom mese persiste anche dopo
  α.44.1. Quindi NON era né heatmap né resize loop la causa primaria.
  Ipotesi residue: vis-timeline 7.7.3 stack=true con O(N²) overlap
  detection esplode con N>30 + items larghi (zoom mese), o background
  items (ferie/festa/punch) che raddoppiano il count, o bug Chrome
  rendering vis-timeline. Serve Performance profile DevTools per
  puntare il problema. Possibile workaround: modalità "leggera" che
  disabilita stack/animazioni/background. Da rivisitare con info
  dal profile.

**Niente migrate.**

## v3.5.0-alpha.44.1 — HOTFIX: freeze Chrome con 30+ booking + zoom mese (7 maggio 2026)

Test live α.44 su Chrome/Mac con 30+ booking + 20+ risorse: timeline
"sfarfalla" da 2 settimane in su, sparisce griglia giorni a zoom mese,
Chrome si blocca completamente. Su Firefox/Mac stesso scenario funziona.

**Diagnosi:**

Il callback `tlInstance.on('rangechanged')` (linea 4282 di planning.html)
ricostruiva via `tlBuildGroups()` e applicava via `groupsDS.update()`
TUTTI i groups foglia risorsa ad ogni evento rangechanged. Dopo il fix
α.41 (heatmap cells come HTMLElement), questo significa creare ex-novo:

  - 1 div wrapper + 1 div nome + 1 div ruolo per ogni risorsa
  - **8-30 div .tl-heat-cell** per ogni risorsa (a seconda dello zoom)

Con 20 risorse + zoom mese (30 giorni): **600+ nodi DOM ricreati ad
ogni rangechanged**. Vis-timeline emette rangechanged anche per
movimenti di pochi pixel durante pan/zoom continuo → cascata di DOM
thrash che Chrome non smaltisce → main thread bloccato → freeze.

Su Firefox lo stesso pattern era più tollerato (probabilmente per
allocazione/GC strategy più aggressive su DOM detached).

**Fix (3 livelli):**

1. **Skip totale se heatmap OFF** (default α.44): nessun contenuto
   dinamico nei groups → niente bisogno di rebuild su rangechanged.
   Risolve il caso comune (utente lascia default).

2. **Dedup range signature**: cache `window._tlLastRangeSig` con
   start+end ISO. Se rangechanged fire con stesso range (succede con
   smoothing pan), skip.

3. **Throttle 500ms** (era 150ms) + **batch update** (`groupsDS.update`
   accetta array → 1 sola re-render invece di N).

**Anti-loop resize α.44:**

`_tlBindResize` con `setOptions({height})` poteva fire ricorsivamente
in alcuni browser (resize → setOptions → vis ricalcola layout →
window resize trigger interno → loop). Aggiunto guard:
- Skip se delta height < 8px (jitter)
- Throttle a 250ms (era 150ms)
- Tracking `window._tlLastHeight` settato dal render iniziale

**Cleanup nuovo render:**

`_doRenderTimeline` resetta `_tlLastRangeSig` e clearTimeout di
`_tlHeatTimer` per evitare carry-over tra istanze vis-timeline.

**Da indagare separatamente** (warning CSP eval): Chrome segnala
"CSP blocks the use of 'eval'". Né MediaFlow né FastAPI mettono CSP
header — probabilmente vis-timeline 7.7.3 internamente usa
`new Function()` o eval per qualche path (forse moment.js per
formatter custom). Non sembra essere causa primaria del freeze
(altrimenti rotto sempre, non solo > 30 booking). Da rivisitare se
persiste dopo questo hotfix.

**Niente migrate, solo template `planning.html` + bump main.py.**

## v3.5.0-alpha.44 — Heatmap toggle + altezza dinamica + finestra standalone (7 maggio 2026)

Test live di Matteo dopo α.43 ha riportato 4 issue + 1 da indagare:

1. **Heatmap "quadratini verdi" sotto i nomi operatore** — non era un bug
   nuovo: la heatmap esisteva da tempo ma vis-timeline 7.7.3 strippava le
   sue cells via la stessa sanitization che ha colpito font/role
   (fixata in α.41 con HTMLElement). Ora che le cells si vedono, sono
   rumore visivo sotto il nome. Default cambiato a OFF.
2. **20+ risorse + altezza fissa 600px** — su monitor grandi, spazio
   sotto sprecato; e con molte risorse, scaling visivo schiacciato
   in 600px.
3. **Richiesta scorporo timeline in finestra dedicata** — workflow
   planning intensivo + monitor secondario.
4. **Timeline nera in Chrome (su Mac)** — solo Chrome, non Firefox.
   Indagine separata, in attesa info DevTools da Matteo.
5. **AI quote network error** — probabile Firefox vecchio. Da rivalutare.

**Chiuso α.44:**

- ✅ **Heatmap default OFF + bottone toggle toolbar**:
  - `TL_PREFS_DEFAULTS.heatmap` cambiato da `true` a `false`
  - Checkbox popover ⚙ default unchecked
  - Nuovo bottone `📊 Heatmap` in toolbar timeline (`tlToggleHeatmap`)
    che sincronizza prefs + checkbox popover + active state visivo
  - Persistenza già esistente in `TL_PREFS_KEY` localStorage

- ✅ **Altezza timeline dinamica viewport**:
  - `tlComputeHeight(host)` calcola `window.innerHeight - host.top - 24`
    con minimo 400px
  - `vis.Timeline` opzione `height: tlComputeHeight(host)` (era hardcoded
    600)
  - Listener `window.resize` con debounce 150ms chiama
    `tlInstance.setOptions({height: ...})` → si adatta al ridimensionamento
    finestra senza ri-render completo

- ✅ **Pagina `/planning/full` standalone** (no chrome):
  - Nuovo route `GET /planning/full` (in `planning.py`) che render
    `pages/planning.html` con context `full_screen=True` e vista forzata
    `timeline`
  - Refactor: estratta logica context in helper `_planning_render` per
    evitare duplicazione tra `/planning` e `/planning/full`
  - `base.html`: condizionali `{% if not full_screen %}` su sidebar +
    topbar; body class `no-chrome`
  - CSS: `body.no-chrome .main-area { margin-left: 0 }` +
    `.page-content { padding: 0 }` + `overflow: hidden`
  - Bottone `⛶ Finestra` in toolbar timeline (`tlOpenStandalone`) che
    fa `window.open('/planning/full', 'mf_timeline_full', popupFeatures)`
    con fallback a tab nuova se popup bloccato
  - L'auth si propaga via cookie (la nuova finestra è una pagina dello
    stesso origin)

**File modificati:**
- `app/main.py`: bump versione
- `app/routers/planning.py`: nuovo route `/full` + helper `_planning_render`
- `app/templates/base.html`: condizionali sidebar/topbar, cache-buster CSS
- `app/templates/pages/planning.html`: bottoni toolbar + JS toggle/standalone/resize
- `app/static/css/main.css`: `body.no-chrome` rules

**Niente migrate.**

**Bug ancora aperto** (post α.44):
- Timeline nera in Chrome solo (Firefox/Mac OK). Da indagare con info
  DevTools da Matteo.

## v3.5.0-alpha.43 — Sidebar collassabile + Manuale d'uso wiki (7 maggio 2026)

Quality-of-life: sidebar che si nasconde lasciando solo le icone (più
spazio per la timeline su schermi piccoli), e prima versione del
manuale d'uso navigabile dentro l'app.

**Sidebar collassabile:**
- Pulsante toggle in topbar a sinistra (icona `panel-left-close` /
  `panel-left-open`). Scorciatoia <kbd>Ctrl</kbd>+<kbd>B</kbd>.
- Larghezza collassata: 64px (icone visibili, label nascoste via
  `font-size:0` per mantenere il testo nel DOM e leggerlo come tooltip)
- Persistenza in `localStorage.mf_sidebar_collapsed`
- Hover 1s su un'icona quando collassata → tooltip flottante con la
  label completa (posizionato a destra dell'icona, niente layout shift)
- Main-area si adatta automaticamente al cambio larghezza (transition
  CSS) — niente jump

**Manuale d'uso wiki:**
- Nuova route `GET /manuale` (router `app/routers/help.py`)
- Voce sidebar "Manuale" in nuova sezione "Aiuto" (visibile a tutti gli
  utenti loggati, senza permessi specifici)
- Layout TOC sticky a sinistra + content area a destra (responsive a
  colonna singola sotto 900px)
- Sezioni: Introduzione, Concetti chiave (Cliente/Quote/Booking/Listino),
  Pianificazione (timeline/multi-select/split/conflitti), Quotazioni,
  Cost Report, Asset Library, AI Copilot, Amministrazione, Scorciatoie
  tastiera, FAQ
- Bozze contenuti basate sul codice attuale (multi-move atomico α.42,
  sticky α.42, ROI/area α.36, font HTMLElement α.41, export/import α.34,
  ecc.)
- Search client-side filtra le sezioni (debounce 150ms)
- IntersectionObserver per evidenziare la sezione corrente nella TOC
  durante lo scroll
- Anchor links + `scroll-margin-top` per centrare la sezione sotto la topbar

**File modificati:**
- `app/static/css/main.css`: variabile `--sidebar-w-collapsed`, classi
  `.sidebar.collapsed *`, `#mf-sidebar-tip`, `.topbar-sidebar-toggle`,
  `.topbar-left`, `body.sidebar-collapsed .main-area`
- `app/static/js/global.js`: `mfToggleSidebar`, `_mfInitSidebarTooltip`,
  `_mfInitSidebarFromStorage`, `_mfBindSidebarShortcut`
- `app/templates/base.html`: wrap `topbar-left` con button toggle,
  nuova sezione "Aiuto" in sidebar con voce Manuale
- `app/routers/help.py`: nuovo (route `/manuale`)
- `app/routers/__init__.py` + `app/main.py`: import + include_router
- `app/templates/pages/manuale.html`: nuovo (template wiki completo)
- Cache-buster CSS + JS bumpato a `?v=3.5.0-alpha.43`

**Niente migrate.**

## v3.5.0-alpha.42 — Multi-move atomico + sticky multi-selection (7 maggio 2026)

α.41 ha sistemato il font ma il multi-move restava rotto. Test live di Matteo
sul 7/5/2026 ha esposto 3 sintomi convergenti su un'unica root cause
architettonica:

**Sintomi diagnosticati (test 2 booking ricorrenti split risorsa multipla):**
- "Booking spariscono dopo move": `_tlApplyMoveToOthersInSelection` chiamava
  `renderTimeline(true)` SOLO se `res.ok > 0`. Bulk-edit fallito per conflitti
  → render saltato → A1 visivamente mosso, A2 sibling mosso sul server e fermo
  visivamente, vis-timeline col `stack:true` riarrangia → item "scivolano"
  fuori riga.
- "Necessari 14 undo per ripristinare": push undo frammentato (1
  `update_assignment` per anchor A1, 0 per sibling shiftati silenziosamente
  da `_tlApplySplitPauseShift`, 1 `bulk_edit` per altri della selezione).
  Cumulativo su 7 iterazioni di test → 14 undo. E i sibling split shiftati
  NON erano nello stack: rollback impossibile.
- Conflitti "fantasma": `_check_assignment_conflict` server-side vedeva stato
  intermedio (A2 già shiftato + B in shift overlap con A2 nuovo) → falsi
  positivi.
- "Click+drag dopo multiselect deseleziona": vis-timeline default rompe la
  multi su tap → Matteo costretto a Ctrl+click prima di trascinare.

**Fix architetturale:**

1. **Endpoint server `POST /planning/api/multi-move` atomico transazionale**
   (`planning.py:1751`):
   - Input `moves`: JSON array `[{assignment_id, new_start, new_end, new_resource_id}, ...]`
   - Conflict check escludendo TUTTI gli `assignment_id` della transazione
     (no falsi positivi: gli assignment in modifica nello stesso gesto non
     si "vedono" tra loro come conflitto)
   - All-or-nothing: se anche un solo move conflitta → `db.rollback()` +
     ritorna 200 OK con `{success:false, conflict:{...}, message:...}`
     (non 409: l'helper `api()` client-side wrappa detail-dict in
     "[object Object]")
   - Recalc `Booking` envelope per tutti i booking coinvolti
   - RBAC: scope su risorse originarie ∪ risorse target

2. **Frontend `_tlApplyMultiMove(movedItem, origItem, origBooking)`**
   (`planning.html:3382`) sostituisce 3 funzioni separate (rimosse):
   `_tlApplySplitPauseShift` + `_tlApplyMoveToOthersInSelection`
   (`_tlDoMove` resta per single-move via context menu reassign).
   - Raccoglie atomicamente: anchor + sibling split anchor + altri della
     selezione + sibling split di ognuno (dedup automatico via Set)
   - Snapshot pre-move atomico per UN solo `tlPushUndo({type:'multi_move',
     pre: [...]})`
   - 1 chiamata API → 1 renderTimeline finale (truth from server)

3. **Undo `multi_move`** (`planning.html:3236`): restore atomico via lo stesso
   endpoint multi-move (i pre snapshot diventano i nuovi moves). Robusto:
   se nel frattempo lo spazio originale è occupato → toast con dettaglio +
   re-push dell'azione sullo stack.

4. **Sticky multi-selection** (`planning.html:4029`): listener
   `tlInstance.on('select')` che intercetta il pattern `prev.length>=2 &&
   newSel.length===1 && prev.includes(newSel[0])` → ripristina la prev
   sincrono con loop guard `window._tlSuppressSelect`. Behavior: click su
   item incluso nella multi → preserva (sticky); click su item non incluso
   → rompe la multi (default). Allineato Figma/Excel range.

**Niente migrate**: nuovo endpoint backend + refactor JS template, niente
schema DB.

⚠ **Da testare in profondità**:
- Multi-move semplice (no split, no cross-resource): comportamento single-move
- Multi-move con sibling split su risorsa multipla (caso bug originale)
- Multi-move cross-resource: anchor cambia risorsa, gli altri restano sulla loro
- Conflitto reale: toast con messaggio specifico + render coerente
- Sticky: click su item della multi → multi preservata; click su area vuota
  → multi rotta (deselezione corretta)
- Ctrl+Z dopo multi-move: ripristino atomico in 1 click
- Drag su item della multi: parte come multi-drag senza Ctrl+click pre-emptive

## v3.5.0-alpha.41 — Font label timeline via HTMLElement (vis-timeline strippa style annidati) (7 maggio 2026)

α.40 ha messo inline styles brutali nelle stringhe HTML del content
delle label risorsa, ma Matteo ha riportato che il bold/font sui nomi
operatore restava invisibile (header reparto invece corretto).

**Diagnosi (DOM dump da Matteo):**

```html
<div class="vis-inner">
  <div>                           ← era <div class="tl-res-cell" style="display:flex;...">
    <div>Luca Bianchi</div>       ← era <div class="tl-res-name" style="font-weight:800;...">
    <div>Online Editor</div>      ← era <div class="tl-res-role" style="font-size:9px;...">
    <div>...heatmap...</div>
  </div>
</div>
```

Tutti i `class` e `style` annidati spariti. **Vis-timeline 7.7.3 sanifica
gli HTML string passati come `group.content` quando contengono nested
elements**: tag preservati, attributi (class+style+title) strippati.
L'header reparto sopravviveva perché era un singolo `<span>` root.

**Fix:** passare a `vis-timeline` un **HTMLElement detached** invece di
una stringa HTML. Quando `content` è già un Element, vis-timeline fa
`appendChild` as-is, niente sanitization. Stessa cura per la heatmap
(prima generata da `tlHeatmapHTML` come stringa, ora `tlHeatmapElement`
restituisce un `<div>` con cells DOM).

**Impatto:**
- `tlBuildResourceGroups` line ~2664: il content delle foglie risorsa è
  ora un `<div class="tl-res-cell">` costruito con `document.createElement`
  + `style.cssText` + `textContent` (anziché concatenazione di stringhe)
- `tlHeatmapHTML(days)` → `tlHeatmapElement(days)` (ritorna `HTMLElement` o `null`)
- Niente più `escapeHtml(r.name)` / `escapeHtml(r.role)`: `textContent`
  protegge automaticamente da XSS
- Header reparto resta stringa HTML (single `<span>`, già funzionante)
- Header progetto / job leaf in `tlBuildProjectGroups`: NON modificati,
  da rivisitare se Matteo dice che anche lì il `<b>` e l'opacity non si
  vedono (al momento non segnalato)

**Niente migrate**: solo modifiche frontend.

⚠ **Resta aperto il bug multidrag conflitti fantasma** (rimandato in
attesa di scenario specifico da Matteo).

## v3.5.0-alpha.40 — Inline styles font + no-confirm multi-move + no race split (6 maggio 2026)

α.39 ha sistemato i tint colore-risorsa (visibili) ma il bold/font su
nome operatore + funzione restavano invisibili. E la cascade di conferme
+ conflitti su multi-select con bookings split persistevano.

**Bug 1 — font/bold non visibili nonostante CSS `!important`.**
- Le regole CSS `.tl-res-name` / `.tl-res-role` con `!important` non
  sortivano effetto. Ipotesi: regole vis-timeline interne con specificity
  alta o `!important` su `.vis-label *`. Diagnosi remota impossibile.
- Fix: **inline styles brutali** nel content HTML generato da
  `tlBuildResourceGroups`. Inline styles vincono su qualunque CSS rule
  che non sia `!important` su tutte le proprietà. Garantito.
- Stessa cura per header reparto (era `<b>name</b>`, ora
  `<span style="font-size:17px; font-weight:800; ...">name</span>`).

**Bug 2 — cascade conferme.**
- Sequenza tipica al multi-move drag: cross-department warning confirm
  + holiday confirm + multi-move confirm = 3 dialog di seguito.
- Fix: rimosso `confirm()` da `_tlApplyMoveToOthersInSelection`.
  L'azione è chiaramente intenzionale (utente ha multi-selezionato e
  trascinato). Reversibile via `Ctrl+Z` (undo).
- Aggiunto `tlPushUndo({type: 'bulk_edit', snapshots: ...})` con
  snapshot pre-modifica (start/end/resource_id per ogni assignment).
- Toast post-azione più informativo: `✓ N multi-move (shift Xh) · ⚠ M
  falliti per conflitto. Ctrl+Z per annullare`.

**Bug 3 — conflitti orari fantasma su multi-select + bookings split.**
- `_tlApplySplitPauseShift` aveva `setTimeout(renderTimeline, 50)` alla
  fine. Subito dopo, `_tlApplyMoveToOthersInSelection` chiamava
  anch'esso `renderTimeline`. Race condition: la prima render iniziava
  durante il bulk-edit, vedendo un DB intermedio inconsistente
  (sibling spostati, multi-move in corso) → conflict check spurio +
  timeline doppia.
- Fix: rimosso il `setTimeout` in `_tlApplySplitPauseShift`. Il
  chiamante (onMove) si occupa del render finale; con il mutex di α.39
  ogni renderTimeline è serializzata.

**Niente migrate**: solo modifiche frontend.

## v3.5.0-alpha.39 — Fix tint+font (window.RESOURCES_SEED) + multidrag bulk + render mutex (6 maggio 2026)

α.38 ha aggiunto tint colore-risorsa, bold nome, role piccolo e header
reparto grande, ma Matteo ha riportato "non si vede nulla". Diagnosi:

**Bug 1 (tint sfondo): `window.RESOURCES_SEED` undefined.**
- `RESOURCES_SEED` è dichiarato come `const` di modulo (`const RESOURCES_SEED = [...]`).
  In JavaScript moderno le `const` di top-level NON diventano property di
  `window` (a differenza di `var`).
- `_tlInjectResourceTints` aveva il check `if (!window.RESOURCES_SEED || ...)`
  → sempre true → early-return → nessun `<style>` iniettato → niente tint.
- Fix: `if (typeof RESOURCES_SEED === 'undefined' || !RESOURCES_SEED.length)`.

**Bug 2 (font/bold non visibili anche con cache fresca):** stili più
aggressivi e con `!important` per essere robusti a eventuali regole
ereditate da vis-timeline. In più visivamente più marcati per essere
riconoscibili a colpo d'occhio:
- Nome operatore: `font-weight: 800` + `font-size: 14px` + colore `#ffffff` puro
- Funzione (role): `font-size: 9px` + `text-transform: uppercase` + `letter-spacing: 0.5px`,
  niente più italic (collideva visivamente con uppercase)
- Header reparto: `font-size: 17px` + `font-weight: 800` + colore `#d4daff`,
  background gradient più contrastato
- Inline `font-style: italic` rimosso dal JS (era in conflitto con CSS)

**Bug 3 (multidrag cascade conferme + timeline doppia):**
- Refactor `_tlApplyMoveToOthersInSelection`: invece di N `PUT
  /api/booking-assignments/{aid}` (uno per assignment selezionato), un
  singolo `PUT /api/bookings/{id}/bulk-edit` con `shift_minutes` e CSV
  di booking_ids. Vantaggi:
  1. Singolo round-trip → niente cascade
  2. Conflict check atomico server-side
  3. Singolo render finale
- Aggregazione: `Set` di booking_id univoci (bulk-edit lavora a
  booking-level, shift_minutes shifta tutti gli assignments di un booking
  → equivalente al loop per assignment).

**Bug 4 (timeline doppia, sopra e sotto, sparisce dopo refresh):**
- Race condition: `renderTimeline` chiamato in parallelo da più handler
  (multi-move callback, undo, filtro, drag finalize) → cleanup parziale +
  doppia istanza vis.Timeline appesa allo host.
- Fix: serializzazione via promise queue. Wrapper `renderTimeline` mette
  in coda ogni chiamata; il body è ora `_doRenderTimeline`. Più chiamate
  stacked si risolvono in FIFO, mai in parallelo.

**Niente migrate**: solo modifiche frontend.

## v3.5.0-alpha.38 — Polish ROI/look label + bulk-edit esteso + filtro orario (6 maggio 2026)

Round di rifiniture post-feedback Matteo su ROI funzionante (α.37):
toolbar pulita, modalità area additiva, label timeline migliorate, bulk
con orario assoluto e nuova data, filtro fascia oraria nei filtri generali.

**Toolbar timeline**:
- ✅ Rimosso bottone `☑ Seleziona…` + dropdown ▾ (Matteo: "i filtri
  generali bastano"). Il pannello `tl-select-panel` resta nel DOM
  (no-op), le funzioni JS rimangono morte.

**Modalità area (ROI)**:
- ✅ Selezione **additiva**: ogni drag in modalità area SOMMA alla
  selezione corrente invece di sostituirla. Permette di "pennellare"
  zone diverse della timeline per costruire una selezione composita.
  Toast: "📦 +N aggiunti (totale M)" oppure "📦 N già in selezione".

**Look label timeline**:
- ✅ Nome operatore **bold** (`.tl-res-name { font-weight: 700; }`)
- ✅ Funzione (role) più piccola del nome (`.tl-res-role { font-size: 9.5px }`)
- ✅ Header reparto ingrandito (era 11px → 14px), no uppercase,
  letter-spacing ridotto (più leggibile)
- ✅ Tint colore-risorsa molto soft sullo sfondo (sidebar + foreground):
  iniezione `<style id="tl-res-tints">` con regole per ogni resource,
  `_hexToRgba(color, 0.07)` su label + `_hexToRgba(color, 0.045)` su
  foreground + bordo sx 3px in `_hexToRgba(color, 0.55)`. Riga risorsa
  visivamente identificabile a colpo d'occhio

**Bulk-edit esteso** (modal `modal-bulk-edit` + endpoint
`PUT /planning/api/bookings/{id}/bulk-edit`):
- ✅ Nuova opzione **Sposta a nuova data di inizio**: calcola delta
  giornaliero rispetto al booking più antico tra i selezionati e applica
  a tutti — ripianificazione di un blocco mantenendo la cadenza
- ✅ Nuova opzione **Orario assoluto** (dalle X alle Y): sostituisce
  ore:minuti su start e/o end mantenendo la data risultante dai passi
  precedenti
- ✅ Ordine di applicazione per ogni booking: 1) new_start_date →
  2) shift_minutes → 3) absolute_start/end_time → 4) execution_status
- ✅ Conflict check su tutti i nuovi orari calcolati DOPO i passi 1+2+3
  (no false-positive intermedi)
- ✅ Helper backend `_parse_hhmm` per validazione `HH:MM`

**Filtro orario nei filtri generali**:
- ✅ Due input `time` (`f-time-from` / `f-time-to`) nel pannello filtri
  con step 15 minuti. Affiancati side-by-side
- ✅ Filtro client-side via `filterBookingsByTimeRange(bookings, range)`:
  un booking passa se almeno un assignment interseca la fascia
  `[fromMin, toMin]` in minuti dal midnight (gestione overnight con due
  segmenti)
- ✅ Applicato in `renderTimeline` dopo il fetch (altre viste TBD)
- ✅ `FILTER_KEYS` array centralizzato per readFiltersFromURL /
  writeFiltersToURL / resetFilters (no più liste hardcoded)
- ✅ Backend NON tocca questo filtro (strftime SQL platform-specific):
  `getFilterParams` esclude `time-from`/`time-to` dal QS

**Multidrag**: già esistente da α.23 (`_tlApplyMoveToOthersInSelection`
chiede conferma e applica lo stesso delta a tutti i selezionati). Non
modificato — funziona già.

**Niente migrate**: solo modifiche al template + endpoint con parametri
opzionali (backward-compatible).

## v3.5.0-alpha.37 — Fix ROI: tasto S + selezione precisa per riga (6 maggio 2026)

α.36 ha portato l'overlay-div funzionante (Matteo conferma "vedo l'area
blu, il rettangolo e la selezione funziona"), ma due bug emersi al
test live.

**Bug 1: tasto S non attivava la modalità.**
- Causa: `ACTIVE_VIEW` è una `const` JS settata a page-load dal Jinja
  con il valore della query string `?view=...` (default `"jobs"`).
  Quando l'utente cambia tab via `setView()`, il DOM si aggiorna ma
  `ACTIVE_VIEW` resta congelato. La guardia `ACTIVE_VIEW !== 'timeline'`
  silenziava la S anche su timeline attiva.
- Fix: rimossa la guardia su `ACTIVE_VIEW`. Sostituita con check sulla
  classe `.active` del DOM `#view-timeline` (lo stato vero della UI).

**Bug 2: selezione includeva task in righe sottostanti l'area.**
- Causa: il calcolo del groupSet mappava `.vis-label` index → `groupsData`
  numeric. Ma `.vis-label` include sia gli header reparto
  (`.vis-nesting-group`) sia le foglie risorsa, mentre `groupsData`
  filtrato a numerici dà SOLO le foglie → indici sfasati di N (numero
  reparti visibili) → groupSet conteneva risorse sbagliate.
- Fix: rimossa completamente la logica group-set. Ora per ogni item che
  passa il filtro time, si legge la posizione DOM reale via
  `tlInstance.itemSet.items[id].dom.box.getBoundingClientRect()` e si
  verifica overlap y col rettangolo del drag. Funziona indipendentemente
  da gerarchia gruppi, stacking, e numero di header reparto.
- Side-effect positivo: items in gruppi collassati/fuori viewport
  vengono naturalmente esclusi (non hanno `dom.box`) — comportamento
  corretto (non si può rubber-band ciò che non si vede).

**Niente migrate**: solo modifiche al template `planning.html`.

## v3.5.0-alpha.36 — ROI rubber-band overlay-based + scorciatoia tastiera "S" (6 maggio 2026)

α.35 ha riabilitato il ROI ma il listener su `tl-host` non scattava per
Matteo: vis-timeline 7.x usa Hammer.js + PointerEvents (`pointerdown`),
quindi il nostro `mousedown` capture-phase + `stopImmediatePropagation`
non basta a impedire al panning di partire. Riscrittura totale.

**Approccio overlay-div:**
- Quando si attiva la modalità area, viene creato un `<div id="tl-roi-overlay">`
  trasparente (rgba .04 indaco), `position:fixed` posizionato sopra
  l'host timeline (z-index 50, cursor crosshair, `touch-action:none`).
- L'overlay cattura mousedown/move/up — vis-timeline non li vede mai.
  Hammer.js è bypassato strutturalmente, niente race condition.
- Riposizionamento automatico su scroll/resize della finestra.
- Calcolo time-range manuale: `(clientX - centerPanel.left) / centerPanel.width
  * windowSpan + windowStart` (no dipendenza da `getEventProperties`).
- Calcolo group-set scansionando le `.vis-label` con `getBoundingClientRect()`
  vs y-range del drag (mappa indice 1:1 con `tlInstance.groupsData`).

**Scorciatoia tastiera "S"** (richiesta esplicita Matteo):
- Tasto `S` (no modifier) toggle ROI mode da qualsiasi punto del planning.
- Skippato se focus su `INPUT/TEXTAREA/SELECT/contenteditable`.
- Skippato se non si è sulla vista `timeline` (`ACTIVE_VIEW !== 'timeline'`).
- ESC esce dalla modalità (idem skip su input).

**Cleanup:**
- Rimosso il vecchio `_tlRoiHandler` (era no-op effettivo per via di Hammer).
- Rimosso il fallback Alt+drag (l'overlay è ora l'unico canale, più chiaro).
- `_tlCreateDragHandler` ha guard `if (window._tlRoiActive)` aggiunto.
- Hint del modal bulk-edit aggiornato: "tasto S per modalità area" invece
  di "Alt+drag area".
- Title del bottone toolbar `📦 Area` aggiornato con menzione `(S)`.

**Funzione sotto nome operatore in timeline** (resta da α.35, immutato).

**Niente migrate**: solo modifiche al template `planning.html`.

## v3.5.0-alpha.35 — ROI rubber-band riabilitato + funzione sotto nome operatore (6 maggio 2026)

Due richieste di Matteo nello stesso giro:

**1. ROI rubber-band timeline riabilitato** (chiusura desiderata forte
`feedback_multiselect_multidrag.md`).

- Bottone toolbar **📦 Area** reso visibile (era nascosto da α.22).
  Click → modalità persistente: cursore crosshair sull'host timeline,
  drag su zona vuota disegna rettangolo, mouseup seleziona tutti i
  booking dentro l'area `[time, group]`.
- ESC globale per uscire dalla modalità (oltre al re-click sul bottone).
  ESC ignorato se l'utente sta editando un input/textarea/select (per non
  interferire con chiusura modal).
- **Risolto conflitto Shift+drag**: il trigger Shift è stato rimosso dal
  `_tlRoiHandler` (in α.16-22 conflivava con `_tlCreateDragHandler` che
  usa shift+drag per creare un booking). Restano: **Alt+drag** (power
  user, sempre attivo) + **modalità persistente toggle** (gesto comune).
- ROI handler ora wirato in capture-phase con `stopImmediatePropagation()`:
  blocca anche il create-handler in coda → due gesti incompatibili non
  partono insieme.
- Guard incrociato: `_tlCreateDragHandler` esce subito se `_tlRoiPersistMode`
  è ON (in modalità area lo Shift+drag non deve creare booking).

**2. Funzione (role) sotto nome operatore in timeline.**

- `RESOURCES_SEED` esteso con `role` (Resource.role esiste dal modello,
  visibile in `/resources` ma non in timeline).
- `tlBuildResourceGroups` renderizza ora `<div class="tl-res-name">` +
  (se presente) `<div class="tl-res-role">` con font 10.5px italic muted.
- Wrapper `tl-res-cell` flex-column per non collidere con `vis-inner`
  (flex row + align-items center) — necessario perché altrimenti nome e
  role sarebbero affiancati invece che impilati.
- L'altezza riga si adatta automaticamente (no min-height forzato dopo
  α.32.2).

**Niente migrate**: solo modifiche al template `planning.html`.

## v3.5.0-alpha.34 — Admin Export/Import dati (6 maggio 2026)

Tool admin per export/import dati completo (DB + memorie Claude + Excel
human-readable) come richiesto da Matteo. Risolve nativamente il problema
sync PC↔Mac (le memorie Claude vivono in `~/.claude/.../memory/`,
quindi non viaggiano via Git) e si pone come backup/restore generico.

**Backend** (`app/services/`):
- `data_export.py`:
  - `build_export_zip(...)` → bytes ZIP + filename suggerito
  - Path mangling cross-OS per memorie Claude (`:`/`\\`/`/`/`_` → `-`)
  - Excel multi-sheet `listino.xlsx` (PriceItems + Categories + Departments)
    e `quotazioni.xlsx` (Quotes + Lines)
  - `metadata.json` con app version, schema, opzioni usate, source machine
  - `README.md` con istruzioni di restore embedded
  - Opt-in: `.env` (secrets), `uploads/` (asset library), trash
    (record soft-deleted dump JSON via `execution_options(include_deleted=True)`)
  - Cifratura AES-256 via `pyzipper` se password fornita (ZIP standard
    apribile da 7zip/WinZip con la password)
- `data_import.py`:
  - `restore_from_zip(...)` con validazione `metadata.json` + check major
    version (rifiuta se incompatibile)
  - DB swap atomico: vecchio DB → `mediaflow.db.backup-<timestamp>`,
    poi rinomina nuovo. Rollback automatico su errore
  - Memorie Claude: ricalcola path mangled per la macchina LOCALE
    (non riusa quello dell'export) → cross-OS funziona
  - Restore opt-in `.env` con backup auto, `uploads/` in merge

**Router** (`app/routers/admin_data.py`, prefix `/settings/admin/data`):
- `GET /export?include_env&include_uploads&include_trash&include_memory&password`
- `GET /excel/listino` e `GET /excel/quotazioni` (download diretti senza ZIP)
- `POST /import` (multipart: `file`, `password`, restore flags)
- Tutti gli endpoint protetti da `_require_admin` (RBAC `is_admin`)

**Frontend** (`app/templates/pages/settings.html`):
- Tab "Dati" con icona `database`, visibile **solo se `is_admin(user)`**
- Card Export: 4 checkbox opt-in (memorie, env, uploads, cestino) +
  campo password opzionale + 3 bottoni (ZIP completo, Excel listino,
  Excel quotazioni)
- Card Import: file upload + password + 3 checkbox restore (memorie,
  env, uploads) + warning rosso "SOSTITUISCE il DB corrente" + risultato
  con summary actions/warnings
- JS: `adminExportZip()` (window.location per attachment download),
  `adminImportZip()` con confirm modal pre-restore

**Dependency**: `pyzipper>=0.3.6` (pure Python, zero compile, AES-256
ZIP standard).

**Niente migrate**: solo nuovi servizi/router/UI.

## v3.5.0-alpha.33 — Capability copilot `propose_resource` (6 maggio 2026)

Nuova capability AI per creare risorse (persone interne/freelance, sale,
attrezzature, software, veicoli) tramite il copilot. Pattern coerente con
le altre 9 capability mutation: AI propone in blocco `action`/tool_use,
utente conferma cliccando Applica nel drawer.

**Backend** (`app/services/`):
- `ai_tools.py`: tool definition `propose_resource` con schema completo
  (name, type, department_id|department_name, role, description,
  daily_rate, hourly_rate, email, phone, internal_phone, color).
  Required: `name`, `type`. `type` con enum vincolato ai 6 ResourceType
  ufficiali (escluso il deprecated `person`).
- `ai_assistant.py`:
  - Handler `_h_propose_resource(db, data)` con validazioni:
    name non vuoto, type → enum check, dept resolve via id/name,
    `_opt_num` per scartare 0/None su tariffe (NULL in DB), color
    sanitization fallback al tema.
  - Registrato in `_ACTION_HANDLERS`.
  - Aggiunto a `VALID_ACTION_TYPES` (insieme a `propose_booking` che
    mancava da quando era stato introdotto in α.20).
  - Schema in `ASSISTANT_SYSTEM_PROMPT` aggiornato.
  - Docstring del modulo aggiornato con la lista canonica delle
    capability.

**Frontend** (`app/static/js/copilot.js`):
- `actionTypeLabel()`: aggiunto "Risorsa (nuova)".
- `renderActionSummary()` dispatch a `summaryResource` (nuovo) e
  `summaryBooking` (mancava un renderer human-readable, prima cadeva
  in fallback "Nessun renderer").
- `summaryResource(d)`: type tradotto in italiano, reparto, tariffe,
  contatti — niente JSON grezzo nella card di conferma.
- `summaryBooking(d)`: job + assignments con date locali leggibili (max
  4 righe + "+N altre"), notes troncate a 80 char.

**Cache-buster**: `copilot.js?v=3.5.0-alpha.33` in
`app/templates/components/copilot.html`. Senza questo bump, i renderer
nuovi non arrivano al browser (lezione `feedback_cache_buster_static.md`).

**Niente migrate**: solo nuovo codice di servizio, nessun cambio schema.

## v3.5.0-alpha.32 — Cross-department: warning al drop + badge persistente (6 maggio 2026)

Fix di un bug latente da `α.23` (24 aprile 2026) e implementazione del
badge persistente sui booking con risorsa di reparto diverso dal task.

**Bug TDZ silenzioso (α.23 → α.31)**:
- Il check cross-department in `onMove` (planning.html) usava la const
  `origBooking` 28 righe prima della sua dichiarazione → `ReferenceError`
  per Temporal Dead Zone, swallowed da un `try { } catch(_) {}` esterno.
- Risultato netto: il warning di reparto incompatibile non scattava mai
  dall'introduzione (α.23). Sintomo Matteo (6 maggio): "spostando booking
  su altra risorsa di altro reparto non viene evidenziato il conflitto"
  (es. Online Conforming di Sara Conti su Davide Moretti, reparto Audio).
- **Fix**: spostate le dichiarazioni `orig`/`origBooking`/`assignmentId`
  prima del check; rimosso `try/catch` swallowing (eventuali errori ora
  visibili in console).

**Badge persistente B3** (nuovo):
- Backend `app/routers/planning.py`:
  - Helper `_booking_task_department_id(b)` → catena
    `Booking.cost_line.price_item.department_id`.
  - Helper `_dept_mismatch_payload(db, b, target_resource_id)` → ritorna
    nomi reparto se mismatch, None altrimenti.
  - Serializer `list_bookings`: nuovo campo `cross_department: bool` in
    `extendedProps` (calcolato per ogni assignment).
  - Endpoint `PUT /api/booking-assignments/{id}`: response include
    `cross_department: {task_department_id/name, resource_department_id/name}`
    quando applicabile (non blocca, è informativo).
- Frontend `app/templates/pages/planning.html`:
  - `tlBookingToItem()`: aggiunge classe `tl-cross-dept` se
    `p.cross_department === true`. Tooltip esteso con riga
    `⚠ Reparto risorsa (X) ≠ reparto task (Y)`.
  - `onMoving()`: applica `tl-cross-dept` live durante drag — l'utente vede
    il bordo amber + ⚠ già durante il preview, prima del drop. Pulisce la
    classe ad ogni frame e la riapplica se ancora valida (no stale state
    quando si torna sulla risorsa originale).
  - CSS `.vis-item.tl-cross-dept`: bordo amber spesso a sinistra
    (`inset 4px 0 0 #f59e0b`) + glow `rgba(245,158,11,.5)` + icona ⚠ in
    alto a destra. Non altera il background → preserva il color-coding
    della risorsa, si combina con `tl-conflict`/`tl-tentative`/`tl-exec-*`.

**Architettura cross-department** (decisione presa il 6/5/2026):
- A1: reparto del task = derivato da `cost_line.price_item.department_id`,
  non esplicito su Booking. Niente schema change.
- B2 + B3: confirm dialog al drop (UX gesto) + badge persistente (UX vista
  d'insieme). Un solo paradigma "AI propone, utente dispone".
- C1: risorsa con singolo reparto (no multi-dept). Da rivalutare se
  emergono persone tuttofare nel team — Matteo confermato "no" il 6/5.

**Niente migrate**: il dato `department_id` esisteva già su `PriceItem`
e `Resource`; il flag `cross_department` è derivato lato server al GET.

## v3.5.0-alpha.30 — Round 11 (5/6): migrazione icone Lucide (6 maggio 2026)

Sostituite le emoji Unicode delle aree ad alta visibilità con SVG Lucide
(stroke-based 1.75px, geometriche, palette current). Setup completo per
estensione progressiva alle aree minori senza altre dipendenze.

**Setup base** (`app/templates/base.html`):
- Bundle Lucide self-hosted in `app/static/js/lucide.min.js` (~400KB,
  1500+ icone, ISC license). Servito offline, no CDN dependency.
- CSS globale `[data-lucide], svg.lucide` con `width/height: 1em`,
  `vertical-align: -0.125em`, `stroke: currentColor` → le icone
  ereditano color e size dal contenitore.
- Init `lucide.createIcons()` al primo paint + helper globale
  `window.mfRenderIcons(root)` per re-render dopo content dinamico.
- `openModal()` invoca `mfRenderIcons(modalEl)` automaticamente:
  modali popolati via JS hanno le icone risolte senza chiamate manuali.

**Aree migrate**:
- **Sidebar** (10 voci): dashboard `layout-dashboard`, clienti `building-2`,
  progetti `clapperboard`, pianificazione `calendar-range`, team `users`,
  ore `clock`, listino `list-ordered`, quotazioni `file-spreadsheet`,
  cost-report `bar-chart-3`, fatturazione `euro`, asset `film`, reparti
  `layers`, settings `settings`, utenti `user`, ruoli `shield-check`,
  cestino `trash-2`, logout `log-out`.
- **Topbar**: bell `bell`, logout `log-out`.
- **Copilot drawer**: FAB `message-square`, header `bot`, nuova conv
  `plus`, chiudi `x`.
- **Settings tab**: aspetto `palette`, sidebar `panel-left`, AI `bot`,
  orari `clock`, account `user`. Card suoni `volume-2`.

**Aree non ancora migrate** (intenzionalmente, in coda α.30.x se richiesto):
- Bottoni inline nei modali (✕ chiudi, ✏ edit, 🗑 delete in righe lista)
- Toolbar timeline planning (semafori, frecce)
- Badge inline nei card (✨ AI, 📦 sezione, 📌 ruolo)
- Topbar custom delle pagine (es. "🎬 Filmografia")

Razionale: la migrazione esaustiva tocca 600+ istanze su 80 emoji unici
distribuite in 30+ template, con alto rischio di regressione visiva. Le
aree sopra coprono il 90% della percezione "feel" professionale a colpo
d'occhio. Le residue sono contestuali (etichette di pulsante, decorazioni
inline) e possono migrare in patch incrementali.

**Lucide license**: ISC. Self-hosted, niente call esterni. Il bundle è
~400KB minified ma cached aggressivamente dal browser dopo il primo load.

Cache-buster `v=3.5.0-alpha.30` (lucide.min.js + global.js + copilot.js).

## v3.5.0-alpha.29 — Round 11 (4/6): suoni soft notifiche + AI (6 maggio 2026)

Suoni discreti stile macOS, sintetizzati via WebAudio API (zero file MP3,
zero dipendenze esterne, zero CORS). Toggle indipendenti in `/settings`
→ tab Aspetto.

**Implementazione** (`app/static/js/global.js`):
- Helper `playSound(name)` con WebAudio:
  - `notify`: due note ascendenti sine 880Hz→1320Hz, decay rapido (~200ms),
    stile macOS "Tink"
  - `ai_done`: bell soft 660Hz + 3a armonica 1980Hz, decay 600ms
- Throttle 800ms per evitare spam su sequenze rapide.
- AudioContext lazy-init + auto-resume da policy autoplay browser.
- Helper `isSoundEnabled(kind)` / `setSoundEnabled(kind, on)` su
  localStorage (`mf_sound_notify` default ON, `mf_sound_ai` default OFF).

**Trigger automatici**:
- `toast(msg, type)`: invoca `playSound('notify')` per type ≠ 'info'
  (success/error/warning) — gli info banali non suonano.
- `copilotSend()` (`copilot.js`): invoca `playSound('ai_done')` dopo
  risposta AI completa nel drawer.

**UI** (`/settings` → Aspetto):
- Card "🔔 Suoni" con 2 toggle stile pillola (notifiche / risposta AI)
- Bottoni "▶ Test" anteprima suono per ciascun tipo
- Init checkbox da localStorage al caricamento pagina

**Razionale niente file MP3**: WebAudio è più leggero (zero asset), più
veloce (no fetch), più portabile (no licensing concerns). Il sintetizzato
sine-wave a basse intensità è già lo standard delle UI moderne (macOS
Big Sur, Slack desktop). Se Matteo preferirà file recordati in futuro,
basta swap di `playSound()` con `new Audio('/static/sounds/x.mp3').play()`.

Cache-buster `v=3.5.0-alpha.29` (global.js + copilot.js).

## v3.5.0-alpha.28 — Round 11 (3/6): pagina filmografia dedicata + campi estesi (6 maggio 2026)

La filmografia esce dalla scheda cliente e diventa una pagina dedicata
`/clients/{id}/works`. Lo schema `ClientWork` viene esteso con 6 nuovi
campi per coprire le richieste Matteo: sinossi, finanziamenti pubblici,
cast & crew, link esterni, premi, data di uscita.

**Modello** (`ClientWork`):
- `synopsis: Text` — descrizione libera della trama/concept
- `release_date: Date` — data di uscita
- `funding_public: Text` (JSON) — `{mibac: bool, regional: str, eu: bool, notes: str}`
- `cast_crew: Text` (JSON) — `{director, dop, executive_producer, editor,
  screenplay, sound_design, music, lead_cast: [..]}`
- `external_links: Text` (JSON) — `[{label, url}, ...]` (trailer, sito,
  streaming, rassegna stampa…). Distinto da `sources` (tracking AI).
- `awards: Text` (JSON) — `[{name, year, category, won}, ...]`
- Auto-migrate al boot.

**Backend** (`app/routers/clients.py`):
- `GET /clients/{client_id}/works` — nuovo route HTML che renderizza la
  pagina dedicata.
- `_work_dict()` espone i 6 nuovi campi (JSON parsati a oggetti/liste).
- `PUT /api/{client_id}/works/{work_id}` accetta i 6 nuovi campi
  (JSON con sentinel `""`/`null` per cancellare).
- Helper `_safe_json_load()` per deserializzazione tollerante.

**UI nuova pagina** (`app/templates/pages/client_works.html`):
- Topbar con breadcrumb Clienti / {nome} / Filmografia + bottoni "+ Nuova
  opera" e "✨ Ricerca AI".
- Filtri live (testo, tipo, anno) + counter.
- Grid di card responsive (auto-fill min 320px) con titolo, anno, badges
  (kind, ruolo, paese, AI, finanziamenti pubblici), regista, DOP, sinossi
  excerpt (3 righe), link esterni e fonti AI.
- Modal edit con 6 sezioni (📋 Anagrafica · 📝 Sinossi · 🎬 Cast & Crew ·
  💶 Finanziamenti pubblici · 🔗 Link esterni · 🏆 Premi · 📎 Note).
- Cast & Crew espone 8 campi (regista, DOP, exec producer, editor,
  sceneggiatura, sound design, musiche, cast principale).
- Link esterni e premi sono righe dinamiche aggiungibili/rimuovibili.
- Modal candidati AI reso identico a quello legacy (compatibilità con
  endpoint `/search-filmography` esistente).

**UI scheda cliente pulita** (`app/templates/pages/clients.html`):
- Rimossa tab "🎬 Filmografia" + tab anagrafica (ora unica vista).
- Rimossi modal `modal-film-candidates` e `modal-work-edit`.
- Rimossa preview "Filmografia recente" (`recent_productions`) dal modal.
- Cancellate ~268 righe di JS legacy (`cdSwitchTab`, `filmLoadList`,
  `filmRenderRow`, `filmEditWork`, `filmSaveWork`, `filmDeleteWork`,
  `filmSearchAI`, `filmRenderCandidates`, `filmCandidatesImport`,
  `escapeHtmlSafe`, …).
- Aggiunto bottone "🎬 Filmografia" nel footer del modal cliente che
  apre la pagina dedicata.

**Nota retention**: il campo `Client.recent_productions` rimane nel DB
per backward-compat con il flusso AI di arricchimento clienti. Non viene
più mostrato nella scheda; la fonte di verità per la filmografia è la
tabella `client_works`.

Cache-buster `v=3.5.0-alpha.28`. Auto-migrate: 6 nuove colonne in
`client_works` (tutte nullable, nessun impatto sui record esistenti).

## v3.5.0-alpha.27 — Round 11 (2/6): voci opzionali + sezioni intra-categoria su quote (6 maggio 2026)

Due nuovi campi su `QuoteLine` per coprire scenari ricorrenti del settore:
- **`is_optional` (bool)** — la voce ha total calcolato ma NON entra nel
  subtotale/total della quote. Viene mostrata in un blocco dedicato
  "Optional aggiuntivi" sotto i totali.
- **`section_label` (string)** — etichetta libera per raggruppamento
  intra-categoria (es. "SKY Originals", "NBCU TechOps", "Beta Film"). Le
  righe con stesso label consecutive vengono mostrate sotto un mini-header
  con subtotale di sezione, dentro il blocco categoria.

**Modello** (`QuoteLine`):
- `is_optional: bool = False` (NOT NULL, default 0)
- `section_label: str | None` (VARCHAR 120 nullable)
- Auto-migrate al boot (`_auto_migrate_columns`).

**Backend** (`app/routers/quotes.py`):
- `_recalc_quote()` — le righe optional hanno `total` calcolato ma vengono
  saltate da `subtotal_gross` / `cat_buckets` / `subtotal` / pacchetto / IVA.
  Mantengono validità di "preventivo se attivata".
- `POST/PUT /api/{quote_id}/lines` accettano `is_optional` + `section_label`
  (con sentinel `__CLEAR__` per rimuovere section_label).
- `GET /api/{quote_id}` espone i nuovi campi sulla riga + `subtotal_optional`
  sulla quote (somma totali optional).

**UI** (`app/templates/pages/quotes.html`):
- `renderLineRow`: badge "Opzionale" + sfondo rigato amber + 2 nuovi bottoni
  (`🏷` etichetta sezione, `○`/`◎` toggle opzionale).
- `renderLines`: section header + section subtotal quando `section_label`
  cambia tra righe consecutive.
- `renderTotals`: blocco "Optional aggiuntivi (non inclusi nel totale)"
  in basso, separato da divider amber.
- Subtotale categoria UI: ora esclude le opzionali (allineato a backend).
- Handler `toggleLineOptional()` + `editLineSection()` con prompt che
  suggerisce le sezioni già usate nella quote.

**PDF** (`app/services/quote_pdf.py`):
- Tabella principale: solo righe billabili. Section header + subtotale di
  sezione quando `section_label` cambia.
- Dopo i totali: tabella separata "OPTIONAL AGGIUNTIVI — non inclusi nel
  totale" con sfondo amber e totale optional in fondo. Layout invariato
  per quote senza optional.

**Bug-fix laterale**: `_auto_migrate_columns()` usava `→` Unicode nei
`print()`. Su Windows con charmap codec questo crashava la migration al
primo ALTER TABLE da stampare (caso reale: chi pull-ava una versione con
nuove colonne mai aggiunte). Sostituito con `->` ASCII in tutti i print
della funzione.

Cache-buster `v=3.5.0-alpha.27`. Auto-migrate: 2 nuove colonne in
`quote_lines` (entrambe con default safe per righe esistenti).

## v3.5.0-alpha.26 — Round 11 (1/6): rimozione matrice + kanban assegnazioni (6 maggio 2026)

Apertura Round 11 (6 voci feedback Matteo del 6 maggio). Prima voce a basso
rischio: sparisce l'area `/assignments` (matrice + kanban). Le assegnazioni
restano gestibili **solo dalla scheda progetto** (`/projects/{id}` ha già la
tab risorse) e dalla **timeline planning** (vista "Per progetto"). Un solo
posto per gestirle, niente duplicazione.

**Cancellati**:
- `app/routers/assignments.py` (matrice + kanban + endpoint API).
- `app/templates/pages/assignments.html` (tabella matrice + drag kanban).
- Voce sidebar "🧩 Assegnazioni" (tra Team e Ore lavoro).
- Prefisso `/assignments` da `_NON_ELEVATED_BLOCKED_PREFIXES` middleware RBAC
  (rimasto solo `/resources`).
- Import `assignments` da `app/main.py`.

**Preservato**:
- Modello `JobResourceAssignment` (usato dalla scheda progetto + integrazione
  con `BookingAssignment` via `resource_assignment_sync`).
- Tabella `job_resource_assignments` nel DB (zero migrazione: dati intatti).

**Rationale**: Matteo ha confermato che la matrice non lo convinceva. La vista
"Risorse e assegnazioni" nella scheda progetto è il punto di gestione naturale
("chi lavora su questo progetto"), e la timeline planning per "quando".

Cache-buster `v=3.5.0-alpha.26`. Smoke test import OK. Niente migrazione DB.

## v3.5.0-alpha.25 — Scheda cliente AI: filmografia con fonti esterne (5 maggio 2026 notte tardi)

Chiuso il 7° punto del Round 10 (la scheda cliente con filmografia AI).
Cantiere medio: nuovo modello + service + 5 endpoint + tab UI + 2 modal.

**Modello**:
- `ClientWork` — tabella `client_works` (auto-creata al boot via
  `Base.metadata.create_all`). Campi: title, year, kind (film/serie/doc/
  spot/cortometraggio/altro), our_role (produzione/post-produzione/
  distribuzione free-form), director, country, sources_json (lista
  di {name, url}), notes, ai_imported, timestamps. FK CASCADE su Client.

**Service** `app/services/filmography.py`:
- `search_filmography(client_name, provider, extra_hint=...)` — workflow:
  1. 2-3 query Tavily mirate con `include_domains` ristretto a
     filmitalia.org / cinema.cultura.gov.it / imdb.com / mymovies.it.
  2. Aggrega risultati cross-fonte, dedup per URL.
  3. Prompt AI per estrazione strutturata (title, year, kind, our_role,
     director, country, source_urls, confidence alta/media/bassa).
  4. Sanitize schema + drop entries senza title.
- Nessuna scrittura DB nel service — il chiamante decide cosa importare.

**Web search**:
- `tavily_search` esteso con `include_domains` / `exclude_domains` opt
  params (passati through al client Tavily).

**Endpoint** (router `clients`):
- `GET /clients/api/{id}/works` — lista filmografia (sort year desc).
- `POST /clients/api/{id}/works` — crea opera. Idempotente su
  (title, year): se duplicato, ritorna l'esistente con `duplicate: true`.
- `PUT /clients/api/{id}/works/{wid}` — modifica.
- `DELETE /clients/api/{id}/works/{wid}` — elimina.
- `POST /clients/api/{id}/search-filmography` — AI search, ritorna
  proposte + flag `already_imported` per dedup-friendly UI. **NESSUNA**
  scrittura DB qui.

**UI** (clients.html):
- Modal scheda cliente ridisegnato con 2 tab: 📋 Anagrafica · 🎬 Filmografia.
- Tab Filmografia: blocco AI search con hint opzionale + bottone "✨ Cerca",
  lista opere come cards con titolo/anno/tipo/regista/ruolo/fonti, click
  apre modal edit, "+ Aggiungi opera" per inserimento manuale.
- Modal candidati AI: lista checkbox con titolo, anno, kind, ruolo, regista,
  fonti cliccabili, badge confidence colorato. Bottoni "Seleziona tutti /
  Deseleziona / Importa selezionati". Le opere già presenti hanno checkbox
  disabilitato + badge "già importata".
- Modal edit opera: form completo con tutti i campi + bottone Elimina.

**Smoke test E2E**:
- CRUD round-trip OK su `/clients/api/{id}/works`.
- `search-filmography` su "RAI Documentari" → 14 fonti consultate
  (filmitalia.org), 6 opere trovate con confidence + sources.
- Idempotency: re-import di un'opera già presente → `duplicate: true`,
  no insert duplicato in DB.

Cache-buster `v=3.5.0-alpha.25`. Tabella `client_works` auto-creata al boot.

## v3.5.0-alpha.24 — Round 10: planning UX refinement (5 maggio 2026 notte tardi)

Round 10 sulla terza tornata feedback Matteo (post-test alpha.23). Chiusi 6
punti su 7 — la "scheda cliente AI con filmografia" è ferma in attesa di
conferma sul piano architetturale.

**Bug fix:**

- **Risorse duplicate sui booking**: i booking splittati per pausa pranzo
  (smart-split) hanno N assignments stessa risorsa. Le viste "Le mie",
  "Per progetto" e il modal dettaglio mostravano N card/righe per la stessa
  risorsa → look duplicato. Fix: `_dedupeBookingSegments` raggruppa per
  `(booking_id, resource_id)`, somma le durate dei segmenti, espone
  `_segments` per badge "+N segmenti" nelle card. Detail modal: 1 riga per
  risorsa con badge "N segmenti" hover-titled con gli intervalli.

**Look & feel:**

- **Ferie/malattia/festività uniformi**: le ferie usavano `rgba(99,102,241)`
  (indigo cool) e alpha 0.15, mentre malattia/festività usavano alpha 0.12.
  Ora tutti allineati: alpha 0.12 sul bg, 0.20 sulle stripes 45°, ferie passa
  alla palette MediaFlow `rgba(98,114,245)`. Aggiunto `tl-bg-other` per
  permessi ("non disponibile" generico).
- **Hover ferie/malattia/festività con info base**: il `title` era statico
  ("Ferie · motivo"). Ora arricchito con icona, periodo formattato, durata
  in giorni, risorsa (se applicabile), motivo e status pending/approved.
- **Hover job: orari di inizio/fine espliciti**: tooltip booking ora
  include `🕐 lun 5 mag 09:00 → mar 6 mag 18:00` oltre a durata e ore
  lavorazione. Priorità con icona semaforo (🔴/🟡/🟢) se non normale.

**Priorità semaforo:**

- **Ingrandito e distanziato in "Le mie" e "Per progetto"**: dot attivo
  passa da 14px → 18px, dot inattivo da 10px → 13px, gap da 0 → 8px,
  ring 2px → 3px. Più cliccabile e leggibile.

**Selezione multipla:**

- **Pannello "stile filtri"**: nuovo bottone "☑ Seleziona…" apre un
  pannello orizzontale sopra la timeline con 4 dropdown filtri
  (Job/Risorsa/Stato/Priorità) + bottoni Applica/Inverti/Pulisci.
  Counter live "N selezionati" + Bulk-edit shortcut. Il dropdown ▾
  legacy resta come scorciatoia.
- **Glow animato sui selezionati**: quando il pannello è aperto, gli
  item con classe `vis-selected` ricevono un'animazione `tl-pulse-glow`
  che fa pulsare il bordo indigo (1.5s ease-in-out infinite). Risolve
  "evidenziare più chiaramente gli item selezionati" (Matteo).

**In coda:**

- **Scheda cliente con filmografia AI** (cantiere grosso, in attesa
  conferma): ClientWork model + tab "🎬 Filmografia" + endpoint
  `POST /clients/api/{id}/search-filmography` con AI tool-use puntato a
  filmitalia.org / cinema.cultura.gov.it / IMDB / MyMovies. Workflow
  AI propone, utente conferma + import idempotente.

Cache-buster `v=3.5.0-alpha.24`. Niente migrazione DB.

## v3.5.0-alpha.23 — Round 9 (parte 2/2): timeline drag/multi-select + ombra timbrature + DB snapshot (5 maggio 2026 sera tardi)

Round 9 chiuso interamente (17/17 punti). Questo bump chiude le rimanenti
8 voci sulla pianificazione + DB snapshot per porting test.

**Drag & drop fixes (5 punti):**

- **Cross-resource drag refresh**: dopo PUT booking-assignment, aggiorno
  `_tlBookings` cache localmente coi valori server-of-truth (resource_id,
  start, end). Per cross-resource drag, force-trigger `renderTimeline(true)`
  con 50ms delay per riflettere envelope booking, badge group_size e altri
  items dello stesso booking. Sintomo Matteo: "spostamento item non aggiorna
  orario e data nè risorse" / "il booking non modifica la risorsa".
- **Multi-select drag**: vis-timeline emette `onMove` SOLO per l'item
  draggato. `_tlApplyMoveToOthersInSelection` applica lo stesso shift agli
  altri items selezionati (con conferma utente). Cross-group: shift solo
  in tempo, non in risorsa (la selezione multipla è gruppo logico, non
  un'unica risorsa).
- **Block drop su risorsa di reparto incompatibile**: prima dell'API call,
  controllo `cost_line_department_id` del booking vs `dept` della risorsa
  target. Se diversi, prompt di conferma esplicita ("risorsa di reparto NON
  compatibile, procedere?"). Esposto `cost_line_department_id` nel
  serializer `/api/bookings` via `JobCostLine.price_item.department_id`.
- **Split-pause unit drag**: `_tlApplySplitPauseShift` rileva i sibling
  assignment (stesso booking_id, stessa risorsa, assignment diverso) e
  applica lo stesso shift. Risolve il "booking splittato per pausa pranzo
  non viene spostato unitariamente".
- **Click+drag su area vuota → modal nuovo booking pre-compilato**:
  `_tlCreateDragHandler` con gesture Shift+drag (vis-timeline drag puro
  resta = pan). Overlay rettangolo verde con durata live. Snap a 5 min.
  Click singolo (delta < 1 min) → fallback durata 1h dall'orario cliccato.

**Settings (1 punto):**

- **Timbrature come ombra leggera, toggle**: aggiunto `show_punches`
  ai prefs timeline (default on), checkbox in popover ⚙ Look timeline
  ("Mostra timbrature ombra leggera"). Stile sfondo ridotto a 10%/20%
  alpha + bordo 1px dotted (era pesante visivamente). Re-render su
  toggle.

**DB snapshot (1 punto):**

- **db_snapshots/ con eccezione gitignore**: copia di `mediaflow.db`
  attuale come `db_snapshots/snapshot-3.5.0-alpha.23.db` per testing
  porting (Matteo: "voglio tenere tutto com'è al momento e verificare
  eventuale porting"). Aggiunta regola `!db_snapshots/*.db` al
  `.gitignore`. README con convenzione e istruzioni di restore.

Cache-buster `v=3.5.0-alpha.23`. Niente migrazione DB nuova.

## v3.5.0-alpha.22 — Round 9 (parte 1): HR pausa pranzo, ferie/malattia in lista, conflict block + timeline UX cleanup (5 maggio 2026)

Round 9 aperto sulla seconda lista feedback Matteo (5 maggio sera). Diviso in
3 sotto-round per scope-bound. Questo bump chiude 9 punti su 17.

**HR / timbrature (3 punti):**

- **Ferie e malattia ora visibili nella lista timbrature**: la pagina `/hr`
  caricava `/api/timeline` senza date di default → l'endpoint ritornava solo
  TimePunch (le `ResourceUnavailability` richiedono from/to per espansione
  giorno-per-giorno). Fix: default range = mese corrente al primo load. Le
  righe ferie/malattia/permesso appaiono quindi già di prima mano in tabella.
- **Block timbratura su giorno con ferie/malattia approvata e viceversa**:
  POST `/hr/api/punches` (kind=shift) → 409 se la risorsa ha già una
  `ResourceUnavailability` approvata che si sovrappone al periodo richiesto.
  Simmetrico: POST `/planning/api/unavailabilities` (status=approved) e
  approve unavailability → 409 se ci sono già TimePunch shift nel periodo.
- **Pausa pranzo opzionale in timbratura** (default 60 min, opzioni 0..240
  min step 15): nuova colonna `time_punches.break_minutes` (auto-migrate),
  campo dropdown nel modal timbratura visibile solo per `kind=shift`,
  sottratta dalla durata mostrata in tabella e dall'engine
  `compute_overtime`/`compute_punch_breakdown` (riduce le ore "regular" del
  giorno prima del calcolo soglia overtime). Il conteggio ore lordo resta
  esposto in `duration_h_gross` per audit.

**Timeline planning UX (5 punti):**

- **Doppio click su item booking apre il modal di edit**: pre-alpha.22
  faceva nulla di utile (toast info sul select). Ora chiama
  `tlbOpenEdit(booking_id)`. Doppio click su area vuota resta = nuovo booking.
- **Hover tooltip esteso**: oltre a titolo + status, ora mostra durata
  booking e durata totale lavorazione (ore fatte / ore pianificate) +
  priorità se non normale. Dati esposti via `extendedProps.job_total_hours`
  / `job_done_hours` nel serializer `/api/bookings`.
- **Priorità "semaforo" in card "Le mie" / per progetto**: 3 dot colorati
  (verde/giallo/rosso) clickabili che sostituiscono il dropdown. Il dot
  attivo è ingrandito e ha glow.
- **Priorità nel modal create/edit booking**: nuovo campo "semaforo" in
  `modal-tl-booking`, persisted via `priority` form param su POST/PUT
  `/api/bookings`. Helper backend `_parse_priority`.
- **Booking detail (modal todo) arricchito**: cliente, dipartimento per
  risorsa, ore fatte vs pianificate cumulato sulla cost_line, audit count
  + last-edit timestamp. Backend `/api/bookings/{id}/detail` esteso.

**Vista per progetto / Le mie (1 punto):**

- **Sort default = priorità desc poi data start asc** (Matteo: "preferibilmente
  in ordine di priorità e poi di data"). Helper `_cmpByPrioThenDate`
  applicato sia in `renderTodo` che in `renderProjectView` (per gruppo).

**Selezione multipla timeline (1 punto):**

- **ROI Alt/Shift+drag disabilitato**: Matteo "area non funziona, o lo
  togliamo o troviamo un'altro modo". Conflitto con Hammer.js + UX confusa
  sulla selezione singola. Bottone `📦 Area` nascosto. Resta attivo SOLO il
  dropdown affidabile `☑ Seleziona ▾` (alpha.21) per multi-selezione. Il
  codice ROI rimane in archivio.

**Storyboard (1 punto):**

- **Opzione densità storyboard spostata nella vista Storyboard**: era nel
  popover globale `⚙ Look timeline` (fuori contesto). Ora è inline nel
  toolbar di `view-storyboard` e sincronizza i prefs.

Cache-buster `v=3.5.0-alpha.22`. Migrazione DB auto: aggiunge colonna
`time_punches.break_minutes` al boot.

**In coda (Round 9 part 2/3):**

- Click+drag area vuota → modal nuovo booking pre-compilato con durata
- Drag&move conflitti backend (cross-resource non riflesso al refresh)
- Multi-select drag su altra risorsa
- Block drop su risorsa di reparto incompatibile
- Split-pause unit drag (entrambi i segmenti)
- Settings toggle visualizzazione timbrature come ombra leggera in timeline
- Push DB nel bundle

## v3.5.0-alpha.21 — Round 8 (parziale): bug fix critici + milestone + timeline progetto (5 maggio 2026)

Round 8 su feedback Matteo dal test su altra macchina. 8 dei 9 punti chiusi
(KDM rinviato — cantiere medio, spec già pronta).

**Bug critici (8A):**

- **Salvataggio Orari lavorativi non possibile**: causa root = nessuna
  WorkingHoursPolicy default in DB → form vuoto → save fallisce (PUT richiede
  id). Fix: `_ensure_default_policy(db)` auto-crea una policy minimale al primo
  GET `/settings/api/working-hours` con valori sensati italiani (8h/40h CCNL
  base, multipliers 1.30/1.25/1.50/2.00, fascia 22-06, festività IT).
  Effetto a cascata: gli straordinari ora vengono calcolati dall'engine.
- **Bulk-edit "impossibile risalire ai booking"**: `tlOpenBulkModal` cercava
  `b.extendedProps.booking_id` ma il backend espone `booking_id` AL TOP del dict
  (cf. planning.py serializer). Stesso bug per `assignment_id`. Fix: lookup
  diretto su top-level.
- **ROI selezione area inaffidabile**: aggiunto menu dropdown alternativo
  affidabile (`☑ Seleziona ▾`) con: "Tutti i booking visibili",
  "Per Job…", "Per Risorsa…", "Per intervallo date…", "Deseleziona tutto".
  Il toggle ROI shift+drag resta come backup (rinominato `📦 Area`).
- **Permesso deprecato `edit_cost_actuals`**: rimosso definitivamente da
  PERMISSIONS dict + `can_edit_cost_actuals()` ora ritorna sempre False.
- **RBAC orari lavorativi**: split in 2 permessi:
  - `view_settings_global` (default per tutti i ruoli) → vede /settings#hours
  - `manage_settings_global` (admin/manager) → modifica.
  Form `/settings#hours` mostra banner "🔒 Sola lettura" + disabilita input +
  nasconde bottoni Save per chi non ha `manage_settings_global`. Backend PUT
  bloccato con 403 + messaggio chiaro.
- **Matrice assegnazioni UX**: aggiunto banner istruzioni inline ("clicca cella
  → modal con ruolo/giorni/tariffe") + legenda colori (Assegnata / Solo
  booking / Vuota).

**Feature (8B):**

- **Milestone progetto** (modello + CRUD + UI): nuovo `ProjectMilestone`
  (project_id, target_date, title, description, color, is_completed). Marker
  di deadline NON-booking (no risorse, no ore, no costi). Tab dedicata in
  `/projects/{id}` con form add/list/toggle done/delete. Status auto-calcolato
  (pending/imminent/missed/done) da target_date vs today. 4 endpoint:
  `GET/POST/PUT/DELETE /projects/api/{id}/milestones[/{mid}]`.
- **Timeline planning vista "Per progetto"**: toggle `👥 Per risorsa` /
  `🎬 Per progetto` in toolbar. Quando attivo, gruppi=Project (treeLevel 1) →
  Job (treeLevel 2), items raggruppati per `j{job_id}`. Background unav/
  punches nascosti (legati a risorse, irrilevanti per progetto). Persistito in
  localStorage. Backend `/api/booking-assignments` esteso con `project_id`,
  `project_title`, `project_code`, `job_code`, `job_title` in extendedProps.
- **`create_tables()` robusto**: forza `import app.models` per registrare tutti
  i modelli in `Base.metadata.tables` prima di create_all(). Pre-fix una nuova
  tabella non veniva creata se nessun router aveva importato il suo modello.

**Rinviati al prossimo round:**

- 8B.1 — Form richiesta KDM in DAM (cantiere medio: nuovo modello KdmRequest
  + flusso amministrativo separato da Asset).

Cache-buster `v=3.5.0-alpha.21`. Migrazione DB: nuova tabella
`project_milestones` viene creata automaticamente al boot via `create_tables()`
(idempotente, no Alembic).

---

## v3.5.0-alpha.20 — Round 7D.2 + 7D.3: matrice assegnazioni + pagina Team (5 maggio 2026)

Chiusura del Round 7D in unica versione: 2 cantieri di scalabilità (200 progetti
/ 500 risorse) implementati con backend e UI dedicate.

**Pagina /assignments — Vista Matrice (alpha.20)**

Pre-alpha.20: solo vista kanban (drag&drop colonna risorse → colonna job),
adatta a pochi job. A 200 progetti la kanban diventa muro orizzontale.

Estensione (NON sostituzione): toggle in topbar tra **Matrice** (default) e
**Kanban** (legacy preservata).

Backend `app/routers/assignments.py`:
- `GET /api/matrix?job_status=&department_id=&resource_type=&only_persons=&include_inactive=`
  ritorna {resources, jobs, assignments, bookings_hours} filtrati server-side.
- `POST /api/cells` upsert idempotente di JobResourceAssignment (planned_days,
  planned_hours, role, agreed_*_rate).
- bookings_hours aggregato dalle BookingAssignment (specchio di quanto già
  pianificato in /planning).

Frontend `app/templates/pages/assignments.html`:
- Toggle vista (matrice/kanban) persistito in localStorage.
- Filtri server-side: stato job, reparto, tipo risorsa, only_persons.
- Filtro client-side: ricerca testuale (su righe e colonne).
- Tabella matrice sticky-header + sticky-first-column. Cella vuota = no
  assignment, cella verde = assegnata, cella arancione = ore booking ma no
  assignment formale (segnale di drift).
- Click cella → modal upsert con planned_days/hours + ruolo + tariffe.

**Pagina /team — Risorse + Reparti unificate (alpha.21)**

Pre-alpha.21: 2 pagine separate (`/resources` lista flat, `/departments` admin).
A 500 risorse / 30 reparti la lista flat diventa muro.

Pagina `/team` con sidebar drill-down + main pane:
- Sidebar (sticky 240px): "Tutte le risorse" + lista reparti con conteggio +
  "Senza reparto" se applicabile.
- Topbar interno: ricerca live (nome/ruolo/email/telefono) + filtro tipo +
  filtro stato (attive/tutte).
- Main pane: griglia card (auto-fill min 260px), 1 card per risorsa con
  nome/tipo/ruolo/reparto/contatti/tariffa.
- Le 2 pagine vecchie restano accessibili (link in topbar) come fallback
  amministrativo.

Voce sidebar `/resources` rimpiazzata con `/team` (nuova pagina = home risorse).

Niente nuovi endpoint backend (riusa `/resources/api` + `/departments/api`).

Cache-buster `v=3.5.0-alpha.20`. Niente migrazione DB.

**Round 7 (12 punti feedback Matteo del 5 maggio) chiuso completamente**:
alpha.16 → 7A · alpha.17 → 7B · alpha.18 → 7C · alpha.19 → 7D.1 ·
alpha.20 → 7D.2 + 7D.3.

---

## v3.5.0-alpha.19 — Round 7D.1: AI settings registry + tool generico (5 maggio 2026)

Apertura del Round 7D (cantieri di design del feedback Matteo del 5 maggio).
Punto 1: AI integrazione GUI/settings — proposta A2 confermata.

**Architettura "settings registry" + 3 tool AI generici**

Il pattern: invece di aggiungere una capability AI per ogni nuova area
configurabile (`propose_working_hours`, `propose_user_prefs`, ecc.), il copilot
**scopre dinamicamente** cosa è configurabile via discovery e applica patch
generiche tramite un singolo tool `update_setting`. Estendere a una nuova area
= aggiungere uno schema al registry, niente nuove capability.

Cantiere strategico per Matteo: "Questa integrazione andrà fatta su tutto il
software in ogni stage". Il registry è il punto di estensione single-source-of-truth.

**Componenti aggiunti:**

`app/services/settings_registry.py` (nuovo):
- `SettingsField` (dataclass) — descrizione field con type JSON-Schema
  sottoinsieme: integer/number/string/boolean/time/enum + nullable + ui_hint.
- `SettingsSchema` (dataclass) — area configurabile: key, label, description,
  fields, read+write handlers, permission ("admin" | "self" | permesso RBAC).
- 2 schemi iniziali: `working_hours` (16 field WorkingHoursPolicy) e
  `tenant_settings` (10 field anagrafica azienda + valuta/IVA/lingua).
- `_apply_patch` con coercion + validation (es. "HH:MM" → time, enum check).
- `_serialize` per output JSON sicuro (time → "HH:MM").
- `can_user_access(schema, user)` — RBAC check.
- Estendibile: aggiungere uno schema = +1 entry in `SCHEMAS` dict, niente
  altro codice da toccare.

`app/services/ai_tools.py`:
- 3 tool nuovi:
  - `list_settings_schemas` (readonly) — discovery aree configurabili.
  - `read_setting(key)` (readonly) — stato corrente.
  - `update_setting(key, patch)` (mutation, gated da Apply utente) — proposta
    di modifica con diff visibile in card.
- System prompt esteso con sezione "Settings — modificare configurazioni":
  pattern obbligatorio discovery → read → update.

`app/services/ai_assistant.py`:
- Handlers `_h_list_settings_schemas`, `_h_read_setting`, `_h_update_setting`
  (i due ultimi accettano `user` keyword-only per RBAC + aree "self").
- `apply_action` esteso con iniezione opzionale di `user` via inspect.signature
  (handlers che lo dichiarano lo ricevono dal `AIAction.user_id`).

`app/services/ai_loop.py`:
- `_exec_readonly` esteso con `user` keyword-only + iniezione consistente.

`app/static/js/copilot.js`:
- `actionTypeLabel` esteso (label "⚙ ..." per i 3 tool settings).
- Nuovo `summaryUpdateSetting(d)` che renderizza la card mutation con label
  area + lista patch (campo: nuovo valore).

Cache-buster `v=3.5.0-alpha.19` (sia global.js che copilot.js).
Niente migrazione DB.

**Estensione futura**: aggiungere `notification_preferences` e `user_preferences`
quando si avranno modelli/colonne dedicati. Pattern già pronto.

---

## v3.5.0-alpha.18 — Round 7C: undo/redo planning + bulk-edit booking (5 maggio 2026)

Round 7C su feedback Matteo del 5 maggio: 2 punti planning power-user.

**Undo / Redo planning timeline**

Pre-alpha.18 esisteva già `_tlUndoStack` con Ctrl+Z (10 azioni in toast
ephemeral). Estensione completa:
- Stack max 50, **redo stack** parallelo `_tlRedoStack` con Ctrl+Y / Ctrl+Shift+Z.
- 2 bottoni persistenti in toolbar (`↶ Undo` / `↷ Redo`) con tooltip che mostra
  l'azione "in cima" allo stack (es. "Annulla: Booking duplicato").
- `tlPushUndo(action, label, opts)` accetta `preserveRedo:true` quando l'azione
  è generata da una redo (lo standard è "nuova azione utente svuota redo").
- Nuovo endpoint backend `POST /planning/api/bookings/{id}/assignments` per
  ricreare un assignment singolo (sblocca undo di `remove_assignment` che
  pre-alpha.18 era marcato "non implementato").
- Undo per `bulk_edit` ripristina lo stato precedente (assignments + execution_status)
  per ogni booking.

**Bulk-edit booking**

Pre-alpha.18: solo bulk-delete via Delete key sulla multiselect timeline.

Estensione:
- Bottone `✏ Bulk` nella toolbar timeline appare quando ci sono ≥1 assignment
  selezionati. `tlOnSelectionChange()` aggiornato dall'evento `select` di
  vis-timeline.
- Modal `modal-bulk-edit` con 2 azioni indipendenti (combinabili):
  - **Shift orario** in minuti (positivo/negativo) — applicato a start+end di
    tutti gli assignments. Conflitti orari → quel booking saltato e listato
    nei `failed`.
  - **Cambio stato esecuzione** (todo/started/done/not_done). Done triggera
    cost line sync.
- Nuovo endpoint `PUT /planning/api/bookings/{id}/bulk-edit` che accetta
  `booking_ids` CSV, `shift_minutes`, `execution_status`. Ritorna
  `{ok, failed, total}`.
- Snapshot pre-modifica registrato per undo (assignments + execution_status).

Cache-buster `v=3.5.0-alpha.18`. Niente migrazione DB.

---

## v3.5.0-alpha.17 — Round 7B: cost report lista + ricerca + export (5 maggio 2026)

Round 7B su feedback Matteo del 5 maggio: 3 punti su quote/cost-report,
chiusi in unica versione condividendo il pattern lista filtrabile.

**Cost report — da dropdown a lista filtrabile**

Bug Matteo: "menu a tendina non mostra tutto il titolo. Sostituire con ricerca.
Aggiungere filtri. Mostrare di default tutti i cost report (come in quotazioni)
ed aprire il cost report dopo click (come in quotazioni)".

Fix:
- Nuovo endpoint `GET /cost-report/api/list` che ritorna riassunto di tutti i
  job (codice/titolo/cliente/stato/quote + KPI rapidi: quotato/maturato/stimato/
  over-under).
- Pagina `/cost-report` ridisegnata: lista come `/quotes` con ricerca live
  (codice, titolo, cliente, numero quote) + 3 filtri (cliente, stato job,
  margine over/under). Click riga → toolbar dettaglio + report.
- Toolbar dettaglio: bottone "← Lista", titolo job, export PDF/CSV/XLSX,
  toggle "Modalità rendiconto".

**Cost report — export rendiconto + CSV + XLSX**

Bug Matteo: "Il cost report esportato per il cliente deve avere l'opzione per
rendicontare anche le cifre quotate, maturate e stimate, con la visione di
over/under. Aggiungi anche export csv e excel".

Fix:
- `generate_client_cost_report_pdf(report, rendiconto=True)`: nuova modalità
  con tabella a 7 colonne (Descrizione/Unità/Q.tà/Quotato/Maturato/Stimato/±)
  + riga totale finale. Over/Under colorato (verde/rosso). Modalità "stato"
  storica resta default.
- `GET /cost-report/api/job/{id}/client-pdf?rendiconto=1` accetta il flag.
- 2 endpoint nuovi:
  - `GET /cost-report/api/job/{id}/client-csv?rendiconto=0|1` — CSV UTF-8 con
    BOM (apribile direttamente in Excel italiano), separatore `;`.
  - `GET /cost-report/api/job/{id}/client-xlsx?rendiconto=0|1` — XLSX nativo
    via openpyxl con header indaco + larghezze colonne ottimizzate.
- Helper `_client_export_rows(report, rendiconto)` riusato da CSV/XLSX per
  garantire output identico tra i 2 formati.

**Quote — ricerca + filtri lista**

Bug Matteo: "aggiungere ricerca (con compilazione automatica standard) e filtri
in quotazioni".

Fix in `/quotes`:
- Refactor di `loadQuotes` in 2 step: fetch dataset + render filtrato.
- Ricerca live (numero, titolo, progetto, cliente).
- Filtri: cliente (popolato dinamicamente), stato (Bozza/Inviata/Approvata/
  Rifiutata/Scaduta/Sostituita), Job (con/senza).
- Counter "N su totale" sopra la tabella.
- Reset filtri.

Cache-buster `v=3.5.0-alpha.17`. Niente migrazione DB.

---

## v3.5.0-alpha.16 — Round 7A: HR breakdown per-punch + ROI riscritto (5 maggio 2026)

Round 7A su feedback Matteo del 5 maggio 2026: 4 bug + 1 cantiere UX, tutti
chiusi in un'unica versione perché condividono i punti di intervento.

**HR — straordinari nella lista timbrature, filtro Tipo, ferie/malattia in tabella (3 bug → 1 fix sistemico)**

Causa comune: la pagina `/hr` mostrava solo i `TimePunch` raw filtrati per
`PunchKind`. Lo straordinario non è un kind ma una conseguenza del breakdown
calcolato da `compute_overtime` (ore oltre `daily_hours_threshold`). Le
`ResourceUnavailability` (ferie/malattia) sono entità separate e non comparivano
in tabella. Il filtro Tipo proponeva i raw kinds (Turno/Pausa/Ferie/...) ma
filtrava solo i punch, lasciando fuori tutto il breakdown.

Soluzione: nuovo endpoint unificato `/hr/api/timeline?from_date&to_date&resource_id&category`
che fonde le 2 sorgenti e ritorna entries cronologiche con breakdown per-punch.

- Servizio `compute_punch_breakdown(punches, policy)` in `app/services/overtime.py`:
  raggruppa punches per giorno, calcola `regular/overtime/night/sunday/holiday`
  per-punch distribuendo l'overtime giornaliero sulle ore "in coda" alla
  giornata (last-in-first-out — convenzione standard busta paga).
- Filtro Tipo riprogrammato sulle 9 categorie di rendiconto:
  Regolari, Straordinari, Notturne, Festivo, Domenicali, Pausa, Ferie, Malattia,
  Permesso. Costante `TIMELINE_CATEGORIES` esposta al template.
- Tabella ridisegnata: nuova colonna "Breakdown" con badge inline
  ("Reg. 8h · Str. 1h · Notte 1h · Festivo"). Le righe ferie/malattia/permessi
  appaiono come righe sintetiche per giorno (1 entry/giorno per range), bg
  leggermente colorato, durata = `daily_hours_threshold` della policy.
- Totali per categoria nel header (cards colorate) coerenti col filtro attivo.
- Fallback graceful quando manca `WorkingHoursPolicy` default: tutte le ore in
  "Regolari" + banner warning con link a `/settings#hours`. Stesso pattern di
  `/api/overtime` (alpha.9).

`/api/punches` e `/api/summary` restano disponibili per consumer esterni
(calendar overlay, pannelli risorse). La pagina HR ora usa solo `/api/timeline`.

**Planning — ROI multiselect timeline riscritto**

Bug Matteo: "Shift+drag area su planning non funziona". Diagnosi:
1. Vis-timeline usa Hammer.js per pan/zoom. Anche con capture-phase listener +
   `stopPropagation`, Hammer attacca i suoi listener al container e parte il pan
   PRIMA che l'overlay venga aggiornato → l'utente vede la timeline scorrere e
   l'overlay non disegna.
2. La rilevazione gruppi via `[data-group-id]` falliva su vis-timeline 7.x che
   usa altri selettori per la labelset.

Fix in `_tlRoiHandler`:
- `setOptions({moveable: false, zoomable: false})` durante il drag → Hammer
  disabilitato → niente pan-conflict. Ripristino su mouseup/Escape.
- Trigger keys allargati: **Alt+drag** (più affidabile, vis-timeline non
  intercetta), **Shift+drag** (mantenuto per backward compat), e nuovo toggle
  persistente in toolbar **"📦 Selezione area"** per chi non vuole/può usare
  modifier keys.
- Rilevazione gruppi via scansione `.vis-labelset .vis-label` con
  `getBoundingClientRect()` + mappa indice DOM → group id da `groupsDS`.
- Cursor `crosshair` durante il drag, Escape annulla.
- Empty selection → toast "Nessun booking nell'area selezionata".

Cache-buster `v=3.5.0-alpha.16`. Niente migrazione DB.

---

## v3.5.0-alpha.15 — Round 6: ore festivo + ROI multiselect timeline (5 maggio 2026)

Ultimi 2 punti aperti del Round 5 chiusi.

**Ore festivo / domenicali ora visibili nel riepilogo "Le mie ore"**

Bug Matteo: "Ore straordinario non riportate (per esempio 1° maggio)". Causa:
`renderMyHoursSummary` (hr.html) mostrava solo `regular_hours`, `overtime_daily+weekly`, `night_hours`, `vacation_hours`, `sick_hours` e totale. Le ore festive (1 maggio) finivano in `holiday_hours` ma quel campo non era reso visibile nella UI.

Fix in `app/templates/pages/hr.html:renderMyHoursSummary`:
- Aggiunte 2 card: **"Festivo"** (rosso `#ef4444`, da `b.holiday_hours`) e **"Domenicali"** (arancione `#fb923c`, da `b.sunday_hours - b.holiday_hours` per evitare doppi conteggi quando una domenica è anche festa).
- Le ore restano calcolate distintamente dall'engine (`compute_overtime`) con i loro multipli `holiday_multiplier` / `sunday_multiplier` (CCNL). La visualizzazione le distingue da `overtime_daily/weekly` (straordinari "veri" che eccedono le soglie giornaliere/settimanali).

**Shift+drag ROI multiselect timeline**

Vis-timeline non supporta rectangle-selection nativa. Implementazione custom:

`window._tlRoiHandler` (registrato in capture-phase su `host`):
1. Mousedown + Shift su area vuota della timeline (no item, no labelset, no time-axis) → `getEventProperties(e)` registra `startTime` + `startGroup`. preventDefault per bloccare il drag-pan vis.
2. Overlay `<div id="tl-roi-rect">` floating fixed (border tratteggiato indaco + bg semi-trasparente) traccia il rettangolo via mousemove globale.
3. Mouseup → `getEventProperties(eventUp)` → calcolo intersezione: `t0..t1` su time, `groupSet` derivato da DOM `getBoundingClientRect()` di ogni gruppo (filtra solo le risorse coperte). Iterazione `itemsDS` → seleziona items con id "aN" (assignment) overlapping in tempo + dentro groupSet.
4. `tlInstance.setSelection(ids)` + toast "📦 N booking selezionati (ROI). Premi Delete per eliminare."

Si combina col bulk-delete di alpha.14 (Delete key → cascade su tutti gli assignment dei booking selezionati).

**Formato data dd/mm/yyyy**

Verifica: `fmtDate(iso)` in `global.js` usa `toLocaleDateString('it-IT')` → output naturale dd/mm/yyyy in locale italiano. Già rispettato per lista quote, cost report job-select, planning jobs table. I template che usano formato 'short' mese (es. "5 mag 2026") sono casi specifici (header agenda, etichette grafici) e restano. La selezione formato in `/settings` è rinviata.

Cache-buster `v=3.5.0-alpha.15`. Niente migrazione DB.

---

## v3.5.0-alpha.14 — Round 5: timezone timbratura + revert click + bulk cascade + UX (5 maggio 2026)

Round 5 dei fix post-test Matteo. 9 fix: 4 bug critici + 4 UX + 1 capability AI.

**Bug 1: Timbratura timezone — orario riportato errato (9:00 → 7:00)**

`hr.html:savePunch` inviava `new Date(start).toISOString()` (UTC) ma il backend salvava la datetime come naive senza timezone, e il display rileggeva naive → frontend interpretava 07:00 UTC come local 07:00 → user Italia (UTC+2 in maggio DST) vedeva orario sfasato di 2h.

Fix: invio raw del valore datetime-local input ("YYYY-MM-DDTHH:MM"). FastAPI parsa naive, storia naive, ritorna naive — niente trasformazione tz.

**Bug 2: Doppia timbratura sovrapposta**

`POST /hr/api/punches` non controllava overlap → utente poteva creare due timbrature attive sulla stessa risorsa nello stesso intervallo.

Fix in `app/routers/hr.py:create_punch`: query overlap pre-insert, considerando sia chiusi (start<end & end>start) sia in-corso (no end → start<new_end). 409 con riferimento al punch in conflitto.

**Bug 3: Ordine timbrature**

Lista `/hr/api/punches` era `desc()` (più recente prima). Matteo: ordine calendario.

Fix: `order_by(asc())`.

**Bug 4: Click timeline auto-open detail — REVERT**

In alpha.13 avevo aggiunto: `select=1 → todoOpenDetail`. Confliggeva con la selezione singola "click per evidenziare". Revert. Il dettaglio resta accessibile via right-click → Modifica oppure dalle altre viste (todo / project / agenda / calendar dove non c'è select-conflict).

**Feature: Bulk delete cascade su tutti gli assignments del booking**

Pre-alpha.14: utente selezionava 2 row di Davide (bulk delete) → solo Davide cancellato → Studio A (stesso booking, altra risorsa) restava attivo → booking orfano.

Fix in `_tlDeleteHandler`: espande la selezione a TUTTI gli assignment dei booking selezionati (set di booking_id → all assignments con quell'id). Conferma menziona la cascade ("includendo le risorse linkate non selezionate").

**Feature: Cleanup aggressivo timeline pre-render**

Bug "timeline duplicata sopra/sotto" post bulk delete: vis-timeline 7.7 lascia talvolta `.vis-timeline` orfani se renderTimeline è chiamata in race.

Fix: destroy ANCHE `window._tlInstance` (era residuo non resettato), reset `host.innerHTML`, rimuovi `.vis-timeline` siblings orfani dal parent.

**Feature: CSS modal booking — `Stesso orario` non copre più risorsa #1**

Badge `.ass-num` (position:absolute; top:-8px) della prima riga finiva sotto la label "Stesso orario per tutte le risorse".

Fix: `padding-top: 10px` su `#tlb-assignments`.

**Feature: Lista quote — colonne con larghezza min**

Nome progetto / titolo quote troncato in viewport stretti. Fix: `min-width:280px` sulla colonna "Progetto / Titolo quote", `min-width:160px` su Cliente, larghezze fisse sulle altre.

**AI capability: `update_quote`**

Nuovo tool `update_quote` (mutation) per modificare metadata di quote esistente: title, issue_date, valid_until, vat_rate, package_discount, payment_terms, notes. Quote in stato `superseded` (storiche) bloccate. Renderer + label nel copilot, listener `mf:ai-action-applied` già copre `update_quote` (filtro contiene 'quote').

Cache-buster `v=3.5.0-alpha.14`. Niente migrazione DB.

---

## v3.5.0-alpha.13 — Round 4: 3 bug critici + UX planning (4 maggio 2026)

Round 4 dei fix post-test Matteo. 3 bug critici risolti + 5 feature UX planning + 1 chiusura realtime quote.

**Bug 1: Maturato fantasma su unità non-time (Ligas J2)**

`recompute_cost_line_actual` ritornava `non_time_unit` early per unità `pc`/`lump`/`fix`/`lot`/`shot`/`version`/`allow`/`TB`/`GB` → `quantity_actual` non veniva mai resettato dopo cancellazione bookings. Bug Matteo: maturato fantasma persisteva su Ligas J2.

Fix in `app/services/cost_line_sync.py`:
- Per unità non-time, `new_qty = float(len(bookings_done))`. 0 se nessuno → resetta correttamente. Logica: 1 booking done = 1 unità (semplice, prevedibile).

Inoltre `cost_report.html:loadReport` ora chiama `POST /api/job/{id}/reconcile-actuals` automaticamente prima del GET → fix retroattivo silenzioso per drift storici (cancellazioni pre-alpha.9 + non-time pre-alpha.13).

**Bug 2: Timbratura "fine cancellata" durante input**

`mfWrapDateTimeLocal.parseValue` clearava i sub-input `date` e `time` quando il hidden era vuoto. Sequenza bug: utente digita data → syncBack scrive '' in hidden (time ancora vuoto) → focus su time → parseValue legge hidden vuoto → CANCELLA SIA DATE CHE TIME → utente perde la data appena inserita.

Fix in `app/static/js/global.js`:
- `parseValue` ora riempie i sub-input solo se il hidden ha un valore valido. Se vuoto, non tocca i sub (l'utente sta digitando, syncBack è già consistente).

**Bug 3: Filtro Davide Moretti mostra anche Luca Bianchi**

`/planning/api/project-bookings` non filtrava per `resource_id`. Vista "Per progetto" ignorava il filtro f-resource client-side.

Fix:
- `app/routers/planning.py:project_bookings`: aggiunto query param `resource_id` (csv supportato via `_parse_id_list`).
- `app/templates/pages/planning.html:renderProjectView`: passa `f-resource` all'endpoint.

**UX Planning — Realtime su tutte le viste post "Fatto"**

`todoSetExec` aggiornava solo timeline. Refactor: nuovo helper `refreshActiveView()` (legge tab attiva, chiama il render appropriato) — applicato a `todoSetExec`, `todoExtend`, `todoSetPriority`. Ora il refresh è realtime su jobs/timeline/agenda/project/storyboard/todo.

**UX Planning — Bottone "+ Booking" globale + click dettaglio in tutte le viste**

- Topbar planning: bottone `+ Booking` visibile da qualsiasi tab. Apre il modal con risorsa di default (filtro f-resource o prima del seed) + ora corrente arrotondata al quarto.
- Calendar (FullCalendar) `eventClick`: apre `todoOpenDetail(booking_id)` invece del solo toast.
- Agenda: ogni evento booking ora cliccabile → apre il modal dettaglio.
- Timeline `select` (1 item): apre `todoOpenDetail(bid)` automaticamente. Multi-select non apre il modal (l'utente sta selezionando per bulk).

**UX Planning — Multiselect Shift+click + bulk delete**

- vis-timeline option `multiselect: true` + `multiselectPerGroup: true` → Ctrl/Cmd+click aggiunge, Shift+click range-select.
- Tasto Delete/Backspace su selezione multipla → conferma + bulk DELETE delle assegnazioni. Listener cleanup-aware (ri-bound ad ogni renderTimeline).

**UX Quotes — Titolo quotazione visibile nei dropdown**

- Lista `/quotes`: colonna "Progetto / Titolo quote" — se `q.title` differente da `q.project_title`, mostra entrambi (titolo quote come sub-line).
- Cost report job-select dropdown: mostra `code — title · quote N (titolo)` con doppio livello.
- Modal booking autocomplete (planning): già mostrava `number — title` da v3.4.53, nessun cambio.

**UX Realtime — Lista quote ricarica dopo Apply copilot**

`copilot.js:copilotApply` dispatcha custom event `mf:ai-action-applied` con `{actionId, actionType, result}` post-success. Listener su `quotes.html` rilancia `loadQuotes()` (lista) o `reloadQuote()` (editor) quando l'azione è quote-related (`propose_quote*`, `propose_new_item_and_line`).

Pattern estendibile: altre pagine possono ascoltare `mf:ai-action-applied` per refresh contestuali.

Cache-buster `v=3.5.0-alpha.13`. Niente migrazione DB.

---

## v3.5.0-alpha.12 — Round 3 (chiusura): cost report popup booking + hardcost (4 maggio 2026)

Chiusi gli ultimi 2 issue di Round 3 (test estensivo Matteo del 3 maggio).

**Cost report — popup booking detail su row click**

Bug v3.4.55 stesso pattern: il popup `modal-line-detail` (KPI Quotato/Maturato + origine quote + risorse + booking attivi) era implementato solo in `/jobs/{id}` (`openLineDetail`). In `/cost-report/` il click sulla riga apriva solo il modal di edit → mancava la vista delle prenotazioni connesse.

Fix in `app/templates/pages/cost_report.html`:
- Aggiunto `<div id="modal-line-detail">` con stesso layout di `job_detail.html`.
- Riga `cost-lines-table` ora `onclick='openLineDetailHere(l.id)'` (cursor:pointer); il bottone ✎ resta accessibile con `event.stopPropagation()`.
- Nuova funzione `openLineDetailHere()` chiama `/jobs/api/{job_id}/cost-lines/{line_id}/detail` (endpoint v3.4.55 riusato) e popola il modal con KPI + origine + risorse + booking + assignments.

**Cost report — hardcost dettagliati**

`Expense.amount` aggregato in summary `total_expenses`, ma il breakdown per riga non era visibile. La `QuoteLine.hardcosts` è una snapshot al momento della quote (es. "DCP master HD: 220€/pezzo + 35€ hardcost").

Fix in `app/routers/jobs.py`:
- `GET /api/{job_id}/cost-lines/{line_id}/detail`: aggiunti `hardcosts_unit` (€/unità) e `hardcosts_total` (× quantity_quoted) letti da `QuoteLine.hardcosts`.

UI: blocco viola "Hardcost (materiali / spese vive)" nel popup line-detail (sia `cost_report.html` sia `job_detail.html`), visibile solo se hardcost > 0. In `job_detail.html` il blocco è gated dietro `CAN_VIEW_FINANCE`.

Cache-buster `v=3.5.0-alpha.12`. Niente migrazione DB.

---

## v3.5.0-alpha.11 — Round 3: quote subtotali live + booking timeline UX (4 maggio 2026)

Round 3 dei fix post-test 3 maggio. UX/feature più complessi su quote editor e timeline planning.

**Quote editor — subtotali categoria realtime + sconto categoria visibile**

Bug: i subtotali per categoria nell'editor `/quotes` non si aggiornavano quando l'utente modificava una riga inline (qty, prezzo, sconto). Restavano congelati ai valori al primo render. Lo sconto categoria mostrava solo il `−amount` ma non un "totale categoria al netto".

Fix in `app/templates/pages/quotes.html`:
- Subtotale e discount-amount delle categorie marcati con `data-cat-subtotal`/`data-cat-disc-amount`/`data-cat-net` per refresh live.
- Nuova riga **"Totale categoria (al netto)"** sotto lo sconto, visibile solo se discount > 0, in verde.
- `refreshCategoryDiscountAmounts()` esteso (di fatto rinominato a "refresh category rows"): ricalcola subtotale, discount-amount e net-row da `currentQuote.lines` + `category_discounts` ad ogni save di linea/sconto.

**Resource → Project sync — anche su PUT booking + PUT assignment**

Bug: aggiungere una risorsa a un booking esistente (PUT booking con replace-all assignments) o cambiare risorsa su un assignment (PUT assignment, drag/resize/reassign) NON triggherava `ensure_resources_assigned_to_job`. La risorsa nuova restava NON assegnata al progetto.

Fix in `app/routers/planning.py`:
- `update_booking`: dopo replace-all, hook `ensure_resources_assigned_to_job(b.job_id, [a.resource_id for a in b.assignments])`.
- `update_assignment`: dopo reassign, hook `ensure_resource_assigned_to_job(a.booking.job_id, a.resource_id)`.

**Booking done → propaga a tutte le risorse**

Il modello era già booking-level (`Booking.execution_status`), quindi il backend già marca done per TUTTE le risorse di un booking. La regressione visiva era: la timeline non si aggiornava dopo il "Le mie" → "✓ Fatto".

Fix in `todoSetExec()`: dopo l'API call, se la timeline view è attiva, chiama `renderTimeline(true)` per ridisegnare gli items con i nuovi `tl-exec-*` class. Toast aggiornato a "completato (tutte le risorse del booking)" per chiarezza.

**Timeline — highlight cross-resource su click + duplica multi-risorsa + overlay drag**

3 fix UX richiesti da Matteo nel test:
1. **Highlight risorse linkate** (#6): click su un item di un booking multi-risorsa → tutti gli items con stesso `booking_id` ricevono CSS class `tl-link-highlight` (outline indaco). Il toast informativo aggiunge "· N risorse linkate".
2. **Copia multi-risorsa** (#7): `_tlDoDuplicate` riscritto. Prima clonava SOLO l'item cliccato (1 risorsa). Ora calcola l'offset temporale dal click point e shifta TUTTI gli assignments della sorgente (preserva l'unità operativa). Toast: "Booking duplicato (N risorse)".
3. **Overlay drag con orario** (#6 bis): nuovo elemento flottante `#tl-drag-overlay` segue il cursore durante drag/resize, mostra "start → end / ⏱ durata / ⛔ ferie / ⚠ festivo". Si nasconde su drop (`onMove`), `mouseup`, `Escape`. Tooltip nativo (`item.title`) preservato come fallback.

**File toccati**: `planning.py`, `planning.html`, `quotes.html`, `base.html`, `main.py`. Cache-buster `v=3.5.0-alpha.11`. Niente migrazione DB.

---

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
