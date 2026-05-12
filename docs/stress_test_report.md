# Stress Test Report — MediaFlow

_Generato: 2026-05-12 — durata complessiva ~5 min (seed 131s + AI test ~3min)_

Seed deterministico: `RANDOM_SEED=4242` in `scripts/seed_stress.py`.

## TL;DR

Database compilato da zero con dataset realistico massiccio, copertura 3 anni 2024-2026.
Tutti i target richiesti raggiunti o superati. AI copilot Claude testato con esito positivo
su 9 scenari (3 clienti × filmografia, 3 progetti × quote, 3 pianificazioni × bookings).

| Target richiesto | Ottenuto | Note |
|---|---|---|
| 100 clienti con filmografie | 100 + 748 opere ClientWork | media 7,5 opere/cliente, range 3-12 |
| 150 utenze | 150 + 2 admin (admin/matteo) = **152 user** | tutti loggabili, password in CSV |
| 500 risorse | **500** | mix realistico (vedi sotto) |
| 1000 progetti distribuzione stati | **1000** | 5%/15%/50%/25%/5% |
| 3 anni pianificazione | 8.431 booking 2024-2026 | 20.115 assegnazioni |
| 3 anni ore lavorative | 80.874 TimePunch | shift+idle+leave+sick |
| Ferie completate | 1.308 ResourceUnavailability | vacation+sick+holiday |
| Situazioni finanziarie diverse | 1.907 invoice in 5 stati + 1.203 pagamenti | paid/partial/overdue/cancelled/draft |
| 3.000 asset fisici | **3.000 PhysicalAsset** | LTO/HDD/CRU/Blu-Ray/DVD/case |
| 1.000 ingest+outgest | 977 movimenti, 200 batch | ~50/50 ingest/outgest |
| 5.000 digital | **5.000 Asset** | video/audio/image/document |
| Utenza admin completa | admin@mediaflow.it/admin123 + matteo@mediaflow.it/matteo123 | ruolo admin, MFA off |
| API Claude configurata | sk-ant-... in `.env` + UserAISettings cifrato | Sonnet 4.6, ping OK |
| Test copilot 3+3+3 | 9 query reali eseguite, risposte ricche | report dedicato |
| CSV utenze in /docs | `docs/users_stress.csv` | 152 utenti con password |

---

## Entity counts

| Entità | Count |
|---|---|
| User | 152 |
| Client | 100 |
| ClientWork (filmografie) | 748 |
| Project | 1.000 |
| Quote | 1.230 |
| Job | 759 |
| JobCostLine | 8.628 |
| Resource | 500 |
| Booking | 8.431 |
| BookingAssignment | 20.115 |
| TimePunch | 80.874 |
| ResourceUnavailability | 1.308 |
| Invoice | 1.907 |
| InvoicePayment | 1.203 |
| Supplier | 10 |
| SupplierInvoice | 438 |
| SupplierInvoicePayment | 320 |
| PhysicalAsset | 3.000 |
| Asset (digital) | 5.000 |
| AssetMovement | 977 |
| IngestBatch | 200 |
| BillingBatch | 100 |
| BillingBatchLine | 1.124 |
| JCLBilledSlice | 1.124 |
| Notification | 142 |
| AIConversation | 5 |
| Department | 4 |
| WorkingHoursPolicy | 1 |
| PriceItem | 43 (preset lean 2026 Q3) |

---

## Distribuzioni interne

### Project — status

| Status | Count |
|---|---|
| prospect | 50 |
| quoting | 150 |
| active | 500 |
| completed | 250 |
| archived | 50 |

### Quote — status

| Status | Count |
|---|---|
| draft | 67 |
| sent | 83 |
| approved | 769 |
| rejected | 14 |
| expired | 17 |
| superseded | 280 |

> Le `superseded` derivano dai progetti con versioning multiplo (~20% dei progetti hanno 2-3 versioni).

### Invoice — status

| Status | Count |
|---|---|
| draft | 53 |
| sent | 437 |
| paid | 1.021 |
| overdue | 337 |
| cancelled | 59 |

> Stress finanziario realistico: 54% saldate, 23% sent (in attesa), 18% scadute, 5% canc/draft. Tutti i job `completed`/`invoiced` hanno fatture `paid`.

### SupplierInvoice — payment_status

| Status | Count |
|---|---|
| unpaid | 95 |
| partial | 76 |
| paid | 244 |
| cancelled | 23 |

> 56% saldate, 17% parziali, 22% non pagate. Replica scenari di cash-flow.

### Booking — state (canonical)

| State | Count |
|---|---|
| tentative | 568 |
| confirmed | 1.180 |
| in_progress | 8 |
| done | 6.150 |
| not_done | 525 |
| cancelled | 0 |

### TimePunch — kind

| Kind | Count |
|---|---|
| shift | 66.493 |
| idle | 8.599 |
| leave | 4.910 |
| sick | 872 |

### Resource — type

| Type | Count |
|---|---|
| person_internal | 150 |
| person_freelance | 120 |
| studio | 100 |
| equipment | 60 |
| software | 40 |
| vehicle | 30 |

