# Tool-use universale per il Copilot — Design

> Spec di design. 4 giugno 2026. Target: v3.5.0-alpha.172.191.

## Obiettivo

Il Copilot deve poter usare i **tool** (readonly: `read_quote_lines`, `query_project_finance`, …; e mutation: `propose_*`) con **qualsiasi modello AI**, non solo Claude. Requisito esplicito: compatibilità universale — API cloud (OpenAI, DeepSeek, Perplexity, Mistral, …) **e LLM locali** (Ollama, LM Studio, vLLM, llama.cpp).

Caso che ha originato la richiesta: con DeepSeek (provider attivo) il copilot non vedeva i tool → non poteva recuperare il dettaglio righe di una quote. DeepSeek (e quasi tutti) supportano il function-calling in formato **OpenAI-compatible**; oggi solo `ClaudeProvider` implementa `chat_with_tools`.

## Stato attuale (riuso)

- `app/services/ai_loop.py:advance_loop` — loop tool-use **già provider-agnostico**: lavora in formato **canonico Anthropic** (messages = lista di `{role, content}` con blocks `text`/`tool_use`/`tool_result`), chiama `provider.chat_with_tools(messages, system, tools)`, riceve `ToolUseResponse`, esegue i readonly inline, sospende le mutation per Apply.
- `AIProvider.chat_with_tools(messages, system, tools) -> ToolUseResponse` (base: `NotImplementedError`). `ClaudeProvider` la implementa (formato Anthropic).
- `AIProvider.supports_tools() -> bool` decide path **native tool-use** vs **legacy markdown** (`chat_with_assistant` con blocchi ```action```).
- `ToolUse(id, name, input: dict)` e `ToolUseResponse(text, tool_uses, stop_reason, raw_assistant_message)` — contratti canonici.
- Tool descriptors in `app/services/ai_tools.py:TOOLS` (formato Anthropic: `{name, description, input_schema, category}`).
- Provider esistenti: `OpenAIProvider` (SDK `openai`), `DeepseekProvider`/`PerplexityProvider` (httpx POST `/chat/completions`), `GeminiProvider` (SDK genai), `OllamaProvider` (httpx `/api/chat`).

## Strategia a livelli (per universalità)

1. **Native — Anthropic** (`ClaudeProvider`): invariato.
2. **Native — OpenAI-compatible** (NUOVO, copre la maggioranza cloud + locale): un **adapter unico** che converte canonico↔OpenAI e implementa `chat_with_tools`. Vale per OpenAI, DeepSeek, Perplexity e **qualsiasi endpoint OpenAI-compatible via `base_url`** (Ollama `/v1`, LM Studio, vLLM, llama.cpp, server custom).
3. **Native — Ollama** `/api/chat`: supporta `tools`; formato risposta quasi-OpenAI ma `tool_calls[].function.arguments` è **oggetto** (non stringa JSON). L'adapter tollera entrambi → Ollama coperto.
4. **Fallback universale — legacy markdown**: qualsiasi provider con `supports_tools()==False` (o modello locale senza function-calling affidabile) continua a usare `chat_with_assistant` con blocchi ```action```. Rete di sicurezza: nessun modello resta senza copertura (almeno le mutation; readonly-in-legacy = follow-up, vedi Non-goal).

## Componenti

### 1. `app/services/openai_tools.py` (NUOVO — conversioni pure, testabili senza rete)

```python
def to_openai_tools(tools: list[dict]) -> list[dict]:
    """Anthropic tool descriptors → OpenAI function tools.
    {name, description, input_schema} → {type:"function", function:{name, description, parameters: input_schema}}.
    `input_schema` mancante → parameters {"type":"object","properties":{}}."""

def to_openai_messages(messages: list[dict], system: Optional[str]) -> list[dict]:
    """Messages canonici Anthropic → messaggi OpenAI chat.
    - system (str) → {"role":"system","content":system} in testa (se presente).
    - blocco/i text in un turno → content stringa.
    - turno assistant con tool_use → {"role":"assistant","content":<text|None>,
      "tool_calls":[{"id":id,"type":"function","function":{"name":name,
                     "arguments": json.dumps(input)}}]}.
    - blocco tool_result (in un turno role=user) → {"role":"tool",
      "tool_call_id": tool_use_id, "content": <stringa>}.
    - content stringa semplice → passthrough con il role.
    Gestisce content sia stringa sia lista-di-blocks."""

def from_openai_message(msg: dict) -> ToolUseResponse:
    """choices[0].message OpenAI/Ollama → ToolUseResponse canonico.
    - text = msg.get("content") or "".
    - per ogni tc in msg.get("tool_calls") or []:
        args = tc.function.arguments; se stringa → json.loads (lenient via
        safe_json_parse); se dict (Ollama) → usa diretto.
        ToolUse(id = tc.get("id") or generato, name = tc.function.name, input = args).
    - stop_reason = "tool_use" se tool_calls altrimenti "end_turn".
    - raw_assistant_message = RICOSTRUITO IN FORMATO CANONICO ANTHROPIC:
      {"role":"assistant","content":[{type:text,...}?, {type:tool_use,id,name,input}...]}
      → così il loop resta canonico e al turno successivo to_openai_messages lo riconverte."""
```

Nota id: OpenAI fornisce `tool_calls[].id`; Ollama a volte no → genera un id stabile (`call_{index}`) e usalo coerentemente sia nel ToolUse sia nel raw_assistant_message (il loop lo userà per il tool_result).

