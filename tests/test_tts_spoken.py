"""How a reply is rewritten for the voice.

Uplift's voice is Urdu-first and reads bare digits in Urdu, so an English reply
containing "65.14" was spoken with Urdu numbers. English replies therefore spell
their numbers out; Urdu replies must keep the digits, where that reading is right.
"""

from __future__ import annotations

import pytest

from server.normalization import _say_int, normalize_for_tts


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Net profit was PKR 65.14 billion.", "sixty five point one four billion rupees"),
        ("The workforce is 1,760 people.", "one thousand seven hundred and sixty"),
        ("Discovered in 1954.", "nineteen fifty four"),
        ("Listed in 2025.", "twenty twenty five"),
        ("Back in 2000.", "two thousand"),
        ("Capacity is 127 KBOEPD.", "one hundred and twenty seven"),
        ("A 20-year ratio.", "twenty-year"),
    ],
)
def test_english_numbers_are_spelled_out(text: str, expected: str) -> None:
    assert expected in normalize_for_tts(text, "en")


def test_english_leaves_no_bare_digits() -> None:
    """Any digit reaching the Urdu-first voice would be read in Urdu."""
    said = normalize_for_tts("Net profit PKR 65.14 billion, 1,760 staff, founded 1954.", "en")
    assert not any(ch.isdigit() for ch in said), said


@pytest.mark.parametrize(
    "text",
    [
        "خالص منافع 65.14 بلین روپے رہا۔",
        "ملازمین کی تعداد 1,760 ہے۔",
    ],
)
def test_urdu_digits_are_left_alone(text: str) -> None:
    """Urdu mode wants the Urdu reading, so the digits must survive untouched."""
    assert normalize_for_tts(text, "ur") == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The reported bug: Uplift read the bare digits as a cardinal quantity,
        # "ایک ہزار نو سو چون", where a year is said as a century pair.
        ("گیس فیلڈ 1954 میں دریافت ہوا۔", "انیس سو چون"),
        ("کمپنی 1984 میں قائم ہوئی۔", "انیس سو چوراسی"),
        ("1866 میں۔", "اٹھارہ سو چھیاسٹھ"),
        ("1905 میں۔", "انیس سو پانچ"),      # a single-digit tail takes no "صفر"
        ("1900 میں۔", "انیس سو"),            # a round century has no tail at all
    ],
)
def test_urdu_years_are_said_as_century_pairs(text: str, expected: str) -> None:
    """A year is "انیس سو چون", not the cardinal count of one thousand nine hundred."""
    said = normalize_for_tts(text, "ur")
    assert expected in said
    assert "ہزار" not in said


@pytest.mark.parametrize(
    "text",
    [
        "2024 میں منافع بڑھا۔",       # 20xx: the cardinal reading IS the year reading
        "FY2024-25 میں۔",             # a fiscal pair, owned by the formats pass
        "2017-2020 کے دوران۔",        # a year range, already spelt with "تا"
        "24/06/2022 کو۔",             # a date, already split into day/month/year
    ],
)
def test_the_urdu_year_rule_leaves_the_other_shapes_alone(text: str) -> None:
    """Fiscal pairs, ranges, dates and 20xx years keep the reading they already had."""
    assert "سو" not in normalize_for_tts(text, "ur")


def test_phone_numbers_are_read_digit_by_digit() -> None:
    """A dialling code is an identifier, not a quantity."""
    said = normalize_for_tts("Call 051-111 410 410.", "en")
    assert "one hundred and eleven" not in said
    assert "zero five one" in said


def test_acronyms_apply_in_both_languages() -> None:
    """Each language gets its own spoken form. Letter-spacing is an English fix; an
    Urdu reply needs Urdu script, because handing Latin to the Urdu-first voice is
    what broke these in the first place."""
    assert "M P C L" in normalize_for_tts("MPCL results", "en")
    assert "ایم پی سی ایل" in normalize_for_tts("MPCL کی رپورٹ", "ur")


def test_mari_is_said_with_the_retroflex_flap() -> None:
    """"Mari" is spelled with ر in both scripts, but said with ڑ, not a tapped ر."""
    assert "ماڑی" in normalize_for_tts("MARI welcomes you to Mari Energies.", "en")
    assert "ماڑی" in normalize_for_tts("آپ ماری ہیں — Mari Energies کی نمائندگی کرتی ہیں۔", "ur")


