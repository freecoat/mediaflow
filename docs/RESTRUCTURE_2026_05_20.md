# Ristrutturazione architetturale JCL → CR → Fatturazione → Cashflow

**Data**: 2026-05-20 · **Stato**: draft per validazione · **Autore**: Matteo + Claude
**Riferimento memory**: `project_bug_acconti_2026_05_20`, `project_backlog_sconti_quote_cr_fatturazione`, `project_dam_physical_assets`

## 1. Visione

Separare nettamente 2 nature semantiche del listino:
- **Lavorazioni** (time-based): consumo ore/giorni, costo da assignment, maturato derivato da booking done.
- **Consegne** (qty/volume/manual): prodotto consegnato al cliente, costo da ore linkate, maturato manuale (+ link asset per verifica).

Asset fisici (LTO/HDD/Drive) restano canale a parte: acquisto vendor + ricarico cliente, 1:1 progetto.

## 2. Workflow standard A-M

| Step | Azione | Owner | Note |
|---|---|---|---|
| A | Crea Cliente | account/admin | esistente |
| B | Crea Project → Client | account | esistente |
| C | Crea Quote → Project | account | esistente, mantiene `category_discounts`/`package_discount` |
| D | Approva Quote → auto-Job | sistema | convert: unit time-based → JCL, altre → JobDeliverable |
| E | Crea Lavorazioni e Deliverable | auto (D) o phantom (Z) | reverse-flow esistente esteso a deliverable |
| F | CR view = aggrega JCL + JobDeliverable | view-only | rendering separato per natura |
| G | Booking pianificazione | operator/producer | link M:N JobDeliverable |
| H | Trasmissione maturato → batch | producer/account | JCL: ore done; Deliverable: manuale |
| I | Approva batch fatturazione | account/admin | crea slices, lock periodi |
| L | Emit Invoice da batch | account | snapshot fiscali |
| M | Cashflow monitora | account/admin | aggrega tutto |

## 3. Modello dati

### 3.1 Modifiche entità esistenti

**JobCostLine (JCL)** — solo lavorazione oraria
- VINCOLO: `unit ∈ {hr, day}` SEMPRE
- Rimuovere flag `external_outsourced` (migra a JobDeliverable unit `lump`)
- Rimuovere regola binary `quantity_actual=quantity_quoted` per non time-based in `cost_line_sync.py:386` (sostituita da workflow Deliverable)
- Maturato = ore_done × unit_price (deterministico)
- Costo = Σ assignment_hours × cost_rate (da snapshot α.167)

**JobDeliverable** — esistente, estesa
- `quantity_planned: float` (esistente, default 1.0)
- `quantity_delivered: float` (default 0.0) — incrementato manualmente o via auto-link
- `unit_price: float` — copia da QuoteLine al convert
- `total_quoted: float` = quantity_planned × unit_price
- `total_accrued: float` = quantity_delivered × unit_price
- `total_cost_accrued: float` — Σ (booking_hours × rate) ripartito sui deliverable linked al booking
- `status: enum` (pending / in_progress / delivered / rejected) — esistente
- `unit: enum` (pc / TB / allow / shot / lot / lump / version / fix / GB / ...) — esistente, esteso
- `nature: enum` (deliverable_qty / deliverable_volume / manual_allow) — NUOVO, deriva da unit
- `confirmed_at: datetime, confirmed_by_user_id: int` — audit
- `billing_status: enum` (not_billed / in_batch / billed / paid / lost) — uguale JCL
- `billing_batch_id: int FK` — uguale JCL
- `billed_amount: float` — uguale JCL
- `linked_asset_ids: array` o tabella pivot `deliverable_assets` — multi-link verifica

**REGOLA spawn deliverable (revisione α.172.14)** — dipende da `unit_nature`:
- `deliverable_qty` (pc/lot/shot/version) → **N row, 1 per unità**.
  Es. QuoteLine "DCP Master" qty=3 pc → 3 JobDeliverable separati (qty_planned=1 each).
  Permette link 1:1 deliverable→asset + conferma indipendente.
