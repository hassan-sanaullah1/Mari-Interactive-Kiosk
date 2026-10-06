"""MARI is a female persona, and Urdu marks gender on verbs.

Any Urdu string describing what MARI is doing — in the prompts or in the two UIs —
has to use feminine forms. Masculine is Urdu's default, so these regress easily:
a new status label written as "سن رہا ہے" reads as a male assistant.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

from server.agent.replies import canned
from server.agent.reply_fixes import feminine_agreement, masculine_agreement
from server.prompts import get_prompts

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
    assert "مؤنث صیغہ" in get_prompts().system[("female", "ur")]


def test_urdu_canned_lines_agree_with_the_presenter() -> None:
    """The canned lines never pass through the LLM or the gender_agreement pass, so
    each one carries the presenter's own verb form or the kiosk speaks the wrong
    gender in the two moments a visitor is most likely to hear it."""
    # (line, feminine verb, masculine verb): the demo line is a present-tense
    # "can't answer", the no-speech line a past-tense "didn't catch".
    for name, fem, masc in (
        ("demo", "سکتی", "سکتا"),
        ("no_speech", "سکی", "سکا"),
    ):
        female = canned(name, "ur", "female")
        male = canned(name, "ur", "male")
        assert fem in female and masc not in female
        assert masc in male and fem not in male
        # An unknown rig degrades to the default presenter rather than raising.
        assert canned(name, "ur", "nobody") == female
        assert canned(name, "fr", "male") == canned(name, "en", "male")


def test_the_male_presenter_never_gets_the_female_persona() -> None:
    """The loudest failure there is: the male rig introducing itself as Maryam."""
    from server.services.generation import GenerationService

    svc = GenerationService()
    male_ur = svc.rules("ur", "male")
    assert "حمزہ" in male_ur and "مریم" not in male_ur
    assert "مذکر" in male_ur
    assert "Hamza" in svc.rules("en", "male") and "Maryam" not in svc.rules("en", "male")
    assert "مریم" in svc.rules("ur", "female")


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
    assert masculine_agreement(given, "ur") == expected


@pytest.mark.parametrize("given", _MASCULINE_LEAVES_ALONE)
def test_masculine_agreement_leaves_other_subjects_alone(given) -> None:
    assert masculine_agreement(given, "ur") == given


@pytest.mark.parametrize("given", [g for g, _ in _MASCULINE_FIXES] + _MASCULINE_LEAVES_ALONE)
def test_feminine_agreement_never_touches_verbs(given) -> None:
    """The female rig's pass only ever fixes the possessive, so every one of these —
    already correct for Maryam — must survive it untouched."""
    assert feminine_agreement(given, "ur") == given
