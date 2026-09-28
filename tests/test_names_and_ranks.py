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

import pytest

from server.normalization import normalize_for_tts
from server.normalization import spoken_names_and_ranks


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
     "Sumair Ashraf Sheikh", "Abid Niaz Hasan", "Ishfaq Nadeem Ahmad",
     "Khalid Nawaz Malik", "Raza Muhammad Khan", "Syed Shahzad Nabi"],
)
def test_every_person_is_respelled_in_english(name: str) -> None:
    """These ten were once pinned as deliberately absent, on a round-trip finding that
    Latin came out closer for them. The deployed kiosk said otherwise — they were the
    names still being mispronounced — so the table now covers every person in the
    corpus, and "which names" is no longer a judgement call."""
    said = spoken_names_and_ranks(f"The director is {name}.", "en")
    assert name not in said
    assert any(ord(c) > 0x600 for c in said)


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
    # The name itself is respelled by the per-word pass, so this asserts the rank and
    # the moved suffix, not the spelling of the name between them.
    assert said.startswith("Retired Brigadier ")
    assert said.endswith(" is Secretary.")


@pytest.mark.parametrize("suffix", ["(Retd)", "(Retd.)", "(R)", "(Retired)"])
def test_every_retired_spelling_the_model_writes(suffix: str) -> None:
    """The model writes "(Retired)" in full as often as "(Retd)" — both must match."""
    said = spoken_names_and_ranks(f"Brigadier Ahmad {suffix} is Secretary.", "en")
    assert said.startswith("Retired Brigadier ")
    assert said.endswith(" is Secretary.")


def test_md_ampersand_ceo_is_separated() -> None:
    """The model writes "MD & CEO" as well as "MD/CEO"; both go through the hyphenated
    form in the addresses section — "the MD and CEO" collided ("ESDM didn't see EO")."""
    assert "M-D and C-E-O" in normalize_for_tts("serves as MD & CEO", "en")


def test_late_moves_in_front_of_the_rank() -> None:
    said = spoken_names_and_ranks("Lt Gen Ishfaq Nadeem Ahmad (Late) served.", "en")
    assert said.startswith("the late Lieutenant General ")
    assert said.endswith(" served.") and "(Late)" not in said


def test_ranks_are_urdu_script_in_urdu_mode() -> None:
    said = spoken_names_and_ranks("چیئرمین Lt Gen Anwar Ali Hyder (Retd) ہیں۔", "ur")
    assert "ریٹائرڈ لیفٹیننٹ جنرل" in said
    assert "Lt Gen" not in said


# ── honours and slashed titles ──────────────────────────────────────

HILAL = "ہلالے امتیاز ملٹری"


def test_honour_is_said_in_full_in_urdu() -> None:
    """Latin "HI(M)" is read as "HIV" and Latin "Hilal-e-Imtiaz" is garbled; the Urdu
    spelling with the izafat written as ے round-trips as "Hilal-e-Imtiaz Military"."""
    said = spoken_names_and_ranks("Anwar Ali Hyder, HI(M), is the Chairman.", "ur")
    assert HILAL in said
    assert "HI(M)" not in said and "HI" not in said


def test_honour_is_dropped_in_english() -> None:
    """English mode leaves the decoration out rather than reading Urdu script aloud."""
    said = spoken_names_and_ranks("Anwar Ali Hyder, HI(M), is the Chairman.", "en")
    assert HILAL not in said
    assert "HI(M)" not in said and "HI" not in said


def test_the_honour_is_dropped_and_retired_moves_to_the_front() -> None:
    said = spoken_names_and_ranks("Lt. Gen. Anwar Ali Hyder, HI(M), (Retd) is Chairman.", "en")
    assert said == "Retired Lieutenant General انور علی حیدر is Chairman."


@pytest.mark.parametrize(
    "text",
    [
        "چیئرمین Lt. Gen. Anwar Ali Hyder, HI(M), (Retd) ہیں۔",
        # The model also writes the whole line in Urdu script. "(ریٹائرڈ)" after an Urdu
        # honour used to be dropped outright, and the honour letters were left in.
        "چیئرمین لیفٹیننٹ جنرل انور علی حیدر، ایچ آئی (ایم)، (ریٹائرڈ) ہیں۔",
        "چیئرمین لیفٹیننٹ جنرل (ر) انور علی حیدر، ہلال امتیاز (ملٹری) ہیں۔",
        "چیئرمین Lt Gen Anwar Ali Hyder, Hilal-e-Imtiaz (Military), (Retd) ہیں۔",
    ],
)
def test_urdu_chairman_line_in_every_form_the_model_writes(text: str) -> None:
    said = normalize_for_tts(text, "ur")
    assert f"ریٹائرڈ لیفٹیننٹ جنرل انور علی حیدر، {HILAL} ہیں۔" in said


