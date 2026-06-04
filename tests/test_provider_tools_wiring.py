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


def test_openai_supports_tools_and_parses(monkeypatch):
    from app.services.ai_provider import OpenAIProvider, ProviderConfig
    p = OpenAIProvider(ProviderConfig(provider="openai", api_key="x"))
    assert p.supports_tools() is True
    monkeypatch.setattr(p, "_post_chat", lambda payload: {
        "choices": [{"message": {"content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "read_quote_lines", "arguments": "{\"quote_id\": 5}"}}]}}]})
    resp = p.chat_with_tools([{"role": "user", "content": "x"}], system=None,
                             tools=[{"name": "read_quote_lines", "description": "d"}])
    assert resp.tool_uses[0].input == {"quote_id": 5}


def test_ollama_supports_tools_and_object_args(monkeypatch):
    from app.services.ai_provider import OllamaProvider, ProviderConfig
    p = OllamaProvider(ProviderConfig(provider="ollama"))
    assert p.supports_tools() is True
    monkeypatch.setattr(p, "_post_chat", lambda payload: {
        "choices": [{"message": {"content": "", "tool_calls": [
            {"function": {"name": "read_quote_lines", "arguments": {"quote_number": "Q-9"}}}]}}]})
    resp = p.chat_with_tools([{"role": "user", "content": "x"}], system=None,
                             tools=[{"name": "read_quote_lines", "description": "d"}])
    assert resp.tool_uses[0].input == {"quote_number": "Q-9"}


def test_ollama_post_chat_normalizes_message(monkeypatch):
    # Ollama /api/chat ritorna {"message": {...}} senza "choices": _post_chat normalizza.
    from app.services.ai_provider import OllamaProvider, ProviderConfig
    p = OllamaProvider(ProviderConfig(provider="ollama"))
    class _R:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "ciao", "tool_calls": []}}
    class _C:
        def __init__(self, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k): return _R()
    monkeypatch.setattr("app.services.ai_provider.httpx.Client", _C)
    data = p._post_chat({"model": p.model, "messages": [], "tools": [], "max_tokens": 100, "temperature": 0.3})
    assert data["choices"][0]["message"]["content"] == "ciao"
