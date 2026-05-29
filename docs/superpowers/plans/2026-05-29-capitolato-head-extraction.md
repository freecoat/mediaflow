# Capitolato Head Extraction (vision) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Estrarre da ogni capitolato (vision su PDF, testo su docx/xlsx/txt) TC start / timeline-testa / codici audio-config con mappatura tracce, e popolare i `default_*` del DeliveryTemplate + gli `AudioConfigPreset`, con preview→apply per-template e batch sui 13.

**Architecture:** Servizio puro `capitolato_head_extractor` (render documento → estrazione LLM → apply idempotente), 2 endpoint (extract preview / apply), bottone UI con preview card, script batch. Riusa `get_provider_for_user`, `extract_text_from_file`, `apply_audio_config_preset`, modelli α.172.127.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + PyMuPDF (`fitz`, nuovo) + Claude vision via `provider.chat` (blocchi Anthropic-canonici `{type:image,source:{media_type,data}}`). Test: pytest (`db`, `tenant_id`).

**Spec:** `docs/superpowers/specs/2026-05-29-capitolato-head-extraction-design.md`

---

## File Structure

| File | Responsabilità | Azione |
|------|----------------|--------|
| `requirements.txt` | aggiungere `PyMuPDF` | Modify |
| `app/services/capitolato_head_extractor.py` | render doc + prompt + extract + apply_head_specs | Create |
| `app/routers/delivery_items.py` | endpoint extract-head / apply-head + source resolver | Modify |
| `app/templates/pages/delivery_templates.html` | bottone + preview card + apply | Modify |
| `scripts/extract_head_specs_batch.py` | batch sui capitolati + report | Create |
| `tests/test_head_extractor_render.py` | render mode selection | Create |
| `tests/test_head_extractor_apply.py` | apply_head_specs idempotenza + TC norm | Create |

---

## Task 1: Dipendenza PyMuPDF + render documento

**Files:**
- Modify: `requirements.txt`
- Create: `app/services/capitolato_head_extractor.py`
- Test: `tests/test_head_extractor_render.py`

- [ ] **Step 1: Add dependency + install**

Append to `requirements.txt` (new line): `PyMuPDF>=1.24`
Run: `.venv/Scripts/python.exe -m pip install "PyMuPDF>=1.24"`
Expected: installs `fitz`. Verify: `.venv/Scripts/python.exe -c "import fitz; print('fitz OK')"` → `fitz OK`.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_head_extractor_render.py
import io
from app.services.capitolato_head_extractor import render_document_for_llm


def _tiny_pdf_bytes() -> bytes:
    import fitz
    doc = fitz.open()
    doc.new_page(); doc.new_page()
    b = doc.tobytes()
    doc.close()
    return b


def test_render_pdf_uses_vision():
    out = render_document_for_llm(_tiny_pdf_bytes(), "RAI.pdf")
    assert out["mode"] == "vision"
    assert out["page_count"] == 2
    assert len(out["images"]) == 2
    assert isinstance(out["images"][0], (bytes, bytearray))


def test_render_txt_uses_text():
    out = render_document_for_llm(b"Barre e toni. TC 00:59:59:00", "spec.txt")
    assert out["mode"] == "text"
    assert "00:59:59:00" in out["text"]


def test_render_docx_uses_text(tmp_path):
    # docx path: extract_text_from_file handles it; a non-pdf extension → text mode
    out = render_document_for_llm(b"dummy", "spec.docx")
    assert out["mode"] == "text"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_head_extractor_render.py -v`
Expected: FAIL — module/function missing.

- [ ] **Step 4: Implement render_document_for_llm**

Create `app/services/capitolato_head_extractor.py`:

```python
"""v3.5.0-alpha.172.128 — Estrazione head-specs (TC/timeline/audio-config) dai
capitolati. PDF → vision (PyMuPDF page images); docx/xlsx/txt → testo.
Vedi docs/superpowers/specs/2026-05-28... e ...-capitolato-head-extraction-design.md.
"""
from __future__ import annotations
import base64
import logging
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PAGE_CAP = 60          # cap di sicurezza: oltre logga warning (no silent truncation)
RENDER_DPI = 150


