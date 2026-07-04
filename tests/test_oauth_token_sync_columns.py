from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool
from app.models.models import Base, UserOAuthToken


def _mem_engine():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return e


def test_useroauthtoken_has_sync_columns():
    e = _mem_engine()
    cols = {c["name"] for c in inspect(e).get_columns("user_oauth_tokens")}
    assert "auto_sync_calendar" in cols
    assert "claqo_calendar_id" in cols


def test_default_auto_sync_is_false():
    tok = UserOAuthToken(user_id=1, provider="google")
    # default applicato dall'ORM al flush; a livello attributo verifichiamo il default column
    assert UserOAuthToken.__table__.c.auto_sync_calendar.default.arg is False
