from app.models.models import DeliveryTemplate, DeliveryItem
from app.services.delivery_timeline_service import effective_timeline


def test_item_inherits_template_default(db, tenant_id):
    t = DeliveryTemplate(tenant_id=tenant_id, code="V-X", name="Vision",
                         default_tc_start="00:59:59:00",
                         default_program_start="01:00:00:00")
    db.add(t); db.flush()
    item = DeliveryItem(tenant_id=tenant_id, delivery_template_id=t.id, name="DCP")
    db.add(item); db.flush()
    eff = effective_timeline(db, item)
    assert eff["tc_start"] == "00:59:59:00"
    assert eff["tc_start_inherited"] is True
    assert eff["program_start"] == "01:00:00:00"


def test_item_override_wins(db, tenant_id):
    t = DeliveryTemplate(tenant_id=tenant_id, code="V-Y", name="Vision",
                         default_tc_start="00:59:59:00")
    db.add(t); db.flush()
    item = DeliveryItem(tenant_id=tenant_id, delivery_template_id=t.id, name="Trailer",
                        tc_start="10:00:00:00")
    db.add(item); db.flush()
    eff = effective_timeline(db, item)
    assert eff["tc_start"] == "10:00:00:00"
    assert eff["tc_start_inherited"] is False
