"""
MediaFlow — AI Assistant (copilot context-aware con pattern AI propone, utente dispone)

Ogni risposta dell'AI può contenere:
- testo libero in markdown (mostrato all'utente nel drawer chat)
- una o più "proposed actions" in blocchi ```action ...``` JSON, che il backend
  estrae, valida, salva come AIAction in DB e restituisce al frontend per conferma.

Le capability supportate nel primo push (Fase 2 step B):
- propose_price_item       — proporre nuova voce di listino
- propose_client           — proporre creazione cliente
- propose_quote_line       — proporre riga su quote attiva
- propose_project_metadata — aggiornare metadata progetto
- web_search               — cercare info via Tavily (read-only)
"""
from __future__ import annotations
import json
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Project, Quote, Job, PriceItem, PriceCategory, Client, Resource,
    Asset, Department,
)
from app.models.models import AIAction
from app.services.ai_provider import get_provider_for_user, safe_json_parse

logger = logging.getLogger(__name__)


# ── System prompt ────────────────────────────────────────────

ASSISTANT_SYSTEM_PROMPT = """Sei l'assistente AI di MediaFlow, un software di gestione per case di postproduzione audiovisiva.

Il tuo ruolo: aiutare l'utente (produttore, project manager, coordinatore post) con:
- Consulenza tecnica su postproduzione cinema/TV/pubblicità
- Pianificazione risorse e tempi
- Suggerimenti su quotazioni e negoziazione
- Controllo di congruità: budget vs scope, rischi di sforamento
- Risposte a domande operative (formati DCP, codec, flussi di mastering, etc.)

Linee guida:
- Rispondi in italiano con tono professionale ma diretto.
- Sii concreto: numeri, range, esempi reali del settore.
- Se hai il contesto (progetto, quote, listino), usalo attivamente.
- Non inventare dati specifici dell'utente: se non presenti, chiedili.
- Formatta con markdown leggero (bold per punti chiave, liste per elenchi).
- Evita preamboli inutili: vai dritto al punto.

PATTERN "AI PROPONE, UTENTE DISPONE":
Tu non puoi modificare direttamente il database. Quando l'utente ti chiede di
fare qualcosa di concreto (creare cliente, progetto, voce listino, quote,
riga su quote, aggiornare metadata progetto, cercare info), tu PROPONI l'azione
in un blocco strutturato e l'utente la conferma cliccando "Applica".

SINTASSI DEL BLOCCO AZIONE (regola rigida, devi seguirla esattamente):

```action
{
  "type": "<uno dei tipi sotto>",
  "title": "Frase breve che descrive l'azione",
  "data": { ... payload ... }
}
```

I tre apici di apertura ` ```action ` e di chiusura ` ``` ` sono OBBLIGATORI
(senza spazio dopo il backtick). Senza i tre apici il sistema non riconosce l'azione.

CAPABILITY DISPONIBILI E SCHEMA `data`:

- propose_client: {name, contact_name?, contact_email?, contact_phone?, vat_number?, address?, city?, country?, website?, notes?}
- propose_project: {code (stringa, es. "MONG25"), title (es. "Mongoloid"), client_id (numero PK del cliente) OPPURE client_name (stringa), project_type? ("feature_film"|"short_film"|"series"|"documentary"|"spot"|"music_video"|"corporate"), length_minutes? (numero), fps? (es. "24"|"25"), shooting_format?, delivery_format?, director?, description?}
- propose_project_metadata: {project_id (numero PK) OPPURE code (stringa), length_minutes?, fps?, shooting_format?, delivery_format?, director?}
- propose_quote: {project_id (numero PK) OPPURE project_code (stringa), number? (auto Q-{anno}-NNN se manca), title? (default = titolo progetto), issue_date? (default oggi), valid_until? (default +30gg), vat_rate? (default 22), lines? (lista di righe — vedi sotto)}
   * lines è opzionale: se presente, crea quote+righe in unica transazione (un solo Apply)
   * ogni riga: {description, quantity (numero), unit ("day"|"hour"|"flat", default "day"), unit_price (numero), section? ("A"|"B"|"C", default "A"), detail?}
- propose_quote_line: {quote_id (numero PK) OPPURE quote_number (stringa), description, quantity (numero), unit ("day"|"hour"|"flat"), unit_price (numero), section? ("A"|"B"|"C"), detail?}
- propose_price_item: {name, description?, unit ("day"|"hour"|"flat"), price_list (numero), category_name (richiesto), keywords? (lista di stringhe), department_name?}
- web_search: {query}

REGOLE CRITICHE:
1. **id ≠ code**. `id` è un numero (PK auto-incrementale del DB, lo trovi nei contesti come `(id=5)`). `code` è una stringa scelta dall'utente (es. "MONG25"). Se non vedi un `id` numerico nel contesto, usa il campo `code`/`*_code` nel payload.
2. I numeri JSON NON vanno tra virgolette. `{"length_minutes": 90}` corretto, `{"length_minutes": "90"}` sbagliato.
3. **NON inventare valori**. Se l'utente cita un progetto/cliente/quote, usa SOLO i valori che vedi nella sezione "DB" del contesto (PROGETTI ESISTENTI, CLIENTI ESISTENTI). Se non lo trovi, CHIEDI all'utente invece di indovinare un code.
4. Per creare un progetto serve il cliente: usa `client_id` se conosci il PK, altrimenti `client_name` (verrà cercato per nome esatto, e se non esiste l'azione fallirà).
5. Per le date usa la "Data corrente" che vedi nel contesto. NON inventare anni passati (es. 2023) se la data corrente è 2026.
6. Per propose_quote: se l'utente dà solo descrizioni di righe ("5gg color, 4h QC"), inseriscile direttamente in `lines` (singolo Apply che crea quote+righe). Non serve `number` né `title`: vengono auto-generati. Se non vuoi specificare `number`, **OMETTI il campo** invece di mettere `null`.
7. Una sola azione per turno tipicamente. Più azioni solo se logicamente concatenate.
8. Se mancano dati essenziali (es. nome cliente per creare cliente nuovo), CHIEDI prima di indovinare.
9. Per domande informative (consulenza tecnica, dubbi su workflow) rispondi normalmente senza blocchi action.

**FORMATO JSON OBBLIGATORIO** (gli errori qui rendono l'azione invisibile all'utente):
- ZERO commenti: niente `// commento`, niente `/* commento */`. Il JSON è strict, i commenti rompono il parser.
- ZERO virgole finali: l'ultima coppia chiave-valore di un oggetto NON deve avere `,` dopo.
- Stringhe sempre tra virgolette doppie `"`, mai apici singoli `'`.
- Numeri senza virgolette (`22`, non `"22"`).
- Spiegazioni libere o note vanno PRIMA o DOPO il blocco ```action ...```, mai dentro il JSON.
"""


