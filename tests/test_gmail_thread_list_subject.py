"""Lista thread /mail: l'oggetto deve arrivare dagli header, non lo snippet.

Regressione α.172.247: `users.threads.list` NON restituisce header (solo id/snippet/
historyId), quindi il subject non esisteva e la UI ripiegava sullo snippet — cioè
mostrava il CORPO al posto dell'oggetto. I test di F1 mockavano `list_threads` a
livello di router, quindi non esercitavano mai questa logica e inventavano una
forma di risposta che Gmail non manda. Qui si mocka `_gmail_request` (punto unico
di mock dichiarato in gmail.py) con le forme REALI dell'API.
"""
import app.services.gmail as gmail


def _fake_request(threads_page, thread_details, calls=None):
    """Emula _gmail_request con le forme reali dell'API Gmail."""
    def _fn(method, path, token, params=None, body=None):
        if calls is not None:
            calls.append((method, path, dict(params or {})))
        if path == "/threads":
            return threads_page
        if path.startswith("/threads/"):
            tid = path.rsplit("/", 1)[-1]
            if tid not in thread_details:
                raise RuntimeError(f"404 thread {tid}")
            return thread_details[tid]
        raise AssertionError(f"path inatteso: {path}")
    return _fn


def _msg(subject, frm, date, snippet):
    return {"id": "M-" + subject, "payload": {"headers": [
        {"name": "Subject", "value": subject},
        {"name": "From", "value": frm},
        {"name": "Date", "value": date},
    ]}, "snippet": snippet}


def test_list_threads_espone_subject_dagli_header(monkeypatch):
    """La lista deve portare l'oggetto vero, non lo snippet del corpo."""
    monkeypatch.setattr(gmail, "get_valid_access_token", lambda db, uid, prov: "tok")
    threads_page = {"threads": [{"id": "T1", "snippet": "Ciao Matteo, in allegato il"}],
                    "nextPageToken": "NEXT"}
    details = {"T1": {"id": "T1", "messages": [
        _msg("Preventivo DI Queer", "anna@a24.com", "Mon, 14 Jul 2026 10:00:00 +0200",
             "Ciao Matteo, in allegato il")]}}
    monkeypatch.setattr(gmail, "_gmail_request", _fake_request(threads_page, details))

    out = gmail.list_threads(None, 1)
    t = out["threads"][0]
    assert t["subject"] == "Preventivo DI Queer"
    assert t["snippet"] == "Ciao Matteo, in allegato il"
    assert t["subject"] != t["snippet"]
    assert t["from"] == "anna@a24.com"
    assert t["date"] == "Mon, 14 Jul 2026 10:00:00 +0200"
    assert out["next_page_token"] == "NEXT"


def test_list_threads_subject_dal_primo_messaggio_data_dall_ultimo(monkeypatch):
    """Come Gmail: oggetto del thread = primo messaggio, data/mittente = più recente."""
    monkeypatch.setattr(gmail, "get_valid_access_token", lambda db, uid, prov: "tok")
    threads_page = {"threads": [{"id": "T1", "snippet": "ultimo corpo"}]}
    details = {"T1": {"id": "T1", "messages": [
        _msg("Consegna Netflix", "anna@a24.com", "Mon, 14 Jul 2026 10:00:00 +0200", "primo"),
        _msg("Re: Consegna Netflix", "bob@a24.com", "Tue, 15 Jul 2026 09:00:00 +0200", "ultimo"),
    ]}}
    monkeypatch.setattr(gmail, "_gmail_request", _fake_request(threads_page, details))

    t = gmail.list_threads(None, 1)["threads"][0]
    assert t["subject"] == "Consegna Netflix"
    assert t["from"] == "bob@a24.com"
    assert t["date"] == "Tue, 15 Jul 2026 09:00:00 +0200"
    assert t["message_count"] == 2


def test_list_threads_chiede_solo_metadata_non_il_corpo(monkeypatch):
    """Efficienza: format=metadata + metadataHeaders, mai format=full sulla lista."""
    monkeypatch.setattr(gmail, "get_valid_access_token", lambda db, uid, prov: "tok")
    calls = []
    threads_page = {"threads": [{"id": "T1", "snippet": "s"}]}
    details = {"T1": {"id": "T1", "messages": [_msg("Oggetto", "a@b.c", "Mon", "s")]}}
    monkeypatch.setattr(gmail, "_gmail_request", _fake_request(threads_page, details, calls))

    gmail.list_threads(None, 1)
    detail_calls = [c for c in calls if c[1].startswith("/threads/")]
    assert len(detail_calls) == 1, "un solo fetch metadata per thread"
    params = detail_calls[0][2]
    assert params.get("format") == "metadata"
    assert "Subject" in str(params.get("metadataHeaders"))


def test_list_threads_degrada_se_il_metadata_fallisce(monkeypatch):
    """Contratto best-effort di gmail.py: mai eccezione al chiamante.
    Se il dettaglio di un thread fallisce, la lista resta utilizzabile."""
    monkeypatch.setattr(gmail, "get_valid_access_token", lambda db, uid, prov: "tok")
    threads_page = {"threads": [{"id": "T1", "snippet": "corpo"}, {"id": "T2", "snippet": "corpo2"}]}
    details = {"T2": {"id": "T2", "messages": [_msg("Oggetto vero", "a@b.c", "Mon", "corpo2")]}}
    monkeypatch.setattr(gmail, "_gmail_request", _fake_request(threads_page, details))

    out = gmail.list_threads(None, 1)
    assert len(out["threads"]) == 2, "il thread rotto non sparisce dalla lista"
    assert out["threads"][0]["subject"] == ""      # ignoto, non lo snippet
    assert out["threads"][0]["snippet"] == "corpo"
    assert out["threads"][1]["subject"] == "Oggetto vero"


def test_list_threads_senza_token_resta_vuota(monkeypatch):
    monkeypatch.setattr(gmail, "get_valid_access_token", lambda db, uid, prov: None)
    assert gmail.list_threads(None, 1) == {"threads": [], "next_page_token": None}
