"""
Sincronizzazione JobCostLine.quantity_actual + total_accrued con i Booking.

v3.4.41 — bug fix: le ore booking marcate `done` non comparivano come
"maturate" nel cost report perché `JobCostLine.quantity_actual` non veniva
aggiornato dal flusso execution_status. La fonte canonica delle ore è il
Booking (decisione architetturale di v3.4.33), ma il cost report continua
ad esporre `total_accrued` per back-compat e per il drilldown per riga.

Conversione unit→ore:
- "hr" / "ore" / "hour": qty in ore = sum(hours_done)
- "day" / "giorno": qty in giorni = sum(hours_done) / 8
- altri unit (fix, lot, ...): non aggiornare automaticamente — quel tipo
  di lavorazione non si misura in ore di booking. Lasciato a edit manuale.

Idempotente: la ricomputazione legge tutti i booking `done` della cost
line, sostituisce quantity_actual + total_accrued. Si auto-rigenera ad
ogni hook (no drift incrementale).

v3.5.0-alpha.65 — Pass-through OT al cliente (opt-in per Job.weighted_revenue).
Quando il job ha `weighted_revenue=True`, le ore lineari vengono sostituite
dal `weighted_factor` di `compute_assignment_breakdown`: ogni assignment
viene pesato con i moltiplicatori della WorkingHoursPolicy della risorsa
(holiday/sunday/overtime/night), e l'overtime APPROVED conta col coefficiente
mentre PENDING resta lineare (vedi memoria progetto su decisioni semantiche).
Default: weighted_revenue=False → comportamento storico (lineare). Il
cost-side interno (costo stimato per risorsa) usa già il weighted_factor a
prescindere via `_bookings_hours_cost`.
"""
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

HOURS_PER_DAY = 8.0
TIME_UNITS_HOUR = {"hr", "ore", "hour", "h"}
TIME_UNITS_DAY = {"day", "giorno", "giornate", "giornata", "d"}
# v3.5.0-alpha.171 (CR-2) — Distinzione umana / non-umana per regola
# "billable hours". Quando 1 booking ha sia sala che persona, le ore
# fatturate al cliente sono quelle della persona (override umana); se
# nessuna persona ma più sale/attrezzature, prendi quella con più ore
# (max). Pre-α.171 sommava tutto → ore raddoppiate.
HUMAN_RESOURCE_TYPES = {"person_internal", "person_freelance", "person"}
# v3.5.0-alpha.66.11 — Categorizzazione delle unità per cost report split
# cliente vs interno. Le voci TIME-based mostrano monte ore al cliente
# (sessioni di lavoro). Le voci NON-time-based (deliverable, materiale,
# forfait) NON mostrano ore al cliente — il loro hardcost interno è il
# costo orario delle risorse che le hanno prodotte (ore booking
# attribuite × Resource.internal_cost_hourly).
TIME_UNITS = TIME_UNITS_HOUR | TIME_UNITS_DAY


def _count_jcl_matching_resources(db, *, job_id, project_id, invoices) -> int:
    """v3.5.0-alpha.119 — Conta le JCL nel job/project che hanno almeno un
    booking_assignment con resource_id in (invoices.resource_id). Usato
    come denominatore per pro-quota distribution di SupplierInvoice ai
    livelli 2 (job) e 3 (project) della priority ranking.

    Garantisce che ogni fattura si spalmi in modo conservativo: la somma
    dei contributi su tutte le JCL = total fattura, no double-count.
    """
    from app.models import (
        JobCostLine as _JCL,
        Booking as _Booking,
        BookingAssignment as _BA,
        Job as _Job,
    )
    res_ids = {si.resource_id for si in invoices if si.resource_id}
    if not res_ids:
        return 0
    q = (
        db.query(_JCL.id)
        .join(_Booking, _Booking.job_cost_line_id == _JCL.id)
        .join(_BA, _BA.booking_id == _Booking.id)
        .filter(_BA.resource_id.in_(res_ids))
    )
    if job_id is not None:
        q = q.filter(_JCL.job_id == job_id)
    elif project_id is not None:
        q = q.join(_Job, _Job.id == _JCL.job_id).filter(_Job.project_id == project_id)
    return q.distinct().count()