# ── Context builder ──────────────────────────────────────────

def _short_money(v) -> str:
    try: return f"€{float(v):,.0f}"
    except Exception: return "€0"


def build_context(db: Session,
                  project_id: Optional[int] = None,
                  quote_id: Optional[int] = None,
                  job_id: Optional[int] = None,
                  page: Optional[str] = None) -> str:
    """
    Costruisce il blocco di contesto da iniettare nel system prompt.
    Se è specificato project/quote/job, mostra il dettaglio dell'entità.
    Altrimenti (o in aggiunta) restituisce una vista d'insieme breve.
    """
    parts = []

    # Entità in canvas (priorità alta, dettaglio alto)
    if project_id:
        p = db.query(Project).filter(Project.id == project_id).first()
        if p:
            parts.append(f"""PROGETTO ATTIVO (id={p.id}):
- Codice: {p.code} | Titolo: {p.title}
- Tipologia: {p.project_type or 'n/d'} | Cliente: {p.client.name if p.client else 'n/d'}
- Durata: {p.length_minutes or '?'} min @ {p.fps or '?'} fps
- Ripresa: {p.shooting_format or 'n/d'} | Consegna: {p.delivery_format or 'n/d'}
- Regista: {p.director or 'n/d'} | Deadline: {p.delivery_deadline or 'n/d'} | Stato: {p.status}""")

    if quote_id:
        q = db.query(Quote).filter(Quote.id == quote_id).first()
        if q:
            parts.append(f"""QUOTAZIONE ATTIVA (id={q.id}, numero {q.number}):
- Titolo: {q.title}
- Totale netto: {_short_money(q.total_after_discount)} | Con IVA: {_short_money(q.total_with_vat)}
- Sconto pacchetto: {(q.package_discount or 0)*100:.0f}% | Voci: {len(q.lines)} | Stato: {q.status}""")
            if q.lines:
                lines = []
                for l in q.lines[:20]:
                    lines.append(f"  [{l.position}] {l.description}: {l.quantity} {l.unit} x {_short_money(l.unit_price)} = {_short_money(l.total)}")
                parts.append("Voci:\n" + "\n".join(lines))

    if job_id:
        j = db.query(Job).filter(Job.id == job_id).first()
        if j:
            cost_lines = j.cost_lines
            total_expected = sum(l.total_expected for l in cost_lines)
            parts.append(f"""JOB ATTIVO (id={j.id}, codice {j.code}):
- Titolo: {j.title} | Stato: {j.status}
- Budget quotato: {_short_money(j.budget_quoted)} | A finire: {_short_money(total_expected)}
- Voci di costo: {len(cost_lines)}""")

    # Vista d'insieme (sempre, breve, per dare consapevolezza globale)
    from datetime import date as date_type
    overview = []
    overview.append(f"Data corrente: {date_type.today().isoformat()}")

    n_clients = db.query(Client).count()
    n_projects = db.query(Project).count()
    n_items = db.query(PriceItem).filter(PriceItem.is_active == True).count()
    n_quotes = db.query(Quote).count()
    n_resources = db.query(Resource).filter(Resource.is_active == True).count()
    n_assets = db.query(Asset).count()
    overview.append(f"DB: {n_clients} clienti, {n_projects} progetti, {n_items} voci listino attive, "
                    f"{n_quotes} quote, {n_resources} risorse, {n_assets} asset.")

    cats = [c.name for c in db.query(PriceCategory).order_by(PriceCategory.sort_order).limit(20).all()]
    if cats:
        overview.append("Categorie listino: " + ", ".join(cats[:20]))

    depts = [d.name for d in db.query(Department).filter(Department.is_active == True).all()]
    if depts:
        overview.append("Reparti: " + ", ".join(depts))

    # Lista clienti esistenti (per evitare allucinazioni di nomi)
    clients_rows = db.query(Client).order_by(Client.name).limit(40).all()
    if clients_rows:
        overview.append("CLIENTI ESISTENTI (id | name):")
        for cl in clients_rows:
            overview.append(f"  {cl.id} | {cl.name}")

    # Lista progetti esistenti (per evitare allucinazioni di code)
    proj_rows = db.query(Project).order_by(Project.id.desc()).limit(40).all()
    if proj_rows:
        overview.append("PROGETTI ESISTENTI (id | code | title | client):")
        for p in proj_rows:
            client_name = p.client.name if p.client else "?"
            overview.append(f"  {p.id} | {p.code} | {p.title} | {client_name}")

    # Quote attive (per riferimento veloce su quote_id)
    quote_rows = db.query(Quote).order_by(Quote.id.desc()).limit(15).all()
    if quote_rows:
        overview.append("QUOTE ESISTENTI (id | number | project_code):")
        for qr in quote_rows:
            overview.append(f"  {qr.id} | {qr.number} | {qr.project.code if qr.project else '?'}")

    if page:
        overview.append(f"Pagina corrente UI: {page}")

    parts.append("\n".join(overview))

    return "\n\n".join(parts)


