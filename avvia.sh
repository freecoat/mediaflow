#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#  MediaFlow — Installazione e avvio su macOS / Linux
#  Lancialo con:  ./avvia.sh   (prima volta: chmod +x avvia.sh)
# ═══════════════════════════════════════════════════════════════════

set -e

cd "$(dirname "$0")"

echo ""
echo " MediaFlow — Avvio"
echo " ─────────────────────────────────────────────────────────────"
echo ""

# Trova Python 3 disponibile
PYTHON_CMD=""
for candidate in python3.12 python3.13 python3.11 python3; do
    if command -v "$candidate" &> /dev/null; then
        PYTHON_CMD="$candidate"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "[ERRORE] Python 3 non trovato nel sistema."
    echo "Su macOS, installa Xcode Command Line Tools con:"
    echo "  xcode-select --install"
    exit 1
fi

PYVER=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
echo "[OK] Python $PYVER ($PYTHON_CMD)"

# Crea venv se non esiste
if [ ! -d ".venv" ]; then
    echo ""
    echo "[1/3] Creazione ambiente virtuale..."
    $PYTHON_CMD -m venv .venv
    echo "[OK] Ambiente virtuale creato"
else
    echo "[OK] Ambiente virtuale già presente"
fi

# Attiva venv
source .venv/bin/activate

# Aggiorna pip e installa dipendenze
echo ""
echo "[2/3] Installazione dipendenze Python..."
pip install --upgrade pip --quiet --disable-pip-version-check
pip install -r requirements.txt --quiet --disable-pip-version-check
echo "[OK] Dipendenze installate"

# Seed database se non esiste
if [ ! -f "mediaflow.db" ]; then
    echo ""
    echo "[3/3] Inizializzazione database con dati demo..."
    python scripts/seed_demo.py
    echo "[OK] Database inizializzato"
else
    echo "[OK] Database esistente trovato"
fi

# Crea cartelle upload
mkdir -p uploads/assets uploads/thumbnails

echo ""
echo " ─────────────────────────────────────────────────────────────"
echo "  MediaFlow è pronto!"
echo ""
echo "  Credenziali demo:"
echo "    Admin  : admin@mediaflow.it  / admin123"
echo "    Editor : editor@mediaflow.it / editor123"
echo ""
echo "  Apertura browser su http://localhost:8000 ..."
echo "  (premi CTRL+C per fermare il server)"
echo " ─────────────────────────────────────────────────────────────"
echo ""

# Apri il browser dopo 2 secondi
(sleep 2 && open http://localhost:8000 2>/dev/null || xdg-open http://localhost:8000 2>/dev/null) &

# Avvia server
python run.py
