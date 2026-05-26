"""Pytest fixtures globali per test Bundle L.

DB in-memory SQLite per test isolato. Ricreato per ogni test.
Tenant fixture id=1 default (allineato a CURRENT_TENANT).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.models.models import Base


@pytest.fixture
def db() -> Session:
    """SQLite in-memory + schema fresh per test."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def tenant_id() -> int:
    """Tenant fixture per test (allineato a CURRENT_TENANT=1)."""
    return 1
