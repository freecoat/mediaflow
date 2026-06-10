# F2 — Watch + Match — E2E checklist

> Eseguita il 10 giugno 2026 (v3.5.0-alpha.172.211). Server `:8000` locale + agent in-process.

## A. Loop integrazione watch→match→conferma (`tools/_e2e_f2.py`) — 12/12 ✅

Guida il pacchetto `agent/` (scan_volume, 2 cicli per stabilità) + endpoint HTTP reali `/agent-api` contro il server live. Domain seed: progetto GOMORRA + JobDeliverable atteso (ProRes/HD1080/25, naming `GOMORRA_S03_EP01`).

| Check | Esito |
|---|---|
| watch ciclo 1 → nessun file stabile (no baseline) | OK |
| watch ciclo 2 → file size-stable rilevato | OK |
| heartbeat 200 + claim job `scan` | OK |
| post scan result `{items:[...]}` 200 | OK |
| proposta creata, `registered_via=agent_watch` | OK |
| rel_path corretto (`OUT/GOMORRA/...`) | OK |
| **match forte → `matched_deliverable_id` = deliverable atteso** | OK |
| conferma → `JobDeliverable.digital_asset_id` = asset | OK |
| conferma → `JobDeliverable.status = qc` | OK |

**Nota ffprobe**: la macchina di test non ha ffprobe → il probe reale del watch dà `tech_specs.tool='none'` (nessuna spec video) → il match sarebbe **debole** (solo naming). L'E2E **inietta** le specs realistiche (container/codec/risoluzione/fps) come le produrrebbe ffprobe in facility, per esercitare il match forte end-to-end. In facility con ffprobe il comportamento è quello testato.

## B. Browser smoke ✅

| Check | Esito |
|---|---|
| `/storage` tab Proposte: colonne **Match** + **Link deliverable** | OK |
| console JS errori | 0 |
| `/m/proposte` (PWA): render + nav "Storage › Proposte" + empty state | OK |
| console mobile errori | 0 |

(Badge match con dati + dropdown candidati + bottone "Scansiona" per-volume: logica provata dall'E2E backend + unit; render colonne verificato. Test manuale completo con dati live = Matteo.)

## Comportamento match (soglie)
- **Forte** = naming concorde + ≥2 specs tecniche concordi (o score ≥0.75) → `matched_deliverable_id` pre-collegato.
- **Debole** = 0.40..0.75 → candidati ordinati, nessun pre-link.
- **Zero** = <0.40 → proposta libera.
- Candidate set = JobDeliverable del progetto (da convenzione path `/OUT/{project_code}/`) con `digital_asset_id` NULL, status non delivered/closed, non cestinati.

## Bug colti durante l'E2E (nello script, non nel prodotto)
- Residuo F1 `OUT/P001/test.mov` raccolto dal watch → query proposta ambigua. Fix: rimosso + query per rel_path specifico.
- `projects.code` / lookup `(tenant_id,name)` UNIQUE → collisione su rerun. Fix: pre-clean idempotente + nomi lookup E2E-specifici.
- `UnicodeEncodeError` su `→` in console cp1252 Windows. Fix: `->` ASCII nei nomi check.

## Backlog F2 (→ fasi successive)
- Scheduler scan server-side ricorrente (v1 = scan-now on-demand + scan job su richiesta).
- Override `output_dir` per-progetto (oggi solo convenzione path).
- Auto-scarto proposte con file sparito prima della conferma.
- Persistenza candidati deboli (oggi ricalcolati on-read).
- Preview QC (F3), LTO/MHL (F4), TransferOrder (F5).