def render_document_for_llm(file_bytes: bytes, filename: str) -> dict:
    """Rende un capitolato per il consumo LLM.
    PDF → {mode:'vision', images:[png bytes], page_count}. Altro → {mode:'text', text}.
    """
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext == "pdf":
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = doc.page_count
        if page_count > PAGE_CAP:
            logger.warning(
                "[head-extractor] %s ha %d pagine (> cap %d): tutte renderizzate, costo vision elevato.",
                filename, page_count, PAGE_CAP,
            )
        zoom = RENDER_DPI / 72.0
        mat = fitz.Matrix(zoom, zoom)
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=mat)
            images.append(pix.tobytes("png"))
        doc.close()
        return {"mode": "vision", "images": images, "page_count": page_count}
    # docx/xlsx/txt/doc → testo
    from app.services.deliverables_parser import extract_text_from_file
    text = extract_text_from_file(file_bytes, filename)
    return {"mode": "text", "text": text or ""}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_head_extractor_render.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt app/services/capitolato_head_extractor.py tests/test_head_extractor_render.py
git commit -m "feat(head-extractor): PyMuPDF render document for LLM (vision/text)"
```

---

## Task 2: Prompt builder + extract_head_specs

**Files:**
- Modify: `app/services/capitolato_head_extractor.py`
- Test: `tests/test_head_extractor_apply.py` (prompt/parse part)

**Context:** `extract_head_specs` chiama l'LLM (non deterministico) → testiamo deterministicamente solo (a) il builder del vocabolario taxonomy, (b) il parsing della risposta. La chiamata vera è validata manualmente (Task 6).

- [ ] **Step 1: Write the failing test (vocab + parse helpers)**

```python
# tests/test_head_extractor_apply.py  (parte 1)
from app.services.capitolato_head_extractor import _taxonomy_vocab, _parse_head_json


def test_taxonomy_vocab_lists_names(db, tenant_id):
    from app.models.models import AudioChannelConfig, AudioMixType
    db.add(AudioChannelConfig(tenant_id=None, name="5.1", channel_count=6))
    db.add(AudioMixType(tenant_id=None, name="M&E"))
    db.flush()
    v = _taxonomy_vocab(db, tenant_id)
    assert "5.1" in v["channel_config"]
    assert "M&E" in v["mix_type"]
    assert "codec" in v and "mix_standard" in v


def test_parse_head_json_tolerant():
    raw = '```json\n{"default_tc_start":"00:59:59:00","timeline_segments":[],"audio_config_codes":[]}\n```'
    d = _parse_head_json(raw)
    assert d["default_tc_start"] == "00:59:59:00"
    assert d["audio_config_codes"] == []


def test_parse_head_json_garbage_returns_empty():
    d = _parse_head_json("non sono json")
    assert d == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_head_extractor_apply.py -v -k "vocab or parse"`
Expected: FAIL — helpers missing.

- [ ] **Step 3: Implement vocab + parse + extract_head_specs**

Append to `capitolato_head_extractor.py`:

```python
from app.models.models import (
    AudioChannelConfig, AudioMixType, MixStandard, AudioCodec,
)

_SYS_PROMPT = (
    "Sei un estrattore tecnico di capitolati di post-produzione audiovisiva. "
    "Estrai SOLO: testa/coda del file (barre, toni, slate, counter, nero, loghi, "
    "titoli, code), timecode di partenza e di programma, e configurazione audio. "
    "I codici audio d'emittente (es. RAI 8T07, 16T09) mappano configurazioni "
    "standard tramite TABELLE con SIGLE spiegate in una LEGENDA: leggi sia la "
    "tabella sia la legenda e fai il cross-reference, espandendo ogni sigla. "
    "Mappa i termini ai NOMI CANONICI forniti quando possibile; se un termine non "
    "esiste fra i canonici, usalo grezzo ed elencalo in suggested_taxonomy. "
    "Timecode in formato HH:MM:SS:FF; se il documento dà prosa, estrai il TC e "
    "metti il resto in notes. Ciò che non riesci a strutturare va in source_notes. "
    "Rispondi SOLO con JSON valido, nessun altro testo."
)


def _taxonomy_vocab(db: Session, tenant_id: int) -> dict:
    """Nomi canonici attivi per il mapping (globali + del tenant)."""
    def names(Model):
        rows = db.query(Model.name).filter(
            (Model.tenant_id == tenant_id) | (Model.tenant_id.is_(None)),
            Model.is_active == True,  # noqa: E712
        ).all()
        return sorted({r[0] for r in rows})
    return {
        "channel_config": names(AudioChannelConfig),
        "mix_type": names(AudioMixType),
        "mix_standard": names(MixStandard),
        "codec": names(AudioCodec),
    }


