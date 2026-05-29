import io
from app.services.capitolato_head_extractor import render_document_for_llm


def _tiny_pdf_bytes() -> bytes:
    import fitz
    doc = fitz.open()
    doc.new_page(); doc.new_page()
    b = doc.tobytes()
    doc.close()
    return b


def test_render_pdf_uses_vision():
    out = render_document_for_llm(_tiny_pdf_bytes(), "RAI.pdf")
    assert out["mode"] == "vision"
    assert out["page_count"] == 2
    assert len(out["images"]) == 2
    assert isinstance(out["images"][0], (bytes, bytearray))


def test_render_txt_uses_text():
    out = render_document_for_llm(b"Barre e toni. TC 00:59:59:00", "spec.txt")
    assert out["mode"] == "text"
    assert "00:59:59:00" in out["text"]


def test_render_docx_uses_text(tmp_path):
    out = render_document_for_llm(b"dummy", "spec.docx")
    assert out["mode"] == "text"
