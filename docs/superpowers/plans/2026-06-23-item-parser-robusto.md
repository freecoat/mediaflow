# Item-list Parser Robusto + Auto-extract — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the delivery-item-list parser reliable (strong model, no 30k truncation, chunk fallback) and auto-extract items after a UI capitolato save, reading from the persisted upload — so UI-uploaded capitolati (e.g. Paramount) get an item list like corpus capitolati.

**Architecture:** Extend α.172.228. Reuse `split_into_chunks` (deliverables_parser) and `pick_parse_provider` (ai_provider). Add a source-resolver in capitolato_storage. Wire auto-extract best-effort into `/api/save`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pytest. AI via `AIProvider.extract_json`. Python 3.11+.

## Global Constraints

- Version bump target: `v3.5.0-alpha.172.229` in `app/main.py`.
- Tenant scope via `current_tenant_id()` (router pattern). Form-based API. Soft-delete conventions.
- `git commit -F <file>` for bodies (heredocs blocked). Trailers on every commit:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_019zP3Q1MJ6LdVQLy1UaFM5y`
- Run tests with `.venv/Scripts/python.exe -m pytest`. Full suite once before each commit.
- Auto-extract on save MUST be best-effort: a failure never breaks the (already committed) save.
- Spec: `docs/superpowers/specs/2026-06-23-item-parser-robusto-design.md`.

---

## Task 1: `parse_delivery_items_v2` robustness (no 30k trunc + chunk PASS1 + merge)

**Files:**
- Modify: `app/services/delivery_items_parser.py` (function `parse_delivery_items_v2` ~line 174, add `_merge_items_by_name`)
- Test: `tests/test_item_parser_robust.py`

**Interfaces:**
- Consumes: `split_into_chunks` (from `app.services.deliverables_parser`), provider `.extract_json`.
- Produces: `_merge_items_by_name(item_lists: list[list[dict]]) -> list[dict]` (dedupe by normalized `name`, first wins, order preserved). `parse_delivery_items_v2(text, db, tenant_id=1, provider=None)` unchanged signature; result dict gains `parse_meta: {chunked, n_chunks, truncated, n_items}`. Module constants `MAX_CHARS_SINGLE=150_000`, `MAX_CHARS_HARD=600_000`; PASS1 `max_tokens` 4000→8000; PASS2 reference text capped at `MAX_CHARS_SINGLE`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_item_parser_robust.py
import pytest
from app.services import delivery_items_parser as dip
from app.services.delivery_items_parser import _merge_items_by_name


def test_merge_items_dedupe_by_name():
    a = [{"name": "ProRes 4444 Master"}, {"name": "Stereo M&E"}]
    b = [{"name": "prores 4444 master"}, {"name": "5.1 Printmaster"}]  # case-diff dup
    out = _merge_items_by_name([a, b])
    names = [i["name"] for i in out]
    assert names == ["ProRes 4444 Master", "Stereo M&E", "5.1 Printmaster"]


class _FakeProv:
    def __init__(self):
        self.pass1 = 0
        self.pass2 = 0
    def extract_json(self, system, user, max_tokens=3000):
        # distinguish pass1 vs pass2 by a marker in the system prompt
        if "MAPPARE" in system or "taxonomy" in system.lower():
            self.pass2 += 1
            return {"items": [{"name": "X"}]}
        self.pass1 += 1
        return {"items": [{"name": "Item%d" % self.pass1, "category": "MASTERING"}],
                "terms": {}}


def test_single_pass_under_limit(db):
    prov = _FakeProv()
    out = dip.parse_delivery_items_v2("capitolato breve " * 20, db, tenant_id=1, provider=prov)
    assert prov.pass1 == 1
    assert out["parse_meta"]["chunked"] is False
    assert prov.pass2 == 1


def test_oversized_chunks_pass1(db):
    prov = _FakeProv()
    out = dip.parse_delivery_items_v2("A" * 200_000, db, tenant_id=1, provider=prov)
    assert prov.pass1 >= 2          # chunked PASS1
    assert out["parse_meta"]["chunked"] is True
    assert prov.pass2 == 1          # PASS2 still single
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_item_parser_robust.py -v`
Expected: FAIL — `ImportError: _merge_items_by_name` / no `parse_meta`.