def _parse_head_json(raw: str) -> dict:
    """Parsing tollerante (riusa il safe-json del progetto)."""
    from app.services.ai_provider import safe_json_parse
    try:
        out = safe_json_parse(raw)
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def _user_prompt(broadcaster: str, vocab: dict, text: Optional[str] = None) -> str:
    schema = (
        '{"default_tc_start":"HH:MM:SS:FF|null","default_program_start":"HH:MM:SS:FF|null",'
        '"timeline_segments":[{"order":1,"kind":"bars_tone|slate|countdown|counter|black|program|textless|logo|main_titles|tail|other","label":"","tc_in":"","tc_out":"","duration":"","reel":null,"source":null,"notes":""}],'
        '"audio_config_codes":[{"code":"","name":"","description":"","tracks":[{"track_label":"","channel_config":"","mix_type":"","mix_standard":"","codec":"","sample_rate":48000,"bit_depth":24}]}],'
        '"suggested_taxonomy":[{"kind":"mix_type|channel_config|mix_standard|codec","name":"","seen_as":""}],'
        '"confidence":0.0,"source_notes":""}'
    )
    parts = [
        f"Capitolato: {broadcaster}.",
        "NOMI CANONICI taxonomy (mappa a questi quando possibile):",
        f"  channel_config: {vocab['channel_config']}",
        f"  mix_type: {vocab['mix_type']}",
        f"  mix_standard: {vocab['mix_standard']}",
        f"  codec: {vocab['codec']}",
        "Estrai ESATTAMENTE questo JSON (leggi tabelle audio riga-per-riga + legenda):",
        schema,
    ]
    if text is not None:
        parts.append("\nTESTO DOCUMENTO:\n" + text)
    return "\n".join(parts)


def extract_head_specs(provider, rendered: dict, broadcaster: str,
                       db: Session, tenant_id: int, max_tokens: int = 12000) -> dict:
    """Chiama l'LLM (vision o testo) e ritorna il dict del contratto. No write."""
    vocab = _taxonomy_vocab(db, tenant_id)
    if rendered.get("mode") == "vision":
        content = [{"type": "text", "text": _user_prompt(broadcaster, vocab)}]
        for png in rendered.get("images", []):
            content.append({
                "type": "image",
                "source": {"media_type": "image/png",
                           "data": base64.b64encode(png).decode("ascii")},
            })
        raw = provider.chat([{"role": "user", "content": content}],
                            system=_SYS_PROMPT, max_tokens=max_tokens, temperature=0.1)
    else:
        user = _user_prompt(broadcaster, vocab, text=(rendered.get("text") or "")[:120000])
        raw = provider.complete(_SYS_PROMPT, user, max_tokens=max_tokens, temperature=0.1)
    return _parse_head_json(raw)
