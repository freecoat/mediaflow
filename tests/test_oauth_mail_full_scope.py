"""Opt-in scope pieno Gmail per elimina-definitivo/svuota-cestino (α.172.263).

gmail.modify NON puo' cancellare messaggi/thread in modo permanente: serve lo
scope pieno https://mail.google.com/. Stesso pattern least-privilege gia' in
produzione per CALENDAR_WRITE_SCOPES: mai nel bundle base, solo su opt-in
esplicito e incrementale.
"""
import urllib.parse

from app.services import oauth_providers as oauth


def _params(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def test_mail_full_scopes_constant():
    assert oauth.MAIL_FULL_SCOPES == "https://mail.google.com/"


def test_authorization_url_default_no_mail_full():
    url = oauth.authorization_url("google", "st")
    assert "mail.google.com" not in _params(url)["scope"]  # opt-in: non nel default


def test_authorization_url_with_mail_full_extra_scope():
    url = oauth.authorization_url("google", "st", extra_scopes=oauth.MAIL_FULL_SCOPES)
    p = _params(url)
    assert "mail.google.com" in p["scope"]
    assert p["include_granted_scopes"] == "true"
    # gli scope base restano (bundle least-privilege invariato)
    assert "gmail.send" in p["scope"]
