"""
MediaFlow — AI Assistant (copilot context-aware con pattern AI propone, utente dispone)

Ogni risposta dell'AI può contenere:
- testo libero in markdown (mostrato all'utente nel drawer chat)
- una o più "proposed actions" in blocchi ```action ...``` JSON, che il backend
  estrae, valida, salva come AIAction in DB e restituisce al frontend per conferma.

Capability mutation supportate (lista canonica in `_ACTION_HANDLERS`):
- propose_price_item       — proporre nuova voce di listino
- propose_client           — proporre creazione cliente
- propose_project          — proporre creazione progetto
- propose_project_metadata — aggiornare metadata progetto
- propose_quote            — proporre quotazione (con righe inline opt)
- update_quote             — aggiornare quote esistente
- propose_quote_line       — proporre riga su quote attiva
- propose_new_item_and_line — voce listino + riga quote in singola transazione
- propose_resource         — proporre nuova risorsa (α.33)
- propose_booking          — proporre booking con N risorse
- web_search               — Tavily (read-only)
"""
from __future__ import annotations
import json
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Project, Quote, Job, JobStatus, PriceItem, PriceCategory, Client, Resource,
    Asset, Department,
    Booking, BookingAssignment, BookingStatus, BookingExecutionStatus,
    ResourceUnavailability, UnavailabilityKind, UnavailabilityStatus,
    JobCostLine, BookingChange,
)
from app.models.models import AIAction, JCLBillingStatus
from app.services.ai_provider import get_provider_for_user, safe_json_parse

logger = logging.getLogger(__name__)


# v3.5.0-alpha.66.14.3 — Tenant scope per le query del context AI.
# I router applicano già `tenant_id == CURRENT_TENANT` ovunque, ma `build_context`
# ignorava questa policy → cross-tenant data leak latente in Fase 7 multi-tenant
# hard. Applicato qui ai modelli che hanno la colonna `tenant_id`.
# Project/Quote/Job/JobCostLine non hanno tenant_id (audit HIGH #1, sarà
# affrontato nel refactor R1 di consolidamento). Per ora restano cross-tenant
# nelle query overview, con un commento esplicito.
# v3.5.0-alpha.66.17.0 (R6) — System prompt + context builder estratti in
# app/services/ai_context.py. Re-export per compatibilita' call site.
from app.services.ai_context import (
    CURRENT_TENANT,
    ASSISTANT_SYSTEM_PROMPT,
    _short_money,
    build_context,
    _build_planning_context,
)

# v3.5.0-alpha.66.17.1 (R6) — Legacy parser markdown action estratto in
# app/services/ai_legacy_parser.py. Re-export per compatibilita' call site
# (router/ai.py importa VALID_ACTION_TYPES + extract_proposed_actions).
from app.services.ai_legacy_parser import (
    VALID_ACTION_TYPES,
    extract_proposed_actions,
    _balanced_json_at,
)

from app.services.ai_capability_registry import (
    ai_capability,
    get_handlers as _registry_get_handlers,
    get_action_types as _registry_get_action_types,
)
# ── Chat principale ─────────────────────────────────────────

def build_system_prompt(db: Session, *, use_tools: bool,
                        project_id: Optional[int] = None,
                        quote_id: Optional[int] = None,
                        job_id: Optional[int] = None,
                        page: Optional[str] = None) -> str:
    """Costruisce il system prompt + sezione contesto.

    Quando `use_tools=True` (provider con tool_use nativo) usa la versione slim
    `ASSISTANT_SYSTEM_PROMPT_TOOLS` di `ai_tools` (niente schema action inline).
    Altrimenti usa `ASSISTANT_SYSTEM_PROMPT` legacy con tutto lo schema.
    """
    if use_tools:
        from app.services.ai_tools import ASSISTANT_SYSTEM_PROMPT_TOOLS as base
    else:
        base = ASSISTANT_SYSTEM_PROMPT
    context = build_context(db, project_id, quote_id, job_id, page=page)
    if context:
        return base + f"\n\n━━━ CONTESTO ATTUALE ━━━\n{context}"
    return base


def chat_with_assistant(db: Session,
                        messages: list[dict],
                        user_id: Optional[int] = None,
                        project_id: Optional[int] = None,
                        quote_id: Optional[int] = None,
                        job_id: Optional[int] = None,
                        page: Optional[str] = None) -> dict:
    """
    Chat multi-turn con l'assistente — path LEGACY (markdown ```action```).
    Usato per provider che non supportano tool_use nativo (Ollama/Perplexity)
    o come fallback.

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

    system = build_system_prompt(db, use_tools=False, project_id=project_id,
                                 quote_id=quote_id, job_id=job_id, page=page)

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

    v3.5.0-alpha.19: gli handler che dichiarano un parametro keyword-only `user`
    (settings registry: read_setting/update_setting) ricevono l'utente che ha
    creato l'action — necessario per i permission check + per le aree
    "self" (preferenze per-utente).
    """
    if action.status != "proposed":
        return {"ok": False, "error": f"Azione in stato {action.status}, non applicabile"}

    payload = json.loads(action.payload) if action.payload else {}
    handler = _ACTION_HANDLERS.get(action.action_type)
    if not handler:
        return {"ok": False, "error": f"Tipo azione non supportato: {action.action_type}"}

    try:
        import inspect
        sig = inspect.signature(handler)
        kwargs: dict = {}
        if "user" in sig.parameters:
            user = None
            if action.user_id:
                from app.models import User
                user = db.query(User).filter(User.id == action.user_id).first()
            kwargs["user"] = user
        result = handler(db, payload, **kwargs)
        return {"ok": True, "result": result}
    except Exception as e:
        logger.exception(f"apply_action {action.action_type} fallita")
        return {"ok": False, "error": str(e)}


# Handler concreti ────────────────────────────────────────────

@ai_capability("propose_price_item")
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
    return {"created": True, "price_item_id": item.id, "name": item.name,
            "category": cat.name, "unit": item.unit, "price_list": item.price_list,
            "message": f"Voce listino '{item.name}' creata con id={item.id} (categoria {cat.name}, {item.unit}, €{item.price_list})."}


@ai_capability("propose_client")
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
    return {"created": True, "client_id": c.id, "name": c.name,
            "message": f"Cliente '{c.name}' creato con id={c.id}."}


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


@ai_capability("propose_project")
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
    return {"created": True, "project_id": p.id, "code": p.code, "title": p.title,
            "client": client.name,
            "message": f"Progetto '{p.code}' ({p.title}) creato con id={p.id} per cliente {client.name}."}


def _next_quote_number(db: Session) -> str:
    """Genera Q-{anno}-{progressivo zero-padded a 3 cifre} basato sulle quote esistenti.

    BYPASS soft-delete filter (`include_deleted=True`): le quote in cestino
    occupano comunque il `number` (vincolo UNIQUE su DB), quindi devono essere
    considerate qui per evitare collisioni di numero al successivo INSERT.
    """
    from datetime import date as date_type
    year = date_type.today().year
    prefix = f"Q-{year}-"
    last = (db.query(Quote)
              .execution_options(include_deleted=True)
              .filter(Quote.number.like(f"{prefix}%"))
              .order_by(Quote.id.desc()).first())
    n = 1
    if last:
        try:
            n = int(last.number.rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            n = 1
    return f"{prefix}{n:03d}"


@ai_capability("propose_quote")
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

    # number: auto se mancante (bypass soft-delete: quote in cestino occupano il number)
    number = (data.get("number") or "").strip()
    if not number:
        number = _next_quote_number(db)
    elif (db.query(Quote)
            .execution_options(include_deleted=True)
            .filter(Quote.number == number).first()):
        raise ValueError(f"Esiste già una quote con number '{number}' (eventualmente nel cestino)")

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
            qty = float(ld.get("quantity") or 1)
            section = (ld.get("section") or "A").strip()[:1].upper() or "A"

            # Risolvi price_item_id se presente, e usa il listino come default
            # per description / unit / unit_price quando l'AI non li ha forniti.
            pi = None
            pi_id_raw = ld.get("price_item_id")
            if isinstance(pi_id_raw, int) or (isinstance(pi_id_raw, str) and str(pi_id_raw).isdigit()):
                pi = db.query(PriceItem).filter(PriceItem.id == int(pi_id_raw)).first()
                if not pi:
                    raise ValueError(f"Riga #{i+1}: price_item_id={pi_id_raw} non trovato in listino.")

            description = (ld.get("description") or "").strip() or (pi.name if pi else "")
            if not description:
                raise ValueError(f"Riga #{i+1}: manca 'description' (e nessun price_item_id da cui ereditarla).")

            raw_unit = (ld.get("unit") or "").strip()
            unit = raw_unit or (pi.unit if pi else "day")
            if unit not in ("day", "hour", "flat"):
                unit = pi.unit if pi else "day"

            raw_price = ld.get("unit_price")
            if raw_price in (None, ""):
                price = float(pi.price_list) if pi else 0.0
            else:
                price = float(raw_price)

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
                price_item_id=pi.id if pi else None,
            )
            db.add(line); db.flush()
            created_lines.append({
                "description":   description,
                "qty":           qty,
                "unit":          unit,
                "total":         line.total,
                "price_item_id": pi.id if pi else None,
            })
        # Ricalcola totali quote
        q = db.query(Quote).filter(Quote.id == q.id).first()
        _recalc_quote(q)

    return {
        "created": True,
        "quote_id": q.id,
        "number": q.number,
        "title": q.title,
        "project_code": project.code,
        "issue_date": issue_date.isoformat(),
        "lines_count": len(created_lines),
        "lines": created_lines,
        "total_after_discount": q.total_after_discount,
        "message": f"Quotazione {q.number} creata con id={q.id} per progetto {project.code} ({len(created_lines)} righe, totale netto €{q.total_after_discount:.2f}).",
    }


@ai_capability("update_quote")
def _h_update_quote(db: Session, data: dict) -> dict:
    """v3.5.0-alpha.14: modifica i metadata di una quote esistente.
    Permette: title, issue_date, valid_until, vat_rate, package_discount, notes,
    payment_terms, status (con validazione transitions).
    Quote in cestino o sostituita non sono modificabili (status=superseded blocca).
    """
    from datetime import date as date_type
    from app.routers.quotes import _recalc_quote

    qid = data.get("quote_id")
    qnum = (data.get("quote_number") or "").strip()
    q = None
    if isinstance(qid, int) or (isinstance(qid, str) and str(qid).isdigit()):
        q = db.query(Quote).filter(Quote.id == int(qid)).first()
    if q is None and qnum:
        q = db.query(Quote).filter(Quote.number == qnum).first()
    if q is None:
        raise ValueError("Specifica `quote_id` (PK) o `quote_number` (es. 'Q-2026-001').")

    # Status superseded → bloccare (è una versione storica di un altro)
    status_v = q.status.value if hasattr(q.status, "value") else str(q.status)
    if status_v == "superseded":
        raise ValueError(f"Quote {q.number} è 'superseded' (sostituita) — non modificabile.")

    changed = []
    if data.get("title") and data["title"].strip():
        q.title = data["title"].strip(); changed.append("title")
    if data.get("notes") is not None:
        q.notes = data["notes"]; changed.append("notes")
    if data.get("payment_terms") is not None:
        q.payment_terms = data["payment_terms"]; changed.append("payment_terms")
    if data.get("vat_rate") is not None:
        q.vat_rate = float(data["vat_rate"]); changed.append("vat_rate")
    if data.get("package_discount") is not None:
        # Convenzione UI: discount positivo (0..1); in DB lo stocchiamo negativo
        pd = float(data["package_discount"])
        if pd > 1: pd = pd / 100.0  # accetta sia "0.1" sia "10"
        q.package_discount = -abs(pd) if pd > 0 else 0.0
        changed.append("package_discount")
    for date_field in ("issue_date", "valid_until"):
        raw = data.get(date_field)
        if raw:
            try:
                setattr(q, date_field, date_type.fromisoformat(raw))
                changed.append(date_field)
            except (ValueError, TypeError):
                raise ValueError(f"{date_field} non è una data ISO valida (atteso YYYY-MM-DD).")

    if not changed:
        raise ValueError("Nessun campo modificabile passato. Usa title/notes/vat_rate/package_discount/issue_date/valid_until/payment_terms.")

    _recalc_quote(q)
    db.flush()
    return {
        "updated": True,
        "quote_id": q.id,
        "number": q.number,
        "title": q.title,
        "fields_changed": changed,
        "total_after_discount": q.total_after_discount,
        "message": f"Quotazione {q.number} aggiornata ({', '.join(changed)}). Totale netto: €{q.total_after_discount:.2f}.",
    }