def is_time_based_unit(unit: Optional[str]) -> bool:
    """True se l'unità implica monte ore (day/hr/h/ore...). False per
    deliverable/materiale/forfait (pc/min/TB/GB/shot/version/allow/lump)."""
    if not unit:
        return False
    return unit.strip().lower() in TIME_UNITS


# v3.5.0-alpha.172.4 (Sprint 4 T1) — Helper centralizzato unit→nature.
# Sostituisce mappa hardcoded duplicata in routers/quotes.py:_create_job_from_quote
# e services/reverse_quote.py. Single source of truth.
_UNIT_TO_NATURE = {
    # time_based → JCL
    "hr": "time_based", "ore": "time_based", "hour": "time_based",
    "h": "time_based", "day": "time_based", "giorno": "time_based",
    "giornate": "time_based", "giornata": "time_based", "d": "time_based",
    # deliverable_qty
    "pc": "deliverable_qty", "lot": "deliverable_qty",
    "shot": "deliverable_qty", "version": "deliverable_qty",
    # deliverable_volume
    "tb": "deliverable_volume", "gb": "deliverable_volume",
    # manual_allow
    "allow": "manual_allow", "lump": "manual_allow", "fix": "manual_allow",
    # min legacy → manual_allow (frazione tempo, fatturata a forfait)
    "min": "manual_allow",
}


def unit_nature_for(unit: Optional[str]) -> str:
    """Ritorna la `DeliverableUnitNature` (stringa) per un'`unit` di QuoteLine.

    Default `deliverable_qty` per unit sconosciute (back-compat: voci pre-restructure
    o unit_label custom).
    """
    if not unit:
        return "deliverable_qty"
    return _UNIT_TO_NATURE.get(unit.strip().lower(), "deliverable_qty")


def _booking_hours_linear(b) -> float:
    """Ore-uomo lineari del booking = somma delle durate degli assignment.
    Path storico (pre-α.65), invariato per back-compat.

    Nota: questa è la SOMMA delle ore di tutti gli assignment. Usato per
    il cost-side interno (`total_cost_accrued`: sala costa, persona costa,
    entrambi vanno contati). NON usare per `quantity_actual` fatturata al
    cliente — quella ha logica `_booking_billable_hours` con override umana.
    """
    if not getattr(b, "assignments", None):
        if not b.start_datetime or not b.end_datetime:
            return 0.0
        return max(0.0, (b.end_datetime - b.start_datetime).total_seconds() / 3600.0)
    total = 0.0
    for a in b.assignments:
        if a.start_datetime and a.end_datetime:
            total += max(0.0, (a.end_datetime - a.start_datetime).total_seconds() / 3600.0)
    return total


def _assignment_hours(a) -> float:
    """Durata in ore di un singolo assignment. 0 se start/end mancanti."""
    if not a.start_datetime or not a.end_datetime:
        return 0.0
    return max(0.0, (a.end_datetime - a.start_datetime).total_seconds() / 3600.0)


