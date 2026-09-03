export type Lang = "en" | "ur";

export const COPY = {
  en: {
    dir: "ltr",
    idle: "Tap to speak",
    loading: "Loading MARI…",
    listening: "Listening…",
    thinking: "Thinking…",
    speaking: "Speaking",
    paused: "Paused",
    chat: "Chat",
    placeholder: "Ask anything",
    you: "You",
    mari: "MARI",
    micDenied: "Microphone access is needed to talk to MARI.",
    noSpeech: "Didn't catch that — tap the mic to try again.",
  },
  ur: {
    dir: "rtl",
    idle: "بولنے کے لیے دبائیں",
    loading: "ماری لوڈ ہو رہی ہے…",
    listening: "سن رہی ہے…",
    thinking: "سوچ رہی ہے…",
    speaking: "بول رہی ہے",
    paused: "رکی ہوئی",
    chat: "گفتگو",
    placeholder: "کچھ بھی پوچھیں",
    you: "آپ",
    mari: "ماری",
    micDenied: "ماری سے بات کرنے کے لیے مائیکروفون کی اجازت درکار ہے۔",
    noSpeech: "سمجھ نہیں آیا — دوبارہ کوشش کے لیے مائیک دبائیں۔",
  },
} as const;
