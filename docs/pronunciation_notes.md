# Pronunciation notes

The evidence behind the rules in `server/normalization.py`: what the Uplift voice said
before each rule, and what was tried and rejected. The code keeps a one-line *why*; the
measurements live here.

Before adding a rule, check the engine actually needs it: synthesize the phrase and
transcribe it back (Uplift TTS → Soniox STT). Re-normalising something Uplift already
says correctly is how this kind of module regresses.

## Why the normalizer is so short

The reference implementation this was adapted from targeted MMS-TTS/ElevenLabs, which
could not read Western digits inside an Urdu sentence, so most of it converted digits to
Urdu words.

**Uplift does not need that.** Round-tripping the live voice (Uplift TTS → Soniox STT)
shows it already handles digits, decimals, percentages, `24/7`, years and phone numbers
— `127` and `ایک سو ستائیس` synthesise to the same audio. Porting the converter would
have duplicated the engine and fought the English number spell-out in
`server/normalization.py`, which exists for the opposite reason.

The same round trip found three things Uplift genuinely gets wrong, all present in the
knowledge base. Those, and only those, are what the Urdu-only section fixes:

| Input | Uplift says | After the fix |
|---|---|---|
| `Tier III` | ٹی آئی آئی لائیو (letter by letter) | ٹیئر 3 |
| `تیل/گیس` | تیل **سلیش** گیس | تیل **اور** گیس |
| `marienergies.com.pk` | میری مرضی کامپی کے | ماڑی انرجیز ڈاٹ کام ڈاٹ پی کے |

Before adding a rule, check the engine actually needs it — synthesize the phrase and
transcribe it back. Re-normalising something Uplift already says correctly is how this
kind of module regresses.

## Report formats and symbols

The *Report formats, dates and symbols* section, unlike the three fixes
above it runs in **both** languages: these are structural failures, not phonetic ones,
so they break the same way in either voice. Each was reproduced against the shapes that
actually occur in `server/data/mari_energies_knowledge_base.md`:

| Written | Was said | Now |
|---|---|---|
| `FY2024-25` (18×) | "FY**twenty twenty four**" — label glued to the year | financial year 2024 to 25 |
| `24/06/2022` (17×) | "twenty four **slash** six" | 24 June 2022 |
| `2.81x` (9×) | "two point eight one **ex**" — no rule fired at all | 2.81 times |
| `2017-2020` | "two zero one seven…" — read as a **dialling code** | twenty seventeen to twenty twenty |
| `Karakoram-01` | "Karakoram-**one**" — leading zero dropped | Karakoram zero one |
| `93,000–113,000` | en-dash silent | 93,000 to 113,000 |
| `~`, `−` (U+2212), `§` | dropped, or read as a dash | approximately / minus / section |
| `PKR 2,291 Mn` | "…two hundred and ninety one **M N**" | …million rupees |

Every rule leaves the **digits in place** rather than writing them out, so the English
spell-out still does the reading and an Urdu reply keeps the digits Uplift already says
correctly. Two ordering constraints hold it together, both for the same reason the
address pass exists — *identifiers are not quantities*:

1. It runs **after** `spoken_addresses`, which claims the identifier shapes it owns
   first. The Islamabad sector `G-10/4` would otherwise be eaten by the well-name rule.
2. It runs **before** the number spell-out, which would read a well number, a date part
   or a year range as a quantity.

Rules are anchored to their own shape so the near-misses survive: a digit *before* the
hyphen is a measurement (`20-year`, `18-inch`), a numeric slash is a ratio (`24/7`,
`2024/25`), and a 4-digit year followed by four more digits is a span, not a fiscal pair.

## What only English gets wrong

The *English-only* section is the mirror of the Urdu-only pass: shapes an Urdu reply never
contains, plus the ones Uplift already reads correctly in Urdu and would only be made
worse by touching. All measured against the same corpus:

| Written | Was said | Now |
|---|---|---|
| `33%` (33×) | "thirty three" — then silence | thirty three percent |
| `AI/ML`, `water/gas` (65 slashes) | "AI **slash** ML" | AI and ML |
| `Ltd` (19×), `Pvt` (12×) | "L T D", "P V T" | Limited, Private |
| `9:00 AM` (12 times) | "nine **colon zero** AM" | nine AM |
| `0.24:99.76` | colon read out | 0.24 **to** 99.76 |
| `w.e.f.` (4×), `e.g.`, `vs.`, `No:` | letter soup | with effect from, for example, versus, number |
| `24/7` | "twenty four **slash** seven" | twenty four seven |
| `MariEnergies` (57×) | missed the ڑ that `Mari Energies` (6×) got | ماڑی Energies |

The last one is a consistency fix rather than a new opinion: the ڑ rule is
boundary-anchored, and there is no boundary inside a camel-cased word, so the brand was
being said two different ways depending on which spelling the model happened to write.

Ordering is the same shape as the formats pass — **after** `spoken_addresses`, which
owns the slash-shaped `MD/CEO` and the Islamabad sectors, and **before** the number
spell-out, so a `%` is already the word "percent" when its number is read. Two bounds
keep the rules from colliding: minutes are `[0-5]\d`, without which the time rule ate
the `24:99` inside the debt ratio, and the colon-ratio rule requires decimals on both
sides, which is what leaves `ISO 9001:2015` alone.

### What was deliberately left alone

`%`, `24/7` and dates are **not** normalised in Urdu. The round trip recorded above
found Uplift reads all three correctly in an Urdu sentence, and rewriting them there
would be exactly the regression this file keeps warning about. `ISO 9001:2015`, `2P`
and `2C` reserves, `&` in company names and the em-dash were all checked and left: they
already read acceptably, and no rule earns its place without a failure behind it.

### Why this is not `prompt related/urdu_normalised.py`

That file is **not** an earlier, richer version of this one. It belonged to the Sky47
kiosk and targeted MMS-TTS/ElevenLabs, and most of its 1,246 lines do not apply here:

- **~200 lines** convert digits to Urdu words, which Uplift does not need and which
  would fight the English number spell-out in `server/normalization.py`.
- **~100 abbreviations** cover NVIDIA, Kubernetes, SaaS/DRaaS, DCIM and colocation.
  Sky47 is a Mari subsidiary, but **none of those terms occur in this knowledge base**,
  and the persona may only state what the knowledge base contains.
- `_WRONG_CHAIRMAN_RE` rewrites "Faheem Haider" to "Anwar Ali Haider". Faheem Haider is
  MariEnergies' MD/CEO and appears 5× in this corpus; porting that rule would corrupt
  correct facts.

What was worth taking from it is the *shape* of the problem — identifiers, dates and
symbols need handling that a digit reader does not provide — measured again against
this corpus. That is what the table above is.

## Why the glossary filters so aggressively

Retrieval ranks whole chunks, so an abbreviation used in a dozen chunks but spelled out
in one may never reach the model. The glossary force-injects the definition.

This knowledge base is an annual-report export, where parentheses are used far more for
asides than for definitions. The reference extractor produced entries like
`EPS = restated`, `OGDCL = 20%` and `GJ = 2024: 4,344,223 GJ` — injected as
*authoritative*, those would cause confidently wrong answers. `_is_plausible_definition`
rejects them: no digits, at least two words, and initials that line up with the
abbreviation. That takes 62 raw candidates down to 40 clean ones.

## Why names are a lookup table, not a rule

One Urdu-first voice serves both languages, and it reads Latin script with English
phonetics. On Pakistani names that is not an accent — it is the wrong name:

| Knowledge-base text | Voice said | Now |
|---|---|---|
| `Lt. Gen. Anwar Ali Hyder, HI(M), (Retd)` | "Lifting in general and more early hike spread" | Retired Lieutenant General انور علی حیدر |
| `Syed Bakhtiyar Kazmi` | "Sit back, ER Kazmi" | سید بختیار کاظمی |
| `Abid Niaz Hasan` | "David Nais Hassan" | عابد نیاز حسن |
| `Muhammad Aamir Salim` | "Mehmet Amir Selim" | محمد عامر سلیم |
| `Brig ... (Retd)` | "We're tired brigadiers ... Shea" | Retired Brigadier ... Sheikh |
| `MD/CEO` | "complete search seekie ko" | MD and CEO |

Writing the name in Urdu script makes the voice reach for Urdu phonemes and it comes out
right.

