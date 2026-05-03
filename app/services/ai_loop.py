"""
MediaFlow — AI tool-use loop (v3.5.0)

Esegue il loop di conversazione con tool_use nativo:
- legge/persistite la storia messages in `AIConversation.tool_state`
- esegue le tool readonly (es. web_search) inline restituendo il tool_result al modello
- per le mutation, salva una AIAction proposed e SOSPENDE il loop
- riprende il loop al successivo /apply (o /reject) costruendo i tool_result
  effettivi a partire dai risultati degli handler

Il modulo è agnostico al provider concreto: usa l'astrazione
`AIProvider.chat_with_tools()` definita in `ai_provider.py`.
"""
from __future__ import annotations
import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.models import AIAction, AIConversation
from app.services.ai_provider import AIProvider, ToolUse
from app.services.ai_tools import is_readonly, to_anthropic_tools

logger = logging.getLogger(__name__)


# Cap di sicurezza: evita loop infiniti se il modello continua a chiamare tool senza
# mai produrre un end_turn.
MAX_LOOP_ITERATIONS = 10


# ── Persistenza stato ──────────────────────────────────────────

def _load_state(conv: AIConversation) -> dict:
    """Decodifica il tool_state, oppure ritorna uno stato vuoto."""
    if not conv.tool_state:
        return {"messages": [], "pending_results": []}
    try:
        return json.loads(conv.tool_state)
    except json.JSONDecodeError:
        logger.warning(f"AIConversation #{conv.id}: tool_state corrotto, reset")
        return {"messages": [], "pending_results": []}


def _save_state(conv: AIConversation, state: Optional[dict]) -> None:
    """Salva (o pulisce) il tool_state. None = loop concluso."""
    conv.tool_state = json.dumps(state, ensure_ascii=False) if state else None


# ── Esecuzione tool readonly ───────────────────────────────────

def _exec_readonly(db: Session, tu: ToolUse) -> str:
    """Esegue una tool readonly e ritorna una stringa con il risultato (per
    iniettarla come `content` di un blocco tool_result Anthropic-style).
    Le eccezioni vengono catturate e tradotte in un messaggio di errore
    leggibile dal modello, che potrà cambiare strategia.
    """
    from app.services.ai_assistant import _ACTION_HANDLERS

    handler = _ACTION_HANDLERS.get(tu.name)
    if handler is None:
        return json.dumps({"error": f"tool '{tu.name}' non implementato"}, ensure_ascii=False)
    try:
        result = handler(db, tu.input or {})
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception(f"Tool readonly {tu.name} fallita")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ── Save AIAction per mutation ─────────────────────────────────

def _save_pending_action(db: Session, conv: AIConversation, tu: ToolUse) -> AIAction:
    """Persiste una mutation come AIAction in stato proposed, legandola al
    tool_use_id così che al successivo /apply potremo costruire il tool_result
    e riprendere il loop."""
    act = AIAction(
        conversation_id=conv.id,
        user_id=conv.user_id,
        action_type=tu.name,
        payload=json.dumps(tu.input or {}, ensure_ascii=False),
        status="proposed",
        tool_use_id=tu.id,
    )
    db.add(act)
    db.flush()
    return act


def _serialize_action(act: AIAction, tu: Optional[ToolUse] = None) -> dict:
    """Schema usato dal frontend (compatibile col path legacy ```action```)."""
    payload = json.loads(act.payload) if act.payload else {}
    title = payload.get("name") or payload.get("title") or payload.get("query") or act.action_type
    return {
        "id":          act.id,
        "action_type": act.action_type,
        "title":       title,
        "data":        payload,
        "status":      act.status,
        "tool_use_id": act.tool_use_id,
    }


# ── Costruzione user block tool_result ─────────────────────────

def _build_tool_result_user_block(results: list[dict]) -> dict:
    """Anthropic richiede che il turno user successivo a un assistant con
    tool_use contenga UN tool_result per OGNI tool_use_id emesso. Costruiamo
    qui il content blocks corrispondente."""
    return {
        "role": "user",
        "content": [
            {
                "type":         "tool_result",
                "tool_use_id":  r["tool_use_id"],
                "content":      r["content"],
                **({"is_error": True} if r.get("is_error") else {}),
            }
            for r in results
        ],
    }


# ── Funzione principale: avanza il loop fino al prossimo "stop point" ──