- `deliverable_volume` (TB/GB) → **1 row aggregato**, qty_planned = qty quote.
  Es. QuoteLine "Backup LTO" qty=10 TB → 1 JobDeliverable qty_planned=10.0.
  qty_delivered incrementato cumulativamente via MHL Yoyotta / CSV LTO / fill manuale.
- `manual_allow` (allow/lump/fix) → **1 row aggregato**, qty_planned = qty quote.
  Forfait per definizione, 1 sola conferma manuale producer.
- `external_outsourced=True` (legacy flag su JCL) → **1 row** unit forzato a `lump`,
  qty_planned = qty quote (outsourcing è 1 entità fatturabile).

**Booking** — link M:N deliverable
- RIMUOVERE: `booking.job_deliverable_id` (FK singolo)
- AGGIUNGERE pivot `booking_deliverables`:
  - `booking_id`, `job_deliverable_id`, `sort_order`, `created_at`
- Cost split rule: per ogni booking con N deliverable linkati, costo aggiuntivo per ogni deliverable = `(booking_total_cost / N)`. Maturato deliverable resta indipendente (confermato manualmente).

**Asset (digital)** — solo verifica, no cost
- `Asset.cost_internal = 0` SEMPRE (vincolo modello)
- Linkabile a JobDeliverable via pivot `deliverable_assets` (M:N — un asset può servire più deliverable, raro ma possibile)
- Producer linka asset → JobDeliverable.confirmed_at popolato (verifica completata)

**PhysicalAsset** — 1:1 progetto
- DROP `AssetMembership` (era N:M)
- `PhysicalAsset.project_id` UNIQUE per asset (se serve cross-project, è asset DIVERSO)
- Costo da SupplierInvoice via `resource_id` o `physical_asset_id` (TBD link diretto)
- Ricarico: `unit_price` finale = vendor_cost × (1 + project.shipping_markup_pct/100), pattern esistente α.94

### 3.2 Entità nuove

**`booking_deliverables`** (pivot M:N)
```python
class BookingDeliverable(Base):
    __tablename__ = "booking_deliverables"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    job_deliverable_id: Mapped[int] = mapped_column(ForeignKey("job_deliverables.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("booking_id", "job_deliverable_id"),)
```

**`deliverable_assets`** (pivot M:N — verifica)
```python
class DeliverableAsset(Base):
    __tablename__ = "deliverable_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_deliverable_id: Mapped[int] = mapped_column(ForeignKey("job_deliverables.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    physical_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("physical_assets.id", ondelete="SET NULL"), nullable=True)
    confirmed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    source: Mapped[str] = mapped_column(String(20))  # manual | mhl_yoyotta | csv_lto | fs_scan
```
NOTA: XOR `asset_id` XOR `physical_asset_id` (uno dei due valorizzato, mai entrambi).

**`deliverable_specs`** (tabella specifiche richiamabile in booking)
```python
class DeliverableSpec(Base):
    """Spec tecnica del deliverable (codec, naming, target, ecc.).
    1 deliverable può avere 1 spec; riusabile cross-deliverable nello stesso job/project.
    Estensione granulare di DeliveryTemplate (che è quote-level)."""
    __tablename__ = "deliverable_specs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_deliverable_id: Mapped[int] = mapped_column(ForeignKey("job_deliverables.id", ondelete="CASCADE"), index=True)
    codec: Mapped[Optional[str]]
    resolution: Mapped[Optional[str]]
    framerate: Mapped[Optional[str]]
    color_space: Mapped[Optional[str]]
    audio_config: Mapped[Optional[str]]
    naming_convention: Mapped[Optional[str]]
    target_size_tb: Mapped[Optional[float]]  # per nature=deliverable_volume
    target_broadcaster: Mapped[Optional[str]]
    notes: Mapped[Optional[str]]
    template_id: Mapped[Optional[int]] = mapped_column(ForeignKey("delivery_templates.id"), nullable=True)
```

