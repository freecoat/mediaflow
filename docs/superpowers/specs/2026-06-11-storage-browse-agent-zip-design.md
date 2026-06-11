# Design — Browse storage via agent + pacchetto install agent ZIP

**Data**: 2026-06-11 · **Versione target**: v3.5.0-alpha.172.212 · **Approvato da**: Matteo (remote)

## Contesto

F1/F2 asset registry: il server è metadata-only, non vede la SAN. Oggi i percorsi
(`rel_path` per register-path, `watch_dirs` sui volumi) si digitano a mano — error-prone.
E l'installazione dell'agent richiede copia manuale del pacchetto + config a mano.

## Feature 1 — Browse storage via agent

Sfogliare le directory di un volume dalla UI `/storage`, tramite job round-trip sull'agent.

### Backend
- `AgentJobType.browse` (nuovo valore enum; colonna stringa → no migrazione DB).
- Agent `main.py`, ramo `browse`: `os.scandir(mount_path/rel_path)` →
  `{"rel_path": ..., "entries": [{"name", "is_dir", "size"}]}`.
  - Ordinamento: directory prima, poi file, alfabetico.
  - Cap 500 entry (+ flag `truncated`).
  - **Guard path-traversal**: path risolto deve restare dentro `mount_path` (realpath prefix check), altrimenti job failed.
- `POST /storage/api/volumes/{id}/browse` (Form `rel_path=""`) → enqueue job browse, ritorna `job_id`. RBAC `edit_planning_all` come il resto del router.
- `GET /storage/api/jobs/{id}` → stato+result del singolo job (per il poll UI). Tenant-scoped.

### UI (`storage.html`)
- Modal file-browser: breadcrumb cliccabile, lista cartelle/file, poll del job ogni 2s, timeout 30s ("Agent offline?").
- Punti di ingresso "📂 Sfoglia": modal register-path (campo rel_path), campi watch_dirs (nuovo/modifica volume — append della dir scelta alla lista CSV).
- "Usa questo percorso" → compila il campo di origine e chiude.

## Feature 2 — Pacchetto install agent ZIP

Scaricare da `/storage` uno ZIP pronto-all'uso con agent + config pre-compilata.

### Backend
- `POST /storage/api/agents/{id}/package` (RBAC come sopra). Form:
  - `server_url` (obbligatorio, prefill UI `window.location.origin`)
  - `token` (opzionale): se passato (flusso creazione, plain appena mostrato) lo usa;
    se assente → **rigenera** il token dell'agent (vecchio invalidato) e usa il nuovo.
- ZIP in-memory (zipfile + BytesIO), root `claqo-agent/`:
  - `agent/*.py` + `agent/requirements.txt` + `agent/README.md` (letti dal pacchetto repo, esclusi `__pycache__`)
  - `claqo-agent.json` → `{"server_url", "token", "poll_seconds": 5, "heartbeat_seconds": 30}`
  - `avvia-agent.bat` e `avvia-agent.sh`: creano `.venv` se assente, `pip install -r`, `python -m agent.main` dalla root del pacchetto.
- Response `application/zip`, filename `claqo-agent-{nome}.zip`.

### UI
- Modal creazione agent: accanto al token mostrato una volta, bottone "📦 Scarica ZIP pronto" (usa il token plain in memoria JS).
- Riga agent esistente: bottone "📦 ZIP" → confirm "Rigenera il token (il vecchio smette di funzionare). Continuare?" → download.

## Test (TDD)
- `browse` agent-side: listing ordinato, cap, traversal bloccato.
- Router: browse enqueue + job singolo GET (404 cross-tenant), package ZIP contiene file attesi + json corretto + token ruotato quando non passato.

## Fuori scope
- Browse ricorsivo/ricerca, multi-selezione, preview file (F3).
- Auto-update agent.