def test_mari_respelling_does_not_touch_unrelated_words() -> None:
    assert normalize_for_tts("مریم آج نہیں آئیں۔", "ur") == "مریم آج نہیں آئیں۔"


@pytest.mark.parametrize(
    "n,said",
    [(0, "zero"), (13, "thirteen"), (21, "twenty one"), (101, "one hundred and one"),
     (3000, "three thousand"), (952, "nine hundred and fifty two")],
)
def test_say_int(n: int, said: str) -> None:
    assert _say_int(n) == said


# ── report formats and symbols ──────────────────────────────────────
# normalization.spoken_formats, measured against the shapes that occur
# in server/data/mari_energies_knowledge_base.md. These run in BOTH languages.

@pytest.mark.parametrize(
    "text,expected",
    [
        # "FY2024-25" was glued into "FYtwenty twenty four": the label never separated.
        ("Revenue in FY2024-25 rose.", "financial year twenty twenty four to twenty five"),
        ("In FY 2024-25 we grew.", "financial year twenty twenty four to twenty five"),
        ("In FY24-25 we grew.", "financial year twenty four to twenty five"),
        ("A bare 2024-25 period.", "twenty twenty four to twenty five"),
        # DD/MM/YYYY kept its slashes, which the voice reads as "slash".
        ("Dated 24/06/2022 today.", "twenty four June twenty twenty two"),
        # "2.81x" matched no rule at all and was read as the letter "ex".
        ("Current ratio is 2.81x.", "two point eight one times"),
        # An en-dash between numbers is a range, not a minus.
        ("Output 93,000-113,000 BOEPD.".replace("-", "–"), "thousand to one hundred"),
        ("It fell −2.72 percent.", "minus two point seven two"),
        ("About ~PKR 753 billion.", "approximately"),
    ],
)
def test_report_formats_are_spoken(text: str, expected: str) -> None:
    assert expected in normalize_for_tts(text, "en")


@pytest.mark.parametrize(
    "text,expected",
    [
        # A well name is an identifier: the spell-out read "-01" as the quantity
        # "one" and silently dropped the leading zero.
        # The name itself is respelled by the places pass, which runs after this one;
        # what matters here is that the "01" is read as two digits, not the quantity
        # "one" with its leading zero dropped.
        ("We drilled Karakoram-01 well.", "zero one"),
        ("The Soho-1 well.", "Soho one"),
        ("Production from Block-5.", "Block five"),
    ],
)
def test_well_identifiers_are_read_digit_by_digit(text: str, expected: str) -> None:
    assert expected in normalize_for_tts(text, "en")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Condensate 20 BOPD.", "barrels of oil per day"),
        ("Output 93,000 BOEPD.", "barrels of oil equivalent per day"),
        ("Gas sold 260 BSCF.", "billion standard cubic feet"),
        ("Mari D&PL, Sindh.", "development and production lease"),
        ("We hold 92,675 sq km.", "square kilometres"),
        ("We moved 932 MT.", "metric tons"),
        ("We used 3,914,393 GJ.", "gigajoules"),
        # "Mn" reached the voice as two letters; "bn" already worked.
        ("Profit was PKR 2,291 Mn.", "million rupees"),
        ("Profit was PKR 65.14bn.", "billion rupees"),
    ],
)
def test_units_and_scale_words_are_expanded(text: str, expected: str) -> None:
    assert expected in normalize_for_tts(text, "en")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("آمدنی FY2024-25 میں بڑھی۔", "مالی سال 2024 تا 25"),
        ("تاریخ 24/06/2022 ہے۔", "24 جون 2022"),
        ("تناسب 2.81x ہے۔", "2.81 گنا"),
    ],
)
def test_report_formats_apply_in_urdu_too(text: str, expected: str) -> None:
    """These are structural, not phonetic, so unlike the number spell-out they are
    not English-only. Urdu keeps its digits, which Uplift reads correctly."""
    assert expected in normalize_for_tts(text, "ur")