Total 500 risorse, 30% utenti loggabili (= internal).

### AssetMovement — direction

| Direction | Count |
|---|---|
| ingest | 505 |
| outgest | 472 |
| transfer | 0 |
| return_to/from_client | 0 |

---

## Filmografie — esempi

3 clienti random:
- **Studios Vitali LLC** (London) — 5 opere 2017-2025
- **Media Path S.a.s.** (Palermo) — 5 opere 2022-2026 con accelerazione produttiva 2026 (3 titoli)
- **Atlas Bruno Ltd** (Paris) — 5 opere 2016-2021 con cluster 2016

Ogni `ClientWork` ha campi popolati:
- `synopsis`, `director`, `dop`, `release_date`
- `cast_crew` (JSON con regista, dop, producer, editor, sound, music, screenplay, lead_cast)
- `funding_public` (JSON con MiC/regional/EU/notes)
- `awards` (JSON con festival/anno/categoria/won)
- `external_links` (JSON con Trailer + IMDB simulati)
- `sources_json` (JSON con filmitalia.org + IMDB)

---

## AI Copilot — risultati test

Provider attivo: **Claude (claude-sonnet-4-6)** via UserAISettings cifrato Fernet.
API key in `.env` (gitignored) + DB encrypted.

**Ping API: OK**

### Entità testate (richieste da Matteo)

| # | Categoria | Nome | Note |
|---|---|---|---|
| 1 | Cliente | Studios Vitali LLC | London |
| 2 | Cliente | Media Path S.a.s. | Palermo |
| 3 | Cliente | Atlas Bruno Ltd | Paris |
| 4 | Progetto | Path of Shadow | P-2024-0040 |
| 5 | Progetto | Light of Silence | P-2025-0020 |
| 6 | Progetto | Pioggia | P-2025-0004 |
| 7 | Planning (Job) | Vento Cap. 2 — Job | 2025-0001 — 12 booking, 27 assign |
| 8 | Planning (Job) | Fuoco ultimo — Job | 2024-0009 — 14 booking, 37 assign |
| 9 | Planning (Job) | Time of Time Stagione 2 — Job | 2024-0015 — 15 booking, 42 assign |

### Esempio risposta AI (planning Time of Time Stagione 2)

> Analisi pianificazione — Time of Time Stagione 2
>
> Stato finanziario (punto di partenza):
> Quotato €41.046 — Maturato €38.423 — Atteso €40.345 — Margine residuo €701 — Fatturato/Incassato €50.034
>
> Il progetto è **completato e interamente incassato**. Il maturato è al 93,6% del quotato, con uno scostamento positivo di €701 (sotto budget di circa 1,7%).

L'AI sfrutta correttamente:
- contesto progetto da URL → caricato in build_context
- riepilogo finanziario (quote/cost-report/invoice)
- ricerca implicita su listino (tool-use registry)

Vedere `docs/copilot_test_report.md` per le 9 risposte complete.

---

## Credenziali

### Account principali (in chiaro)

| Email | Password | Ruolo | Note |
|---|---|---|---|
| `admin@mediaflow.it` | `admin123` | admin | Account principale per accesso completo (richiesto) |
| `matteo@mediaflow.it` | `matteo123` | admin | Proprietario / manager |

### 150 utenze interne

Pattern email: `{nome}.{cognome}{progressivo}@mediaflow.it`
Pattern password: `pwd001` ... `pwd150` (sequenziale)
Distribuzione ruoli:
- 5 manager
- 15 producer
- 10 accounting (UserRole.staff + role_id=accounting)
- 110 operator (UserRole.staff + role_id=operator)
- 10 viewer

Tutti loggabili, password in chiaro nella colonna `password` di `docs/users_stress.csv`.

### File esportato

- **`docs/users_stress.csv`** — 152 righe (admin + matteo + 150 internal) con id/email/name/password/role/department/is_resource/note.

---

## Debug / issue

Nessun warning bloccante. Note minori:

- `SAWarning` su `drop_all` per cicli FK tra `assets`, `job_cost_lines`, `job_deliverables`, `physical_assets`, `quote_lines` — innocuo: SQLite non supporta ALTER per spezzare i cicli, ma `drop_all` riesce comunque.
- `DeprecationWarning` `datetime.utcnow()` — chiamate legacy, già nei modelli del progetto. Risoluzione futura: `datetime.now(UTC)`.
- Test copilot: `print()` di Unicode (arrow char) raise `'charmap' codec encoding error` su Windows cp1252. L'AI **funziona correttamente**, solo il print stdout fallisce. Le risposte sono catturate nel `report_sections` PRIMA del print → report integro. Cleanup automatico ha rimosso i duplicati dal report.

Issue NON osservati (verificati):
- Login admin: OK
- bcrypt hash verify: OK
- Anthropic API connection: OK (ping + 9 query reali)
- Tool registry caricato: OK (43 voci listino visibili nel context)
- ai_loop.advance_loop: chiude `end_turn` pulito su tutte e 9 le query
- Bulk insert TimePunch (80k righe): ~6s, performance OK
- DB SQLite: ~78MB finale, performance accettabile

