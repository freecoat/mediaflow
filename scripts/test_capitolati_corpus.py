"""F15 — Test E2E parser DeliveryTemplate sui 17 capitolati reali.

v3.5.0-alpha.66.20.1 — Batch-parsa ogni file in `docs/capitolati_esempio/`
e produce un report (stdout + JSON file) con:
  - n_blocchi_popolati (su 8)
  - ai_confidence
  - code + name + broadcaster estratti
  - errori (estrazione testo fallita / AI provider non disponibile /
    JSON parse fail / risposta vuota)
  - tempo elapsed per file
  - somma costi (se provider Anthropic con cache logging)

USO:
    # Sul Mac di Matteo, con venv attivo e provider AI configurato:
    python scripts/test_capitolati_corpus.py

    # Specifica un file singolo per debug:
    python scripts/test_capitolati_corpus.py --file Netflix_Deliverables.txt

    # Output JSON per analisi successiva:
    python scripts/test_capitolati_corpus.py --json out_report.json

    # Skip un file specifico (es. xlsx pesanti):
    python scripts/test_capitolati_corpus.py --skip "*.xlsx"

NB: ogni chiamata API consuma token. 17 file × ~4k token = ~68k token
totali. Con Claude Sonnet 4.6 + cache è circa $0.20-0.40 per run.
"""
from __future__ import annotations
import argparse
import fnmatch
import json
import sys
import time
from pathlib import Path

# Bootstrap path verso il modulo `app` (script lanciato da scripts/)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CORPUS_DIR = ROOT / "docs" / "capitolati_esempio"

# Blocchi attesi nel DeliveryTemplate (gli 8 canonici)
EXPECTED_BLOCKS = [
    "video_specs", "audio_specs", "text_specs", "head_format",
    "textless_format", "naming_convention", "archive_specs",
    "metadata_requirements",
]


def fmt_status(filled: int) -> str:
    """Banner colorato per terminale (ANSI). Verde 7-8, giallo 4-6, rosso 0-3."""
    if filled >= 7:
        return f"\033[92m{filled}/8\033[0m"
    if filled >= 4:
        return f"\033[93m{filled}/8\033[0m"
    return f"\033[91m{filled}/8\033[0m"


