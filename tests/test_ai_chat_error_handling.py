"""v3.5.0-alpha.172.189 — l'endpoint /ai/api/chat non deve mai restituire un
500 plain-text: qualsiasi eccezione non gestita → JSON pulito con
error=internal_error. HTTPException invece passa intatta (JSON via FastAPI).
"""
import asyncio
import json as _json
import pytest
from fastapi import HTTPException
from app.routers import ai as ai_router


class _DummyDB:
    def rollback(self):
        pass


def test_chat_wraps_exceptions_as_clean_json(monkeypatch):
    async def boom(request, access_token, db):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(ai_router, "_chat_impl", boom)
    resp = asyncio.run(ai_router.chat(request=None, access_token=None, db=_DummyDB()))
    assert resp.status_code == 200
    body = _json.loads(resp.body)
    assert body["error"] == "internal_error"
    assert body["actions"] == []
    assert isinstance(body["reply"], str) and body["reply"]


def test_chat_passes_through_httpexception(monkeypatch):
    async def boom(request, access_token, db):
        raise HTTPException(400, "Nessun messaggio")
    monkeypatch.setattr(ai_router, "_chat_impl", boom)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ai_router.chat(request=None, access_token=None, db=_DummyDB()))
    assert ei.value.status_code == 400
