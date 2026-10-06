/**
 * Which presenter the kiosk shows, remembered across reloads.
 *
 * Same shape as lib/theme.ts, and for the same reason: a kiosk reloads often,
 * and an operator who picked a presenter should not have to pick it again.
 *
 * Unlike the theme there is no pre-paint inline script for this — the choice
 * only affects which model the avatar chunk fetches, which happens well after
 * first paint, so reading it from an effect is early enough.
 */

import { DEFAULT_AVATAR, type AvatarId } from "@/components/avatar/models";

export const AVATAR_KEY = "mari-avatar";

export function applyAvatar(id: AvatarId) {
  try {
    localStorage.setItem(AVATAR_KEY, id);
  } catch {
    /* private mode / storage disabled — the choice just won't persist */
  }
}

export function readAvatar(): AvatarId {
  try {
    return localStorage.getItem(AVATAR_KEY) === "male" ? "male" : DEFAULT_AVATAR;
  } catch {
    return DEFAULT_AVATAR;
  }
}
