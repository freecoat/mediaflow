"""
MediaFlow — sessione database (SQLAlchemy 2.0 async-ready).
Supporta SQLite per sviluppo locale e PostgreSQL per produzione.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings

# Nota: per semplicità usiamo il motore sincrono con SQLite.
# Per passare ad async + PostgreSQL basta sostituire con
# create_async_engine e AsyncSession.
engine = create_engine(
    str(settings.database_url),
    connect_args={"check_same_thread": False} if "sqlite" in str(settings.database_url) else {},
    echo=(settings.app_env == "development"),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class per tutti i modelli ORM."""
    pass


def get_db():
    """Dependency injection: fornisce una sessione DB per ogni request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Crea tutte le tabelle al primo avvio (dev only — usa Alembic in produzione)."""
    Base.metadata.create_all(bind=engine)