- [ ] **Step 3: Implement**

Read the current `parse_delivery_items_v2` (lines ~174-247) and `PASS1_SYSTEM_PROMPT`/`PASS2_SYSTEM_PROMPT`. Then:

1. Add at module level (after imports): `from app.services.deliverables_parser import split_into_chunks` and constants `MAX_CHARS_SINGLE = 150_000`, `MAX_CHARS_HARD = 600_000`.
2. Add `_merge_items_by_name`:

```python
def _merge_items_by_name(item_lists):
    """Unisce liste di item da più chunk; dedupe per name normalizzato, primo vince, ordine preservato."""
    out, seen = [], set()
    for lst in item_lists:
        for it in (lst or []):
            if not isinstance(it, dict):
                continue
            key = (it.get("name") or "").strip().lower()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            out.append(it)
    return out
```

3. Replace the `MAX_CHARS = 30000` truncation block + PASS1 with single-pass/chunk logic:
   - `truncated = False`; if `len(text) > MAX_CHARS_HARD: text = text[:MAX_CHARS_HARD] + "..."; truncated = True`.
   - `chunks = split_into_chunks(text, size=MAX_CHARS_SINGLE)`; `chunked = len(chunks) > 1`.
   - PASS1: run the existing PASS1 call per chunk (with `max_tokens=8000`), collect each result's `items` and merge with `_merge_items_by_name`; collect `terms` (merge dicts shallow). If no items at all → return `{"items": [], "pass1_terms": terms, "pass1_categories": [], "parse_meta": {...}}`.
4. PASS2: unchanged logic, but cap the reference `text` in `pass2_user` to `text[:MAX_CHARS_SINGLE]`. Keep `max_tokens=32000`.
5. Add `parse_meta` to the returned dict: `{"chunked": chunked, "n_chunks": len(chunks), "truncated": truncated, "n_items": len(<final items>)}`. Keep existing keys (`items`, `pass1_terms`, `pass1_categories`).

Preserve all existing error handling/returns (None on pass failures).

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_item_parser_robust.py -v` then full `.venv/Scripts/python.exe -m pytest tests/ -q`.
Expected: new tests PASS; no regression (existing item-parser tests still green).

- [ ] **Step 5: Commit**

`git add app/services/delivery_items_parser.py tests/test_item_parser_robust.py` → `git commit -F .git/COMMIT_I1.txt`
Subject: `feat(items): parse_delivery_items_v2 single-pass 150k + chunk PASS1 + merge`.

---

## Task 2: `resolve_capitolato_source` (persisted-or-corpus)

**Files:**
- Modify: `app/services/capitolato_storage.py`
- Test: `tests/test_capitolato_storage.py` (append)

**Interfaces:**
- Produces: `resolve_capitolato_source(template) -> tuple[bytes, str] | None` — returns `(file_bytes, filename)`. Order: (1) if `template.source_document_path` set AND file exists under `UPLOAD_DIR` (reuse the path-traversal guard) → read it; (2) elif `template.source_document_name` exists under `docs/capitolati_esempio/` → read it; (3) else None. Reads `template.source_document_path` / `.source_document_name` attributes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_capitolato_storage.py  (append)
from app.services import capitolato_storage as cs


class _Tpl:
    def __init__(self, path=None, name=None):
        self.source_document_path = path
        self.source_document_name = name


def test_resolve_prefers_persisted(tmp_path, monkeypatch):
    up = tmp_path / "up"; up.mkdir()
    monkeypatch.setattr(cs, "UPLOAD_DIR", up)
    f = up / "abc.pdf"; f.write_bytes(b"PERSISTED")
    tpl = _Tpl(path="data/capitolato_uploads/abc.pdf", name="whatever.pdf")
    # resolve uses UPLOAD_DIR-relative; write a real file resolvable from the rel path
    # (the function resolves rel_path relative to CWD; for the unit test we point path at the tmp file)
    monkeypatch.setattr(cs, "_resolve_persisted", lambda p: f if p.endswith("abc.pdf") else None, raising=False)
    res = cs.resolve_capitolato_source(tpl)
    assert res is not None
    assert res[0] == b"PERSISTED"


def test_resolve_none_when_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "UPLOAD_DIR", tmp_path / "nope")
    tpl = _Tpl(path=None, name="does-not-exist-xyz.pdf")
    assert cs.resolve_capitolato_source(tpl) is None
```

