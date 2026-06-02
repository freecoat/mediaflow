# Deploy Claqo — hosting backend

Artefatti portabili (v3.5.0-alpha.172.171): `Dockerfile`, `docker-compose.yml`,
`.dockerignore`, `.env.production.example`, `scripts/docker-entrypoint.sh`,
`scripts/bootstrap_admin.py`. Girano su **qualsiasi host Docker** (VPS, Fly.io,
Render, Railway).

## 1. Prerequisiti
- Host con Docker + Docker Compose.
- Un dominio (per HTTPS e branding) — opzionale all'inizio (si può usare l'IP).

## 2. Configurazione segreti
```bash
cp .env.production.example .env
# genera i segreti:
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print('AI_KEY_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
# incollali in .env + imposta ADMIN_EMAIL / ADMIN_PASSWORD
```

## 3. Avvio
```bash
docker compose up -d --build
docker compose logs -f          # verifica: bootstrap admin + "Application startup complete"
curl -fsS http://localhost:8000/health
```
Primo boot: crea tabelle + auto-migrate colonne + admin (da `ADMIN_EMAIL/PASSWORD`).
DB SQLite e uploads vivono sul volume `claqo_data` (persistono ai redeploy).

## 4. HTTPS + dominio (VPS) — Caddy (TLS automatico)
Esporre il container solo su localhost (`127.0.0.1:8000:8000` in compose) e mettere
Caddy davanti. `Caddyfile`:
```
claqo.tuodominio.it {
    reverse_proxy 127.0.0.1:8000
}
```
Caddy ottiene e rinnova il certificato Let's Encrypt da solo. Alternative: nginx +
certbot, o Traefik.

## 5. Backup (importante)
Il DB è un file sul volume. Backup periodico:
```bash
docker compose exec claqo sh -c "cp /data/mediaflow.db /data/backup-$(date +%F).db"
# poi sync del volume / del file su storage esterno (S3/rclone/cron)
```
Per gli asset: in cloud conviene configurare lo **storage S3** (vars `AWS_*` in `.env`)
così gli upload non stanno sul volume locale.

## 6. Note sicurezza produzione
- `APP_ENV=production` → SQL echo OFF, niente reload.
- `AUTH_REQUIRED=true` → auth fail-closed (niente fallback primo-admin).
- Cambia la password admin al primo accesso. MFA TOTP disponibile in `/settings`.
- Esporre solo 443 (Caddy); il container resta su localhost.

## 7. Scelte aperte (vedi STATO.md)
- **DB**: SQLite-su-volume (parti subito, ok piccolo team) → **Postgres** quando
  servono più worker / concorrenza scrittura (`DATABASE_URL=postgresql+psycopg://…`,
  alzare `--workers`). Il porting Float→Numeric è già previsto per Postgres.
- **Provider**: PaaS (Fly/Render/Railway, low-ops) vs VPS EU (Hetzner, sovranità
  dato + costo, gestione manuale). Regione **EU** consigliata (GDPR, post-house IT).
- **Multi-tenant hard** (Fase 7) e **rebrand** finale si intrecciano con l'hosting
  pubblico.
