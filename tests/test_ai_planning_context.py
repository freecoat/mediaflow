"""v3.5.0-alpha.172.188 — regressione: il copilot sulla pagina /planning
crashava (500) perché _build_planning_context referenziava
UnavailabilityKind.weekend (inesistente) nella label-map indisponibilità.
"""
from datetime import date, timedelta
from app.models import models as m
from app.services import ai_context


def test_planning_context_with_unavailability_no_crash(db, monkeypatch):
    monkeypatch.setattr(ai_context, "CURRENT_TENANT", 1)
    t = db.query(m.Tenant).filter(m.Tenant.id == 1).first()
    if not t:
        db.add(m.Tenant(id=1, name="T", slug="t", default_currency="EUR")); db.flush()
    r = m.Resource(tenant_id=1, name="Tecnico", type=m.ResourceType.person_internal)
    db.add(r); db.flush()
    today = date.today()
    u = m.ResourceUnavailability(
        resource_id=r.id, start_date=today, end_date=today + timedelta(days=2),
        kind=m.UnavailabilityKind.holiday, status=m.UnavailabilityStatus.approved,
    )
    db.add(u); db.flush()
    # Prima del fix: AttributeError 'UnavailabilityKind' has no attribute 'weekend'.
    out = ai_context._build_planning_context(db)
    assert isinstance(out, str)
    assert "Festività" in out  # la label-map si è costruita senza crash


def test_planning_context_permit_recovery_labels(db, monkeypatch):
    monkeypatch.setattr(ai_context, "CURRENT_TENANT", 1)
    t = db.query(m.Tenant).filter(m.Tenant.id == 1).first()
    if not t:
        db.add(m.Tenant(id=1, name="T", slug="t", default_currency="EUR")); db.flush()
    r = m.Resource(tenant_id=1, name="Tec2", type=m.ResourceType.person_internal)
    db.add(r); db.flush()
    today = date.today()
    db.add(m.ResourceUnavailability(
        resource_id=r.id, start_date=today, end_date=today + timedelta(days=1),
        kind=m.UnavailabilityKind.permit_rol, status=m.UnavailabilityStatus.approved,
    ))
    db.flush()
    out = ai_context._build_planning_context(db)
    assert "Permesso ROL" in out
