import os, time
from pathlib import Path
import pytest
from app.services import capitolato_storage as cs
from app.models.models import DeliveryTemplate


def test_save_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "UPLOAD_DIR", tmp_path / "up")
    rel = cs.save_capitolato_upload(b"%PDF-1.4 fake", "Paramount.pdf")
    assert rel.endswith(".pdf")
    assert (tmp_path / "up").exists()
    # file fisico presente
    assert any((tmp_path / "up").iterdir())


def test_sweep_removes_orphan_keeps_referenced(tmp_path, monkeypatch, db):
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(cs, "UPLOAD_DIR", up)
    orphan = up / "orphan.pdf"; orphan.write_bytes(b"x")
    kept = up / "kept.pdf"; kept.write_bytes(b"y")
    old = time.time() - 48 * 3600
    os.utime(orphan, (old, old))
    os.utime(kept, (old, old))
    db.add(DeliveryTemplate(tenant_id=1, code="K", name="Kept",
                            source_document_path="data/capitolato_uploads/kept.pdf"))
    db.commit()
    removed = cs.sweep_capitolato_uploads(db, max_age_h=24)
    assert removed == 1
    assert not orphan.exists()
    assert kept.exists()


def test_sweep_keeps_recent_orphan(tmp_path, monkeypatch, db):
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(cs, "UPLOAD_DIR", up)
    fresh = up / "fresh.pdf"; fresh.write_bytes(b"z")  # mtime = now
    removed = cs.sweep_capitolato_uploads(db, max_age_h=24)
    assert removed == 0
    assert fresh.exists()
