"use client";

import { useCallback, useEffect, useState } from "react";
import styles from "./page.module.css";
import AvatarStage from "@/components/AvatarStage";
import ChatPanel from "@/components/ChatPanel";
import ControlDock from "@/components/ControlDock";
import LanguageBar from "@/components/LanguageBar";
import LoadingScreen from "@/components/LoadingScreen";
import { useVoiceSession } from "@/hooks/use-voice-session";
import { applyTheme, readTheme, type Theme } from "@/lib/theme";
import { applyAvatar, readAvatar } from "@/lib/avatar";
import { avatarConfig, DEFAULT_AVATAR, type AvatarId } from "@/components/avatar/models";
import { uiCopy, type Lang } from "@/lib/i18n";

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
  // Resolved here because this is where the presenter is known; the Urdu status
  // lines have to agree with who is on screen.
  const presenterGender = avatarConfig(avatar).grammaticalGender;
  const t = uiCopy(lang, presenterGender);

  // Pick up the theme the inline script in layout.tsx already applied, and the
  // stored presenter, which has no such script — see lib/avatar.ts.
  useEffect(() => {
    setTheme(readTheme());
    setAvatar(readAvatar());
  }, []);

  // Warm the OTHER theme's background in the browser's HTTP cache once the page
  // is idle, so a later light/dark toggle swaps instantly instead of waiting on
  // a fresh fetch. The CSS in page.module.css deliberately never fetches the
  // non-matching rule's image on its own (see the .bg comment there) — this is
  // the one place that asks for it anyway, off the critical path and after the
  // active background has already painted. Cheap now that both images are a
  // few hundred KB WebP rather than multi-megabyte PNGs.
  useEffect(() => {
    const other = theme === "light" ? "dark" : "light";
    const idle = window.requestIdleCallback ?? ((fn: () => void) => window.setTimeout(fn, 1));
    const cancel = window.cancelIdleCallback ?? window.clearTimeout;
    const handle = idle(() => {
      const img = new Image();
      img.src = `/bg-mobile-${other}.webp`;
    });
    return () => cancel(handle);
  }, [theme]);

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
   *
   * It also hard-stops the session first: the reply audio is the old rig's
   * voice, and leaving it playing means the new presenter appears while the
   * previous one is still talking. The transcript stays — only the turn ends.
   */
  const changeAvatar = (id: AvatarId) => {
    if (id === avatar) return;
    voice.stop();
    setAvatarReady(false);
    setAvatar(id);
    applyAvatar(id);
  };

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  // Every failure except a denied mic currently reads as "didn't catch that",
  // including a server error, which is misleading but needs its own copy to fix.
  const errorText = !voice.error ? null : voice.error === "mic-denied" ? t.micDenied : t.noSpeech;

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
        gender={presenterGender}
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
        gender={presenterGender}
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