@pytest.mark.parametrize(
    "lang,text,must_keep",
    [
        ("en", "A 20-year ratio.", "twenty-year"),   # digits before the hyphen
        ("en", "An 18-inch pipeline.", "eighteen-inch"),
        # A full year-to-year span reads as two years, not as a fiscal pair — and not
        # as a dialling code, which is what the phone rule made of "2017-2020".
        ("en", "Tenure 2017-2020.", "twenty seventeen to twenty twenty"),
        ("ur", "ہم 24/7 دستیاب ہیں۔", "24/7"),        # a ratio, not a date
        ("ur", "2024/25 کے دوران۔", "2024/25"),        # a financial year, not a date
    ],
)
def test_formats_do_not_touch_what_already_reads_correctly(
    lang: str, text: str, must_keep: str
) -> None:
    """The rules are anchored to their own shapes. A digit before the hyphen is a
    measurement, not an identifier, and a numeric slash is a ratio, not a date."""
    assert must_keep in normalize_for_tts(text, lang)


def test_an_acronym_beside_its_own_expansion_is_not_said_twice() -> None:
    """The model habitually writes the full title then the acronym in brackets —
    "سپلائی چین مینجمنٹ (SCM)". Expanding the bracket said the same three words twice
    in a breath. The bracket is there to be read as letters, which is what a speaker
    does; the same reasoning as the MD/CEO pair in the addresses section."""
    said = normalize_for_tts("سپلائی چین مینجمنٹ (SCM) ٹیم کو بھیجیں۔", "ur")
    assert said.count("سپلائی چین مینجمنٹ") == 1
    assert "ایس سی ایم" in said


def test_a_respelled_loanword_beside_its_own_gloss_is_not_said_twice() -> None:
    """The model also writes an Urdu-script loanword then its own Latin spelling in
    brackets — "ورٹیکلز (verticals)". Respelling the Urdu word to Latin and leaving the
    bracket alone said "verticals (verticals)" — the same word twice."""
    said = normalize_for_tts("ہمارے چار ورٹیکلز (verticals) ہیں۔", "ur")
    assert said.count("verticals") == 1


@pytest.mark.parametrize("text", [
    "GEM Energy جو میتھین مٹی گیشن میں ماہر ہے۔",
    "GEM Energy جو میٹھین مٹیگیشن میں ماہر ہے۔",
    # "CH4" is expanded to "میتھین" by the address pass, after the first phrase rule.
    "GEM Energy جو CH4 مٹیگیشن میں ماہر ہے۔",
])
def test_methane_mitigation_is_said_in_one_script(text: str) -> None:
    """Fixing the two words separately left the phrase half Latin ("methayn") and half
    Urdu ("مٹی گیشن"). Uplift takes its vowels from the script it is reading, and the
    change mid-phrase turned the second word into "matigation"."""
    said = normalize_for_tts(text, "ur")
    assert "methayn mitigation" in said
    assert "مٹی گیشن" not in said


@pytest.mark.parametrize("text", [
    "GEM Energy works on methane mitigation.",
    "Methane Mitigation is one of our verticals.",
    "Mari Minerals mines rare earth elements and copper.",
])
def test_english_phrases_are_left_unpunctuated(text: str) -> None:
    """No sentence stop is spliced into these phrases any more.

    Each used to get a period mid-phrase to stop the voice slurring the pair. Measured
    against the live Uplift voice — synthesise, transcribe, read the word timings back —
    the stop did not help and usually hurt: "rare earth elements and copper" is said
    correctly with no punctuation (longest internal gap 0.00s) and mangled with it
    ("way, Earth's elements", 0.64s), while "methane mitigation" is identical either
    way and merely gained a 0.9s hole. The unnatural gaps a visitor hears were these
    rules, so the phrases now reach the voice exactly as written."""
    said = normalize_for_tts(text, "en")
    assert ". Mitigation" not in said
    assert "rare. Earth" not in said
    assert "food. Grade" not in said


@pytest.mark.parametrize("text", [
    "We produce food-grade CO2.",
    "We produce food grade CO2.",
])
def test_food_grade_keeps_its_space_and_gains_no_stop(text: str) -> None:
    """The voice says "grade" as "great" whatever punctuation it is given, so the stop
    bought nothing and only widened the gap. The corpus's hyphen is still normalised to
    a space, because a hyphen mid-word does read as a break."""
    said = normalize_for_tts(text, "en")
    assert "food grade" in said
    assert "food. Grade" not in said
    assert "food-grade" not in said


