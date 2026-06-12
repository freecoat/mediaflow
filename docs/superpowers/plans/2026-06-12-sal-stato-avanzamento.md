# SAL Stato Avanzamento Lavori — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pagina `/finance/sal` read-only: tab Per-progetto (% avanzamento ore lavorate/quotate, monte ore, allarme sforamento, drill-down reparto+job) + tab Temporale (mese/trimestre: pianificate/lavorate/fatturato/%).

**Architecture:** Spec `docs/superpowers/specs/2026-06-12-sal-stato-avanzamento-design.md` — LEGGILA PRIMA. Nessun modello/migrazione: aggrega Job/JobCostLine/Booking/Invoice esistenti. Helper riusati: `_booking_billable_hours` in app/services/cost_line_sync.py, `WorkingHoursPolicy.daily_hours_threshold`, `BookingExecutionStatus.done`, `BookingStatus.cancelled`. Pattern endpoint/tenant: app/routers/finance.py (`current_tenant_id()`, gate `view_finance`). Pattern UI tabella+filtri: app/templates/pages/cost_report.html.

**Convenzioni:** tenant filter ovunque, read-only (no Form mutator), gate `view_finance`, commenti italiani, helper JS globali (api/toast/escapeHtml), niente Jinja in commenti JS, `.venv/Scripts/python`, fixture client_admin pattern tests esistenti (Asset/Job ctor: leggi i NOT NULL). Commit con Co-Authored-By Claude Fable 5.

---

### Task 1: Service `sal_metrics.py` — ore quotate/pianificate/lavorate + allarme

**Files:** Create `app/services/sal_metrics.py`; Test `tests/test_sal_metrics.py`

- [ ] **Step 1: Test RED.** DB in-memory; helper che crea Job + JobCostLine (unit vari) + Booking (con assignment+resource per le ore). Leggi `_booking_billable_hours` e `compute_billable_hours` in cost_line_sync.py per costruire booking con ore note (assignment con start/end → billable_hours). Casi:
  1. `quoted_hours(job)`: JCL unit="hr" quantity_quoted=10 → 10; unit="day" qty=2 + policy daily=8 → 16; unit="pc" qty=5 → 0 (esclusa); mix → somma corretta solo tempo
  2. `quoted_hours` senza policy → default 8.0 per i giorni
  3. `planned_hours(job)`: Σ billable di booking non-cancelled (cancelled esclusi)
  4. `worked_hours(job)`: solo execution_status==done
  5. `by_department(job)`: dict department_id → {quoted, planned, worked}; quotato da PriceItem.department_id della JCL, pian/lav da Resource.department_id del booking; None → chiave 0 ("Altro")
  6. `job_alarm(job)`: worked>quoted o planned>quoted → "red"; max(worked,planned)>=0.9*quoted (quoted>0) → "amber"; altrimenti "none"; quoted=0 → "none"
  7. `project_metrics(db, project)`: Σ sui job; pct = worked/quoted (0 se quoted 0); alarm = peggiore tra i job

  Funzioni firma:
  ```python
  def quoted_hours(job, *, daily_hours: float = 8.0) -> float
  def planned_hours(job) -> float          # usa _booking_billable_hours
  def worked_hours(job) -> float
  def by_department(job, *, daily_hours=8.0) -> dict[int, dict]
  def job_alarm(job) -> str                # "red"|"amber"|"none"
  def job_metrics(job, *, daily_hours=8.0) -> dict   # {quoted,planned,worked,pct,alarm}
  def project_metrics(db, project) -> dict           # aggrega job, risolve daily_hours per job
  ```
- [ ] **Step 2: RED** — `.venv/Scripts/python -m pytest tests/test_sal_metrics.py -q`.
- [ ] **Step 3: Implementa.** Unit-tempo set: `{"hr","hour","h","ore","ora","day","days","gg","giorno","giorni"}` (lower/strip). Ora-unit = {hr,hour,h,ore,ora} → quantity_quoted as-is; giorno-unit → × daily_hours. daily_hours per job: `job.working_hours_policy.daily_hours_threshold` se esiste, altrimenti default WorkingHoursPolicy.is_default, altrimenti 8.0 (helper `_daily_hours_for_job(db, job)` usato da project_metrics; le funzioni pure prendono daily_hours come param). Booking ore via `from app.services.cost_line_sync import _booking_billable_hours`. by_department: itera cost_lines (quotato per dept) e booking (pian/lav per dept via assignment.resource.department_id — se multi-assignment, somma ore per la dept di ciascuna risorsa proporzionalmente? NO: usa la dept del booking = dept della risorsa primaria; semplice: per ogni booking attribuisci billable alla dept della prima risorsa con department_id, fallback 0).
- [ ] **Step 4: GREEN.**
- [ ] **Step 5: Commit** `feat(SAL): service sal_metrics — ore quotate/pianificate/lavorate + allarme`.

### Task 2: Service timeline + endpoint SAL

**Files:** Modify `app/services/sal_metrics.py` (timeline_metrics), `app/routers/finance.py` (3 endpoint + route pagina); Test `tests/test_sal_endpoints.py`

