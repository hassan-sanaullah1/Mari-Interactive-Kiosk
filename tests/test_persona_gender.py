"""MARI is a female persona, and Urdu marks gender on verbs.

Any Urdu string describing what MARI is doing — in the prompts or in the two UIs —
has to use feminine forms. Masculine is Urdu's default, so these regress easily:
a new status label written as "سن رہا ہے" reads as a male assistant.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import knowledge as K  # noqa: E402

# Masculine verb endings that describe the speaker/subject. Each has a feminine
# counterpart (رہا->رہی, سکتا->سکتی, تھا->تھی, رہے گا->رہے گی).
MASCULINE = ("رہا ہے", "رہا ہوں", "سکتا ہوں", "سکتا ہے", "رہا تھا", "سنتا", "رہے گا")

UI_FILES = ("frontend/lib/i18n.ts", "web/app.js")


def _urdu_strings(path: Path) -> list[str]:
    """Quoted literals in the file that contain Urdu text."""
    return [
        lit
        for lit in re.findall(r'"([^"\n]*)"', path.read_text(encoding="utf-8"))
        if re.search(r"[ؠ-ۿ]", lit)
    ]


@pytest.mark.parametrize("relpath", UI_FILES)
def test_ui_strings_use_feminine_forms(relpath: str) -> None:
    offenders = [
        s for s in _urdu_strings(ROOT / relpath) if any(m in s for m in MASCULINE)
    ]
    assert not offenders, f"masculine forms in {relpath}: {offenders}"


def test_urdu_prompt_instructs_feminine_self_reference() -> None:
    """The rule has to be stated, or the model drifts to Urdu's masculine default."""
    assert "مؤنث صیغہ" in K._RULES_UR


def test_urdu_canned_lines_agree_with_the_presenter() -> None:
    """The canned lines never pass through the LLM or the gender_agreement pass, so
    each one carries the presenter's own verb form or the kiosk speaks the wrong
    gender in the two moments a visitor is most likely to hear it."""
    from server.app import DEMO_REPLY, NO_SPEECH_REPLY, _canned

    # (table, feminine verb, masculine verb) — the demo line is a present-tense
    # "can't answer", the no-speech line a past-tense "didn't catch".
    for table, fem, masc in (
        (DEMO_REPLY, "سکتی", "سکتا"),
        (NO_SPEECH_REPLY, "سکی", "سکا"),
    ):
        female = _canned(table, "ur", "female")
        male = _canned(table, "ur", "male")
        assert fem in female and masc not in female
        assert masc in male and fem not in male
        # An unknown rig degrades to the default presenter rather than raising.
        assert _canned(table, "ur", "nobody") == female
        assert _canned(table, "fr", "male") == _canned(table, "en", "male")


def test_urdu_fallback_rules_agree_with_the_presenter() -> None:
    """The inline stub is what a missing prompt file falls back to; it names the
    presenter, so it cannot be shared between the two rigs."""
    from server.services.generation import _fallback_rules

    assert "مریم" in _fallback_rules("female", "ur")
    assert "مؤنث" in _fallback_rules("female", "ur")
    assert "حمزہ" in _fallback_rules("male", "ur")
    assert "مذکر" in _fallback_rules("male", "ur")
    assert "Hamza" in _fallback_rules("male", "en")
    assert _fallback_rules("nobody", "ur") == _fallback_rules("female", "ur")


def test_missing_male_prompt_never_falls_back_to_the_female_persona(monkeypatch) -> None:
    """A missing *_male.md must degrade to the male inline stub, not to Maryam's text.

    Only reachable when a prompt file is absent, so it is easy to regress unnoticed —
    and the failure mode is the loudest one there is: the male rig introducing itself
    as Maryam, in the feminine, on every turn.
    """
    import voice_config
    from server.services.generation import GenerationService

    real = voice_config.load_prompt
    monkeypatch.setattr(
        voice_config, "load_prompt", lambda n: None if n.endswith("_male") else real(n)
    )

    svc = GenerationService()
    svc.load_templates()

    male_ur = svc.rules("ur", "male")
    assert "حمزہ" in male_ur and "مریم" not in male_ur
    assert "مذکر" in male_ur
    assert "Hamza" in svc.rules("en", "male") and "Maryam" not in svc.rules("en", "male")
    # The female persona is untouched by the male files going missing.
    assert "مریم" in svc.rules("ur", "female")
    # And no male greeting is served rather than one that names the wrong presenter.
    assert ("male", "ur") not in svc._greetings


# (input, expected) for the male rig's runtime agreement pass. The second group is the
# one that matters most: Urdu marks the feminine on plenty of verbs that have nothing to
# do with the speaker, and an over-eager rewrite corrupts them.
_MASCULINE_FIXES = [
    ("معاف کیجیے، میں سن نہیں سکی۔", "معاف کیجیے، میں سن نہیں سکا۔"),
    ("میں آپ کا سوال سمجھ نہیں سکی۔", "میں آپ کا سوال سمجھ نہیں سکا۔"),
    ("میں یہ بتا نہیں پائی۔", "میں یہ بتا نہیں پایا۔"),
    ("میں آپ کی مدد کر سکتی ہوں۔", "میں آپ کی مدد کر سکتا ہوں۔"),
    ("میں بتا رہی ہوں۔", "میں بتا رہا ہوں۔"),
]

_MASCULINE_LEAVES_ALONE = [
    # The feminine agrees with a noun, not the speaker.
    "یہاں موجود ٹیم مدد کر سکتی ہے۔",
    "ٹیم یہ کام مکمل کر سکی۔",
    "کمپنی نے یہ رپورٹ شائع کی تھی۔",
    "Mari Energies کی پیداوار بڑھی تھی۔",
    # A new subject after a subordinator or a comma, inside a sentence that opens with میں.
    "میں بتا سکتا ہوں کہ ٹیم یہ کر سکی۔",
    "میں نے کہا تھا کہ رپورٹ شائع ہوئی تھی۔",
    "میں حاضر ہوں، ہماری ٹیم مدد کر سکی۔",
    "میں نے دیکھا کہ پیداوار بڑھ سکی۔",
    # Ergative "میں نے" agrees with the object — correct as it stands for a male speaker.
    "میں نے یہ رپورٹ پڑھی تھی۔",
]


@pytest.mark.parametrize("given,expected", _MASCULINE_FIXES)
def test_masculine_agreement_fixes_the_speakers_own_verb(given, expected) -> None:
    from voice_config import masculine_agreement

    assert masculine_agreement(given, "ur") == expected


@pytest.mark.parametrize("given", _MASCULINE_LEAVES_ALONE)
def test_masculine_agreement_leaves_other_subjects_alone(given) -> None:
    from voice_config import masculine_agreement

    assert masculine_agreement(given, "ur") == given


@pytest.mark.parametrize("given", [g for g, _ in _MASCULINE_FIXES] + _MASCULINE_LEAVES_ALONE)
def test_feminine_agreement_never_touches_verbs(given) -> None:
    """The female rig's pass only ever fixes the possessive, so every one of these —
    already correct for Maryam — must survive it untouched."""
    from voice_config import feminine_agreement

    assert feminine_agreement(given, "ur") == given
