@echo off
title MediaFlow — Utilità

:menu
cls
echo.
echo  MediaFlow — Strumenti
echo  ─────────────────────────────────────────────────────
echo.
echo  [1] Avvia server
echo  [2] Resetta database (ATTENZIONE: cancella tutti i dati)
echo  [3] Ricarica dati demo
echo  [4] Aggiorna dipendenze Python
echo  [5] Migra database esistente (v1 -^> v2 con Progetti)
echo  [6] Migra database esistente (v2 -^> v3 con Reparti e Tenant) [Fase 1-bis]
echo  [7] Migra database esistente (sconti multilivello quotazioni)
echo  [8] Migra database esistente (AI per-utente, tab Impostazioni AI) [v3.2]
echo  [9] Migra database esistente (categoria override sulle righe quote) [v3.4.2]
echo  [B] Migra database esistente (tenant_id su bookings) [v3.4.6]
echo  [C] Migra database esistente (tabella time_punches HR) [v3.4.7]
echo  [D] Migra database esistente (is_extra su job_cost_lines) [v3.4.9]
echo  [E] Migra database esistente (Booking.kind/cost_line + job_id nullable) [v3.4.10]
echo  [F] Migra database esistente (multi-resource booking_assignments) [v3.4.16]
echo  [G] Migra database esistente (working hours + ferie tipizzate) [v3.4.17]
echo  [H] Migra database esistente (soglie/moltiplicatori straordinari) [v3.4.21]
echo  [I] Migra database esistente (workflow approvazione ferie/malattia) [v3.4.22]
echo  [J] Migra database esistente (sistema permessi configurabili Role) [v3.4.23]
echo  [K] Migra database esistente (permessi extra per-utente) [v3.4.25]
echo  [L] Migra database esistente (Booking esecutivo: priorita+stato+overtime) [v3.4.32]
echo  [M] Cleanup orfani lifecycle Quote/Job/Booking [v3.4.36]
echo  [P] Migra OAuth calendario (Fase A) [v3.5.0-alpha.172]
echo  [Q] Migra calendario (Fase B) [v3.5.0-alpha.172]
echo  [R] Migra Fase D - documenti Drive [v3.5.0-alpha.172]
echo  [S] Migra Client email F2 - email_links [v3.5.0-alpha.172]
echo  [U] Migra Client email F3 - rubrica contatti (client_id nullable + link) [v3.5.0-alpha.172]
echo  [T] Seed Job di test per notifica deadline (scadenza fra 2 giorni) [v3.4.28]
echo  [A] Apri cartella upload
echo  [0] Esci
echo.
set /p scelta="Scegli un'opzione (0-9, A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q, T): "

if "%scelta%"=="1" goto avvia
if "%scelta%"=="2" goto reset_db
if "%scelta%"=="3" goto seed
if "%scelta%"=="4" goto update
if "%scelta%"=="5" goto migrate
if "%scelta%"=="6" goto migrate_1bis
if "%scelta%"=="7" goto migrate_discounts
if "%scelta%"=="8" goto migrate_ai
if "%scelta%"=="9" goto migrate_cat_override
if /i "%scelta%"=="B" goto migrate_booking_tenant
if /i "%scelta%"=="C" goto migrate_time_punches
if /i "%scelta%"=="D" goto migrate_jobcostline_extra
if /i "%scelta%"=="E" goto migrate_booking_cost_line_kind
if /i "%scelta%"=="F" goto migrate_multi_resource
if /i "%scelta%"=="G" goto migrate_working_hours
if /i "%scelta%"=="H" goto migrate_overtime
if /i "%scelta%"=="I" goto migrate_unav_approval
if /i "%scelta%"=="J" goto migrate_roles_v2
if /i "%scelta%"=="K" goto migrate_user_extra_perms
if /i "%scelta%"=="L" goto migrate_booking_executive
if /i "%scelta%"=="M" goto migrate_lifecycle_cleanup
if /i "%scelta%"=="N" goto migrate_quote_versioning
if /i "%scelta%"=="O" goto reset_business_data
if /i "%scelta%"=="P" goto migrate_oauth_calendar
if /i "%scelta%"=="Q" goto migrate_calendar_events
if /i "%scelta%"=="R" goto migrate_documents
if /i "%scelta%"=="S" goto migrate_email_links
if /i "%scelta%"=="U" goto migrate_contacts_rubrica
if /i "%scelta%"=="T" goto seed_test_deadline
if /i "%scelta%"=="A" goto uploads
if "%scelta%"=="0" exit /b

