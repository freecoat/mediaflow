"""Content Lockdown — chokepoint unico per l'egress verso servizi cloud.

v3.5.0-alpha.172.195 — TPN / MPA Content Security Best Practices.

Modello: un megaswitch `lockdown_master` (OPEN | LOCKDOWN) + 3 sub-switch
booleani sul Tenant. Quando master=LOCKDOWN i sub sono tutti forzati off
(1-click). Quando master=OPEN i sub valgono singolarmente (controllo fine).

Tre vettori di egress gestiti:
  - cloud_ai   → uso di provider AI cloud (Claude/OpenAI/Gemini/...). Off =
                 force-Ollama locale nel provider factory (kill anche la
                 native web search lato modello).
  - web_search → chiamate Tavily (motore di ricerca esterno).
  - enrichment → feature che mandano FUORI nomi cliente/progetto
                 (enrich_client, filmography, web_crosscheck).

Principio FAIL-CLOSED: tenant None / non risolvibile → trattato come LOCKED.
Direzione sicura per un sistema content-security: in dubbio, niente egress.

Le funzioni pure (`effective_flags`, `*_allowed`, `assert_*`) lavorano su un
oggetto tenant duck-typed (testabili senza DB). I wrapper `*_current` risolvono
il tenant CURRENT_TENANT da una sessione passata dal chiamante.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

OPEN = "OPEN"
LOCKDOWN = "LOCKDOWN"

# Sub-switch attivi quando master=OPEN. Default True (retrocompat: tenant
# esistenti senza colonne migrate o appena migrati restano pienamente aperti).
_DEFAULT_SUBS = ("cloud_ai_enabled", "web_search_enabled", "enrichment_enabled")


class EgressLocked(Exception):
    """Sollevata quando un vettore di egress è bloccato dal lockdown.

    `vector` ∈ {"cloud_ai", "web_search", "enrichment"}. Gestita a livello
    router/handler per restituire 403 pulito (non 500 nudo) e messaggio chiaro.
    """

    def __init__(self, vector: str, tenant_id: Optional[int] = None):
        self.vector = vector
        self.tenant_id = tenant_id
        super().__init__(
            f"Cloud egress '{vector}' bloccato dal Content Lockdown "
            f"(tenant {tenant_id})."
        )


def effective_flags(tenant) -> dict:
    """Risolve master + sub-switch → flag effettivi.

    FAIL-CLOSED: tenant None → tutto bloccato (master=LOCKDOWN virtuale).
    Attributi mancanti su un tenant reale → default OPEN/True (retrocompat
    pre-migrazione: un tenant che esiste ma non ha ancora le colonne non deve
    rompere il flusso esistente).
    """
    if tenant is None:
        return {"master": LOCKDOWN, "cloud_ai": False,
                "web_search": False, "enrichment": False}

    master = getattr(tenant, "lockdown_master", OPEN) or OPEN
    is_open = (master == OPEN)
    return {
        "master": master,
        "cloud_ai": is_open and bool(getattr(tenant, "cloud_ai_enabled", True)),
        "web_search": is_open and bool(getattr(tenant, "web_search_enabled", True)),
        "enrichment": is_open and bool(getattr(tenant, "enrichment_enabled", True)),
    }


# ── boolean helpers ─────────────────────────────────────────────────

def cloud_ai_allowed(tenant) -> bool:
    return effective_flags(tenant)["cloud_ai"]


def web_search_allowed(tenant) -> bool:
    return effective_flags(tenant)["web_search"]


def enrichment_allowed(tenant) -> bool:
    return effective_flags(tenant)["enrichment"]


# ── assert helpers (raise EgressLocked) ─────────────────────────────

def assert_cloud_ai_allowed(tenant) -> None:
    if not cloud_ai_allowed(tenant):
        raise EgressLocked("cloud_ai", getattr(tenant, "id", None))


def assert_web_search_allowed(tenant) -> None:
    if not web_search_allowed(tenant):
        raise EgressLocked("web_search", getattr(tenant, "id", None))


def assert_enrichment_allowed(tenant) -> None:
    if not enrichment_allowed(tenant):
        raise EgressLocked("enrichment", getattr(tenant, "id", None))


# ── tenant resolution (CURRENT_TENANT, single-tenant copilot) ───────

def _load_current_tenant(db):
    """Carica il Tenant CURRENT_TENANT da una sessione. None su errore."""
    if db is None:
        return None
    try:
        from app.models.models import Tenant
        # Import locale per evitare cicli; CURRENT_TENANT=1 (single-tenant).
        return db.query(Tenant).filter(Tenant.id == 1).first()
    except Exception as e:  # pragma: no cover - difensivo
        logger.warning(f"egress_guard: risoluzione tenant fallita: {e}")
        return None


def web_search_allowed_current(db) -> bool:
    """Flag web_search per il tenant corrente. Fail-closed se non risolvibile."""
    return web_search_allowed(_load_current_tenant(db))


def enrichment_allowed_current(db) -> bool:
    return enrichment_allowed(_load_current_tenant(db))


def assert_web_search_allowed_current(db) -> None:
    assert_web_search_allowed(_load_current_tenant(db))


def assert_enrichment_allowed_current(db) -> None:
    assert_enrichment_allowed(_load_current_tenant(db))


def web_search_positively_locked() -> bool:
    """Backstop per call-site SENZA sessione (es. tavily_search low-level).

    Apre una sessione propria, risolve CURRENT_TENANT e ritorna True SOLO se
    il tenant è risolvibile ED ha web_search bloccato. Su qualsiasi errore /
    tenant non risolvibile ritorna False (LENIENT): qui è solo difesa in
    profondità — l'enforcement fail-closed autoritativo è ai call-site che
    hanno il tenant reale. Evita di rompere test/contesti senza DB.
    """
    try:
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            tenant = _load_current_tenant(db)
            if tenant is None:
                return False  # lenient: nessun tenant → lascia decidere ai gate
            return not web_search_allowed(tenant)
        finally:
            db.close()
    except Exception as e:  # pragma: no cover - difensivo
        logger.warning(f"egress_guard backstop tavily fallito: {e}")
        return False


# ── self-test (prova reale ogni vettore) ────────────────────────────

def selftest(tenant) -> dict:
    """Report stato lockdown per UI/audit. Non esegue chiamate di rete:
    riflette la configurazione effettiva (ciò che SAREBBE permesso).

    Ritorna shape consumabile dal template:
      {master, vectors: {cloud_ai, web_search, enrichment}, locked: bool}
    """
    f = effective_flags(tenant)
    return {
        "master": f["master"],
        "vectors": {
            "cloud_ai": f["cloud_ai"],
            "web_search": f["web_search"],
            "enrichment": f["enrichment"],
        },
        "locked": not (f["cloud_ai"] or f["web_search"] or f["enrichment"]),
    }
