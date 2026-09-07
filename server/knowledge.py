"""MARI · Voice — grounding knowledge for the LLM.

The avatar is a Mari Energies kiosk assistant, so every reply has to come from
``server/data/mari_energies_knowledge_base.md`` rather than the model's own memory. That
file is ~58 KB — far too large to prepend to each turn on a latency-sensitive voice
pipeline — so this module does two things:

  * keeps a short hand-written CORE brief that is *always* in the system prompt, and
  * retrieves the few knowledge-base sections that match what the visitor just asked
    (BM25-style scoring over heading-delimited chunks, stdlib only — no embeddings,
    no extra service to deploy).

Urdu questions are scored against the English knowledge base by expanding them
through GLOSSARY first; the model is then told to read English and answer in Urdu.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from . import config as C

try:  # voice_config is optional — the in-code prompt literals below are the fallback
    from voice_config import (
        extract_glossary,
        find_glossary_matches,
        format_glossary_block,
        load_prompt as _load_prompt,
    )
except ImportError:  # pragma: no cover - only hit if the folder is removed
    def _load_prompt(name: str) -> str | None:
        return None

    def extract_glossary(text: str) -> dict[str, str]:
        return {}

    def find_glossary_matches(query: str, glossary: dict[str, str]) -> dict[str, str]:
        return {}

    def format_glossary_block(matches: dict[str, str]) -> str:
        return ""

KB_PATH = Path(
    C.env("APP_KNOWLEDGE_FILE", str(C.ROOT / "server" / "data" / "mari_energies_knowledge_base.md"))
)

# How much retrieved material a single turn may carry. Roughly 1.5k tokens — enough
# for two or three sections, small enough that time-to-first-token stays kiosk-fast.
MAX_CHUNKS = 4
MAX_CONTEXT_CHARS = 6000
# Chunks longer than this are split so one giant section can't crowd out the rest.
MAX_CHUNK_CHARS = 2200


# ── chunking ────────────────────────────────────────────────────────

@dataclass
class Chunk:
    title: str      # "1. Overview of Mari Energies Limited › 1.5 Ownership and Shareholding Structure"
    text: str
    tf: dict[str, int]
    length: int


def _split_long(title: str, body: str) -> list[tuple[str, str]]:
    """Break an oversized section on line boundaries, repeating the heading."""
    if len(body) <= MAX_CHUNK_CHARS:
        return [(title, body)]
    parts, buf = [], ""
    for line in body.splitlines(keepends=True):
        if buf and len(buf) + len(line) > MAX_CHUNK_CHARS:
            parts.append(buf)
            buf = ""
        buf += line
    if buf.strip():
        parts.append(buf)
    n = len(parts)
    return [(f"{title} (part {i}/{n})" if n > 1 else title, p) for i, p in enumerate(parts, 1)]


def _parse(md: str) -> list[tuple[str, str]]:
    """Slice the markdown into (heading-path, body) sections at ## / ### headings."""
    sections: list[tuple[str, str]] = []
    h2 = ""
    title, body = "", []

    def flush() -> None:
        if title and "".join(body).strip():
            sections.extend(_split_long(title, "".join(body).strip()))

    for line in md.splitlines(keepends=True):
        m = re.match(r"^(#{2,3})\s+(.*?)\s*$", line)
        if not m:
            body.append(line)
            continue
        flush()
        body = []
        head = m.group(2)
        if len(m.group(1)) == 2:
            h2, title = head, head
        else:
            title = f"{h2} › {head}" if h2 else head
    flush()
    return sections


_WORD = re.compile(r"[a-z0-9]+")

# Terms that appear in nearly every section carry no signal for ranking.
_STOP = {
    "the", "and", "for", "with", "that", "this", "are", "was", "will", "from", "has",
    "have", "its", "not", "you", "your", "our", "who", "what", "when", "where", "how",
    "can", "does", "did", "any", "all", "also", "more", "than", "about", "into", "over",
    "mari", "marienergies", "energies", "pakistan", "company", "limited",
}


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP]


def _load() -> tuple[list[Chunk], dict[str, int]]:
    if not KB_PATH.exists():
        return [], {}
    chunks: list[Chunk] = []
    df: dict[str, int] = {}
    for title, body in _parse(KB_PATH.read_text(encoding="utf-8")):
        # the heading is repeated so a question phrased like a section name scores high
        toks = _tokens(title) * 3 + _tokens(body)
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        chunks.append(Chunk(title=title, text=body, tf=tf, length=len(toks) or 1))
        for t in tf:
            df[t] = df.get(t, 0) + 1
    return chunks, df


