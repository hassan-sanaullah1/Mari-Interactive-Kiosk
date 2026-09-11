"""The voice_config layer: prompt files, abbreviation glossary, Uplift spoken-form fixes.

The normalizer cases here are the ones a round trip through the real Uplift voice
(TTS → Soniox STT) got wrong before the fix and right after it; the rest of what the
reference implementation normalised — digits, decimals, percentages, "24/7", years,
phone numbers — Uplift already pronounces correctly and is deliberately left alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import knowledge  # noqa: E402
from voice_config import load_prompt  # noqa: E402
from voice_config.glossary import (  # noqa: E402
    extract_glossary,
    find_glossary_matches,
    format_glossary_block,
)
from server.providers.tts import _spoken  # noqa: E402
from voice_config.urdu_normalise import normalise_for_uplift, spoken_urls  # noqa: E402


# ── prompt files ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name", ["system_prompt_english", "system_prompt_urdu", "greeting_english"]
)
def test_prompt_files_load(name: str) -> None:
    assert load_prompt(name)


def test_missing_prompt_falls_back_to_none() -> None:
    """A bad filename must not raise — callers rely on the in-code fallback."""
    assert load_prompt("no_such_prompt") is None


def test_loaded_prompts_are_the_ones_actually_used() -> None:
    assert knowledge.RULES["en"] == load_prompt("system_prompt_english")
    assert knowledge.RULES["ur"] == load_prompt("system_prompt_urdu")
    assert knowledge.GREETINGS["en"] == load_prompt("greeting_english")
    assert knowledge.GREETINGS["ur"] == load_prompt("greeting_urdu")


def test_in_code_fallbacks_still_match_the_files_byte_for_byte() -> None:
    """The literals in knowledge.py are the fallback when a prompt file is unreadable.

    A fallback that has drifted from the file is worse than no fallback: the kiosk would
    keep answering, in a persona nobody edited.
    """
    assert knowledge._RULES_EN == load_prompt("system_prompt_english")
    assert knowledge._RULES_UR == load_prompt("system_prompt_urdu")
    assert knowledge._GREETING_EN == load_prompt("greeting_english")
    assert knowledge._GREETING_UR == load_prompt("greeting_urdu")


def test_persona_and_tone_rules_survived_the_move_to_files() -> None:
    """The .md files were extracted verbatim; these are the rules we most rely on."""
    en, ur = knowledge.RULES["en"], knowledge.RULES["ur"]
    assert "Maryam" in en and "مریم" in ur           # she has a name, and uses it
    assert "Mari Energies" in en and "Mari Energies" in ur   # brand stays in Latin script
    assert "کر سکتی ہوں" in ur          # feminine verb forms
    assert "نمائندہ" in ur              # feminine role noun
    # She presents as a member of the team, not as an assistant.
    assert "never a salesperson" in en
    assert "chatbot" in en and "چیٹ بوٹ" in ur       # ...and is told not to admit to being one


def test_the_greeting_prompts_demand_the_salam_and_the_name() -> None:
    """The kiosk's one hard promise: the first reply opens with the salam and her name."""
    en, ur = knowledge.GREETINGS["en"], knowledge.GREETINGS["ur"]
    assert "Assalamualaikum" in en and "Maryam" in en
    assert "السلام علیکم" in ur and "مریم" in ur
    assert "وعلیکم السلام" in ur         # named explicitly so it is never returned instead


def test_the_greeting_is_not_baked_into_the_urdu_rules() -> None:
    """The introduction must reach the model ONLY on a greeting turn.

    Each turn is a stateless call, so anything in RULES is in the system prompt every
    time. While the opening-turn script lived inside system_prompt_urdu.md, Urdu answers
    opened with "السلام علیکم، میرا نام مریم ہے ..." and "بتائیے، میں آپ کی کیا مدد کر
    سکتی ہوں؟" before every answer, however far into the conversation the visitor was.
    """
    ur = knowledge.RULES["ur"]
    assert "وعلیکم السلام" not in ur              # the opening script, not the base rules
    assert "میں آپ کی کیا مدد کر سکتی ہوں؟" not in ur   # the invitation it ended on
    # ...and the rules still tell her to stay silent about it until told otherwise.
    assert "سیدھا سوال کا جواب دیں" in ur


# ── abbreviation glossary ───────────────────────────────────────────

def test_real_definitions_are_extracted() -> None:
    g = extract_glossary("The Mari Seismic Processing Center (MSPC) opened in 2019.")
    assert g["MSPC"] == "Mari Seismic Processing Center"


