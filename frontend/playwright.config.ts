import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests against the running kiosk.
 *
 * These exist because the kiosk's worst failures are invisible to every other check:
 * the mouth stops moving, the 43 MB rig downloads twice, or the avatar darkens a
 * little more each time the presenter is switched. None of them raises an error, none
 * of them fails a unit test, and the first two need a real WebGL context and a real
 * audio element to happen at all.
 *
 * They need the stack up, because the lipsync path runs from the browser through the
 * backend to the Audio2Face NIM and back:
 *
 *     docker compose up -d && npm run e2e
 *
 * Point them somewhere else with MARI_E2E_URL. No web server is started here on
 * purpose — the frontend alone cannot answer a question.
 */
const baseURL = process.env.MARI_E2E_URL ?? "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./e2e",
  // The avatar is 20-43 MB and the first turn waits on a real LLM.
  timeout: 120_000,
  expect: { timeout: 30_000 },
  // Shared module state and the model cache make these order-dependent by nature.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL,
    // WebGL is the whole point; headless shell has no GPU path.
    headless: true,
    launchOptions: {
      args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"],
    },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
