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
 * This is the .gz, and lib/avatarFetch.ts fetches it with ONE plain GET.
 *
 * An older comment here claimed the raw .glb was faster because the file was
 * pulled as six parallel byte ranges, which a gzip stream cannot be split into.
 * That implementation no longer exists — avatarFetch.ts is a single GET and says
 * in its own header not to add Range headers, because ranged responses (206) are
 * never written to the browser's disk cache, so every reload re-downloaded the
 * whole model. The comment outlived the code and is corrected here.
 *
 * With one GET, smaller simply wins. The raw 30MB girl15.glb was abandoned
 * mid-download by a real client (ERR_NETWORK_CHANGED, no avatar); the 20MB .gz is
 * a third less to carry. This page (/netcheck) is how to measure the rest, from
 * the kiosk rather than from a developer machine whose own link may be the
 * bottleneck — which is exactly what happened the first time it was measured.
 */
export const AVATAR_MODEL_URL = AVATARS[DEFAULT_AVATAR].url;