CHUNKS, _DF = _load()
_AVG_LEN = (sum(c.length for c in CHUNKS) / len(CHUNKS)) if CHUNKS else 1.0


def ready() -> bool:
    return bool(CHUNKS)


# ── Urdu → English query expansion ──────────────────────────────────
# The knowledge base is English; visitors ask in Urdu. Mapping the handful of words a
# kiosk visitor actually uses is enough to land on the right section, and costs nothing
# at runtime compared with a multilingual embedding model.
# Multi-word terms first: Urdu spells several of these out letter by letter
# ("سی ای او" = C-E-O), so matching the phrase avoids the single letters colliding
# with unrelated words.
PHRASES: dict[str, str] = {
    "سی ای او": "ceo managing director chief executive leadership",
    "ایم ڈی": "managing director ceo leadership",
    "ای میل": "contact email investor relations",
    "ڈیٹا سینٹر": "data center technologies sky47 subsidiary",
    "اسلام آباد": "islamabad head office contact",
    "اے آئی": "artificial intelligence digital transformation technology",
    "مصنوعی ذہانت": "artificial intelligence digital transformation technology",
    "تیل اور گیس": "oil gas upstream exploration production",
    "قدرتی گیس": "gas production reserves field",
    "اسٹاک ایکسچینج": "psx listed shares market capitalization",
    "منافع": "profit financial performance earnings",
    "ماری گیس فیلڈ": "mari gas field daharki discovery",
    "ری نیو ایبل": "renewable solar energy transition",
    "ہیڈ آفس": "head office contact address islamabad",
    "آف شور": "offshore exploration expansion",
    "سرمایہ کار": "investor relations shareholders",
    "بورڈ آف ڈائریکٹرز": "board directors governance",
    "ری برانڈنگ": "rebranding identity logo mari petroleum",
    "منافع منقسمہ": "dividend per share payout",
    "سرمایہ کاری": "investor relations investment",
    "ای ایس جی": "esg sustainability governance",
    "سی ایس آر": "csr community initiatives welfare",
}

