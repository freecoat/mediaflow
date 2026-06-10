# F1 — Asset Registry metadata-only + Claqo Agent — E2E checklist

> Eseguita il 10 giugno 2026 (v3.5.0-alpha.172.210). Server `:8000` locale + agent in-process.

## A. Loop integrazione server ↔ agent (`tools/_e2e_f1.py`) — 18/18 ✅

Script guida il pacchetto `agent/` attraverso gli endpoint HTTP reali `/agent-api`
(auth `X-Agent-Token`) contro il server live. Nessun byte di contenuto transita.

| Check | Esito |
|---|---|
| tenant 1 / user esistono | OK |
| `POST /agent-api/heartbeat` → 200 + ritorna volumi del tenant | OK |
| token invalido → 401 | OK |
| `POST /agent-api/jobs/claim` → ritorna il job probe (FIFO) | OK |
| probe locale: checksum xxh64 (16 char) + file_size reale | OK |
| `POST /agent-api/jobs/{id}/result` done → crea proposta Asset | OK |
| proposta `proposed_state = pending_review` | OK |
| checksum / `file_path = agent://{vol}/{rel}` / rel_path / storage_volume_id | OK |
| dedup: ri-probe stesso checksum+volume → stesso asset_id | OK |

ffprobe non in PATH sulla macchina di test → `tech_specs.tool = "none"` (gestito gentile),
checksum + size comunque corretti. Su una facility con ffprobe le specs si popolano.

## B. Browser smoke (`/storage`, login admin) ✅

| Check | Esito |
|---|---|
| `/storage` senza login → redirect `/auth/login` | OK (gated) |
| login admin → pagina render, titolo "Storage — Claqo" | OK |
| 4 tab (📥 Proposte / 💾 Volumi / 🤖 Agent / 📋 Job) + switching | OK |
| tab Proposte: empty state "Nessuna proposta in attesa di revisione." | OK |
| tab Volumi: "+ Volume" → modal completo (nome/mount/watch CSV/RO) | OK |
| crea volume via UI → POST + reload + riga con badge RO + watch dirs | OK |
| console JS errori (escluso i 422 attesi sotto) | 0 |

## C. Guard upload contenuti media (`/dam/api/assets/upload`) ✅

Fetch nel contesto browser autenticato:

| File | Atteso | Esito |
|---|---|---|
| `master_v3.mov` (video/quicktime) | 422 blocco | 422 ✅ |
| `mix_51.wav` (audio/wav) | 422 blocco | 422 ✅ |
| `capitolato.pdf` (application/pdf) | 200 upload ok | 200 ✅ |

Messaggio 422: *"File di contenuto media: vietato l'upload sul server. Registralo via agent dalla pagina Storage (metadata-only)."*

## Bug trovati e fixati durante l'E2E

1. **`/agent-api` dirottato a login** (E2E A) — il middleware `auth_guard` globale
   rispondeva 303 → `/auth/login` su ogni chiamata agent. L'agent autentica via
   `X-Agent-Token`, non ha cookie JWT. Fix: `/agent-api/` in `PUBLIC_PATHS`
   (`app/main.py`). Commit `4d53728`.
2. **`list_proposals` 500** (browser B) — filtrava `Asset.is_active` (inesistente;
   Asset usa `status`). Fix: rimosso il filtro (pending_review già attivo).
   Commit `e67543f`.
3. **`nav.storage` non tradotto** — chiave i18n mancante → sidebar mostrava la chiave
   grezza. Fix: aggiunta a `i18n.js` (it/en/fr/de). Si applica col bump `?v=`.
   Commit `e67543f`.

## Note operative
- Snapshot DB pre-test: non necessario (operazioni additive + cleanup). Artefatti
  smoke (volume "SAN-01 Smoke" + asset pdf di test) rimossi a fine giro.
- `tools/_e2e_f1.py` ripetibile: pulisce i propri artefatti; in caso di run interrotto,
  drenare i job `queued` residui prima di rieseguire.

## Backlog (non bloccante F1, → F2)
- Upload guard usa filename/mime indovinato, non i byte reali (security review MEDIUM):
  rinominare `.mov`→`.pdf` bypassa. Cap 200 MB mitiga. Sniff byte (libmagic) se mai
  servirà hardening.
- Dedup proposta non filtra `proposed_state`: un asset `discarded` con stesso
  checksum+volume verrebbe ritornato al re-probe. Innocuo per F1.
