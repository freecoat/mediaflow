import pathlib


def test_mail_html_panes():
    html = pathlib.Path("app/templates/pages/mail.html").read_text(encoding="utf-8")
    assert 'id="mail-labels"' in html
    assert 'id="mail-thread-list"' in html
    assert 'id="mail-reading"' in html
    assert 'mail.js' in html


def test_mail_js_globals_and_sandbox():
    src = pathlib.Path("app/static/js/mail.js").read_text(encoding="utf-8")
    for fn in ("mfMailInit", "mfMailLoadThreads", "mfMailOpenThread", "mfMailCompose", "mfMailSend"):
        assert fn in src, fn
    assert "sandbox" in src            # corpo email in iframe sandboxed
    assert "srcdoc" in src


def test_i18n_mail_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("nav.mail", "mail.inbox", "mail.compose", "mail.send", "mail.reply",
                "mail.replyAll", "mail.forward", "mail.search", "mail.notConnected",
                "mail.connect", "mail.showImages", "mail.sent", "mail.sendError"):
        assert key in src, key


def test_sidebar_has_mail():
    html = pathlib.Path("app/templates/base.html").read_text(encoding="utf-8")
    assert '/mail' in html
    assert 'data-i18n="nav.mail"' in html


def test_mail_layout_uses_classes_not_inline_grid():
    html = pathlib.Path("app/templates/pages/mail.html").read_text(encoding="utf-8")
    assert "grid-template-columns:200px 320px 1fr" not in html.replace(" ", "")
    assert 'data-mail-view' in html or 'mailMobileView' in html
    assert 'id="mail-mobile-bar"' in html


def test_mail_js_has_mobile_view():
    src = pathlib.Path("app/static/js/mail.js").read_text(encoding="utf-8")
    assert "mailMobileView" in src


def test_mail_has_responsive_style_block():
    html = pathlib.Path("app/templates/pages/mail.html").read_text(encoding="utf-8")
    assert "@media" in html and "max-width" in html
