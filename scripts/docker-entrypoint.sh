#!/bin/sh
# v3.5.0-alpha.172.171 — entrypoint produzione Claqo.
# 1) assicura le cartelle dati sul volume  2) bootstrap admin idempotente
# 3) avvia il comando (uvicorn). Le tabelle + auto-migrate colonne avvengono
#    nello startup lifespan di app.main.
set -e

mkdir -p /data/uploads 2>/dev/null || true

# Bootstrap admin SOLO se il DB non ha utenti (idempotente). Disattivabile con
# BOOTSTRAP_ADMIN=0 (es. quando si gestiscono gli utenti manualmente).
if [ "${BOOTSTRAP_ADMIN:-1}" = "1" ]; then
  python scripts/bootstrap_admin.py || echo "[entrypoint] bootstrap_admin saltato/errore (non bloccante)"
fi

exec "$@"
