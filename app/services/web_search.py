"""
MediaFlow — Web Search via Tavily API
https://tavily.com — 1000 query/mese gratis con account free.
"""
from __future__ import annotations
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)


def tavily_search(query: str, max_results: int = 5,
                  search_depth: str = "advanced",
                  include_raw_content: bool = False,
                  include_domains: Optional[list] = None,
                  exclude_domains: Optional[list] = None,
                  timeout: int = 20) -> Optional[dict]:
    """
    Esegue una ricerca web tramite Tavily.
    Restituisce: {'answer': str, 'results': [{'title', 'url', 'content', 'score'}], 'query': str}
    oppure None in caso di errore.

    `include_domains`/`exclude_domains` (v3.5.0-alpha.25): liste di domini da
    includere/escludere dai risultati. Usato dalla ricerca filmografia per
    restringere a filmitalia.org / cinema.cultura.gov.it / IMDB / MyMovies.
    """
    if not settings.tavily_api_key:
        logger.warning("TAVILY_API_KEY non configurata — ricerca web disabilitata")
        return None
    try:
        from tavily import TavilyClient
    except ImportError:
        logger.error("tavily-python non installato: pip install tavily-python")
        return None

    try:
        client = TavilyClient(api_key=settings.tavily_api_key)
        kwargs = dict(
            query=query,
            search_depth=search_depth,
            max_results=max_results,
            include_answer=True,
            include_raw_content=include_raw_content,
            # α.172.146 — timeout esplicito: senza, una chiamata lenta/bloccata
            # appendeva il loop copilot (utente "non ho ricevuto i risultati").
            timeout=timeout,
        )
        if include_domains:
            kwargs["include_domains"] = include_domains
        if exclude_domains:
            kwargs["exclude_domains"] = exclude_domains
        try:
            resp = client.search(**kwargs)
        except TypeError:
            # SDK più vecchio senza kwarg timeout → retry senza.
            kwargs.pop("timeout", None)
            resp = client.search(**kwargs)
        return resp
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        return None


def format_search_results_for_ai(results: dict) -> str:
    """Converte i risultati Tavily in un testo utile per il prompt AI."""
    if not results or not results.get("results"):
        return "Nessun risultato trovato."
    
    out = []
    if results.get("answer"):
        out.append(f"SOMMARIO: {results['answer']}\n")
    out.append("FONTI:")
    for i, r in enumerate(results["results"], 1):
        out.append(f"\n[{i}] {r.get('title', 'Senza titolo')}")
        out.append(f"URL: {r.get('url', '')}")
        content = r.get("content", "")[:1500]
        out.append(f"Contenuto: {content}")
    return "\n".join(out)
