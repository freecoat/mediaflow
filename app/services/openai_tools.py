"""Conversioni pure fra formato canonico Anthropic (usato da advance_loop) e
formato OpenAI chat-completions function-calling. Nessuna dipendenza di rete.

Usato da OpenAICompatToolsMixin per dare tool-use ai provider OpenAI-compatible
(OpenAI, DeepSeek, Perplexity, Ollama, endpoint locali).
"""
from __future__ import annotations
import json
from typing import Any, Optional

from app.services.ai_provider import ToolUse, ToolUseResponse, safe_json_parse


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
            # safe_json_parse tollera fence/commenti/trailing-comma: i modelli
            # locali (Ollama/llama.cpp) spesso emettono arguments malformati.
            parsed = safe_json_parse(args)
            args = parsed if isinstance(parsed, dict) else {}
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
