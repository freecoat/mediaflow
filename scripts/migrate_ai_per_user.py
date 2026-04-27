"""
Migrazione v3.1 -> v3.2: configurazione AI per-utente.

Aggiunge:
- Tabella `user_ai_settings` (id, user_id, provider, api_key_encrypted,
  model, base_url, verified_at, last_error, created_at, updated_at)
- Colonna `users.active_ai_provider` (nullable string)
- Tabella `ai_actions` (audit AI propone / utente dispone)

Genera anche `AI_KEY_ENCRYPTION_KEY` se mancante in `.env`.

Idempotente: rieseguibile più volte senza danni.
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

# Path setup per esecuzione diretta dello script
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, text
from app.database import engine, Base
from app.models import models  # noqa: F401  (registra i modelli)


ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"


def ensure_env_encryption_key() -> None:
    """Garantisce AI_KEY_ENCRYPTION_KEY presente nel .env. Se manca o vuoto,
    ne genera uno nuovo e lo scrive in coda al file."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        print("[!!] pacchetto 'cryptography' non installato. Esegui: pip install -r requirements.txt")
        return

    if not ENV_FILE.exists():
        # Crea .env partendo da .env.example
        if ENV_EXAMPLE.exists():
            ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"[OK] Creato .env da .env.example")
        else:
            ENV_FILE.write_text("# MediaFlow .env\n", encoding="utf-8")

    content = ENV_FILE.read_text(encoding="utf-8")
    m = re.search(r"^AI_KEY_ENCRYPTION_KEY=(.*)$", content, flags=re.MULTILINE)
    if m and m.group(1).strip():
        print("[OK] AI_KEY_ENCRYPTION_KEY già presente in .env")
        return

    new_key = Fernet.generate_key().decode("utf-8")
    if m:
        # Sostituisci la riga vuota
        content = re.sub(
            r"^AI_KEY_ENCRYPTION_KEY=.*$",
            f"AI_KEY_ENCRYPTION_KEY={new_key}",
            content, flags=re.MULTILINE)
    else:
        content = content.rstrip() + f"\n\n# Generata da migrate_ai_per_user.py\nAI_KEY_ENCRYPTION_KEY={new_key}\n"
    ENV_FILE.write_text(content, encoding="utf-8")
    print(f"[OK] Generata AI_KEY_ENCRYPTION_KEY e scritta in .env")


def column_exists(insp, table: str, column: str) -> bool:
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


def table_exists(insp, table: str) -> bool:
    return table in insp.get_table_names()


def migrate() -> None:
    print("-- Migrazione AI per-user ----------------------")

    ensure_env_encryption_key()

    # Crea tabelle nuove (no-op se già esistenti)
    Base.metadata.create_all(bind=engine, tables=[
        models.UserAISettings.__table__,
        models.AIAction.__table__,
    ])
    print("[OK] Tabelle user_ai_settings e ai_actions: presenti")

    insp = inspect(engine)

    # ALTER users ADD COLUMN active_ai_provider
    if not column_exists(insp, "users", "active_ai_provider"):
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN active_ai_provider VARCHAR(32)"))
        print("[OK] users.active_ai_provider aggiunta")
    else:
        print("[OK] users.active_ai_provider già presente")

    print("-- Migrazione completata ----------------------")
    print()
    print("Prossimo passo: avvia il server e vai in Impostazioni -> tab AI")
    print("per configurare il provider che preferisci.")


if __name__ == "__main__":
    migrate()
