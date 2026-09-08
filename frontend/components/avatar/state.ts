/**
 * The conversation states the avatar reacts to, and the mapping from the voice
 * session's own `Mode`. Kept separate from the R3F components so the page can
 * import it without pulling three.js into the initial bundle.
 */

import type { Mode } from "@/hooks/useVoiceSession";
import { AVATARS, DEFAULT_AVATAR } from "./models";

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

/**
 * Where the DEFAULT avatar lives, served from frontend/public.
 *
 * The full per-model registry — URLs, loop windows, materials — is in
 * ./models.ts, and the scene resolves its URL from there. This re-export is the
 * default rig's URL under its original name, for app/netcheck, which times a
 * cold and a warm fetch of one representative model rather than of every rig.
 *
 * This points at the UNCOMPRESSED .glb on purpose, even though a .gz sits next
 * to it and is 10MB smaller. The deployed host throttles each connection rather
 * than the account: measured against it, the 20MB gzip on one stream takes 118s,
 * while the 30MB raw file pulled as six parallel byte ranges takes 32s. Range
 * requests index the bytes on the wire, so a gzip stream cannot be split that
 * way — the smaller file is the slower one here.
 *
 * lib/avatarFetch.ts does the splitting and falls back to a single stream when
 * the server will not serve ranges, so this stays correct on a host that
 * behaves differently. The .gz is still built and served (see next.config.ts)
 * for exactly that fallback path.
 */
export const AVATAR_MODEL_URL = AVATARS[DEFAULT_AVATAR].url;
