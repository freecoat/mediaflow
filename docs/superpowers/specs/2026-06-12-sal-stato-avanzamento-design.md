# Design — SAL: Stato Avanzamento Lavori (vista finanza)

**Data**: 2026-06-12 · **Versione target**: v3.5.0-alpha.172.217 · **Approvato da**: Matteo (remote, brainstorming)

## Contesto

Manca una vista d'insieme dello stato di avanzamento dei progetti centrata sulle
ore. Il cost-report esistente è money-centric e per-job; il cashflow ragiona per
cassa/scadenze. Il SAL (Stato Avanzamento Lavori) è una vista nuova, **read-only**,
che risponde a: a che punto sono i progetti? quante ore quotate vs pianificate vs
lavorate? chi sta sforando? — più una vista temporale mese/trimestre.

Decisioni Matteo:
- riga principale = **Progetto** (aggrega i job; drill-down sui job)
- **% avanzamento = ore lavorate / ore quotate** (sempre questa formula)
- breakdown generico ad ampia visibilità (il dettaglio fine resta nel cost-report)
- allarme su **ore lavorate o pianificate > ore quotate** a livello job
- pagina dedicata (NON dentro il cashflow), con due viste in tab
- monte ore quotate = SOLO voci a tempo (giorni → ore via policy); voci a corpo escluse

## Pagina `/finance/sal` (gate `view_finance`)

Voce nel menu Finanza "📊 SAL — Avanzamento". Due tab.

### Tab 1 — Per progetto

Lista progetti del tenant (escludendo cestinati), una riga per progetto:
- **Cliente** (Project.client.name)
- **Quotazioni**: numeri+titolo delle Quote collegate ai job del progetto (chip;
  drill nel dettaglio riga)
- **% avanzamento** = ore_lavorate / ore_quotate (barra + numero; 0 se ore_quotate=0)
- **Monte ore**: quotate / pianificate / lavorate (tre numeri)
- **Stato** progetto (badge)
- **Allarme**: 🔴 se in ALMENO un job del progetto `ore_lavorate > ore_quotate_job`
  o `ore_pianificate > ore_quotate_job`; 🟠 warning se ≥90% su almeno un job;
  tooltip elenca i job che sforano
- Filtri: stato progetto, cliente (select), solo-in-allarme (checkbox), ricerca testo
- Ordinabile per % avanzamento / monte ore / cliente

**Drill-down** (apertura riga, fetch on-demand):
- Breakdown **per reparto** (Department: DI/Video, VFX, Audio, Commercial): per
  reparto ore quotate / pianificate / lavorate + mini-%. Reparto risolto da
  `Resource.department` del booking (lavorato/pianificato) e da
  `PriceItem.department` della JobCostLine (quotato). Righe senza reparto → "Altro".
- Lista **job** del progetto: code, titolo, quote, ore q/p/l, %, allarme per-job.

### Tab 2 — Temporale (mese/trimestre)

- Selettore **anno** + granularità **mese | trimestre**
- Tabella per periodo (12 mesi o 4 trimestri) con colonne:
  **ore pianificate, ore lavorate, € fatturato, % avanzamento (lav/pian)** +
  riga TOTALE anno
- Aggregato su tutti i progetti del tenant. Periodo del booking = dal
  `start_datetime` (mese/trim di competenza). Fatturato = Σ Invoice.subtotal
  (no draft/cancelled, TD04 sottratto) per mese di `issue_date`.

## Calcolo ore (servizio `app/services/sal_metrics.py`)

Single source of truth, riusa helper esistenti:
- **ore_quotate(job)**: Σ su JobCostLine a unit-tempo. `unit` in
  {hr, hour, h, ore, ora, day, days, gg, giorno, giorni} (case-insensitive,
  normalizzato). Ore: `quantity_quoted` se unit-ora; Giorni:
  `quantity_quoted × daily_hours` (da WorkingHoursPolicy del job o default 8.0).
  Voci a corpo (pc/TB/forfait/flat…) ESCLUSE.
- **ore_pianificate(job)**: Σ `_booking_billable_hours(b)` (da cost_line_sync) su
  Booking non-cancelled del job.
- **ore_lavorate(job)**: idem ma solo `execution_status == done`.
- **per_department(job)**: stesse tre metriche raggruppate per department_id
  (quotato da PriceItem.department, pian/lav da Resource.department del booking).
- Aggregazione progetto = Σ sui suoi job. % = lavorate/quotate (guard /0).
- Allarme job: `lavorate > quotate or pianificate > quotate` (rosso);
  `max(lavorate,pianificate) ≥ 0.9 × quotate` (ambra) se quotate>0.

Tutte le funzioni tenant-scoped, batch dove possibile (lista progetti: pre-fetch
job+cost_lines+booking in poche query, no N+1).

## Endpoint (`/finance/api/sal/*`, gate view_finance, read-only)

- `GET /finance/api/sal/projects?status=&client_id=&q=&alarm_only=` →
  lista righe progetto (cliente, quotazioni, ore q/p/l, %, allarme, job_count).
- `GET /finance/api/sal/projects/{id}/detail` → breakdown reparto + lista job.
- `GET /finance/api/sal/timeline?year=&granularity=month|quarter` →
  righe periodo (pianificate, lavorate, fatturato, %) + totale.

## UI (`app/templates/pages/sal.html`)

Tab bar (Per progetto / Temporale), filtri, tabella con barre %, badge allarme,
drill-down a riga espandibile (reparto + job). Vanilla JS, helper globali, niente
modelli/migrazioni. Pattern tabella+filtri come cost_report.html.

## Test (TDD)

- sal_metrics: ore_quotate (unit-tempo vs corpo, giorni→ore con policy),
  pianificate/lavorate da booking (done vs non), per_department, allarme
  rosso/ambra/nessuno, progetto = Σ job, guard /0.
- endpoint: shape, filtri, tenant, detail breakdown, timeline mese/trimestre +
  fatturato per periodo.
- E2E `tools/_e2e_sal.py`: progetto con 2 job, booking done/non, voci tempo+corpo,
  fattura → verifica %, monte ore, allarme, breakdown reparto, timeline.

## Fuori scope

Export PDF/Excel del SAL, drill-down oltre il reparto (è il cost-report),
forecast/proiezioni, SAL per singola risorsa, editing (è read-only),
percentuali "fatturato" nel tab1 (solo nel temporale).
