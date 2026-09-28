"use client";

import dynamic from "next/dynamic";
import styles from "./AvatarStage.module.css";
import { avatarStateFor } from "./avatar/state";
import { DEFAULT_AVATAR, type AvatarId } from "./avatar/models";
import type { Mode } from "@/hooks/useVoiceSession";
import type { Theme } from "@/lib/theme";

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
  /** Which presenter to show — see components/avatar/models.ts. */
  avatar?: AvatarId;
  /** Smoothed 0..1 amplitude, passed straight through to the light rig so the
   *  key and rim lights breathe with her voice. */
  levelRef?: { current: number };
  /** Fires once the rig has loaded and is posed — see AvatarModel's onReady.
   *  The page uses it to gate its loading overlay. */
  onReady?: () => void;
  /** Mirrors onReady's state. Before it flips, the canvas is kept invisible
   *  (opacity, not unmounted) so the glTF's bind-pose T-pose — which paints
   *  for however long the asset takes to parse, before onReady's mixer.update(0)
   *  applies a real pose — is never shown on screen. */
  ready?: boolean;
  /** The page theme — the scene lights the presenter brighter on the light one. */
  theme?: Theme;
}

export default function AvatarStage({
  mode,
  avatar = DEFAULT_AVATAR,
  levelRef,
  onReady,
  ready = false,
  theme,
}: AvatarStageProps) {
  return (
    <div className={styles.stage} data-ready={ready} aria-hidden="true">
      <AvatarScene
        state={avatarStateFor(mode)}
        avatar={avatar}
        levelRef={levelRef}
        onReady={onReady}
        theme={theme}
      />
    </div>
  );
}
