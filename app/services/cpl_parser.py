"""Parser CPL.xml (SMPTE + Interop), namespace-tolerant. Niente crypto.

SICUREZZA: il CPL.xml arriva dal cliente (input non fidato). Usa defusedxml
per neutralizzare XXE (external entity) e billion-laughs (entity expansion).
NON usare xml.etree.ElementTree.fromstring direttamente su input non fidato.
"""
from defusedxml.ElementTree import fromstring as _safe_fromstring
from xml.etree.ElementTree import ParseError


def _local(tag: str) -> str:
    """Strip namespace: '{ns}Id' -> 'Id'."""
    return tag.rsplit("}", 1)[-1]


def _find_local(elem, name: str):
    for e in elem.iter():
        if _local(e.tag) == name:
            return e
    return None


def _findall_local(elem, name: str):
    return [e for e in elem.iter() if _local(e.tag) == name]


def parse_cpl(xml_bytes: bytes) -> dict:
    """Estrae metadati da un CPL.xml. Raises ValueError se non è un CPL."""
    try:
        root = _safe_fromstring(xml_bytes)
    except ParseError as e:
        raise ValueError(f"XML non valido: {e}")
    except Exception as e:
        # defusedxml solleva EntitiesForbidden / DTDForbidden su payload ostili
        raise ValueError(f"XML rifiutato (sicurezza): {e}")
    if _local(root.tag) != "CompositionPlaylist":
        raise ValueError("Non è un CompositionPlaylist (CPL)")

    id_el = _find_local(root, "Id")
    cpl_uuid = (id_el.text or "").strip() if id_el is not None else ""
    if not cpl_uuid:
        raise ValueError("CPL senza Id")

    title_el = _find_local(root, "ContentTitleText")
    content_title = (title_el.text or "").strip() if title_el is not None else None

    er_el = _find_local(root, "EditRate")
    edit_rate = (er_el.text or "").strip() if er_el is not None else None

    # Durata: max IntrinsicDuration tra le tracce (proxy della durata reel).
    durations = []
    for d in _findall_local(root, "IntrinsicDuration"):
        try:
            durations.append(int((d.text or "").strip()))
        except (TypeError, ValueError):
            pass
    duration_frames = max(durations) if durations else None

    key_ids = [(k.text or "").strip() for k in _findall_local(root, "KeyId")
               if (k.text or "").strip()]

    return {
        "cpl_uuid": cpl_uuid,
        "content_title_text": content_title,
        "edit_rate": edit_rate,
        "duration_frames": duration_frames,
        "encrypted": bool(key_ids),
        "key_ids": key_ids,
    }
