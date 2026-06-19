"""FSM transizioni richiesta KDM. Unico punto che muta `status`."""
from app.models import KdmRequestEvent
from app.services.clock import now_utc

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "received":     {"matched", "rejected"},
    "matched":      {"keys_pending", "rejected", "received"},
    "keys_pending": {"generated", "rejected"},
    "generated":    {"delivered", "rejected"},
    "delivered":    {"confirmed", "expired"},
    "confirmed":    {"expired"},
    "rejected":     set(),
    "expired":      set(),
}

_TIMESTAMP_FIELD: dict[str, str] = {
    "generated": "generated_at",
    "delivered": "delivered_at",
    "confirmed": "confirmed_at",
}


def transition(db, req, to_status: str, user_id=None):
    """Applica una transizione legale, stampa timestamp, logga evento.

    Raises ValueError se la transizione non è permessa.
    Hook point per Task 20: inserire logica post-transizione prima del flush.
    """
    cur = req.status
    if to_status not in ALLOWED_TRANSITIONS.get(cur, set()):
        raise ValueError(f"Transizione illegale {cur!r} → {to_status!r}")

    req.status = to_status

    field = _TIMESTAMP_FIELD.get(to_status)
    if field and getattr(req, field) is None:
        setattr(req, field, now_utc())

    db.add(KdmRequestEvent(
        kdm_request_id=req.id,
        event_type="transition",
        payload_json={"from": cur, "to": to_status},
        user_id=user_id,
    ))

    # --- Task 20 hook point: materialize deliverable on "generated" ---
    # if to_status == "generated":
    #     _materialize_kdm_deliverable(db, req)

    db.flush()
    return req