This was originally a *measured subset*: only names a round trip proved broken were
listed, and ten people were pinned as deliberately absent because Latin had come out
closer for them. **Listening to the deployed kiosk showed that was the wrong call** —
those ten were exactly the names still being mispronounced in English. The names table now
covers **every person in the corpus in both languages**, so which names get respelled
is no longer a judgement call that can be got wrong, and adding a person to the corpus
means adding one row.

The second half of the fix is that a full name is not enough. The table only matched a
whole name, but a spoken answer rarely repeats one:

| Reply says | Was said | Now |
|---|---|---|
| `Syed Bakhtiyar Kazmi chairs it` | سید بختیار کاظمی | سید بختیار کاظمی |
| `Kazmi chairs it` | **"Kazmi", untouched** | کاظمی |
| `Ask Faheem about it` | **"Faheem", untouched** | فہیم |

So the same person was said correctly in one sentence and mangled in the next.
`_WORD_FORMS` gives each name word its own spoken form, applied after the full-name
pass and filtered by the words that actually occur in the tables — one source of truth,
so the two cannot drift apart. `Ali`, `Khan` and `Malik` are blocklisted from that
per-word pass: they appear outside a person's name often enough that matching them
would fire on unrelated sentences, and the full-name pass still covers them.

Ranks and honours are rules rather than a table, because there the failure is
abbreviation, not phonetics: `Lt. Gen.` → "Leftenant"/"Eldeej" and `(Retd)` → "Grade",
but the spelled-out words are said correctly. `HI(M)` reads as "HIV" or "a type M", and
the Latin "Hilal-e-Imtiaz" fares no better ("Hello team, here's Mummy Tree"), so it was
once dropped from speech. It is now said in full, because the Urdu spelling works:

| Written | Round trip |
|---|---|
| `ہلال امتیاز ملٹری` | "Hilal Imtiaz Military" — the izafat is lost |
| `ہلالِ امتیاز ملٹری` | "Hilal M. Tayyaz" — the zer diacritic breaks the word |
| `ہلالے امتیاز ملٹری` | **"Hilal-e-Imtiaz Military"**, in both voices |

`SI`, `TI` and `NI` follow the same pattern. The honour sits between the name and
`(Retd)` in the corpus, so the suffix is lifted in front of it first and the rank rules
still see "name (Retd)". The model also writes the whole line in Urdu script —
`ایچ آئی (ایم)، (ریٹائرڈ)` — which used to lose the "retired" entirely.

### What was tried and rejected

Letter-spacing the other initialisms (`SECP`, `ICAP`, `SNGPL`, `HSE`) made the voice
**worse**, not better — `S N G P L` is heard as "S and GPL". `HR&R` (run together as
"H9R") and the credit rating `A1` (glued into the non-word "Aone" by the number
spell-out) were changed. Leaving the rest in Latin turned out to be wrong too; see
*Every other initialism* below.

## Initialisms, formulae and ranks in Urdu

The tables above were built around the English voice, and one assumption ran through
all of them: an Urdu reply keeps initialisms in Latin script, so the same spoken form
can serve both languages. That assumption was backwards. **Handing Latin script to an
Urdu-first voice is the failure, not the fix** — it is the same finding as `ماڑی` and
the names table, applied to everything else.

The clearest case was `CO₂`. Spacing it to `C O 2` fixed the English readings, but in
Urdu the voice said the Latin letters in English and then the digit in Urdu — **"C-O-do"**.
A formula is a compound with a name, so it is now named per language, which fixes the
English reading at the same time (nobody says "C O two" out loud either):

| Written | Was said | English | Urdu |
|---|---|---|---|
| `CO₂` | "C-O-do" | carbon dioxide | کاربن ڈائی آکسائیڈ |
| `CH4`, `H2S`, `SO2`, `N2`, `N2O` | letters + digit | methane, hydrogen sulphide … | میتھین، ہائیڈروجن سلفائیڈ … |

`_ACRONYMS` is now a **per-language table** for the same
reason. The English column is unchanged — every measured English finding is preserved
verbatim, including the decision to leave `SNGPL`, `SECP`, `ICAP` and `HSE` alone,
which was a finding about the *English* reading. The Urdu column is Urdu script
throughout:

