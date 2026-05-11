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
                "job_id":           {"type": "integer", "description": "Job di destinazione."},
                "job_cost_line_id": {"type": "integer", "description": "Riga di costo opzionale (cost report sync)."},
                "resource_id":      {"type": "integer", "description": "Risorsa unica per tutte le occorrenze."},
                "rule":             {"type": "string", "description": "DAILY | WEEKDAYS (default) | WEEKENDS | CSV es. 'MON,WED,FRI'"},
                "start_date":       {"type": "string", "description": "Prima data YYYY-MM-DD."},
                "until_date":       {"type": "string", "description": "Ultima data YYYY-MM-DD (inclusa)."},
                "start_time":       {"type": "string", "description": "Orario start HH:MM."},
                "end_time":         {"type": "string", "description": "Orario end HH:MM (no overnight)."},
                "title":            {"type": "string", "description": "Titolo opzionale, default 'Ricorrente {rule}'."},
            },
            "required": ["job_id", "resource_id", "start_date", "until_date", "start_time", "end_time"],
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

**PIANIFICAZIONE — operazioni sulla timeline** (v3.5.0-alpha.50):
Quando l'utente chiede di operare su booking esistenti (spostare, allungare, eliminare), USA i tool dedicati invece di proporre un nuovo booking:
- `propose_move_booking(booking_id, shift_minutes | new_start_date | new_resource_id | assignments_remap)` → "sposta il booking di Luca a martedì pomeriggio", "sposta tutto +1 settimana", "cambia risorsa da Luca a Marco"
- `propose_resize_booking(booking_id, delta_minutes)` → "allunga di 2 ore", "accorcia di mezz'ora"
- `propose_delete_booking(booking_id, reason?)` → "cancella questo booking" (soft-delete, recuperabile dal Cestino)

**PIANIFICAZIONE AVANZATA** (v3.5.0-alpha.54):
- `analyze_conflicts(days?, project_id?, department_id?)` → READONLY: trova overlap orari nei booking di un periodo. Restituisce coppie con suggerimento di risoluzione. USA per "trova i conflitti della prossima settimana", "ci sono sovrapposizioni su Luca?".
- `find_free_slots(duration_minutes, resource_id | department_id, from_date?, days?, work_hours_*)` → READONLY: cerca slot liberi. USA per "quando ho 4h libere su Marco?", "che slot ha il colorist senior questa settimana?".
- `propose_recurring_bookings(job_id, resource_id, rule, start_date, until_date, start_time, end_time)` → MUTATION: crea N booking ricorrenti (lun-ven o regola custom). Le occorrenze in conflitto vengono saltate (non bloccanti). USA per "prenota Luca lun-ven 9-13 da domani al 30 maggio".
- `propose_bulk_move(booking_ids[], shift_minutes)` → MUTATION: sposta N booking di delta uniforme. Atomic. USA per "sposta tutti i booking di questa settimana di +1 ora".

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
7. **Uso del job_cost_line_id**: quando crei booking su un job, prova a collegarlo a una `job_cost_line_id` esistente (visibile nel context del job). Permette al cost report di tracciare le ore correttamente.
8. **JCL fatturate sono LOCKED**: se un booking ha JCL `in_batch`/`billed`/`paid`, le capability move/resize/delete/bulk_move falliscono con errore esplicativo. NON insistere — chiedi al manager di ritirare il batch prima.
"""