- [ ] **Step 1: Test RED.**
  - `timeline_metrics(db, *, year, granularity)`: helper service. Aggrega booking del tenant per mese/trimestre del `start_datetime` (planned = tutti non-cancelled, worked = done) + fatturato Σ Invoice.subtotal (no draft/cancelled, TD04 = -1) per mese di issue_date → mappato a periodo. Ritorna lista periodi {label, planned, worked, invoiced, pct} + totale. Test: 2 booking in mesi diversi + 1 fattura → righe corrette, quarter aggrega 3 mesi.
  - Endpoint (fixture client_admin con view_finance):
    - `GET /finance/api/sal/projects` → lista righe progetto {id, code, title, client, quotes:[{number,title}], quoted, planned, worked, pct, alarm, job_count}; filtri status/client_id/q/alarm_only; tenant; progetti cestinati esclusi (deleted_at IS NULL)
    - `GET /finance/api/sal/projects/{id}/detail` → {departments:[{department_id, name, quoted, planned, worked}], jobs:[{id, code, title, quote_number, quoted, planned, worked, pct, alarm}]}; 404 cross-tenant
    - `GET /finance/api/sal/timeline?year=&granularity=month|quarter` → da timeline_metrics
  - 403 senza view_finance (se testabile col pattern multi-user; altrimenti verifica solo che il gate sia presente).
- [ ] **Step 2: RED.**
- [ ] **Step 3: Implementa.** `GET /finance/sal` route pagina (HTMLResponse, template sal.html, gate view_finance come le altre pagine finance — guarda come `/finance/cashflow` rende). Endpoint batch: pre-fetch progetti tenant (joinedload client + jobs + jobs.cost_lines + jobs.quote + jobs.bookings con assignments.resource) per evitare N+1; quotes del progetto = distinct quote dei job. Filtri SQL dove possibile, alarm_only in Python (deriva da metrics). Riusa project_metrics/job_metrics/by_department di Task 1.
- [ ] **Step 4: GREEN** + regressione `tests/ -q -k "finance or cost_report"`.
- [ ] **Step 5: Commit** `feat(SAL): endpoint projects/detail/timeline + route pagina`.

### Task 3: UI `sal.html` + voce menu

**Files:** Create `app/templates/pages/sal.html`; Modify `app/templates/base.html` (voce menu Finanza); eventuale i18n key se serve (guarda come le altre nav usano data-i18n — aggiungi `nav.sal` ai dizionari se il progetto fallisce su key mancante, altrimenti testo diretto)

- [ ] **Step 1:** voce menu in base.html sezione Finanza (dopo cost-report): `<a href="/finance/sal" data-nav-id="sal" class="nav-item {% if active_page == 'sal' %}active{% endif %}"><span class="nav-icon"><i data-lucide="trending-up"></i></span> <span>SAL — Avanzamento</span></a>`.
- [ ] **Step 2:** sal.html (`{% set active_page = "sal" %}`, extends base.html). Tab bar (Per progetto / Temporale). 
  - Tab Progetto: barra filtri (select stato, select cliente popolato da /clients o dai dati, input ricerca debounce, checkbox solo-allarme); tabella (Cliente, Progetto, Quotazioni chip, Monte ore q/p/l, % avanzamento barra, Allarme badge 🔴/🟠, Stato); riga cliccabile → drill-down espandibile (fetch /detail): tabella reparti (q/p/l/%) + tabella job (code/quote/q/p/l/%/allarme). Ordinamento per colonna.
  - Tab Temporale: select anno + radio mese/trimestre → fetch /timeline → tabella periodi (Pianificate, Lavorate, Fatturato €, %) + riga totale; mini-barre %.
  - Vincoli JS: api/toast/escapeHtml globali, data-* per id riga, niente Jinja in commenti JS, no JSON.stringify in onclick, funzioni definite nello stesso script. Badge % con stessa palette degli altri (verde/ambra/rosso). Numeri ore con 1 decimale, € con separatori.
- [ ] **Step 3:** verifiche — jinja get_template sal.html + base.html; grep funzioni onclick definite; `.venv/Scripts/python -m pytest tests/ -q -k sal`.
- [ ] **Step 4:** Commit `feat(SAL): UI pagina /finance/sal tab progetto + temporale + voce menu`.

### Task 4: E2E + bump + push

**Files:** Create `tools/_e2e_sal.py`; Modify `app/main.py` (3.5.0-alpha.172.217), CHANGELOG, STATO

- [ ] **Step 1:** E2E (pattern tools/_e2e_f6.py, TestClient, no browser): tenant + cliente + progetto con 2 job; JCL unit "hr"/"day"/"pc"; booking (uno done, uno non-done, uno cancelled) con assignment+resource (dept settato) per avere ore note; 1 Invoice non-draft. Verifica: GET /finance/api/sal/projects → riga col cliente, quoted/planned/worked attesi, pct=worked/quoted, alarm corretto (forza uno sforamento); /detail → breakdown reparto + 2 job; /timeline year/quarter → fatturato e ore nei periodi giusti; filtro alarm_only e client_id.
- [ ] **Step 2:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python tools/_e2e_sal.py` → tutti verdi; suite completa `pytest tests/ -q` 0 failed.
- [ ] **Step 3:** bump versione; CHANGELOG entry SAL; STATO (sezione + Prossimo); graphify update; export DB ZIP; commit bump; push origin main.

## Self-review (fatto)
- Spec coverage: ore-quotate-solo-tempo/giorni→ore (T1), pianificate/lavorate da booking (T1), allarme job (T1), per-progetto+drill reparto+job (T1/T2/T3), temporale mese/trim+fatturato (T2/T3), pagina dedicata gate view_finance (T2/T3). ✔
- Tipi coerenti: dict metrics {quoted,planned,worked,pct,alarm} uniforme service→endpoint→UI; alarm "red|amber|none". ✔
- Niente modelli/migrazioni: solo aggregazione. ✔