| | English (unchanged) | Urdu (new) |
|---|---|---|
| `MPCL` | M P C L | ایم پی سی ایل |
| `MMSCFD` | million standard cubic feet per day | ملین اسٹینڈرڈ کیوبک فٹ یومیہ |
| `EPS` | earnings per share | فی حصص آمدنی |
| `SNGPL` | *(left alone)* | ایس این جی پی ایل |
| `PKR 65bn` | 65 billion rupees | 65 بلین روپے |

Two consequences worth knowing:

- **`MD/CEO` in Urdu is now «ایم ڈی اور سی ای او».** The hyphenated `M-D and C-E-O`
  was an English fix — it makes an English voice read the letters apart. In Urdu the
  Urdu spelling needs no such trick, and the Latin letters were the problem.
- **Currency scale words follow the language too**, so an Urdu reply no longer ends a
  figure with the English word "rupees".

### Ranks

`Col`, `Capt`, `Maj` and a bare `Lt` existed only in the English table, so in Urdu they
stayed Latin — the same failure again. Every rank now has a form in both languages,
plus `Brigadier General` and `Lieutenant Colonel`, and the spelled-out English forms
are matched in Urdu mode because the model writes those when asked for a title in full.

Two ordering rules hold it together, both pinned in `tests/test_names_and_ranks.py`:
the two-word ranks are matched **before** their own first half, or a bare `Lt` claims
half of `Lt Gen` and strands `Gen`; and any rank added to the tables must also be added
to the rank-name alternation used by the `(Retd)` lift-and-reattach, or the suffix is
silently dropped.

## Places, fields and programme names

The people table covers the people. Everything else Urdu- or Pashto-origin in the corpus —
gas fields, districts, formations, wells and the CSR programme names — had **no
coverage at all**, in either language, and the corpus is 100% Latin script, so the
Urdu-first voice read every one of them with English phonetics:

| Written | Count | Now |
|---|---|---|
| `Fauji` (the majority shareholder) | 25× | فوجی |
| `Daharki` | 13× | ڈھرکی |
| `Waziristan` | 12× | وزیرستان |
| `Sujawal`, `Ghazij`, `Shewa` | 7× each | سجاول, غازیج, شیوہ |
| `Spinwam`, `Sui` | 5× each | سپین وام, سوئی |
| `Kissan Dost`, `Dastarkhwan`, `Roshan Mustaqbil` | CSR programmes | کسان دوست, دسترخوان, روشن مستقبل |

Unlike the names table originally, this is **one table applied in both languages**. A person's name
needed a per-language split because the round trip found some better in Latin; a
toponym has no such split — the Urdu spelling is what the word *is*, and it is right in
an English sentence and an Urdu one alike. `Dastarkhwan` is spelled two ways in the
corpus (§12.5.4 vs §14.3.2) and both map to the one spoken form.

It runs **after** the formats pass, because that pass splits a well identifier
(`Spinwam-1` → `Spinwam 1`) with a rule that needs a Latin letter before the hyphen —
a name already respelled into Urdu script would no longer have one, and the hyphen
would survive unspoken.

### Familiarity is not pronunciation

The first version of this table held back every name a reader would recognise —
`Islamabad`, `Karachi`, `Sindh`, `Balochistan`, `Karakoram` — on the grounds that an
English voice "already handles" them. That was too broad: the engine applies English
phonetics to Latin script whether or not the word is famous, so `Karakoram` was mangled
exactly like `Sujawal`. Recognisability alone is not the test.

**`Pakistan` is the one name here that must stay in the Latin alphabet**, and it took
three attempts to land on why. It was first respelled with the rest, then pulled on the
theory that an ordinary English word needs no help, then respelled again when the
request turned out to be about *accent* rather than mispronunciation. All three missed
the actual constraint, which only round-tripping the word exposes:

| Written | Voice said |
|---|---|
| `Pakistan` | correct, but in an English accent |
| `پاکستان` | "pakesten" — and sometimes the Urdu letters read out one at a time |
| `Paakistaan` | the Pakistani vowels, reliably |

The `ماڑی` trick — hand the Urdu-first voice Urdu letters and it reaches for Pakistani
phonemes — works on most names in this table and fails on this one. A Latin respelling
lengthens the two /aː/ vowels the way a Pakistani speaker does while staying in the
alphabet this voice reads reliably. **Urdu script is a means to an accent here, not the
goal**; when it does not produce one, the accent is still available another way.

