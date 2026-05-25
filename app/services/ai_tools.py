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
            "Crea un Booking con N risorse su un job. BookingState iniziale = tentative. "
            "5 stati esclusivi: tentative → confirmed → in_progress → done | not_done. "
            "Cancelled è soft-delete (azione 'Elimina', non uno stato del selettore). "
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
    # ── v3.5.0-alpha.50: Planning operations su booking esistenti ──
    {
        "name": "propose_move_booking",
        "category": "mutation",
        "description": (
            "Sposta un booking esistente nel tempo e/o cambia risorsa. "
            "Modalità: shift_minutes (delta in minuti, +/-), oppure new_start_date "
            "(ancora a YYYY-MM-DD, sposta tutti gli assignment del delta giornaliero), "
            "oppure new_resource_id (cambia risorsa di TUTTI gli assignment), "
            "oppure assignments_remap (rimappa specifiche risorse). "
            "Conflict check sui nuovi orari pre-apply, atomic. "
            "USA QUESTA per richieste tipo 'sposta il booking di Luca a martedì pomeriggio', "
            "'sposta tutto +1 settimana', 'cambia risorsa da Luca a Marco'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id":        {"type": "integer", "description": "ID booking esistente da spostare. Obbligatorio."},
                "shift_minutes":     {"type": "integer", "description": "Delta in minuti. Positivo=avanti, negativo=indietro. Es. 60=+1h, -1440=-1giorno."},
                "new_start_date":    {"type": "string", "description": "Nuova data di inizio YYYY-MM-DD (alternativa a shift_minutes per ancorare a una data specifica)."},
                "new_resource_id":   {"type": "integer", "description": "Cambia la risorsa di TUTTI gli assignment a questa risorsa."},
                "assignments_remap": {
                    "type": "array",
                    "description": "Rimappa singole risorse (es. [{from_resource_id:1, to_resource_id:5}]).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from_resource_id": {"type": "integer"},
                            "to_resource_id":   {"type": "integer"},
                        },
                        "required": ["from_resource_id", "to_resource_id"],
                    },
                },
            },
            "required": ["booking_id"],
        },
        "handler": "propose_move_booking",
    },
    {
        "name": "propose_resize_booking",
        "category": "mutation",
        "description": (
            "Cambia la durata di un booking esistente: delta_minutes positivo allunga "
            "l'end, negativo accorcia. Per booking split (più assignment), modifica "
            "l'ULTIMO segmento (mantiene la pausa pranzo intatta). USA per richieste "
            "tipo 'allunga di 2 ore', 'accorcia di mezz'ora', 'estendi a fine giornata'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id":    {"type": "integer", "description": "ID booking esistente."},
                "delta_minutes": {"type": "integer", "description": "Delta in minuti. Positivo=allunga end. Es. 120=+2h, -30=-30min."},
            },
            "required": ["booking_id", "delta_minutes"],
        },
        "handler": "propose_resize_booking",
    },
    {
        "name": "propose_delete_booking",
        "category": "mutation",
        "description": (
            "Cancella (soft-delete via status=cancelled) un booking esistente. "
            "Recupero possibile dal Cestino. Le ore done già conteggiate nel cost "
            "report vengono ritirate automaticamente (recompute_for_booking)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {"type": "integer", "description": "ID booking da cancellare."},
                "reason":     {"type": "string", "description": "Motivo (opzionale, salvato come nota nel booking)."},
            },
            "required": ["booking_id"],
        },
        "handler": "propose_delete_booking",
    },
    # ── v3.5.0-alpha.54: Capability avanzate ───────────────────
    {
        "name": "analyze_conflicts",
        "category": "readonly",
        "description": (
            "Analizza conflitti orari nei booking di un periodo (default 14 giorni). "
            "Restituisce coppie di assignment in overlap sulla stessa risorsa, con "
            "minuti di overlap e suggerimento di risoluzione (sposta, cambia risorsa, "
            "split). Filtri opzionali: project_id, department_id. Massimo 50 risultati."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days":          {"type": "integer", "description": "Finestra in giorni dalla data corrente. Default 14."},
                "project_id":    {"type": "integer", "description": "Restringi a un progetto."},
                "department_id": {"type": "integer", "description": "Restringi a un reparto."},
            },
        },
        "handler": "analyze_conflicts",
    },
    {
        "name": "find_free_slots",
        "category": "readonly",
        "description": (
            "Cerca slot liberi per una risorsa (o tutte le risorse di un reparto) "
            "in un periodo, di durata richiesta. Salta sab/dom, rispetta orario "
            "lavorativo (default 09:00–18:00). Usa per 'quando posso prenotare X ore "
            "su risorsa Y?', 'che slot ha il colorist senior questa settimana?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "duration_minutes":  {"type": "integer", "description": "Durata richiesta in minuti."},
                "resource_id":       {"type": "integer", "description": "Risorsa specifica."},
                "department_id":     {"type": "integer", "description": "Tutte le risorse del reparto (alternativa a resource_id)."},
                "from_date":         {"type": "string", "description": "Data inizio YYYY-MM-DD. Default oggi."},
                "days":              {"type": "integer", "description": "Numero giorni da scansionare. Default 7."},
                "work_hours_start":  {"type": "string", "description": "Inizio orario lavorativo HH:MM. Default 09:00."},
                "work_hours_end":    {"type": "string", "description": "Fine orario lavorativo HH:MM. Default 18:00."},
            },
            "required": ["duration_minutes"],
        },
        "handler": "find_free_slots",
    },
    {
        "name": "compute_recurring_date_range",
        "category": "readonly",
        "description": (
            "READONLY. Calcola start_date+until_date ESATTI per una serie ricorrente di "
            "N giorni lavorativi, partendo in avanti o a ritroso da una data ancora. "
            "Conta solo i giorni della `rule` ed esclude festività italiane (skip_holidays). "
            "USA SEMPRE quando l'utente specifica un numero di giorni lavorativi invece di "
            "una data fine: \"36 giorni di dailies a ritroso dal 30 maggio\", \"4 settimane "
            "lun-ven da domani\", \"prenota 10 giornate prima del 15 giugno\". "
            "Restituisce il range pronto per `check_recurring_booking_collisions` e "
            "`propose_recurring_bookings`, più la lista di festività attraversate (da "
            "presentare all'utente per conferma)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "anchor_date":         {"type": "string", "description": "Data ancora YYYY-MM-DD. Se direction=forward è la prima data candidata; se backward è l'ultima."},
                "working_days_count":  {"type": "integer", "description": "Numero di giorni lavorativi target (>0). Festività italiane vengono saltate (skip_holidays default true) — il conteggio rispetta sempre il netto."},
                "direction":           {"type": "string", "description": "forward (default) = anchor è start_date; backward = anchor è until_date."},
                "rule":                {"type": "string", "description": "DAILY | WEEKDAYS (default) | WEEKENDS | CSV es. 'MON,WED,FRI'."},
                "skip_holidays":       {"type": "boolean", "description": "Salta festività italiane + override tenant nel conteggio (default true)."},
            },
            "required": ["anchor_date", "working_days_count"],
        },
        "handler": "compute_recurring_date_range",
    },
    {
        "name": "check_recurring_booking_collisions",
        "category": "readonly",
        "description": (
            "READONLY. Anticipa festività italiane + ferie/malattie + booking esistenti "
            "che cadono nel range di una serie ricorrente che stai per proporre. USA "
            "SEMPRE PRIMA di `propose_recurring_bookings` quando il range copre più di "
            "5 giorni. Se ritorna festività o ferie, mostra all'utente la lista in "
            "italiano e chiedi conferma (saltiamo / cambiamo date) prima di proporre la "
            "creazione effettiva. Stessi parametri di propose_recurring_bookings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "resource_id":  {"type": "integer", "description": "Risorsa singola."},
                "resource_ids": {"type": "array", "items": {"type": "integer"}, "description": "Lista risorse coinvolte."},
                "rule":         {"type": "string", "description": "DAILY|WEEKDAYS|WEEKENDS|CSV (default WEEKDAYS)."},
                "start_date":   {"type": "string", "description": "Prima data YYYY-MM-DD."},
                "until_date":   {"type": "string", "description": "Ultima data YYYY-MM-DD inclusa."},
                "start_time":   {"type": "string", "description": "Orario start HH:MM (default 09:00)."},
                "end_time":     {"type": "string", "description": "Orario end HH:MM (default 18:00)."},
            },
            "required": ["start_date", "until_date"],
        },
        "handler": "check_recurring_booking_collisions",
    },
    {
        "name": "propose_recurring_bookings",
        "category": "mutation",
        "description": (
            "Crea una serie ricorrente di booking (es. lun-ven X→Y per 4 settimane). "
            "Conflict check per ogni occorrenza, le date in conflitto vengono saltate "
            "(non bloccanti). USA per 'prenota Luca lun-ven 9-13 da domani al 30 maggio', "
            "'serie tutti i mercoledì'. Le occorrenze in conflitto restano da "
            "pianificare manualmente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id":           {"type": "integer", "description": "Job di destinazione (preferito). Se assente, sarà risolto da quote_id/quote_number/project_id."},
                "quote_id":         {"type": "integer", "description": "Fallback: quote.id linkata al job (resolver server-side quote.job.id)."},
                "quote_number":     {"type": "string", "description": "Fallback: numero quote (es. 'Q-2026-001')."},
                "project_id":       {"type": "integer", "description": "Fallback: project.id (prende job approved più recente del project)."},
                "job_cost_line_id": {"type": "integer", "description": "OBBLIGATORIO. Riga di costo (lavorazione) del job. Senza JCL il booking non viene attribuito nel cost report. Vedi cost_lines del job."},
                "resource_id":      {"type": "integer", "description": "Risorsa singola (back-compat). Preferire resource_ids quando servono più risorse insieme (persona + studio)."},
                "resource_ids":     {"type": "array", "items": {"type": "integer"}, "description": "PREFERITO se >1 risorsa serve sullo stesso slot (es. colorist + sala color). Crea 1 booking con N assignments — NO double-count CR."},
                "rule":             {"type": "string", "description": "DAILY | WEEKDAYS (default) | WEEKENDS | CSV es. 'MON,WED,FRI'"},
                "start_date":       {"type": "string", "description": "Prima data YYYY-MM-DD."},
                "until_date":       {"type": "string", "description": "Ultima data YYYY-MM-DD (inclusa)."},
                "start_time":       {"type": "string", "description": "Orario start HH:MM."},
                "end_time":         {"type": "string", "description": "Orario end HH:MM (no overnight)."},
                "title":            {"type": "string", "description": "Titolo opzionale, default 'Ricorrente {rule}'."},
                "skip_holidays":    {"type": "boolean", "description": "Salta festività nazionali italiane (default true). Le date festive vengono escluse + listate nella risposta."},
            },
            "required": ["job_cost_line_id", "start_date", "until_date", "start_time", "end_time"],
        },
        "handler": "propose_recurring_bookings",
    },
    {
        "name": "propose_bulk_move",
        "category": "mutation",
        "description": (
            "Sposta N booking di un delta uniforme (positivo=avanti, negativo=indietro). "
            "Conflict check escludendo gli stessi booking della transazione. Atomic: "
            "se uno fallisce, nessuno viene spostato. JCL fatturate (in_batch/billed/paid) "
            "bloccate. USA per 'sposta tutti i booking di Marco di +3 ore', 'shift +1 "
            "settimana per i 5 booking della prossima settimana'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_ids":   {"type": "array", "items": {"type": "integer"}, "description": "Lista ID booking."},
                "shift_minutes": {"type": "integer", "description": "Delta uniforme in minuti."},
            },
            "required": ["booking_ids", "shift_minutes"],
        },
        "handler": "propose_bulk_move",
    },
    {
        "name": "propose_bulk_booking_status_change",
        "category": "mutation",
        "description": (
            "Cambia lo stato (BookingState) di N booking in batch. Tipico: portare a "
            "'done' la prima metà di una serie ricorrente, marcare 'not_done' una "
            "settimana saltata, riportare a 'confirmed' una pianificazione errata. "
            "Atomic per-booking: i booking dentro periodo già fatturato (slice locked) "
            "o JCL in batch di approvazione vengono SKIPPATI (loggati come failed) — "
            "i restanti procedono. Per 'done' viene ricomputato automaticamente il "
            "maturato (recompute_for_booking). Per 'not_done' SERVE `note` (motivo). "
            "Passa `booking_ids` OPPURE `filter` (mutuamente esclusivi): il filtro è "
            "comodo quando hai criteri (job, range, stato corrente) ma non vuoi "
            "enumerare ID. Limite hard: 200 booking per chiamata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_ids": {"type": "array", "items": {"type": "integer"}, "description": "Lista esplicita ID booking. Mutuamente esclusivo con `filter`."},
                "filter": {
                    "type": "object",
                    "description": "Criteri di selezione (alternativa a booking_ids). Almeno uno tra job_id/project_id/resource_id obbligatorio.",
                    "properties": {
                        "job_id":         {"type": "integer", "description": "Limita ai booking di questo job."},
                        "project_id":     {"type": "integer", "description": "Limita ai booking dei job di questo progetto."},
                        "resource_id":    {"type": "integer", "description": "Limita ai booking con questa risorsa in assignments."},
                        "date_from":      {"type": "string", "description": "Solo booking con start_date >= YYYY-MM-DD."},
                        "date_to":        {"type": "string", "description": "Solo booking con start_date <= YYYY-MM-DD."},
                        "current_state":  {"type": "string", "description": "Solo booking attualmente in questo stato (tentative|confirmed|in_progress|done|not_done)."},
                    },
                },
                "new_state": {"type": "string", "description": "Stato target: tentative | confirmed | in_progress | done | not_done. 'done' triggera recompute maturato."},
                "note":      {"type": "string", "description": "OBBLIGATORIO se new_state=not_done (motivo). Altrimenti opzionale (audit summary)."},
            },
            "required": ["new_state"],
        },
        "handler": "propose_bulk_booking_status_change",
    },
    {
        "name": "propose_transmit_to_billing",
        "category": "mutation",
        "description": (
            "Trasmetti il maturato di un progetto come BillingBatch in stato draft. "
            "Equivalente al bottone 'Trasmetti' dal Cost Report. Periodo derivato "
            "automaticamente dai booking done (work_date) se non specificato. USA per "
            "'genera la fattura mensile del progetto X', 'trasmetti a fatturazione'. "
            "Il batch creato passa poi al manager per approvazione + emissione fattura."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id":     {"type": "integer", "description": "ID progetto."},
                "include_extras": {"type": "boolean", "description": "Includi righe extra (lavorazioni oltre quote). Default true."},
                "notes":          {"type": "string", "description": "Note opzionali per il batch."},
            },
            "required": ["project_id"],
        },
        "handler": "propose_transmit_to_billing",
    },
    {
        "name": "query_project_finance",
        "category": "readonly",
        "description": (
            "Aggrega lo stato finanziario di un progetto: quotato, maturato, atteso, "
            "spese, margine, ripartizione fatturazione (not_billed / in_batch / billed / "
            "paid / lost), fatture emesse e incassate. Include top job per scostamento. "
            "USA per 'qual è il margine del progetto X?', 'quanto è già fatturato sul "
            "progetto Y?', 'quanto resta da fatturare?', 'come stiamo a maturato?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "ID del progetto."},
            },
            "required": ["project_id"],
        },
        "handler": "query_project_finance",
    },
    # ────────── SUPPLIER / FATTURE PASSIVE (v3.5.0-alpha.68.5) ──────────
    {
        "name": "propose_supplier",
        "category": "mutation",
        "description": (
            "Crea un nuovo fornitore (commessa esterna / freelance fatturante / "
            "service company). Usa quando l'utente menziona una commessa esterna "
            "non ancora in anagrafica. Solo nome è obbligatorio. Tutti i dati "
            "fiscali (P.IVA, CF, IBAN) e i contatti sono opzionali — l'utente "
            "può completarli in seguito da /suppliers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name":             {"type": "string", "description": "Ragione sociale del fornitore."},
                "vat_number":       {"type": "string"},
                "tax_code":         {"type": "string"},
                "contact_email":    {"type": "string"},
                "contact_phone":    {"type": "string"},
                "address":          {"type": "string"},
                "iban":             {"type": "string"},
                "default_payment_terms_days": {"type": "integer"},
                "notes":            {"type": "string"},
            },
            "required": ["name"],
        },
        "handler": "propose_supplier",
    },
    {
        "name": "propose_supplier_invoice",
        "category": "mutation",
        "description": (
            "Registra una fattura passiva (ricevuta da un fornitore). Richiede "
            "fornitore (per id o name; se name non esiste non crea — usa prima "
            "propose_supplier), numero, data emissione, imponibile. IVA default 22%. "
            "Può essere linkata a project_id (più granulare) o job_id o "
            "job_cost_line_id per integrare nel cost-report. amount_paid opzionale "
            "(per fatture già parzialmente saldate al momento dell'inserimento)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "supplier_id":      {"type": "integer", "description": "PK fornitore. Preferito se conosciuto."},
                "supplier_name":    {"type": "string", "description": "Fallback se id non noto. Deve corrispondere esattamente."},
                "number":           {"type": "string", "description": "Numero fattura del fornitore."},
                "issue_date":       {"type": "string", "description": "YYYY-MM-DD."},
                "due_date":         {"type": "string", "description": "YYYY-MM-DD. Se omesso, calcolato da default_payment_terms_days del fornitore."},
                "amount_net":       {"type": "number", "description": "Imponibile in EUR."},
                "vat_rate":         {"type": "number", "description": "Aliquota IVA %. Default 22."},
                "currency":         {"type": "string", "description": "Default EUR."},
                "amount_paid":      {"type": "number", "description": "Default 0."},
                "project_id":       {"type": "integer"},
                "job_id":           {"type": "integer"},
                "job_cost_line_id": {"type": "integer"},
                "notes":            {"type": "string"},
            },
            "required": ["number", "issue_date", "amount_net"],
        },
        "handler": "propose_supplier_invoice",
    },
    # ────────── CAPITOLATI → QUOTE (v3.5.0-alpha.69) ──────────
    {
        "name": "propose_quote_from_template",
        "category": "mutation",
        "description": (
            "Aggiunge bulk righe a una quotazione esistente caricandole da un "
            "DeliveryTemplate (suggested_items). Usa quando l'utente dice "
            "'carica il template X sulla quote Y' o 'aggiungi le voci del "
            "template Netflix alla quote Q-2026-12'. Skip duplicati e voci "
            "con price_item mancante. Idempotente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "template_id":   {"type": "integer", "description": "PK DeliveryTemplate."},
                "template_code": {"type": "string", "description": "Fallback se id ignoto (es. 'NETFLIX-IMF')."},
                "quote_id":      {"type": "integer", "description": "PK Quote destinazione."},
                "quote_number":  {"type": "string", "description": "Fallback se id ignoto (es. 'Q-2026-12')."},
                "price_level":   {"type": "string", "enum": ["list_price", "average", "low"], "description": "Default list_price."},
            },
            "required": [],
        },
        "handler": "propose_quote_from_template",
    },
    # ────────── QUERY SUPPLIER (v3.5.0-alpha.71) ──────────
    {
        "name": "query_suppliers",
        "category": "readonly",
        "description": (
            "Lista fornitori con KPI outstanding + overdue count. "
            "Filtri: q (ricerca per nome contiene), only_with_outstanding "
            "(solo fornitori con € da pagare). USA per domande tipo "
            "'quali fornitori devo pagare?', 'lista i fornitori con scaduto', "
            "'cerca fornitore X'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Filtro ricerca per nome."},
                "only_with_outstanding": {"type": "boolean"},
            },
        },
        "handler": "query_suppliers",
    },
    {
        "name": "query_supplier_invoices",
        "category": "readonly",
        "description": (
            "Lista fatture passive filtrate. Filtri: supplier_id o "
            "supplier_name, status (unpaid/partial/paid/cancelled), "
            "only_overdue (due_date passata e non pagate), project_id, "
            "job_id. USA per 'quali fatture passive sono scadute?', "
            "'fatture del fornitore X', 'fatture passive del progetto Y'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "supplier_id":   {"type": "integer"},
                "supplier_name": {"type": "string"},
                "status":        {"type": "string", "enum": ["unpaid", "partial", "paid", "cancelled"]},
                "only_overdue":  {"type": "boolean"},
                "project_id":    {"type": "integer"},
                "job_id":        {"type": "integer"},
                "limit":         {"type": "integer", "description": "Default 30, max 100."},
            },
        },
        "handler": "query_supplier_invoices",
    },
    # ────────── ASSET INVENTORY (v3.5.0-alpha.76) ──────────
    {
        "name": "query_physical_assets",
        "category": "readonly",
        "description": (
            "Cerca asset fisici (LTO/HDD/CRU/Blu-Ray/case) con filtri: "
            "kind, owner_type (internal/client/supplier), client_id, "
            "logistics_status (in_storage/transit_out/delivered_external), "
            "q (label/serial/barcode). USA per 'trovami l\\'HDD X', "
            "'quali asset del cliente Y abbiamo in deposito?', 'LTO disponibili'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind":             {"type": "string", "enum": ["lto","hdd","cru","bluray","dvd","case","other"]},
                "owner_type":       {"type": "string", "enum": ["internal","client","supplier","third_party"]},
                "client_id":        {"type": "integer"},
                "logistics_status": {"type": "string"},
                "q":                {"type": "string"},
                "limit":            {"type": "integer"},
            },
        },
        "handler": "query_physical_assets",
    },
    {
        "name": "query_asset_contents",
        "category": "readonly",
        "description": (
            "Lista digital asset contenuti in un PhysicalAsset (cosa c'è "
            "dentro l'HDD X). Mostra storico se include_removed=true. "
            "USA per 'cosa c\\'è sul disco del cliente X?', 'storico "
            "contenuti dell\\'LTO 042'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "physical_asset_id": {"type": "integer"},
                "label":             {"type": "string", "description": "Fallback se id ignoto."},
                "include_removed":   {"type": "boolean"},
            },
            "required": [],
        },
        "handler": "query_asset_contents",
    },
    # ────────── EMAIL SEND (v3.5.0-alpha.130) ──────────
    {
        "name": "propose_send_invoice_email",
        "category": "mutation",
        "description": (
            "Invia una fattura via email al cliente (admin_email + fallback "
            "contact_email) con PDF allegato. Richiede SMTP configurato in "
            ".env (SMTP_HOST/PORT/USER/PASS/FROM). Esempi: 'invia fattura "
            "2026-00042 al cliente', 'manda la NC TD04 a admin@horizon.it'. "
            "Conferma utente obbligatoria (Apply). 409 se fattura cancelled, "
            "400 se cliente senza email."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "integer", "description": "ID fattura."},
                "invoice_number": {"type": "string", "description": "Fallback se ID ignoto: cerca per number."},
                "recipient_override": {"type": "string", "description": "Email destinatario diverso da admin_email del cliente. Opzionale."},
            },
            "required": [],
        },
        "handler": "propose_send_invoice_email",
    },
    # ────────── FILESYSTEM (v3.5.0-alpha.129) ──────────
    {
        "name": "query_filesystem",
        "category": "readonly",
        "description": (
            "Lista file/cartelle in un path filesystem (asset library locale). "
            "Solo path autorizzati nella whitelist tenant (configurati in "
            "/settings → fs-scan-paths). Filtri: glob_pattern (es. '*.mov', "
            "'**/dolby_*.xml'), max_depth, max_results. Ritorna metadata: "
            "nome, size, mtime, mime_type. USA per: 'cosa c\\'è in "
            "/mnt/asset_library/PROJ-2024-0001/?', 'cerca tutti i .mov "
            "consegnati', 'lista deliverable nel deposito disco'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path assoluto (deve essere dentro la whitelist tenant)."},
                "glob_pattern": {"type": "string", "description": "Pattern glob opzionale (es. '*.mov', '*.xml'). Default: tutti."},
                "max_depth": {"type": "integer", "description": "Profondità max ricorsione. Default 4, max 8."},
                "max_results": {"type": "integer", "description": "Limite risultati. Default 100, max 500."},
            },
            "required": ["path"],
        },
        "handler": "query_filesystem",
    },
    {
        "name": "propose_asset_movement",
        "category": "mutation",
        "description": (
            "Registra movimento ingresso/uscita per un PhysicalAsset. "
            "Auto-genera DDT (BB-YYYY-NNN). Esempi: 'registra ritiro disco "
            "cliente X', 'spedisco LTO 042 al laboratorio Y'. "
            "Conferma consegna separata (utente, post-arrivo)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "physical_asset_id": {"type": "integer"},
                "asset_label":       {"type": "string", "description": "Fallback se id ignoto."},
                "movement_type":     {"type": "string", "enum": ["ingest","outgest","transfer","return_to_client","return_from_client"]},
                "from_party":        {"type": "string"},
                "to_party":          {"type": "string"},
                "carrier":           {"type": "string"},
                "tracking_number":   {"type": "string"},
                "package_count":     {"type": "integer"},
                "total_weight_kg":   {"type": "number"},
                "notes":             {"type": "string"},
            },
            "required": ["movement_type"],
        },
        "handler": "propose_asset_movement",
    },
    # v3.5.0-alpha.171.6 (Sprint 2 Step 8) — Phantom / Consuntivo workflow
    {
        "name": "propose_promote_phantom",
        "category": "mutation",
        "description": (
            "Promuove una Quotazione a Consuntivo (phantom) STANDBY a quote effettiva: "
            "is_phantom passa a False, phantom_status a 'promoted'. Lo status quote (di "
            "solito approved) resta invariato. Pattern: usa quando il commerciale/account "
            "manager decide che la Consuntivo è valida come quote di riferimento."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "quote_id": {"type": "integer", "description": "PK numerico della Consuntivo da promuovere"},
            },
            "required": ["quote_id"],
        },
        "handler": "propose_promote_phantom",
    },
    {
        "name": "propose_merge_phantom",
        "category": "mutation",
        "description": (
            "Accorpa una Quotazione a Consuntivo (source) in una quote target (anche approvata). "
            "Crea una nuova VERSIONE della target con le righe Consuntivo aggiunte. La target "
            "passa a superseded, la Consuntivo a phantom_status=merged_into. Pattern: usa quando "
            "il commerciale decide che le voci Consuntivo vanno integrate nella quote ufficiale. "
            "Source e target devono appartenere allo stesso progetto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_quote_id": {"type": "integer", "description": "PK Consuntivo standby da accorpare"},
                "target_quote_id": {"type": "integer", "description": "PK quote target (non-phantom, stesso progetto)"},
            },
            "required": ["source_quote_id", "target_quote_id"],
        },
        "handler": "propose_merge_phantom",
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

