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
import { applyAvatar, readAvatar } from "@/lib/avatar";
import { DEFAULT_AVATAR, type AvatarId } from "@/components/avatar/models";
import { COPY, type Lang } from "@/lib/i18n";

export default function Page() {
  const [lang, setLang] = useState<Lang>("en");
  const [theme, setTheme] = useState<Theme>("dark");
  // Starts on the default rather than on the stored choice: this renders on the
  // server too, and reading localStorage during render would not match. The
  // effect below corrects it before the model is fetched.
  const [avatar, setAvatar] = useState<AvatarId>(DEFAULT_AVATAR);
  const [chatOpen, setChatOpen] = useState(false);
  // False until the avatar reports it has loaded AND is posed — see
  // AvatarModel's onReady. The rest of the page mounts and loads underneath
  // regardless (the background art, the voice session, the avatar's own glTF
  // fetch all proceed in parallel); LoadingScreen just sits on top of all of
  // it at the highest z-index until this flips.
  const [avatarReady, setAvatarReady] = useState(false);
  const onAvatarReady = useCallback(() => setAvatarReady(true), []);

  // The presenter goes in so the reply comes back in that rig's voice — the
  // toggle switches the voice with the model. Turns already in flight keep the
  // voice they started in; see run_reply's `avatar`.
  const voice = useVoiceSession(lang, avatar);
  const t = COPY[lang];

  // Pick up the theme the inline script in layout.tsx already applied, and the
  // stored presenter, which has no such script — see lib/avatar.ts.
  useEffect(() => {
    setTheme(readTheme());
    setAvatar(readAvatar());
  }, []);

  const changeTheme = (t: Theme) => {
    setTheme(t);
    applyTheme(t);
  };

  /**
   * Switching presenters re-arms the loading overlay, because it is a fresh
   * multi-megabyte download and a fresh parse. Without this the old rig stays
   * on screen, apparently frozen, until the new one is posed — and coming back
   * to a rig already in drei's cache still needs it, because `avatarReady` is
   * what un-hides the canvas and the new rig has not signalled it yet.
   */
  const changeAvatar = (id: AvatarId) => {
    if (id === avatar) return;
    setAvatarReady(false);
    setAvatar(id);
    applyAvatar(id);
  };

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const errorText =
    voice.error === "mic-denied" ? t.micDenied : voice.error === "no-speech" ? t.noSpeech : voice.error ? t.noSpeech : null;

  return (
    <main className={styles.root}>
      {/* The supplied artwork — real image assets, not a CSS recreation.
          Picked in page.module.css by viewport and by the `data-theme` the
          inline script in layout.tsx sets before first paint, so only the one
          crop for the current theme downloads and a light-theme load never
          flashes the dark art first. */}
      <div className={styles.bg} aria-hidden />
      {/* The 3D presenter. `mode` drives her body animation (idle → listening →
          talking); her mouth is driven separately by the Audio2Face frames that
          arrive alongside the reply audio. */}
      <AvatarStage
        mode={voice.mode}
        avatar={avatar}
        levelRef={voice.levelRef}
        onReady={onAvatarReady}
        ready={avatarReady}
        theme={theme}
      />

      <LanguageBar
        className={styles.langBar}
        lang={lang}
        onLang={setLang}
        avatar={avatar}
        onAvatar={changeAvatar}
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
