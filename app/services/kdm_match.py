"""Match engine: richiesta KDM → CPL dei DCP esistenti.

Strategia: UUID esatto (100) → fuzzy su ContentTitleText (60-90)
→ (in router) fuzzy su titolo progetto (40-70). Solo stdlib difflib.
Soglia auto-link configurabile (default 95), tarabile in beta.
"""
from difflib import SequenceMatcher
from app.models import DcpCpl
from app.context import current_tenant_id

AUTO_LINK_THRESHOLD = 95


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def match_request(db, req) -> list[dict]:
    """Ritorna candidati [{dcp_cpl_id, confidence, source, title}] desc."""
    rows = (db.query(DcpCpl)
            .filter(DcpCpl.tenant_id == current_tenant_id(),
                    DcpCpl.is_active == True)  # noqa: E712
            .all())
    out: list[dict] = []
    want_uuid = (req.requested_cpl_uuid or "").strip().lower()
    want_title = (req.requested_title or "").strip()
    for c in rows:
        conf = 0
        source = ""
        if want_uuid and (c.cpl_uuid or "").strip().lower() == want_uuid:
            conf, source = 100, "cpl_uuid"
        elif want_title and c.content_title_text:
            r = _ratio(want_title, c.content_title_text)
            conf = int(round(60 + r * 30)) if r > 0.30 else int(round(r * 60))
            source = "title_fuzzy"
        if conf > 0:
            out.append({"dcp_cpl_id": c.id, "confidence": conf,
                        "source": source, "title": c.content_title_text or ""})
    out.sort(key=lambda d: d["confidence"], reverse=True)
    return out
