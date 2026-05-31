"""
MediaFlow — AI context builder + system prompt (v3.5.0-alpha.66.17.0)

Estratto da ai_assistant.py (sprint R6 dell'audit). ai_assistant.py
era 2287 righe e mischiava 4 responsabilita':
  (a) system prompt + build_context (questo file)
  (b) legacy parser markdown action regex
  (c) 21 capability handlers
  (d) apply_action orchestrator

Questo modulo isola (a). build_system_prompt resta in ai_assistant.py
ma importa ASSISTANT_SYSTEM_PROMPT + build_context da qui.

Le funzioni esposte sono identiche per signature al blocco originale,
nessun call site va aggiornato (re-export in ai_assistant.py).

NB: CURRENT_TENANT resta una costante locale (= 1 per single-tenant
attuale). Quando R1 sara' completato sara' rimpiazzata da
current_tenant_id() di app.context.
"""
from __future__ import annotations
from app.services.clock import now_utc

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Project, Quote, Job, JobStatus, PriceItem, PriceCategory, Client, Resource,
    Asset, Department,
    Booking, BookingAssignment, BookingStatus,
    ResourceUnavailability, UnavailabilityKind, UnavailabilityStatus,
)


CURRENT_TENANT = 1


# ── System prompt ────────────────────────────────────────────

