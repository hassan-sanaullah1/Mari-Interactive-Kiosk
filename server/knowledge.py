"""MARI · Voice — grounding knowledge for the LLM.

The avatar is a Sky47 kiosk assistant, so every reply has to come from
``sky47_knowledge_base.md`` rather than the model's own memory. That file is ~90 KB —
far too large to prepend to each turn on a latency-sensitive voice pipeline — so this
module does two things:

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

KB_PATH = Path(C.env("APP_KNOWLEDGE_FILE", str(C.ROOT / "sky47_knowledge_base.md")))

# How much retrieved material a single turn may carry. Roughly 1.5k tokens — enough
# for two or three sections, small enough that time-to-first-token stays kiosk-fast.
MAX_CHUNKS = 4
MAX_CONTEXT_CHARS = 6000
# Chunks longer than this are split so one giant section can't crowd out the rest.
MAX_CHUNK_CHARS = 2200


# ── chunking ────────────────────────────────────────────────────────

@dataclass
class Chunk:
    title: str      # "2. Data Center Facilities › 2.1 Overview of Facilities"
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
    "sky47", "pakistan", "company", "limited",
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
    "سی ای او": "ceo chief executive leadership",
    "اے آئی": "artificial intelligence gpu",
    "مصنوعی ذہانت": "artificial intelligence gpu",
    "جی پی یو": "gpu compute",
    "ای میل": "contact email",
    "ڈیٹا سینٹر": "data center facility campus",
    "اسلام آباد": "islamabad campus",
    "نیٹ ورک": "connectivity network carrier",
    "اپ ٹائم": "uptime availability sla",
}

GLOSSARY: dict[str, str] = {
    "ڈیٹا": "data center",
    "سینٹر": "data center facility",
    "کلاؤڈ": "cloud hosting",
    "سرور": "server infrastructure",
    "کمپنی": "company overview",
    "ادارہ": "company overview",
    "کیا": "overview",
    "ملکیت": "ownership shareholding stake",
    "مالک": "ownership shareholding parent",
    "حصص": "shareholding stake shareholders",
    "شیئر": "shareholding stake",
    "ماری": "mari energies technologies parent",
    "فوجی": "fauji foundation",
    "بانی": "establishment founded",
    "سربراہ": "ceo chief executive leadership",
    "چیئرمین": "chairman board",
    "قیادت": "leadership executive team",
    "انتظامیہ": "leadership management team",
    "ٹیم": "leadership team members",
    "رابطہ": "contact address email website",
    "پتہ": "contact address location",
    "فون": "contact phone",
    "ویب": "website contact",
    "خدمات": "services portfolio pillars",
    "سروس": "services portfolio pillars",
    "قیمت": "pricing billing cost",
    "بلنگ": "billing pricing models",
    "سیکیورٹی": "security cybersecurity secure",
    "حفاظت": "security safety compliance",
    "تحفظ": "data sovereignty security privacy",
    "کراچی": "karachi campus",
    "لاہور": "lahore campus",
    "شہر": "campus locations facilities",
    "شراکت": "partnership partners collaboration",
    "پارٹنر": "partnership partners collaboration",
    "سرٹیفکیٹ": "certification compliant standards",
    "سرٹیفیکیشن": "certification compliant standards",
    "معیار": "certification tier standards",
    "بجلی": "power infrastructure energy",
    "پاور": "power infrastructure energy",
    "توانائی": "power energy sector",
    "کولنگ": "cooling systems",
    "ٹھنڈا": "cooling systems",
    "انٹرنیٹ": "connectivity network bandwidth",
    "ملازمت": "careers jobs hiring team",
    "نوکری": "careers jobs hiring team",
    "افتتاح": "inauguration launch milestone",
    "لانچ": "launch inauguration milestone",
    "تاریخ": "timeline milestones date",
    "کب": "timeline milestones date launch",
    "منصوبہ": "project campus milestones",
    "صلاحیت": "capacity racks megawatt scale",
    "ریک": "racks capacity colocation",
    "وژن": "vision mission",
    "مشن": "vision mission",
    "مقصد": "vision mission purpose",
    "گاہک": "customers sectors use cases",
    "صارف": "customers sectors use cases",
    "شعبے": "target sectors use cases",
    "بینک": "financial services banking",
    "صحت": "healthcare sector",
    "حکومت": "government public sector",
    "حریف": "competitive positioning market",
    "مقابلہ": "competitive positioning market",
    "سپورٹ": "support noc 24/7",
    "مدد": "support noc 24/7",
}


def _expand(query: str) -> list[str]:
    """Query terms, plus English equivalents for any Urdu words we recognise."""
    terms = _tokens(query)
    rest = query
    for phrase, mapped in PHRASES.items():
        if phrase in rest:
            terms.extend(_tokens(mapped))
            rest = rest.replace(phrase, " ")
    for word in re.findall(r"[\u0600-\u06ff]+", rest):
        if mapped := GLOSSARY.get(word):
            terms.extend(_tokens(mapped))
    return terms


# ── retrieval ───────────────────────────────────────────────────────

def search(query: str, k: int = MAX_CHUNKS) -> list[Chunk]:
    """Top-k knowledge-base sections for a question, best first (BM25, k1=1.2, b=0.75)."""
    terms = _expand(query)
    if not terms or not CHUNKS:
        return []
    n = len(CHUNKS)
    scored: list[tuple[float, int, Chunk]] = []
    for i, c in enumerate(CHUNKS):
        score = 0.0
        for t in set(terms):
            f = c.tf.get(t)
            if not f:
                continue
            idf = math.log(1 + (n - _DF[t] + 0.5) / (_DF[t] + 0.5))
            score += idf * (f * 2.2) / (f + 1.2 * (0.25 + 0.75 * c.length / _AVG_LEN))
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
Sky47 Limited is Pakistan's leading sovereign digital infrastructure provider: Tier III/IV
certified, purpose-built data centers for cloud hosting, colocation, AI infrastructure and
cybersecurity. Tagline "Secure. Scalable. Sovereign."; mission "Powering Pakistan's Digital Future."
Ownership: Mari Technologies Limited holds 60% and management control; Mari Technologies is
wholly owned by Mari Energies Limited (PSX-listed, formerly Mari Petroleum / MPCL), so Mari
Energies is the ultimate parent. Paramount Ventures holds 30%, Capital Smart Technologies 10%.
CEO: Hassan Abbas. Chairman: Lt Gen (R) Anwar Ali Haider.
Campuses: Islamabad (Capital Smart City — cloud and AI live since 15 January 2026, data center
inauguration 21 July 2026), Karachi and Lahore (planned). 3,000+ racks and up to 50 MW combined.
Five service pillars: Sky47 Space (colocation), Sky47 Cloud (sovereign cloud), Sky47 Manage
(managed services), Sky47 Secure (cybersecurity), Sky47 AI (AI solutions and GPU-as-a-Service).
Head office: Building 1-C, Kohistan Road, F-8 Markaz, Islamabad 44000 · sky47.com.pk · info@sky47.com.pk"""

