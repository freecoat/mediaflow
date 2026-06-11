# Design — F3 Preview QC (asset registry MAM)

**Data**: 2026-06-11 · **Versione target**: v3.5.0-alpha.172.213 · **Approvato da**: Matteo (remote, AskUserQuestion)

## Contesto

F1/F2: asset metadata-only, master in facility, agent outbound-only. Il QC oggi si fa
senza vedere il contenuto: il modal QC (job_detail, event-sourced Stack 2) logga errori
per timecode ma l'operatore deve guardare il file altrove. F3 porta un **proxy di preview**
generato in facility dentro la scheda QC.

Decisioni Matteo: storage server locale + S3 opzionale · proxy 1080p alta qualità +
TC burn-in + watermark · trigger manuale + auto su conferma (flag per-volume) ·
player SOLO nel modal QC job_detail.

## Flusso

1. **Trigger** (uno dei due):
   - Bottone "🎬 Genera preview" nel modal QC (deliverable con `digital_asset_id`).
   - Auto: conferma proposta con link deliverable, se `StorageVolume.auto_preview=True`.
   Entrambi → helper unico `enqueue_preview(db, asset, requested_by)` → `AgentJob type=preview`
   payload `{volume_id, rel_path, asset_id, upload: {...}}`. Idempotente: no doppio job
   queued/claimed per lo stesso asset; rigenerazione consentita se ready/failed.
2. **Agent** (`agent/preview.py`): ffmpeg →
   - video: `scale=-2:1080`, libx264 CRF 20 preset medium, max ~6 Mbps
   - audio: AAC stereo 192k (downmix)
   - `drawtext` timecode burn-in alto-centro (TC iniziale da ffprobe `timecode` tag,
     fallback `00:00:00:00`; rate dal frame rate probed)
   - `drawtext` watermark diagonale semitrasparente "PREVIEW — QC ONLY — {tenant}"
   - output `.mp4` temp, `+faststart`
   - ffmpeg assente → job failed con messaggio chiaro.
3. **Upload** (deciso dal server nel payload del job):
   - **S3 configurato** (`.env`: `PREVIEW_S3_BUCKET`, `PREVIEW_S3_REGION`,
     `PREVIEW_S3_ACCESS_KEY`, `PREVIEW_S3_SECRET_KEY`, opz. `PREVIEW_S3_ENDPOINT`):
     il server mette nel payload un **presigned PUT URL** → agent carica diretto su S3.
   - **Senza S3**: agent streama il file raw al server
     `PUT /agent-api/jobs/{job_id}/preview-upload` (auth X-Agent-Token, streaming
     `request.stream()` su disco, cap `PREVIEW_MAX_GB` default 20).
   - Server salva in `uploads/previews/{tenant_id}/{asset_id}.mp4` (local).
4. **Esito**: result del job → `Asset.preview_status=ready`, `preview_path`,
   `preview_storage` (local|s3), `preview_generated_at`. Failed → `preview_status=failed`
   + `preview_error`.
5. **Player** (modal QC in job_detail):
   - `<video controls>` sopra il log eventi; src `GET /storage/api/assets/{id}/preview`.
   - Local: `FileResponse` con supporto Range (scrub). S3: 302 redirect a presigned GET (15 min).
   - Stato: none → bottone Genera; queued/generating → spinner + poll; failed → errore + Rigenera;
     ready → player + Rigenera.
   - **Bottone "📍 TC"** accanto al campo timecode del form errori: `currentTime` del player
     + TC iniziale (dal result del job: `start_tc`, `fps`) → stringa TC `HH:MM:SS:FF` nel campo.

## Modello (auto-migrate al boot)

- `Asset` += `preview_status` (String, default `none`), `preview_path` (nullable),
  `preview_storage` (nullable), `preview_error` (nullable), `preview_generated_at` (nullable).
- `StorageVolume` += `auto_preview` (bool default False) + checkbox nei modal volume UI.

## Sicurezza

- `GET /assets/{id}/preview`: stesso gate RBAC degli endpoint QC del job (utente loggato
  con permesso di vedere il job detail), tenant-scoped.
- `PUT /preview-upload`: solo l'agent che ha claimato il job, job type=preview, tenant match,
  cap dimensione, scrittura atomica (tmp + rename).
- Presigned URL: scadenza breve (PUT 1h, GET 15 min). Niente credenziali S3 all'agent.
- Path preview costruito server-side (mai dal client/agent).

## Test (TDD)

- Builder comando ffmpeg: scala/CRF/TC/watermark/fallback TC, escaping drawtext.
- `enqueue_preview`: idempotenza, payload upload local vs s3 (mock config).
- Upload streaming: file scritto, cap superato → 413, agent sbagliato → 404/403.
- Esito job: asset aggiornato ready/failed.
- Player endpoint: 200 Range local, 302 s3, 404 senza preview, RBAC.
- Auto-trigger: confirm con volume.auto_preview → job accodato (desktop e mobile).
- E2E (`tools/_e2e_f3.py`): round-trip con ffmpeg reale su clip sintetica
  (`ffmpeg -f lavfi -i testsrc`) se ffmpeg presente, altrimenti skip con mock.

## Fuori scope v1

HLS/DASH, thumbnails scrub, player su /storage proposte / DAM / mobile, preview batch
per-episodio, retention/purge automatica preview, transcode hardware.
