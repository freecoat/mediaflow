# Fase A — Fondamenta OAuth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collegare/scollegare l'account Google per-utente da `/settings`, con scope calendario + Drive, refresh token automatico e CSRF state firmato — fondamenta riusabili per calendario (Fase B/C) e documenti (Fase D).

**Architecture:** Riuso l'infra OAuth già scaffoldata (`UserOAuthToken`, `app/services/oauth_providers.py`, `app/routers/oauth.py`). Amplio gli scope Google, aggiungo refresh token automatico, sostituisco lo state CSRF in-memory con uno firmato HMAC stateless, aggiungo due colonne di preferenza sync a `UserOAuthToken`, ed espongo tutto in un nuovo tab `🔗 Account` in `/settings`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), SQLite, Jinja2, vanilla JS, `urllib` per HTTP OAuth, Fernet (`cryptography`) per cifratura, HMAC (`hmac`/`hashlib` stdlib) per lo state.

## Global Constraints

- **Python** 3.11+ (priorità 3.14). Niente `python-jose`, `passlib`, `WeasyPrint`, `authlib`. Usa stdlib + `urllib` + `PyJWT`/`bcrypt` esistenti.
- **Nessuna nuova dipendenza Python.** Chiamate OAuth/refresh via `urllib` (pattern esistente in `oauth_providers._http_post`).
- **Tenant filter:** ogni query di business filtra `tenant_id == CURRENT_TENANT`. (I token OAuth sono per-utente, non per-tenant: filtrati per `user_id`.)
- **Soft-delete:** `is_active=False` dove applicabile (non applicabile ai token: disconnect = DELETE fisico, già così).
- **Form-based API:** POST/PUT accettano `Form(...)`, non JSON. Frontend usa `FormData`.
- **i18n da subito:** ogni stringa UI nuova tradotta in tutte le 5 lingue (`it/en/fr/de/es`) in `app/static/js/i18n.js` + `data-i18n` nel template, stesso commit.
- **Cache-buster:** static JS/CSS referenziati con `?v={{ app_version }}` in `base.html`.
- **Auto-migrate:** ogni colonna nuova va aggiunta a `_auto_migrate_columns()` in `app/main.py` (ALTER idempotente) per non crashare al boot se l'utente non migra.
- **Segreti:** token cifrati (Fernet, già). Mai loggare access/refresh token. Redirect URI fisso e whitelisted.
- **Versioning:** a fine fase bump `app/main.py` versione + `CHANGELOG.md` + `docs/STATO.md`, commit nello stesso giro. Commit message via file (`git commit -F`), niente heredoc.

---

### Task 1: Scope Google calendario + Drive

Amplia gli scope OAuth di Google per includere Google Calendar (gestione eventi + creazione calendario secondario in Fase C) mantenendo `drive.file` (documenti, Fase D). I parametri `access_type=offline` + `prompt=consent` sono già presenti in `authorization_url()` (garantiscono il refresh token) — nessuna modifica lì.

**Files:**
- Modify: `app/services/oauth_providers.py:41-53` (dict `PROVIDERS["google"]`)
- Test: `tests/test_oauth_google_scopes.py`

**Interfaces:**
- Consumes: nulla.
- Produces: `oauth_providers.PROVIDERS["google"]["scopes"]` contiene ora `.../auth/calendar` e `.../auth/drive.file`. Label aggiornata a `"Google (Calendar + Drive)"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oauth_google_scopes.py
from app.services import oauth_providers as oauth


def test_google_scopes_include_calendar_and_drive():
    scopes = oauth.PROVIDERS["google"]["scopes"]
    assert "https://www.googleapis.com/auth/calendar" in scopes
    assert "https://www.googleapis.com/auth/drive.file" in scopes
    assert "email" in scopes and "profile" in scopes


def test_google_authorization_url_forces_offline_consent():
    url = oauth.authorization_url("google", "state123")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "calendar" in url  # scope url-encoded contiene calendar
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_oauth_google_scopes.py -v`
Expected: FAIL su `test_google_scopes_include_calendar_and_drive` (manca `auth/calendar`).

- [ ] **Step 3: Implement the scope change**

In `app/services/oauth_providers.py`, sostituisci il blocco `PROVIDERS["google"]`:

```python
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "scopes": (
            "openid email profile "
            "https://www.googleapis.com/auth/gmail.send "
            "https://www.googleapis.com/auth/drive.file "
            "https://www.googleapis.com/auth/calendar"
        ),
        "client_id_env": "GOOGLE_OAUTH_CLIENT_ID",
        "client_secret_env": "GOOGLE_OAUTH_CLIENT_SECRET",
        "label": "Google (Calendar + Drive)",
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_oauth_google_scopes.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/oauth_providers.py tests/test_oauth_google_scopes.py
git commit -F <msgfile>
# messaggio: "feat(oauth): scope Google Calendar + Drive per account linking"
```

