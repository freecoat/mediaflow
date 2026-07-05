"""
Task 7 — Fase A OAuth foundation
Verifica che .env.example documenti le 3 variabili OAuth obbligatorie.
"""
import pathlib


def test_env_example_documents_oauth_vars():
    txt = pathlib.Path(".env.example").read_text(encoding="utf-8")
    assert "GOOGLE_OAUTH_CLIENT_ID" in txt
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in txt
    assert "OAUTH_REDIRECT_BASE_URL" in txt