@ai_capability("propose_quote_line")
def _h_propose_quote_line(db: Session, data: dict) -> dict:
    """Aggiunge una riga a una quote esistente.

    Se `price_item_id` è valorizzato: lega la riga al listino e usa
    `price_item.price_list` come `unit_price` di default (sovrascrivibile).
    Se mancante: voce libera (storico).
    """
    from app.models import QuoteLine, PriceLevel
    q = _resolve_quote(db, data)
    qty = float(data.get("quantity") or 1)

    # Risolvi eventuale price_item per default su unit_price/unit/description
    price_item_id = data.get("price_item_id")
    pi = None
    if isinstance(price_item_id, int) or (isinstance(price_item_id, str) and str(price_item_id).isdigit()):
        pi = db.query(PriceItem).filter(PriceItem.id == int(price_item_id)).first()
        if not pi:
            raise ValueError(f"price_item_id={price_item_id} non trovato in listino.")

    # unit_price: usa valore esplicito se passato, altrimenti default da listino
    raw_price = data.get("unit_price")
    if raw_price in (None, ""):
        price = float(pi.price_list) if pi else 0.0
    else:
        price = float(raw_price)

    # description e unit: se non passate ma c'è price_item, eredita
    description = data.get("description") or (pi.name if pi else "")
    unit = data.get("unit") or (pi.unit if pi else "day")

    line = QuoteLine(
        quote_id=q.id,
        section=data.get("section") or "A",
        position=data.get("position") or f"A.{len(q.lines)+1}",
        description=description,
        detail=data.get("detail"),
        quantity=qty,
        unit=unit,
        price_level=PriceLevel.list_price,
        unit_price=price,
        total=round(qty * price, 2),
        sort_order=(len(q.lines) + 1) * 10,
        price_item_id=pi.id if pi else None,
    )
    db.add(line); db.flush()
    from app.routers.quotes import _recalc_quote
    _recalc_quote(q)
    return {
        "created": True,
        "quote_line_id": line.id, "quote_id": q.id,
        "total": line.total,
        "price_item_id": pi.id if pi else None,
        "price_item_name": pi.name if pi else None,
        "message": (f"Riga aggiunta alla quote #{q.id}: {line.description}, "
                    f"qty={line.quantity} {line.unit}, total €{line.total:.2f}."),
    }


@ai_capability("propose_new_item_and_line")
def _h_propose_new_item_and_line(db: Session, data: dict) -> dict:
    """Scenario C — search-first AI fallback.

    In singola transazione:
      1. Crea una nuova `PriceItem` nel listino (richiede category_name)
      2. Crea una `QuoteLine` sulla quote indicata, legata alla voce appena creata

    Schema atteso in `data`:
      - quote_id (PK) o quote_number (stringa)        — obbligatorio
      - name (stringa)                                — obbligatorio (nome voce listino)
      - category_name (stringa)                       — obbligatorio
      - unit ("day"|"hour"|"flat", default "day")
      - price_list (numero)                           — obbligatorio (prezzo listino)
      - quantity (numero, default 1)                  — quantità nella quote
      - description? (alias di name se omesso)
      - keywords? (lista di stringhe, per matching futuro)
      - department_name?
      - section? ("A"|"B"|"C", default "A")
    """
    from app.models import QuoteLine, PriceLevel
    q = _resolve_quote(db, data)

    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Manca 'name' (nome voce listino)")
    cat_name = (data.get("category_name") or "").strip()
    if not cat_name:
        raise ValueError("Manca 'category_name' (la categoria è obbligatoria)")
    if data.get("price_list") in (None, ""):
        raise ValueError("Manca 'price_list' (prezzo listino della voce)")

    # Categoria: trova o crea
    cat = db.query(PriceCategory).filter(PriceCategory.name == cat_name).first()
    if not cat:
        cat = PriceCategory(name=cat_name)
        db.add(cat); db.flush()

    # Reparto opzionale
    dept_id = None
    dept_name = (data.get("department_name") or "").strip()
    if dept_name:
        d = db.query(Department).filter(Department.name == dept_name).first()
        if d:
            dept_id = d.id

    price = float(data["price_list"])
    unit = data.get("unit") or "day"

    pi = PriceItem(
        name=name,
        description=data.get("description") or name,
        unit=unit,
        price_list=price,
        price_average=price,
        price_low=price,
        category_id=cat.id,
        department_id=dept_id,
        keywords=data.get("keywords") or [],
        is_active=True,
    )
    db.add(pi); db.flush()

    qty = float(data.get("quantity") or 1)
    line = QuoteLine(
        quote_id=q.id,
        section=data.get("section") or "A",
        position=data.get("position") or f"A.{len(q.lines)+1}",
        description=data.get("description") or name,
        quantity=qty,
        unit=unit,
        price_level=PriceLevel.list_price,
        unit_price=price,
        total=round(qty * price, 2),
        sort_order=(len(q.lines) + 1) * 10,
        price_item_id=pi.id,
    )
    db.add(line); db.flush()

    from app.routers.quotes import _recalc_quote
    _recalc_quote(q)
    return {
        "created": True,
        "price_item_id": pi.id, "price_item_name": pi.name, "category": cat.name,
        "quote_line_id": line.id, "quote_id": q.id, "total": line.total,
        "message": (f"Voce listino '{pi.name}' creata e aggiunta alla quote #{q.id} "
                    f"(qty={line.quantity}, total €{line.total:.2f})."),
    }


@ai_capability("propose_project_metadata")
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


@ai_capability("web_search")
def _h_web_search(db: Session, data: dict) -> dict:
    """Ricerca web read-only via Tavily, restituisce snippet testuali."""
    from app.services.web_search import tavily_search
    query = (data.get("query") or "").strip()
    if not query:
        raise ValueError("Manca 'query'")
    results = tavily_search(query, max_results=5)
    return {"query": query, "results": results}


# ── Settings registry handlers (v3.5.0-alpha.19) ─────────────
# Tre tool generici per scoprire/leggere/modificare qualsiasi area di settings
# registrata in `settings_registry.SCHEMAS`. Sostituiscono l'idea di una
# capability AI per ogni area. Per estendere a una nuova area: aggiungi una
# `SettingsSchema` al registry, niente codice qui da toccare.

@ai_capability("list_settings_schemas")
def _h_list_settings_schemas(db: Session, data: dict) -> dict:
    from app.services.settings_registry import list_schemas
    schemas = list_schemas()
    return {
        "schemas": schemas,
        "message": (
            f"Aree configurabili: {', '.join(s['key'] for s in schemas)}. "
            "Usa read_setting per vedere lo stato corrente di un'area, "
            "update_setting per proporre modifiche."
        ),
    }


@ai_capability("read_setting")
def _h_read_setting(db: Session, data: dict, *, user=None) -> dict:
    from app.services.settings_registry import get_schema
    key = (data.get("key") or "").strip()
    if not key:
        raise ValueError("Manca 'key' (es. 'working_hours', 'tenant_settings')")
    schema = get_schema(key)
    if not schema:
        raise ValueError(f"Schema settings '{key}' non trovato")
    state = schema.read(db, user)
    return {
        "key": key,
        "label": schema.label,
        "permission_required": schema.permission,
        "current": state,
        "fields": [f.to_dict() for f in schema.fields],
    }


@ai_capability("update_setting")
def _h_update_setting(db: Session, data: dict, *, user=None) -> dict:
    from app.services.settings_registry import get_schema, can_user_access
    key = (data.get("key") or "").strip()
    if not key:
        raise ValueError("Manca 'key'")
    patch = data.get("patch") or {}
    if not isinstance(patch, dict) or not patch:
        raise ValueError("'patch' deve essere un dict non vuoto con i campi da modificare")
    schema = get_schema(key)
    if not schema:
        raise ValueError(f"Schema settings '{key}' non trovato")
    if user is not None and not can_user_access(schema, user):
        raise ValueError(
            f"Permesso negato: per modificare '{schema.label}' serve permesso "
            f"'{schema.permission}'"
        )
    result = schema.write(db, user, patch)
    applied = result.get("applied") or {}
    if not applied:
        return {
            "key": key,
            "label": schema.label,
            "applied": {},
            "current": result.get("current"),
            "message": f"Nessuna modifica effettiva su '{schema.label}' (i valori erano già corretti).",
        }
    diff_lines = [f"{k}: {v['old']} → {v['new']}" for k, v in applied.items()]
    return {
        "key": key,
        "label": schema.label,
        "applied": applied,
        "current": result.get("current"),
        "message": f"'{schema.label}' aggiornato. Cambi: " + " · ".join(diff_lines),
    }


@ai_capability("propose_resource")
def _h_propose_resource(db: Session, data: dict) -> dict:
    """Crea una nuova Resource (v3.5.0-alpha.33).

    Risolve il reparto via `department_id` (PK) o `department_name` (match esatto).
    `type` deve essere uno dei ResourceType supportati. Tariffe ignorate se 0/None.
    """
    from app.models import ResourceType
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Manca 'name'")
    type_str = (data.get("type") or "").strip()
    try:
        rtype = ResourceType(type_str)
    except Exception:
        raise ValueError(
            f"'type' non valido: '{type_str}'. Valori ammessi: "
            "person_internal, person_freelance, studio, equipment, software, vehicle."
        )

    # Risolvi reparto: id (PK) o name (string match esatto)
    dept_id = data.get("department_id")
    department = None
    if isinstance(dept_id, int) or (isinstance(dept_id, str) and str(dept_id).isdigit()):
        department = db.query(Department).filter(Department.id == int(dept_id)).first()
    if department is None:
        dept_name = (data.get("department_name") or "").strip()
        if dept_name:
            department = db.query(Department).filter(Department.name == dept_name).first()
            if not department:
                raise ValueError(
                    f"Reparto '{dept_name}' non trovato. Usa il PK numerico o il nome esatto "
                    "(vedi DEPARTMENTS nel contesto)."
                )

    # Tariffe: 0 e None considerati "non noto" → NULL in DB (consistente col modello)
    def _opt_num(key):
        v = data.get(key)
        if v is None: return None
        try:
            n = float(v)
            return n if n > 0 else None
        except Exception:
            return None

    color = (data.get("color") or "").strip() or "#6272f5"
    if not color.startswith("#") or len(color) not in (4, 7):
        color = "#6272f5"

    r = Resource(
        tenant_id=1,
        name=name,
        type=rtype,
        department_id=(department.id if department else None),
        role=(data.get("role") or None),
        description=(data.get("description") or None),
        daily_rate=_opt_num("daily_rate"),
        hourly_rate=_opt_num("hourly_rate"),
        email=(data.get("email") or None),
        phone=(data.get("phone") or None),
        internal_phone=(data.get("internal_phone") or None),
        color=color,
        is_active=True,
    )
    db.add(r); db.flush()
    return {
        "created": True,
        "resource_id": r.id,
        "name": r.name,
        "type": r.type.value if hasattr(r.type, "value") else r.type,
        "department_id": r.department_id,
        "department_name": (department.name if department else None),
        "message": (
            f"Risorsa '{r.name}' creata"
            + (f" nel reparto {department.name}" if department else "")
            + f" (id={r.id})."
        ),
    }


