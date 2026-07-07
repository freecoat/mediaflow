# tests/test_mail_assign.py
import pathlib


def test_mail_js_has_assign():
    src = pathlib.Path("app/static/js/mail.js").read_text(encoding="utf-8")
    assert "mfMailAssign" in src
    assert "data-mail-assign" in src
    assert "/acquisitions/api/list" in src


def test_i18n_assign_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    assert "email.assign" in src
