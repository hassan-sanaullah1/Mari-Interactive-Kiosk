"""Urdu replies: names, the brand and abbreviations put back in Latin script.

Every case below is a reply Qwen 3.5 actually produced for "mujhe board of directors ke
baray mein bataiye" or the reserves question, despite the prompt's Latin-script rule. In
that form none of the pronunciation fixes in server/normalization.py could fire.
"""

from __future__ import annotations

import pytest

from server.agent.script_fixes import latin_terms
from server.normalization import normalize_for_tts


@pytest.mark.parametrize(
    "written,latin",
    [
        # the brand, including «میری» ("my") which the voice says as "my energies"
        ("میری انرجیز کا بورڈ", "Mari Energies کا بورڈ"),
        ("میری Energies کے چیئرمین", "Mari Energies کے چیئرمین"),
        ("ماری انرجیز کے ذخائر", "Mari Energies کے ذخائر"),
        ("ماری پیٹرولیم", "Mari Petroleum"),
        # honours, in every broken form seen
        ("انور علی حیدر، ایچ آئی (ایم) ہیں", "Anwar Ali Hyder، HI(M) ہیں"),
        ("انور علی حیدر، ایچ آئی (م) ہیں", "Anwar Ali Hyder، HI(M) ہیں"),
        ("انور علی حیدر، ہیو (ایم) ہیں", "Anwar Ali Hyder، HI(M) ہیں"),
        ("انور علی حیدر، ہی (M) ہیں", "Anwar Ali Hyder، HI(M) ہیں"),
        # abbreviations spelled as letter names, and the gloss that repeated them
        ("952 ایم ایم بی او ای (MMBOE) ہیں", "952 MMBOE ہیں"),
        ("اور سی ای او فہیم حیدر ہیں", "اور CEO Faheem Haider ہیں"),
        ("ان کے سی ای او", "ان کے CEO"),
        ("کے پی ایم جی میں کام کیا", "KPMG میں کام کیا"),
        ("952 ملین بارل آئل ایکویویلنٹ (MMBOE) ہیں", "952 ملین بارل آئل ایکویویلنٹ ہیں"),
        # names, correctly and wrongly spelled
        ("فیہم حیدر", "Faheem Haider"),
        ("انور علی ہائڈر", "Anwar Ali Hyder"),
        ("انور علی ہائر", "Anwar Ali Hyder"),
        ("ایلا ماجد", "Ayla Majid"),
        ("سید شاہ زاد نبی", "Syed Shahzad Nabi"),
        ("بختیار کاظمی", "Bakhtiyar Kazmi"),
        # a rank misspelling stays Urdu, but correctly spelled
        ("لیٹنٹ جنرل (ر)", "لیفٹیننٹ جنرل (ر)"),
    ],
)
def test_observed_urdu_script_forms_are_put_back(written: str, latin: str) -> None:
    assert latin_terms(written, "ur") == latin


def test_the_board_reply_keeps_its_punctuation_and_joining_words() -> None:
    said = latin_terms(
        "ارکان میں ایلا ماجد، سید بختیار کاظمی، سید شاہ زاد نبی اور سیما عادل شامل ہیں۔", "ur")
    assert said == ("ارکان میں Ayla Majid، Syed Bakhtiyar Kazmi، Syed Shahzad Nabi اور "
                    "Seema Adil شامل ہیں۔")


@pytest.mark.parametrize(
    "text",
    [
        # name words that are everyday Urdu words on their own
        "ان کے پاس حسن اور نبی کی باتیں ہیں، عادل آدمی، حیات اچھی ہے۔",
        # «ماری» is also "killed"; «میری انرجی» is "my energy"
        "اس نے گیند ماری۔ یہ میری انرجی ہے۔",
        # letter names that spell nothing the kiosk knows
        "ایف ایچ ایم سی ایف",
        # an ordinary «کے» before a letter
        "ان کے پی ایچ",
        # «لیے» skeletons like «علی» and «ہماری» is one letter from «حیدر»: this became "Ali Hyder"
        "مزید تفصیل کے لیے ہماری ویب سائٹ دیکھ لیں۔",
        # «لیے» again, with «موجود» skeletoning exactly like «مجید»: this became "Ayla Majid"
        "یہ سہولت آپ کے لیے موجود ہے۔",
    ],
)
def test_ordinary_urdu_is_left_alone(text: str) -> None:
    assert latin_terms(text, "ur") == text


