from app.services.ai_assistant import build_system_prompt


def test_prompt_contains_email_guidance_tools_mode():
    p = build_system_prompt(None, use_tools=True)
    assert "email" in p.lower()
    assert "propose_activity" in p
    assert "update_client" in p


def test_prompt_contains_email_guidance_legacy_mode():
    p = build_system_prompt(None, use_tools=False)
    assert "email" in p.lower()
