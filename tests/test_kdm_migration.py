# tests/test_kdm_migration.py
from sqlalchemy import inspect
from app.database import engine
import app.main as main


def test_auto_migrate_kdm_creates_tables():
    main._auto_migrate_kdm_tables()
    names = inspect(engine).get_table_names()
    for t in ("dcp_cpls", "cinema_facilities", "cinema_servers",
              "kdm_requests", "kdm_request_events", "kdm_request_links"):
        assert t in names
