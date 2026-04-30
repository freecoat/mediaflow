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
    echo "  [a] Apri cartella upload"
    echo "  [0] Esci"
    echo ""
    read -p "Scegli un'opzione (0-9, a, b, c, d, e, f, g, h, i, j): " scelta

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
        a|A)
            open uploads 2>/dev/null || xdg-open uploads 2>/dev/null
            ;;
        0)
            exit 0
            ;;
    esac
done
