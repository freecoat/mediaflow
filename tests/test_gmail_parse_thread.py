from app.services import gmail


def test_parse_inbox_fragment():
    assert gmail.parse_gmail_thread_id(
        "https://mail.google.com/mail/u/0/#inbox/FMfcgzABC123") == "FMfcgzABC123"


def test_parse_label_fragment():
    assert gmail.parse_gmail_thread_id(
        "https://mail.google.com/mail/u/0/#label/Clienti/FMfcgzXYZ") == "FMfcgzXYZ"


def test_parse_search_fragment():
    assert gmail.parse_gmail_thread_id(
        "https://mail.google.com/mail/u/2/#search/foo/FMfcgzQ9") == "FMfcgzQ9"


def test_parse_th_param():
    assert gmail.parse_gmail_thread_id(
        "https://mail.google.com/mail/u/0/?th=abc123def") == "abc123def"


def test_parse_non_gmail_none():
    assert gmail.parse_gmail_thread_id("https://example.com/x") is None


def test_parse_gmail_no_id_none():
    assert gmail.parse_gmail_thread_id("https://mail.google.com/mail/u/0/#inbox") is None