**`deliverable_billed_slices`** (parallelo a JCLBilledSlice)
```python
class DeliverableBilledSlice(Base):
    """Snapshot immutabile della qty_delivered fatturata per un deliverable
    in un batch. Lock anti-modifica analoga a JCLBilledSlice."""
    __tablename__ = "deliverable_billed_slices"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(default=1, index=True)
    job_deliverable_id: Mapped[int] = mapped_column(ForeignKey("job_deliverables.id"), index=True)
    billing_batch_id: Mapped[int] = mapped_column(ForeignKey("billing_batches.id"), index=True)
    quantity_billed: Mapped[float]  # qty_delivered al momento del batch
    billed_amount: Mapped[float]
    period_start: Mapped[date]
    period_end: Mapped[date]
    created_at: Mapped[datetime]
```

**`vfx_shots`** (anchor point — schema minimo, logica TBD)
```python
class VFXShot(Base):
    __tablename__ = "vfx_shots"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_deliverable_id: Mapped[int] = mapped_column(ForeignKey("job_deliverables.id"), index=True)
    code: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id"), nullable=True)
    notes: Mapped[Optional[str]]
```

### 3.3 Tassonomia `unit` (configurabile)

Tabella `pricelist_units` (NUOVA, seed-loaded):

| Code | Label | Nature | JCL/Deliverable | Auto-fill |
|---|---|---|---|---|
| `hr` | Ora | time_based | JCL | booking done |
| `day` | Giorno | time_based | JCL | booking done |
| `pc` | Pezzo | deliverable_qty | Deliverable | manuale (+ asset link verifica) |
| `lot` | Lotto | deliverable_qty | Deliverable | manuale |
| `shot` | Shot | deliverable_qty | Deliverable + VFXShot anchor | manuale (futuro asset) |
| `version` | Versione | deliverable_qty | Deliverable | manuale |
| `TB` | Terabyte | deliverable_volume | Deliverable | MHL Yoyotta + manuale |
| `GB` | Gigabyte | deliverable_volume | Deliverable | manuale |
| `allow` | Allowance | manual_allow | Deliverable | manuale only |
| `lump` | Lump sum | manual_allow | Deliverable | manuale (incluso ex external_outsourced) |
| `fix` | Forfait | manual_allow | Deliverable | manuale |

UI: editor listino mostra `nature` derivata + `unit_label` editabile. Convertibile post-create se nessuna QuoteLine la usa.

## 4. Regola cost allocation booking → deliverable

Booking con N deliverable linkati + assignment con cost (resource hours):

```
booking_total_cost = Σ (assignment_hours × cost_rate_snap)  # esistente
per ogni deliverable D in booking_deliverables:
    D.total_cost_accrued += booking_total_cost / N
```

Implementazione: hook `recompute_cost_for_booking` (nuovo) chiamato dopo mutazione booking/assignment. Idempotente: ricomputa SEMPRE da zero (azzera cost dei deliverable linkati, ricalcola somma).

NOTA: Il booking continua a fare cost-side influence sulla JCL `job_cost_line_id` (se presente). I 2 sistemi coesistono:
- JCL cost = ore × rate (full)
- Deliverable cost = quota da booking SE booking ha JCL E ha deliverable_links
- Per evitare double-count revenue: maturato JCL = ore × unit_price (revenue lavorazione); maturato Deliverable = quantity_delivered × unit_price (revenue consegna) — sono entità DIVERSE che cliente paga separatamente.

## 5. Phantom quote (Z) esteso a Deliverable

Pattern reverse-flow esistente:
- Booking su progetto senza quote OR su voce non in quote → spawn phantom quote standby
- Estensione: deliverable extra (non in quote originale) → riga phantom quote con `unit` non-time-based + JobDeliverable creato linkato

Idempotency / merge: invariato (1 phantom quote per progetto).

## 6. Cascade hard-delete progetto (admin-only)

Endpoint: `DELETE /admin/projects/{id}/hard-delete`
Body: `{"confirm_token": "DELETE-{project.code}"}` (anti-misclick)
RBAC: `RequireAdmin` (solo role=admin, no manager)

