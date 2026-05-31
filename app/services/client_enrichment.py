"""
MediaFlow — Client Enrichment
Arricchisce dati cliente via AI con tre strategie in cascata:
1. provider.supports_web_search() → ricerca web nativa multi-step (Anthropic Claude),
   il modello cerca autonomamente sito ufficiale, P.IVA, filmografia, ecc.
2. Tavily configurato → ricerca web esterna + AI struttura le fonti
3. Fallback "AI knowledge only" — solo training del modello, nessuna ricerca
"""
from __future__ import annotations
from app.services.clock import now_utc
import json, logging
from datetime import datetime
from typing import Optional
from app.config import settings
from app.services.ai_provider import get_provider
from app.services.web_search import tavily_search, format_search_results_for_ai

logger = logging.getLogger(__name__)


ENRICHMENT_SYSTEM_PROMPT_WEB = """Sei un assistente che analizza informazioni aziendali da fonti web e le struttura in un formato JSON specifico.

Il contesto è un software di gestione per case di produzione audiovisiva/postproduzione: i clienti sono tipicamente case di produzione, distributori cinematografici, broadcaster, agenzie pubblicitarie, istituzioni culturali.

Estrai SOLO informazioni verificabili dalle fonti fornite. Se un campo non è presente o incerto, lascialo null.
Non inventare dati.

Schema di output JSON (tutti i campi opzionali, None se non trovato):
{
  "legal_form": "SRL | SPA | GmbH | Inc | ...",
  "vat_number": "P.IVA o numero IVA",
  "tax_code": "Codice fiscale se diverso",
  "address": "Indirizzo completo sede legale",
  "city": "Città",
  "country": "Paese",
  "website": "URL sito ufficiale (https://...)",
  "contact_email": "Email generica aziendale",
  "contact_phone": "Telefono centralino",
  "industry": "Settore (es. 'Produzione cinematografica', 'Distribuzione', 'Broadcaster')",
  "company_size": "Piccola (<10) | Media (10-50) | Grande (50-250) | Enterprise (250+)",
  "founded_year": 2003,
  "recent_productions": [
    {
      "title": "Nome opera",
      "year": 2023,
      "role": "Produttore | Coproduttore | Distributore | Esecutivo | ...",
      "format": "Lungometraggio | Cortometraggio | Serie TV | Documentario | Spot | Branded",
      "genre": "Drammatico | Commedia | Thriller | Animazione | ...",
      "length_minutes": 110,
      "director": "Nome cognome",
      "cast": ["Attore 1", "Attore 2", "Attore 3"],
      "dop": "Direttore della fotografia (se noto)",
      "release_date": "YYYY-MM-DD o null",
      "festival_premiere": "es. 'Venezia 2023', 'Cannes 2024' o null",
      "distributor": "Distributore IT/internazionale (se diverso da role)",
      "broadcaster": "Broadcaster/Streamer (Netflix, Sky, RAI, ...) o null",
      "funding": ["MIC", "Eurimages", "Regione Lazio Film Commission", "tax credit", ...],
      "co_producers": ["Coproduttori esteri/nazionali"],
      "box_office_eur": 1234567,
      "awards": ["Coppa Volpi 2023", "David di Donatello"],
      "imdb_id": "tt1234567 o null"
    },
    ...
  ],
  "notes": "Sintesi 2-3 frasi: cosa fa l'azienda, specializzazione, reputazione.",
  "sources": ["url1", "url2", ...]
}

IMPORTANTE filmografia: per case di produzione audiovisiva i campi rilevanti
per un software gestionale post-prod sono cast/regista/dop (per matching
risorse), finanziamenti (per valutare budget tipici), date uscita (per
pianificare consegne future), festival/awards (per posizionamento). NON
limitarti a title+year+role: cerca dettagli completi per almeno le ultime
5-10 produzioni rilevanti."""