goto menu

:avvia
call .venv\Scripts\activate.bat
start "" /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"
python run.py
goto menu

:reset_db
echo.
set /p conferma="Sei sicuro? Tutti i dati saranno eliminati (s/n): "
if /i "%conferma%"=="s" (
    if exist "mediaflow.db" del "mediaflow.db"
    echo [OK] Database eliminato
    call .venv\Scripts\activate.bat
    python scripts\seed_demo.py
    echo [OK] Database ricreato con dati demo
)
pause & goto menu

:seed
call .venv\Scripts\activate.bat
python scripts\seed_demo.py
pause & goto menu

:update
call .venv\Scripts\activate.bat
pip install -r requirements.txt --upgrade --quiet
echo [OK] Dipendenze aggiornate
pause & goto menu

:migrate
echo.
echo Questo script aggiunge la struttura Progetti al database esistente,
echo preservando tutti i dati. Esegui una sola volta dopo l'aggiornamento.
echo.
set /p conferma="Procedo con la migrazione? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_to_projects.py
)
pause & goto menu

:migrate_1bis
echo.
echo Migrazione Fase 1-bis: aggiunge Tenant, Reparti e DeliveryTemplate.
echo Aggiorna anche il listino con le keywords AI e collega le voci ai reparti.
echo Operazione non distruttiva: i dati esistenti sono preservati.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_phase1bis.py
)
pause & goto menu

:migrate_discounts
echo.
echo Migrazione sconti multilivello: aggiunge sconto su singola voce, su categorie
echo dinamiche e subtotal_gross per visibilita' cliente. Operazione non distruttiva.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_quote_discounts.py
)
pause & goto menu

:migrate_ai
echo.
echo Migrazione AI per-utente: aggiunge tabelle user_ai_settings + ai_actions
echo e la colonna users.active_ai_provider. Genera AI_KEY_ENCRYPTION_KEY in .env
echo se mancante. Operazione non distruttiva.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_ai_per_user.py
)
pause & goto menu

:migrate_cat_override
echo.
echo Migrazione: aggiunge la colonna `category_override` a `quote_lines`.
echo Permette di spostare voci tra categorie senza cambiare la voce listino.
echo Operazione non distruttiva e idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_quote_category_override.py
)
pause & goto menu

:migrate_booking_tenant
echo.
echo Migrazione: aggiunge tenant_id su bookings (default 1).
echo Allinea Booking alla convenzione multi-tenant soft Fase 1-bis.
echo Operazione non distruttiva e idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_booking_tenant.py
)
pause & goto menu

:migrate_time_punches
echo.
echo Migrazione: crea tabella time_punches per la sezione HR.
echo Timbrature/presenze separate dai Booking (intenzione vs consuntivo).
echo Operazione non distruttiva e idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_time_punches.py
)
pause & goto menu

:migrate_jobcostline_extra
echo.
echo Migrazione: aggiunge is_extra su job_cost_lines.
echo Marca lavorazioni aggiunte dopo l'approvazione della quote.
echo Operazione non distruttiva e idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_jobcostline_extra.py
)
pause & goto menu

:migrate_booking_cost_line_kind
echo.
echo Migrazione: Booking.kind + job_cost_line_id, TimePunch.job_cost_line_id
echo e bookings.job_id rilassato a NULL (per booking interni).
echo Richiede recreate-table SQLite, operazione idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_booking_cost_line_kind.py
)
pause & goto menu

:migrate_multi_resource
echo.
echo Migrazione: multi-resource booking. Nuova tabella booking_assignments,
echo popolata da Booking esistenti (1:1). Booking.resource_id rimosso.
echo Richiede recreate-table SQLite, operazione idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_multi_resource.py
)
pause & goto menu

:migrate_working_hours
echo.
echo Migrazione: WorkingHoursPolicy + ferie tipizzate.
echo Crea policy default 'Italia 9-13/14-18 lun-ven', aggiunge
echo Resource.working_hours_policy_id e ResourceUnavailability.kind.
echo Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_working_hours.py
)
pause & goto menu

:migrate_overtime
echo.
echo Migrazione: soglie ore + moltiplicatori straordinari.
echo Aggiunge daily_hours_threshold, weekly_hours_threshold,
echo overtime/night/sunday/holiday_multiplier, night_start/night_end
echo a working_hours_policies. Default Italia (8h/40h, +25%%/+50%%/+50%%/x2).
echo Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_overtime_thresholds.py
)
pause & goto menu

