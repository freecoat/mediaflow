# tests/test_update_client_capability.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, Client
from app.services.ai_capability_registry import get_handler
import app.services.ai_assistant  # noqa: F401  (registra handler)


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="Lucky Red", city="Roma")); s.commit()
    yield s
    s.close()


def test_update_client_only_changes_given_fields(db):
    h = get_handler("update_client")
    out = h(db, {"client_id": 1, "vat_number": "IT01234567890", "website": "luckyred.it"})
    db.commit()
    c = db.get(Client, 1)
    assert c.vat_number == "IT01234567890"
    assert c.website == "luckyred.it"
    assert c.city == "Roma"  # invariato
    assert c.name == "Lucky Red"  # invariato
    assert set(out["changed_fields"]) == {"vat_number", "website"}


def test_update_client_missing_id_raises(db):
    with pytest.raises(ValueError):
        get_handler("update_client")(db, {"website": "x.it"})


def test_update_client_unknown_client_raises(db):
    with pytest.raises(ValueError):
        get_handler("update_client")(db, {"client_id": 999, "city": "Milano"})


def test_update_client_skips_empty_string(db):
    h = get_handler("update_client")
    out = h(db, {"client_id": 1, "city": ""})
    db.commit()
    c = db.get(Client, 1)
    assert c.city == "Roma"  # invariato — stringa vuota ignorata
    assert "city" not in out["changed_fields"]
