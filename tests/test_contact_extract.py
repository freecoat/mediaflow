from app.services.contact_extract import extract_from_thread, _parse_address


def test_parse_address_display_name_and_bare():
    assert _parse_address('"Mario Rossi" <mario@acme.com>') == {"name": "Mario Rossi", "email": "mario@acme.com"}
    assert _parse_address("mario@acme.com") == {"name": "mario", "email": "mario@acme.com"}
    assert _parse_address("") is None
    assert _parse_address("not an address") is None


def test_extract_from_thread_dedups_participants_by_email():
    thread = {
        "id": "T1",
        "messages": [
            {"from": "Mario Rossi <mario@acme.com>", "to": "Noi <noi@casa.it>", "cc": "",
             "body_text": "Ciao,\ngrazie.\n"},
            {"from": "Noi <noi@casa.it>", "to": "Mario Rossi <mario@acme.com>", "cc": "",
             "body_text": "Prego."},
        ],
    }
    cands = extract_from_thread(thread)
    emails = sorted(c["email"] for c in cands)
    assert emails == ["mario@acme.com", "noi@casa.it"]


def test_extract_pulls_phone_and_role_from_signature_block():
    body = (
        "Ciao,\n\nconfermo l'invio dei materiali.\n\n"
        "Mario Rossi\nDIT Supervisor\nAcme Post S.r.l.\n"
        "Tel: +39 02 1234 5678\nmario@acme.com\n"
    )
    thread = {
        "id": "T1",
        "messages": [{"from": "Mario Rossi <mario@acme.com>", "to": "a@b.com", "cc": "",
                      "body_text": body}],
    }
    cands = extract_from_thread(thread)
    m = next(c for c in cands if c["email"] == "mario@acme.com")
    assert m["phone"] and "1234" in m["phone"]
    assert m["company_text"] and "acme" in m["company_text"].lower()
    assert m["source"] == "email"


def test_extract_ignores_quoted_reply_chain_for_signature():
    body = (
        "Va bene, procedo.\n\nMario Rossi\nProduttore\n\n"
        "Il giorno 1 luglio 2026 Anna Bianchi ha scritto:\n"
        "> vecchio messaggio\n> altra riga citata\n"
    )
    thread = {
        "id": "T1",
        "messages": [{"from": "mario@acme.com", "to": "a@b.com", "cc": "", "body_text": body}],
    }
    cands = extract_from_thread(thread)
    m = next(c for c in cands if c["email"] == "mario@acme.com")
    assert m["role"] == "Produttore"


def test_extract_empty_thread_returns_empty_list():
    assert extract_from_thread({"id": "T1", "messages": []}) == []
    assert extract_from_thread({}) == []
