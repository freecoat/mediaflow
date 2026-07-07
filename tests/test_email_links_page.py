import pathlib


def test_acquisitions_has_email_tab():
    html = pathlib.Path("app/templates/pages/acquisitions.html").read_text(encoding="utf-8")
    assert 'data-tab="email"' in html
    assert 'id="det-tab-email"' in html
    assert 'email_links.js' in html


def test_email_links_js_globals():
    src = pathlib.Path("app/static/js/email_links.js").read_text(encoding="utf-8")
    for fn in ("mfEmailInit", "mfEmailList", "mfEmailSearch", "mfEmailPin",
               "mfEmailPinUrl", "mfEmailPreview", "mfEmailExtract", "mfEmailRemove"):
        assert fn in src, fn
    assert "sandbox" in src  # anteprima corpo in iframe sandboxed


def test_i18n_email_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("email.tab", "email.search", "email.pin", "email.pinUrl",
                "email.urlPlaceholder", "email.extract", "email.expand", "email.remove",
                "email.pinned", "email.empty", "email.invalidUrl", "email.error"):
        assert key in src, key
