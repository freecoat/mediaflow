"""Regressione prompt parser: il prompt di parse_delivery_template deve chiedere
all'AI la naming convention in forma STRUTTURATA a token (α.172.182, NC-T4).

Niente AI reale: si verifica solo che la costante prompt contenga le istruzioni
chiave, per non perdere la struttura in futuri refactor del prompt."""
from app.services import deliverables_parser as dp


def test_parser_prompt_mentions_structured_naming():
    prompt_text = dp.PARSE_TEMPLATE_SYSTEM_PROMPT
    assert "naming_convention" in prompt_text
    assert "pattern" in prompt_text
    assert "raw_note" in prompt_text


def test_parser_prompt_lists_valid_tokens():
    # I token citati nel prompt devono essere tra quelli noti (naming_helper).
    from app.services.naming_helper import KNOWN_TOKENS
    prompt_text = dp.PARSE_TEMPLATE_SYSTEM_PROMPT
    for tok in ("project_code", "film_name", "resolution", "lang_audio", "date_compact"):
        assert tok in KNOWN_TOKENS  # sanity: il token esiste davvero
        assert tok in prompt_text  # ed è citato nel prompt


def test_parser_prompt_requests_per_item_naming():
    # Il prompt deve richiedere naming anche per singola consegna (deliverables[]).
    prompt_text = dp.PARSE_TEMPLATE_SYSTEM_PROMPT
    assert "deliverables" in prompt_text


def test_pass2_prompt_mentions_per_item_naming():
    # Anche il parser per-item (delivery_items_parser, PASS2) deve chiedere la
    # naming convention strutturata per la singola voce (α.172.182, NC-T4).
    from app.services import delivery_items_parser as dip
    txt = dip.PASS2_SYSTEM_PROMPT
    assert "naming_convention" in txt
    assert "pattern" in txt
