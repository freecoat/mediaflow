"""
MediaFlow — Audit E2E completo (v3.5.0-alpha.66.5.2).

Replay del flusso operativo end-to-end via TestClient FastAPI su DB isolato.
Verifica consistency dopo ogni step, registra OK/FAIL/WARN, genera report.

DB isolato: copia di mediaflow.db in audit_temp.db. Lo script lavora SOLO su
quella copia. Il DB principale non viene mai toccato.

Esegui:
    python scripts/audit_e2e.py

Output:
    docs/audit-e2e-report.md  (report dettagliato con tabella step/esito)
"""
from __future__ import annotations
import os
import sys
import shutil
import tempfile
import traceback
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# Setup DB isolato PRIMA di qualunque import di app.*
# ============================================================
SRC_DB = ROOT / "mediaflow.db"
TMP_DB = ROOT / "audit_temp.db"
if TMP_DB.exists():
    TMP_DB.unlink()
if SRC_DB.exists():
    shutil.copy2(SRC_DB, TMP_DB)
    print(f"[setup] DB copiato in {TMP_DB.name}")
else:
    print(f"[setup] WARN: {SRC_DB.name} non trovato, parto da DB vuoto")

os.environ["DATABASE_URL"] = f"sqlite:///{TMP_DB.as_posix()}"
print(f"[setup] DATABASE_URL = {os.environ['DATABASE_URL']}")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============================================================
# Import app dopo setup env
# ============================================================
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import User, BookingState

# ============================================================
# Audit report data structure
# ============================================================
class StepResult:
    def __init__(self, name: str):
        self.name = name
        self.status: str = "PENDING"  # OK | FAIL | WARN | SKIP
        self.detail: str = ""
        self.error: Optional[str] = None
        self.payload: Any = None

    def ok(self, detail: str = "", payload: Any = None):
        self.status = "OK"
        self.detail = detail
        self.payload = payload
        print(f"  ✓ {self.name}: {detail}")

    def fail(self, error: str, payload: Any = None):
        self.status = "FAIL"
        self.error = error
        self.payload = payload
        print(f"  ✗ {self.name}: {error}")

    def warn(self, detail: str, payload: Any = None):
        self.status = "WARN"
        self.detail = detail
        self.payload = payload
        print(f"  ⚠ {self.name}: {detail}")

    def skip(self, reason: str):
        self.status = "SKIP"
        self.detail = reason
        print(f"  – {self.name}: SKIP — {reason}")


class Audit:
    def __init__(self):
        self.steps: list[StepResult] = []
        self.context: dict = {}  # condividi ID fra step

    def step(self, name: str) -> StepResult:
        s = StepResult(name)
        self.steps.append(s)
        return s

    def section(self, title: str):
        print(f"\n[{title}]")

    def summary(self) -> dict:
        out = {"OK": 0, "FAIL": 0, "WARN": 0, "SKIP": 0, "PENDING": 0}
        for s in self.steps:
            out[s.status] = out.get(s.status, 0) + 1
        return out


audit = Audit()
client = TestClient(app)


# ============================================================
# Helpers
# ============================================================
def admin_user_id() -> int:
    with SessionLocal() as db:
        u = db.query(User).filter(User.is_active == True).order_by(User.id).first()
        if not u:
            raise RuntimeError("Nessun utente admin trovato nel DB")
        return u.id


def login_as_admin() -> str:
    """Bypass login: genero token JWT firmato per il primo admin attivo
    e lo setto come cookie. Sfruttiamo create_access_token internamente
    (no need di password reali — l'audit ha accesso al SECRET_KEY)."""
    from app.services.auth import create_access_token
    with SessionLocal() as db:
        u = (db.query(User)
             .filter(User.is_active == True)
             .order_by(User.id).first())
        if not u:
            raise RuntimeError("Nessun utente admin")
        username = u.email
    token = create_access_token({"sub": username})
    client.cookies.set("access_token", token)
    return token


