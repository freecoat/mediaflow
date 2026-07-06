"""Google Drive API client — Fase D (v3.5.0-alpha.172.243).

Layer HTTP isolato (urllib, coerente con google_calendar.py). Unico
`_drive_request` = punto di mock nei test. Scope: drive.file (vede solo i file
creati/aperti dall'app; un URL incollato mai toccato può dare 403/404 →
metadata None → il router usa un fallback name)."""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Optional

from sqlalchemy.orm import Session

from app.services.oauth_providers import get_valid_access_token

log = logging.getLogger(__name__)

_API_BASE = "https://www.googleapis.com/drive/v3"
_META_FIELDS = "id,name,mimeType,webViewLink,iconLink,owners"

# Varianti URL Drive/Docs/Sheets/Slides
_PATTERNS = [
    re.compile(r"/(?:file|document|spreadsheets|presentation|drawings)/d/([A-Za-z0-9_-]+)"),
    re.compile(r"[?&]id=([A-Za-z0-9_-]+)"),
]


def parse_drive_file_id(url: str) -> Optional[str]:
    if not url:
        return None

    # Path-based patterns (drive.google.com/file/d/ID, docs.google.com/document/d/ID, etc.)
    path_pattern = _PATTERNS[0]
    m = path_pattern.search(url)
    if m:
        return m.group(1)

    # Query-string pattern (?id=ID, &id=ID) — only for Google Drive/Docs hosts
    try:
        netloc = urllib.parse.urlparse(url).netloc
        if netloc.endswith("google.com"):
            id_pattern = _PATTERNS[1]
            m = id_pattern.search(url)
            if m:
                return m.group(1)
    except Exception:
        pass

    return None


def _drive_request(method: str, url: str, token: str, params=None) -> dict:
    """Chiamata HTTP all'API Drive. Ritorna dict JSON (o {} se vuoto).
    Punto unico di mock. Solleva urllib.error.HTTPError su status >=400."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method, headers={
        "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else {}


def fetch_file_metadata(db: Session, user_id: int, file_id: str) -> Optional[dict]:
    """Metadata di un file Drive. Best-effort: token assente/403/404/rete → None."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    try:
        res = _drive_request("GET", _API_BASE + "/files/" + urllib.parse.quote(file_id),
                             token, params={"fields": _META_FIELDS}) or {}
    except Exception as e:
        log.warning(f"fetch_file_metadata fallita file={file_id} user={user_id}: {e}")
        return None
    owners = res.get("owners") or []
    owner_email = owners[0].get("emailAddress") if owners else None
    return {
        "file_id": res.get("id") or file_id,
        "name": res.get("name") or "",
        "mime_type": res.get("mimeType"),
        "web_url": res.get("webViewLink") or "",
        "icon_url": res.get("iconLink"),
        "owner_email": owner_email,
    }
