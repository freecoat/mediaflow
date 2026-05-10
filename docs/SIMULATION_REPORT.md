# Simulazione MediaFlow — report 2026-05-10 23:08:35

Dataset generato da `scripts/simulate_full.py` per test manuale + verifica affidabilità.

## Counters

| Entità | Count |
|--------|-------|
| `ai_actions` | 14 |
| `ai_actions_applied` | 10 |
| `ai_actions_failed` | 1 |
| `ai_actions_proposed` | 1 |
| `ai_actions_rejected` | 2 |
| `ai_usage_logs` | 5 |
| `billing_batches` | 1 |
| `bookings_done` | 25 |
| `bookings_in_progress` | 0 |
| `bookings_planned` | 14 |
| `bookings_total` | 40 |
| `categories` | 6 |
| `clients` | 4 |
| `departments` | 4 |
| `invoices` | 2 |
| `jobs` | 6 |
| `price_items` | 20 |
| `projects` | 12 |
| `quote_status_approved` | 6 |
| `quote_status_draft` | 4 |
| `quote_status_sent` | 2 |
| `quotes` | 12 |
| `resources` | 30 |
| `slices_billed` | 7 |
| `users` | 1 |

## Issue rilevate

Nessuna. ✅

## Riepilogo DB

- Quote totali: **12** (vedi tabella `quote_status_*` sopra)
- Job totali: **6**
- Booking totali (tenant=1): **40**
- Invoice totali: **2**
- AIAction totali: **14**
- AIUsageLog totali: **5** (costo simulato totale: **$0.1966**)

## Cosa testare manualmente

Login: **admin@mediaflow.it / admin**

1. **Dashboard**: kpi conteggi corretti
2. **/clients**: 4+ clienti (A24, MUBI, Vision, Sky + AI sim)
3. **/projects**: 12+ progetti distribuiti
4. **/quotes**: filtro per status (draft/sent/approved). Aprire una approved e verificare le righe importate da listino
5. **/jobs/{id}**: per il primo job dovrebbe vedersi cost report con `total_accrued > 0` (booking done)
6. **/planning**: timeline con ~80 booking colorati per stato (done/in_progress/planned/tentative). Light mode auto-on dovrebbe scattare
7. **/cost-report**: kpi job + lista filtrabile
8. **/finance**: 1+ fatture paid + 1 cancelled + 1 batch approved
9. **/admin/cestino** (admin): vuoto (nessun soft-delete in seed)
10. **AI usage**: `GET /ai/api/usage?period_days=30&by=model` deve ritornare 5 entry con cache hit ratio

## Scenari per stress slice-lock

Lo script crea 1+ JCLBilledSlice per il job completed (paid). Test:
- Aprire la timeline e provare a spostare un booking dentro il periodo slice → 409
- Stesso da copilot via `propose_move_booking` → ValueError catturato

## Scenari per RBAC

Login con utente non-admin (creare via /admin/users) e provare:
- `POST /quotes/api` → 403 (richiede `edit_quotes`)
- `POST /finance/api/invoices` → 403 (richiede `edit_invoices`)
- `POST /pricelist/api/items` → 403 (richiede `edit_pricelist`)

## Note tecniche

- **Backup pre-simulation** in `db_snapshots/snapshot-presimulation-{ts}.db` (auto)
- **Schema reset**: drop_all + create_all su tutte le tabelle Base
- **Auto-migrate**: chiamato dopo create_tables (ALTER TABLE idempotenti per colonne aggiunte recentemente)

---
_Generato 2026-05-10 23:08:35 da `scripts/simulate_full.py` v1.0_