ASSISTANT_SYSTEM_PROMPT = """Sei l'assistente AI di MediaFlow, un software di gestione per case di postproduzione audiovisiva.

Il tuo ruolo: aiutare l'utente (produttore, project manager, coordinatore post) con:
- Consulenza tecnica su postproduzione cinema/TV/pubblicità
- Pianificazione risorse e tempi
- Suggerimenti su quotazioni e negoziazione
- Controllo di congruità: budget vs scope, rischi di sforamento
- Risposte a domande operative (formati DCP, codec, flussi di mastering, etc.)

Linee guida:
- Rispondi in italiano con tono professionale ma diretto.
- Sii concreto: numeri, range, esempi reali del settore.
- Se hai il contesto (progetto, quote, listino), usalo attivamente.
- Non inventare dati specifici dell'utente: se non presenti, chiedili.
- Formatta con markdown leggero (bold per punti chiave, liste per elenchi).
- Evita preamboli inutili: vai dritto al punto.

PATTERN "AI PROPONE, UTENTE DISPONE":
Tu non puoi modificare direttamente il database. Quando l'utente ti chiede di
fare qualcosa di concreto (creare cliente, progetto, voce listino, quote,
riga su quote, aggiornare metadata progetto, cercare info), tu PROPONI l'azione
in un blocco strutturato e l'utente la conferma cliccando "Applica".

SINTASSI DEL BLOCCO AZIONE (regola rigida, devi seguirla esattamente):

```action
{
  "type": "<uno dei tipi sotto>",
  "title": "Frase breve che descrive l'azione",
  "data": { ... payload ... }
}
```

I tre apici di apertura ` ```action ` e di chiusura ` ``` ` sono OBBLIGATORI
(senza spazio dopo il backtick). Senza i tre apici il sistema non riconosce l'azione.

CAPABILITY DISPONIBILI E SCHEMA `data`:

- propose_client: {name, contact_name?, contact_email?, contact_phone?, vat_number?, address?, city?, country?, website?, notes?}
- propose_project: {code (stringa, es. "MONG25"), title (es. "Mongoloid"), client_id (numero PK del cliente) OPPURE client_name (stringa), project_type? ("feature_film"|"short_film"|"series"|"documentary"|"spot"|"music_video"|"corporate"), length_minutes? (numero), fps? (es. "24"|"25"), shooting_format?, delivery_format?, director?, description?}
- propose_project_metadata: {project_id (numero PK) OPPURE code (stringa), length_minutes?, fps?, shooting_format?, delivery_format?, director?}
- propose_quote: {project_id (numero PK) OPPURE project_code (stringa), number? (auto Q-{anno}-NNN se manca), title? (default = titolo progetto), issue_date? (default oggi), valid_until? (default +30gg), vat_rate? (default 22), lines? (lista di righe — vedi sotto)}
   * lines è opzionale: se presente, crea quote+righe in unica transazione (un solo Apply)
   * ogni riga: {price_item_id? (numero PK voce listino — usa quando esiste un match), description (auto da listino se ometti e dai price_item_id), quantity (numero), unit ("day"|"turno"|"hour"|"flat", auto da listino), unit_price (numero, auto da listino se ometti), section? ("A"|"B"|"C", default "A"), detail?}
- propose_quote_line: {quote_id (numero PK) OPPURE quote_number (stringa), price_item_id? (numero PK voce listino — usa SEMPRE se possibile, vedi REGOLA SEARCH-FIRST), description (auto da listino se ometti e dai price_item_id), quantity (numero), unit ("day"|"turno"|"hour"|"flat", auto da listino), unit_price (numero, auto da listino se ometti), section? ("A"|"B"|"C"), detail?}
- propose_price_item: {name, description?, unit ("day"|"turno"|"hour"|"flat"), price_list (numero), category_name (richiesto), keywords? (lista di stringhe), department_name?}
- propose_new_item_and_line: {quote_id OPPURE quote_number, name (nome voce listino), category_name (obbligatorio), unit, price_list (numero), quantity (numero, default 1), description?, keywords?, department_name?, section?} — fa due cose in singola transazione: crea voce listino + aggiunge riga alla quote
- propose_resource: {name, type ("person_internal"|"person_freelance"|"studio"|"equipment"|"software"|"vehicle"), department_id (numero PK) OPPURE department_name (stringa esatta), role?, description?, daily_rate?, hourly_rate?, email?, phone?, internal_phone?, color? (#hex)} — crea una nuova risorsa. Tariffe: ometti se non note (NON scrivere 0).
- propose_booking: {job_id (numero) OPPURE job_code (stringa) (richiesto se kind=project), kind? ("project"|"internal_maintenance"|"internal_research"|"internal_training", default "project"), job_cost_line_id?, notes?, assignments: [{resource_id (numero) OPPURE resource_name (stringa), start_datetime (ISO), end_datetime (ISO)}, ...]} — crea un Booking con N risorse. BookingState iniziale=tentative (5 stati esclusivi: tentative→confirmed→in_progress→done|not_done; cancelled è soft-delete). Conflict check su ferie/altri booking.
- web_search: {query}

REGOLE CRITICHE:
1. **id ≠ code**. `id` è un numero (PK auto-incrementale del DB, lo trovi nei contesti come `(id=5)`). `code` è una stringa scelta dall'utente (es. "MONG25"). Se non vedi un `id` numerico nel contesto, usa il campo `code`/`*_code` nel payload.
2. I numeri JSON NON vanno tra virgolette. `{"length_minutes": 90}` corretto, `{"length_minutes": "90"}` sbagliato.
3. **NON inventare valori**. Se l'utente cita un progetto/cliente/quote, usa SOLO i valori che vedi nella sezione "DB" del contesto (PROGETTI ESISTENTI, CLIENTI ESISTENTI). Se non lo trovi, CHIEDI all'utente invece di indovinare un code.
4. Per creare un progetto serve il cliente: usa `client_id` se conosci il PK, altrimenti `client_name` (verrà cercato per nome esatto, e se non esiste l'azione fallirà).
5. Per le date usa la "Data corrente" che vedi nel contesto. NON inventare anni passati (es. 2023) se la data corrente è 2026.
6. Per propose_quote: se l'utente dà solo descrizioni di righe ("5gg color, 4h QC"), inseriscile direttamente in `lines` (singolo Apply che crea quote+righe). Non serve `number` né `title`: vengono auto-generati. Se non vuoi specificare `number`, **OMETTI il campo** invece di mettere `null`.
7. Una sola azione per turno tipicamente. Più azioni solo se logicamente concatenate.
8. Se mancano dati essenziali (es. nome cliente per creare cliente nuovo), CHIEDI prima di indovinare.
9. Per domande informative (consulenza tecnica, dubbi su workflow) rispondi normalmente senza blocchi action.

**REGOLA SEARCH-FIRST (priorità assoluta per tutte le richieste su quote)**

Quando l'utente ti chiede di aggiungere una o più voci a una quote (esistente o nuova),
PRIMA di proporre azioni devi cercare nel listino. Le voci listino attive sono nel contesto
sotto "VOCI LISTINO ATTIVE (id | name | category | unit | €list | keywords)".

Per OGNI voce richiesta dall'utente, segui questa cascata:

1. **1 match chiaro** (la descrizione utente coincide o è molto simile a una voce di listino):
   → proponi `propose_quote_line` includendo `price_item_id` (il numero della voce listino).
   → ometti `unit_price` e `unit` se vuoi usare i default del listino.
   → esempio: utente dice "5 giorni di Color HDR", listino ha `12 | Color HDR | Color | day | €1200`
     → `propose_quote_line` con `price_item_id: 12, quantity: 5` (basta).

2. **2-4 match plausibili** (più voci hanno nomi/keywords simili):
   → NON proporre azione. Rispondi in markdown con un elenco numerato dei match,
     ognuno con id, nome, categoria, prezzo. Chiedi all'utente quale scegliere.
   → esempio:
     "Trovo più match per 'color':
     1. **Color SDR** — Color · day · €800
     2. **Color HDR** — Color · day · €1200
     3. **Color grading dailies** — Color · day · €600
     Quale intendi?"

3. **0 match plausibili**: spiega cosa non hai trovato e proponi DUE strade in markdown:
   - **(a)** voce libera nella sola quote (usa `propose_quote_line` senza `price_item_id`,
     specifica `description` e `unit_price` espliciti)
   - **(b)** crea la voce nuova nel listino e aggiungila alla quote (scenario C)
     → usa `propose_new_item_and_line` (richiede `category_name` e `price_list`)
   → esempio:
     "Non trovo nulla per 'Foley editing' nel listino. Vuoi:
     (a) aggiungerla solo a questa quote come voce libera, o
     (b) crearla anche nel listino (in che categoria? quale prezzo?)"
   Aspetta la risposta, poi proponi l'azione corrispondente.

4. **Voce ovviamente nuova** (es. l'utente dice esplicitamente "crea una nuova voce X
   in listino e aggiungila a questa quote a Y €"): usa direttamente `propose_new_item_and_line`
   senza chiedere conferma.

**FORMATO JSON OBBLIGATORIO** (gli errori qui rendono l'azione invisibile all'utente):
- ZERO commenti: niente `// commento`, niente `/* commento */`. Il JSON è strict, i commenti rompono il parser.
- ZERO virgole finali: l'ultima coppia chiave-valore di un oggetto NON deve avere `,` dopo.
- Stringhe sempre tra virgolette doppie `"`, mai apici singoli `'`.
- Numeri senza virgolette (`22`, non `"22"`).
- Spiegazioni libere o note vanno PRIMA o DOPO il blocco ```action ...```, mai dentro il JSON.
"""


