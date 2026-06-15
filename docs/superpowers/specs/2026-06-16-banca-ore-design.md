# Banca ore (hour-bank) — Design

> Data: 16 giugno 2026 · Versione target: v3.5.0-alpha.172.222+ · Fase: solo HR (v1)
> Stato: approvato in brainstorming (Matteo, 15 giu). Prossimo passo: implementation plan.

## Problema

Oggi straordinari (OT), permessi/recuperi e giornate sotto l'orario ordinario sono **flussi indipendenti**: l'OT viene calcolato e pesato come costo, il recupero è un'assenza che consuma il bucket ROL, una giornata corta non produce nulla. **Non esiste compensazione** (banca ore / time-off-in-lieu). Manca un saldo straordinari accumulabile e recuperabile.

Riferimento investigazione: `app/services/overtime.py` (calcolo OT on-demand, nessun saldo persistito), `app/services/leave_balance.py` (bucket ferie/rol/permit indipendenti; `recovery` consuma ROL — `leave_balance.py:167`), `app/models/models.py` (`WorkingHoursPolicy` ~L1725, `TimePunch` ~L2344, `ResourceUnavailability` ~L1642 con `UnavailabilityKind.recovery` ~L1631).

## Obiettivo (v1, solo HR)

Registro **banca ore** event-sourced: l'OT si accumula, viene recuperato tramite assenze di recupero e giornate corte, con chiusura mensile obbligatoria che definisce la quota pagata in busta vs quella lasciata a recupero. Il **cost report resta invariato** in v1 (l'OT continua a pesare come oggi alla maturazione). Nessuna integrazione finanza/cashflow in questa fase.

## Decisioni (fissate in brainstorming)

1. **Modello OT**: tutto l'OT confluisce in banca; il pagamento è un **cash-out** deciso al **marker mensile obbligatorio** (la busta del mese non si finalizza senza). Default = recupero, si paga solo la quota cash-out marcata.
2. **Maggiorazione CCNL sull'OT a recupero**: **configurabile per WorkingHoursPolicy** (`recovery_mode`):
   - `ratio_1to1_pay_premium`: banca += ore base (1:1); la maggiorazione viene **pagata** in busta.
   - `weighted_no_pay`: banca += ore **pesate** (ore × maggiorazione); niente pagato.
   - `flat_no_premium`: banca += ore base (1:1); maggiorazione **persa**.
3. **Drawdown (cosa scala la banca)**: assenze esplicite `kind=recovery` **+** giornate timbrate sotto l'orario ordinario (deficit automatico).
4. **Saldo negativo**: ammesso **senza limiti** (ore dovute dal lavoratore, riassorbite da OT futuri).
5. **Architettura**: **ledger event-sourced** (`banca_ore_entries`), saldo = somma; correzioni via righe di rettifica (append-only, immutabile).
6. **Scope**: **solo HR** in v1; cost report invariato.

## Modello dati

### Tabella `banca_ore_entries` (ledger, append-only)
| campo | tipo | note |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK | scope tenant (CURRENT_TENANT) |
| `resource_id` | int FK → resources | solo risorse interne (vedi eligibilità) |
| `entry_date` | date | data competenza del movimento |
| `hours` | float | **firmato**: + accrual, − consumo/rettifica |
| `kind` | enum `BancaOreEntryKind` | `accrual_overtime` · `recovery_leave` · `short_day_deficit` · `manual_adjustment` |
| `source_type` | str nullable | es. `banca_ore_marker` · `resource_unavailability` |
| `source_id` | int nullable | id del record sorgente |
| `period_year` | int | anno competenza (per raggruppi/marker) |
| `period_month` | int | mese competenza 1–12 |
| `note` | str nullable | |
| `created_at` | datetime | |
| `created_by_user_id` | int FK nullable | |

- **Immutabile**: nessun update/delete fisico delle entry. Correzioni = nuova entry `manual_adjustment` (storno). Coerente con l'ethos `JCLBilledSlice`.
- **Saldo risorsa** = `Σ hours` (può essere negativo).
- Indici: `(tenant_id, resource_id)`, `(resource_id, period_year, period_month)`.