:migrate_unav_approval
echo.
echo Migrazione: workflow approvazione ferie/malattia/permessi.
echo Aggiunge status, requested_by_user_id, approved_by_user_id,
echo approved_at, rejection_reason, created_at a resource_unavailabilities.
echo Backfill record esistenti come 'approved'.
echo Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_unavailability_approval.py
)
pause & goto menu

:migrate_roles_v2
echo.
echo Migrazione: sistema permessi configurabili Role.
echo Crea tabella roles con 6 preset (admin/manager/producer/accounting/operator/viewer)
echo Aggiunge users.role_id e mappa utenti esistenti dall'enum legacy.
echo Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_roles_v2.py
)
pause & goto menu

:migrate_user_extra_perms
echo.
echo Migrazione: permessi extra per-utente (additivi sopra il ruolo).
echo Aggiunge users.extra_permissions JSON NULL. Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_user_extra_permissions.py
)
pause & goto menu

:migrate_booking_executive
echo.
echo Migrazione: Booking esecutivo. Aggiunge a `bookings` priority,
echo execution_status, not_done_reason, count_in_costs, overtime_status,
echo original_end_datetime. Mappa permesso approve_overtime su admin/manager/producer.
echo Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_booking_executive.py
)
pause & goto menu

:migrate_lifecycle_cleanup
echo.
echo Cleanup orfani lifecycle:
echo  [1] JobCostLine con quote_line_id che punta a riga quote inesistente
echo  [2] Booking.job_cost_line_id che punta a JobCostLine inesistente -^> NULL
echo  [3] TimePunch.job_cost_line_id che punta a JobCostLine inesistente -^> NULL
echo Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_lifecycle_cleanup.py
)
pause & goto menu

:migrate_quote_versioning
echo.
echo Migrazione versioning quote (v3.4.39):
echo  [1] quotes.parent_quote_id (catena versioni)
echo  [2] quotes.superseded_by_id (puntatore al successore approvato)
echo  [3] quote_lines.parent_line_id (eredita riga in V_n+1)
echo Idempotente. Auto-applicata anche al boot.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_quote_versioning.py
)
pause ^& goto menu

:reset_business_data
echo.
echo RESET BUSINESS DATA (v3.4.49):
echo Cancella: clienti, progetti, quotazioni, job, booking, risorse,
echo timbrature, fatture, asset, notifiche, conversazioni AI.
echo Preserva: listino, utenti, ruoli, reparti, tenant, policy ore, AI settings.
echo.
echo ATTENZIONE: operazione non reversibile (no soft-delete).
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\reset_business_data.py --yes
)
pause ^& goto menu

:seed_test_deadline
echo.
echo Crea (o aggiorna) un job 'JOB-TEST-DEADLINE' con scadenza fra 2 giorni.
echo La notifica job_deadline_approaching verra emessa al prossimo riavvio server
echo (check al boot) o via POST /admin/api/check-deadlines (admin).
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\seed_test_deadline.py
)
pause & goto menu

:migrate_oauth_calendar
echo.
echo Migrazione OAuth calendario (Fase A): aggiunge auto_sync_calendar
echo e claqo_calendar_id su user_oauth_tokens. Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_oauth_calendar.py
)
pause & goto menu

:migrate_calendar_events
echo.
echo Migrazione calendario (Fase B): crea la tabella calendar_events.
echo Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_calendar_events.py
)
pause & goto menu

:migrate_documents
echo.
echo Migrazione Fase D: crea la tabella document_links (documenti Drive collegati).
echo Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_documents.py
)
pause & goto menu

:migrate_email_links
echo.
echo Migrazione Client email F2: crea la tabella email_links (thread agganciati a trattative).
echo Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_email_links.py
)
pause & goto menu

:migrate_contacts_rubrica
echo.
echo Migrazione Client email F3: rende contacts.client_id nullable, aggiunge
echo company_text/source, crea contact_acquisitions/contact_projects.
echo Idempotente.
echo.
set /p conferma="Procedo? (s/n): "
if /i "%conferma%"=="s" (
    call .venv\Scripts\activate.bat
    python scripts\migrate_contacts_rubrica.py
)
pause & goto menu

:uploads
explorer uploads
goto menu