GLOSSARY: dict[str, str] = {
    # company, identity, ownership
    "کمپنی": "company overview legal entity",
    "ادارہ": "company overview",
    "تعارف": "overview about",
    "ملکیت": "ownership shareholding shareholders",
    "مالک": "ownership shareholding parent",
    "حصص": "shareholding shares shareholders free float",
    "شیئر": "shareholding shares stock price psx",
    "شیئرہولڈر": "shareholders shareholding structure",
    "فوجی": "fauji foundation shareholding",
    "حکومت": "government pakistan shareholding ogdcl",
    "ذیلی": "subsidiaries group structure equity",
    "کمپنیاں": "subsidiaries associated companies group",
    "ماری": "marienergies mari petroleum mpcl",
    "نام": "rebranding name mari petroleum",
    "تاریخ": "history timeline milestones",
    "بانی": "history establishment discovery",
    # leadership and governance
    "سربراہ": "ceo managing director leadership",
    "چیئرمین": "chairman board directors",
    "قیادت": "leadership management team executives",
    "انتظامیہ": "senior management team leadership",
    "ٹیم": "management team board members",
    "بورڈ": "board directors governance committees",
    "کمیٹی": "board committees audit governance",
    "گورننس": "governance board committees compliance",
    # business, operations, exploration
    "کاروبار": "principal business activities verticals",
    "خدمات": "services mari services drilling seismic",
    "سروس": "services mari services drilling seismic",
    "شعبے": "verticals business segments diversification",
    "تیل": "oil liquids production upstream",
    "گیس": "gas production reserves field",
    "کنواں": "well drilling discovery",
    "کھدائی": "drilling program wells",
    "دریافت": "discoveries exploration hydrocarbon",
    "تلاش": "exploration portfolio blocks",
    "بلاک": "exploration blocks acreage",
    "پیداوار": "production sales capacity",
    "ذخائر": "reserves resources mmboe",
    "فیلڈ": "field development mari gas field daharki",
    "معدنیات": "minerals copper gold rare earth",
    "کان": "minerals mining copper gold",
    "ٹیکنالوجی": "technology digital transformation data center",
    "ڈیٹا": "data center technologies digital",
    "سینٹر": "data center technologies sky47",
    "کلاؤڈ": "cloud high performance computing infrastructure",
    "ڈیجیٹل": "digital transformation technology automation",
    # financials
    "منافع": "profit earnings financial performance",
    "آمدنی": "net sales revenue financial performance",
    "مالی": "financial performance results reports",
    "سرمایہ": "market capitalization investment",
    "ڈیویڈنڈ": "dividend per share payout",
    "ٹیکس": "taxation national exchequer contribution",
    "قیمت": "stock price share price psx",
    # sustainability, people, community
    "ماحول": "environment sustainability esg emissions",
    "پائیداری": "sustainability esg environment",
    "توانائی": "energy transition renewable power",
    "شمسی": "solar renewable energy project",
    "ملازمت": "careers jobs recruitment hiring",
    "نوکری": "careers jobs recruitment hiring",
    "بھرتی": "recruitment process careers",
    "تربیت": "training talent development learning",
    "ملازمین": "workforce employees headcount",
    "خواتین": "diversity inclusion women workforce",
    "فلاح": "csr community welfare initiatives",
    "تعلیم": "education csr schools scholarships",
    "صحت": "healthcare csr medical camps",
    "کھیل": "sports sponsorship csr",
    # contact
    "رابطہ": "contact address email website phone",
    "پتہ": "contact address head office location",
    "فون": "contact phone number",
    "ویب": "website contact",
    "دفتر": "office head office karachi quetta",
    "کراچی": "karachi office contact",
    "کوئٹہ": "quetta office contact",
    # transliterated English — kiosk visitors mix English terms into Urdu speech far
    # more often than they use the formal Urdu word, so both spellings must resolve.
    "ریکروٹمنٹ": "recruitment process careers hiring",
    "پروسیس": "process procedure steps",
    "جاب": "careers jobs vacancies",
    "جابز": "careers jobs vacancies",
    "کیریئر": "careers jobs recruitment",
    "انٹرویو": "interview recruitment process",
    "اپلائی": "apply application recruitment careers",
    "درخواست": "application apply recruitment",
    "ٹریننگ": "training talent development",
    "پروفٹ": "profit earnings financial performance",
    "ریونیو": "net sales revenue financial performance",
    "شیئرز": "shares shareholding psx",
    "اسٹاک": "stock price psx shares",
    "مارکیٹ": "market capitalization psx",
    "ڈائریکٹر": "directors board governance",
    "منیجمنٹ": "management team leadership",
    "لیڈرشپ": "leadership management team",
    "سبسڈری": "subsidiaries group structure",
    "پروڈکشن": "production capacity output",
    "ایکسپلوریشن": "exploration blocks portfolio",
    "ڈرلنگ": "drilling wells program",
    "ریزروز": "reserves resources",
    "منرلز": "minerals copper gold rare earth",
    "کاپر": "copper minerals mining",
    "گولڈ": "gold minerals mining",
    "سولر": "solar renewable energy",
    "کنٹیکٹ": "contact address phone email",
    "سپلائر": "supplier hub vendors procurement",
    "ویکنسی": "vacancies careers jobs",
    # remaining gaps found by sweeping every KB section with realistic Urdu questions
    "آڈیٹر": "auditors external ferguson",
    "ریٹنگ": "credit rating",
    "کریڈٹ": "credit rating",
    "ورٹیکل": "verticals business segments",
    "ورٹیکلز": "verticals business segments",
    "سکائی": "sky47 technologies data center",
    "آفشور": "offshore exploration expansion",
    "سمندری": "offshore exploration",
    "کنواں": "wells drilling program",
    "کنویں": "wells drilling program",
    "دریافت": "discoveries exploration hydrocarbon",
    "دریافتیں": "discoveries hydrocarbon wells",
    "سیلز": "net sales revenue",
    "فروخت": "net sales revenue",
    "درخت": "trees plantation environment",
    "شجرکاری": "trees plantation environment",
    "فائدے": "benefits employer join us careers",
    "مراعات": "benefits compensation careers",
    "میل": "meal program nourish flourish",
    "کھانا": "meal program nutrition",
    "اعلان": "announcements recent developments",
    "اعلانات": "announcements recent developments",
    "تعداد": "workforce total employees figures",
    "انویسٹر": "investor relations queries",
    # generic
    "وژن": "vision mission",
    "مشن": "vision mission",
    "مقصد": "vision mission values purpose",
    "اقدار": "core values integrity unity excellence",
    "گاہک": "customers fertilizer buyers",
    "صارف": "customers fertilizer buyers",
    "کھاد": "fertilizer feed gas customers",
    "کب": "timeline history milestones date",
    "کتنا": "figures quick reference capacity",
    "سپلائر": "supplier hub vendors procurement",
}