def test_english_replies_are_untouched() -> None:
    assert latin_terms("Faheem Haider leads Mari Energies.", "en") == \
        "Faheem Haider leads Mari Energies."


def test_the_pronunciation_fixes_reach_the_reply_again() -> None:
    """The point of the module: the Urdu voice now gets the measured spoken forms."""
    reply = ("میری انرجیز کے بورڈ کے چیئرمین لیٹنٹ جنرل (ر) انور علی ہائڈر، ایچ آئی (م) ہیں، "
             "اور ذخائر 952 ایم ایم بی او ای (MMBOE) ہیں۔")
    said = normalize_for_tts(latin_terms(reply, "ur"), "ur")
    assert "ماڑی Energies" in said
    assert "ریٹائرڈ لیفٹیننٹ جنرل انور علی حیدر" in said
    assert "ہلالے امتیاز ملٹری" in said
    assert "ملین بیرل آئل ایکوی ویلنٹ" in said
    assert "میری" not in said and "ایچ آئی" not in said


def test_the_responder_applies_it_to_every_sentence() -> None:
    import inspect

    from server.agent import responder

    assert "latin_terms(sentence, lang)" in inspect.getsource(responder.respond_sentences)
    assert "latin_terms(reply, lang)" in inspect.getsource(responder.respond)


@pytest.mark.parametrize(
    "written,fixed",
    [
        # Qwen switches script after the first letter; each of these reached the screen.
        ("Mari Energies کے کiosk پر", "Mari Energies کے kiosk پر"),
        ("یہ فiscal year 2024-25 ہے", "یہ fiscal year 2024-25 ہے"),
        ("عابد نiaz حسن", "عابد Niaz حسن"),        # the corpus's own capitalisation
        ("ہم کompany ہیں", "ہم company ہیں"),       # lower case where the corpus uses it
    ],
)
def test_a_word_that_switches_script_partway_is_made_latin(written: str, fixed: str) -> None:
    assert latin_terms(written, "ur") == fixed


@pytest.mark.parametrize(
    "text",
    ["Sky47 کی سروس", "میں نے 2024 میں دیکھا", "Mari Energies کے kiosk پر", "MD/CEO Faheem Haider ہیں"],
)
def test_words_wholly_in_one_script_are_left_alone(text: str) -> None:
    assert latin_terms(text, "ur") == text


@pytest.mark.parametrize(
    "written,fixed",
    [
        # The female presenter's name in place of the brand, from a real long introduction.
        ("یہاں مریم انرجیز کے ہیڈ آفس میں", "یہاں Mari Energies کے ہیڈ آفس میں"),
        ("(پہلے مریم پٹرولیم کمپنی لمیٹڈ)", "(پہلے Mari Petroleum کمپنی لمیٹڈ)"),
        ("ڈہرکی میں مریم گیس فیلڈ کی دریافت", "ڈہرکی میں Mari Gas Field کی دریافت"),
        ("1954 میں ماری گیس فیلڈ", "1954 میں Mari Gas Field"),
        ("مریم سروسز اور مریم منرلز", "Mari Services اور Mari Minerals"),
    ],
)
def test_the_presenters_name_in_place_of_the_brand_is_fixed(written: str, fixed: str) -> None:
    assert latin_terms(written, "ur") == fixed


@pytest.mark.parametrize("text", ["میں مریم ہوں۔", "میرا نام مریم ہے، Mari Energies سے۔"])
def test_the_presenter_still_has_her_own_name(text: str) -> None:
    assert latin_terms(text, "ur") == text
