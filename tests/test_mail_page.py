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


def test_mail_body_frame_never_allows_scripts():
    """allow-same-origin serve a misurare l'altezza del corpo dal parent. Da solo
    e' innocuo: senza allow-scripts nessun JS gira nel frame. I due insieme
    annullerebbero il sandbox e renderebbero eseguibile l'HTML di chiunque ci
    scriva. Il controllo guarda gli attributi sandbox emessi, non il sorgente
    grezzo: 'allow-scripts' puo' comparire nei commenti."""
    import re
    src = pathlib.Path("app/static/js/mail.js").read_text(encoding="utf-8")
    sandboxes = re.findall(r'sandbox="([^"]*)"', src)
    assert sandboxes, "nessun attributo sandbox: il corpo email deve restare in un iframe sandboxed"
    for sb in sandboxes:
        assert "allow-scripts" not in sb, sb
    assert "allow-same-origin" in sandboxes[0]


def test_mail_body_frame_is_autosized():
    """Un iframe senza altezza esplicita cade sul default UA 300x150."""
    src = pathlib.Path("app/static/js/mail.js").read_text(encoding="utf-8")
    assert "mfMailFitFrame" in src
    assert "scrollHeight" in src
    assert "onload=" in src


def test_mail_css_exists_and_sizes_body_frame():
    """Da F1 le classi mail-* vivevano solo in mail.js: nessun CSS le definiva."""
    css = pathlib.Path("app/static/css/main.css").read_text(encoding="utf-8")
    for sel in (".mail-body-frame", ".mail-msg", ".mail-thread-row", ".mail-label",
                ".mail-att", ".mail-cta"):
        assert sel in css, sel


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
