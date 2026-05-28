"""
v3.5.0-alpha.172.106 — i18n audit script.

Scansiona template Jinja + JS, identifica stringhe italiane hardcoded NON
gia' coperte da data-i18n / MF_I18N / t() / __(). Output: report markdown
a `docs/i18n_audit_report.md` con count per file + sample strings + chiave
suggerita.

Heuristica detection italiana:
- Match parole italiane comuni (preposizioni, articoli, verbi tipici).
- Esclude: data-i18n="..." (gia' traducibile), code blocks, JSON, URL, classi CSS.
- Esclude: stringhe interamente numeriche/simboliche.

Output suggerisce chiave i18n basata su nome file + slug del testo.

Uso:
    python tools/i18n_audit.py [--root app] [--output docs/i18n_audit_report.md]
"""
from __future__ import annotations

import argparse
import re
import json
from pathlib import Path
from collections import defaultdict
from typing import Iterator


# Parole italiane indicative (matching case-insensitive su word boundary)
ITALIAN_WORDS = {
    # Articoli
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una",
    # Preposizioni
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
    "del", "dello", "della", "dei", "degli", "delle",
    "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "nel", "nello", "nella", "nei", "negli", "nelle",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    # Congiunzioni
    "e", "ed", "ma", "o", "anche", "ancora", "se", "che", "come", "quando",
    # Verbi comuni
    "Ã¨", "sono", "siete", "siamo", "stato", "stata", "stati", "state",
    "ha", "hanno", "abbiamo", "avete", "avete",
    "fare", "fatto", "fatti", "fai", "fa",
    "salva", "salvato", "salvati", "salvare",
    "elimina", "eliminato", "eliminati", "eliminare",
    "modifica", "modificato", "modificati", "modificare",
    "crea", "creato", "creati", "creare",
    "carica", "caricato", "caricati", "caricare",
    "aggiungi", "aggiunto", "aggiunti", "aggiungere",
    "annulla", "annullato", "conferma", "confermato",
    # Sostantivi UI/dominio
    "errore", "errori", "successo", "avviso", "messaggio",
    "cliente", "clienti", "progetto", "progetti", "quotazione", "quotazioni",
    "fattura", "fatture", "voce", "voci", "riga", "righe",
    "nuovo", "nuova", "nuovi", "nuove",
    "totale", "totali", "subtotale", "importo", "importi",
    "data", "date", "ora", "ore", "giorno", "giorni", "settimana", "mese", "mesi",
    "consegna", "consegne", "spedizione", "spedizioni",
    "campo", "campi", "obbligatorio", "opzionale",
    "selezionare", "scegli", "scelta",
    "ricerca", "filtra", "filtro", "filtri",
    "stato", "stati",
    "approvata", "approvato", "approvati",
    "rifiutata", "rifiutato",
    "inviata", "inviato",
    "scaduta", "scaduto",
    "bozza", "bozze",
    "attiva", "attivo", "attivi", "attive",
    "inattiva", "inattivo",
    "valida", "valido", "non valido",
    "richiesto", "richiesti",
    "salvataggio", "caricamento", "elaborazione",
    "specifiche", "tecniche", "tecnico", "tecnica",
    "fornitore", "fornitori",
    "risorsa", "risorse",
    "lavorazione", "lavorazioni",
    "pianificato", "pianificata",
    "consegnato", "consegnata", "consegnati", "consegnate",
    "approva", "rifiuta", "invia", "scarica", "carica", "esporta", "importa",
    "prenota", "prenotato", "prenotata",
}

# File da scansionare
TEMPLATE_GLOB = "templates/**/*.html"
JS_GLOB = "static/js/**/*.js"

