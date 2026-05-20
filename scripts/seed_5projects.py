"""
MediaFlow — seed_5projects.py (v3.5.0-alpha.171.11+)

Test data targeted: cancella tutti i progetti/booking/fatture esistenti
(via reset_business_data) e ricostruisce 5 progetti specifici con stati
operativi/finanziari diversi, ristretti ai reparti DI-VIDEO e AUDIO,
con tutte le lavorazioni compresse in 1 mese.

Stati progetti:
  P1: completamente maturato (tutti i booking done), nessuna fattura.
  P2: come P1 + 2 acconti al 30% l'uno.
  P3: come P1 ma maturato 50% (metà booking done, metà confirmed
      per arrivare al 100% di stima).
  P4: come P2 maturato 50% + booking confermati a riempimento.
  P5: quote in stato sent, nessun job, nessun booking, project quoting.

Risorse: 2 persone DI (Online Editor + Colorist) + 1 sala DI; 1 mixer
freelance Audio + 1 sala mix Audio. Ogni booking standard ha 1 persona
+ 1 sala dello stesso reparto.

Idempotente: rerun ricostruisce da zero. Listino/Tenant/Users/Reparti
preservati dal reset.

Esegui:
  python scripts/seed_5projects.py        # chiede conferma
  python scripts/seed_5projects.py --yes  # senza conferma
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from datetime import date, datetime, timedelta
from sqlalchemy import select

from app.database import SessionLocal, create_tables
from app.models import (
    Tenant, Department, PriceItem, PriceCategory,
    Client, Project, ProjectStatus,
    Resource, ResourceType, ResourceCostType,
    Quote, QuoteLine, QuoteStatus, PriceLevel,
    Job, JobStatus, JobCostLine, JCLBillingStatus,
    Booking, BookingAssignment, BookingStatus, BookingState, BookingKind,
    BookingExecutionStatus, BookingPriority,
    Invoice, InvoiceLine, InvoiceStatus, InvoiceKind, InvoicePayment,
    AdvancePayment, AdvancePaymentStatus, AdvancePaymentAllocation,
)
from app.services.cost_line_sync import recompute_cost_line_actual


# ── CONFIG ──────────────────────────────────────────────────────────

# Finestra temporale: tutte le lavorazioni in 1 mese.
WINDOW_START = date.today() - timedelta(days=20)   # 20gg fa
WINDOW_END   = date.today() + timedelta(days=10)   # 10gg avanti
# Ore standard giornaliere per booking
HOURS_PER_DAY = 8

# Listino di riferimento (nomi voci come da preset lean_2026q3_v1).
# Mix DI-VIDEO + AUDIO. Quantità coerenti con un mese.
QUOTE_TEMPLATE = [
    # (price_item_name, qty, department_code, role_hint)
    ("Online conform",            5,  "DI-VIDEO", "online"),
    ("Color grading SDR",         6,  "DI-VIDEO", "colorist"),
    ("Mastering DCP standard",    1,  "DI-VIDEO", "online"),
    ("Master ProRes 4444 XQ",     1,  "DI-VIDEO", "online"),
    ("Sound editorial day",       4,  "AUDIO",    "mixer"),
    ("Foley session",             2,  "AUDIO",    "mixer"),
    ("Re-recording mix surround", 5,  "AUDIO",    "mixer"),
    ("Surround printmaster / M&E",1,  "AUDIO",    "mixer"),
]
# Totale giorni booking ≈ 25 → ben dentro 1 mese.

# Progetti da seedare
PROJECTS_SPEC = [
    {
        "code": "TEST-001", "title": "Test 1 — Maturato 100%, nessuna fattura",
        "matured_pct": 1.0, "fill_to_100": False, "advances": [],
        "quote_only": False,
    },
    {
        "code": "TEST-002", "title": "Test 2 — Maturato 100% + 2 acconti 30%",
        "matured_pct": 1.0, "fill_to_100": False, "advances": [0.30, 0.30],
        "quote_only": False,
    },
    {
        "code": "TEST-003", "title": "Test 3 — Maturato 50% + fill confirmed 100%",
        "matured_pct": 0.5, "fill_to_100": True, "advances": [],
        "quote_only": False,
    },
    {
        "code": "TEST-004", "title": "Test 4 — Maturato 50% + fill 100% + 2 acconti 30%",
        "matured_pct": 0.5, "fill_to_100": True, "advances": [0.30, 0.30],
        "quote_only": False,
    },
    {
        "code": "TEST-005", "title": "Test 5 — Quote pending, nessun job",
        "matured_pct": 0.0, "fill_to_100": False, "advances": [],
        "quote_only": True,
    },
]


# ── PURGE ───────────────────────────────────────────────────────────

def purge_business_data():
    """Reuse reset_business_data logic (FK-safe purge) + extra orphan tables
    che lo script standard non tocca (advance_payments, billing_batches,
    jcl_billed_slices, supplier_invoices, anomaly_entries, ecc.).
    """
    from scripts.reset_business_data import reset
    rc = reset(confirm=True)
    if rc != 0:
        raise RuntimeError(f"purge failed with rc={rc}")

    # Extra purge per tabelle satellite non incluse in reset_business_data.
    from sqlalchemy import text, inspect
    from app.database import engine
    extra_tables = [
        # Invoice payments (non purgato da reset_business_data, lascia residui)
        "invoice_payments",
        # Acconti
        "advance_payment_consumptions",
        "advance_payment_allocations",
        "advance_payments",
        "quote_advance_allocations",
        "quote_advance_schedules",
        # Billing
        "billing_batch_lines",
        "billing_batches",
        "loss_entries",
        "jcl_billed_slices",
        # Suppliers
        "supplier_invoice_payments",
        "supplier_invoices",
        "suppliers",
        # Assets
        "asset_access_logs",
        "asset_movements",
        "asset_memberships",
        "ingest_batches",
        "physical_assets",
        "job_deliverables",
        # Anomalie / accessi
        "anomaly_entries",
        "project_access_grants",
        # Booking changes (might be referenced)
        "booking_changes",
        # Schedules quote
        "project_milestones",
        # Reverse-flow / phantom audit
        "ai_actions",
        "ai_messages",
        "ai_conversations",
    ]
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    with engine.begin() as conn:
        for t in extra_tables:
            if t in existing:
                conn.execute(text(f"DELETE FROM {t}"))
                if "sqlite_sequence" in existing:
                    conn.execute(text("DELETE FROM sqlite_sequence WHERE name = :n").bindparams(n=t))


# ── HELPERS ─────────────────────────────────────────────────────────

def _next_business_day(d: date) -> date:
    """Sabato/domenica → lunedì successivo."""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _ensure_resources(db, departments):
    """Crea 2 persone DI + 1 sala DI + 1 mixer Audio + 1 sala Audio.
    Idempotente: skip se già presenti (per name)."""
    di_id = departments["DI-VIDEO"].id
    au_id = departments["AUDIO"].id

    existing = {r.name: r for r in db.query(Resource).filter(Resource.tenant_id == 1).all()}

    def ensure(name, **kw):
        if name in existing:
            return existing[name]
        r = Resource(tenant_id=1, name=name, is_active=True, **kw)
        db.add(r)
        db.flush()
        existing[name] = r
        return r

    luca = ensure(
        "Luca Bianchi",
        department_id=di_id, role="Online Editor",
        type=ResourceType.person_internal,
        email="luca.bianchi@mediaflow.it", internal_phone="201",
        hourly_rate=75, daily_rate=600, color="#6272f5",
        cost_type=ResourceCostType.employee,
        monthly_gross_salary=2800, annual_bonus_months=13.0,
        cost_multiplier_oneri=1.30, annual_working_hours=1720,
    )
    sara = ensure(
        "Sara Conti",
        department_id=di_id, role="Senior Colorist",
        type=ResourceType.person_internal,
        email="sara.conti@mediaflow.it", internal_phone="202",
        hourly_rate=100, daily_rate=800, color="#2ec4b6",
        cost_type=ResourceCostType.employee,
        monthly_gross_salary=3500, annual_bonus_months=13.0,
        cost_multiplier_oneri=1.30, annual_working_hours=1720,
    )
    suite_di = ensure(
        "Suite DI 1",
        department_id=di_id, role="Sala DI / Grading 4K HDR",
        type=ResourceType.studio,
        daily_rate=1200, color="#f59e0b",
        cost_type=ResourceCostType.studio, studio_hourly_cost=80,
    )
    davide = ensure(
        "Davide Moretti",
        department_id=au_id, role="Re-recording Mixer",
        type=ResourceType.person_freelance,
        email="davide.moretti@freelance.it", phone="+39 333 1234567",
        hourly_rate=70, daily_rate=550, color="#a855f7",
        cost_type=ResourceCostType.freelance, freelance_hourly_cost=55,
    )
    studio_a = ensure(
        "Studio A — Mixing Stage",
        department_id=au_id, role="Sala mix Dolby Atmos",
        type=ResourceType.studio,
        daily_rate=1800, color="#f43f5e",
        cost_type=ResourceCostType.studio, studio_hourly_cost=120,
    )

    return {
        "online":   luca,
        "colorist": sara,
        "sala_di":  suite_di,
        "mixer":    davide,
        "sala_au":  studio_a,
    }


def _find_price_item(db, name: str) -> PriceItem:
    item = db.query(PriceItem).filter(
        PriceItem.tenant_id == 1, PriceItem.name == name,
    ).first()
    if item is None:
        raise ValueError(f"Voce listino mancante: {name!r}. Esegui prima seed_demo o ripristina preset lean.")
    return item


def _ensure_client(db, name: str, vat: str, contact_email: str) -> Client:
    c = db.query(Client).filter(Client.tenant_id == 1, Client.name == name).first()
    if c:
        return c
    c = Client(
        tenant_id=1, name=name,
        contact_name="Test Producer", contact_email=contact_email,
        vat_number=vat,
    )
    db.add(c); db.flush()
    return c


def _bk_state_sync(b: Booking, state: BookingState):
    """Imposta state + sincronizza status/execution_status (mirror legacy mapping)."""
    b.state = state
    if state == BookingState.tentative:
        b.status = BookingStatus.tentative;  b.execution_status = BookingExecutionStatus.planned
    elif state == BookingState.confirmed:
        b.status = BookingStatus.confirmed;  b.execution_status = BookingExecutionStatus.planned
    elif state == BookingState.in_progress:
        b.status = BookingStatus.confirmed;  b.execution_status = BookingExecutionStatus.in_progress
    elif state == BookingState.done:
        b.status = BookingStatus.confirmed;  b.execution_status = BookingExecutionStatus.done
    elif state == BookingState.not_done:
        b.status = BookingStatus.confirmed;  b.execution_status = BookingExecutionStatus.not_done
    elif state == BookingState.cancelled:
        b.status = BookingStatus.cancelled;  b.execution_status = BookingExecutionStatus.planned


def _make_booking(db, job, jcl, resource_person, resource_room,
                  start_dt: datetime, hours: int, state: BookingState) -> Booking:
    """Crea 1 booking con 2 assignment: persona + sala (stesso slot)."""
    end_dt = start_dt + timedelta(hours=hours)
    b = Booking(
        tenant_id=1,
        job_id=job.id, job_cost_line_id=jcl.id,
        start_datetime=start_dt, end_datetime=end_dt,
        kind=BookingKind.project, priority=BookingPriority.normal,
    )
    _bk_state_sync(b, state)
    db.add(b); db.flush()

    # Assignment persona
    cost_rate_p = resource_person.internal_cost_hourly
    db.add(BookingAssignment(
        booking_id=b.id, resource_id=resource_person.id,
        start_datetime=start_dt, end_datetime=end_dt,
        cost_rate_snap=cost_rate_p,
    ))
    # Assignment sala
    cost_rate_r = resource_room.internal_cost_hourly
    db.add(BookingAssignment(
        booking_id=b.id, resource_id=resource_room.id,
        start_datetime=start_dt, end_datetime=end_dt,
        cost_rate_snap=cost_rate_r,
    ))
    return b


# ── BUILD ONE PROJECT ───────────────────────────────────────────────

def _build_quote_lines(db, quote: Quote):
    """Crea le QuoteLine dal template, ritorna lista di tuple (line, item, role)."""
    rows = []
    subtotal_gross = 0.0
    for idx, (item_name, qty, dept_code, role) in enumerate(QUOTE_TEMPLATE, start=1):
        item = _find_price_item(db, item_name)
        unit_price = item.price_list or 0.0
        total = round(qty * unit_price, 2)
        ql = QuoteLine(
            quote_id=quote.id,
            price_item_id=item.id,
            section="A", position=f"A.{idx}",
            description=item.name, detail=None,
            quantity=qty, unit=item.unit,
            price_level=PriceLevel.list_price, unit_price=unit_price,
            allowance=0, line_discount_pct=0,
            total=total, hardcosts=0,
            sort_order=idx * 10,
        )
        db.add(ql); db.flush()
        rows.append((ql, item, role))
        subtotal_gross += qty * unit_price

    quote.subtotal_gross = round(subtotal_gross, 2)
    quote.subtotal = round(subtotal_gross, 2)
    quote.total_after_discount = round(subtotal_gross, 2)
    quote.total_with_vat = round(subtotal_gross * 1.22, 2)
    db.flush()
    return rows


def _build_project(db, spec: dict, client: Client, today: date, resources: dict, seq: int):
    """Crea Project + Quote + (eventuale) Job/JCL/Bookings + (eventuali) Advances."""

    proj = Project(
        tenant_id=1,
        code=spec["code"],
        title=spec["title"],
        client_id=client.id,
        project_type="feature_film",
        length_minutes=90, fps="24",
        delivery_format="4K-DCI-Scope",
        director="Test Director",
        producer=client.name,
        shoot_start=WINDOW_START - timedelta(days=60),
        shoot_end=WINDOW_START - timedelta(days=30),
        post_start=WINDOW_START,
        delivery_deadline=WINDOW_END + timedelta(days=15),
        status=ProjectStatus.quoting if spec["quote_only"] else ProjectStatus.active,
        description=spec["title"],
        billing_frequency="monthly",
        billing_terms_days=30,
        finance_status="active",
    )
    db.add(proj); db.flush()

    quote_status = QuoteStatus.sent if spec["quote_only"] else QuoteStatus.approved
    quote = Quote(
        tenant_id=1,
        number=f"Q-{spec['code']}-v1", version=1,
        project_id=proj.id, client_id=client.id,
        title=f"{spec['title']} — Quote",
        status=quote_status,
        issue_date=today - timedelta(days=30),
        valid_until=today + timedelta(days=30),
        production_material="ARRI Alexa ProRes 4444",
        length_minutes=90, fps="24",
        delivery_format="4K-DCI-Scope",
        package_discount=0.0, vat_rate=22.0,
        currency="EUR", fx_rate_to_base=1.0,
        payment_terms="30% all'avvio / 30% a metà / 40% a consegna" if spec["advances"]
                      else "30gg fine mese fatturazione mensile",
        notes="Progetto di test E2E (seed 5 progetti).",
    )
    db.add(quote); db.flush()

    rows = _build_quote_lines(db, quote)

    if spec["quote_only"]:
        # Niente job, niente booking, niente JCL.
        return proj, quote, None, []

    # Job + JCL
    job = Job(
        tenant_id=1,
        code=f"J-{spec['code']}",
        title=spec["title"],
        client_id=client.id, project_id=proj.id, quote_id=quote.id,
        status=JobStatus.active,
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        budget_quoted=quote.total_after_discount,
    )
    db.add(job); db.flush()

    jcls = []
    for (ql, item, role) in rows:
        jcl = JobCostLine(
            tenant_id=1, job_id=job.id, quote_line_id=ql.id, price_item_id=item.id,
            description=ql.description,
            quantity_quoted=ql.quantity, quantity_actual=0.0,
            unit=ql.unit, unit_price=ql.unit_price,
            total_quoted=ql.total, total_accrued=0.0, total_expected=0.0,
            is_billable=True, billing_status=JCLBillingStatus.not_billed,
        )
        db.add(jcl); db.flush()
        jcls.append((jcl, ql, role))

    # ── BOOKINGS ─────────────────────────────────────────────
    # Per ogni JCL distribuisci `quantity_quoted` giorni in slot 8h consecutivi.
    # Frazione `matured_pct` dei giorni → state=done. Resto:
    #   - se fill_to_100=True → state=confirmed (riempie a 100% stima)
    #   - se fill_to_100=False → SKIP (no booking residuo): quote 100% matured.
    cursor_date = WINDOW_START
    for (jcl, ql, role) in jcls:
        person = resources["online" if role == "online" else
                           "colorist" if role == "colorist" else
                           "mixer"]
        room = resources["sala_di" if role in ("online", "colorist") else "sala_au"]

        n_days = int(ql.quantity)  # qty è giorni interi nel template
        n_done = int(round(n_days * spec["matured_pct"]))
        n_planned = n_days - n_done if spec["fill_to_100"] else 0

        for i in range(n_done):
            d = _next_business_day(cursor_date)
            start_dt = datetime.combine(d, datetime.min.time()).replace(hour=9)
            _make_booking(db, job, jcl, person, room, start_dt, HOURS_PER_DAY, BookingState.done)
            cursor_date = d + timedelta(days=1)
        for i in range(n_planned):
            d = _next_business_day(cursor_date)
            start_dt = datetime.combine(d, datetime.min.time()).replace(hour=9)
            _make_booking(db, job, jcl, person, room, start_dt, HOURS_PER_DAY, BookingState.confirmed)
            cursor_date = d + timedelta(days=1)

    db.flush()

    # ── ADVANCE PAYMENTS ─────────────────────────────────────
    # Per ogni acconto:
    #   1. Invoice (kind=advance, status=paid, amount_paid=full)
    #   2. InvoicePayment (cassa ricevuta)
    #   3. AdvancePayment (ledger)
    #   4. AdvancePaymentAllocation pro-quota su tutte le JCL del job
    #      (necessaria per la colonna "Coperto da acconto" nel CR detail
    #      e per advance_paid_coverage nel CR aggregato).
    if spec["advances"]:
        total_net = quote.total_after_discount
        total_jcl_quoted = sum(jcl.total_quoted for (jcl, _, _) in jcls) or 1.0
        for idx_adv, pct in enumerate(spec["advances"], start=1):
            net = round(total_net * pct, 2)
            vat = round(net * 0.22, 2)
            tot = round(net + vat, 2)
            issue_d = today - timedelta(days=20 - (idx_adv - 1) * 5)
            due_d = today + timedelta(days=10 + (idx_adv - 1) * 5)
            inv = Invoice(
                number=f"INV-{spec['code']}-AC{idx_adv}",
                client_id=client.id, job_id=job.id, project_id=proj.id,
                quote_id=quote.id,
                status=InvoiceStatus.paid,
                kind=InvoiceKind.advance,
                doc_type="TD01",
                issue_date=issue_d, due_date=due_d,
                subtotal=net, vat_rate=22.0, total=tot,
                amount_paid=tot,
                notes=f"Acconto {int(pct*100)}% — rata {idx_adv}",
            )
            db.add(inv); db.flush()
            db.add(InvoiceLine(
                invoice_id=inv.id,
                description=f"Acconto {int(pct*100)}% su {spec['title']}",
                quantity=1, unit_price=net, total=net,
                vat_rate=22.0, discount_pct=0.0,
            ))
            # InvoicePayment: cassa ricevuta
            db.add(InvoicePayment(
                tenant_id=1, invoice_id=inv.id,
                amount=tot, payment_date=issue_d + timedelta(days=2),
                method="bonifico", reference=f"TRN-{inv.number}",
            ))
            ap = AdvancePayment(
                tenant_id=1, project_id=proj.id, invoice_id=inv.id,
                amount=net, balance_remaining=net,
                status=AdvancePaymentStatus.paid,
                label=f"Acconto {int(pct*100)}% #{idx_adv}",
                scheduled_due_date=due_d,
            )
            db.add(ap); db.flush()
            # Allocation pro-quota su ogni JCL (amount = AP.amount × JCL.tq/Σtq)
            running = 0.0
            for sort_idx, (jcl, _, _) in enumerate(jcls):
                quota = round(net * (jcl.total_quoted / total_jcl_quoted), 2)
                # Last allocation absorbs rounding residual
                if sort_idx == len(jcls) - 1:
                    quota = round(net - running, 2)
                running += quota
                db.add(AdvancePaymentAllocation(
                    advance_payment_id=ap.id,
                    job_cost_line_id=jcl.id,
                    amount=quota,
                    pct=round(quota / net, 4) if net else 0.0,
                    sort_order=sort_idx,
                ))

    return proj, quote, job, jcls


# ── MAIN ────────────────────────────────────────────────────────────

def seed(confirm: bool = False):
    print("=" * 70)
    print("MediaFlow · Seed 5 progetti di test")
    print("=" * 70)
    print()
    print("Cancellerà tutti i progetti/booking/fatture esistenti e ricostruirà:")
    for s in PROJECTS_SPEC:
        print(f"  • {s['code']}  {s['title']}")
    print()
    if not confirm:
        ans = input("Procedere? Scrivi 'YES' per confermare: ").strip()
        if ans != "YES":
            print("Annullato.")
            return 1

    # 1. Purge
    print("\n▸ Purge business data via reset_business_data ...")
    purge_business_data()

    # 2. Seed
    create_tables()
    db = SessionLocal()

    # Sanity check: listino + reparti devono esistere (preservati dal reset).
    departments = {d.code: d for d in db.query(Department).filter(Department.tenant_id == 1).all()}
    for needed in ("DI-VIDEO", "AUDIO"):
        if needed not in departments:
            print(f"✗ Reparto {needed} mancante. Esegui prima seed_demo.")
            db.close()
            return 2

    pricelist_n = db.query(PriceItem).filter(PriceItem.tenant_id == 1).count()
    if pricelist_n == 0:
        print("✗ Listino vuoto. Esegui prima seed_demo (lean_2026q3_v1).")
        db.close()
        return 2

    resources = _ensure_resources(db, departments)
    db.flush()

    client = _ensure_client(
        db, name="Cliente Test 5P",
        vat="IT09999990001",
        contact_email="produzione@cliente-test.it",
    )

    today = date.today()
    summary = []
    for seq, spec in enumerate(PROJECTS_SPEC, start=1):
        print(f"\n▸ Build {spec['code']} — {spec['title']}")
        proj, quote, job, jcls = _build_project(db, spec, client, today, resources, seq)
        n_bk = 0
        n_done = 0
        n_conf = 0
        if job:
            for (jcl, ql, role) in jcls:
                bks = db.query(Booking).filter(Booking.job_cost_line_id == jcl.id).all()
                n_bk += len(bks)
                for b in bks:
                    if b.state == BookingState.done:
                        n_done += 1
                    elif b.state == BookingState.confirmed:
                        n_conf += 1
        summary.append({
            "code": spec["code"], "project_id": proj.id, "quote_id": quote.id,
            "job_id": job.id if job else None,
            "bookings": n_bk, "done": n_done, "confirmed": n_conf,
            "advances": len(spec["advances"]),
        })

    db.commit()

    # 3. Recompute JCL su tutti i job creati
    print("\n▸ Recompute JCL (cost_line_sync) ...")
    n_jcl_recomputed = 0
    for entry in summary:
        if not entry["job_id"]:
            continue
        for jcl in db.query(JobCostLine).filter(JobCostLine.job_id == entry["job_id"]).all():
            recompute_cost_line_actual(db, jcl)
            n_jcl_recomputed += 1
    db.commit()

    # 4. Report
    print()
    print("=" * 70)
    print("✓ Seed 5 progetti completato")
    print("=" * 70)
    print(f"  Finestra lavorazioni: {WINDOW_START.isoformat()}  →  {WINDOW_END.isoformat()}")
    print(f"  Risorse usate: 2 persone DI + 1 sala DI + 1 mixer Audio + 1 sala Audio")
    print(f"  Cliente comune: {client.name}")
    print(f"  JCL ricomputate: {n_jcl_recomputed}")
    print()
    print(f"  {'CODE':<10} {'PROJ':<6} {'QUOTE':<6} {'JOB':<6} {'BKs':<5} {'done':<5} {'conf':<5} {'adv':<5}")
    for e in summary:
        print(f"  {e['code']:<10} {e['project_id']:<6} {e['quote_id']:<6} "
              f"{(e['job_id'] or '-'):<6} {e['bookings']:<5} {e['done']:<5} "
              f"{e['confirmed']:<5} {e['advances']:<5}")
    print()

    db.close()
    return 0


if __name__ == "__main__":
    confirmed = "--yes" in sys.argv or "-y" in sys.argv
    sys.exit(seed(confirm=confirmed))
