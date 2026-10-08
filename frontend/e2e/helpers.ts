import { expect, type Page, type Request } from "@playwright/test";

/** The avatar's accessible names come from the profile; these are its labels. */
export const PRESENTER = {
  female: "Female presenter",
  male: "Male presenter",
} as const;

export type PresenterName = (typeof PRESENTER)[keyof typeof PRESENTER];

/** Records every model request the page makes, so a duplicate download is visible. */
export function trackModelRequests(page: Page): string[] {
  const urls: string[] = [];
  page.on("request", (request: Request) => {
    const url = request.url();
    if (/\.glb(\.gz)?(\?|$)/.test(url)) urls.push(url);
  });
  return urls;
}

/** Wait until the avatar has loaded and the loading overlay is gone. */
export async function waitForAvatar(page: Page): Promise<void> {
  // The overlay only disappears once the rig has parsed and rendered a frame.
  await expect(page.locator("canvas")).toBeVisible({ timeout: 90_000 });
  await page.waitForFunction(
    () => {
      const probe = (window as unknown as { __MARI?: Record<string, { state?: unknown }> }).__MARI;
      return Boolean(probe?.fetch);
    },
    undefined,
    { timeout: 90_000 },
  );
}

/** Ask a question through the chat composer. Returns once the reply has begun. */
export async function askTyped(page: Page, question: string): Promise<void> {
  const launcher = page.getByRole("button", { name: /Open Chat|گفتگو/ });
  if (await launcher.isVisible().catch(() => false)) await launcher.click();

  const composer = page.getByRole("textbox");
  await composer.fill(question);
  await composer.press("Enter");
}

/** Switch to a presenter by its accessible label and wait for the rig to settle. */
export async function switchPresenter(page: Page, name: PresenterName): Promise<void> {
  await page.getByRole("button", { name, exact: true }).first().click();
  await waitForAvatar(page);
  // The material pass runs in an effect after the scene mounts.
  await page.waitForTimeout(1500);
}

/** `window.__A2F.state` — the lipsync probe the player publishes. */
export async function a2fState(page: Page): Promise<{
  messages: number;
  framesReceived: number;
  clips: number;
  samples: number;
  buffered: number;
  activeUid: string | null;
}> {
  return page.evaluate(
    () => (window as unknown as { __A2F: { state: never } }).__A2F.state,
  );
}

/** `window.__MARI.tints` — the tinted material colours, for the darkening check. */
export async function tintReadings(page: Page): Promise<Record<string, number>> {
  return page.evaluate(() => {
    const probe = (window as unknown as { __MARI?: { tints?: Record<string, number> } }).__MARI;
    return { ...(probe?.tints ?? {}) };
  });
}

/** `window.__MARI_SINGLETONS` — how many times each single-instance module loaded. */
export async function singletonCounts(page: Page): Promise<Record<string, number>> {
  return page.evaluate(() => ({
    ...((window as unknown as { __MARI_SINGLETONS?: Record<string, number> })
      .__MARI_SINGLETONS ?? {}),
  }));
}
