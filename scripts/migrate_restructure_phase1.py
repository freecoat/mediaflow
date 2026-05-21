"""
MediaFlow — Migration Sprint 1 Restructure 2026-05-20 (v3.5.0-alpha.172)

Spec di riferimento: docs/RESTRUCTURE_2026_05_20.md

Pattern:
- Single transaction (BEGIN ... COMMIT/ROLLBACK)
- ALTER TABLE ADD COLUMN idempotenti (check via PRAGMA table_info)
- CREATE TABLE IF NOT EXISTS via SQLAlchemy metadata.create_all
- Backfill SQL deterministico
- Log dettagliato per audit

Idempotente: rerun safe. Nessun DROP distruttivo in questo step
(`booking.job_deliverable_id` viene migrato a pivot ma colonna conservata
back-compat finché Sprint 2 non sostituisce le query).

Esegui:
  python scripts/migrate_restructure_phase1.py             # chiede conferma
  python scripts/migrate_restructure_phase1.py --yes       # auto-confirm
  python scripts/migrate_restructure_phase1.py --dry-run   # mostra solo cosa farebbe
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import logging
from datetime import datetime
from sqlalchemy import text, inspect

from app.database import engine, SessionLocal, create_tables
from app.models.models import (
    Base,
    JobCostLine, JobDeliverable, DeliverableUnitNature, DeliverableBillingStatus,
    Booking, BookingDeliverable,
    PricelistUnit, PriceItem,
    Quote,
)

log = logging.getLogger("migrate_restructure_phase1")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ── Tassonomia preset PricelistUnit ──────────────────────────
# Seed per tenant=1 al boot. Tenant nuovi ereditano tramite seed_demo.
PRICELIST_UNITS_PRESET = [
    # (code, label, nature, sort_order)
    ("hr",      "Ora",        "time_based",         10),
    ("day",     "Giornata",   "time_based",         20),
    ("pc",      "Pezzo",      "deliverable_qty",    30),
    ("lot",     "Lotto",      "deliverable_qty",    40),
    ("shot",    "Shot",       "deliverable_qty",    50),
    ("version", "Versione",   "deliverable_qty",    60),
    ("TB",      "Terabyte",   "deliverable_volume", 70),
    ("GB",      "Gigabyte",   "deliverable_volume", 80),
    ("allow",   "Allowance",  "manual_allow",       90),
    ("lump",    "Forfait",    "manual_allow",      100),
    ("fix",     "Fisso",      "manual_allow",      110),
]


# Mapping unit → nature (back-compat: unit ignote → deliverable_qty)
UNIT_TO_NATURE = {u[0]: u[2] for u in PRICELIST_UNITS_PRESET}


def _columns(conn, table: str) -> set:
    try:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
        return {r[1] for r in rows}
    except Exception:
        return set()


def _table_exists(insp, name: str) -> bool:
    return name in set(insp.get_table_names())


def ensure_tables(insp):
    """Create new tables via SQLAlchemy metadata. Idempotente."""
    log.info("▸ Step 1 — Create new tables (booking_deliverables, deliverable_*, "
             "advance_payment_deliverable_allocations, vfx_shots, pricelist_units)")
    Base.metadata.create_all(bind=engine, checkfirst=True)


def ensure_columns(conn, dry_run: bool = False) -> dict:
    """ALTER TABLE ADD COLUMN idempotenti per JobDeliverable, Quote, PriceItem."""
    added = {}

    # ── JobDeliverable ──
    jd_cols = _columns(conn, "job_deliverables")
    jd_alters = [
        ("quote_line_id",        "INTEGER REFERENCES quote_lines(id)"),
        ("unit",                 "VARCHAR(20)"),
        ("unit_price",           "FLOAT NOT NULL DEFAULT 0"),
        ("unit_nature",          "VARCHAR(32) NOT NULL DEFAULT 'deliverable_qty'"),
        ("quantity_planned",     "FLOAT NOT NULL DEFAULT 1"),
        ("quantity_delivered",   "FLOAT NOT NULL DEFAULT 0"),
        ("total_quoted",         "FLOAT NOT NULL DEFAULT 0"),
        ("total_accrued",        "FLOAT NOT NULL DEFAULT 0"),
        ("total_cost_accrued",   "FLOAT NOT NULL DEFAULT 0"),
        ("accrued_stale",        "BOOLEAN NOT NULL DEFAULT 0"),
        ("confirmed_at",         "DATETIME"),
        ("confirmed_by_user_id", "INTEGER REFERENCES users(id)"),
        ("billing_status",       "VARCHAR(32) NOT NULL DEFAULT 'not_billed'"),
        ("billing_batch_id",     "INTEGER REFERENCES billing_batches(id)"),
        ("billed_amount",        "FLOAT"),
        ("deleted_by_user_id",   "INTEGER REFERENCES users(id)"),
    ]
    added["job_deliverables"] = []
    for col, ddl in jd_alters:
        if col not in jd_cols:
            sql = f"ALTER TABLE job_deliverables ADD COLUMN {col} {ddl}"
            log.info("  + job_deliverables.%s", col)
            if not dry_run:
                conn.execute(text(sql))
            added["job_deliverables"].append(col)

    # ── Quote ──
    q_cols = _columns(conn, "quotes")
    added["quotes"] = []
    for col, ddl in [
        ("subtotal_gross_jcl",         "FLOAT NOT NULL DEFAULT 0"),
        ("subtotal_gross_deliverable", "FLOAT NOT NULL DEFAULT 0"),
    ]:
        if col not in q_cols:
            log.info("  + quotes.%s", col)
            if not dry_run:
                conn.execute(text(f"ALTER TABLE quotes ADD COLUMN {col} {ddl}"))
            added["quotes"].append(col)

    # ── PriceItem ──
    pi_cols = _columns(conn, "price_items")
    added["price_items"] = []
    if "unit_nature" not in pi_cols:
        log.info("  + price_items.unit_nature")
        if not dry_run:
            conn.execute(text(
                "ALTER TABLE price_items ADD COLUMN unit_nature VARCHAR(32) "
                "NOT NULL DEFAULT 'deliverable_qty'"
            ))
        added["price_items"].append("unit_nature")

    return added


def seed_pricelist_units(conn, dry_run: bool = False) -> int:
    """Popola pricelist_units per tenant=1 con preset 11 row.
    Idempotente: skip code già presente (UNIQUE(tenant_id, code))."""
    log.info("▸ Step 3 — Seed pricelist_units preset (tenant=1)")
    existing = set()
    for r in conn.execute(text(
        "SELECT code FROM pricelist_units WHERE tenant_id = 1"
    )).all():
        existing.add(r[0])

    inserted = 0
    for code, label, nature, sort_order in PRICELIST_UNITS_PRESET:
        if code in existing:
            continue
        log.info("  + pricelist_units[%s] %s (nature=%s)", code, label, nature)
        if not dry_run:
            conn.execute(text(
                "INSERT INTO pricelist_units (tenant_id, code, label, nature, "
                "sort_order, is_active, created_at) "
                "VALUES (1, :c, :l, :n, :s, 1, :ts)"
            ).bindparams(c=code, l=label, n=nature, s=sort_order,
                         ts=datetime.utcnow().isoformat()))
        inserted += 1
    return inserted


def backfill_priceitem_unit_nature(conn, dry_run: bool = False) -> int:
    """Imposta price_items.unit_nature derivato da unit mapping.
    Default deliverable_qty per unit ignote."""
    log.info("▸ Step 4 — Backfill price_items.unit_nature")
    rows = conn.execute(text(
        "SELECT id, unit FROM price_items"
    )).all()
    updates = 0
    for r in rows:
        nature = UNIT_TO_NATURE.get((r[1] or "").strip().lower(), "deliverable_qty")
        log.debug("  price_item#%s unit=%s → nature=%s", r[0], r[1], nature)
        if not dry_run:
            conn.execute(text(
                "UPDATE price_items SET unit_nature = :n WHERE id = :id"
            ).bindparams(n=nature, id=r[0]))
        updates += 1
    log.info("  ✓ backfilled %d price_items rows", updates)
    return updates


def backfill_deliverable_quote_link(conn, dry_run: bool = False) -> int:
    """Per JobDeliverable preesistenti (pre-restructure), prova a popolare
    `quote_line_id` derivandolo da `job_cost_line_id → quote_line_id`.
    Permette mapping AdvancePaymentDeliverableAllocation futuro."""
    log.info("▸ Step 5 — Backfill job_deliverables.quote_line_id (via JCL)")
    rows = conn.execute(text(
        "SELECT d.id, j.quote_line_id "
        "FROM job_deliverables d "
        "JOIN job_cost_lines j ON j.id = d.job_cost_line_id "
        "WHERE d.quote_line_id IS NULL AND j.quote_line_id IS NOT NULL"
    )).all()
    n = 0
    for d_id, ql_id in rows:
        if not dry_run:
            conn.execute(text(
                "UPDATE job_deliverables SET quote_line_id = :q WHERE id = :id"
            ).bindparams(q=ql_id, id=d_id))
        n += 1
    log.info("  ✓ linked %d deliverables to quote_lines", n)
    return n


def backfill_quote_subtotal_split(conn, dry_run: bool = False) -> int:
    """Calcola subtotal_gross_jcl + subtotal_gross_deliverable per Quote
    esistenti basandosi su QuoteLine.unit ∈ time/non-time."""
    log.info("▸ Step 6 — Backfill quotes.subtotal_gross_jcl + subtotal_gross_deliverable")
    time_units = ("hr", "day")
    rows = conn.execute(text(
        "SELECT q.id, ql.unit, ql.quantity, ql.unit_price, ql.allowance, "
        "ql.is_optional "
        "FROM quotes q JOIN quote_lines ql ON ql.quote_id = q.id"
    )).all()
    agg: dict[int, tuple[float, float]] = {}
    for q_id, unit, qty, up, allow, is_opt in rows:
        if is_opt:
            continue
        unit_l = (unit or "").strip().lower()
        gross = (qty or 0) * (up or 0) * (1 + (allow or 0))
        cur = agg.get(q_id, (0.0, 0.0))
        if unit_l in time_units:
            agg[q_id] = (cur[0] + gross, cur[1])
        else:
            agg[q_id] = (cur[0], cur[1] + gross)
    n = 0
    for q_id, (g_jcl, g_del) in agg.items():
        if not dry_run:
            conn.execute(text(
                "UPDATE quotes SET subtotal_gross_jcl = :j, "
                "subtotal_gross_deliverable = :d WHERE id = :id"
            ).bindparams(j=round(g_jcl, 2), d=round(g_del, 2), id=q_id))
        n += 1
    log.info("  ✓ updated %d quotes", n)
    return n


def autospawn_deliverables_from_jcl(conn, dry_run: bool = False) -> dict:
    """Step CRITICO: per ogni JobCostLine con unit non-time-based, spawn
    1 JobDeliverable per ogni `quantity_quoted` unità (1 row = 1 qty).

    Pre-condizioni:
    - JCL non già migrate (no JobDeliverable child con quote_line_id matching)
    - Sopravvive a rerun (idempotenza via check existing)

    Mappa cascade:
    - booking.job_cost_line_id → primo JobDeliverable spawnato → pivot booking_deliverables
    - JCL.external_outsourced=True → JobDeliverable.unit='lump', quantity_planned=quantity_quoted
      (1 sola row, NON 1-per-qty: external è lump)
    """
    log.info("▸ Step 7 — Autospawn JobDeliverable per JCL non-time-based")

    # Recupera JCL non-time + non già migrate
    jcl_rows = conn.execute(text(
        "SELECT j.id, j.tenant_id, j.job_id, j.quote_line_id, j.price_item_id, "
        "       j.description, j.quantity_quoted, j.quantity_actual, j.unit, "
        "       j.unit_price, j.total_quoted, j.total_accrued, j.is_extra, "
        "       j.external_outsourced "
        "FROM job_cost_lines j"
    )).all()

    summary = {"jcl_examined": 0, "deliverables_spawned": 0,
               "external_lump_spawned": 0, "bookings_relinked": 0,
               "skipped_time_based": 0, "skipped_already_migrated": 0}

    time_units = ("hr", "day")
    for jcl in jcl_rows:
        summary["jcl_examined"] += 1
        unit = (jcl[8] or "").strip().lower()
        if unit in time_units:
            summary["skipped_time_based"] += 1
            continue

        # Skip se già un deliverable esiste linkato a questa JCL via job_cost_line_id
        # AND ha quote_line_id matching (= autospawn precedente)
        existing = conn.execute(text(
            "SELECT COUNT(*) FROM job_deliverables "
            "WHERE job_cost_line_id = :jid"
        ).bindparams(jid=jcl[0])).scalar()
        if existing and existing > 0:
            summary["skipped_already_migrated"] += 1
            continue

        external = bool(jcl[13])
        nature = UNIT_TO_NATURE.get(unit, "deliverable_qty")
        if external:
            nature = "manual_allow"
            unit_eff = "lump"
        else:
            unit_eff = unit

        # v3.5.0-alpha.172.14 — Spawn rule per nature:
        # external/manual_allow/deliverable_volume → 1 row aggregato.
        # deliverable_qty (pc/lot/shot/version) → N row, 1 per unità.
        qty_raw = float(jcl[6] or 0)
        if external or nature in ("manual_allow", "deliverable_volume"):
            n_rows = 1
            per_row_qty = qty_raw if qty_raw > 0 else 1.0
        else:
            n_rows = max(1, int(round(qty_raw)))
            per_row_qty = 1.0

        aggregated = (n_rows == 1)
        new_deliv_ids = []
        for idx in range(n_rows):
            up = float(jcl[9] or 0.0)
            tq = round(per_row_qty * up, 2)
            # quantity_delivered iniziale derivato da JCL.quantity_actual.
            qa_total = float(jcl[7] or 0.0)
            if aggregated:
                qty_done = min(qa_total, per_row_qty) if per_row_qty > 0 else qa_total
            else:
                qa = round(qa_total)
                qty_done = 1.0 if idx < qa else 0.0
            ta = round(qty_done * up, 2)

            payload = dict(
                tenant_id=jcl[1], job_id=jcl[2],
                job_cost_line_id=jcl[0],
                price_item_id=jcl[4],
                quote_line_id=jcl[3],
                name=jcl[5] or f"Deliverable {idx+1}",
                unit=unit_eff,
                unit_price=up,
                unit_nature=nature,
                quantity_planned=per_row_qty,
                quantity_delivered=qty_done,
                total_quoted=tq,
                total_accrued=ta,
                total_cost_accrued=0.0,
                nature="digital",  # default; tipologia digital/physical legacy
                status="planned" if qty_done == 0 else "delivered",
                billing_status="not_billed",
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
            )
            if dry_run:
                new_deliv_ids.append(-1)
                summary["deliverables_spawned" if not external else "external_lump_spawned"] += 1
                continue
            cur = conn.execute(text("""
                INSERT INTO job_deliverables (
                    tenant_id, job_id, job_cost_line_id, price_item_id,
                    quote_line_id, name, unit, unit_price, unit_nature,
                    quantity_planned, quantity_delivered, total_quoted,
                    total_accrued, total_cost_accrued, nature, status,
                    billing_status, accrued_stale, created_at, updated_at
                ) VALUES (
                    :tenant_id, :job_id, :job_cost_line_id, :price_item_id,
                    :quote_line_id, :name, :unit, :unit_price, :unit_nature,
                    :quantity_planned, :quantity_delivered, :total_quoted,
                    :total_accrued, :total_cost_accrued, :nature, :status,
                    :billing_status, 0, :created_at, :updated_at
                )
            """).bindparams(**payload))
            new_deliv_ids.append(cur.lastrowid)
            if external:
                summary["external_lump_spawned"] += 1
            else:
                summary["deliverables_spawned"] += 1

        # Cascade booking.job_cost_line_id → booking_deliverables (primo deliverable)
        if new_deliv_ids and new_deliv_ids[0] != -1:
            primary_did = new_deliv_ids[0]
            booking_rows = conn.execute(text(
                "SELECT id FROM bookings WHERE job_cost_line_id = :jid"
            ).bindparams(jid=jcl[0])).all()
            for (b_id,) in booking_rows:
                # Idempotency check (UNIQUE constraint)
                already = conn.execute(text(
                    "SELECT 1 FROM booking_deliverables "
                    "WHERE booking_id = :b AND job_deliverable_id = :d"
                ).bindparams(b=b_id, d=primary_did)).first()
                if already:
                    continue
                if not dry_run:
                    conn.execute(text(
                        "INSERT INTO booking_deliverables "
                        "(booking_id, job_deliverable_id, sort_order, created_at) "
                        "VALUES (:b, :d, 0, :ts)"
                    ).bindparams(b=b_id, d=primary_did,
                                 ts=datetime.utcnow().isoformat()))
                summary["bookings_relinked"] += 1

    return summary


def backfill_booking_deliverables_legacy(conn, dry_run: bool = False) -> int:
    """Per ogni Booking con `job_deliverable_id` (FK singolo legacy)
    aggiunge pivot booking_deliverables se mancante. Idempotente."""
    log.info("▸ Step 8 — Backfill booking_deliverables da Booking.job_deliverable_id legacy")
    cols = _columns(conn, "bookings")
    if "job_deliverable_id" not in cols:
        log.info("  (colonna legacy assente, skip)")
        return 0
    rows = conn.execute(text(
        "SELECT id, job_deliverable_id FROM bookings "
        "WHERE job_deliverable_id IS NOT NULL"
    )).all()
    n = 0
    for b_id, d_id in rows:
        already = conn.execute(text(
            "SELECT 1 FROM booking_deliverables "
            "WHERE booking_id = :b AND job_deliverable_id = :d"
        ).bindparams(b=b_id, d=d_id)).first()
        if already:
            continue
        if not dry_run:
            conn.execute(text(
                "INSERT INTO booking_deliverables "
                "(booking_id, job_deliverable_id, sort_order, created_at) "
                "VALUES (:b, :d, 0, :ts)"
            ).bindparams(b=b_id, d=d_id, ts=datetime.utcnow().isoformat()))
        n += 1
    log.info("  ✓ migrated %d legacy booking.job_deliverable_id → pivot", n)
    return n


def run(confirm: bool = False, dry_run: bool = False) -> int:
    print("=" * 70)
    print("MediaFlow · Migration Sprint 1 Restructure (v3.5.0-alpha.172)")
    print("=" * 70)
    print(f"DRY-RUN: {dry_run}")
    print()
    print("Operazioni:")
    print("  1. CREATE TABLE pivot/spec/slice/alloc/vfx/units (idempotente)")
    print("  2. ALTER TABLE job_deliverables (+16 colonne), quotes (+2), price_items (+1)")
    print("  3. Seed pricelist_units (11 row preset)")
    print("  4. Backfill price_items.unit_nature da unit")
    print("  5. Backfill job_deliverables.quote_line_id via JCL")
    print("  6. Backfill quotes.subtotal_gross_jcl + subtotal_gross_deliverable")
    print("  7. Autospawn JobDeliverable per JCL non-time + cascade booking pivot")
    print("  8. Backfill booking_deliverables da Booking.job_deliverable_id legacy")
    print()

    if not confirm and not dry_run:
        ans = input("Procedere? Scrivi 'YES' per confermare: ").strip()
        if ans != "YES":
            print("Annullato.")
            return 1

    insp = inspect(engine)

    # Step 1: create tables
    if not dry_run:
        ensure_tables(insp)

    summary = {}
    with engine.begin() as conn:
        # Step 2: alter columns
        log.info("▸ Step 2 — ALTER TABLE ADD COLUMN")
        summary["columns_added"] = ensure_columns(conn, dry_run)

        # Step 3-8
        summary["pricelist_units_seeded"] = seed_pricelist_units(conn, dry_run)
        summary["price_items_backfilled"] = backfill_priceitem_unit_nature(conn, dry_run)
        summary["deliverables_linked_to_quote_line"] = backfill_deliverable_quote_link(conn, dry_run)
        summary["quotes_subtotal_split"] = backfill_quote_subtotal_split(conn, dry_run)
        summary["autospawn"] = autospawn_deliverables_from_jcl(conn, dry_run)
        summary["legacy_pivot_migrated"] = backfill_booking_deliverables_legacy(conn, dry_run)

    print()
    print("=" * 70)
    print("✓ Migration Sprint 1 completata")
    print("=" * 70)
    import json
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    confirmed = "--yes" in sys.argv or "-y" in sys.argv
    dry = "--dry-run" in sys.argv
    sys.exit(run(confirm=confirmed, dry_run=dry))
