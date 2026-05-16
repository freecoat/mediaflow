"""Build single PDF from docs/ARCHITETTURA.md with rendered Mermaid SVGs.

Uses: mmdc-generated rendered markdown + inline SVG + python-markdown + Chrome headless.
"""
from __future__ import annotations

import base64
import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ORIG_MD = DOCS / "ARCHITETTURA.md"
SRC_MD = DOCS / "ARCHITETTURA-rendered.md"
OUT_HTML = DOCS / "ARCHITETTURA.html"
OUT_PDF = DOCS / "ARCHITETTURA.pdf"


def run_mmdc() -> bool:
    """Render Mermaid charts to SVG + produce intermediate markdown."""
    if not ORIG_MD.exists():
        print(f"ERR {ORIG_MD} non trovato", file=sys.stderr)
        return False
    cmd = [
        "npx", "-p", "@mermaid-js/mermaid-cli", "mmdc",
        "-i", str(ORIG_MD), "-o", str(SRC_MD), "-e", "svg",
    ]
    print("> mmdc: rendering Mermaid -> SVG")
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=300)
    if result.returncode != 0:
        print(f"ERR mmdc exit {result.returncode}\n{result.stderr}", file=sys.stderr)
        return False
    return True


def cleanup_intermediates() -> None:
    """Remove mmdc temp files after PDF is built."""
    for p in DOCS.glob("ARCHITETTURA-rendered*.svg"):
        p.unlink(missing_ok=True)
    SRC_MD.unlink(missing_ok=True)
    for p in DOCS.glob("ARCHITETTURA-[0-9]*.pdf"):
        p.unlink(missing_ok=True)

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 10.5pt;
  line-height: 1.55;
  color: #1f2330;
  max-width: 100%;
}
h1 { font-size: 22pt; color: #6272f5; border-bottom: 2px solid #6272f5; padding-bottom: 6px; margin-top: 0; }
h2 { font-size: 16pt; color: #2a2f45; margin-top: 26px; border-bottom: 1px solid #e2e5ef; padding-bottom: 4px; }
h3 { font-size: 13pt; color: #3a4060; margin-top: 18px; }
h4 { font-size: 11pt; color: #4a5070; }
p, li { color: #2a2f45; }
code {
  background: #f4f5fa; padding: 1px 5px; border-radius: 3px;
  font-family: 'SF Mono', Consolas, monospace; font-size: 9.5pt; color: #c0457f;
}
pre {
  background: #f8f9fc; padding: 12px; border-radius: 6px; overflow-x: auto;
  border-left: 3px solid #6272f5; font-size: 9pt; line-height: 1.4;
  page-break-inside: avoid;
}
pre code { background: transparent; color: #2a2f45; padding: 0; }
blockquote {
  border-left: 4px solid #6272f5; background: #f4f5fa; padding: 8px 14px;
  margin: 12px 0; color: #4a5070; font-style: italic;
}
table {
  border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 9.5pt;
  page-break-inside: avoid;
}
th, td { border: 1px solid #d8dbe6; padding: 6px 9px; text-align: left; vertical-align: top; }
th { background: #eef0f8; color: #2a2f45; font-weight: 600; }
tr:nth-child(even) td { background: #f9fafc; }
img {
  max-width: 100%; height: auto; display: block; margin: 14px auto;
  page-break-inside: avoid;
}
img.mermaid-svg { max-height: 220mm; }
hr { border: none; border-top: 1px solid #d8dbe6; margin: 24px 0; }
a { color: #6272f5; text-decoration: none; }
ul, ol { padding-left: 22px; }
li { margin: 3px 0; }
.cover {
  page-break-after: always; text-align: center; padding-top: 80mm;
}
.cover h1 { border: none; font-size: 32pt; }
.cover .subtitle { font-size: 14pt; color: #6272f5; margin-top: 8px; }
.cover .meta { font-size: 10pt; color: #6c7287; margin-top: 40mm; }
"""


def inline_svg_images(html: str, base_dir: Path) -> str:
    """Replace <img src="local.svg"> with inline base64 to embed in single PDF."""
    pattern = re.compile(r'<img([^>]*?)src="([^"]+\.svg)"([^>]*)>')

    def repl(m: re.Match) -> str:
        before, src, after = m.group(1), m.group(2), m.group(3)
        svg_path = (base_dir / src).resolve()
        if not svg_path.exists():
            return m.group(0)
        data = svg_path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f'<img{before}src="data:image/svg+xml;base64,{b64}" class="mermaid-svg"{after}>'

    return pattern.sub(repl, html)


def find_chrome() -> str | None:
    """Find Chrome/Edge executable for headless PDF print on Windows."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    for name in ("chrome", "google-chrome", "msedge"):
        which = shutil.which(name)
        if which:
            return which
    return None


def main() -> int:
    if not SRC_MD.exists():
        if not run_mmdc():
            return 1

    md_text = SRC_MD.read_text(encoding="utf-8")

    cover = """
<div class="cover">
  <h1>MediaFlow</h1>
  <div class="subtitle">Architettura del Progetto</div>
  <div class="meta">
    v3.5.0-alpha.118 &middot; 16 maggio 2026<br/>
    Documento di sintesi per condivisione con team
  </div>
</div>
"""

    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "codehilite", "toc"],
        extension_configs={"codehilite": {"guess_lang": False, "noclasses": True}},
    )

    html_body = inline_svg_images(html_body, DOCS)

    full_html = f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8"/>
<title>MediaFlow - Architettura</title>
<style>{CSS}</style>
</head>
<body>
{cover}
{html_body}
</body>
</html>
"""

    OUT_HTML.write_text(full_html, encoding="utf-8")
    print(f"OK HTML scritto: {OUT_HTML}")

    chrome = find_chrome()
    if not chrome:
        print("WARN Chrome/Edge non trovato. Apri l'HTML e usa Stampa→Salva come PDF.", file=sys.stderr)
        return 0

    url = OUT_HTML.resolve().as_uri()
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--print-to-pdf={OUT_PDF}",
        "--print-to-pdf-no-header",
        "--no-pdf-header-footer",
        "--virtual-time-budget=10000",
        url,
    ]
    print(f"> {chrome} headless -> PDF")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        print(f"ERR Chrome exit {result.returncode}\n{result.stderr}", file=sys.stderr)
        return 1
    if not OUT_PDF.exists():
        print(f"ERR {OUT_PDF} non generato", file=sys.stderr)
        return 1
    size_kb = OUT_PDF.stat().st_size / 1024
    print(f"OK PDF: {OUT_PDF} ({size_kb:.1f} KB)")
    cleanup_intermediates()
    print("OK pulizia intermedi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
