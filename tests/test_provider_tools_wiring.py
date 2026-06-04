from app.services.ai_provider import DeepseekProvider, PerplexityProvider, ProviderConfig, ToolUseResponse


def _fake_chat_response(tool_name="read_quote_lines"):
    return {"choices": [{"message": {
        "content": "",
        "tool_calls": [{"id": "call_0", "type": "function",
                        "function": {"name": tool_name, "arguments": "{\"quote_id\": 18}"}}],
    }}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def test_deepseek_supports_tools():
    p = DeepseekProvider(ProviderConfig(provider="deepseek", api_key="x"))
    assert p.supports_tools() is True


def test_deepseek_chat_with_tools_parses_tool_calls(monkeypatch):
    p = DeepseekProvider(ProviderConfig(provider="deepseek", api_key="x"))
    monkeypatch.setattr(p, "_post_chat", lambda payload: _fake_chat_response())
    resp = p.chat_with_tools([{"role": "user", "content": "conta consegne v4"}],
                             system="SYS", tools=[{"name": "read_quote_lines", "description": "d",
                                                   "input_schema": {"type": "object", "properties": {}}}])
    assert isinstance(resp, ToolUseResponse)
    assert resp.tool_uses[0].name == "read_quote_lines"
    assert resp.tool_uses[0].input == {"quote_id": 18}


def test_deepseek_chat_with_tools_sends_tools_in_payload(monkeypatch):
    p = DeepseekProvider(ProviderConfig(provider="deepseek", api_key="x"))
    captured = {}
    def _cap(payload):
        captured.update(payload)
        return _fake_chat_response()
    monkeypatch.setattr(p, "_post_chat", _cap)
    p.chat_with_tools([{"role": "user", "content": "x"}], system="SYS",
                      tools=[{"name": "read_quote_lines", "description": "d"}])
    assert captured["model"]  # modello presente
    assert captured["tools"][0]["function"]["name"] == "read_quote_lines"
    assert captured["messages"][0] == {"role": "system", "content": "SYS"}


def test_perplexity_supports_tools():
    p = PerplexityProvider(ProviderConfig(provider="perplexity", api_key="x"))
    assert p.supports_tools() is True


def test_deepseek_post_still_returns_content(monkeypatch):
    # back-compat: _post (usato da chat/complete) continua a ritornare la stringa content
    p = DeepseekProvider(ProviderConfig(provider="deepseek", api_key="x"))
    monkeypatch.setattr(p, "_post_chat", lambda payload: {"choices": [{"message": {"content": "ciao"}}]})
    assert p._post({"model": "m", "messages": []}) == "ciao"