@ai_capability("propose_booking")
def _h_propose_booking(db: Session, data: dict) -> dict:
    """Crea un Booking con N risorse (E6 v3.4.20).

    Payload atteso:
      {
        "job_id" o "job_code": ...,
        "kind": "project" (default) | "internal_*",
        "job_cost_line_id"?: id lavorazione,
        "notes"?: str,
        "assignments": [
          {"resource_id" o "resource_name": ..., "start_datetime": ISO, "end_datetime": ISO}
        ]
      }
    """
    from app.models import Booking, BookingAssignment, BookingStatus, BookingKind, Resource, Job, JobCostLine
    from datetime import datetime as _dt
    CURRENT_TENANT = 1

    # Risolvi job (per kind=project)
    kind_str = (data.get("kind") or "project").strip()
    try:
        kind = BookingKind(kind_str)
    except Exception:
        kind = BookingKind.project
    job_id = None
    if kind == BookingKind.project:
        job_id = data.get("job_id")
        if not job_id and data.get("job_code"):
            j = db.query(Job).filter(Job.code == data["job_code"]).first()
            if not j:
                raise ValueError(f"Job '{data['job_code']}' non trovato")
            job_id = j.id
        if not job_id:
            raise ValueError("Manca job_id o job_code per kind=project")

    line_id = data.get("job_cost_line_id")
    if line_id:
        line = db.query(JobCostLine).filter(JobCostLine.id == line_id).first()
        if not line:
            raise ValueError(f"Lavorazione #{line_id} non trovata")
        if line.job_id != job_id:
            raise ValueError("Lavorazione non appartiene al job indicato")

    # Risolvi assignments
    raw_ass = data.get("assignments") or []
    if not isinstance(raw_ass, list) or not raw_ass:
        raise ValueError("Servono almeno 1 risorsa in 'assignments'")
    parsed = []
    for i, a in enumerate(raw_ass):
        rid = a.get("resource_id")
        if not rid and a.get("resource_name"):
            r = db.query(Resource).filter(Resource.name.ilike(a["resource_name"])).first()
            if not r:
                raise ValueError(f"Risorsa '{a['resource_name']}' non trovata")
            rid = r.id
        if not rid:
            raise ValueError(f"assignments[{i}]: serve resource_id o resource_name")
        s = a.get("start_datetime"); e = a.get("end_datetime")
        try:
            sd = _dt.fromisoformat(s) if isinstance(s, str) else s
            ed = _dt.fromisoformat(e) if isinstance(e, str) else e
        except Exception:
            raise ValueError(f"assignments[{i}]: date non valide")
        if not sd or not ed or ed <= sd:
            raise ValueError(f"assignments[{i}]: end_datetime > start_datetime richiesto")
        parsed.append({"resource_id": int(rid), "start_datetime": sd, "end_datetime": ed})

    # Conflict check
    for i, pa in enumerate(parsed):
        c = db.query(BookingAssignment).join(Booking).filter(
            Booking.tenant_id == CURRENT_TENANT,
            Booking.status != BookingStatus.cancelled,
            BookingAssignment.resource_id == pa["resource_id"],
            BookingAssignment.start_datetime < pa["end_datetime"],
            BookingAssignment.end_datetime > pa["start_datetime"],
        ).first()
        if c:
            raise ValueError(f"Conflitto su risorsa per assignments[{i}]")

    # Crea Booking + assignments
    env_s = min(pa["start_datetime"] for pa in parsed)
    env_e = max(pa["end_datetime"] for pa in parsed)
    from app.models import BookingState
    b = Booking(
        tenant_id=CURRENT_TENANT,
        job_id=job_id, job_cost_line_id=line_id,
        start_datetime=env_s, end_datetime=env_e,
        status=BookingStatus.tentative, kind=kind,
        notes=data.get("notes"),
        state=BookingState.tentative,  # v3.5.0-alpha.66.5.1: sync state
    )
    db.add(b); db.flush()
    for pa in parsed:
        db.add(BookingAssignment(
            booking_id=b.id, resource_id=pa["resource_id"],
            start_datetime=pa["start_datetime"], end_datetime=pa["end_datetime"],
        ))
    return {"booking_id": b.id, "assignments_count": len(parsed),
            "start": b.start_datetime.isoformat(), "end": b.end_datetime.isoformat()}


# ── v3.5.0-alpha.50: capability planning (move/resize/delete booking esistente) ──

def _assert_jcl_not_locked(db: Session, b: Booking) -> None:
    """v3.5.0-alpha.51.1 fix A2: blocca AI su booking la cui JobCostLine
    è in stato `in_batch` (batch in approvazione, nessuno slice ancora).

    v3.5.0-alpha.59 affinato: per `billed`/`paid` il check granulare è ora
    in `_assert_no_blocking_slice` (basato su JCLBilledSlice + periodo del
    booking). Il blocco JCLBillingStatus resta utile solo per `in_batch`,
    quando il batch è ancora draft/approved e nessuno slice esiste."""
    if not b.job_cost_line_id:
        return
    jcl = db.query(JobCostLine).filter(JobCostLine.id == b.job_cost_line_id).first()
    if not jcl:
        return
    if jcl.billing_status == JCLBillingStatus.in_batch:
        raise ValueError(
            f"Booking #{b.id} non modificabile: la riga di costo (JCL #{jcl.id}) "
            f"è in un BillingBatch in approvazione. Il manager deve prima "
            f"approvare/annullare il batch."
        )


def _assert_no_blocking_slice(db: Session, b: Booking) -> None:
    """v3.5.0-alpha.59: blocca AI su booking dentro periodo già fatturato.
    Stesso check di `app.routers.planning._assert_no_blocking_slice` ma
    solleva ValueError (handler AI traduce in failure card)."""
    from app.services.billing_slice_guard import find_blocking_slice, slice_lock_message
    s = find_blocking_slice(db, b)
    if s is not None:
        raise ValueError(slice_lock_message(s))


