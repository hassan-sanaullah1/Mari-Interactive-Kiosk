"""Names, military ranks and honours, as the Uplift voice should say them.

The kiosk runs one Urdu-first voice for both languages, and it applies English phonetics
to Latin script. On the Pakistani names in the knowledge base that is not an accent, it
is the wrong name — a round trip through the live voice (Uplift TTS → Soniox STT) gave
"Lifting in general and more early hike spread" for the Chairman's line, and "Sit back,
ER Kazmi" for a director's.

Every expectation below was checked against the real engine. The negative cases matter
as much as the positive ones: respelling a name that already works makes it worse, so
names absent from the table are pinned here as deliberately absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.providers.tts import _spoken  # noqa: E402
from voice_config.names import spoken_names_and_ranks  # noqa: E402


# ── names ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name,urdu",
    [
        ("Faheem Haider", "فہیم حیدر"),                  # was "Fahim Hayrat"
        ("Syed Bakhtiyar Kazmi", "سید بختیار کاظمی"),     # was "Seda Akhtyar Kazmi"
        ("Hamed Yaqoob Sheikh", "حامد یعقوب شیخ"),        # was "saying Yağmur Çelik"
        ("Ahmed Hayat Lak", "احمد حیات لک"),              # was "Ahmet Heytlak"
        ("Muhammad Aamir Salim", "محمد عامر سلیم"),        # was "Mehmet Ami Selim"
        ("Seema Adil", "سیما عادل"),                      # was "Sina Ado"
        ("Ayla Majid", "عائلہ مجید"),                     # was "Isle of Magic"
        ("Ghulam Muhammad Malik", "غلام محمد ملک"),        # was "Gülüm Hanım Melek"
        ("Imtiaz Shaheen", "امتیاز شاہین"),               # was "in chase shehin"
        ("Hazoor Bakhsh", "حضور بخش"),                    # was "Hazal Bakış"
        ("Muhammad Sajjad", "محمد سجاد"),                 # was "Mehmet Sercan"
    ],
)
def test_mangled_names_are_respelled_in_english(name: str, urdu: str) -> None:
    assert urdu in spoken_names_and_ranks(f"The director is {name}.", "en")


@pytest.mark.parametrize(
    "name",
    ["Zafar Abbas", "Anwar Ali Hyder", "Abdullah Asif", "Nadeem Ahmed",
     "Sumair Ashraf Sheikh", "Abid Niaz Hasan"],
)
def test_names_the_english_voice_already_says_correctly_are_left_alone(name: str) -> None:
    """Respelling a name the voice already gets right makes it worse, so these are
    pinned as deliberately absent from the table."""
    assert name in spoken_names_and_ranks(f"The director is {name}.", "en")


def test_every_person_in_the_knowledge_base_was_measured() -> None:
    """The table is a measured list, not a guess: each name is either respelled or
    explicitly kept Latin. A new name in the corpus should be round-tripped, not added
    on assumption."""
    from voice_config.names import _NAMES_FOR_ENGLISH, _NAMES_FOR_URDU

    assert set(_NAMES_FOR_ENGLISH) <= set(_NAMES_FOR_URDU)
    assert len(_NAMES_FOR_URDU) >= 26


def test_urdu_mode_respells_latin_names() -> None:
    """The prompt asks the model to keep names in Latin script; the voice mangles them."""
    said = spoken_names_and_ranks("MD/CEO Faheem Haider ہیں۔", "ur")
    assert "فہیم حیدر" in said and "Faheem Haider" not in said


# ── ranks ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Lt. Gen. Nadeem", "Lieutenant General"),   # was "Leftenant" / "Eldeej"
        ("Lt Gen Nadeem", "Lieutenant General"),
        ("Maj Gen Janjua", "Major General"),         # was "Mert Can"
        ("Brig Sheikh", "Brigadier"),                # was "Brick" / "Greg"
    ],
)
def test_abbreviated_ranks_are_spelled_out(text: str, expected: str) -> None:
    assert expected in spoken_names_and_ranks(text, "en")


def test_retired_moves_in_front_of_the_rank() -> None:
    """"(Retd)" is read as "Grade"; left in place the bare word is also ungrammatical."""
    said = spoken_names_and_ranks("Brig Ahmad (Retd) is Secretary.", "en")
    assert said.startswith("Retired Brigadier Ahmad is Secretary.")


@pytest.mark.parametrize("suffix", ["(Retd)", "(Retd.)", "(R)", "(Retired)"])
def test_every_retired_spelling_the_model_writes(suffix: str) -> None:
    """The model writes "(Retired)" in full as often as "(Retd)" — both must match."""
    said = spoken_names_and_ranks(f"Brigadier Ahmad {suffix} is Secretary.", "en")
    assert said.startswith("Retired Brigadier Ahmad is Secretary.")


def test_md_ampersand_ceo_is_separated() -> None:
    """The model writes "MD & CEO" as well as "MD/CEO"; both go through the hyphenated
    form in voice_config.addresses — "the MD and CEO" collided ("ESDM didn't see EO")."""
    from server.providers.tts import _spoken

    assert "M-D and C-E-O" in _spoken("serves as MD & CEO", "en")


def test_late_moves_in_front_of_the_rank() -> None:
    said = spoken_names_and_ranks("Lt Gen Ishfaq Nadeem Ahmad (Late) served.", "en")
    assert said.startswith("the late Lieutenant General Ishfaq Nadeem Ahmad served.")


def test_ranks_are_urdu_script_in_urdu_mode() -> None:
    said = spoken_names_and_ranks("چیئرمین Lt Gen Anwar Ali Hyder (Retd) ہیں۔", "ur")
    assert "ریٹائرڈ لیفٹیننٹ جنرل" in said
    assert "Lt Gen" not in said


# ── honours and slashed titles ──────────────────────────────────────

@pytest.mark.parametrize("lang", ["en", "ur"])
def test_honour_is_dropped_from_speech(lang: str) -> None:
    """"HI(M)" is read as "HIV" / "a type M", and the spelled-out form is no better."""
    said = spoken_names_and_ranks("Anwar Ali Hyder, HI(M), is the Chairman.", lang)
    assert "HI(M)" not in said and "HI" not in said


def test_dropping_the_honour_leaves_no_stray_comma() -> None:
    said = spoken_names_and_ranks("Lt. Gen. Anwar Ali Hyder, HI(M), (Retd) is Chairman.", "en")
    assert said.startswith("Retired Lieutenant General")
    assert ", ," not in said and " ," not in said


@pytest.mark.parametrize(
    "lang,expected",
    [("en", "M-D and C-E-O"), ("ur", "M-D اور C-E-O")],
)
def test_md_slash_ceo_is_separated(lang: str, expected: str) -> None:
    """"MD/CEO" is read as one run-on token ("MD/C8 August"), and a plain "MD and CEO"
    still collides across the "and". Hyphenating the letters separates them."""
    from server.providers.tts import _spoken

    assert expected in _spoken("The MD/CEO is here.", lang)


# ── the full pipeline ───────────────────────────────────────────────

def test_chairman_line_from_the_knowledge_base() -> None:
    """The worst case found: the raw line came back as "Lifting in general and more
    early hike spread is the chairman"."""
    said = _spoken("Board Chairman: Lt. Gen. Anwar Ali Hyder, HI(M), (Retd)", "en")
    # "Anwar Ali Hyder" measured better in Latin than in Urdu script, so only the rank
    # and the honour are rewritten here.
    assert said.startswith("Board Chairman: Retired Lieutenant General Anwar Ali Hyder")


