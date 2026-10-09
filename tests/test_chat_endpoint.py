"""Pins the JSON `/chat` returns in each of its four outcomes.

The golden snapshot only covers the streaming `/ws` path, so a change to the response
model here would otherwise ship unnoticed. `error` in particular must be absent, not
null, unless the LLM call failed.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from server import app as app_module
from server.agent.policy import Fallback


@pytest.fixture
def client() -> TestClient:
    # Not used as a context manager, so the startup hooks (model warm-up, retrieval)
    # never run.
    return TestClient(app_module.app)


def test_empty_text_returns_an_empty_reply(client: TestClient) -> None:
    body = client.post("/chat", json={"text": "   "}).json()
    assert set(body) == {"reply", "demo"}
    assert body["reply"] == ""


def test_stand_in_reply_when_the_llm_is_not_used(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app_module, "fallback_reply", lambda lang, avatar: Fallback("pitch", is_demo=False)
    )
    body = client.post("/chat", json={"text": "hello"}).json()
    assert body == {"reply": "pitch", "demo": False}


def test_answered_reply(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_respond(text: str, lang: str, history: object, avatar: str) -> str:
        return f"answer to {text}"

    monkeypatch.setattr(app_module, "fallback_reply", lambda lang, avatar: None)
    monkeypatch.setattr(app_module, "respond", fake_respond)
    body = client.post("/chat", json={"text": "hello", "lang": "en"}).json()
    assert body == {"reply": "answer to hello", "demo": False}


def test_failed_llm_call_carries_an_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_respond(text: str, lang: str, history: object, avatar: str) -> str:
        raise RuntimeError("upstream down")

    monkeypatch.setattr(app_module, "fallback_reply", lambda lang, avatar: None)
    monkeypatch.setattr(app_module, "respond", failing_respond)
    monkeypatch.setattr(
        app_module, "failure_reply", lambda lang, avatar: Fallback("sorry", is_demo=True)
    )
    body = client.post("/chat", json={"text": "hello"}).json()
    assert body == {"reply": "sorry", "demo": True, "error": "upstream down"}