def test_the_english_phrase_rules_leave_urdu_alone() -> None:
    """Urdu keeps its own methane rule, which has the harder job of holding one script
    across the phrase and so cannot use a stop."""
    said = normalize_for_tts("GEM Energy جو میتھین مٹیگیشن میں ماہر ہے۔", "ur")
    assert "methayn mitigation" in said
    assert "methane. Mitigation" not in said


@pytest.mark.parametrize("text", [
    "Huawei Cloud Stack powers Sky47 Cloud.",
    "Huawei Ascend NPUs power the AI Farm.",
])
def test_huawei_is_respelled_for_the_english_voice(text: str) -> None:
    """English runs through the same Uplift Urdu-first voice, which gives Latin
    "Huawei" English letter values ("hoo-AH-way"). Urdu script is what that voice
    reads correctly — the same trick "Maryam" and "Hamza" use in both languages."""
    said = normalize_for_tts(text, "en")
    assert "ہواوے" in said
    assert "Huawei" not in said


def test_huawei_in_urdu_script_is_left_alone() -> None:
    """The Urdu-first voice already reads ہواوے correctly — only the Latin spelling is
    the problem, so the Urdu-script form must not be rewritten to Latin."""
    said = normalize_for_tts("ہواوے کے ساتھ شراکت داری۔", "ur")
    assert "ہواوے" in said


@pytest.mark.parametrize("text", [
    "liquid-cooled for AI training",
    "liquid cooled for AI training",
])
def test_liquid_cooled_hyphen_is_not_swallowed_in_english(text: str) -> None:
    """The hyphen carries no sound but the voice ran the compound into one non-word.
    A space is what it needs; the visitor still reads the written form."""
    said = normalize_for_tts(text, "en")
    assert "liquid cooled" in said
    assert "liquid-cooled" not in said


def test_kw_is_spoken_as_a_unit_in_english() -> None:
    """"50kW" is closed up against its number, so the \\b-anchored acronym table could
    never match it and the unit was dropped: the voice said "fifty" and moved on."""
    said = normalize_for_tts("up to 50kW per rack density", "en")
    assert "fifty kilowatts" in said
    assert "kW" not in said


def test_kw_keeps_its_unit_in_urdu() -> None:
    """The regression this rule exists for: with the unit dropped, the Urdu voice read
    the bare number as "پچاس" and a rack density became a plain count."""
    said = normalize_for_tts("50kW فی ریک کثافت۔", "ur")
    assert "کلو واٹ" in said
    assert "kW" not in said


def test_kw_matches_the_spaced_form_too() -> None:
    """The corpus writes it closed up; a reply may not."""
    assert "kilowatts" in normalize_for_tts("up to 50 kW per rack", "en")


def test_kw_number_is_said_in_english_not_urdu() -> None:
    """The unit rule must leave the digits as a separate token for the English number
    spell-out that follows it. If they stay welded to the unit ("50kilowatts") the
    spell-out cannot see them, and Uplift's Urdu-first voice reads the bare "50" as
    "پچاس" in the middle of an English sentence — the same failure as "65"/"پینسٹھ"
    that _spell_numbers exists for."""
    said = normalize_for_tts("up to 50kW per rack density", "en")
    assert "fifty kilowatts" in said
    assert "50" not in said


@pytest.mark.parametrize("text,expected", [
    ("Huawei Ascend NPU clusters", "اینپیو"),
    ("Huawei Ascend NPUs power the AI Farm", "اینپیوز"),
])
def test_npu_is_letter_named_in_english(text: str, expected: str) -> None:
    """English runs through the same Uplift Urdu-first voice, which does not reliably
    read spaced Latin capitals as letter NAMES: "N P U" was three separate tokens and
    the plural "N P Us" left a trailing "Us" heard as the English word "us". Urdu
    script spells the letter names themselves — the same fix "Huawei" uses."""
    assert expected in normalize_for_tts(text, "en")


def test_npu_is_one_token_in_english() -> None:
    """Written with spaces the voice broke on each one, so an English sentence said
    "NP ... U" with an audible pause before the last letter. The letterforms are
    joined into a single token to close it. Urdu keeps the spaced form — see
    test_npu_is_urdu_script_in_urdu."""
    assert "این پی یو" not in normalize_for_tts("Ascend NPU clusters", "en")