def _resolve_booking_for_planning(db: Session, data: dict) -> Booking:
    """Helper comune per move/resize/delete: risolve booking_id obbligatorio."""
    CURRENT_TENANT = 1  # v3.5.0-alpha.51.1 fix A1
    bid = data.get("booking_id")
    if not bid:
        raise ValueError("Manca 'booking_id'")
    try:
        bid = int(bid)
    except (TypeError, ValueError):
        raise ValueError(f"booking_id non numerico: {bid}")
    b = db.query(Booking).filter(
        Booking.id == bid, Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise ValueError(f"Booking #{bid} non trovato")
    if b.status == BookingStatus.cancelled:
        raise ValueError(f"Booking #{bid} è già cancellato")
    _assert_jcl_not_locked(db, b)
    _assert_no_blocking_slice(db, b)  # v3.5.0-alpha.59
    return b


@ai_capability("propose_move_booking")
def _h_propose_move_booking(db: Session, data: dict) -> dict:
    """Sposta un booking esistente di un delta temporale, opzionalmente
    cambiando risorsa/risorse degli assignment.

    Payload:
      {
        "booking_id": int (obbligatorio),
        "shift_minutes"?: int (positivo = avanti, negativo = indietro),
        "new_start_date"?: "YYYY-MM-DD" (alternativa: imposta nuova data ancorata
            a min start del booking, sposta TUTTI gli assignment del delta),
        "new_resource_id"?: int (cambia risorsa di TUTTI gli assignment),
        "assignments_remap"?: [{from_resource_id, to_resource_id}, ...] (rimappa
            risorse mantenendo la struttura)
      }
    Almeno uno tra shift_minutes / new_start_date / new_resource_id /
    assignments_remap deve essere fornito.

    Conflict check sui nuovi orari prima di applicare. Atomic.
    """
    from datetime import datetime as _dt, timedelta as _td, date as _d
    b = _resolve_booking_for_planning(db, data)

    shift_min = data.get("shift_minutes")
    new_start_date_str = data.get("new_start_date")
    new_resource_id = data.get("new_resource_id")
    remap_list = data.get("assignments_remap") or []

    if not any([shift_min, new_start_date_str, new_resource_id, remap_list]):
        raise ValueError(
            "Servono almeno uno tra: shift_minutes, new_start_date, "
            "new_resource_id, assignments_remap"
        )

    delta = _td(0)
    if shift_min:
        try:
            delta += _td(minutes=int(shift_min))
        except (TypeError, ValueError):
            raise ValueError(f"shift_minutes non numerico: {shift_min}")
    if new_start_date_str:
        try:
            new_d = _d.fromisoformat(new_start_date_str)
        except Exception:
            raise ValueError(f"new_start_date non valido (atteso YYYY-MM-DD): {new_start_date_str}")
        # Calcola delta giornaliero da min(start) a new_d
        cur_start_date = min(a.start_datetime for a in b.assignments).date()
        delta += _td(days=(new_d - cur_start_date).days)

    # Costruisci remap: from_resource_id → to_resource_id
    remap: dict[int, int] = {}
    if new_resource_id:
        try:
            target = int(new_resource_id)
        except (TypeError, ValueError):
            raise ValueError(f"new_resource_id non numerico: {new_resource_id}")
        # Verifica esistenza
        if not db.query(Resource).filter(Resource.id == target).first():
            raise ValueError(f"Risorsa #{target} non trovata")
        for a in b.assignments:
            remap[a.id] = target  # qui la chiave è assignment_id (univoca)
    for entry in remap_list:
        try:
            fr = int(entry["from_resource_id"])
            to = int(entry["to_resource_id"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("assignments_remap entry malformato (need from_resource_id, to_resource_id)")
        if not db.query(Resource).filter(Resource.id == to).first():
            raise ValueError(f"Risorsa #{to} non trovata")
        for a in b.assignments:
            if a.resource_id == fr:
                remap[a.id] = to

    # Calcola nuovi valori per ogni assignment
    new_values = []
    for a in b.assignments:
        ns = a.start_datetime + delta
        ne = a.end_datetime + delta
        nrid = remap.get(a.id, a.resource_id)
        new_values.append((a, ns, ne, nrid))

    # v3.5.0-alpha.66.16.2 — Sprint R4: pre-flight check unificato via
    # booking_mutate.assert_mutation_safe. Sostituisce 2 blocchi inline
    # (conflict check + slice-lock re-check su NEW dates) con 1 chiamata.
    # Solleva BookingConflict / SliceLocked → re-raise come ValueError (la
    # capability AI traduce ValueError in "failure card" UI).
    from app.services.booking_mutate import (
        assert_mutation_safe, BookingConflict, SliceLocked,
        audit_booking_mutation,
    )
    try:
        assert_mutation_safe(db, b, new_values, force_unlock=False)
    except BookingConflict as e:
        raise ValueError(e.message)
    except SliceLocked as e:
        raise ValueError(
            "Move bloccato: " + e.message +
            " — la nuova posizione del booking ricade in periodo già fatturato."
        )

    # Applica
    for a, ns, ne, nrid in new_values:
        a.start_datetime = ns
        a.end_datetime = ne
        a.resource_id = nrid
    # Ricalcola envelope booking
    b.start_datetime = min(a.start_datetime for a in b.assignments)
    b.end_datetime = max(a.end_datetime for a in b.assignments)
    # v3.5.0-alpha.51.1 fix C2: ricomputa la cost line. Se cambiano risorse
    # cross-reparto, il rate effettivo può variare; se il booking è done, le
    # ore stesse spostano `total_accrued`. Allineato a planning.delete_booking.
    try:
        from app.services.cost_line_sync import recompute_for_booking
        recompute_for_booking(db, b)
    except Exception as _e:
        logger.warning(f"recompute_for_booking failed in propose_move_booking: {_e}")
    # Audit log centralizzato via booking_mutate (R4)
    try:
        audit_booking_mutation(
            db, b,
            kind="ai_move",
            summary=f"AI move ({int(delta.total_seconds()/60)}min, "
                    f"{sum(1 for a in b.assignments if a.id in remap)} risorse rimappate)",
            payload={
                "delta_minutes": int(delta.total_seconds()/60),
                "resources_changed": sum(1 for a in b.assignments if a.id in remap),
            },
        )
    except Exception:
        pass
    return {
        "booking_id": b.id,
        "assignments_count": len(b.assignments),
        "new_start": b.start_datetime.isoformat(),
        "new_end": b.end_datetime.isoformat(),
        "shifted_minutes": int(delta.total_seconds() / 60),
        "resources_changed": sum(1 for a in b.assignments if a.id in remap),
    }


@ai_capability("propose_resize_booking")
def _h_propose_resize_booking(db: Session, data: dict) -> dict:
    """Cambia la durata di un booking modificando end (o start) di tutti gli
    assignment del medesimo delta. Mantenere proporzioni se booking è split
    (più assignment stessa risorsa) — il delta viene applicato all'envelope:
    sib intermedi shiftano in time per mantenere la pausa.

    Payload:
      {
        "booking_id": int,
        "delta_minutes": int (positivo = allunga end, negativo = accorcia)
      }
    """
    from datetime import timedelta as _td
    b = _resolve_booking_for_planning(db, data)
    dm = data.get("delta_minutes")
    if dm is None:
        raise ValueError("Manca 'delta_minutes'")
    try:
        dm = int(dm)
    except (TypeError, ValueError):
        raise ValueError(f"delta_minutes non numerico: {dm}")
    if dm == 0:
        raise ValueError("delta_minutes = 0, niente da fare")

    # Trova l'assignment con end massimo (l'ultimo) e applica delta a esso
    # Per gli altri (split intermedi) lascia invariati. Comportamento intuitivo:
    # "estendi/accorcia il booking" = sposta l'end finale.
    last_a = max(b.assignments, key=lambda a: a.end_datetime)
    new_end = last_a.end_datetime + _td(minutes=dm)
    if new_end <= last_a.start_datetime:
        raise ValueError(
            f"Resize porta end <= start (delta {dm}min troppo negativo). "
            f"Per cancellare il booking usa propose_delete_booking."
        )
    # v3.5.0-alpha.66.16.2 — Sprint R4: pre-flight unificato per resize.
    # Costruisco proposed_assignments con SOLO last_a modificato (gli altri
    # assignment intermedi del booking restano invariati). Combina
    # conflict-check + slice-lock NEW (estensione dentro periodo billed).
    from app.services.booking_mutate import (
        assert_mutation_safe, BookingConflict, SliceLocked,
        audit_booking_mutation,
    )
    proposed = [(last_a, last_a.start_datetime, new_end, last_a.resource_id)]
    try:
        assert_mutation_safe(db, b, proposed, force_unlock=False)
    except BookingConflict as e:
        raise ValueError(f"Resize crea conflitto: {e.message}")
    except SliceLocked as e:
        raise ValueError(
            "Resize bloccato: " + e.message +
            " — l'estensione entra in periodo già fatturato."
        )
    last_a.end_datetime = new_end
    b.end_datetime = max(a.end_datetime for a in b.assignments)
    # v3.5.0-alpha.51.1 fix C2: ricomputa cost line. Se booking è done, le
    # ore-uomo cambiano e quantity_actual / total_accrued vanno aggiornati.
    try:
        from app.services.cost_line_sync import recompute_for_booking
        recompute_for_booking(db, b)
    except Exception as _e:
        logger.warning(f"recompute_for_booking failed in propose_resize_booking: {_e}")
    # Audit log centralizzato via booking_mutate (R4)
    try:
        audit_booking_mutation(
            db, b,
            kind="ai_resize",
            summary=f"AI resize ({dm:+d}min)",
            payload={"delta_minutes": dm, "resized_assignment_id": last_a.id},
        )
    except Exception:
        pass
    return {
        "booking_id": b.id,
        "delta_minutes": dm,
        "new_end": b.end_datetime.isoformat(),
        "resized_assignment_id": last_a.id,
    }


@ai_capability("propose_delete_booking")
def _h_propose_delete_booking(db: Session, data: dict) -> dict:
    """Cancella un booking (soft-delete via status=cancelled).

    Payload: {"booking_id": int, "reason"?: str}

    Soft-delete preserva audit + permette undo via cestino. Il backend
    `delete_booking` standard fa la stessa cosa + recompute cost line.
    """
    b = _resolve_booking_for_planning(db, data)
    reason = (data.get("reason") or "").strip() or None
    b.status = BookingStatus.cancelled
    from app.models import BookingState
    b.state = BookingState.cancelled  # v3.5.0-alpha.66.5.1
    if reason:
        existing = b.notes or ""
        b.notes = (existing + ("\n" if existing else "") + f"[AI cancel] {reason}").strip()
    # Recompute cost line (le ore done finiscono al netto)
    try:
        from app.services.cost_line_sync import recompute_for_booking
        recompute_for_booking(db, b)
    except Exception as _e:
        logger.warning(f"recompute_for_booking failed in propose_delete_booking: {_e}")
    # v3.5.0-alpha.51.1 fix A4: log audit (planning.delete_booking lo fa già)
    try:
        db.add(BookingChange(
            booking_id=b.id, kind="ai_delete",
            summary=f"AI cancel" + (f": {reason}" if reason else ""),
            payload={"reason": reason},
        ))
    except Exception:
        pass
    return {"booking_id": b.id, "status": "cancelled", "reason": reason}


# ── v3.5.0-alpha.54: Capability planning avanzate ──────────────────

@ai_capability("analyze_conflicts")
def _h_analyze_conflicts(db: Session, data: dict) -> dict:
    """READONLY. Trova conflitti orari nei booking di un periodo
    (default = prossimi 14 giorni) e suggerisce risoluzioni.

    Payload: {"days"?: int (default 14), "project_id"?: int, "department_id"?: int}
    """
    from datetime import datetime as _dt, timedelta as _td
    CURRENT_TENANT = 1
    days = int(data.get("days") or 14)
    project_id = data.get("project_id")
    department_id = data.get("department_id")
    now = _dt.utcnow()
    end = now + _td(days=days)
    q = db.query(BookingAssignment).join(Booking).filter(
        Booking.tenant_id == CURRENT_TENANT,
        Booking.status != BookingStatus.cancelled,
        BookingAssignment.start_datetime < end,
        BookingAssignment.end_datetime > now,
    )
    if project_id:
        q = q.filter(Booking.project_id == int(project_id))
    assignments = q.all()
    # Group by resource_id; ordina; trova overlap
    by_res: dict[int, list] = {}
    for a in assignments:
        by_res.setdefault(a.resource_id, []).append(a)
    conflicts = []
    for rid, lst in by_res.items():
        lst.sort(key=lambda x: x.start_datetime)
        for i in range(len(lst) - 1):
            cur, nxt = lst[i], lst[i + 1]
            if nxt.start_datetime < cur.end_datetime:
                if department_id:
                    res = db.query(Resource).filter(Resource.id == rid).first()
                    if not res or res.department_id != int(department_id):
                        continue
                res = db.query(Resource).filter(Resource.id == rid).first()
                conflicts.append({
                    "resource_id": rid,
                    "resource_name": res.name if res else f"#{rid}",
                    "assignment_a_id": cur.id,
                    "booking_a_id": cur.booking_id,
                    "a_start": cur.start_datetime.isoformat(),
                    "a_end": cur.end_datetime.isoformat(),
                    "assignment_b_id": nxt.id,
                    "booking_b_id": nxt.booking_id,
                    "b_start": nxt.start_datetime.isoformat(),
                    "b_end": nxt.end_datetime.isoformat(),
                    "overlap_minutes": int((cur.end_datetime - nxt.start_datetime).total_seconds() / 60),
                    "suggestion": (
                        f"Sposta booking #{nxt.booking_id} dopo {cur.end_datetime.strftime('%d/%m %H:%M')} "
                        f"oppure cambia risorsa, oppure split del booking #{cur.booking_id}."
                    ),
                })
    return {
        "period_start": now.isoformat(),
        "period_end": end.isoformat(),
        "scope_filter": {"project_id": project_id, "department_id": department_id},
        "conflicts_count": len(conflicts),
        "conflicts": conflicts[:50],  # cap per tener context piccolo
    }


@ai_capability("find_free_slots")
def _h_find_free_slots(db: Session, data: dict) -> dict:
    """READONLY. Cerca slot liberi per una risorsa (o reparto) in un periodo.

    Payload: {
      "resource_id"?: int (alternativa: department_id per cercare su tutte le risorse del reparto),
      "department_id"?: int,
      "duration_minutes": int (durata richiesta),
      "from_date"?: "YYYY-MM-DD" (default oggi),
      "days"?: int (default 7),
      "work_hours_start"?: "HH:MM" (default "09:00"),
      "work_hours_end"?: "HH:MM" (default "18:00"),
    }
    """
    from datetime import datetime as _dt, timedelta as _td, date as _d, time as _t
    CURRENT_TENANT = 1
    duration_min = int(data.get("duration_minutes") or 0)
    if duration_min <= 0:
        raise ValueError("duration_minutes deve essere > 0")
    from_str = data.get("from_date")
    start_d = _d.fromisoformat(from_str) if from_str else _d.today()
    days = int(data.get("days") or 7)
    end_d = start_d + _td(days=days)
    wh_start = data.get("work_hours_start") or "09:00"
    wh_end = data.get("work_hours_end") or "18:00"
    h_s = _t.fromisoformat(wh_start)
    h_e = _t.fromisoformat(wh_end)
    # Risolvi risorse target
    rids: list[int] = []
    if data.get("resource_id"):
        rids = [int(data["resource_id"])]
    elif data.get("department_id"):
        ress = db.query(Resource).filter(
            Resource.department_id == int(data["department_id"]),
            Resource.is_active == True,  # noqa
        ).all()
        rids = [r.id for r in ress]
    else:
        raise ValueError("Specifica resource_id o department_id")
    if not rids:
        return {"slots": [], "reason": "no_resources_in_scope"}
    # Booking esistenti per le risorse target nell'intervallo
    busy_by_res: dict[int, list] = {rid: [] for rid in rids}
    rows = db.query(BookingAssignment).join(Booking).filter(
        Booking.tenant_id == CURRENT_TENANT,
        Booking.status != BookingStatus.cancelled,
        BookingAssignment.resource_id.in_(rids),
        BookingAssignment.start_datetime < _dt.combine(end_d, h_e),
        BookingAssignment.end_datetime > _dt.combine(start_d, h_s),
    ).all()
    for a in rows:
        busy_by_res.setdefault(a.resource_id, []).append((a.start_datetime, a.end_datetime))
    # Trova slot liberi: scan per giorno × risorsa, salta intervalli busy
    slots = []
    cap = 30  # cap output
    cur_d = start_d
    while cur_d < end_d and len(slots) < cap:
        if cur_d.weekday() >= 5:  # salta sab/dom default
            cur_d += _td(days=1)
            continue
        day_start = _dt.combine(cur_d, h_s)
        day_end = _dt.combine(cur_d, h_e)
        for rid in rids:
            busy = sorted([(s, e) for (s, e) in busy_by_res.get(rid, []) if e > day_start and s < day_end])
            cursor = day_start
            for (b_s, b_e) in busy:
                if b_s > cursor:
                    free_min = int((b_s - cursor).total_seconds() / 60)
                    if free_min >= duration_min:
                        slots.append({
                            "resource_id": rid,
                            "start": cursor.isoformat(),
                            "end": (cursor + _td(minutes=duration_min)).isoformat(),
                            "available_minutes": free_min,
                        })
                        if len(slots) >= cap:
                            break
                cursor = max(cursor, b_e)
            if cursor < day_end and len(slots) < cap:
                free_min = int((day_end - cursor).total_seconds() / 60)
                if free_min >= duration_min:
                    slots.append({
                        "resource_id": rid,
                        "start": cursor.isoformat(),
                        "end": (cursor + _td(minutes=duration_min)).isoformat(),
                        "available_minutes": free_min,
                    })
        cur_d += _td(days=1)
    return {
        "duration_minutes": duration_min,
        "from_date": start_d.isoformat(),
        "to_date": end_d.isoformat(),
        "scope": {"resource_ids": rids, "department_id": data.get("department_id")},
        "slots_count": len(slots),
        "slots": slots,
    }


@ai_capability("propose_recurring_bookings")
def _h_propose_recurring_bookings(db: Session, data: dict) -> dict:
    """MUTATION. Crea una serie ricorrente di booking dal lunedì al venerdì
    (o regola custom). Atomic per occorrenza, conflict check on each.

    Payload: {
      "job_id": int,
      "job_cost_line_id"?: int,
      "resource_id": int,
      "rule": "DAILY" | "WEEKDAYS" | "WEEKENDS" | csv giorni "MON,WED,FRI",
      "start_date": "YYYY-MM-DD",
      "until_date": "YYYY-MM-DD",
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "title"?: str,
    }
    """
    from datetime import datetime as _dt, timedelta as _td, date as _d, time as _t
    from app.models import BookingKind
    CURRENT_TENANT = 1
    DAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}

    # v3.5.0-alpha.172.15 — Resolver job_id robusto:
    # Accetta job_id diretto OPPURE quote_id/quote_number/project_id (fallback)
    # per evitare allucinazione "Job #4" su number che è Quote/Project id.
    # v3.5.0-alpha.172.25 — Resolver esteso: se l'AI passa solo
    # job_cost_line_id (caso comune dopo che ha visto LAVORAZIONI DEI JOB nel
    # context), deriviamo job_id dalla JCL stessa. La JCL è univoca → 1 solo job.
    job_id = data.get("job_id")
    if not job_id:
        from app.models import Quote as _Q, Project as _P
        # Fallback 0: job_cost_line_id → JCL.job_id
        jcl_hint = data.get("job_cost_line_id")
        if jcl_hint:
            jcl_row = db.query(JobCostLine).filter(JobCostLine.id == int(jcl_hint)).first()
            if jcl_row and jcl_row.job_id:
                job_id = jcl_row.job_id
        # Fallback 1: quote_id
        qid = data.get("quote_id")
        if not job_id and qid:
            q = db.query(_Q).filter(_Q.id == int(qid)).first()
            if q and q.job:
                job_id = q.job.id
        # Fallback 2: quote_number
        if not job_id and data.get("quote_number"):
            q = db.query(_Q).filter(_Q.number == str(data["quote_number"])).first()
            if q and q.job:
                job_id = q.job.id
        # Fallback 3: project_id (prendi job approved più recente)
        if not job_id and data.get("project_id"):
            j = (db.query(Job)
                 .filter(Job.project_id == int(data["project_id"]),
                         Job.status.in_([JobStatus.approved, JobStatus.active]))
                 .order_by(Job.id.desc()).first())
            if j:
                job_id = j.id
        if not job_id:
            raise ValueError(
                "job non risolto. Passa job_cost_line_id (lavorazione), "
                "quote_id o project_id."
            )
    # v3.5.0-alpha.172.17 — Multi-resource: 1 booking con N assignments
    # invece di N booking separati (evita doppia rendicontazione CR).
    # Back-compat: accetta `resource_id` singolo OR `resource_ids` array.
    rids_in = data.get("resource_ids")
    if rids_in is None:
        rid_single = int(data.get("resource_id") or 0)
        rids = [rid_single] if rid_single else []
    else:
        if not isinstance(rids_in, list):
            raise ValueError("resource_ids deve essere un array")
        rids = [int(r) for r in rids_in if r]
    if not rids:
        raise ValueError("resource_id o resource_ids obbligatorio")
    start_d = _d.fromisoformat(data["start_date"])
    until_d = _d.fromisoformat(data["until_date"])
    start_t = _t.fromisoformat(data["start_time"])
    end_t = _t.fromisoformat(data["end_time"])
    if end_t <= start_t:
        raise ValueError("end_time deve essere > start_time (overnight non supportato)")
    rule = (data.get("rule") or "WEEKDAYS").upper().strip()
    if rule == "DAILY":
        days = set(range(7))
    elif rule == "WEEKDAYS":
        days = {0, 1, 2, 3, 4}
    elif rule == "WEEKENDS":
        days = {5, 6}
    else:
        days = {DAYS[d.strip()[:3].upper()] for d in rule.split(",") if d.strip()}
    if not days:
        raise ValueError(f"Regola ricorrenza non valida: {rule}")
    job = db.query(Job).filter(Job.id == int(job_id)).first()
    if not job:
        raise ValueError(f"Job #{job_id} non trovato")
    for _rid in rids:
        if not db.query(Resource).filter(Resource.id == _rid).first():
            raise ValueError(f"Risorsa #{_rid} non trovata")

    # v3.5.0-alpha.172.17 — HARD-BLOCK booking project senza JCL.
    # I booking kind=project DEVONO essere associati a una lavorazione (JCL)
    # del job, altrimenti il cost report non li attribuisce e si crea "lavoro
    # fantasma". UI normale lo richiede già, AI bypassava il check.
    jcl_id = data.get("job_cost_line_id")
    if not jcl_id:
        raise ValueError(
            f"job_cost_line_id obbligatorio per booking kind=project. "
            f"Scegli una lavorazione del Job #{job.id} ({job.code}) dal context "
            f"(sezione JOB ATTIVI mostra le voci) o passa quote_line_id."
        )
    # Verifica JCL coerente col job
    _jcl = db.query(JobCostLine).filter(JobCostLine.id == int(jcl_id)).first()
    if not _jcl or _jcl.job_id != job.id:
        raise ValueError(
            f"JobCostLine #{jcl_id} non appartiene al Job #{job.id}. "
            f"Scegli una JCL del job corretto."
        )

    title = (data.get("title") or "").strip() or f"Ricorrente {rule.lower()}"
    created = []
    skipped_conflict = []
    cur_d = start_d
    while cur_d <= until_d:
        if cur_d.weekday() in days:
            ns = _dt.combine(cur_d, start_t)
            ne = _dt.combine(cur_d, end_t)
            # conflict check su QUALUNQUE risorsa: se anche solo una è
            # già impegnata, saltiamo il giorno. Doppia booking sulla stessa
            # risorsa NON è ammessa (la PIANIFICAZIONE VIVA segnala duplicate).
            conflict = db.query(BookingAssignment).join(Booking).filter(
                Booking.status != BookingStatus.cancelled,
                BookingAssignment.resource_id.in_(rids),
                BookingAssignment.start_datetime < ne,
                BookingAssignment.end_datetime > ns,
            ).first()
            if conflict:
                skipped_conflict.append(cur_d.isoformat())
                cur_d += _td(days=1)
                continue
            from app.models import BookingState as _BSt
            # 1 SOLO booking per occorrenza, con N assignments (1 per risorsa).
            # Cost report aggrega correttamente: persona + studio = un solo
            # "set" di ore lavorate, no double-count.
            b = Booking(
                tenant_id=CURRENT_TENANT, job_id=job.id,
                start_datetime=ns, end_datetime=ne,
                status=BookingStatus.confirmed, kind=BookingKind.project,
                job_cost_line_id=int(jcl_id),
                state=_BSt.confirmed,
                notes=title if title else None,
            )
            db.add(b); db.flush()
            for _rid in rids:
                db.add(BookingAssignment(
                    booking_id=b.id, resource_id=_rid,
                    start_datetime=ns, end_datetime=ne,
                ))
            try:
                db.add(BookingChange(
                    booking_id=b.id, kind="ai_create_recurring",
                    summary=f"AI recurring create ({rule}, {cur_d}, {len(rids)} risorse)",
                    payload={"rule": rule, "date": cur_d.isoformat(),
                             "resource_ids": rids},
                ))
            except Exception:
                pass
            created.append({"booking_id": b.id, "date": cur_d.isoformat()})
        cur_d += _td(days=1)
    return {
        "rule": rule, "start_date": start_d.isoformat(), "until_date": until_d.isoformat(),
        "created_count": len(created),
        "skipped_conflicts_count": len(skipped_conflict),
        "created": created[:20],
        "skipped_conflicts": skipped_conflict[:20],
    }


@ai_capability("propose_bulk_move")
def _h_propose_bulk_move(db: Session, data: dict) -> dict:
    """MUTATION. Sposta N booking di un delta uniforme. Conflict check
    cross-batch (escludendo gli stessi booking della transazione).

    Payload: {"booking_ids": [int], "shift_minutes": int}
    """
    from datetime import timedelta as _td
    CURRENT_TENANT = 1
    bids_raw = data.get("booking_ids") or []
    if not bids_raw or not isinstance(bids_raw, list):
        raise ValueError("booking_ids deve essere una lista non vuota")
    bids = [int(x) for x in bids_raw]
    sm = int(data.get("shift_minutes") or 0)
    if sm == 0:
        raise ValueError("shift_minutes = 0, niente da fare")

    bookings = db.query(Booking).filter(
        Booking.id.in_(bids),
        Booking.tenant_id == CURRENT_TENANT,
        Booking.status != BookingStatus.cancelled,
    ).all()
    if not bookings:
        raise ValueError("Nessun booking valido in booking_ids")

    # Verifica JCL non locked per ognuno + slice lock granulare
    for b in bookings:
        _assert_jcl_not_locked(db, b)
        _assert_no_blocking_slice(db, b)  # v3.5.0-alpha.59

    delta = _td(minutes=sm)
    aids_set = set()
    for b in bookings:
        for a in b.assignments:
            aids_set.add(a.id)

    # Conflict check escludendo aids della transazione
    for b in bookings:
        for a in b.assignments:
            ns = a.start_datetime + delta
            ne = a.end_datetime + delta
            c = db.query(BookingAssignment).join(Booking).filter(
                Booking.status != BookingStatus.cancelled,
                ~BookingAssignment.id.in_(aids_set),
                BookingAssignment.resource_id == a.resource_id,
                BookingAssignment.start_datetime < ne,
                BookingAssignment.end_datetime > ns,
            ).first()
            if c:
                raise ValueError(
                    f"Conflitto: booking #{b.id} su risorsa #{a.resource_id} "
                    f"({ns.strftime('%d/%m %H:%M')}→{ne.strftime('%H:%M')}) "
                    f"overlap con assignment #{c.id} (booking #{c.booking_id})"
                )

    # Applica
    for b in bookings:
        for a in b.assignments:
            a.start_datetime = a.start_datetime + delta
            a.end_datetime = a.end_datetime + delta
        b.start_datetime = min(a.start_datetime for a in b.assignments)
        b.end_datetime = max(a.end_datetime for a in b.assignments)
        try:
            from app.services.cost_line_sync import recompute_for_booking
            recompute_for_booking(db, b)
        except Exception as _e:
            logger.warning(f"recompute_for_booking failed in bulk_move: {_e}")
        try:
            db.add(BookingChange(
                booking_id=b.id, kind="ai_bulk_move",
                summary=f"AI bulk move ({sm:+d}min)",
                payload={"shift_minutes": sm},
            ))
        except Exception:
            pass

    return {
        "shifted_minutes": sm,
        "moved_count": len(bookings),
        "moved_booking_ids": [b.id for b in bookings],
    }


@ai_capability("query_project_finance")
def _h_query_project_finance(db: Session, data: dict) -> dict:
    """READONLY. Stato finanziario aggregato di un progetto: quotato,
    maturato, atteso, spese, margine, fatturato, incassato, ripartizione
    JCL per billing_status, top job per scostamento.

    Payload: {"project_id": int}
    """
    from sqlalchemy import func as _func
    from app.models import Expense, Invoice
    from app.models.models import InvoiceStatus
    CURRENT_TENANT = 1
    pid = int(data.get("project_id") or 0)
    if not pid:
        raise ValueError("project_id obbligatorio")
    proj = db.query(Project).filter(
        Project.id == pid, Project.tenant_id == CURRENT_TENANT
    ).first()
    if not proj:
        raise ValueError(f"Progetto #{pid} non trovato")

    jobs = db.query(Job).filter(Job.project_id == pid).all()
    if not jobs:
        return {
            "project_id": pid, "project_code": proj.code, "project_title": proj.title,
            "jobs_count": 0, "summary": {}, "billing_status_breakdown": {},
            "invoices": {}, "top_jobs_by_variance": [],
        }
    job_ids = [j.id for j in jobs]

    # JCL aggregati
    cost_lines = []
    for j in jobs:
        cost_lines.extend(j.cost_lines)
    total_quoted   = sum(l.total_quoted   or 0 for l in cost_lines)
    total_accrued  = sum(l.total_accrued  or 0 for l in cost_lines)
    total_expected = sum(l.total_expected or 0 for l in cost_lines)
    budget_quoted  = sum(j.budget_quoted  or 0 for j in jobs)

    # Spese
    total_expenses = db.query(_func.sum(Expense.amount)).filter(
        Expense.job_id.in_(job_ids)
    ).scalar() or 0

    # Fatturato (Invoice sent/paid) + incassato (Invoice paid)
    invoiced = db.query(_func.sum(Invoice.total)).filter(
        Invoice.job_id.in_(job_ids),
        Invoice.status.in_([InvoiceStatus.sent, InvoiceStatus.paid]),
    ).scalar() or 0
    paid = db.query(_func.sum(Invoice.total)).filter(
        Invoice.job_id.in_(job_ids),
        Invoice.status == InvoiceStatus.paid,
    ).scalar() or 0

    # Billing status breakdown su JCL
    bs = {"not_billed": 0.0, "in_batch": 0.0, "billed": 0.0, "paid": 0.0, "lost": 0.0}
    for l in cost_lines:
        st = l.billing_status.value if l.billing_status else "not_billed"
        amt = (l.billed_amount if st in ("billed", "paid") and l.billed_amount is not None
               else l.total_accrued)
        if st in bs:
            bs[st] += amt or 0

    margin = total_quoted - (total_expected + (total_expenses or 0))

    # Top 5 job per scostamento (over-under = quoted − expected)
    job_variances = []
    for j in jobs:
        jq = sum(l.total_quoted   or 0 for l in j.cost_lines)
        je = sum(l.total_expected or 0 for l in j.cost_lines)
        job_variances.append({
            "job_id": j.id, "code": j.code, "title": j.title,
            "status": j.status.value if hasattr(j.status, "value") else str(j.status),
            "quoted": round(jq, 2), "expected": round(je, 2),
            "variance": round(jq - je, 2),
        })
    job_variances.sort(key=lambda x: x["variance"])  # più rosso prima

    return {
        "project_id": pid,
        "project_code": proj.code,
        "project_title": proj.title,
        "jobs_count": len(jobs),
        "summary": {
            "budget_quoted":  round(budget_quoted, 2),
            "total_quoted":   round(total_quoted, 2),
            "total_accrued":  round(total_accrued, 2),
            "total_expected": round(total_expected, 2),
            "total_expenses": round(total_expenses, 2),
            "margin":         round(margin, 2),
            "over_under":     round(total_quoted - total_expected, 2),
        },
        "billing_status_breakdown": {k: round(v, 2) for k, v in bs.items()},
        "invoices": {
            "invoiced": round(invoiced, 2),
            "paid":     round(paid, 2),
            "to_collect": round((invoiced or 0) - (paid or 0), 2),
        },
        "top_jobs_by_variance": job_variances[:5],
    }


# ── Capitolati → quote (v3.5.0-alpha.69) ──────────────────────

@ai_capability("propose_quote_from_template")
def _h_propose_quote_from_template(db: Session, data: dict) -> dict:
    """MUTATION. Carica suggested_items di un DeliveryTemplate dentro una
    quote esistente (bulk-add). Skip duplicati + voci con price_item
    mancante. Idempotente."""
    from app.models import DeliveryTemplate, PriceLevel
    # Resolve template
    t = None
    tid = data.get("template_id")
    if tid:
        t = db.query(DeliveryTemplate).filter(
            DeliveryTemplate.id == int(tid),
            DeliveryTemplate.tenant_id == CURRENT_TENANT,
        ).first()
    if not t:
        code = (data.get("template_code") or "").strip().upper()
        if code:
            t = db.query(DeliveryTemplate).filter(
                DeliveryTemplate.code == code,
                DeliveryTemplate.tenant_id == CURRENT_TENANT,
            ).first()
    if not t:
        raise ValueError(
            f"Template non trovato (template_id={tid!r}, template_code={data.get('template_code')!r})."
        )
    items = t.suggested_items or []
    if not items:
        raise ValueError(
            f"Il template {t.code} non ha suggested_items configurate. "
            "Vai in /delivery-templates e popola le voci suggerite prima."
        )
    # Resolve quote
    q = _resolve_quote(db, data)
    if q.status in (QuoteStatus.approved, QuoteStatus.rejected):
        raise ValueError(f"Quote {q.number} in stato {q.status.value}, non modificabile")
    # Price level
    level_str = (data.get("price_level") or "list_price").strip()
    try:
        price_level = PriceLevel(level_str)
    except ValueError:
        price_level = PriceLevel.list_price
    existing_pi = {l.price_item_id for l in q.lines if l.price_item_id}
    sort_order = max((l.sort_order for l in q.lines), default=0)
    added = 0
    skipped_dup = 0
    skipped_missing = 0
    section_counters: dict[str, int] = {}
    for it in items:
        pid = it.get("price_item_id")
        if not pid:
            skipped_missing += 1
            continue
        if pid in existing_pi:
            skipped_dup += 1
            continue
        item = db.query(PriceItem).filter(
            PriceItem.id == int(pid),
            PriceItem.tenant_id == CURRENT_TENANT,
            PriceItem.is_active == True,  # noqa: E712
        ).first()
        if not item:
            skipped_missing += 1
            continue
        price = {
            PriceLevel.list_price: item.price_list,
            PriceLevel.average: item.price_average,
            PriceLevel.low: item.price_low,
        }.get(price_level, item.price_list) or 0.0
        section = (it.get("section") or "A").strip().upper()[:1]
        section_counters[section] = section_counters.get(section, 0) + 1
        position = f"{section}.{section_counters[section]}"
        sort_order += 10
        qty = float(it.get("qty_hint") or 1)
        from app.models import QuoteLine
        line = QuoteLine(
            quote_id=q.id,
            description=item.name,
            section=section,
            position=position,
            detail=(it.get("notes") or None),
            quantity=qty,
            unit=item.unit,
            price_level=price_level,
            unit_price=price,
            allowance=0.0,
            line_discount_pct=0.0,
            total=0.0,
            hardcosts=0.0,
            price_item_id=item.id,
            sort_order=sort_order,
            is_optional=False,
        )
        db.add(line)
        added += 1
        existing_pi.add(item.id)
    if added > 0:
        from app.routers.quotes import _recalc_quote
        db.flush()
        db.refresh(q)
        _recalc_quote(q)
    return {
        "ok": True,
        "template_id": t.id,
        "template_code": t.code,
        "quote_id": q.id,
        "quote_number": q.number,
        "added": added,
        "skipped_duplicate": skipped_dup,
        "skipped_missing": skipped_missing,
        "message": (
            f"Aggiunte {added} righe da template {t.code} alla quote {q.number}. "
            f"({skipped_dup} duplicati + {skipped_missing} mancanti saltati)"
        ),
    }


# ── Asset inventory AI (v3.5.0-alpha.76) ──────────────────────

@ai_capability("query_physical_assets")
def _h_query_physical_assets(db: Session, data: dict) -> dict:
    from app.models import PhysicalAsset, PhysicalAssetKind, AssetOwnerType
    q = db.query(PhysicalAsset).filter(
        PhysicalAsset.tenant_id == CURRENT_TENANT,
        PhysicalAsset.deleted_at.is_(None),
    )
    if data.get("kind"):
        try: q = q.filter(PhysicalAsset.kind == PhysicalAssetKind(data["kind"]))
        except ValueError: pass
    if data.get("owner_type"):
        try: q = q.filter(PhysicalAsset.owner_type == AssetOwnerType(data["owner_type"]))
        except ValueError: pass
    if data.get("client_id"):
        q = q.filter(PhysicalAsset.owner_client_id == int(data["client_id"]))
    if data.get("logistics_status"):
        q = q.filter(PhysicalAsset.logistics_status == data["logistics_status"])
    qq = (data.get("q") or "").strip().lower()
    rows = q.order_by(PhysicalAsset.created_at.desc()).limit(int(data.get("limit") or 50)).all()
    if qq:
        rows = [
            r for r in rows
            if qq in (r.label or "").lower()
            or qq in (r.serial_number or "").lower()
            or qq in (r.barcode or "").lower()
            or qq in (r.location or "").lower()
        ]
    return {
        "count": len(rows),
        "assets": [
            {
                "id": r.id, "label": r.label,
                "kind": r.kind.value if r.kind else None,
                "owner_type": r.owner_type.value if r.owner_type else None,
                "owner_client_id": r.owner_client_id,
                "serial_number": r.serial_number, "barcode": r.barcode,
                "capacity_gb": r.capacity_gb, "location": r.location,
                "logistics_status": r.logistics_status,
            }
            for r in rows
        ],
    }


@ai_capability("query_asset_contents")
def _h_query_asset_contents(db: Session, data: dict) -> dict:
    from app.models import PhysicalAsset, AssetMembership, Asset
    pa = None
    pid = data.get("physical_asset_id")
    if pid:
        pa = db.query(PhysicalAsset).filter(
            PhysicalAsset.id == int(pid),
            PhysicalAsset.tenant_id == CURRENT_TENANT,
        ).first()
    if not pa:
        lbl = (data.get("label") or "").strip()
        if lbl:
            pa = db.query(PhysicalAsset).filter(
                PhysicalAsset.label == lbl,
                PhysicalAsset.tenant_id == CURRENT_TENANT,
            ).first()
    if not pa:
        raise ValueError(
            f"Asset fisico non trovato (id={pid!r}, label={data.get('label')!r})"
        )
    include_removed = bool(data.get("include_removed", False))
    q = db.query(AssetMembership).filter(
        AssetMembership.physical_asset_id == pa.id,
        AssetMembership.tenant_id == CURRENT_TENANT,
    )
    if not include_removed:
        q = q.filter(AssetMembership.removed_at.is_(None))
    rows = q.order_by(AssetMembership.added_at.desc()).all()
    a_ids = list({r.asset_id for r in rows})
    a_map = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(a_ids)).all()} if a_ids else {}
    return {
        "physical_asset_id": pa.id,
        "physical_asset_label": pa.label,
        "physical_asset_kind": pa.kind.value if pa.kind else None,
        "count": len(rows),
        "contents": [
            {
                "membership_id": r.id,
                "asset_id": r.asset_id,
                "asset_name": (a_map.get(r.asset_id).original_name if a_map.get(r.asset_id) else None),
                "path_on_media": r.path_on_media,
                "checksum": r.checksum,
                "file_size": r.file_size,
                "added_at": str(r.added_at)[:19] if r.added_at else None,
                "removed_at": str(r.removed_at)[:19] if r.removed_at else None,
                "is_present": r.removed_at is None,
            }
            for r in rows
        ],
    }


