"""The Urdu greeting opener.

The prompt asks a greeting reply to start with "السلام علیکم". DeepSeek complied; Qwen
3.5 does not — sampling twelve greetings it opened with "وعلیکم السلام", with
"آپ کا خیر مقدم ہے", or with no salam at all about a third of the time, and once with the
non-word "نمٹے". The opener is a fixed string on a turn the server has already classified,
so it is normalised in code instead of being left to the model.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import knowledge  # noqa: E402
from voice_config.greetings import force_salam  # noqa: E402


@pytest.mark.parametrize(
    "reply",
    [
        "وعلیکم السلام، میں ماری ہوں۔",
        "آپ کا خیر مقدم ہے، میں ماری ہوں۔",
        "آپ کا شکریہ، میں حاضر ہوں۔",
        "میں ماری ہوں، Mari Energies کی AI Representative۔",
        "نمٹے، آپ کا خیر مقدم ہے، بتا رہی ہوں کہ کس طرح مدد کر سکتی ہوں؟",
    ],
)
def test_every_wrong_opener_becomes_the_salam(reply: str) -> None:
    said = force_salam(reply, "ur")
    assert said.startswith("السلام علیکم")
    for wrong in ("وعلیکم السلام", "خیر مقدم", "نمٹے", "آپ کا شکریہ"):
        assert not said.startswith(wrong)


def test_a_correct_opener_is_left_as_one_salam() -> None:
    said = force_salam("السلام علیکم! میں ماری ہوں۔", "ur")
    assert said.count("السلام علیکم") == 1


def test_the_rest_of_the_reply_survives() -> None:
    """Only the opener is replaced — the introduction is still the model's."""
    said = force_salam("وعلیکم السلام، میں ماری ہوں، Mari Energies کی نمائندہ۔", "ur")
    assert "میں ماری ہوں، Mari Energies کی نمائندہ۔" in said


@pytest.mark.parametrize(
    "reply",
    [
        "Hello! I am Maryam from Mari Energies.",
        "Walaikum assalam, I am Maryam.",
        "Wa alaikum as-salam! I am Maryam.",
        "Assalam o alaikum, I am Maryam.",
        "Welcome to Mari Energies! I am Maryam.",
        "Good morning, I am Maryam.",
        "I am Maryam from Mari Energies.",
    ],
)
def test_english_greetings_open_with_one_assalamualaikum(reply: str) -> None:
    said = force_salam(reply, "en")
    assert said.startswith("Assalamualaikum")
    assert said.lower().count("assalam") == 1
    assert "Maryam" in said


@pytest.mark.parametrize("reply", ["Highly productive fields.", "Heyward is a name.",
                                   "Salamander facts."])
def test_a_word_that_merely_starts_like_a_greeting_is_not_eaten(reply: str) -> None:
    """"hi" must not swallow the start of "Highly" — the opener match is word-bounded."""
    assert force_salam(reply, "en") == f"Assalamualaikum! {reply}"


def test_other_languages_are_untouched() -> None:
    assert force_salam("Bonjour, je suis Maryam.", "fr") == "Bonjour, je suis Maryam."


def test_an_empty_reply_is_not_turned_into_a_bare_salam() -> None:
    assert force_salam("", "ur") == ""
    assert force_salam("", "en") == ""
    assert force_salam("Assalamualaikum", "en") == "Assalamualaikum"
    assert force_salam("وعلیکم السلام", "ur") == "وعلیکم السلام"


# ── which turns count as a greeting ──────────────────────────────────

@pytest.mark.parametrize(
    "text", ["السلام علیکم", "ہیلو", "آپ کون ہیں؟", "آپ کون ہیں", "اپنا تعارف کرائیں؟", "hi"]
)
def test_greeting_turns_are_detected(text: str) -> None:
    assert knowledge.is_greeting(text)