```

VERIFY before relying on it: confirm `safe_json_parse` exists in `app/services/ai_provider.py` (grep it). If the real name differs, use the real one. Confirm `provider.chat` image-block shape by reading `app/services/ai_provider.py` lines ~36-60 and ~393 — the canonical block is `{"type":"image","source":{"media_type":...,"data":<base64>}}`. If the ClaudeProvider expects `source.type="base64"` too, add `"type":"base64"` into the source dict.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_head_extractor_apply.py -v -k "vocab or parse"`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/capitolato_head_extractor.py tests/test_head_extractor_apply.py
git commit -m "feat(head-extractor): taxonomy-vocab prompt + extract_head_specs (vision/text)"
```

---

## Task 3: apply_head_specs idempotente

**Files:**
- Modify: `app/services/capitolato_head_extractor.py`
- Test: `tests/test_head_extractor_apply.py` (apply part)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_head_extractor_apply.py  (parte 2 — append)
from app.services.capitolato_head_extractor import apply_head_specs


def _tpl(db, tenant_id, code="RAI-AP"):
    from app.models.models import DeliveryTemplate
    t = DeliveryTemplate(tenant_id=tenant_id, code=code, name=code)
    db.add(t); db.flush()
    return t


def test_apply_sets_defaults_and_creates_presets(db, tenant_id):
    from app.models.models import AudioConfigPreset
    t = _tpl(db, tenant_id)
    parsed = {
        "default_tc_start": "00:59:59:00", "default_program_start": "01:00:00:00",
        "timeline_segments": [{"order": 1, "kind": "bars_tone", "label": "barre"}],
        "audio_config_codes": [
            {"code": "8T07", "name": "8 tracce", "tracks": [{"track_label": "T1", "channel_config": "5.1"}]},
        ],
        "suggested_taxonomy": [{"kind": "mix_type", "name": "Audiodescrizione", "seen_as": "AD"}],
    }
    out = apply_head_specs(db, t.id, parsed, tenant_id)
    db.flush()
    db.refresh(t)
    assert t.default_tc_start == "00:59:59:00"
    assert t.default_program_start == "01:00:00:00"
    assert t.default_timeline_segments[0]["kind"] == "bars_tone"
    p = db.query(AudioConfigPreset).filter(
        AudioConfigPreset.delivery_template_id == t.id, AudioConfigPreset.code == "8T07").first()
    assert p is not None and p.track_layout[0]["channel_config"] == "5.1"
    assert out["presets_created"] == 1
    assert out["suggested_taxonomy"] == parsed["suggested_taxonomy"]


def test_apply_is_idempotent_upsert(db, tenant_id):
    from app.models.models import AudioConfigPreset
    t = _tpl(db, tenant_id, code="RAI-AP2")
    parsed = {"audio_config_codes": [{"code": "8T07", "name": "v1", "tracks": []}]}
    apply_head_specs(db, t.id, parsed, tenant_id); db.flush()
    parsed["audio_config_codes"][0]["name"] = "v2"
    out = apply_head_specs(db, t.id, parsed, tenant_id); db.flush()
    presets = db.query(AudioConfigPreset).filter(
        AudioConfigPreset.delivery_template_id == t.id, AudioConfigPreset.code == "8T07").all()
    assert len(presets) == 1                 # niente duplicati
    assert presets[0].name == "v2"           # aggiornato
    assert out["presets_updated"] == 1 and out["presets_created"] == 0


def test_apply_empty_preview_does_not_wipe(db, tenant_id):
    t = _tpl(db, tenant_id, code="RAI-AP3")
    t.default_tc_start = "00:59:59:00"; db.flush()
    apply_head_specs(db, t.id, {"default_tc_start": None, "timeline_segments": [], "audio_config_codes": []}, tenant_id)
    db.flush(); db.refresh(t)
    assert t.default_tc_start == "00:59:59:00"  # non azzerato da preview vuota
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_head_extractor_apply.py -v -k "apply"`
Expected: FAIL — `apply_head_specs` missing.

- [ ] **Step 3: Implement apply_head_specs**

Append to `capitolato_head_extractor.py`:

```python
import re as _re
_TC_RE = _re.compile(r"\b(\d{1,2}:\d{2}:\d{2}[:;.]\d{2})\b")


def _clean_tc(raw):
    if not raw:
        return None
    m = _TC_RE.search(str(raw))
    return m.group(1) if m else None


def apply_head_specs(db: Session, template_id: int, parsed: dict, tenant_id: int) -> dict:
    """Idempotente. Setta i default_* del template SOLO se presenti nella preview
    (preview vuota non azzera) e fa upsert degli AudioConfigPreset per (template, code).
    NON crea voci taxonomy. Ritorna riepilogo. NON committa (il caller decide)."""
    from app.models.models import DeliveryTemplate, AudioConfigPreset
    tpl = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == template_id,
        DeliveryTemplate.tenant_id == tenant_id).first()
    if not tpl:
        raise ValueError("template non trovato")

    tc = _clean_tc(parsed.get("default_tc_start"))
    pg = _clean_tc(parsed.get("default_program_start"))
    segs = parsed.get("timeline_segments") or []
    tc_set = pg_set = False
    if tc:
        tpl.default_tc_start = tc; tc_set = True
    if pg:
        tpl.default_program_start = pg; pg_set = True
    if segs:
        tpl.default_timeline_segments = segs

    created = updated = 0
    for code_def in parsed.get("audio_config_codes") or []:
        code = (code_def.get("code") or "").strip()
        if not code:
            continue
        preset = db.query(AudioConfigPreset).filter(
            AudioConfigPreset.delivery_template_id == template_id,
            AudioConfigPreset.code == code).first()
        if preset:
            preset.name = code_def.get("name") or preset.name
            preset.description = code_def.get("description") or preset.description
            preset.track_layout = code_def.get("tracks") or preset.track_layout
            updated += 1
        else:
            db.add(AudioConfigPreset(
                tenant_id=tenant_id, delivery_template_id=template_id,
                code=code, name=code_def.get("name") or code,
                description=code_def.get("description"),
                track_layout=code_def.get("tracks") or [],
            ))
            created += 1
    return {
        "tc_set": tc_set, "program_set": pg_set,
        "segments_n": len(segs),
        "presets_created": created, "presets_updated": updated,
        "suggested_taxonomy": parsed.get("suggested_taxonomy") or [],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_head_extractor_apply.py -v`
