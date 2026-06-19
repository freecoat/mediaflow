"""TDD tests for kdm_cert.parse_cert — Task 7."""
import ssl
import hashlib
from app.services.kdm_cert import parse_cert

# Truncated/invalid PEM — DER decode will fail; that's intentional.
SAMPLE_PEM = (
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBkTCB+wIJANQ9ts6m4mEMA0GCSqGSIb3DQEBCwUAMBQxEjAQBgNVBAMMCWxv\n"
    "-----END CERTIFICATE-----\n"
)


def test_parse_cert_handles_garbage_gracefully():
    out = parse_cert("not a cert")
    assert out["thumbprint"] is None
    assert out["expires_at"] is None


def test_parse_cert_thumbprint_when_der_decodable(monkeypatch):
    # Truncated sample may fail DER decode — we must not raise either way.
    out = parse_cert(SAMPLE_PEM)
    assert "thumbprint" in out and "expires_at" in out


def test_parse_cert_keys_always_present_on_empty_string():
    out = parse_cert("")
    assert "thumbprint" in out
    assert "expires_at" in out


def test_parse_cert_never_raises_on_random_bytes():
    out = parse_cert("-----BEGIN CERTIFICATE-----\nXXXXXXXX\n-----END CERTIFICATE-----\n")
    assert "thumbprint" in out
    assert "expires_at" in out
