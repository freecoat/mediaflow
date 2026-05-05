"""
MediaFlow — Ricerca filmografia cliente via AI + fonti esterne (v3.5.0-alpha.25)

Cerca le opere prodotte/distribuite/post-prodotte da un cliente del settore
audiovisivo usando 4 fonti pubbliche:

  - filmitalia.org           — filmografia italiana
  - cinema.cultura.gov.it    — database opere cinematografiche MIC
  - imdb.com                 — database internazionale
  - mymovies.it              — magazine cinema italiano

L'AI analizza i risultati di Tavily (con `include_domains` ristretto a
queste fonti) e ritorna una lista strutturata di candidati. L'utente
conferma quali importare; l'import è idempotente su (title, year).

Workflow "AI propone, utente dispone": NIENTE scrittura DB qui — solo
proposta. La write-path passa dal router con conferma esplicita.
"""
from __future__ import annotations
import logging
from typing import Optional

from app.services.web_search import tavily_search
from app.services.ai_provider import AIProvider, safe_json_parse

logger = logging.getLogger(__name__)


# Fonti pubbliche affidabili per filmografia di case di produzione/post.
FILMOGRAPHY_DOMAINS = [
    "filmitalia.org",
    "cinema.cultura.gov.it",
    "imdb.com",
    "mymovies.it",
]


def search_filmography(
    client_name: str,
    provider: AIProvider,
    *,
    max_results_per_query: int = 8,
    extra_hint: Optional[str] = None,
) -> Optional[dict]:
    """Cerca le opere di `client_name` sulle fonti FILMOGRAPHY_DOMAINS.

    Workflow:
      1. 2 query Tavily mirate con `include_domains` (italiana + internazionale).
      2. Concatena gli snippet → prompt all'AI per estrazione strutturata.
      3. Ritorna `{"works": [...], "sources_consulted": [{name,url}, ...]}`
         o `None` se la ricerca o l'estrazione falliscono.

    Ogni `work` ha campi: title, year, kind, our_role (inferito), director,
    country, source_urls (lista), confidence (alta/media/bassa basata su
    quante fonti citano l'opera).

    NESSUNA scrittura DB. Il chiamante decide cosa importare.
    """
    if not client_name or not client_name.strip():
        return None

    # ── Step 1: 2 query Tavily mirate ─────────────────────────────────
    queries = [
        f'"{client_name}" filmografia produzioni opere',
        f'"{client_name}" produced films movies series',
    ]
    if extra_hint:
        queries.append(f'"{client_name}" {extra_hint}')

    aggregated_results = []
    sources_consulted = []
    seen_urls = set()
    for q in queries:
        resp = tavily_search(
            q,
            max_results=max_results_per_query,
            search_depth="advanced",
            include_domains=FILMOGRAPHY_DOMAINS,
        )
        if not resp:
            continue
        for r in (resp.get("results") or []):
            url = r.get("url") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            aggregated_results.append(r)
            try:
                from urllib.parse import urlparse
                host = urlparse(url).netloc.lower()
            except Exception:
                host = ""
            sources_consulted.append({"name": host, "url": url})

    if not aggregated_results:
        logger.warning(f"filmography: nessun risultato Tavily per '{client_name}'")
        return {
            "works": [],
            "sources_consulted": [],
            "warning": "Nessuna fonte ha restituito risultati. Riprova con un nome più completo (es. 'Cattleya srl' invece di 'Cattleya') o aggiungi un hint.",
        }

    # ── Step 2: prompt AI per estrazione strutturata ──────────────────
    sources_blob = "\n\n".join(
        f"[{i+1}] {r.get('title','(senza titolo)')}\nURL: {r.get('url','')}\n"
        f"Estratto: {(r.get('content') or '')[:1800]}"
        for i, r in enumerate(aggregated_results[:20])
    )
    system = (
        "Sei un assistente specializzato in filmografie del settore audiovisivo "
        "(post-produzione, produzione, distribuzione). Estrai dalle fonti fornite "
        "le opere collegate al cliente indicato. Solo opere CON FONTE ESPLICITA "
        "tra quelle fornite — niente invenzioni, niente memoria addestramento."
    )
    user = f"""Cliente target: {client_name}

Fonti consultate:
{sources_blob}

ESTRAI tutte le opere (film, serie, documentari, spot, cortometraggi) in cui il cliente ha avuto un ruolo, con le seguenti regole:

1. **Solo opere supportate dalle fonti**: niente memoria addestramento, niente invenzioni.
2. **Dedup intelligente**: se la stessa opera appare in più fonti, una sola entry con tutti gli URL.
3. **Ruolo del cliente** (`our_role`): inferisci dal contesto. Se la fonte dice "prodotto da X", `our_role`="produzione". Se dice "post-produzione di X", `our_role`="post-produzione". Se incerto, lascia null.
4. **Tipo opera** (`kind`): film, serie, documentario, spot, cortometraggio, altro.
5. **Anno** (`year`): solo se chiaramente indicato. Se non sicuro, null.
6. **Confidence**: "alta" (≥2 fonti citano l'opera), "media" (1 fonte primaria), "bassa" (menzione marginale).

Rispondi SOLO con questo JSON, senza testo prima o dopo, senza markdown:

{{
  "works": [
    {{
      "title": "Titolo opera",
      "year": 2024,
      "kind": "film|serie|documentario|spot|cortometraggio|altro",
      "our_role": "produzione|post-produzione|distribuzione|co-produzione|... (o null)",
      "director": "Nome Cognome (o null)",
      "country": "IT (o null)",
      "source_urls": ["https://...", "https://..."],
      "confidence": "alta|media|bassa"
    }}
  ]
}}

Se nessuna opera è chiaramente identificabile, ritorna `{{"works": []}}`.
"""
    extracted = provider.extract_json(system, user, max_tokens=6000)
    if not extracted:
        return {
            "works": [],
            "sources_consulted": sources_consulted,
            "warning": "L'AI non è riuscita a estrarre opere strutturate dalle fonti.",
        }

    works = extracted.get("works") or []
    # Sanitize: enforce schema + drop entries senza title
    clean = []
    for w in works:
        if not isinstance(w, dict):
            continue
        title = (w.get("title") or "").strip()
        if not title:
            continue
        year = w.get("year")
        try:
            year = int(year) if year else None
            if year and (year < 1900 or year > 2100):
                year = None
        except (ValueError, TypeError):
            year = None
        urls = w.get("source_urls") or []
        if not isinstance(urls, list):
            urls = []
        urls = [str(u) for u in urls if u]
        clean.append({
            "title": title[:255],
            "year": year,
            "kind": (w.get("kind") or None),
            "our_role": (w.get("our_role") or None),
            "director": (w.get("director") or None),
            "country": (w.get("country") or None),
            "source_urls": urls,
            "confidence": w.get("confidence") or "media",
        })

    return {
        "works": clean,
        "sources_consulted": sources_consulted,
    }