ENRICHMENT_SYSTEM_PROMPT_NOWEB = """Sei un assistente che struttura informazioni aziendali in un formato JSON specifico.

Il contesto è un software di gestione per case di produzione audiovisiva/postproduzione: i clienti sono tipicamente case di produzione, distributori cinematografici, broadcaster, agenzie pubblicitarie, istituzioni culturali.

NON hai accesso a una ricerca web in tempo reale. Usa SOLO la conoscenza del tuo training. Se l'azienda è famosa o ha presenza pubblica nota, compila i campi che ricordi con certezza. Se NON sei sicuro di un dato (es. P.IVA esatta, indirizzo preciso, anno fondazione), lascialo null. È meglio lasciare un campo vuoto che inventarlo.

Schema di output JSON (tutti i campi opzionali, null se non sai):
{
  "legal_form": "SRL | SPA | GmbH | Inc | ...",
  "vat_number": null,
  "tax_code": null,
  "address": null,
  "city": "Città se molto nota",
  "country": "Paese se molto noto",
  "website": "URL sito ufficiale solo se certo (https://...)",
  "contact_email": null,
  "contact_phone": null,
  "industry": "Settore generale (es. 'Produzione cinematografica', 'Distribuzione', 'Broadcaster')",
  "company_size": "Piccola | Media | Grande | Enterprise — solo se noto",
  "founded_year": null,
  "recent_productions": [
    {
      "title": "Nome opera ricordata",
      "year": 2023,
      "role": "Produttore/Coproduttore/Distributore/...",
      "format": "Lungometraggio | Serie TV | Documentario | ...",
      "genre": "Drammatico | Commedia | ...",
      "length_minutes": null,
      "director": "Nome cognome se ricordato",
      "cast": ["Attori principali se ricordati"],
      "dop": null,
      "release_date": "YYYY-MM-DD o null",
      "festival_premiere": "es. 'Venezia 2023' o null",
      "distributor": null,
      "broadcaster": null,
      "funding": ["MIC", "tax credit", ...] o [],
      "co_producers": [],
      "box_office_eur": null,
      "awards": ["David", "Coppa Volpi", ...] o [],
      "imdb_id": null
    }
  ],
  "notes": "2-3 frasi su cosa fa l'azienda. Indica esplicitamente se sono informazioni dal tuo training, potenzialmente non aggiornate.",
  "sources": []
}

IMPORTANTE filmografia: anche senza accesso web, per case famose ricorda
quanto puoi su cast/regista/festival/awards delle produzioni note. Lascia
null SOLO i campi di cui non sei certo (date precise, IBAN, P.IVA, box
office). Cast/regista sono spesso noti per produzioni di rilievo."""


def _normalize_result(result: dict, web_used: bool) -> dict:
    """Serializza liste per Text column + aggiunge metadata."""
    if isinstance(result.get("recent_productions"), list):
        result["recent_productions"] = json.dumps(result["recent_productions"], ensure_ascii=False)
    if isinstance(result.get("sources"), list):
        result["ai_sources"] = json.dumps(result["sources"], ensure_ascii=False)
        del result["sources"]
    result["ai_enriched"] = True
    result["ai_enriched_at"] = now_utc().isoformat()
    result["web_search_used"] = web_used
    return result


def _try_native_web_search(provider, name: str, known_info: Optional[dict]) -> Optional[dict]:
    """Path 1: il provider espone web_search nativo (Anthropic). Multi-step autonomo."""
    if not provider.supports_web_search():
        return None
    user_prompt = (
        f'Cerca informazioni dettagliate sull\'azienda audiovisiva "{name}". '
        f'Fai più ricerche separate per ciascuna area: '
        f'(1) sito ufficiale + sede legale + P.IVA + anno fondazione; '
        f'(2) filmografia recente (ultimi 5 anni) con per ogni produzione '
        f'cast principale, regista, DOP, date uscita theatrical/streaming, '
        f'premiere festival, distributore, broadcaster; '
        f'(3) finanziamenti pubblici noti (MIC, Eurimages, Film Commission '
        f'regionali, tax credit), coproduttori esteri/nazionali; '
        f'(4) box office italiano/internazionale se reperibile, premi/awards. '
        f'Usa anche IMDb/CineDataBase/Mymovies/Variety come fonti.\n\n'
        + (f"Info già note (puoi usarle per affinare le query): "
           f"{json.dumps(known_info, ensure_ascii=False)}\n\n" if known_info else "")
        + 'Restituisci poi UN SOLO oggetto JSON secondo lo schema, senza testo extra. '
        + 'Per ogni produzione popola TUTTI i campi che riesci a trovare con '
        + 'ragionevole certezza (cast, regista, finanziamenti, date). Lascia '
        + 'null solo i campi davvero non documentati.'
    )
    logger.info(f"Native web_search per: {name}")
    result = provider.extract_json_with_web_search(
        ENRICHMENT_SYSTEM_PROMPT_WEB, user_prompt, max_tokens=4000, max_searches=5
    )
    if result:
        return _normalize_result(result, web_used=True)
    logger.warning("Native web_search non ha prodotto JSON — fallback")
    return None