> NOTE implementer: design `resolve_capitolato_source` so the persisted branch is testable. Simplest: read via `read_capitolato_text`-style path resolution but return raw bytes — factor a small `_read_persisted_bytes(rel_path) -> bytes|None` (applies the same guard, returns None if missing/outside) and a corpus branch checking `docs/capitolati_esempio/<name>`. Adjust the test to your final factoring if needed, but keep: persisted-wins, corpus-fallback, None-when-neither, and the path-traversal guard on the persisted branch.

- [ ] **Step 2: Run → fail** (`ImportError: resolve_capitolato_source`).

- [ ] **Step 3: Implement** `resolve_capitolato_source` + any `_read_persisted_bytes` helper in `capitolato_storage.py`, reusing the existing guard logic from `read_capitolato_text`. Corpus path: `Path("docs/capitolati_esempio")/name` with an `is_file()` check and a `.relative_to` guard (mirror the existing `ai-extract` guard).

- [ ] **Step 4: Run** `.venv/Scripts/python.exe -m pytest tests/test_capitolato_storage.py -v` + full suite.

- [ ] **Step 5: Commit** — Subject: `feat(items): resolve_capitolato_source (persisted-or-corpus)`.

---

## Task 3: `ai-extract` uses resolver + strong provider

**Files:**
- Modify: `app/routers/delivery_items.py` (`ai_extract_items`, ~line 1161)
- Test: `tests/test_item_parser_robust.py` (append endpoint test) — optional if heavy; at minimum keep full suite green.

**Interfaces:**
- Consumes: `resolve_capitolato_source`, `pick_parse_provider`.

- [ ] **Step 1: Implement**

Rewrite the body of `ai_extract_items`:
- Replace the corpus-only file read (the `docs/capitolati_esempio` block + `source_document_name` 400 guard) with `src = resolve_capitolato_source(tpl)`; if `src is None` → `raise HTTPException(404, "Nessun documento sorgente disponibile (caricato o nel corpus).")`. `content, fname = src`.
- Replace `provider = get_provider_for_user(...) or get_provider()` with `picked = pick_parse_provider(user.id if user else None, db); if not picked: raise HTTPException(503, ...); provider = picked[0]`.
- Keep `extract_text_from_file(content, fname)`, `parse_delivery_items_v2(...)`, `materialize_items(...)`, and the response shape (add `parse_meta` from parsed if present).

- [ ] **Step 2: Test** — Add an endpoint test (use the `client_admin` StaticPool pattern from `tests/test_delivery_templates_parse_api.py`): create a template with a persisted `source_document_path` (monkeypatch `cs.UPLOAD_DIR` + write a file), monkeypatch `pick_parse_provider` and `parse_delivery_items_v2` to return a fixed item, POST `ai-extract`, assert 200 + `saved >= 1`. If the fixture wiring proves heavy, assert at least that the endpoint no longer 400s on a UI-uploaded template (the core fix). Run full suite.

- [ ] **Step 3: Commit** — Subject: `feat(items): ai-extract resolves persisted source + strong model`.

---

## Task 4: Auto-extract items after `/api/save` (best-effort) + bump

**Files:**
- Modify: `app/routers/delivery_templates.py` (`save_template`, insert before `return _dt_dict(t)` ~line 1033)
- Modify: `app/main.py` (version), `CHANGELOG.md`, `docs/STATO.md`
- Test: `tests/test_delivery_templates_parse_api.py` (append)

