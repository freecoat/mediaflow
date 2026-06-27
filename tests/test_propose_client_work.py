import pytest, json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, Client, ClientWork
from app.services.ai_capability_registry import get_handler
import app.services.ai_assistant  # noqa: F401


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    s.add(Client(id=1, tenant_id=1, name="Lucky Red")); s.commit()
    yield s
    s.close()


def test_propose_client_work_creates_filmography_entry(db):
    h = get_handler("propose_client_work")
    out = h(db, {"client_id": 1, "title": "Queer", "year": 2024,
                 "kind": "film", "director": "Guadagnino",
                 "sources": ["https://imdb.com/x"]})
    db.commit()
    w = db.query(ClientWork).get(out["client_work_id"])
    assert w.title == "Queer" and w.year == 2024 and w.client_id == 1
    assert w.ai_imported is True
    assert "imdb.com" in (w.sources_json or "")


def test_propose_client_work_requires_title_and_client(db):
    with pytest.raises(ValueError):
        get_handler("propose_client_work")(db, {"client_id": 1})
    with pytest.raises(ValueError):
        get_handler("propose_client_work")(db, {"title": "X"})