### Tabella `banca_ore_markers` (chiusura mensile per risorsa)
| campo | tipo | note |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK | |
| `resource_id` | int FK | |
| `period_year` | int | |
| `period_month` | int | |
| `computed_ot_hours` | float | OT base calcolato nel mese (da `overtime.py`) |
| `cashout_hours` | float | quota OT base pagata in busta (NON entra in banca) |
| `banked_hours` | float | credito accreditato in banca (dopo `recovery_mode`) |
| `premium_paid` | float | maggiorazione pagata in busta (ore o €; vedi sotto) |
| `status` | enum | `open` · `closed` |
| `closed_at` | datetime nullable | |
| `closed_by_user_id` | int FK nullable | |
| `note` | str nullable | |

- **Unico** per `(tenant_id, resource_id, period_year, period_month)` (UNIQUE; rispettare soft-delete bypass se applicabile).
- `premium_paid`: per `1to1_pay_premium` = maggiorazione sulla quota **banked** pagata in busta; per gli altri mode = 0. **Unità: ore-equivalenti di premio** (es. 2h a +25% → `premium_paid = 0,5`); l'eventuale export busta converte in € a valle. Nessun calcolo € in v1.

### WorkingHoursPolicy — nuovi campi
- `banca_ore_enabled` (bool, default `False`) — gate per policy.
- `recovery_mode` (enum `RecoveryMode`, default `ratio_1to1_pay_premium`).

## Calcolo (servizio `app/services/banca_ore.py`)

### Eligibilità
Solo risorse **interne** (`ResourceType.person_internal`, e legacy `person`). Freelance/studio/equipment → banca non applicabile (coerente con `leave_balance.py` eligibility).

### Accrual OT (alla chiusura marker)
1. `compute_month_overtime(resource, year, month)` → riusa `overtime.compute_overtime()` sui punch del mese → `H_ot` (ore base OT) + info maggiorazione (multiplier medio / brackets).
2. Il manager imposta `cashout_hours` ∈ [0, H_ot]. La quota cash-out è pagata in busta come OT pesato normale (payroll) e **non** entra in banca.
3. `banked_base = H_ot − cashout_hours`.
4. Credito banca secondo `recovery_mode`:
   - `1to1_pay_premium`: `bank_credit = banked_base`; `premium_paid = banked_base × (mult−1)`.
   - `weighted_no_pay`: `bank_credit = banked_base × mult`; `premium_paid = 0`.
   - `flat_no_premium`: `bank_credit = banked_base`; `premium_paid = 0`.
   (`mult` = maggiorazione media/bracket dal calcolo OT.)
5. Crea entry `accrual_overtime` `+bank_credit` (source = marker).

### Drawdown recupero (real-time)
All'**approvazione** di `ResourceUnavailability(kind=recovery)` → entry `recovery_leave` `−ore` (ore = `hours_duration` se intra-day, altrimenti giorni × ordinario). **Cambio semantico**: `recovery` attinge ora dalla **banca ore**, non più dal bucket ROL. `leave_balance.py` va aggiornato: `kind=recovery` esce dal conteggio ROL e non figura più come consumo ROL. ROL resta alimentato solo da `permit_rol`.

