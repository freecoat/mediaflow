"""
MediaFlow — migrazione KDM/DKDM request tracking (v3.5.0-alpha.172.226)

Crea: dcp_cpls, cinema_facilities, cinema_servers, kdm_requests,
      kdm_request_events, kdm_request_links.
Tutto in tabelle nuove, nessuna ALTER su tabelle esistenti. Idempotente.

Esegui:
  python scripts/migrate_kdm.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import inspect
from app.database import engine, create_tables
from app.models import (  # noqa: F401
    DcpCpl, CinemaFacility, CinemaServer, KdmRequest, KdmRequestEvent,
    KdmRequestLink,
)


def migrate():
    print("▸ MediaFlow · migrazione KDM/DKDM (v3.5.0-alpha.172.226)")
    print("─" * 70)
    create_tables()
    names = inspect(engine).get_table_names()
    for t in ("dcp_cpls", "cinema_facilities", "cinema_servers",
              "kdm_requests", "kdm_request_events", "kdm_request_links"):
        print(f"  {'✓' if t in names else '✗'} {t}")
    print("▸ Fatto.")


if __name__ == "__main__":
    migrate()