def test_abbreviation_first_ordering() -> None:
    g = extract_glossary("HSE (Health Safety & Environment) reporting is quarterly.")
    assert g["HSE"] == "Health Safety & Environment"


@pytest.mark.parametrize(
    "text",
    [
        "EPS 54.25 (restated)",                    # an aside, not a definition
        "OGDCL (20%)",                             # a shareholding figure
        "energy use 4,344,223 GJ (2024: 728 ML)",  # a prior-year comparison
    ],
)
def test_parenthetical_asides_are_rejected(text: str) -> None:
    """This corpus is an annual report; most parentheses are not definitions.

    Injecting these as authoritative would produce confidently wrong answers.
    """
    assert extract_glossary(text) == {}


def test_comma_stops_the_backward_scan() -> None:
    """Without this, a comma-separated list glues several items into one 'full form'."""
    g = extract_glossary("Fauji Meat Limited, Pakistan Maroc Phosphate (FFBL)")
    assert g.get("FFBL") in (None, "Pakistan Maroc Phosphate")


def test_the_live_knowledge_base_yields_clean_entries() -> None:
    assert knowledge.ABBREVIATIONS["MPCL"] == "Mari Petroleum Company Limited"
    # the noisy ones the tightened filter exists to reject
    for bogus in ("EPS", "GJ", "MT"):
        assert bogus not in knowledge.ABBREVIATIONS


def test_matches_are_whole_word_only() -> None:
    g = {"HSE": "Health Safety & Environment"}
    assert find_glossary_matches("what is HSE?", g) == g
    assert find_glossary_matches("horses", g) == {}


def test_glossary_block_is_empty_without_matches() -> None:
    assert format_glossary_block({}) == ""


# The prompt is assembled by the generation service now, from a RetrievalResult, rather
# than by knowledge.system_prompt building its own context. These two tests take the
# same path the server does, minus the retrieval step: the glossary block is computed
# from the query and carried on the result, so it survives an empty or failed retrieval.


def _prompt_for(query: str) -> str:
    from server.services.generation import GenerationService
    from server.services.retriever import RetrievalResult

    matches = find_glossary_matches(query, knowledge.ABBREVIATIONS)
    result = RetrievalResult(query=query, glossary_block=format_glossary_block(matches))
    return GenerationService().build_prompt(
        result, "en", core_brief=knowledge.CORE_BRIEF
    ).system


def test_definition_is_injected_into_the_system_prompt() -> None:
    assert "Mari Seismic Processing Center" in _prompt_for("what is MSPC?")


def test_prompt_is_untouched_when_no_abbreviation_matches() -> None:
    assert "Glossary" not in _prompt_for("who is the CEO")


# ── Uplift spoken-form fixes ────────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Tier III سرٹیفائیڈ ہے۔", "Tier 3 سرٹیفائیڈ ہے۔"),
        ("Tier III/IV سرٹیفائیڈ۔", "Tier 3/4 سرٹیفائیڈ۔"),
        ("مرحلہ II مکمل ہوا۔", "مرحلہ 2 مکمل ہوا۔"),
    ],
)
def test_roman_numerals_become_digits(text: str, expected: str) -> None:
    """Uplift reads "III" letter by letter ("آئی آئی آئی"); digits it reads correctly."""
    assert normalise_for_uplift(text, "ur") == expected


def test_slash_between_words_becomes_aur() -> None:
    """Uplift says "flash" for a bare "/" between words."""
    assert normalise_for_uplift("تیل/گیس کی پیداوار۔", "ur") == "تیل اور گیس کی پیداوار۔"


@pytest.mark.parametrize("text", ["ہم 24/7 دستیاب ہیں۔", "2024/25 کے دوران۔"])
def test_numeric_slashes_are_left_alone(text: str) -> None:
    """"24/7" is a ratio the voice already reads correctly — and "اور" would change it."""
    assert normalise_for_uplift(text, "ur") == text


def test_bare_url_is_spelled_for_the_voice() -> None:
    said = normalise_for_uplift("تفصیلات marienergies.com.pk پر ہیں۔", "ur")
    assert "ڈاٹ کام ڈاٹ پی کے" in said
    assert "marienergies.com.pk" not in said


