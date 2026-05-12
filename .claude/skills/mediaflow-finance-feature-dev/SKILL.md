---
name: mediaflow-finance-feature-dev
description: Use when implementing financial features in MediaFlow (cashflow, billing, cost-report, invoicing, supplier-invoice, anomalies). Encodes project conventions: tenant scope, RBAC permission gate, soft-delete, AI capability registry, migration pattern, audit-log, JCLBilledSlice immutability. Trigger on tasks like "add cashflow forecast", "new billing batch", "anomaly type", "supplier KPI", "AI capability propose_*", "cost report column".
---

# MediaFlow — Financial feature development

Pattern di riferimento per QUALSIASI feature finanziaria nel repo `mediaflow_fase1bis`. Quando crei nuovo endpoint, modello, AI capability o tab UI in area finanza, segui questa checklist nell'ordine elencato.

## Checklist mandatoria (in ordine)

### 1. Tenant scope su query
Ogni router monta `CURRENT_TENANT = 1` in cima. Ogni `db.query(Model)` parte con `.filter(Model.tenant_id == CURRENT_TENANT)`. Modelli senza tenant_id (es. `Tag`) sono globali — accettati ma rari.

**Modelli a cui SERVE tenant scope (audit α.66.15)**: Tenant, Department, Resource, Client, ClientWork, Project, Quote, QuoteLine, Job, JobCostLine, Booking, BookingAssignment, TimePunch, Invoice, InvoicePayment, Supplier, SupplierInvoice, BillingBatch, BillingBatchLine, LossEntry, JCLBilledSlice, Asset, PhysicalAsset, IngestBatch, AssetMovement, AssetMembership, JobDeliverable, ProjectAccessGrant, AssetAccessLog, AIConversation, AIUsageLog, Notification, ProjectTechSheet, PricelistSnapshot, ResourcePreset, WorkingHoursPolicy, DeliveryTemplate, PriceCategory, PriceItem.

### 2. RBAC permission gate (al router)
Mutator endpoint = `dependencies=[RequireEditXxx]`. Permission keys vivono in `app/services/rbac.py` (PERMISSIONS dict). Aggiungerne uno nuovo:

```python
# app/services/rbac.py
PERMISSIONS = {
  "Finanza": {
    ...
    "approve_billing_batch": ["Approva batch fatturazione"],
  }
}
RequireApproveBillingBatch = Depends(_require_perm("approve_billing_batch"))
```

Then in router: `@router.post("/x", dependencies=[RequireApproveBillingBatch])`.

### 3. Soft-delete (cestino)
Tutti i record di business hanno:
- `deleted_at: Optional[datetime]` (indexed)
- `deleted_by_user_id: Optional[int] FK users`
- Default invisible: SQLAlchemy event listener filtra `deleted_at IS NULL` automaticamente.
- Per query include cestino: `db.execute(stmt.execution_options(include_deleted=True))`.

**Trappola** (vedi memory `feedback_soft_delete_unique_bypass`): auto-numero/progressivi/pre-check unicità DEVONO usare `include_deleted=True`, altrimenti collidono con record cestinati.

### 4. Soft-delete eligible models
Già implementato: Quote, Project, JobDeliverable, Asset, PhysicalAsset, Supplier, SupplierInvoice, PricelistSnapshot.

Da estendere se serve: Job, Invoice (oggi hard-delete via status=cancelled).

### 5. JCLBilledSlice immutability (HARD-BLOCK)
Booking `done` dentro `[period_start, period_end]` di una slice della loro JCL **NON sono editabili** (HTTP 409). Vedi `app/services/billing_slice_guard.py`. Per modifiche: emettere nota credito tramite endpoint dedicato (in roadmap), non bypass.

Quando crei nuovo endpoint che muta Booking, usa `booking_mutate.guarded_mutate(...)` wrapper — fallisce auto su slice-lock.

### 6. Audit log + booking change
Tutti i mutator booking emettono `BookingChange` row (kind=create|update|delete|restore|assignment_*). Pattern in `app/services/booking_mutate.py`.

Per audit financial: BillingBatch e LossEntry sono già self-audited via campi `transmitted_by_user_id`, `approved_by_user_id`, `created_by_user_id`.

### 7. AI capability (propose_*)
Pattern "AI propone, utente dispone":
1. Registra handler in `app/services/ai_capability_registry.py` con decorator `@ai_capability(name="propose_xxx", ...)`.
2. Handler: prende payload dict, applica mutazione, ritorna result dict.
3. Tool schema esportato da `to_anthropic_tools()` per Claude.
4. AI chiama tool → server crea `AIAction status=proposed`.
5. User clicca "Applica" → handler eseguito → `AIAction status=applied`.