# Pattern stringhe da analizzare
HTML_TEXT_PATTERN = re.compile(r">([^<>{}\n]{3,}?)<", re.UNICODE)
HTML_ATTR_PATTERN = re.compile(
    r'\b(title|placeholder|alt|aria-label|value)\s*=\s*"([^"]{3,}?)"',
    re.UNICODE,
)
JS_STRING_PATTERN = re.compile(r"""(?:'([^'\\\n]{3,}?)'|"([^"\\\n]{3,}?)"|`([^`\\\n]{3,}?)`)""", re.UNICODE)
JINJA_BLOCK_PATTERN = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)


def is_italian(text: str) -> bool:
    """Heuristica: la stringa contiene parole italiane indicative."""
    if len(text.strip()) < 3:
        return False
    # Skip stringhe interamente numeriche/punteggiatura
    if re.match(r"^[\d\s\.,;:!?+\-*/=()\[\]{}<>%€$_#@&|\\'\"`~^]+$", text):
        return False
    # Skip URL, percorsi, classi CSS, code
    if re.match(r"^(https?://|/[a-z]|#[a-z]|\.[a-z\-]+|[a-z\-_]+\(\))", text.strip().lower()):
        return False
    # Skip identificatori snake_case/camelCase (sembrano variabili)
    if re.match(r"^[a-z_]+$", text.strip()) or re.match(r"^[a-z][a-zA-Z0-9]*$", text.strip()):
        return False
    # Match parola italiana
    words = re.findall(r"[a-zA-ZÃ Ã¨Ã©ÃÃ²Ã¹]+", text.lower())
    italian_hits = sum(1 for w in words if w in ITALIAN_WORDS)
    return italian_hits >= 1


def has_i18n_marker(line: str, text: str) -> bool:
    """Check se la stringa o la riga e' gia' coperta da i18n marker."""
    if "data-i18n" in line:
        return True
    if 't(' in line and '"' in line:
        return True
    if "MF_I18N" in line:
        return True
    return False


def slugify(s: str, max_len: int = 24) -> str:
    """Slug per chiave i18n suggerita."""
    s = re.sub(r"[^\w\s]", "", s).strip().lower()
    s = re.sub(r"\s+", "_", s)
    return s[:max_len]


def scan_html(path: Path) -> Iterator[dict]:
    """Yield {line, kind, text, suggested_key} per ogni stringa italiana non-coperta."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return
    # Rimuovi blocchi Jinja per non sporcare match
    cleaned = JINJA_BLOCK_PATTERN.sub("", content)
    file_slug = path.stem
    for i, line in enumerate(cleaned.splitlines(), start=1):
        # Text in tag
        for m in HTML_TEXT_PATTERN.finditer(line):
            text = m.group(1).strip()
            if not is_italian(text):
                continue
            if has_i18n_marker(line, text):
                continue
            yield {
                "line": i, "kind": "text", "text": text,
                "suggested_key": f"{file_slug}.{slugify(text)}",
            }
        # Attributi
        for m in HTML_ATTR_PATTERN.finditer(line):
            attr, text = m.group(1), m.group(2).strip()
            if not is_italian(text):
                continue
            if has_i18n_marker(line, text):
                continue
            yield {
                "line": i, "kind": f"attr:{attr}", "text": text,
                "suggested_key": f"{file_slug}.{attr}.{slugify(text)}",
            }


def scan_js(path: Path) -> Iterator[dict]:
    """Yield stringhe italiane in JS (toast, prompt, alert, console.log, etc)."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return
    file_slug = path.stem
    for i, line in enumerate(content.splitlines(), start=1):
        # Skip comments
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        for m in JS_STRING_PATTERN.finditer(line):
            text = m.group(1) or m.group(2) or m.group(3) or ""
            text = text.strip()
            if not is_italian(text):
                continue
            if has_i18n_marker(line, text):
                continue
            yield {
                "line": i, "kind": "js_string", "text": text,
                "suggested_key": f"{file_slug}.{slugify(text)}",
            }