# ── domains, in both languages ──────────────────────────────────────
# The voice runs a written domain into a different word and drops the dots entirely:
# "marienergies.com.pk" -> "marionettes.com.pk" in English, "میری انرجیز کام پی کے"
# (no "ڈاٹ" at all) in Urdu.

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Visit marienergies.com.pk today.", "Mari Energies dot com dot P K"),
        ("Visit mariservices.com.pk today.", "Mari Services dot com dot P K"),
        ("Visit sky47.com.pk today.", "Sky Forty Seven dot com dot P K"),
        ("Find us on linkedin.com.", "LinkedIn dot com"),
    ],
)
def test_english_domains_say_their_dots(text: str, expected: str) -> None:
    assert expected in spoken_urls(text, "en")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("تفصیلات marienergies.com.pk پر ہیں۔", "ماڑی انرجیز ڈاٹ کام ڈاٹ پی کے"),
        ("sky47.com.pk دیکھیں۔", "اسکائی فورٹی سیون ڈاٹ کام ڈاٹ پی کے"),
    ],
)
def test_urdu_domains_say_their_dots(text: str, expected: str) -> None:
    assert expected in spoken_urls(text, "ur")


def test_www_prefix_is_spoken() -> None:
    said = spoken_urls("See www.marienergies.com.pk.", "en")
    assert said.startswith("See double u double u double u dot Mari Energies dot com dot P K")


def test_domain_is_matched_before_the_sky47_rule_rewrites_its_label() -> None:
    """_spoken() must see "sky47.com.pk" whole, or the dots are left behind unsaid."""
    said = _spoken("Visit sky47.com.pk today.", "en")
    assert "Sky Forty Seven dot com dot P K" in said
    assert ".com.pk" not in said


def test_bare_brand_without_a_domain_is_untouched_by_the_url_rule() -> None:
    assert _spoken("Sky47 is our data centre arm.", "en").startswith("Sky Forty Seven is")


def test_domains_are_fixed_in_english_mode_too() -> None:
    """The original fix only ran in Urdu mode, leaving English broken."""
    assert "dot com dot P K" in _spoken("Visit marienergies.com.pk.", "en")


@pytest.mark.parametrize(
    "text",
    [
        "منافع 65.14 ارب روپے۔",      # decimals — Uplift is correct already
        "یہ 2024 میں ہوا۔",            # 20xx years — the cardinal reading is the year
        # 18xx/19xx years are NOT in this list: Uplift reads "1954" as the cardinal
        # "ایک ہزار نو سو چون" where the year is "انیس سو چون", which is why
        # urdu_normalise.spoken_years exists. See tests/test_tts_spoken.py.
        "یہ 99.98% ہے۔",              # percentages
        "ہم AI استعمال کرتے ہیں۔",     # acronyms
    ],
)
def test_what_uplift_already_handles_is_not_touched(text: str) -> None:
    """Re-normalising these would duplicate the engine and risk breaking it."""
    assert normalise_for_uplift(text, "ur") == text


def test_english_replies_are_not_normalised() -> None:
    assert normalise_for_uplift("Tier III certified.", "en") == "Tier III certified."


def test_latin_only_urdu_mode_text_is_left_alone() -> None:
    """The fixes key off Urdu script, so a Latin-only string is passed through."""
    assert normalise_for_uplift("Tier III", "ur") == "Tier III"


@pytest.mark.parametrize(
    "prompt_name",
    [
        "system_prompt_english",
        "system_prompt_english_male",
        "system_prompt_urdu",
        "system_prompt_urdu_male",
    ],
)
def test_gpuaas_answers_must_name_both_vendors(prompt_name: str) -> None:
    """A "do you offer GPU as a Service" question was being answered "yes, we do",
    dropping the hardware in §3.1.3.3. Every persona and language carries the rule."""
    rules = load_prompt(prompt_name)
    assert "GPU as a Service" in rules
    assert "Huawei Ascend NPU" in rules
    assert "NVIDIA-compatible GPU" in rules


def test_the_core_brief_carries_the_sky47_ai_hardware() -> None:
    """The brief is injected even when the index is empty, so the fact has to be here
    too — not only in the retrieved section."""
    brief = knowledge.CORE_BRIEF
    assert "GPU as a Service" in brief
    assert "Huawei Ascend NPU" in brief
    assert "NVIDIA-compatible GPU clusters" in brief


@pytest.mark.parametrize("query", ["جی پی یو", "جی پی یوز", "اے آئی فارم", "کلسٹرز"])
def test_urdu_gpuaas_questions_expand_to_the_english_section_terms(query: str) -> None:
    """§3.1.3.3 is the only section naming the accelerators, and Urdu spells "GPU" out
    letter by letter, which matched nothing in the lexical channel."""
    from server.services.expansion import expand_for_lexical

    expanded, terms = expand_for_lexical(f"{query} کے بارے میں بتائیں")
    assert "gpu" in expanded.lower() or "clusters" in expanded.lower()
    assert terms