@ai_capability("propose_asset_movement")
def _h_propose_asset_movement(db: Session, data: dict) -> dict:
    """MUTATION. Crea AssetMovement per PhysicalAsset (DDT auto)."""
    from app.models import PhysicalAsset, AssetMovement, AssetMovementType
    pa = None
    pid = data.get("physical_asset_id")
    if pid:
        pa = db.query(PhysicalAsset).filter(
            PhysicalAsset.id == int(pid),
            PhysicalAsset.tenant_id == CURRENT_TENANT,
        ).first()
    if not pa:
        lbl = (data.get("asset_label") or "").strip()
        if lbl:
            pa = db.query(PhysicalAsset).filter(
                PhysicalAsset.label == lbl,
                PhysicalAsset.tenant_id == CURRENT_TENANT,
            ).first()
    if not pa:
        raise ValueError("Asset fisico non trovato")
    try:
        mt = AssetMovementType(data.get("movement_type") or "")
    except ValueError:
        raise ValueError(f"movement_type non valido: {data.get('movement_type')}")
    from app.routers.physical_assets import _next_ddt_number
    ddt = _next_ddt_number(db)
    m = AssetMovement(
        tenant_id=CURRENT_TENANT,
        physical_asset_id=pa.id,
        movement_type=mt,
        delivery_note_number=ddt,
        from_party=(data.get("from_party") or "").strip() or None,
        to_party=(data.get("to_party") or "").strip() or None,
        carrier=(data.get("carrier") or "").strip() or None,
        tracking_number=(data.get("tracking_number") or "").strip() or None,
        package_count=int(data.get("package_count") or 1),
        total_weight_kg=data.get("total_weight_kg"),
        notes=(data.get("notes") or "").strip() or None,
    )
    db.add(m); db.flush()
    return {
        "ok": True,
        "movement_id": m.id,
        "delivery_note_number": ddt,
        "physical_asset_id": pa.id,
        "physical_asset_label": pa.label,
        "movement_type": mt.value,
        "message": f"Movimento {mt.value} creato per {pa.label} con DDT {ddt}. Conferma consegna a parte.",
    }