**Quotazione a Consuntivo (ex Phantom Quote, v3.5.0-alpha.171)**: quote speciale per voci aggiunte via booking su progetto senza quote attiva. 1 sola Consuntivo standby per progetto. Voci `quantity_quoted=0`, ore reali dai booking via JCL. Lifecycle: standby → promoted (diventa quote effettiva) | merged_into (accorpata in altra quote, crea versione).
- NON proporre creazione di una nuova Consuntivo se il progetto ha già `phantom_status=standby` o quote attiva (sent/approved). Il sistema rifiuterà con 409.
- Quando l'utente chiede di **"promuovere"** o **"rendere ufficiale"** la Consuntivo → `propose_promote_phantom(quote_id)`.
- Quando l'utente chiede di **"accorpare"** o **"unire"** la Consuntivo in una quote esistente → `propose_merge_phantom(source_quote_id, target_quote_id)`. Crea nuova versione della target. Usabile anche su target approvata.

**Settings — modificare configurazioni del sistema** (NUOVO in v3.5.0-alpha.19):
Quando l'utente chiede di **modificare una configurazione** (es. "porta lo straordinario al 35%", "cambia la mia P.IVA", "imposta orario 9-13/14-19"), NON cercare di indovinare se esiste un endpoint dedicato. Usa il flusso generico:
1. **Discovery**: chiama `list_settings_schemas` per scoprire quali aree sono configurabili e con quali field. Si ottiene una lista tipo `[{key:"working_hours", label:"Orario di lavoro", fields:[...]}, {key:"tenant_settings", ...}]`.
2. **Stato corrente**: chiama `read_setting(key="working_hours")` per vedere i valori attuali. Così quando proporrai la modifica avrai chiaro cosa cambia.
3. **Proposta**: chiama `update_setting(key="working_hours", patch={"overtime_multiplier": 1.35})`. Il sistema mostra una card con diff (vecchio → nuovo) e l'utente conferma cliccando Applica. Includi nel `patch` SOLO i campi da modificare; i campi assenti restano invariati.
Se l'utente è vago ("velocizza l'elaborazione"), prima chiarisci con una domanda — non inventare quale setting cambiare.

