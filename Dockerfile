# ───────────────────────────────────────────────────────────────────
# Claqo — immagine produzione (v3.5.0-alpha.172.171)
# Portabile: gira su qualsiasi host Docker (VPS, Fly.io, Render, Railway).
# DB SQLite + uploads su volume montato in /data (vedi docker-compose).
# ───────────────────────────────────────────────────────────────────
FROM python:3.13-slim

# Dipendenze di sistema minime (Pillow runtime libs). Niente toolchain build:
# i requirements usano solo wheel precompilate.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo zlib1g curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production

WORKDIR /app

# Layer dipendenze separato (cache build): copia solo requirements prima.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Codice applicativo
COPY . .

# Utente non-root + cartella dati persistente (DB + uploads)
RUN useradd -m -u 10001 claqo && mkdir -p /data/uploads && chown -R claqo:claqo /app /data
USER claqo

# Default: DB e uploads sul volume /data (override via env in compose/PaaS)
ENV DATABASE_URL=sqlite:////data/mediaflow.db \
    UPLOAD_DIR=/data/uploads \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# Healthcheck nativo (l'endpoint /health esiste già)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Avvio: lo startup lifespan di main.py crea tabelle + auto-migrate colonne.
# 1 solo worker: SQLite non regge scritture concorrenti multi-processo
# (WAL gestisce i lettori). Passare a Postgres → alzare --workers.
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
