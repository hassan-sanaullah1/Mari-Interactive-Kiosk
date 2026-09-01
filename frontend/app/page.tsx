"use client";

import { useCallback, useEffect, useState } from "react";
import styles from "./page.module.css";
import AvatarStage from "@/components/AvatarStage";
import ChatPanel from "@/components/ChatPanel";
import ControlDock from "@/components/ControlDock";
import LanguageBar from "@/components/LanguageBar";
import LoadingScreen from "@/components/LoadingScreen";
import { useVoiceSession } from "@/hooks/useVoiceSession";
import { applyTheme, readTheme, type Theme } from "@/lib/theme";
import { COPY, type Lang } from "@/lib/i18n";

export default function Page() {
  const [lang, setLang] = useState<Lang>("en");
  const [theme, setTheme] = useState<Theme>("dark");
  const [chatOpen, setChatOpen] = useState(false);
  // False until the avatar reports it has loaded AND is posed — see
  // AvatarModel's onReady. The rest of the page mounts and loads underneath
  // regardless (the background art, the voice session, the avatar's own glTF
  // fetch all proceed in parallel); LoadingScreen just sits on top of all of
  // it at the highest z-index until this flips.
  const [avatarReady, setAvatarReady] = useState(false);
  const onAvatarReady = useCallback(() => setAvatarReady(true), []);

  const voice = useVoiceSession(lang);
  const t = COPY[lang];

  // Pick up the theme the inline script in layout.tsx already applied.
  useEffect(() => {
    setTheme(readTheme());
  }, []);

  const changeTheme = (t: Theme) => {
    setTheme(t);
    applyTheme(t);
  };

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const errorText =
    voice.error === "mic-denied" ? t.micDenied : voice.error === "no-speech" ? t.noSpeech : voice.error ? t.noSpeech : null;

  return (
    <main className={styles.root}>
      {/* The supplied artwork — real image assets, not a CSS recreation.
          <picture> art-directs it: phones get the portrait crop and never
          download the landscape one (and vice versa). */}
      <picture>
        <source srcSet="/mobile_background.png" media="(max-width: 760px)" />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className={styles.bg} src="/background.png" alt="" fetchPriority="high" />
      </picture>
      {/* The 3D presenter. `mode` drives her body animation (idle → listening →
          talking); her mouth is driven separately by the Audio2Face frames that
          arrive alongside the reply audio. */}
      <AvatarStage mode={voice.mode} levelRef={voice.levelRef} onReady={onAvatarReady} />

      <LanguageBar
        className={styles.langBar}
        lang={lang}
        onLang={setLang}
        theme={theme}
        onTheme={changeTheme}
      />

      <ControlDock
        className={styles.dock}
        lang={lang}
        mode={voice.mode}
        active={voice.active}
        paused={voice.paused}
        levelRef={voice.levelRef}
        onToggle={voice.toggle}
        onStop={voice.endAndClear}
        onTogglePause={voice.togglePause}
      />

      <ChatPanel
        lang={lang}
        open={chatOpen}
        onOpen={() => setChatOpen(true)}
        onClose={() => setChatOpen(false)}
        messages={voice.messages}
        partial={voice.partial}
        onSend={voice.sendText}
      />

      {errorText && (
        <div className={styles.toast} role="alert" onClick={voice.clearError}>
          {errorText}
        </div>
      )}

      <LoadingScreen lang={lang} ready={avatarReady} />
    </main>
  );
}