# ── Estrazione azioni proposte ───────────────────────────────

VALID_ACTION_TYPES = {
    "propose_client",
    "propose_project",
    "propose_project_metadata",
    "propose_quote",
    "propose_quote_line",
    "propose_price_item",
    "web_search",
}


def _balanced_json_at(text: str, start: int) -> tuple[Optional[str], int]:
    """
    Estrae un blocco JSON balanced partendo da text[start] (deve essere `{`).
    Ritorna (json_str, end_index_after_closing_brace) oppure (None, start).
    """
    if start >= len(text) or text[start] != "{":
        return None, start
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False; continue
        if ch == "\\":
            escape = True; continue
        if ch == '"':
            in_string = not in_string; continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1], i + 1
    return None, start


def extract_proposed_actions(reply_text: str) -> tuple[str, list[dict]]:
    """
    Estrae i blocchi azione dalla risposta dell'AI. Tollera tre formati che
    i modelli piccoli (Llama 8B, Qwen 7B) emettono con frequenza:

      1. ```action\n{...}\n```    (canonica)
      2. ```\naction\n{...}\n```  (action su riga successiva)
      3. action\n{...}            (senza code fence)

    Usa parsing balanced delle parentesi così supporta JSON annidato.
    Ritorna (testo_ripulito, [azioni_valide]).
    """
    if not reply_text:
        return "", []

    actions: list[dict] = []
    text = reply_text

    # Trova tutti i punti di partenza dei blocchi action e estraili in ordine
    # Pattern 1+2: tre apici opzionali + parola action + JSON balanced
    # Pattern 3: solo parola action a inizio linea + JSON balanced
    fence_pat = re.compile(
        r"(```)?\s*\n?\s*action\s*\n", re.IGNORECASE)

    # Iteriamo finché troviamo "action\n{"
    pos = 0
    spans_to_strip: list[tuple[int, int]] = []
    while True:
        m = fence_pat.search(text, pos)
        if not m:
            break
        # cerca la prima `{` subito dopo il match
        brace_idx = text.find("{", m.end() - 1)
        if brace_idx < 0 or brace_idx > m.end() + 5:
            pos = m.end()
            continue
        payload, after = _balanced_json_at(text, brace_idx)
        if not payload:
            pos = m.end()
            continue
        parsed = safe_json_parse(payload)
        if not parsed:
            logger.warning(
                "Blocco action trovato ma JSON non parsabile (probabilmente "
                "contiene commenti o virgole finali). Primi 200 char: %r",
                payload[:200],
            )
            pos = after
            continue
        if parsed.get("type") not in VALID_ACTION_TYPES:
            logger.warning(
                "Blocco action con type non riconosciuto: %r (validi: %s)",
                parsed.get("type"), sorted(VALID_ACTION_TYPES),
            )
            pos = after
            continue
        actions.append(parsed)
        # estendi span per togliere anche eventuali ``` di chiusura
        end = after
        tail = text[end:end + 8]
        m2 = re.match(r"\s*```", tail)
        if m2:
            end += m2.end()
        spans_to_strip.append((m.start(), end))
        pos = end

    # Rimuovi gli span (in ordine inverso per non shiftare gli indici)
    for s, e in reversed(spans_to_strip):
        text = text[:s] + text[e:]

    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    return cleaned, actions


