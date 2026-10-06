"""The Kokoro English voice: every Uplift fix that makes sense in English, without Urdu script.

With APP_EN_TTS=remote the English reply goes to Kokoro, which used to skip normalization
entirely: Pakistani names came out American, "Mari" lost its ڑ, "50kW" was read as
letters, "65bn" as "65 BN". Uplift's fixes respell names in Urdu script, which Kokoro
cannot read, so Kokoro gets inline pronunciations ("[Kazmi](/kˈaːzmi/)") instead — a
syntax the live server was checked to honour ("[Kazmi](/hˈɛloʊ/)" was spoken "Hello").
"""

from __future__ import annotations

import asyncio
import re

import pytest

from server import normalization as N
from server.kokoro_lexicon import KOKORO_ALIASES, KOKORO_IPA, KOKORO_PLAIN

# hexgrad/Kokoro-82M config.json "vocab": a phoneme outside it is silently dropped.
KOKORO_VOCAB = set(
    ' !"(),.:;?AIOQSTWYabcdefhijklmnopqrstuvwxyzæçðøŋœɐɑɒɔɕɖəɚɛɜɟɡɣɤɥɨɪɯɰɲɳɴɸɹɻɽɾʁʂʃʈʊʋʌʎʒʔʝʣʤʥʦʧʨʰʲˈˌː̃βθχᵊᵝᵻ—“”…→↓↗↘ꭧ'
)
_ARABIC = re.compile(r"[\u0600-\u06ff]")


def kokoro(text: str) -> str:
    return N.normalize_for_tts(text, "en", "kokoro")


# ── the lexicon ─────────────────────────────────────────────────────

def test_every_phoneme_is_one_kokoro_can_say() -> None:
    for word, ipa in KOKORO_IPA.items():
        unknown = {c for c in ipa if c not in KOKORO_VOCAB}
        assert not unknown, (word, unknown)


def test_every_pakistani_word_the_uplift_tables_know_has_a_kokoro_pronunciation() -> None:
    """One sweep, so a person or place added for Uplift fails here until Kokoro has it too."""
    words = set(N._WORD_FORMS)
    for table in (N._PLACES, N._PROGRAMMES, N._PARTS):
        for key in table:
            words |= {key} if key in KOKORO_IPA else set(re.split(r"[\s-]+", key))
    missing = {w for w in words if w not in KOKORO_IPA and w not in KOKORO_PLAIN
               and w not in ("e",)}
    assert not missing, sorted(missing)


def test_aliases_point_at_real_entries() -> None:
    assert set(KOKORO_ALIASES.values()) <= set(KOKORO_IPA)


def test_the_american_voice_never_gets_phonemes_it_mishears() -> None:
    """Round-tripped: ɾ was heard as a flapped t ("Karachi" → "Katachi"), ʋ as v, and the
    retroflex stops ʈ ɖ garbled the word ("Ghotki" → "Ghorki")."""
    for word, ipa in KOKORO_IPA.items():
        assert not set(ipa) & set("ɾʋʈɖ"), word


# ── what Kokoro receives ────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    [
        "Assalamualaikum! Welcome to MariEnergies, I am Maryam.",
        "Board Chairman: Lt. Gen. Anwar Ali Hyder, HI(M), (Retd).",
        "Members: Syed Bakhtiyar Kazmi, Ayla Majid and Zafar Abbas, at Daharki, Sindh.",
        "Sky47 runs Huawei Ascend NPU clusters at 50kW per rack.",
    ],
)
def test_no_urdu_script_ever_reaches_kokoro(text: str) -> None:
    assert not _ARABIC.search(kokoro(text))


def test_mari_is_said_with_the_retroflex_flap() -> None:
    said = kokoro("Welcome to Mari Energies and MariEnergies, ticker MARI.")
    assert said.count("[Mari](/mˈaːɽi/)") == 2 and "[MARI](/mˈaːɽi/)" in said


def test_a_full_name_and_a_surname_alone_are_said_the_same_way() -> None:
    full = kokoro("Syed Bakhtiyar Kazmi chairs it.")
    alone = kokoro("Ask Kazmi about it.")
    assert "[Syed](/sˈɛːjəd/) [Bakhtiyar](/bˌəxtɪjˈaːr/) [Kazmi](/kˈaːzmi/)" in full
    assert "[Kazmi](/kˈaːzmi/)" in alone


