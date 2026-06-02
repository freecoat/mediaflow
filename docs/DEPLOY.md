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

### A) Produzione VPS con HTTPS (consigliato) — `docker-compose.prod.yml` + Caddy
Imposta `DOMAIN` + `ACME_EMAIL` in `.env`, punta il dominio (A/AAAA) al server, apri 80/443:
```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f   # bootstrap admin + "startup complete"
```
Caddy ottiene e rinnova il certificato Let's Encrypt da solo. `claqo` NON è esposto
sull'host (solo rete interna); pubblico solo 80/443 via Caddy. Header di sicurezza
(HSTS, nosniff, frame SAMEORIGIN) già applicati in `deploy/Caddyfile`.

### B) Avvio semplice / locale-docker (no TLS) — `docker-compose.yml`
```bash
docker compose up -d --build
curl -fsS http://localhost:8000/health
```
Espone :8000 in chiaro — solo per test/dietro un proxy già esistente.

Primo boot (entrambi): crea tabelle + auto-migrate colonne + admin (da
`ADMIN_EMAIL/PASSWORD`). DB SQLite e uploads vivono sul volume `claqo_data`.

## 4. Sicurezza HTTPS già inclusa
- Cookie auth/portal con flag **Secure** automatico in `APP_ENV=production` (oltre a
  HttpOnly + SameSite=Lax).
- Caddy: HSTS, X-Content-Type-Options, Referrer-Policy, X-Frame-Options SAMEORIGIN.
- Alternative a Caddy: nginx+certbot o Traefik (sostituiscono il servizio `caddy`).

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

## 7. Roadmap hosting (decisioni 2 giu 2026)
- **Linea attuale**: VPS EU + **SQLite singola istanza** su volume. Self-hosted
  sempre supportato (clienti con prerequisiti di sicurezza straordinari).
- **Postgres = milestone pianificata** (NON ora). Trigger per migrare:
  2° tenant/team in una stessa istanza · errori "database is locked" sotto carico ·
  necessità di più worker · cliente enterprise che lo impone. La migrazione comporta:
  `Float→Numeric`, adozione **Alembic** (le auto-migrate attuali sono DDL SQLite-shaped),
  retest su PG. `DATABASE_URL=postgresql+psycopg://…` + alzare `--workers`.
- **Isolamento per cliente sicurezza**: **deployment-per-tenant** = un'istanza Docker
  + DB dedicati per quel cliente (anche self-hosted da loro). Isolamento fisico totale,
  zero codice nuovo — già abilitato da questi artefatti.
- **DB-per-tenant in una sola istanza** (SaaS multi-tenant) = **Fase 7**: serve un
  connection-registry (engine/SessionLocal per tenant; la resolution chain
  `_resolve_tenant_from_request` esiste già), migrazioni ×N tenant, dashboard
  platform-admin a fan-out. Con SQLite: un `.db` per tenant aggira il single-writer.
- **Dominio/rebrand**: il dominio finale dipende dal nome (Claqo non confermato) →
  primo deploy su IP/sottodominio provvisorio.
