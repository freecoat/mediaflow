import os
import tempfile

import pytest
from sqlalchemy import create_engine, text, inspect


@pytest.fixture
def old_shape_engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", future=True)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE tenants (id INTEGER PRIMARY KEY, name VARCHAR(100))
        """))
        conn.execute(text("""
            CREATE TABLE clients (id INTEGER PRIMARY KEY, tenant_id INTEGER, name VARCHAR(255))
        """))
        conn.execute(text("""
            CREATE TABLE contacts (
                id INTEGER NOT NULL,
                tenant_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                role VARCHAR(120),
                email VARCHAR(255),
                phone VARCHAR(50),
                notes TEXT,
                is_primary BOOLEAN NOT NULL,
                ai_extracted BOOLEAN NOT NULL,
                is_active BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                FOREIGN KEY(client_id) REFERENCES clients (id) ON DELETE CASCADE
            )
        """))
        conn.execute(text(
            "CREATE INDEX ix_contacts_client_id ON contacts(client_id)"))
        conn.execute(text(
            "INSERT INTO tenants (id, name) VALUES (1, 'T')"))
        conn.execute(text(
            "INSERT INTO clients (id, tenant_id, name) VALUES (1, 1, 'Cliente')"))
        conn.execute(text(
            "INSERT INTO contacts (id, tenant_id, client_id, name, is_primary, "
            "ai_extracted, is_active, created_at, updated_at) VALUES "
            "(1, 1, 1, 'Mario Rossi', 0, 0, 1, '2026-07-01 00:00:00', '2026-07-01 00:00:00')"))
    yield engine
    engine.dispose()
    os.remove(path)


def test_migrate_relaxes_notnull_adds_columns_and_tables_preserving_data(old_shape_engine):
    from scripts.migrate_contacts_rubrica import migrate
    result = migrate(old_shape_engine)

    assert "contacts.company_text" in result["columns_added"]
    assert "contacts.source" in result["columns_added"]
    assert result["contacts_rebuilt"] is True
    assert set(result["tables_created"]) == {"contact_acquisitions", "contact_projects"}

    insp = inspect(old_shape_engine)
    cols = {c["name"]: c for c in insp.get_columns("contacts")}
    assert cols["client_id"]["nullable"] is True
    assert "company_text" in cols
    assert "source" in cols
    assert {"contact_acquisitions", "contact_projects"}.issubset(set(insp.get_table_names()))

    with old_shape_engine.begin() as conn:
        row = conn.execute(text("SELECT id, client_id, name FROM contacts WHERE id=1")).fetchone()
        assert row == (1, 1, "Mario Rossi")
        # nullable now actually accepts NULL
        conn.execute(text(
            "INSERT INTO contacts (id, tenant_id, client_id, name, is_primary, ai_extracted, "
            "is_active, created_at, updated_at, company_text, source) VALUES "
            "(2, 1, NULL, 'Orfano', 0, 0, 1, '2026-07-01 00:00:00', '2026-07-01 00:00:00', 'ACME', 'manual')"))


def test_migrate_is_idempotent(old_shape_engine):
    from scripts.migrate_contacts_rubrica import migrate
    migrate(old_shape_engine)
    result2 = migrate(old_shape_engine)
    assert result2["columns_added"] == []
    assert result2["contacts_rebuilt"] is False
    assert result2["tables_created"] == []