**PIANIFICAZIONE — operazioni sulla timeline** (v3.5.0-alpha.50):
Quando l'utente chiede di operare su booking esistenti (spostare, allungare, eliminare), USA i tool dedicati invece di proporre un nuovo booking:
- `propose_move_booking(booking_id, shift_minutes | new_start_date | new_resource_id | assignments_remap)` → "sposta il booking di Luca a martedì pomeriggio", "sposta tutto +1 settimana", "cambia risorsa da Luca a Marco"
- `propose_resize_booking(booking_id, delta_minutes)` → "allunga di 2 ore", "accorcia di mezz'ora"
- `propose_delete_booking(booking_id, reason?)` → "cancella questo booking" (soft-delete, recuperabile dal Cestino)

**PIANIFICAZIONE AVANZATA** (v3.5.0-alpha.54):
- `analyze_conflicts(days?, project_id?, department_id?)` → READONLY: trova overlap orari nei booking di un periodo. Restituisce coppie con suggerimento di risoluzione. USA per "trova i conflitti della prossima settimana", "ci sono sovrapposizioni su Luca?".
- `find_free_slots(duration_minutes, resource_id | department_id, from_date?, days?, work_hours_*)` → READONLY: cerca slot liberi. USA per "quando ho 4h libere su Marco?", "che slot ha il colorist senior questa settimana?".
- `compute_recurring_date_range(anchor_date, working_days_count, direction, rule, skip_holidays)` → READONLY: calcola start/until ESATTI per N giorni lavorativi forward/backward dall'ancora, festività italiane saltate dal conteggio. USA SEMPRE prima di `propose_recurring_bookings` quando l'utente dà un numero di giornate ("36 giorni di dailies a ritroso dal 30 maggio", "4 settimane lun-ven da domani") invece di una data fine esplicita.
- `propose_recurring_bookings(job_id, resource_id, rule, start_date, until_date, start_time, end_time)` → MUTATION: crea N booking ricorrenti (lun-ven o regola custom). Le occorrenze in conflitto vengono saltate (non bloccanti). USA per "prenota Luca lun-ven 9-13 da domani al 30 maggio".
- `propose_bulk_move(booking_ids[], shift_minutes)` → MUTATION: sposta N booking di delta uniforme. Atomic. USA per "sposta tutti i booking di questa settimana di +1 ora".
- `propose_bulk_booking_status_change(booking_ids[] | filter{job_id|project_id|resource_id, date_from?, date_to?, current_state?}, new_state, note?)` → MUTATION: cambia stato di N booking (tentative/confirmed/in_progress/done/not_done). USA per "porta a done la prima metà della serie", "marca not_done la settimana saltata". Booking dentro fatture/batch skippati con motivo. Per `not_done` `note` è obbligatorio.

