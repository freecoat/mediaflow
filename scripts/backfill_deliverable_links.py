"""
MediaFlow — α.172.202 backfill: ripristina i link capitolato sulle consegne orfane.

Per ogni JobDeliverable con quote_line_id valorizzato ma con delivery_template_id
e/o section_label NULL, copia i valori dalla QuoteLine sorgente.

Sequenza di risoluzione delivery_template_id:
  1. quote_line.delivery_template_id (settato da α.172.202 in poi)
  2. DeliveryItem.delivery_template_id (per righe pre-α.172.202 che hanno
     delivery_item_id ma non delivery_template_id sulla QuoteLine)

Risoluzione delivery_item_id:
  - Se JobDeliverable.delivery_item_id è NULL ma quote_line.delivery_item_id è
    valorizzato, copia il valore (es. bucket mono-item non propagato in versioni
    precedenti).

Idempotente: elabora solo le righe che necessitano di aggiornamento.

Eseguire una sola volta dopo il deploy di α.172.202:
    python scripts/backfill_deliverable_links.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import JobDeliverable, QuoteLine


def backfill(session) -> dict:
    """Riempie i campi mancanti sui JobDeliverable orfani.

    Restituisce un dizionario con i conteggi:
        deliverables_scanned  — totale righe esaminate
        section_label_filled  — righe con section_label compilato
        template_filled       — righe con delivery_template_id compilato
        item_filled           — righe con delivery_item_id compilato
    """
    counts = {
        "deliverables_scanned": 0,
        "section_label_filled": 0,
        "template_filled": 0,
        "item_filled": 0,
    }

    # Carica tutti i JobDeliverable con un quote_line_id valorizzato e almeno
    # uno dei tre campi target NULL. Processa tutti i tenant.
    candidates = (
        session.query(JobDeliverable)
        .filter(
            JobDeliverable.quote_line_id.isnot(None),
        )
        .all()
    )

    # Cache DeliveryItem.delivery_template_id per evitare query ripetute.
    # Importazione lazy per evitare dipendenze circolari al momento del boot.
    from app.models import DeliveryItem

    di_template_cache: dict[int, int | None] = {}

    def _di_template(di_id: int | None) -> int | None:
        if di_id is None:
            return None
        if di_id not in di_template_cache:
            di = session.get(DeliveryItem, di_id)
            di_template_cache[di_id] = di.delivery_template_id if di else None
        return di_template_cache[di_id]

    # α.172.203 — mappa broadcaster→template_id per tenant: ultimo fallback per
    # le consegne orfane che hanno solo section_label (es. bucket multi-item Sky
    # senza scelta item, riga pre-α.172.202). Il section_label deriva da
    # DeliveryTemplate.broadcaster, quindi il match esatto rilinka al capitolato
    # a livello template (l'item specifico resta scegliibile in planning).
    from app.models import DeliveryTemplate
    bcast_cache: dict[int, dict[str, int]] = {}

    def _template_by_broadcaster(tenant_id: int, label: str | None) -> int | None:
        if not label:
            return None
        if tenant_id not in bcast_cache:
            m: dict[str, int] = {}
            for t in (session.query(DeliveryTemplate)
                      .filter(DeliveryTemplate.tenant_id == tenant_id).all()):
                if t.broadcaster:
                    m.setdefault(t.broadcaster.strip(), t.id)
            bcast_cache[tenant_id] = m
        return bcast_cache[tenant_id].get(label.strip())

    # Cache QuoteLine per evitare N query ripetute sullo stesso set.
    line_cache: dict[int, QuoteLine | None] = {}

    def _get_line(line_id: int) -> QuoteLine | None:
        if line_id not in line_cache:
            line_cache[line_id] = session.get(QuoteLine, line_id)
        return line_cache[line_id]

    for d in candidates:
        counts["deliverables_scanned"] += 1
        needs_update = (
            d.section_label is None
            or d.delivery_template_id is None
            or d.delivery_item_id is None
        )
        if not needs_update:
            continue

        line = _get_line(d.quote_line_id)
        if line is None:
            # QuoteLine cancellata (soft-delete o fisica): salta.
            continue

        # --- section_label ---
        if d.section_label is None and line.section_label:
            d.section_label = line.section_label
            counts["section_label_filled"] += 1

        # --- delivery_template_id ---
        if d.delivery_template_id is None:
            tmpl_id = line.delivery_template_id
            if tmpl_id is None:
                # Fallback: ricava il template dall'item della QuoteLine (se
                # ha delivery_item_id ma non delivery_template_id — righe
                # create con versioni precedenti ad α.172.202).
                tmpl_id = _di_template(line.delivery_item_id)
                if tmpl_id is None:
                    # Secondo fallback: dall'item del deliverable stesso
                    # (potrebbe essere stato settato in altri path).
                    tmpl_id = _di_template(d.delivery_item_id)
                if tmpl_id is None:
                    # Terzo fallback (α.172.203): match section_label↔broadcaster.
                    tmpl_id = _template_by_broadcaster(
                        d.tenant_id, d.section_label or line.section_label)
            if tmpl_id is not None:
                d.delivery_template_id = tmpl_id
                counts["template_filled"] += 1

        # --- delivery_item_id ---
        if d.delivery_item_id is None and line.delivery_item_id is not None:
            d.delivery_item_id = line.delivery_item_id
            counts["item_filled"] += 1

    session.commit()
    return counts


if __name__ == "__main__":
    db = SessionLocal()
    try:
        result = backfill(db)
        print("Backfill completato:")
        print(f"  Deliverable esaminati : {result['deliverables_scanned']}")
        print(f"  section_label compilati: {result['section_label_filled']}")
        print(f"  delivery_template_id   : {result['template_filled']}")
        print(f"  delivery_item_id       : {result['item_filled']}")
    finally:
        db.close()
