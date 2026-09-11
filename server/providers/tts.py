"""TTS adapters — each implements :class:`server.providers.base.TTSProvider`.

  UpliftTTS        Urdu, and English while APP_EN_TTS=uplift — UpliftAI REST (mp3)
  KokoroLocalTTS   English — local Kokoro (GPU if available)
  KokoroRemoteTTS  English — remote OpenAI-compatible /v1/audio/speech

Shared by both entrypoints: server/app.py (FastAPI) and mari_s2s/handlers/*.py
(huggingface/speech-to-speech plugin handlers) — no more duplicated REST-call logic.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from .. import config as C
from .base import TTSProvider

try:  # voice_config is optional — without it the Uplift-specific fixes just don't apply
    from voice_config import (
        normalise_for_english as _normalise_for_english,
        normalise_for_uplift as _normalise_for_uplift,
        spoken_addresses as _spoken_addresses,
        spoken_formats as _spoken_formats,
        spoken_names_and_ranks as _spoken_names_and_ranks,
        spoken_places as _spoken_places,
        spoken_urls as _spoken_urls,
    )
except ImportError:  # pragma: no cover - only hit if the folder is removed
    def _normalise_for_uplift(text: str, lang: str = "ur") -> str:
        return text

    def _spoken_formats(text: str, lang: str = "en") -> str:
        return text

    def _normalise_for_english(text: str, lang: str = "en") -> str:
        return text

    def _spoken_places(text: str, lang: str = "en") -> str:
        return text

    def _spoken_names_and_ranks(text: str, lang: str = "en") -> str:
        return text

    def _spoken_urls(text: str, lang: str = "en") -> str:
        return text

    def _spoken_addresses(text: str, lang: str = "en") -> str:
        return text


# The brand name has to be forced into words for Uplift's Urdu-first voices, both ways:
# in English text "Sky47" comes out as one mangled word ("SkySitalis"), and in Urdu text
# the digits are read as the Urdu number — "اسکائی ۴۷" is spoken "sentaalees", not "forty
# seven". Spelling it out fixes both, and "Sky Forty Seven" is pronounced identically in
# an Urdu sentence, so one replacement covers every reply.
_SKY = r"(?:Sky|\u0627\u0633\u06a9\u0627\u0626\u06cc|\u0633\u06a9\u0627\u0626\u06cc|\u0627\u0633\u06a9\u0627\u06cc|\u0633\u06a9\u0627\u06cc)"
_47 = r"(?:47|\u06f4\u06f7|\u0664\u0667)"  # ASCII, Urdu (۴۷) and Arabic-Indic (٤٧) digits

# "Mari" is spelled with ر (tapped r) in both scripts (Latin "Mari" and Urdu
# "ماری"), but the name is actually said with a retroflex flap — ڑ, as in
# "ماڑی" — not a tapped ر. Uplift's voice reads whatever script it is given
# literally, so both spellings are rewritten to ماڑی before synthesis, in either
# language.
_MARI = r"(?:Mari|ماری)"
# The PSX ticker symbol is written all-caps ("MARI"), which the case-sensitive rule
# above does not match, so it fell through unrewritten and Uplift read it letter by
# letter in English. It gets the same ڑ treatment as the brand name.
_MARI_TICKER = r"MARI"

# "Lead"/"leading" written in Urdu script (لیڈ) is read by Uplift's Urdu-first voice as
# "late" instead of "lead". Forcing it to the Latin "Lead" makes the voice read it with
# English phonemes, which is correct here — it is an English loanword sitting in an
# otherwise-Urdu sentence, the same situation "listed energy company" is in and is
# always written in Latin script by the persona rules. The visitor still reads whatever
# the model wrote; only the TTS payload changes.
_LEAD = r"(?:Lead|لیڈ)"

# Same problem, same fix: "listed" written in Urdu script is read wrong. The model
# writes it two ways — لیسٹڈ and لسٹڈ (without the ی) — both mispronounced.
_LISTED = r"(?:Listed|لیسٹڈ|لسٹڈ)"

# Same problem, same fix: "interactive" written in Urdu script (انٹرایکٹو) is read
# incompletely/incorrectly — part of the word gets dropped or garbled. The persona's
# own opening line uses this word (voice_config/prompts/system_prompt_urdu.md), so it
# comes up on nearly every first turn.
_INTERACTIVE = r"(?:Interactive|انٹرایکٹو)"

# Same problem, same fix: "capitalization" written in Urdu script (کیپیٹلائزیشن) is
# read wrong — comes up whenever the reply mentions MARI's market capitalization.
_CAPITALIZATION = r"(?:Capitalization|Capitalisation|کیپیٹلائزیشن)"

# Same problem, same fix: "verticals"/"vertical" written in Urdu script is read wrong.
# The persona rules themselves use the Urdu singular (system_prompt_urdu.md's "کسی
# ورٹیکل یا شعبے کے کام میں"), so the model can echo it. The model writes the ٹ (retroflex
# t) as plain ت two ways too — ورتیکلز/ورتیکل — so both spellings are matched. Plural
# matched before singular so the plural forms are not left with a stray ز.
_VERTICALS_PL = r"(?:Verticals|ورٹیکلز|ورتیکلز)"
_VERTICAL_SG = r"(?:Vertical|ورٹیکل|ورتیکل)"

# Same problem, same fix: "seismic" written in Urdu script is read wrong. The model
# writes it two ways — سیزمک and سیسمک (with a س instead of ز) — comes up whenever the
# reply describes Mari Services' E&P work.
_SEISMIC = r"(?:Seismic|سیزمک|سیسمک)"

# Same problem, same fix: "earth" written in Urdu script (ایتھ) is read wrong — comes
# up in "rare earth elements", one of Mari Minerals' mining products.
_EARTH = r"(?:Earth|ایتھ)"

# Same problem, same fix: "grade" written in Urdu script (گریڈ) is read wrong — comes
# up in "food grade CO2", one of GEM Energy's products.
_GRADE = r"(?:Grade|گریڈ)"

# Same problem, same fix: "cloud" written in Urdu script (کلڈ, missing the اؤ that
# spells the diphthong) is read wrong — comes up in "AI cloud infrastructure", one of
# Sky47's products.
_CLOUD = r"(?:Cloud|کلڈ|کلاؤڈ)"

# "Huawei" is read by the English voice as spelled — "hoo-AH-way" / "hwa-wei" — not the
# way the company is actually said, "WAH-way". The vendor's own English guidance is
# "Wah-way", and the Latin spelling gives the voice no way to reach it, so the spoken
# payload is respelled phonetically. Comes up throughout §3.1.3: Huawei Cloud Stack
# powers Sky47 Cloud and Huawei Ascend NPUs power the AI Farm.
# BOTH languages get the Urdu spelling, for the same reason "Maryam" and "Hamza" do
# (see _SAY_AS): the kiosk runs English through the SAME Uplift Urdu-first voice as Urdu
# (APP_EN_TTS=uplift, one voice id for both), and that voice takes its phonemes from the
# script it is reading. Latin "Huawei" gets English letter values and comes out
# "hoo-AH-way".
#
# Three Latin respellings were tried and all failed, because ad-hoc English phonetic
# spelling is the wrong tool for a voice that is not reading English: "Wah-way" was
# split at the hyphen into two clipped pieces; "Wah way" was two tokens AND silently
# dropped the H, which no piece of it spelled; "Hwahway" was one token but spelled a
# consonant cluster the voice has no reading for. ہواوے is the name as an Urdu speaker
# writes it, and that voice already says it correctly in Urdu replies — so it is the
# spelling that works in both. The visitor still READS "Huawei" on screen; only the TTS
# payload changes.
_HUAWEI_RE = re.compile(r"\bHuawei\b")
_HUAWEI_SAID = {"en": "ہواوے", "ur": "ہواوے"}

# "liquid-cooled" is read with the hyphen swallowed, running the two words together into
# a single non-word. The hyphen carries no sound — it is an English compound modifier —
# so replacing it with a space is enough, and the visitor still reads the written form.
# Comes up in the GPU as a Service rack description (§3.1.3.3).
_LIQUID_COOLED = r"(?:liquid[-\s]*cooled|لیکوئڈ[-\s]*کولڈ)"

# Power density is written closed up against the number — "50kW per rack". The unit
# cannot go in the _ACRONYMS table below, because that table is compiled with \b on
# both sides and there is NO word boundary between "0" and "k": both are word
# characters, so "\bkW\b" silently never matches "50kW" and the unit is dropped
# entirely. In English the voice then said "fifty" and moved on; in Urdu the bare
# number was read as the Urdu numeral "پچاس" with no unit at all, which is how a rack
# density became a plain count. A lookbehind for the digit is what actually matches,
# and a space is inserted so the number spell-out still sees a separate number.
_KW_RE = re.compile(r"(?<=\d)\s*kW\b")
_KW_SAID = {"en": " kilowatts", "ur": " کلو واٹ"}

# The model sometimes splits "انفراسٹرکچر" (infrastructure) into two words with a space
# — "انفرا اسٹرکچر" — which the voice reads as two separate, mispronounced words
# instead of one. Gluing them back together fixes it.
_INFRASTRUCTURE_SPLIT_RE = re.compile(r"انفرا\s+اسٹرکچر")

# "mitigation" — unlike the other loanword fixes, the WORD-JOINED Urdu spelling
# (مٹیگیشن) is what reads wrong; the model's split spelling (مٹی گیشن, with a space)
# and the plain Latin spelling both already sound correct, so this normalises any
# joined spelling to the split one instead of forcing Latin. Comes up in "methane
# mitigation", one of GEM Energy's products.
_MITIGATION_RE = re.compile(r"مٹیگیشن")

# "rare earth elements" needs NO punctuation, and adding some actively breaks it.
#
# This used to insert a sentence-ending period between "rare" and "earth" to stop the
# voice slurring the pair. Re-measured against the live Uplift voice (synthesise, then
# transcribe and read the word timings back), that is not what happens:
#
#   "rare earth elements and copper"   → said correctly, longest internal gap 0.00s
#   "rare, earth elements and copper"  → "wear, birth, elements", 0.56s gap
#   "rare. Earth elements and copper"  → "way, Earth's elements", 0.64s gap
#
# The plain text is the only one the voice gets right, and every inserted pause is both
# an unnatural gap and a WORSE pronunciation. The rule is gone rather than softened.

# "methane mitigation" (English) needed no help either: synthesised with and without
# the sentence stop this rule used to insert, the voice says "methane mitigation work"
# identically both ways — the stop bought nothing and cost a 0.9s hole mid-phrase.
# The Urdu side keeps _METHANE_MITIGATION_RE below, which does a different job (holding
# ONE script across the pair) and is still needed.

# "food grade": the voice mispronounces "grade" as "great" whatever we do — with the
# stop, with a comma, and plain — so the stop was not fixing the pronunciation it was
# added for, it was only adding a 0.9s gap (vs 0.46s plain). Left plain. The corpus's
# hyphenated "food-grade" is normalised to a space so it does not read as a stop.
_FOOD_GRADE_HYPHEN_RE = re.compile(r"\bfood-grade\b", re.I)

# "methane" is Urdu-only, same reasoning as _KIOSK_RE below: in English mode Uplift
# already says the plain Latin spelling correctly, so only the Urdu voice needs the
# "methayn" respelling. Matches the Latin spelling and both Urdu-script spellings the
# model writes — میتھین and میٹھین (with a retroflex ٹھ instead of plain تھ) — comes up
# whenever a reply describes GEM Energy's methane mitigation work.
_METHANE_RE = re.compile(r"(?:Methane|میتھین|میٹھین)", re.I)

# The two words above occur together — "methane mitigation" is how GEM Energy's work is
# described — and fixing them one at a time made the pair worse than either alone. The
# methane rule rewrites its word to Latin ("methayn") while the mitigation rule leaves
# its word in Urdu script, so the phrase reached the voice as "methayn مٹی گیشن": a
# script change mid-phrase, and Uplift takes its vowels from the script it is reading,
# which is what turned the second word into "matigation". Rewriting the PAIR in one
# step, both halves in Latin, keeps one script across the phrase. Matched before either
# single-word rule so neither gets to split it up.
_METHANE_MITIGATION_RE = re.compile(
    rf"{_METHANE_RE.pattern}[\s-]*(?:Mitigation|مٹیگیشن|مٹی\s+گیشن)", re.I
)

# "kiosk" is Urdu-only and language-dependent (see _KIOSK_RE below, applied in
# _say_as_for): in English mode the English engine already says it correctly, so only
# the Urdu voice needs the respelling. It also has to catch the malformed hybrid the
# model sometimes writes — the first letter as Urdu ک (kaf, U+06A9) instead of Latin
# "k", e.g. "کiosk" — not just the plain spelling.
_KIOSK_RE = re.compile(r"[kک]iosk", re.I)

# "سبسڈیری" (subsidiary) is written with no vowel between the two ب-س clusters, so the
# Urdu voice runs "sub" and "sid" together and drops the middle syllable — closer to
# "sabsdri" than "subsidiary". Respelling it with the ی that spells the missing vowel
# gives the voice the three syllables the word actually has. Urdu-only: in English mode
# the model writes the English word, which the engine says correctly.
# The model spells it many ways — "سبسڈیری", "سبسڈییری" (a doubled ی), "سبسیڈیری" (a ی
# before the ڈ), with a space after the first syllable, and sometimes MALFORMED with a
# repeated tail ("سبسیڈیریاری"). So the pattern allows an optional space, an optional ی
# on either side of the ڈ, and swallows any run of trailing ری/اری syllables.
#
# That trailing run matters: matching only the well-formed prefix rewrote the head and
# left the garbage attached, turning "سبسیڈیریاری" into "سب سِڈی ریاری" — the rule made
# the word worse rather than skipping it. Consuming the tail collapses any of these to
# the one correct pronunciation. Each spelling that slips through is one more reply
# that mispronounces the word, so this stays deliberately loose.
_SUBSIDIARY_RE = re.compile(r"سب\s*سی?ڈی+(?:ا?ری)+")

# "Nvidia" is Latin in an otherwise-Urdu sentence, so the Urdu-first voice reads it
# letter-wise and loses the initial "en-" — the corpus writes it "NVIDIA-compatible"
# (§3.1.3.3), all caps, which is worse still. Urdu script gives the voice the vowels.
# The hyphen is stripped with the match so "NVIDIA-compatible" does not leave a dangling
# hyphen between two scripts. Urdu-only: the English voice already says it correctly.
# Matched case-insensitively so the corpus's all-caps "NVIDIA" is caught as well as
# "Nvidia": to this voice the all-caps form looks like an initialism and gets letter-
# spelled ("N V I D I A"). The company says it "en-VID-ee-uh".
#
# The respelling has to be ONE unbroken word, like "kaeosk" and "methayn" above. A
# spaced form ("en VID ee uh") is read as four separate tokens — which is spelling it
# out again, just with different pieces — and a hyphen is read as a break by this
# voice. "Envidia" keeps it a single word the voice can say in one go.
_NVIDIA_RE = re.compile(r"\bNVIDIA\b(\s*-\s*(?=\w))?", re.I)
_NVIDIA_SAID = {"en": "Envidia", "ur": "اینویڈیا"}

# "cooled" handed to the Urdu-first voice as Latin is read with a single long "o" — it
# comes out as "cold", losing the "-ed" that makes it a participle, so "liquid cooled"
# became "liquid cold". The English rule in _SAY_AS above normalises the hyphen for
# both languages; this one goes further for Urdu only.
#
# The Urdu-script respelling was the first two attempts and BOTH produced the very
# thing the rule exists to stop: "کولڈ" is how Urdu writes the English word "cold", so
# it said "liquid cold", and the diacritic form ("لِکوئڈ کُولڈ") before it was not read
# reliably by this voice at all. The term is wanted in ENGLISH anyway — it is the
# industry's phrase and the visitor reads it in Latin on screen.
#
# So it is mapped to a Latin phonetic respelling instead, the same trick as "kaeosk",
# "methayn" and "klustur" above: doubling the vowel ("koold") is what forces the "oo",
# and keeping the "-d" as its own sounded ending preserves the participle. Each word
# stays ONE unbroken token — a hyphen reads as a break on this voice.
_LIQUID_COOLED_UR_RE = re.compile(
    r"(?:liquid[\s-]*cooled|لیکویڈ[\s-]*کولڈ|لیکوئڈ[\s-]*کولڈ)", re.I
)

# "clusters"/"cluster" is a technical term and is wanted in ENGLISH, said the English
# way, in both languages — it is the word the industry uses, and the visitor sees it in
# Latin on screen.
#
# The Urdu-script spelling was the first attempt and is what this rule now undoes.
# "کلسٹر" is a bare consonant run (ک-ل-س-ٹ-ر) with no vowel letter, which the voice ran
# together; respelling it as "کلاسٹر" added the missing vowel but added it in the wrong
# place, giving a long Urdu "aa" — "klaaster" — which is not how the word is said.
# Neither Urdu spelling can produce the English vowel, so both are mapped OUT, to the
# same Latin phonetic respelling used for "kaeosk" and "methayn" above: one unbroken
# Latin word, which is what makes this Urdu-first voice reach for English phonemes.
# "klustur"/"klusturz" spells the English short "u" that "cluster" actually has.
#
# Plural first: the singular pattern would otherwise match inside it and leave the
# trailing ز or s stranded, the same trap _SUBSIDIARY_RE hit on a malformed spelling.
_CLUSTERS_UR_RE = re.compile(r"(?:کلاسٹرز|کلسٹرز|\bclusters\b)", re.I)
_CLUSTER_UR_RE = re.compile(r"(?:کلاسٹر|کلسٹر|\bcluster\b)", re.I)

# "compatible" follows "NVIDIA-" in the corpus's own phrasing and is the other half of
# that modifier; left in Latin beside the Urdu-script vendor name it puts a script
# change mid-phrase, which is exactly what mis-vowels the Urdu voice.
_COMPATIBLE_RE = re.compile(r"\bcompatible\b", re.I)

# The persona's own two most-spoken phrases, for the SAME reason and by the same trick.
# In English mode the model writes them in Latin script and the Urdu-first voice applies
# English phonetics: "Maryam" comes out as the English "Mary-am" and "Assalamualaikum" as
# a flat "assa-lamu-a-LAY-kum" — an English speaker's attempt at both. Written in Urdu
# script the same voice reaches for Urdu phonemes and says them as a Pakistani speaker
# does. The visitor still READS the Latin spelling on screen; only the TTS payload changes.
_MARYAM = r"(?:Maryam|Mariam|Marium)"
# The male presenter's name, same treatment: Latin "Hamza" is said with an English "z"
# and a flat first vowel; حمزہ gets the Urdu ح and the right stress. Both names are
# rewritten in either language — the rig on screen decides which one the model wrote,
# so there is nothing to gate on here.
_HAMZA = r"(?:Hamza|Hamzah)"
# Every spelling of the salam the model actually writes: "Assalamualaikum" (what
# greetings.force_salam normalises the opener to), plus the hyphenated and spaced forms
# it uses mid-reply — "Assalam-o-Alaikum", "As-salamu alaykum", "Salam alaikum".
_SALAM = r"(?:as?[-\s]*)?salaa?m[ou]?[-\s]*(?:o[-\s]*)?a?l[ae][iy]kum"
# The returned salam, for the rare non-greeting turn where the model writes one anyway
# (greetings.force_salam rewrites the opener on greeting turns, so it never reaches here
# from there). Matched before _SALAM because the two overlap on the word "salam".
_WALAIKUM = r"w[ae]?[-\s]*a?l[ae][iy]kum[-\s,]*(?:as?[-\s]*)?salaa?m[ou]?"
# Mari Energies' own reports are full of initialisms and industry units that the voices
# either spell out wrongly or run together into a non-word, so they are written out too.
#
# This used to be one table applied to both languages, on the grounds that an Urdu reply
# keeps these in Latin script. It does — but handing Latin to an Urdu-first voice is the
# whole problem, not the solution: "M P C L" was read with English letter names dropped
# into an Urdu sentence, and an English expansion ("million standard cubic feet per day")
# was read as a run of English words. Both are wrong in Urdu for the same reason "CO2"
# was: the script decides the phonemes. So each entry now carries an Urdu spoken form as
# well, and the Urdu column is Urdu script throughout.
_ACRONYMS: dict[str, dict[str, str]] = {
    "MPCL": {"en": "M P C L", "ur": "ایم پی سی ایل"},
    "PSX": {"en": "P S X", "ur": "پی ایس ایکس"},
    "OGDCL": {"en": "O G D C L", "ur": "او جی ڈی سی ایل"},
    "MMBOE": {"en": "million barrels of oil equivalent",
              "ur": "ملین بیرل آئل ایکوی ویلنٹ"},
    "KBOEPD": {"en": "thousand barrels of oil equivalent per day",
               "ur": "ہزار بیرل آئل ایکوی ویلنٹ یومیہ"},
    "MMSCFD": {"en": "million standard cubic feet per day",
               "ur": "ملین اسٹینڈرڈ کیوبک فٹ یومیہ"},
    "MMSCF": {"en": "million standard cubic feet", "ur": "ملین اسٹینڈرڈ کیوبک فٹ"},
    "BSCF": {"en": "billion standard cubic feet", "ur": "بلین اسٹینڈرڈ کیوبک فٹ"},
    # The corpus quotes condensate in BOPD and total output in BOEPD; neither is a
    # word, and both sit beside the MMBOE/KBOEPD pair already expanded above.
    "BOEPD": {"en": "barrels of oil equivalent per day",
              "ur": "بیرل آئل ایکوی ویلنٹ یومیہ"},
    "BOPD": {"en": "barrels of oil per day", "ur": "بیرل تیل یومیہ"},
    "BBLs": {"en": "barrels", "ur": "بیرل"},
    "BBL": {"en": "barrel", "ur": "بیرل"},
    # A lease, not an initialism to letter-space: "Mari D&PL, Sindh". The ampersand
    # is what breaks it, exactly as in E&P below.
    "D&PL": {"en": "development and production lease",
             "ur": "ڈیولپمنٹ اینڈ پروڈکشن لیز"},
    # "sq km" stays ahead of the bare "km" below: _SAY_AS applies in insertion order,
    # so the longer form is consumed before "km" can match half of it.
    "sq km": {"en": "square kilometres", "ur": "مربع کلومیٹر"},
    "km": {"en": "kilometres", "ur": "کلومیٹر"},
    "GJ": {"en": "gigajoules", "ur": "گیگا جول"},
    "MT": {"en": "metric tons", "ur": "میٹرک ٹن"},
    "REE": {"en": "rare earth elements", "ur": "نایاب معدنی عناصر"},
    "TCF": {"en": "trillion cubic feet", "ur": "ٹریلین کیوبک فٹ"},
    "E&P": {"en": "exploration and production", "ur": "تلاش اور پیداوار"},
    "ESG": {"en": "E S G", "ur": "ای ایس جی"},
    "EPS": {"en": "earnings per share", "ur": "فی حصص آمدنی"},
    # "HR&R" is run together into "H9R" by the voice; splitting the ampersand out is
    # enough to fix it. Other initialisms in the corpus (SECP, ICAP, SNGPL, HSE) were
    # tested the same way and left alone in ENGLISH — letter-spacing them made the
    # English voice WORSE ("S N G P L" is heard as "S and GPL"). That finding is about
    # the English reading; in Urdu they are Latin script in an Urdu sentence, which is
    # the failure this table now exists to fix, so they carry an Urdu form below.
    "HR&R": {"en": "H R and R", "ur": "ایچ آر اینڈ آر"},
    # Urdu-only entries: the English column repeats the acronym unchanged, so the
    # measured English behaviour above is preserved exactly.
    "SNGPL": {"en": "SNGPL", "ur": "ایس این جی پی ایل"},
    "SSGCL": {"en": "SSGCL", "ur": "ایس ایس جی سی ایل"},
    "SECP": {"en": "SECP", "ur": "ایس ای سی پی"},
    "ICAP": {"en": "ICAP", "ur": "آئی سی اے پی"},
    "HSE": {"en": "HSE", "ur": "ایچ ایس ای"},
    "CEO": {"en": "CEO", "ur": "سی ای او"},
    "CFO": {"en": "CFO", "ur": "سی ایف او"},
    "COO": {"en": "COO", "ur": "سی او او"},
    "MD": {"en": "MD", "ur": "ایم ڈی"},
    "AGM": {"en": "AGM", "ur": "اے جی ایم"},
    "EGM": {"en": "EGM", "ur": "ای جی ایم"},
    "GHG": {"en": "GHG", "ur": "گرین ہاؤس گیسیں"},
    "LNG": {"en": "LNG", "ur": "ایل این جی"},
    "LPG": {"en": "LPG", "ur": "ایل پی جی"},
    "CSR": {"en": "CSR", "ur": "سی ایس آر"},
    "IFRS": {"en": "IFRS", "ur": "آئی ایف آر ایس"},
    "ISO": {"en": "ISO", "ur": "آئی ایس او"},
    "PKR": {"en": "PKR", "ur": "پاکستانی روپے"},
    "USD": {"en": "USD", "ur": "امریکی ڈالر"},
    "AI": {"en": "AI", "ur": "اے آئی"},
    # "AI/ML" is the corpus's phrasing in §3.1.3.3. The slash rules split the pair, but
    # only "AI" had an entry — "ML" fell through as bare Latin and the Urdu-first voice
    # read the two letters as a non-word instead of naming them.
    "ML": {"en": "ML", "ur": "ایم ایل"},
    "IT": {"en": "IT", "ur": "آئی ٹی"},
    "HR": {"en": "HR", "ur": "ایچ آر"},
    # A timezone beside office hours: "5:00 PM (PKT)" read as a word, not letters.
    # The English form deliberately avoids the word "Pakistan": the places pass runs
    # after this one and would respell it, leaving "پاکستان Standard Time" — Urdu
    # script stranded inside an otherwise English phrase.
    "PKT": {"en": "local time", "ur": "پاکستانی وقت"},
    # Site and facility initialisms the corpus uses without ever expanding them in the
    # same sentence, so the visitor hears letters with nothing to attach them to.
    "SGPC": {"en": "S G P C", "ur": "ایس جی پی سی"},
    "MSPC": {"en": "M S P C", "ur": "ایم ایس پی سی"},
    "MKDP": {"en": "M K D P", "ur": "ایم کے ڈی پی"},
    # Letters, not an expansion. The model habitually writes the full title and then
    # the acronym in brackets — "سپلائی چین مینجمنٹ (SCM)" — and expanding the bracket
    # said the same three words twice in a breath. Reading the letters is what the
    # bracket is for, and it is what a speaker does.
    "SCM": {"en": "S C M", "ur": "ایس سی ایم"},
    "PQ": {"en": "P Q", "ur": "پی کیو"},
    "JV": {"en": "joint venture", "ur": "جوائنٹ وینچر"},
    "ERP": {"en": "E R P", "ur": "ای آر پی"},
    "SAP": {"en": "SAP", "ur": "ایس اے پی"},
    "CPU": {"en": "C P U", "ur": "سی پی یو"},
    # Plurals before their singulars: these rules apply in insertion order and are
    # anchored with \b on both sides, so a bare "GPU" entry cannot match inside "GPUs"
    # — the trailing "s" leaves no boundary after the "U". Without the plural entry the
    # acronym fell through unspaced and the voice ran it into a non-word. The corpus
    # writes both forms in §3.1.3.3 ("GPU clusters", "Huawei Ascend NPUs").
    "GPUs": {"en": "G P Us", "ur": "جی پی یوز"},
    "GPU": {"en": "G P U", "ur": "جی پی یو"},
    # Huawei's AI accelerator: three letter names, not a word. The English column is
    # Urdu script for the same reason "Huawei" is (see _HUAWEI_SAID) — the kiosk runs
    # English through the SAME Uplift Urdu-first voice, and spaced Latin capitals are
    # not reliably read as letter NAMES by it: "N P U" came out as three separate
    # tokens, and the plural "N P Us" left a trailing "Us" that reads as the English
    # word "us" ("en pee us") instead of "U-s". Urdu script spells the letter names
    # themselves, so the voice says "en-pee-you" in either language.
    "NPUs": {"en": "این پی یوز", "ur": "این پی یوز"},
    "NPU": {"en": "این پی یو", "ur": "این پی یو"},
    "UNGC": {"en": "U N G C", "ur": "یو این جی سی"},
    "SDGs": {"en": "S D Gs", "ur": "ایس ڈی جیز"},
    "UN": {"en": "U N", "ur": "اقوام متحدہ"},
}

# ── English words the model transliterates into Urdu script ──────────
#
# The Urdu prompt forbids this (see system_prompt_urdu.md), but the model still does it
# intermittently, and an English word spelled in Urdu letters is exactly the case this
# voice reads worst: it takes its phonemes from the script, so "کاپر" comes out as a
# mangled non-word rather than "copper". Mapping the transliteration back to the Latin
# spelling is the same fix the _SAY_AS entries above use for گریڈ/ایتھ — this table just
# covers the words that come up in Mari Energies' own corpus.
#
# Deliberately NOT here: words with an ordinary Urdu equivalent the voice says well
# (سونا for gold), and abbreviations, which have their own table.
_TRANSLITERATED = {
    "کاپر": "copper",
    "گولڈ": "gold",
    "مائننگ": "mining",
    "منرلز": "Minerals",
    "انفراسٹرکچر": "infrastructure",
    "انفرا اسٹرکچر": "infrastructure",
    "ڈیٹا سینٹر": "data centre",
    "ڈیٹا سینٹرز": "data centres",
    "فرینڈلی": "friendly",
    "اسسٹنٹ": "assistant",
    "ریسیپشن": "reception",
    "ریسپشن": "reception",
    "پروڈکشن": "production",
    "ایکسپلوریشن": "exploration",
    "ٹیکنالوجیز": "Technologies",
    "سروسز": "Services",
    "انرجی": "Energy",
    "انرجیز": "Energies",
}
# Longest first, so "ڈیٹا سینٹرز" is matched before "ڈیٹا سینٹر" would consume its head.
_TRANSLITERATED_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(_TRANSLITERATED, key=len, reverse=True))
)


# The credit rating "A1" is a letter followed by a grade, not a quantity: the number
# spell-out below turns it into the non-word "Aone". Written apart, the voice says it
# correctly. "AAA" already reads fine on its own.
_RATING_RE = re.compile(r"\bA1\b")

# The corpus writes the scale word both ways — "PKR 65.14bn" and "PKR 2,291 Mn" — and
# the abbreviated form was passed straight through to the voice, which read "Mn" as two
# letters. Spelling it out here keeps both spellings on the one path.
_SCALE_WORDS = {
    "bn": {"en": "billion", "ur": "بلین"},
    "mn": {"en": "million", "ur": "ملین"},
    "tn": {"en": "trillion", "ur": "ٹریلین"},
    "billion": {"en": "billion", "ur": "بلین"},
    "million": {"en": "million", "ur": "ملین"},
    "trillion": {"en": "trillion", "ur": "ٹریلین"},
}


def _scale(word: str | None, lang: str = "en") -> str:
    """Normalise an optional scale word to its spoken form, with a trailing space.

    Urdu gets Urdu script for the same reason the acronym table does: an English scale
    word dropped into an Urdu sentence is read with English phonemes.
    """
    if not word:
        return ""
    said = _SCALE_WORDS.get(word.lower(), {}).get(lang, word.lower())
    return f"{said} "


_SAY_AS = (
    (re.compile(rf"(?<!\w){_SKY}\s*-?\s*{_47}(?!\w)", re.I), "Sky Forty Seven"),
    # Before the _MARI rule below: "Maryam" must be matched whole. (_MARI is
    # boundary-anchored on both sides, so it would not touch it, but the order says why.)
    (re.compile(rf"(?<!\w){_WALAIKUM}(?!\w)", re.I), "وعلیکم السلام"),
    (re.compile(rf"(?<!\w){_SALAM}(?!\w)", re.I), "السلام علیکم"),
    (re.compile(rf"(?<!\w){_MARYAM}(?!\w)"), "مریم"),
    (re.compile(rf"(?<!\w){_HAMZA}(?!\w)"), "حمزہ"),
    (re.compile(rf"(?<!\w){_LEAD}(?!\w)", re.I), "Lead"),
    (re.compile(rf"(?<!\w){_LISTED}(?!\w)", re.I), "Listed"),
    (re.compile(rf"(?<!\w){_INTERACTIVE}(?!\w)", re.I), "Interactive"),
    (re.compile(rf"(?<!\w){_CAPITALIZATION}(?!\w)", re.I), "Capitalization"),
    (re.compile(rf"(?<!\w){_VERTICALS_PL}(?!\w)", re.I), "verticals"),
    (re.compile(rf"(?<!\w){_VERTICAL_SG}(?!\w)", re.I), "vertical"),
    (re.compile(rf"(?<!\w){_SEISMIC}(?!\w)", re.I), "Seismic"),
    (re.compile(rf"(?<!\w){_EARTH}(?!\w)", re.I), "earth"),
    (re.compile(rf"(?<!\w){_GRADE}(?!\w)", re.I), "grade"),
    (re.compile(rf"(?<!\w){_CLOUD}(?!\w)", re.I), "Cloud"),
    (re.compile(rf"(?<!\w){_LIQUID_COOLED}(?!\w)", re.I), "liquid cooled"),
    # The corpus writes the brand closed up as "MariEnergies" 57 times against 6 for
    # the spaced form, and the rule below cannot see it: it is boundary-anchored, and
    # there is no boundary inside a camel-cased word. The result was one company said
    # two ways. Splitting on the capital lets the ڑ rule underneath reach both.
    (re.compile(r"(?<!\w)Mari(?=[A-Z])"), "ماڑی "),
    (re.compile(rf"(?<!\w){_MARI}(?!\w)"), "ماڑی"),
    (re.compile(rf"(?<!\w){_MARI_TICKER}(?!\w)"), "ماڑی"),
)

# The model sometimes writes an Urdu-script loanword immediately followed by its own
# Latin spelling in brackets — "ورٹیکلز (verticals)" — the same "full title then the
# acronym in brackets" habit as SCM below, but here the bracket is not an acronym, it
# is the very word the rules above are about to respell to Latin anyway. Left alone,
# the respelling turns that into "verticals (verticals)" and the voice says it twice.
# Matching each rule's own pattern immediately followed by a bracket holding its own
# replacement, and collapsing the whole thing to just the replacement, fixes any of
# them without a separate word list to keep in sync.
_DEDUPE_GLOSS = tuple(
    (re.compile(rf"{pattern.pattern}\s*\(\s*{re.escape(replacement)}\s*\)", pattern.flags),
     replacement)
    for pattern, replacement in _SAY_AS
)


def _drop_repeated_gloss(text: str) -> str:
    """Strip a Latin "(word)" that only repeats the loanword right before it."""
    for pattern, replacement in _DEDUPE_GLOSS:
        text = pattern.sub(replacement, text)
    return text

# Currency and the acronym table both depend on the language, which a static tuple of
# (pattern, replacement) pairs cannot see, so they are applied by _say_as_for() below
# rather than in _SAY_AS. Currency reads after the amount in both languages —
# "PKR 65 billion" → "65 billion rupees" / "65 بلین روپے".
_CURRENCY = (
    (re.compile(r"\b(?:PKR|Rs\.?)\s*([\d,.]+)\s*(billion|million|trillion|bn|mn|tn)?\b", re.I),
     {"en": "rupees", "ur": "روپے"}),
    (re.compile(r"\bUSD\s*([\d,.]+)\s*(billion|million|trillion|bn|mn|tn)?\b", re.I),
     {"en": "US dollars", "ur": "امریکی ڈالر"}),
)

_ACRONYM_RULES = tuple(
    (re.compile(rf"\b{re.escape(k)}\b"), v) for k, v in _ACRONYMS.items()
)


def _say_as_for(text: str, lang: str) -> str:
    """Apply the rules whose spoken form depends on the language."""
    key = "ur" if lang == "ur" else "en"
    # Currency first: the PKR/USD patterns consume the symbol along with its amount,
    # and the acronym entries for "PKR"/"USD" must not claim it before they do.
    for pattern, unit in _CURRENCY:
        text = pattern.sub(
            lambda m, u=unit[key]: f"{m.group(1)} {_scale(m.group(2), key)}{u}", text
        )
    text = _HUAWEI_RE.sub(_HUAWEI_SAID[key], text)
    text = _NVIDIA_RE.sub(
        lambda m, s=_NVIDIA_SAID[key]: f"{s} " if m.group(1) else s, text
    )
    for pattern, spoken in _ACRONYM_RULES:
        text = pattern.sub(spoken[key], text)
    # After the acronym table, whose \b-anchored rules cannot reach a unit written
    # closed up against its number. See _KW_RE.
    text = _KW_RE.sub(_KW_SAID[key], text)
    if key == "ur":
        text = _KIOSK_RE.sub("kaeosk", text)
        text = _SUBSIDIARY_RE.sub("سب سِڈی ری", text)
        text = _COMPATIBLE_RE.sub("کمپیٹیبل", text)
        text = _LIQUID_COOLED_UR_RE.sub("likwid koold", text)
        text = _CLUSTERS_UR_RE.sub("klusturz", text)
        text = _CLUSTER_UR_RE.sub("klustur", text)
        text = _METHANE_RE.sub("methayn", text)
    return text

# Uplift's voice is Urdu-first and reads bare digits in Urdu — "65" becomes "پینسٹھ" even
# in an otherwise English sentence, which is wrong in the kiosk's English mode. The voice
# takes its cue from the script, so the digits are written out as English words before an
# English reply is sent. Urdu replies keep their digits: there the Urdu reading is correct.
_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_SCALES = ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand"))


def _say_int(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else "")
    if n < 1000:
        return f"{_ONES[n // 100]} hundred" + (f" and {_say_int(n % 100)}" if n % 100 else "")
    for value, name in _SCALES:
        if n >= value:
            head = f"{_say_int(n // value)} {name}"
            return head + (f" {_say_int(n % value)}" if n % value else "")
    return str(n)


def _say_number(match: re.Match[str]) -> str:
    whole, frac = match.group(1).replace(",", ""), match.group(2)
    try:
        said = _say_int(int(whole))
    except (ValueError, IndexError):
        return match.group(0)
    if frac:
        # "54.25" is read "fifty four point two five", digit by digit after the point
        said += " point " + " ".join(_ONES[int(d)] for d in frac)
    return said


# Digit runs that are identifiers rather than quantities — phone numbers, postcodes,
# well names — are read digit by digit; saying "one hundred and eleven" for a dialling
# code is worse than not touching it. Anything attached to a hyphen or another digit
# group is treated as an identifier and left for the voice to read as characters.
_PHONE = re.compile(r"(?:\+?\d[\d\s-]{6,}\d)")
_DIGITS = {str(i): w for i, w in enumerate(_ONES[:10])}


def _say_digits(match: re.Match[str]) -> str:
    return " ".join(_DIGITS.get(ch, ch) for ch in match.group(0) if ch.isdigit() or ch == "+")


# Years read naturally ("nineteen fifty four"), not as a count ("one thousand nine...").
# Round centuries are excluded: "2000" is "two thousand", not "twenty hundred".
_YEAR = re.compile(r"(?<![\d.])(1[89]|20)(\d{2})\b(?!\.\d)")
# A number not glued to a hyphen or decimal point on either side is a real quantity.
_NUMBER = re.compile(r"(?<![\d.])(\d[\d,]*)(?:\.(\d+))?\b(?!\.\d)")


def _say_year(match: re.Match[str]) -> str:
    century, rest = int(match.group(1)), int(match.group(2))
    if rest == 0:
        # 1900 / 2000 are said as counts, not as "nineteen hundred"-style year pairs
        return _say_int(century * 100)
    return f"{_say_int(century)} {'oh ' + _ONES[rest] if rest < 10 else _say_int(rest)}"


def _spell_numbers(text: str) -> str:
    text = _PHONE.sub(_say_digits, text)
    text = _YEAR.sub(_say_year, text)
    return _NUMBER.sub(_say_number, text)


def _spoken(text: str, lang: str = "en") -> str:
    """Rewrite a reply the way it should be *said* rather than read."""
    # Domains come FIRST: "sky47.com.pk" has to be seen whole, before the Sky47 rule in
    # _SAY_AS rewrites its label and leaves the dots behind unsaid.
    text = _spoken_urls(text, lang)
    text = _drop_repeated_gloss(text)
    # "rare earth elements" and "methane mitigation" are deliberately left exactly as
    # written: measured against the live voice, plain text is what it says correctly,
    # and every inserted stop made both the pause and the pronunciation worse. Only the
    # corpus's hyphen is normalised, since a hyphen mid-word reads as a break.
    text = _FOOD_GRADE_HYPHEN_RE.sub("food grade", text)
    text = _INFRASTRUCTURE_SPLIT_RE.sub("انفراسٹرکچر", text)
    # Before the two single-word rules below, which would otherwise leave this phrase
    # half in Latin and half in Urdu script. Urdu only: in English mode both words are
    # already plain Latin and read correctly.
    if lang == "ur":
        text = _METHANE_MITIGATION_RE.sub("methayn mitigation", text)
    text = _MITIGATION_RE.sub("مٹی گیشن", text)
    # Undo any English word the model wrote in Urdu letters, in BOTH languages: an Urdu
    # reply legitimately contains English terms, and they belong in Latin script for the
    # voice either way.
    text = _TRANSLITERATED_RE.sub(lambda m: _TRANSLITERATED[m.group(0)], text)
    for pattern, replacement in _SAY_AS:
        text = pattern.sub(replacement, text)
    # Currency and initialisms, whose spoken form differs by language.
    text = _say_as_for(text, lang)
    # Names, ranks and honours, in BOTH languages: the Urdu-first voice mangles
    # Latin-script Pakistani names ("Anwar Ali Hyder" → "and were early hired") and
    # abbreviated ranks ("Lt. Gen." → "Leftenant"). Runs before the number spell-out
    # so a rank's own digits, if any, are still handled below.
    text = _spoken_names_and_ranks(text, lang)
    # Addresses, contact lines, chemical formulae and symbol-bearing abbreviations.
    # Must precede the number spell-out below: a postcode, an Islamabad sector and the
    # "2" in CO2 are identifiers, and that pass would turn them into quantities
    # ("forty four thousand", "G-ten/four", "COtwo").
    text = _spoken_addresses(text, lang)
    # Re-applied: the address pass just expanded "CH4" to "میتھین" via its own formula
    # table, which is the same word the pre-address pass above already tried to catch —
    # so a reply that writes methane as the chemical formula rather than the English
    # word slipped past the first pass and needs this second look.
    if lang == "ur":
        # Phrase first, for the same reason as the pass above: the address expansion may
        # have just put "میتھین" back in front of an Urdu-script "mitigation".
        text = _METHANE_MITIGATION_RE.sub("methayn mitigation", text)
        text = _METHANE_RE.sub("methayn", text)
    # Report formats and symbols, in BOTH languages: fiscal years, DD/MM/YYYY dates,
    # ratio multiples, well identifiers, ~ − §. Runs AFTER addresses, which claims the
    # identifier shapes it owns ("G-10/4" would otherwise match the well-name rule),
    # and before the spell-out below, which would read a well number or a date part as
    # a quantity. See voice_config/urdu_normalise.py.
    text = _spoken_formats(text, lang)
    # English-only: percent, word/word slashes, clock times, "Ltd", "w.e.f.". Urdu
    # reaches none of these shapes. After the address pass, which owns "MD/CEO" and
    # the sectors — both slash-shaped — and before the spell-out, so that a "%" is
    # already the word "percent" when its number is read.
    text = _normalise_for_english(text, lang)
    # Urdu- and Pashto-origin place, field and programme names, in both languages.
    # AFTER the formats pass on purpose: that pass splits a well identifier
    # ("Spinwam-1" → "Spinwam 1"), and its rule needs a Latin letter before the
    # hyphen, which a name already respelled into Urdu script would no longer have.
    text = _spoken_places(text, lang)
    text = _RATING_RE.sub("A one", text)
    if lang != "ur":
        text = _spell_numbers(text)
    # Urdu-only fixes for what the Uplift voice gets wrong on its own — Roman numerals,
    # word/word slashes and bare URLs. Runs last so it sees the fully rewritten text.
    # See voice_config/urdu_normalise.py for why it is this short.
    return _normalise_for_uplift(text, lang)


class UpliftTTS(TTSProvider):
    """UpliftAI REST synthesis. Handles Urdu and English with the same voice."""

    def __init__(
        self,
        api_key: str = "",
        base: str = "",
        path: str = "",
        voice: str = "",
        output_format: str = "",
        speed: float = 1.0,
        lang: str = "ur",
    ):
        self.api_key = api_key or C.UPLIFT_KEY
        self.base = (base or C.UPLIFT_BASE).rstrip("/")
        self.path = path or C.UPLIFT_PATH
        self.voice = voice or C.UPLIFT_VOICE
        self.output_format = output_format or C.UPLIFT_FORMAT
        # 1.0 is the signature default, so "caller did not ask" means "use the
        # configured rate"; an explicit speed still wins. The configured rate is
        # per-language: English runs slower than Urdu (C.UPLIFT_SPEED_EN vs
        # C.UPLIFT_SPEED) because the receptionist persona reads English prose at a
        # brisk clip that lands as rushed. Resolved here rather than at the call site
        # so every entrypoint — server/app.py and the s2s handler — gets the right
        # default from the language it already passes.
        self.lang = lang
        self.speed = speed if speed != 1.0 else (
            C.UPLIFT_SPEED_EN if lang == "en" else C.UPLIFT_SPEED
        )

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        text = (text or "").strip()
        if not text:
            return b"", "audio/mpeg"
        path = self.path if self.path.startswith("/") else f"/{self.path}"
        url = f"{self.base}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "voiceId": self.voice,
            "text": _spoken(text, self.lang),
            "speed": self.speed,
            "outputFormat": self.output_format,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            mime = r.headers.get("content-type", "audio/mpeg").split(";")[0]
            return r.content, mime or "audio/mpeg"


class KokoroLocalTTS(TTSProvider):
    """In-process Kokoro pipeline (GPU if available)."""

    _pipe = None  # class-level cache: one pipeline instance per process

    def __init__(self, voice: str = ""):
        self.voice = voice or C.VOICE_EN

    def _get_pipe(self):
        if KokoroLocalTTS._pipe is None:
            from kokoro import KPipeline

            KokoroLocalTTS._pipe = KPipeline(lang_code="a")  # 'a' = American English
        return KokoroLocalTTS._pipe

    def warm(self) -> None:
        self._get_pipe()

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        import io

        import numpy as np
        import soundfile as sf

        text = (text or "").strip()
        if not text:
            return b"", "audio/wav"
        pipe = self._get_pipe()

        def run() -> tuple[bytes, str]:
            parts = []
            for _, _, audio in pipe(text, voice=self.voice):
                if hasattr(audio, "detach"):
                    audio = audio.detach().cpu().numpy()
                parts.append(np.asarray(audio, dtype=np.float32).reshape(-1))
            if not parts:
                return b"", "audio/wav"
            buf = io.BytesIO()
            sf.write(buf, np.concatenate(parts), 24000, format="WAV", subtype="PCM_16")
            return buf.getvalue(), "audio/wav"

        return await asyncio.to_thread(run)


class KokoroRemoteTTS(TTSProvider):
    def __init__(self, base: str = "", path: str = "", token: str = "", model: str = "", voice: str = "", fmt: str = ""):
        self.base = (base or C.KOKORO_BASE).rstrip("/")
        self.path = path or C.KOKORO_PATH
        self.token = token or C.KOKORO_TOKEN
        self.model = model or C.KOKORO_MODEL
        self.voice = voice or C.VOICE_EN
        self.fmt = fmt or C.KOKORO_FORMAT

    async def synthesize(self, text: str) -> tuple[bytes, str]:
        text = (text or "").strip()
        if not text:
            return b"", "audio/mpeg"
        url = f"{self.base}{self.path}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = {"model": self.model, "input": text, "voice": self.voice, "response_format": self.fmt}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            mime = r.headers.get("content-type", "audio/mpeg").split(";")[0]
            return r.content, mime or "audio/mpeg"


# ─────────────────────────── selection + dispatch ────────────────────
_tts_cache: dict[str, TTSProvider] = {}


def get_tts_provider(lang: str, avatar: str = "female") -> TTSProvider:
    """Return the configured TTS adapter for a language and presenter (cached —
    local-model adapters keep their loaded pipeline across calls).

    ``avatar`` picks the voice, not the engine: the male rig speaks in
    UPLIFT_VOICE_MALE and every other rig in the language's usual voice. It is
    part of the cache key because two presenters are two adapters with two
    different voice ids, and one must not be handed out for the other.

    Only the Uplift paths vary by presenter. Kokoro has one configured voice per
    language here, so a male rig on a Kokoro deployment sounds as it always did
    rather than silently failing to find a voice that was never set up.
    """
    male = avatar == "male"
    key = f"{lang}:{C.EN_TTS if lang != 'ur' else 'uplift'}:{'male' if male else 'female'}"
    if key not in _tts_cache:
        if lang == "ur":
            _tts_cache[key] = UpliftTTS(voice=C.UPLIFT_VOICE_MALE if male else C.UPLIFT_VOICE)
        elif C.EN_TTS == "uplift":
            # No Kokoro deployment right now — English goes out through Uplift too.
            # The male voice covers both languages; there is no separate male
            # English id, and the Uplift voices are not language-specific.
            _tts_cache[key] = UpliftTTS(
                voice=C.UPLIFT_VOICE_MALE if male else C.UPLIFT_VOICE_EN, lang="en"
            )
        else:
            _tts_cache[key] = KokoroLocalTTS() if C.EN_TTS == "local" else KokoroRemoteTTS()
    return _tts_cache[key]


async def tts(text: str, lang: str, avatar: str = "female") -> tuple[bytes, str]:
    return await get_tts_provider(lang, avatar).synthesize(text)
