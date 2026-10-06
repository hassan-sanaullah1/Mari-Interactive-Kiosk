"use client";

import { useEffect, useRef, type RefObject } from "react";
import styles from "./ControlDock.module.css";
import { CloseIcon, PauseIcon, PlayIcon, WaveformIcon } from "./icons";
import { COPY, type Lang } from "@/lib/i18n";
import type { Mode } from "@/hooks/useVoiceSession";

type Props = {
  className?: string;
  lang: Lang;
  mode: Mode;
  active: boolean;
  paused: boolean;
  levelRef: RefObject<number>;
  onToggle: () => void;
  onStop: () => void;
  onTogglePause: () => void;
};

export default function ControlDock({
  className,
  lang,
  mode,
  active,
  paused,
  levelRef,
  onToggle,
  onStop,
  onTogglePause,
}: Props) {
  const dockRef = useRef<HTMLDivElement>(null);
  const t = COPY[lang];

  /* Drive the halo/waveform from the audio level without re-rendering per frame. */
  useEffect(() => {
    let raf = 0;
    let shown = 0;
    const tick = () => {
      shown += (levelRef.current - shown) * 0.16;
      dockRef.current?.style.setProperty("--lvl", shown.toFixed(3));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [levelRef]);

  const live = mode === "listening" || mode === "speaking";
  // Enabled whenever there is something to hold. NOT `active`: that is the mic
  // session's flag, and a question typed in the chat composer never sets it, so
  // this button showed as disabled while the kiosk was speaking the answer.
  const canPause = mode !== "idle";
  const status = t[mode];

  return (
    <div ref={dockRef} className={`${styles.dock} ${className ?? ""}`}>
      <button
        type="button"
        className={styles.small}
        onClick={onStop}
        aria-label="End conversation and clear transcript"
      >
        <CloseIcon className={styles.smallIcon} />
      </button>

      <button
        type="button"
        className={styles.micWrap}
        data-live={live ? "1" : "0"}
        onClick={onToggle}
        aria-label={active ? "Stop listening" : "Start speaking"}
        aria-pressed={active}
      >
        <span className={styles.ring2} aria-hidden="true" />
        <span className={styles.ring1} aria-hidden="true" />
        {/* Concentric waves that travel outward while audio is live. */}
        <span className={styles.ripples} aria-hidden="true">
          <span className={styles.ripple} />
          <span className={styles.ripple} />
          <span className={styles.ripple} />
        </span>
        <span className={styles.disc}>
          <WaveformIcon className={styles.wave} />
        </span>
        <span className={styles.srOnly} role="status" aria-live="polite">
          {status}
        </span>
      </button>

      <button
        type="button"
        className={styles.small}
        onClick={onTogglePause}
        aria-disabled={!canPause}
        aria-label={paused ? "Resume conversation" : "Pause conversation"}
      >
        {paused ? <PlayIcon className={styles.smallIcon} /> : <PauseIcon className={styles.smallIcon} />}
      </button>
    </div>
  );
}
