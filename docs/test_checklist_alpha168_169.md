# Test checklist α.168 + α.169 — sessione 18 mag 2026

> Lista punto per punto da eseguire alla riapertura.
> Marcare ✅ / ❌ + note per ogni step.

---

## α.169 — UI / UX

### T1. Timeline planning — sticky axis + scroll interno
- [ ] `/planning` → tab Timeline
- [ ] Toolbar pagina (filtri/zoom/groupby) resta visibile durante scroll pagina
- [ ] Vedo tutte 40 risorse via scroll **interno** al widget timeline (rotella sopra widget)
- [ ] Axis data/ora resta **fisso in alto** durante scroll interno (stile header Excel)
- [ ] Badge `40 risorse` (no filtri) o `N/40 risorse (filtrate)` visibile in toolbar timeline accanto a 🪶 Light
- [ ] Light ON/OFF non incide su risorse visibili (< 100 totali, cap dormant)
- [ ] Filtro dept singolo → counter mostra `N/40 risorse (filtrate)` tint indigo
- [ ] Zoom giorno/settimana/mese/trimestre: axis sticky resta sempre sopra

### T2. Cost Report — refresh in dettaglio
- [ ] `/cost-report` → apri un job → bottone `🔄 Aggiorna` visibile a destra accanto a "+ Assegna risorsa"
- [ ] Click `🔄 Aggiorna` → toast verde "Report aggiornato"
- [ ] Posizione scroll preservata (non torna a inizio pagina)
- [ ] Numeri ricaricati (testa cambiando un booking in altra tab → refresh → numeri aggiornati senza uscire)

### T3. Anomalie — filtri cliente + progetto
- [ ] `/finance` → tab Anomalie
- [ ] Dropdown "Cliente" presente accanto a "Dipartimento", popolato (—tutti— + lista clienti)
- [ ] Dropdown "Progetto" presente, popolato
- [ ] Selezione cliente → lista filtra correttamente
- [ ] Selezione progetto → lista filtra correttamente
- [ ] Combinazione cliente + progetto + type funziona

---

## α.169 — Anomalie detector

### T4. Sforamento monetario (Bug 3b principale)
- [ ] Su un progetto, JCL "Production Management" (o altra non-extra): forza scenario over via batch
- [ ] Trasmetti a fatturazione → manager alza `total_approved` oltre `total_quoted` → approva → emetti fattura
- [ ] Senza premere "Rileva" manualmente: ricarica `/finance` Anomalie
- [ ] Anomalia `sforamento_monte_ore` su JCL Production Management presente
- [ ] Amount = (billed o accrued) − quoted (in €)
- [ ] Descrizione cita "fatturato €X > quotato €Y" o "maturato €X > quotato €Y"

