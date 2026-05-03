"""
MediaFlow — AI Tools registry (refactor tool-use nativo, v3.5.0)

Definisce in un unico posto gli "strumenti" che l'AI può proporre/eseguire:
- ogni tool ha JSON Schema canonico (formato Anthropic, riusabile via converter
  per OpenAI function-calling e Google Gemini function-calling);
- ogni tool è marcato `category` ∈ {"readonly", "mutation"};
  - readonly  → eseguito server-side automaticamente dentro il loop tool_use;
                il risultato torna come tool_result al modello, che prosegue.
  - mutation  → NON eseguito automaticamente. Salvato come AIAction proposed,
                il loop si interrompe, la UI mostra una card con bottoni
                Applica/Rifiuta. Su Apply, il backend esegue, costruisce il
                tool_result e riprende il loop chiamando di nuovo il provider
                (continuation). Mantiene il pattern "AI propone, utente dispone".
- ogni tool referenzia un handler in `ai_assistant._ACTION_HANDLERS` per
  l'esecuzione concreta sul DB.

Le 9 capability iniziali sono identiche a quelle del precedente sistema basato
su blocchi ```action ...```; lo schema qui è sostanzialmente lo stesso, ma
serializzato in JSON Schema invece che descritto nel system prompt.
"""
from __future__ import annotations
from typing import Any, Optional


# ── Tool registry ─────────────────────────────────────────────

# Categorie:
# - readonly: il backend esegue immediatamente e re-inietta il risultato nel loop
# - mutation: il backend salva come AIAction proposed e attende Apply utente