@pytest.mark.parametrize("text", ["Ali Baba trading", "Khan Research Labs", "The Malik Road site"])
def test_common_name_words_only_fire_inside_a_full_name(text: str) -> None:
    assert kokoro(text) == text


def test_the_salam_returned_and_offered() -> None:
    said = kokoro("Walaikum Assalam! And Assalam-o-Alaikum to you.")
    assert "[Walaikum Assalam](/wəlˈɛːkʊm əssəlˈaːm/)" in said
    assert "(/ʌssəlˈaːmʊ ʌlˈɛːkʊm/)" in said


def test_chairman_line_keeps_rank_order_and_drops_the_honour() -> None:
    said = kokoro("Board Chairman: Lt. Gen. Anwar Ali Hyder, HI(M), (Retd)")
    assert said.startswith("Board Chairman: Retired [Lieutenant](/lɛftˈɛnənt/) General "
                           "Anwar [Ali](/ˈəli/) [Hyder](/")
    assert "Imtiaz" not in said and "Military" not in said
    assert "HI(M)" not in said and "(Retd)" not in said


def test_report_shapes_kokoro_misread_are_fixed() -> None:
    """Probed on the live voice: "65 BN", "F2024-25", "KBOAPD"."""
    said = kokoro("PKR 65bn in FY2024-25, 127 KBOEPD and 100 MMSCFD, joined 24/06/2022.")
    assert "sixty five billion rupees" in said
    assert "financial year twenty twenty four to twenty five" in said
    assert "thousand barrels of oil equivalent per day" in said
    assert "million standard cubic feet per day" in said
    assert "June" in said


def test_plain_capitals_are_left_for_kokoro_to_spell() -> None:
    """Kokoro reads "SECP" correctly; the Uplift hyphenation turned "U-E-T" into "UIT"."""
    said = kokoro("The SECP, UET and ACCA, rated AAA.")
    assert "SECP" in said and "UET" in said and "ACCA" in said and "-" not in said
    assert "triple A" in said


def test_units_are_said_by_name() -> None:
    assert "fifty kilowatts per rack" in kokoro("up to 50kW per rack")


def test_a_name_mixes_pronunciations_with_words_said_as_written() -> None:
    """Audited: "[Zafar](/…/)" was heard as "zephyr", plain "Zafar" was heard right."""
    assert kokoro("Zafar Abbas chairs it.") == "Zafar [Abbas](/əbbˈaːs/) chairs it."


def test_audited_words_that_sound_better_plain_are_left_plain() -> None:
    assert kokoro("The Chowk in Lahore near Okara.") == "The Chowk in Lahore near Okara."


def test_digits_inside_a_pronunciation_are_never_spelled_out() -> None:
    """Placeholders keep the IPA away from the number pass and the slash rule."""
    said = kokoro("Spinwam-1 in North Waziristan, 12 wells.")
    assert "[Spinwam](/spˌɪnwˈaːm/) one" in said and "twelve wells" in said


# ── wiring ──────────────────────────────────────────────────────────

def test_speech_sends_kokoro_its_own_spoken_form(monkeypatch) -> None:
    from server import providers
    from server.agent import speech
    from server.providers.tts import KokoroRemoteTTS

    sent: list[str] = []

    async def synthesize(self, text: str):
        sent.append(text)
        return b"x", "audio/mpeg"

    monkeypatch.setattr(KokoroRemoteTTS, "synthesize", synthesize)
    monkeypatch.setattr(providers, "get_tts_provider",
                        lambda lang, avatar="female": KokoroRemoteTTS(base="http://k.test", voice="af_heart"))
    asyncio.run(speech.speak("Faheem Haider says up to 50kW per rack.", "en"))
    assert sent == ["[Faheem](/fəhˈiːm/) [Haider](/hˈɛːdər/) says up to fifty kilowatts per rack."]


def test_uplift_is_untouched_by_the_engine_switch() -> None:
    text = "Faheem Haider of Mari Energies, 50kW per rack."
    assert N.normalize_for_tts(text, "en") == N.normalize_for_tts(text, "en", "uplift")
    assert "فہیم حیدر" in N.normalize_for_tts(text, "en")