### T5. Extra puro fatturato (Bug 3b complementare)
- [ ] Cerca JCL `[EXTRA] ...` con quantity=0 ma billed_amount > 0 (es. JCL #66 [EXTRA] Production Management)
- [ ] Apri `/finance` Anomalie → tipo "➕ Extra puri"
- [ ] JCL #66 (o equivalente) presente con amount = billed
- [ ] Descrizione cita "fatturato €X senza quantità maturata (forzato in batch)"

### T6. Auto-trigger detect dopo emit_invoice
- [ ] Trasmetti un batch nuovo + approva + emetti fattura
- [ ] Senza azioni extra, controlla anomalie: nuove sforamento/over_budget appaiono
- [ ] Toast emit_invoice arriva, nessun errore (try/except non blocking)

---

## α.168 — Vasi comunicanti billing (Bug 2+4)

### T7. Transmit preview — saturate escluse
- [ ] Progetto con acconto pagato → JCL coperte 100% (= accrued ≤ already_filled)
- [ ] `/cost-report#job-X` → bottone Trasmetti
- [ ] Modal preview: count `saturated_excluded` mostrato nel banner esclusioni (`N saturate (acconto/slice copre 100%)`)
- [ ] JCL saturate NON appaiono nella tabella checkbox
- [ ] JCL parzialmente coperte: appaiono CON badge `💧 Già coperto €X`
- [ ] Colonna "Maturato" mostra **billable_now** (residuo da fatturare), non accrued totale
- [ ] Subtotale = somma billable_now selezionate

### T8. Transmit batch — default total_approved = billable_now
- [ ] Trasmetti effettivamente un batch dal modal sopra
- [ ] Apri `/finance` → batch creato → verifica righe
- [ ] Ogni line: `total_proposed = total_approved = billable_now` (residuo, NON quoted intero per UNDER)
- [ ] Esempio numerico: JCL accrued=12000, quoted=10000, già fatturato 4000 → billable_now=8000, approved=8000

### T9. JCL billed/paid trasmissibile per supplementi
- [ ] JCL già `billed` con accrued aumentato (booking aggiunti post-fattura) → billable_now>0
- [ ] Trasmetti → JCL inclusa, status rimane `billed` (non torna in_batch)
- [ ] Batch raccoglie quota supplementare

---

## α.168 — Auto-numero fattura (Bug 3)

### T10. Numero auto su 4 modal
- [ ] Modal "Nuova fattura" (`/finance` → Fatture → +Nuova): campo Numero vuoto + placeholder "auto…"
- [ ] Compila senza numero → fattura creata con `2026-NNNNN` progressivo
- [ ] Modal "Emetti fattura da batch": campo vuoto → auto, compilato → override manuale rispettato
- [ ] Modal "Componi fattura" (compose-invoice): stesso
- [ ] Modal "Chiusura progetto" (closing-invoice): stesso
- [ ] Override manuale: digitare numero esistente → 409 "già esistente"
- [ ] Override manuale: digitare numero nuovo → usato as-is

### T11. Numerazione tenant-scoped + anno-rotation
- [ ] Verifica che numero parta da `{anno_emissione}-00001`
- [ ] Cambia issue_date al 2027 → nuovo auto: `2027-00001`
- [ ] No collisioni con fatture esistenti

---

## α.169 — Fattura InvoiceLine quantity (Bug 4)

### T12. Quantity coerente con total
- [ ] Trasmetti JCL con `total_quoted=1000, total_accrued=1200, unit_price=100`
- [ ] In batch: manager mantiene `total_approved=1200` (over)
- [ ] Approva + emetti fattura
- [ ] Apri PDF fattura o `/finance` Fatture → riga: quantity=**12** (= 1200/100), prezzo=100, totale=1200
- [ ] Pre-α.169 mostrava qty=ore totali lavorate (poteva essere 12 o 15 a seconda del maturato totale)

### T13. Caso under
- [ ] JCL accrued=800, quoted=1000, manager non modifica → approved=800
- [ ] Fattura: quantity=8, prezzo=100, totale=800 (= billable_now)

### T14. Extra puro
- [ ] JCL extra con unit_price=100, qty quoted/actual=0, manager forza approved=500
- [ ] Fattura: quantity=5 (= 500/100), prezzo=100, totale=500

### T15. JCLBilledSlice billed_quantity sync
- [ ] Verifica via DB: `jcl_billed_slices.billed_quantity` per la fattura emessa = stessa quantità InvoiceLine (non quantity_actual)

---

## Regressioni da verificare

### R1. PDF cliente cost-report
- [ ] Export PDF cliente con job parzialmente fatturato: numeri coerenti

### R2. Cashflow
- [ ] Cashflow non rotto da nuovi auto-numeri o quantity recompute

### R3. SDI XML / FatturaPA
- [ ] Endpoint sdi-xml su fattura nuova: line.quantity coerente con XML

### R4. Reverse-flow Quote→Job
- [ ] Job nato da quote nuova: prima trasmissione su billable_now = accrued (no slice precedenti)

### R5. Storno NC TD04
- [ ] Storno fattura emessa α.169: quantity in NC coerente con originale

---

## Note operative

- Eseguire test in ordine T1→T15 per coprire UI prima, logica detector seconda, billing flow ultima.
- Per T7-T9 serve un progetto con AdvancePayment **pagato** (invoice.amount_paid > 0). Se manca nel DB, creare advance + segnare paid via UI.
- Per T4 serve manager con permessi finance per modificare batch.total_approved.
- Tempo stimato: 60-90 min sequenziale, 30 min "happy path" minimo.

---

*Creato 18 mag 2026 a chiusura sessione α.168+α.169 (commit `7f30015`).*
