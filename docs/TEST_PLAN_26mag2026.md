# Test Plan — 26 maggio 2026

Versione corrente: **v3.5.0-alpha.172.92**.
Maratona 25 mag chiusa: 4 bundle implementati (I → J → H2 → H3), 4 commit pushati + 1 export ZIP DB.

Restart server **prima di tutto** per attivare:
- Auto-migrate Bundle I (legacy enum → 5 main + qc_substatus + Asset.status)
- 526 routes finali (+5 vs α.172.88)

```
python run.py
```

Verifica console boot. Cerca:
```
[auto-migrate-bundle-i] job_deliverables.qc_substatus -> ALTER
[auto-migrate-bundle-i] assets.status -> ALTER
[auto-migrate-bundle-i] Nx deliverable.status in_production -> in_progress
[auto-migrate-bundle-i] Nx asset.status planned -> uploaded
```

Se non vedi log = colonne già presenti (DB già migrato in dev → OK skip).

---

## FASE A — Bundle I (stati nested + cascade QC)

### A1. Boot migrate
- [ ] Log `[auto-migrate-bundle-i]` visibile o "gia' presente"
- [ ] Server avviato pulito su `:8000`
- [ ] `/health` ritorna 200 con `version: 3.5.0-alpha.172.92`

### A2. UI cost report — badge stato nested
1. Apri `/cost-report` di progetto con deliverable
2. Verifica colonna "Stato" mostra badge 5 valori (planned/in_progress/qc/delivered/closed)
3. Se deliverable era `qc_failed` legacy → ora `qc + qc_substatus=rejected` (badge giallo + sub-badge rosso "reject")

### A3. Workflow lineare stato
1. Crea deliverable nuovo (status=planned)
2. Click `▶` → status=in_progress
3. Click `🔍` → status=qc + qc_substatus=in_progress (sub-badge "in corso")
4. Click `✓` → status=qc + qc_substatus=passed (sub-badge verde "pass")
5. Click `📤` → status=delivered (verde)
6. Click `🔒` → conferma → status=closed (viola, lucchetto)
7. Prova update da closed via API → atteso 409

### A4. Cascade QC reject
1. Carica un asset al deliverable (es. via /dam)
2. Riporta deliverable in stato `qc + in_progress`
3. Click `✗ Reject` con motivazione "Test cascade reject"
4. Verifica toast: "✗ QC reject applicato — N asset rejected · N placeholder · N notifiche"
5. Deliverable torna a status=planned (badge grigio)
6. Apri `/dam` → asset principale ora ha badge "Rifiutato (QC)" rosso
7. Nuovo asset placeholder visibile con stessa filename "(re-run QC)" e versione+1
8. Apri drawer notifiche → notifica `deliverable_qc_rejected` ricevuta da utente view_finance

### A5. Upload QC report PDF + AI summary
1. Su deliverable in QC, click `📎`
2. Seleziona qualsiasi PDF QC test (anche fittizio)
3. Toast: "📎 QC report caricato (asset #N)"
4. Dopo ~5s → toast: "🤖 QC AI: PASS/REJECT — suggerito qc_substatus='...'"
5. Verifica asset QC linkato in /dam con `source='qc_report'`
6. DeliverableAsset.notes contiene summary AI estratto

### A6. Hook booking→deliverable auto-bump
1. Booking linkato a deliverable status=planned
2. Cambia execution_status booking a `in_progress`
3. Refresh cost report
4. Deliverable status automaticamente `in_progress`
5. Audit log mostra `deliverable_auto_bump`
6. Ripeti: cambio booking done → planned → nessun re-bump (idempotente)

---

## FASE B — Bundle J (Planning HUB Deliverable)

### B1. Tab Deliverable in /planning
1. Apri `/planning`
2. Click tab `📦 Deliverable` (ultimo a destra)
3. Vista kanban 5 colonne con count corretto per status

### B2. Drag&drop tra colonne
1. Drag card da Pianificato → In lavorazione
2. Verifica toast OK + refresh kanban
3. Drag → QC: auto qc_substatus=in_progress
4. Drag → Closed: conferma confirm() prima
5. Drag su stessa colonna = no-op (no toast)

### B3. Toggle Kanban/Lista
1. Cambia dropdown da Kanban a Lista
2. Tabella con colonne Nome/Progetto/Job/Stato/QC sub/Unit/Qty/Target
3. Click riga apre stesso modal

### B4. Modal tech specs 8 blocchi
1. Click card kanban
2. Modal `#modal-deliverable-specs` con 8 textarea
3. Se spec_json vuoto → textarea vuote con placeholder
4. Edit JSON in textarea → verifica validazione real-time

### B5. Pre-fill da template
1. Dropdown `DeliveryTemplate` mostra template attivi
2. Seleziona template + click `📋 Applica`
3. Toast "📋 N blocchi precompilati da {code}"
4. Solo blocchi VUOTI riempiti (preserva edit utente)

### B6. AI propose_specs
1. Seleziona template + click `🤖 AI`
2. Toast "🤖 AI sta proponendo le specifiche…"
3. Dopo ~10s → toast "🤖 AI ha proposto N blocchi · revisiona e Salva"
4. Tutti i blocchi popolati con proposta adattata al deliverable
5. Es: template UHD generico + deliverable "DCP IT" → spec mostra JPEG2000+DCI 2K+24fps