# ── Chat principale ─────────────────────────────────────────

def chat_with_assistant(db: Session,
                        messages: list[dict],
                        user_id: Optional[int] = None,
                        project_id: Optional[int] = None,
                        quote_id: Optional[int] = None,
                        job_id: Optional[int] = None,
                        page: Optional[str] = None) -> dict:
    """
    Chat multi-turn con l'assistente.
    Ritorna dict {reply, actions, error}.
    Le azioni proposte NON sono ancora salvate nel DB: lo fa il router.
    """
    provider = get_provider_for_user(user_id, db)
    if not provider:
        return {
            "reply": "AI non configurata. Vai in Impostazioni → tab AI per scegliere e attivare un provider.",
            "actions": [],
            "error": "provider_disabled",
        }

    system = ASSISTANT_SYSTEM_PROMPT
    context = build_context(db, project_id, quote_id, job_id, page=page)
    if context:
        system += f"\n\n━━━ CONTESTO ATTUALE ━━━\n{context}"

    try:
        raw_reply = provider.chat(messages, system=system, max_tokens=2000, temperature=0.5) or ""
    except Exception as e:
        logger.error(f"Assistant chat failed: {e}")
        return {
            "reply": f"Errore comunicazione con l'AI: {str(e)[:200]}",
            "actions": [],
            "error": "provider_error",
        }

    cleaned, actions = extract_proposed_actions(raw_reply)
    return {"reply": cleaned or raw_reply, "actions": actions, "error": None}


# ── Applicazione delle azioni proposte ───────────────────────

def apply_action(db: Session, action: AIAction) -> dict:
    """
    Esegue concretamente l'azione approvata dall'utente.
    Ritorna {ok, result} oppure {ok: False, error}.
    Solleva ValueError se il payload è incompleto.
    """
    if action.status != "proposed":
        return {"ok": False, "error": f"Azione in stato {action.status}, non applicabile"}

    payload = json.loads(action.payload) if action.payload else {}
    handler = _ACTION_HANDLERS.get(action.action_type)
    if not handler:
        return {"ok": False, "error": f"Tipo azione non supportato: {action.action_type}"}

    try:
        result = handler(db, payload)
        return {"ok": True, "result": result}
    except Exception as e:
        logger.exception(f"apply_action {action.action_type} fallita")
        return {"ok": False, "error": str(e)}


