"""Where the admin panel's username and password live, and how they are checked.

`MARI_ADMIN_TOKEN` is passed into the container as a real environment variable, so it
cannot be rewritten from inside: it is the INITIAL password only. The first time the
operator changes it, the new credentials are written to a file on the `rag_state`
volume, which is writable and survives a container recreate and an image rebuild.
While that file is absent the env token stands in, so a fresh deployment works with
nothing to set up; once it exists the env token stops being accepted, otherwise
changing the password would never actually retire the old one.

Forgotten password, on the kiosk:

    docker exec mari-interactive-kiosk-backend-1 rm -f /app/state/admin-credentials.json

which reverts to `mari` plus `MARI_ADMIN_TOKEN` from `.env`.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import tempfile
from dataclasses import dataclass
from hashlib import scrypt
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

# The state volume (docker-compose.yml: rag_state:/app/state). Falls back to a path
# beside the code when the server runs outside a container, as the tests do.
_STATE_DIR = Path(os.environ.get("MARI_STATE_DIR", "/app/state"))
_FALLBACK_DIR = Path(__file__).resolve().parent.parent / "state"

#: Username before anyone changes it.
DEFAULT_USER: Final = "mari"

# scrypt parameters. n=2**14 costs roughly 100 ms on this hardware — slow enough that
# guessing the password offline from a stolen file is expensive, fast enough that a
# sign-in does not feel delayed.
_SCRYPT_N: Final = 2**14
_SCRYPT_R: Final = 8
_SCRYPT_P: Final = 1
_KEY_LEN: Final = 32

MIN_PASSWORD_LENGTH: Final = 8


class CredentialError(ValueError):
    """A proposed username or password that the rules reject."""


@dataclass(frozen=True)
class Credentials:
    """The stored pair. `password_hash` and `salt` are hex."""

    user: str
    password_hash: str
    salt: str


def _state_path() -> Path:
    directory = _STATE_DIR if _STATE_DIR.is_dir() else _FALLBACK_DIR
    return directory / "admin-credentials.json"


def _hash(password: str, salt: bytes) -> str:
    derived = scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_LEN
    )
    return derived.hex()


def load() -> Credentials | None:
    """The stored credentials, or None while the operator has never changed them."""
    path = _state_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Credentials(user=raw["user"], password_hash=raw["hash"], salt=raw["salt"])
    except (OSError, ValueError, KeyError):
        # A truncated or hand-edited file must not lock the panel shut: fall back to
        # the env token, which is what a fresh deployment uses anyway.
        logger.exception("admin credentials file is unreadable; falling back to MARI_ADMIN_TOKEN")
        return None


def save(user: str, password: str) -> None:
    """Write new credentials, replacing any stored pair."""
    salt = secrets.token_bytes(16)
    payload = json.dumps(
        {"user": user, "hash": _hash(password, salt), "salt": salt.hex()}, indent=2
    )
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file in the same directory, then rename: a crash mid-write must
    # not leave a half-written file that locks the operator out.
    handle, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".credentials-")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        tmp.chmod(0o600)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    logger.info("admin credentials updated (user=%s)", user)


def verify(user: str | None, password: str | None) -> bool:
    """Are these the current credentials?

    Both halves are always compared, and the comparisons are constant time, so a
    wrong username is not measurably faster than a wrong password.
    """
    candidate_user = user or ""
    candidate_password = password or ""
    stored = load()

    if stored is None:
        # Nothing stored yet: the environment token and the default username.
        expected_token = os.environ.get("MARI_ADMIN_TOKEN", "")
        if not expected_token:
            return False
        user_ok = hmac.compare_digest(DEFAULT_USER, candidate_user)
        token_ok = hmac.compare_digest(expected_token, candidate_password)
        return user_ok and token_ok

    user_ok = hmac.compare_digest(stored.user, candidate_user)
    password_ok = hmac.compare_digest(
        stored.password_hash, _hash(candidate_password, bytes.fromhex(stored.salt))
    )
    return user_ok and password_ok


def is_configured() -> bool:
    """Can anyone sign in at all? False means every admin route must refuse."""
    return load() is not None or bool(os.environ.get("MARI_ADMIN_TOKEN", ""))


def current_user() -> str:
    """The username to show on the panel."""
    stored = load()
    return stored.user if stored else DEFAULT_USER


def validate(user: str, password: str) -> None:
    """Reject a new pair that would be unusable or too weak. Raises CredentialError."""
    if not user.strip():
        raise CredentialError("the username cannot be empty")
    if len(user.strip()) > 64:
        raise CredentialError("the username is too long")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise CredentialError(f"the password must be at least {MIN_PASSWORD_LENGTH} characters")
    if not any(character.isdigit() for character in password):
        raise CredentialError("the password must contain a number")
