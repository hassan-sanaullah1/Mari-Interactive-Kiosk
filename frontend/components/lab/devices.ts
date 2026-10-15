/**
 * Screens the lab can preview the presenter on, and the kiosk's portrait
 * layout, so framing can be judged on the shape it will actually be seen at.
 *
 * Every number about the layout mirrors the kiosk's own CSS:
 *   - portrait (any screen narrower than 6:5) uses bg-mobile-*.png and gives
 *     the avatar the full width and the bottom 79% of the height
 *     (components/AvatarStage.module.css);
 *   - the controls are placed in the 402 x 874 design space of mobile_UI.png
 *     (app/globals.css, the max-aspect-ratio block).
 */

import type { Theme } from "@/lib/theme";

export interface Device {
  label: string;
  width: number;
  height: number;
}

export const DEVICES = {
  phone: { label: "Phone 402×874 (mobile design)", width: 402, height: 874 },
  iphone: { label: "iPhone 390×844", width: 390, height: 844 },
  android: { label: "Android 412×915", width: 412, height: 915 },
  kioskPortrait: { label: "Portrait kiosk 1080×1920", width: 1080, height: 1920 },
  tablet: { label: "Tablet 768×1024", width: 768, height: 1024 },
} satisfies Record<string, Device>;

export type DeviceId = keyof typeof DEVICES;

/** Share of the screen's height the avatar's canvas takes, from the bottom (AvatarStage.module.css). */
export const PORTRAIT_STAGE_HEIGHT = 0.79;

/** The portrait artwork per theme, as page.module.css picks it. */
export const MOBILE_BACKDROP_DEFAULT: Record<Theme, string> = {
  dark: "/bg-mobile-dark.png",
  light: "/bg-mobile-light.png",
};

/** Every portrait artwork in public/, to try against each other. */
export const MOBILE_BACKDROPS = [
  "/bg-mobile-light.png",
  "/bg-mobile-light-2.png",
  "/bg-mobile-light-3.png",
  "/bg-mobile-light4.png",
  "/bg-mobile-dark.png",
] as const;

/**
 * Where the kiosk's portrait controls sit, in the 402 x 874 design space, so
 * the frame can outline them and her hands and face can be kept clear.
 * The design space scales with the shorter of width/402 and height/874.
 */
export const MOBILE_GUIDES = {
  design: { width: 402, height: 874 },
  /** The mic disc's outer halo: 64 across, x1.406, bottom 104.5 up. */
  mic: { centerX: 201, centerY: 874 - 104.5 - 32, radius: 45 },
  /** The bottom row: language pill, presenter and theme buttons, chat. */
  bottomRow: { left: 16, right: 402 - 16, top: 874 - 25.5 - 45, bottom: 874 - 25.5 },
};