def advance_loop(db: Session, conv: AIConversation, provider: AIProvider,
                 system: str, *, initial_messages: Optional[list[Any]] = None,
                 user_message: Optional[str] = None) -> dict:
    """Avanza il loop tool_use fino a uno dei seguenti stop point:
    - `end_turn`: il modello ha finito (return {done: True, text, actions: []}).
    - mutation pendenti: una o più tool_use mutation da approvare manualmente
      (return {done: False, text, actions: [...], pending: True}).
    - errore o limite iterazioni (return {done: True, text, actions, error}).

    Parametri:
    - `initial_messages`: storia messages canonica (Anthropic format) usata
      per AVVIARE una conversazione. Ignorato se conv.tool_state esiste.
    - `user_message`: messaggio utente da appendere (in primo invocazione
      o per follow-up). Ignorato se conv.tool_state contiene già un turno
      utente in attesa.

    Side effect:
    - Mutua `conv.tool_state` (salva o cancella).
    - Crea AIAction proposed per le mutation incontrate.
    """
    state = _load_state(conv)
    messages: list[Any] = state.get("messages") or []

    # Se non c'è ancora storia, partiamo dai initial_messages forniti dal caller.
    if not messages and initial_messages:
        messages = list(initial_messages)

    # Append del messaggio utente nuovo (se chiamato dal /chat normale).
    if user_message is not None:
        messages.append({"role": "user", "content": user_message})

    tools = to_anthropic_tools()
    final_text = ""
    pending_actions: list[dict] = []

    for iteration in range(MAX_LOOP_ITERATIONS):
        try:
            resp = provider.chat_with_tools(messages, system, tools)
        except Exception as e:
            logger.exception("chat_with_tools failed")
            _save_state(conv, None)
            return {
                "done":    True,
                "text":    f"Errore comunicazione con l'AI: {str(e)[:200]}",
                "actions": [],
                "error":   "provider_error",
            }

        # Append della risposta assistant alla storia (sempre, anche con tool_use).
        messages.append(resp.raw_assistant_message)
        final_text = resp.text or final_text

        if not resp.tool_uses:
            # end_turn pulito.
            _save_state(conv, None)
            return {
                "done":    True,
                "text":    final_text,
                "actions": [],
                "error":   None,
                "messages": messages,  # esposto solo per debug/test
            }

        # Esegue readonly inline; raccoglie mutation come AIAction.
        tool_results: list[dict] = []
        has_mutation = False
        for tu in resp.tool_uses:
            if is_readonly(tu.name):
                content = _exec_readonly(db, tu)
                tool_results.append({"tool_use_id": tu.id, "content": content})
            else:
                # Mutation → salva AIAction proposed; tool_result verrà
                # costruito al momento dell'/apply (o /reject).
                has_mutation = True
                act = _save_pending_action(db, conv, tu)
                pending_actions.append(_serialize_action(act, tu))
                # Placeholder marcato che verrà sostituito al apply.
                tool_results.append({
                    "tool_use_id":  tu.id,
                    "content":      None,
                    "_pending_action_id": act.id,
                })

        if has_mutation:
            # Salva lo stato del loop (messages + tool_results pending) e ferma.
            new_state = {
                "messages":         messages,
                "pending_results":  tool_results,
            }
            _save_state(conv, new_state)
            db.flush()
            return {
                "done":    False,
                "text":    final_text,
                "actions": pending_actions,
                "error":   None,
                "pending": True,
            }

        # Solo readonly → append user block con tutti i tool_result, prosegui.
        messages.append(_build_tool_result_user_block(tool_results))

    # Limite iterazioni — interrompi forzatamente.
    _save_state(conv, None)
    return {
        "done":    True,
        "text":    final_text or "(loop tool_use interrotto: limite iterazioni)",
        "actions": [],
        "error":   "loop_limit",
    }


# ── Resume dopo /apply o /reject ───────────────────────────────

def resume_after_action(db: Session, conv: AIConversation, provider: AIProvider,
                        system: str, action: AIAction,
                        action_result: Optional[dict] = None,
                        rejected: bool = False) -> dict:
    """Chiamata dal router `/apply` (o `/reject`) per:
    1. Sostituire il placeholder tool_result della mutation appena gestita.
    2. Se TUTTI i tool_result della batch corrente sono ora pronti (cioè
       nessuna altra mutation della stessa batch è ancora `proposed`),
       costruire il prossimo turno user con i tool_result e proseguire il
       loop chiamando `advance_loop`.
    3. Altrimenti, restituire una "continuation parziale" che la UI può
       mostrare ma il loop rimane sospeso fino alla prossima Apply.

    Parametri:
    - `action_result`: il dict ritornato da `apply_action()` (campo "result"),
      messo come content del tool_result. Ignorato se `rejected=True`.
    - `rejected`: True se l'utente ha rifiutato. Costruisce un tool_result con
      messaggio "rejected by user" perché il modello sappia.
    """
    state = _load_state(conv)
    messages: list[Any] = state.get("messages") or []
    pending: list[dict] = state.get("pending_results") or []

    if not messages or not pending:
        # Loop non in attesa, nessun resume da fare.
        return {"done": True, "text": "", "actions": [], "error": None}

    # Sostituisci il placeholder relativo a questa action con il vero contenuto.
    target_id = action.tool_use_id
    target_pid = action.id
    found = False
    for slot in pending:
        if slot.get("_pending_action_id") == target_pid or slot.get("tool_use_id") == target_id:
            if rejected:
                slot["content"] = json.dumps({
                    "status": "rejected_by_user",
                    "message": "L'utente ha rifiutato questa azione. Considera un'alternativa o chiedi chiarimenti.",
                }, ensure_ascii=False)
                slot["is_error"] = True
            else:
                slot["content"] = json.dumps(action_result or {"ok": True}, ensure_ascii=False, default=str)
            slot.pop("_pending_action_id", None)
            found = True
            break

    if not found:
        logger.warning(f"resume_after_action: action {action.id} non trovata in pending state")
        # Stato incoerente — pulisci e termina, l'utente continuerà via chat normale.
        _save_state(conv, None)
        return {"done": True, "text": "", "actions": [], "error": "state_mismatch"}

    # Verifica se tutti i pending sono ora pronti.
    still_pending_pids = [s.get("_pending_action_id") for s in pending if s.get("content") is None]
    if still_pending_pids:
        # Ci sono altre mutation della stessa batch ancora da approvare.
        # Aggiorna stato (con il placeholder appena risolto) e ferma.
        state["pending_results"] = pending
        _save_state(conv, state)
        db.flush()
        return {
            "done":           False,
            "text":           "",
            "actions":        [],
            "still_pending":  True,
            "error":          None,
        }

    # Tutti pronti → append user block con tool_results e riprendi il loop.
    messages.append(_build_tool_result_user_block(pending))
    state["messages"] = messages
    state["pending_results"] = []
    _save_state(conv, state)
    db.flush()

    return advance_loop(db, conv, provider, system)
