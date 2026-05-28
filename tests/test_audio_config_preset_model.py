from app.models.models import DeliveryItem, DeliveryTemplate, AudioConfigPreset


def test_delivery_item_has_timeline_fields():
    cols = {c.name for c in DeliveryItem.__table__.columns}
    assert {"tc_start", "program_start", "timeline_segments",
            "audio_config_preset_id", "audio_config_code"} <= cols


def test_delivery_template_has_default_timeline_fields():
    cols = {c.name for c in DeliveryTemplate.__table__.columns}
    assert {"default_tc_start", "default_program_start",
            "default_timeline_segments"} <= cols


def test_audio_config_preset_model(db, tenant_id):
    t = DeliveryTemplate(tenant_id=tenant_id, code="TST-AC", name="Test AC")
    db.add(t); db.flush()
    p = AudioConfigPreset(
        tenant_id=tenant_id, delivery_template_id=t.id, code="8T07",
        name="8 tracce 5.1+ST",
        track_layout=[{"track_label": "5.1 L", "channel_config": "5.1",
                       "codec": "PCM", "sample_rate": 48000, "bit_depth": 24}],
    )
    db.add(p); db.flush()
    assert p.id is not None
    assert p.is_active is True
    assert p.track_layout[0]["track_label"] == "5.1 L"