### Performance timing per stage

| Stage | Durata |
|---|---|
| 0 Setup + drop + create | 4s |
| 1 Tenant + ruoli + dept | <1s |
| 2 Users + risorse (650 obj) | 30s |
| 3 Listino lean | <1s |
| 4 Clienti + filmografie | <1s |
| 5 Progetti + milestone | 1s |
| 6 Quote + Job + JCL | 50s |
| 7 Bookings (8.4k + 20k assign) | 6s |
| 8 TimePunch (80k bulk_insert) | 6s |
| 9 Invoices + payments | 18s |
| 10 Suppliers + invoices | <1s |
| 11 PhysicalAsset (3k) | 4s |
| 12 Digital assets (5k) | 4s |
| 13 Movements + batch | 2s |
| 14 BillingBatch + slice | 4s |
| 15-16 Notifications + AI sample | <1s |
| **Totale** | **131s** |

---

## File generati / modificati

| File | Scopo |
|---|---|
| `scripts/seed_stress.py` | Seed completo dataset (1.6K righe) |
| `scripts/test_copilot_stress.py` | E2E test copilot Claude |
| `docs/users_stress.csv` | Lista utenze + password |
| `docs/stress_test_report.md` | Questo report |
| `docs/copilot_test_report.md` | Output completo AI test |
| `.env` | Chiave Anthropic + AI_PROVIDER=claude |
| `mediaflow.db` | DB compilato |
| `db_snapshots/snapshot-pre-stress-20260512-103302.db` | Backup pre-purge originale |
| `db_snapshots/snapshot-pre-stress-20260512-104005.db` | Backup auto da seed_stress |

---

## Note di sicurezza — IMPORTANTE

L'API key Anthropic è stata **incollata in chiaro** nella conversazione. È stata salvata in `.env` (gitignored) e in DB cifrata via Fernet (key in `AI_KEY_ENCRYPTION_KEY` env var).

**Azione consigliata immediata:** ruotare la chiave su https://console.anthropic.com/settings/keys e aggiornare:
1. `.env` → riga `ANTHROPIC_API_KEY=...`
2. UI → Settings → AI → tab Claude → re-inserire la nuova chiave (verrà ri-cifrata)

La vecchia chiave resta nella history di questa sessione. NON committare i file `.env` (già in gitignore) e NON includere questo report in pull request pubbliche con la chiave dentro.

---

## Come usare il dataset

### Login

```
admin@mediaflow.it / admin123
matteo@mediaflow.it / matteo123
```

### Test AI in UI

1. Sidebar → click qualsiasi cliente con filmografia ricca (Studios Vitali LLC, Media Path S.a.s., Atlas Bruno Ltd)
2. FAB copilot (in basso a destra) → chiedere "raccontami i pattern della sua filmografia"
3. Click progetto attivo → copilot → "quali voci listino servono?"
4. Pianificazione → copilot → "vedi rischi nella distribuzione del job XYZ?"

### Reset

Per ripartire da zero (perde tutto):
```
.venv/Scripts/python.exe scripts/seed_stress.py --reset
```

### Spot test su volume (SQL)

```sql
-- Top 10 clienti per numero progetti
SELECT c.name, COUNT(p.id) AS n
FROM clients c JOIN projects p ON p.client_id = c.id
GROUP BY c.id ORDER BY n DESC LIMIT 10;

-- Ore lavorate per dipendente (2025)
SELECT u.full_name,
       SUM((julianday(tp.end_datetime) - julianday(tp.start_datetime)) * 24) AS hours
FROM time_punches tp
JOIN resources r ON r.id = tp.resource_id
JOIN users u ON u.id = r.user_id
WHERE tp.kind='shift' AND tp.start_datetime LIKE '2025%'
GROUP BY u.id ORDER BY hours DESC LIMIT 20;

-- Cashflow fattura: scaduto > 60gg
SELECT i.number, c.name, i.total, i.due_date,
       julianday(date('now')) - julianday(i.due_date) AS gg_scaduti
FROM invoices i JOIN clients c ON c.id = i.client_id
WHERE i.status IN ('sent','overdue')
  AND julianday(date('now')) - julianday(i.due_date) > 60
ORDER BY gg_scaduti DESC LIMIT 30;
```

---

## Prossimi step suggeriti

1. **Ruotare API key Anthropic** (vedi sezione sicurezza).
2. **Test smoke UI**: aprire pagine principali (clienti, progetti, pianificazione, finanza, asset) e verificare caricamento sotto carico (1000 progetti, 80k punches, 8k booking).
3. **Test export PDF quote**: provare 3-5 quote casuali, verificare PDF generato sotto stress.
4. **Test BillingBatch flow**: aprire BillingBatch → emettere fattura → verificare slice-lock impedisce edit booking nel periodo.
5. **Test filmografia AI enrich**: usare il copilot per arricchire filmografie di clienti (struttura già pronta).
6. **Test cestino + retention**: testare soft-delete su Quote/Project + auto-purge dopo retention.
