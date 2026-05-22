# Tag reparto su Client e Project — Design (MVP)

**Data:** 2026-05-22  
**Versione target:** v3.5.0-alpha.173.x  
**Stato:** Approved (Matteo), pronto per implementation plan  
**Autore:** brainstorming session Claude + Matteo

---

## Sommario

Aggiungere un tag multi-reparto (N:N) a `Client` e `Project` per consentire
classificazione e filtraggio della loro lista in UI. **Scope MVP volutamente
limitato alla sola visualizzazione**: nessun impatto su cost report, cashflow,
booking, RBAC o AI. Eventuali estensioni (attribution engine P&L per reparto,
RBAC by department, AI backfill) saranno valutate in fase successiva sulla
base dell'uso reale.

## Obiettivi

- Permettere all'utente di assegnare uno o più reparti di riferimento a ogni
  Client e a ogni Project.
- Mostrare i tag come badge colorati nelle liste e nelle schede.
- Offrire un filtro multiselect lasco (OR) sulle liste `/clients` e
  `/projects`.
- Persistere la selezione del filtro per utente via `localStorage`.

## Non-obiettivi (espliciti)

- **Niente attribution engine**: i tag non influenzano CR, cashflow, anomalie,
  invoicing.
- **Niente RBAC**: nessun blocco di visibilità o accesso basato sui tag.
- **Niente impatto operativo**: bookings, JCL, risorse restano liberi. Un job
  taggato DI/Video può continuare ad avere lavorazioni Audio o VFX.
- **Niente tag su Quote**: si filtra via Project (se serve, si aggiunge
  in fase successiva).
- **Niente backfill automatico**: tag vuoti su record esistenti = nessun
  filtro applicato (semantica "trasversale/legacy").
- **Niente capability AI** di proposta tag: rimandato.

## Modello dati

Due tabelle join, una per Client e una per Project. Pattern già usato
implicitamente in altri punti del codice (PriceItem.department_id) ma qui
con cardinalità N:N esplicita.

```python
class ClientDepartment(Base):
    __tablename__ = "client_departments"
    __table_args__ = (
        UniqueConstraint("client_id", "department_id", name="uq_client_dept"),
    )
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True)
    tenant_id:     Mapped[int]      = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    client_id:     Mapped[int]      = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[int]      = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), index=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProjectDepartment(Base):
    __tablename__ = "project_departments"
    __table_args__ = (
        UniqueConstraint("project_id", "department_id", name="uq_project_dept"),
    )
    id:            Mapped[int]      = mapped_column(Integer, primary_key=True)
    tenant_id:     Mapped[int]      = mapped_column(ForeignKey("tenants.id"), default=1, index=True)
    project_id:    Mapped[int]      = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[int]      = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"), index=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

### Relationships da aggiungere

Su `Client` (models.py:708):

```python
departments: Mapped[List["Department"]] = relationship(
    secondary="client_departments",
    lazy="selectin",
)
```

Su `Project` (models.py:817):

```python
departments: Mapped[List["Department"]] = relationship(
    secondary="project_departments",
    lazy="selectin",
)
```

Su `Department` (back-ref opzionale, utile per query future ma non
strettamente necessario per MVP — si può aggiungere alla bisogna):

```python
clients:  Mapped[List["Client"]]  = relationship(secondary="client_departments",  viewonly=True)
projects: Mapped[List["Project"]] = relationship(secondary="project_departments", viewonly=True)
```

### Vincoli e semantica

- `UniqueConstraint(client_id, department_id)` impedisce duplicati.
- `ondelete="CASCADE"` su entrambe le FK: cancellando un Client/Project o un
  Department, le righe della join spariscono automaticamente. Coerente con il
  fatto che il tag è metadato di relazione, non entità autonoma.
- `tenant_id` ridondante rispetto a client/project ma utile per query
  cross-tenant future e per coerenza con il pattern degli altri modelli.
- Soft-delete del Client/Project (`deleted_at`) **non** cancella le righe
  della join: restano per coerenza con il record soft-deleted. Il filtro UI
  parte dalle entità non-deleted, quindi non emergono.

## Endpoint API

Nessuna integrazione AI (quindi nessun `get_provider_for_user`). RBAC:
permission gate esistente `client.update` / `project.update`. Tenant filter
standard.

### `GET /clients/{id}/departments`

Response:

```json
{
  "client_id": 42,
  "departments": [
    {"id": 1, "name": "DI/Video", "code": "DI", "color": "#6272f5"},
    {"id": 2, "name": "Audio",    "code": "AU", "color": "#f57262"}
  ]
}
```

### `PUT /clients/{id}/departments`

Form-based (coerente con la convenzione progetto):

- Body: `department_ids=1,2,3` (CSV) **oppure** ripetuto `department_ids=1&department_ids=2`
- Logica: replace completo del set. Cancella le righe esistenti per
  `client_id` e ricrea le nuove. Singola transazione.
- Validazione: tutti i `department_id` devono esistere e appartenere al
  tenant corrente; altrimenti 422.
- Response: stesso payload di GET con il nuovo stato.

### `GET /projects/{id}/departments` e `PUT /projects/{id}/departments`

Stesso pattern, sostituendo `client_id` con `project_id`.

### Serializzazione inline

Per evitare round-trip extra in UI, i payload esistenti delle liste
(`/clients/api/list`, `/projects/api/list`) e delle scheda
(`/clients/api/{id}`, `/projects/api/{id}`) **includono** il campo
`departments` come array di mini-oggetti `{id, name, code, color}`.

## UI

Frontend vanilla JS, niente framework. Riuso degli helper globali
(`api()`, `openModal()`, `closeModal()`, `toast()`).

### `/clients`

- **Lista**: nuova colonna "Reparti" tra "Industry" e "Progetti". Mostra
  chip colorati (background = `Department.color`, fallback grigio), max
  3 visibili, eventuali eccedenze come "+N".
- **Toolbar**: filtro multiselect "Reparti" accanto al filtro testuale
  esistente. Default: nessun reparto selezionato = mostra tutti. Selezione
  multipla con logica OR (un client che ha almeno uno dei reparti
  selezionati passa il filtro).
- **Persistenza**: `localStorage.setItem('clients.filter.departments', json)`.
  Letto al load della pagina e riapplicato.
- **Modal create/edit**: nuovo campo "Reparti" sotto "Industry". Multiselect
  chip-style (riuso pattern già presente, vedi `MFAutocomplete` o
  fallback `<select multiple>` styled).

### `/projects`

Stesso pattern. La colonna "Reparti" sta tra "Cliente" e "Stato".

### Chip style

Coerente con badge già usati in `/pricelist`:

```css
.dept-chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  margin-right: 4px;
}
```

Background = `Department.color` se presente, altrimenti `#888`.

