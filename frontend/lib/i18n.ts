export type Lang = "en" | "ur";

/** Grammatical gender of the presenter on screen. See AvatarConfig. */
export type Gender = "f" | "m";

/**
 * UI copy.
 *
 * The Urdu entries below are the feminine forms. Urdu marks gender on verbs, so any
 * line describing what the presenter is *doing* has to agree with who is on screen —
 * and the male presenter was getting the feminine ones. Those lines are listed in
 * MASCULINE_UR and resolved by `uiCopy(lang, gender)`; everything else (an instruction
 * to the visitor, a label, the product's own name) is the same either way.
 *
 * Read it through `uiCopy`, never directly, so a new gendered line cannot slip in
 * ungendered.
 */
const COPY = {
  en: {
    idle: "Tap to speak",
    loading: "Loading MARI…",
    listening: "Listening…",
    thinking: "Thinking…",
    speaking: "Speaking",
    paused: "Paused",
    chat: "Chat",
    placeholder: "Ask anything",
    presenter: "Presenter",
    slowConnection: "Slow connection…",
    micDenied: "Microphone access is needed to talk to MARI.",
    noSpeech: "Didn't catch that - tap the mic to try again.",
  },
  ur: {
    idle: "بولنے کے لیے دبائیں",
    // "MARI is loading" — the product, not the presenter, so not gendered.
    loading: "ماری لوڈ ہو رہی ہے…",
    listening: "سن رہی ہے…",
    thinking: "سوچ رہی ہے…",
    speaking: "بول رہی ہے",
    paused: "رکی ہوئی",
    chat: "گفتگو",
    placeholder: "کچھ بھی پوچھیں",
    presenter: "پیشکار",
    slowConnection: "سست کنکشن…",
    micDenied: "ماری سے بات کرنے کے لیے مائیکروفون کی اجازت درکار ہے۔",
    noSpeech: "سمجھ نہیں آیا — دوبارہ کوشش کے لیے مائیک دبائیں۔",
  },
} as const;

/**
 * Keys fixed, values free. `as const` above would otherwise pin each value to its own
 * English literal, so the Urdu table would not be assignable to it — while the mapped
 * key set still makes a missing or misspelled line a type error.
 */
export type Copy = { readonly [K in keyof (typeof COPY)["en"]]: string };

/**
 * The Urdu lines that change with the presenter's gender: رہی → رہا, رکی → رکا.
 * Only the four that describe the presenter mid-turn.
 */
const MASCULINE_UR: Partial<Copy> = {
  listening: "سن رہا ہے…",
  thinking: "سوچ رہا ہے…",
  speaking: "بول رہا ہے",
  paused: "رکا ہوا",
};

/** The copy for this language and presenter. */
export function uiCopy(lang: Lang, gender: Gender = "f"): Copy {
  if (lang !== "ur" || gender === "f") return COPY[lang];
  return { ...COPY.ur, ...MASCULINE_UR };
}
