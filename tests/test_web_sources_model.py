from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant


def test_tenant_web_sources_column():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    t = Tenant(id=1, name="T", slug="t", is_active=True,
               web_sources=["filmitalia.org", "imdb.com"])
    s.add(t); s.commit(); s.refresh(t)
    assert t.web_sources == ["filmitalia.org", "imdb.com"]
    t2 = Tenant(id=2, name="U", slug="u", is_active=True)
    s.add(t2); s.commit(); s.refresh(t2)
    assert t2.web_sources is None