_RULES_EN = """\
You are MARI, the voice assistant on Sky47's interactive kiosk. You speak for Sky47 Limited and
answer visitors' questions about the company.

Ground every factual claim in the SKY47 KNOWLEDGE below — it is the authoritative source and
overrides anything you think you know. Never invent figures, dates, names, prices or
capabilities. If the knowledge does not cover the question, say so briefly and point the visitor
to sky47.com.pk or info@sky47.com.pk. For general chit-chat or greetings, just be a good host.

Always answer in English, whatever language the question arrives in — this is the kiosk's
English mode, and your reply is sent straight to an English text-to-speech voice. Never use
Urdu script.

Your reply is spoken aloud by an avatar, so keep it natural and brief — usually one to three
sentences, no markdown, no bullet points, no emoji, and no reading out URLs character by
character. Round large numbers the way a person would say them, and write out any number the
voice should say in full ("Tier three", "fifty megawatts")."""

_RULES_UR = """\
آپ ماری ہیں — Sky47 کے انٹرایکٹو کیوسک پر موجود صوتی معاون۔ آپ Sky47 Limited کی نمائندگی کرتی ہیں
اور آنے والوں کے سوالات کا جواب دیتی ہیں۔

ہر حقیقت نیچے دیے گئے SKY47 KNOWLEDGE سے لیں — یہی مستند ماخذ ہے اور آپ کی اپنی معلومات پر مقدم ہے۔
اعداد، تاریخیں، نام، قیمتیں یا خصوصیات خود سے مت گھڑیں۔ اگر جواب اس معلومات میں موجود نہ ہو تو مختصراً
بتا دیں اور sky47.com.pk یا info@sky47.com.pk کا حوالہ دیں۔ عام سلام دعا میں بس اچھی میزبان بنیں۔

معلومات انگریزی میں ہے مگر جواب ہمیشہ رواں اردو میں دیں۔ کمپنی کے نام، عہدے اور تکنیکی اصطلاحات
(Sky47، Mari Energies، CEO، data center، cloud، AI) اپنی اصل انگریزی شکل میں ہی رہنے دیں — برانڈ کا نام
ہمیشہ انگریزی حروف میں «Sky47» لکھیں، اردو رسم الخط یا اردو ہندسوں (اسکائی ۴۷) میں نہیں۔

آپ کا جواب اوتار کی آواز میں بولا جائے گا، اس لیے فطری اور مختصر رکھیں — عموماً ایک سے تین جملے،
بغیر مارک ڈاؤن، بغیر فہرست، بغیر ایموجی۔ بڑے اعداد ایسے بولیں جیسے کوئی شخص بولتا ہے۔"""

RULES = {"en": _RULES_EN, "ur": _RULES_UR}
LANGS = tuple(RULES)


def system_prompt(lang: str, query: str = "") -> str:
    """Persona + rules + core brief + whatever the knowledge base has on `query`."""
    parts = [RULES.get(lang, _RULES_EN), "SKY47 KNOWLEDGE — core facts:", CORE_BRIEF]
    if retrieved := context_for(query):
        parts += ["SKY47 KNOWLEDGE — sections relevant to this question:", retrieved]
    return "\n\n".join(parts)
