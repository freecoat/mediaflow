"""Admin restore service (v3.5.0-alpha.34).

Riceve un ZIP creato da `data_export.build_export_zip()` e ripristina:
- mediaflow.db (con backup automatico del DB esistente prima dell'overwrite)
- claude-memory/* nella cartella mangled della MACCHINA CORRENTE
  (calcolata al volo, NON quella della macchina sorgente)
- env/.env opt-in (chiede conferma — può sovrascrivere chiavi locali)
- uploads/ opt-in (merge in `./uploads/`)

Validazioni:
- ZIP deve contenere `metadata.json`
- Schema check: confronto major version corrente vs export. Se major
  diverso, rifiuta. Se solo minor/patch, accetta.
- DB swap atomico: sposta vecchio in `mediaflow.db.backup-<timestamp>`,
  poi rinomina il nuovo. Su errore, ripristina backup.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

# pyzipper è lazy-imported dentro `_open_zip()` quando serve (file cifrato).
# Senza pyzipper, ZIP normali funzionano comunque via zipfile stdlib.

from app.services.data_export import _mangled_root_for_path


def _major_version(v: str) -> str:
    """Estrae la versione major (prima del primo punto). '3.5.0-alpha.32' → '3'."""
    if not v:
        return ""
    return v.split(".")[0].strip()


def _open_zip(zip_path: Path, password: Optional[str]):
    """Apre il ZIP — pyzipper se cifrato, zipfile altrimenti.
    Heuristica: prova prima zipfile (file standard), se fallisce e c'è
    pyzipper disponibile, fall-back a quello. Se password è fornita, va
    direttamente su pyzipper (richiesto)."""
    if password:
        try:
            import pyzipper
        except ImportError as e:
            raise ValueError(
                "pyzipper non installato — impossibile aprire archivi cifrati. "
                "Esegui `pip install -r requirements.txt` e riprova."
            ) from e
        zf = pyzipper.AESZipFile(zip_path)
        zf.setpassword(password.encode("utf-8"))
        return zf
    try:
        return zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        try:
            import pyzipper
            return pyzipper.AESZipFile(zip_path)
        except ImportError:
            raise


def restore_from_zip(
    zip_bytes: bytes,
    *,
    password: Optional[str] = None,
    restore_env: bool = False,
    restore_uploads: bool = False,
    restore_memory: bool = True,
    current_app_version: str = "?",
) -> dict:
    """Esegue il restore. Ritorna un dict con summary di cosa è stato fatto.

    Solleva ValueError per validazioni fallite, RuntimeError per errori IO.
    """
    project_root = Path(__file__).resolve().parent.parent.parent

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        zip_path = tmp_root / "incoming.zip"
        zip_path.write_bytes(zip_bytes)

        extract_dir = tmp_root / "extracted"
        extract_dir.mkdir()

        try:
            with _open_zip(zip_path, password) as zf:
                zf.extractall(extract_dir)
        except RuntimeError as e:
            # pyzipper alza RuntimeError per password sbagliata
            raise ValueError(
                f"Impossibile aprire l'archivio: password errata o file corrotto ({e})"
            ) from e
        except zipfile.BadZipFile as e:
            raise ValueError(f"Archivio non valido: {e}") from e

        # 1) metadata.json check
        meta_path = extract_dir / "metadata.json"
        if not meta_path.exists():
            raise ValueError(
                "metadata.json mancante: l'archivio non sembra un export MediaFlow valido."
            )
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"metadata.json non parsabile: {e}") from e
        if meta.get("app") != "MediaFlow":
            raise ValueError("metadata.json: campo 'app' non è 'MediaFlow'.")

        export_version = meta.get("app_version", "?")
        if _major_version(current_app_version) and _major_version(export_version):
            if _major_version(current_app_version) != _major_version(export_version):
                raise ValueError(
                    f"Versione major incompatibile: export={export_version}, "
                    f"corrente={current_app_version}. Importazione rifiutata."
                )

        summary = {
            "export_version": export_version,
            "exported_at": meta.get("exported_at"),
            "actions": [],
            "warnings": [],
        }

        # 2) DB swap atomico con backup
        db_src = extract_dir / "mediaflow.db"
        if db_src.exists():
            db_dst = project_root / "mediaflow.db"
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = project_root / f"mediaflow.db.backup-{ts}"
            # v3.5.0-alpha.172.22 — Windows ferma il swap finché il connection
            # pool di SQLAlchemy tiene handle aperti sul DB. Dispose esplicito +
            # GC forzato per rilasciare lock prima del move. Su Linux/Mac il
            # rename funziona comunque ma il dispose evita stale connection nel
            # pool subito dopo lo swap (queries on new DB con connection vecchio).
            try:
                from app.database import engine as _eng
                _eng.dispose()
            except Exception as e_d:
                summary["warnings"].append(f"engine.dispose pre-swap warning: {e_d}")
            import gc
            gc.collect()
            try:
                if db_dst.exists():
                    shutil.move(str(db_dst), str(backup_path))
                shutil.copy2(str(db_src), str(db_dst))
                summary["actions"].append(
                    f"DB ripristinato. Backup precedente: {backup_path.name}"
                )
            except Exception as e:
                # Tentiamo il rollback se il backup esiste
                if backup_path.exists() and not db_dst.exists():
                    try:
                        shutil.move(str(backup_path), str(db_dst))
                        summary["warnings"].append("Restore fallito, ripristinato backup.")
                    except Exception:
                        pass
                raise RuntimeError(f"DB swap fallito: {e}") from e
            # v3.5.0-alpha.172.22 — Dopo swap, dispose di nuovo per scartare
            # cache statement bound al vecchio DB. Il primo SessionLocal()
            # successivo ricreerà il pool sul nuovo file.
            try:
                from app.database import engine as _eng2
                _eng2.dispose()
            except Exception:
                pass
        else:
            summary["warnings"].append(
                "Archivio senza mediaflow.db. DB locale invariato."
            )

        # 3) Memorie Claude → cartella mangled della MACCHINA CORRENTE
        mem_src = extract_dir / "claude-memory"
        if restore_memory and mem_src.exists() and mem_src.is_dir():
            local_mangled = _mangled_root_for_path(project_root)
            local_mem = (
                Path.home() / ".claude" / "projects" / local_mangled / "memory"
            )
            local_mem.mkdir(parents=True, exist_ok=True)
            n = 0
            for f in mem_src.glob("*.md"):
                shutil.copy2(f, local_mem / f.name)
                n += 1
            summary["actions"].append(
                f"Memorie Claude ripristinate ({n} file) in {local_mem}"
            )

        # 4) .env opt-in (chiede esplicitamente nel form: il caller passa il flag)
        env_src = extract_dir / "env" / ".env"
        if restore_env and env_src.exists():
            env_dst = project_root / ".env"
            backup_env = project_root / f".env.backup-{ts if 'ts' in dir() else datetime.now().strftime('%Y%m%d-%H%M%S')}"
            if env_dst.exists():
                shutil.copy2(str(env_dst), str(backup_env))
            shutil.copy2(str(env_src), str(env_dst))
            summary["actions"].append(
                f".env ripristinato. Backup precedente: {backup_env.name}"
            )

        # 5) Uploads opt-in (merge, non overwrite della cartella intera)
        up_src = extract_dir / "uploads"
        if restore_uploads and up_src.exists() and up_src.is_dir():
            up_dst = project_root / "uploads"
            up_dst.mkdir(exist_ok=True)
            n = 0
            for f in up_src.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(up_src)
                    target = up_dst / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)
                    n += 1
            summary["actions"].append(f"Uploads ripristinati ({n} file in merge).")

        return summary
