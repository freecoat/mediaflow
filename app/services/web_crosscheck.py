"""v3.5.0-alpha.96 (#9d) — Web cross-check progetti/clienti.

Verifica AI delle info salvate vs realtà web (IMDB, MyMovies, BoxOfficeMojo,
Variety, ecc.). Use case Matteo: dopo 6 mesi un progetto "Mare Nostrum"
potrebbe avere pubblicato cast updates, premi, incassi, distribuzione su
nuovi mercati — info non in DB ma rilevanti per il commerciale.

Strategia in cascata identica a client_enrichment.py:
1. provider.supports_web_search() → ricerca nativa multi-step (Anthropic)
2. Tavily configurato → search esterna + AI struttura
3. AI knowledge only (fallback)

Output: lista `differences` con `{field, current, suggested, source_url}`.
NO DB write — la UI mostra preview, l'utente decide cosa applicare.
"""
from __future__ import annotations
import json, logging
from typing import Optional
from app.config import settings
from app.services.ai_provider import get_provider
from app.services.web_search import tavily_search, format_search_results_for_ai

logger = logging.getLogger(__name__)


PROJECT_CHECK_SCHEMA = """Sei un esperto di cinema/TV/streaming che verifica
informazioni su un'opera audiovisiva confrontando dati salvati con info pubbliche.

Confronta i dati forniti con quanto sai/trovi sul web (IMDB, BoxOfficeMojo,
MyMovies, Variety, Wikipedia). Per ogni campo che DIFFERISCE o è MIGLIORABILE,
proponi il valore corretto/aggiornato con sorgente.

Schema output JSON:
{
  "differences": [
    {
      "field": "title | length_minutes | director | producer | dop | shoot_start | delivery_deadline | description | notes",
      "current": "<valore in DB>",
      "suggested": "<valore corretto/aggiornato>",
      "confidence": "high | medium | low",
      "source": "URL o riferimento (es. 'IMDB tt12345')",
      "rationale": "1 frase perché"
    }
  ],
  "external_info": {
    "imdb_url": "...",
    "boxoffice_url": "...",
    "awards": ["David di Donatello 2024 Best Actor", ...],
    "distribution_countries": ["IT", "FR", "DE"],
    "box_office_usd": 12500000,
    "rotten_tomatoes_pct": 85,
    "release_dates": [{"country": "IT", "date": "2024-09-15"}],
    "notes": "Sintesi 2-3 frasi: nuove info significative emerse rispetto al DB."
  },
  "sources": ["url1", "url2"]
}

Lascia `differences: []` se non hai trovato discrepanze.
Lascia `external_info` parzialmente vuoto se non trovi info — meglio null
che inventare. Cita sempre source per gli `awards`/`distribution_countries`."""


CLIENT_CHECK_SCHEMA = """Sei un esperto che verifica info aziendali per case
di produzione/distribuzione/broadcaster audiovisivi.

Confronta i dati cliente con info pubbliche aggiornate. Indica differenze
significative (es. cambio P.IVA dopo fusione, cambio sede, acquisizione).

Schema output JSON:
{
  "differences": [
    {
      "field": "name | vat_number | address | city | website | contact_email | industry | company_size",
      "current": "<valore in DB>",
      "suggested": "<valore corretto/aggiornato>",
      "confidence": "high | medium | low",
      "source": "URL o riferimento",
      "rationale": "1 frase perché (es. 'sede trasferita 2024 secondo Cerved')"
    }
  ],
  "external_info": {
    "recent_productions": [{"title": "...", "year": 2024, "role": "Produttore"}],
    "recent_news": ["Acquisita da Mediaset Feb 2024", ...],
    "linkedin_url": "...",
    "notes": "Sintesi cambi rilevanti dall'ultimo arricchimento."
  },
  "sources": ["url1", "url2"]
}

Lascia `differences: []` se non hai trovato discrepanze."""


