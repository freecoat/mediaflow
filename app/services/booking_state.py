"""
Stato unificato Booking (v3.5.0-alpha.66.5).

Il campo `Booking.state` (BookingState) è la fonte canonica del ciclo di vita
del booking. I 2 campi legacy `status` (BookingStatus) e `execution_status`
(BookingExecutionStatus) restano nel DB per back-compat con slice-lock,
billing-slice-guard, recompute_cost_line_actual che li leggono.

Questa modulo fornisce il sync helper: `apply_state_to_booking(b, new_state)`
imposta `state` + `status` + `execution_status` in modo coerente, secondo la
mappa BOOKING_STATE_TO_LEGACY definita in models.

Sequenza tipica (transizioni libere):
    tentative → confirmed → in_progress → done | not_done

Cancelled è soft-delete (azione separata via "Elimina"), non appare nel
selettore UI.
"""
from __future__ import annotations

from app.models import (
    Booking, BookingState, BookingStatus, BookingExecutionStatus,
    BOOKING_STATE_TO_LEGACY,
)


def apply_state_to_booking(b: Booking, new_state: BookingState) -> dict:
    """Imposta state + status + execution_status coerentemente.

    Ritorna dict con i valori PRIMA del cambio + i nuovi (utile per audit
    log e undo). NON commetta — chi chiama gestisce la transazione.
    """
    old_state = b.state
    old_status = b.status
    old_exec = b.execution_status

    # Coerce a string se enum
    state_value = new_state.value if hasattr(new_state, "value") else str(new_state)
    legacy = BOOKING_STATE_TO_LEGACY.get(state_value)
    if legacy is None:
        raise ValueError(f"BookingState non valido: {state_value!r}")
    status_value, exec_value = legacy

    b.state = new_state if isinstance(new_state, BookingState) else BookingState(state_value)
    b.status = BookingStatus(status_value)
    b.execution_status = BookingExecutionStatus(exec_value)

    return {
        "old_state": old_state.value if hasattr(old_state, "value") else str(old_state),
        "old_status": old_status.value if hasattr(old_status, "value") else str(old_status),
        "old_execution_status": old_exec.value if hasattr(old_exec, "value") else str(old_exec),
        "new_state": b.state.value,
        "new_status": b.status.value,
        "new_execution_status": b.execution_status.value,
    }


def state_label(state: BookingState | str) -> str:
    """Etichetta umana italiana per UI/notifiche."""
    s = state.value if hasattr(state, "value") else str(state)
    return {
        "tentative":   "Tentative",
        "confirmed":   "Confermato",
        "in_progress": "In lavorazione",
        "done":        "Fatto",
        "not_done":    "Non fatto",
        "cancelled":   "Annullato",
    }.get(s, s)
