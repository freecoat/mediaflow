# Deliverable orfani — fix causa + cleanup + ghost-link — Design

> Spec. 4 giugno 2026. Target: v3.5.0-alpha.172.192. Anomalia: deliverable orfani non devono esistere.

## Problema (diagnosi confermata)

Job GLO-J007 (quote v4 id=18): 82 JobDeliverable attivi = 62 legati a righe v4 + **20 orfani con `quote_line_id` NULL**. Due batch (31 mag, 3 giu), diversi duplicati per nome.

3 cause radice:
- **RC1 — `migrate_job` (primario)** `app/routers/quotes.py:4043-4048`: quando una riga V_old non è più in V_new, con `orphan_strategy="keep_as_extra"` fa **soft-detach** `d.quote_line_id = None` invece di rimuovere. Il deliverable resta orfano; a ogni migrazione versione se ne accumulano altri. (I duplicati per-nome sono il coesistere di vecchi-detached + nuovi-v4 con stessa descrizione.)
- **RC2 — pre-restructure**: `quote_line_id` aggiunto α.172.2 (20 mag); deliverable creati prima + backfill parziale → NULL permanenti. `migrate_job` li **salta** del tutto (né rebind né orphan-branch, che richiedono `quote_line_id` truthy).
- **RC3 — `jobs.py:create_deliverable`** (`POST /api/{job_id}/deliverables`, "Aggiungi consegna" manuale): non setta mai `quote_line_id` → orfano by-design.

## Decisioni (Matteo)
- Riga rimossa nella nuova versione → il suo deliverable va in **SOFT-DELETE** (cestino), non detached-NULL, non duplicato.
- Deliverable **manuali**: restano leciti, ma aggiungiamo una **funzione per collegarli a una ghost quote** (phantom Consuntivo) così diventano tracciabili.

## Componenti

### Fix 1 — `migrate_job`: orphan branch → soft-delete guardato (RC1)

`app/routers/quotes.py:4043-4048`. Sostituire il soft-detach con soft-delete **guardato** (non si può cancellare un deliverable con impegni a valle):

```python
elif d.quote_line_id:
    # Riga V_old non più in V_new → il deliverable non ha più una riga di quote.
    # Soft-delete se "pulito"; se ha impegni a valle (booking/confermato/fatturato)
    # NON si tocca (resta legato alla vecchia riga, segnalato come residuo).
    if _deliverable_safe_to_remove(db, d):
        d.deleted_at = now_utc()
        d.deleted_by_user_id = None  # azione di sistema (migrazione)
        deliverables_orphaned += 1   # riusa il contatore (semantica: rimossi)
    else:
        deliverables_kept_locked += 1  # nuovo contatore: non rimovibili
```

`_deliverable_safe_to_remove(db, d)` (nuovo helper, modulo `quotes.py` o `soft_delete`): True se `billing_status == not_billed` AND `confirmed_at is None` AND `quantity_delivered in (0, None)` AND nessun `BookingDeliverable` attivo che lo lega. (Riusa la stessa logica di guardia di `_respawn_line_artifacts`; estrarla in un helper condiviso se duplicata.)

Effetto: niente più orfani-da-migrazione; niente duplicati (la riga rimossa sparisce, le righe V_new hanno il loro deliverable rebound/creato). I deliverable con impegni restano (non si distruggono asset/fatture) ma sono pochi e tracciati.

NOTA: il ramo `d.quote_line_id is None` (RC2/RC3, manuali o pre-restructure) resta **non toccato** da migrate_job (potrebbero essere extra manuali legittimi). Gestiti da Fix 2 (cleanup una tantum) + Fix 3 (ghost-link).

### Fix 2 — cleanup una tantum dei 20 orfani GLO (dati)

Script `scripts/cleanup_orphan_deliverables.py` (riusabile, parametrico per job o tenant):
1. Snapshot DB (`db_snapshots/`) PRIMA.
2. Seleziona `JobDeliverable` con `quote_line_id IS NULL AND deleted_at IS NULL` del job (o tenant), **guardati** da `_deliverable_safe_to_remove` (no booking/confermato/fatturato).
3. Verifica `booking_deliverables` count = 0 per ciascuno; quelli con booking → NON cancellati, elencati per intervento manuale.
4. Soft-delete dei sicuri. Stampa report (quanti rimossi, quali tenuti).

Eseguito su GLO (job 1): atteso ~20 rimossi (tutti planned/not_billed/qty0). Reversibile (cestino).

### Fix 3 — funzione "collega a ghost quote" (RC3)

Capability + endpoint per attaccare un deliverable orfano (`quote_line_id` NULL) a una **phantom/ghost quote** (Consuntivo, `is_phantom=True`, `phantom_status=standby`) del progetto:
- Riusa il pattern `_get_or_create_phantom(project)` già esistente (vedi `batch_delete_quote_lines` α.172.18).
- Crea una `QuoteLine` sulla phantom (descrizione/unit/price dal deliverable) e setta `deliverable.quote_line_id = nuova_riga.id`.
- Endpoint `POST /jobs/api/deliverables/{id}/link-ghost` (RBAC edit). Ritorna `{ok, quote_id (phantom), quote_line_id}`.
- (UI: bottone nel dettaglio deliverable del planning — opzionale, follow-up.)
Così un deliverable manuale diventa tracciabile a una quote (phantom) → niente "orfano vero".

Inoltre, opzionale: `create_deliverable` (jobs.py:826) accetta `quote_line_id` opzionale (per chi vuole linkare subito). Non obbligatorio.

## Test (pytest)
- **Fix 1**: migrate_job con una riga droppata in V_new → il deliverable della riga droppata risulta `deleted_at` non-null (soft-deleted), NON duplicato, e le righe V_new hanno 1 deliverable ciascuna. Caso "droppata ma con booking" → NON cancellato (kept_locked).
- **Fix 1 regressione**: migrate_job standard (nessuna riga droppata) → rebind invariato, nessun soft-delete.
- **Fix 2**: cleanup script su un job seeded con N orfani NULL puliti + 1 orfano con booking → rimuove gli N, tiene quello con booking.
- **Fix 3**: link-ghost su deliverable NULL → crea/riusa phantom, setta quote_line_id, il deliverable non è più orfano; idempotente (riusa la stessa phantom).

## Invariante risultante
Ogni `JobDeliverable` attivo: o **(a)** linkato a una riga di quote (versione corrente del job, via migrate rebind) o **(b)** linkato a una riga di **phantom/ghost quote** (extra manuali via Fix 3). Nessun deliverable attivo con `quote_line_id` NULL non intenzionale. migrate_job non lascia più residui.

## Non-goal
- UI del bottone ghost-link (follow-up; per ora endpoint + cleanup).
- Backfill automatico di TUTTI gli orfani storici di tutti i tenant (lo script è parametrico, si lancia quando serve).
- Distinzione automatica "manuale vs bug" per i NULL pre-esistenti (non c'è flag storico; il cleanup è guardato + reversibile).

## Versioning
Bump α.172.192. CHANGELOG + STATO. Snapshot pre-cleanup. Commit a feature completa + test verdi. Export ZIP + push.