# Urdu letters only. The wider \u0600-\u06ff block also holds the sentence punctuation
# (۔ U+06D4, ؟ U+061F) and the Urdu digits, which would otherwise be glued onto the word
# and stop "بتائیے۔" or "ہے؟" from ever matching a glossary key.
_UR_WORD = re.compile(r"[\u0620-\u064a\u0670-\u06d3\u06fa-\u06ff]+")
# Grammatical particles carry no topic signal; stripping them keeps a question like
# "ریکروٹمنٹ کا کیا پروسیس ہے" from being expanded on "کیا" alone.
_UR_STOP = {
    "میں", "کا", "کی", "کے", "کو", "سے", "پر", "ہے", "ہیں", "ہو", "تھا", "تھی", "اور",
    "یا", "بھی", "تو", "نے", "ایک", "یہ", "وہ", "کیا", "کون", "کیسے", "کیوں", "کہاں",
    "براہ", "کرم", "مجھے", "ہمیں", "آپ", "بتائیے", "بتائیں", "بتاؤ", "سکتے", "سکتی",
}


# Urdu spells acronyms out letter by letter ("پی ایس ایکس" = P-S-X), so the letters arrive
# as separate tokens that individually mean nothing. Joining a run of them recovers the
# acronym the knowledge base actually contains. Deterministic, and it needs no word list.
_LETTER = {
    "اے": "a", "بی": "b", "سی": "c", "ڈی": "d", "ای": "e", "ایف": "f", "جی": "g",
    "ایچ": "h", "آئی": "i", "جے": "j", "کے": "k", "ایل": "l", "ایم": "m", "این": "n",
    "او": "o", "پی": "p", "کیو": "q", "آر": "r", "ایس": "s", "ٹی": "t", "یو": "u",
    "وی": "v", "ڈبلیو": "w", "ایکس": "x", "وائے": "y", "زیڈ": "z",
}


def _acronyms(words: list[str]) -> list[str]:
    """Runs of two or more spelled-out letters, joined ("پی ایس ایکس" -> "psx")."""
    out, run = [], []
    for w in words + [""]:
        if letter := _LETTER.get(w):
            run.append(letter)
            continue
        if len(run) >= 2:
            out.append("".join(run))
        run = []
    return out


# GLOSSARY is looked up one word at a time, so a key containing a space could never
# match; several did, and failed silently. Multi-word terms belong in PHRASES.
# ── sounding out unlisted words ─────────────────────────────────────
# GLOSSARY can only hold words someone thought to add, which is fine for topics but
# hopeless for the long tail: people's names, well names, programmes ("آیلہ مجید",
# "بھٹائی", "سیڈ"). Those are unbounded, and a question containing one used to expand
# to nothing at all, so the whole question retrieved nothing and MARI said she had no
# information about a fact sitting in the knowledge base.
#
# Proper nouns survive the trip between scripts phonetically, so we sound the Urdu out
# and look for a knowledge-base word that sounds the same. Matching is exact on a
# normalised consonant skeleton — never fuzzy. An earlier attempt with edit distance
# matched "آڈیٹر" to "dsra" and "درخت" to "direct"; grounding a reply in the wrong
# section is worse than retrieving nothing, so the tolerance is gone.
_ROMAN = {
    "ا": "a", "آ": "a", "ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ث": "s", "ج": "j",
    "چ": "ch", "ح": "h", "خ": "kh", "د": "d", "ڈ": "d", "ذ": "z", "ر": "r", "ڑ": "r",
    "ز": "z", "ژ": "zh", "س": "s", "ش": "sh", "ص": "s", "ض": "z", "ط": "t", "ظ": "z",
    "ع": "a", "غ": "gh", "ف": "f", "ق": "k", "ک": "k", "گ": "g", "ل": "l", "م": "m",
    "ن": "n", "ں": "n", "و": "w", "ہ": "h", "ھ": "h", "ء": "", "ی": "y", "ے": "e",
    "ئ": "y", "ؤ": "w", "أ": "a", "ۃ": "h", "ة": "h",
}
# A single consonant matches a dozen unrelated words, so two is the floor — and a
# two-consonant key is only trusted when exactly one knowledge-base word has it.
_MIN_KEY = 2
_SHORT_KEY = 2
# A longer key claiming more than this many words is too vague to be worth injecting.
_MAX_CANDIDATES = 4