Ordine cascade (FK-safe, top-down):
```
1. ai_messages (via conv→project), ai_actions, ai_conversations
2. notifications (filter payload.project_id = X)
3. booking_changes, booking_deliverables, booking_assignments
4. bookings (job IN project OR project_id direct su phantom)
5. timesheets, job_resource_assignments, time_punches (project_id direct)
6. deliverable_billed_slices, jcl_billed_slices
7. advance_payment_consumptions, advance_payment_allocations, advance_payments
8. quote_advance_allocations, quote_advance_schedules
9. invoice_payments, invoice_lines, billing_batch_lines
10. invoices, billing_batches, loss_entries (FULL CASCADE, no archivio orfane)
11. job_cost_lines
12. deliverable_assets, deliverable_specs, vfx_shots, job_deliverables
13. jobs
14. quote_lines, quotes
15. asset_access_logs, asset_movements, assets, ingest_batches, physical_assets
16. anomaly_entries, project_access_grants, project_tech_sheets, project_milestones
17. projects
```

Tutto in singola transazione (`db.begin()` esplicito), rollback su errore.

Test-only use, NO production. Conferma: solo per debug/test, non per produzione standard.

## 7. Migration plan (step-by-step)

### Sprint 1 — Schema + backfill
1. Migrazione SQL: ADD `booking_deliverables`, `deliverable_assets`, `deliverable_specs`, `deliverable_billed_slices`, `vfx_shots`, `pricelist_units`
2. ADD columns su `job_deliverables`: quantity_delivered, unit_price, total_quoted, total_accrued, total_cost_accrued, nature, confirmed_at, confirmed_by_user_id, billing_status, billing_batch_id, billed_amount
3. Backfill: per JCL esistenti con unit ∈ non-time-based → spawn 1 JobDeliverable per `quantity_quoted` (1 row per qty). Cascade bookings esistenti: if `booking.job_cost_line_id` punta a JCL non-time → migrate a `booking_deliverables[0]` (primo deliverable spawnato).
4. DROP `AssetMembership` (dopo verifica zero cross-project)
5. DROP `Booking.job_deliverable_id` (dopo migrazione pivot)
6. Migrazione `JCL.external_outsourced=True` → JobDeliverable unit `lump`, total_quoted preservato

### Sprint 2 — Service layer
1. `cost_line_sync.py`: rimuovere branch binary (linee 386-393), JCL solo time-based
2. Nuovo `deliverable_cost_sync.py`: cost split booking → N deliverable linkati
3. Estendere `reverse_quote.py` per deliverable extra
4. Hook hard-delete in nuovo `project_purge.py` (riusabile da admin endpoint)

### Sprint 3 — Endpoint
1. `DELETE /admin/projects/{id}/hard-delete`
2. `POST /jobs/{id}/deliverables/{did}/confirm-delivery` (+ optional asset_id)
3. `POST /bookings/{id}/link-deliverable` (M:N add)
4. `POST /ingest/yoyotta-mhl` (upload MHL → parse → spawn PhysicalAsset + auto-link Deliverable)
5. `POST /ingest/csv-lto` (CSV alternativo)

### Sprint 4 — UI
1. Editor quote: tab "Lavorazioni" (JCL) + tab "Consegne" (Deliverable) separati
2. CR detail: sezione "Lavorazioni" e "Consegne" con regole maturato distinte
3. Booking modal: multi-select deliverable da linkare
4. Pagina "Consegne progetto": kanban deliverable per status + link asset
5. Listino: editor `unit` con `nature` derivata + modificabile

### Sprint 5 — Migration UX
1. Tool one-shot "Sposta voce X in deliverable" per quote storiche
2. Notifica admin "Hai JCL non-time-based: migrare a Deliverable?" (warning post-migration)

## 8. Decisioni finali (2026-05-20 sessione)

