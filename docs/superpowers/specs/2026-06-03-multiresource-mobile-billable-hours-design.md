# Design — Multi-risorsa su mobile + policy ore fatturabili

> Data: 2026-06-03
> Versione base: 3.5.0-alpha.172.178
> Stato: approvato da Matteo (design dialogue), pronto per writing-plans

## Problema

1. Il booking mobile (`booking_new.html`) permette **una sola risorsa**. Su desktop si possono assegnare più risorse a un booking.
2. Esiste una regola di pairing (`_classify_assignments_pairing`, planning.py) che genera un warning soft `SINGLE_TYPE_WARNING` quando un booking ha SOLO risorse umane o SOLO risorse tecniche (manca l'appaiamento umana+sala/equipment). Su mobile, avendo 1 sola risorsa, il warning scatta **sempre** e l'utente può solo bypassarlo — non può mai soddisfarlo creando un mix.
3. La regola di conteggio delle **ore fatturabili al cliente** con più risorse umane è oggi hardcoded a `max` (`_booking_billable_hours`, cost_line_sync.py). Non sempre corretta: due operatori in parallelo possono dover fatturare entrambi (somma), oppure una sola risorsa definisce le ore (specific), oppure il producer vuole digitarle a mano (manual).

## Contesto codice (stato attuale)

Tre concetti di "ore" già distinti e separati in `app/services/cost_line_sync.py`:

| Concetto | Funzione | A cosa serve | Regola attuale |
|---|---|---|---|
| Ore fatturabili (cliente) | `_booking_billable_hours` | `quantity_actual` → maturato fatturato | se ≥1 umana → `max(somma-ore per risorsa umana)`; else `max` tra non-umane. Mai somma umana+sala |
| Costo interno | loop assignment × rate in `recompute_cost_line_actual` | `total_cost_accrued` | somma TUTTI gli assignment (umana+sala+equipment) × `cost_rate_snap` (fallback `internal_cost_hourly`) |
| Ore pesate (OT) | `_booking_hours_weighted` | solo se `Job.weighted_revenue=True` | moltiplicatori CCNL/festivo/straordinario sulle ore done |

`HUMAN_RESOURCE_TYPES = {"person_internal", "person_freelance", "person"}`.

Conversione ore→quantità unit via `HOURS_PER_UNIT` (hr=1, day=8, turno=3). Le JCL sono SOLO time-based dopo il restructure α.172; le voci non-time vivono su `JobDeliverable`.

Pattern gate esistente da riusare come riferimento: `force_single_type` (planning.py:1279/1363, global.js:612, booking_new.html:129) — 422 `SINGLE_TYPE_WARNING` → conferma → retry con param.

## Decisioni di design (dal dialogo)

- **D1** — La scelta di conteggio ore vive **per-booking** (non per-JCL, non globale). Massima precisione: ogni sessione può avere dinamiche diverse.
- **D2** — Opzioni di conteggio: `max` (una principale, altre assistono), `sum` (tutte in parallelo, fatturano tutte), `specific` (una risorsa definisce le ore), `manual` (producer digita le ore). Default sempre `max`.
- **D3** — **Niente prompt bloccante** per la scelta modalità: controllo **inline nel modal** del booking — mostra il totale ore generato live + il selector modalità, default `max`. Visibile solo quando ci sono ≥2 risorse **umane**.
- **D4** — Le opzioni di conteggio impattano **solo le ore fatturabili al cliente**. Il **costo interno** continua a sommare sempre tutti gli assignment (non in discussione).
- **D5** — Edit durata da parte di un operatore: **ricalcolo silenzioso** (opzione A). Il cost report è la fonte di verità, il producer lo vede lì. Nessuna notifica, nessun flag stale. La modalità `manual` persiste finché il producer non la cambia (un edit durata operatore NON tocca il valore manuale).
- **D6** — Booking già fatturato (esiste `JCLBilledSlice`) → HARD-BLOCK 409 esistente, invariato.
- **D7** — Preview del totale ore: **endpoint server** (`compute_billable_hours` autorevole), non calcolo client-side, per evitare drift JS-vs-server.

## Architettura

### §1 Modello dati — `Booking` (app/models/models.py)

Tre colonne nuove:
- `billable_hours_mode: Mapped[str]` default `'max'` — valori `max | sum | specific | manual`
- `billable_hours_resource_id: Mapped[Optional[int]]` FK `resources.id` nullable — usata se mode=`specific`
- `billable_hours_manual: Mapped[Optional[float]]` nullable — usata se mode=`manual`

Default `'max'` su tutte le righe esistenti → comportamento identico a oggi.

### §2 Calcolo — refactor single-source (cost_line_sync.py)

Nuova funzione pura:
```python
def compute_billable_hours(items, mode, specific_rid=None, manual=None) -> float:
    """items = list[(resource_id:int, rtype:str, hours:float)]"""
    # mode == 'manual' → ritorna float(manual or 0)
    # aggrega ore per resource_id (somma slot stessa risorsa: smart_split AM+PM)
    # split human_by_res / nonhuman_by_res via HUMAN_RESOURCE_TYPES
    # se nessuna umana → max(nonhuman_by_res.values()) (mode ignorato, invariato)
    # mode == 'specific' → ore aggregate della specific_rid (0 se assente)
    # mode == 'sum'      → sum(human_by_res.values())
    # mode == 'max' (default) → max(human_by_res.values())
```

`_booking_billable_hours(b)` diventa thin wrapper: costruisce `items` da `b.assignments` (resolve rtype dalla relationship `resource`), legge `b.billable_hours_mode/_resource_id/_manual`, delega a `compute_billable_hours`. Comportamento con default `max` = identico all'attuale.

Nessun'altra modifica a `recompute_cost_line_actual`: continua a usare `_booking_billable_hours` per le ore-cliente e il loop assignment×rate per il costo interno.

Edge: se mode=`specific` ma la risorsa scelta non è più tra gli assignment (rimossa) → 0 ore-cliente; il producer lo vede nel preview e nel cost report (coerente con D5).

### §3 Endpoint preview (app/routers/planning.py)

`POST /planning/api/bookings/preview-billable`
- Input (Form): `assignments` (JSON, stesso shape del create), `billable_hours_mode`, `billable_hours_resource_id?`, `billable_hours_manual?`
- Risolve i `rtype` delle risorse dagli `resource_id`, costruisce `items`, chiama `compute_billable_hours`.
- Output JSON: `{ "billable_hours": float, "human_count": int, "breakdown": [{resource_id, name, rtype, hours}] }`
- Scope/tenant: stesso guard degli altri endpoint planning. Read-only (nessuna scrittura).

### §4 UI desktop — modal booking (planning.html)

Nel modal di creazione/modifica booking, blocco visibile **solo se ≥2 assignment umani**:
- riga "Ore fatturabili: **Xh**" aggiornata live via §3 (debounce 200ms al cambio di durata/risorse/modalità)
- selector modalità (radio o select), default **Max**
  - `specific` → dropdown delle sole risorse umane del booking
  - `manual` → input numerico ore
- al submit, i campi `billable_hours_mode/_resource_id/_manual` vanno nella FormData del create/update booking.

0-1 umana → blocco nascosto, nessun campo inviato (server usa default `max`).

### §5 UI mobile — `booking_new.html`

- `<select id="bn-resource">` → **multi-select** (lista di checkbox/righe selezionabili delle risorse attive). Submit costruisce `assignments` con N elementi, ciascuno con la stessa `date/start/end`.
- stesso blocco di §4 (totale ore live via §3 + selector modalità) quando ≥2 umane.
- il gate `SINGLE_TYPE_WARNING` resta invariato — ora però è soddisfabile scegliendo un mix umana+sala in un solo booking (risolve il problema 2).
- riusa `mClear`/`mapi`/`mToast` esistenti.

### §6 Migrazione + boot

- Script `scripts/migrate_billable_hours_mode.py` — ALTER TABLE idempotenti (pattern `migrate_phase1bis.py`): aggiunge le 3 colonne se mancanti, backfill `billable_hours_mode='max'`.
- Check in `_auto_migrate_columns()` del lifespan in `main.py` (lezione auto-migrate: colonna senza check al boot = crash se l'utente non lancia la migrazione).
- Voce nello strumenti.bat/sh se coerente col pattern delle altre migrazioni.

### §7 RBAC

Modificare `billable_hours_mode` è parte della mutazione booking (create/update) → passa dal gate di permesso già esistente sui mutator booking (`booking_mutate`/permesso planning). Nessun permesso nuovo.

## Test

- **Unit `compute_billable_hours`**: 1 umana; 2 umane mode=max; 2 umane mode=sum; mode=specific (presente e assente); mode=manual; solo non-umane (mode ignorato, max); smart_split stessa risorsa AM+PM (sum per risorsa prima dell'aggregazione); 0 ore / assignment senza date.
- **Endpoint preview**: payload multi-risorsa → `billable_hours` atteso per ogni modalità; tenant/scope enforce.
- **Integrazione `recompute_cost_line_actual`**: cambiando mode su un booking done, `quantity_actual`/`total_accrued` cambiano come atteso; `total_cost_accrued` (costo interno) **invariato**.
- **Migrazione**: idempotente (doppio run no-op); backfill `max`; boot con DB pre-esistente non crasha.
- **Regressione**: booking esistenti (default `max`) → cost report invariato vs baseline.

## Non-goal (YAGNI)

- Notifiche/flag stale su edit operatore (scartato in D5).
- Modalità per-JCL o policy globale (scartato in D1).
- Cambiare il calcolo del costo interno o delle ore pesate OT (D4).
- Drag/multi-select timeline su mobile (fuori scope, già parcheggiato).

## File toccati (stima)

- `app/models/models.py` — 3 colonne Booking
- `app/services/cost_line_sync.py` — `compute_billable_hours` + wrapper
- `app/routers/planning.py` — endpoint preview + passaggio campi in create/update
- `app/templates/pages/planning.html` — blocco UI modal booking
- `app/templates/mobile/booking_new.html` — multi-select + blocco UI
- `app/static/js/global.js` — eventuale helper preview condiviso (se serve)
- `scripts/migrate_billable_hours_mode.py` — nuovo
- `main.py` — `_auto_migrate_columns`
- test: nuovi file in `tests/`
