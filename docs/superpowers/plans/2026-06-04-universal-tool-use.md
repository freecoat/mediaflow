# Tool-use universale Copilot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps usano checkbox `- [ ]`.

**Goal:** dare al Copilot l'uso dei tool con qualsiasi modello OpenAI-compatible (OpenAI, DeepSeek, Perplexity, Ollama, e endpoint locali via base_url), oltre a Claude già supportato.

**Architecture:** modulo di conversione puro `openai_tools.py` (canonico Anthropic ↔ OpenAI) + `OpenAICompatToolsMixin` che implementa `chat_with_tools` usando `_post_chat` di ciascun provider. Il loop `advance_loop` resta provider-agnostico (formato canonico Anthropic). Claude invariato; provider senza tool → fallback legacy markdown.

**Tech Stack:** FastAPI/SQLAlchemy non toccati; Python puro per le conversioni; pytest con monkeypatch (zero HTTP reale).

**Contratti chiave (già esistenti in `app/services/ai_provider.py`):**
- `ToolUse(id: str, name: str, input: dict)`.
- `ToolUseResponse(text, tool_uses: list[ToolUse], stop_reason, raw_assistant_message)`.
- `advance_loop` appende `resp.raw_assistant_message` ai messages e costruisce tool_result canonici `{role:"user", content:[{"type":"tool_result","tool_use_id":id,"content":str}]}`. → **`raw_assistant_message` DEVE essere in formato canonico Anthropic** (`{"role":"assistant","content":[blocks]}`).
- Tool descriptors: `app/services/ai_tools.py:TOOLS` = `[{name, description, input_schema, category}]`.

---

### Task 1: `openai_tools.py` — conversioni pure + test

**Files:**
- Create: `app/services/openai_tools.py`
- Test: `tests/test_openai_tools.py`

- [ ] **Step 1: test che falliscono**

```python
# tests/test_openai_tools.py
import json
from app.services.ai_provider import ToolUse, ToolUseResponse
from app.services.openai_tools import (
    to_openai_tools, to_openai_messages, from_openai_message,
)


def test_to_openai_tools_maps_schema():
    tools = [{"name": "read_quote_lines", "description": "Legge righe",
              "input_schema": {"type": "object", "properties": {"quote_id": {"type": "integer"}}},
              "category": "readonly"}]
    out = to_openai_tools(tools)
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "read_quote_lines"
    assert out[0]["function"]["description"] == "Legge righe"
    assert out[0]["function"]["parameters"]["properties"]["quote_id"]["type"] == "integer"


def test_to_openai_tools_missing_schema_defaults_empty_object():
    out = to_openai_tools([{"name": "x", "description": "d"}])
    assert out[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_to_openai_messages_system_and_text():
    msgs = to_openai_messages([{"role": "user", "content": "ciao"}], system="SYS")
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1] == {"role": "user", "content": "ciao"}


def test_to_openai_messages_assistant_tool_use_and_tool_result():
    canonical = [
        {"role": "user", "content": "conta"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "calcolo"},
            {"type": "tool_use", "id": "call_0", "name": "read_quote_lines", "input": {"quote_id": 18}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_0", "content": "{\"counts\": {\"consegne\": 15}}"},
        ]},
    ]
    out = to_openai_messages(canonical, system=None)
    # assistant con tool_calls
    asst = [m for m in out if m["role"] == "assistant"][0]
    assert asst["tool_calls"][0]["id"] == "call_0"
    assert asst["tool_calls"][0]["function"]["name"] == "read_quote_lines"
    assert json.loads(asst["tool_calls"][0]["function"]["arguments"]) == {"quote_id": 18}
    # tool_result → role tool
    tool_msg = [m for m in out if m["role"] == "tool"][0]
    assert tool_msg["tool_call_id"] == "call_0"
    assert "consegne" in tool_msg["content"]


def test_from_openai_message_with_tool_calls_string_args():
    msg = {"content": "ok", "tool_calls": [
        {"id": "call_9", "type": "function",
         "function": {"name": "read_quote_lines", "arguments": "{\"quote_number\": \"Q-1\"}"}},
    ]}
    resp = from_openai_message(msg)
    assert isinstance(resp, ToolUseResponse)
    assert resp.stop_reason == "tool_use"
    assert resp.tool_uses[0].name == "read_quote_lines"
    assert resp.tool_uses[0].input == {"quote_number": "Q-1"}
    # raw canonico Anthropic
    assert resp.raw_assistant_message["role"] == "assistant"
    blocks = resp.raw_assistant_message["content"]
    assert any(b["type"] == "tool_use" and b["id"] == "call_9" for b in blocks)


def test_from_openai_message_ollama_object_args():
    # Ollama: arguments è un oggetto, non stringa
    msg = {"content": "", "tool_calls": [
        {"function": {"name": "read_quote_lines", "arguments": {"quote_id": 7}}},
    ]}
    resp = from_openai_message(msg)
    assert resp.tool_uses[0].input == {"quote_id": 7}
    assert resp.tool_uses[0].id  # id generato non vuoto


def test_from_openai_message_no_tools_end_turn():
    resp = from_openai_message({"content": "risposta semplice"})
    assert resp.stop_reason == "end_turn"
    assert resp.tool_uses == []
    assert resp.text == "risposta semplice"
```

