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


def test_read_path_traversal_raises_value_error(tmp_path, monkeypatch):
    """Percorsi fuori da UPLOAD_DIR devono sollevare ValueError (path-traversal guard)."""
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(cs, "UPLOAD_DIR", up)
    with pytest.raises(ValueError, match="Path outside upload dir"):
        cs.read_capitolato_text("../../etc/passwd")


def test_read_roundtrip_valid_path(tmp_path, monkeypatch):
    """Un file valido dentro UPLOAD_DIR deve essere leggibile via read_capitolato_text."""
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(cs, "UPLOAD_DIR", up)
    # Scrive il file direttamente dentro up (simula save_capitolato_upload con UPLOAD_DIR monkeypatched)
    target = up / "deadbeef.txt"
    target.write_bytes(b"hello capitolato")
    # Usa il path assoluto: deve passare il guard e restituire stringa
    result = cs.read_capitolato_text(str(target))
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# resolve_capitolato_source tests
# ---------------------------------------------------------------------------

class _Tpl:
    def __init__(self, path=None, name=None):
        self.source_document_path = path
        self.source_document_name = name


def test_resolve_prefers_persisted(tmp_path, monkeypatch):
    """Persisted upload branch wins when file exists inside UPLOAD_DIR."""
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(cs, "UPLOAD_DIR", up)
    f = up / "abc.pdf"
    f.write_bytes(b"PERSISTED")
    # source_document_path points at the real file (absolute path)
    tpl = _Tpl(path=str(f), name="whatever.pdf")
    res = cs.resolve_capitolato_source(tpl)
    assert res is not None
    assert res[0] == b"PERSISTED"
    assert res[1] == "abc.pdf"


def test_resolve_corpus_fallback(tmp_path, monkeypatch):
    """Falls back to corpus dir when persisted file is absent."""
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(cs, "UPLOAD_DIR", up)
    # Fake a corpus directory and file
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    corpus_file = corpus / "Sample.pdf"
    corpus_file.write_bytes(b"CORPUS")
    # Patch the corpus dir lookup by monkeypatching __file__ resolution
    # Instead, monkeypatch the module-level constant via parents path trick:
    # We patch the _corpus_dir inside resolve_capitolato_source by temporarily
    # redirecting Path(__file__).resolve().parents[2] via a wrapper approach.
    # Simplest: monkeypatch the entire function's corpus resolution via partial override.
    # Actually, let's test via a real corpus file that exists in the project.
    # Use Amazon_MGM_Deliverables.txt which is a lightweight text file.
    real_corpus = Path(__file__).resolve().parents[1] / "docs" / "capitolati_esempio"
    if not real_corpus.exists():
        pytest.skip("corpus dir not present")
    # Pick the lightest file in the corpus
    corpus_names = [f.name for f in real_corpus.iterdir() if f.is_file()]
    if not corpus_names:
        pytest.skip("corpus dir empty")
    pick = corpus_names[0]
    tpl = _Tpl(path=None, name=pick)
    res = cs.resolve_capitolato_source(tpl)
    assert res is not None
    assert res[1] == pick
    assert len(res[0]) > 0


def test_resolve_none_when_nothing(tmp_path, monkeypatch):
    """Returns None when no persisted file and corpus name does not exist."""
    monkeypatch.setattr(cs, "UPLOAD_DIR", tmp_path / "nope")
    tpl = _Tpl(path=None, name="does-not-exist-xyz.pdf")
    assert cs.resolve_capitolato_source(tpl) is None


def test_resolve_none_when_no_attrs(tmp_path, monkeypatch):
    """Returns None when both path and name are None."""
    monkeypatch.setattr(cs, "UPLOAD_DIR", tmp_path / "nope")
    tpl = _Tpl(path=None, name=None)
    assert cs.resolve_capitolato_source(tpl) is None


def test_resolve_persisted_path_traversal_returns_none(tmp_path, monkeypatch):
    """Path-traversal in source_document_path must NOT raise — returns None silently."""
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(cs, "UPLOAD_DIR", up)
    tpl = _Tpl(path="../../etc/passwd", name=None)
    result = cs.resolve_capitolato_source(tpl)
    assert result is None


def test_read_persisted_bytes_valid(tmp_path, monkeypatch):
    """_read_persisted_bytes returns bytes for a valid file inside UPLOAD_DIR."""
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(cs, "UPLOAD_DIR", up)
    f = up / "test.pdf"
    f.write_bytes(b"DATA")
    result = cs._read_persisted_bytes(str(f))
    assert result == b"DATA"


def test_read_persisted_bytes_outside_dir_returns_none(tmp_path, monkeypatch):
    """_read_persisted_bytes returns None for paths outside UPLOAD_DIR."""
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(cs, "UPLOAD_DIR", up)
    result = cs._read_persisted_bytes("../../etc/passwd")
    assert result is None


def test_read_persisted_bytes_missing_file_returns_none(tmp_path, monkeypatch):
    """_read_persisted_bytes returns None for a missing file."""
    up = tmp_path / "up"
    up.mkdir()
    monkeypatch.setattr(cs, "UPLOAD_DIR", up)
    f = up / "nonexistent.pdf"
    result = cs._read_persisted_bytes(str(f))
    assert result is None
