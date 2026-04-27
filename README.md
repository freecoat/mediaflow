# MediaFlow

Piattaforma open-source per **gestione risorse**, **pianificazione**, **rendicontazione finanziaria** e **DAM**.

## Avvio Windows

1. Installa Python 3.11+ da python.org (spunta "Add Python to PATH")
2. Estrai la cartella `mediaflow`
3. Doppio clic su **`avvia.bat`** — installa tutto e apre il browser

Oppure manualmente:
```
.venv\Scripts\activate
pip install -r requirements.txt
python scripts\seed_demo.py
python run.py
```

## Avvio macOS / Linux

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/seed_demo.py
python run.py
```

## Credenziali demo
- Admin: admin@mediaflow.it / admin123
- Editor: editor@mediaflow.it / editor123

## API PDF fattura
GET /finance/api/invoices/{id}/pdf
