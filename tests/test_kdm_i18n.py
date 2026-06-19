import re
from pathlib import Path

I18N_PATH = Path("app/static/js/i18n.js")
I18N = I18N_PATH.read_text(encoding="utf-8")

KEYS = ["nav.kdm", "kdm.title", "kdm.tab.requests", "kdm.tab.facilities",
        "kdm.tab.cpl", "kdm.col.status", "kdm.action.match"]

# Full set from the brief (all 18 keys)
ALL_KDM_KEYS = [
    "nav.kdm",
    "kdm.title",
    "kdm.new_request",
    "kdm.tab.requests",
    "kdm.tab.facilities",
    "kdm.tab.cpl",
    "kdm.col.status",
    "kdm.col.type",
    "kdm.col.title",
    "kdm.col.window",
    "kdm.col.match",
    "kdm.action.match",
    "kdm.candidates",
    "kdm.load_error",
    "kdm.empty.facilities",
    "kdm.empty.cpl",
    "kdm.gen_link",
    "kdm.link_copied",
    "kdm.prefill_title",
]

# The project uses a flat MF_I18N dict with single-quoted keys and all 5
# locale values inline: 'key': {it: '...', en: '...', fr: '...', de: '...', es: '...'}
# A key "present in all 5 locales" means it exists in the dict AND has all 5 lang codes.
_ENTRY_RE = re.compile(r"'([\w.]+)'\s*:\s*\{([^}]+)\}", re.MULTILINE)


def _parse_i18n():
    """Return dict of key -> set of locale codes present."""
    result = {}
    for m in _ENTRY_RE.finditer(I18N):
        key = m.group(1)
        body = m.group(2)
        langs = set(re.findall(r'\b(it|en|fr|de|es)\s*:', body))
        result[key] = langs
    return result


_PARSED = _parse_i18n()


def test_kdm_keys_present_in_all_locales():
    """Each KDM key must exist with all 5 locale codes (it/en/fr/de/es)."""
    for k in KEYS:
        assert k in _PARSED, f"Key '{k}' not found in MF_I18N"
        missing = {'it', 'en', 'fr', 'de', 'es'} - _PARSED[k]
        assert not missing, f"Key '{k}' missing locales: {missing}"


def test_all_kdm_keys_present():
    """All 18 KDM keys from the brief must be present with all 5 locales."""
    for k in ALL_KDM_KEYS:
        assert k in _PARSED, f"Key '{k}' not found in MF_I18N"
        missing = {'it', 'en', 'fr', 'de', 'es'} - _PARSED[k]
        assert not missing, f"Key '{k}' missing locales: {missing}"
