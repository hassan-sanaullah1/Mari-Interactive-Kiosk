"""How the Kokoro English voice should say Pakistani words, as Kokoro IPA.

Kokoro reads Latin script with American phonetics, so "Kazmi", "Daharki" and the brand
"Mari" come out as English words. Uplift was fixed by respelling them in Urdu script,
which Kokoro cannot read. Kokoro instead accepts an inline pronunciation, ``[word](/IPA/)``,
and its phoneme set has the sounds these words need: the retroflex flap ɽ of «ماڑی», q,
x, ɣ and the aspirated kʰ and tʰ.

Generated once from a Hindi-script spelling of each word with ``espeak-ng -v hi --ipa``,
then corrected by hand where espeak gets the Pakistani form wrong (ڑ written "r.", the
"Ah-mad" and "Sai-yed" vowels, the silent w of "dastarkhwan"). No runtime espeak needed.

Round-tripped on af_heart, some Hindi phonemes do not survive the American voice, so they
are written as the nearest sound it does say: the tap ɾ was heard as a flapped t
("Rasheed" → "Tashid", "Karachi" → "Katachi"), so it is r; ʋ was heard as v ("Anwar" →
"Unved"), so it is w; the retroflex stops ʈ ɖ garbled the word ("Ghotki" → "Ghorki",
"Quetta" → "quite on"), so they are t d — which is how Pakistani English says t and d
anyway. ɽ is kept: it is the «ڑ» in ماڑی, and the voice says it.

Every entry was then audited on af_heart — a carrier sentence synthesized with the IPA and
with the plain spelling, both transcribed. Stressed ə was heard as "e" ("Hasan" → "hessen",
"Malik" → "melik"), so those names use ʌ; where the plain spelling won outright the word
moved to ``KOKORO_PLAIN``. Pakistani forms the transcriber marks as misses were kept
deliberately: "Ramzan" for Ramadan, "Haider-abad", "Hazur", "Nur", "Zahbi" for Dhabi.

Keys are the Latin spellings the reply uses; server/normalization.py matches them whole.
Brand and foreign names that English already reads correctly (Paramount, Clifton, Engro,
Portia …) are deliberately absent — see ``KOKORO_PLAIN``.
"""

from __future__ import annotations

