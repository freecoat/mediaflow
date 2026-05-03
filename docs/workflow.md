# MediaFlow — Workflow chart

> Diagrammi di flusso. Mermaid renderizza nativamente in GitHub e in molti viewer markdown.
> Per export PNG/SVG: `npx -p @mermaid-js/mermaid-cli mmdc -i docs/workflow.md -o docs/workflow.svg`.
>
> Aggiornato a v3.4.56 (3 maggio 2026).

---

## 1. Lifecycle Quote

```mermaid
stateDiagram-v2
    [*] --> draft: create_quote (manuale o AI)
    draft --> sent: PUT /api/{id}/status
    sent --> approved: PUT /api/{id}/status (manuale)
    draft --> approved: promote-line-to-cost-line\n(reverse-flow implicit)
    sent --> approved: promote-line-to-cost-line\n(reverse-flow implicit)
    approved --> superseded: new_version_quote\n(versioning v3.4.39)
    sent --> rejected: PUT /api/{id}/status
    draft --> rejected: PUT /api/{id}/status
    approved --> draft: PUT /api/{id}/status\n(BLOCK se job ha attività)
    approved --> sent: PUT /api/{id}/status\n(BLOCK se job ha attività)
    rejected --> [*]
    superseded --> [*]

    note right of approved
        Side-effect: _create_job_from_quote()
        - Crea Job + JobCostLine da QuoteLines
        - Se non ci sono assignment risorse →
          notify quote_approved_no_resources
          ai producer/manager (non bloccante)
    end note

    note right of draft
        is_phantom=true se generata da
        booking reverse senza quote pre-esistente
        (create_phantom_quote_with_line)
    end note
```

---

## 2. Lifecycle Booking

```mermaid
stateDiagram-v2
    [*] --> tentative: POST /api/bookings\n(default kind=project)
    tentative --> confirmed: PUT /api/bookings/{id}/status
    confirmed --> in_progress: operatore "▶ Inizia"
    in_progress --> done: operatore "✓ Fatto"
    in_progress --> not_done: operatore "✗ Non fatto"\n(richiede motivazione)
    confirmed --> done: operatore "✓ Fatto" (skip in_progress)
    confirmed --> not_done: operatore "✗ Non fatto"

    tentative --> cancelled: DELETE
    confirmed --> cancelled: DELETE
    done --> [*]
    not_done --> [*]
    cancelled --> [*]

    note right of done
        Side-effect: cost_line_sync.recompute_for_booking()
        - Aggrega man-hours da assignments
        - Converte in qty (day/hour/altro)
        - Aggiorna JobCostLine.quantity_actual
          + total_accrued
    end note

    note right of in_progress
        Se booking esteso oltre original_end_datetime
        e WorkingHoursPolicy.overtime_brackets:
        - overtime_status: none → pending → approved/rejected
        - notify booking_overtime_pending agli approvatori
    end note
```

---

## 3. Flusso Booking → Job (forward + reverse + phantom)

```mermaid
flowchart TD
    Start([Producer crea booking]) --> PickProject[Sceglie progetto]
    PickProject --> PickQuote[Sceglie quotazione del progetto<br/>filtro: draft sent approved]
    PickQuote --> HasQuote{Quote disponibile?}

    HasQuote -->|no| OpenPhantom[CTA: Genera phantom quote<br/>+ price_item + qty da booking_hours]
    OpenPhantom --> CreatePhantom[create_phantom_quote_with_line<br/>Quote.is_phantom=true status=approved]
    CreatePhantom --> CreateJob[_create_job_from_quote<br/>Job + JobCostLines]
    CreateJob --> NotifyAM[notify_permission edit_quotes<br/>quote_reverse_approval]

    HasQuote -->|sì| PickLine[Sceglie lavorazione<br/>filtro: dept delle risorse]
    PickLine --> LineKind{Kind?}

    LineKind -->|cost_line approved| UseExisting[Usa job_cost_line_id esistente]
    LineKind -->|quote_line draft sent| Promote[POST promote-line-to-cost-line<br/>approva implicit + Job + JobCostLine]
    Promote --> NotifyAM

    UseExisting --> CovCheck[GET resource-coverage<br/>verifica risorse vs JobResourceAssignment]
    NotifyAM --> CovCheck
    CreateJob --> CovCheck

    CovCheck --> Missing{Risorse mancanti?}
    Missing -->|sì| Confirm[Confirm dialog:<br/>aggiungo risorse al progetto?]
    Confirm -->|no| Abort([Annulla])
    Confirm -->|sì| SaveBooking
    Missing -->|no| SaveBooking[POST /planning/api/bookings]

    SaveBooking --> AutoAssign[Hook auto-assignment<br/>ensure_resources_assigned_to_job]
    AutoAssign --> Done([Booking creato + assignment garantito])

    style CreatePhantom fill:#6272f5,color:#fff
    style Promote fill:#f59e0b,color:#fff
    style NotifyAM fill:#fbbf24
    style AutoAssign fill:#22c55e,color:#fff
    style Abort fill:#ef4444,color:#fff
```

---

## 4. Cost report — fonti del Maturato

```mermaid
flowchart LR
    subgraph Forward
        Q[Quote approved] -->|create_job_from_quote| J[Job]
        Q -->|copia QuoteLine| JCL[JobCostLine\nquantity_quoted, unit_price]
    end

    subgraph Esecuzione
        B[Booking] -->|job_cost_line_id| JCL
        B -->|status=done| Sync[cost_line_sync.recompute]
        Sync -->|sum man-hours assignments| QH[total_hours]
        QH -->|/8 se day, 1:1 se hour| QA[JobCostLine.quantity_actual]
        QA -->|× unit_price| TA[JobCostLine.total_accrued]
    end

    subgraph Override
        Admin[admin/manager/accounting<br/>permesso edit_cost_actuals] -.->|PUT /jobs/.../cost-lines| QA
    end

    subgraph CostReport
        TA --> CR[Cost report]
        JCL --> CR
        Hardcost[Expenses + hardcosts] --> CR
    end

    style B fill:#6272f5,color:#fff
    style QA fill:#22c55e,color:#fff
    style Admin fill:#fbbf24
```

---

## 5. Vincoli di integrità (HARD-BLOCK)

```mermaid
flowchart TD
    DelQL[DELETE QuoteLine] --> CheckQL{JobCostLine collegate<br/>con booking attivi?}
    CheckQL -->|sì| Block409a[409 Conflict<br/>elenco booking ostativi]
    CheckQL -->|no| OkDelQL[Cascade: cancella JobCostLine<br/>+ soft-detach TimePunch]

    DelJCL[DELETE JobCostLine] --> CheckJCL{Booking attivi sulla line?}
    CheckJCL -->|sì| Block409b[409 Conflict<br/>elenco booking ostativi]
    CheckJCL -->|no| IsExtra{is_extra=true?}
    IsExtra -->|no| Block400[400: solo extra eliminabili]
    IsExtra -->|sì| OkDelJCL[Cancella JobCostLine<br/>+ soft-detach TimePunch]

    EditQA[PUT JobCostLine quantity_actual] --> Perm{user ha edit_cost_actuals?}
    Perm -->|no| Block403[403: deriva dai booking done]
    Perm -->|sì| OkEditQA[Aggiorna manualmente<br/>override del sync]

    style Block409a fill:#ef4444,color:#fff
    style Block409b fill:#ef4444,color:#fff
    style Block400 fill:#ef4444,color:#fff
    style Block403 fill:#ef4444,color:#fff
```