def _build_project_prompt(p_data: dict) -> str:
    return (
        f"Verifica i seguenti dati salvati per un progetto audiovisivo:\n\n"
        f"{json.dumps(p_data, ensure_ascii=False, indent=2)}\n\n"
        f"Cerca informazioni pubbliche recenti. Restituisci JSON secondo schema."
    )


def _build_client_prompt(c_data: dict) -> str:
    return (
        f"Verifica i seguenti dati salvati per un'azienda audiovisiva:\n\n"
        f"{json.dumps(c_data, ensure_ascii=False, indent=2)}\n\n"
        f"Cerca info pubbliche aggiornate (sede, P.IVA, produzioni recenti, "
        f"notizie aziendali). Restituisci JSON secondo schema."
    )


def _try_native_web_search(provider, schema: str, user_prompt: str) -> Optional[dict]:
    if not provider.supports_web_search():
        return None
    result = provider.extract_json_with_web_search(
        schema, user_prompt, max_tokens=4000, max_searches=6
    )
    return result


def _try_tavily(provider, schema: str, base_query: str, user_prompt: str) -> Optional[dict]:
    if not settings.tavily_api_key:
        return None
    results = tavily_search(base_query, max_results=8, search_depth="advanced")
    if not results:
        return None
    web_ctx = format_search_results_for_ai(results)
    enriched_prompt = f"{user_prompt}\n\nRisultati ricerca web:\n{web_ctx}"
    return provider.extract_json(schema, enriched_prompt, max_tokens=3500)


def check_project(project_data: dict, provider=None) -> Optional[dict]:
    """Verifica progetto vs web. project_data: dict con `id, code, title,
    length_minutes, director, producer, dop, fps, shoot_start,
    delivery_deadline, description, status`.

    Ritorna `{differences: [...], external_info: {...}, sources: [...],
    web_search_used: bool}` o None se tutti i path falliscono.
    """
    if provider is None:
        provider = get_provider()
    if not provider:
        logger.warning("AI provider non disponibile — check_project disabilitato")
        return None
    user_prompt = _build_project_prompt(project_data)
    title = project_data.get("title", "")
    base_query = f'"{title}" film OR serie OR documentario {project_data.get("director","")} cast box office'.strip()

    # Path 1: native web search
    try:
        result = _try_native_web_search(provider, PROJECT_CHECK_SCHEMA, user_prompt)
        if result:
            result["web_search_used"] = True
            return result
    except Exception as e:
        logger.error(f"native web_search project failed: {e}")

    # Path 2: Tavily
    try:
        result = _try_tavily(provider, PROJECT_CHECK_SCHEMA, base_query, user_prompt)
        if result:
            result["web_search_used"] = True
            return result
    except Exception as e:
        logger.error(f"tavily project failed: {e}")

    # Path 3: AI knowledge only
    try:
        result = provider.extract_json(PROJECT_CHECK_SCHEMA, user_prompt, max_tokens=3000)
        if result:
            result["web_search_used"] = False
            return result
    except Exception as e:
        logger.error(f"knowledge-only project failed: {e}")
    return None


def check_client(client_data: dict, provider=None) -> Optional[dict]:
    """Verifica cliente vs web. Analoga a `check_project`."""
    if provider is None:
        provider = get_provider()
    if not provider:
        return None
    user_prompt = _build_client_prompt(client_data)
    name = client_data.get("name", "")
    base_query = (f'"{name}" casa produzione cinematografica OR distribuzione '
                  f'{client_data.get("city","")} {client_data.get("country","")}').strip()
    paths = [
        ("native", lambda: _try_native_web_search(provider, CLIENT_CHECK_SCHEMA, user_prompt)),
        ("tavily", lambda: _try_tavily(provider, CLIENT_CHECK_SCHEMA, base_query, user_prompt)),
        ("knowledge", lambda: provider.extract_json(CLIENT_CHECK_SCHEMA, user_prompt, max_tokens=3000)),
    ]
    for path_name, fn in paths:
        try:
            r = fn()
            if r:
                r["web_search_used"] = (path_name != "knowledge")
                return r
        except Exception as e:
            logger.error(f"check_client path {path_name} failed: {e}")
            continue
    return None
