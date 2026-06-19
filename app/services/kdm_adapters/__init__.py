from app.services.kdm_adapters.manual import ManualAdapter

_ADAPTERS = {"manual": ManualAdapter}


def get_adapter(name: str):
    """Ritorna l'adapter richiesto; fallback su manual se sconosciuto."""
    cls = _ADAPTERS.get(name, ManualAdapter)
    return cls()