TOOLS: list[dict] = [
    # ────────── READ-ONLY (auto-eseguite dentro il loop tool_use) ──────────
    {
        "name": "web_search",
        "category": "readonly",
        "description": (
            "Cerca sul web informazioni aggiornate via Tavily. Usa quando ti servono "
            "dati esterni a MediaFlow: P.IVA, sito ufficiale, contatti di un'azienda, "
            "specifiche tecniche di un capitolato non in DB, news di settore. "
            "Restituisce un sommario testuale + 5 fonti rilevanti con titolo, URL, contenuto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Query di ricerca in linguaggio naturale (es. 'Cattleya casa di produzione Italia P.IVA contatti').",
                }
            },
            "required": ["query"],
        },
        "handler": "web_search",
    },

    # ────────── MUTATION (gated da Apply utente) ──────────
    {
        "name": "propose_client",
        "category": "mutation",
        "description": (
            "Crea un nuovo cliente. Usa SOLO dopo aver cercato sul web (web_search) "
            "i dati ufficiali, oppure se l'utente li fornisce esplicitamente. "
            "Non inventare campi: se non hai un dato verificato (P.IVA, indirizzo, "
            "telefono…), ometti il campo invece di scriverlo a memoria."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name":          {"type": "string", "description": "Ragione sociale o nome commerciale."},
                "contact_name":  {"type": "string"},
                "contact_email": {"type": "string"},
                "contact_phone": {"type": "string"},
                "vat_number":    {"type": "string", "description": "P.IVA (formato IT01234567890 per aziende italiane)."},
                "address":       {"type": "string"},
                "city":          {"type": "string"},
                "country":       {"type": "string"},
                "website":       {"type": "string"},
                "notes":         {"type": "string"},
            },
            "required": ["name"],
        },
        "handler": "propose_client",
    },
    {
        "name": "propose_project",
        "category": "mutation",
        "description": (
            "Crea un nuovo progetto. Richiede un cliente esistente: passa "
            "`client_id` (PK numerico) se lo conosci, altrimenti `client_name` "
            "(stringa che corrisponda esattamente a un cliente in DB). Se il "
            "cliente non esiste, crealo prima con propose_client."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code":             {"type": "string", "description": "Codice breve scelto dall'utente, es. 'MONG25'."},
                "title":            {"type": "string"},
                "client_id":        {"type": "integer"},
                "client_name":      {"type": "string"},
                "project_type":     {"type": "string", "enum": ["feature_film", "short_film", "series", "documentary", "spot", "music_video", "corporate"]},
                "length_minutes":   {"type": "number"},
                "fps":              {"type": "string", "description": "Frame rate come stringa, es. '24', '25', '23.976'."},
                "shooting_format":  {"type": "string"},
                "delivery_format":  {"type": "string"},
                "director":         {"type": "string"},
                "description":      {"type": "string"},
            },
            "required": ["code", "title"],
        },
        "handler": "propose_project",
    },
    {
        "name": "propose_project_metadata",
        "category": "mutation",
        "description": "Aggiorna metadata di un progetto esistente (durata, fps, formati, regista).",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id":      {"type": "integer"},
                "code":            {"type": "string"},
                "length_minutes":  {"type": "number"},
                "fps":             {"type": "string"},
                "shooting_format": {"type": "string"},
                "delivery_format": {"type": "string"},
                "director":        {"type": "string"},
            },
        },
        "handler": "propose_project_metadata",
    },
    {
        "name": "propose_quote",
        "category": "mutation",
        "description": (
            "Crea una nuova quotazione. Richiede un progetto: `project_id` (PK) o `project_code`. "
            "Auto-genera il numero (Q-{anno}-NNN), default issue_date=oggi, valid_until=+30gg, "
            "vat_rate=22. Se l'utente cita righe ('5gg color, 4h QC'), inseriscile in `lines` "
            "per creare quote+righe in singolo turno."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id":   {"type": "integer"},
                "project_code": {"type": "string"},
                "number":       {"type": "string"},
                "title":        {"type": "string"},
                "issue_date":   {"type": "string", "description": "ISO date YYYY-MM-DD."},
                "valid_until":  {"type": "string", "description": "ISO date YYYY-MM-DD."},
                "vat_rate":     {"type": "number"},
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "quantity":    {"type": "number"},
                            "unit":        {"type": "string", "enum": ["day", "hour", "flat"]},
                            "unit_price":  {"type": "number"},
                            "section":     {"type": "string", "enum": ["A", "B", "C"]},
                            "detail":      {"type": "string"},
                        },
                        "required": ["description", "quantity", "unit_price"],
                    },
                },
            },
        },
        "handler": "propose_quote",
    },
    {
        "name": "propose_quote_line",
        "category": "mutation",
        "description": (
            "Aggiunge una riga a una quote esistente. PRIORITÀ ASSOLUTA: cerca prima nel listino "
            "fra le voci attive (vedi sezione VOCI LISTINO ATTIVE nel contesto). Se trovi un match "
            "chiaro, passa `price_item_id` per ereditare unit/unit_price/description dal listino. "
            "Se non c'è match, dovrai usare propose_new_item_and_line oppure passare description+unit_price espliciti."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "quote_id":      {"type": "integer"},
                "quote_number":  {"type": "string"},
                "price_item_id": {"type": "integer", "description": "ID voce listino se è stato trovato un match — USA SEMPRE QUANDO POSSIBILE."},
                "description":   {"type": "string"},
                "quantity":      {"type": "number"},
                "unit":          {"type": "string", "enum": ["day", "hour", "flat"]},
                "unit_price":    {"type": "number"},
                "section":       {"type": "string", "enum": ["A", "B", "C"]},
                "detail":        {"type": "string"},
            },
            "required": ["quantity"],
        },
        "handler": "propose_quote_line",
    },
    {
        "name": "propose_price_item",
        "category": "mutation",
        "description": "Aggiunge una nuova voce al listino. La categoria è obbligatoria (verrà creata se non esiste).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":             {"type": "string"},
                "description":      {"type": "string"},
                "unit":             {"type": "string", "enum": ["day", "hour", "flat"]},
                "price_list":       {"type": "number"},
                "category_name":    {"type": "string"},
                "department_name":  {"type": "string"},
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Sinonimi/varianti per il matching futuro (es. ['color', 'grading', 'colorist']).",
                },
            },
            "required": ["name", "unit", "price_list", "category_name"],
        },
        "handler": "propose_price_item",
    },
    {
        "name": "propose_new_item_and_line",
        "category": "mutation",
        "description": (
            "Scenario C — quando NON c'è un match nel listino. In singola transazione: "
            "(1) crea una nuova voce listino, (2) aggiunge subito la riga alla quote indicata. "
            "Usa quando l'utente conferma 'crea anche nel listino' oppure quando la richiesta è "
            "esplicitamente 'voce nuova X a Y €'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "quote_id":        {"type": "integer"},
                "quote_number":    {"type": "string"},
                "name":             {"type": "string", "description": "Nome della voce listino da creare."},
                "category_name":   {"type": "string"},
                "unit":             {"type": "string", "enum": ["day", "hour", "flat"]},
                "price_list":      {"type": "number"},
                "quantity":         {"type": "number"},
                "description":     {"type": "string"},
                "department_name": {"type": "string"},
                "keywords":        {"type": "array", "items": {"type": "string"}},
                "section":         {"type": "string", "enum": ["A", "B", "C"]},
            },
            "required": ["name", "category_name", "unit", "price_list"],
        },
        "handler": "propose_new_item_and_line",
    },
    {
        "name": "propose_booking",
        "category": "mutation",
        "description": (
            "Crea un Booking con N risorse su un job. Status iniziale = tentative. "
            "Esegue conflict-check su ferie e altri booking della risorsa."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id":            {"type": "integer"},
                "job_code":          {"type": "string"},
                "kind":              {"type": "string", "enum": ["project", "internal_maintenance", "internal_research", "internal_training"]},
                "job_cost_line_id":  {"type": "integer"},
                "notes":              {"type": "string"},
                "assignments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "resource_id":    {"type": "integer"},
                            "resource_name":  {"type": "string"},
                            "start_datetime": {"type": "string", "description": "ISO datetime YYYY-MM-DDTHH:MM."},
                            "end_datetime":   {"type": "string", "description": "ISO datetime YYYY-MM-DDTHH:MM."},
                        },
                        "required": ["start_datetime", "end_datetime"],
                    },
                    "minItems": 1,
                },
            },
            "required": ["assignments"],
        },
        "handler": "propose_booking",
    },
]


