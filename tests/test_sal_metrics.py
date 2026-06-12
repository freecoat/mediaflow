"""SAL — service sal_metrics: ore quotate/pianificate/lavorate + allarme.

DB in-memory. Costruisce Job + JobCostLine (unit vari) + Booking
(con/senza assignment) per ore note. Le ore di un booking senza assignment
sono la shell-duration (end-start), deterministiche (es. 09:00→17:00 = 8h).
"""
import pytest
from datetime import datetime

from app.services import sal_metrics


# ── Helper costruttori ───────────────────────────────────────────

def _hierarchy(db, *, daily_policy=None):
    """Crea Tenant→Client→Project e ritorna (client, project)."""
    from app.models import Client, Project
    cli = Client(tenant_id=1, name="ACME")
    db.add(cli); db.flush()
    prj = Project(tenant_id=1, code="P-SAL", title="Progetto SAL", client_id=cli.id)
    db.add(prj); db.flush()
    return cli, prj


def _job(db, prj, cli, *, code="J-1"):
    from app.models import Job
    job = Job(tenant_id=1, code=code, title="Job " + code,
              project_id=prj.id, client_id=cli.id)
    db.add(job); db.flush()
    return job


def _jcl(db, job, *, unit, qty, price=100.0, price_item_id=None, desc="Voce"):
    from app.models import JobCostLine
    jcl = JobCostLine(
        tenant_id=1, job_id=job.id, description=desc, unit=unit,
        quantity_quoted=qty, unit_price=price, price_item_id=price_item_id,
    )
    db.add(jcl); db.flush()
    return jcl


def _booking(db, job, *, start, end, status=None, execution=None,
             assignments=None):
    """Booking con shell-duration (no assignment) o con assignment espliciti.
    `assignments` = list di (resource, start, end)."""
    from app.models import (
        Booking, BookingAssignment, BookingStatus,
        BookingExecutionStatus, BookingState,
    )
    if status is None:
        status = BookingStatus.confirmed
    if execution is None:
        execution = BookingExecutionStatus.planned
    b = Booking(
        tenant_id=1, job_id=job.id,
        start_datetime=start, end_datetime=end,
        status=status, execution_status=execution,
    )
    db.add(b); db.flush()
    if assignments:
        for res, a_start, a_end in assignments:
            db.add(BookingAssignment(
                booking_id=b.id, resource_id=res.id,
                start_datetime=a_start, end_datetime=a_end,
            ))
        db.flush()
    db.refresh(b)
    return b


def _resource(db, *, name, department_id=None):
    from app.models import Resource, ResourceType
    r = Resource(tenant_id=1, name=name, type=ResourceType.person_internal,
                 department_id=department_id, is_active=True)
    db.add(r); db.flush()
    return r


def _department(db, *, name, code=None):
    from app.models import Department
    d = Department(tenant_id=1, name=name, code=(code or name.upper().replace("/", "-")))
    db.add(d); db.flush()
    return d


# ── Gruppo 1: quoted_hours unit-tempo vs corpo ───────────────────

def test_quoted_hours_hr(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="hr", qty=10)
    assert sal_metrics.quoted_hours(job) == 10.0


def test_quoted_hours_day_with_policy_daily_8(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="day", qty=2)
    assert sal_metrics.quoted_hours(job, daily_hours=8.0) == 16.0


def test_quoted_hours_pc_excluded(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="pc", qty=5)
    assert sal_metrics.quoted_hours(job) == 0.0


def test_quoted_hours_mix(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="hr", qty=10)      # 10
    _jcl(db, job, unit="day", qty=2)      # 16 @ daily 8
    _jcl(db, job, unit="pc", qty=5)       # 0 (escluso)
    _jcl(db, job, unit="ore", qty=4)      # 4 (italiano)
    assert sal_metrics.quoted_hours(job, daily_hours=8.0) == 30.0


def test_quoted_hours_unit_normalized_case_space(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit=" HR ", qty=3)
    _jcl(db, job, unit="Giorni", qty=1)   # giorno-unit → ×daily
    assert sal_metrics.quoted_hours(job, daily_hours=8.0) == 11.0


# ── Gruppo 2: quoted senza policy → default 8 ────────────────────

def test_quoted_hours_default_daily(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="day", qty=3)
    # default param 8.0
    assert sal_metrics.quoted_hours(job) == 24.0


# ── Gruppo 3: planned_hours = Σ billable non-cancelled ───────────

