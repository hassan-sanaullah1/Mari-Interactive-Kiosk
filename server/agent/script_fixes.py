"""Put names, the brand and abbreviations back in Latin script in an Urdu reply.

The Urdu prompt asks for them in Latin, and every pronunciation fix in
server/normalization.py is keyed on the Latin form. Qwen 3.5 ignores the rule in about half
of its Urdu replies (6 of 12 sampled; lowering the temperature or repeating the rule on the
user turn only brought it to 4 of 12), and invents spellings when it does: «فیہم حیدر»,
«انور علی ہائڈر», «ایلا ماجد», «میری انرجیز» ("my energies"), «ایچ آئی (م)»,
«ایم ایم بی او ای (MMBOE)». So the rule is enforced here, like the salam in reply_fixes.

Only known terms are rewritten: abbreviations the knowledge base actually uses, and names as
two or more consecutive words of a known person, since «حسن», «نبی» and «عادل» on their own are
ordinary Urdu words.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .. import config as C
from ..normalization import (
    _ACRONYMS,
    _CAPS_WORDS,
    _PERSON_NAMES,
    _ROMAN_NUMERALS,
    _UR_LETTER_NAMES,
)

_URDU_CHAR = "\u0600-\u06ff"

# ── Brand ───────────────────────────────────────────────────────────
# Bare «ماری» is a real Urdu word ("killed"), and «میری انرجی» can mean "my energy", so only
# the company's own compounds are matched. «مریم» is the female presenter's name and sits all
# over her prompt; when the model slips into Urdu script for the brand it reaches for it
# («مریم انرجیز», «مریم گیس فیلڈ»), and the company is named after her. In a compound it is
# never the presenter, so it is matched there too — «میں مریم ہوں» is left alone.
_MARI = r"(?:ماری|ماڑی|میری|مریم)"
_BRAND_RULES = (
    (re.compile(rf"{_MARI}\s*(?:گیس|Gas)\s*(?:فیلڈ|Field)", re.I), "Mari Gas Field"),
    (re.compile(rf"{_MARI}\s*(?:انرجیز|Energies)|(?:ماری|ماڑی)\s*انرجی(?![{_URDU_CHAR}])", re.I),
     "Mari Energies"),
    (re.compile(rf"{_MARI}\s*(?:پٹرولیم|پیٹرولیم|Petroleum)", re.I), "Mari Petroleum"),
    (re.compile(rf"{_MARI}\s*(?:سروسز|Services)", re.I), "Mari Services"),
    (re.compile(rf"{_MARI}\s*(?:منرلز|Minerals)", re.I), "Mari Minerals"),
    (re.compile(rf"{_MARI}\s*(?:ٹیکنالوجیز|Technologies)", re.I), "Mari Technologies"),
)

# ── Honours and ranks ───────────────────────────────────────────────
_HONOURS = (
    (re.compile(r"(?:ایچ\s*آئی|ہیو|ہی|ایچ\s*ای|\bHI)\s*\(\s*(?:ایم|م|M)\s*\)"), "HI(M)"),
    (re.compile(r"(?:ایس\s*آئی|\bSI)\s*\(\s*(?:ایم|م|M)\s*\)"), "SI(M)"),
    (re.compile(r"(?:ٹی\s*آئی|\bTI)\s*\(\s*(?:ایم|م|M)\s*\)"), "TI(M)"),
    (re.compile(r"(?:این\s*آئی|\bNI)\s*\(\s*(?:ایم|م|M)\s*\)"), "NI(M)"),
)
# Misspellings of «لیفٹیننٹ», which server/normalization.py reads correctly.
_RANK_RE = re.compile(r"(?:لیٹنٹ|لیٹیننٹ|لفٹیننٹ|لیفٹنٹ|لیفٹیننٹ)(?=\s+(?:جنرل|کرنل))")

# ── Abbreviations spelled as Urdu letter names ──────────────────────
_LETTERS: dict[str, tuple[str, ...]] = {urdu: (latin,) for latin, urdu in _UR_LETTER_NAMES.items()}
_LETTERS["ای"] = ("E", "A")          # the model writes A as «ای» as often as «اے»
_LETTERS["ائی"] = ("I",)
_LETTER_TOKEN = "|".join(sorted(map(re.escape, _LETTERS), key=len, reverse=True))
_LETTER_RUN_RE = re.compile(
    rf"(?<![{_URDU_CHAR}])(?:{_LETTER_TOKEN})(?:\s+(?:{_LETTER_TOKEN}))+(?![{_URDU_CHAR}])"
)


@lru_cache(maxsize=1)
def _known_acronyms() -> frozenset[str]:
    """Acronyms the kiosk can meet: the acronym table plus every one the corpus uses."""
    known = {k for k in _ACRONYMS if re.fullmatch(r"[A-Z]{2,7}", k)}
    try:
        corpus = C.KNOWLEDGE_FILE.read_text(encoding="utf-8")
        known |= set(re.findall(r"\b[A-Z]{2,7}\b", corpus))
    except OSError:
        pass
    return frozenset(known - _CAPS_WORDS - _ROMAN_NUMERALS)


def _spell(tokens: list[str]) -> list[str]:
    words = [""]
    for token in tokens:
        words = [w + letter for w in words for letter in _LETTERS[token]]
    return words


# Letter names that are also everyday Urdu words: a run may start or end with one that is
# not part of the abbreviation («ان کے سی ای او» is "their CEO").
_ALSO_WORDS = frozenset({"کے", "سی", "او", "پی", "بی", "یو", "ای"})


def _latin_letters(run: str) -> str:
    """The run as a known acronym, allowing only everyday words to be left over at its ends."""
    tokens = run.split()
    known = _known_acronyms()
    for size in range(len(tokens), 1, -1):
        for start in range(len(tokens) - size + 1):
            before, window, after = tokens[:start], tokens[start:start + size], tokens[start + size:]
            if not set(before + after) <= _ALSO_WORDS:
                continue
            # «کے» is also the everyday postposition: a two-letter "K?" is too often a false hit.
            if size == 2 and window[0] == "کے":
                continue
            hit = next((w for w in _spell(window) if w in known), None)
            if hit:
                return " ".join([*before, hit, *after])
    return run


# "MMBOE (MMBOE)" once the letters are converted, and a Latin gloss after Urdu words that
# already say it ("… ایکویویلنٹ (MMBOE)"); the prompt forbids both, and speech says each twice.
_SAME_GLOSS_RE = re.compile(r"\b([A-Z][A-Za-z&]{1,7})\s*\(\s*\1\s*\)")
_GLOSS_AFTER_URDU_RE = re.compile(rf"(?<=[{_URDU_CHAR}])\s*\(\s*([A-Z]{{2,7}})\s*\)")

# ── Person names ────────────────────────────────────────────────────
_SKELETON_MAP = str.maketrans({
    "ح": "ہ", "ھ": "ہ", "ۃ": "ہ", "ة": "ہ", "ذ": "ز", "ض": "ز", "ظ": "ز", "ص": "س", "ث": "س",
    "ط": "ت", "ٹ": "ت", "ق": "ک", "ك": "ک", "ڈ": "د", "ي": "ی",
})
_SKELETON_DROP_RE = re.compile(r"[اآعوىیےئؤء\u064b-\u065f\u0670]")
# Urdu letters only: «،» and «۔» sit in the same Unicode block but end a word.
_URDU_WORD_RE = re.compile(r"[\u0621-\u063a\u0641-\u064a\u064b-\u065f\u0670-\u06d3\u06fa-\u06ff]+")


def _skeleton(word: str) -> str:
    """Consonants only, with letters the model confuses merged: «فیہم» and «فہیم» agree."""
    s = _SKELETON_DROP_RE.sub("", word.translate(_SKELETON_MAP))
    return s[:-1] if len(s) > 1 and s.endswith("ہ") else s


def _close(a: str, b: str) -> bool:
    if a == b:
        return True
    if max(len(a), len(b)) < 3 or abs(len(a) - len(b)) > 1:
        return False
    # One insertion, deletion or substitution.
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


# (Latin words, skeletons of the Urdu spelling) for every known person.
_PEOPLE = tuple(
    (latin.split(), [_skeleton(w) for w in urdu.split()]) for latin, urdu in _PERSON_NAMES.items()
)

# Name words whose skeleton is a single letter match far too much («لیے» for «علی», so
# «کے لیے موجود» became "Ayla Majid"); for those the word itself must be a known spelling.
_ONE_LETTER_SPELLINGS: dict[str, frozenset[str]] = {
    "Ali": frozenset({"علی"}),
    "Ayla": frozenset({"عائلہ", "ایلا", "آئلہ", "عائلا", "آیلا"}),
}


def _trustworthy(skels: list[str], exact: list[bool]) -> bool:
    """Enough of the window matched exactly that it is really a name.

    Without this, «تفصیل کے لیے ہماری ویب سائٹ» became "Ali Hyder": «لیے» reduces to the same
    one letter as «علی», and «ہماری» is one letter from «حیدر».
    """
    if all(exact):
        return sum(map(len, skels)) >= 3
    anchors = [s for s, e in zip(skels, exact) if e]
    return len(anchors) >= 2 and any(len(s) >= 2 for s in anchors)


def _match_at(tokens: list[re.Match[str]], i: int, text: str, exact: bool):
    """Longest known-name window starting at token i: (tokens consumed, Latin words)."""
    best: tuple[int, list[str]] | None = None
    close = (lambda a, b: a == b) if exact else _close
    for latin, skels in _PEOPLE:
        for start in range(len(skels) - 1):
            ti, ni, used, hits = i, start, 0, []
            while ni < len(skels) and ti < len(tokens):
                # Tokens must be separated by whitespace only.
                if ti > i and text[tokens[ti - 1].end():tokens[ti].start()].strip():
                    break
                one = _skeleton(tokens[ti].group())
                if len(skels[ni]) <= 1 and tokens[ti].group() not in _ONE_LETTER_SPELLINGS.get(
                        latin[ni], frozenset()):
                    break
                # One name word split in two («شاہ زاد» for «شہزاد»). Exact only: a fuzzy join
                # swallowed the «اور» in «نبی اور سیما».
                two = (_skeleton(tokens[ti].group() + tokens[ti + 1].group())
                       if ti + 1 < len(tokens)
                       and not text[tokens[ti].end():tokens[ti + 1].start()].strip() else None)
                if close(one, skels[ni]):
                    hits.append(one == skels[ni])
                    ti += 1
                elif two is not None and two == skels[ni]:
                    hits.append(True)
                    ti += 2
                else:
                    break
                ni += 1
                used = ti - i
            matched = ni - start
            if (matched >= 2 and _trustworthy(skels[start:ni], hits)
                    and (best is None or matched > len(best[1]))):
                best = (used, latin[start:ni])
    return best


def _latin_names(text: str) -> str:
    tokens = list(_URDU_WORD_RE.finditer(text))
    out, last, i = [], 0, 0
    while i < len(tokens):
        exact = _match_at(tokens, i, text, exact=True)
        fuzzy = _match_at(tokens, i, text, exact=False)
        # The longer match wins; on a tie the exact one does.
        hit = fuzzy if fuzzy and (not exact or len(fuzzy[1]) > len(exact[1])) else exact
        if hit:
            used, latin = hit
            out.append(text[last:tokens[i].start()])
            out.append(" ".join(latin))
            last = tokens[i + used - 1].end()
            i += used
        else:
            i += 1
    out.append(text[last:])
    return "".join(out)


# ── Words that switch script part-way ───────────────────────────────
# Qwen sometimes writes the first letter of an English word in Urdu script and the rest
# in Latin: «کiosk», «فiscal», «نiaz». Such a word is never correct, so whatever the word,
# the Urdu letters are replaced by their Latin sound. Where a letter has more than one
# (ک is k, c or q), the spelling the knowledge base uses wins, with its capitalisation.
_LATIN_SOUNDS: dict[str, tuple[str, ...]] = {
    "ا": ("a",), "آ": ("a",), "ع": ("a",), "ب": ("b",), "پ": ("p",), "ت": ("t",),
    "ٹ": ("t",), "ث": ("s",), "ج": ("j",), "چ": ("ch",), "ح": ("h",), "خ": ("kh",),
    "د": ("d",), "ڈ": ("d",), "ذ": ("z",), "ر": ("r",), "ڑ": ("r",), "ز": ("z", "s"),
    "ژ": ("zh",), "س": ("s", "c"), "ش": ("sh",), "ص": ("s",), "ض": ("z",), "ط": ("t",),
    "ظ": ("z",), "غ": ("gh",), "ف": ("f", "ph"), "ق": ("q", "k"), "ک": ("k", "c", "q"),
    "ك": ("k", "c"), "گ": ("g",), "ل": ("l",), "م": ("m",), "ن": ("n",), "و": ("w", "v"),
    "ہ": ("h",), "ھ": ("h",), "ی": ("y", "i", "e"), "ي": ("y", "i"), "ے": ("e",),
}
_MIXED_WORD_RE = re.compile(rf"(?<![{_URDU_CHAR}A-Za-z])([{''.join(_LATIN_SOUNDS)}]{{1,2}})([A-Za-z]{{2,}})\b")


@lru_cache(maxsize=1)
def _corpus_words() -> dict[str, str]:
    """Every Latin word in the knowledge base, lower-cased, mapped to its usual spelling."""
    try:
        corpus = C.KNOWLEDGE_FILE.read_text(encoding="utf-8")
    except OSError:
        return {}
    words: dict[str, str] = {}
    for word in re.findall(r"[A-Za-z][A-Za-z'-]*", corpus):
        # Lower case wins when the corpus uses it at all: capitals there may just open a sentence.
        if word.islower() or word.lower() not in words:
            words[word.lower()] = word
    return words


def _latin_word(m: re.Match[str]) -> str:
    urdu, rest = m.group(1), m.group(2)
    heads = [""]
    for letter in urdu:
        heads = [h + s for h in heads for s in _LATIN_SOUNDS[letter]]
    known = _corpus_words()
    for head in heads:
        if (head + rest).lower() in known:
            return known[(head + rest).lower()]
    word = heads[0] + rest
    return word.capitalize() if rest[:1].isupper() else word


def latin_terms(reply: str, lang: str = "ur") -> str:
    """Rewrite Urdu-script names, brand and abbreviations in an Urdu reply to Latin."""
    if lang != "ur" or not reply:
        return reply
    reply = _MIXED_WORD_RE.sub(_latin_word, reply)
    for pattern, latin in _BRAND_RULES:
        reply = pattern.sub(latin, reply)
    for pattern, latin in _HONOURS:
        reply = pattern.sub(latin, reply)
    reply = _RANK_RE.sub("لیفٹیننٹ", reply)
    reply = _LETTER_RUN_RE.sub(lambda m: _latin_letters(m.group()), reply)
    reply = _SAME_GLOSS_RE.sub(r"\1", reply)
    reply = _GLOSS_AFTER_URDU_RE.sub(
        lambda m: "" if m.group(1) in _known_acronyms() else m.group(0), reply)
    return _latin_names(reply)