---

### Task 2: Colonne preferenza sync su UserOAuthToken

Aggiungi due colonne a `user_oauth_tokens`: `auto_sync_calendar` (bool, on/off del push automatico, usata in Fase C) e `claqo_calendar_id` (id del calendario secondario "Claqo", popolato in Fase C). Vengono introdotte ORA per non ri-migrare la tabella dopo. Include: modello, script di migrazione idempotente, registrazione in `_auto_migrate_columns()`, voce `strumenti`.

**Files:**
- Modify: `app/models/models.py:2859-2873` (classe `UserOAuthToken`)
- Create: `scripts/migrate_oauth_calendar.py`
- Modify: `app/main.py` (funzione `_auto_migrate_columns`, dopo il blocco `users`)
- Modify: `strumenti.bat` e `strumenti.sh` (nuova voce menu)
- Test: `tests/test_oauth_token_sync_columns.py`

**Interfaces:**
- Consumes: nulla.
- Produces: `UserOAuthToken.auto_sync_calendar: bool` (default False), `UserOAuthToken.claqo_calendar_id: Optional[str]`. Script `scripts/migrate_oauth_calendar.py::main()` idempotente.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oauth_token_sync_columns.py
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool
from app.models.models import Base, UserOAuthToken


def _mem_engine():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return e


def test_useroauthtoken_has_sync_columns():
    e = _mem_engine()
    cols = {c["name"] for c in inspect(e).get_columns("user_oauth_tokens")}
    assert "auto_sync_calendar" in cols
    assert "claqo_calendar_id" in cols


def test_default_auto_sync_is_false():
    tok = UserOAuthToken(user_id=1, provider="google")
    # default applicato dall'ORM al flush; a livello attributo verifichiamo il default column
    assert UserOAuthToken.__table__.c.auto_sync_calendar.default.arg is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_oauth_token_sync_columns.py -v`
Expected: FAIL (colonne assenti).

- [ ] **Step 3: Add columns to the model**

In `app/models/models.py`, dentro `class UserOAuthToken`, dopo la riga `account_email` (2868) e prima di `created_at`:

```python
    account_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Fase A (2026-07-04) — preferenze sync calendario (usate in Fase C)
    auto_sync_calendar: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    claqo_calendar_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
```

(Verifica che `Boolean` sia già importato in cima a `models.py` — lo è, usato ovunque.)

- [ ] **Step 4: Run test to verify model passes**

Run: `python -m pytest tests/test_oauth_token_sync_columns.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Write the migration script**