## Migration

Nuovo script `scripts/migrate_dept_tags.py`, idempotente, pattern coerente
con `scripts/migrate_phase1bis.py`:

1. `CREATE TABLE IF NOT EXISTS client_departments (...)` con tutti gli indici
   e i vincoli.
2. `CREATE TABLE IF NOT EXISTS project_departments (...)` idem.
3. Crea indici `idx_client_dept_client`, `idx_client_dept_dept` (e analoghi
   per project).
4. Nessun backfill: tag vuoti = stato neutro.
5. Output finale: conteggio righe create (sempre 0 al primo run, utile per
   verifica idempotenza).

Aggiunto a `strumenti.bat` / `strumenti.sh` come nuova voce di menu.

Aggiunto a `main.py` `_auto_migrate_columns()` lifespan: chiamata diretta a
`CREATE TABLE IF NOT EXISTS` per le 2 tabelle, così l'utente che non lancia
manualmente lo script non si trova il sistema rotto al boot.

## File toccati

```
app/models/models.py                +~30 righe (2 classi + relationships su Client/Project/Department)
app/routers/clients.py              +~40 righe (2 endpoint + serialize departments in get/list)
app/routers/projects.py             +~40 righe (idem)
app/templates/pages/clients.html    +~60 righe (badge + filtro toolbar + multiselect modal)
app/templates/pages/projects.html   +~60 righe (idem)
static/js/global.js                 +~20 righe (helper renderDeptChips, opzionale)
scripts/migrate_dept_tags.py        nuovo, ~80 righe
strumenti.bat                       +1 voce menu
strumenti.sh                        +1 voce menu
main.py                             +~10 righe in _auto_migrate_columns
CHANGELOG.md                        nuova entry
```

## Test plan

- [ ] Migration su DB esistente: lancia 2 volte, verifica idempotenza
  (nessuna eccezione, conteggio = 0 al secondo run).
- [ ] Crea un Client con 2 reparti via modal: badge visibili in lista,
  payload GET corretto.
- [ ] Modifica reparti di un Client (rimuove uno, aggiunge un altro): replace
  funziona, nessun duplicato in DB.
- [ ] Cancella un Department: le righe della join collegate vengono rimosse
  (CASCADE).
- [ ] Soft-delete un Client: le righe della join restano, ma il Client non
  appare in lista quindi sono invisibili.
- [ ] Filtro lista `/clients` con 2 reparti selezionati: appaiono solo
  client che hanno almeno uno dei due reparti. Refresh pagina: filtro
  persistito.
- [ ] Stesso ciclo per `/projects`.
- [ ] Permission gate: utente senza `client.update` riceve 403 su PUT.
- [ ] Tenant filter: PUT con `department_id` di altro tenant → 422.
- [ ] Performance: lista `/clients` con 1000 client e 4 reparti — payload
  non degrada (selectin loader).
- [ ] Smoke test browser: rendering chips, nessun errore console JS.

## Rischi e mitigazioni

- **Rischio**: relationship `lazy="selectin"` introduce N+1 in liste molto
  grandi.  
  **Mitigazione**: `selectin` fa già una sola query batch; verificato il
  pattern già usato in altri modelli. Se in futuro emerge come collo di
  bottiglia, si passa a `joinedload` esplicito nei router.
- **Rischio**: utente confuso da "tag vuoti = visibile a tutti".  
  **Mitigazione**: helper text nella modal: *"Lascia vuoto per progetti
  trasversali (visibili in tutti i filtri reparto)"*.
- **Rischio**: i 4 reparti seed (`DI/Video`, `VFX`, `Audio`, `Commercial`)
  non hanno colore.  
  **Mitigazione**: lo script di seed lo popola; per i tenant esistenti la
  migration imposta colori default solo se NULL.

## Estensioni future (fuori scope MVP)

Documentate qui per non perdere il filo, ma **NON** implementate ora:

1. **Attribution engine P&L per reparto**: mono-tag / multi-tag /
   zero-tag, con regola natural-dept fallback. Vedi conversazione di design
   originale.
2. **RBAC by department**: soft scope con default filter sui reparti
   dell'utente + bypass admin/manager.
3. **Tag su Quote**: ereditati da Project al promote, modificabili.
4. **AI capability `propose_project_departments`**: analizza JCL/Booking
   storici e propone reparti via approval workflow.
5. **Tab "Per reparto" in Cost Report**: aggregazione P&L.
6. **Dashboard reparto**: KPI dedicata.

---

*Approvato 2026-05-22 — implementation plan da scrivere via writing-plans.*
