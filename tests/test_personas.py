"""The two presenters, and the persona each one speaks as.

The kiosk shows one of two rigs (frontend/components/avatar/models.ts) and the browser
sends which on every turn. That id now picks more than the voice: Maryam for the female
rig, Hamza for the male one, and — because Urdu marks gender on the verb and on the
possessive — which way an intermittent model slip gets corrected.

Half of what is pinned here is that the FEMALE path did not move. She was the kiosk's
only persona for its whole life so far, so every test that asserts "female" behaves
exactly as it always did is deliberate, not redundant.
"""

from __future__ import annotations

import pytest

from server.normalization import normalize_for_tts
from server.services.generation import GenerationService
from server.services.retriever import RetrievalResult
from server.agent.reply_fixes import (
    feminine_agreement,
    gender_agreement,
    masculine_agreement,
)
from server.prompts import load_prompt


@pytest.fixture(scope="module")
def gen() -> GenerationService:
    g = GenerationService()
    g.load_templates()
    return g


# ── the prompt files exist and name the right person ─────────────────

@pytest.mark.parametrize(
    "name", ["system/male_english.md", "system/male_urdu.md",
             "greeting/male_english.md", "greeting/male_urdu.md"]
)
def test_the_male_prompt_files_load(name: str) -> None:
    assert load_prompt(name)


def test_each_persona_prompt_names_only_its_own_presenter() -> None:
    """A name leaking across would make the kiosk introduce itself as the other rig."""
    for lang in ("english", "urdu"):
        her, him = load_prompt(f"system/female_{lang}.md"), load_prompt(f"system/male_{lang}.md")
        me, him_name = ("Maryam", "Hamza") if lang == "english" else ("مریم", "حمزہ")
        assert me in her and him_name not in her
        assert him_name in him and me not in him


def test_the_male_greeting_still_demands_the_salam_and_a_name() -> None:
    en, ur = load_prompt("greeting/male_english.md"), load_prompt("greeting/male_urdu.md")
    assert "Assalamualaikum" in en and "Hamza" in en
    assert "السلام علیکم" in ur and "حمزہ" in ur


def test_the_urdu_male_prompt_asks_for_masculine_agreement() -> None:
    ur = load_prompt("system/male_urdu.md")
    assert "کر سکتا ہوں" in ur          # the form it wants
    assert "مذکر صیغہ استعمال کریں" in ur


# ── prompt assembly picks the right persona ──────────────────────────

@pytest.mark.parametrize(
    "avatar,lang,expected",
    [
        ("female", "en", "You are Maryam"),
        ("female", "ur", "آپ مریم ہیں"),
        ("male", "en", "You are Hamza"),
        ("male", "ur", "آپ حمزہ ہیں"),
    ],
)
def test_build_prompt_opens_with_the_right_persona(
    gen: GenerationService, avatar: str, lang: str, expected: str
) -> None:
    prompt = gen.build_prompt(RetrievalResult(), lang=lang, avatar=avatar)
    assert prompt.system.startswith(expected)


@pytest.mark.parametrize("avatar,name", [("female", "Maryam"), ("male", "Hamza")])
def test_the_greeting_block_matches_the_persona(
    gen: GenerationService, avatar: str, name: str
) -> None:
    prompt = gen.build_prompt(RetrievalResult(), lang="en", greeting=True, avatar=avatar)
    assert f'your name "{name}"' in prompt.system


@pytest.mark.parametrize("avatar", ["", "nonsense", "girl15", None])
def test_an_unknown_rig_id_falls_back_to_the_female_presenter(
    gen: GenerationService, avatar: str
) -> None:
    """The browser is the only source of this id; a bad one must not drop the persona."""
    assert gen.build_prompt(RetrievalResult(), lang="en", avatar=avatar).system.startswith(
        "You are Maryam"
    )


def test_the_default_is_still_the_female_presenter(gen: GenerationService) -> None:
    """Every caller that predates the male rig omits the argument entirely."""
    assert gen.build_prompt(RetrievalResult(), lang="en").system.startswith("You are Maryam")
    assert gen.rules("en").startswith("You are Maryam")


# ── gender agreement ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "reply,expected",
    [
        ("میں Mari Energies کی نمائندہ ہوں۔", "میں Mari Energies کا نمائندہ ہوں۔"),
        ("میں Mari Energies کی representative ہوں۔", "میں Mari Energies کا representative ہوں۔"),
        ("میں مدد کر سکتی ہوں۔", "میں مدد کر سکتا ہوں۔"),
        ("میں آپ کو بتا رہی ہوں۔", "میں آپ کو بتا رہا ہوں۔"),
    ],
)
def test_the_male_presenter_gets_masculine_agreement(reply: str, expected: str) -> None:
    assert masculine_agreement(reply, "ur") == expected
    assert gender_agreement(reply, "ur", "male") == expected


def test_the_female_presenter_gets_feminine_agreement_on_representative() -> None:
    reply = "میں Mari Energies کا representative ہوں۔"
    assert gender_agreement(reply, "ur", "female") == "میں Mari Energies کی representative ہوں۔"


def test_a_possessive_belonging_to_something_else_is_left_alone() -> None:
    """"Mari Energies کے kiosk پر" agrees with the kiosk, not with the speaker."""
    text = "میں Mari Energies کے kiosk پر موجود نمائندہ ہوں۔"
    assert masculine_agreement(text, "ur") == text


def test_a_feminine_verb_about_the_company_is_not_the_speaker() -> None:
    """"کام کر رہی ہے" is third person — the company — and must survive."""
    said = masculine_agreement("میں بتا رہی ہوں کہ کمپنی 1954 سے کام کر رہی ہے۔", "ur")
    assert "بتا رہا ہوں" in said and "کام کر رہی ہے" in said


@pytest.mark.parametrize(
    "reply",
    [
        "میں Mari Energies کا نمائندہ ہوں۔",
        "میں مدد کر سکتی ہوں۔",
        "میں Mari Energies کے kiosk پر موجود نمائندہ ہوں۔",
    ],
)
def test_the_female_path_is_byte_for_byte_what_it_always_was(reply: str) -> None:
    """gender_agreement(..., "female") must be exactly the old feminine_agreement."""
    assert gender_agreement(reply, "ur", "female") == feminine_agreement(reply, "ur")


@pytest.mark.parametrize("avatar", ["", "nonsense", None])
def test_an_unknown_rig_id_gets_the_female_agreement(avatar: str) -> None:
    reply = "میں Mari Energies کا نمائندہ ہوں۔"
    assert gender_agreement(reply, "ur", avatar) == feminine_agreement(reply, "ur")


def test_english_replies_are_untouched_by_either_agreement() -> None:
    text = "I am Hamza, a representative for Mari Energies."
    assert masculine_agreement(text, "en") == text
    assert gender_agreement(text, "en", "male") == text


# ── how the voice says each name ─────────────────────────────────────

@pytest.mark.parametrize(
    "written,spoken", [("Maryam", "مریم"), ("Hamza", "حمزہ"), ("Hamzah", "حمزہ")]
)
def test_both_names_are_said_in_urdu_in_english_mode(written: str, spoken: str) -> None:
    said = normalize_for_tts(f"Assalamualaikum! I'm {written} from Mari Energies.", "en")
    assert spoken in said and written not in said


def test_a_word_that_merely_starts_like_the_male_name_is_untouched() -> None:
    # "Lahore" is now respelled by the places table, so the filler here is a word no
    # table owns; the point of the test is the name boundary, not the sentence.
    assert normalize_for_tts("The Hamzas gathered.", "en") == "The Hamzas gathered."