@pytest.mark.parametrize(
    "text,expected",
    [("Dr. Seema Adil", "ڈاکٹر سیما عادل"), ("Engr. Zafar Abbas", "انجینئر ظفر عباس"),
     ("Mr. Faheem Haider", "مسٹر فہیم حیدر")],
)
def test_honorifics_are_urdu_script_in_urdu_mode(text: str, expected: str) -> None:
    assert expected in normalize_for_tts(f"{text} ہیں۔", "ur")


def test_drive_is_not_mistaken_for_doctor() -> None:
    assert "ڈاکٹر" not in normalize_for_tts("دفتر Jinnah Dr. پر ہے۔", "ur")


@pytest.mark.parametrize(
    "lang,expected",
    # English hyphenates the letters so the English voice reads them apart; Urdu says
    # the title in Urdu script, where that trick is neither needed nor correct.
    [("en", "M-D and C-E-O"), ("ur", "ایم ڈی اور سی ای او")],
)
def test_md_slash_ceo_is_separated(lang: str, expected: str) -> None:
    """"MD/CEO" is read as one run-on token ("MD/C8 August"), and a plain "MD and CEO"
    still collides across the "and". Hyphenating the letters separates them."""
    assert expected in normalize_for_tts("The MD/CEO is here.", lang)


# ── the full pipeline ───────────────────────────────────────────────

def test_chairman_line_from_the_knowledge_base() -> None:
    """The worst case found: the raw line came back as "Lifting in general and more
    early hike spread is the chairman"."""
    said = normalize_for_tts("Board Chairman: Lt. Gen. Anwar Ali Hyder, HI(M), (Retd)", "en")
    # Every part of the line is now rewritten: the rank spelled out, the honour dropped,
    # the suffix moved in front, and the name itself respelled in Urdu script.
    assert said.startswith("Board Chairman: Retired Lieutenant General ")
    assert "انور علی حیدر" in said and HILAL not in said
    assert "HI(M)" not in said and "(Retd)" not in said


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
    said = normalize_for_tts(reply, "en")
    assert "السلام علیکم" in said
    assert "مریم" in said
    assert "Maryam" not in said and "alaikum" not in said.lower()


def test_a_returned_salam_is_not_split_across_the_two_rules() -> None:
    """"Walaikum assalam" overlaps _SALAM on the word "salam"; it must match as one."""
    said = normalize_for_tts("Walaikum assalam, I'm Maryam.", "en")
    assert "وعلیکم السلام" in said and "السلام علیکم" not in said


def test_urdu_mode_leaves_an_already_urdu_salam_alone() -> None:
    said = normalize_for_tts("السلام علیکم! میں مریم ہوں۔", "ur")
    assert said.count("السلام علیکم") == 1 and "مریم" in said


def test_urdu_mode_still_respells_a_latin_name_the_model_left_behind() -> None:
    """The Urdu prompt asks for Latin-script names, and sometimes catches her own."""
    assert "مریم" in normalize_for_tts("میں Maryam ہوں۔", "ur")


@pytest.mark.parametrize("reply", ["The marina is in Marietta.", "Mary and Sam arrived.",
                                   "Salamanders live there."])
def test_words_that_merely_look_like_the_persona_phrases_are_untouched(reply: str) -> None:
    assert normalize_for_tts(reply, "en") == reply


def test_credit_rating_a1_is_not_glued_into_a_non_word() -> None:
    """The number spell-out turned "A1" into "Aone"; the voice said "Aon"."""
    assert "A one" in normalize_for_tts("Credit rating AAA long term, A1 short term.", "en")


def test_hr_and_r_committee() -> None:
    """"HR&R" is run together into "H9R" by the voice."""
    assert "H R and R" in normalize_for_tts("The HR&R Committee met.", "en")


def test_existing_english_number_spellout_still_works() -> None:
    """The names pass runs before the number pass; neither may break the other."""
    said = normalize_for_tts("Net profit was PKR 65.14 billion in 1954.", "en")
    assert "sixty five point one four" in said and "nineteen fifty four" in said


def test_urdu_digits_still_survive_the_names_pass() -> None:
    assert "65.14" in normalize_for_tts("منافع 65.14 ارب روپے۔", "ur")


def test_urdu_letter_retired_suffix() -> None:
    """Urdu replies write the suffix in Urdu too — "(ر)" rather than "(Retd)"."""
    said = spoken_names_and_ranks("چیئرمین لیفٹیننٹ جنرل (ر) انور علی حیدر ہیں۔", "ur")
    assert "ریٹائرڈ لیفٹیننٹ جنرل" in said and "(ر)" not in said


