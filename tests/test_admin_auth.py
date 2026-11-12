"""The admin panel's authentication, pinned.

Every route here is reachable from any PC on the office Wi-Fi and manages the files
the kiosk answers from. These tests exist because of a real regression: an earlier
_check_token substituted the stored username when the X-Admin-User header was absent,
so a caller who knew only the password was let straight in and the username protected
nothing at all. A missing credential must FAIL the check, never skip it.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from server import admin, admin_credentials

USER = "mari"
PASSWORD = "rightpass1"


def headers(user: str | None = None, token: str | None = None) -> dict[str, str]:
    """Only the headers actually given, so a `None` is genuinely absent."""
    pairs = (("X-Admin-User", user), ("X-Admin-Token", token))
    return {key: value for key, value in pairs if value is not None}


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The admin router over an isolated corpus and credential store."""
    corpus = tmp_path / "data"
    corpus.mkdir()
    (corpus / "existing.md").write_text("# Existing\n", encoding="utf-8")

    class _Settings:
        corpus_dir = corpus

    monkeypatch.setattr(admin, "get_settings", lambda: _Settings())
    monkeypatch.setattr(admin_credentials, "_STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("MARI_ADMIN_TOKEN", PASSWORD)

    async def _no_ingest() -> dict:
        return {"chunks": 1, "duration_s": 0.1, "failed": {}}

    monkeypatch.setattr(admin, "_reingest", _no_ingest)

    app = FastAPI()
    app.include_router(admin.router)
    yield TestClient(app)


# ── The regression itself ────────────────────────────────────────────


def test_the_right_credentials_are_accepted(client: TestClient) -> None:
    assert client.get("/upload/kb", headers=headers(USER, PASSWORD)).status_code == 200


@pytest.mark.parametrize(
    "sent",
    [
        pytest.param(headers(token=PASSWORD), id="username header omitted"),
        pytest.param(headers("", PASSWORD), id="username header empty"),
        pytest.param(headers("someone-else", PASSWORD), id="wrong username"),
        pytest.param(headers(USER), id="password header omitted"),
        pytest.param(headers(USER, ""), id="password header empty"),
        pytest.param(headers(USER, "wrong"), id="wrong password"),
        pytest.param({}, id="no headers at all"),
    ],
)
def test_a_missing_or_wrong_credential_is_refused(client: TestClient, sent: dict) -> None:
    """Knowing one half must never be enough: a missing header fails the check.

    The omitted-username case is the regression - it used to return 200.
    """
    assert client.get("/upload/kb", headers=sent).status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/upload/kb", None),
        ("get", "/upload/whoami", None),
        ("get", "/upload/kb/existing.md", None),
        ("delete", "/upload/kb/existing.md", None),
        (
            "post",
            "/upload/credentials",
            {"current_password": PASSWORD, "new_user": "x", "new_password": "zzzzzzz1"},
        ),
    ],
)
def test_no_route_accepts_the_password_alone(
    client: TestClient, method: str, path: str, body: dict | None
) -> None:
    """Every route, not just the listing: one guard missed is the whole panel open."""
    call = getattr(client, method)
    response = call(path, headers=headers(token=PASSWORD), **({"json": body} if body else {}))
    assert response.status_code == 401


def test_the_username_argument_has_no_default() -> None:
    """A default would let a future route call _check_token(token) and authenticate on
    the password alone - which is exactly how the regression was introduced."""
    import inspect

    parameter = inspect.signature(admin._check_token).parameters["user"]
    assert parameter.default is inspect.Parameter.empty


# ── Changing the credentials ─────────────────────────────────────────


def test_changing_credentials_retires_the_old_pair(client: TestClient) -> None:
    """The point of a password change is that the old one stops working."""
    response = client.post(
        "/upload/credentials",
        headers=headers(USER, PASSWORD),
        json={"current_password": PASSWORD, "new_user": "admin", "new_password": "newpass2026"},
    )
    assert response.status_code == 200
    assert response.json()["user"] == "admin"

    assert client.get("/upload/kb", headers=headers("admin", "newpass2026")).status_code == 200
    assert client.get("/upload/kb", headers=headers(USER, PASSWORD)).status_code == 401
    # The new password with the OLD username must not work either.
    assert client.get("/upload/kb", headers=headers(USER, "newpass2026")).status_code == 401
    # And the new username is what /whoami reports.
    assert client.get("/upload/whoami", headers=headers("admin", "newpass2026")).json()["user"] == "admin"


def test_changing_credentials_needs_the_current_password(client: TestClient) -> None:
    """Being signed in is not enough: a browser left open must not lock the owner out."""
    response = client.post(
        "/upload/credentials",
        headers=headers(USER, PASSWORD),
        json={"current_password": "not-it", "new_user": "admin", "new_password": "newpass2026"},
    )
    assert response.status_code == 401
    # Unchanged.
    assert client.get("/upload/kb", headers=headers(USER, PASSWORD)).status_code == 200


@pytest.mark.parametrize(
    ("password", "reason"),
    [("short1", "too short"), ("nodigitshere", "no digit")],
)
def test_a_weak_new_password_is_refused(client: TestClient, password: str, reason: str) -> None:
    response = client.post(
        "/upload/credentials",
        headers=headers(USER, PASSWORD),
        json={"current_password": PASSWORD, "new_user": "admin", "new_password": password},
    )
    assert response.status_code == 400, reason


def test_the_password_is_never_stored_in_clear(client: TestClient, tmp_path) -> None:
    client.post(
        "/upload/credentials",
        headers=headers(USER, PASSWORD),
        json={"current_password": PASSWORD, "new_user": "admin", "new_password": "newpass2026"},
    )
    stored = (tmp_path / "state" / "admin-credentials.json").read_text(encoding="utf-8")
    assert "newpass2026" not in stored
    assert "hash" in stored and "salt" in stored


def test_deleting_the_file_restores_the_env_password(client: TestClient, tmp_path) -> None:
    """The documented recovery path (docs/admin-panel.md) has to keep working."""
    client.post(
        "/upload/credentials",
        headers=headers(USER, PASSWORD),
        json={"current_password": PASSWORD, "new_user": "admin", "new_password": "newpass2026"},
    )
    assert client.get("/upload/kb", headers=headers(USER, PASSWORD)).status_code == 401
    (tmp_path / "state" / "admin-credentials.json").unlink()
    assert client.get("/upload/kb", headers=headers(USER, PASSWORD)).status_code == 200


def test_an_unset_token_closes_the_panel(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """No credentials configured must mean closed, not open."""
    monkeypatch.setenv("MARI_ADMIN_TOKEN", "")
    assert client.get("/upload/kb", headers=headers(USER, PASSWORD)).status_code == 503
