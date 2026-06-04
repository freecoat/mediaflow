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
    asst = [m for m in out if m["role"] == "assistant"][0]
    assert asst["tool_calls"][0]["id"] == "call_0"
    assert asst["tool_calls"][0]["function"]["name"] == "read_quote_lines"
    assert json.loads(asst["tool_calls"][0]["function"]["arguments"]) == {"quote_id": 18}
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
    assert resp.raw_assistant_message["role"] == "assistant"
    blocks = resp.raw_assistant_message["content"]
    assert any(b["type"] == "tool_use" and b["id"] == "call_9" for b in blocks)


def test_from_openai_message_ollama_object_args():
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


def test_from_openai_message_lenient_args_trailing_comma():
    # modello locale emette JSON con trailing comma → safe_json_parse lo tollera
    msg = {"content": "", "tool_calls": [
        {"function": {"name": "read_quote_lines", "arguments": "{\"quote_id\": 3,}"}},
    ]}
    resp = from_openai_message(msg)
    assert resp.tool_uses[0].input == {"quote_id": 3}


def test_round_trip_id_stability_no_id():
    """raw_assistant_message di from_openai_message (id generato) deve
    ri-convertirsi con to_openai_messages mantenendo lo stesso id, così il
    tool_result successivo combacia. Proprietà critica per advance_loop."""
    resp = from_openai_message({"content": "calcolo", "tool_calls": [
        {"function": {"name": "read_quote_lines", "arguments": {"quote_id": 18}}},
    ]})
    gen_id = resp.tool_uses[0].id
    assert gen_id
    canonical = [
        {"role": "user", "content": "conta"},
        resp.raw_assistant_message,
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": gen_id, "content": "{\"counts\": {\"consegne\": 15}}"},
        ]},
    ]
    out = to_openai_messages(canonical, system=None)
    asst = [m for m in out if m["role"] == "assistant"][0]
    tool_msg = [m for m in out if m["role"] == "tool"][0]
    assert asst["tool_calls"][0]["id"] == gen_id
    assert tool_msg["tool_call_id"] == gen_id