def _booking_billable_hours(b) -> float:
    """v3.5.0-alpha.171 (CR-2) — Ore "fatturabili al cliente" del booking.
    v3.5.0-alpha.172.97 — fix smart_split: somma per risorsa, poi max tra risorse.

    Regola Matteo (19 mag 2026):
    - Se almeno 1 assignment è risorsa umana (person_internal/freelance/person)
      → max(hours_per_resource) tra le umane (override umana, ignora sala/equipment)
    - Else → max(hours_per_resource) tra non-umane (sala/equipment/software/vehicle)

    Aggregazione per resource_id PRIMA del max: con smart_split (α.172.75) la
    stessa persona ha 2 assignment giornalieri (AM 4h + PM 4h) → sum=8h.
    Senza aggregazione, max() prendeva un solo slot da 4h sotto-stimando del 50%.

    Rationale: il cliente paga le ORE LAVORO della persona; la sala è un costo
    interno (mostrato in cost-side) ma non si fattura come ore separate.
    Pre-α.171 sommava sala+persona → fatturazione doppia delle ore.

    Esempi:
    - Booking: Carlo 8h + Sala A 8h → billable = 8h (max umana)
    - Booking: Carlo AM 4h + Carlo PM 4h (smart_split) → billable = 8h (sum stessa risorsa)
    - Booking: Carlo 4h + Mario 6h + Sala A 8h → billable = 6h (max umana)
    - Booking: Sala A 8h + Sala B 4h (nessuna umana) → billable = 8h
    - Booking: solo Carlo 8h → billable = 8h
    - Booking senza assignments → shell-duration (back-compat)
    """
    if not getattr(b, "assignments", None):
        if not b.start_datetime or not b.end_datetime:
            return 0.0
        return max(0.0, (b.end_datetime - b.start_datetime).total_seconds() / 3600.0)
    from collections import defaultdict
    human_by_res: dict = defaultdict(float)
    nonhuman_by_res: dict = defaultdict(float)
    for a in b.assignments:
        h = _assignment_hours(a)
        if h <= 0:
            continue
        rid = a.resource_id or 0
        res = getattr(a, "resource", None)
        # Resolve type: prefer relationship enum, fallback to nothing → non-human bucket
        rtype = None
        if res is not None:
            rtype = res.type.value if hasattr(res.type, "value") else str(res.type)
        if rtype in HUMAN_RESOURCE_TYPES:
            human_by_res[rid] += h
        else:
            nonhuman_by_res[rid] += h
    if human_by_res:
        return max(human_by_res.values())
    if nonhuman_by_res:
        return max(nonhuman_by_res.values())
    return 0.0


def _booking_hours_weighted(db: Session, b) -> float:
    """Ore-uomo pesate del booking via `compute_assignment_breakdown`.

    Per ciascun assignment risolve la WorkingHoursPolicy della risorsa (override
    o default tenant), calcola il `weighted_factor` (multiplier holiday/sunday/
    overtime/night + brackets CCNL), e somma. Se la risorsa non ha policy
    associabile, fallback alle ore lineari del singolo assignment.

    `Booking.overtime_status=pending` → le ore overtime di quel booking NON
    vengono pesate (restano in `pending_overtime_hours`, fuori dal weighted),
    coerente con la decisione semantica α.65 ("solo APPROVED applica
    moltiplicatori").
    """
    from app.models import WorkingHoursPolicy
    from app.services.booking_cost import compute_assignment_breakdown
    from app.services.working_hours import get_holidays

    if not getattr(b, "assignments", None):
        # Senza assignments non c'è una risorsa su cui applicare la policy:
        # restiamo sullo shell-duration lineare.
        return _booking_hours_linear(b)

    # Cache policy default tenant (1 query) e holidays (1 calcolo per policy/year)
    default_policy = db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.is_default == True  # noqa: E712
    ).first()
    holidays_cache: dict = {}

    def _resolve(resource) -> Optional["WorkingHoursPolicy"]:
        if resource and resource.working_hours_policy_id:
            p = db.query(WorkingHoursPolicy).filter(
                WorkingHoursPolicy.id == resource.working_hours_policy_id
            ).first()
            if p:
                return p
        return default_policy

    def _hols(policy, y0, y1):
        key = (id(policy), y0, y1)
        if key not in holidays_cache:
            holidays_cache[key] = get_holidays(policy, y0, y1)
        return holidays_cache[key]

    total = 0.0
    for a in b.assignments:
        if not (a.start_datetime and a.end_datetime):
            continue
        policy = _resolve(a.resource)
        if not policy:
            # Nessuna policy: fallback lineare per questo assignment
            total += max(0.0, (a.end_datetime - a.start_datetime).total_seconds() / 3600.0)
            continue
        hols = _hols(policy, a.start_datetime.year, a.end_datetime.year)
        br = compute_assignment_breakdown(a, policy, hols, b)
        total += br.weighted_factor
    return total


def _booking_hours(b, db: Optional[Session] = None, weighted: bool = False) -> float:
    """Ore-uomo del booking. `weighted=True` (richiede `db`) usa il
    weighted_factor della policy; default lineare (back-compat).

    v3.4.55 fix: prima usavamo shell-duration (start→end del booking),
    sottostimando il maturato per booking multi-risorsa. Allineato con
    `reverse_quote.compute_quantity_from_hours` che già usa man-hours.
    """
    if weighted and db is not None:
        return _booking_hours_weighted(db, b)
    return _booking_hours_linear(b)