# ── Query supplier / fatture passive read-only (v3.5.0-alpha.71) ──

@ai_capability("query_suppliers")
def _h_query_suppliers(db: Session, data: dict) -> dict:
    """READONLY. Lista fornitori con KPI outstanding + overdue count.
    Filtri opzionali: q (nome contiene), only_with_outstanding."""
    from app.models import Supplier, SupplierInvoice, SupplierInvoiceStatus
    from datetime import date as _d
    q_str = (data.get("q") or "").strip().lower()
    only_outstanding = bool(data.get("only_with_outstanding", False))
    rows = db.query(Supplier).filter(
        Supplier.tenant_id == CURRENT_TENANT,
        Supplier.deleted_at.is_(None),
        Supplier.is_active == True,  # noqa: E712
    ).all()
    if q_str:
        rows = [r for r in rows if q_str in (r.name or "").lower()]
    today = _d.today()
    out = []
    for s in rows:
        invs = db.query(SupplierInvoice).filter(
            SupplierInvoice.supplier_id == s.id,
            SupplierInvoice.tenant_id == CURRENT_TENANT,
            SupplierInvoice.deleted_at.is_(None),
            SupplierInvoice.payment_status != SupplierInvoiceStatus.cancelled,
        ).all()
        outstanding = sum(
            (i.amount_total or 0) - (i.amount_paid or 0)
            for i in invs
            if i.payment_status != SupplierInvoiceStatus.paid
        )
        overdue = sum(
            1 for i in invs
            if i.due_date and i.due_date < today
            and i.payment_status != SupplierInvoiceStatus.paid
        )
        if only_outstanding and outstanding <= 0:
            continue
        out.append({
            "supplier_id": s.id,
            "name": s.name,
            "vat_number": s.vat_number,
            "invoices_count": len(invs),
            "outstanding": round(outstanding, 2),
            "overdue_count": overdue,
        })
    out.sort(key=lambda r: r["outstanding"], reverse=True)
    return {
        "count": len(out),
        "suppliers": out[:50],
        "total_outstanding": round(sum(r["outstanding"] for r in out), 2),
    }


