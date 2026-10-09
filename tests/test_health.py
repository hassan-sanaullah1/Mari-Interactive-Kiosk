"""The health endpoints a container platform and a person checking a deployment rely on.

`/health/ready` is the container's HEALTHCHECK, so a wrong 200 hides a broken deploy and
a wrong 503 marks a working kiosk unhealthy. Retrieval still warming must count as
ready: turns are answered from the core brief meanwhile. `/healthz` is for developers
and must not leak internal hostnames.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from server import app as app_module
from server import config, rag


@pytest.fixture
def client() -> TestClient:
    # Not a context manager, so the startup hooks (model warm-up, retrieval) never run.
    return TestClient(app_module.app)


def _ready_with(monkeypatch: pytest.MonkeyPatch, *, llm: bool, qdrant: str) -> None:
    async def fake_readiness() -> str:
        return qdrant

    monkeypatch.setattr(config, "FORCE_DEMO", False)
    monkeypatch.setattr(config, "llm_ready", lambda: llm)
    monkeypatch.setattr(app_module.rag, "readiness", fake_readiness)


def test_live_is_always_ok(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_environment_and_commit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready_with(monkeypatch, llm=True, qdrant="ok")
    monkeypatch.setattr(config, "APP_ENV", "staging")
    monkeypatch.setattr(config, "APP_COMMIT", "a1b2c3d")
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "staging",
        "commit": "a1b2c3d",
        "checks": {"llm": "ok", "qdrant": "ok"},
    }


def test_retrieval_warming_still_counts_as_ready(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready_with(monkeypatch, llm=True, qdrant="warming")
    assert client.get("/health/ready").status_code == 200


@pytest.mark.parametrize(("llm", "qdrant"), [(True, "fail"), (False, "ok")])
def test_ready_is_503_when_a_dependency_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, llm: bool, qdrant: str
) -> None:
    _ready_with(monkeypatch, llm=llm, qdrant=qdrant)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "fail"


def test_demo_mode_counts_as_ready(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready_with(monkeypatch, llm=False, qdrant="ok")
    monkeypatch.setattr(config, "FORCE_DEMO", True)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["llm"] == "demo"


# ── rag.readiness ───────────────────────────────────────────────────


def _retriever_whose_store(health: object) -> SimpleNamespace:
    return SimpleNamespace(store=SimpleNamespace(health=health))


def test_readiness_before_and_after_a_failed_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag, "_retriever", None)
    monkeypatch.setattr(rag, "_status", {"state": "warming"})
    assert asyncio.run(rag.readiness()) == "warming"
    monkeypatch.setattr(rag, "_status", {"state": "failed"})
    assert asyncio.run(rag.readiness()) == "fail"


def test_readiness_follows_qdrant(monkeypatch: pytest.MonkeyPatch) -> None:
    async def reachable() -> dict:
        return {"reachable": True}

    async def unreachable() -> dict:
        return {"reachable": False}

    monkeypatch.setattr(rag, "_retriever", _retriever_whose_store(reachable))
    assert asyncio.run(rag.readiness()) == "ok"
    monkeypatch.setattr(rag, "_retriever", _retriever_whose_store(unreachable))
    assert asyncio.run(rag.readiness()) == "fail"


def test_readiness_gives_up_within_its_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def hangs() -> dict:
        await asyncio.sleep(10)
        return {"reachable": True}

    monkeypatch.setattr(rag, "_retriever", _retriever_whose_store(hangs))
    assert asyncio.run(rag.readiness(timeout_s=0.05)) == "fail"


# ── /healthz ────────────────────────────────────────────────────────


def _keys_and_values(node: object) -> tuple[set[str], list[str]]:
    keys: set[str] = set()
    values: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(key)
            child_keys, child_values = _keys_and_values(value)
            keys |= child_keys
            values += child_values
    elif isinstance(node, list):
        for item in node:
            child_keys, child_values = _keys_and_values(item)
            keys |= child_keys
            values += child_values
    elif isinstance(node, str):
        values.append(node)
    return keys, values


def test_healthz_exposes_no_internal_hostnames(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import server.avatar

    async def a2f_status() -> dict:
        return {"configured": True, "client": True, "connected": False, "ready": False}

    async def rag_health() -> dict:
        return {"enabled": False, "state": "not started"}

    # Point every URL-bearing setting somewhere recognisable, then make sure none of it
    # comes back out.
    monkeypatch.setattr(config, "LLM_BASE", "http://llm.internal:8000/v1")
    monkeypatch.setattr(config, "UR_TTS", "uplift")
    monkeypatch.setattr(server.avatar, "a2f_status", a2f_status)
    monkeypatch.setattr(app_module.rag, "health", rag_health)
    keys, values = _keys_and_values(client.get("/healthz").json())
    assert not keys & {"url", "base"}
    assert not [v for v in values if "://" in v]