def main():
    parser = argparse.ArgumentParser(description="Audit stringhe italiane non-traducibili.")
    parser.add_argument("--root", default="app", help="Root path (default: app)")
    parser.add_argument(
        "--output", default="docs/i18n_audit_report.md",
        help="Output markdown path",
    )
    parser.add_argument("--max-samples", type=int, default=5,
                        help="Sample strings per file (default 5)")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"Root non trovata: {root}")
        return 1

    findings_by_file: dict = defaultdict(list)
    total_count = 0

    # Scansiona template
    for tpl in sorted(root.glob(TEMPLATE_GLOB)):
        for f in scan_html(tpl):
            findings_by_file[str(tpl)].append(f)
            total_count += 1

    # Scansiona JS
    for js in sorted(root.glob(JS_GLOB)):
        # Skip i18n.js stesso (dict di traduzioni)
        if js.name == "i18n.js":
            continue
        for f in scan_js(js):
            findings_by_file[str(js)].append(f)
            total_count += 1

    # Genera report markdown
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append(f"# i18n Audit Report — v3.5.0-alpha.172.106")
    lines.append("")
    lines.append(f"**Totale stringhe italiane hardcoded NON coperte da i18n**: {total_count}")
    lines.append(f"**File con findings**: {len(findings_by_file)}")
    lines.append(f"**Lingue target**: it (sorgente), en, fr, de, es")
    lines.append("")
    lines.append("## Top 30 file per count")
    lines.append("")
    lines.append("| File | Count | Esempi |")
    lines.append("| --- | ---: | --- |")
    sorted_files = sorted(
        findings_by_file.items(), key=lambda kv: -len(kv[1])
    )
    for path, items in sorted_files[:30]:
        examples = ", ".join(f'"{x["text"][:30]}"' for x in items[:3])
        lines.append(f"| `{path}` | {len(items)} | {examples} |")
    lines.append("")

    lines.append("## Findings per file (top 15 file, dettaglio)")
    lines.append("")
    for path, items in sorted_files[:15]:
        lines.append(f"### `{path}` ({len(items)} stringhe)")
        lines.append("")
        lines.append("| Line | Kind | Text | Suggested key |")
        lines.append("| ---: | --- | --- | --- |")
        for f in items[:args.max_samples * 4]:  # max 20 per file in report
            txt = f["text"].replace("|", "\\|")[:80]
            lines.append(
                f"| {f['line']} | {f['kind']} | `{txt}` | `{f['suggested_key']}` |"
            )
        if len(items) > args.max_samples * 4:
            lines.append(f"| ... | ... | ({len(items) - args.max_samples * 4} altre stringhe) | ... |")
        lines.append("")

    lines.append("## Come procedere")
    lines.append("")
    lines.append("1. **Aggiungi chiave** a `app/static/js/i18n.js` dict `window.MF_I18N`:")
    lines.append("   ```js")
    lines.append("   'chiave.suggerita': {it: 'Testo italiano', en: 'English', fr: 'Français', de: 'Deutsch', es: 'Español'},")
    lines.append("   ```")
    lines.append("")
    lines.append("2. **Annota nel template** la stringa con `data-i18n`:")
    lines.append("   ```html")
    lines.append("   <span data-i18n=\"chiave.suggerita\">Testo italiano</span>")
    lines.append("   ```")
    lines.append("")
    lines.append("3. **Per attributi** (placeholder/title/etc) usa `data-i18n-attr`:")
    lines.append("   ```html")
    lines.append("   <input data-i18n=\"chiave.placeholder\" data-i18n-attr=\"placeholder\" placeholder=\"Cerca\">")
    lines.append("   ```")
    lines.append("")
    lines.append("4. **Per JS toast/prompt** crea helper `t(key, default)`:")
    lines.append("   ```js")
    lines.append("   toast(t('errors.save_failed', 'Salvataggio fallito'), 'error');")
    lines.append("   ```")
    lines.append("")
    lines.append("Re-run audit per verificare gap dopo ogni batch di traduzioni.")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report scritto in {out_path}")
    print(f"Totale stringhe: {total_count}")
    print(f"File interessati: {len(findings_by_file)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
