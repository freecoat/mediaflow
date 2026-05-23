"""JCLBilledSlice immutability — Sprint 5.A BLOCCO 6 audit.

SQLAlchemy event listener model-level che blocca UPDATE su una slice
billed eccetto i campi di storno (`voided_at`, `voided_by_invoice_id`).

Defense-in-depth complementare al guard router-level
(`assert_slice_lock_safe`/`assert_jcl_lock_safe`). Pre-α.172.40 la
sequenza di guard era:
  - planning/AI lato: assert_slice_lock_safe(booking)
  - quotes lato (post Sprint 2): assert_jcl_lock_safe(jcl)
  - ma se chi modifica accede direttamente al model (es. script
    di migrazione, batch job, AI tool-use futuro) bypassava tutto

Event listener garantisce che NESSUNA modifica ai campi immutabili
passi tramite SQLAlchemy ORM, indipendentemente dal punto di ingresso.

Storno via NC TD04 USA `voided_at` + `voided_by_invoice_id` — questi
restano modificabili (vedi `_MUTABLE_FIELDS`).
"""
from __future__ import annotations
from sqlalchemy import event, inspect
from sqlalchemy.orm.attributes import get_history

# Campi che POSSONO essere modificati post-creazione (storno via NC TD04).
_MUTABLE_FIELDS = {"voided_at", "voided_by_invoice_id"}


def _on_before_update(mapper, connection, target):
    """SQLAlchemy event listener. Solleva ValueError se UPDATE tocca un
    campo immutabile. Idempotenti UPDATE senza modifiche reali passano
    (no field change → no history)."""
    state = inspect(target)
    for attr in state.attrs:
        if attr.key in _MUTABLE_FIELDS:
            continue
        hist = get_history(target, attr.key)
        if hist.has_changes():
            raise ValueError(
                f"JCLBilledSlice #{target.id}: campo `{attr.key}` immutabile "
                f"post-creazione. Slice fatturata = snapshot finanziario. "
                f"Per storno usa NC TD04 (popola voided_at/voided_by_invoice_id). "
                f"Per correzioni emit nuova fattura."
            )


def register_immutability_listener() -> None:
    """Registra il listener `before_update` su `JCLBilledSlice`.

    Idempotente: chiamato dal main.py al boot. Re-call su sessione hot-reload
    duplica il listener (SQLAlchemy de-dup interno via fn identity, OK).
    """
    from app.models import JCLBilledSlice
    if not event.contains(JCLBilledSlice, "before_update", _on_before_update):
        event.listen(JCLBilledSlice, "before_update", _on_before_update)
