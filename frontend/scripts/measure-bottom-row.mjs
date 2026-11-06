/**
 * Measures the bottom control row against the running kiosk.
 *
 * The row's width budget is tight enough that token arithmetic gets it wrong:
 * --pill-seg is a min-width and the language words overflow it, so the pill is
 * ~207 reference units rather than the 168 the tokens imply. Adding a control
 * to this row overflowed it at every gap value, and the collision only showed
 * on a narrow screen. Measure, don't calculate — see docs/kiosk-layout.md.
 *
 *     npm run dev          # or the compose stack
 *     node scripts/measure-bottom-row.mjs
 *
 * Point it elsewhere with MARI_E2E_URL.
 */

import { chromium } from "@playwright/test";

const URL = process.env.MARI_E2E_URL ?? "http://127.0.0.1:3000";

/** The kiosk panel plus the sizes either layout can collapse to. */
const VIEWPORTS = [
  { name: "kiosk portrait 1080x1920", width: 1080, height: 1920 },
  { name: "reference phone 402x874", width: 402, height: 874 },
  { name: "small phone 360x640", width: 360, height: 640 },
  { name: "desktop 1920x1080", width: 1920, height: 1080 },
];

const browser = await chromium.launch({
  args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"],
});

let failed = 0;

for (const viewport of VIEWPORTS) {
  const page = await browser.newPage({
    viewport: { width: viewport.width, height: viewport.height },
  });
  await page.goto(URL, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="subtitle-toggle"]', { timeout: 60_000 });
  // The theme effect and the fonts both move these boxes.
  await page.waitForTimeout(1500);

  const measured = await page.evaluate(() => {
    const box = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { left: +r.left.toFixed(1), right: +r.right.toFixed(1), width: +r.width.toFixed(1) };
    };
    const byLabel = (re) =>
      [...document.querySelectorAll("button")].find((b) =>
        re.test(b.getAttribute("aria-label") ?? ""),
      );
    const english = [...document.querySelectorAll("button")].find(
      (b) => b.textContent.trim() === "English",
    );
    return {
      frame: box(document.querySelector("main")),
      bar: box(english?.closest("div")?.parentElement),
      captions: box(document.querySelector('[data-testid="subtitle-toggle"]')),
      chat: box(byLabel(/Open Chat|گفتگو/)),
    };
  });

  const { frame, bar, captions, chat } = measured;
  const gapToCaptions = +(captions.left - bar.right).toFixed(1);
  const gapToChat = +(chat.left - captions.right).toFixed(1);
  const overflowsFrame = captions.left < frame.left || chat.right > frame.right;
  const collides = gapToCaptions < 0 || gapToChat < 0;

  console.log(`\n=== ${viewport.name} ===`);
  console.log(`  left cluster   ${bar.left} .. ${bar.right}`);
  console.log(`  captions       ${captions.left} .. ${captions.right}  (${captions.width}px)`);
  console.log(`  chat           ${chat.left} .. ${chat.right}  (${chat.width}px)`);
  console.log(`  clear: cluster→captions ${gapToCaptions}px, captions→chat ${gapToChat}px`);

  if (collides || overflowsFrame) {
    failed += 1;
    console.log(`  FAIL: ${collides ? "controls overlap" : "a control is outside the frame"}`);
  } else if (captions.width !== chat.width) {
    failed += 1;
    console.log(`  FAIL: captions (${captions.width}px) and chat (${chat.width}px) differ in size`);
  } else {
    console.log("  ok");
  }

  await page.close();
}

await browser.close();
console.log(failed === 0 ? "\nthe row fits at every size" : `\n${failed} viewport(s) failed`);
process.exit(failed === 0 ? 0 : 1);
