/**
 * The conversation states the avatar reacts to, and the mapping from the voice
 * session's own `Mode`. Kept separate from the R3F components so the page can
 * import it without pulling three.js into the initial bundle.
 */

import type { Mode } from "@/hooks/useVoiceSession";

export type AvatarState = "idle" | "listening" | "thinking" | "speaking";

/** "paused" holds the at-rest idle pose — the session is up but nothing is moving. */
export function avatarStateFor(mode: Mode): AvatarState {
  switch (mode) {
    case "listening":
      return "listening";
    case "thinking":
      return "thinking";
    case "speaking":
      return "speaking";
    default:
      return "idle";
  }
}

/** Where the .glb lives, served from frontend/public. */
export const AVATAR_MODEL_URL = "/models/girl13.glb";