### B7. Save + validazione
1. Edit blocco con JSON malformato (es. virgola finale)
2. Click 💾 Salva → toast errore: "Blocco 'X' non e' JSON valido: ..."
3. Correggi JSON → click Salva → toast "💾 Specifiche salvate"
4. Riapri modal → spec_json persistito

---

## FASE C — Bundle H2 (Jobs page READ-ONLY)

### C1. Allineamento enum kanban
1. Apri `/jobs/{id}` di un job con deliverable
2. Sezione Consegne → toggle Kanban
3. Kanban 5 colonne (era 4 legacy)
4. Card rispettano nuovi colori (grigio/indigo/amber/verde/viola)
5. Sub-badge QC visibile se status=qc + substatus

### C2. Click card → modal read-only
1. Click card kanban o riga lista deliverable
2. Modal `#modal-jd-specs` apre
3. Banner top "🔒 Read-only" con link `/planning → 📦 Deliverable`
4. Meta-row: status badge + sub QC + qty + target_date
5. 8 cards una per blocco tech_specs in `<pre>` JSON pretty
6. Blocchi vuoti mostrano "— vuoto —"
7. NESSUNA textarea editabile (solo lettura)
8. Footer: Chiudi + bottone "✏ Modifica in /planning" (apre nuovo tab)

### C3. Status closed protetto
1. Deliverable closed → card mostra 🔒 al posto bottone elimina
2. Bottone "Conferma consegna" disabilitato/assente
3. Click card → modal read-only normale (visualizzazione OK)

### C4. Stop propagation
1. Click bottone "✓ Conferma" SU card → apre solo modal conferma (NON modal specs)
2. Click bottone "✕ Elimina" → confirm + delete (NON apre specs)
3. Click area card vuota → apre specs read-only

---

## FASE D — Bundle H3 (Asset Library metadata + delivery)

### D1. Modal asset detail
1. Apri `/dam`
2. Click su un asset (preferibilmente video MP4/MOV)
3. Modal `#modal-asset-detail` apre con:
   - Thumbnail/icona
   - Tabella base (Tipo/Dimensione/Caricato/Versione/Tag)
   - Sezione "📦 Delivery linked" (placeholder "Caricamento…")
   - Sezione "🎬 Specifiche tecniche file" (placeholder "Analisi file…")

### D2. Delivery linked
1. Asset linkato a deliverable → sezione Delivery popolata
2. Badge AssetStatus visibile (planned/uploaded/rejected/accepted)
3. Flag is_internal_archive / is_delivered_external se applicabili
4. Per ogni deliverable: badge main + sub-badge QC + nome + project/job + target_date
5. Link "✏ Modifica in /planning →" apre nuovo tab su Planning HUB

### D3. Metadata ffprobe
**Prerequisito**: `ffprobe` installato sul sistema (controllo `where ffprobe` su Win, `which` su Mac).

1. Asset video MP4 → sezione Specifiche tecniche popolata con:
   - Tool: ffprobe
   - Container: mp4 + durata + bitrate
   - Video: risoluzione + codec + framerate + pixel format
   - Audio 1: codec + canali + sample rate + bitrate + lingua

2. Asset immagine JPG → sezione popolata con:
   - Tool: ffprobe o pillow (fallback)
   - Video: width × height + codec=JPEG + pixel_format

3. Asset PDF → tool=none + errore "ffprobe rc=... non e' immagine"

### D4. Asset rejected post-cascade
1. Esegui FASE A4 (cascade QC reject)
2. Apri /dam → asset originale ora ha badge "Rifiutato (QC)" rosso
3. Modal asset → AssetStatus badge "Rifiutato (QC)"
4. Placeholder spawn visibile con parent_asset_id su asset originale
5. Modal placeholder → AssetStatus="Pianificato" + Delivery linked stesso deliverable

---

## FASE E — Test integrazione cross-bundle

### E1. Flow end-to-end completo
1. Crea quote con 1 line quantity=3, unit_nature=deliverable_qty → convert in job → 3 deliverable spawnati
2. Su /planning HUB → vedi 3 card identical in Pianificato
3. Rinomina ognuno via API (NB: necessita endpoint update name, già esistente)
4. Avanza primo a in_progress + QC + Pass
5. Upload asset principale + asset QC report PDF
6. AI propose_qc_report_summary → suggerisce qc_substatus
7. Reject QC → cascade asset rejected + placeholder + notifica
8. Verifica su /dam asset originale rejected + placeholder linkato
9. Apri /jobs/{job_id} → kanban allineato + modal read-only
10. Apri /cost-report → badge stati corretti + bottoni workflow

### E2. AI Tool-use end-to-end (via copilot drawer)
Apri qualunque pagina → drawer copilot → query:
- "Mostra deliverable del progetto Filmetto"
- "Propose tech specs per deliverable #N usando template A24"
- "Riepilogo QC report PDF asset #M"

Verifica capability invocate correttamente:
- `propose_deliverable_specs` (proposta + apply via UI dsmSave)
- `propose_qc_report_summary` (estrae pass/fail da PDF)

---

## Report richiesto

Al termine compila brevemente:
- ✅ / ❌ per ogni fase
- Bug osservati: descrizione + screenshot in `docs/Logs-temp/Screenshots/`
- Performance: lentezze su pagine grosse (planning HUB con N>100 deliverable, asset modal con video 4GB)
- Suggerimenti UX

Versioni proposte se servono fix:
- Bug critici → hotfix α.172.93+
- Polish UX → α.172.94+
