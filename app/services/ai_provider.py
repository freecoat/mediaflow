"""
MediaFlow — AI Provider layer

Astrazione che supporta Anthropic Claude, OpenAI GPT, Google Gemini, Perplexity
e Ollama locale.

In v3.2 la configurazione principale è per-utente nel DB (UserAISettings).
La configurazione globale via .env resta come fallback se l'utente non ha
nulla salvato.

Uso tipico:
    provider = get_provider_for_user(user_id, db)
    if provider:
        provider.complete(system, user)
"""
from __future__ import annotations
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _translate_blocks_to_openai(content):
    """v3.5.0-alpha.53 — Traduce content Anthropic-canonico → OpenAI multimodal.

    Input:
      - stringa → ritornata invariata (modalità testo semplice)
      - list[dict] con block types Anthropic ({type:text}, {type:image,source:base64})
        → list[dict] OpenAI ({type:text}, {type:image_url, image_url:{url:data:...}})

    Block sconosciuti vengono droppati con warning. La traduzione è
    lossy ma sufficiente per il chat semplice; il path tool_use non
    passa da qui (richiederebbe traduzione completa di tool_use/tool_result).
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    out = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            out.append({"type": "text", "text": block.get("text", "")})
        elif btype == "image":
            src = block.get("source", {}) or {}
            if src.get("type") == "base64":
                data_url = f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"
                out.append({"type": "image_url", "image_url": {"url": data_url}})
            elif src.get("type") == "url":
                out.append({"type": "image_url", "image_url": {"url": src.get("url", "")}})
        else:
            logger.debug(f"openai translate: skipping unknown block type={btype!r}")
    return out if out else ""


# ── Modelli supportati per-provider (Apr 2026) ────────────────

PROVIDER_MODELS: dict[str, list[dict]] = {
    "claude": [
        {"id": "claude-opus-4-7",      "label": "Opus 4.7 (top)"},
        {"id": "claude-sonnet-4-6",    "label": "Sonnet 4.6 (default)"},
        {"id": "claude-haiku-4-5",     "label": "Haiku 4.5 (rapido)"},
    ],
    "openai": [
        {"id": "gpt-4o",        "label": "GPT-4o (default)"},
        {"id": "o1",            "label": "o1 (ragionamento)"},
        {"id": "o3-mini",       "label": "o3-mini (rapido/ragionamento)"},
    ],
    "gemini": [
        {"id": "gemini-2.0-flash",        "label": "Gemini 2.0 Flash (default)"},
        {"id": "gemini-2.0-flash-thinking", "label": "Gemini 2.0 Flash Thinking"},
        {"id": "gemini-1.5-pro",          "label": "Gemini 1.5 Pro"},
    ],
    "perplexity": [
        {"id": "sonar-pro",     "label": "Sonar Pro (default, con citazioni)"},
        {"id": "sonar",         "label": "Sonar (rapido)"},
        {"id": "sonar-reasoning", "label": "Sonar Reasoning"},
    ],
    "ollama": [
        {"id": "llama3.1:70b",  "label": "Llama 3.1 70B"},
        {"id": "llama3.1:8b",   "label": "Llama 3.1 8B (leggero)"},
        {"id": "qwen2.5:32b",   "label": "Qwen 2.5 32B"},
    ],
}

PROVIDER_LABELS: dict[str, str] = {
    "claude":     "Anthropic Claude",
    "openai":     "OpenAI",
    "gemini":     "Google Gemini",
    "perplexity": "Perplexity",
    "ollama":     "Ollama (locale)",
}


# v3.5.0-alpha.66.16.4 — Tabella prezzi per il calcolo del costo USD per
# token. Sorgenti: pricing pubblico provider al maggio 2026. Aggiornare
# quando si aggiunge un nuovo modello o cambiano i prezzi.
# Convenzione: prezzi in USD per 1M tokens. cache_read prezzo Anthropic =
# 0.1× input cold; cache_create = 1.25× input cold (write-through).
# Ollama: locale = 0 USD (compute on-prem).
MODEL_PRICING_USD_PER_M_TOKENS: dict[str, dict[str, float]] = {
    # Claude (Anthropic) — pricing maggio 2026
    "claude-opus-4-7":      {"input": 15.0,  "output": 75.0,  "cache_read": 1.5,    "cache_create": 18.75},
    "claude-sonnet-4-6":    {"input": 3.0,   "output": 15.0,  "cache_read": 0.30,   "cache_create": 3.75},
    "claude-haiku-4-5":     {"input": 1.0,   "output": 5.0,   "cache_read": 0.10,   "cache_create": 1.25},
    # OpenAI
    "gpt-4o":               {"input": 2.5,   "output": 10.0,  "cache_read": 1.25,   "cache_create": 0.0},
    "o1":                   {"input": 15.0,  "output": 60.0,  "cache_read": 7.5,    "cache_create": 0.0},
    "o3-mini":              {"input": 1.10,  "output": 4.40,  "cache_read": 0.55,   "cache_create": 0.0},
    # Gemini
    "gemini-2.0-flash":          {"input": 0.10,  "output": 0.40,  "cache_read": 0.025,  "cache_create": 0.0},
    "gemini-2.0-flash-thinking": {"input": 0.15,  "output": 0.60,  "cache_read": 0.0375, "cache_create": 0.0},
    "gemini-1.5-pro":            {"input": 1.25,  "output": 5.0,   "cache_read": 0.3125, "cache_create": 0.0},
    # Perplexity
    "sonar-pro":            {"input": 3.0,   "output": 15.0,  "cache_read": 0.0, "cache_create": 0.0},
    "sonar":                {"input": 1.0,   "output": 1.0,   "cache_read": 0.0, "cache_create": 0.0},
    "sonar-reasoning":      {"input": 1.0,   "output": 5.0,   "cache_read": 0.0, "cache_create": 0.0},
    # Ollama (locale → costo zero compute on-prem)
    "llama3.1:70b":         {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0},
    "llama3.1:8b":          {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0},
    "qwen2.5:32b":          {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_create": 0.0},
}


def compute_cost_usd(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_create_tokens: int = 0,
) -> float:
    """Calcola costo USD per una singola call API.

    Modelli sconosciuti → 0.0 (no errore: l'audit log resta utilizzabile,
    il costo è underestimate ma noto). Aggiungere il modello a
    `MODEL_PRICING_USD_PER_M_TOKENS` per evitare drift.

    NB: usa float, non Decimal. Per analytics microcent precision sufficiente.
    Se un giorno servirà fatturazione interna AI, migrare a Decimal('0.0001').
    """
    p = MODEL_PRICING_USD_PER_M_TOKENS.get(model)
    if not p:
        return 0.0
    cost = (
        input_tokens * p["input"] / 1_000_000
        + output_tokens * p["output"] / 1_000_000
        + cache_read_tokens * p["cache_read"] / 1_000_000
        + cache_create_tokens * p["cache_create"] / 1_000_000
    )
    return round(cost, 6)


def log_ai_usage(
    *,
    db,
    user_id,
    conversation_id,
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_create_tokens: int = 0,
    call_kind: str = "chat_with_tools",
    stop_reason: Optional[str] = None,
    duration_ms: Optional[int] = None,
    tenant_id: int = 1,
) -> None:
    """v3.5.0-alpha.66.16.4 — Persiste 1 riga AIUsageLog per la call.

    Best-effort: errori di I/O loggati ma non re-raise (il logging non
    deve mai bloccare la response AI all'utente). Calcola `cost_usd` via
    `compute_cost_usd` automaticamente.

    `db` è la Session SQLAlchemy del request. Tipo non annotato per evitare
    import circolari (SessionLocal sta in app/database.py che importa qui).
    """
    if db is None:
        return
    try:
        from app.models.models import AIUsageLog
        cost = compute_cost_usd(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_create_tokens=cache_create_tokens,
        )
        row = AIUsageLog(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_create_tokens=cache_create_tokens,
            cost_usd=cost,
            call_kind=call_kind,
            stop_reason=stop_reason,
            duration_ms=duration_ms,
        )
        db.add(row)
        # NB: niente commit. La transazione è del caller (router/loop).
    except Exception as e:
        logger.warning(f"log_ai_usage failed: {e}")


# ── Config dataclass ──────────────────────────────────────────

@dataclass
class ProviderConfig:
    """Config concreta per istanziare un provider, indipendente da .env vs DB."""
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None


# ── Tool-use response ─────────────────────────────────────────

@dataclass
class ToolUse:
    """Una richiesta del modello di invocare un tool. `id` è opaco al backend
    (Anthropic genera 'toolu_xxx', OpenAI genera UUID, Gemini genera index str)
    e DEVE essere riportato pari pari nel tool_result corrispondente."""
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolUseResponse:
    """Risposta di un turno chat_with_tools, normalizzata cross-provider.

    - `text`: testo libero emesso dal modello (può essere vuoto se il modello
      ha solo prodotto tool_use senza commento).
    - `tool_uses`: tool che il modello vuole invocare in questo turno.
    - `stop_reason`: 'end_turn' | 'tool_use' | 'max_tokens' | 'stop_sequence' | 'other'.
    - `raw_assistant_message`: payload assistant da rimettere intero in `messages`
      al prossimo turno (Anthropic: lista di content blocks; OpenAI: dict
      message; Gemini: dict). Opaco — non interpretare.
    """
    text: str
    tool_uses: list[ToolUse] = field(default_factory=list)
    stop_reason: str = "end_turn"
    raw_assistant_message: Any = None


# ── Interfaccia ───────────────────────────────────────────────

class AIProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 2000,
                 temperature: float = 0.3) -> str: ...

    @abstractmethod
    def chat(self, messages: list[dict], system: Optional[str] = None,
             max_tokens: int = 2000, temperature: float = 0.5) -> str: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    def extract_json(self, system: str, user: str, max_tokens: int = 3000) -> Optional[dict]:
        system_with_json = (
            system + "\n\nIMPORTANTE: Rispondi SOLO con un oggetto JSON valido, "
            "senza testo prima o dopo, senza markdown, senza backtick."
        )
        try:
            response = self.complete(system_with_json, user, max_tokens=max_tokens, temperature=0.1)
            return safe_json_parse(response)
        except Exception as e:
            logger.error(f"AI extract_json failed: {e}")
            return None

    def supports_web_search(self) -> bool:
        """True se il provider espone un tool web_search server-side nativo."""
        return False

    def supports_tools(self) -> bool:
        """True se il provider supporta il loop tool_use (Claude/OpenAI/Gemini).
        Provider che ritornano False (Ollama, Perplexity) usano il fallback
        markdown ```action``` legacy.
        """
        return False

    def supports_vision(self) -> bool:
        """v3.5.0-alpha.53 — True se il provider accetta image blocks
        nei messaggi user. Quando False, il copilot cade su placeholder
        testuale (vedi `copilot_attachments.build_user_content_blocks`).
        """
        return False

    def chat_with_tools(self, messages: list[Any], system: Optional[str],
                        tools: list[dict], max_tokens: int = 4000,
                        temperature: float = 0.3) -> ToolUseResponse:
        """Esegue UN turno di chat con tool-use abilitato.

        - `messages`: storico conversazione in formato canonico Anthropic
          (lista di {role, content}, dove content può essere stringa o lista
          di blocks misti text/tool_use/tool_result).
        - `system`: system prompt (può essere None).
        - `tools`: lista di tool descriptors in formato Anthropic
          ({name, description, input_schema}). Il provider concreto le converte
          al proprio formato interno.

        Default: solleva NotImplementedError. Provider che supportano tool-use
        (Claude/OpenAI/Gemini) override.
        """
        raise NotImplementedError(f"{self.name} non supporta tool_use")

    def extract_json_with_web_search(self, system: str, user: str,
                                     max_tokens: int = 4000,
                                     max_searches: int = 5) -> Optional[dict]:
        """
        Esegue una ricerca web autonoma (multi-step) e ritorna un JSON strutturato.
        Default: non supportato. Override in ClaudeProvider.
        """
        return None


# ── Provider concreti ─────────────────────────────────────────

class ClaudeProvider(AIProvider):
    def __init__(self, cfg: ProviderConfig):
        try:
            from anthropic import Anthropic
        except ImportError:
            raise RuntimeError("anthropic package not installed")
        if not cfg.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY mancante")
        self.client = Anthropic(api_key=cfg.api_key)
        self.model = cfg.model or settings.anthropic_model

    @property
    def name(self) -> str: return f"Claude ({self.model})"

    def complete(self, system, user, max_tokens=2000, temperature=0.3):
        resp = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            system=system, messages=[{"role": "user", "content": user}])
        return resp.content[0].text

    def chat(self, messages, system=None, max_tokens=2000, temperature=0.5):
        kwargs = {"model": self.model, "max_tokens": max_tokens,
                  "temperature": temperature, "messages": messages}
        if system: kwargs["system"] = system
        return self.client.messages.create(**kwargs).content[0].text

    def supports_web_search(self) -> bool:
        return True

    def supports_tools(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        # Tutti i modelli Claude 3.x+ supportano image blocks nativamente
        return True

    def chat_with_tools(self, messages, system, tools, max_tokens=4000, temperature=0.3,
                        *, usage_db=None, usage_user_id=None,
                        usage_conversation_id=None, usage_tenant_id: int = 1):
        """Loop tool_use Anthropic. Ritorna UN turno (un singolo round-trip API).
        Il caller decide se proseguire (eseguire i tool, append tool_result,
        richiamare chat_with_tools) o fermarsi (mutation in attesa di Apply).

        v3.5.0-alpha.66.14.7 — Prompt caching su system + tools per ridurre
        ~90% del costo input ricorrente (Anthropic addebita 0.1× cache hits
        vs 1× cold). Soglia minima 1024 tokens per Claude 3.x+, sotto la
        soglia il marker `cache_control` viene ignorato senza errore.

        v3.5.0-alpha.66.16.4 (R10) — Logging persistente AIUsageLog. I
        parametri `usage_*` sono opzionali: se passati, loga 1 row con
        token + costo USD. Caller (`ai_loop.advance_loop`) ha db+user+conv
        a portata di mano e può popolarli senza overhead.
        """
        import time as _t
        _t0 = _t.time()
        kwargs: dict = {
            "model":       self.model,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "messages":    messages,
        }
        # System prompt: cache_control ephemeral. Accettiamo sia stringa (compat
        # con call site esistenti) che list di blocks già pronta.
        if system:
            if isinstance(system, str):
                kwargs["system"] = [{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                kwargs["system"] = system
        # Tools: marca l'ULTIMO tool con cache_control. Anthropic estende il
        # cache fino a quel punto (cumulativo: system+tools cachato insieme).
        if tools:
            cached_tools = list(tools)
            if cached_tools:
                last = dict(cached_tools[-1])
                last["cache_control"] = {"type": "ephemeral"}
                cached_tools[-1] = last
            kwargs["tools"] = cached_tools

        resp = self.client.messages.create(**kwargs)

        # v3.5.0-alpha.66.14.7 — Log cache stats + (R10) persistenza AIUsageLog.
        cc_in, cr_in, tot_in, tot_out = 0, 0, 0, 0
        try:
            usage = getattr(resp, "usage", None)
            if usage is not None:
                cc_in = getattr(usage, "cache_creation_input_tokens", 0) or 0
                cr_in = getattr(usage, "cache_read_input_tokens", 0) or 0
                tot_in = getattr(usage, "input_tokens", 0) or 0
                tot_out = getattr(usage, "output_tokens", 0) or 0
                if cc_in or cr_in:
                    logger.info(
                        f"[anthropic cache] read={cr_in} create={cc_in} "
                        f"input={tot_in} output={tot_out} "
                        f"hit_ratio={cr_in/(cr_in+tot_in) if (cr_in+tot_in) else 0:.0%}"
                    )
        except Exception:
            pass

        # v3.5.0-alpha.66.16.4 (R10) — Persisti riga AIUsageLog se il caller
        # ha passato i `usage_*` parametri.
        if usage_db is not None:
            log_ai_usage(
                db=usage_db,
                user_id=usage_user_id,
                conversation_id=usage_conversation_id,
                tenant_id=usage_tenant_id,
                provider="claude",
                model=self.model,
                input_tokens=tot_in,
                output_tokens=tot_out,
                cache_read_tokens=cr_in,
                cache_create_tokens=cc_in,
                call_kind="chat_with_tools",
                stop_reason=str(getattr(resp, "stop_reason", "") or ""),
                duration_ms=int((_t.time() - _t0) * 1000),
            )

        text_parts: list[str] = []
        tool_uses: list[ToolUse] = []
        # Salviamo il content blocks completo per rimetterlo in messages al prossimo turno.
        # Anthropic vuole gli oggetti TextBlock/ToolUseBlock; ma accetta anche dict equivalenti.
        raw_blocks: list[dict] = []
        for block in resp.content:
            btype = getattr(block, "type", "")
            if btype == "text":
                txt = getattr(block, "text", "") or ""
                text_parts.append(txt)
                raw_blocks.append({"type": "text", "text": txt})
            elif btype == "tool_use":
                tu = ToolUse(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    input=dict(getattr(block, "input", {}) or {}),
                )
                tool_uses.append(tu)
                raw_blocks.append({
                    "type":  "tool_use",
                    "id":    tu.id,
                    "name":  tu.name,
                    "input": tu.input,
                })
            else:
                # Future-proof: ignora blocks sconosciuti ma logga.
                logger.warning(f"Anthropic content block sconosciuto: type={btype!r}")

        return ToolUseResponse(
            text="\n".join(p for p in text_parts if p).strip(),
            tool_uses=tool_uses,
            stop_reason=getattr(resp, "stop_reason", "end_turn") or "end_turn",
            raw_assistant_message={"role": "assistant", "content": raw_blocks},
        )

    def extract_json_with_web_search(self, system, user, max_tokens=4000, max_searches=5):
        """
        Usa il tool server-side `web_search_20250305` di Anthropic.
        Il modello decide autonomamente quante ricerche fare (cap = max_searches),
        legge i risultati lato server, e produce il JSON finale.
        """
        system_with_json = (
            system + "\n\nProcedura obbligatoria: 1) Cerca sul web tutte le informazioni "
            "necessarie usando il tool web_search (puoi farlo più volte con query diverse: "
            "sito ufficiale, P.IVA + nome, filmografia recente, sede legale). "
            "2) Solo dopo aver completato la ricerca, rispondi con UN SOLO oggetto JSON "
            "valido secondo lo schema, senza testo prima o dopo, senza markdown, senza backtick."
        )
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_with_json,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": max_searches,
                }],
                messages=[{"role": "user", "content": user}],
            )
            text_parts = []
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    text_parts.append(getattr(block, "text", "") or "")
            full_text = "\n".join(p for p in text_parts if p).strip()
            if not full_text:
                logger.warning("Anthropic web_search: nessun blocco text in risposta")
                return None
            return safe_json_parse(full_text)
        except Exception as e:
            logger.error(f"Anthropic web_search extract_json failed: {e}")
            return None


class OpenAIProvider(AIProvider):
    def __init__(self, cfg: ProviderConfig):
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai package not installed")
        if not cfg.api_key:
            raise RuntimeError("OPENAI_API_KEY mancante")
        self.client = OpenAI(api_key=cfg.api_key)
        self.model = cfg.model or settings.openai_model

    @property
    def name(self) -> str: return f"OpenAI ({self.model})"

    def complete(self, system, user, max_tokens=2000, temperature=0.3):
        resp = self.client.chat.completions.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        return resp.choices[0].message.content or ""

    def chat(self, messages, system=None, max_tokens=2000, temperature=0.5):
        msgs = [{"role": "system", "content": system}] if system else []
        # v3.5.0-alpha.53 — Traduzione image blocks Anthropic-canonici → OpenAI
        for m in messages:
            msgs.append({
                "role": m.get("role", "user"),
                "content": _translate_blocks_to_openai(m.get("content", "")),
            })
        resp = self.client.chat.completions.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature, messages=msgs)
        return resp.choices[0].message.content or ""

    def supports_vision(self) -> bool:
        # GPT-4o e o1 supportano vision; o3-mini no.
        # Verifico via model name (tutti i recenti hanno multimodal).
        model = (self.model or "").lower()
        return any(k in model for k in ("4o", "vision", "o1", "gpt-4-turbo"))


class GeminiProvider(AIProvider):
    """
    Google Gemini via google-generativeai SDK.
    Mapping: usiamo il system prompt come `system_instruction`, e i messaggi
    come content list (user/model roles).
    """
    def __init__(self, cfg: ProviderConfig):
        try:
            import google.generativeai as genai
        except ImportError:
            raise RuntimeError("google-generativeai package not installed")
        if not cfg.api_key:
            raise RuntimeError("GOOGLE_API_KEY mancante")
        genai.configure(api_key=cfg.api_key)
        self._genai = genai
        self.model_name = cfg.model or settings.google_model

    @property
    def name(self) -> str: return f"Gemini ({self.model_name})"

    def _model(self, system: Optional[str] = None):
        return self._genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system,
        )

    def complete(self, system, user, max_tokens=2000, temperature=0.3):
        cfg = self._genai.types.GenerationConfig(
            max_output_tokens=max_tokens, temperature=temperature)
        resp = self._model(system).generate_content(user, generation_config=cfg)
        return resp.text or ""

    def chat(self, messages, system=None, max_tokens=2000, temperature=0.5):
        cfg = self._genai.types.GenerationConfig(
            max_output_tokens=max_tokens, temperature=temperature)
        # Mapping: openai-style messages → gemini "contents"
        contents = []
        for m in messages:
            role = "model" if m.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [m.get("content", "")]})
        resp = self._model(system).generate_content(contents, generation_config=cfg)
        return resp.text or ""


class PerplexityProvider(AIProvider):
    """
    Perplexity API via httpx (OpenAI-compatible chat completions).
    Endpoint: https://api.perplexity.ai/chat/completions
    """
    BASE_URL = "https://api.perplexity.ai"

    def __init__(self, cfg: ProviderConfig):
        if not cfg.api_key:
            raise RuntimeError("PERPLEXITY_API_KEY mancante")
        self.api_key = cfg.api_key
        self.model = cfg.model or settings.perplexity_model

    @property
    def name(self) -> str: return f"Perplexity ({self.model})"

    def _post(self, payload: dict) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        with httpx.Client(timeout=120) as client:
            r = client.post(f"{self.BASE_URL}/chat/completions",
                            headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""

    def complete(self, system, user, max_tokens=2000, temperature=0.3):
        return self._post({
            "model": self.model, "max_tokens": max_tokens, "temperature": temperature,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]})

    def chat(self, messages, system=None, max_tokens=2000, temperature=0.5):
        msgs = [{"role": "system", "content": system}] if system else []
        msgs.extend(messages)
        return self._post({"model": self.model, "max_tokens": max_tokens,
                           "temperature": temperature, "messages": msgs})


class OllamaProvider(AIProvider):
    def __init__(self, cfg: ProviderConfig):
        self.base_url = (cfg.base_url or settings.ollama_base_url).rstrip("/")
        self.model = cfg.model or settings.ollama_model

    @property
    def name(self) -> str: return f"Ollama ({self.model})"

    def _call(self, payload):
        try:
            with httpx.Client(timeout=120) as client:
                r = client.post(f"{self.base_url}/api/chat", json=payload)
                r.raise_for_status()
                return r.json().get("message", {}).get("content", "")
        except httpx.HTTPError as e:
            raise RuntimeError(f"Ollama non raggiungibile su {self.base_url}: {e}")

    def complete(self, system, user, max_tokens=2000, temperature=0.3):
        return self._call({
            "model": self.model, "stream": False,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "options": {"num_predict": max_tokens, "temperature": temperature}})

    def chat(self, messages, system=None, max_tokens=2000, temperature=0.5):
        msgs = [{"role": "system", "content": system}] if system else []
        msgs.extend(messages)
        return self._call({
            "model": self.model, "stream": False, "messages": msgs,
            "options": {"num_predict": max_tokens, "temperature": temperature}})


# ── Factory ───────────────────────────────────────────────────

PROVIDER_CLASSES = {
    "claude":     ClaudeProvider,
    "openai":     OpenAIProvider,
    "gemini":     GeminiProvider,
    "perplexity": PerplexityProvider,
    "ollama":     OllamaProvider,
}


def build_provider(cfg: ProviderConfig) -> AIProvider:
    """Costruisce un provider da una config esplicita. Solleva RuntimeError se invalida."""
    cls = PROVIDER_CLASSES.get(cfg.provider)
    if cls is None:
        raise RuntimeError(f"Provider sconosciuto: {cfg.provider}")
    return cls(cfg)


def _global_config() -> Optional[ProviderConfig]:
    """Fallback dalla configurazione .env globale."""
    if settings.ai_provider == "disabled":
        return None
    p = settings.ai_provider
    if p == "claude":
        return ProviderConfig("claude", settings.anthropic_api_key, settings.anthropic_model)
    if p == "openai":
        return ProviderConfig("openai", settings.openai_api_key, settings.openai_model)
    if p == "gemini":
        return ProviderConfig("gemini", settings.google_api_key, settings.google_model)
    if p == "perplexity":
        return ProviderConfig("perplexity", settings.perplexity_api_key, settings.perplexity_model)
    if p == "ollama":
        return ProviderConfig("ollama", None, settings.ollama_model, settings.ollama_base_url)
    return None


def _user_config(user_id: int, db) -> Optional[ProviderConfig]:
    """Legge la config attiva per l'utente dal DB. Decifra la api_key."""
    from app.models.models import User, UserAISettings
    from app.services.crypto import decrypt_secret

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.active_ai_provider:
        return None
    row = db.query(UserAISettings).filter(
        UserAISettings.user_id == user_id,
        UserAISettings.provider == user.active_ai_provider,
    ).first()
    if not row:
        return None
    api_key = decrypt_secret(row.api_key_encrypted) if row.api_key_encrypted else None
    return ProviderConfig(
        provider=row.provider,
        api_key=api_key,
        model=row.model,
        base_url=row.base_url,
    )


def get_provider_for_user(user_id: Optional[int], db) -> Optional[AIProvider]:
    """
    Risolve il provider AI da usare per uno specifico utente.
    Ordine: config DB per-user → fallback config globale .env.
    Ritorna None se nessuna config valida.
    """
    cfg: Optional[ProviderConfig] = None
    if user_id and db is not None:
        try:
            cfg = _user_config(user_id, db)
        except Exception as e:
            logger.warning(f"Lettura config AI utente {user_id} fallita: {e}")
    if cfg is None:
        cfg = _global_config()
    if cfg is None:
        return None
    try:
        return build_provider(cfg)
    except Exception as e:
        logger.error(f"Init AI provider {cfg.provider} fallito: {e}")
        return None


# Legacy: funzione globale singleton per il codice che ancora la chiama.
# Da rimuovere quando tutti i call-site saranno migrati a get_provider_for_user.
_legacy_instance: Optional[AIProvider] = None


def get_provider() -> Optional[AIProvider]:
    global _legacy_instance
    if _legacy_instance is not None:
        return _legacy_instance
    cfg = _global_config()
    if cfg is None:
        return None
    try:
        _legacy_instance = build_provider(cfg)
        logger.info(f"AI provider globale: {_legacy_instance.name}")
        return _legacy_instance
    except Exception as e:
        logger.error(f"Init AI provider globale fallito: {e}")
        return None


def reset_provider():
    global _legacy_instance
    _legacy_instance = None


# ── Utility ───────────────────────────────────────────────────

def _strip_json_comments_and_trailing_commas(text: str) -> str:
    """
    Tollera tre abitudini comuni dei modelli (specie open-source <30B):
    - commenti `// ...` (JS-style) e `# ...` (Python-style) a fine riga
    - commenti `/* ... */` block
    - virgole finali prima di `}` o `]`
    Stato-aware sulle stringhe e sugli escape per non toccare URL, stringhe con `//`,
    o stringhe contenenti `#` (es. CSS color, hashtag, ancore URL).
    """
    out = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        # Fuori dalle stringhe
        if ch == '"':
            in_string = True
            out.append(ch); i += 1; continue
        # Commento a fine riga (// stile JS o # stile Python)
        if ch == "#" or (ch == "/" and i + 1 < n and text[i + 1] == "/"):
            j = text.find("\n", i + 1)
            i = j if j != -1 else n
            continue
        # Commento a blocco
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = (j + 2) if j != -1 else n
            continue
        out.append(ch); i += 1
    cleaned = "".join(out)
    # Virgole finali prima di } o ]
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    return cleaned


def safe_json_parse(text: str) -> Optional[dict]:
    if not text: return None
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    # Primo tentativo: JSON puro
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Secondo tentativo: dopo aver rimosso commenti e trailing commas
    cleaned = _strip_json_comments_and_trailing_commas(text)
    if cleaned != text:
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    # Terzo tentativo: cerca il primo blocco {…} o […] dentro il testo
    m = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return None
