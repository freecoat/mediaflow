# tests/test_oauth_state.py
from app.services import oauth_providers as oauth


def test_state_roundtrip():
    st = oauth.make_oauth_state(7, "google")
    data = oauth.verify_oauth_state(st)
    assert data == {"user_id": 7, "provider": "google"}


def test_tampered_state_rejected():
    st = oauth.make_oauth_state(7, "google")
    tampered = st[:-2] + ("aa" if not st.endswith("aa") else "bb")
    assert oauth.verify_oauth_state(tampered) is None


def test_expired_state_rejected():
    st = oauth.make_oauth_state(7, "google", ttl_seconds=-1)  # già scaduto
    assert oauth.verify_oauth_state(st) is None


def test_garbage_state_rejected():
    assert oauth.verify_oauth_state("not-a-real-state") is None
    assert oauth.verify_oauth_state("") is None


def test_valid_signature_missing_keys_returns_none():
    import json, base64, hmac, hashlib
    from app.services.clock import now_utc
    payload = json.dumps({"e": int(now_utc().timestamp()) + 600}, separators=(",", ":")).encode()
    b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    sig = hmac.new(oauth._state_secret(), b64.encode(), hashlib.sha256).hexdigest()
    assert oauth.verify_oauth_state(f"{b64}.{sig}") is None
