"""
MediaFlow — AI capability decorator registry (v3.5.0-alpha.66.17.2)

Sprint R6 Step 2 dell'audit (pattern systemico N): chiude il drift fra le
3 source-of-truth sparse per le capability AI:

  1. `_ACTION_HANDLERS = {"propose_x": _h_propose_x, ...}` (handlers)
  2. `VALID_ACTION_TYPES = {"propose_x", ...}` (parser legacy markdown)
  3. `TOOLS = [{"name": "propose_x", ...}]` (Anthropic tool descriptors)

L'audit aveva rilevato che (1) e (2) divergevano: 21 handlers vs 13
type validi nel parser legacy → capability silenziosamente non
disponibili per provider non-Anthropic (Ollama/Perplexity).

**Soluzione**: decorator `@ai_capability("name")` che registra il
handler in `_REGISTRY`. Da qui derivano automaticamente:
- `get_handlers() → dict[name, fn]` (replace per `_ACTION_HANDLERS`)
- `get_action_types() → set[name]` (replace per `VALID_ACTION_TYPES`)

I 21 handler in `ai_assistant.py` aggiungono il decorator sopra la
definizione. `_ACTION_HANDLERS` e `VALID_ACTION_TYPES` esistenti
continuano a funzionare come alias verso il registry (zero call site
toccati).

USO:

    from app.services.ai_capability_registry import ai_capability

    @ai_capability("propose_quote_line")
    def _h_propose_quote_line(db, data):
        ...

NB: il decorator NON modifica la funzione (ritorna `fn` invariato),
quindi è no-op runtime. Si limita a popolare il registry al import-time.

CATEGORIE (opzionale): un capability può dichiarare `category=` per
clustering UI/audit. Default: derivata dal nome (`propose_*` =
"mutation", `analyze_*` / `find_*` / `query_*` / `read_*` / `list_*` =
"readonly", altro = "action").
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# Registry interno: name → (fn, category)
_REGISTRY: dict[str, tuple[Callable, str]] = {}


def _infer_category(name: str) -> str:
    """Inferisce la categoria dal nome se non esplicitata."""
    if name.startswith("propose_") or name.startswith("update_"):
        return "mutation"
    if name.startswith(("analyze_", "find_", "query_", "read_", "list_")):
        return "readonly"
    if name == "web_search":
        return "readonly"
    return "action"


def ai_capability(name: str, *, category: Optional[str] = None):
    """Decorator: registra `fn` come handler per la capability `name`.

    Idempotente: registrare la stessa capability due volte (stessa
    identità funzione) è no-op. Re-registrare con funzione diversa
    sovrascrive con warning.
    """
    def _wrap(fn: Callable) -> Callable:
        existing = _REGISTRY.get(name)
        if existing is not None and existing[0] is not fn:
            logger.warning(
                f"ai_capability: re-registering '{name}' "
                f"(prev={existing[0].__qualname__}, new={fn.__qualname__})"
            )
        cat = category or _infer_category(name)
        _REGISTRY[name] = (fn, cat)
        return fn  # no-op a runtime: il decorator serve solo al registry
    return _wrap


def get_handlers() -> dict[str, Callable]:
    """Mappa name → handler (alias compat per `_ACTION_HANDLERS`)."""
    return {k: v[0] for k, v in _REGISTRY.items()}


def get_action_types() -> set[str]:
    """Set dei nomi capability registrati (alias compat per
    `VALID_ACTION_TYPES`)."""
    return set(_REGISTRY.keys())


def get_categories() -> dict[str, str]:
    """Mappa name → category (per filtri UI/audit)."""
    return {k: v[1] for k, v in _REGISTRY.items()}


def get_handler(name: str) -> Optional[Callable]:
    """Lookup singolo. None se la capability non è registrata."""
    entry = _REGISTRY.get(name)
    return entry[0] if entry else None


def list_capabilities() -> list[dict]:
    """Per debug / introspection: lista [{name, category, qualname}]
    ordinata per name."""
    return [
        {"name": n, "category": c, "qualname": fn.__qualname__}
        for n, (fn, c) in sorted(_REGISTRY.items())
    ]
