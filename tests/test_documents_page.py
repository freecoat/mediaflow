# tests/test_documents_page.py
import pathlib


def test_project_detail_has_doc_section():
    html = pathlib.Path("app/templates/pages/project_detail.html").read_text(encoding="utf-8")
    assert 'doc-list-project' in html
    assert 'documents.js' in html


def test_acquisitions_has_doc_section():
    html = pathlib.Path("app/templates/pages/acquisitions.html").read_text(encoding="utf-8")
    assert 'doc-list-acquisition' in html
    assert 'documents.js' in html


def test_i18n_has_doc_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("doc.section", "doc.addByUrl", "doc.urlPlaceholder", "doc.pick",
                "doc.empty", "doc.remove", "doc.added", "doc.error", "doc.invalidUrl"):
        assert key in src, key


def test_documents_js_defines_globals():
    src = pathlib.Path("app/static/js/documents.js").read_text(encoding="utf-8")
    for fn in ("mfDocInit", "mfDocList", "mfDocAddByUrl", "mfDocPicker"):
        assert fn in src, fn
