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

export default function AvatarStage({ mode }: { mode: Mode }) {
  return (
    <div className={styles.stage} aria-hidden="true">
      <AvatarScene state={avatarStateFor(mode)} />
    </div>
  );
}