def test_planned_hours_sums_non_cancelled(db):
    from app.models import BookingStatus, BookingExecutionStatus
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    # booking 8h (09→17), planned
    _booking(db, job, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 17, 0))
    # booking 4h (09→13), confirmed
    _booking(db, job, start=datetime(2026, 6, 11, 9, 0),
             end=datetime(2026, 6, 11, 13, 0))
    # cancelled → escluso
    _booking(db, job, start=datetime(2026, 6, 12, 9, 0),
             end=datetime(2026, 6, 12, 17, 0),
             status=BookingStatus.cancelled)
    assert sal_metrics.planned_hours(job) == 12.0


# ── Gruppo 4: worked_hours = solo done ───────────────────────────

def test_worked_hours_only_done(db):
    from app.models import BookingExecutionStatus
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _booking(db, job, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 17, 0),
             execution=BookingExecutionStatus.done)            # 8h done
    _booking(db, job, start=datetime(2026, 6, 11, 9, 0),
             end=datetime(2026, 6, 11, 13, 0),
             execution=BookingExecutionStatus.planned)         # 4h non-done
    assert sal_metrics.worked_hours(job) == 8.0


def test_worked_hours_excludes_cancelled_done(db):
    from app.models import BookingStatus, BookingExecutionStatus
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    # cancelled anche se done → escluso (non-cancelled è prerequisito)
    _booking(db, job, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 17, 0),
             status=BookingStatus.cancelled,
             execution=BookingExecutionStatus.done)
    assert sal_metrics.worked_hours(job) == 0.0


# ── Gruppo 5: by_department ──────────────────────────────────────

def test_by_department_quoted_planned_worked(db):
    from app.models import BookingExecutionStatus
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    dep_di = _department(db, name="DI/Video")
    dep_audio = _department(db, name="Audio")
    # PriceItem per dare department_id alla JCL
    from app.models import PriceItem, PriceCategory
    cat = PriceCategory(tenant_id=1, name="Cat")
    db.add(cat); db.flush()
    pi_di = PriceItem(tenant_id=1, category_id=cat.id, name="Color",
                      unit="hr", department_id=dep_di.id)
    pi_audio = PriceItem(tenant_id=1, category_id=cat.id, name="Mix",
                         unit="hr", department_id=dep_audio.id)
    db.add_all([pi_di, pi_audio]); db.flush()
    _jcl(db, job, unit="hr", qty=10, price_item_id=pi_di.id)      # 10 quotate DI
    _jcl(db, job, unit="hr", qty=6, price_item_id=pi_audio.id)    # 6 quotate Audio
    _jcl(db, job, unit="hr", qty=4, price_item_id=None)           # 4 quotate Altro (0)

    res_di = _resource(db, name="Colorist", department_id=dep_di.id)
    res_audio = _resource(db, name="Mixer", department_id=dep_audio.id)
    # booking DI done 8h
    _booking(db, job, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 17, 0),
             execution=BookingExecutionStatus.done,
             assignments=[(res_di, datetime(2026, 6, 10, 9, 0),
                           datetime(2026, 6, 10, 17, 0))])
    # booking Audio planned (non done) 4h
    _booking(db, job, start=datetime(2026, 6, 11, 9, 0),
             end=datetime(2026, 6, 11, 13, 0),
             execution=BookingExecutionStatus.planned,
             assignments=[(res_audio, datetime(2026, 6, 11, 9, 0),
                           datetime(2026, 6, 11, 13, 0))])

    bd = sal_metrics.by_department(job, daily_hours=8.0)
    assert bd[dep_di.id]["quoted"] == 10.0
    assert bd[dep_di.id]["worked"] == 8.0
    assert bd[dep_di.id]["planned"] == 8.0      # done è anche planned (non-cancelled)
    assert bd[dep_audio.id]["quoted"] == 6.0
    assert bd[dep_audio.id]["worked"] == 0.0
    assert bd[dep_audio.id]["planned"] == 4.0
    # chiave 0 = Altro (JCL senza price_item.department)
    assert bd[0]["quoted"] == 4.0


def test_by_department_none_goes_to_zero(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="hr", qty=5, price_item_id=None)   # nessun dept → 0
    bd = sal_metrics.by_department(job)
    assert bd[0]["quoted"] == 5.0


# ── Gruppo 6: job_alarm ──────────────────────────────────────────

def test_alarm_red_worked_exceeds_quoted(db):
    from app.models import BookingExecutionStatus
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="hr", qty=4)
    _booking(db, job, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 17, 0),
             execution=BookingExecutionStatus.done)   # 8h worked > 4 quoted
    assert sal_metrics.job_alarm(job) == "red"


def test_alarm_red_planned_exceeds_quoted(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="hr", qty=4)
    _booking(db, job, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 17, 0))   # 8h planned > 4 quoted, non done
    assert sal_metrics.job_alarm(job) == "red"


