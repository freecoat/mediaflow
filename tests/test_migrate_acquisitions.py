"""Test di migrazione per tabelle Acquisizioni (Task 2)."""
from sqlalchemy import create_engine, inspect
import scripts.migrate_acquisitions as mig


def test_migration_creates_tables(monkeypatch, tmp_path):
    """Verifica che la migrazione crei le 4 tabelle acquisizioni idempotentemente."""
    db_file = tmp_path / "t.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    monkeypatch.setattr(mig, "engine", engine)

    # Prima volta: crea tabelle
    mig.main()
    insp = inspect(engine)
    for t in ("acquisitions", "contacts", "activities", "acquisition_departments"):
        assert t in insp.get_table_names(), f"Tabella {t} non trovata dopo migration"

    # Seconda volta: idempotente, non esplode
    mig.main()
    insp = inspect(engine)
    for t in ("acquisitions", "contacts", "activities", "acquisition_departments"):
        assert t in insp.get_table_names(), f"Tabella {t} scomparsa dopo secondo run"
