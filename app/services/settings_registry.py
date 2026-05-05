"""
MediaFlow — Settings registry (v3.5.0-alpha.19)

Registry centrale di tutte le aree configurabili dell'applicazione, esposto
all'AI tramite tool generici (`list_settings_schemas`, `read_setting`,
`update_setting`). Idea architetturale: invece di aggiungere una capability AI
per ogni nuova area di settings (`propose_working_hours`, `propose_user_prefs`,
ecc.), il copilot scopre dinamicamente cosa è configurabile via discovery API e
applica patch generiche. Estendere a una nuova area = aggiungere una
`SettingsSchema` qui, niente nuove capability.

Ogni schema descrive:
- `key`: identificatore stabile (es. "working_hours", "user_preferences")
- `label` / `description`: testi human-readable per UI e prompt AI
- `fields`: lista di field-spec (nome, type JSON-Schema, label, choices, ...)
- `read(db, user) -> dict`: legge stato corrente
- `write(db, user, patch) -> dict`: applica patch (può sollevare errori validati)
- `permission`: permesso richiesto (chiave da rbac.PERMISSIONS)
  - `"admin"` → solo admin
  - `"self"`  → ogni utente sui propri dati
  - permesso specifico (es. "edit_settings") per RBAC fine

Convenzioni:
- I field type seguono JSON Schema sottoinsieme (`integer`, `number`, `string`,
  `boolean`, `time`, `enum`).
- Per `time` accettiamo stringa "HH:MM" (24h).
- Patch contiene solo i field da cambiare; field assenti restano invariati.
- Le write_handler validano i tipi e sollevano `ValueError` con messaggio
  comprensibile in caso di problemi.

Quando aggiungi un nuovo schema:
1. Definisci read/write helpers privati al modulo.
2. Crea l'oggetto `SettingsSchema` e aggiungilo a `SCHEMAS` in fondo al file.
3. Niente altro: il tool AI lo scopre automaticamente.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import time, datetime
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.models import (
    User, Tenant, WorkingHoursPolicy,
)


# ── Datatypes ─────────────────────────────────────────────────


@dataclass
class SettingsField:
    key: str
    label: str
    type: str  # 'integer' | 'number' | 'string' | 'boolean' | 'time' | 'enum'
    description: str = ""
    choices: Optional[list[str]] = None  # per type=enum
    nullable: bool = False
    # Hint UI: 'short_text' | 'long_text' | 'time' | 'currency' (informativi)
    ui_hint: Optional[str] = None

    def to_dict(self) -> dict:
        out: dict = {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "description": self.description,
            "nullable": self.nullable,
        }
        if self.choices:
            out["choices"] = self.choices
        if self.ui_hint:
            out["ui_hint"] = self.ui_hint
        return out


@dataclass
class SettingsSchema:
    key: str
    label: str
    description: str
    fields: list[SettingsField]
    read: Callable[[Session, User], dict]
    write: Callable[[Session, User, dict], dict]
    permission: str = "admin"  # "admin" | "self" | permission key

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "fields": [f.to_dict() for f in self.fields],
            "permission": self.permission,
        }


# ── Validation helpers ────────────────────────────────────────


def _coerce_field(field: SettingsField, value: Any) -> Any:
    """Coerce + validate il valore secondo il type del field. Solleva ValueError."""
    if value is None:
        if field.nullable:
            return None
        raise ValueError(f"{field.key}: valore null non consentito")
    t = field.type
    try:
        if t == "integer":
            return int(value)
        if t == "number":
            return float(value)
        if t == "boolean":
            if isinstance(value, str):
                return value.strip().lower() in ("true", "1", "yes", "on", "y")
            return bool(value)
        if t == "string":
            return str(value)
        if t == "time":
            # Accetta "HH:MM" o "HH:MM:SS" o time
            if isinstance(value, time):
                return value
            s = str(value).strip()
            parts = s.split(":")
            if len(parts) < 2:
                raise ValueError("formato HH:MM atteso")
            h = int(parts[0]); m = int(parts[1])
            sec = int(parts[2]) if len(parts) >= 3 else 0
            return time(h, m, sec)
        if t == "enum":
            if field.choices and str(value) not in field.choices:
                raise ValueError(f"{field.key}: valore '{value}' non in {field.choices}")
            return str(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{field.key}: {e}") from e
    raise ValueError(f"{field.key}: type {t} non gestito")


def _apply_patch(target: Any, fields: list[SettingsField], patch: dict) -> dict:
    """Applica patch su un object SQLAlchemy validando ogni field. Ritorna il
    diff effettivamente applicato come dict {field_key: {old, new}}.
    """
    diff: dict = {}
    valid_keys = {f.key for f in fields}
    for k, v in patch.items():
        if k not in valid_keys:
            raise ValueError(f"campo sconosciuto: {k}")
        f = next(f for f in fields if f.key == k)
        new_val = _coerce_field(f, v)
        old_val = getattr(target, k, None)
        # Confronto best-effort: time con time, ecc.
        if old_val == new_val:
            continue
        setattr(target, k, new_val)
        # Serializzo old/new per il diff (time → "HH:MM")
        diff[k] = {
            "old": _serialize(old_val),
            "new": _serialize(new_val),
        }
    return diff


def _serialize(v: Any) -> Any:
    if isinstance(v, time):
        return v.strftime("%H:%M")
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _serialize_dict(target: Any, fields: list[SettingsField]) -> dict:
    """Legge i fields da target e ritorna dict serializzabile JSON."""
    return {f.key: _serialize(getattr(target, f.key, None)) for f in fields}


# ── Schema: working_hours ─────────────────────────────────────
#
# WorkingHoursPolicy default del tenant. È quella che usano tutti gli engine
# (overtime, calendar, holiday detection) come fallback per le risorse senza
# override.

CURRENT_TENANT = 1

_WH_FIELDS = [
    SettingsField("name", "Nome policy", "string", "Etichetta interna (es. 'Italia base')."),
    SettingsField("ccnl_label", "CCNL di riferimento", "string", "Es. 'CCNL Cinema Doppiaggio'.", nullable=True),
    SettingsField("daily_hours_threshold", "Soglia ore giornaliere", "number",
                  "Oltre questa soglia le ore eccedenti contano come straordinario giornaliero."),
    SettingsField("weekly_hours_threshold", "Soglia ore settimanali", "number",
                  "Oltre questa soglia le ore eccedenti contano come straordinario settimanale."),
    SettingsField("overtime_multiplier", "Moltiplicatore straordinario", "number",
                  "Es. 1.30 per +30%."),
    SettingsField("night_multiplier", "Moltiplicatore notturno", "number"),
    SettingsField("sunday_multiplier", "Moltiplicatore domenicale", "number"),
    SettingsField("holiday_multiplier", "Moltiplicatore festivo", "number"),
    SettingsField("morning_start", "Inizio mattina", "time", ui_hint="time"),
    SettingsField("morning_end", "Fine mattina", "time", ui_hint="time"),
    SettingsField("afternoon_start", "Inizio pomeriggio", "time", nullable=True, ui_hint="time"),
    SettingsField("afternoon_end", "Fine pomeriggio", "time", nullable=True, ui_hint="time"),
    SettingsField("night_start", "Inizio fascia notturna", "time", nullable=True, ui_hint="time"),
    SettingsField("night_end", "Fine fascia notturna", "time", nullable=True, ui_hint="time"),
    SettingsField("working_days", "Giorni lavorativi (bitmask lun=1, mar=2, ..., dom=64)", "integer",
                  "Es. 31 = lun-ven (0b0011111). 127 = tutti i giorni."),
    SettingsField("holidays_country", "Paese festività (ISO 2 lettere o vuoto)", "string",
                  "Es. 'IT' per festività italiane. Vuoto = nessuna detection auto.",
                  nullable=True),
]


def _wh_get(db: Session) -> Optional[WorkingHoursPolicy]:
    return db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.tenant_id == CURRENT_TENANT,
        WorkingHoursPolicy.is_default == True,  # noqa: E712
    ).first()


def _wh_read(db: Session, user: User) -> dict:
    p = _wh_get(db)
    if not p:
        return {"_missing": True, "_message": "Nessuna WorkingHoursPolicy default configurata."}
    return _serialize_dict(p, _WH_FIELDS)


def _wh_write(db: Session, user: User, patch: dict) -> dict:
    p = _wh_get(db)
    if not p:
        # Crea una policy default minimale al volo
        p = WorkingHoursPolicy(
            tenant_id=CURRENT_TENANT, is_default=True,
            name=patch.get("name") or "Default",
            morning_start=time(9, 0), morning_end=time(13, 0),
            afternoon_start=time(14, 0), afternoon_end=time(18, 0),
            working_days=31,
            daily_hours_threshold=8.0, weekly_hours_threshold=40.0,
            overtime_multiplier=1.30, night_multiplier=1.25,
            sunday_multiplier=1.50, holiday_multiplier=2.00,
            night_start=time(22, 0), night_end=time(6, 0),
            holidays_country="IT",
        )
        db.add(p)
        db.flush()
    diff = _apply_patch(p, _WH_FIELDS, patch)
    db.commit()
    return {"applied": diff, "current": _serialize_dict(p, _WH_FIELDS)}


# ── Schema: tenant_settings ───────────────────────────────────


_TENANT_FIELDS = [
    SettingsField("name", "Nome azienda", "string"),
    SettingsField("legal_name", "Ragione sociale", "string", nullable=True),
    SettingsField("vat_number", "P.IVA", "string", nullable=True),
    SettingsField("email", "Email aziendale", "string", nullable=True),
    SettingsField("phone", "Telefono", "string", nullable=True),
    SettingsField("website", "Sito web", "string", nullable=True),
    SettingsField("address", "Indirizzo", "string", nullable=True, ui_hint="long_text"),
    SettingsField("default_currency", "Valuta default", "enum",
                  choices=["EUR", "USD", "GBP", "CHF"]),
    SettingsField("default_vat_rate", "IVA default (%)", "number"),
    SettingsField("default_language", "Lingua default", "enum",
                  choices=["it", "en", "fr", "es", "de"]),
]


def _tenant_get(db: Session) -> Optional[Tenant]:
    return db.query(Tenant).filter(Tenant.id == CURRENT_TENANT).first()


def _tenant_read(db: Session, user: User) -> dict:
    t = _tenant_get(db)
    if not t:
        return {"_missing": True}
    return _serialize_dict(t, _TENANT_FIELDS)


def _tenant_write(db: Session, user: User, patch: dict) -> dict:
    t = _tenant_get(db)
    if not t:
        raise ValueError("Tenant non configurato")
    diff = _apply_patch(t, _TENANT_FIELDS, patch)
    db.commit()
    return {"applied": diff, "current": _serialize_dict(t, _TENANT_FIELDS)}


# ── Schema: user_preferences (UI per-utente, localStorage mirror) ──
#
# Le preferenze UI vivevano su localStorage (theme, font, sidebar layout). Le
# espongo via questo schema così che l'AI possa modificarle. Backed da User
# `extra_permissions`-style JSON column? No: le metto in una NotificationPref-
# style table. Per ora, un JSON column su User.
#
# DECISIONE: mantenere localStorage come fonte primaria (zero migrazione, no
# round-trip) e NON esporre questo schema all'AI. Lo aggiungiamo quando avremo
# una colonna User.preferences_json. Per ora, niente schema user_preferences.
#
# Esempio di come aggiungerlo in futuro:
# _USER_PREF_FIELDS = [
#     SettingsField("theme", "Tema", "enum", choices=["dark", "light", "auto"]),
#     SettingsField("sidebar_layout", "Layout sidebar", "string"),
# ]


# ── Registry pubblico ─────────────────────────────────────────


SCHEMAS: dict[str, SettingsSchema] = {
    "working_hours": SettingsSchema(
        key="working_hours",
        label="Orario di lavoro (policy default)",
        description=(
            "Soglie e moltiplicatori per il calcolo straordinari (giornaliero, "
            "settimanale, notturno, domenicale, festivo). Si applica come fallback "
            "a tutte le risorse senza override individuale."
        ),
        fields=_WH_FIELDS,
        read=_wh_read,
        write=_wh_write,
        permission="admin",
    ),
    "tenant_settings": SettingsSchema(
        key="tenant_settings",
        label="Dati azienda",
        description=(
            "Anagrafica fiscale dell'azienda (ragione sociale, P.IVA, indirizzo) e "
            "preferenze di default (valuta, IVA, lingua). Usate in fatture, quote, "
            "PDF clienti."
        ),
        fields=_TENANT_FIELDS,
        read=_tenant_read,
        write=_tenant_write,
        permission="admin",
    ),
}


def get_schema(key: str) -> Optional[SettingsSchema]:
    return SCHEMAS.get(key)


def list_schemas() -> list[dict]:
    """Ritorna lista di schema dicts (senza handlers, sicura per JSON)."""
    return [s.to_dict() for s in SCHEMAS.values()]


def can_user_access(schema: SettingsSchema, user: User) -> bool:
    """RBAC check: l'utente può modificare quest'area?

    - `permission == "self"` → ogni utente attivo (modifica i propri dati).
    - `permission == "admin"` → solo admin (legacy enum o role permissions).
    - altro → cercato in extra_permissions/role.permissions.
    """
    if not user or not user.is_active:
        return False
    p = schema.permission
    if p == "self":
        return True
    if p == "admin":
        if hasattr(user, "role") and user.role and getattr(user.role, "value", None) == "admin":
            return True
        # Fallback: role_obj con permission "admin" (se esiste)
        return bool(user.role_obj and "admin" in (user.role_obj.permissions or []))
    # Permesso specifico
    extra = set(user.extra_permissions or [])
    role_perms = set((user.role_obj.permissions or []) if user.role_obj else [])
    return p in (extra | role_perms)
