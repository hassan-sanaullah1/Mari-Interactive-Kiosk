"use client";

import dynamic from "next/dynamic";
import styles from "./AvatarStage.module.css";
import { avatarStateFor } from "./avatar/state";
import type { Mode } from "@/hooks/useVoiceSession";

/**
 * The 3D presenter's mount point.
 *
 * Position, size, responsive behaviour and z-index (10 — above the background,
 * below the controls) are unchanged from the placeholder this replaced; only
 * the contents differ. The scene is loaded client-side only: it uses
 * WebGLRenderer / requestAnimationFrame and cannot render on the server, and
 * keeping three.js out of the server bundle keeps first paint on the artwork.
 */
const AvatarScene = dynamic(() => import("./avatar/AvatarScene"), {
  ssr: false,
  loading: () => null,
});

export interface AvatarStageProps {
  mode: Mode;
  /** Smoothed 0..1 amplitude, passed straight through to the light rig so the
   *  key and rim lights breathe with her voice. */
  levelRef?: { current: number };
  /** Fires once the rig has loaded and is posed — see AvatarModel's onReady.
   *  The page uses it to gate its full-screen loading overlay; this stage
   *  itself stays a plain passthrough so it has no loading UI of its own. */
  onReady?: () => void;
}

export default function AvatarStage({ mode, levelRef, onReady }: AvatarStageProps) {
  return (
    <div className={styles.stage} aria-hidden="true">
      <AvatarScene state={avatarStateFor(mode)} levelRef={levelRef} onReady={onReady} />
    </div>
  );
}