```python
# scripts/migrate_oauth_calendar.py
"""Migrazione non distruttiva — Fase A OAuth calendario.

Aggiunge user_oauth_tokens.auto_sync_calendar + claqo_calendar_id.
Idempotente: ALTER TABLE ADD COLUMN solo se mancanti.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text
from app.database import engine


def main():
    insp = inspect(engine)
    if "user_oauth_tokens" not in insp.get_table_names():
        # tabella creata da Base.metadata.create_all() al boot; niente da fare
        print("SKIP: user_oauth_tokens non esiste ancora (verrà creata al boot).")
        return
    cols = {c["name"] for c in insp.get_columns("user_oauth_tokens")}
    alters = [
        ("auto_sync_calendar", "BOOLEAN NOT NULL DEFAULT 0"),
        ("claqo_calendar_id", "VARCHAR(255) NULL"),
    ]
    with engine.begin() as conn:
        for col, ddl in alters:
            if col not in cols:
                print(f"ALTER user_oauth_tokens ADD {col}")
                conn.execute(text(f"ALTER TABLE user_oauth_tokens ADD COLUMN {col} {ddl}"))
    print("OK: migrazione OAuth calendario completata.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Register in `_auto_migrate_columns()`**

In `app/main.py`, dentro `_auto_migrate_columns()`, aggiungi un blocco (dopo il blocco `users`, stesso stile):

```python
    # Fase A (2026-07-04) — colonne sync calendario su user_oauth_tokens
    if "user_oauth_tokens" in insp.get_table_names():
        oc = {c["name"] for c in insp.get_columns("user_oauth_tokens")}
        oauth_alters = [
            ("auto_sync_calendar", "BOOLEAN NOT NULL DEFAULT 0"),
            ("claqo_calendar_id", "VARCHAR(255) NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in oauth_alters:
                if col not in oc:
                    print(f"[auto-migrate] user_oauth_tokens.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE user_oauth_tokens ADD COLUMN {col} {ddl}"))
```

- [ ] **Step 7: Add `strumenti` menu entry**

In `strumenti.bat` e `strumenti.sh`, aggiungi una voce che esegue `python scripts/migrate_oauth_calendar.py` (segui il pattern delle voci di migrazione esistenti nei due file — copia lo stile della voce `migrate_ai_per_user.py` cambiando script e label a "Migra OAuth calendario (Fase A)").

- [ ] **Step 8: Verify migration is idempotent**

Run: `python scripts/migrate_oauth_calendar.py && python scripts/migrate_oauth_calendar.py`
Expected: entrambe le esecuzioni terminano con `OK:` senza errori (la seconda non ri-aggiunge colonne).

- [ ] **Step 9: Commit**

```bash
git add app/models/models.py scripts/migrate_oauth_calendar.py app/main.py strumenti.bat strumenti.sh tests/test_oauth_token_sync_columns.py
git commit -F <msgfile>
# messaggio: "feat(oauth): colonne auto_sync_calendar + claqo_calendar_id su UserOAuthToken"
```

---

### Task 3: Refresh token automatico

Aggiungi `get_valid_access_token(db, user_id, provider)` a `oauth_providers.py`: ritorna un access token valido, rinnovandolo via refresh token se scaduto/in scadenza (soglia 120s). Ogni futura chiamata alle API Google (Fase C/D) passerà da qui.

**Files:**
- Modify: `app/services/oauth_providers.py` (nuova funzione + helper `_refresh_access_token`)
- Test: `tests/test_oauth_refresh.py`

**Interfaces:**
- Consumes: `PROVIDERS`, `get_token`, `decrypt_refresh_token`, `_http_post`, `now_utc`.
- Produces:
  - `refresh_access_token(provider: str, refresh_token: str) -> dict` — chiama il token endpoint con grant_type=refresh_token, ritorna il token response.
  - `get_valid_access_token(db: Session, user_id: int, provider: str) -> Optional[str]` — ritorna access token valido o None se non collegato/refresh fallito. Aggiorna la riga token (access_token, expires_at) in DB (senza commit — il chiamante committa).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oauth_refresh.py
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, UserOAuthToken
from app.services import oauth_providers as oauth
from app.services.clock import now_utc


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, expire_on_commit=False, future=True)()


def test_returns_current_token_when_not_expired(monkeypatch):
    s = _session()
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="live-abc",
                         expires_at=now_utc() + timedelta(hours=1))); s.commit()
    # non deve chiamare la rete
    monkeypatch.setattr(oauth, "_http_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no net")))
    assert oauth.get_valid_access_token(s, 1, "google") == "live-abc"


def test_refreshes_when_expired(monkeypatch):
    s = _session()
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="old",
                         refresh_token_enc=oauth.encrypt_refresh_token("rt-xyz"),
                         expires_at=now_utc() - timedelta(minutes=5))); s.commit()
    calls = {}

    def fake_post(url, data):
        calls["grant"] = data.get("grant_type")
        calls["rt"] = data.get("refresh_token")
        return {"access_token": "new-token", "expires_in": 3600}

    monkeypatch.setattr(oauth, "_http_post", fake_post)
    tok = oauth.get_valid_access_token(s, 1, "google")
    assert tok == "new-token"
    assert calls["grant"] == "refresh_token"
    assert calls["rt"] == "rt-xyz"
    row = oauth.get_token(s, 1, "google")
    assert row.access_token == "new-token"
    assert row.expires_at > now_utc()


def test_returns_none_when_no_token():
    s = _session()
    assert oauth.get_valid_access_token(s, 99, "google") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_oauth_refresh.py -v`
Expected: FAIL (`get_valid_access_token` non esiste).

- [ ] **Step 3: Implement refresh functions**

In `app/services/oauth_providers.py`, aggiungi in fondo (dopo `list_tokens`):

```python
# ── Refresh automatico access token ──────────────────────────────────

_REFRESH_SKEW_SECONDS = 120


def refresh_access_token(provider: str, refresh_token: str) -> dict:
    """Rinnova l'access token usando il refresh token. Ritorna il token response."""
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ValueError(f"Provider sconosciuto: {provider}")
    data = {
        "client_id": os.getenv(cfg["client_id_env"], ""),
        "client_secret": os.getenv(cfg["client_secret_env"], ""),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    return _http_post(cfg["token_url"], data)


def get_valid_access_token(db: Session, user_id: int, provider: str) -> Optional[str]:
    """Ritorna un access token valido, rinnovandolo se scaduto/in scadenza.

    Aggiorna la riga token in DB (access_token, expires_at) SENZA commit:
    il chiamante è responsabile del commit. Ritorna None se non collegato
    o se il refresh fallisce.
    """
    row = get_token(db, user_id, provider)
    if not row or not row.access_token:
        return None
    # token ancora valido oltre la soglia di skew?
    if row.expires_at and row.expires_at > now_utc() + timedelta(seconds=_REFRESH_SKEW_SECONDS):
        return row.access_token
    # serve refresh
    rt = decrypt_refresh_token(row.refresh_token_enc) if row.refresh_token_enc else None
    if not rt:
        log.warning(f"get_valid_access_token: nessun refresh_token per user {user_id}/{provider}")
        return row.access_token  # best effort: potrebbe essere ancora valido
    try:
        resp = refresh_access_token(provider, rt)
    except Exception as e:
        log.error(f"refresh_access_token failed user {user_id}/{provider}: {e}")
        return None
    new_access = resp.get("access_token")
    if not new_access:
        log.error(f"refresh_access_token: risposta senza access_token user {user_id}/{provider}")
        return None
    row.access_token = new_access
    row.expires_at = now_utc() + timedelta(seconds=int(resp.get("expires_in", 3600)))
    if resp.get("refresh_token"):  # Google talvolta ri-emette
        row.refresh_token_enc = encrypt_refresh_token(resp["refresh_token"])
    row.updated_at = now_utc()
    return new_access
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_oauth_refresh.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/oauth_providers.py tests/test_oauth_refresh.py
git commit -F <msgfile>
# messaggio: "feat(oauth): refresh access token automatico (get_valid_access_token)"
```

---

### Task 4: CSRF state firmato HMAC (stateless)

Sostituisci `_state_store` in-memory con uno state firmato HMAC (`settings.secret_key`), così il flow regge multi-processo e non perde lo state a un restart. Lo state porta `user_id`, `provider`, `exp` (timestamp scadenza) ed è verificato nel callback.

**Files:**
- Modify: `app/services/oauth_providers.py` (helper `make_oauth_state` / `verify_oauth_state`)
- Modify: `app/routers/oauth.py:29-31` (rimuove `_state_store`), `:68-70` (`oauth_start`), `:87-94` (`oauth_callback`)
- Test: `tests/test_oauth_state.py`

**Interfaces:**
- Consumes: `settings.secret_key` (da `app.config`), `now_utc`.
- Produces:
  - `make_oauth_state(user_id: int, provider: str, ttl_seconds: int = 600) -> str` — token `base64(payload).hexsig`.
  - `verify_oauth_state(state: str) -> Optional[dict]` — ritorna `{"user_id", "provider"}` se firma valida e non scaduto, altrimenti None.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_oauth_state.py -v`
Expected: FAIL (`make_oauth_state` non esiste).

- [ ] **Step 3: Implement signed state helpers**

In `app/services/oauth_providers.py`, aggiungi gli import in cima (dopo gli import esistenti):

```python
import hmac
import hashlib
import base64
from app.config import settings
```

E aggiungi le funzioni (dopo `redirect_uri`):

```python
def _state_secret() -> bytes:
    return (settings.secret_key or "").encode()


def make_oauth_state(user_id: int, provider: str, ttl_seconds: int = 600) -> str:
    """State CSRF firmato HMAC, stateless. Formato: b64url(payload).hexsig"""
    exp = int(now_utc().timestamp()) + ttl_seconds
    payload = json.dumps({"u": user_id, "p": provider, "e": exp}, separators=(",", ":")).encode()
    b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    sig = hmac.new(_state_secret(), b64.encode(), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def verify_oauth_state(state: str) -> Optional[dict]:
    """Verifica firma + scadenza. Ritorna {'user_id','provider'} o None."""
    if not state or "." not in state:
        return None
    b64, _, sig = state.partition(".")
    expected = hmac.new(_state_secret(), b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padded = b64 + "=" * (-len(b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception:
        return None
    if int(data.get("e", 0)) < int(now_utc().timestamp()):
        return None
    return {"user_id": data["u"], "provider": data["p"]}
```

- [ ] **Step 4: Run state helper tests**

Run: `python -m pytest tests/test_oauth_state.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Wire helpers into the router**

In `app/routers/oauth.py`:

- Rimuovi le righe 29-31 (commento + `_state_store: dict[str, dict] = {}`).
- In `oauth_start` (righe 68-70), sostituisci:

```python
    state = oauth.make_oauth_state(user.id, provider)
    return RedirectResponse(oauth.authorization_url(provider, state))
```

- In `oauth_callback` (righe 87-94), sostituisci il blocco di validazione state:

```python
    if not code or not state:
        raise HTTPException(400, "Missing code/state")
    parsed = oauth.verify_oauth_state(state)
    if not parsed:
        raise HTTPException(400, "Invalid or expired state (CSRF)")
    if parsed["provider"] != provider:
        raise HTTPException(400, "Provider mismatch")
    user_id = parsed["user_id"]
```

(Rimuovi anche l'import ora inutile `import secrets` se non più usato altrove nel file — verifica con grep prima di rimuoverlo.)

- [ ] **Step 6: Write a router-level test for the state flow**

```python
# tests/test_oauth_router_state.py — riusa la fixture client dal file acquisitions
from tests.test_acquisitions_api import client  # noqa: F401
from app.services import oauth_providers as oauth


def test_callback_rejects_bad_state(client):
    c, _ = client
    r = c.get("/auth/oauth/google/callback?code=x&state=forged.deadbeef",
              follow_redirects=False)
    assert r.status_code == 400
    assert "state" in r.text.lower()


def test_callback_accepts_valid_state(client, monkeypatch):
    c, s = client
    # user id 1 esiste nella fixture
    state = oauth.make_oauth_state(1, "google")
    monkeypatch.setattr(oauth, "exchange_code_for_token",
                        lambda p, code: {"access_token": "at", "expires_in": 3600})
    monkeypatch.setattr(oauth, "fetch_userinfo",
                        lambda p, at: {"email": "linked@gmail.com"})
    r = c.get(f"/auth/oauth/google/callback?code=x&state={state}",
              follow_redirects=False)
    assert r.status_code == 200
    assert "linked@gmail.com" in r.text
    assert oauth.get_token(s, 1, "google") is not None
```

- [ ] **Step 7: Run router state tests**

Run: `python -m pytest tests/test_oauth_router_state.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Commit**

```bash
git add app/services/oauth_providers.py app/routers/oauth.py tests/test_oauth_state.py tests/test_oauth_router_state.py
git commit -F <msgfile>
# messaggio: "feat(oauth): CSRF state firmato HMAC stateless (no in-memory store)"
```

---

### Task 5: Status esteso + toggle auto-sync

Estendi `GET /auth/oauth/status` per esporre `auto_sync_calendar` e `claqo_calendar_id`, e aggiungi `POST /auth/oauth/{provider}/sync-toggle` per accendere/spegnere il push automatico. Serve alla UI del Task 6.

**Files:**
- Modify: `app/routers/oauth.py` (endpoint `oauth_status` + nuovo endpoint `oauth_sync_toggle`)
- Test: `tests/test_oauth_sync_toggle.py`

**Interfaces:**
- Consumes: `oauth.get_token`, fixture `client`.
- Produces:
  - `GET /auth/oauth/status` → per provider aggiunge `"auto_sync_calendar": bool` e `"claqo_calendar_id": str|None`.
  - `POST /auth/oauth/{provider}/sync-toggle` (Form `enabled: bool`) → `{"ok": True, "auto_sync_calendar": bool}`; 404 se non collegato.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oauth_sync_toggle.py
from tests.test_acquisitions_api import client  # noqa: F401
from app.models.models import UserOAuthToken


def test_status_includes_sync_fields(client):
    c, _ = client
    st = c.get("/auth/oauth/status").json()
    assert "google" in st["providers"]
    assert "auto_sync_calendar" in st["providers"]["google"]


def test_sync_toggle_requires_connection(client):
    c, _ = client
    r = c.post("/auth/oauth/google/sync-toggle", data={"enabled": "true"})
    assert r.status_code == 404


def test_sync_toggle_flips_flag(client):
    c, s = client
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="at",
                         auto_sync_calendar=False)); s.commit()
    r = c.post("/auth/oauth/google/sync-toggle", data={"enabled": "true"})
    assert r.status_code == 200
    assert r.json()["auto_sync_calendar"] is True
    s.refresh(s.query(UserOAuthToken).filter_by(user_id=1, provider="google").first())
    assert s.query(UserOAuthToken).filter_by(user_id=1, provider="google").first().auto_sync_calendar is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_oauth_sync_toggle.py -v`
Expected: FAIL (campo assente / endpoint 404 su tutto).

- [ ] **Step 3: Extend status + add toggle endpoint**

In `app/routers/oauth.py`, nella dict per-provider dentro `oauth_status`, aggiungi due chiavi:

```python
        out["providers"][pid] = {
            "label": cfg["label"],
            "configured": oauth.is_configured(pid),
            "connected": bool(token),
            "account_email": token.account_email if token else None,
            "expires_at": token.expires_at.isoformat() if token and token.expires_at else None,
            "scopes": token.scopes if token else None,
            "auto_sync_calendar": bool(token.auto_sync_calendar) if token else False,
            "claqo_calendar_id": token.claqo_calendar_id if token else None,
        }
```

Aggiungi l'import `Form` in cima (`from fastapi import APIRouter, Depends, HTTPException, Request, Form`) e il nuovo endpoint in fondo al file:

```python
@router.post("/{provider}/sync-toggle")
async def oauth_sync_toggle(provider: str, request: Request,
                            enabled: bool = Form(...),
                            db: Session = Depends(get_db)):
    """Accende/spegne il push automatico calendario per il provider collegato."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Autenticazione richiesta")
    if provider not in oauth.PROVIDERS:
        raise HTTPException(404, "Provider sconosciuto")
    token = oauth.get_token(db, user.id, provider)
    if not token:
        raise HTTPException(404, "Account non collegato")
    token.auto_sync_calendar = bool(enabled)
    db.commit()
    return {"ok": True, "auto_sync_calendar": token.auto_sync_calendar}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_oauth_sync_toggle.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add app/routers/oauth.py tests/test_oauth_sync_toggle.py
git commit -F <msgfile>
# messaggio: "feat(oauth): status con campi sync + endpoint sync-toggle"
```

---

### Task 6: UI tab 🔗 Account in /settings

Aggiungi un tab "Account" in `/settings` con la card Google (stato, Connetti/Disconnetti, scope, toggle sync) e la card Microsoft disabilitata. Tutte le stringhe i18n nelle 5 lingue. Nessun endpoint nuovo: consuma `GET /auth/oauth/status`, `GET /auth/oauth/google/start`, `POST /auth/oauth/google/disconnect`, `POST /auth/oauth/google/sync-toggle`.

**Files:**
- Modify: `app/templates/pages/settings.html` (nuovo tab + markup card)
- Create: `app/static/js/settings_account.js` (fetch status, render, azioni)
- Modify: `app/templates/pages/settings.html` o `base.html` — include dello script con `?v={{ app_version }}`
- Modify: `app/static/js/i18n.js` (chiavi `settings.account.*` in 5 lingue)
- Test: `tests/test_settings_account_page.py` (smoke: la pagina contiene il tab + il JS non ha ReferenceError evidenti via presenza funzioni)

**Interfaces:**
- Consumes: endpoint OAuth dei Task 4/5.
- Produces: funzione JS globale `loadAccountSettings()` chiamata all'attivazione del tab. Chiavi i18n `settings.account.title`, `settings.account.connect`, `settings.account.disconnect`, `settings.account.notLinked`, `settings.account.autoSync`, `settings.account.comingSoon`.

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/test_settings_account_page.py
from tests.test_acquisitions_api import client  # noqa: F401


def test_settings_page_has_account_tab(client):
    c, _ = client
    html = c.get("/settings/").text
    assert 'data-i18n="settings.account.title"' in html
    # il tab account deve referenziare lo script dedicato
    assert "settings_account.js" in html


def test_i18n_has_account_keys():
    # la chiave deve esistere in tutte le 5 lingue
    import re, pathlib
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    assert "settings.account.title" in src
    for lang in ("it", "en", "fr", "de", "es"):
        # sanity: ogni lingua compare almeno una volta nel file
        assert f"{lang}:" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings_account_page.py -v`
Expected: FAIL (tab/script assenti).

- [ ] **Step 3: Add i18n keys**

In `app/static/js/i18n.js`, dentro `window.MF_I18N`, aggiungi (mantieni l'allineamento a colonne dello stile esistente):

```javascript
  // ── Settings › Account linking (Fase A) ───────────
  'settings.account.title':     {it: 'Account collegati', en: 'Linked accounts', fr: 'Comptes liés',        de: 'Verknüpfte Konten', es: 'Cuentas vinculadas'},
  'settings.account.connect':   {it: 'Collega',           en: 'Connect',         fr: 'Connecter',           de: 'Verbinden',         es: 'Conectar'},
  'settings.account.disconnect':{it: 'Scollega',          en: 'Disconnect',      fr: 'Déconnecter',         de: 'Trennen',           es: 'Desconectar'},
  'settings.account.notLinked': {it: 'Non collegato',     en: 'Not linked',      fr: 'Non lié',             de: 'Nicht verknüpft',   es: 'No vinculada'},
  'settings.account.autoSync':  {it: 'Sync calendario automatico', en: 'Auto calendar sync', fr: 'Sync agenda auto', de: 'Auto-Kalender-Sync', es: 'Sinc. calendario auto'},
  'settings.account.comingSoon':{it: 'Prossimamente',     en: 'Coming soon',     fr: 'Bientôt',             de: 'Demnächst',         es: 'Próximamente'},
```

- [ ] **Step 4: Add the tab + card markup**

In `app/templates/pages/settings.html`, aggiungi un tab "Account" seguendo il pattern dei tab esistenti (es. il tab AI). Il pannello contiene un container che il JS popola:

```html
<!-- Tab Account (Fase A) -->
<section id="tab-account" class="settings-tab" hidden>
  <h2 data-i18n="settings.account.title">Account collegati</h2>
  <div id="account-cards">
    <p class="muted" data-i18n="common.loading">Caricamento…</p>
  </div>
</section>
```

Aggiungi il bottone-tab nella barra dei tab (stesso stile degli altri) con `data-i18n="settings.account.title"` e l'handler che mostra `#tab-account` e chiama `loadAccountSettings()`.

In fondo al template (o nel blocco script include), aggiungi:

```html
<script src="/static/js/settings_account.js?v={{ app_version }}"></script>
```

(Verifica come gli altri script di settings sono inclusi e segui lo stesso meccanismo — `app_version` è già disponibile nel context Jinja per il cache-buster.)

- [ ] **Step 5: Write the account JS**

```javascript
// app/static/js/settings_account.js — Fase A account linking UI
async function loadAccountSettings() {
  const box = document.getElementById('account-cards');
  if (!box) return;
  let data;
  try {
    const r = await fetch('/auth/oauth/status');
    if (!r.ok) throw new Error('status ' + r.status);
    data = await r.json();
  } catch (e) {
    box.innerHTML = '<p class="error">' + escapeHtml(String(e)) + '</p>';
    return;
  }
  const t = (k) => (window.t ? window.t(k) : k); // helper i18n globale se presente
  box.innerHTML = '';
  for (const [pid, p] of Object.entries(data.providers)) {
    const card = document.createElement('div');
    card.className = 'card account-card';
    const connected = p.connected;
    const microsoftDisabled = pid === 'microsoft';
    let actions;
    if (microsoftDisabled && !connected) {
      actions = '<span class="badge" data-i18n="settings.account.comingSoon">Prossimamente</span>';
    } else if (connected) {
      actions =
        '<label class="switch"><input type="checkbox" ' + (p.auto_sync_calendar ? 'checked' : '') +
        ' onchange="toggleAccountSync(\'' + pid + '\', this.checked)"> ' +
        '<span data-i18n="settings.account.autoSync">Sync calendario automatico</span></label>' +
        '<button class="btn btn-danger" onclick="disconnectAccount(\'' + pid + '\')" ' +
        'data-i18n="settings.account.disconnect">Scollega</button>';
    } else {
      const disabled = p.configured ? '' : 'disabled title="client_id non configurato"';
      actions = '<a class="btn" ' + disabled + ' href="/auth/oauth/' + pid + '/start" ' +
        'data-i18n="settings.account.connect">Collega</a>';
    }
    card.innerHTML =
      '<h3>' + escapeHtml(p.label) + '</h3>' +
      '<p>' + (connected
        ? escapeHtml(p.account_email || '')
        : '<span class="muted" data-i18n="settings.account.notLinked">Non collegato</span>') + '</p>' +
      '<div class="account-actions">' + actions + '</div>';
    box.appendChild(card);
  }
  if (window.applyI18n) window.applyI18n();
}

async function disconnectAccount(pid) {
  await fetch('/auth/oauth/' + pid + '/disconnect', {method: 'POST'});
  loadAccountSettings();
}

async function toggleAccountSync(pid, enabled) {
  const fd = new FormData();
  fd.append('enabled', enabled ? 'true' : 'false');
  await fetch('/auth/oauth/' + pid + '/sync-toggle', {method: 'POST', body: fd});
}
```

(Usa `escapeHtml` centralizzato da `global.js` — NON ridefinirlo. Verifica che esista; se il nome helper i18n runtime è diverso da `window.t`/`window.applyI18n`, adegua ai nomi reali in `i18n.js`.)

- [ ] **Step 6: Restart server + run smoke test**

Nota: i template Jinja su OneDrive non si ricaricano a runtime — riavvia il server prima dello smoke.

Run: `python -m pytest tests/test_settings_account_page.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Grep guard against JS ReferenceError**

Run: `grep -n "loadAccountSettings\|disconnectAccount\|toggleAccountSync" app/static/js/settings_account.js app/templates/pages/settings.html`
Expected: ogni funzione è definita in `settings_account.js` ed è referenziata (chiamata) dal template/JS. Verifica che `escapeHtml` NON sia ridefinita nel nuovo file.

- [ ] **Step 8: Commit**

```bash
git add app/templates/pages/settings.html app/static/js/settings_account.js app/static/js/i18n.js tests/test_settings_account_page.py
git commit -F <msgfile>
# messaggio: "feat(settings): tab Account con connect/disconnect Google + toggle sync (i18n 5 lingue)"
```

---

### Task 7: Config, env, docs, version bump

Documenta le env var OAuth necessarie e chiudi la fase con bump versione + CHANGELOG + STATO.

**Files:**
- Modify: `app/config.py` (se le env OAuth vanno esposte come settings; altrimenti restano `os.getenv` in `oauth_providers` — vedi step 1)
- Modify: `.env.example` (aggiungi le 3 var OAuth)
- Modify: `app/main.py` (bump stringa versione)
- Modify: `CHANGELOG.md`, `docs/STATO.md`
- Test: `tests/test_env_example_oauth.py`

**Interfaces:**
- Consumes: nulla.
- Produces: `.env.example` contiene `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `OAUTH_REDIRECT_BASE_URL`.

- [ ] **Step 1: Decide config surface**

Le env OAuth sono già lette via `os.getenv` in `oauth_providers.py` (`is_configured`, `authorization_url`, ecc.) — NON serve aggiungerle a `app/config.py`. Lascia `config.py` invariato salvo che tu voglia un default esplicito; questa fase NON lo richiede. (Nota decisionale registrata per evitare doppia sorgente di verità.)

- [ ] **Step 2: Write the failing test**

```python
# tests/test_env_example_oauth.py
import pathlib


def test_env_example_documents_oauth_vars():
    txt = pathlib.Path(".env.example").read_text(encoding="utf-8")
    assert "GOOGLE_OAUTH_CLIENT_ID" in txt
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in txt
    assert "OAUTH_REDIRECT_BASE_URL" in txt
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_env_example_oauth.py -v`
Expected: FAIL (var non documentate).

- [ ] **Step 4: Add OAuth vars to `.env.example`**

Aggiungi in fondo a `.env.example` (verifica il nome esatto del file; se è `.env.example`):

```bash
# ── OAuth account linking (Fase A) ──────────────────────────
# OAuth client "Web" da Google Cloud Console, con Calendar API + Drive API
# abilitate e redirect URI: {OAUTH_REDIRECT_BASE_URL}/auth/oauth/google/callback
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
OAUTH_REDIRECT_BASE_URL=http://localhost:8000
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_env_example_oauth.py -v`
Expected: PASS.

- [ ] **Step 6: Bump version + CHANGELOG + STATO**

- In `app/main.py` incrementa la stringa di versione (segui il formato `3.5.0-alpha.172.NNN` corrente; leggi il valore attuale e aumenta l'ultimo segmento).
- In `CHANGELOG.md` aggiungi una voce per la nuova versione che riassume la Fase A (scope Google calendar+drive, refresh automatico, state HMAC, colonne sync, UI tab Account).
- In `docs/STATO.md` aggiorna versione corrente + "in corso" (Fase A OAuth completata) + "prossimo step" (Fase B — CalendarEvent + FullCalendar).

- [ ] **Step 7: Run the full test suite**

Run: `python -m pytest tests/ -q`
Expected: tutti verdi (nessuna regressione). Se qualche test OAuth preesistente dipendeva da `_state_store`, aggiornalo.

- [ ] **Step 8: Commit**

```bash
git add app/main.py CHANGELOG.md docs/STATO.md .env.example tests/test_env_example_oauth.py
git commit -F <msgfile>
# messaggio: "chore: Fase A OAuth foundation — bump versione + docs env OAuth"
```

---

## Self-Review

**1. Spec coverage (sezione Fase A della spec):**
- Scope calendario Google → Task 1 ✓
- Refresh automatico `get_valid_access_token` → Task 3 ✓
- CSRF state firmato HMAC → Task 4 ✓
- UI tab Account (connect/disconnect/scope/toggle sync) → Task 6 ✓
- Config/env `GOOGLE_OAUTH_CLIENT_ID/SECRET`, `OAUTH_REDIRECT_BASE_URL` → Task 7 ✓
- Colonne `auto_sync_calendar` + `claqo_calendar_id` su `UserOAuthToken` → Task 2 ✓
- Card Microsoft "Prossimamente" → Task 6 ✓
- Sicurezza (token cifrati, no log token, redirect fisso, overlay mai in scrittura) → cifratura preesistente + nessun log token introdotto; overlay è Fase C ✓

**2. Placeholder scan:** nessun TODO/TBD; ogni step di codice mostra il codice. ✓

**3. Type consistency:** `make_oauth_state`/`verify_oauth_state`, `get_valid_access_token`, `refresh_access_token` usati con firme coerenti tra Task 3/4 e i test. `auto_sync_calendar`/`claqo_calendar_id` coerenti tra Task 2 (modello/migrazione), Task 5 (status/toggle) e Task 6 (UI). ✓

## Note operative (fuori codice, per Matteo)

- Prerequisito: creare un **OAuth client "Web"** in Google Cloud Console, abilitare **Google Calendar API** + **Google Drive API**, impostare il redirect URI `{OAUTH_REDIRECT_BASE_URL}/auth/oauth/google/callback` (dev e prod), e incollare `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` in `.env`.
- Cambio scope ⇒ gli account eventualmente già collegati devono **riconnettersi** (nessuno in UI oggi).

## Execution Handoff

Fasi B/C/D avranno il proprio piano dopo che A è spedita e testata.