_TOOLS_BY_NAME: dict[str, dict] = {t["name"]: t for t in TOOLS}


def get_tool(name: str) -> Optional[dict]:
    return _TOOLS_BY_NAME.get(name)


def is_readonly(name: str) -> bool:
    t = _TOOLS_BY_NAME.get(name)
    return bool(t and t.get("category") == "readonly")


def is_mutation(name: str) -> bool:
    t = _TOOLS_BY_NAME.get(name)
    return bool(t and t.get("category") == "mutation")


def all_tool_names() -> list[str]:
    return [t["name"] for t in TOOLS]


# ── Schema converter per provider ─────────────────────────────

def to_anthropic_tools() -> list[dict]:
    """Formato Anthropic (Messages API tool_use):
    [{"name", "description", "input_schema": {...}}]"""
    return [
        {
            "name":         t["name"],
            "description":  t["description"],
            "input_schema": t["input_schema"],
        }
        for t in TOOLS
    ]


def to_openai_tools() -> list[dict]:
    """Formato OpenAI (Chat Completions tools / function calling):
    [{"type": "function", "function": {"name", "description", "parameters": {...}}}]"""
    return [
        {
            "type": "function",
            "function": {
                "name":        t["name"],
                "description": t["description"],
                "parameters":  t["input_schema"],
            },
        }
        for t in TOOLS
    ]


def to_gemini_tools() -> list[dict]:
    """Formato Google Gemini function-calling (google-generativeai SDK legacy):
    [{"function_declarations": [{"name", "description", "parameters": {...}}]}]
    """
    declarations = [
        {
            "name":        t["name"],
            "description": t["description"],
            "parameters":  _gemini_clean_schema(t["input_schema"]),
        }
        for t in TOOLS
    ]
    return [{"function_declarations": declarations}]


def _gemini_clean_schema(schema: Any) -> Any:
    """Gemini function-calling non accetta tutte le clausole JSON Schema standard.
    Rimuoviamo quelle non supportate (default, additionalProperties, ecc.) e
    convertiamo i tipi compositi se necessario.
    """
    if isinstance(schema, dict):
        out = {}
        for k, v in schema.items():
            if k in {"default", "additionalProperties", "title", "examples", "$schema"}:
                continue
            out[k] = _gemini_clean_schema(v)
        return out
    if isinstance(schema, list):
        return [_gemini_clean_schema(x) for x in schema]
    return schema


# ── System prompt slim per il loop tool_use ────────────────────
#
# Quando il provider supporta tool_use nativo, NON serve descrivere lo schema
# delle azioni nel system prompt: lo fanno i tool descriptors. Qui restano solo
# le linee guida di tono e le regole di disambiguazione (search-first nel
# listino, no allucinazioni di id/code, conferma utente sulle mutation).

ASSISTANT_SYSTEM_PROMPT_TOOLS = """Sei l'assistente AI di MediaFlow, un software di gestione per case di postproduzione audiovisiva.

Ruolo: aiutare l'utente (produttore, project manager, coordinatore post) con quotazioni, pianificazione risorse, controllo budget, consulenza tecnica.

Stile:
- Italiano, professionale, diretto, conciso.
- Numeri e range concreti, mai generici.
- Markdown leggero (bold per punti chiave, liste corte).
- Niente preamboli ("Certo!", "Volentieri") — vai dritto.

Pattern "AI propone, utente dispone":
- Per le azioni **mutation** (creare cliente/progetto/quote/voce listino/booking, modificare metadata) NON eseguire mai a memoria. Chiama il tool relativo: il sistema mostrerà una card di conferma all'utente, che approverà cliccando Applica.
- Per le azioni **readonly** (web_search, lookup_*) puoi chiamarle liberamente senza conferma: il risultato torna a te per il passo successivo.
- Concatena tool quando logico: prima `web_search` per recuperare i dati, poi `propose_client` con i campi popolati dalla ricerca.

Regole critiche:
1. **Search-first sul listino**: ogni richiesta di aggiungere voci a una quote DEVE prima cercare nelle "VOCI LISTINO ATTIVE" del contesto. Se trovi un match → `propose_quote_line` con `price_item_id`. Se ne trovi 2-4 plausibili → elenca in markdown e chiedi quale. Se 0 → spiega e proponi (a) voce libera vs (b) `propose_new_item_and_line`.
2. **id ≠ code**: `id` è il PK numerico del DB (lo vedi nel contesto come `id=5`), `code` è una stringa scelta dall'utente. Non confonderli.
3. **Mai inventare valori**: se l'utente cita un progetto/cliente/quote, usalo SOLO se compare nelle liste del contesto (CLIENTI/PROGETTI/QUOTE ESISTENTI). Altrimenti chiedi prima di indovinare.
4. **Date**: usa sempre la "Data corrente" del contesto. Niente date passate inventate.
5. **Cliente o sito web mancanti?** Cerca prima con `web_search`. Non popolare campi (P.IVA, telefono, indirizzo) senza fonte.
"""