def _qty_from_hours(unit: str, total_hours: float, n_bookings: int) -> float:
    """Conversione ore → quantità nell'unit della cost line.

    v3.5.0-alpha.13: per unità non temporali (pc/lump/fix/lot/shot/version/
    allow/TB/GB) usiamo il count dei booking, non le ore.
    """
    u = (unit or "").strip().lower()
    if u in TIME_UNITS_HOUR:
        return round(total_hours, 2)
    if u in TIME_UNITS_DAY:
        return round(total_hours / HOURS_PER_DAY, 4)
    return float(n_bookings)


def recompute_cost_line_actual(db: Session, jcl) -> dict:
    """Ricomputa `quantity_actual`, `total_accrued`, `total_expected`
    per una JobCostLine aggregando i booking associati.

    v3.5.0-alpha.55: oltre al maturato (booking done) ora calcoliamo anche
    la **stima** = tutti i booking non cancellati × prezzo. Va a popolare
    `total_expected` (prima riempito solo da edit manuale, lasciava il
    cost report con Over/Under sempre 0). Semantica:

    - `quantity_actual` = booking done (lavoro fatto)
    - `total_accrued`   = quantity_actual × unit_price (maturato certo)
    - `total_expected`  = qty pianificata × unit_price (forecast: tutti i
       booking confermati o done, esclusi solo cancelled)

    L'over/under nel cost report è poi calcolato lato API in due viste:
    Now (accrued − quoted) e Forecast (expected − quoted).
    """
    from app.models import Booking, BookingExecutionStatus, BookingStatus, Job
    if jcl is None:
        return {"updated": False, "reason": "no_jcl"}

    # v3.5.0-alpha.172 Restructure — Branch external_outsourced rimosso.
    # Le voci precedentemente marcate `external_outsourced=True` sono ora
    # JobDeliverable con `unit_nature=manual_allow` (vedi migrate_restructure_phase1).
    # La JCL legacy con flag=True viene tollerata back-compat (no-op breve
    # branch): comportamento atteso è che `migrate_restructure_phase1` abbia
    # già spawnato un Deliverable lump, ma se per qualche motivo è rimasta,
    # azzeriamo accrued e usciamo, per non causare maturato fantasma.
    if getattr(jcl, "external_outsourced", False):
        jcl.quantity_actual = 0.0
        jcl.total_accrued = 0.0
        jcl.total_expected = 0.0
        jcl.total_cost_accrued = 0.0
        jcl.total_cost_external = 0.0
        jcl.accrued_stale = False
        return {
            "updated": True, "jcl_id": jcl.id,
            "mode": "external_outsourced_legacy_zeroed",
            "note": "Run migrate_restructure_phase1 to convert to JobDeliverable lump",
        }

    # v3.5.0-alpha.65 — risolvi weighted_revenue del job parent (1 query)
    weighted = False
    if jcl.job_id:
        job_row = db.query(Job.weighted_revenue).filter(Job.id == jcl.job_id).first()
        weighted = bool(job_row and job_row[0])

    # Tutti i booking non cancellati associati alla cost line
    all_bookings = db.query(Booking).filter(
        Booking.job_cost_line_id == jcl.id,
        Booking.status != BookingStatus.cancelled,
    ).all()
    done_bookings = [b for b in all_bookings if b.execution_status == BookingExecutionStatus.done]

    unit = (jcl.unit or "").strip().lower()
    is_time = is_time_based_unit(unit)
    # v3.5.0-alpha.172 Restructure — JCL DEVE essere time-based.
    # Voci non-time sono state migrate a JobDeliverable da migrate_restructure_phase1.
    # Se incontriamo una JCL non-time qui (legacy), azzeriamo maturato e usciamo
    # con warning per evitare il maturato fantasma del Bug 2 pre-restructure.
    if not is_time:
        import logging as _log
        _log.getLogger(__name__).warning(
            f"[cost_line_sync] JCL #{jcl.id} ha unit non-time '{unit}': "
            f"esegui migrate_restructure_phase1 per convertirla a JobDeliverable. "
            f"Azzeramento maturato per evitare Bug 2."
        )
        jcl.quantity_actual = 0.0
        jcl.total_accrued = 0.0
        jcl.total_expected = 0.0
        jcl.total_cost_accrued = 0.0
        jcl.accrued_stale = False
        return {
            "updated": True, "jcl_id": jcl.id,
            "mode": "non_time_legacy_zeroed",
            "unit": unit,
            "note": "JCL non-time legacy. Run migrate_restructure_phase1.",
        }
    # Ore "fatturabili" usano _booking_billable_hours (override umana,
    # no double-count sala+persona). Cost-side (sotto) somma SEMPRE tutti gli
    # assignment via _booking_hours (è un consumo reale).
    #
    # v3.5.0-alpha.172.37 (Sprint 3.A BLOCCO 4) — pass-through OT al cliente:
    # se `Job.weighted_revenue=True`, le ore done vengono pesate via
    # `_booking_hours_weighted` (CCNL brackets + holiday/sunday/overtime
    # multiplier). Solo `done_hours` (maturato): `planned_hours` (forecast)
    # resta lineare per non sovra-stimare i ricavi attesi.
    # Pre-α.172.37 il flag esisteva su Job ma NON era applicato — feature
    # dichiarata ma muta. Bug audit BLOCCO 4.
    if weighted:
        done_hours = sum(_booking_hours_weighted(db, b) for b in done_bookings)
    else:
        done_hours = sum(_booking_billable_hours(b) for b in done_bookings)
    planned_hours = sum(_booking_billable_hours(b) for b in all_bookings)
    new_qty_actual = _qty_from_hours(unit, done_hours, len(done_bookings))
    new_qty_planned = _qty_from_hours(unit, planned_hours, len(all_bookings))

    # v3.5.0-alpha.66.21 — α.67 cost-side risorsa.
    # Per ogni assignment dei booking done, somma ore × Resource.internal_cost_hourly.
    # internal_cost_hourly è property derivata da cost_type:
    #   employee → monthly_gross_salary × bonus × multiplier / annual_hours
    #   freelance → freelance_hourly_cost
    #   studio    → studio_hourly_cost
    #   external/None → None (skip, non concorre al costo)
    # Risultato: somma realistica del costo aziendale interno per la riga.
    # v3.5.0-alpha.167 — Prefer cost_rate_snap (snapshot al create/update assignment).
    # Garantisce stabilità storica: cambio rate Resource futuro NON impatta JCL già
    # consuntivate. Fallback Resource.internal_cost_hourly per assignment pre-α.167
    # (cost_rate_snap=NULL) — back-compat con DB esistenti.
    new_cost_accrued = 0.0
    for b in done_bookings:
        for a in (b.assignments or []):
            if not a.start_datetime or not a.end_datetime:
                continue
            rate = getattr(a, "cost_rate_snap", None)
            if rate is None or rate <= 0:
                res = getattr(a, "resource", None)
                if res is None:
                    continue
                rate = res.internal_cost_hourly
                if rate is None or rate <= 0:
                    continue
            hours_a = max(0.0, (a.end_datetime - a.start_datetime).total_seconds() / 3600.0)
            new_cost_accrued += hours_a * rate
    new_cost_accrued = round(new_cost_accrued, 2)

    # v3.5.0-alpha.172 Restructure — JCL solo time-based (vedi guard sopra).
    # actual_qty = ore done convertite (regola billable α.171: max umana)
    # expected_qty = ore planned convertite (NESSUN booking → 0, non quoted)
    new_qty_actual_final = new_qty_actual
    expected_qty = new_qty_planned if all_bookings else 0.0
    new_qty_actual = new_qty_actual_final
    new_accrued = round(new_qty_actual * (jcl.unit_price or 0.0), 2)
    new_expected = round(expected_qty * (jcl.unit_price or 0.0), 2)

    new_work_date = max(
        (b.start_datetime.date() for b in done_bookings if b.start_datetime),
        default=None,
    )

    # v3.5.0-alpha.119 — Cost reale da fatture passive con priority ranking.
    # Fix double-count del Finding 1 smoke α.118: il vecchio filtro OR-soup
    # (jcl OR job OR project) sommava la stessa fattura su tutte le JCL del
    # job se più JCL avevano resource_id matching → cost_external job-level
    # raddoppiato/triplicato.
    #
    # Nuovo modello di attribuzione (priority + esclusività):
    #   livello 1 (jcl):     SupplierInvoice.job_cost_line_id IS NOT NULL
    #                        → attribuita a quella JCL esclusivamente
    #   livello 2 (job):     SupplierInvoice.job_cost_line_id IS NULL AND
    #                        SupplierInvoice.job_id IS NOT NULL
    #                        → distribuita pro-quota sulle JCL del job con
    #                          resource_id matching (somma a quota uguale)
    #   livello 3 (project): solo project_id, no job/jcl
    #                        → distribuita pro-quota sulle JCL del progetto
    #                          (qualsiasi job) con resource_id matching
    #
    # Vincolo: una fattura contribuisce a UNA sola JCL al livello 1, o si
    # spalma su N JCL ai livelli 2/3 — la somma su tutte le JCL del job/
    # project resta sempre = total fattura.
    new_cost_external = 0.0
    try:
        from app.models import SupplierInvoice, BookingAssignment as _BA
        # Risorse coinvolte = quelle dei booking della JCL
        resource_ids = set()
        for b in all_bookings:
            for a in (b.assignments or []):
                if a.resource_id:
                    resource_ids.add(a.resource_id)
        if resource_ids and jcl.job_id:
            from app.models import Job as _Job, JobCostLine as _JCL
            job_row = db.query(_Job).filter(_Job.id == jcl.job_id).first()
            if job_row:
                base_q = db.query(SupplierInvoice).filter(
                    SupplierInvoice.resource_id.in_(resource_ids),
                    SupplierInvoice.deleted_at.is_(None),
                )

                # Livello 1: fatture linkate ESATTAMENTE a questa JCL
                lvl1 = base_q.filter(SupplierInvoice.job_cost_line_id == jcl.id).all()
                total_lvl1 = sum((si.amount_total or si.amount_net or 0) for si in lvl1)

                # Livello 2: fatture linkate al job (no jcl), pro-quota fra
                # JCL del job con almeno una resource matching
                lvl2_invoices = base_q.filter(
                    SupplierInvoice.job_cost_line_id.is_(None),
                    SupplierInvoice.job_id == jcl.job_id,
                ).all()
                total_lvl2_share = 0.0
                if lvl2_invoices:
                    n_share = _count_jcl_matching_resources(
                        db, job_id=jcl.job_id, project_id=None, invoices=lvl2_invoices
                    )
                    if n_share > 0:
                        total_lvl2_share = sum(
                            (si.amount_total or si.amount_net or 0)
                            for si in lvl2_invoices
                        ) / n_share

                # Livello 3: fatture solo project (no jcl, no job)
                lvl3_invoices = base_q.filter(
                    SupplierInvoice.job_cost_line_id.is_(None),
                    SupplierInvoice.job_id.is_(None),
                    SupplierInvoice.project_id == job_row.project_id,
                ).all()
                total_lvl3_share = 0.0
                if lvl3_invoices:
                    n_share = _count_jcl_matching_resources(
                        db, job_id=None, project_id=job_row.project_id,
                        invoices=lvl3_invoices,
                    )
                    if n_share > 0:
                        total_lvl3_share = sum(
                            (si.amount_total or si.amount_net or 0)
                            for si in lvl3_invoices
                        ) / n_share

                new_cost_external = round(
                    total_lvl1 + total_lvl2_share + total_lvl3_share, 2
                )
    except Exception as _e:
        # Non bloccare il recompute se l'aggregazione fallisce
        print(f"[recompute] cost_external aggregation failed for jcl#{jcl.id}: {_e}")
        new_cost_external = jcl.total_cost_external or 0.0

    changed = (
        abs((jcl.quantity_actual or 0) - new_qty_actual) > 1e-6
        or abs((jcl.total_accrued or 0) - new_accrued) > 1e-2
        or abs((jcl.total_expected or 0) - new_expected) > 1e-2
        or abs((jcl.total_cost_accrued or 0) - new_cost_accrued) > 1e-2
        or abs((jcl.total_cost_external or 0) - new_cost_external) > 1e-2
        or jcl.work_date != new_work_date
    )
    jcl.quantity_actual = new_qty_actual
    jcl.total_accrued = new_accrued
    jcl.total_expected = new_expected
    jcl.total_cost_accrued = new_cost_accrued
    jcl.total_cost_external = new_cost_external
    jcl.work_date = new_work_date
    # v3.5.0-alpha.115 — reset stale flag dopo recompute (dirty flag pattern)
    jcl.accrued_stale = False
    return {
        "updated": changed,
        "jcl_id": jcl.id,
        "unit": unit,
        "bookings_done": len(done_bookings),
        "bookings_planned": len(all_bookings),
        "total_hours": round(done_hours, 2),
        "planned_hours": round(planned_hours, 2),
        "quantity_actual": new_qty_actual,
        "quantity_planned": new_qty_planned,
        "total_accrued": new_accrued,
        "total_expected": new_expected,
        "total_cost_accrued": new_cost_accrued,
        "total_cost_external": new_cost_external,
        "weighted_revenue": weighted,
    }