# ── ranks that had no Urdu form ─────────────────────────────────────
# "Col", "Capt", "Maj" and a bare "Lt" were in the English table only, so in Urdu mode
# they stayed Latin — a two- or three-letter abbreviation in an Urdu sentence, which is
# the same failure the acronym table in server/normalization.py exists to fix.

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Col Ahmed Khan", "کرنل"),
        ("Capt Iqbal Shah", "کیپٹن"),
        ("Maj Ali Raza", "میجر"),
        ("Lt Ali Khan", "لیفٹیننٹ"),
        ("Lt Col Bilal", "لیفٹیننٹ کرنل"),
        ("Brig Gen Asif", "بریگیڈیئر جنرل"),
    ],
)
def test_every_rank_has_an_urdu_form(text: str, expected: str) -> None:
    said = normalize_for_tts(f"{text} ہیں۔", "ur")
    assert expected in said
    assert text.split()[0] not in said


@pytest.mark.parametrize(
    "text,expected",
    [("Maj Ali Raza", "Major"), ("Lt Ali Khan", "Lieutenant"),
     ("Lt Col Bilal", "Lieutenant Colonel"), ("Brig Gen Asif", "Brigadier General")],
)
def test_the_new_ranks_are_spelled_out_in_english_too(text: str, expected: str) -> None:
    assert expected in normalize_for_tts(text, "en")


@pytest.mark.parametrize(
    "lang,text,expected",
    [
        ("ur", "Col Ahmed (Retd) ہیں۔", "ریٹائرڈ کرنل"),
        ("ur", "Capt Iqbal (Late) ہیں۔", "مرحوم کیپٹن"),
        ("en", "Col Ahmed (Retd)", "Retired Colonel"),
        ("en", "Capt Iqbal (Late)", "the late Captain"),
    ],
)
def test_the_suffix_reattaches_to_the_new_ranks(lang: str, text: str, expected: str) -> None:
    """The "(Retd)" lift-and-reattach reads from the rank-name alternation, so a rank
    added to the tables above must be added there too or its suffix is simply dropped."""
    assert expected in normalize_for_tts(text, lang)


def test_a_two_word_rank_beats_its_own_first_half() -> None:
    """"Lt Gen" must match whole: the bare "Lt" rule would otherwise claim its first
    half and strand "Gen"."""
    said = normalize_for_tts("Lt Gen Nadeem Ahmed (Retd)", "en")
    assert "Retired Lieutenant General" in said
    assert "Gen" not in said.replace("General", "")


# ── every person, and every part of their name ──────────────────────
# Two gaps were found by listening to the deployed kiosk. Ten people were absent from
# the English table entirely, and the table only ever matched a FULL name — so a reply
# that said "Kazmi" or "Faheem" on its own went through untouched, and the same person
# was said correctly in one sentence and mangled in the next.

def test_every_person_in_the_corpus_is_covered() -> None:
    """One table serves both languages; every person in the corpus is respelled."""
    from server.normalization import _PERSON_NAMES

    assert len(_PERSON_NAMES) >= 26


@pytest.mark.parametrize(
    "word,urdu",
    [("Faheem", "فہیم"), ("Haider", "حیدر"), ("Kazmi", "کاظمی"), ("Ayla", "عائلہ"),
     ("Seema", "سیما"), ("Nabeel", "نبیل"), ("Sajjad", "سجاد"), ("Janjua", "جنجوعہ"),
     ("Bakhsh", "بخش"), ("Shaheen", "شاہین"), ("Rasheed", "رشید"), ("Abbas", "عباس"),
     ("Sheikh", "شیخ"), ("Bakhtiyar", "بختیار"), ("Mushtaq", "مشتاق")],
)
def test_a_name_on_its_own_is_respelled(word: str, urdu: str) -> None:
    """A conversational answer rarely repeats the full name."""
    assert urdu in normalize_for_tts(f"Ask {word} about it.", "en")


@pytest.mark.parametrize("lang", ["en", "ur"])
def test_partial_and_full_mentions_agree(lang: str) -> None:
    """The whole point: the surname must be said the same way in both sentences."""
    full = normalize_for_tts("Syed Bakhtiyar Kazmi chairs it.", lang)
    part = normalize_for_tts("Kazmi chairs it.", lang)
    assert "کاظمی" in full and "کاظمی" in part


@pytest.mark.parametrize(
    "text",
    ["Ali Baba trading", "Khan Research Labs", "The Malik Road site"],
)
def test_name_words_that_are_also_ordinary_words_do_not_fire(text: str) -> None:
    """"Ali", "Khan" and "Malik" are blocklisted from the per-word pass: they appear
    outside a person's name often enough that matching them would fire on sentences
    that have nothing to do with anyone. The full-name pass still covers them."""
    assert normalize_for_tts(text, "en") == text


def test_the_word_pass_is_built_from_the_name_tables() -> None:
    """One source of truth: a word is only respelled if it occurs in a name the kiosk
    actually knows, so adding a person covers their name parts automatically."""
    from server.normalization import _KNOWN_WORDS, _PERSON_NAMES

    every_word = {w for full in _PERSON_NAMES for w in full.split()}
    assert set(_KNOWN_WORDS) <= every_word
