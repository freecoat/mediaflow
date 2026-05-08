"""
MediaFlow — AI Assistant (copilot context-aware con pattern AI propone, utente dispone)

Ogni risposta dell'AI può contenere:
- testo libero in markdown (mostrato all'utente nel drawer chat)
- una o più "proposed actions" in blocchi ```action ...``` JSON, che il backend
  estrae, valida, salva come AIAction in DB e restituisce al frontend per conferma.

Capability mutation supportate (lista canonica in `_ACTION_HANDLERS`):
- propose_price_item       — proporre nuova voce di listino
- propose_client           — proporre creazione cliente
- propose_project          — proporre creazione progetto
- propose_project_metadata — aggiornare metadata progetto
- propose_quote            — proporre quotazione (con righe inline opt)
- update_quote             — aggiornare quote esistente
- propose_quote_line       — proporre riga su quote attiva
- propose_new_item_and_line — voce listino + riga quote in singola transazione
- propose_resource         — proporre nuova risorsa (α.33)
- propose_booking          — proporre booking con N risorse
- web_search               — Tavily (read-only)
"""
from __future__ import annotations
import json
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Project, Quote, Job, JobStatus, PriceItem, PriceCategory, Client, Resource,
    Asset, Department,
    Booking, BookingAssignment, BookingStatus, BookingExecutionStatus,
    ResourceUnavailability, UnavailabilityKind, UnavailabilityStatus,
    JobCostLine, BookingChange,
)
from app.models.models import AIAction, JCLBillingStatus
from app.services.ai_provider import get_provider_for_user, safe_json_parse

logger = logging.getLogger(__name__)


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
   * ogni riga: {price_item_id? (numero PK voce listino — usa quando esiste un match), description (auto da listino se ometti e dai price_item_id), quantity (numero), unit ("day"|"hour"|"flat", auto da listino), unit_price (numero, auto da listino se ometti), section? ("A"|"B"|"C", default "A"), detail?}
