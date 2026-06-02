# Self-host Claqo da ufficio/casa (Cloudflare Tunnel)

Hosting on-premise: il server gira sulla tua macchina (ufficio/casa), il dato resta
in sede. `cloudflared` apre una connessione **uscente** verso Cloudflare → niente
port-forward, niente IP pubblico, **funziona anche dietro CGNAT**. HTTPS + hostname
stabile li gestisce Cloudflare. (v3.5.0-alpha.172.173)

## Prerequisiti
- Macchina sempre accesa con Docker (mini-PC, Mac mini, NAS, PC dedicato).
- Account Cloudflare (free) + un dominio gestito su Cloudflare.

## Setup
1. **Cloudflare Zero Trust → Networks → Tunnels → Create tunnel** (tipo *Cloudflared*).
   Copia il **token** del tunnel.
2. Nel tunnel, **Public hostname**: scegli `app.tuodominio.it` →
   **Service**: `HTTP` → `claqo:8000`.
3. Sulla macchina:
   ```bash
   cp .env.production.example .env
   # genera SECRET_KEY + AI_KEY_ENCRYPTION_KEY (vedi DEPLOY.md), imposta ADMIN_*
   # incolla il token:  TUNNEL_TOKEN=...
   docker compose -f docker-compose.tunnel.yml up -d --build
   docker compose -f docker-compose.tunnel.yml logs -f
   ```
4. Apri `https://app.tuodominio.it` → login con `ADMIN_EMAIL/ADMIN_PASSWORD`.

## Sicurezza extra (consigliata)
- **Cloudflare Access** (Zero Trust, free): gate email/SSO *prima* di raggiungere
  l'app → secondo fattore d'accesso a livello di rete.
- `AUTH_REQUIRED=true`, MFA TOTP in `/settings`, cookie Secure (già attivi in prod).
- Cloudflare nasconde l'IP di casa e filtra abusi/DDoS.

## ⚠️ Backup offsite (obbligatorio)
Hardware di casa/ufficio può rompersi. Il DB è un file sul volume `claqo_data`:
```bash
docker compose -f docker-compose.tunnel.yml exec claqo \
  sh -c "cp /data/mediaflow.db /data/backup-$(date +%F).db"
```
Poi sincronizza il file **fuori sede** (rclone/S3/altro NAS) via cron. In più, l'app
ha l'export DB ZIP in /settings → Dati.

## Asset: metadato nel SaaS, binari sul server del tenant
**Principio architetturale (decisione 2 giu 2026)**: Claqo NON carica fisicamente i
file degli asset. Conserva **metadato + riferimento** al path dove il file vive già,
sul server/storage del tenant. Vantaggi: niente duplicazione, banda risparmiata,
dato sotto controllo del tenant (sovranità/sicurezza).

Già supportato:
- **`POST /dam/api/fs-scan`** indicizza i file dai path consentiti
  (`Tenant.fs_scan_allowed_paths` / `Project.fs_scan_paths`); **`/dam/api/fs-import`**
  registra gli `Asset` selezionati con `file_path` = riferimento al path reale,
  **senza copiare** il binario (resta sul NAS/server del tenant).
- `Project.storage_backend` / `storage_root` / `s3_bucket` astraggono la sorgente.

Roadmap: integrazione con **sistemi MAM** e/o **AWS S3 / S3-compatibili** (le vars
`AWS_*` esistono già in config) → recupero/stream del binario on-demand senza
ospitarlo nel SaaS. L'upload diretto resta possibile ma è la via secondaria.

## On-prem ≠ esposto: doppio uso
Questo stesso setup è la base del **deployment-per-tenant** per clienti con requisiti
di sicurezza straordinari: ognuno la propria istanza on-premise, dato che non lascia
mai i loro server.