### 8.1 Advance Payment allocation per Deliverable
**Scelta**: tabella separata `advance_payment_deliverable_allocations` parallela a `advance_payment_allocations` (per JCL). NO polimorfismo. Stessi campi (advance_payment_id, amount, pct, sort_order) + FK a `job_deliverables.id`.

Ragione: coerenza con DeliverableBilledSlice (stesso pattern), FK strong, evita edge case SQLAlchemy single-table inheritance, query CR/finance restano semplici (no UNION forzata).

UI: modal "Acconto applicato a..." mostra entrambe le liste (JCL + Deliverable) con tab o sezioni.

### 8.2 Sconti category/package — spalmati proporzionali DENTRO sezione

Quote denormalized:
- `subtotal_gross_jcl` = Σ QuoteLine.qty × unit_price con unit time-based
- `subtotal_gross_deliverable` = Σ QuoteLine.qty × unit_price con unit non-time-based
- `subtotal_gross` = somma totale (mantiene back-compat)

Apply discount cascade SEPARATA per sezione:
```python
for section in (jcl_lines, deliverable_lines):
    section_subtotal = sum(qty × unit_price × (1-line_discount) for line in section)
    cat_bucket = group_by_category(section)
    section_after_cat = sum(b × (1-cat_disc[cat_key]) for cat_key, b in cat_bucket.items())
    section_after_package = section_after_cat × (1 + package_discount)
```

Cliente vede in PDF:
- Sezione "Lavorazioni": subtotal + sconti applicati separati
- Sezione "Consegne": subtotal + sconti applicati separati
- Total quote = somma 2 sezioni post-sconti

Audit completo in sprint dedicato (memory `project_backlog_sconti_quote_cr_fatturazione`).

### 8.3 Cashflow forecast horizon — configurabile default 90gg

UI: dropdown horizon `[30 | 90 (default) | 180 | 365 | custom]` salvato per-utente (`UserSettings.cashflow_horizon_days`).

Visualizzazione:
- Sub-categorie SEPARABILI (toggle UI per filtrare):
  - JCL maturato (lavorazioni done)
  - Deliverable confermato (consegne delivered)
  - Acconti pendenti (AP status=pending|invoiced)
  - Fatture emesse non incassate (Invoice.status=sent + amount_paid<total)
  - Fatture passive da pagare (SupplierInvoice non paid)
  - Stipendi previsti (da WorkingHoursPolicy + Resource employee)
  - Costi ricorrenti (OverheadCost)
- Vista aggregata OPZIONALE (totale entrate/uscite per giorno-settimana-mese, sub-categorie nascoste)

Toggle "Sub-categorie separabili" / "Aggregato totale" salvato per-utente.

### 8.4 Migration backfill — autospawn

JCL esistenti con unit non-time-based → spawn 1 JobDeliverable per ogni `quantity_quoted` unità.
Cascade `booking.job_cost_line_id` → `booking_deliverables` (primo deliverable spawnato).
Log dettagliato per audit post-migrazione.

## 9. Open items minori / future sprint

- [ ] **AI capabilities**: nuove `propose_confirm_deliverable`, `propose_link_asset_to_deliverable`. Da registrare in registry.
- [ ] **Bug acconti** (memory `project_bug_acconti_2026_05_20`): risolto strutturalmente:
  - Bug 1 allocation: PUT advance-schedules accetta `allocations`; materialize considera anche Deliverable
  - Bug 2 maturato fantasma: rimosso branch binary (regola time-based only su JCL)

## 9. Riferimenti memoria

- `project_bug_acconti_2026_05_20` — Bug 1+2 da fixare nel restructure
- `project_backlog_sconti_quote_cr_fatturazione` — sconti da incrociare
- `project_dam_physical_assets` — PhysicalAsset 1:1 confermato
- `project_reverse_quote_flow` — phantom Z esteso
- `project_costreport_vs_timesheet` — CR=Booking-driven mantenuto per JCL
- `feedback_soft_delete_unique_bypass` — hard-delete deve mascherare anche soft-deleted
- `feedback_auto_migrate_columns` — ricordati di aggiornare `_auto_migrate_columns` per nuove colonne