- propose_quote_line: {quote_id (numero PK) OPPURE quote_number (stringa), price_item_id? (numero PK voce listino — usa SEMPRE se possibile, vedi REGOLA SEARCH-FIRST), description (auto da listino se ometti e dai price_item_id), quantity (numero), unit ("day"|"hour"|"flat", auto da listino), unit_price (numero, auto da listino se ometti), section? ("A"|"B"|"C"), detail?}
- propose_price_item: {name, description?, unit ("day"|"hour"|"flat"), price_list (numero), category_name (richiesto), keywords? (lista di stringhe), department_name?}
- propose_new_item_and_line: {quote_id OPPURE quote_number, name (nome voce listino), category_name (obbligatorio), unit, price_list (numero), quantity (numero, default 1), description?, keywords?, department_name?, section?} — fa due cose in singola transazione: crea voce listino + aggiunge riga alla quote
- propose_resource: {name, type ("person_internal"|"person_freelance"|"studio"|"equipment"|"software"|"vehicle"), department_id (numero PK) OPPURE department_name (stringa esatta), role?, description?, daily_rate?, hourly_rate?, email?, phone?, internal_phone?, color? (#hex)} — crea una nuova risorsa. Tariffe: ometti se non note (NON scrivere 0).
- propose_booking: {job_id (numero) OPPURE job_code (stringa) (richiesto se kind=project), kind? ("project"|"internal_maintenance"|"internal_research"|"internal_training", default "project"), job_cost_line_id?, notes?, assignments: [{resource_id (numero) OPPURE resource_name (stringa), start_datetime (ISO), end_datetime (ISO)}, ...]} — crea un Booking con N risorse. Status=tentative. Conflict check su ferie/altri booking.
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

    # Vista d'insieme (sempre, breve, per dare consapevolezza globale)
    from datetime import date as date_type
    overview = []
    overview.append(f"Data corrente: {date_type.today().isoformat()}")

    n_clients = db.query(Client).count()
    n_projects = db.query(Project).count()
    n_items = db.query(PriceItem).filter(PriceItem.is_active == True).count()
    n_quotes = db.query(Quote).count()
    n_resources = db.query(Resource).filter(Resource.is_active == True).count()
    n_assets = db.query(Asset).count()
    overview.append(f"DB: {n_clients} clienti, {n_projects} progetti, {n_items} voci listino attive, "
                    f"{n_quotes} quote, {n_resources} risorse, {n_assets} asset.")

    cats = [c.name for c in db.query(PriceCategory).order_by(PriceCategory.sort_order).limit(20).all()]
    if cats:
        overview.append("Categorie listino: " + ", ".join(cats[:20]))

    depts = [d.name for d in db.query(Department).filter(Department.is_active == True).all()]
    if depts:
        overview.append("Reparti: " + ", ".join(depts))

    # Voci listino attive (per matching search-first AI: vedi REGOLA SEARCH-FIRST nel prompt).
    # Limite 200 voci attive per non gonfiare il context oltre il ragionevole.
    PRICELIST_LIMIT = 200
    items = (db.query(PriceItem)
             .filter(PriceItem.is_active == True)
             .order_by(PriceItem.id)
             .limit(PRICELIST_LIMIT)
             .all())
    if items:
        overview.append(f"VOCI LISTINO ATTIVE ({len(items)} su {n_items}, formato: id | name | category | unit | €list | keywords):")
        for it in items:
            cat_name = it.category.name if it.category else "—"
            kws = ", ".join((it.keywords or [])[:5]) if it.keywords else ""
            kws_part = f" | kw: {kws}" if kws else ""
            overview.append(f"  {it.id} | {it.name} | {cat_name} | {it.unit} | €{it.price_list:.0f}{kws_part}")
        if n_items > PRICELIST_LIMIT:
            overview.append(f"  …(altre {n_items - PRICELIST_LIMIT} voci omesse — chiedi all'utente se serve cercare oltre)")

    # Lista clienti esistenti (per evitare allucinazioni di nomi)
    clients_rows = db.query(Client).order_by(Client.name).limit(40).all()
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

    today = datetime.utcnow()
    horizon_14 = today + timedelta(days=14)
    horizon_7 = today + timedelta(days=7)
    deadline_horizon = (today + timedelta(days=30)).date()

    parts: list[str] = []

    # ── Booking prossimi 14 giorni ────────────────────────────
    bk_q = db.query(Booking).options(
        _jl(Booking.assignments).joinedload(BookingAssignment.resource),
        _jl(Booking.job),
    ).filter(
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
    unav = db.query(ResourceUnavailability).options(
        _jl(ResourceUnavailability.resource),
    ).filter(
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


# ── Estrazione azioni proposte ───────────────────────────────

VALID_ACTION_TYPES = {
    "propose_client",
    "propose_project",
    "propose_project_metadata",
    "propose_quote",
    "propose_quote_line",
    "propose_price_item",
    "propose_new_item_and_line",
    "propose_resource",
    "propose_booking",
    # v3.5.0-alpha.50 — Planning operations (move/resize/delete su booking esistenti)
    "propose_move_booking",
    "propose_resize_booking",
    "propose_delete_booking",
    "web_search",
}


def _balanced_json_at(text: str, start: int) -> tuple[Optional[str], int]:
    """
    Estrae un blocco JSON balanced partendo da text[start] (deve essere `{`).
    Ritorna (json_str, end_index_after_closing_brace) oppure (None, start).
    """
    if start >= len(text) or text[start] != "{":
        return None, start
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False; continue
        if ch == "\\":
            escape = True; continue
        if ch == '"':
            in_string = not in_string; continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1], i + 1
    return None, start


def extract_proposed_actions(reply_text: str) -> tuple[str, list[dict]]:
    """
    Estrae i blocchi azione dalla risposta dell'AI. Tollera tre formati che
    i modelli piccoli (Llama 8B, Qwen 7B) emettono con frequenza:

      1. ```action\n{...}\n```    (canonica)
      2. ```\naction\n{...}\n```  (action su riga successiva)
      3. action\n{...}            (senza code fence)

    Usa parsing balanced delle parentesi così supporta JSON annidato.
    Ritorna (testo_ripulito, [azioni_valide]).
    """
    if not reply_text:
        return "", []

    actions: list[dict] = []
    text = reply_text

    # Trova tutti i punti di partenza dei blocchi action e estraili in ordine
    # Pattern 1+2: tre apici opzionali + parola action + JSON balanced
    # Pattern 3: solo parola action a inizio linea + JSON balanced
    fence_pat = re.compile(
        r"(```)?\s*\n?\s*action\s*\n", re.IGNORECASE)

    # Iteriamo finché troviamo "action\n{"
    pos = 0
    spans_to_strip: list[tuple[int, int]] = []
    while True:
        m = fence_pat.search(text, pos)
        if not m:
            break
        # cerca la prima `{` subito dopo il match
        brace_idx = text.find("{", m.end() - 1)
        if brace_idx < 0 or brace_idx > m.end() + 5:
            pos = m.end()
            continue
        payload, after = _balanced_json_at(text, brace_idx)
        if not payload:
            pos = m.end()
            continue
        parsed = safe_json_parse(payload)
        if not parsed:
            logger.warning(
                "Blocco action trovato ma JSON non parsabile (probabilmente "
                "contiene commenti o virgole finali). Primi 200 char: %r",
                payload[:200],
            )
            pos = after
            continue
        if parsed.get("type") not in VALID_ACTION_TYPES:
            logger.warning(
                "Blocco action con type non riconosciuto: %r (validi: %s)",
                parsed.get("type"), sorted(VALID_ACTION_TYPES),
            )
            pos = after
            continue
        actions.append(parsed)
        # estendi span per togliere anche eventuali ``` di chiusura
        end = after
        tail = text[end:end + 8]
        m2 = re.match(r"\s*```", tail)
        if m2:
            end += m2.end()
        spans_to_strip.append((m.start(), end))
        pos = end

    # Rimuovi gli span (in ordine inverso per non shiftare gli indici)
    for s, e in reversed(spans_to_strip):
        text = text[:s] + text[e:]

    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    return cleaned, actions


# ── Chat principale ─────────────────────────────────────────

def build_system_prompt(db: Session, *, use_tools: bool,
                        project_id: Optional[int] = None,
                        quote_id: Optional[int] = None,
                        job_id: Optional[int] = None,
                        page: Optional[str] = None) -> str:
    """Costruisce il system prompt + sezione contesto.

    Quando `use_tools=True` (provider con tool_use nativo) usa la versione slim
    `ASSISTANT_SYSTEM_PROMPT_TOOLS` di `ai_tools` (niente schema action inline).
    Altrimenti usa `ASSISTANT_SYSTEM_PROMPT` legacy con tutto lo schema.
    """
    if use_tools:
        from app.services.ai_tools import ASSISTANT_SYSTEM_PROMPT_TOOLS as base
    else:
        base = ASSISTANT_SYSTEM_PROMPT
    context = build_context(db, project_id, quote_id, job_id, page=page)
    if context:
        return base + f"\n\n━━━ CONTESTO ATTUALE ━━━\n{context}"
    return base


def chat_with_assistant(db: Session,
                        messages: list[dict],
                        user_id: Optional[int] = None,
                        project_id: Optional[int] = None,
                        quote_id: Optional[int] = None,
                        job_id: Optional[int] = None,
                        page: Optional[str] = None) -> dict:
    """
    Chat multi-turn con l'assistente — path LEGACY (markdown ```action```).
    Usato per provider che non supportano tool_use nativo (Ollama/Perplexity)
    o come fallback.

    Ritorna dict {reply, actions, error}.
    Le azioni proposte NON sono ancora salvate nel DB: lo fa il router.
    """
    provider = get_provider_for_user(user_id, db)
    if not provider:
        return {
            "reply": "AI non configurata. Vai in Impostazioni → tab AI per scegliere e attivare un provider.",
            "actions": [],
            "error": "provider_disabled",
        }

    system = build_system_prompt(db, use_tools=False, project_id=project_id,
                                 quote_id=quote_id, job_id=job_id, page=page)

    try:
        raw_reply = provider.chat(messages, system=system, max_tokens=2000, temperature=0.5) or ""
    except Exception as e:
        logger.error(f"Assistant chat failed: {e}")
        return {
            "reply": f"Errore comunicazione con l'AI: {str(e)[:200]}",
            "actions": [],
            "error": "provider_error",
        }

    cleaned, actions = extract_proposed_actions(raw_reply)
    return {"reply": cleaned or raw_reply, "actions": actions, "error": None}


# ── Applicazione delle azioni proposte ───────────────────────

def apply_action(db: Session, action: AIAction) -> dict:
    """
    Esegue concretamente l'azione approvata dall'utente.
    Ritorna {ok, result} oppure {ok: False, error}.
    Solleva ValueError se il payload è incompleto.

    v3.5.0-alpha.19: gli handler che dichiarano un parametro keyword-only `user`
    (settings registry: read_setting/update_setting) ricevono l'utente che ha
    creato l'action — necessario per i permission check + per le aree
    "self" (preferenze per-utente).
    """
    if action.status != "proposed":
        return {"ok": False, "error": f"Azione in stato {action.status}, non applicabile"}

    payload = json.loads(action.payload) if action.payload else {}
    handler = _ACTION_HANDLERS.get(action.action_type)
    if not handler:
        return {"ok": False, "error": f"Tipo azione non supportato: {action.action_type}"}

    try:
        import inspect
        sig = inspect.signature(handler)
        kwargs: dict = {}
        if "user" in sig.parameters:
            user = None
            if action.user_id:
                from app.models import User
                user = db.query(User).filter(User.id == action.user_id).first()
            kwargs["user"] = user
        result = handler(db, payload, **kwargs)
        return {"ok": True, "result": result}
    except Exception as e:
        logger.exception(f"apply_action {action.action_type} fallita")
        return {"ok": False, "error": str(e)}


# Handler concreti ────────────────────────────────────────────

def _h_propose_price_item(db: Session, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Manca 'name'")
    cat_name = (data.get("category_name") or "").strip()
    if not cat_name:
        raise ValueError("Manca 'category_name' (la categoria è obbligatoria)")
    cat = db.query(PriceCategory).filter(PriceCategory.name == cat_name).first()
    if not cat:
        cat = PriceCategory(name=cat_name)
        db.add(cat); db.flush()
    category_id = cat.id
    dept_id = None
    dept_name = (data.get("department_name") or "").strip()
    if dept_name:
        d = db.query(Department).filter(Department.name == dept_name).first()
        if d:
            dept_id = d.id
    price = float(data.get("price_list") or 0)
    item = PriceItem(
        name=name,
        description=data.get("description"),
        unit=data.get("unit") or "day",
        price_list=price,
        price_average=price,
        price_low=price,
        category_id=category_id,
        department_id=dept_id,
        keywords=data.get("keywords") or [],
        is_active=True,
    )
    db.add(item); db.flush()
    return {"created": True, "price_item_id": item.id, "name": item.name,
            "category": cat.name, "unit": item.unit, "price_list": item.price_list,
            "message": f"Voce listino '{item.name}' creata con id={item.id} (categoria {cat.name}, {item.unit}, €{item.price_list})."}


def _h_propose_client(db: Session, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Manca 'name'")
    # accetta sia campi dello schema (contact_email/phone) che alias comuni
    email = data.get("contact_email") or data.get("email")
    phone = data.get("contact_phone") or data.get("phone")
    c = Client(
        name=name,
        contact_name=data.get("contact_name"),
        contact_email=email,
        contact_phone=phone,
        vat_number=data.get("vat_number"),
        address=data.get("address"),
        city=data.get("city"),
        country=data.get("country"),
        website=data.get("website"),
        notes=data.get("notes"),
    )
    db.add(c); db.flush()
    return {"created": True, "client_id": c.id, "name": c.name,
            "message": f"Cliente '{c.name}' creato con id={c.id}."}


def _resolve_project(db: Session, data: dict) -> Project:
    """Risolve un progetto da `project_id` (numero PK) o `code` (stringa)."""
    pid = data.get("project_id")
    if isinstance(pid, int) or (isinstance(pid, str) and pid.isdigit()):
        p = db.query(Project).filter(Project.id == int(pid)).first()
        if p:
            return p
    code = data.get("code") or (pid if isinstance(pid, str) else None)
    if code:
        p = db.query(Project).filter(Project.code == code).first()
        if p:
            return p
    raise ValueError(f"Progetto non trovato (project_id={pid!r}, code={code!r}). "
                     f"Usa il PK numerico o il code esatto.")


def _resolve_quote(db: Session, data: dict) -> Quote:
    """Risolve una quote da `quote_id` (PK) o `quote_number` (stringa)."""
    qid = data.get("quote_id")
    if isinstance(qid, int) or (isinstance(qid, str) and qid.isdigit()):
        q = db.query(Quote).filter(Quote.id == int(qid)).first()
        if q:
            return q
    number = data.get("quote_number") or (qid if isinstance(qid, str) else None)
    if number:
        q = db.query(Quote).filter(Quote.number == number).first()
        if q:
            return q
    raise ValueError(f"Quote non trovata (quote_id={qid!r}, quote_number={number!r}).")


def _h_propose_project(db: Session, data: dict) -> dict:
    code = (data.get("code") or "").strip()
    title = (data.get("title") or "").strip()
    if not code:
        raise ValueError("Manca 'code'")
    if not title:
        raise ValueError("Manca 'title'")
    if db.query(Project).filter(Project.code == code).first():
        raise ValueError(f"Esiste già un progetto con code '{code}'")

    # Risolvi cliente: client_id (PK) o client_name (stringa)
    client_id = data.get("client_id")
    client = None
    if isinstance(client_id, int) or (isinstance(client_id, str) and str(client_id).isdigit()):
        client = db.query(Client).filter(Client.id == int(client_id)).first()
    if client is None:
        client_name = (data.get("client_name") or "").strip()
        if client_name:
            client = db.query(Client).filter(Client.name == client_name).first()
            if not client:
                raise ValueError(f"Cliente '{client_name}' non trovato. Crealo prima.")
    if client is None:
        raise ValueError("Specifica 'client_id' (PK) o 'client_name' (esistente).")

    p = Project(
        code=code, title=title, client_id=client.id,
        project_type=data.get("project_type"),
        length_minutes=data.get("length_minutes"),
        fps=str(data["fps"]) if data.get("fps") is not None else None,
        shooting_format=data.get("shooting_format"),
        delivery_format=data.get("delivery_format"),
        director=data.get("director"),
        description=data.get("description"),
    )
    db.add(p); db.flush()
    return {"created": True, "project_id": p.id, "code": p.code, "title": p.title,
            "client": client.name,
            "message": f"Progetto '{p.code}' ({p.title}) creato con id={p.id} per cliente {client.name}."}


def _next_quote_number(db: Session) -> str:
    """Genera Q-{anno}-{progressivo zero-padded a 3 cifre} basato sulle quote esistenti.

    BYPASS soft-delete filter (`include_deleted=True`): le quote in cestino
    occupano comunque il `number` (vincolo UNIQUE su DB), quindi devono essere
    considerate qui per evitare collisioni di numero al successivo INSERT.
    """
    from datetime import date as date_type
    year = date_type.today().year
    prefix = f"Q-{year}-"
    last = (db.query(Quote)
              .execution_options(include_deleted=True)
              .filter(Quote.number.like(f"{prefix}%"))
              .order_by(Quote.id.desc()).first())
    n = 1
    if last:
        try:
            n = int(last.number.rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            n = 1
    return f"{prefix}{n:03d}"


def _h_propose_quote(db: Session, data: dict) -> dict:
    """
    Crea una quote. Se data['lines'] è una lista, crea anche le righe in transazione.
    Defaults intelligenti:
      - number: auto-generato Q-{anno}-NNN se non specificato
      - title: titolo del progetto se non specificato
      - issue_date: oggi se non specificato
      - valid_until: oggi+30 giorni se non specificato
    """
    from datetime import date as date_type, timedelta
    from app.models import QuoteLine, PriceLevel
    from app.routers.quotes import _recalc_quote

    # Risolvi progetto: project_id o project_code
    pid = data.get("project_id")
    project = None
    if isinstance(pid, int) or (isinstance(pid, str) and str(pid).isdigit()):
        project = db.query(Project).filter(Project.id == int(pid)).first()
    if project is None:
        pcode = (data.get("project_code") or "").strip()
        if pcode:
            project = db.query(Project).filter(Project.code == pcode).first()
            if not project:
                raise ValueError(
                    f"Progetto con code '{pcode}' non trovato. "
                    "Crea prima il progetto, oppure usa il code di uno esistente."
                )
    if project is None:
        raise ValueError("Specifica 'project_id' (PK numerico) o 'project_code' (stringa).")

    # number: auto se mancante (bypass soft-delete: quote in cestino occupano il number)
    number = (data.get("number") or "").strip()
    if not number:
        number = _next_quote_number(db)
    elif (db.query(Quote)
            .execution_options(include_deleted=True)
            .filter(Quote.number == number).first()):
        raise ValueError(f"Esiste già una quote con number '{number}' (eventualmente nel cestino)")

    # title: fallback al titolo del progetto
    title = (data.get("title") or "").strip() or project.title

    # date: oggi e +30gg di default
    today = date_type.today()
    issue_raw = data.get("issue_date")
    try:
        issue_date = date_type.fromisoformat(issue_raw) if issue_raw else today
    except (ValueError, TypeError):
        issue_date = today
    # Se l'AI mette una data nel passato (allucinazione) la sovrascriviamo a oggi
    if issue_date.year < today.year - 1:
        issue_date = today

    valid_raw = data.get("valid_until")
    try:
        valid_until = date_type.fromisoformat(valid_raw) if valid_raw else issue_date + timedelta(days=30)
    except (ValueError, TypeError):
        valid_until = issue_date + timedelta(days=30)
    if valid_until <= issue_date:
        valid_until = issue_date + timedelta(days=30)

    q = Quote(
        number=number, title=title,
        project_id=project.id, client_id=project.client_id,
        issue_date=issue_date, valid_until=valid_until,
        vat_rate=float(data.get("vat_rate", 22.0)),
    )
    db.add(q); db.flush()

    # Righe opzionali (transazione: se una fallisce, rollback dell'intera quote)
    lines_data = data.get("lines") or []
    created_lines = []
    if lines_data:
        for i, ld in enumerate(lines_data):
            qty = float(ld.get("quantity") or 1)
            section = (ld.get("section") or "A").strip()[:1].upper() or "A"

            # Risolvi price_item_id se presente, e usa il listino come default
            # per description / unit / unit_price quando l'AI non li ha forniti.
            pi = None
            pi_id_raw = ld.get("price_item_id")
            if isinstance(pi_id_raw, int) or (isinstance(pi_id_raw, str) and str(pi_id_raw).isdigit()):
                pi = db.query(PriceItem).filter(PriceItem.id == int(pi_id_raw)).first()
                if not pi:
                    raise ValueError(f"Riga #{i+1}: price_item_id={pi_id_raw} non trovato in listino.")

            description = (ld.get("description") or "").strip() or (pi.name if pi else "")
            if not description:
                raise ValueError(f"Riga #{i+1}: manca 'description' (e nessun price_item_id da cui ereditarla).")

            raw_unit = (ld.get("unit") or "").strip()
            unit = raw_unit or (pi.unit if pi else "day")
            if unit not in ("day", "hour", "flat"):
                unit = pi.unit if pi else "day"

            raw_price = ld.get("unit_price")
            if raw_price in (None, ""):
                price = float(pi.price_list) if pi else 0.0
            else:
                price = float(raw_price)

            line = QuoteLine(
                quote_id=q.id,
                section=section,
                position=ld.get("position") or f"{section}.{i+1}",
                description=description,
                detail=ld.get("detail"),
                quantity=qty,
                unit=unit,
                price_level=PriceLevel.list_price,
                unit_price=price,
                total=round(qty * price, 2),
                sort_order=(i + 1) * 10,
                price_item_id=pi.id if pi else None,
            )
            db.add(line); db.flush()
            created_lines.append({
                "description":   description,
                "qty":           qty,
                "unit":          unit,
                "total":         line.total,
                "price_item_id": pi.id if pi else None,
            })
        # Ricalcola totali quote
        q = db.query(Quote).filter(Quote.id == q.id).first()
        _recalc_quote(q)

    return {
        "created": True,
        "quote_id": q.id,
        "number": q.number,
        "title": q.title,
        "project_code": project.code,
        "issue_date": issue_date.isoformat(),
        "lines_count": len(created_lines),
        "lines": created_lines,
        "total_after_discount": q.total_after_discount,
        "message": f"Quotazione {q.number} creata con id={q.id} per progetto {project.code} ({len(created_lines)} righe, totale netto €{q.total_after_discount:.2f}).",
    }


def _h_update_quote(db: Session, data: dict) -> dict:
    """v3.5.0-alpha.14: modifica i metadata di una quote esistente.
    Permette: title, issue_date, valid_until, vat_rate, package_discount, notes,
    payment_terms, status (con validazione transitions).
    Quote in cestino o sostituita non sono modificabili (status=superseded blocca).
    """
    from datetime import date as date_type
    from app.routers.quotes import _recalc_quote

    qid = data.get("quote_id")
    qnum = (data.get("quote_number") or "").strip()
    q = None
    if isinstance(qid, int) or (isinstance(qid, str) and str(qid).isdigit()):
        q = db.query(Quote).filter(Quote.id == int(qid)).first()
    if q is None and qnum:
        q = db.query(Quote).filter(Quote.number == qnum).first()
    if q is None:
        raise ValueError("Specifica `quote_id` (PK) o `quote_number` (es. 'Q-2026-001').")

    # Status superseded → bloccare (è una versione storica di un altro)
    status_v = q.status.value if hasattr(q.status, "value") else str(q.status)
    if status_v == "superseded":
        raise ValueError(f"Quote {q.number} è 'superseded' (sostituita) — non modificabile.")

    changed = []
    if data.get("title") and data["title"].strip():
        q.title = data["title"].strip(); changed.append("title")
    if data.get("notes") is not None:
        q.notes = data["notes"]; changed.append("notes")
    if data.get("payment_terms") is not None:
        q.payment_terms = data["payment_terms"]; changed.append("payment_terms")
    if data.get("vat_rate") is not None:
        q.vat_rate = float(data["vat_rate"]); changed.append("vat_rate")
    if data.get("package_discount") is not None:
        # Convenzione UI: discount positivo (0..1); in DB lo stocchiamo negativo
        pd = float(data["package_discount"])
        if pd > 1: pd = pd / 100.0  # accetta sia "0.1" sia "10"
        q.package_discount = -abs(pd) if pd > 0 else 0.0
        changed.append("package_discount")
    for date_field in ("issue_date", "valid_until"):
        raw = data.get(date_field)
        if raw:
            try:
                setattr(q, date_field, date_type.fromisoformat(raw))
                changed.append(date_field)
            except (ValueError, TypeError):
                raise ValueError(f"{date_field} non è una data ISO valida (atteso YYYY-MM-DD).")

    if not changed:
        raise ValueError("Nessun campo modificabile passato. Usa title/notes/vat_rate/package_discount/issue_date/valid_until/payment_terms.")

    _recalc_quote(q)
    db.flush()
    return {
        "updated": True,
        "quote_id": q.id,
        "number": q.number,
        "title": q.title,
        "fields_changed": changed,
        "total_after_discount": q.total_after_discount,
        "message": f"Quotazione {q.number} aggiornata ({', '.join(changed)}). Totale netto: €{q.total_after_discount:.2f}.",
    }


def _h_propose_quote_line(db: Session, data: dict) -> dict:
    """Aggiunge una riga a una quote esistente.

    Se `price_item_id` è valorizzato: lega la riga al listino e usa
    `price_item.price_list` come `unit_price` di default (sovrascrivibile).
    Se mancante: voce libera (storico).
    """
    from app.models import QuoteLine, PriceLevel
    q = _resolve_quote(db, data)
    qty = float(data.get("quantity") or 1)

    # Risolvi eventuale price_item per default su unit_price/unit/description
    price_item_id = data.get("price_item_id")
    pi = None
    if isinstance(price_item_id, int) or (isinstance(price_item_id, str) and str(price_item_id).isdigit()):
        pi = db.query(PriceItem).filter(PriceItem.id == int(price_item_id)).first()
        if not pi:
            raise ValueError(f"price_item_id={price_item_id} non trovato in listino.")

    # unit_price: usa valore esplicito se passato, altrimenti default da listino
    raw_price = data.get("unit_price")
    if raw_price in (None, ""):
        price = float(pi.price_list) if pi else 0.0
    else:
        price = float(raw_price)

    # description e unit: se non passate ma c'è price_item, eredita
    description = data.get("description") or (pi.name if pi else "")
    unit = data.get("unit") or (pi.unit if pi else "day")

    line = QuoteLine(
        quote_id=q.id,
        section=data.get("section") or "A",
        position=data.get("position") or f"A.{len(q.lines)+1}",
        description=description,
        detail=data.get("detail"),
        quantity=qty,
        unit=unit,
        price_level=PriceLevel.list_price,
        unit_price=price,
        total=round(qty * price, 2),
        sort_order=(len(q.lines) + 1) * 10,
        price_item_id=pi.id if pi else None,
    )
    db.add(line); db.flush()
    from app.routers.quotes import _recalc_quote
    _recalc_quote(q)
    return {
        "created": True,
        "quote_line_id": line.id, "quote_id": q.id,
        "total": line.total,
        "price_item_id": pi.id if pi else None,
        "price_item_name": pi.name if pi else None,
        "message": (f"Riga aggiunta alla quote #{q.id}: {line.description}, "
                    f"qty={line.quantity} {line.unit}, total €{line.total:.2f}."),
    }


def _h_propose_new_item_and_line(db: Session, data: dict) -> dict:
    """Scenario C — search-first AI fallback.

    In singola transazione:
      1. Crea una nuova `PriceItem` nel listino (richiede category_name)
      2. Crea una `QuoteLine` sulla quote indicata, legata alla voce appena creata

    Schema atteso in `data`:
      - quote_id (PK) o quote_number (stringa)        — obbligatorio
      - name (stringa)                                — obbligatorio (nome voce listino)
      - category_name (stringa)                       — obbligatorio
      - unit ("day"|"hour"|"flat", default "day")
      - price_list (numero)                           — obbligatorio (prezzo listino)
      - quantity (numero, default 1)                  — quantità nella quote
      - description? (alias di name se omesso)
      - keywords? (lista di stringhe, per matching futuro)
      - department_name?
      - section? ("A"|"B"|"C", default "A")
    """
    from app.models import QuoteLine, PriceLevel
    q = _resolve_quote(db, data)

    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Manca 'name' (nome voce listino)")
    cat_name = (data.get("category_name") or "").strip()
    if not cat_name:
        raise ValueError("Manca 'category_name' (la categoria è obbligatoria)")
    if data.get("price_list") in (None, ""):
        raise ValueError("Manca 'price_list' (prezzo listino della voce)")

    # Categoria: trova o crea
    cat = db.query(PriceCategory).filter(PriceCategory.name == cat_name).first()
    if not cat:
        cat = PriceCategory(name=cat_name)
        db.add(cat); db.flush()

    # Reparto opzionale
    dept_id = None
    dept_name = (data.get("department_name") or "").strip()
    if dept_name:
        d = db.query(Department).filter(Department.name == dept_name).first()
        if d:
            dept_id = d.id

    price = float(data["price_list"])
    unit = data.get("unit") or "day"

    pi = PriceItem(
        name=name,
        description=data.get("description") or name,
        unit=unit,
        price_list=price,
        price_average=price,
        price_low=price,
        category_id=cat.id,
        department_id=dept_id,
        keywords=data.get("keywords") or [],
        is_active=True,
    )
    db.add(pi); db.flush()

    qty = float(data.get("quantity") or 1)
    line = QuoteLine(
        quote_id=q.id,
        section=data.get("section") or "A",
        position=data.get("position") or f"A.{len(q.lines)+1}",
        description=data.get("description") or name,
        quantity=qty,
        unit=unit,
        price_level=PriceLevel.list_price,
        unit_price=price,
        total=round(qty * price, 2),
        sort_order=(len(q.lines) + 1) * 10,
        price_item_id=pi.id,
    )
    db.add(line); db.flush()

    from app.routers.quotes import _recalc_quote
    _recalc_quote(q)
    return {
        "created": True,
        "price_item_id": pi.id, "price_item_name": pi.name, "category": cat.name,
        "quote_line_id": line.id, "quote_id": q.id, "total": line.total,
        "message": (f"Voce listino '{pi.name}' creata e aggiunta alla quote #{q.id} "
                    f"(qty={line.quantity}, total €{line.total:.2f})."),
    }


def _h_propose_project_metadata(db: Session, data: dict) -> dict:
    p = _resolve_project(db, data)
    fields = ["length_minutes", "fps", "shooting_format", "delivery_format", "director"]
    updated = {}
    for f in fields:
        if f in data and data[f] not in (None, ""):
            val = str(data[f]) if f == "fps" else data[f]
            setattr(p, f, val)
            updated[f] = val
    return {"project_id": p.id, "code": p.code, "updated": updated}


def _h_web_search(db: Session, data: dict) -> dict:
    """Ricerca web read-only via Tavily, restituisce snippet testuali."""
    from app.services.web_search import tavily_search
    query = (data.get("query") or "").strip()
    if not query:
        raise ValueError("Manca 'query'")
    results = tavily_search(query, max_results=5)
    return {"query": query, "results": results}


# ── Settings registry handlers (v3.5.0-alpha.19) ─────────────
# Tre tool generici per scoprire/leggere/modificare qualsiasi area di settings
# registrata in `settings_registry.SCHEMAS`. Sostituiscono l'idea di una
# capability AI per ogni area. Per estendere a una nuova area: aggiungi una
# `SettingsSchema` al registry, niente codice qui da toccare.

def _h_list_settings_schemas(db: Session, data: dict) -> dict:
    from app.services.settings_registry import list_schemas
    schemas = list_schemas()
    return {
        "schemas": schemas,
        "message": (
            f"Aree configurabili: {', '.join(s['key'] for s in schemas)}. "
            "Usa read_setting per vedere lo stato corrente di un'area, "
            "update_setting per proporre modifiche."
        ),
    }


def _h_read_setting(db: Session, data: dict, *, user=None) -> dict:
    from app.services.settings_registry import get_schema
    key = (data.get("key") or "").strip()
    if not key:
        raise ValueError("Manca 'key' (es. 'working_hours', 'tenant_settings')")
    schema = get_schema(key)
    if not schema:
        raise ValueError(f"Schema settings '{key}' non trovato")
    state = schema.read(db, user)
    return {
        "key": key,
        "label": schema.label,
        "permission_required": schema.permission,
        "current": state,
        "fields": [f.to_dict() for f in schema.fields],
    }


def _h_update_setting(db: Session, data: dict, *, user=None) -> dict:
    from app.services.settings_registry import get_schema, can_user_access
    key = (data.get("key") or "").strip()
    if not key:
        raise ValueError("Manca 'key'")
    patch = data.get("patch") or {}
    if not isinstance(patch, dict) or not patch:
        raise ValueError("'patch' deve essere un dict non vuoto con i campi da modificare")
    schema = get_schema(key)
    if not schema:
        raise ValueError(f"Schema settings '{key}' non trovato")
    if user is not None and not can_user_access(schema, user):
        raise ValueError(
            f"Permesso negato: per modificare '{schema.label}' serve permesso "
            f"'{schema.permission}'"
        )
    result = schema.write(db, user, patch)
    applied = result.get("applied") or {}
    if not applied:
        return {
            "key": key,
            "label": schema.label,
            "applied": {},
            "current": result.get("current"),
            "message": f"Nessuna modifica effettiva su '{schema.label}' (i valori erano già corretti).",
        }
    diff_lines = [f"{k}: {v['old']} → {v['new']}" for k, v in applied.items()]
    return {
        "key": key,
        "label": schema.label,
        "applied": applied,
        "current": result.get("current"),
        "message": f"'{schema.label}' aggiornato. Cambi: " + " · ".join(diff_lines),
    }


def _h_propose_resource(db: Session, data: dict) -> dict:
    """Crea una nuova Resource (v3.5.0-alpha.33).

    Risolve il reparto via `department_id` (PK) o `department_name` (match esatto).
    `type` deve essere uno dei ResourceType supportati. Tariffe ignorate se 0/None.
    """
    from app.models import ResourceType
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Manca 'name'")
    type_str = (data.get("type") or "").strip()
    try:
        rtype = ResourceType(type_str)
    except Exception:
        raise ValueError(
            f"'type' non valido: '{type_str}'. Valori ammessi: "
            "person_internal, person_freelance, studio, equipment, software, vehicle."
        )

    # Risolvi reparto: id (PK) o name (string match esatto)
    dept_id = data.get("department_id")
    department = None
    if isinstance(dept_id, int) or (isinstance(dept_id, str) and str(dept_id).isdigit()):
        department = db.query(Department).filter(Department.id == int(dept_id)).first()
    if department is None:
        dept_name = (data.get("department_name") or "").strip()
        if dept_name:
            department = db.query(Department).filter(Department.name == dept_name).first()
            if not department:
                raise ValueError(
                    f"Reparto '{dept_name}' non trovato. Usa il PK numerico o il nome esatto "
                    "(vedi DEPARTMENTS nel contesto)."
                )

    # Tariffe: 0 e None considerati "non noto" → NULL in DB (consistente col modello)
    def _opt_num(key):
        v = data.get(key)
        if v is None: return None
        try:
            n = float(v)
            return n if n > 0 else None
        except Exception:
            return None

    color = (data.get("color") or "").strip() or "#6272f5"
    if not color.startswith("#") or len(color) not in (4, 7):
        color = "#6272f5"

    r = Resource(
        tenant_id=1,
        name=name,
        type=rtype,
        department_id=(department.id if department else None),
        role=(data.get("role") or None),
        description=(data.get("description") or None),
        daily_rate=_opt_num("daily_rate"),
        hourly_rate=_opt_num("hourly_rate"),
        email=(data.get("email") or None),
        phone=(data.get("phone") or None),
        internal_phone=(data.get("internal_phone") or None),
        color=color,
        is_active=True,
    )
    db.add(r); db.flush()
    return {
        "created": True,
        "resource_id": r.id,
        "name": r.name,
        "type": r.type.value if hasattr(r.type, "value") else r.type,
        "department_id": r.department_id,
        "department_name": (department.name if department else None),
        "message": (
            f"Risorsa '{r.name}' creata"
            + (f" nel reparto {department.name}" if department else "")
            + f" (id={r.id})."
        ),
    }


def _h_propose_booking(db: Session, data: dict) -> dict:
    """Crea un Booking con N risorse (E6 v3.4.20).

    Payload atteso:
      {
        "job_id" o "job_code": ...,
        "kind": "project" (default) | "internal_*",
        "job_cost_line_id"?: id lavorazione,
        "notes"?: str,
        "assignments": [
          {"resource_id" o "resource_name": ..., "start_datetime": ISO, "end_datetime": ISO}
        ]
      }
    """
    from app.models import Booking, BookingAssignment, BookingStatus, BookingKind, Resource, Job, JobCostLine
    from datetime import datetime as _dt
    CURRENT_TENANT = 1

    # Risolvi job (per kind=project)
    kind_str = (data.get("kind") or "project").strip()
    try:
        kind = BookingKind(kind_str)
    except Exception:
        kind = BookingKind.project
    job_id = None
    if kind == BookingKind.project:
        job_id = data.get("job_id")
        if not job_id and data.get("job_code"):
            j = db.query(Job).filter(Job.code == data["job_code"]).first()
            if not j:
                raise ValueError(f"Job '{data['job_code']}' non trovato")
            job_id = j.id
        if not job_id:
            raise ValueError("Manca job_id o job_code per kind=project")

    line_id = data.get("job_cost_line_id")
    if line_id:
        line = db.query(JobCostLine).filter(JobCostLine.id == line_id).first()
        if not line:
            raise ValueError(f"Lavorazione #{line_id} non trovata")
        if line.job_id != job_id:
            raise ValueError("Lavorazione non appartiene al job indicato")

    # Risolvi assignments
    raw_ass = data.get("assignments") or []
    if not isinstance(raw_ass, list) or not raw_ass:
        raise ValueError("Servono almeno 1 risorsa in 'assignments'")
    parsed = []
    for i, a in enumerate(raw_ass):
        rid = a.get("resource_id")
        if not rid and a.get("resource_name"):
            r = db.query(Resource).filter(Resource.name.ilike(a["resource_name"])).first()
            if not r:
                raise ValueError(f"Risorsa '{a['resource_name']}' non trovata")
            rid = r.id
        if not rid:
            raise ValueError(f"assignments[{i}]: serve resource_id o resource_name")
        s = a.get("start_datetime"); e = a.get("end_datetime")
        try:
            sd = _dt.fromisoformat(s) if isinstance(s, str) else s
            ed = _dt.fromisoformat(e) if isinstance(e, str) else e
        except Exception:
            raise ValueError(f"assignments[{i}]: date non valide")
        if not sd or not ed or ed <= sd:
            raise ValueError(f"assignments[{i}]: end_datetime > start_datetime richiesto")
        parsed.append({"resource_id": int(rid), "start_datetime": sd, "end_datetime": ed})

    # Conflict check
    for i, pa in enumerate(parsed):
        c = db.query(BookingAssignment).join(Booking).filter(
            Booking.tenant_id == CURRENT_TENANT,
            Booking.status != BookingStatus.cancelled,
            BookingAssignment.resource_id == pa["resource_id"],
            BookingAssignment.start_datetime < pa["end_datetime"],
            BookingAssignment.end_datetime > pa["start_datetime"],
        ).first()
        if c:
            raise ValueError(f"Conflitto su risorsa per assignments[{i}]")

    # Crea Booking + assignments
    env_s = min(pa["start_datetime"] for pa in parsed)
    env_e = max(pa["end_datetime"] for pa in parsed)
    b = Booking(
        tenant_id=CURRENT_TENANT,
        job_id=job_id, job_cost_line_id=line_id,
        start_datetime=env_s, end_datetime=env_e,
        status=BookingStatus.tentative, kind=kind,
        notes=data.get("notes"),
    )
    db.add(b); db.flush()
    for pa in parsed:
        db.add(BookingAssignment(
            booking_id=b.id, resource_id=pa["resource_id"],
            start_datetime=pa["start_datetime"], end_datetime=pa["end_datetime"],
        ))
    return {"booking_id": b.id, "assignments_count": len(parsed),
            "start": b.start_datetime.isoformat(), "end": b.end_datetime.isoformat()}


# ── v3.5.0-alpha.50: capability planning (move/resize/delete booking esistente) ──

def _assert_jcl_not_locked(db: Session, b: Booking) -> None:
    """v3.5.0-alpha.51.1 fix A2: blocca AI su booking la cui JobCostLine
    è già `in_batch`, `billed` o `paid`. Modificare un booking il cui maturato
    è stato trasmesso a un BillingBatch corromperebbe lo snapshot e il
    `total_accrued` rendendo le LossEntry non più tracciabili al booking
    originale. AI deve passare per il manager (cancel batch o emit refund)."""
    if not b.job_cost_line_id:
        return
    jcl = db.query(JobCostLine).filter(JobCostLine.id == b.job_cost_line_id).first()
    if not jcl:
        return
    locked = {JCLBillingStatus.in_batch, JCLBillingStatus.billed, JCLBillingStatus.paid}
    if jcl.billing_status in locked:
        raise ValueError(
            f"Booking #{b.id} non modificabile: la riga di costo (JCL #{jcl.id}) "
            f"è in stato `{jcl.billing_status.value}`. Il manager deve prima "
            f"ritirare/annullare il batch di fatturazione."
        )


def _resolve_booking_for_planning(db: Session, data: dict) -> Booking:
    """Helper comune per move/resize/delete: risolve booking_id obbligatorio."""
    CURRENT_TENANT = 1  # v3.5.0-alpha.51.1 fix A1
    bid = data.get("booking_id")
    if not bid:
        raise ValueError("Manca 'booking_id'")
    try:
        bid = int(bid)
    except (TypeError, ValueError):
        raise ValueError(f"booking_id non numerico: {bid}")
    b = db.query(Booking).filter(
        Booking.id == bid, Booking.tenant_id == CURRENT_TENANT,
    ).first()
    if not b:
        raise ValueError(f"Booking #{bid} non trovato")
    if b.status == BookingStatus.cancelled:
        raise ValueError(f"Booking #{bid} è già cancellato")
    _assert_jcl_not_locked(db, b)
    return b


def _h_propose_move_booking(db: Session, data: dict) -> dict:
    """Sposta un booking esistente di un delta temporale, opzionalmente
    cambiando risorsa/risorse degli assignment.

    Payload:
      {
        "booking_id": int (obbligatorio),
        "shift_minutes"?: int (positivo = avanti, negativo = indietro),
        "new_start_date"?: "YYYY-MM-DD" (alternativa: imposta nuova data ancorata
            a min start del booking, sposta TUTTI gli assignment del delta),
        "new_resource_id"?: int (cambia risorsa di TUTTI gli assignment),
        "assignments_remap"?: [{from_resource_id, to_resource_id}, ...] (rimappa
            risorse mantenendo la struttura)
      }
    Almeno uno tra shift_minutes / new_start_date / new_resource_id /
    assignments_remap deve essere fornito.

    Conflict check sui nuovi orari prima di applicare. Atomic.
    """
    from datetime import datetime as _dt, timedelta as _td, date as _d
    b = _resolve_booking_for_planning(db, data)

    shift_min = data.get("shift_minutes")
    new_start_date_str = data.get("new_start_date")
    new_resource_id = data.get("new_resource_id")
    remap_list = data.get("assignments_remap") or []

    if not any([shift_min, new_start_date_str, new_resource_id, remap_list]):
        raise ValueError(
            "Servono almeno uno tra: shift_minutes, new_start_date, "
            "new_resource_id, assignments_remap"
        )

    delta = _td(0)
    if shift_min:
        try:
            delta += _td(minutes=int(shift_min))
        except (TypeError, ValueError):
            raise ValueError(f"shift_minutes non numerico: {shift_min}")
    if new_start_date_str:
        try:
            new_d = _d.fromisoformat(new_start_date_str)
        except Exception:
            raise ValueError(f"new_start_date non valido (atteso YYYY-MM-DD): {new_start_date_str}")
        # Calcola delta giornaliero da min(start) a new_d
        cur_start_date = min(a.start_datetime for a in b.assignments).date()
        delta += _td(days=(new_d - cur_start_date).days)

    # Costruisci remap: from_resource_id → to_resource_id
    remap: dict[int, int] = {}
    if new_resource_id:
        try:
            target = int(new_resource_id)
        except (TypeError, ValueError):
            raise ValueError(f"new_resource_id non numerico: {new_resource_id}")
        # Verifica esistenza
        if not db.query(Resource).filter(Resource.id == target).first():
            raise ValueError(f"Risorsa #{target} non trovata")
        for a in b.assignments:
            remap[a.id] = target  # qui la chiave è assignment_id (univoca)
    for entry in remap_list:
        try:
            fr = int(entry["from_resource_id"])
            to = int(entry["to_resource_id"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("assignments_remap entry malformato (need from_resource_id, to_resource_id)")
        if not db.query(Resource).filter(Resource.id == to).first():
            raise ValueError(f"Risorsa #{to} non trovata")
        for a in b.assignments:
            if a.resource_id == fr:
                remap[a.id] = to

    # Calcola nuovi valori per ogni assignment
    new_values = []
    for a in b.assignments:
        ns = a.start_datetime + delta
        ne = a.end_datetime + delta
        nrid = remap.get(a.id, a.resource_id)
        new_values.append((a, ns, ne, nrid))

    # Conflict check per ogni assignment (esclude se stesso)
    for a, ns, ne, nrid in new_values:
        c = db.query(BookingAssignment).join(Booking).filter(
            Booking.status != BookingStatus.cancelled,
            BookingAssignment.id != a.id,
            BookingAssignment.resource_id == nrid,
            BookingAssignment.start_datetime < ne,
            BookingAssignment.end_datetime > ns,
        ).first()
        if c:
            raise ValueError(
                f"Conflitto: assignment #{a.id} su risorsa #{nrid} "
                f"({ns.strftime('%d/%m %H:%M')}→{ne.strftime('%H:%M')}) "
                f"overlap con assignment #{c.id}"
            )

    # Applica
    for a, ns, ne, nrid in new_values:
        a.start_datetime = ns
        a.end_datetime = ne
        a.resource_id = nrid
    # Ricalcola envelope booking
    b.start_datetime = min(a.start_datetime for a in b.assignments)
    b.end_datetime = max(a.end_datetime for a in b.assignments)
    # v3.5.0-alpha.51.1 fix C2: ricomputa la cost line. Se cambiano risorse
    # cross-reparto, il rate effettivo può variare; se il booking è done, le
    # ore stesse spostano `total_accrued`. Allineato a planning.delete_booking.
    try:
        from app.services.cost_line_sync import recompute_for_booking
        recompute_for_booking(db, b)
    except Exception as _e:
        logger.warning(f"recompute_for_booking failed in propose_move_booking: {_e}")
    # Audit log (A4)
    try:
        db.add(BookingChange(
            booking_id=b.id, kind="ai_move",
            summary=f"AI move ({int(delta.total_seconds()/60)}min, {sum(1 for a in b.assignments if a.id in remap)} risorse rimappate)",
            payload={"delta_minutes": int(delta.total_seconds()/60), "resources_changed": sum(1 for a in b.assignments if a.id in remap)},
        ))
    except Exception:
        pass
    return {
        "booking_id": b.id,
        "assignments_count": len(b.assignments),
        "new_start": b.start_datetime.isoformat(),
        "new_end": b.end_datetime.isoformat(),
        "shifted_minutes": int(delta.total_seconds() / 60),
        "resources_changed": sum(1 for a in b.assignments if a.id in remap),
    }


def _h_propose_resize_booking(db: Session, data: dict) -> dict:
    """Cambia la durata di un booking modificando end (o start) di tutti gli
    assignment del medesimo delta. Mantenere proporzioni se booking è split
    (più assignment stessa risorsa) — il delta viene applicato all'envelope:
    sib intermedi shiftano in time per mantenere la pausa.

    Payload:
      {
        "booking_id": int,
        "delta_minutes": int (positivo = allunga end, negativo = accorcia)
      }
    """
    from datetime import timedelta as _td
    b = _resolve_booking_for_planning(db, data)
    dm = data.get("delta_minutes")
    if dm is None:
        raise ValueError("Manca 'delta_minutes'")
    try:
        dm = int(dm)
    except (TypeError, ValueError):
        raise ValueError(f"delta_minutes non numerico: {dm}")
    if dm == 0:
        raise ValueError("delta_minutes = 0, niente da fare")

    # Trova l'assignment con end massimo (l'ultimo) e applica delta a esso
    # Per gli altri (split intermedi) lascia invariati. Comportamento intuitivo:
    # "estendi/accorcia il booking" = sposta l'end finale.
    last_a = max(b.assignments, key=lambda a: a.end_datetime)
    new_end = last_a.end_datetime + _td(minutes=dm)
    if new_end <= last_a.start_datetime:
        raise ValueError(
            f"Resize porta end <= start (delta {dm}min troppo negativo). "
            f"Per cancellare il booking usa propose_delete_booking."
        )
    # Conflict check sull'estensione
    c = db.query(BookingAssignment).join(Booking).filter(
        Booking.status != BookingStatus.cancelled,
        BookingAssignment.id != last_a.id,
        BookingAssignment.resource_id == last_a.resource_id,
        BookingAssignment.start_datetime < new_end,
        BookingAssignment.end_datetime > last_a.start_datetime,
    ).first()
    if c:
        raise ValueError(
            f"Resize crea conflitto su risorsa #{last_a.resource_id} con assignment #{c.id}"
        )
    last_a.end_datetime = new_end
    b.end_datetime = max(a.end_datetime for a in b.assignments)
    # v3.5.0-alpha.51.1 fix C2: ricomputa cost line. Se booking è done, le
    # ore-uomo cambiano e quantity_actual / total_accrued vanno aggiornati.
    try:
        from app.services.cost_line_sync import recompute_for_booking
        recompute_for_booking(db, b)
    except Exception as _e:
        logger.warning(f"recompute_for_booking failed in propose_resize_booking: {_e}")
    # Audit log (A4)
    try:
        db.add(BookingChange(
            booking_id=b.id, kind="ai_resize",
            summary=f"AI resize ({dm:+d}min)",
            payload={"delta_minutes": dm, "resized_assignment_id": last_a.id},
        ))
    except Exception:
        pass
    return {
        "booking_id": b.id,
        "delta_minutes": dm,
        "new_end": b.end_datetime.isoformat(),
        "resized_assignment_id": last_a.id,
    }


def _h_propose_delete_booking(db: Session, data: dict) -> dict:
    """Cancella un booking (soft-delete via status=cancelled).

    Payload: {"booking_id": int, "reason"?: str}

    Soft-delete preserva audit + permette undo via cestino. Il backend
    `delete_booking` standard fa la stessa cosa + recompute cost line.
    """
    b = _resolve_booking_for_planning(db, data)
    reason = (data.get("reason") or "").strip() or None
    b.status = BookingStatus.cancelled
    if reason:
        existing = b.notes or ""
        b.notes = (existing + ("\n" if existing else "") + f"[AI cancel] {reason}").strip()
    # Recompute cost line (le ore done finiscono al netto)
    try:
        from app.services.cost_line_sync import recompute_for_booking
        recompute_for_booking(db, b)
    except Exception as _e:
        logger.warning(f"recompute_for_booking failed in propose_delete_booking: {_e}")
    # v3.5.0-alpha.51.1 fix A4: log audit (planning.delete_booking lo fa già)
    try:
        db.add(BookingChange(
            booking_id=b.id, kind="ai_delete",
            summary=f"AI cancel" + (f": {reason}" if reason else ""),
            payload={"reason": reason},
        ))
    except Exception:
        pass
    return {"booking_id": b.id, "status": "cancelled", "reason": reason}


_ACTION_HANDLERS = {
    "propose_client":            _h_propose_client,
    "propose_project":           _h_propose_project,
    "propose_project_metadata":  _h_propose_project_metadata,
    "propose_quote":             _h_propose_quote,
    "update_quote":              _h_update_quote,
    "propose_quote_line":        _h_propose_quote_line,
    "propose_price_item":        _h_propose_price_item,
    "propose_new_item_and_line": _h_propose_new_item_and_line,
    "propose_resource":          _h_propose_resource,
    "propose_booking":           _h_propose_booking,
    # v3.5.0-alpha.50 — Planning operations
    "propose_move_booking":      _h_propose_move_booking,
    "propose_resize_booking":    _h_propose_resize_booking,
    "propose_delete_booking":    _h_propose_delete_booking,
    "web_search":                _h_web_search,
    # v3.5.0-alpha.19 — Settings registry tools
    "list_settings_schemas":     _h_list_settings_schemas,
    "read_setting":              _h_read_setting,
    "update_setting":            _h_update_setting,
}


# ── Review quotazione (legacy, immutato funzionalmente) ──────

REVIEW_SYSTEM_PROMPT = """Sei un senior producer di postproduzione. Analizza una quotazione e dai 3-5 osservazioni concrete sul suo contenuto.

Focus su:
- Voci sospette mancanti per il tipo di progetto
- Quantità che sembrano sotto/sovrastimate
- Mix di prezzi list/average/low poco coerente
- Rischi di sforamento identificabili
- Ottimizzazioni possibili sullo sconto pacchetto

Formato output: lista di osservazioni in markdown. Una osservazione per riga, inizia ognuna con un'icona pertinente (! per rischio, * per suggerimento, + per conferma positiva).

Sii schietto e concreto. Meglio 3 osservazioni utili che 10 generiche."""


def review_quote(db: Session, quote_id: int, user_id: Optional[int] = None) -> Optional[str]:
    provider = get_provider_for_user(user_id, db)
    if not provider:
        return None
    q = db.query(Quote).filter(Quote.id == quote_id).first()
    if not q:
        return None
    context = build_context(db, project_id=q.project_id, quote_id=q.id)
    user_prompt = f"Ecco la quotazione da analizzare:\n\n{context}\n\nFornisci la tua review."
    try:
        return provider.complete(REVIEW_SYSTEM_PROMPT, user_prompt,
                                 max_tokens=1500, temperature=0.4)
    except Exception as e:
        logger.error(f"Quote review failed: {e}")
        return None