### 2. `OpenAICompatToolsMixin` (in `ai_provider.py`)

```python
class OpenAICompatToolsMixin:
    def supports_tools(self) -> bool: return True
    def chat_with_tools(self, messages, system, tools, max_tokens=4000, temperature=0.3,
                        *, usage_db=None, usage_user_id=None,
                        usage_conversation_id=None, usage_tenant_id=1) -> ToolUseResponse:
        payload = {
            "model": self.model,
            "messages": to_openai_messages(messages, system),
            "tools": to_openai_tools(tools),
            "tool_choice": "auto",
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        raw = self._post_chat(payload)          # ogni provider fornisce _post_chat → dict completo
        msg = raw["choices"][0]["message"]
        # usage logging best-effort (raw.get("usage")) se usage_db
        return from_openai_message(msg)
```

I provider espongono `_post_chat(payload) -> dict` (ritorna il JSON completo, non solo content):
- `DeepseekProvider` / `PerplexityProvider`: httpx POST a `{base_url}/chat/completions` (refactor: estrai `_post_chat` che ritorna `data`, e `_post` esistente diventa `_post_chat(...)["choices"][0]["message"]["content"]`).
- `OpenAIProvider`: `self.client.chat.completions.create(**payload)` e converti l'oggetto SDK in dict (`.model_dump()`), oppure leggi attributi.
- `OllamaProvider`: POST `{base_url}/api/chat` con `tools`, `stream:false`; risposta `data["message"]` (no `choices`) → adattare `_post_chat` per normalizzare a `{"choices":[{"message": data["message"]}], "usage": ...}`.

Applicare il mixin a: **DeepseekProvider, OpenAIProvider, PerplexityProvider, OllamaProvider** (MRO: `class DeepseekProvider(OpenAICompatToolsMixin, AIProvider)`).

### 3. Capability flag model-aware (opzionale, sicurezza)

`supports_tools()` resta True a livello provider per la famiglia OpenAI-compat. Se un modello locale specifico fallisce il function-calling, il loop riceve `tool_uses=[]` e il modello risponde in testo: nessun crash. (Niente blocklist per-modello in v1.)

## Flusso end-to-end (DeepSeek, esempio)

1. `/ai/api/chat` con conversazione → `provider.supports_tools()` ora True per DeepSeek → path `advance_loop`.
2. `advance_loop` chiama `DeepseekProvider.chat_with_tools(canonical_messages, system, TOOLS)`.
3. Mixin converte → POST DeepSeek con `tools`; DeepSeek decide di chiamare `read_quote_lines`.
4. `from_openai_message` → `ToolUseResponse(tool_uses=[read_quote_lines], raw=canonico)`.
5. `advance_loop` esegue il readonly (`_exec_readonly`), appende `tool_result` canonico, richiama `chat_with_tools`.
6. DeepSeek risponde col conteggio/dettaglio reale. Mutation → sospese per Apply (invariato).

## Test (pytest, niente rete)

`tests/test_openai_tools.py`:
- `to_openai_tools`: descrittore Anthropic → function tool; input_schema mancante → parameters vuoto valido.
- `to_openai_messages`: system in testa; turno assistant con tool_use → `tool_calls` con `arguments` JSON-string; `tool_result` → `role:tool` con `tool_call_id`; content stringa passthrough.
- `from_openai_message`: `tool_calls` con arguments-stringa → ToolUse con input dict; arguments-oggetto (Ollama) → ToolUse; nessun tool_calls → stop_reason end_turn; raw_assistant_message in formato canonico (blocks text+tool_use).
- **Round-trip**: canonical → openai → (simulo risposta tool_calls) → from_openai → raw canonico → re-feed to_openai (stabile, id coerenti).

`tests/test_provider_tools_wiring.py`:
- `DeepseekProvider().supports_tools() is True` (idem OpenAI/Perplexity/Ollama).
- `chat_with_tools` con `_post_chat` monkeypatchato (ritorna un dict finto con tool_calls) → ritorna `ToolUseResponse` con il tool atteso. Nessuna chiamata HTTP reale.

Verifica live (manuale, post-deploy): copilot su DeepSeek → "dettaglio righe consegna di Q-…-v4 con quantità" → usa `read_quote_lines` e risponde con le quantità.

## Non-goal (YAGNI)

- Readonly tools nel path **legacy markdown** (per modelli senza function-calling): rete di sicurezza già copre le mutation; estendere ai readonly = follow-up separato.
- Gemini tool-use (SDK genai, formato diverso): deferito; Gemini resta legacy finché non serve.
- Streaming nel tool-use loop (DeepSeek v4 output grande): il loop fa round-trip brevi; streaming non necessario per i tool. Mantenere `max_tokens` ragionevole.
- Prompt caching OpenAI-compat (Anthropic-only feature): non applicabile.
- Refactor in un unico `OpenAICompatibleProvider(base_url)` generico: desiderabile ma rischioso ora; il mixin sui provider esistenti dà lo stesso risultato in modo incrementale. Un provider "custom OpenAI endpoint" (per LLM locali arbitrari) può essere aggiunto dopo riusando il mixin.

## Versioning

- Bump `main.py` → `3.5.0-alpha.172.191`. CHANGELOG + STATO. Commit a feature completa + test verdi. Export ZIP + push.
