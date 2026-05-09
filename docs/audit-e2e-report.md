# Audit E2E MediaFlow — 3.5.0-alpha.66.5.2

_Eseguito: 2026-05-09 21:02:34_
_DB isolato: `audit_temp.db` (copia di mediaflow.db)_

## Sintesi
| Esito | Conteggio |
|---|---|
| ✓ OK | 37 |
| ✗ FAIL | 0 |
| ⚠ WARN | 0 |
| – SKIP | 0 |
| **Totale step** | 37 |

## Dettaglio per fase

| Step | Esito | Dettaglio / Errore |
|---|---|---|
| App boot pulito (routes + version) | ✓ OK | 277 routes, version 3.5.0-alpha.66.5.2 |
| DB migrazione bookings.state al boot | ✓ OK | bookings.state presente (migrazione α.66.5 eseguita) |
| Login admin (cookie JWT) | ✓ OK | login OK, token len=141 |
| Reparti pre-esistenti | ✓ OK | 4 reparti, primo: DI / Video (id=1) |
| Crea risorsa | ✓ OK | risorsa #1 creata |
| Crea cliente | ✓ OK | cliente #1 creato |
| Crea progetto | ✓ OK | progetto #1 (TEST-E2E-01) creato |
| Listino pre-esistente (price_items) | ✓ OK | 79 voci listino, primi 2 selezionati: Dailies sync + color + proxy / Dailies QC |
| Crea quote | ✓ OK | quote #1 (Q-E2E-001) creata |
| Aggiungi righe alla quote | ✓ OK | 2 righe aggiunte: [1, 2] |
| Convert quote → Job + JCL | ✓ OK | quote convertita, job #1 |
| Verify JobCostLines auto-create | ✓ OK | 2 JCL auto-create, ids=[1, 2] |
| Crea booking (1 risorsa, 1 giorno) | ✓ OK | booking #1 creato (tentative) |
| Verify state=tentative in DB | ✓ OK | state=tentative, status=tentative, exec=planned — sync coerente |
| PATCH /state → confirmed | ✓ OK | state=confirmed, status=confirmed, exec=planned |
| PATCH /state → in_progress | ✓ OK | state=in_progress, exec=in_progress |
| PATCH /state → done (triggera cost-line sync) | ✓ OK | state=done, jcl quantity_actual=1.125, total_accrued=112.5 |
| PATCH /state → not_done senza reason → 400 | ✓ OK | 400 corretto: motivazione obbligatoria |
| PATCH /state → not_done con reason | ✓ OK | state=not_done, reason='Test risorsa malata' |
| PATCH /state → confirmed (riapri da not_done) | ✓ OK | riaperto, state=confirmed, reason=None |
| Crea booking smart-split (2 segmenti contigui stessa risorsa) | ✓ OK | booking #2 con 2 segmenti: aids=[2, 3] |
| [α.66.5.2] Drag-resize mattina 09-13 → 10-13:30 (NON deve vedere pomeriggio come conflitto) | ✓ OK | drag-resize OK, fratello pomeriggio non blocca |
| [α.66.5.2] Drag-resize che sovrappone strettamente al fratello → 409 chiaro | ✓ OK | 409 con msg chiaro: 'Sovrapposizione con segmento dello stesso booking (#3): 14:00–18:00. Sposta o ri…' |
| [α.66.5.2] Bulk-edit absolute_start/end su smart-split → errore esplicito INTRA-OVERLAP | ✓ OK | bulk respinge correttamente: 'Segmenti smart-split #2 e #3 diventerebbero sovrapposti (stesso orario assoluto …' |
| [α.66.5.2] Bulk-edit shift_minutes +60 su smart-split → entrambi shiftati | ✓ OK | shift +60min OK su smart-split (entrambi i segmenti) |
| AI tools registry esposto (schema) | ✓ OK | 23 capability registrate, tutte le previste presenti |
| Endpoint copilot /ai/api/chat raggiungibile (no provider call) | ✓ OK | endpoint risponde con 200 |
| [α.66.5.1] propose_booking schema menziona BookingState | ✓ OK | description aggiornata: 'Crea un Booking con N risorse su un job. BookingState inizia…' |
| Cost-report aggregati corretti | ✓ OK | total_quoted=800.0, total_accrued=0.0, lines=2 |
| Soft-delete booking smart-split (verifica state=cancelled) | ✓ OK | soft-delete OK, state=cancelled, status=cancelled |
| Restore booking → state=tentative | ✓ OK | restore OK, state=tentative, status=tentative |
| GET /api/diag/scan-duplicate-overlaps | ✓ OK | scanned=2, dirty=0, phantom_h=0.0 |
| GET /api/diag/booking-raw/1 | ✓ OK | booking #1 dump OK, assignments=1, audit_changes=6 |
| Tutti i bookings: state ↔ status+execution_status sono coerenti | ✓ OK | tutti i 2 booking sono coerenti |
| Nessun assignment duplicate-overlap residuo | ✓ OK | DB pulito da duplicate-overlap |
| Job.weighted_revenue colonna esiste (α.65) | ✓ OK | colonna jobs.weighted_revenue presente |
| Quote.parent_quote_id + superseded_by_id (versioning α.39) | ✓ OK | versioning quote presente |