# Handler concreti ────────────────────────────────────────────

def _h_propose_price_item(db: Session, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Manca 'name'")
    cat_name = (data.get("category_name") or "").strip()
    if not cat_name:
        raise ValueError("Manca 'category_name' (la categoria è obbligatoria)")
    cat = db.query(PriceCategory).filter(PriceCategory.name == cat_name).first()
    if not cat:
        cat = PriceCategory(name=cat_name)
        db.add(cat); db.flush()
    category_id = cat.id
    dept_id = None
    dept_name = (data.get("department_name") or "").strip()
    if dept_name:
        d = db.query(Department).filter(Department.name == dept_name).first()
        if d:
            dept_id = d.id
    price = float(data.get("price_list") or 0)
    item = PriceItem(
        name=name,
        description=data.get("description"),
        unit=data.get("unit") or "day",
        price_list=price,
        price_average=price,
        price_low=price,
        category_id=category_id,
        department_id=dept_id,
        keywords=data.get("keywords") or [],
        is_active=True,
    )
    db.add(item); db.flush()
    return {"price_item_id": item.id, "name": item.name, "category": cat.name}


def _h_propose_client(db: Session, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Manca 'name'")
    # accetta sia campi dello schema (contact_email/phone) che alias comuni
    email = data.get("contact_email") or data.get("email")
    phone = data.get("contact_phone") or data.get("phone")
    c = Client(
        name=name,
        contact_name=data.get("contact_name"),
        contact_email=email,
        contact_phone=phone,
        vat_number=data.get("vat_number"),
        address=data.get("address"),
        city=data.get("city"),
        country=data.get("country"),
        website=data.get("website"),
        notes=data.get("notes"),
    )
    db.add(c); db.flush()
    return {"client_id": c.id, "name": c.name}


def _resolve_project(db: Session, data: dict) -> Project:
    """Risolve un progetto da `project_id` (numero PK) o `code` (stringa)."""
    pid = data.get("project_id")
    if isinstance(pid, int) or (isinstance(pid, str) and pid.isdigit()):
        p = db.query(Project).filter(Project.id == int(pid)).first()
        if p:
            return p
    code = data.get("code") or (pid if isinstance(pid, str) else None)
    if code:
        p = db.query(Project).filter(Project.code == code).first()
        if p:
            return p
    raise ValueError(f"Progetto non trovato (project_id={pid!r}, code={code!r}). "
                     f"Usa il PK numerico o il code esatto.")


def _resolve_quote(db: Session, data: dict) -> Quote:
    """Risolve una quote da `quote_id` (PK) o `quote_number` (stringa)."""
    qid = data.get("quote_id")
    if isinstance(qid, int) or (isinstance(qid, str) and qid.isdigit()):
        q = db.query(Quote).filter(Quote.id == int(qid)).first()
        if q:
            return q
    number = data.get("quote_number") or (qid if isinstance(qid, str) else None)
    if number:
        q = db.query(Quote).filter(Quote.number == number).first()
        if q:
            return q
    raise ValueError(f"Quote non trovata (quote_id={qid!r}, quote_number={number!r}).")


def _h_propose_project(db: Session, data: dict) -> dict:
    code = (data.get("code") or "").strip()
    title = (data.get("title") or "").strip()
    if not code:
        raise ValueError("Manca 'code'")
    if not title:
        raise ValueError("Manca 'title'")
    if db.query(Project).filter(Project.code == code).first():
        raise ValueError(f"Esiste già un progetto con code '{code}'")

    # Risolvi cliente: client_id (PK) o client_name (stringa)
    client_id = data.get("client_id")
    client = None
    if isinstance(client_id, int) or (isinstance(client_id, str) and str(client_id).isdigit()):
        client = db.query(Client).filter(Client.id == int(client_id)).first()
    if client is None:
        client_name = (data.get("client_name") or "").strip()
        if client_name:
            client = db.query(Client).filter(Client.name == client_name).first()
            if not client:
                raise ValueError(f"Cliente '{client_name}' non trovato. Crealo prima.")
    if client is None:
        raise ValueError("Specifica 'client_id' (PK) o 'client_name' (esistente).")

    p = Project(
        code=code, title=title, client_id=client.id,
        project_type=data.get("project_type"),
        length_minutes=data.get("length_minutes"),
        fps=str(data["fps"]) if data.get("fps") is not None else None,
        shooting_format=data.get("shooting_format"),
        delivery_format=data.get("delivery_format"),
        director=data.get("director"),
        description=data.get("description"),
    )
    db.add(p); db.flush()
    return {"project_id": p.id, "code": p.code, "title": p.title, "client": client.name}


def _next_quote_number(db: Session) -> str:
    """Genera Q-{anno}-{progressivo zero-padded a 3 cifre} basato sulle quote esistenti."""
    from datetime import date as date_type
    year = date_type.today().year
    prefix = f"Q-{year}-"
    last = db.query(Quote).filter(Quote.number.like(f"{prefix}%"))\
            .order_by(Quote.id.desc()).first()
    n = 1
    if last:
        try:
            n = int(last.number.rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            n = 1
    return f"{prefix}{n:03d}"


def _h_propose_quote(db: Session, data: dict) -> dict:
    """
    Crea una quote. Se data['lines'] è una lista, crea anche le righe in transazione.
    Defaults intelligenti:
      - number: auto-generato Q-{anno}-NNN se non specificato
      - title: titolo del progetto se non specificato
      - issue_date: oggi se non specificato
      - valid_until: oggi+30 giorni se non specificato
    """
    from datetime import date as date_type, timedelta
    from app.models import QuoteLine, PriceLevel
    from app.routers.quotes import _recalc_quote

    # Risolvi progetto: project_id o project_code
    pid = data.get("project_id")
    project = None
    if isinstance(pid, int) or (isinstance(pid, str) and str(pid).isdigit()):
        project = db.query(Project).filter(Project.id == int(pid)).first()
    if project is None:
        pcode = (data.get("project_code") or "").strip()
        if pcode:
            project = db.query(Project).filter(Project.code == pcode).first()
            if not project:
                raise ValueError(
                    f"Progetto con code '{pcode}' non trovato. "
                    "Crea prima il progetto, oppure usa il code di uno esistente."
                )
    if project is None:
        raise ValueError("Specifica 'project_id' (PK numerico) o 'project_code' (stringa).")

    # number: auto se mancante
    number = (data.get("number") or "").strip()
    if not number:
        number = _next_quote_number(db)
    elif db.query(Quote).filter(Quote.number == number).first():
        raise ValueError(f"Esiste già una quote con number '{number}'")

    # title: fallback al titolo del progetto
    title = (data.get("title") or "").strip() or project.title

    # date: oggi e +30gg di default
    today = date_type.today()
    issue_raw = data.get("issue_date")
    try:
        issue_date = date_type.fromisoformat(issue_raw) if issue_raw else today
    except (ValueError, TypeError):
        issue_date = today
    # Se l'AI mette una data nel passato (allucinazione) la sovrascriviamo a oggi
    if issue_date.year < today.year - 1:
        issue_date = today

    valid_raw = data.get("valid_until")
    try:
        valid_until = date_type.fromisoformat(valid_raw) if valid_raw else issue_date + timedelta(days=30)
    except (ValueError, TypeError):
        valid_until = issue_date + timedelta(days=30)
    if valid_until <= issue_date:
        valid_until = issue_date + timedelta(days=30)

    q = Quote(
        number=number, title=title,
        project_id=project.id, client_id=project.client_id,
        issue_date=issue_date, valid_until=valid_until,
        vat_rate=float(data.get("vat_rate", 22.0)),
    )
    db.add(q); db.flush()

    # Righe opzionali (transazione: se una fallisce, rollback dell'intera quote)
    lines_data = data.get("lines") or []
    created_lines = []
    if lines_data:
        for i, ld in enumerate(lines_data):
            description = (ld.get("description") or "").strip()
            if not description:
                raise ValueError(f"Riga #{i+1}: manca 'description'")
            qty = float(ld.get("quantity") or 1)
            price = float(ld.get("unit_price") or 0)
            unit = (ld.get("unit") or "").strip() or "day"
            if unit not in ("day", "hour", "flat"):
                unit = "day"
            section = (ld.get("section") or "A").strip()[:1].upper() or "A"
            line = QuoteLine(
                quote_id=q.id,
                section=section,
                position=ld.get("position") or f"{section}.{i+1}",
                description=description,
                detail=ld.get("detail"),
                quantity=qty,
                unit=unit,
                price_level=PriceLevel.list_price,
                unit_price=price,
                total=round(qty * price, 2),
                sort_order=(i + 1) * 10,
            )
            db.add(line); db.flush()
            created_lines.append({"description": description, "qty": qty, "unit": unit, "total": line.total})
        # Ricalcola totali quote
        q = db.query(Quote).filter(Quote.id == q.id).first()
        _recalc_quote(q)

    return {
        "quote_id": q.id,
        "number": q.number,
        "title": q.title,
        "project_code": project.code,
        "issue_date": issue_date.isoformat(),
        "lines_count": len(created_lines),
        "lines": created_lines,
        "total_after_discount": q.total_after_discount,
    }


def _h_propose_quote_line(db: Session, data: dict) -> dict:
    from app.models import QuoteLine, PriceLevel
    q = _resolve_quote(db, data)
    qty = float(data.get("quantity") or 1)
    price = float(data.get("unit_price") or 0)
    line = QuoteLine(
        quote_id=q.id,
        section=data.get("section") or "A",
        position=data.get("position") or f"A.{len(q.lines)+1}",
        description=data.get("description") or "",
        detail=data.get("detail"),
        quantity=qty,
        unit=data.get("unit") or "day",
        price_level=PriceLevel.list_price,
        unit_price=price,
        total=round(qty * price, 2),
        sort_order=(len(q.lines) + 1) * 10,
    )
    db.add(line); db.flush()
    from app.routers.quotes import _recalc_quote
    _recalc_quote(q)
    return {"quote_line_id": line.id, "quote_id": q.id, "total": line.total}


def _h_propose_project_metadata(db: Session, data: dict) -> dict:
    p = _resolve_project(db, data)
    fields = ["length_minutes", "fps", "shooting_format", "delivery_format", "director"]
    updated = {}
    for f in fields:
        if f in data and data[f] not in (None, ""):
            val = str(data[f]) if f == "fps" else data[f]
            setattr(p, f, val)
            updated[f] = val
    return {"project_id": p.id, "code": p.code, "updated": updated}


def _h_web_search(db: Session, data: dict) -> dict:
    """Ricerca web read-only via Tavily, restituisce snippet testuali."""
    from app.services.web_search import tavily_search
    query = (data.get("query") or "").strip()
    if not query:
        raise ValueError("Manca 'query'")
    results = tavily_search(query, max_results=5)
    return {"query": query, "results": results}


_ACTION_HANDLERS = {
    "propose_client":           _h_propose_client,
    "propose_project":          _h_propose_project,
    "propose_project_metadata": _h_propose_project_metadata,
    "propose_quote":            _h_propose_quote,
    "propose_quote_line":       _h_propose_quote_line,
    "propose_price_item":       _h_propose_price_item,
    "web_search":               _h_web_search,
}


# ── Review quotazione (legacy, immutato funzionalmente) ──────

REVIEW_SYSTEM_PROMPT = """Sei un senior producer di postproduzione. Analizza una quotazione e dai 3-5 osservazioni concrete sul suo contenuto.

Focus su:
- Voci sospette mancanti per il tipo di progetto
- Quantità che sembrano sotto/sovrastimate
- Mix di prezzi list/average/low poco coerente
- Rischi di sforamento identificabili
- Ottimizzazioni possibili sullo sconto pacchetto

Formato output: lista di osservazioni in markdown. Una osservazione per riga, inizia ognuna con un'icona pertinente (! per rischio, * per suggerimento, + per conferma positiva).

Sii schietto e concreto. Meglio 3 osservazioni utili che 10 generiche."""


def review_quote(db: Session, quote_id: int, user_id: Optional[int] = None) -> Optional[str]:
    provider = get_provider_for_user(user_id, db)
    if not provider:
        return None
    q = db.query(Quote).filter(Quote.id == quote_id).first()
    if not q:
        return None
    context = build_context(db, project_id=q.project_id, quote_id=q.id)
    user_prompt = f"Ecco la quotazione da analizzare:\n\n{context}\n\nFornisci la tua review."
    try:
        return provider.complete(REVIEW_SYSTEM_PROMPT, user_prompt,
                                 max_tokens=1500, temperature=0.4)
    except Exception as e:
        logger.error(f"Quote review failed: {e}")
        return None
