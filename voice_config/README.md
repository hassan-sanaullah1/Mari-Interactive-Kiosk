# voice_config

Everything that shapes **what the avatar says** — persona, abbreviation definitions, and
pronunciation fixes — kept in one place instead of scattered through the pipeline code
that decides *when* it says it.

```
voice_config/
  prompts/
    system_prompt_english.md   persona + rules, English mode
    system_prompt_urdu.md      persona + rules, Urdu mode
    greeting_english.md        opt-in introduction, added only on a greeting turn
    greeting_urdu.md
  addresses.py                 addresses, contact lines, formulae, symbol abbreviations
  glossary.py                  ABBR → full-form pairs mined from the knowledge base
  names.py                     people's names, military ranks and honours
  urdu_normalise.py            spoken-form fixes for what the Uplift voice gets wrong
```

## How it is wired in

| Piece | Hook | Where |
|---|---|---|
| Prompts | `RULES` / `GREETINGS` load from `prompts/*.md` | `server/knowledge.py` |
| Glossary | `system_prompt()` force-injects matched definitions ahead of retrieved context | `server/knowledge.py` |
| Names/ranks | `_spoken()` applies it in both languages | `server/providers/tts.py` |
| Addresses | `_spoken()`, before the number spell-out | `server/providers/tts.py` |
| Normalizer | `_spoken()` runs it last, before the Uplift request | `server/providers/tts.py` |

Each import is wrapped in `try/except ImportError` with a working fallback, so deleting
this folder degrades the kiosk to its previous behaviour rather than breaking startup.

## Editing the prompts

The `.md` files are the source of truth at runtime; the string literals still in
`server/knowledge.py` are the fallback and were the origin of these files (extracted
verbatim). Edit the `.md` file and restart the backend — `./mari.sh restart`.

## Why the normalizer is so short

The reference implementation this was adapted from targeted MMS-TTS/ElevenLabs, which
could not read Western digits inside an Urdu sentence, so most of it converted digits to
Urdu words.

**Uplift does not need that.** Round-tripping the live voice (Uplift TTS → Soniox STT)
shows it already handles digits, decimals, percentages, `24/7`, years and phone numbers
— `127` and `ایک سو ستائیس` synthesise to the same audio. Porting the converter would
have duplicated the engine and fought the English number spell-out in
`server/providers/tts.py`, which exists for the opposite reason.

The same round trip found three things Uplift genuinely gets wrong, all present in the
knowledge base. Those, and only those, are what `urdu_normalise.py` fixes:

| Input | Uplift says | After the fix |
|---|---|---|
| `Tier III` | ٹی آئی آئی لائیو (letter by letter) | ٹیئر 3 |
| `تیل/گیس` | تیل **سلیش** گیس | تیل **اور** گیس |
| `marienergies.com.pk` | میری مرضی کامپی کے | ماڑی انرجیز ڈاٹ کام ڈاٹ پی کے |

Before adding a rule, check the engine actually needs it — synthesize the phrase and
transcribe it back. Re-normalising something Uplift already says correctly is how this
kind of module regresses.

## Why the glossary filters so aggressively

Retrieval is BM25 over whole sections, so an abbreviation used in a dozen sections but
spelled out in one may never reach the model. The glossary force-injects the definition.

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
right. **But it is not a blanket win** — "Faheem Haider" is already correct in English and
Urdu script makes it *worse* ("Fahim headers"), while in Urdu mode the reverse holds. So
`names.py` keeps a per-language table, and only names a round trip proved broken are in
it. Names that already work are pinned as deliberately absent in
`tests/test_names_and_ranks.py`.

Ranks and honours are rules rather than a table, because there the failure is
abbreviation, not phonetics: `Lt. Gen.` → "Leftenant"/"Eldeej" and `(Retd)` → "Grade",
but the spelled-out words are said correctly. `HI(M)` is dropped from speech — it reads
as "HIV" or "a type M", and the expanded "Hilal-e-Imtiaz" fares no better ("Hello team,
here's Mummy Tree"). It is a decoration, not a fact, and only the audio is affected.

### What was tried and rejected

Letter-spacing the other initialisms (`SECP`, `ICAP`, `SNGPL`, `HSE`) made the voice
**worse**, not better — `S N G P L` is heard as "S and GPL". They are left alone. Only
`HR&R` (run together as "H9R") and the credit rating `A1` (glued into the non-word
"Aone" by the number spell-out) were changed.

## Addresses, formulae and symbol abbreviations

All measured the same way — round trip the live voice, keep only what came back right:

| Written | Voice said | Now |
|---|---|---|
| `CO₂` / `CO2` | "seagull dough" / "COtwo" | C O two |
| `E&P` | "ENP" (en), "ایم ای این پی" (ur) | exploration and production |
| `MD/CEO` | "MD/C8 August" | Managing Director and Chief Executive Officer |
| `Ext. 483` | "x483" | extension four eight three |
| `G-10/4` | "G-ten/four" (en), "ٹی جا **سلاش** ۴" (ur) | G ten four, slash silent |
| `44000` | "forty four thousand" | postal code four four zero zero zero |
| `3rd Road` | "Teen Ardi Road" | Third Road |
| `P.O. Box 1614` | "one thousand six hundred and fourteen" | Post Office Box one six one four |

Three principles hold this together:

1. **Identifiers are not quantities.** A postcode, a sector, a box number, an extension
   and the "2" in CO2 are all read digit-by-digit or letter-by-letter. This is why
   `spoken_addresses` must run *before* the number spell-out in `tts.py` — that pass
   would otherwise turn each of them into a number.
2. **Scope narrowly.** The sector rule fires only on the sector shape, so `24/7` and
   `2024/25` keep their own handling. The postcode rule refuses a five-digit run
   followed by a scale word, so "12500 million cubic feet" stays a quantity.
3. **Spelling a title out beats splitting it.** "MD and CEO" still collided across the
   "and" ("ESDM didn't see EO"), so title pairs become full job titles in both
   languages.

### What was tried and rejected

`anti-corruption` → `anti corruption` is **English-only**. The Urdu voice already says
"اینٹی کرپشن" correctly and spacing it made it worse ("این ڈی کرپشن"). Letter-spacing
`M D and C E O` also failed ("PSD, MDA, and CTO"), which is what forced the full-title
approach.
