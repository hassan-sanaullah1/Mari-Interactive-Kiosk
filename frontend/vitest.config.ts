import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * Unit tests for the logic that needs no browser: the voice-activity state machine,
 * the blendshape sampling, the A2F name resolution, the avatar profiles.
 *
 * Anything that needs a real WebGL context, a real audio element or webpack's own
 * module resolution is in e2e/ instead, driven by Playwright — those are the failures
 * that only exist in a browser.
 */
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
    // e2e/ is Playwright's; it must not be collected here.
    exclude: ["e2e/**", "node_modules/**", ".next/**"],
  },
});
