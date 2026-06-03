"""
Naming helper per JobDeliverable.

Genera il nome file di consegna applicando un template a un set di token
risolti dal contesto (JobDeliverable + Job + Project + Client + DeliveryTemplate).

Riferimenti delle convenzioni implementate:
- ISDCF DCP Naming Convention v9 — https://registry-page.isdcf.com/
- Netflix Picture Archival Folder Structure & File Naming —
  https://partnerhelp.netflixstudios.com/hc/en-us/articles/360000384727

Pattern d'uso:
1. UI in `/jobs/{id}/deliverables` modal: dropdown "Template naming" +
   campo "file_naming" + bottone "📋 Genera da template" → resolve_template().
2. Output preview live mentre l'utente compila i campi (ajax debounced).
3. Save: il `file_naming` finale viene scritto su JobDeliverable.file_naming
   (sempre stringa libera, l'helper è solo assist).

Token sono case-INSENSITIVE in input ma normalizzati upper nel template
(es. {project_code} == {Project_Code} == {PROJECT_CODE}).

Token mancanti producono `__` come placeholder (così è visibile cosa serve).
"""
from __future__ import annotations
import re
from datetime import datetime, date
from typing import Optional, Any
from sqlalchemy.orm import Session


# ── PRESET TEMPLATES ──────────────────────────────────────────
# Ognuno è (codice_id, label, descrizione, template_string).
# I template usano la sintassi {token_name}. I token disponibili sono
# documentati in TOKEN_HELP più sotto.

PRESET_TEMPLATES: list[dict] = [
    {
        "id": "isdcf_dcp",
        "label": "ISDCF DCP (cinema)",
        "description": (
            "Convenzione cinema ISDCF v9 per DCP. Esempio: "
            "MareNostrum_FTR-F_IT-it_51_2K_RAI_20260612_TPRBerlin_IOP_OV"
        ),
        "template": (
            "{film_name}_{content_type}-{aspect}_{territory}-{lang_audio}_"
            "{audio_config}_{resolution}_{studio_code}_{date_compact}_"
            "{facility_code}_{standard}_{package_type}"
        ),
    },
    {
        "id": "isdcf_dcp_short",
        "label": "ISDCF DCP — short form",
        "description": (
            "Versione abbreviata della ISDCF, senza territory/lang/standard. "
            "Buona per festival pass o promo."
        ),
        "template": (
            "{film_name}_{content_type}-{aspect}_{audio_config}_{resolution}_{date_compact}_OV"
        ),
    },
    {
        "id": "netflix_archival",
        "label": "Netflix Picture Archival",
        "description": (
            "Folder structure Netflix per archive. Esempio: "
            "MARE_S01_E04_FTR_2026-06-12_R02"
        ),
        "template": (
            "{show_abbr}_{season}_{episode}_{content_type}_{date_iso}_R{revision}"
        ),
    },
    {
        "id": "netflix_imf",
        "label": "Netflix IMF master",
        "description": (
            "Master IMF Netflix con language code e package type."
        ),
        "template": (
            "{show_abbr}_{season}_{episode}_IMF_{lang_audio}_{territory}_R{revision}"
        ),
    },
    {
        "id": "broadcast_dpp",
        "label": "DPP / AS-11 broadcast (UK/IT)",
        "description": "Standard DPP per broadcast UK + AS-11 italiano.",
        "template": (
            "{show_abbr}_{season}_{episode}_DPP_{date_iso}_R{revision}"
        ),
    },
    {
        "id": "prores_master",
        "label": "ProRes master deliverable",
        "description": "Master ProRes 4444/422 con dynamic range e audio config.",
        "template": (
            "{film_name}_{deliverable_kind}_{resolution}_{dynamic_range}_"
            "{audio_config}_{lang_audio}_{date_iso}_v{revision}"
        ),
    },
    {
        "id": "screener",
        "label": "Screener H.264 / H.265",
        "description": "Screener con timecode e watermark opzionali.",
        "template": (
            "{film_name}_SCREENER_{resolution}_{lang_audio}-{lang_subs}_{date_iso}_v{revision}"
        ),
    },
    {
        "id": "lto_archive",
        "label": "LTO archive label",
        "description": "Etichetta LTO con tipo materiale e progetto.",
        "template": (
            "LTO-{barcode}_{film_name}_{deliverable_kind}_{date_compact}"
        ),
    },
    {
        "id": "custom",
        "label": "Custom (libero)",
        "description": "Template libero — compila il campo file_naming senza usare placeholder.",
        "template": "",
    },
]