def _sound_key(word: str) -> str:
    """Spelling-independent skeleton: c/k/q folded, doubles collapsed, vowels dropped.

    Urdu writes no short vowels and picks its own consonant for a borrowed sound, so
    "کارپلنک"/"Corplink" and "پنی"/"Panni" only line up once both are reduced this far.
    """
    word = word.lower()
    for a, b in (("ck", "k"), ("ph", "f"), ("c", "k"), ("q", "k"), ("x", "ks")):
        word = word.replace(a, b)
    # Urdu writes both v and w as و, spells plural -s with ز, and hears a soft g as ج
    word = re.sub(r"g(?=[eiy])", "j", word)
    word = word.replace("v", "w").replace("z", "s")
    word = re.sub(r"(.)\1+", r"\1", word)
    word = re.sub(r"[aeiouwy]", "", word)
    word = re.sub(r"h$", "", word)          # silent final ہ: "آیلہ" is "ayla"
    return re.sub(r"(.)\1+", r"\1", word)


def _romanise(word: str) -> str:
    return "".join(_ROMAN.get(ch, "") for ch in word)


def _sound_index() -> dict[str, list[str]]:
    """Sound key -> knowledge-base words, built from the corpus so it needs no upkeep."""
    idx: dict[str, list[str]] = {}
    for term in _DF:
        if term in _STOP:
            continue
        key = _sound_key(term)
        if len(key) >= _MIN_KEY:
            idx.setdefault(key, []).append(term)
    limit = {k: (1 if len(k) == _SHORT_KEY else _MAX_CANDIDATES) for k in idx}
    return {k: v for k, v in idx.items() if len(v) <= limit[k]}


_SOUNDS = _sound_index()


def _sounds_like(word: str) -> list[str]:
    """Knowledge-base words that sound like this Urdu one, or [] if none clearly does."""
    key = _sound_key(_romanise(word))
    return _SOUNDS.get(key, []) if len(key) >= _MIN_KEY else []


assert not [k for k in GLOSSARY if " " in k], "multi-word GLOSSARY key: use PHRASES"


# What the visitor actually said outweighs what we inferred from it. A glossary entry
# expands one Urdu word into several broad English ones ("فیلڈ" -> field development gas
# daharki), and at equal weight those swamped the single specific term that identified
# the section — a question about the Daharki field ranked generic "Field Development"
# sections above the one naming Daharki.
_W_LITERAL = 1.0    # words the visitor typed, and acronyms they spelled out
_W_SOUND = 0.7      # a name matched by sound: usually right, but it can catch a
                    # common word inside a compound ("ہولڈرز" -> the KB's "holders")
_W_GLOSS = 0.5      # our own topic expansion: a hint, not evidence


def _expand_weighted(query: str) -> dict[str, float]:
    """Search terms mapped to how much trust each one has earned."""
    weights: dict[str, float] = {}

    def add(items, weight: float) -> None:
        for t in items:
            weights[t] = max(weights.get(t, 0.0), weight)

    add(_tokens(query), _W_LITERAL)
    rest = query
    for phrase, mapped in PHRASES.items():
        if phrase in rest:
            add(_tokens(mapped), _W_GLOSS)
            rest = rest.replace(phrase, " ")

    words = [w for w in _UR_WORD.findall(rest) if w not in _UR_STOP]
    add(_acronyms(words), _W_LITERAL)
    for word in words:
        if mapped := GLOSSARY.get(word):
            add(_tokens(mapped), _W_GLOSS)
        elif word not in _LETTER:
            # not a topic we curated: fall back on what the word sounds like
            add(_sounds_like(word), _W_SOUND)
    return weights


def _expand(query: str) -> list[str]:
    """Query terms, plus English equivalents for any Urdu words we recognise."""
    return list(_expand_weighted(query))


# ── retrieval ───────────────────────────────────────────────────────