Expected: PASS (all: vocab + parse + 3 apply).

- [ ] **Step 5: Commit**

```bash
git add app/services/capitolato_head_extractor.py tests/test_head_extractor_apply.py
git commit -m "feat(head-extractor): apply_head_specs idempotent upsert (clean TC, no-wipe)"
```

---

## Task 4: Endpoint extract-head / apply-head

**Files:**
- Modify: `app/routers/delivery_items.py` (append + a source-resolver helper)

- [ ] **Step 1: Reconnaissance**
Read `app/routers/delivery_items.py`: confirm imports (`current_tenant_id`, `RequireEdit`, `HTTPException`, `Form`, `Depends`, `get_db`, `Request`). Read how an existing endpoint gets the current user (for `get_provider_for_user`) — search `current_user_optional` / how `revalidate_item_ai` obtains the user + provider (it already calls an AI provider). Reuse that exact idiom.

- [ ] **Step 2: Implement source resolver + endpoints (append at end of file)**

```python
# ── Head extraction (v3.5.0-alpha.172.128) ────────────────────
def _resolve_capitolato_path(tpl):
    """Trova il file sorgente del capitolato: source_document_path se esiste,
    altrimenti per nome in docs/capitolati_esempio/. Ritorna Path o None."""
    from pathlib import Path as _P
    if tpl.source_document_path:
        p = _P(tpl.source_document_path)
        if p.is_file():
            return p
    if tpl.source_document_name:
        cand = _P("docs/capitolati_esempio") / tpl.source_document_name
        if cand.is_file():
            return cand
    return None


@router.post("/delivery-templates/api/{tid}/extract-head", dependencies=[RequireEdit])
async def extract_head(tid: int, request: Request, db: Session = Depends(get_db)):
    from app.models.models import DeliveryTemplate
    from app.services.ai_provider import get_provider_for_user
    from app.services.capitolato_head_extractor import (
        render_document_for_llm, extract_head_specs,
    )
    tpl = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == tid,
        DeliveryTemplate.tenant_id == current_tenant_id()).first()
    if not tpl:
        raise HTTPException(404, "DeliveryTemplate non trovato")
    path = _resolve_capitolato_path(tpl)
    if not path:
        raise HTTPException(400, "Capitolato sorgente non trovato (source_document_name/path).")
    user = current_user_optional(request, db)
    provider = get_provider_for_user(user.id if user else None, db)
    if not provider:
        raise HTTPException(400, "Nessun provider AI configurato per l'utente.")
    rendered = render_document_for_llm(path.read_bytes(), path.name)
    parsed = extract_head_specs(provider, rendered, tpl.broadcaster or tpl.code, db, current_tenant_id())
    return {"template_id": tid, "mode": rendered.get("mode"),
            "page_count": rendered.get("page_count"), "preview": parsed}


@router.post("/delivery-templates/api/{tid}/apply-head", dependencies=[RequireEdit])
async def apply_head(tid: int, payload_json: str = Form(...),
                     request: Request = None, db: Session = Depends(get_db)):
    from app.services.capitolato_head_extractor import apply_head_specs
    parsed = json.loads(payload_json)
    summary = apply_head_specs(db, tid, parsed, current_tenant_id())
    # audit AIAction (pattern progetto)
    try:
        from app.models.models import AIAction
        db.add(AIAction(tenant_id=current_tenant_id(), capability="extract_head_specs",
                        status="applied", payload=json.dumps({"template_id": tid, "summary": summary})[:4000]))
    except Exception:
        pass
    db.commit()
    return summary
```