def test_urdu_question_mark_is_recognised() -> None:
    """"؟" is U+061F, not ASCII "?" — with only the ASCII form in the pattern,
    "آپ کون ہیں؟" was never detected and an identity question got no introduction."""
    assert knowledge.is_greeting("آپ کون ہیں؟")


@pytest.mark.parametrize("text", ["منافع کتنا ہے؟", "ماری کا منافع؟", "who is the CEO"])
def test_ordinary_questions_are_not_greetings(text: str) -> None:
    """The base prompt forbids a salam on these turns, so they must not be normalised."""
    assert not knowledge.is_greeting(text)


@pytest.mark.parametrize("text", [
    # A salam, an intro ask and a real question in one breath — how a visitor actually
    # opens. This matched neither pattern, so the kiosk skipped its own introduction.
    "السلام علیکم۔ اپنا انٹروڈکشن دیجیے، اور مجھے ماری انرجیز کے ورٹیکلز کے بارے میں بتائیے۔",
    "سلام، مجھے verticals بتائیں",
    # The borrowed "انٹروڈکشن" and the "دیجیے/دیں" verbs, not just "تعارف کرائیں".
    "اپنا انٹروڈکشن دیجیے",
    "اپنا انٹروڈکشن دیں",
    "Hi, introduce yourself and tell me about the verticals",
])
def test_a_greeting_followed_by_a_real_question_still_greets(text: str) -> None:
    assert knowledge.is_greeting(text)


@pytest.mark.parametrize("text", [
    # The same question WITHOUT the greeting must not trigger the introduction.
    "ماری انرجیز کے ورٹیکلز کے بارے میں بتائیے۔",
    "tell me about Mari Energies",
    "کمپنی کی تاریخ بتائیں",
])
def test_the_same_question_without_a_greeting_does_not_greet(text: str) -> None:
    assert not knowledge.is_greeting(text)


# ── feminine agreement ──────────────────────────────────────────────
# Urdu marks gender on the possessive as well as on the verb. The prompt covers the
# verbs and Qwen gets those right, but it intermittently writes "میں Mari Energies کا
# AI Representative ہوں" — masculine "کا" for a female speaker.

@pytest.mark.parametrize(
    "reply",
    [
        "میں Mari Energies کا AI Representative ہوں۔",
        "میں Mari Energies کے AI Representative ہوں۔",
        "میں Mari Energies Limited کا نمائندہ ہوں۔",
        "میں Mari Energies کا ایک AI Representative ہوں۔",
    ],
)
def test_self_description_becomes_feminine(reply: str) -> None:
    from voice_config.greetings import feminine_agreement

    said = feminine_agreement(reply, "ur")
    assert "کی" in said                       # feminine possessive
    assert "کا" not in said and "کے" not in said


def test_an_already_feminine_self_description_is_unchanged() -> None:
    from voice_config.greetings import feminine_agreement

    text = "میں Mari Energies کی AI Representative ہوں۔"
    assert feminine_agreement(text, "ur") == text


@pytest.mark.parametrize(
    "text",
    [
        # the possessive agrees with "kiosk" here, not with MARI — rewriting it would
        # introduce an error rather than remove one
        "میں Mari Energies کے kiosk پر موجود AI Representative ہوں۔",
        "میں Mari Energies کے انٹرایکٹو kiosk پر موجود ایک AI Representative ہوں۔",
        # nothing to do with the speaker at all
        "کمپنی کا منافع 65.14 ارب روپے تھا۔",
        "یہ Mari Energies کا سب سے بڑا منصوبہ ہے۔",
        "بورڈ کے چیئرمین انور علی حیدر ہیں۔",
    ],
)
def test_possessives_that_are_not_about_mari_are_left_alone(text: str) -> None:
    from voice_config.greetings import feminine_agreement

    assert feminine_agreement(text, "ur") == text


def test_english_replies_are_not_touched_by_agreement() -> None:
    from voice_config.greetings import feminine_agreement

    text = "I am the AI Representative for Mari Energies."
    assert feminine_agreement(text, "en") == text