**FATTURAZIONE** (v3.5.0-alpha.54):
- `query_project_finance(project_id)` → READONLY: stato finanziario completo del progetto (quotato, maturato, atteso, spese, margine, fatturato, incassato, ripartizione billing_status). USA per "qual è il margine del progetto X?", "quanto resta da fatturare?", "come stiamo a maturato?".
- `propose_transmit_to_billing(project_id, include_extras?, notes?)` → MUTATION: trasmette il maturato del progetto come BillingBatch in stato draft. Il periodo è derivato auto dai booking done. Equivalente al bottone Trasmetti dal cost report. USA per "genera la fattura mensile del progetto Ligas", "trasmetti a fatturazione il progetto X".

Per **CREARE** nuovi booking singoli usa `propose_booking` (esistente).

**Regole pianificazione:**
1. **Consulta sempre la sezione "PIANIFICAZIONE VIVA" del contesto** (se presente) PRIMA di proporre azioni: vedi booking esistenti, conflitti attuali, carico per risorsa, ferie/festività, job critici. Riferisci sempre booking per `id` (es. "booking #42") quando puoi.
2. **Rispetta indisponibilità**: se la sezione INDISPONIBILITÀ mostra ferie/malattia di una risorsa nel periodo richiesto, NON proporre booking lì. Spiega all'utente e suggerisci alternative.
3. **Carico bilanciato**: se la sezione CARICO mostra una risorsa al 🔴 (>105% capacità), evita di aggiungere altri booking su quella. Suggerisci una risorsa 🟢 (<80%).
4. **Conflict awareness**: prima di proporre booking nuovi su una finestra contesa, considera `analyze_conflicts` per dare un quadro chiaro all'utente. Non sovrascrivere conflitti esistenti.
5. **Spiega il perché**: dopo aver proposto un'azione di pianificazione, aggiungi 1-2 frasi che giustificano la scelta (es. "Ho scelto martedì perché Luca è libero e non ci sono festività nel periodo").
6. **Booking ricorrenti**: per richieste tipo "online editor lun-ven 9-18 per 4 settimane", USA `propose_recurring_bookings` (un singolo Apply) invece di proporre 20 booking singoli.

   **Conteggio per giornate (NON per data fine)** — quando l'utente dice "N giornate" / "N giorni di X" / "a ritroso da Y" / "per le prossime 4 settimane" senza una data fine esplicita, NON stimare il range a mente (errore tipico: sbagliare conteggio festività). Chiama SEMPRE `compute_recurring_date_range` con anchor_date + working_days_count + direction (forward|backward). Restituisce start/until esatti pronti per il passo successivo + lista festività attraversate (cita all'utente per trasparenza).

   **PRIMA di proporre la creazione** (quando il range copre >5 giorni o tocca aprile/maggio/giugno/agosto/dicembre — periodi con festività), chiama SEMPRE `check_recurring_booking_collisions` con stessi parametri. Se la response contiene:
   - `holidays[]` non vuoto → cita le festività in italiano ("il 2 giugno cade Festa della Repubblica") e chiedi: *vuoi saltare quei giorni o cambiare le date?*
   - `unavailabilities[]` non vuoto → cita ferie/malattia per risorsa ("Luca è in ferie il 5 giugno") e chiedi: *salto, sposto su altra risorsa, o cambio range?*
   - `existing_conflicts[]` non vuoto → cita conflitti ("Conforming 1 ha già booking #42 il 3 giugno") e chiedi alternativa
   Solo dopo conferma esplicita utente, chiama `propose_recurring_bookings` (skip_holidays resta true).

   **Cambio stato in batch** — quando l'utente chiede di portare a "done"/"in lavorazione"/"non fatto" un gruppo di booking ("marca done la prima metà", "metti in lavorazione tutti i booking di Luca di questa settimana"), USA `propose_bulk_booking_status_change`. NON dire mai "non disponibile via AI, fallo a mano dalla timeline". Passa `filter` (job_id + date_from/date_to + current_state) se hai criteri chiari; passa `booking_ids[]` se hai già la lista esplicita dal context. Per `not_done` chiedi prima il motivo all'utente — è obbligatorio.
