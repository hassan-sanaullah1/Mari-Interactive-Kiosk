"""Byte-for-byte guard on the /ws endpoint and the lipsync frames it sends.

``test_golden_snapshots.py`` calls ``run_reply`` directly with A2F off, so the socket
endpoint and the whole lipsync path are unguarded there. This drives the real app over
a test websocket with every provider faked, and compares the full ordered frame list.

A mismatch means behaviour changed — fix the code, do not regenerate the fixture
(see tests/ws_harness.py).
"""

from __future__ import annotations

import json

import pytest

from tests.ws_harness import FIXTURE, collect


@pytest.fixture(scope="module")
def expected() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def actual() -> dict:
    monkeypatch = pytest.MonkeyPatch()
    try:
        # Round-tripped through JSON so tuples and the fixture's types agree.
        return json.loads(json.dumps(collect(monkeypatch.setattr), ensure_ascii=False))
    finally:
        monkeypatch.undo()


def test_same_scenarios(expected, actual) -> None:
    assert sorted(actual["scenarios"]) == sorted(expected["scenarios"])


def _scenario_names() -> list[str]:
    return sorted(json.loads(FIXTURE.read_text(encoding="utf-8"))["scenarios"])


@pytest.mark.parametrize("name", _scenario_names())
def test_scenario_matches(expected, actual, name) -> None:
    assert actual["scenarios"][name] == expected["scenarios"][name]


def test_lipsync_protocol_shape(expected) -> None:
    """The lipsync contract the browser's player depends on, asserted directly.

    The snapshot above would catch a change here, but not explain it; these spell
    out what blendshapePlayer.ts requires of every clip.
    """
    for name, record in expected["scenarios"].items():
        frames = [f for f in record["socket"] if f.get("type") == "lipsync"]
        if not frames:
            continue
        by_clip: dict[str, list[dict]] = {}
        for frame in frames:
            by_clip.setdefault(frame["uid"], []).append(frame)

        for uid, clip in by_clip.items():
            named = [f for f in clip if "names" in f]
            assert len(named) == 1, f"{name}/{uid}: names must be sent exactly once"
            assert clip[0] is named[0], f"{name}/{uid}: names must arrive before any frame"
            width = len(named[0]["names"]) + 1  # one leading time code
            previous = -1.0
            for frame in clip:
                for row in frame["frames"]:
                    assert len(row) == width, f"{name}/{uid}: frame width must match names"
                    assert row[0] >= previous, f"{name}/{uid}: frame times must not go backwards"
                    previous = row[0]
                    assert all(0.0 <= weight <= 1.0 for weight in row[1:]), (
                        f"{name}/{uid}: weights outside [0,1] tear the mesh"
                    )

        # Every clip id announced in a {"tts"} header must actually get frames, and
        # no clip may send frames the browser has no audio element for.
        tts_clips = {f["clip"] for f in record["socket"] if f.get("type") == "tts" and f.get("clip")}
        assert set(by_clip) == tts_clips, f"{name}: lipsync clips and tts clips disagree"


def test_turn_always_ends(expected) -> None:
    """Every scenario closes with exactly one terminal frame, or none at all.

    The browser's reply queue waits on {"done"}; a turn that ends without one (and
    without an error) leaves the kiosk's mic shut.
    """
    for name, record in expected["scenarios"].items():
        terminal = [f for f in record["socket"] if f.get("type") in ("done", "error")]
        if name == "disconnect/before_end":
            assert not record["socket"], "a closed socket gets nothing"
            continue
        assert len(terminal) == 1, f"{name}: expected one done/error, got {terminal}"