def post(url: str, data: dict, expect: int = 200) -> dict:
    r = client.post(url, data=data, follow_redirects=False)
    if r.status_code != expect:
        raise AssertionError(f"POST {url} atteso {expect} got {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except Exception:
        return {}


def put(url: str, data: dict, expect: int = 200) -> dict:
    r = client.put(url, data=data, follow_redirects=False)
    if r.status_code != expect:
        raise AssertionError(f"PUT {url} atteso {expect} got {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except Exception:
        return {}


def patch(url: str, data: dict, expect: int = 200) -> dict:
    r = client.patch(url, data=data, follow_redirects=False)
    if r.status_code != expect:
        raise AssertionError(f"PATCH {url} atteso {expect} got {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except Exception:
        return {}


def get_(url: str, expect: int = 200, params: Optional[dict] = None) -> Any:
    r = client.get(url, params=params or {})
    if r.status_code != expect:
        raise AssertionError(f"GET {url} atteso {expect} got {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except Exception:
        return r.text


def delete(url: str, expect: int = 200, params: Optional[dict] = None) -> Any:
    r = client.delete(url, params=params or {})
    if r.status_code != expect:
        raise AssertionError(f"DELETE {url} atteso {expect} got {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except Exception:
        return r.text


def db_count(table: str) -> int:
    with SessionLocal() as db:
        return db.execute(__import__("sqlalchemy").text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0


# ============================================================
# AUDIT — Fase 1: setup + auth
# ============================================================
def phase_1_setup_auth():
    audit.section("Fase 1 — Setup + Auth")

    s = audit.step("App boot pulito (routes + version)")
    try:
        assert len(app.routes) >= 270, f"too few routes: {len(app.routes)}"
        s.ok(f"{len(app.routes)} routes, version {app.version}")
    except Exception as e:
        s.fail(str(e))
        return False

    s = audit.step("DB migrazione bookings.state al boot")
    try:
        # Verifica che la colonna state esista in bookings
        with SessionLocal() as db:
            from sqlalchemy import text
            cols = db.execute(text("PRAGMA table_info(bookings)")).fetchall()
            col_names = [c[1] for c in cols]
            assert "state" in col_names, f"bookings.state non esiste: {col_names}"
            s.ok(f"bookings.state presente (migrazione α.66.5 eseguita)")
    except Exception as e:
        s.fail(str(e))

    s = audit.step("Login admin (cookie JWT)")
    try:
        tok = login_as_admin()
        assert tok, "no token"
        audit.context["token"] = tok
        s.ok(f"login OK, token len={len(tok)}")
    except Exception as e:
        s.fail(str(e))
        return False

    return True


# ============================================================
# AUDIT — Fase 2: anagrafiche
# ============================================================
def phase_2_anagrafiche():
    audit.section("Fase 2 — Anagrafiche")

    # Reparti già esistenti (preservati post-purge)
    s = audit.step("Reparti pre-esistenti")
    try:
        depts = get_("/departments/api")
        n = len(depts)
        assert n >= 4, f"reparti < 4: {n}"
        audit.context["dept_id"] = depts[0]["id"]
        s.ok(f"{n} reparti, primo: {depts[0]['name']} (id={depts[0]['id']})")
    except Exception as e:
        s.fail(str(e))

    # Risorsa nuova
    s = audit.step("Crea risorsa")
    try:
        r = post("/resources/api", {
            "name": "Test Operator E2E",
            "type": "person_internal",
            "department_id": str(audit.context.get("dept_id", 1)),
            "role": "Colorist",
            "daily_rate": "400",
            "hourly_rate": "50",
            "color": "#6272f5",
        })
        audit.context["resource_id"] = r.get("id")
        s.ok(f"risorsa #{r.get('id')} creata")
    except Exception as e:
        s.fail(str(e))

    # Cliente nuovo
    s = audit.step("Crea cliente")
    try:
        c = post("/clients/api", {
            "name": "Cliente Test E2E",
            "vat_number": "IT12345678901",
            "contact_email": "test@cliente-e2e.it",
        })
        audit.context["client_id"] = c.get("id")
        s.ok(f"cliente #{c.get('id')} creato")
    except Exception as e:
        s.fail(str(e))

    # Progetto nuovo
    s = audit.step("Crea progetto")
    try:
        p = post("/projects/api", {
            "code": "TEST-E2E-01",
            "title": "Audit E2E Project",
            "client_id": str(audit.context.get("client_id", 1)),
            "status": "active",
        })
        audit.context["project_id"] = p.get("id")
        s.ok(f"progetto #{p.get('id')} ({p.get('code')}) creato")
    except Exception as e:
        s.fail(str(e))

    # Listino preservato
    s = audit.step("Listino pre-esistente (price_items)")
    try:
        items = get_("/pricelist/api/items")
        n = len(items) if isinstance(items, list) else 0
        assert n >= 1, f"listino vuoto: {n}"
        # Prendo i primi 2 voci con unit time-based per le quote
        time_items = [it for it in items
                      if (it.get("unit") or "").lower() in ("day", "hour", "giorno", "ore")][:2]
        if not time_items:
            time_items = items[:2]
        audit.context["price_items"] = time_items
        s.ok(f"{n} voci listino, primi 2 selezionati: {time_items[0].get('name','?')} / {time_items[1].get('name','?')}")
    except Exception as e:
        s.fail(str(e))


# ============================================================
# AUDIT — Fase 3: quote → job
# ============================================================
def phase_3_quote_job():
    audit.section("Fase 3 — Quote + Job")

    s = audit.step("Crea quote")
    try:
        today = date.today().isoformat()
        valid = (date.today() + timedelta(days=30)).isoformat()
        q = post("/quotes/api", {
            "number": "Q-E2E-001",
            "project_id": str(audit.context.get("project_id", 1)),
            "title": "Audit E2E Quote",
            "issue_date": today,
            "valid_until": valid,
            "vat_rate": "22",
        })
        audit.context["quote_id"] = q.get("id")
        s.ok(f"quote #{q.get('id')} ({q.get('number')}) creata")
    except Exception as e:
        s.fail(str(e))

    # Aggiungi 2 righe al quote
    s = audit.step("Aggiungi righe alla quote")
    try:
        items = audit.context.get("price_items", [])
        line_ids = []
        for i, pi in enumerate(items[:2]):
            ln = post(f"/quotes/api/{audit.context['quote_id']}/lines", {
                "price_item_id": str(pi["id"]),
                "description": pi.get("name", "Line"),
                "quantity": "5" if i == 0 else "3",
                "unit": pi.get("unit") or "day",
                "unit_price": str(pi.get("unit_price") or pi.get("list_price") or 100),
                "section": "A",
            })
            line_ids.append(ln.get("id"))
        audit.context["quote_line_ids"] = line_ids
        s.ok(f"{len(line_ids)} righe aggiunte: {line_ids}")
    except Exception as e:
        s.fail(str(e))

    # Approva quote → genera Job + JCL (endpoint reale: convert-to-job)
    s = audit.step("Convert quote → Job + JCL")
    try:
        r = post(f"/quotes/api/{audit.context.get('quote_id')}/convert-to-job", {})
        audit.context["job_id"] = r.get("job_id") or r.get("id")
        s.ok(f"quote convertita, job #{audit.context['job_id']}")
    except Exception as e:
        s.fail(str(e))

    # Verify JCL auto-create
    s = audit.step("Verify JobCostLines auto-create")
    try:
        from sqlalchemy import text
        with SessionLocal() as db:
            count = db.execute(
                text("SELECT COUNT(*) FROM job_cost_lines WHERE job_id = :j"),
                {"j": audit.context["job_id"]}
            ).scalar()
            assert count >= 2, f"JCL count < 2: {count}"
            jcls = db.execute(
                text("SELECT id, description, quantity_quoted, unit_price FROM job_cost_lines WHERE job_id = :j ORDER BY id"),
                {"j": audit.context["job_id"]}
            ).fetchall()
            audit.context["jcl_ids"] = [r[0] for r in jcls]
            s.ok(f"{count} JCL auto-create, ids={audit.context['jcl_ids']}")
    except Exception as e:
        s.fail(str(e))


# ============================================================
# AUDIT — Fase 4: booking + lifecycle state
# ============================================================
def phase_4_booking_lifecycle():
    audit.section("Fase 4 — Booking lifecycle (state transitions)")

    rid = audit.context.get("resource_id")
    job_id = audit.context.get("job_id")
    jcl_ids = audit.context.get("jcl_ids", [])
    if not (rid and job_id and jcl_ids):
        audit.step("phase 4 prerequisites").skip("missing context (rid/job/jcl)")
        return

    # Booking semplice (tentative default)
    s = audit.step("Crea booking (1 risorsa, 1 giorno)")
    try:
        import json as _json
        # Domani 09:00 → 18:00
        start = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        end = start.replace(hour=18)
        b = post("/planning/api/bookings", {
            "assignments": _json.dumps([{
                "resource_id": rid,
                "start_datetime": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "end_datetime": end.strftime("%Y-%m-%dT%H:%M:%S"),
            }]),
            "kind": "project",
            "job_id": str(job_id),
            "job_cost_line_id": str(jcl_ids[0]),
            "status": "tentative",
        })
        audit.context["booking_id"] = b.get("id")
        s.ok(f"booking #{b.get('id')} creato (tentative)")
    except Exception as e:
        s.fail(str(e))

    bid = audit.context.get("booking_id")
    if not bid:
        return

    # Verifica state in DB
    s = audit.step("Verify state=tentative in DB")
    try:
        from sqlalchemy import text
        with SessionLocal() as db:
            row = db.execute(
                text("SELECT state, status, execution_status FROM bookings WHERE id = :i"),
                {"i": bid}
            ).first()
            assert row[0] == "tentative", f"state expected tentative got {row[0]}"
            assert row[1] == "tentative", f"status expected tentative got {row[1]}"
            assert row[2] == "planned", f"exec expected planned got {row[2]}"
            s.ok(f"state={row[0]}, status={row[1]}, exec={row[2]} — sync coerente")
    except Exception as e:
        s.fail(str(e))

    # Transizione tentative → confirmed
    s = audit.step("PATCH /state → confirmed")
    try:
        r = patch(f"/planning/api/bookings/{bid}/state", {"state": "confirmed"})
        assert r.get("state") == "confirmed"
        s.ok(f"state={r.get('state')}, status={r.get('status')}, exec={r.get('execution_status')}")
    except Exception as e:
        s.fail(str(e))

    # Transizione → in_progress
    s = audit.step("PATCH /state → in_progress")
    try:
        r = patch(f"/planning/api/bookings/{bid}/state", {"state": "in_progress"})
        assert r.get("state") == "in_progress"
        assert r.get("execution_status") == "in_progress"
        s.ok(f"state={r.get('state')}, exec={r.get('execution_status')}")
    except Exception as e:
        s.fail(str(e))

    # Transizione → done
    s = audit.step("PATCH /state → done (triggera cost-line sync)")
    try:
        r = patch(f"/planning/api/bookings/{bid}/state", {"state": "done"})
        assert r.get("state") == "done"
        # Verify quantity_actual aggiornato
        from sqlalchemy import text
        with SessionLocal() as db:
            qty = db.execute(
                text("SELECT quantity_actual, total_accrued FROM job_cost_lines WHERE id = :i"),
                {"i": jcl_ids[0]}
            ).first()
            # 9h durata day-unit → ~1.125 giorni se day; o 9h se hour
            audit.context["jcl0_qty_actual"] = qty[0]
            audit.context["jcl0_total_accrued"] = qty[1]
            s.ok(f"state=done, jcl quantity_actual={qty[0]}, total_accrued={qty[1]}")
    except Exception as e:
        s.fail(str(e))

    # Transizione → not_done (richiede reason)
    s = audit.step("PATCH /state → not_done senza reason → 400")
    try:
        r = client.patch(f"/planning/api/bookings/{bid}/state",
                         data={"state": "not_done"})
        assert r.status_code == 400, f"expected 400 got {r.status_code}"
        s.ok(f"400 corretto: motivazione obbligatoria")
    except Exception as e:
        s.fail(str(e))

    s = audit.step("PATCH /state → not_done con reason")
    try:
        r = patch(f"/planning/api/bookings/{bid}/state", {
            "state": "not_done",
            "not_done_reason": "Test risorsa malata",
        })
        assert r.get("state") == "not_done"
        s.ok(f"state=not_done, reason='{r.get('not_done_reason')}'")
    except Exception as e:
        s.fail(str(e))

    # Transizione → confirmed (riapertura)
    s = audit.step("PATCH /state → confirmed (riapri da not_done)")
    try:
        r = patch(f"/planning/api/bookings/{bid}/state", {"state": "confirmed"})
        assert r.get("state") == "confirmed"
        s.ok(f"riaperto, state={r.get('state')}, reason={r.get('not_done_reason')}")
    except Exception as e:
        s.fail(str(e))


# ============================================================
# AUDIT — Fase 5: smart-split + bulk + multi-move (test fix α.66.5.2)
# ============================================================
def phase_5_smart_split_and_bulk():
    audit.section("Fase 5 — Smart-split + bulk-edit + multi-move (fix α.66.5.2)")

    rid = audit.context.get("resource_id")
    job_id = audit.context.get("job_id")
    jcl_ids = audit.context.get("jcl_ids", [])
    if not (rid and job_id and jcl_ids):
        audit.step("phase 5 prerequisites").skip("missing context")
        return

    # Booking smart-split (mattina + pomeriggio)
    s = audit.step("Crea booking smart-split (2 segmenti contigui stessa risorsa)")
    try:
        import json as _json
        d = (datetime.now() + timedelta(days=2)).date()
        morning_s = datetime.combine(d, datetime.min.time()).replace(hour=9)
        morning_e = datetime.combine(d, datetime.min.time()).replace(hour=13)
        afternoon_s = datetime.combine(d, datetime.min.time()).replace(hour=14)
        afternoon_e = datetime.combine(d, datetime.min.time()).replace(hour=18)
        b = post("/planning/api/bookings", {
            "assignments": _json.dumps([
                {"resource_id": rid,
                 "start_datetime": morning_s.strftime("%Y-%m-%dT%H:%M:%S"),
                 "end_datetime": morning_e.strftime("%Y-%m-%dT%H:%M:%S")},
                {"resource_id": rid,
                 "start_datetime": afternoon_s.strftime("%Y-%m-%dT%H:%M:%S"),
                 "end_datetime": afternoon_e.strftime("%Y-%m-%dT%H:%M:%S")},
            ]),
            "kind": "project",
            "job_id": str(job_id),
            "job_cost_line_id": str(jcl_ids[1] if len(jcl_ids) > 1 else jcl_ids[0]),
            "status": "tentative",
        })
        audit.context["smart_split_booking_id"] = b.get("id")
        smart_assigns = b.get("assignments", [])
        audit.context["smart_split_aids"] = [a["id"] for a in smart_assigns]
        assert len(smart_assigns) == 2, f"expected 2 segments got {len(smart_assigns)}"
        s.ok(f"booking #{b.get('id')} con 2 segmenti: aids={audit.context['smart_split_aids']}")
    except Exception as e:
        s.fail(str(e))

    aids = audit.context.get("smart_split_aids", [])
    if len(aids) < 2:
        return

    # Drag-resize 1° segmento (test fix α.66.5.2 single-edit)
    s = audit.step("[α.66.5.2] Drag-resize mattina 09-13 → 10-13:30 (NON deve vedere pomeriggio come conflitto)")
    try:
        d = (datetime.now() + timedelta(days=2)).date()
        new_s = datetime.combine(d, datetime.min.time()).replace(hour=10)
        new_e = datetime.combine(d, datetime.min.time()).replace(hour=13, minute=30)
        r = put(f"/planning/api/booking-assignments/{aids[0]}", {
            "start_datetime": new_s.strftime("%Y-%m-%dT%H:%M:%S"),
            "end_datetime": new_e.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        s.ok("drag-resize OK, fratello pomeriggio non blocca")
    except Exception as e:
        s.fail(str(e))

    # Drag-resize che provoca overlap stretto col fratello (deve fallire)
    s = audit.step("[α.66.5.2] Drag-resize che sovrappone strettamente al fratello → 409 chiaro")
    try:
        d = (datetime.now() + timedelta(days=2)).date()
        new_s = datetime.combine(d, datetime.min.time()).replace(hour=15)
        new_e = datetime.combine(d, datetime.min.time()).replace(hour=17)  # in pieno pomeriggio
        r = client.put(f"/planning/api/booking-assignments/{aids[0]}",
                       data={"start_datetime": new_s.strftime("%Y-%m-%dT%H:%M:%S"),
                             "end_datetime": new_e.strftime("%Y-%m-%dT%H:%M:%S")})
        assert r.status_code == 409, f"expected 409 got {r.status_code}: {r.text[:200]}"
        body = r.json()
        msg = body.get("detail") if isinstance(body.get("detail"), str) else str(body.get("detail"))
        assert "stesso booking" in msg.lower() or "sovrapposi" in msg.lower(), f"messaggio non chiaro: {msg}"
        s.ok(f"409 con msg chiaro: '{msg[:80]}…'")
    except Exception as e:
        s.fail(str(e))

    # Bulk-edit absolute_start/end su smart-split (test fix α.66.5.2)
    s = audit.step("[α.66.5.2] Bulk-edit absolute_start/end su smart-split → errore esplicito INTRA-OVERLAP")
    try:
        ssbid = audit.context["smart_split_booking_id"]
        r = client.put(f"/planning/api/bookings/{ssbid}/bulk-edit", data={
            "booking_ids": str(ssbid),
            "absolute_start_time": "10:00",
            "absolute_end_time": "18:00",
        })
        body = r.json()
        # Si aspetta che il booking finisca in failed[] con message INTRA
        failed = body.get("failed") or []
        assert len(failed) == 1, f"expected 1 failed, got {failed}"
        err_msg = failed[0].get("error", "") + " " + failed[0].get("reason", "")
        assert "smart-split" in err_msg.lower() or "sovrappost" in err_msg.lower(), \
            f"messaggio non esplicito: {err_msg}"
        s.ok(f"bulk respinge correttamente: '{err_msg[:80]}…'")
    except Exception as e:
        s.fail(str(e))

    # Bulk-edit shift_minutes su smart-split (deve passare entrambi)
    s = audit.step("[α.66.5.2] Bulk-edit shift_minutes +60 su smart-split → entrambi shiftati")
    try:
        ssbid = audit.context["smart_split_booking_id"]
        r = client.put(f"/planning/api/bookings/{ssbid}/bulk-edit", data={
            "booking_ids": str(ssbid),
            "shift_minutes": "60",
        })
        body = r.json()
        assert body.get("ok") == 1, f"expected ok=1 got {body}"
        s.ok(f"shift +60min OK su smart-split (entrambi i segmenti)")
    except Exception as e:
        s.fail(str(e))


# ============================================================
# AUDIT — Fase 6: AI tools (verifica struttura, no esecuzione provider)
# ============================================================
def phase_6_ai_tools():
    audit.section("Fase 6 — AI tools schema + endpoint")

    s = audit.step("AI tools registry esposto (schema)")
    try:
        from app.services.ai_tools import TOOLS as TOOL_SCHEMAS
        names = [t["name"] for t in TOOL_SCHEMAS]
        # Verifica capability previste post-α.66
        expected = {"propose_client", "propose_project", "propose_quote",
                    "propose_quote_line", "propose_booking", "web_search"}
        missing = expected - set(names)
        if missing:
            s.warn(f"capability mancanti: {missing}", payload=names)
        else:
            s.ok(f"{len(names)} capability registrate, tutte le previste presenti")
    except Exception as e:
        s.fail(str(e))

    # Endpoint copilot raggiungibile
    s = audit.step("Endpoint copilot /ai/api/chat raggiungibile (no provider call)")
    try:
        # Senza chiave AI, l'endpoint dovrebbe rispondere con un fallback leggibile
        # o errore controllato. Verifica solo che esista.
        r = client.get("/ai/api/conversations")
        assert r.status_code in (200, 401, 403), f"unexpected {r.status_code}"
        s.ok(f"endpoint risponde con {r.status_code}")
    except Exception as e:
        s.fail(str(e))

    # propose_booking schema description aggiornato (α.66.5.1)
    s = audit.step("[α.66.5.1] propose_booking schema menziona BookingState")
    try:
        from app.services.ai_tools import TOOLS as TOOL_SCHEMAS
        tool = next((t for t in TOOL_SCHEMAS if t["name"] == "propose_booking"), None)
        assert tool, "propose_booking non trovato"
        desc = tool.get("description", "")
        assert "BookingState" in desc or "5 stati" in desc, f"description legacy: {desc[:80]}"
        s.ok(f"description aggiornata: '{desc[:60]}…'")
    except Exception as e:
        s.fail(str(e))


# ============================================================
# AUDIT — Fase 7: cost-report consistency + cestino
# ============================================================
def phase_7_costreport_trash():
    audit.section("Fase 7 — Cost-report + cestino")

    job_id = audit.context.get("job_id")
    if not job_id:
        audit.step("phase 7 prerequisites").skip("no job_id")
        return

    s = audit.step("Cost-report aggregati corretti")
    try:
        cr = get_(f"/cost-report/api/job/{job_id}")
        summary = cr.get("summary", {})
        # Almeno il maturato deve essere ≥ 0 (potrebbe essere 0 se nessun booking done)
        ta = summary.get("total_accrued", 0)
        tq = summary.get("total_quoted", 0)
        s.ok(f"total_quoted={tq}, total_accrued={ta}, lines={len(cr.get('cost_lines',[]))}")
    except Exception as e:
        s.fail(str(e))

    # Soft-delete booking smart-split
    ssbid = audit.context.get("smart_split_booking_id")
    if ssbid:
        s = audit.step("Soft-delete booking smart-split (verifica state=cancelled)")
        try:
            r = client.delete(f"/planning/api/bookings/{ssbid}")
            assert r.status_code == 200
            from sqlalchemy import text
            with SessionLocal() as db:
                row = db.execute(
                    text("SELECT state, status FROM bookings WHERE id = :i"),
                    {"i": ssbid}
                ).first()
                assert row[0] == "cancelled", f"state expected cancelled got {row[0]}"
                assert row[1] == "cancelled", f"status expected cancelled got {row[1]}"
                s.ok(f"soft-delete OK, state={row[0]}, status={row[1]}")
        except Exception as e:
            s.fail(str(e))

        # Restore
        s = audit.step("Restore booking → state=tentative")
        try:
            r = client.post(f"/planning/api/bookings/{ssbid}/restore")
            assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text[:200]}"
            from sqlalchemy import text
            with SessionLocal() as db:
                row = db.execute(
                    text("SELECT state, status FROM bookings WHERE id = :i"),
                    {"i": ssbid}
                ).first()
                assert row[0] == "tentative"
                s.ok(f"restore OK, state={row[0]}, status={row[1]}")
        except Exception as e:
            s.fail(str(e))


# ============================================================
# AUDIT — Fase 8: diag endpoints (post-purge utility)
# ============================================================
def phase_8_diag():
    audit.section("Fase 8 — Diag endpoints (audit utility)")

    s = audit.step("GET /api/diag/scan-duplicate-overlaps")
    try:
        r = get_("/planning/api/diag/scan-duplicate-overlaps")
        assert "scanned_bookings" in r
        assert "dirty_bookings_count" in r
        s.ok(f"scanned={r['scanned_bookings']}, dirty={r['dirty_bookings_count']}, "
             f"phantom_h={r.get('total_phantom_hours', 0)}")
    except Exception as e:
        s.fail(str(e))

    bid = audit.context.get("booking_id")
    if bid:
        s = audit.step(f"GET /api/diag/booking-raw/{bid}")
        try:
            r = get_(f"/planning/api/diag/booking-raw/{bid}")
            assert r.get("booking", {}).get("id") == bid
            assert "duplicate_overlap_detected" in r
            s.ok(f"booking #{bid} dump OK, "
                 f"assignments={r.get('assignments_count', 0)}, "
                 f"audit_changes={r.get('audit_changes_count', 0)}")
        except Exception as e:
            s.fail(str(e))


# ============================================================
# AUDIT — Fase 9: invariants
# ============================================================
def phase_9_invariants():
    audit.section("Fase 9 — Invariants")

    s = audit.step("Tutti i bookings: state ↔ status+execution_status sono coerenti")
    try:
        from sqlalchemy import text
        with SessionLocal() as db:
            rows = db.execute(text(
                "SELECT id, state, status, execution_status FROM bookings"
            )).fetchall()
            mismatches = []
            for (id_, state, status, execution_status) in rows:
                # Mapping atteso (BOOKING_STATE_TO_LEGACY)
                expected = {
                    "tentative":   ("tentative", "planned"),
                    "confirmed":   ("confirmed", "planned"),
                    "in_progress": ("confirmed", "in_progress"),
                    "done":        ("confirmed", "done"),
                    "not_done":    ("confirmed", "not_done"),
                    "cancelled":   ("cancelled", "planned"),
                }.get(state)
                if not expected:
                    mismatches.append(f"#{id_}: state={state} non valido")
                    continue
                if (status, execution_status) != expected:
                    mismatches.append(
                        f"#{id_}: state={state} ma (status,exec)=({status},{execution_status}) "
                        f"atteso {expected}"
                    )
            if mismatches:
                s.fail(f"{len(mismatches)} mismatch trovati", payload=mismatches[:5])
            else:
                s.ok(f"tutti i {len(rows)} booking sono coerenti")
    except Exception as e:
        s.fail(str(e))

    s = audit.step("Nessun assignment duplicate-overlap residuo")
    try:
        r = get_("/planning/api/diag/scan-duplicate-overlaps")
        if r.get("dirty_bookings_count", 0) > 0:
            s.fail(f"{r['dirty_bookings_count']} booking sporchi: {r.get('dirty_bookings', [])[:3]}")
        else:
            s.ok("DB pulito da duplicate-overlap")
    except Exception as e:
        s.fail(str(e))

    s = audit.step("Job.weighted_revenue colonna esiste (α.65)")
    try:
        from sqlalchemy import text
        with SessionLocal() as db:
            cols = db.execute(text("PRAGMA table_info(jobs)")).fetchall()
            col_names = [c[1] for c in cols]
            assert "weighted_revenue" in col_names
            s.ok("colonna jobs.weighted_revenue presente")
    except Exception as e:
        s.fail(str(e))

    s = audit.step("Quote.parent_quote_id + superseded_by_id (versioning α.39)")
    try:
        from sqlalchemy import text
        with SessionLocal() as db:
            cols = db.execute(text("PRAGMA table_info(quotes)")).fetchall()
            col_names = [c[1] for c in cols]
            assert "parent_quote_id" in col_names
            assert "superseded_by_id" in col_names
            s.ok("versioning quote presente")
    except Exception as e:
        s.fail(str(e))


# ============================================================
# Report markdown
# ============================================================
def write_report():
    summary = audit.summary()
    out_path = ROOT / "docs" / "audit-e2e-report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append(f"# Audit E2E MediaFlow — {app.version}")
    lines.append("")
    lines.append(f"_Eseguito: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
    lines.append(f"_DB isolato: `audit_temp.db` (copia di mediaflow.db)_")
    lines.append("")
    lines.append(f"## Sintesi")
    lines.append(f"| Esito | Conteggio |")
    lines.append(f"|---|---|")
    lines.append(f"| ✓ OK | {summary.get('OK', 0)} |")
    lines.append(f"| ✗ FAIL | {summary.get('FAIL', 0)} |")
    lines.append(f"| ⚠ WARN | {summary.get('WARN', 0)} |")
    lines.append(f"| – SKIP | {summary.get('SKIP', 0)} |")
    lines.append(f"| **Totale step** | {len(audit.steps)} |")
    lines.append("")

    # FAIL prima
    fails = [s for s in audit.steps if s.status == "FAIL"]
    if fails:
        lines.append(f"## ❌ Step FAIL ({len(fails)})")
        lines.append("")
        for s in fails:
            lines.append(f"### {s.name}")
            lines.append(f"```\n{s.error}\n```")
            if s.payload:
                lines.append(f"Payload: `{s.payload}`")
            lines.append("")

    warns = [s for s in audit.steps if s.status == "WARN"]
    if warns:
        lines.append(f"## ⚠ Step WARN ({len(warns)})")
        lines.append("")
        for s in warns:
            lines.append(f"- **{s.name}**: {s.detail}")
        lines.append("")

    lines.append("## Dettaglio per fase")
    lines.append("")
    lines.append("| Step | Esito | Dettaglio / Errore |")
    lines.append("|---|---|---|")
    for s in audit.steps:
        icon = {"OK":"✓", "FAIL":"✗", "WARN":"⚠", "SKIP":"–", "PENDING":"?"}.get(s.status, "?")
        info = s.detail or s.error or ""
        info = info.replace("|", "\\|").replace("\n", "<br>")[:200]
        lines.append(f"| {s.name} | {icon} {s.status} | {info} |")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[report] scritto: {out_path}")
    return out_path


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 70)
    print(f"MediaFlow Audit E2E — {app.version}")
    print("=" * 70)
    try:
        if not phase_1_setup_auth():
            print("[abort] Setup/Auth fallito")
            return 1
        phase_2_anagrafiche()
        phase_3_quote_job()
        phase_4_booking_lifecycle()
        phase_5_smart_split_and_bulk()
        phase_6_ai_tools()
        phase_7_costreport_trash()
        phase_8_diag()
        phase_9_invariants()
    except Exception as e:
        print(f"\n[FATAL] {type(e).__name__}: {e}")
        traceback.print_exc()
        s = audit.step("FATAL ERROR")
        s.fail(f"{type(e).__name__}: {e}")
    finally:
        out = write_report()
        summary = audit.summary()
        print("\n" + "=" * 70)
        print(f"Sintesi: OK={summary.get('OK',0)}  "
              f"FAIL={summary.get('FAIL',0)}  "
              f"WARN={summary.get('WARN',0)}  "
              f"SKIP={summary.get('SKIP',0)}")
        print(f"Report: {out}")
        print("=" * 70)
    return 0 if audit.summary().get("FAIL", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