KOKORO_IPA: dict[str, str] = {
    # ── The kiosk's own words ──
    "Mari": "mˈaːɽi",
    "Maryam": "mˈərjəm",
    "Hamza": "hˈəmzaː",
    "Assalamualaikum": "ʌssəlˈaːmʊ ʌlˈɛːkʊm",
    "Walaikum Assalam": "wəlˈɛːkʊm əssəlˈaːm",
    "Pakistan": "pˌaːkɪstˈaːn",
    "Pakistani": "pˌaːkɪstˈaːni",
    "Pakistanis": "pˌaːkɪstaːnˈiːz",
    # Pakistani (British) "lef-tenant", not the American "loo-tenant".
    "Lieutenant": "lɛftˈɛnənt",

    # ── People ──
    "Abbas": "əbbˈaːs", "Abdullah": "ˌəbdʊllˈaːh", "Abid": "ˈaːbɪd",
    "Ahmad": "ˈəhməd", "Ahmed": "ˈəhməd", "Ali": "ˈəli",
    "Aamir": "ˈaːmɪr", "Ashraf": "ˈʌʃrəf", "Asif": "ˈaːsɪf", "Aslam": "ˈʌsləm",
    "Ayla": "ˈaːɪlaː", "Afzal": "ˈʌfzəl", "Bakhsh": "bˈəxʃ", "Bakhtiyar": "bˌəxtɪjˈaːr",
    "Faheem": "fəhˈiːm", "Ghulam": "ɣʊlˈaːm", "Haider": "hˈɛːdər", "Hamed": "hˈaːmɪd",
    "Hamid": "hˈaːmɪd", "Hasan": "hˈʌsən", "Hayat": "həjˈaːt", "Hazoor": "hʊzˈuːr",
    "Hussain": "hʊsˈɛːn", "Hyder": "hˈɛːdər", "Imtiaz": "ˌɪmtɪjˈaːz", "Ishfaq": "ɪʃfˈaːq",
    "Kazmi": "kˈaːzmi", "Khalid": "xˈaːlɪd",
    "Lak": "lˈʌk", "Majid": "məʤˈiːd", "Malik": "mˈʌlɪk", "Mehmood": "məhmˈuːd",
    "Muhammad": "mʊhˈəmməd", "Mushtaq": "mʊʃtˈaːq", "Nabeel": "nəbˈiːl", "Nabi": "nˈəbi",
    "Nadeem": "nədˈiːm", "Niaz": "nɪjˈaːz", "Rasheed": "rəʃˈiːd",
    "Raza": "rˈʌzaː", "Sajjad": "səʤʤˈaːd", "Salim": "səlˈiːm", "Seema": "sˈiːmaː",
    "Shaheen": "ʃaːhˈiːn", "Shahzad": "ʃɛːhzˈaːd", "Sumair": "sʊmˈɛːr",
    "Syed": "sˈɛːjəd", "Yaqoob": "jaːqˈuːb",

    # ── Military honours ──
    "Hilal-e-Imtiaz": "hɪlˈaːleː ˌɪmtɪjˈaːz",
    "Sitara-e-Imtiaz": "sɪtˈaːreː ˌɪmtɪjˈaːz",
    "Tamgha-e-Imtiaz": "tˈəmɣeː ˌɪmtɪjˈaːz",
    "Nishan-e-Imtiaz": "nɪʃˈaːneː ˌɪmtɪjˈaːz",

    # ── Fields, formations and wells ──
    "Daharki": "dˈəhərki", "Sujawal": "sʊʤˈaːwəl", "Ghotki": "ɡˈoːtki",
    "Kandhkot": "kˌʌndkˈoːt", "Sachal": "sˈəʧəl",
    "Halini": "hˈaːlɪni", "Zarghun": "zˌərɣˈuːn", "Pirkoh": "pˌiːrkˈoːh",
    "Ghazij": "ɣaːzˈiːʤ", "Habib": "həbˈiːb",
    "Rahi": "rˈaːhi", "Mughal": "mˈʊɣəl", "Rani": "rˈaːni", "Sui": "sˈuːi",
    "Samanasuk": "sˌəmaːnˈaːsʊk", "Hangu": "hˈəŋɡuː",
    "Dughan": "dʊɣˈaːn", "Chiltan": "ʧˈɪltən", "Spinwam": "spˌɪnwˈaːm", "Shewa": "ʃˈeːwaː",
    "Shawal": "ʃəwˈaːl", "Maiwand": "mɛːwˈənd", "Pateji": "pətˈeːʤi", "Jhim": "ʤˈɪm",


    # ── Provinces, cities and regions ──
    "Sindh": "sˈɪnd", "Punjab": "pənʤˈaːb", "Balochistan": "bˌəloːʧɪstˈaːn",
    "Pakhtunkhwa": "pˌəxtuːnxˈaː", "Islamabad": "ˌɪslaːmaːbˈaːd",
    "Karachi": "kərˈaːʧi", "Karakoram": "qərˈaːqərəm",
    "Suleiman": "sˌʊleːmˈaːn",
    "Bannu": "bˈənnũ", "Daud": "daːˈuːd",
    "Diq": "dˈɪk", "Ziarat": "zɪjˈaːrət",
    "Quetta": "kwˈɛtə", "Hyderabad": "hˌɛːdəraːbˈaːd",
    "Dadu": "dˈaːduː", "Kabirwala": "kˌəbiːrwˈaːlaː", "Khipro": "kʰˈɪproː",
    "Sukkur": "sˈəkkʰər", "Peshawar": "peːʃˈaːwər", "Rawalpindi": "rˌaːwəlpˈɪɳdi",
    "Makran": "mˌəkrˈaːn", "Mach": "mˈʌʧʰ",
    "Nandpur": "nˈʌndpʊr", "Jinnah": "ʤɪnnˈaːh",
    "Azadi": "aːzˈaːdi", "Tuzgi": "tˈuːzɡi", "Ammuri": "əmˈuːri",

    # ── Programmes, banks and partners ──
    "Dastarkhwan": "dˌʌstərxˈaːn", "Dastarkhawn": "dˌʌstərxˈaːn", "Roshan": "rˈoːʃən",
    "Mustaqbil": "mʊstəqbˈɪl", "Dost": "dˈoːst",
    "Umeed": "ʊmmˈiːd", "Gharonda": "ɡərˈɔ̃daː", "Sehar": "sˈəhər", "Naya": "nˈəjaː",
    "Fauji": "fˈɔːʤi", "Askari": "ˈəskəri", "Faysal": "fˈɛːsəl",
    "Alfalah": "ˌəlfəlˈaːh", "Baraka": "bərˈəkaː", "Alhaj": "ˌəlhˈaːʤ",
    "Noor": "nˈuːr", "Kehkashan": "kəhkəʃˈãː", "Panni": "pˈʌnni",
    "Fatima": "fˈaːtɪmaː", "Ramadan": "rəmzˈaːn", "Pak": "pˈaːk", "Arab": "ˈərəb",
    "Turk": "tˈʊrk", "Noor-e-Sehar": "nˈuːreː sˈəhər",
    "Dad": "dˈaːd", "Hilal": "hɪlˈaːl", "Abu": "ˈəbuː", "Dhabi": "zˈəhbi",
    "Attock": "ˈətək", "BankIslami": "bˈæŋk ɪslˈaːmi", "EZShifa": "ˈiː zˈɛd ʃˈɪfaː",
}

# Spellings the reply uses for the same word.
KOKORO_ALIASES: dict[str, str] = {
    "Mariam": "Maryam", "Marium": "Maryam", "Hamzah": "Hamza", "MARI": "Mari",
}

# In the Uplift tables but read correctly by an English voice as written.
KOKORO_PLAIN: frozenset[str] = frozenset({
    "Mobile", "Corplink", "Portia", "Orient", "Paramount", "Stanvac", "Clifton", "Engro",
    "Esso", "Petroserv", "Infraavest", "Planetive",
    # Audited on af_heart (synthesize, transcribe, compare): the inline pronunciation turned
    # these into other words — "Zafar" → "zephyr", "Sheikh" → "shah", "Karak" → "tariq",
    # "Okara" → "our guide", "Chowk" → "chalk", "Kot" → "court" — and the plain spelling was
    # heard correctly. The ɽ of Okara, Sanghar, Kawagarh and Aligarh is lost with them.
    # On am_michael too: "[Anwar]" → "unward", "[Adil]" → "idol"; plain is right on both voices.
    "Anwar", "Adil",
    "Zafar", "Sheikh", "Karak", "Laghari", "Meezan", "Okara", "Bijjar", "Goru", "Sanghar",
    "Chowk", "Khel", "Lahore", "Khyber", "Kot", "Pab", "Kissan", "Janjua", "Nawaz",
    "Khan", "Thar", "Waziristan", "Kawagarh", "Aligarh", "Bhitai", "Sehat", "Ghani", "Al",
    "Noor-Sehar", "Reko", "Jhelum",
})