7. **Linguaggio umano, mai ID tecnici nelle risposte** (v3.5.0-alpha.172.24): NON menzionare mai all'utente termini tipo `job_cost_line_id`, `quote_id`, `project_id`, `JCL`, `propose_*`, `tool_result`, `payload`, "fallback". L'utente è un produttore, non uno sviluppatore. USA invece parole umane: "lavorazione di color grading", "quotazione Q-DNHP-v3", "fattura passiva n. 42", "progetto Mare Nostrum". Anche nelle conferme/errori riformula in italiano leggibile.

8. **Lavorazione obbligatoria su booking — chiedi opzioni, NON ID** (v3.5.0-alpha.172.24): se per proporre un booking ti serve sapere a quale lavorazione del job collegarlo (campo `job_cost_line_id` del tool) E nel contesto vedi più candidati plausibili, NON dire "qual è il `job_cost_line_id`?". USA invece:
   - Cerca la JCL nel context del job (sezione JOB ATTIVI / lavorazioni)
   - Se 1 sola JCL plausibile per il task richiesto (es. "color grading" → unica JCL con price_item.name che contiene "color") → usala direttamente senza chiedere
   - Se 2-4 plausibili → presenta LISTA NUMERATA leggibile in markdown, es:

     > Su quale lavorazione vuoi schedulare il color grading?
     > 1. **Color grading SDR** (10 giornate quotate)
     > 2. **Color grading HDR Dolby Vision** (5 giornate quotate)
     > 3. **Conforming online** (8 giornate quotate)

     Aspetta la scelta utente (numero o nome), poi proponi il tool con l'id corretto.
   - Se nessuna JCL match (job vuoto) → spiega all'utente "il job non ha lavorazioni create — vuoi prima aggiungerne una?" e proponi `propose_quote_line` o `propose_new_item_and_line`.

9. **JCL fatturate sono LOCKED**: se un booking ha JCL `in_batch`/`billed`/`paid`, le capability move/resize/delete/bulk_move falliscono. NON insistere — riformula all'utente: "Quella lavorazione è già fatturata, chiedi al commerciale di ritirare il batch."

10. **MATCH RUOLO RISORSA con tipo lavorazione**: la sezione `RISORSE ATTIVE` mostra `role` di ogni risorsa (colorist, online editor, sound designer, ...) e `type` (person_internal/studio/equipment/...). USA il `role` per decidere chi fa cosa. Es. "color grading" → cerca risorsa con role `colorist`. Es. "online conform" → role `online editor`. Per studio/sale: usa il `type=studio` filtrato per `department` coerente. NON inventare ruoli/risorse non presenti.

11. **Job da QUOTE**: la sezione `JOB ATTIVI` mappa job ↔ quote ↔ progetto. Quando proponi booking, usa il job corretto del progetto richiesto. Risoluzione server-side: puoi anche passare quote o progetto e il sistema risolve. Per l'utente parla solo di "progetto X / quotazione Y", non di id.
"""