`Indus` is a different case, and stays out entirely: the entry it once had (`سندھ دریا`)
was not a respelling of "Indus" at all, it was the *translation* "the Sindh river" — a
different name, not an accent. See the table below.

The test for everything in this section, `Pakistan` included, is **what the entry
actually does**: change how a name sounds — never translate it into a different name,
and never respell an ordinary word for no reason beyond "it could be." Measured
intent wins over a blanket rule, which is the lesson the names table records.

Two further entries were removed as outright errors rather than style calls, because
they replaced a name with a *different word*:

| Was | Why it was wrong |
|---|---|
| `Indus` → سندھ دریا | a translation, "the Sindh river" — not a way of saying "Indus" |
| `Cantt` → چھاؤنی | the Urdu *word* for cantonment; changes what the address says |
| `Maroc` → مراکش | that is Morocco; the company is "Pakistan Maroc Phosphate" |

**This table changes how a name sounds, never which name is said.**

Also deliberately absent, on the separate ground that they are not Urdu at all:
`Lockhart` (a formation named after a Briton), `Neptune`, `Miyawaki`, `Chevening`,
`Dundee`, `Wolverhampton`.

### Phrases and their parts

Multiword keys match only as a whole phrase, and a reply does not always give one — it
says "the Kot formation", "the Dost scheme", or splits `Reko Diq` across a clause. Each
component word therefore has its own entry, with longest-first matching so the phrase
still wins when the whole phrase is present:

| Reply says | Was said | Now |
|---|---|---|
| `The Mughal Kot Sst formation` | مغل کوٹ ✓ | مغل کوٹ |
| `The Kot formation` | **"Kot", untouched** | کوٹ |
| `The Dost scheme` | **"Dost", untouched** | دوست |

`tests/test_places.py` closes this with a **sweep of the whole knowledge base** rather
than a spot check: every capitalised token that is not an English dictionary word, an
abbreviation owned by another pass, or a genuinely foreign name must reach the voice in
Urdu script. A new local name in the corpus fails that test until it is added here.

`Indus` is the one that needs whole-word anchoring for a different reason: it is a
substring of "industry" and "industrial", which occur far more often than the basin.

> **Not round-tripped.** Unlike every other table here, these entries were built from
> the corpus rather than from Uplift → Soniox verification, after the kiosk was
> reported mispronouncing English-mode names. The spellings are conventional, so the
> risk is a wrong vowel rather than a wrong word — but anything a round trip shows was
> already correct in Latin should be deleted, exactly as the names notes above say.

## Addresses, formulae and symbol abbreviations

All measured the same way — round trip the live voice, keep only what came back right:

| Written | Voice said | Now |
|---|---|---|
| `CO₂` / `CO2` | "seagull dough" / "COtwo" / **"C-O-do" (ur)** | carbon dioxide / کاربن ڈائی آکسائیڈ |
| `E&P` | "ENP" (en), "ایم ای این پی" (ur) | exploration and production |
| `MD/CEO` | "MD/C8 August" | M-D and C-E-O (heard as "MD and CEO") |
| `Ext. 483` | "x483" | extension four eight three |
| `G-10/4` | "G-ten/four" (en), "ٹی جا **سلاش** ۴" (ur) | G ten four, slash silent |
| `44000` | "forty four thousand" | postal code four four zero zero zero |
| `3rd Road` | "Teen Ardi Road" | Third Road |
| `P.O. Box 1614` | "one thousand six hundred and fourteen" | Post Office Box one six one four |

Three principles hold this together:

1. **Identifiers are not quantities.** A postcode, a sector, a box number, an extension
   and the "2" in CO2 are all read digit-by-digit or letter-by-letter. This is why
   `spoken_addresses` must run *before* the number spell-out — that pass
   would otherwise turn each of them into a number.
2. **Scope narrowly.** The sector rule fires only on the sector shape, so `24/7` and
   `2024/25` keep their own handling. The postcode rule refuses a five-digit run
   followed by a scale word, so "12500 million cubic feet" stays a quantity.
