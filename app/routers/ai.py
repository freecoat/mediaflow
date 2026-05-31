"""
Router AI — chat copilot context-aware, azioni propose/apply/reject,
upload capitolato, review quotazioni.

In v3.2:
- get_provider() globale sostituito da get_provider_for_user(user_id, db)
- ogni risposta della chat può proporre AIAction da confermare manualmente
- nuovi endpoint per applicare/rifiutare le azioni proposte
"""
from app.services.clock import now_utc
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
    save_attachment, embed_attachments_in_text, build_user_content_blocks,
    MAX_FILE_SIZE,
)
from app.services.rbac import requires_permission

router = APIRouter(prefix="/ai", tags=["ai"])

# v3.5.0-alpha.66.16.0 — Sprint R3: gate per i mutator AI che possono
# scrivere su Quote (review è read-AI ma può materializzare suggestions;
# parse + create-quote scrivono direttamente).
RequireViewQuotes = Depends(requires_permission("view_quotes"))
RequireEditQuotesAI = Depends(requires_permission("edit_quotes"))


# v3.5.0-alpha.51 — Upload documenti per copilot
# v3.5.0-alpha.66.14.4 — Auth required + magic-bytes validati in
# save_attachment. Il file_id ritornato include il prefisso utente per
# enforcement ownership lato server (vedi copilot_attachments._ownership_ok).
@router.post("/api/upload")
async def copilot_upload(
    file: UploadFile = File(...),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Carica un documento (PDF/DOCX/TXT/MD/immagine) per allegarlo al
    prossimo messaggio del copilot. Ritorna metadata + extracted_text per
    file text-based. Per immagini, vision integration dal v3.5.0-alpha.53.

    Auth: richiede utente autenticato (cookie JWT). In produzione con
    AUTH_REQUIRED=true risponde 401 senza fallback.
    """
    user = _resolve_current_user(db, access_token)
    if not user:
        raise HTTPException(401, "Autenticazione richiesta per upload allegati")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File troppo grande (max {MAX_FILE_SIZE // 1024 // 1024} MB)")
    try:
        meta = save_attachment(file.filename or "untitled", content, user_id=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return meta


def _tpl():
    from app.main import templates
    return templates


# v3.5.0-alpha.66.14.2: alias verso il singleton in app.services.auth.
# La logica fail-closed (settings.auth_required=True → no fallback) vive lì.
from app.services.auth import resolve_current_user as _resolve_current_user  # noqa: E402,F401


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

    def _flatten_content(c):
        """Estrae il testo da content che può essere stringa o list[dict]."""
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            parts = []
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif isinstance(b, dict) and b.get("type") == "image":
                    parts.append("[immagine]")
            return "\n".join(parts)
        return str(c)

    # Risolvi/crea conversazione
    conv_id = data.get("conversation_id")
    conv = None
    if conv_id:
        conv = db.query(AIConversation).filter(AIConversation.id == conv_id).first()
    if conv is None and user_id:
        # v3.5.0-alpha.172.80 (Bundle D1) — Titolo auto-generato più leggibile.
        # Prefisso col code/titolo del progetto se nel context, poi primi
        # ~40 char del messaggio utente. Esempio:
        # "Filmetto Test · ri-splitta tutti i booking di dailies con pausa..."
        # Utente può rinominare via PATCH /api/conversations/{id}/title.
        title_src = _flatten_content(messages[0].get("content", "")) if messages else ""
        title_src = (title_src or "").strip()
        prefix = ""
        if project_id:
            proj = db.query(Project).filter(Project.id == project_id).first()
            if proj:
                prefix = (proj.title or proj.code or "")[:30].strip()
        elif quote_id:
            qz = db.query(Quote).filter(Quote.id == quote_id).first()
            if qz:
                prefix = (qz.number or qz.title or "")[:30].strip()
        if prefix and title_src:
            auto_title = f"{prefix} · {title_src[:40]}"
        elif title_src:
            auto_title = title_src[:60]
        elif prefix:
            auto_title = prefix
        else:
            auto_title = None
        if auto_title:
            auto_title = auto_title[:255]
        conv = AIConversation(
            user_id=user_id,
            project_id=project_id, quote_id=quote_id, job_id=job_id,
            title=auto_title,
        )
        db.add(conv); db.flush()

    provider = get_provider_for_user(user_id, db)
    if not provider:
        return {
            "reply": "AI non configurata. Vai in Impostazioni → tab AI per scegliere e attivare un provider.",
            "actions": [], "conversation_id": conv.id if conv else None,
            "error": "provider_disabled",
        }

    # v3.5.0-alpha.53 — Costruisce il content del messaggio user con
    # vision blocks se il provider li supporta. `last_user_content` può
    # essere stringa (compat) o list[dict] (multimodal).
    # v3.5.0-alpha.66.14.4 — Passa user_id per enforcement ownership su
    # file_id immagine: file di altri utenti vengono droppati (sostituiti
    # con placeholder testuale "non caricabile").
    if attachments and isinstance(attachments, list) and messages:
        last_msg = messages[-1]
        if last_msg.get("role") == "user":
            original = last_msg.get("content", "")
            last_msg["content"] = build_user_content_blocks(
                original, attachments, supports_vision=provider.supports_vision(),
                user_id=user_id,
            )

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
        db.add(AIMessage(conversation_id=conv.id, role="user", content=_flatten_content(last_user_content)))
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
        db.add(AIMessage(conversation_id=conv.id, role="user", content=_flatten_content(last_user_content)))
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


# v3.5.0-alpha.172.80 (Bundle D1) — Rinomina + elimina conversazione AI.
# Permette all'utente di organizzare la storia chat con titoli human-readable
# (es. "Filmetto · split dailies pausa pranzo") e cancellare quelle obsolete.
# Ownership check: solo l'utente che ha creato la conversation può modificarla.

@router.patch("/api/conversations/{conv_id}/title")
async def patch_conversation_title(
    conv_id: int,
    title: str = Form(...),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(401, "Login richiesto")
    conv = db.query(AIConversation).filter(AIConversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversazione non trovata")
    if conv.user_id != u.id:
        raise HTTPException(403, "Solo il proprietario può rinominare")
    new_title = (title or "").strip()[:255] or None
    conv.title = new_title
    db.commit()
    return {"ok": True, "id": conv.id, "title": conv.title}


@router.delete("/api/conversations/{conv_id}")
async def delete_conversation(
    conv_id: int,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(401, "Login richiesto")
    conv = db.query(AIConversation).filter(AIConversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversazione non trovata")
    if conv.user_id != u.id:
        raise HTTPException(403, "Solo il proprietario può eliminare")
    # cascade="all, delete-orphan" su AIConversation.messages → cancella anche
    # i messaggi. AIAction.conversation_id è nullable=True quindi le azioni
    # storiche sopravvivono per audit (con conversation_id orfano).
    db.delete(conv)
    db.commit()
    return {"ok": True, "id": conv_id}


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
        act.applied_at = now_utc()
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
    act.applied_at = now_utc()

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

@router.post("/api/quotes/{quote_id}/review", dependencies=[RequireViewQuotes])
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


# ── Deliverable tech_specs propose AI (v3.5.0-alpha.172.90 Bundle J) ──

@router.post("/api/deliverables/{deliverable_id}/propose-specs")
async def ai_propose_deliverable_specs(
    deliverable_id: int,
    template_id: int = Form(...),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Invoca capability AI propose_deliverable_specs: adatta 8 blocchi
    DeliveryTemplate al JobDeliverable specifico. Readonly DB (la UI salva
    via PUT /jobs/api/deliverables/{id} dopo revisione utente).
    """
    u = _resolve_current_user(db, access_token)
    user_id = u.id if u else None
    if get_provider_for_user(user_id, db) is None:
        raise HTTPException(503, "AI non configurata per l'utente")
    from app.services.ai_assistant import _h_propose_deliverable_specs
    try:
        return _h_propose_deliverable_specs(db, {
            "deliverable_id": deliverable_id,
            "template_id": template_id,
            "_user_id": user_id,
        })
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"AI propose specs fallita: {e}")