- [ ] **Step 2: run → FAIL** (`No module named 'app.services.openai_tools'`)
Run: `.\.venv\Scripts\python.exe -m pytest tests/test_openai_tools.py -v`

- [ ] **Step 3: implementa `app/services/openai_tools.py`**

```python
"""Conversioni pure fra formato canonico Anthropic (usato da advance_loop) e
formato OpenAI chat-completions function-calling. Nessuna dipendenza di rete.

Usato da OpenAICompatToolsMixin per dare tool-use ai provider OpenAI-compatible
(OpenAI, DeepSeek, Perplexity, Ollama, endpoint locali).
"""
from __future__ import annotations
import json
from typing import Any, Optional

from app.services.ai_provider import ToolUse, ToolUseResponse


def to_openai_tools(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools or []:
        schema = t.get("input_schema") or {"type": "object", "properties": {}}
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": schema,
            },
        })
    return out


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return str(content or "")


def to_openai_messages(messages: list[dict], system: Optional[str]) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
            if tool_uses:
                text = _content_to_text(content)
                out.append({
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": [{
                        "id": tu.get("id") or f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": tu.get("name", ""),
                            "arguments": json.dumps(tu.get("input") or {}, ensure_ascii=False),
                        },
                    } for i, tu in enumerate(tool_uses)],
                })
                continue
            if tool_results:
                for tr in tool_results:
                    c = tr.get("content")
                    if not isinstance(c, str):
                        c = json.dumps(c, ensure_ascii=False, default=str)
                    out.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id") or tr.get("id") or "",
                        "content": c,
                    })
                continue
            # lista di soli text block
            out.append({"role": role, "content": _content_to_text(content)})
        else:
            out.append({"role": role, "content": content})
    return out


def from_openai_message(msg: dict) -> ToolUseResponse:
    text = msg.get("content") or ""
    raw_calls = msg.get("tool_calls") or []
    tool_uses: list[ToolUse] = []
    raw_blocks: list[dict] = []
    if text:
        raw_blocks.append({"type": "text", "text": text})
    for i, tc in enumerate(raw_calls):
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, TypeError):
                args = {}
        elif not isinstance(args, dict):
            args = {}
        call_id = tc.get("id") or f"call_{i}"
        name = fn.get("name", "")
        tool_uses.append(ToolUse(id=call_id, name=name, input=args))
        raw_blocks.append({"type": "tool_use", "id": call_id, "name": name, "input": args})
    return ToolUseResponse(
        text=text.strip() if isinstance(text, str) else "",
        tool_uses=tool_uses,
        stop_reason="tool_use" if tool_uses else "end_turn",
        raw_assistant_message={"role": "assistant", "content": raw_blocks},
    )
```

- [ ] **Step 4: run → PASS**
Run: `.\.venv\Scripts\python.exe -m pytest tests/test_openai_tools.py -v` → tutti verdi.

- [ ] **Step 5: commit**
```
git add app/services/openai_tools.py tests/test_openai_tools.py
git commit -m "feat(ai): openai_tools conversioni canonico Anthropic <-> OpenAI function-calling"
```
Body: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 2: `OpenAICompatToolsMixin` + httpx providers (DeepSeek, Perplexity)

**Files:**
- Modify: `app/services/ai_provider.py`
- Test: `tests/test_provider_tools_wiring.py`

- [ ] **Step 1: test che falliscono**

