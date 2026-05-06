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
            "per creare quote+righe in singolo turno. Ogni riga DOVREBBE legarsi al listino "
            "via `price_item_id` quando un match esiste (anche per voci appena create con "
            "`propose_price_item` — il loro id ti torna come tool_result dopo l'Apply); "
            "una riga libera (senza price_item_id) richiede `description` e `unit_price` espliciti."
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
                            "price_item_id": {"type": "integer", "description": "ID voce listino — usa SEMPRE quando esiste un match (anche per voci appena create). Se valorizzato, description/unit/unit_price sono opzionali e vengono ereditati dal listino."},
                            "description":   {"type": "string"},
                            "quantity":      {"type": "number"},
                            "unit":          {"type": "string", "enum": ["day", "hour", "flat"]},
                            "unit_price":    {"type": "number"},
                            "section":       {"type": "string", "enum": ["A", "B", "C"]},
                            "detail":        {"type": "string"},
                        },
                        "required": ["quantity"],
                    },
                },
            },
        },
        "handler": "propose_quote",
    },
    {
        "name": "update_quote",
        "category": "mutation",
        "description": (
            "Modifica i metadata di una quote esistente: titolo, date (issue/valid_until), "
            "VAT rate, sconto pacchetto, payment_terms, note. NON tocca le righe — per "
            "modificare/aggiungere/rimuovere righe usa propose_quote_line o gli altri tool. "
            "Richiede `quote_id` (PK) o `quote_number` (es. 'Q-2026-001'). Quote in stato "
            "'superseded' (storiche, sostituite da nuova versione) non modificabili."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "quote_id":         {"type": "integer"},
                "quote_number":     {"type": "string"},
                "title":            {"type": "string"},
                "issue_date":       {"type": "string", "description": "ISO YYYY-MM-DD."},
                "valid_until":      {"type": "string", "description": "ISO YYYY-MM-DD."},
                "vat_rate":         {"type": "number", "description": "% IVA (es. 22)."},
                "package_discount": {"type": "number", "description": "Sconto pacchetto in percentuale (es. 10 per -10%)."},
                "payment_terms":    {"type": "string"},
                "notes":            {"type": "string"},
            },
        },
        "handler": "update_quote",
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
    # ────────── SETTINGS (read-only discovery + read + mutation update) ──────────
    {
        "name": "list_settings_schemas",
        "category": "readonly",
        "description": (
            "Elenca tutte le aree configurabili del sistema (orario di lavoro, dati "
            "azienda, ecc.) con i rispettivi field e tipi. Usa questo tool come "
            "PRIMO passo se l'utente chiede di modificare una configurazione: ti "
            "mostra cosa è effettivamente configurabile e dove sta. Non modifica "
            "niente, solo discovery."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "handler": "list_settings_schemas",
    },
    {
        "name": "read_setting",
        "category": "readonly",
        "description": (
            "Legge lo stato corrente di un'area di settings (es. working_hours). "
            "Usalo per sapere il valore attuale prima di proporre una modifica, "
            "così l'utente vede chiaramente il diff (prima → dopo)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Chiave dello schema (es. 'working_hours', 'tenant_settings'). Vedi list_settings_schemas.",
                }
            },
            "required": ["key"],
        },
        "handler": "read_setting",
    },
    {
        "name": "update_setting",
        "category": "mutation",
        "description": (
            "Propone modifiche a un'area di settings. Il sistema mostrerà una card "
            "di conferma con il diff (campo: vecchio → nuovo); l'utente approva "
            "cliccando Applica. Specifica `key` (es. 'working_hours') e `patch` "
            "(dict con SOLO i field da modificare — i campi assenti restano "
            "invariati). Per scoprire field validi e tipi, chiama prima "
            "list_settings_schemas + read_setting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Chiave schema (vedi list_settings_schemas).",
                },
                "patch": {
                    "type": "object",
                    "description": (
                        "Dict {field_key: nuovo_valore}. Solo i field da cambiare. "
                        "Per i field di tipo 'time' usa 'HH:MM' (es. '08:30'). Per "
                        "boolean usa true/false."
                    ),
                },
            },
            "required": ["key", "patch"],
        },
        "handler": "update_setting",
    },
    {
        "name": "propose_resource",
        "category": "mutation",
        "description": (
            "Crea una nuova risorsa (persona interna/freelance, sala, attrezzatura, "
            "software, veicolo). Richiede `name` e `type`. Per legarla a un reparto, "
            "passa `department_id` (PK numerico) o `department_name` (stringa, match "
            "esatto sui DEPARTMENTS in context). Tariffe (daily_rate, hourly_rate) "
            "opzionali — ometti se non note invece di scrivere zero."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name":            {"type": "string", "description": "Nome persona o etichetta sala/attrezzatura."},
                "type":            {
                    "type": "string",
                    "enum": ["person_internal", "person_freelance", "studio", "equipment", "software", "vehicle"],
                    "description": "Tipo risorsa. person_internal=dipendente, person_freelance=esterno.",
                },
                "department_id":   {"type": "integer"},
                "department_name": {"type": "string", "description": "Nome reparto esatto (alternativa a department_id)."},
                "role":            {"type": "string", "description": "Ruolo nel reparto, es. 'Colorist', 'Mixer', 'Flame Artist'."},
                "description":     {"type": "string"},
                "daily_rate":      {"type": "number"},
                "hourly_rate":     {"type": "number"},
                "email":           {"type": "string"},
                "phone":           {"type": "string"},
                "internal_phone":  {"type": "string", "description": "Interno aziendale (utile per studio/sale)."},
                "color":           {"type": "string", "description": "Colore esadecimale per timeline (es. '#6272f5'), default tema."},
            },
            "required": ["name", "type"],
        },
        "handler": "propose_resource",
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
1. **Search-first sul listino**: ogni richiesta di aggiungere voci a una quote DEVE prima cercare nelle "VOCI LISTINO ATTIVE" del contesto. Se trovi un match → `propose_quote_line` con `price_item_id`. Se ne trovi 2-4 plausibili → elenca in markdown e chiedi quale. Se 0 → spiega e proponi (a) voce libera vs (b) creare voce nuova nel listino.
2. **id ≠ code**: `id` è il PK numerico del DB (lo vedi nel contesto come `id=5`), `code` è una stringa scelta dall'utente. Non confonderli.
3. **Mai inventare valori**: se l'utente cita un progetto/cliente/quote, usalo SOLO se compare nelle liste del contesto (CLIENTI/PROGETTI/QUOTE ESISTENTI). Altrimenti chiedi prima di indovinare.
4. **Date**: usa sempre la "Data corrente" del contesto. Niente date passate inventate.
5. **Cliente o sito web mancanti?** Cerca prima con `web_search`. Non popolare campi (P.IVA, telefono, indirizzo) senza fonte.