VERIFY: read the `AIAction` model fields before using it (column names may differ — `capability`/`status`/`payload`/`tenant_id`). Adapt to the real schema; if it doesn't fit cleanly, drop the AIAction logging (it's best-effort audit, wrapped in try/except). Confirm `current_user_optional` import exists at top of file (it's imported: `from app.services.rbac import requires_permission, current_user_optional`).

- [ ] **Step 3: Verify import + smoke**

Run: `.venv/Scripts/python.exe -c "from app.main import app; print('OK')"`
Then (server-independent) confirm route registered:
```bash
.venv/Scripts/python.exe -c "from app.main import app; print([r.path for r in app.routes if 'extract-head' in r.path or 'apply-head' in r.path])"
```
Expected: both paths listed.

- [ ] **Step 4: Commit**

```bash
git add app/routers/delivery_items.py
git commit -m "feat(api): extract-head (preview) + apply-head endpoints"
```

---

## Task 5: UI — bottone + preview card + apply

**Files:**
- Modify: `app/templates/pages/delivery_templates.html`

- [ ] **Step 1: Reconnaissance**
Find the template-edit modal and the existing "🤖 Estrai items" button (search `ai-extract` / `Estrai items`). Note: the function that opens the template modal, the helpers `api()`/`escapeHtml()`/`toast()`, and the template id variable in scope.

- [ ] **Step 2: Add button + handlers**
Near the "🤖 Estrai items" button add:
```html
<button type="button" class="btn btn-secondary btn-sm" onclick="extractHeadSpecs()">🤖 Estrai TC/Timeline/Audio</button>
<div id="head-preview" style="display:none;margin-top:12px;"></div>
```
Add JS (top-level functions; `_headTemplateId` set when opening the template modal, or read from the existing template-id variable):
```javascript
async function extractHeadSpecs() {
  const tid = _headTemplateId || window._currentTemplateId;
  if (!tid) { toast('Nessun template attivo', 'warning'); return; }
  const box = document.getElementById('head-preview');
  box.style.display = 'block';
  box.innerHTML = '<div class="text-muted">⏳ Estrazione in corso (vision)…</div>';
  let r;
  try { r = await fetch(`/delivery-templates/api/${tid}/extract-head`, {method:'POST', credentials:'same-origin'}); }
  catch(e) { box.innerHTML = '<div class="text-danger">Errore rete</div>'; return; }
  if (!r.ok) { box.innerHTML = `<div class="text-danger">Errore ${r.status}</div>`; return; }
  const data = await r.json();
  window._headPreview = data.preview;
  renderHeadPreview(data);
}

function renderHeadPreview(data) {
  const p = data.preview || {};
  const segs = (p.timeline_segments||[]).map(s => `<li>${escapeHtml(s.kind||'')} — ${escapeHtml(s.label||'')} ${escapeHtml(s.tc_in||'')}</li>`).join('');
  const presets = (p.audio_config_codes||[]).map(c =>
    `<div><strong>${escapeHtml(c.code||'')}</strong> — ${escapeHtml(c.name||'')} (${(c.tracks||[]).length} tracce)</div>`).join('');
  const sugg = (p.suggested_taxonomy||[]).map(s => `<li>${escapeHtml(s.kind||'')}: ${escapeHtml(s.name||'')} (visto come "${escapeHtml(s.seen_as||'')}")</li>`).join('');
  const box = document.getElementById('head-preview');
  box.innerHTML = `
    <div style="border:1px solid var(--border);border-radius:8px;padding:12px;">
      <div>TC start: <strong>${escapeHtml(p.default_tc_start||'—')}</strong> · Program: <strong>${escapeHtml(p.default_program_start||'—')}</strong> · ${data.mode==='vision'?('vision '+(data.page_count||'')+'pp'):'testo'}</div>
      <div style="margin-top:6px;">Timeline:<ul>${segs||'<li>—</li>'}</ul></div>
      <div>Audio config:${presets||' —'}</div>
      ${sugg?`<div style="margin-top:6px;color:#fbbf24;">Taxonomy da aggiungere a mano (<a href="/settings/delivery-taxonomy">apri</a>):<ul>${sugg}</ul></div>`:''}
      <div style="margin-top:10px;">
        <button class="btn btn-primary btn-sm" onclick="applyHeadSpecs()">Applica</button>
        <button class="btn btn-ghost btn-sm" onclick="document.getElementById('head-preview').style.display='none'">Annulla</button>
      </div>
    </div>`;
}

async function applyHeadSpecs() {
  const tid = _headTemplateId || window._currentTemplateId;
  const fd = new FormData();
  fd.append('payload_json', JSON.stringify(window._headPreview||{}));
  const r = await fetch(`/delivery-templates/api/${tid}/apply-head`, {method:'POST', body:fd, credentials:'same-origin'});
  if (!r.ok) { toast('Errore apply', 'error'); return; }
  const s = await r.json();
  toast(`Applicato: ${s.presets_created} preset creati, ${s.presets_updated} aggiornati`, 'success');
  document.getElementById('head-preview').style.display='none';
}
```
Set `_headTemplateId` where the template modal opens (reuse the existing template-id variable; if the page already tracks `_currentTemplate`/`_currentTemplateId`, use it and skip introducing a new one). NO JSON.stringify in onclick (the stringify above is in function bodies — OK). escapeHtml on all dynamic values.

- [ ] **Step 3: Verify**
```bash
.venv/Scripts/python.exe -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('pages/delivery_templates.html'); print('jinja OK')"
grep -n "extractHeadSpecs\|renderHeadPreview\|applyHeadSpecs" app/templates/pages/delivery_templates.html
```
Expected: jinja OK; each function defined once + referenced.

- [ ] **Step 4: Commit**
```bash
git add app/templates/pages/delivery_templates.html
git commit -m "feat(ui): Estrai TC/Timeline/Audio button + preview/apply card"
```

---

## Task 6: Batch script + eval RAI (table+legend verification)

**Files:**
- Create: `scripts/extract_head_specs_batch.py`

- [ ] **Step 1: Implement batch**

```python
# scripts/extract_head_specs_batch.py
"""v3.5.0-alpha.172.128 — Batch estrazione head-specs sui capitolati attivi.
Uso:
  .venv/Scripts/python.exe scripts/extract_head_specs_batch.py --dry-run
  .venv/Scripts/python.exe scripts/extract_head_specs_batch.py --only RAI-SDHDUHD-1.4
  .venv/Scripts/python.exe scripts/extract_head_specs_batch.py            # applica a tutti
"""
from __future__ import annotations
import sys, json, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models.models import DeliveryTemplate
from app.services.ai_provider import get_provider_for_user
from app.services.capitolato_head_extractor import (
    render_document_for_llm, extract_head_specs, apply_head_specs,
)
from app.routers.delivery_items import _resolve_capitolato_path
from app.context import current_tenant_id


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None, help="CSV di code template")
    ap.add_argument("--user-id", type=int, default=1)
    args = ap.parse_args()

    db = SessionLocal()
    tid = 1
    provider = get_provider_for_user(args.user_id, db)
    if not provider:
        print("[ERR] nessun provider AI per user", args.user_id); return 1
    only = set(args.only.split(",")) if args.only else None
    q = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.tenant_id == tid,
        DeliveryTemplate.is_active == True)  # noqa: E712
    print(f"{'CODE':32} {'mode':7} {'tc':12} {'segs':>4} {'presets':>8} {'sugg':>4}")
    for t in q.all():
        if only and t.code not in only:
            continue
        path = _resolve_capitolato_path(t)
        if not path:
            print(f"{t.code:32} SKIP (no source)"); continue
        rendered = render_document_for_llm(path.read_bytes(), path.name)
        parsed = extract_head_specs(provider, rendered, t.broadcaster or t.code, db, tid)
        if args.dry_run:
            print(f"{t.code:32} {rendered.get('mode'):7} {str(parsed.get('default_tc_start')):12} "
                  f"{len(parsed.get('timeline_segments') or []):>4} {len(parsed.get('audio_config_codes') or []):>8} "
                  f"{len(parsed.get('suggested_taxonomy') or []):>4}")
            print("   PREVIEW:", json.dumps(parsed, ensure_ascii=False)[:500])
        else:
            s = apply_head_specs(db, t.id, parsed, tid)
            db.commit()
            print(f"{t.code:32} {rendered.get('mode'):7} {str(parsed.get('default_tc_start')):12} "
                  f"{s['segments_n']:>4} {s['presets_created']+s['presets_updated']:>8} {len(s['suggested_taxonomy']):>4}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Snapshot DB**
```bash
.venv/Scripts/python.exe -c "import shutil; shutil.copy('mediaflow.db','db_snapshots/snapshot-pre-head-extraction.db'); print('snapshot OK')"
```

- [ ] **Step 3: Eval RAI dry-run (manual table+legend verification)**
```bash
.venv/Scripts/python.exe scripts/extract_head_specs_batch.py --dry-run --only RAI-SDHDUHD-1.4
```
Expected: stampa preview RAI con 8T07/16T09 e tracce espanse. **VERIFICA MANUALE OBBLIGATORIA**: confronta il track_layout estratto contro la tabella Cap. 10 + legenda del PDF RAI (sigle espanse correttamente: L/R/C/LFE/Ls/Rs, Lt/Rt, M&E, dialoghi, AD). Riporta l'esito a Matteo PRIMA di applicare. Se la mappatura è errata/incompleta, fermarsi e segnalare (BLOCKED) — non applicare dati sbagliati.

- [ ] **Step 4: Commit script (apply al corpus avviene dopo l'OK di Matteo sull'eval)**
```bash
git add scripts/extract_head_specs_batch.py db_snapshots/snapshot-pre-head-extraction.db
git commit -m "feat(batch): extract_head_specs_batch + RAI eval (dry-run)"
```

---

## Task 7: Finalize — version bump + changelog + STATO

**Files:**
- Modify: `app/main.py`, `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: Full test suite**
Run: `.venv/Scripts/python.exe -m pytest tests/ -q 2>&1 | tail -4`
Expected: all pass (existing 66 + new render/apply tests).

- [ ] **Step 2: Bump version**
In `app/main.py` set `version="3.5.0-alpha.172.128"`.

- [ ] **Step 3: CHANGELOG + STATO**
Add a `## v3.5.0-alpha.172.128` entry (vision head extraction: render PyMuPDF, extract_head_specs taxonomy-mapped, apply idempotent, endpoints, UI button, batch). Update `docs/STATO.md` header + section + next step (apply corpus dopo eval RAI; assegnazione code→item manuale; aggiungere voci suggested_taxonomy).

- [ ] **Step 4: Restart server + health**
Kill python + relaunch (zombie-proof avvia_muto pattern) + `curl -s http://localhost:8000/health` → `172.128`.

- [ ] **Step 5: Commit**
```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -m "v3.5.0-alpha.172.128 — capitolato head extraction (vision) pipeline"
```

---

## Self-Review

- **Spec coverage:** E1 render vision/text → Task 1; E2 populate template+preset → Task 3; E3 UI+batch → Task 5+6; E4 suggested_taxonomy no-auto → Task 2 (contract) + Task 3 (apply returns, doesn't create); E5 all pages + cap warning → Task 1; E6 PyMuPDF → Task 1. Table+legend cross-reference → Task 2 (prompt) + Task 6 (eval verification). TC clean → Task 3 (`_clean_tc`). ✓
- **Placeholder scan:** none. Two VERIFY notes (safe_json_parse name, AIAction schema, provider image-block shape) have explicit grep-and-adapt instructions — resolved in-task, not deferred.
- **Type consistency:** `render_document_for_llm`→dict{mode,images|text,page_count}; `extract_head_specs(provider,rendered,broadcaster,db,tenant_id)`; `apply_head_specs(db,template_id,parsed,tenant_id)`→summary; `_resolve_capitolato_path(tpl)`; contract keys (default_tc_start/default_program_start/timeline_segments/audio_config_codes/suggested_taxonomy) consistent across service, endpoint, UI, batch. ✓

## Note di rischio per l'esecutore
- VERIFY `safe_json_parse` real name (memory `feedback_ai_json_lenient`); `provider.chat` image-block exact shape (may need `source.type="base64"`); `AIAction` real columns (drop logging if mismatch).
- Vision cost on large RAI PDF — run RAI dry-run alone first; report token/time.
- Eval RAI table+legend is a HARD GATE before corpus apply (Task 6 Step 3): do not apply wrong audio mappings.
- Restart server after changes (OneDrive breaks reload — α.172.125).