**Capability esistenti**: propose_client, propose_project, propose_project_metadata, propose_quote, propose_quote_line, propose_price_item, propose_new_item_and_line, propose_resource_cost_update, web_search.

Per nuova capability finanziaria: `propose_billing_batch`, `propose_anomaly_action`, `propose_cashflow_forecast`, ecc.

### 8. Migration pattern
Niente Alembic. Pattern in `scripts/migrate_*.py`:
- ALTER TABLE idempotenti via raw SQL su SQLite
- Backfill dati nuova colonna
- Idempotente: rerunnable senza errore

Esempio:
```python
def migrate():
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(invoices)"))}
        if "doc_type" not in cols:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN doc_type VARCHAR(8) DEFAULT 'TD01'"))
```

**Trappola** (memory `feedback_auto_migrate_columns`): aggiungere colonna a modello SENZA aggiungere check in `_auto_migrate_columns()` di `main.py` lifespan = crash al boot. Sempre allineare.

### 9. Frontend filtri standard (MFFilterBar v3.5.0-alpha.86)
Per nuova pagina o tab finanziaria, usa `MFFilterBar` in `global.js`:

```html
<div id="xxx-global-filters"></div>
<script>
  MFFilterBar({
    host: document.getElementById('xxx-global-filters'),
    filters: [
      { kind: 'autocomplete', id: 'client_id', label: 'Cliente', data: () => CLIENTS, ... },
      { kind: 'autocomplete', id: 'project_id', label: 'Progetto', dependsOn: 'client_id', ... },
      { kind: 'date', id: 'from_date', label: 'Dal' },
      { kind: 'date', id: 'to_date',   label: 'Al' },
    ],
    onChange: (v) => reload(),
  });
</script>
```

Endpoint server-side accetta `client_id`, `project_id`, `from_date`, `to_date` come Optional query params.

### 10. Notifications
Emit `Notification` row per eventi finanziari rilevanti:
- `extra_after_billed` → producer/manager+accounting (extra emerso su periodo già fatturato)
- `quote_discrepancy_alert` → admin/accounting (sforamenti)
- `job_floating_alert` → admin/accounting (job orfani)

Pattern: `notifications.notify(db, user_id=..., kind=..., title=..., body=..., payload={...})`.

### 11. Test E2E
Pattern stress-test in `scripts/seed_stress.py`:
- `RANDOM_SEED = 4242` deterministic
- TestClient + JWT cookie
- Smoke 200 OK per ogni endpoint nuovo
- Verifica filtri opzionali (`?client_id=X` ritorna ridotto)

### 12. Cache-buster (memory `feedback_cache_buster_static`)
Modifiche a `static/css/main.css` o `static/js/global.js` → bumpa `?v=` in `base.html`. Altrimenti fix non arriva al browser.

### 13. Commit conventions
- Bump versione in `app/main.py` (FastAPI title)
- CHANGELOG.md voce con riassunto
- STATO.md aggiornato (versione corrente + prossimo step)
- Memory `feedback_commit_auto`: commit auto dopo bump
- Memory `feedback_push_solo_major`: push solo a major bump (rare); intermedie commit only

## Anti-pattern da evitare

- **NO JSON.stringify in onclick HTML** — memory `feedback_no_jsonstringify_in_onclick`. Usa `data-*` attributes + addEventListener.
- **NO helper JS ridefiniti** — escapeHtml/fmtCurrency/etc. SOLO in `global.js`. Memory `feedback_global_helpers_centralizzati`.
- **NO ALTER senza auto-migrate** — sempre check in `_auto_migrate_columns()`.
- **NO bypass slice-lock** — emetti nota credito formale, non patch silenzioso.
- **NO commit con .env tracked** — memory `feedback_env_untracked`. `.env` untracked dal 12 mag 2026.

## Riferimenti rapidi

- Modelli: `app/models/models.py` (53 classi)
- Router finanza: `app/routers/finance.py`, `billing.py`, `cost_report.py`, `suppliers.py`
- Service finanza: `quote_forecast.py`, `financial_reports.py`, `billing_slice_guard.py`
- Memory rilevanti: project_billing_roadmap_alpha65plus, project_integrity_invariants, project_costreport_vs_timesheet, project_reverse_quote_flow
