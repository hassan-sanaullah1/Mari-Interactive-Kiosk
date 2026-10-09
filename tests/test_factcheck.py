"""The answer-eval scorer's matching rules.

eval/factcheck.py decides whether a spoken reply carried a required fact, and every
number in an answer-eval run rests on it. The pairs below are the real ones from the
tester's evaluation: the knowledge base writes "40%" and "A.F. Ferguson", the kiosk
speaks "forty percent", and the two have to meet. Offline by construction — the scorer
imports nothing but the stdlib and server/normalization.py.
"""

import pytest

from eval.factcheck import canon, hit, score


@pytest.mark.parametrize(
    "fact, reply",
    [
        # Numerals against the number words the TTS normaliser produces.
        ("40%", "The Fauji Foundation holds a forty percent stake"),
        ("31%", "a 31 percent share of the country's gas output"),
        ("127,000", "capacity stands at one hundred and twenty-seven thousand barrels"),
        ("952", "reserves totalling nine hundred and fifty-two million barrels"),
        ("1,760", "a team of one thousand, seven hundred and sixty people"),
        ("35", "he brings over thirty-five years of leadership"),
        # Thousands separators and dashes are never meaningful.
        ("322,973", "we produced 322973 MMSCF of gas"),
        ("1975–2006", "Operations Advisor at the World Bank from 1975-2006"),
        ("2024-25", "in FY 2024 25 the company reported"),
        # Initials and abbreviations survive canonicalisation.
        ("A.F. Ferguson", "our auditors are A.F. Ferguson & Co."),
        ("AAA/A1", "a credit rating of AAA/A1"),
        ("G-10/4", "21 Mauve Area, 3rd Road, G 10/4, Islamabad"),
    ],
)
def test_a_fact_said_either_way_is_found(fact, reply):
    assert hit([fact], reply)


@pytest.mark.parametrize(
    "fact, reply",
    [
        # The exact omissions the tester flagged. These must NOT match, or the eval
        # would score a reply as complete when the visitor never heard the fact.
        ("A.F. Ferguson", "Our external auditors are Ferguson & Co., Chartered Accountants."),
        ("P.O. Box 1614", "The head office is at 21 Mauve Area, G-10/4, Islamabad, 44000."),
        ("Neptune Energy", "over 30 years with Union Texas Petroleum and BG Group"),
        ("1,053,210", "held a 31 percent share of the country's gas output"),
    ],
)
def test_a_fact_the_reply_omitted_is_not_found(fact, reply):
    assert not hit([fact], reply)


def test_any_accepted_variant_counts():
    assert hit(["27/03/2026", "27 March 2026"], "having joined the board on 27 March 2026")


def test_canon_folds_case_dashes_and_separators():
    assert canon("Twenty–Seven, 1,234") == canon("twenty seven 1234")


def test_all_facts_present_is_matched():
    reply = "A.F. Ferguson & Co., Chartered Accountants, of Islamabad."
    got = score([["A.F. Ferguson"], ["Chartered Accountants"], ["Islamabad"]], [], reply)
    assert got.grade == "Matched"
    assert (got.hits, got.total) == (3, 3)


def test_some_facts_present_is_partial():
    reply = "Our external auditors are Ferguson & Co., Chartered Accountants."
    got = score([["A.F. Ferguson"], ["Chartered Accountants"], ["Islamabad"]], [], reply)
    assert got.grade == "Partial"
    assert got.missing == [["A.F. Ferguson"], ["Islamabad"]]


def test_no_facts_present_is_not_matched():
    got = score([["Reko Diq"], ["OGDCL"]], [], "I don't have that one to hand.")
    assert got.grade == "Not Matched"


def test_a_miss_is_blamed_on_generation_when_the_context_had_it():
    """The distinction the whole eval turns on: retrieval's fault, or the prompt's."""
    got = score(
        [["Neptune Energy"], ["Reko Diq"]],
        [],
        "He worked at BG Group.",
        context="...career including OMV, BG Group and Neptune Energy.",
    )
    assert [e.cause for e in got.entries] == ["generation", "retrieval"]


def test_optional_facts_are_counted_but_never_graded():
    got = score([["Sky47"]], ["Ammuri", "Tuzgi"], "Sky47 runs the data centres, with Tuzgi.")
    assert got.grade == "Matched"
    assert (got.optional_hits, got.optional_total) == (1, 2)
