"""Regressione numerazione quote — v3.5.0-alpha.172.145.

Bug trovato durante test estensivo (30 mag): `_next_quote_number_progressive`
riemetteva un numero base già usato da una quote attiva quando il contatore
`NumberingConfig.current_seq` era disallineato dal max reale (versioning -vN e
import snapshot non bumpano il contatore) E il -v1 originale era stato cestinato
(bin-rename libera la stringa esatta). La check ora rileva anche la collisione
sul BASE tra quote attive e ricade sullo scan autoritativo.
"""
from datetime import date
import pytest
from app.models import models as m
from app.routers.quotes import _next_quote_number_progressive

Y = date.today().year


def _seed_counter(db, seq, year=None):
    db.add(m.NumberingConfig(
        tenant_id=1, doc_type="quote", format_pattern="Q-{YYYY}-{NNN}",
        reset_yearly=True, current_year=year or Y, current_seq=seq,
    ))
    db.flush()


def _add_quote(db, number, project_id=1):
    db.add(m.Quote(tenant_id=1, number=number, title="t",
                   project_id=project_id, client_id=1, issue_date=date.today()))
    db.flush()


def test_numbering_fresh_db(db):
    _seed_counter(db, 0)
    assert _next_quote_number_progressive(db) == f"Q-{Y}-001-v1"


def test_numbering_counter_behind_real_max_no_base_collision(db):
    # Contatore a 7 ma esiste già una quote ATTIVA con base 008 (versione v2).
    # Senza fix → gen_doc_code dà 008 e (008-v1 libero) riemette Q-YYYY-008-v1
    # collidendo col base 008. Con fix → fallback scan → 009.
    _seed_counter(db, 7)
    _add_quote(db, f"Q-{Y}-008-v2")
    result = _next_quote_number_progressive(db)
    assert not result.startswith(f"Q-{Y}-008"), f"collisione base 008: {result}"
    assert result == f"Q-{Y}-009-v1"


def test_numbering_ignores_binned_quotes(db):
    # Quote cestinate (bin-rename ~Bn~) NON devono contare nello scan.
    _seed_counter(db, 0)
    _add_quote(db, f"Q-{Y}-005-v1")
    q = db.query(m.Quote).filter_by(number=f"Q-{Y}-005-v1").first()
    # simula bin-delete: rename + soft-delete
    q.number = f"~B{q.id}~Q-{Y}-005-v1"
    from datetime import datetime
    q.deleted_at = datetime.utcnow()
    db.flush()
    # nessuna quote attiva Q-YYYY-* → next = 001 (binnata ignorata dal prefisso)
    assert _next_quote_number_progressive(db) == f"Q-{Y}-001-v1"