# ── Context builder ──────────────────────────────────────────

def _short_money(v) -> str:
    try: return f"€{float(v):,.0f}"
    except Exception: return "€0"


def build_context(db: Session,
                  project_id: Optional[int] = None,
                  quote_id: Optional[int] = None,
                  job_id: Optional[int] = None,
                  page: Optional[str] = None) -> str:
    """
    Costruisce il blocco di contesto da iniettare nel system prompt.
    Se è specificato project/quote/job, mostra il dettaglio dell'entità.
    Altrimenti (o in aggiunta) restituisce una vista d'insieme breve.
    """
    parts = []

    # Entità in canvas (priorità alta, dettaglio alto)
    if project_id:
        p = db.query(Project).filter(Project.id == project_id).first()
        if p:
            parts.append(f"""PROGETTO ATTIVO (id={p.id}):
- Codice: {p.code} | Titolo: {p.title}
- Tipologia: {p.project_type or 'n/d'} | Cliente: {p.client.name if p.client else 'n/d'}
- Durata: {p.length_minutes or '?'} min @ {p.fps or '?'} fps
- Ripresa: {p.shooting_format or 'n/d'} | Consegna: {p.delivery_format or 'n/d'}
- Regista: {p.director or 'n/d'} | Deadline: {p.delivery_deadline or 'n/d'} | Stato: {p.status}""")

    if quote_id:
        q = db.query(Quote).filter(Quote.id == quote_id).first()
        if q:
            parts.append(f"""QUOTAZIONE ATTIVA (id={q.id}, numero {q.number}):
- Titolo: {q.title}
- Totale netto: {_short_money(q.total_after_discount)} | Con IVA: {_short_money(q.total_with_vat)}
- Sconto pacchetto: {(q.package_discount or 0)*100:.0f}% | Voci: {len(q.lines)} | Stato: {q.status}""")
            if q.lines:
                lines = []
                for l in q.lines[:20]:
                    lines.append(f"  [{l.position}] {l.description}: {l.quantity} {l.unit} x {_short_money(l.unit_price)} = {_short_money(l.total)}")
                parts.append("Voci:\n" + "\n".join(lines))

    if job_id:
        j = db.query(Job).filter(Job.id == job_id).first()
        if j:
            cost_lines = j.cost_lines
            total_expected = sum(l.total_expected for l in cost_lines)
            parts.append(f"""JOB ATTIVO (id={j.id}, codice {j.code}):
- Titolo: {j.title} | Stato: {j.status}
- Budget quotato: {_short_money(j.budget_quoted)} | A finire: {_short_money(total_expected)}
- Voci di costo: {len(cost_lines)}""")
            # v3.5.0-alpha.172.24 — lista JCL del job (lavorazioni) per
            # consentire all'AI di scegliere autonomamente quale lavorazione
            # collegare a un nuovo booking senza chiedere ID all'utente.
            if cost_lines:
                jcl_lines = ["Lavorazioni del job (job_cost_line_id | descrizione | unità | qty quotata):"]
                for cl in cost_lines[:30]:
                    desc = cl.description or (cl.price_item.name if cl.price_item else "?")
                    jcl_lines.append(f"  {cl.id} | {desc} | {cl.unit or '?'} | {cl.quantity_quoted or 0}")
                parts.append("\n".join(jcl_lines))

    # Vista d'insieme (sempre, breve, per dare consapevolezza globale)
    from datetime import date as date_type
    overview = []
    overview.append(f"Data corrente: {date_type.today().isoformat()}")

    # v3.5.0-alpha.66.14.3 — tenant scope esplicito su tutte le entità con
    # colonna tenant_id. Modelli senza tenant_id (Project/Quote/Job/JobCostLine/
    # Asset) restano cross-tenant finché non saranno migrati in R1.
    n_clients = db.query(Client).filter(Client.tenant_id == CURRENT_TENANT).count()
    n_projects = db.query(Project).count()  # TODO R1: project.tenant_id
    n_items = db.query(PriceItem).filter(
        PriceItem.is_active == True,
        PriceItem.tenant_id == CURRENT_TENANT,
    ).count()
    n_quotes = db.query(Quote).count()  # TODO R1: quote.tenant_id
    n_resources = db.query(Resource).filter(
        Resource.is_active == True,
        Resource.tenant_id == CURRENT_TENANT,
    ).count()
    n_assets = db.query(Asset).count()  # TODO R1: asset.tenant_id
    overview.append(f"DB: {n_clients} clienti, {n_projects} progetti, {n_items} voci listino attive, "
                    f"{n_quotes} quote, {n_resources} risorse, {n_assets} asset.")

    cats = [c.name for c in db.query(PriceCategory).filter(
        PriceCategory.tenant_id == CURRENT_TENANT,
    ).order_by(PriceCategory.sort_order).limit(20).all()]
    if cats:
        overview.append("Categorie listino: " + ", ".join(cats[:20]))

    depts = [d.name for d in db.query(Department).filter(
        Department.is_active == True,
        Department.tenant_id == CURRENT_TENANT,
    ).all()]
    if depts:
        overview.append("Reparti: " + ", ".join(depts))

    # Voci listino attive (per matching search-first AI: vedi REGOLA SEARCH-FIRST nel prompt).
    # Limite 200 voci attive per non gonfiare il context oltre il ragionevole.
    PRICELIST_LIMIT = 200
    items = (db.query(PriceItem)
             .filter(
                 PriceItem.is_active == True,
                 PriceItem.tenant_id == CURRENT_TENANT,
             )
             .order_by(PriceItem.id)
             .limit(PRICELIST_LIMIT)
             .all())
    if items:
        overview.append(f"VOCI LISTINO ATTIVE ({len(items)} su {n_items}, formato: id | name | category | unit | €list | keywords):")
        for it in items:
            cat_name = it.category.name if it.category else "—"
            kws = ", ".join((it.keywords or [])[:5]) if it.keywords else ""
            kws_part = f" | kw: {kws}" if kws else ""
            # price_list può essere None per voci deliverable/bucket (prezzate
            # per bucket/quote, non a listino): NON formattare None con :.0f
            # (TypeError) e NON mostrare €0 (l'AI proporrebbe righe a prezzo zero).
            price_str = f"€{it.price_list:.0f}" if it.price_list is not None else "€n/d"
            overview.append(f"  {it.id} | {it.name} | {cat_name} | {it.unit} | {price_str}{kws_part}")
        if n_items > PRICELIST_LIMIT:
            overview.append(f"  …(altre {n_items - PRICELIST_LIMIT} voci omesse — chiedi all'utente se serve cercare oltre)")

    # v3.5.0-alpha.172.15 — Risorse attive con role + dept (per assegnazioni
    # corrette in propose_recurring_bookings / propose_booking).
    # Pre-fix l'AI vedeva solo `name` + count → allucinava ruoli (colorist su
    # online editor, scambio reparti).
    res_rows = (db.query(Resource).filter(
        Resource.tenant_id == CURRENT_TENANT,
        Resource.is_active == True,
    ).order_by(Resource.id).limit(60).all())
    if res_rows:
        overview.append("RISORSE ATTIVE (id | name | role | type | department):")
        for r in res_rows:
            role = (r.role or "—")
            rtype = (r.type.value if hasattr(r.type, "value") else str(r.type or "—"))
            dept = (r.department.name if r.department else "—")
            overview.append(f"  {r.id} | {r.name} | {role} | {rtype} | {dept}")

    # v3.5.0-alpha.172.15 — Job attivi con quote+project (per evitare confusione
    # quote_id↔job_id nei propose_recurring_bookings). AI ricava Job.id da
    # Quote.id senza guess.
    job_rows = (db.query(Job)
        .filter(Job.tenant_id == CURRENT_TENANT,
                Job.status.in_([JobStatus.approved, JobStatus.active]))
        .order_by(Job.id.desc()).limit(30).all())
    if job_rows:
        overview.append("JOB ATTIVI (job_id | code | project_id | quote_id | status):")
        for j in job_rows:
            overview.append(f"  {j.id} | {j.code} | proj#{j.project_id} | quote#{j.quote_id or '?'} | {j.status.value if hasattr(j.status,'value') else j.status}")
        # v3.5.0-alpha.172.24 — Lavorazioni (JCL) per ogni job attivo: AI le usa
        # per scegliere autonomamente il job_cost_line_id su nuovi booking
        # senza chiedere "qual è l'ID?" all'utente. Cap 60 JCL totali.
        budget = 60
        jcl_overview = []
        for j in job_rows:
            if budget <= 0:
                break
            jcls = list(j.cost_lines)[:8]  # top 8 per job
            if not jcls:
                continue
            jcl_overview.append(f"  Job #{j.id} ({j.code}) — lavorazioni:")
            for cl in jcls:
                if budget <= 0:
                    break
                desc = cl.description or (cl.price_item.name if cl.price_item else "?")
                jcl_overview.append(f"    jcl#{cl.id} | {desc} | {cl.unit or '?'} | qty={cl.quantity_quoted or 0}")
                budget -= 1
        if jcl_overview:
            overview.append("LAVORAZIONI DEI JOB (job_cost_line_id | descrizione | unit | qty quotata):")
            overview.extend(jcl_overview)

    # Lista clienti esistenti (per evitare allucinazioni di nomi)
    clients_rows = db.query(Client).filter(
        Client.tenant_id == CURRENT_TENANT,
    ).order_by(Client.name).limit(40).all()
    if clients_rows:
        overview.append("CLIENTI ESISTENTI (id | name):")
        for cl in clients_rows:
            overview.append(f"  {cl.id} | {cl.name}")

    # Lista progetti esistenti (per evitare allucinazioni di code)
    proj_rows = db.query(Project).order_by(Project.id.desc()).limit(40).all()
    if proj_rows:
        overview.append("PROGETTI ESISTENTI (id | code | title | client):")
        for p in proj_rows:
            client_name = p.client.name if p.client else "?"
            overview.append(f"  {p.id} | {p.code} | {p.title} | {client_name}")

    # Quote attive (per riferimento veloce su quote_id)
    quote_rows = db.query(Quote).order_by(Quote.id.desc()).limit(15).all()
    if quote_rows:
        overview.append("QUOTE ESISTENTI (id | number | project_code):")
        for qr in quote_rows:
            overview.append(f"  {qr.id} | {qr.number} | {qr.project.code if qr.project else '?'}")

    if page:
        overview.append(f"Pagina corrente UI: {page}")

    parts.append("\n".join(overview))

    # v3.5.0-alpha.50 — Sezione PIANIFICAZIONE viva (in-depth context).
    # Mostrata SOLO se utente è in /planning o ha un progetto/job in canvas.
    # Senza questa sezione l'AI non sa dei booking esistenti, conflitti,
    # carico risorse, ferie → propone azioni "alla cieca". Con questa sezione
    # può: rispondere a "che fa Luca questa settimana?", suggerire
    # ottimizzazioni, evitare conflitti prima di proporre nuovi booking.
    is_planning_page = bool(page and "/planning" in page)
    if is_planning_page or project_id or job_id:
        planning_section = _build_planning_context(db, project_id=project_id, job_id=job_id)
        if planning_section:
            parts.append(planning_section)

    return "\n\n".join(parts)