def test_npu_plural_is_matched_before_the_singular() -> None:
    """The acronym rules are \\b-anchored on both sides, so a bare "NPU" entry cannot
    reach inside "NPUs": the trailing "s" leaves no boundary after the "U". The plural
    needs its own entry, listed first because the table applies in insertion order."""
    said = normalize_for_tts("Ascend NPUs and NPU clusters", "en")
    assert "اینپیوز" in said
    assert "NPUs" not in said


def test_gpu_plural_is_spaced_too() -> None:
    """Same boundary gap, found while fixing NPU: "GPU" was in the table but "GPUs"
    fell straight through it."""
    assert "G P Us" in normalize_for_tts("GPUs are fast", "en")


@pytest.mark.parametrize("text,expected", [
    ("ہواوے Ascend NPU پر", "این پی یو"),
    ("NPUs کے ساتھ", "این پی یوز"),
])
def test_npu_is_urdu_script_in_urdu(text: str, expected: str) -> None:
    """Latin letters handed to the Urdu-first voice are read with English letter names
    dropped into an Urdu sentence — the failure the Urdu column of this table exists
    for."""
    assert expected in normalize_for_tts(text, "ur")


@pytest.mark.parametrize("text", [
    "یہ liquid-cooled ریک ہیں۔",
    # Both earlier Urdu-script respellings, which SAID "cold" — "کولڈ" is how Urdu
    # writes the English word. They are mapped out too, so a reply written either way
    # is still corrected.
    "یہ لیکویڈ کولڈ ریک ہیں۔",
    "یہ لیکوئڈ کولڈ ریک ہیں۔",
])
def test_liquid_cooled_is_said_in_english_in_urdu_too(text: str) -> None:
    """Latin "cooled" is read by the Urdu-first voice with one long "o" and loses the
    "-ed", so "liquid cooled" was heard as "liquid cold". The term is wanted in English,
    so it maps to a Latin phonetic respelling — the doubled vowel forces the "oo" and
    the final "-d" keeps the participle."""
    said = normalize_for_tts(text, "ur")
    assert "likwid koold" in said
    # No spelling that reads as "cold" survives.
    assert "کولڈ" not in said
    assert "cooled" not in said


@pytest.mark.parametrize("spelling", [
    "سبسڈیری", "سبسڈییری", "سب سڈیری", "سبسیڈیری",
    # Malformed, as the model actually wrote it in a live reply: a repeated tail.
    "سبسیڈیریاری",
])
def test_subsidiary_is_respelled_for_the_urdu_voice(spelling: str) -> None:
    """"سبسڈیری" has no vowel between its ب-س clusters, so the voice ran the syllables
    together and dropped the middle one. The model spells the word many ways, and
    sometimes malforms it with a repeated tail — matching only the well-formed prefix
    rewrote the head and left the garbage attached ("سب سِڈی ریاری"), making the word
    worse rather than skipping it. The rule must consume the whole thing."""
    said = normalize_for_tts(f"یہ ماری کی {spelling} ہے۔", "ur")
    assert "سب سِڈی ری" in said
    assert spelling not in said


@pytest.mark.parametrize("text", [
    "Nvidia کلسٹرز",
    "NVIDIA-compatible GPU کلسٹرز",
])
def test_nvidia_is_urdu_script_in_urdu(text: str) -> None:
    """Latin in an otherwise-Urdu sentence is read letter-wise and loses the initial
    "en-"; the corpus's all-caps "NVIDIA-compatible" is worse still."""
    said = normalize_for_tts(text, "ur")
    assert "اینویڈیا" in said
    assert "NVIDIA" not in said and "Nvidia" not in said


def test_nvidia_compatible_stays_in_one_script() -> None:
    """Leaving "compatible" in Latin beside the Urdu-script vendor name puts a script
    change mid-modifier, which is what mis-vowels the voice."""
    said = normalize_for_tts("NVIDIA-compatible GPU کلسٹرز", "ur")
    assert "اینویڈیا کمپیٹیبل" in said
    assert "compatible" not in said


def test_nvidia_is_respelled_in_english_too() -> None:
    """English runs through the same Uplift Urdu-first voice, which letter-spells the
    corpus's all-caps "NVIDIA" as an initialism. The respelling must be ONE word: a
    spaced form is read as separate tokens, which is spelling it out again. Each
    language gets its own form; the Urdu one must not leak into an English reply."""
    said = normalize_for_tts("NVIDIA-compatible GPU clusters", "en")
    assert "Envidia" in said
    assert "NVIDIA" not in said
    assert "اینویڈیا" not in said