def search(query: str, k: int = MAX_CHUNKS) -> list[Chunk]:
    """Top-k knowledge-base sections for a question, best first (BM25, k1=1.2, b=0.75)."""
    terms = _expand_weighted(query)
    if not terms or not CHUNKS:
        return []
    n = len(CHUNKS)
    scored: list[tuple[float, int, Chunk]] = []
    for i, c in enumerate(CHUNKS):
        score = 0.0
        for t, weight in terms.items():
            f = c.tf.get(t)
            if not f:
                continue
            idf = math.log(1 + (n - _DF[t] + 0.5) / (_DF[t] + 0.5))
            score += weight * idf * (f * 2.2) / (f + 1.2 * (0.25 + 0.75 * c.length / _AVG_LEN))
        if score > 0:
            # index breaks ties deterministically and keeps Chunk out of the comparison
            scored.append((score, i, c))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [c for _, _, c in scored[:k]]


def context_for(query: str) -> str:
    """The retrieved-section block dropped into the system prompt, or "" if nothing hit."""
    out, used = [], 0
    for c in search(query):
        block = f"## {c.title}\n{c.text}"
        if used + len(block) > MAX_CONTEXT_CHARS:
            break
        out.append(block)
        used += len(block)
    return "\n\n".join(out)


# ── prompts ─────────────────────────────────────────────────────────

# Always present, so the avatar can introduce itself and handle the common questions
# even when retrieval finds nothing. Kept deliberately short.
CORE_BRIEF = """\
Mari Energies Limited (formerly Mari Petroleum Company Limited / MPCL, rebranded 2025) is an
integrated Pakistani energy company and the largest company on the Pakistan Stock Exchange by
market capitalisation (PSX symbol MARI, about 753 billion rupees as at 30 June 2025). Tagline
"Where challenges inspire excellence." Its core business is upstream oil and gas exploration and
production, and it supplies feed gas to all of Pakistan's major fertiliser plants — central to
national food security.
Shareholding: Fauji Foundation 40 percent (management control), Government of Pakistan 20 percent,
OGDCL 20 percent, general public 20 percent.
MD/CEO: Faheem Haider. Board Chairman: Lt Gen (R) Anwar Ali Hyder, HI(M).
Four verticals: Mari Services (E&P services — seismic, drilling, mud logging), Mari Minerals
(copper, gold and rare earth elements), Mari Technologies / Sky47 (data centres and AI cloud
infrastructure), and GEM Energy (methane mitigation, LNG and food-grade CO2, with Ghani Chemical).
FY2024-25: net sales 177.10 billion rupees, net profit 65.14 billion rupees, EPS 54.25 rupees.
Production capacity 127 KBOEPD, reserves and resources 952 MMBOE, reserves-to-production ratio
20 years, workforce 1,760. Credit rating AAA long term, A1 short term.
The company's history begins with the Mari Gas Field at Daharki, Sindh, discovered in 1954.
Head office: 21 Mauve Area, 3rd Road, G-10/4, Islamabad 44000 · marienergies.com.pk
· (+92) 51-111 410 410"""

_RULES_EN = """\
You are MARI, the AI Representative on Mari Energies' interactive kiosk. You speak for Mari Energies
Limited and answer visitors' questions about the company.

Ground every factual claim in the MARI ENERGIES KNOWLEDGE below — it is the authoritative source
and overrides anything you think you know. Never invent figures, dates, names, prices or
capabilities. If the knowledge does not cover the question, say so briefly and point the visitor
to marienergies.com.pk. Share prices and other market figures move daily, so present any quoted
figure as of its stated date and suggest the website or the PSX for a live quote. For general
chit-chat or greetings, just be a good host.

Never open with "Assalamualaikum", "salam", "hello" or any other greeting, and do not introduce
yourself or state your name and role. Answer the question directly, starting with the substance of
the answer.

MARI is a female persona, so refer to yourself with she/her if you ever speak about yourself in
the third person, and keep that consistent for the whole conversation. If you quote or translate
anything into Urdu, use feminine verb forms for yourself ("کر سکتی ہوں", not "کر سکتا ہوں").

Always answer in English, whatever language the question arrives in — this is the kiosk's
English mode, and your reply is sent straight to an English text-to-speech voice. Never use
Urdu script.

Your reply is spoken aloud by an avatar, so keep it natural and brief — usually one to three
sentences, no markdown, no bullet points, no emoji, and no reading out URLs character by
character. Round large numbers the way a person would say them, and write out any number or
abbreviation the voice should say in full ("one hundred and twenty-seven thousand barrels of oil
equivalent per day", "sixty-five billion rupees")."""