```python
# tests/test_provider_tools_wiring.py
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


def test_perplexity_supports_tools():
    p = PerplexityProvider(ProviderConfig(provider="perplexity", api_key="x"))
    assert p.supports_tools() is True
```

- [ ] **Step 2: run → FAIL** (`supports_tools` False / `_post_chat` assente)
Run: `.\.venv\Scripts\python.exe -m pytest tests/test_provider_tools_wiring.py -v`

- [ ] **Step 3: implementa il mixin + refactor `_post_chat`**

In `ai_provider.py`, dopo la definizione di `ToolUseResponse` e prima dei provider concreti, aggiungi il mixin:

```python
class OpenAICompatToolsMixin:
    """Tool-use per provider con API chat-completions OpenAI-compatible.
    Richiede che il provider esponga `_post_chat(payload: dict) -> dict`
    (JSON completo con `choices[0].message`) e abbia `self.model`."""

    def supports_tools(self) -> bool:
        return True

    def chat_with_tools(self, messages, system, tools, max_tokens=4000, temperature=0.3,
                        *, usage_db=None, usage_user_id=None,
                        usage_conversation_id=None, usage_tenant_id: int = 1):
        from app.services.openai_tools import to_openai_messages, to_openai_tools, from_openai_message
        payload = {
            "model": self.model,
            "messages": to_openai_messages(messages, system),
            "tools": to_openai_tools(tools),
            "tool_choice": "auto",
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = self._post_chat(payload)
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            msg = {"content": ""}
        return from_openai_message(msg)
```

Per `DeepseekProvider` e `PerplexityProvider`:
- Cambia la classe in `class DeepseekProvider(OpenAICompatToolsMixin, AIProvider):` (idem Perplexity).
- Estrai `_post_chat(self, payload) -> dict` che fa il POST e ritorna `data` (JSON completo). Rifai `_post` esistente in termini di `_post_chat`:

```python
    def _post_chat(self, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=180) as client:
            r = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            return r.json()

    def _post(self, payload: dict) -> str:
        data = self._post_chat(payload)
        return data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
```
(Perplexity: usa `self.BASE_URL`; non ha `base_url` istanza → usa `f"{self.BASE_URL}/chat/completions"`, timeout 120.)

Verifica che `self.model` esista su entrambi (sì). Non toccare `chat`/`complete`.

- [ ] **Step 4: run → PASS**
Run: `.\.venv\Scripts\python.exe -m pytest tests/test_provider_tools_wiring.py -v`
Poi regressione: `.\.venv\Scripts\python.exe -m pytest -q -k "provider or ai or openai"` → nessun fallimento nuovo.

- [ ] **Step 5: commit**
```
git add app/services/ai_provider.py tests/test_provider_tools_wiring.py
git commit -m "feat(ai): OpenAICompatToolsMixin + tool-use DeepSeek/Perplexity"
```
Body: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 3: OpenAI (SDK) + Ollama (`/api/chat`) tool-use

**Files:**
- Modify: `app/services/ai_provider.py`
- Test: `tests/test_provider_tools_wiring.py` (append)

- [ ] **Step 1: test**

```python
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
    # Ollama: niente "choices"; message.tool_calls con arguments oggetto.
    monkeypatch.setattr(p, "_post_chat", lambda payload: {
        "choices": [{"message": {"content": "", "tool_calls": [
            {"function": {"name": "read_quote_lines", "arguments": {"quote_number": "Q-9"}}}]}}]})
    resp = p.chat_with_tools([{"role": "user", "content": "x"}], system=None,
                             tools=[{"name": "read_quote_lines", "description": "d"}])
    assert resp.tool_uses[0].input == {"quote_number": "Q-9"}
```

- [ ] **Step 2: run → FAIL**
Run: `.\.venv\Scripts\python.exe -m pytest tests/test_provider_tools_wiring.py -k "openai or ollama" -v`

- [ ] **Step 3: implementa**

`OpenAIProvider(OpenAICompatToolsMixin, AIProvider)`. Aggiungi `_post_chat` che usa il SDK e ritorna un dict normalizzato:
```python
    def _post_chat(self, payload: dict) -> dict:
        resp = self.client.chat.completions.create(**payload)
        # SDK object → dict (pydantic v2 .model_dump(); fallback manuale)
        try:
            return resp.model_dump()
        except AttributeError:
            m = resp.choices[0].message
            return {"choices": [{"message": {
                "content": m.content or "",
                "tool_calls": [{
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                } for tc in (m.tool_calls or [])],
            }}]}
```
(Il SDK `create(**payload)` accetta `tools`/`tool_choice`/`messages`/`model`/`max_tokens`/`temperature`. `model_dump()` produce `choices[0].message.tool_calls[].function.arguments` come stringa → `from_openai_message` la fa `json.loads`.)