**Ordine delle azioni quando si lavora su una quote nuova** (sequenza obbligatoria, ogni step richiede Apply utente):
- (a) **Voci listino mancanti** → proponile UNA ALLA VOLTA con `propose_price_item`. Aspetti che l'utente le applichi: il tool_result conterrà `{price_item_id: N, name, category}` da usare al passo successivo.
- (b) **Quote** → SE non esiste nel context "QUOTE ESISTENTI" per il progetto richiesto, propone `propose_quote` con `lines` inline. Per ogni riga, usa `price_item_id` se la voce è in listino (da context o appena creata in (a)) — qty basta, gli altri campi vengono ereditati. Per voci libere (raro), passa `description` + `unit_price` espliciti. Aspetti l'Apply (riceverai il `quote_id`).
- (c) **Aggiunte successive** → solo dopo che la quote esiste, usa `propose_quote_line` (con `price_item_id` quando applicabile).
NON proporre `propose_new_item_and_line` se la quote non esiste ancora — fallirà perché serve un `quote_id` valido. Per nuove voci listino + nuova quote in unica creazione, segui (a) → (b).

**Settings — modificare configurazioni del sistema** (NUOVO in v3.5.0-alpha.19):
Quando l'utente chiede di **modificare una configurazione** (es. "porta lo straordinario al 35%", "cambia la mia P.IVA", "imposta orario 9-13/14-19"), NON cercare di indovinare se esiste un endpoint dedicato. Usa il flusso generico:
1. **Discovery**: chiama `list_settings_schemas` per scoprire quali aree sono configurabili e con quali field. Si ottiene una lista tipo `[{key:"working_hours", label:"Orario di lavoro", fields:[...]}, {key:"tenant_settings", ...}]`.
2. **Stato corrente**: chiama `read_setting(key="working_hours")` per vedere i valori attuali. Così quando proporrai la modifica avrai chiaro cosa cambia.
3. **Proposta**: chiama `update_setting(key="working_hours", patch={"overtime_multiplier": 1.35})`. Il sistema mostra una card con diff (vecchio → nuovo) e l'utente conferma cliccando Applica. Includi nel `patch` SOLO i campi da modificare; i campi assenti restano invariati.
Se l'utente è vago ("velocizza l'elaborazione"), prima chiarisci con una domanda — non inventare quale setting cambiare.
"""