# ── QC report summary AI (v3.5.0-alpha.172.89 Bundle I) ──────

@router.post("/api/deliverables/{deliverable_id}/qc-report-summary")
async def ai_qc_report_summary(
    deliverable_id: int,
    asset_id: int = Form(...),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Invoca capability AI propose_qc_report_summary per analizzare un PDF
    QC report linkato come DeliverableAsset(source='qc_report'). Esegue
    inline (no AIAction proposta perche' e' solo lettura+summary, l'utente
    decide poi se applicare il suggerimento via setDeliverableStatus).
    """
    u = _resolve_current_user(db, access_token)
    user_id = u.id if u else None
    if get_provider_for_user(user_id, db) is None:
        raise HTTPException(503, "AI non configurata per l'utente")
    from app.services.ai_assistant import _h_propose_qc_report_summary
    try:
        result = _h_propose_qc_report_summary(db, {
            "deliverable_id": deliverable_id,
            "asset_id": asset_id,
            "_user_id": user_id,
        })
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"AI summary fallita: {e}")


# ── Deliverables parser (upload capitolato) ──────────────────

@router.post("/api/deliverables/parse", dependencies=[RequireEditQuotesAI])
async def parse_deliverables_api(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    hint: Optional[str] = Form(None),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    # v3.5.0-alpha.172.81 (Bundle F): istanzia provider per-utente UNA VOLTA e
    # lo iniettiamo nel parser/matcher. Pre-fix: parse_deliverables chiamava
    # get_provider() (global) che era None se la AI key non era sul tenant
    # globale → 500 anche se l'utente aveva configurato la propria chiave AI.
    provider = get_provider_for_user(u.id if u else None, db)
    if provider is None:
        raise HTTPException(503, "AI non configurata. Vai in Impostazioni → tab AI per configurare un provider.")

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

    # v3.5.0-alpha.172.85: AI provider sync (requests.post) blocca event loop
    # in async def. run_in_threadpool sposta in thread → server resta
    # responsivo per altre request durante l'analisi capitolato.
    # v3.5.0-alpha.172.86: skip match per ridurre durata totale request.
    # Cloudflare tunnel free ha hard limit 100s → 2 AI call seriali (~30s
    # parse + ~60s match su listino grande) sforavano = 524. Ora ritorna
    # solo deliverables (rapido); il match è opzionale via separato
    # endpoint /api/deliverables/match (UI Step 2 lo chiama in background).
    from fastapi.concurrency import run_in_threadpool
    parsed = await run_in_threadpool(parse_deliverables, extracted_text, hint=hint, provider=provider)
    if not parsed:
        raise HTTPException(500, "Parser AI ha fallito. Verifica il contenuto del capitolato (es. PDF immagine non OCR-izzato).")

    deliverables = parsed.get("deliverables", [])
    # Default fields per consistenza (match avviene in chiamata separata)
    for d in deliverables:
        d["matched_price_item_id"] = None
        d["match_confidence"] = "none"

    return {
        "project_info": parsed.get("project_info", {}),
        "deliverables": deliverables,
        "global_notes": parsed.get("global_notes"),
        "source_document_name": source_name,
        "needs_match": True,  # signal UI di chiamare /api/deliverables/match
    }


@router.post("/api/deliverables/match", dependencies=[RequireEditQuotesAI])
async def match_deliverables_api(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.172.86: estratto da parse_deliverables_api per evitare
    cloudflare 524 (>100s totale tra parse + match). UI chiama questo
    endpoint dopo aver ricevuto parsed.deliverables, in background mentre
    l'utente già vede la lista.

    Payload JSON: { deliverables: [...] }
    Risposta: { matches: { idx: {price_item_id, confidence, ...} } }
    """
    from fastapi.concurrency import run_in_threadpool
    u = _resolve_current_user(db, access_token)
    provider = get_provider_for_user(u.id if u else None, db)
    if provider is None:
        raise HTTPException(503, "AI non configurata")

    data = await request.json()
    deliverables = data.get("deliverables") or []
    if not isinstance(deliverables, list) or not deliverables:
        return {"matches": {}}

    pricelist = [
        {"id": i.id, "name": i.name,
         "category": i.category.name if i.category else None,
         "unit": i.unit, "price_list": i.price_list}
        for i in db.query(PriceItem).filter(PriceItem.is_active == True).all()
    ]
    if not pricelist:
        return {"matches": {}}

    result = await run_in_threadpool(match_deliverables_to_pricelist, deliverables, pricelist, provider=provider)
    matches = {}
    if result and result.get("matches"):
        pi_by_id = {p["id"]: p for p in pricelist}
        for m in result["matches"]:
            idx = m.get("deliverable_index")
            pid = m.get("price_item_id")
            if idx is None:
                continue
            pi = pi_by_id.get(pid) if pid else None
            matches[str(idx)] = {
                "price_item_id": pid,
                "price_item_name": pi["name"] if pi else None,
                "unit_price": pi["price_list"] if pi else None,
                "unit": pi["unit"] if pi else None,
                "confidence": m.get("confidence", "medium"),
                "reasoning": m.get("reasoning", ""),
            }
    return {"matches": matches}


# ── Crea quotazione da capitolato confermato ─────────────────

@router.post("/api/deliverables/create-quote", dependencies=[RequireEditQuotesAI])
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

    # v3.5.0-alpha.172.82 (Bundle F7) — number opzionale: se vuoto usa
    # naming convention NumberingConfig tenant-scope (allinea AI capitolato
    # al pattern di tutte le altre quote, niente hardcode Q-2026-NNN).
    number = (data.get("number") or "").strip()
    if not number:
        from app.services.numbering import gen_doc_code
        from app.context import current_tenant_id
        # v3.5.0-alpha.172.85 fix: Client non ha attributo `code`, solo `name`.
        # Per i pattern che usano {CLIENT_CODE} si usa il nome sanitizzato
        # (primi 12 char uppercase senza spazi). Se serve un vero codice
        # cliente, aggiungere Client.code separato in futuro.
        client_code = None
        if project.client_id:
            from app.models import Client as _Client
            cli = db.query(_Client).filter(_Client.id == project.client_id).first()
            if cli and cli.name:
                import re as _re
                client_code = _re.sub(r"\s+", "", cli.name)[:12].upper() or None
        number, _seq = gen_doc_code(
            db, "quote", tenant_id=current_tenant_id(),
            project_code=project.code, client_code=client_code,
        )

    quote = Quote(
        number=number,
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


# ── AI Usage stats (R10 v3.5.0-alpha.66.16.4) ────────────────

@router.get("/api/usage")
async def ai_usage_stats(
    period_days: int = 30,
    by: str = "user",  # "user" | "model" | "day"
    user_id: Optional[int] = None,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Aggregati AIUsageLog: token + costo per periodo, raggruppati per
    user/model/day a scelta. Default: ultimi 30 giorni, breakdown per user.

    Richiede `view_finance` (i costi AI sono dato finanziario interno).
    L'utente standard può vedere solo le proprie usage (filtro implicito
    via `user_id == self`).
    """
    from datetime import timedelta
    from sqlalchemy import func
    from app.models.models import AIUsageLog
    from app.services.rbac import has_permission

    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(401, "Autenticazione richiesta")
    can_see_all = has_permission(u, "view_finance")
    if not can_see_all:
        # Standard user: vede solo i suoi
        user_id = u.id

    cutoff = now_utc() - timedelta(days=max(1, min(period_days, 365)))
    # current_tenant_id() pattern come in altri router (R1 future-ready stub)
    from app.context import current_tenant_id
    base_q = db.query(AIUsageLog).filter(
        AIUsageLog.tenant_id == current_tenant_id(),
        AIUsageLog.created_at >= cutoff,
    )
    if user_id is not None:
        base_q = base_q.filter(AIUsageLog.user_id == user_id)

    # Totali aggregati (sempre presenti)
    totals_row = base_q.with_entities(
        func.coalesce(func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(AIUsageLog.cache_read_tokens), 0).label("cache_read_tokens"),
        func.coalesce(func.sum(AIUsageLog.cache_create_tokens), 0).label("cache_create_tokens"),
        func.coalesce(func.sum(AIUsageLog.cost_usd), 0.0).label("cost_usd"),
        func.count(AIUsageLog.id).label("calls"),
    ).first()
    totals = {
        "input_tokens":         int(totals_row.input_tokens or 0),
        "output_tokens":        int(totals_row.output_tokens or 0),
        "cache_read_tokens":    int(totals_row.cache_read_tokens or 0),
        "cache_create_tokens":  int(totals_row.cache_create_tokens or 0),
        "cost_usd":             round(float(totals_row.cost_usd or 0.0), 4),
        "calls":                int(totals_row.calls or 0),
    }
    # hit_ratio cache (saving prompt caching)
    crt = totals["cache_read_tokens"]
    inp = totals["input_tokens"]
    totals["cache_hit_ratio"] = round(crt / (crt + inp), 3) if (crt + inp) else 0.0

    # Breakdown
    breakdown: list[dict] = []
    if by == "user":
        rows = (base_q.with_entities(
            AIUsageLog.user_id.label("k"),
            func.sum(AIUsageLog.cost_usd).label("cost"),
            func.count(AIUsageLog.id).label("calls"),
            func.sum(AIUsageLog.input_tokens).label("inp"),
            func.sum(AIUsageLog.output_tokens).label("out"),
        ).group_by(AIUsageLog.user_id).order_by(func.sum(AIUsageLog.cost_usd).desc()).all())
        breakdown = [{
            "user_id": r.k, "cost_usd": round(float(r.cost or 0.0), 4),
            "calls": int(r.calls), "input_tokens": int(r.inp or 0),
            "output_tokens": int(r.out or 0),
        } for r in rows]
    elif by == "model":
        rows = (base_q.with_entities(
            AIUsageLog.model.label("k"),
            func.sum(AIUsageLog.cost_usd).label("cost"),
            func.count(AIUsageLog.id).label("calls"),
            func.sum(AIUsageLog.input_tokens).label("inp"),
            func.sum(AIUsageLog.output_tokens).label("out"),
        ).group_by(AIUsageLog.model).order_by(func.sum(AIUsageLog.cost_usd).desc()).all())
        breakdown = [{
            "model": r.k, "cost_usd": round(float(r.cost or 0.0), 4),
            "calls": int(r.calls), "input_tokens": int(r.inp or 0),
            "output_tokens": int(r.out or 0),
        } for r in rows]
    elif by == "day":
        rows = (base_q.with_entities(
            func.date(AIUsageLog.created_at).label("k"),
            func.sum(AIUsageLog.cost_usd).label("cost"),
            func.count(AIUsageLog.id).label("calls"),
        ).group_by(func.date(AIUsageLog.created_at))
         .order_by(func.date(AIUsageLog.created_at).desc()).all())
        breakdown = [{
            "date": str(r.k), "cost_usd": round(float(r.cost or 0.0), 4),
            "calls": int(r.calls),
        } for r in rows]
    else:
        raise HTTPException(400, "by deve essere user|model|day")

    return {
        "period_days": period_days,
        "by": by,
        "scope": "all" if can_see_all and user_id is None else f"user:{user_id}",
        "totals": totals,
        "breakdown": breakdown,
    }
