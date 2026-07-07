#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#  MediaFlow — Strumenti (macOS / Linux)
#  Lancialo con:  ./strumenti.sh
# ═══════════════════════════════════════════════════════════════════

cd "$(dirname "$0")"

# Trova Python
PYTHON_CMD=""
for candidate in python3.12 python3.13 python3.11 python3; do
    if command -v "$candidate" &> /dev/null; then
        PYTHON_CMD="$candidate"
        break
    fi
done

# Attiva venv se esiste
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

while true; do
    clear
    echo ""
    echo " MediaFlow — Strumenti"
    echo " ─────────────────────────────────────────────────────"
    echo ""
    echo "  [1] Avvia server"
    echo "  [2] Resetta database (ATTENZIONE: cancella tutti i dati)"
    echo "  [3] Ricarica dati demo"
    echo "  [4] Aggiorna dipendenze Python"
    echo "  [5] Migra database esistente (v1 → v2 con Progetti)"
    echo "  [6] Migra database esistente (v2 → v3 con Reparti) [Fase 1-bis]"
    echo "  [7] Migra database esistente (sconti multilivello quotazioni)"
    echo "  [8] Migra database esistente (AI per-utente, tab Impostazioni AI) [v3.2]"
    echo "  [9] Migra database esistente (categoria override righe quote) [v3.4.2]"
    echo "  [b] Migra database esistente (tenant_id su bookings) [v3.4.6]"
    echo "  [c] Migra database esistente (tabella time_punches HR) [v3.4.7]"
    echo "  [d] Migra database esistente (is_extra su job_cost_lines) [v3.4.9]"
    echo "  [e] Migra database esistente (Booking.kind/cost_line + job_id nullable) [v3.4.10]"
    echo "  [f] Migra database esistente (multi-resource booking_assignments) [v3.4.16]"
    echo "  [g] Migra database esistente (working hours + ferie tipizzate) [v3.4.17]"
    echo "  [h] Migra database esistente (soglie/moltiplicatori straordinari) [v3.4.21]"
    echo "  [i] Migra database esistente (workflow approvazione ferie/malattia) [v3.4.22]"
    echo "  [j] Migra database esistente (sistema permessi configurabili Role) [v3.4.23]"
    echo "  [k] Migra database esistente (permessi extra per-utente) [v3.4.25]"
    echo "  [l] Migra database esistente (Booking esecutivo: priorità+stato+overtime) [v3.4.32]"
    echo "  [m] Cleanup orfani lifecycle Quote/Job/Booking [v3.4.36]"
    echo "  [p] Migra OAuth calendario (Fase A) [v3.5.0-alpha.172]"
    echo "  [q] Migra calendario (Fase B) [v3.5.0-alpha.172]"
    echo "  [r] Migra Fase D - documenti Drive [v3.5.0-alpha.172]"
    echo "  [s] Migra Client email F2 - email_links [v3.5.0-alpha.172]"
    echo "  [t] Seed Job di test per notifica deadline (scadenza fra 2 giorni) [v3.4.28]"
    echo "  [a] Apri cartella upload"
    echo "  [0] Esci"
    echo ""
    read -p "Scegli un'opzione (0-9, a, b, c, d, e, f, g, h, i, j, k, l, m, n, o, p, q, t): " scelta

    case $scelta in
        1)
            (sleep 2 && open http://localhost:8000 2>/dev/null || xdg-open http://localhost:8000 2>/dev/null) &
            python run.py
            ;;
        2)
            read -p "Sei sicuro? Tutti i dati saranno eliminati (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                rm -f mediaflow.db
                python scripts/seed_demo.py
                echo "[OK] Database ricreato con dati demo"
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        3)
            python scripts/seed_demo.py
            read -p "Premi INVIO per continuare..."
            ;;
        4)
            pip install -r requirements.txt --upgrade --quiet
            echo "[OK] Dipendenze aggiornate"
            read -p "Premi INVIO per continuare..."
            ;;
        5)
            echo ""
            echo "Migrazione v1→v2: aggiunge la struttura Progetti."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_to_projects.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        6)
            echo ""
            echo "Migrazione Fase 1-bis: aggiunge Tenant, Reparti e DeliveryTemplate."
            echo "Aggiorna il listino con keywords AI. Operazione NON distruttiva."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_phase1bis.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        7)
            echo ""
            echo "Migrazione sconti multilivello: aggiunge sconto su singola voce, su"
            echo "categorie dinamiche e subtotal_gross per visibilità cliente."
            echo "Operazione NON distruttiva."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_quote_discounts.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        8)
            echo ""
            echo "Migrazione AI per-utente: aggiunge user_ai_settings + ai_actions"
            echo "e users.active_ai_provider. Genera AI_KEY_ENCRYPTION_KEY in .env"
            echo "se mancante. Operazione NON distruttiva."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_ai_per_user.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        9)
            echo ""
            echo "Migrazione: aggiunge category_override su quote_lines."
            echo "Permette di spostare voci tra categorie senza cambiare il listino."
            echo "Operazione NON distruttiva e idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_quote_category_override.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        b|B)
            echo ""
            echo "Migrazione: aggiunge tenant_id su bookings (default 1)."
            echo "Allinea Booking alla convenzione multi-tenant soft Fase 1-bis."
            echo "Operazione NON distruttiva e idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_booking_tenant.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        c|C)
            echo ""
            echo "Migrazione: crea tabella time_punches per la sezione HR."
            echo "Timbrature/presenze separate dai Booking (intenzione vs consuntivo)."
            echo "Operazione NON distruttiva e idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_time_punches.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        d|D)
            echo ""
            echo "Migrazione: aggiunge is_extra su job_cost_lines."
            echo "Marca lavorazioni aggiunte dopo l'approvazione della quote."
            echo "Operazione NON distruttiva e idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_jobcostline_extra.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        e|E)
            echo ""
            echo "Migrazione: Booking.kind + job_cost_line_id, TimePunch.job_cost_line_id"
            echo "e bookings.job_id rilassato a NULL (per booking interni)."
            echo "Richiede recreate-table SQLite, operazione idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_booking_cost_line_kind.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        f|F)
            echo ""
            echo "Migrazione: multi-resource booking. Nuova tabella booking_assignments,"
            echo "popolata da Booking esistenti (1:1). Booking.resource_id rimosso."
            echo "Richiede recreate-table SQLite, operazione idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_multi_resource.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        g|G)
            echo ""
            echo "Migrazione: WorkingHoursPolicy + ferie tipizzate."
            echo "Crea policy default 'Italia 9-13/14-18 lun-ven', aggiunge"
            echo "Resource.working_hours_policy_id e ResourceUnavailability.kind."
            echo "Idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_working_hours.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        h|H)
            echo ""
            echo "Migrazione: soglie ore + moltiplicatori straordinari."
            echo "Aggiunge daily_hours_threshold, weekly_hours_threshold,"
            echo "overtime/night/sunday/holiday_multiplier, night_start/night_end"
            echo "a working_hours_policies. Default Italia (8h/40h, +25%/+50%/+50%/x2)."
            echo "Idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_overtime_thresholds.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        i|I)
            echo ""
            echo "Migrazione: workflow approvazione ferie/malattia/permessi."
            echo "Aggiunge status, requested_by_user_id, approved_by_user_id,"
            echo "approved_at, rejection_reason, created_at a resource_unavailabilities."
            echo "Backfill record esistenti come 'approved'."
            echo "Idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_unavailability_approval.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        j|J)
            echo ""
            echo "Migrazione: sistema permessi configurabili Role."
            echo "Crea tabella roles con 6 preset, users.role_id, mapping utenti."
            echo "Idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_roles_v2.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        k|K)
            echo ""
            echo "Migrazione: permessi extra per-utente (additivi sopra il ruolo)."
            echo "Aggiunge users.extra_permissions JSON NULL. Idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_user_extra_permissions.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        m|M)
            echo ""
            echo "Cleanup orfani lifecycle:"
            echo " [1] JobCostLine con quote_line_id orfano"
            echo " [2] Booking.job_cost_line_id orfano → NULL"
            echo " [3] TimePunch.job_cost_line_id orfano → NULL"
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_lifecycle_cleanup.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        l|L)
            echo ""
            echo "Migrazione: Booking esecutivo. Aggiunge a 'bookings' priority,"
            echo "execution_status, not_done_reason, count_in_costs, overtime_status,"
            echo "original_end_datetime. Mappa permesso approve_overtime su admin/manager/producer."
            echo "Idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_booking_executive.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        n|N)
            echo ""
            echo "Migrazione versioning quote (v3.4.39):"
            echo " [1] quotes.parent_quote_id (catena versioni)"
            echo " [2] quotes.superseded_by_id (puntatore al successore approvato)"
            echo " [3] quote_lines.parent_line_id (eredità riga in V_n+1)"
            echo "Idempotente. Auto-applicata anche al boot."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_quote_versioning.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        o|O)
            echo ""
            echo "RESET BUSINESS DATA (v3.4.49):"
            echo "Cancella: clienti, progetti, quotazioni, job, booking, risorse,"
            echo "timbrature, fatture, asset, notifiche, conversazioni AI."
            echo "Preserva: listino, utenti, ruoli, reparti, tenant, policy ore, AI settings."
            echo ""
            echo "ATTENZIONE: operazione non reversibile (no soft-delete)."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/reset_business_data.py --yes
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        p|P)
            echo ""
            echo "Migrazione OAuth calendario (Fase A): aggiunge auto_sync_calendar"
            echo "e claqo_calendar_id su user_oauth_tokens. Idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_oauth_calendar.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        q|Q)
            echo ""
            echo "Migrazione calendario (Fase B): crea la tabella calendar_events."
            echo "Idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_calendar_events.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        r|R)
            echo ""
            echo "Migrazione Fase D: crea la tabella document_links (documenti Drive)."
            echo "Idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_documents.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        s|S)
            echo ""
            echo "Migrazione Client email F2: crea la tabella email_links (thread agganciati a trattative)."
            echo "Idempotente."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/migrate_email_links.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        t|T)
            echo ""
            echo "Crea (o aggiorna) un job 'JOB-TEST-DEADLINE' con scadenza fra 2 giorni."
            echo "La notifica job_deadline_approaching verrà emessa al prossimo riavvio server"
            echo "(check al boot) o via POST /admin/api/check-deadlines (admin)."
            read -p "Procedo? (s/n): " conferma
            if [ "$conferma" = "s" ] || [ "$conferma" = "S" ]; then
                python scripts/seed_test_deadline.py
            fi
            read -p "Premi INVIO per continuare..."
            ;;
        a|A)
            open uploads 2>/dev/null || xdg-open uploads 2>/dev/null
            ;;
        0)
            exit 0
            ;;
    esac
done