**Interfaces:**
- `/api/save` response gains `items_extracted: int` and `items_warning: str|None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_delivery_templates_parse_api.py  (append)
def test_save_autoextract_items(client_admin, monkeypatch):
    import app.services.capitolato_storage as cs
    import app.services.delivery_items_parser as dip
    import app.services.ai_provider as ai
    monkeypatch.setattr(ai, "pick_parse_provider", lambda uid, db: (object(), "strong", "claude-sonnet-4-6"))
    monkeypatch.setattr(cs, "resolve_capitolato_source", lambda t: (b"x", "x.pdf"))
    monkeypatch.setattr(dip, "parse_delivery_items_v2",
                        lambda text, db, tenant_id=1, provider=None: {"items": [{"name": "I1"}]})
    monkeypatch.setattr(dip, "materialize_items", lambda db, tid, parsed, tenant_id=1: (1, 0))
    monkeypatch.setattr("app.services.deliverables_parser.extract_text_from_file", lambda b, fn: "capitolato text " * 20)
    r = client_admin.post("/delivery-templates/api/save", data={
        "code": "AUTOX", "name": "Auto X", "version": "1.0",
        "source_document_path": "data/capitolato_uploads/x.pdf"})
    assert r.status_code in (200, 201), r.text
    assert r.json().get("items_extracted") == 1


def test_save_autoextract_best_effort(client_admin, monkeypatch):
    import app.services.capitolato_storage as cs
    import app.services.ai_provider as ai
    monkeypatch.setattr(ai, "pick_parse_provider", lambda uid, db: (object(), "strong", "m"))
    def _boom(t): raise RuntimeError("extract boom")
    monkeypatch.setattr(cs, "resolve_capitolato_source", _boom)
    r = client_admin.post("/delivery-templates/api/save", data={
        "code": "AUTOX2", "name": "Auto X2", "version": "1.0",
        "source_document_path": "data/capitolato_uploads/y.pdf"})
    assert r.status_code in (200, 201), r.text   # save still succeeds
    assert r.json().get("items_warning")          # warning present
```

- [ ] **Step 2: Run → fail** (no `items_extracted` / `items_warning`).

- [ ] **Step 3: Implement**

In `save_template`, after `db.refresh(t)` and before `return _dt_dict(t)`:

```python
    result = _dt_dict(t)
    result["items_extracted"] = 0
    result["items_warning"] = None
    if t.source_document_path:
        try:
            from app.services.capitolato_storage import resolve_capitolato_source
            from app.services.ai_provider import pick_parse_provider
            from app.services.deliverables_parser import extract_text_from_file
            from app.services.delivery_items_parser import parse_delivery_items_v2, materialize_items
            src = resolve_capitolato_source(t)
            picked = pick_parse_provider(<current_user_id>, db)
            if src and picked:
                content, fname = src
                text = extract_text_from_file(content, fname)
                parsed = parse_delivery_items_v2(text, db, tenant_id=current_tenant_id(), provider=picked[0])
                if parsed:
                    saved, _sk = materialize_items(db, t.id, parsed, tenant_id=current_tenant_id())
                    db.commit()
                    result["items_extracted"] = saved
            else:
                result["items_warning"] = "auto-extract skipped (no source/provider)"
        except Exception as e:
            logger.warning("auto-extract items failed for template %s: %s", t.id, e)
            result["items_warning"] = "estrazione item fallita (riprova con Ri-analizza)"
    return result
```

Resolve `<current_user_id>`: read how `save_template` accesses the current user (it has `request: Request`; use `current_user_optional(request)` like the other endpoints — import it). Ensure `logger` exists in the module (it does — verify). The auto-extract `db.commit()` only commits the new items (the template was already committed above).

- [ ] **Step 4: Run** new tests + FULL suite.

- [ ] **Step 5: Bump + changelog + STATO**

Bump `app/main.py` version → `3.5.0-alpha.172.229`. Add CHANGELOG entry + STATO update (item-parser robusto + auto-extract; Paramount item-list fix). 

- [ ] **Step 6: Commit** — Subject: `feat(items): auto-extract after save (best-effort) + bump v3.5.0-alpha.172.229`.

---

## Self-Review notes
- Spec A→Task1, B→Task2, C→Task3, D→Task4. Migration: none (delivery_items table exists). All covered.
- `parse_meta` (items) is diagnostic only; `_merge_items_by_name` dedupes PASS1 across chunks; PASS2 stays single. Names consistent across tasks.
- Best-effort guarantee tested explicitly (test_save_autoextract_best_effort).