# v3.5.0-alpha.115 — Dirty flag pattern: hook leggero da chiamare su tutti
# i path booking-mutate. Setta stale=True senza ricomputare subito.
# reconcile-all bulk userà solo le righe stale.
def mark_jcl_stale(db: Session, jcl_ids) -> int:
    """Marca una o più JCL come stale (lazy reconcile pattern).
    Accetta int singolo o lista. No-op se id None/vuoti."""
    from app.models import JobCostLine
    if not jcl_ids:
        return 0
    if isinstance(jcl_ids, int):
        jcl_ids = [jcl_ids]
    ids = [i for i in jcl_ids if i]
    if not ids:
        return 0
    db.query(JobCostLine).filter(JobCostLine.id.in_(ids)).update(
        {JobCostLine.accrued_stale: True}, synchronize_session=False
    )
    return len(ids)


def mark_booking_jcl_stale(db: Session, booking) -> int:
    """Helper specifico: marca la JCL associata al booking come stale."""
    if booking is None or not booking.job_cost_line_id:
        return 0
    return mark_jcl_stale(db, [booking.job_cost_line_id])


def recompute_for_booking(db: Session, booking) -> Optional[dict]:
    """Helper per gli hook negli endpoint planning. Se il booking ha
    una cost line associata, ricomputa la sua actual e ritorna il
    risultato. Altrimenti None.

    v3.5.0-alpha.61: dopo il recompute, se la JCL ha almeno una slice già
    fatturata e il maturato eccede il già fatturato → emette notifica
    `extra_after_billed` (idempotente). Permette al producer/manager/
    accounting di accorgersi al volo che è emerso lavoro extra dopo la
    fatturazione, e di valutare trasmissione/coordinamento col commerciale.
    """
    if booking is None or not booking.job_cost_line_id:
        return None
    from app.models import JobCostLine
    jcl = db.query(JobCostLine).filter(JobCostLine.id == booking.job_cost_line_id).first()
    if not jcl:
        return None
    result = recompute_cost_line_actual(db, jcl)
    try:
        from app.services.billing_slice_guard import maybe_notify_extra_after_billed
        maybe_notify_extra_after_billed(db, jcl)
    except Exception as e:
        # Notifica non bloccante: l'errore non deve far fallire l'hook.
        print(f"[recompute_for_booking] extra_after_billed notify failed: {e}")
    return result


def recompute_for_job(db: Session, job_id: int) -> dict:
    """Ricalcola tutte le JobCostLine di un job. Utile come azione di
    riconciliazione (fix one-shot per DB esistenti dove i booking sono
    stati marcati done senza generare il sync)."""
    from app.models import JobCostLine
    jcls = db.query(JobCostLine).filter(JobCostLine.job_id == job_id).all()
    results = []
    for jcl in jcls:
        r = recompute_cost_line_actual(db, jcl)
        if r.get("updated"):
            results.append(r)
    return {
        "job_id": job_id,
        "lines_total": len(jcls),
        "lines_updated": len(results),
        "details": results,
    }