def _build_planning_context(db: Session,
                            project_id: Optional[int] = None,
                            job_id: Optional[int] = None) -> str:
    """v3.5.0-alpha.50: contesto pianificazione per copilot in-depth.

    Aggrega:
    - Booking nei prossimi 14 giorni (id, risorsa, range, kind/job)
    - Conflitti orari attivi (overlap su stessa risorsa)
    - Carico per risorsa nei prossimi 7 giorni (ore prenotate vs cap 40h)
    - Ferie/festività nei prossimi 14 giorni
    - Job in scadenza (deadline entro 30 giorni)

    Filtri:
    - Se project_id presente → restringe ai booking del progetto
    - Se job_id presente → restringe al job specifico
    """
    from datetime import datetime, timedelta
    from sqlalchemy.orm import joinedload as _jl

    today = now_utc()
    horizon_14 = today + timedelta(days=14)
    horizon_7 = today + timedelta(days=7)
    deadline_horizon = (today + timedelta(days=30)).date()

    parts: list[str] = []

    # ── Booking prossimi 14 giorni ────────────────────────────
    # v3.5.0-alpha.66.14.3 — tenant scope esplicito
    bk_q = db.query(Booking).options(
        _jl(Booking.assignments).joinedload(BookingAssignment.resource),
        _jl(Booking.job),
    ).filter(
        Booking.tenant_id == CURRENT_TENANT,
        Booking.status != BookingStatus.cancelled,
        Booking.start_datetime < horizon_14,
        Booking.end_datetime >= today,
    )
    if job_id:
        bk_q = bk_q.filter(Booking.job_id == job_id)
    elif project_id:
        bk_q = bk_q.join(Job, Booking.job_id == Job.id, isouter=True).filter(
            Job.project_id == project_id
        )
    bookings = bk_q.order_by(Booking.start_datetime).limit(80).all()

    if bookings:
        parts.append(f"PIANIFICAZIONE — booking prossimi 14gg ({len(bookings)} mostrati):")
        parts.append("(formato: bid | start→end | risorse | job/kind | exec_status)")
        for b in bookings[:50]:
            res_names = ", ".join((a.resource.name if a.resource else "?") for a in b.assignments[:4])
            if len(b.assignments) > 4:
                res_names += f" +{len(b.assignments)-4}"
            job_lbl = (b.job.code if b.job else b.kind.value if b.kind else "internal")
            s = b.start_datetime.strftime("%d/%m %H:%M")
            e = b.end_datetime.strftime("%d/%m %H:%M")
            est = b.execution_status.value if b.execution_status else "planned"
            parts.append(f"  {b.id} | {s}→{e} | {res_names} | {job_lbl} | {est}")
        if len(bookings) > 50:
            parts.append(f"  …altri {len(bookings)-50} omessi")

    # ── Conflitti orari attivi ────────────────────────────────
    # Trova coppie di assignment sovrapposti sulla stessa risorsa nei prossimi 14gg.
    # Query semplice: tutti gli assignment del periodo, group by resource_id, check overlap.
    conflicts = []
    ass_q = db.query(BookingAssignment).join(Booking).filter(
        Booking.tenant_id == CURRENT_TENANT,
        Booking.status != BookingStatus.cancelled,
        BookingAssignment.start_datetime < horizon_14,
        BookingAssignment.end_datetime >= today,
    )
    if job_id:
        ass_q = ass_q.filter(Booking.job_id == job_id)
    elif project_id:
        ass_q = ass_q.join(Job, Booking.job_id == Job.id, isouter=True).filter(
            Job.project_id == project_id
        )
    ass_list = ass_q.order_by(BookingAssignment.resource_id, BookingAssignment.start_datetime).all()
    by_res: dict[int, list] = {}
    for a in ass_list:
        by_res.setdefault(a.resource_id, []).append(a)
    for rid, lst in by_res.items():
        for i, a1 in enumerate(lst):
            for a2 in lst[i+1:]:
                if a2.start_datetime >= a1.end_datetime:
                    break  # ordinati per start, no più overlap
                if a2.end_datetime > a1.start_datetime:
                    conflicts.append((rid, a1, a2))
                    if len(conflicts) >= 10:
                        break
            if len(conflicts) >= 10:
                break
        if len(conflicts) >= 10:
            break
    if conflicts:
        parts.append(f"\nCONFLITTI orari attivi prossimi 14gg ({len(conflicts)} mostrati):")
        for rid, a1, a2 in conflicts[:10]:
            res = db.query(Resource).filter(Resource.id == rid).first()
            res_name = res.name if res else f"#{rid}"
            parts.append(
                f"  ⚠ {res_name}: assignment #{a1.id} ({a1.start_datetime.strftime('%d/%m %H:%M')}→{a1.end_datetime.strftime('%H:%M')}) "
                f"overlap #{a2.id} ({a2.start_datetime.strftime('%d/%m %H:%M')}→{a2.end_datetime.strftime('%H:%M')})"
            )

    # ── Carico per risorsa prossimi 7 giorni ──────────────────
    week_load: dict[int, float] = {}
    week_q = db.query(BookingAssignment).join(Booking).filter(
        Booking.tenant_id == CURRENT_TENANT,
        Booking.status != BookingStatus.cancelled,
        BookingAssignment.start_datetime < horizon_7,
        BookingAssignment.end_datetime >= today,
    )
    if job_id:
        week_q = week_q.filter(Booking.job_id == job_id)
    elif project_id:
        week_q = week_q.join(Job, Booking.job_id == Job.id, isouter=True).filter(
            Job.project_id == project_id
        )
    for a in week_q.all():
        # Calcola ore SOVRAPPOSTE alla finestra [today, horizon_7]
        s = max(a.start_datetime, today)
        e = min(a.end_datetime, horizon_7)
        if e > s:
            hrs = (e - s).total_seconds() / 3600
            week_load[a.resource_id] = week_load.get(a.resource_id, 0) + hrs
    if week_load:
        parts.append(f"\nCARICO settimana corrente per risorsa (ore prenotate, cap riferimento 40h):")
        for rid, hrs in sorted(week_load.items(), key=lambda kv: -kv[1])[:20]:
            res = db.query(Resource).filter(Resource.id == rid).first()
            name = res.name if res else f"#{rid}"
            ratio = hrs / 40
            badge = "🟢" if ratio < 0.8 else ("🟡" if ratio < 1.05 else "🔴")
            parts.append(f"  {badge} {name}: {hrs:.1f}h ({ratio*100:.0f}%)")

    # ── Ferie/festa prossime 14 giorni ─────────────────────────
    # ResourceUnavailability scope via Resource (la riga unav è per resource)
    unav = db.query(ResourceUnavailability).outerjoin(Resource).options(
        _jl(ResourceUnavailability.resource),
    ).filter(
        # Resource.tenant_id check via outerjoin (holiday rows hanno resource_id NULL → restano)
        ((Resource.tenant_id == CURRENT_TENANT) | (Resource.id.is_(None))),
        ResourceUnavailability.status == UnavailabilityStatus.approved,
        ResourceUnavailability.start_date <= horizon_14.date(),
        ResourceUnavailability.end_date >= today.date(),
    ).order_by(ResourceUnavailability.start_date).limit(30).all()
    if unav:
        kind_lbl = {
            UnavailabilityKind.vacation: "Ferie",
            UnavailabilityKind.sick: "Malattia",
            UnavailabilityKind.holiday: "Festività",
            UnavailabilityKind.weekend: "Weekend",
            UnavailabilityKind.other: "Non disp.",
        }
        parts.append(f"\nINDISPONIBILITÀ prossimi 14gg ({len(unav)} mostrate):")
        for u in unav[:15]:
            who = u.resource.name if u.resource else "TUTTI"
            kl = kind_lbl.get(u.kind, str(u.kind))
            parts.append(f"  {kl} | {u.start_date}→{u.end_date} | {who}")

    # ── Job critici (deadline ≤ 30gg) ─────────────────────────
    crit_q = db.query(Job).filter(
        Job.status.in_([JobStatus.active, JobStatus.approved, JobStatus.draft]),
        Job.end_date.isnot(None),
        Job.end_date <= deadline_horizon,
    )
    if project_id:
        crit_q = crit_q.filter(Job.project_id == project_id)
    if job_id:
        crit_q = crit_q.filter(Job.id == job_id)
    critical = crit_q.order_by(Job.end_date).limit(15).all()
    if critical:
        parts.append(f"\nJOB CRITICI (deadline ≤ 30gg, {len(critical)} mostrati):")
        for j in critical:
            days_left = (j.end_date - today.date()).days
            urg = "🔴" if days_left < 7 else ("🟡" if days_left < 14 else "🟢")
            parts.append(f"  {urg} {j.code} · {j.title or '?'} · scadenza {j.end_date} ({days_left}gg)")

    if not parts:
        return ""
    return "━━━ PIANIFICAZIONE VIVA ━━━\n" + "\n".join(parts)

