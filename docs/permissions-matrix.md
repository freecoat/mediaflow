# MediaFlow — Matrice permessi

> Generata da `app/services/rbac.py` (PRESET_PERMISSIONS).
> Fonte canonica: il codice. Questo doc è snapshot leggibile.
>
> Aggiornato a v3.4.56 (3 maggio 2026).

---

## Ruoli built-in

| Code         | Descrizione                                                      |
| ------------ | ---------------------------------------------------------------- |
| `admin`      | Amministratore di sistema — accesso completo                     |
| `manager`    | Manager / produzione esecutiva — full progetto + finanza, no impostazioni globali |
| `producer`   | Producer / project manager — full progetto, no editing listino, no fatture |
| `accounting` | Contabilità — finanza + fatturazione, no editing operativo       |
| `operator`   | Tecnico / risorsa — solo info tecniche progetti, propria pianificazione e timbrature |
| `viewer`     | Sola lettura — accesso in lettura ai dati operativi              |

---

## Matrice permesso × ruolo

Legenda: ● = consentito  ○ = no

### Anagrafica
| Permesso          | admin | manager | producer | accounting | operator | viewer |
|-------------------|:-----:|:-------:|:--------:|:----------:|:--------:|:------:|
| view_clients      |   ●   |    ●    |    ●     |     ●      |    ○     |   ●    |
| edit_clients      |   ●   |    ●    |    ○     |     ○      |    ○     |   ○    |
| view_projects     |   ●   |    ●    |    ●     |     ●      |    ●     |   ●    |
| edit_projects     |   ●   |    ●    |    ●     |     ○      |    ○     |   ○    |
| create_projects   |   ●   |    ●    |    ●     |     ○      |    ○     |   ○    |

### Pianificazione
| Permesso              | admin | manager | producer | accounting | operator | viewer |
|-----------------------|:-----:|:-------:|:--------:|:----------:|:--------:|:------:|
| view_planning         |   ●   |    ●    |    ●     |     ●      |    ●     |   ●    |
| edit_planning_own     |   ●   |    ●    |    ●     |     ○      |    ●     |   ○    |
| edit_planning_all     |   ●   |    ●    |    ●     |     ○      |    ○     |   ○    |
| assign_resources      |   ●   |    ●    |    ●     |     ○      |    ○     |   ○    |
| approve_overtime      |   ●   |    ●    |    ●     |     ○      |    ○     |   ○    |

### HR / Timbrature
| Permesso                | admin | manager | producer | accounting | operator | viewer |
|-------------------------|:-----:|:-------:|:--------:|:----------:|:--------:|:------:|
| view_punches_own        |   ●   |    ●    |    ●     |     ○      |    ●     |   ●    |
| view_punches_all        |   ●   |    ●    |    ●     |     ●      |    ○     |   ○    |
| edit_punches_own        |   ●   |    ●    |    ●     |     ○      |    ●     |   ○    |
| edit_punches_all        |   ●   |    ●    |    ●     |     ○      |    ○     |   ○    |
| approve_unavailability  |   ●   |    ●    |    ●     |     ○      |    ○     |   ○    |

### Finanza
| Permesso              | admin | manager | producer | accounting | operator | viewer |
|-----------------------|:-----:|:-------:|:--------:|:----------:|:--------:|:------:|
| view_finance          |   ●   |    ●    |    ●     |     ●      |    ○     |   ○    |
| view_quotes           |   ●   |    ●    |    ●     |     ●      |    ○     |   ○    |
| edit_quotes           |   ●   |    ●    |    ●     |     ●      |    ○     |   ○    |
| view_pricelist        |   ●   |    ●    |    ●     |     ●      |    ○     |   ○    |
| edit_pricelist        |   ●   |    ●    |    ○     |     ○      |    ○     |   ○    |
| view_cost_report      |   ●   |    ●    |    ●     |     ●      |    ○     |   ○    |
| view_invoices         |   ●   |    ●    |    ○     |     ●      |    ○     |   ○    |
| edit_invoices         |   ●   |    ●    |    ○     |     ●      |    ○     |   ○    |
| **edit_cost_actuals** |   ●   |    ●    |    ○     |     ●      |    ○     |   ○    |

### Risorse
| Permesso         | admin | manager | producer | accounting | operator | viewer |
|------------------|:-----:|:-------:|:--------:|:----------:|:--------:|:------:|
| view_resources   |   ●   |    ●    |    ●     |     ○      |    ○     |   ○    |
| edit_resources   |   ●   |    ●    |    ○     |     ○      |    ○     |   ○    |

### Configurazione
| Permesso                  | admin | manager | producer | accounting | operator | viewer |
|---------------------------|:-----:|:-------:|:--------:|:----------:|:--------:|:------:|
| manage_departments        |   ●   |    ●    |    ○     |     ○      |    ○     |   ○    |
| manage_settings_global    |   ●   |    ○    |    ○     |     ○      |    ○     |   ○    |
| manage_users              |   ●   |    ○    |    ○     |     ○      |    ○     |   ○    |
| manage_roles              |   ●   |    ○    |    ○     |     ○      |    ○     |   ○    |

---

## Permessi gate-keeper per azioni critiche

| Azione                                                  | Permesso richiesto    | Versione |
| ------------------------------------------------------- | --------------------- | -------- |
| DELETE Project                                          | `view_finance`        | v3.4.50.3|
| DELETE Cost-line / DELETE QuoteLine                     | `view_finance`        | v3.4.54  |
| PUT Cost-line `quantity_actual` (override maturato)     | `edit_cost_actuals`   | v3.4.54  |
| Modifica cost-line da modal-line-detail (bottone)       | `view_finance`        | v3.4.55  |
| Approva booking overtime                                | `approve_overtime`    | v3.4.32.2|
| Approva richiesta ferie/permesso                        | `approve_unavailability` | v3.4.22 |
| Override permessi extra per-utente                      | `manage_users`        | v3.4.25  |
| Notify reverse-flow (target audience)                   | `edit_quotes`         | v3.4.52  |
| Notify quote_approved_no_resources (target)             | `assign_resources`    | v3.4.56  |

---

## Note

- I permessi sono **additivi**: `User.extra_permissions` (JSON) si somma ai permessi del ruolo.
- Permesso `edit_cost_actuals` riservato perché il maturato deve derivare dai booking marcati `done` (sync automatico via `cost_line_sync.py`). L'override manuale è eccezione di finance.
- Tutti i preset sono modificabili via `/admin/roles` (`manage_roles`). Il built-in è stato disegnato per uso quotidiano post-prod IT.

---

## Aggiornamento di questo doc

Per rigenerare a partire dal codice: leggi `PRESET_PERMISSIONS` e `PERMISSIONS` in `app/services/rbac.py`. Vale la pena automatizzare con uno script `scripts/generate_permissions_matrix.py` quando cresce. Per ora manuale.