def test_alarm_amber_at_90pct(db):
    from app.models import BookingExecutionStatus
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="hr", qty=10)
    # worked 9h = 90% di 10 → amber
    _booking(db, job, start=datetime(2026, 6, 10, 8, 0),
             end=datetime(2026, 6, 10, 17, 0),
             execution=BookingExecutionStatus.done)
    assert sal_metrics.job_alarm(job) == "amber"


def test_alarm_none_below_90(db):
    from app.models import BookingExecutionStatus
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="hr", qty=10)
    _booking(db, job, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 13, 0),
             execution=BookingExecutionStatus.done)   # 4h = 40%
    assert sal_metrics.job_alarm(job) == "none"


def test_alarm_none_when_quoted_zero(db):
    from app.models import BookingExecutionStatus
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    # nessuna JCL a tempo → quoted 0
    _jcl(db, job, unit="pc", qty=5)
    _booking(db, job, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 17, 0),
             execution=BookingExecutionStatus.done)
    assert sal_metrics.job_alarm(job) == "none"


# ── Gruppo 6b: job_metrics ───────────────────────────────────────

def test_job_metrics_shape_and_pct(db):
    from app.models import BookingExecutionStatus
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="hr", qty=10)
    _booking(db, job, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 13, 0),
             execution=BookingExecutionStatus.done)   # 4h worked
    m = sal_metrics.job_metrics(job, daily_hours=8.0)
    assert m["quoted"] == 10.0
    assert m["worked"] == 4.0
    assert m["planned"] == 4.0
    assert m["pct"] == pytest.approx(0.4)
    assert m["alarm"] == "none"


def test_job_metrics_pct_zero_when_quoted_zero(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="pc", qty=5)
    m = sal_metrics.job_metrics(job)
    assert m["pct"] == 0.0


# ── Gruppo 7: project_metrics ────────────────────────────────────

def test_project_metrics_sums_jobs_default_policy(db):
    from app.models import BookingExecutionStatus
    cli, prj = _hierarchy(db)
    j1 = _job(db, prj, cli, code="J-1")
    j2 = _job(db, prj, cli, code="J-2")
    _jcl(db, j1, unit="hr", qty=10)
    _jcl(db, j2, unit="hr", qty=20)
    _booking(db, j1, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 13, 0),
             execution=BookingExecutionStatus.done)    # 4h worked j1
    _booking(db, j2, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 17, 0),
             execution=BookingExecutionStatus.done)    # 8h worked j2
    db.commit()
    db.refresh(prj)
    m = sal_metrics.project_metrics(db, prj)
    assert m["quoted"] == 30.0
    assert m["worked"] == 12.0
    assert m["planned"] == 12.0
    assert m["pct"] == pytest.approx(12.0 / 30.0)
    assert m["job_count"] == 2
    assert m["alarm"] == "none"


def test_project_metrics_alarm_worst_of_jobs(db):
    from app.models import BookingExecutionStatus
    cli, prj = _hierarchy(db)
    j1 = _job(db, prj, cli, code="J-1")   # ok
    j2 = _job(db, prj, cli, code="J-2")   # red
    _jcl(db, j1, unit="hr", qty=100)
    _jcl(db, j2, unit="hr", qty=2)
    _booking(db, j1, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 17, 0),
             execution=BookingExecutionStatus.done)   # 8h / 100
    _booking(db, j2, start=datetime(2026, 6, 10, 9, 0),
             end=datetime(2026, 6, 10, 17, 0),
             execution=BookingExecutionStatus.done)   # 8h / 2 → red
    db.commit(); db.refresh(prj)
    m = sal_metrics.project_metrics(db, prj)
    assert m["alarm"] == "red"


def test_project_metrics_uses_tenant_default_policy_for_days(db):
    """daily_hours risolto dalla WorkingHoursPolicy default del tenant."""
    from app.models import WorkingHoursPolicy
    from datetime import time
    cli, prj = _hierarchy(db)
    pol = WorkingHoursPolicy(
        tenant_id=1, name="Default", is_default=True,
        morning_start=time(9, 0), morning_end=time(13, 0),
        daily_hours_threshold=6.0,
    )
    db.add(pol); db.flush()
    job = _job(db, prj, cli)
    _jcl(db, job, unit="day", qty=2)   # 2 × 6 = 12
    db.commit(); db.refresh(prj)
    m = sal_metrics.project_metrics(db, prj)
    assert m["quoted"] == 12.0


def test_project_metrics_pct_zero_when_quoted_zero(db):
    cli, prj = _hierarchy(db)
    job = _job(db, prj, cli)
    _jcl(db, job, unit="pc", qty=3)
    db.commit(); db.refresh(prj)
    m = sal_metrics.project_metrics(db, prj)
    assert m["pct"] == 0.0
    assert m["job_count"] == 1