@ai_capability("query_supplier_invoices")
def _h_query_supplier_invoices(db: Session, data: dict) -> dict:
    """READONLY. Lista fatture passive filtrate.
    Filtri: supplier_id|supplier_name, status (unpaid/partial/paid),
    only_overdue, project_id, job_id, limit (default 30)."""
    from app.models import Supplier, SupplierInvoice, SupplierInvoiceStatus
    from datetime import date as _d
    q = db.query(SupplierInvoice).options(
        joinedload(SupplierInvoice.supplier)
    ).filter(
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
    )
    sup_id = data.get("supplier_id")
    if sup_id:
        q = q.filter(SupplierInvoice.supplier_id == int(sup_id))
    sup_name = (data.get("supplier_name") or "").strip()
    if sup_name and not sup_id:
        sup = db.query(Supplier).filter(
            Supplier.name == sup_name,
            Supplier.tenant_id == CURRENT_TENANT,
            Supplier.deleted_at.is_(None),
        ).first()
        if sup:
            q = q.filter(SupplierInvoice.supplier_id == sup.id)
        else:
            return {"count": 0, "invoices": [], "message": f"Fornitore '{sup_name}' non trovato"}
    status = (data.get("status") or "").strip()
    if status:
        try:
            st = SupplierInvoiceStatus(status)
            q = q.filter(SupplierInvoice.payment_status == st)
        except ValueError:
            raise ValueError(f"Stato non valido: {status}")
    if data.get("only_overdue"):
        q = q.filter(
            SupplierInvoice.due_date < _d.today(),
            SupplierInvoice.payment_status.in_([
                SupplierInvoiceStatus.unpaid, SupplierInvoiceStatus.partial,
            ]),
        )
    if data.get("project_id"):
        q = q.filter(SupplierInvoice.project_id == int(data["project_id"]))
    if data.get("job_id"):
        q = q.filter(SupplierInvoice.job_id == int(data["job_id"]))
    limit = min(int(data.get("limit") or 30), 100)
    rows = q.order_by(SupplierInvoice.issue_date.desc()).limit(limit).all()
    return {
        "count": len(rows),
        "invoices": [
            {
                "id": i.id,
                "supplier_id": i.supplier_id,
                "supplier_name": i.supplier.name if i.supplier else None,
                "number": i.number,
                "issue_date": str(i.issue_date) if i.issue_date else None,
                "due_date": str(i.due_date) if i.due_date else None,
                "amount_net": i.amount_net,
                "amount_total": i.amount_total,
                "amount_paid": i.amount_paid,
                "outstanding": round((i.amount_total or 0) - (i.amount_paid or 0), 2),
                "status": i.payment_status.value if i.payment_status else None,
            }
            for i in rows
        ],
    }


# ── Send invoice email (v3.5.0-alpha.130) ─────────────────────

@ai_capability("propose_send_invoice_email")
def _h_propose_send_invoice_email(db: Session, data: dict) -> dict:
    """MUTATION. Invia fattura via email cliente con PDF allegato.

    Args (uno fra invoice_id/invoice_number richiesto):
    - invoice_id: ID fattura
    - invoice_number: fallback se ID ignoto, cerca per number
    - recipient_override: email diverso da admin_email cliente (opzionale)

    Riusa `app.services.invoice_email.send_invoice_via_smtp`. Errori
    sollevati come ValueError per integration con apply_action.
    """
    from app.services.invoice_email import send_invoice_via_smtp, InvoiceEmailError
    invoice_id = data.get("invoice_id")
    invoice_number = (data.get("invoice_number") or "").strip()
    if not invoice_id and invoice_number:
        from app.models import Invoice as _Inv
        row = db.query(_Inv).filter(
            _Inv.number == invoice_number,
        ).first()
        if not row:
            raise ValueError(f"Fattura con numero '{invoice_number}' non trovata")
        invoice_id = row.id
    if not invoice_id:
        raise ValueError("Manca invoice_id o invoice_number")
    recipient = (data.get("recipient_override") or "").strip() or None
    try:
        result = send_invoice_via_smtp(db, int(invoice_id), recipient_override=recipient)
    except InvoiceEmailError as e:
        raise ValueError(f"[{e.code}] {e.message}")
    return result


# ── Filesystem asset library query (v3.5.0-alpha.129) ────────

@ai_capability("query_filesystem")
def _h_query_filesystem(db: Session, data: dict) -> dict:
    """READONLY. Lista file/cartelle in un path filesystem.

    Sicurezza:
    - Path richiesto deve essere ENTRO la whitelist `Tenant.fs_scan_allowed_paths`.
    - No path traversal (resolve + relative_to check).
    - Limite max_depth (≤8) e max_results (≤500) per evitare scan invasivi.

    Pattern uso: AI assistente domanda "cosa c'è in X" e fornisce path
    autorizzato. Risposta include nome relativo, size, mtime, mime_type.
    """
    from pathlib import Path as _P
    import fnmatch as _fnm
    import mimetypes as _mime
    from datetime import datetime as _dt
    from app.models import Tenant as _Tenant

    raw_path = (data.get("path") or "").strip()
    if not raw_path:
        raise ValueError("Manca 'path'")
    glob_pattern = (data.get("glob_pattern") or "").strip()
    max_depth = max(1, min(int(data.get("max_depth") or 4), 8))
    max_results = max(1, min(int(data.get("max_results") or 100), 500))

    # Whitelist tenant
    t = db.query(_Tenant).filter(_Tenant.id == CURRENT_TENANT).first()
    allowed = t.fs_scan_allowed_paths if t else None
    if not allowed:
        return {
            "error": "Nessun path filesystem autorizzato per questo tenant. "
                     "Configura whitelist in /settings → fs-scan-paths.",
            "files": [],
            "count": 0,
        }

    try:
        target = _P(raw_path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as e:
        return {"error": f"Path non valido: {e}", "files": [], "count": 0}

    # Verifica target sia dentro almeno uno dei path autorizzati
    target_str = str(target).lower()
    authorized = False
    for p in allowed:
        try:
            allow_p = _P(p).expanduser().resolve(strict=False)
        except Exception:
            continue
        try:
            target.relative_to(allow_p)
            authorized = True
            break
        except ValueError:
            # match prefix case-insensitive su windows (resolve può differire)
            if target_str.startswith(str(allow_p).lower()):
                authorized = True
                break
    if not authorized:
        return {
            "error": f"Path '{raw_path}' fuori dalla whitelist autorizzata "
                     f"(consentiti: {allowed}).",
            "files": [],
            "count": 0,
        }

    if not target.exists():
        return {"error": f"Path non esistente: {target}", "files": [], "count": 0}
    if not target.is_dir():
        # Singolo file: ritorna metadata
        try:
            st = target.stat()
            mime, _ = _mime.guess_type(target.name)
            return {
                "count": 1,
                "files": [{
                    "name": target.name,
                    "relative_path": target.name,
                    "is_dir": False,
                    "size": st.st_size,
                    "size_human": _human_size(st.st_size),
                    "mtime": _dt.fromtimestamp(st.st_mtime).isoformat(),
                    "mime_type": mime,
                }],
                "base_path": str(target.parent),
            }
        except OSError as e:
            return {"error": str(e), "files": [], "count": 0}

    # Walk con depth limit
    results: list[dict] = []
    base = target

    def _walk(d: _P, depth: int):
        if len(results) >= max_results:
            return
        if depth > max_depth:
            return
        try:
            for child in sorted(d.iterdir()):
                if len(results) >= max_results:
                    return
                try:
                    st = child.stat()
                except OSError:
                    continue
                is_dir = child.is_dir()
                rel = child.relative_to(base).as_posix()
                if glob_pattern and not is_dir:
                    if not _fnm.fnmatch(child.name, glob_pattern):
                        if depth < max_depth:
                            continue
                        continue
                mime = None
                if not is_dir:
                    mime, _ = _mime.guess_type(child.name)
                results.append({
                    "name": child.name,
                    "relative_path": rel,
                    "is_dir": is_dir,
                    "size": st.st_size if not is_dir else None,
                    "size_human": _human_size(st.st_size) if not is_dir else None,
                    "mtime": _dt.fromtimestamp(st.st_mtime).isoformat(),
                    "mime_type": mime,
                })
                if is_dir:
                    _walk(child, depth + 1)
        except PermissionError:
            return

    _walk(base, 1)
    truncated = len(results) >= max_results
    return {
        "count": len(results),
        "files": results,
        "base_path": str(base),
        "glob_pattern": glob_pattern or None,
        "truncated": truncated,
    }


def _human_size(size: int) -> str:
    """Formatta byte in KB/MB/GB human-readable."""
    if size is None:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} PB"


# ── Supplier / fatture passive (v3.5.0-alpha.68.5) ────────────

