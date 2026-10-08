"""Urdu marks gender on verbs, and the kiosk has a presenter of each.

Every line describing what the presenter is doing — spoken or on screen — has to agree
with who is on screen. Masculine is Urdu's default, so the feminine forms regress
easily: a status label written as "سن رہا ہے" reads as a male assistant under the
female presenter.

The spoken side is `server/agent/reply_fixes.py`, selected by the presenter's
`grammatical_gender` in personas.toml. The UI side is `uiCopy()` in
`frontend/lib/i18n.ts`. That the two agree is checked in
`tests/test_personas_are_data.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from server.agent.replies import canned
from server.agent.reply_fixes import feminine_agreement, masculine_agreement
from server.prompts import get_prompts

ROOT = Path(__file__).resolve().parent.parent

# Masculine verb endings that describe the speaker/subject. Each has a feminine
# counterpart (رہا->رہی, سکتا->سکتی, تھا->تھی, رہے گا->رہے گی).
MASCULINE = ("رہا ہے", "رہا ہوں", "سکتا ہوں", "سکتا ہے", "رہا تھا", "سنتا", "رہے گا")

I18N = ROOT / "frontend" / "lib" / "i18n.ts"

# The copy keys that describe the presenter mid-turn, and so must be gendered. Anything
# else — an instruction to the visitor, a label, the product's own name — is not.
PRESENTER_LINES = ("listening", "thinking", "speaking", "paused")


def _urdu_strings(path: Path) -> list[str]:
    """Quoted literals in the file that contain Urdu text."""
    return [
        lit
        for lit in re.findall(r'"([^"\n]*)"', path.read_text(encoding="utf-8"))
        if re.search(r"[ؠ-ۿ]", lit)
    ]


def _copy_block(name: str) -> str:
    """The body of a named object literal in i18n.ts."""
    text = I18N.read_text(encoding="utf-8")
    start = text.index(name)
    return text[start : text.index("};", start)]


def test_default_urdu_copy_is_feminine() -> None:
    """The base table is the female presenter's, so masculine forms must not appear."""
    urdu_block = _copy_block("  ur: {")
    offenders = [
        line
        for line in re.findall(r'"([^"\n]*)"', urdu_block)
        if re.search(r"[ؠ-ۿ]", line) and any(m in line for m in MASCULINE)
    ]
    assert not offenders, (
        f"masculine forms in the default Urdu copy: {offenders}. The base table is the "
        "feminine one; masculine goes in MASCULINE_UR."
    )


def test_every_presenter_line_has_a_masculine_form() -> None:
    """A gendered line with no masculine override shows the wrong gender for him."""
    masculine_block = _copy_block("const MASCULINE_UR")
    missing = [key for key in PRESENTER_LINES if f"{key}:" not in masculine_block]
    assert not missing, (
        f"these lines describe the presenter but have no masculine form: {missing}"
    )


def test_masculine_overrides_are_actually_masculine() -> None:
    masculine_block = _copy_block("const MASCULINE_UR")
    lines = [
        line
        for line in re.findall(r'"([^"\n]*)"', masculine_block)
        if re.search(r"[ؠ-ۿ]", line)
    ]
    assert lines, "MASCULINE_UR has no Urdu lines"
    feminine = ("رہی ہے", "رہی ہوں", "سکتی ہوں", "سکتی ہے", "رہی تھی", "رکی")
    offenders = [line for line in lines if any(f in line for f in feminine)]
    assert not offenders, f"feminine forms inside the masculine overrides: {offenders}"


def test_no_stray_urdu_outside_the_copy_tables() -> None:
    """Urdu copy belongs in i18n.ts, where the gender rule above can police it."""
    frontend = ROOT / "frontend"
    offenders = []
    for path in list(frontend.glob("app/**/*.tsx")) + list(frontend.glob("components/**/*.tsx")):
        for line in _urdu_strings(path):
            offenders.append(f"{path.relative_to(ROOT)}: {line}")
    assert not offenders, (
        "Urdu text outside lib/i18n.ts, where nothing checks its gender:\n  "
        + "\n  ".join(offenders)
    )


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
    from server.rag.generation import GenerationService

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
