from app.services.kdm_adapters import get_adapter


def test_manual_adapter_default():
    a = get_adapter("manual")
    assert a.send_kdm(None)["mode"] == "manual"
    assert a.fetch_certs(None) == []


def test_unknown_adapter_falls_back_to_manual():
    a = get_adapter("does-not-exist")
    assert a.send_kdm(None)["mode"] == "manual"
