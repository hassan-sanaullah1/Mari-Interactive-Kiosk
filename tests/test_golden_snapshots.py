"""Byte-for-byte guard on what the kiosk says and sends.

The fixture was generated from the code before the modular clean-up; every section here
must keep matching it. A mismatch means behaviour changed — fix the code, do not
regenerate the fixture (see tests/golden_harness.py).
"""

from __future__ import annotations

import json

import pytest

from tests.golden_harness import FIXTURE, collect


@pytest.fixture(scope="module")
def expected() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def actual(expected) -> dict:
    mp = pytest.MonkeyPatch()
    from server import config as C

    def set_env(key, value):
        if value is None:
            mp.delenv(key, raising=False)
            mp.delitem(C.ENV, key, raising=False)
        else:
            mp.setenv(key, value)
            mp.setitem(C.ENV, key, value)

    try:
        return json.loads(json.dumps(collect(mp.setattr, set_env, expected["inputs"]),
                                     ensure_ascii=False))
    finally:
        mp.undo()


@pytest.mark.parametrize("section", ["reply_fixes", "is_greeting", "expansion", "prompts", "canned"])
def test_section_matches(expected, actual, section) -> None:
    assert actual[section] == expected[section]


@pytest.mark.parametrize("lang", ["en", "ur"])
def test_tts_normalization_matches(expected, actual, lang) -> None:
    diffs = [
        (text, want, got)
        for text, want, got in zip(expected["inputs"]["tts"], expected["normalize"][lang],
                                   actual["normalize"][lang])
        if want != got
    ]
    assert not diffs[:5], f"{len(diffs)} normalization outputs changed"


def test_turns_match(expected, actual) -> None:
    assert sorted(actual["turns"]) == sorted(expected["turns"])
    for label, want in expected["turns"].items():
        assert actual["turns"][label] == want, label