### Drawdown giornata corta (alla chiusura marker)
Per ogni giorno **lavorativo schedulato** del mese (default Lun–Ven meno festività; riusare l'helper giorni-lavorativi/festività già presente nel progetto, non reinventarlo):
`deficit = max(0, ordinario − lavorato − assenze_giustificate)`
dove `ordinario` = `WorkingHoursPolicy.daily_hours_threshold` della policy applicabile alla risorsa (in v1 **nessun override orario-giornaliero per-risorsa**: non esiste un campo dedicato; se in futuro servisse, va aggiunto esplicitamente), `lavorato` = ore shift dei `TimePunch` del giorno, `assenze_giustificate` = ore assenze approvate del giorno (ferie/permessi/malattia/recupero). Giorni pienamente coperti da assenza o non lavorativi → deficit 0. Per ogni giorno con deficit > 0 → entry `short_day_deficit` `−deficit` (source = marker).

### Ordine e idempotenza
- Recupero: event-driven (approvazione).
- OT + deficit: batch alla chiusura del marker mensile (quando le timbrature sono definitive).
- Ri-chiusura dello stesso mese **bloccata** se già `closed` (richiede riapertura admin che genera storni `manual_adjustment` e rimette `open`).

## Workflow marker mensile

1. UI `/hr` → pannello **Chiusura banca ore**: elenco risorse interne con mesi `open`/non ancora chiusi, con `computed_ot_hours` precalcolato.
2. Manager apre la chiusura di (risorsa, mese): vede OT calcolato, imposta `cashout_hours` (default 0 = tutto a recupero), conferma.
3. Sistema: crea entry `accrual_overtime` + entries `short_day_deficit` del mese, salva marker `status=closed`.
4. **Obbligatorietà**: l'export busta / report HR mensile per le risorse interne è **bloccato** finché il marker del mese non è `closed` (gate esplicito con elenco risorse mancanti).
5. Riapertura (admin): storna le entry del marker via `manual_adjustment` e rimette `status=open`.

## UI (`/hr`)

- **Card "Banca ore"** per risorsa: saldo corrente (h, colorato — verde ≥0, rosso <0) + link ai **movimenti** (tabella ledger: data, tipo, ore, nota, sorgente).
- **Pannello chiusura mese**: tabella risorse interne × mese, stato marker, OT calcolato, azione "Chiudi mese" (modale set cash-out).
- Badge/avviso obbligatorietà nel flusso busta/report.
- i18n: tutte le stringhe nuove in 5 lingue (`it/en/fr/de/es`) in `i18n.js` + `data-i18n` (P1), namespace `banca.*`.

## RBAC
- Nuovo permesso `manage_banca_ore` (chiusura mesi, rettifiche, riapertura) → manager/admin.
- Visualizzazione saldo proprio: staff (riusa gate HR esistente). Visualizzazione saldi altrui: manager/admin.

## Migrazione
- Script idempotente `scripts/migrate_banca_ore.py`: crea `banca_ore_entries` + `banca_ore_markers`, aggiunge colonne WHP (`banca_ore_enabled`, `recovery_mode`).
- Aggiungere le 2 colonne WHP a `_auto_migrate_columns()` (boot) per il pattern auto-migrate.

## Test (TDD)
- `short_day_deficit`: giorno corto, giorno pieno, giorno con assenza piena, weekend/festivo → 0.
- Accrual per i 3 `recovery_mode` (1:1+premio / pesata / secca) con cashout parziale.
- Drawdown recupero (intra-day e a giornate) → entry corretta, ROL non più toccato.
- Saldo = Σ entries, incluso negativo.
- Chiusura marker: crea entries attese, idempotenza (ri-chiusura bloccata), riapertura genera storni.
- Gate obbligatorietà busta finché marker non chiuso.
- Eligibilità: freelance/non-human → no banca.

## Confini di scope (YAGNI, v1)
**Esclusi (futuro)**:
- Integrazione cost report / cashflow (l'OT a recupero resta costo come oggi alla maturazione).
- Scadenza / liquidazione automatica del saldo vecchio (es. CCNL "recupera entro N mesi o paga").
- Soglie/blocchi sul saldo negativo.
- Logica OT settimanale vs mensile oltre a quanto già fa `overtime.py`.

## File toccati (previsione)
- `app/models/models.py` — 2 modelli nuovi + 3 enum + 2 campi WHP.
- `app/services/banca_ore.py` — nuovo (accrual, deficit, drawdown, saldo, chiusura).
- `app/services/leave_balance.py` — `recovery` non consuma più ROL.
- `app/routers/hr.py` (+ eventuale `planning_unavailabilities.py`) — endpoint saldo/movimenti/chiusura + hook approvazione recupero.
- `app/templates/pages/hr*.html` — card saldo + pannello chiusura.
- `app/static/js/i18n.js` — chiavi `banca.*`.
- `scripts/migrate_banca_ore.py` — nuovo. `app/main.py` `_auto_migrate_columns`.
- `tests/test_banca_ore.py` — nuovo.
