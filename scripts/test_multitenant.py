"""v3.5.0-alpha.103 R-MT4 — Smoke test cross-tenant leak.

Test E2E via HTTP. Richiede server in esecuzione su localhost:8000 +
tenant `acme` già creato via `scripts/create_tenant.py`.

Eseguibile: `python scripts/test_multitenant.py`

Test eseguiti:
1. Login admin@acme.it via ?tenant=acme → 303 + JWT.tid=2
2. Login admin@mediaflow.it via ?tenant=acme → 401 (cross-tenant block)
3. Cookie tenant 1 + header X-Tenant-Slug=acme → redirect (gate)
4. /clients/api con cookie acme → []
5. /clients/api con cookie tenant 1 → lista popolata
6. /projects/api con cookie acme + project_id da tenant 1 → 404
"""
import sys, json, base64
import urllib.request, urllib.parse, http.cookiejar
import re

BASE = "http://127.0.0.1:8000"


def decode_jwt(token: str) -> dict:
    parts = token.split(".")
    pad = "=" * ((4 - len(parts[1]) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(parts[1] + pad).decode("utf-8"))


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # disabilita follow


def make_session(follow=True):
    cj = http.cookiejar.CookieJar()
    handlers = [urllib.request.HTTPCookieProcessor(cj)]
    if not follow:
        handlers.append(NoRedirectHandler())
    opener = urllib.request.build_opener(*handlers)
    return cj, opener


def login(session_opener, email: str, password: str, tenant_slug: str = None):
    url = f"{BASE}/auth/login"
    if tenant_slug:
        url += f"?tenant={tenant_slug}"
    data = urllib.parse.urlencode({"email": email, "password": password}).encode()
    req = urllib.request.Request(url, data=data)
    try:
        resp = session_opener.open(req)
        return resp.status, resp
    except urllib.error.HTTPError as e:
        return e.code, e


def get(session_opener, path: str, headers: dict = None):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        resp = session_opener.open(req)
        body = resp.read().decode("utf-8", errors="ignore")
        return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="ignore")


def find_cookie(cj, name):
    for c in cj:
        if c.name == name:
            return c.value
    return None


def run():
    passed = 0
    failed = 0

    def check(label, cond, detail=""):
        nonlocal passed, failed
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {label} {detail}")
        if cond: passed += 1
        else: failed += 1

    # ── Test 1+2: login con tenant scope ──
    print("\n=== T1: Login admin@acme.it via ?tenant=acme ===")
    cj_acme, op_acme = make_session(follow=False)
    status, _ = login(op_acme, "admin@acme.it", "acmepw123", "acme")
    check("303 redirect", status == 303, f"got {status}")
    # Re-make session WITH cookie ma con redirect follow per i test seguenti
    op_acme_follow = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj_acme),
    )
    tok = find_cookie(cj_acme, "access_token")
    if tok:
        payload = decode_jwt(tok)
        check("JWT.tid == 2", payload.get("tid") == 2, f"got tid={payload.get('tid')}")
    else:
        check("JWT cookie set", False)

    print("\n=== T2: Login admin@mediaflow.it via ?tenant=acme (cross) ===")
    cj_x, op_x = make_session()
    status, _ = login(op_x, "admin@mediaflow.it", "admin123", "acme")
    check("401 (cross-tenant block)", status == 401, f"got {status}")

    # ── Test 3: cookie tenant 1 + header acme ──
    print("\n=== T3: Cookie tenant 1 + header X-Tenant-Slug=acme ===")
    cj1, op1 = make_session(follow=False)
    login(op1, "admin@mediaflow.it", "admin123")
    # Re-make con follow per test normale (no cross)
    op1_follow = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj1),
    )
    # Senza header
    status, body = get(op1_follow, "/clients/api")
    rows = json.loads(body) if status == 200 and body.startswith("[") else []
    check("/clients/api tenant 1 (no header) → 200 + lista", status == 200 and len(rows) > 0,
          f"got {status} rows={len(rows)}")
    # Con header cross — usa op1 senza follow per vedere il 303
    status, body = get(op1, "/clients/api", headers={"X-Tenant-Slug": "acme"})
    check("/clients/api tenant 1 + header acme → 303/401 (gate)",
          status in (303, 401), f"got {status}")

    # ── Test 4: tenant acme vede [] ──
    print("\n=== T4: tenant acme isolato (no clienti) ===")
    status, body = get(op_acme_follow, "/clients/api")
    rows = json.loads(body) if status == 200 and body.startswith("[") else None
    check("acme /clients/api → 200 + []", status == 200 and rows == [],
          f"got {status} body={body[:80]}")

    # ── Test 5: tenant 1 vede dati ──
    print("\n=== T5: tenant 1 ha clienti ===")
    status, body = get(op1_follow, "/clients/api")
    rows = json.loads(body) if status == 200 and body.startswith("[") else []
    check("/clients/api tenant 1 → lista non vuota", status == 200 and len(rows) > 0,
          f"rows={len(rows)}")

    # ── Test 6: cross-tenant project access ──
    print("\n=== T6: acme cerca project_id=1 (di tenant 1) ===")
    status, body = get(op_acme_follow, "/projects/api/1")
    check("acme GET /projects/api/1 → 404", status == 404, f"got {status}")

    print(f"\n\n=== RESULT: {passed} pass, {failed} fail ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