@ai_capability("propose_supplier")
def _h_propose_supplier(db: Session, data: dict) -> dict:
    """MUTATION. Crea nuovo fornitore (anagrafica commessa esterna).
    Solo `name` obbligatorio."""
    from app.models import Supplier
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Manca 'name'")
    s = Supplier(
        tenant_id=CURRENT_TENANT,
        name=name,
        vat_number=(data.get("vat_number") or "").strip() or None,
        tax_code=(data.get("tax_code") or "").strip() or None,
        contact_email=(data.get("contact_email") or "").strip() or None,
        contact_phone=(data.get("contact_phone") or "").strip() or None,
        address=(data.get("address") or "").strip() or None,
        iban=(data.get("iban") or "").strip() or None,
        default_payment_terms_days=data.get("default_payment_terms_days"),
        notes=(data.get("notes") or "").strip() or None,
    )
    db.add(s)
    db.flush()
    return {
        "created": True,
        "supplier_id": s.id,
        "name": s.name,
        "message": f"Fornitore '{s.name}' creato con id={s.id}.",
    }


@ai_capability("propose_supplier_invoice")
def _h_propose_supplier_invoice(db: Session, data: dict) -> dict:
    """MUTATION. Registra una fattura passiva. Richiede supplier_id o
    supplier_name esistente, number, issue_date, amount_net."""
    from app.models import Supplier, SupplierInvoice, SupplierInvoiceStatus
    from datetime import date as _d, timedelta
    # Resolve supplier
    sup_id = data.get("supplier_id")
    sup = None
    if sup_id:
        sup = db.query(Supplier).filter(
            Supplier.id == int(sup_id),
            Supplier.tenant_id == CURRENT_TENANT,
            Supplier.deleted_at.is_(None),
        ).first()
    if not sup:
        name = (data.get("supplier_name") or "").strip()
        if name:
            sup = db.query(Supplier).filter(
                Supplier.name == name,
                Supplier.tenant_id == CURRENT_TENANT,
                Supplier.deleted_at.is_(None),
            ).first()
    if not sup:
        raise ValueError(
            f"Fornitore non trovato (supplier_id={sup_id!r}, "
            f"supplier_name={data.get('supplier_name')!r}). "
            "Usa propose_supplier prima per crearlo."
        )
    number = (data.get("number") or "").strip()
    if not number:
        raise ValueError("Manca 'number'")
    issue_str = data.get("issue_date")
    if not issue_str:
        raise ValueError("Manca 'issue_date' (YYYY-MM-DD)")
    issue_date = _d.fromisoformat(issue_str) if isinstance(issue_str, str) else issue_str
    amount_net = float(data.get("amount_net") or 0)
    if amount_net <= 0:
        raise ValueError("'amount_net' deve essere > 0")
    vat_rate = float(data.get("vat_rate") if data.get("vat_rate") is not None else 22.0)
    amount_vat = round(amount_net * (vat_rate / 100.0), 2)
    amount_total = round(amount_net + amount_vat, 2)
    amount_paid = float(data.get("amount_paid") or 0)
    # Pre-check unicità (supplier+number)
    dup = db.query(SupplierInvoice).filter(
        SupplierInvoice.supplier_id == sup.id,
        SupplierInvoice.number == number,
        SupplierInvoice.tenant_id == CURRENT_TENANT,
        SupplierInvoice.deleted_at.is_(None),
    ).first()
    if dup:
        raise ValueError(f"Fattura {number} già registrata per {sup.name}")
    # due_date: explicit, oppure derivato da terms
    due_date = None
    due_str = data.get("due_date")
    if due_str:
        due_date = _d.fromisoformat(due_str) if isinstance(due_str, str) else due_str
    elif sup.default_payment_terms_days:
        due_date = issue_date + timedelta(days=sup.default_payment_terms_days)
    # status
    if amount_paid <= 0:
        status = SupplierInvoiceStatus.unpaid
    elif amount_paid >= amount_total:
        status = SupplierInvoiceStatus.paid
    else:
        status = SupplierInvoiceStatus.partial
    inv = SupplierInvoice(
        tenant_id=CURRENT_TENANT,
        supplier_id=sup.id,
        number=number,
        issue_date=issue_date,
        due_date=due_date,
        project_id=data.get("project_id"),
        job_id=data.get("job_id"),
        job_cost_line_id=data.get("job_cost_line_id"),
        amount_net=amount_net,
        vat_rate=vat_rate,
        amount_vat=amount_vat,
        amount_total=amount_total,
        currency=(data.get("currency") or "EUR").upper(),
        payment_status=status,
        amount_paid=amount_paid,
        notes=(data.get("notes") or "").strip() or None,
    )
    db.add(inv)
    db.flush()
    return {
        "created": True,
        "supplier_invoice_id": inv.id,
        "supplier_id": sup.id,
        "supplier_name": sup.name,
        "number": inv.number,
        "amount_total": inv.amount_total,
        "payment_status": status.value,
        "message": (
            f"Fattura passiva {inv.number} da {sup.name} registrata: "
            f"€{inv.amount_total:.2f} ({status.value})."
        ),
    }


@ai_capability("propose_transmit_to_billing")
def _h_propose_transmit_to_billing(db: Session, data: dict) -> dict:
    """MUTATION. Trasmetti il maturato di un progetto come BillingBatch
    in stato draft. Equivalente al bottone "Trasmetti" dal Cost Report
    ma invocato dall'AI.

    Payload: {"project_id": int, "include_extras"?: bool, "notes"?: str}
    """
    from app.routers.billing import _transmit_core, CURRENT_TENANT as CT
    return _transmit_core(
        db,
        project_id=int(data["project_id"]),
        include_extras=bool(data.get("include_extras", True)),
        notes=(data.get("notes") or None),
    )


# ── Phantom / Quotazione a Consuntivo (v3.5.0-alpha.171.6 Step 8) ──

@ai_capability("propose_promote_phantom")
def _h_propose_promote_phantom(db: Session, data: dict) -> dict:
    """MUTATION. Promuove una Quotazione a Consuntivo standby a quote
    effettiva (is_phantom=False, phantom_status=promoted). Lo status quote
    (di solito approved) resta invariato.

    Payload: {"quote_id": int} (PK numerico Consuntivo).
    """
    from app.models import PhantomStatus
    qid = data.get("quote_id")
    if not qid:
        raise ValueError("quote_id richiesto")
    q = db.query(Quote).filter(
        Quote.id == int(qid),
        Quote.tenant_id == CURRENT_TENANT,
    ).first()
    if not q:
        raise ValueError(f"Quote {qid} non trovata")
    if not q.is_phantom:
        raise ValueError(f"Quote {q.number} non è Quotazione a Consuntivo (is_phantom=False)")
    if q.phantom_status != PhantomStatus.standby:
        raise ValueError(
            f"Quote {q.number} è in stato '{q.phantom_status.value if q.phantom_status else 'unknown'}', "
            f"solo standby può essere promossa."
        )
    q.is_phantom = False
    q.phantom_status = PhantomStatus.promoted
    db.commit()
    return {
        "quote_id": q.id, "quote_number": q.number,
        "status": q.status.value,
        "phantom_status": q.phantom_status.value,
        "promoted": True,
    }


@ai_capability("propose_merge_phantom")
def _h_propose_merge_phantom(db: Session, data: dict) -> dict:
    """MUTATION. Accorpa una Quotazione a Consuntivo standby in una quote
    target (anche approvata). Crea una NUOVA VERSIONE della target con le
    voci della Consuntivo aggiunte.

    Payload: {"source_quote_id": int, "target_quote_id": int}.
    Vincoli: source = Consuntivo standby; target non-phantom, stesso project.
    """
    from app.models import PhantomStatus, QuoteLine
    from app.routers.quotes import _quote_root, _quote_chain, _copy_quote_lines, _recalc_quote
    import re

    src_id = data.get("source_quote_id")
    tgt_id = data.get("target_quote_id")
    if not src_id or not tgt_id:
        raise ValueError("source_quote_id e target_quote_id richiesti")
    src = db.query(Quote).filter(
        Quote.id == int(src_id),
        Quote.tenant_id == CURRENT_TENANT,
    ).first()
    if not src or not src.is_phantom or src.phantom_status != PhantomStatus.standby:
        raise ValueError("Source non è Quotazione a Consuntivo standby")
    tgt = db.query(Quote).filter(
        Quote.id == int(tgt_id),
        Quote.tenant_id == CURRENT_TENANT,
    ).first()
    if not tgt or tgt.is_phantom:
        raise ValueError("Target non valida (non esiste o è phantom)")
    if tgt.project_id != src.project_id:
        raise ValueError("Source e target devono appartenere allo stesso progetto")

    root = _quote_root(db, tgt)
    chain = _quote_chain(db, root)
    next_version = max(q.version for q in chain) + 1
    base_number = re.sub(r"-v\d+$", "", root.number)
    new_number = f"{base_number}-v{next_version}"

    new_q = Quote(
        number=new_number,
        version=next_version,
        parent_quote_id=tgt.id,
        project_id=tgt.project_id,
        client_id=tgt.client_id,
        title=tgt.title,
        status=QuoteStatus.draft,
        issue_date=date.today(),
        valid_until=tgt.valid_until,
        vat_rate=tgt.vat_rate,
        notes=(tgt.notes or "") + f"\n[AI merge] da Consuntivo {src.number}",
        tenant_id=CURRENT_TENANT,
    )
    db.add(new_q); db.flush()

    new_lines_target = _copy_quote_lines(tgt.lines, new_q.id, track_parent=True)
    db.add_all(new_lines_target)
    new_lines_phantom = _copy_quote_lines(src.lines, new_q.id, track_parent=False)
    for nl in new_lines_phantom:
        nl.detail = (nl.detail or "") + f"\n[da Consuntivo {src.number}]"
    db.add_all(new_lines_phantom)
    db.flush()

    _recalc_quote(new_q)

    tgt.superseded_by_id = new_q.id
    if tgt.status != QuoteStatus.superseded:
        tgt.status = QuoteStatus.superseded
    src.phantom_status = PhantomStatus.merged_into
    src.merged_into_quote_id = new_q.id
    db.commit()
    return {
        "new_version_id": new_q.id, "new_version_number": new_q.number,
        "target_id": tgt.id, "target_number": tgt.number,
        "source_id": src.id, "source_number": src.number,
        "lines_from_target": len(new_lines_target),
        "lines_from_phantom": len(new_lines_phantom),
    }


# v3.5.0-alpha.66.17.2 (R6.2) — `_ACTION_HANDLERS` derivato dal registry
# popolato dai decorator `@ai_capability("name")` sopra ogni `_h_*`.
# Manteniamo l'attributo come dict (non funzione) per compat back-compat
# call site `_ACTION_HANDLERS.get(...)`/`_ACTION_HANDLERS[...]`.
# Idem VALID_ACTION_TYPES nel modulo `ai_legacy_parser`: viene rimpiazzato
# in fondo (vedi `_sync_legacy_parser_action_types()`).
_ACTION_HANDLERS = _registry_get_handlers()


def _sync_legacy_parser_action_types() -> None:
    """Aggiorna `ai_legacy_parser.VALID_ACTION_TYPES` con il set derivato
    dal registry. Eseguito una volta a import-time di questo modulo, dopo
    che TUTTI i decorator `@ai_capability` sono stati eseguiti.

    Risolve il drift documentato nell'audit: legacy parser aveva 13 type
    statici hardcoded vs 23 handler reali → 10 capability invisibili al
    parser markdown (path Ollama/Perplexity).
    """
    from app.services import ai_legacy_parser as _legacy
    actual = _registry_get_action_types()
    # Update in-place (set object identity preservata: chi ha fatto
    # `from ai_legacy_parser import VALID_ACTION_TYPES` continua a vederlo).
    _legacy.VALID_ACTION_TYPES.clear()
    _legacy.VALID_ACTION_TYPES.update(actual)


_sync_legacy_parser_action_types()


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