# ── TOKEN HELP (per UI: tooltip / pannello "Token disponibili") ──
TOKEN_HELP: list[dict] = [
    # Project / Client
    {"token": "project_code",       "group": "Project",  "desc": "Codice progetto (es. MARE-2026)"},
    {"token": "project_title",      "group": "Project",  "desc": "Titolo progetto completo"},
    {"token": "client_name",        "group": "Client",   "desc": "Nome cliente"},
    {"token": "client_code",        "group": "Client",   "desc": "Codice cliente abbreviato"},
    {"token": "studio_code",        "group": "Client",   "desc": "Codice studio (4-8 caratteri, es. RAI/SKY/A24)"},
    # Show / Episode
    {"token": "show_name",          "group": "Show",     "desc": "Nome show (per serie)"},
    {"token": "show_abbr",          "group": "Show",     "desc": "Abbreviazione show 4-6 char (es. MARE)"},
    {"token": "film_name",          "group": "Show",     "desc": "Nome film o show senza spazi (es. MareNostrum)"},
    {"token": "season",             "group": "Show",     "desc": "Stagione formato S01"},
    {"token": "season_no",          "group": "Show",     "desc": "Numero stagione (1)"},
    {"token": "episode",            "group": "Show",     "desc": "Episodio formato E04"},
    {"token": "episode_no",         "group": "Show",     "desc": "Numero episodio (4)"},
    {"token": "content_type",       "group": "Show",     "desc": "FTR/EPS/TRL/PRO/SHR (feature/episode/trailer/promo/short)"},
    # Format / Tech
    {"token": "aspect",             "group": "Format",   "desc": "F/S (flat/scope) o 1.85/2.39"},
    {"token": "resolution",         "group": "Format",   "desc": "HD/2K/UHD/4K/8K"},
    {"token": "framerate",          "group": "Format",   "desc": "24/25/2997/30"},
    {"token": "audio_config",       "group": "Format",   "desc": "51/71/Atmos/Stereo/Mono"},
    {"token": "color_space",        "group": "Format",   "desc": "Rec709/P3/Rec2020"},
    {"token": "dynamic_range",      "group": "Format",   "desc": "SDR/HDR/DV (Dolby Vision)"},
    # Language / Territory
    {"token": "lang_audio",         "group": "Language", "desc": "ISO 639-2: it/en/fr/es/de"},
    {"token": "lang_subs",          "group": "Language", "desc": "ISO 639-2 sottotitoli"},
    {"token": "territory",          "group": "Language", "desc": "ISO 3166-1 alpha-2: IT/US/GB; INT per international"},
    # Versioning
    {"token": "version",            "group": "Version",  "desc": "FT/FT2/IS (first/second/intermediate)"},
    {"token": "revision",           "group": "Version",  "desc": "Numero revisione (01/02/03)"},
    {"token": "rev",                "group": "Version",  "desc": "Alias di revision"},
    {"token": "cut",                "group": "Version",  "desc": "TC/DR/FN (temp/director/final)"},
    # Standards
    {"token": "standard",           "group": "Standard", "desc": "IOP/SMPTE/IMF/DPP/AS-11"},
    {"token": "package_type",       "group": "Standard", "desc": "OV/VF/SUPP (original/version/supplement)"},
    {"token": "deliverable_kind",   "group": "Standard", "desc": "DCP/IMF/PRORES/H264/H265/IMG/MASTER"},
    # Date / Facility
    {"token": "date_iso",           "group": "Date",     "desc": "Data ISO YYYY-MM-DD (oggi se non specificato)"},
    {"token": "date_compact",       "group": "Date",     "desc": "Data compatta YYYYMMDD"},
    {"token": "facility_code",      "group": "Facility", "desc": "Codice casa di post (es. TPRBerlin)"},
    # Physical asset
    {"token": "barcode",            "group": "Physical", "desc": "Barcode/serial dell'asset fisico (LTO/HDD)"},
    {"token": "deliverable_id",     "group": "System",   "desc": "ID interno del deliverable (4 cifre, zero-padded)"},
]

# v3.5.0-alpha.172.182 — set dei token noti, single source per validazione
# delle naming convention (capitolato/tenant/item). Derivato da TOKEN_HELP.
KNOWN_TOKENS: set = {t["token"] for t in TOKEN_HELP}


# ── RESOLVER ──────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _safe(v: Any) -> str:
    """Pulisce un valore per uso in nome file: spazi → '', rimuove caratteri
    non sicuri tipo /, \\, :, *, ?, ", <, >, |."""
    if v is None:
        return ""
    s = str(v).strip()
    s = re.sub(r"[\s/\\:\*\?\"<>\|]+", "", s)
    return s


def _safe_or_placeholder(v: Any) -> str:
    s = _safe(v)
    return s if s else "__"


