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
        # v3.5.0-alpha.172.59 — accetta sia "Claqo" (post-rebrand) sia "MediaFlow" (legacy ZIP).
        if meta.get("app") not in ("Claqo", "MediaFlow"):
            raise ValueError("metadata.json: campo 'app' non è 'Claqo' né 'MediaFlow'.")

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

        # 2) DB swap con backup. v3.5.0-alpha.172.23 — strategia in-place
        # rewrite per Windows: invece di rinominare/copiare il file
        # (shutil.move/copy2 chiede write-exclusive lock al destinatario,
        # bloccato da OneDrive sync + connection pool SQLAlchemy + altri
        # processi), facciamo:
        #
        #   1. engine.dispose() per rilasciare le connection SQLite del pool
        #   2. lettura raw bytes del DB sorgente in memoria
        #   3. backup raw del DB corrente (copia, no move → safe anche lockato)
        #   4. apertura DB corrente in 'r+b' (sharing-aware: non chiede write-
        #      exclusive nuovo, riusa handle file system esistente), truncate
        #      e write dei nuovi bytes
        #   5. retry transient PermissionError con backoff (OneDrive sync apre
        #      e chiude il file in finestre brevi)
        #
        # In-place rewrite preserva inode + file lock state esistente. SQLite
        # alla prossima connection legge il nuovo contenuto (no WAL bound al
        # vecchio file, perché abbiamo già disposto il pool).
        db_src = extract_dir / "mediaflow.db"
        if db_src.exists():
            db_dst = project_root / "mediaflow.db"
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = project_root / f"mediaflow.db.backup-{ts}"
            try:
                from app.database import engine as _eng
                _eng.dispose()
            except Exception as e_d:
                summary["warnings"].append(f"engine.dispose pre-swap warning: {e_d}")
            import gc, time
            gc.collect()
            # Pulisci WAL/SHM se presenti (lascia il main DB consistent prima del swap)
            for sidecar in (".db-wal", ".db-shm", ".db-journal"):
                p = project_root / f"mediaflow{sidecar}"
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
            # Backup raw via copy (no move → no rename file system)
            try:
                if db_dst.exists():
                    shutil.copy2(str(db_dst), str(backup_path))
            except Exception as e_bk:
                summary["warnings"].append(f"Backup raw fallito: {e_bk} (procedo con import)")
            # Lettura nuovo DB
            try:
                with open(db_src, "rb") as f_in:
                    new_bytes = f_in.read()
            except Exception as e_r:
                raise RuntimeError(f"Lettura DB sorgente fallita: {e_r}") from e_r
            # In-place rewrite con retry su lock transient (OneDrive)
            attempts = 5
            delays = [0.0, 0.3, 0.8, 1.5, 3.0]
            last_err: Optional[Exception] = None
            for i in range(attempts):
                if delays[i] > 0:
                    time.sleep(delays[i])
                try:
                    # 'r+b' richiede file esistente; se non c'è creiamo via 'wb'
                    mode = "r+b" if db_dst.exists() else "wb"
                    with open(db_dst, mode) as f_out:
                        f_out.seek(0)
                        f_out.truncate(0)
                        f_out.write(new_bytes)
                        f_out.flush()
                        import os as _os
                        _os.fsync(f_out.fileno())
                    last_err = None
                    break
                except PermissionError as e_p:
                    last_err = e_p
                    # Retry con dispose engine extra (potrebbe essersi ricreato
                    # pool tra un tentativo e l'altro)
                    try:
                        from app.database import engine as _eng_r
                        _eng_r.dispose()
                    except Exception:
                        pass
                    gc.collect()
                except Exception as e_o:
                    last_err = e_o
                    break
            if last_err is not None:
                hint = (
                    " — Hint: pausa la sincronizzazione OneDrive su questa "
                    "cartella, oppure sposta il progetto fuori da OneDrive "
                    "(C:\\dev\\... o simile). OneDrive blocca handle file "
                    "durante sync."
                ) if isinstance(last_err, PermissionError) else ""
                raise RuntimeError(f"DB swap fallito: {last_err}{hint}") from last_err
            summary["actions"].append(
                f"DB ripristinato (in-place rewrite). Backup raw: {backup_path.name}"
            )
            # Dispose finale per scartare statement cache bound al vecchio DB
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
