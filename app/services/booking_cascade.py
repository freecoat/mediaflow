"""Adaptive cascade per estensione durata booking (v3.4.32).

Quando l'operatore estende un booking di Δ minuti dalla card "Le mie",
i booking adiacenti (stessa risorsa, stesso giorno, start ≥ end del modificato)
vengono spostati avanti dello stesso Δ. Mai slittamento al giorno successivo.

Se il cascade fa entrare uno o più booking (anche solo in parte) nella fascia
straordinaria della WorkingHoursPolicy della risorsa, quei booking vengono
marcati `overtime_status=pending` e producer/manager ricevono notifica di
approvazione.

Limite assoluto: nessun booking può sforare `night_end` del giorno successivo
(per default 06:00 — copre i turni notturni di post-prod). Oltre = reject.

Su rifiuto overtime (vedi `split_overtime_to_next_day`): la parte regolare
resta sul giorno corrente, la parte oltre la fascia regolare diventa un
nuovo booking il giorno successivo (stessa policy oraria).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from app.models import (
    Booking, BookingAssignment, BookingChange, BookingOvertimeStatus,
    Resource, WorkingHoursPolicy,
)
from app.services.booking_cost import (
    has_overtime_window, working_day_end, absolute_day_limit,
)
from app.services.working_hours import get_holidays


@dataclass
class CascadeResult:
    booking_id: int
    delta_minutes: int
    moved_assignments: List[int] = field(default_factory=list)
    overtime_pending_booking_ids: List[int] = field(default_factory=list)
    rejected: bool = False
    reject_reason: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "booking_id": self.booking_id,
            "delta_minutes": self.delta_minutes,
            "moved_assignments": self.moved_assignments,
            "overtime_pending_booking_ids": self.overtime_pending_booking_ids,
            "rejected": self.rejected,
            "reject_reason": self.reject_reason,
        }


def _resource_policy(resource: Resource, db: Session) -> Optional[WorkingHoursPolicy]:
    if resource.working_hours_policy_id and resource.working_hours_policy:
        return resource.working_hours_policy
    return db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.is_default == True  # noqa: E712
    ).first()


def _refresh_envelope(booking: Booking) -> None:
    """Aggiorna start_datetime/end_datetime dal min/max degli assignments."""
    if not booking.assignments:
        return
    booking.start_datetime = min(a.start_datetime for a in booking.assignments)
    booking.end_datetime = max(a.end_datetime for a in booking.assignments)


def extend_booking_adaptive(
    booking: Booking,
    delta_minutes: int,
    db: Session,
) -> CascadeResult:
    """Estende il booking di delta_minutes (può essere negativo per accorciare).

    Logica:
      1. Calcola il nuovo end del booking modificato.
      2. Per ogni risorsa coinvolta nel booking, trova i booking adiacenti
         (stessa risorsa, stesso giorno, start ≥ vecchio_end ASC).
      3. Verifica che il cascade non sfori `absolute_day_limit` per nessuno.
      4. Se OK, applica shift +delta a tutti gli adiacenti + estende il booking.
      5. Marca `overtime_status=pending` su ogni booking che (dopo shift)
         cade fuori dalla fascia regolare della policy.
    """
    res = CascadeResult(booking_id=booking.id, delta_minutes=delta_minutes)
    if delta_minutes == 0:
        return res

    delta = timedelta(minutes=delta_minutes)

    # Cascade per ogni assignment del booking modificato
    affected_pairs: List[Tuple[BookingAssignment, BookingAssignment]] = []
    # affected_pairs = (assignment_to_shift, original_to_check_against)
    extending_assignments = list(booking.assignments)
    if not extending_assignments:
        res.rejected = True
        res.reject_reason = "Booking senza risorse assegnate"
        return res

    # Costruisco la lista delle modifiche, validate prima di applicare
    pending_updates: List[Tuple[BookingAssignment, datetime, datetime]] = []
    bookings_in_overtime_check: set[int] = set()

    for own_a in extending_assignments:
        resource = own_a.resource
        policy = _resource_policy(resource, db)
        if not policy:
            res.rejected = True
            res.reject_reason = f"Risorsa {resource.name}: nessuna WorkingHoursPolicy attiva"
            return res

        old_end = own_a.end_datetime
        new_end = old_end + delta
        # Confine giornata: new_end NON deve passare a domani.
        if new_end.date() > old_end.date() and delta_minutes > 0:
            res.rejected = True
            res.reject_reason = (
                f"Estensione a {new_end.strftime('%H:%M')} oltre la mezzanotte: "
                "i booking restano intra-day. Riduci la durata o riprogramma."
            )
            return res
        if delta_minutes < 0 and new_end <= own_a.start_datetime:
            res.rejected = True
            res.reject_reason = "Riduzione troppo grande: durata risultante non positiva"
            return res

        pending_updates.append((own_a, own_a.start_datetime, new_end))
        bookings_in_overtime_check.add(own_a.booking_id)

        if delta_minutes > 0:
            # Trova booking adiacenti (stessa risorsa, stessa giornata,
            # start ≥ old_end). Ordinati per start crescente.
            day_start = datetime.combine(old_end.date(), time(0, 0))
            day_end = day_start + timedelta(days=1)
            adjacents = (
                db.query(BookingAssignment)
                .options(joinedload(BookingAssignment.booking))
                .filter(
                    BookingAssignment.resource_id == resource.id,
                    BookingAssignment.id != own_a.id,
                    BookingAssignment.start_datetime >= old_end,
                    BookingAssignment.start_datetime < day_end,
                )
                .order_by(BookingAssignment.start_datetime.asc())
                .all()
            )
            shift_so_far = delta
            for adj in adjacents:
                new_adj_start = adj.start_datetime + shift_so_far
                new_adj_end = adj.end_datetime + shift_so_far
                # Non slittare a domani: ogni adiacente deve restare intra-day
                if new_adj_end.date() > old_end.date():
                    res.rejected = True
                    res.reject_reason = (
                        f"Cascade su risorsa {resource.name}: "
                        "uno dei booking successivi sforerebbe la mezzanotte. "
                        "Sposta o accorcia uno dei booking nella stessa giornata."
                    )
                    return res
                # Limite assoluto: night_end giorno dopo
                abs_limit = absolute_day_limit(old_end.date(), policy)
                if new_adj_end > abs_limit:
                    res.rejected = True
                    res.reject_reason = (
                        f"Cascade su risorsa {resource.name}: "
                        f"un booking successivo sforerebbe il limite assoluto "
                        f"({abs_limit.strftime('%H:%M')} del giorno successivo)."
                    )
                    return res
                pending_updates.append((adj, new_adj_start, new_adj_end))
                bookings_in_overtime_check.add(adj.booking_id)

    # Limite assoluto sul booking principale modificato
    for own_a in extending_assignments:
        policy = _resource_policy(own_a.resource, db)
        if not policy:
            continue
        new_end = own_a.end_datetime + delta
        abs_limit = absolute_day_limit(own_a.start_datetime.date(), policy)
        if new_end > abs_limit:
            res.rejected = True
            res.reject_reason = (
                f"Estensione su {own_a.resource.name}: "
                f"sforerebbe il limite assoluto giornaliero "
                f"({abs_limit.strftime('%H:%M')} del giorno successivo)."
            )
            return res

    # Applico
    for assignment, new_start, new_end in pending_updates:
        # Snapshot original_end_datetime sul booking solo la prima volta
        b = assignment.booking
        if b.original_end_datetime is None:
            b.original_end_datetime = b.end_datetime
        assignment.start_datetime = new_start
        assignment.end_datetime = new_end
        res.moved_assignments.append(assignment.id)

    # Refresh envelope + check overtime su ogni booking toccato
    affected_bookings = (
        db.query(Booking).filter(Booking.id.in_(bookings_in_overtime_check)).all()
    )
    booking_overtime_pending: List[int] = []
    for b in affected_bookings:
        _refresh_envelope(b)
        # Verifica se uno qualsiasi degli assignment cade in fascia overtime
        is_ot = False
        for a in b.assignments:
            policy = _resource_policy(a.resource, db)
            if not policy:
                continue
            holidays_set = get_holidays(
                policy, a.start_datetime.year, a.end_datetime.year
            )
            if has_overtime_window(a.start_datetime, a.end_datetime, policy, holidays_set):
                is_ot = True
                break
        if is_ot and b.overtime_status == BookingOvertimeStatus.none:
            b.overtime_status = BookingOvertimeStatus.pending
            booking_overtime_pending.append(b.id)
            db.add(BookingChange(
                booking_id=b.id,
                kind="overtime_pending",
                summary=f"Auto-flag pending: cascade extend +{delta_minutes}min",
            ))

    res.overtime_pending_booking_ids = booking_overtime_pending
    db.add(BookingChange(
        booking_id=booking.id,
        kind="adaptive_extend",
        summary=f"Estensione adattiva {delta_minutes:+d} min, "
                f"{len(res.moved_assignments)} assignment toccati",
        payload={"delta_minutes": delta_minutes, "moved": res.moved_assignments,
                 "overtime_pending": booking_overtime_pending},
    ))

    db.commit()
    for b in affected_bookings:
        db.refresh(b)
    return res


def split_overtime_to_next_day(booking: Booking, db: Session) -> Optional[Booking]:
    """Su rifiuto overtime: spezza il booking. La parte dentro la fascia
    regolare resta sul giorno corrente, la parte overtime diventa un nuovo
    booking il giorno successivo (stesso job/cost_line/risorse, fascia
    morning_start del giorno dopo per la durata residua).

    Ritorna il nuovo booking creato (o None se nessuna porzione overtime).
    """
    if not booking.assignments:
        return None
    # Prendiamo policy della prima risorsa (assumiamo coerenza tra assignment
    # dello stesso booking; altrimenti faremmo split per-resource).
    first = booking.assignments[0]
    policy = _resource_policy(first.resource, db)
    if not policy:
        return None

    day = first.start_datetime.date()
    reg_end = working_day_end(day, policy)
    if not reg_end:
        return None

    # Calcola la "coda" overtime per ogni assignment
    overtime_queue: List[Tuple[BookingAssignment, timedelta]] = []
    for a in booking.assignments:
        if a.end_datetime > reg_end:
            extra = a.end_datetime - max(a.start_datetime, reg_end)
            if extra.total_seconds() > 0:
                overtime_queue.append((a, extra))
                # Tronca l'assignment alla fine fascia regolare
                a.end_datetime = reg_end

    if not overtime_queue:
        return None

    # Crea nuovo booking il giorno successivo, partendo da morning_start
    next_day = day + timedelta(days=1)
    next_morning = datetime.combine(next_day, policy.morning_start) if policy.morning_start \
        else datetime.combine(next_day, time(9, 0))

    new_booking = Booking(
        tenant_id=booking.tenant_id,
        job_id=booking.job_id,
        job_cost_line_id=booking.job_cost_line_id,
        start_datetime=next_morning,
        end_datetime=next_morning,  # ricalcolato sotto
        status=booking.status,
        kind=booking.kind,
        notes=(booking.notes or "") + f"\n[Auto] Split da booking #{booking.id} (overtime rifiutato)",
        priority=booking.priority,
    )
    db.add(new_booking)
    db.flush()

    for orig_a, dur in overtime_queue:
        new_a = BookingAssignment(
            booking_id=new_booking.id,
            resource_id=orig_a.resource_id,
            start_datetime=next_morning,
            end_datetime=next_morning + dur,
        )
        db.add(new_a)

    db.flush()
    new_booking.assignments  # populate
    _refresh_envelope(new_booking)
    _refresh_envelope(booking)

    db.add(BookingChange(
        booking_id=booking.id,
        kind="overtime_split",
        summary=f"Split overtime → nuovo booking #{new_booking.id} il {next_day.isoformat()}",
        payload={"new_booking_id": new_booking.id, "next_day": next_day.isoformat()},
    ))
    db.add(BookingChange(
        booking_id=new_booking.id,
        kind="overtime_split_target",
        summary=f"Generato da split overtime di booking #{booking.id}",
        payload={"source_booking_id": booking.id},
    ))
    db.commit()
    return new_booking