def build_token_dict(
    db: Session,
    deliverable=None,
    job=None,
    project=None,
    client=None,
    delivery_template=None,
    physical_asset=None,
    overrides: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Costruisce il dict di token risolti dal contesto.

    `overrides` permette di sovrascrivere/forzare token specifici (es. la UI
    può inviare {framerate: "25", audio_config: "Atmos"} mentre l'utente
    digita).

    Tutti i valori sono passati attraverso `_safe()` per uso in filename.
    """
    # Lazy imports per evitare circular
    from app.models import Job, Project, Client, JobDeliverable, DeliveryTemplate

    # Defaults
    today = date.today()
    tokens: dict[str, str] = {
        "date_iso": today.isoformat(),
        "date_compact": today.strftime("%Y%m%d"),
    }

    # Project
    if project is None and job is not None and getattr(job, "project_id", None):
        project = db.query(Project).filter(Project.id == job.project_id).first()
    if project is None and deliverable is not None and getattr(deliverable, "job_id", None):
        j = db.query(Job).filter(Job.id == deliverable.job_id).first()
        if j and j.project_id:
            project = db.query(Project).filter(Project.id == j.project_id).first()
            if job is None:
                job = j
    if project is not None:
        tokens["project_code"] = _safe(project.code)
        tokens["project_title"] = _safe(project.title)
        # show_name / film_name fallback al project title
        tokens["show_name"] = _safe(project.title)
        film = re.sub(r"\s+", "", str(project.title or ""))
        tokens["film_name"] = _safe(film) if film else _safe(project.code)
        # show_abbr: prime 4-6 lettere maiuscole del titolo, rimuovendo articoli comuni
        if project.title:
            words = re.sub(r"\b(il|la|i|gli|le|un|uno|una|the|a|of|and|e)\b", "",
                           project.title.lower()).split()
            words = [w for w in words if w]
            abbr = ("".join(w[:3] for w in words[:2]) or words[0][:6] if words else "")[:6]
            tokens["show_abbr"] = _safe(abbr.upper())

    # Client
    if client is None and project is not None and getattr(project, "client_id", None):
        client = db.query(Client).filter(Client.id == project.client_id).first()
    if client is not None:
        tokens["client_name"] = _safe(client.name)
        # client_code / studio_code: prime 3-4 lettere del nome
        clean = re.sub(r"[^\w]", "", str(client.name or "")).upper()
        tokens["client_code"] = clean[:4]
        tokens["studio_code"] = clean[:6]

    # Tenant facility code (dal Tenant del db)
    try:
        from app.models import Tenant
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if tenant:
            tokens["facility_code"] = _safe(
                getattr(tenant, "slug", None) or tenant.name
            )[:12]
    except Exception:
        pass

    # JobDeliverable
    if deliverable is not None:
        tokens["deliverable_id"] = f"{deliverable.id:04d}" if getattr(deliverable, "id", None) else "0000"
        # date_iso può essere il target_delivery_date se presente
        if getattr(deliverable, "target_delivery_date", None):
            d = deliverable.target_delivery_date
            tokens["date_iso"] = d.isoformat()
            tokens["date_compact"] = d.strftime("%Y%m%d")
        # spec_json può contenere campi tecnici
        spec = deliverable.spec_json or {}
        for k in ("aspect", "resolution", "framerate", "audio_config",
                  "color_space", "dynamic_range",
                  "lang_audio", "lang_subs", "territory",
                  "version", "revision", "cut",
                  "standard", "package_type", "deliverable_kind",
                  "content_type"):
            if k in spec and spec[k]:
                tokens[k] = _safe(spec[k])

    # Physical asset (per LTO label, ecc.)
    if physical_asset is not None:
        if getattr(physical_asset, "barcode", None):
            tokens["barcode"] = _safe(physical_asset.barcode)
        elif getattr(physical_asset, "serial_number", None):
            tokens["barcode"] = _safe(physical_asset.serial_number)

    # DeliveryTemplate spec — può contribuire token tecnici
    if delivery_template is not None:
        try:
            video = (delivery_template.video_specs or {}) if hasattr(delivery_template, "video_specs") else {}
            audio = (delivery_template.audio_specs or {}) if hasattr(delivery_template, "audio_specs") else {}
            if "resolution" in video and "resolution" not in tokens:
                tokens["resolution"] = _safe(video["resolution"])
            if "framerate" in video and "framerate" not in tokens:
                tokens["framerate"] = _safe(video["framerate"])
            if "audio_config" in audio and "audio_config" not in tokens:
                tokens["audio_config"] = _safe(audio["audio_config"])
        except Exception:
            pass

    # Overrides utente (vincono su tutto)
    if overrides:
        for k, v in overrides.items():
            if v is not None and str(v).strip():
                tokens[k.lower()] = _safe(v)

    # Default revision se non presente
    tokens.setdefault("revision", "01")
    tokens.setdefault("rev", tokens["revision"])

    return tokens


def resolve_template(template: str, tokens: dict[str, str]) -> tuple[str, list[str]]:
    """Sostituisce i {token} nel template con i valori in `tokens`.

    Token mancanti producono `__` (visibile placeholder) e vengono raccolti
    in `missing` per feedback UI.

    Restituisce (output, missing_tokens).
    """
    if not template:
        return "", []
    missing: list[str] = []

    def replace(match: re.Match) -> str:
        key = match.group(1).lower()
        if key in tokens and tokens[key]:
            return tokens[key]
        missing.append(key)
        return "__"

    out = _TOKEN_RE.sub(replace, template)
    return out, missing


def get_preset_template(preset_id: str) -> Optional[dict]:
    """Restituisce il template preset per id, o None."""
    for p in PRESET_TEMPLATES:
        if p["id"] == preset_id:
            return p
    return None