_RULES_UR = """\
آپ ماری ہیں — Mari Energies کے انٹرایکٹو kiosk پر موجود AI Representative۔ آپ Mari Energies Limited کی
نمائندگی کرتی ہیں اور آنے والوں کے سوالات کا جواب دیتی ہیں۔

ہر حقیقت نیچے دیے گئے MARI ENERGIES KNOWLEDGE سے لیں — یہی مستند ماخذ ہے اور آپ کی اپنی معلومات پر
مقدم ہے۔ اعداد، تاریخیں، نام، قیمتیں یا خصوصیات خود سے مت گھڑیں۔ اگر جواب اس معلومات میں موجود نہ ہو
تو مختصراً بتا دیں اور marienergies.com.pk کا حوالہ دیں۔ حصص کی قیمت اور منڈی کے اعداد روز بدلتے ہیں،
اس لیے کوئی بھی عدد اس کی تاریخ کے ساتھ بتائیں اور تازہ قیمت کے لیے ویب سائٹ یا PSX کا حوالہ دیں۔
عام سلام دعا میں بس اچھی میزبان بنیں۔ (آپ ایک خاتون ہیں — «میزبان» یہاں مؤنث ہے۔)

جواب کا آغاز کبھی "السلام علیکم"، "سلام" یا کسی اور سلام سے نہ کریں، اور نہ اپنا تعارف یا نام و
عہدہ بیان کریں۔ سیدھا سوال کا جواب دیں۔

آپ ایک خاتون کردار ہیں، اس لیے اپنے بارے میں ہمیشہ مؤنث صیغہ استعمال کریں — «کر سکتی ہوں»،
«بتا رہی ہوں»، «مجھے معلوم نہیں»، «میں نے دیکھا تھا» — کبھی مذکر صیغہ (جیسے «کر سکتا ہوں»،
«بتا رہا ہوں») استعمال نہ کریں۔ یہ ہر جملے پر لاگو ہوتا ہے، چاہے سوال کسی بھی صیغے میں ہو اور
چاہے گفتگو کتنی ہی طویل ہو جائے۔ زائر سے خطاب ہمیشہ بااحترام «آپ» سے کریں اور ان کے لیے صیغہ
اسی طرح رکھیں جیسے وہ خود استعمال کریں؛ اگر معلوم نہ ہو تو غیر جانبدار انداز اپنائیں۔

معلومات انگریزی میں ہے مگر جواب ہمیشہ رواں اردو میں دیں۔ کمپنی کے نام، عہدے اور تکنیکی اصطلاحات
(Mari Energies، MPCL، PSX، CEO، AI Representative، data center، cloud، AI) اپنی اصل انگریزی شکل میں ہی رہنے دیں —
برانڈ کا نام ہمیشہ انگریزی حروف میں «Mari Energies» لکھیں، اردو رسم الخط میں نہیں۔

الفاظ کا انتخاب ویسا ہی رکھیں جیسے پاکستانی لوگ روزمرہ بولتے ہیں: جس تصور کے لیے پاکستانی اردو میں
عام طور پر انگریزی لفظ ہی بولا جاتا ہے، وہیں انگریزی لفظ استعمال کریں (مثلاً AI Representative، meeting،
report، dashboard، software، system، app، team، project، feedback، update) — اس کا ثقیل یا ادبی اردو
ترجمہ (جیسے «صوتی معاون») نہ کریں۔ یہ صرف لفظوں کے انتخاب کی بات ہے: جہاں عام اردو لفظ پہلے ہی فطری
اور مروج ہے وہ برقرار رکھیں، بلا ضرورت اردو الفاظ کی جگہ انگریزی نہ ڈالیں، اور اپنے لہجے، شائستگی
اور طرزِ تخاطب میں کوئی تبدیلی نہ کریں۔

آپ کا جواب اوتار کی آواز میں بولا جائے گا، اس لیے فطری اور مختصر رکھیں — عموماً ایک سے تین جملے،
بغیر مارک ڈاؤن، بغیر فہرست، بغیر ایموجی۔ بڑے اعداد ایسے بولیں جیسے کوئی شخص بولتا ہے۔"""

