"""
Router AI — chat copilot context-aware, azioni propose/apply/reject,
upload capitolato, review quotazioni.

In v3.2:
- get_provider() globale sostituito da get_provider_for_user(user_id, db)
- ogni risposta della chat può proporre AIAction da confermare manualmente
- nuovi endpoint per applicare/rifiutare le azioni proposte
"""
from datetime import datetime
import json
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AIConversation, AIMessage, PriceItem, Project, Quote, QuoteLine, PriceLevel, User,
)
from app.models.models import AIAction
from app.services.ai_assistant import (
    chat_with_assistant, review_quote, apply_action, VALID_ACTION_TYPES,
    build_system_prompt,
)
from app.services.ai_loop import advance_loop, resume_after_action
from app.services.ai_provider import get_provider_for_user
from app.services.auth import get_current_user_from_token
from app.services.deliverables_parser import (
    extract_text_from_file, parse_deliverables, match_deliverables_to_pricelist,
)
from app.services.copilot_attachments import (
    save_attachment, embed_attachments_in_text, MAX_FILE_SIZE,
)

router = APIRouter(prefix="/ai", tags=["ai"])


# v3.5.0-alpha.51 — Upload documenti per copilot
@router.post("/api/upload")
async def copilot_upload(file: UploadFile = File(...)):
    """Carica un documento (PDF/DOCX/TXT/MD/immagine) per allegarlo al
    prossimo messaggio del copilot. Ritorna metadata + extracted_text per
    file text-based. Le immagini vengono salvate ma per ora non passate
    al provider come vision (placeholder per α.52).
    """
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File troppo grande (max {MAX_FILE_SIZE // 1024 // 1024} MB)")
    try:
        meta = save_attachment(file.filename or "untitled", content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return meta


def _tpl():
    from app.main import templates
    return templates


def _resolve_current_user(db: Session, token: Optional[str]) -> Optional[User]:
    """Stessa logica di settings.py: cookie JWT, fallback su primo user attivo."""
    if token:
        u = get_current_user_from_token(db, token)
        if u:
            return u
    return db.query(User).filter(User.is_active == True).order_by(User.id).first()


# ── Stato provider ───────────────────────────────────────────

@router.get("/api/status")
async def ai_status(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    provider = get_provider_for_user(u.id if u else None, db)
    from app.config import settings as cfg
    return {
        "configured": provider is not None,
        "provider_name": provider.name if provider else None,
        "active_provider": u.active_ai_provider if u else None,
        "tavily_enabled": bool(cfg.tavily_api_key),
    }


# ── Chat assistant ───────────────────────────────────────────

@router.post("/api/chat")
async def chat(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """
    Body JSON: {messages, project_id?, quote_id?, job_id?, page?, conversation_id?}
    Risposta: {reply, actions: [{id, action_type, title, data}], conversation_id}

    Dispatch:
    - Se provider supporta tool_use nativo (Claude/OpenAI/Gemini) → path nuovo
      basato su `ai_loop.advance_loop` (loop tool_use, mutation gated da Apply,
      readonly auto-eseguite con tool_result re-injected nel modello).
    - Altrimenti (Ollama/Perplexity) → path LEGACY `chat_with_assistant`
      (blocchi markdown ```action``` estratti via regex).
    """
    data = await request.json()
    messages = data.get("messages", [])
    if not messages:
        raise HTTPException(400, "Nessun messaggio")

    user = _resolve_current_user(db, access_token)
    user_id = user.id if user else None

    project_id = data.get("project_id")
    quote_id   = data.get("quote_id")
    job_id     = data.get("job_id")
    page       = data.get("page")
    # v3.5.0-alpha.51 — Allegati copilot inviati col messaggio.
    # Format atteso: list[{file_id, filename, kind, extracted_text, ...}]
    attachments = data.get("attachments") or []
    if attachments and isinstance(attachments, list) and messages:
        # Embed extracted_text inline nell'ultimo messaggio user
        last_msg = messages[-1]
        if last_msg.get("role") == "user":
            original = last_msg.get("content", "")
            last_msg["content"] = embed_attachments_in_text(original, attachments)

    # Risolvi/crea conversazione
    conv_id = data.get("conversation_id")
    conv = None
    if conv_id:
        conv = db.query(AIConversation).filter(AIConversation.id == conv_id).first()
    if conv is None and user_id:
        conv = AIConversation(
            user_id=user_id,
            project_id=project_id, quote_id=quote_id, job_id=job_id,
            title=(messages[0]["content"][:60] if messages else None),
        )
        db.add(conv); db.flush()

    provider = get_provider_for_user(user_id, db)
    if not provider:
        return {
            "reply": "AI non configurata. Vai in Impostazioni → tab AI per scegliere e attivare un provider.",
            "actions": [], "conversation_id": conv.id if conv else None,
            "error": "provider_disabled",
        }

    last_user_content = messages[-1].get("content", "") if messages else ""

    # ── Path 1: provider con tool_use nativo ──────────────────
    if conv and provider.supports_tools():
        system = build_system_prompt(db, use_tools=True, project_id=project_id,
                                     quote_id=quote_id, job_id=job_id, page=page)
        # Per ora ignoriamo `messages` storici dal client: la storia è quella
        # nel tool_state della conversazione (autoritativa). Il client manda
        # solo l'ultimo messaggio utente.
        result = advance_loop(db, conv, provider, system, user_message=last_user_content)

        # Persisti display-friendly delle interazioni
        db.add(AIMessage(conversation_id=conv.id, role="user", content=last_user_content))
        db.add(AIMessage(conversation_id=conv.id, role="assistant", content=result.get("text") or ""))
        db.commit()

        return {
            "reply":           result.get("text") or "",
            "actions":         result.get("actions") or [],
            "conversation_id": conv.id,
            "pending":         not result.get("done", True),
            "error":           result.get("error"),
        }

    # ── Path 2: legacy markdown ```action``` ────────────────────
    result = chat_with_assistant(
        db, messages,
        user_id=user_id,
        project_id=project_id, quote_id=quote_id, job_id=job_id, page=page,
    )

    if conv:
        db.add(AIMessage(conversation_id=conv.id, role="user", content=last_user_content))
        db.add(AIMessage(conversation_id=conv.id, role="assistant", content=result["reply"] or ""))

    saved_actions = []
    for a in (result.get("actions") or []):
        if a.get("type") not in VALID_ACTION_TYPES:
            continue
        act = AIAction(
            conversation_id=conv.id if conv else None,
            user_id=user_id or 0,
            action_type=a["type"],
            payload=json.dumps(a.get("data") or {}, ensure_ascii=False),
            status="proposed",
        )
        db.add(act); db.flush()
        saved_actions.append({
            "id": act.id, "action_type": act.action_type,
            "title": a.get("title") or act.action_type,
            "data": a.get("data") or {}, "status": act.status,
        })

    db.commit()

    return {
        "reply":           result["reply"],
        "actions":         saved_actions,
        "conversation_id": conv.id if conv else None,
        "error":           result.get("error"),
    }


@router.get("/api/conversations")
async def list_conversations(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    if not u:
        return []
    convs = db.query(AIConversation).filter(
        AIConversation.user_id == u.id
    ).order_by(AIConversation.created_at.desc()).limit(20).all()
    return [
        {"id": c.id, "title": c.title, "created_at": c.created_at.isoformat(),
         "message_count": len(c.messages)}
        for c in convs
    ]


@router.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: int, db: Session = Depends(get_db)):
    conv = db.query(AIConversation).filter(AIConversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404)
    return {
        "id": conv.id, "title": conv.title,
        "project_id": conv.project_id, "quote_id": conv.quote_id, "job_id": conv.job_id,
        "messages": [
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in sorted(conv.messages, key=lambda x: x.id)
        ],
    }


# ── Azioni proposte (apply / reject) ─────────────────────────

@router.post("/api/actions/{action_id}/apply")
async def action_apply(
    action_id: int,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    act = db.query(AIAction).filter(AIAction.id == action_id).first()
    if not act:
        raise HTTPException(404, "Azione non trovata")
    if u and act.user_id and act.user_id != u.id:
        raise HTTPException(403, "Azione di un altro utente")
    if act.status != "proposed":
        raise HTTPException(400, f"Azione già in stato {act.status}")

    res = apply_action(db, act)
    if res.get("ok"):
        act.status = "applied"
        act.applied_at = datetime.utcnow()
        act.result = json.dumps(res.get("result") or {}, ensure_ascii=False)
    else:
        act.status = "failed"
        act.result = json.dumps({"error": res.get("error")}, ensure_ascii=False)

    # Resume del loop tool_use se la conversazione era in attesa.
    # Anche su Apply fallito riprendiamo il loop: il modello vedrà il
    # tool_result con `error: ...` e potrà proporre un'alternativa
    # (es. creare prima la quote che mancava).
    continuation = _maybe_resume_loop(db, act, action_result=res.get("result"),
                                      rejected=False, applied_ok=res.get("ok"))
    db.commit()

    # Envelope 200 OK in entrambi i casi: un Apply fallito non è un errore
    # HTTP (la richiesta è stata processata correttamente), è un risultato
    # applicativo che il frontend mostra come stato della card.
    if not res.get("ok"):
        return {
            "ok":           False,
            "status":       "failed",
            "error":        res.get("error") or "Esecuzione fallita",
            "continuation": continuation,
        }
    return {
        "ok":           True,
        "status":       "applied",
        "result":       res.get("result"),
        "continuation": continuation,
    }


@router.post("/api/actions/{action_id}/reject")
async def action_reject(
    action_id: int,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    act = db.query(AIAction).filter(AIAction.id == action_id).first()
    if not act:
        raise HTTPException(404, "Azione non trovata")
    if u and act.user_id and act.user_id != u.id:
        raise HTTPException(403, "Azione di un altro utente")
    if act.status != "proposed":
        raise HTTPException(400, f"Azione già in stato {act.status}")
    act.status = "rejected"
    act.applied_at = datetime.utcnow()

    continuation = _maybe_resume_loop(db, act, action_result=None,
                                      rejected=True, applied_ok=False)
    db.commit()
    return {"ok": True, "status": "rejected", "continuation": continuation}


def _maybe_resume_loop(db: Session, act: AIAction, *,
                       action_result, rejected: bool, applied_ok: bool):
    """Se la conversazione collegata all'action è un loop tool_use sospeso,
    chiama resume_after_action e ritorna la continuation (testo + nuove
    AIAction proposte). Altrimenti ritorna None.
    """
    if not act.conversation_id or not act.tool_use_id:
        return None
    conv = db.query(AIConversation).filter(AIConversation.id == act.conversation_id).first()
    if not conv or not conv.tool_state:
        return None
    provider = get_provider_for_user(act.user_id, db)
    if not provider or not provider.supports_tools():
        return None

    system = build_system_prompt(
        db, use_tools=True,
        project_id=conv.project_id, quote_id=conv.quote_id, job_id=conv.job_id,
    )
    # Se l'apply è fallito, segnaliamo l'errore al modello come tool_result error
    # così che possa proporre un'alternativa.
    if rejected:
        result = resume_after_action(db, conv, provider, system, act,
                                     action_result=None, rejected=True)
    elif applied_ok:
        result = resume_after_action(db, conv, provider, system, act,
                                     action_result=action_result, rejected=False)
    else:
        # Apply fallito → tratta come rejected nel loop, il modello vedrà l'errore
        result = resume_after_action(db, conv, provider, system, act,
                                     action_result={"error": "apply_failed"}, rejected=True)

    # Persisti il messaggio assistant aggiuntivo (display)
    if result.get("text"):
        db.add(AIMessage(conversation_id=conv.id, role="assistant",
                          content=result["text"]))

    return {
        "text":           result.get("text") or "",
        "actions":        result.get("actions") or [],
        "done":           result.get("done", True),
        "still_pending":  result.get("still_pending", False),
    }


# ── Review quotazione ────────────────────────────────────────

@router.post("/api/quotes/{quote_id}/review")
async def ai_review_quote(
    quote_id: int,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    user_id = u.id if u else None
    if get_provider_for_user(user_id, db) is None:
        raise HTTPException(503, "AI non configurata")
    review = review_quote(db, quote_id, user_id=user_id)
    if review is None:
        raise HTTPException(500, "Review fallita")
    return {"review": review}


# ── Deliverables parser (upload capitolato) ──────────────────

@router.post("/api/deliverables/parse")
async def parse_deliverables_api(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    hint: Optional[str] = Form(None),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    if get_provider_for_user(u.id if u else None, db) is None:
        raise HTTPException(503, "AI non configurata")

    if file:
        file_bytes = await file.read()
        if len(file_bytes) > 10 * 1024 * 1024:
            raise HTTPException(413, "File troppo grande (max 10 MB)")
        extracted_text = extract_text_from_file(file_bytes, file.filename)
        source_name = file.filename
    elif text:
        extracted_text = text
        source_name = "testo incollato"
    else:
        raise HTTPException(400, "Fornire un file o del testo")

    if not extracted_text.strip():
        raise HTTPException(400, "Impossibile estrarre testo dal file")

    parsed = parse_deliverables(extracted_text, hint=hint)
    if not parsed:
        raise HTTPException(500, "Parser AI ha fallito. Verifica il contenuto del capitolato.")

    pricelist = [
        {"id": i.id, "name": i.name,
         "category": i.category.name if i.category else None,
         "unit": i.unit, "price_list": i.price_list}
        for i in db.query(PriceItem).filter(PriceItem.is_active == True).all()
    ]

    deliverables = parsed.get("deliverables", [])
    matches = match_deliverables_to_pricelist(deliverables, pricelist) if deliverables else None
    match_map = {}
    if matches and matches.get("matches"):
        for m in matches["matches"]:
            match_map[m["deliverable_index"]] = m

    for i, d in enumerate(deliverables):
        match = match_map.get(i)
        if match and match.get("price_item_id"):
            item = next((x for x in pricelist if x["id"] == match["price_item_id"]), None)
            if item:
                d["matched_price_item_id"] = item["id"]
                d["matched_price_item_name"] = item["name"]
                d["matched_unit_price"] = item["price_list"]
                d["match_confidence"] = match.get("confidence", "medium")
                d["match_reasoning"] = match.get("reasoning", "")
        else:
            d["matched_price_item_id"] = None
            d["match_confidence"] = "none"

    return {
        "project_info": parsed.get("project_info", {}),
        "deliverables": deliverables,
        "global_notes": parsed.get("global_notes"),
        "source_document_name": source_name,
    }


# ── Crea quotazione da capitolato confermato ─────────────────

@router.post("/api/deliverables/create-quote")
async def create_quote_from_deliverables(
    request: Request,
    db: Session = Depends(get_db),
):
    data = await request.json()

    project_id = data.get("project_id")
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Progetto non trovato")

    from datetime import date as date_type
    proj_info = data.get("project_info", {}) or {}

    quote = Quote(
        number=data["number"],
        project_id=project_id,
        client_id=project.client_id,
        title=data.get("title") or project.title,
        issue_date=date_type.fromisoformat(data["issue_date"]),
        production_material=proj_info.get("shooting_format"),
        length_minutes=proj_info.get("length_minutes"),
        fps=proj_info.get("fps"),
        delivery_format=proj_info.get("delivery_format"),
        generated_from_deliverables=True,
        source_document_name=data.get("source_document_name"),
        notes=data.get("notes"),
    )
    db.add(quote); db.flush()

    sort_order = 0
    for d in data.get("deliverables", []):
        section = d.get("section", "A")
        sort_order += 10
        position = d.get("position") or f"{section}.{sort_order // 10}"
        unit_price = d.get("matched_unit_price") or d.get("unit_price", 0) or 0
        quantity = d.get("quantity", 1)
        total = round(quantity * unit_price, 2)

        source_hint = None
        if d.get("match_reasoning") or d.get("notes"):
            source_hint = json.dumps({
                "confidence": d.get("match_confidence"),
                "reasoning": d.get("match_reasoning"),
                "notes": d.get("notes"),
            }, ensure_ascii=False)

        line = QuoteLine(
            quote_id=quote.id,
            price_item_id=d.get("matched_price_item_id"),
            section=section, position=position,
            description=d.get("description", ""),
            detail=d.get("detail"),
            quantity=quantity, unit=d.get("unit", "day"),
            price_level=PriceLevel.list_price,
            unit_price=unit_price,
            total=total,
            sort_order=sort_order,
            source_hint=source_hint,
        )
        db.add(line)

    db.flush()
    from app.routers.quotes import _recalc_quote
    quote = db.query(Quote).filter(Quote.id == quote.id).first()
    _recalc_quote(quote)
    db.commit()
    db.refresh(quote)

    return {"ok": True, "quote_id": quote.id, "quote_number": quote.number}
