// Lint rules for the kiosk UI.
//
// Two jobs beyond catching mistakes:
//
//   1. Keep the import direction one-way. `lib/` is the bottom layer and must not
//      reach up into `components/` or `hooks/`; today two files do, which is how the
//      avatar registry ended up imported from three directions at once.
//   2. Keep presenter differences in data. A `=== "male"` anywhere outside the avatar
//      profiles is the branch this refactor exists to remove, so the linter says so
//      rather than a reviewer having to notice.
//
// `next lint` is deprecated and removed in Next 16, so package.json calls eslint directly.

import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

// ── Temporary, each removed by the refactor step named ──────────────
//
// The rules above already fail on exactly the things this refactor is for, so turning
// them on in one go would just mean a red build. Each entry below is scoped to one
// file and one rule, so the rule still guards every other file and the list can only
// get shorter. Phase 4 of the plan empties it.
const scheduled = [
  {
    // Phase 4.4: the hook splits into micCapture / vad / replyQueue, every empty catch
    // either logs in debug mode or narrows, and the presenter id stops being compared.
    files: ["hooks/use-voice-session.ts"],
    rules: { "no-empty": "off", "no-restricted-syntax": "off", complexity: "off" },
  },
  {
    // Phase 4.1: these two read the avatar registry, which moves down into
    // lib/avatar/ so the import points the right way.
    files: ["lib/avatar.ts", "lib/avatar-fetch.ts"],
    rules: { "no-restricted-imports": "off" },
  },
  {
    // Phase 4.5/4.6: the lipsync logging moves behind lib/debug.ts, and AvatarModel
    // splits into hooks.
    files: ["lib/blendshape-player.ts", "lib/a2f-morphs.ts", "components/avatar/AvatarModel.tsx"],
    rules: { "no-console": "off", complexity: "off" },
  },
  {
    // Not scheduled: a CLI's console output IS its output, and a flat config file is
    // an anonymous default export by design.
    files: ["scripts/**/*.mjs", "eslint.config.mjs"],
    rules: { "no-console": "off", "import/no-anonymous-default-export": "off" },
  },
];

export default [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "next-env.d.ts",
      "public/**",
      "test/fixtures/**",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      // Complexity. Deliberately above the Python side's 10: a React component's
      // JSX branches inflate the count without making it harder to follow.
      complexity: ["warn", 15],
      "max-depth": ["warn", 4],
      // An empty catch hides a real failure. `catch { /* why */ }` with a comment
      // is allowed; a bare `catch {}` is not.
      "no-empty": ["error", { allowEmptyCatch: false }],
      "no-console": ["warn", { allow: ["warn", "error"] }],
      eqeqeq: ["error", "always", { null: "ignore" }],
      "prefer-const": "error",
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    // The bottom layer: generic helpers with no knowledge of the UI above them.
    files: ["lib/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/components/*", "../components/*", "@/hooks/*", "../hooks/*"],
              message:
                "lib/ is the bottom layer: move the shared value into lib/ (or lib/types.ts) " +
                "and import it from there instead of reaching up into components/ or hooks/.",
            },
          ],
        },
      ],
    },
  },
  {
    // Presenter differences belong in components/avatar/profiles/ (Phase 4) and, until
    // that exists, in models.ts / tuning.ts. Nowhere else.
    files: ["**/*.{ts,tsx}"],
    ignores: [
      "components/avatar/models.ts",
      "components/avatar/tuning.ts",
      "components/avatar/profiles/**",
      "lib/avatar.ts",
      "lib/i18n.ts",
    ],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "Literal[value='male']",
          message:
            "Presenters are data: put the value in the avatar profile and read it from " +
            "the config, rather than branching on the id here.",
        },
        {
          selector: "Literal[value='female']",
          message:
            "Presenters are data: put the value in the avatar profile and read it from " +
            "the config, rather than branching on the id here.",
        },
      ],
    },
  },
  ...scheduled,
];