def test_huawei_is_urdu_script_in_both_languages() -> None:
    """One voice serves both languages, so one spelling works for both. Three Latin
    respellings were tried and all failed: "Wah-way" split at the hyphen, "Wah way"
    was two tokens and dropped the H, "Hwahway" spelled a cluster the voice cannot
    read. ad-hoc English phonetics is the wrong tool for a voice not reading English."""
    assert "ہواوے" in normalize_for_tts("Huawei Ascend NPUs", "en")
    assert "ہواوے" in normalize_for_tts("Huawei Ascend NPU", "ur")


def test_english_respellings_use_no_hyphen() -> None:
    """The kiosk runs English through the SAME Uplift Urdu-first voice as Urdu
    (APP_EN_TTS=uplift), which reads a hyphen as a break rather than a syllable join —
    "Wah-way" was said as two clipped pieces, and the spaced "Wah way" then lost the
    leading H. One unbroken word is what this voice says whole."""
    said = normalize_for_tts("Huawei and NVIDIA build the AI Farm.", "en")
    assert "Wah-way" not in said
    assert "Envidia" in said


def test_nvidia_respelling_is_a_single_token() -> None:
    """The regression this guards: "en VID ee uh" is four tokens, so the voice read the
    pieces one after another instead of saying the name — spelling it out by another
    route. The replacement must contain no space and no hyphen."""
    said = normalize_for_tts("NVIDIA clusters", "en")
    nvidia = next(w for w in said.split() if "vidia" in w.lower())
    assert nvidia == "Envidia"



@pytest.mark.parametrize("text,expected", [
    ("GPU کلسٹرز", "klusturz"),
    ("یہ کلسٹر ہے۔", "klustur"),
    # The earlier Urdu-script respelling, which said a long "aa" ("klaaster"). It is
    # mapped out too, so a reply written that way is still corrected.
    ("یہ کلاسٹر ہے۔", "klustur"),
    ("GPU کلاسٹرز", "klusturz"),
    # The model writes the Latin spelling in an Urdu reply too.
    ("NVIDIA GPU clusters استعمال کرتا ہے۔", "klusturz"),
])
def test_clusters_is_said_in_english_in_urdu_too(text: str, expected: str) -> None:
    """"Clusters" is a technical term and is wanted in English, said the English way.
    Neither Urdu spelling can produce the English short "u", so both map out to a Latin
    phonetic respelling — the same trick as "kaeosk" and "methayn"."""
    said = normalize_for_tts(text, "ur")
    assert expected in said
    # No Urdu-script spelling of the word survives, in either form.
    assert "کلسٹر" not in said
    assert "کلاسٹر" not in said


def test_clusters_plural_is_matched_before_the_singular() -> None:
    """The singular pattern would otherwise match inside the plural and leave the
    trailing ز stranded — the same trap _SUBSIDIARY_RE hit on a malformed spelling."""
    said = normalize_for_tts("GPU کلسٹرز", "ur")
    assert "klusturz" in said
    assert "klusturz" == said.split()[-1]


def test_clusters_is_left_alone_in_english() -> None:
    """English mode already reads the English word correctly, so it is not respelled."""
    said = normalize_for_tts("GPU clusters", "en")
    assert "clusters" in said
    assert "کلاسٹر" not in said
    assert "klustur" not in said


@pytest.mark.parametrize(("lang", "expected"), [
    ("en", "AI and ML"),
    ("ur", "اے آئی اور ایم ایل"),
])
def test_ai_ml_names_both_acronyms(lang: str, expected: str) -> None:
    """The slash rules split "AI/ML", but only "AI" had an acronym entry — "ML" fell
    through as bare Latin and the Urdu-first voice read it as a non-word."""
    said = normalize_for_tts("AI/ML training and inference", lang)
    assert expected in said
    assert "AI/ML" not in said


def test_ml_is_not_left_as_bare_latin_in_urdu() -> None:
    """A bare Latin two-letter token mid-Urdu-sentence is the shape that mis-reads."""
    said = normalize_for_tts("یہ ML training کے لیے ہے۔", "ur")
    assert "ایم ایل" in said
    assert "ML" not in said