# ── the persona's own name, and the salam ────────────────────────────
# Same trick as the names above and as "ماڑی": in English mode the Urdu-first voice
# applies English phonetics to Latin script, so the two phrases Maryam says most often
# come out in an English accent. Urdu script makes the same voice say them as a
# Pakistani speaker does. Only the TTS payload changes — the kiosk still displays the
# Latin spelling the model wrote.

@pytest.mark.parametrize(
    "reply",
    [
        "Assalamualaikum! I'm Maryam from Mari Energies.",
        "Assalam-o-Alaikum, I'm Maryam.",
        "As-salamu alaykum. Maryam here.",
        "Salam alaikum! Maryam speaking.",
    ],
)
def test_the_salam_and_her_name_are_said_in_urdu_in_english_mode(reply: str) -> None:
    said = _spoken(reply, "en")
    assert "السلام علیکم" in said
    assert "مریم" in said
    assert "Maryam" not in said and "alaikum" not in said.lower()


def test_a_returned_salam_is_not_split_across_the_two_rules() -> None:
    """"Walaikum assalam" overlaps _SALAM on the word "salam"; it must match as one."""
    said = _spoken("Walaikum assalam, I'm Maryam.", "en")
    assert "وعلیکم السلام" in said and "السلام علیکم" not in said


def test_urdu_mode_leaves_an_already_urdu_salam_alone() -> None:
    said = _spoken("السلام علیکم! میں مریم ہوں۔", "ur")
    assert said.count("السلام علیکم") == 1 and "مریم" in said


def test_urdu_mode_still_respells_a_latin_name_the_model_left_behind() -> None:
    """The Urdu prompt asks for Latin-script names, and sometimes catches her own."""
    assert "مریم" in _spoken("میں Maryam ہوں۔", "ur")


@pytest.mark.parametrize("reply", ["The marina is in Marietta.", "Mary and Sam arrived.",
                                   "Salamanders live there."])
def test_words_that_merely_look_like_the_persona_phrases_are_untouched(reply: str) -> None:
    assert _spoken(reply, "en") == reply


def test_credit_rating_a1_is_not_glued_into_a_non_word() -> None:
    """The number spell-out turned "A1" into "Aone"; the voice said "Aon"."""
    assert "A one" in _spoken("Credit rating AAA long term, A1 short term.", "en")


def test_hr_and_r_committee() -> None:
    """"HR&R" is run together into "H9R" by the voice."""
    assert "H R and R" in _spoken("The HR&R Committee met.", "en")


def test_existing_english_number_spellout_still_works() -> None:
    """The names pass runs before the number pass; neither may break the other."""
    said = _spoken("Net profit was PKR 65.14 billion in 1954.", "en")
    assert "sixty five point one four" in said and "nineteen fifty four" in said


def test_urdu_digits_still_survive_the_names_pass() -> None:
    assert "65.14" in _spoken("منافع 65.14 ارب روپے۔", "ur")


def test_urdu_letter_retired_suffix() -> None:
    """Urdu replies write the suffix in Urdu too — "(ر)" rather than "(Retd)"."""
    said = spoken_names_and_ranks("چیئرمین لیفٹیننٹ جنرل (ر) انور علی حیدر ہیں۔", "ur")
    assert "ریٹائرڈ لیفٹیننٹ جنرل" in said and "(ر)" not in said