def process_file(path: Path) -> dict:
    """Processa un singolo capitolato. Ritorna dict con stats + payload (o errore)."""
    from app.services.deliverables_parser import (
        extract_text_from_file, parse_delivery_template,
    )

    out = {
        "file": path.name,
        "size_kb": round(path.stat().st_size / 1024, 1),
        "elapsed_s": None,
        "text_chars": 0,
        "blocks_filled": 0,
        "blocks_detail": {},
        "code": None,
        "name": None,
        "broadcaster": None,
        "ai_confidence": None,
        "error": None,
    }
    start = time.time()
    try:
        file_bytes = path.read_bytes()
        text = extract_text_from_file(file_bytes, path.name)
        out["text_chars"] = len(text)
        if not text or len(text.strip()) < 20:
            out["error"] = f"Estrazione testo fallita o troppo breve ({len(text)} chars)"
            out["elapsed_s"] = round(time.time() - start, 2)
            return out

        parsed = parse_delivery_template(text)
        out["elapsed_s"] = round(time.time() - start, 2)
        if parsed is None:
            out["error"] = "Parser ha ritornato None (provider AI non configurato o estrazione fallita)"
            return out

        out["code"] = parsed.get("code")
        out["name"] = parsed.get("name")
        out["broadcaster"] = parsed.get("broadcaster")
        out["ai_confidence"] = parsed.get("ai_confidence")

        for blk in EXPECTED_BLOCKS:
            data = parsed.get(blk)
            has_data = bool(data) and isinstance(data, dict) and len(data) > 0
            out["blocks_detail"][blk] = {
                "present": has_data,
                "keys": list(data.keys()) if isinstance(data, dict) else [],
            }
            if has_data:
                out["blocks_filled"] += 1
    except Exception as e:
        out["elapsed_s"] = round(time.time() - start, 2)
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def main():
    ap = argparse.ArgumentParser(description="F15 test corpus capitolati")
    ap.add_argument("--file", help="Processa solo questo nome file (basename)")
    ap.add_argument("--skip", action="append", default=[], help="Pattern glob da saltare (ripetibile)")
    ap.add_argument("--json", help="Salva report JSON in questo path")
    ap.add_argument("--limit", type=int, default=None, help="Processa solo primi N file")
    args = ap.parse_args()

    if not CORPUS_DIR.is_dir():
        print(f"❌ Directory non trovata: {CORPUS_DIR}", file=sys.stderr)
        sys.exit(1)

    all_files = sorted([p for p in CORPUS_DIR.iterdir() if p.is_file()])
    if args.file:
        all_files = [p for p in all_files if p.name == args.file]
        if not all_files:
            print(f"❌ File non trovato: {args.file}", file=sys.stderr)
            sys.exit(1)
    for pat in args.skip:
        all_files = [p for p in all_files if not fnmatch.fnmatch(p.name, pat)]
    if args.limit:
        all_files = all_files[: args.limit]

    print(f"📦 Corpus: {len(all_files)} file in {CORPUS_DIR}")
    print(f"⏱  Stima: ~{len(all_files) * 15}s ({len(all_files) * 4}k token, ~${len(all_files) * 0.02:.2f})")
    print("─" * 90)

    results = []
    total_start = time.time()
    for i, f in enumerate(all_files, 1):
        print(f"[{i:2d}/{len(all_files)}] {f.name[:60]:<60} ", end="", flush=True)
        r = process_file(f)
        results.append(r)
        if r["error"]:
            print(f"❌ {r['error'][:50]}")
        else:
            conf = r["ai_confidence"]
            conf_pct = f"{int(conf*100)}%" if conf is not None else "  —"
            print(f"{fmt_status(r['blocks_filled'])}  conf={conf_pct:<4}  {r['elapsed_s']:>5.1f}s  {r['code'] or '?'}")

    elapsed_total = round(time.time() - total_start, 1)
    print("─" * 90)
    ok = [r for r in results if not r["error"]]
    failed = [r for r in results if r["error"]]
    avg_blocks = sum(r["blocks_filled"] for r in ok) / len(ok) if ok else 0
    avg_conf = sum(r["ai_confidence"] or 0 for r in ok if r["ai_confidence"] is not None) / max(1, len([r for r in ok if r["ai_confidence"] is not None]))

    print(f"\n📊 RIASSUNTO")
    print(f"   File OK:           {len(ok)}/{len(results)}")
    print(f"   File falliti:      {len(failed)}")
    print(f"   Blocchi medi:      {avg_blocks:.1f}/8")
    print(f"   Confidence media:  {avg_conf*100:.0f}%")
    print(f"   Tempo totale:      {elapsed_total}s")

    if failed:
        print(f"\n❌ FALLITI:")
        for r in failed:
            print(f"   - {r['file']}: {r['error']}")

    # Frequenza blocchi popolati
    if ok:
        print(f"\n📈 FREQUENZA BLOCCHI (su {len(ok)} file OK):")
        for blk in EXPECTED_BLOCKS:
            n = sum(1 for r in ok if r["blocks_detail"].get(blk, {}).get("present"))
            bar = "█" * int(n / max(1, len(ok)) * 20)
            print(f"   {blk:<22} {bar:<20}  {n}/{len(ok)} ({int(n/len(ok)*100)}%)")

    if args.json:
        out_path = Path(args.json)
        out_path.write_text(json.dumps({
            "summary": {
                "total": len(results),
                "ok": len(ok),
                "failed": len(failed),
                "avg_blocks_filled": round(avg_blocks, 2),
                "avg_confidence": round(avg_conf, 3),
                "elapsed_total_s": elapsed_total,
            },
            "results": results,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n💾 Report JSON salvato in {out_path}")


if __name__ == "__main__":
    main()