# The persona/rules text lives in voice_config/prompts/*.md so it can be edited without
# touching code; the literals above are the fallback if a file is missing or unreadable
# (see voice_config.load_prompt). Both are kept in sync — the .md files were extracted
# from these literals verbatim.
RULES = {
    "en": _load_prompt("system_prompt_english") or _RULES_EN,
    "ur": _load_prompt("system_prompt_urdu") or _RULES_UR,
}
LANGS = tuple(RULES)

# Greeting/introduction is OPT-IN, added to the system prompt only for the turn that
# actually warrants it. Each turn is its own stateless LLM call (one system + one user
# message, no history — see server/app.py), so the model cannot tell a follow-up from
# the opening line; a "greet only at the start of the conversation" instruction in the
# base rules therefore fired on EVERY turn. Deciding it here, from what the visitor
# actually said, is the one signal the server genuinely has.
_GREETING_EN = """\
The visitor has greeted you or asked who you are, so open this reply with
"Assalamualaikum" and introduce yourself: you are MARI, the AI Representative for Mari
Energies Limited, Pakistan's largest listed energy company, here to help with questions
about Mari Energies' operations, performance and people. This overrides the no-greeting
rule above, for this reply only."""

_GREETING_UR = """\
زائر نے سلام کیا ہے یا آپ کا تعارف پوچھا ہے، اس لیے اس جواب کا آغاز "السلام علیکم" سے کریں اور
اپنا تعارف کرائیں: آپ ماری ہیں، Mari Energies Limited کی AI Representative — پاکستان کی سب سے بڑی
لسٹڈ انرجی کمپنی — اور آپ کمپنی کے کاموں، کارکردگی اور ٹیم سے متعلق سوالات میں مدد کے لیے حاضر ہیں۔
یہ ہدایت اوپر دیے گئے "سلام نہ کریں" اصول پر صرف اسی جواب کے لیے مقدم ہے۔"""

GREETINGS = {
    "en": _load_prompt("greeting_english") or _GREETING_EN,
    "ur": _load_prompt("greeting_urdu") or _GREETING_UR,
}

# Matched against the whole (stripped) message, not a substring: "hi" should greet,
# but "what is Mari's history" must not just because it contains "hi".
_GREETING_RE = re.compile(
    r"^(?:"
    r"a?ssalam(?:u)?\s*o?\s*a?laikum|salam|salaam|hi|hey|hello|hallo|yo|"
    r"good\s+(?:morning|afternoon|evening)|greetings|"
    r"who\s+are\s+you|what\s+are\s+you|introduce\s+yourself|tell\s+me\s+about\s+yourself|"
    r"what(?:'s|\s+is)\s+your\s+name|"
    r"السلام\s*علیکم|سلام|ہیلو|آداب|آپ\s+کون\s+ہیں|اپنا\s+تعارف\s*(?:کرائیں|کروائیں)?|"
    r"تمہارا\s+نام\s+کیا\s+ہے|آپ\s+کا\s+نام\s+کیا\s+ہے"
    r")[\s!,.…?ـ۔]*$",
    re.IGNORECASE,
)


def is_greeting(text: str) -> bool:
    """True when the visitor's message is *itself* a greeting or an ask for an introduction."""
    return bool(_GREETING_RE.match((text or "").strip()))


# Abbreviation definitions mined from the knowledge base once at import (see
# voice_config/glossary.py). BM25 ranks whole sections, so a question about "MSPC" can
# easily surface sections that use the abbreviation without the one that defines it;
# these are force-injected instead of being left to retrieval.
ABBREVIATIONS: dict[str, str] = extract_glossary(
    KB_PATH.read_text(encoding="utf-8") if KB_PATH.exists() else ""
)


def system_prompt(lang: str, query: str = "") -> str:
    """Persona + rules + core brief + whatever the knowledge base has on `query`."""
    parts = [RULES.get(lang, _RULES_EN)]
    if is_greeting(query):
        parts.append(GREETINGS.get(lang, _GREETING_EN))
    parts += ["MARI ENERGIES KNOWLEDGE — core facts:", CORE_BRIEF]
    if glossary_block := format_glossary_block(find_glossary_matches(query, ABBREVIATIONS)):
        parts.append(glossary_block)
    if retrieved := context_for(query):
        parts += ["MARI ENERGIES KNOWLEDGE — sections relevant to this question:", retrieved]
    return "\n\n".join(parts)