3. **Separate the letters, don't expand them.** "MD and CEO" still collided across the
   "and" ("ESDM didn't see EO"), so title pairs are hyphenated — "M-D and C-E-O" reads
   back as "MD and CEO" in English and "ایم ڈی اور سی ای او" in Urdu. Spelling them out
   in full also worked, but §3.1.7 repeats the pair inside one sentence ("Faheem Haider
   (MD/CEO) serves as Chairman and MD/CEO") and six words twice in a breath was worse to
   listen to than the original problem. Only a *pair* joined by a separator is rewritten;
   a lone "the CEO" is left alone.

### What was tried and rejected

`anti-corruption` → `anti corruption` is **English-only**. The Urdu voice already says
"اینٹی کرپشن" correctly and spacing it made it worse ("این ڈی کرپشن"). Letter-spacing
`M D and C E O` also failed ("PSD, MDA, and CTO"), which is what forced the full-title
approach.

## Loanword and brand respellings

The Uplift voice takes its phonemes from the script, so an English loanword written in
Urdu letters is read wrong, and Latin text in an Urdu sentence is read with English
letter values. Measured findings behind `_SAY_AS` and `_respell_by_language`:

| Term | What happened | Fix |
|---|---|---|
| `Sky47` | English: one mangled word ("SkySitalis"); Urdu: `اسکائی ۴۷` said "sentaalees" | "Sky Forty Seven" in both |
| `Mari`, `MARI` | tapped ر instead of the retroflex flap; the all-caps ticker was letter-spelled | ماڑی |
| `Maryam`, `Hamza`, the salam | English phonetics ("Mary-am", a flat "assa-lamu-a-LAY-kum") | مریم، حمزہ، السلام علیکم |
| `Huawei` | "hoo-AH-way" | ہواوے, in both languages |
| `NVIDIA` | all caps letter-spelled as an initialism | "Envidia" (en), اینویڈیا (ur) |
| `50kW` | the `\b`-anchored acronym rule never matched a unit glued to its number; English said "fifty", Urdu read a bare count | lookbehind for the digit: kilowatts / کلو واٹ |
| `NPU`/`NPUs` | "N P U" read as separate tokens; "N P Us" ended in the English word "us" | Urdu letter names; joined into one token in English so the voice does not pause |
| `subsidiary` (سبسڈیری) | middle syllable dropped; malformed tails like سبسیڈیریاری were made worse by matching only the prefix | سب سِڈی ری, swallowing any repeated tail |

**Huawei.** Three Latin respellings failed before the Urdu one: "Wah-way" was split at
the hyphen into two clipped pieces, "Wah way" was two tokens and dropped the H, and
"Hwahway" spelled a consonant cluster the voice cannot read. ہواوے is how an Urdu speaker
writes the name, and the voice already said it correctly in Urdu replies.

**liquid cooled (Urdu).** Both Urdu-script attempts said "liquid cold": کولڈ is how Urdu
writes "cold", and the diacritic form لِکوئڈ کُولڈ was not read reliably. The Latin
respelling "likwid koold" doubles the vowel to force the "oo" and keeps the "-d".

**cluster(s) (Urdu).** کلسٹر is a bare consonant run the voice ran together; کلاسٹر added
the vowel in the wrong place ("klaaster"). "klustur"/"klusturz" spells the English
short "u". Plural rules run first so a stray ز or s is not left behind.

**methane mitigation (Urdu).** Fixed one word at a time, the phrase reached the voice as
"methayn مٹی گیشن", a script change mid-phrase that turned the second word into
"matigation". The pair is rewritten in one step, both halves Latin.

**Inserted pauses make things worse.** Re-measured against the live voice (synthesise,
transcribe, read the word timings back):

| Input | Heard | Longest internal gap |
|---|---|---|
| `rare earth elements and copper` | correct | 0.00s |
| `rare, earth elements and copper` | "wear, birth, elements" | 0.56s |
| `rare. Earth elements and copper` | "way, Earth's elements" | 0.64s |

"methane mitigation" was said identically with and without an inserted stop, which only
added a 0.9s hole. "food grade" is mispronounced ("great") however it is punctuated, so
only the corpus hyphen is normalised. Rate (`APP_UPLIFT_SPEED`) is the only lever that
slows this voice without corrupting it.

## Speaking rate

`APP_UPLIFT_SPEED` defaults to 0.9: at 1.0 the voice clips short unstressed words
("about us" lost the "us": 0.18s at 1.0, 0.26s at 0.9). The curve is not monotonic
(0.95 measured worse than 1.0, at 0.14s), so retune by measuring. English has its own
rate, `APP_UPLIFT_SPEED_EN` (0.78), because the English prose read at a rushed clip,
which is a pacing complaint, not a clipping one.

## Every other initialism

The acronym table held about sixty entries; the knowledge base has some 150 more
(`UET`, `NTN`, `UBL`, `ACCA`, `PPL`, `GHPL` …). Round-tripped in a sentence, plain Latin
capitals failed in both voices:

| Written | English voice | Urdu voice |
|---|---|---|
| `UBL` | "above" | "ابل" |
| `IBA` | "Eber" | "ایبا" |
| `NTN` | "MTN" | "ایم ٹی آئی این" |
| `ACCA` | "a care" | dropped |
| `PPL` | "TPL" | ✓ |
| `SNGPL`, `SECP` | "SNDPO", "SEPI type" | — |

`spoken_initialisms` runs after every pass that owns a capitalised shape:

- **English: hyphenated letters.** `U-E-T`, `S-E-C-P`, `S-N-G-P-L` all read back as the
  initialism — the same trick as `M-D and C-E-O`. Spaces fail ("S and GPL"); hyphens do
  not. Tokens already measured fine in Latin (`AI`, `HR`, `CEO`, `MD`, `ISO`, `UK` …) are
  left alone.
- **Urdu: Urdu letter names** (`یو ای ٹی`), as the acronym table's Urdu column already does.
- **Said as a word, not letters:** `LUMS` → لمز (Latin lost the S: "لم"), `PARCO` → پارکو,
  `GEM` → جیم (Latin was spelled "جی ای ایم"). English keeps these in Latin, except
  `PACRA`: Latin came back "Petra", hyphenated letters "PECRA".
- `AAA` is "triple A" / "ٹرپل اے", as a rating is said aloud.
- Capitalised English words (`THIS IS NOT`) and Roman numerals are not initialisms.

A spaced `&` in an Urdu reply (`ایم ڈی & سی ای او`) came back "ایم ڈی ایم پسند سی ای او";
it is now «اور».

## Returning the salam

A visitor who says "Assalamualaikum" is answered "Walaikum Assalam" / «وعلیکم السلام», as
a Pakistani receptionist would; any other greeting still gets the kiosk's own
"Assalamualaikum". `said_salam` in `server/agent/greeting.py` recognises every spelling
Soniox writes (`اسلام علیکم`, `السلام و علیکم`, `Asalam o alaikum`, with or without the
blessing), and `force_salam(..., returning=True)` enforces the opener. The TTS pass already
respells "Walaikum Assalam" as «وعلیکم السلام», which round-trips correctly in both voices.

## Units

Unit symbols were read as letters: `kW` as "K W", and `MW`, `TB` and `GB` were spelled
by the initialism pass. The old rule only caught `50kW`/`50 kW`, so a bare "kW per rack",
a "50-kW rack", an uppercase `KW`, or the model's Urdu letters «50 کے ڈبلیو» all slipped
through. `spoken_units` says every symbol by name, and runs before the acronym table.

Round-tripped, the names came back as the symbol in both voices: "fifty kilowatts" →
"50 kW", «گیارہ کلو وولٹ» → "11 kV", «پچیس ڈگری سینٹی گریڈ» → "25°C".

| Case | Handling |
|---|---|
| `1 kW`, `a 50-kW rack`, `a 100 MW plant` | singular in English: a count of one, or an adjective |
| `30 kW/rack` | "kilowatts per rack" / «کلو واٹ فی» — otherwise the slash rule says "and" |
| `500 TB` (Urdu) | **Latin** "terabyte": «500 ٹیرا بائٹ» and «ٹیرابائٹ» were both heard as "513 بائٹ", with «سو» run into «ٹیرا» |
| `m`, `g`, `t`, `W`, `V` | left alone: "5m" is as often money as metres, and "4G" is a network |
| `TB`, `GB`, `m³`, `psi` | only after a number: "TB" alone is tuberculosis in the CSR section |