`OllamaProvider(OpenAICompatToolsMixin, AIProvider)`. Aggiungi `_post_chat` che fa POST `/api/chat` con `tools` e **normalizza** la risposta (Ollama ritorna `{"message": {...}}`, niente `choices`):
```python
    def _post_chat(self, payload: dict) -> dict:
        body = {
            "model": payload["model"],
            "messages": payload["messages"],
            "tools": payload.get("tools") or [],
            "stream": False,
            "options": {"num_predict": payload.get("max_tokens", 4000),
                        "temperature": payload.get("temperature", 0.3)},
        }
        with httpx.Client(timeout=180) as client:
            r = client.post(f"{self.base_url}/api/chat", json=body)
            r.raise_for_status()
            data = r.json()
        return {"choices": [{"message": data.get("message", {"content": ""})}]}
```
Nota: `from_openai_message` già tollera `arguments` oggetto (Ollama) e id mancante (genera `call_i`).

- [ ] **Step 4: run → PASS** + regressione `.\.venv\Scripts\python.exe -m pytest -q`

- [ ] **Step 5: commit**
```
git add app/services/ai_provider.py tests/test_provider_tools_wiring.py
git commit -m "feat(ai): tool-use OpenAI (SDK) + Ollama (/api/chat normalizzato)"
```
Body: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 4: smoke live + bump + docs + export + push

**Files:** `app/main.py`, `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: full pytest** `.\.venv\Scripts\python.exe -m pytest -q` → verde.
- [ ] **Step 2: restart server** (`:8000`, no-reload; OneDrive richiede restart per modifiche). `$env:APP_ENV="development"`.
- [ ] **Step 3: smoke live DeepSeek** via browser (login admin/admin123, pagina /quotes/): `POST /ai/api/chat` `{messages:[{role:user, content:"Elenca le righe consegna di Q-2026-008-v4 con quantità"}], page:"quotes"}` → la risposta deve riportare le quantità reali (il modello ha chiamato `read_quote_lines`). Conferma 200 JSON. Verifica anche nessun errore console. Annota esito.
- [ ] **Step 4: bump** `main.py` → `3.5.0-alpha.172.191`; CHANGELOG + STATO (sezione α.172.191: tool-use universale, provider coperti, fallback legacy).
- [ ] **Step 5: commit + export ZIP + push**
```
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -m "chore: v3.5.0-alpha.172.191 tool-use universale copilot"
```
Poi genera export ZIP in docs/ (build_export_zip, app_version 3.5.0-alpha.172.191) + commit + `git push origin main`.
Body commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## Self-Review
- Conversioni pure (tools/messages/response) + round-trip → Task 1 ✓
- Mixin + httpx providers (DeepSeek/Perplexity) → Task 2 ✓
- OpenAI SDK + Ollama normalizzato → Task 3 ✓
- raw_assistant_message canonico (loop resta agnostico) → garantito da `from_openai_message` ✓ (verificato: advance_loop appende raw + tool_result canonici)
- Fallback legacy per provider senza tool → invariato (Gemini resta legacy; `supports_tools` non toccato lì) ✓
- Smoke live + bump + push → Task 4 ✓

**Placeholder scan:** nessuno; ogni step ha codice/comando concreto.

**Type consistency:** `_post_chat(payload)->dict` su tutti i provider OpenAI-compat; `from_openai_message(msg)` consuma `choices[0].message` normalizzato; `ToolUse`/`ToolUseResponse` invariati.

**Rischi noti (verificare in esecuzione):**
- `OpenAIProvider.client.chat.completions.create(**payload)` — il payload contiene `tools`/`tool_choice`: il SDK li accetta (sì, openai>=1.x). Se la versione SDK è vecchia, fallback al ramo manuale.
- `model_dump()` su risposta SDK: disponibile in openai>=1.x (pydantic v2). Fallback manuale incluso.
- Ollama `/api/chat` con `tools`: richiede Ollama recente; se il modello non supporta tools ritorna senza tool_calls → degrada a risposta testo (no crash).