def _try_tavily(provider, name: str, known_info: Optional[dict]) -> Optional[dict]:
    """Path 2: Tavily configurato → ricerca esterna + AI struttura."""
    if not settings.tavily_api_key:
        return None
    query_parts = [name]
    if known_info:
        if known_info.get("city"):
            query_parts.append(known_info["city"])
        if known_info.get("country"):
            query_parts.append(known_info["country"])
    query_parts.append("casa di produzione audiovisiva OR produzione cinematografica OR distribuzione")
    search_query = " ".join(query_parts)
    logger.info(f"Tavily search per: {search_query}")
    search_results = tavily_search(search_query, max_results=6, search_depth="advanced")
    if not search_results:
        logger.warning("Tavily ha risposto vuoto — fallback")
        return None
    web_context = format_search_results_for_ai(search_results)
    user_prompt = (
        f'Nome azienda da analizzare: "{name}"\n\n'
        + (f"Informazioni già note: {json.dumps(known_info, ensure_ascii=False)}\n\n" if known_info else "")
        + f"Ricerca web eseguita:\n{web_context}\n\n"
        + "Estrai i dati aziendali secondo lo schema JSON richiesto."
    )
    result = provider.extract_json(ENRICHMENT_SYSTEM_PROMPT_WEB, user_prompt, max_tokens=3000)
    if not result:
        return None
    return _normalize_result(result, web_used=True)


def _try_noweb(provider, name: str, known_info: Optional[dict]) -> Optional[dict]:
    """Path 3: solo knowledge dell'AI, nessuna ricerca web."""
    user_prompt = (
        f'Nome azienda da analizzare: "{name}"\n\n'
        + (f"Informazioni già note: {json.dumps(known_info, ensure_ascii=False)}\n\n" if known_info else "")
        + "Compila quel che sai con certezza dal tuo training, lascia null il resto."
    )
    logger.info(f"AI knowledge only per: {name}")
    result = provider.extract_json(ENRICHMENT_SYSTEM_PROMPT_NOWEB, user_prompt, max_tokens=3000)
    if not result:
        return None
    return _normalize_result(result, web_used=False)


def enrich_client(name: str, known_info: Optional[dict] = None, provider=None) -> Optional[dict]:
    """
    Arricchisce i dati di un cliente partendo dal nome.

    Strategia in cascata (priorità decrescente):
    1. provider.supports_web_search() → ricerca nativa multi-step (Anthropic Claude:
       il modello cerca autonomamente sito, P.IVA, filmografia ecc., decide le query).
    2. Tavily configurato → ricerca web esterna + AI struttura le fonti.
    3. AI knowledge only → solo training del modello, nessuna ricerca.

    known_info: dati già noti (city/country) — usati per affinare le query.
    provider: provider AI risolto (get_provider_for_user). Se None, fallback legacy.
    Ritorna dict con campi del cliente + `web_search_used: bool`, oppure None se tutto fallisce.
    """
    if provider is None:
        provider = get_provider()
    if not provider:
        logger.warning("AI provider non disponibile — arricchimento impossibile")
        return None

    for path in (_try_native_web_search, _try_tavily, _try_noweb):
        try:
            result = path(provider, name, known_info)
            if result:
                return result
        except Exception as e:
            logger.error(f"Enrichment path {path.__name__} ha sollevato {e}")
            continue

    logger.error("Tutti i path di arricchimento hanno fallito")
    return None
