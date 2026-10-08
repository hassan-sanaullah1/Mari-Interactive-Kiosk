/**
 * Dumps every resolved per-avatar value to a JSON snapshot.
 *
 * The look of each presenter is spread over models.ts (asset facts, animation
 * windows) and tuning.ts (camera, lights, materials, A2F gains), merged by a spread.
 * Phase 4 of the refactor replaces both with profiles/{base,female,male}.ts, and the
 * only way to prove that reshuffle changed no pixel is to compare the resolved values
 * before and after — hence this snapshot rather than a reading of the diff.
 *
 *   node scripts/dump-avatar-profiles.mjs            compare against the snapshot
 *   node scripts/dump-avatar-profiles.mjs --write     record a new one
 *
 * Values hard-coded in components (the female makeup pass) are picked up by the
 * regex block below, because they are per-avatar values that do not live in config
 * yet; Phase 4 moves them into the profiles and they must survive that move intact.
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "..");
const SNAPSHOT = path.join(FRONTEND, "test/fixtures/avatar-profiles.json");

/** Sets and typed arrays would both serialise as {}. */
function plain(value) {
  if (value instanceof Set) return { __set: [...value].sort() };
  if (Array.isArray(value)) return value.map(plain);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, plain(value[key])]),
    );
  }
  return value;
}

/**
 * Compile models.ts to JS and read its exports.
 *
 * Only models.ts is named: tuning.ts comes in through its runtime import, and the
 * type-only imports (state.ts, which uses the `@/` alias) need the project's `paths`,
 * so this goes through a generated tsconfig rather than bare CLI flags.
 */
function resolvedAvatars() {
  const out = mkdtempSync(path.join(tmpdir(), "mari-profiles-"));
  try {
    const config = path.join(out, "tsconfig.json");
    writeFileSync(
      config,
      JSON.stringify({
        compilerOptions: {
          outDir: path.join(out, "js"),
          rootDir: FRONTEND,
          // CommonJS: tsc keeps extensionless relative imports, which Node's ESM
          // loader rejects but its require() resolves.
          module: "commonjs",
          target: "es2022",
          moduleResolution: "bundler",
          skipLibCheck: true,
          noEmitOnError: false,
          baseUrl: FRONTEND,
          paths: { "@/*": ["./*"] },
          types: ["node"],
        },
        files: [path.join(FRONTEND, "components/avatar/models.ts")],
      }),
    );
    // tsc exits non-zero for type errors in files it only pulled in for their types,
    // having emitted anyway. `npm run typecheck` is what polices those; here only the
    // emit matters, so judge by whether the output exists.
    const compiled = path.join(out, "js/components/avatar/models.js");
    try {
      execFileSync(path.join(FRONTEND, "node_modules/.bin/tsc"), ["--project", config], {
        cwd: FRONTEND,
        stdio: "pipe",
      });
    } catch (error) {
      if (!existsSync(compiled)) {
        const detail = [error.stdout, error.stderr].filter(Boolean).join("\n").trim();
        throw new Error(`tsc emitted nothing:\n${detail || error.message}`);
      }
    }
    writeFileSync(path.join(out, "js", "package.json"), JSON.stringify({ type: "commonjs" }));
    const models = createRequire(import.meta.url)(compiled);
    return { avatars: models.AVATARS, defaultAvatar: models.DEFAULT_AVATAR };
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
}

/**
 * Per-avatar numbers that still live inside components. Read as text on purpose:
 * importing AvatarModel.tsx would pull in three and react-three-fiber.
 */
function constantsInComponents() {
  const sources = {
    "AvatarModel.tsx": "components/avatar/AvatarModel.tsx",
    "AvatarScene.tsx": "components/avatar/AvatarScene.tsx",
    "blendshapePlayer.ts": "lib/blendshapePlayer.ts",
    "a2fMorphs.ts": "lib/a2fMorphs.ts",
  };
  const wanted = [
    // The female-only makeup pass.
    "MAKEUP_DESATURATION", "MAKEUP_MAX_HUE", "MAKEUP_MIN_SAT", "FACE_UV_BOX",
    // Shared defaults that the female rig currently falls back to.
    "AVATAR_POSITION_X", "BOB_", "READY_FRAME_DELAY",
    "DEFAULT_GAIN", "DEFAULT_SHAPE_GAINS",
    "FADE_", "FOLLOW_", "DECAY_", "MAX_INFLUENCE",
    "CLIP_FRAME_WAIT", "MAX_BUFFERED_CLIPS",
  ];
  const found = {};
  for (const [label, relative] of Object.entries(sources)) {
    const text = readFileSync(path.join(FRONTEND, relative), "utf8");
    // `const NAME = <value>;` possibly spanning lines, comments stripped.
    const pattern = /^\s*(?:export\s+)?const\s+([A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=\s*([\s\S]*?);\s*$/gm;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      const [, name, raw] = match;
      if (!wanted.some((prefix) => name.startsWith(prefix))) continue;
      found[`${label}:${name}`] = raw
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/\/\/.*$/gm, "")
        .replace(/\s+/g, " ")
        .trim();
    }
  }
  return Object.fromEntries(Object.keys(found).sort().map((key) => [key, found[key]]));
}

const snapshot = plain({
  ...resolvedAvatars(),
  componentConstants: constantsInComponents(),
});
const serialised = JSON.stringify(snapshot, null, 1) + "\n";

if (process.argv.includes("--write")) {
  mkdirSync(path.dirname(SNAPSHOT), { recursive: true });
  writeFileSync(SNAPSHOT, serialised);
  console.log(`wrote ${path.relative(FRONTEND, SNAPSHOT)} (${serialised.length} bytes)`);
} else {
  let expected;
  try {
    expected = readFileSync(SNAPSHOT, "utf8");
  } catch {
    console.error(`no snapshot at ${SNAPSHOT}; run with --write first`);
    process.exit(2);
  }
  if (expected === serialised) {
    console.log("avatar profiles match the snapshot");
  } else {
    console.error(
      "avatar profiles CHANGED.\n" +
        "Some presenter value moved or was edited. If that was deliberate, re-run\n" +
        "with --write and say so in the commit; otherwise it is a regression in how\n" +
        "a presenter looks.\n",
    );
    const expectedLines = expected.split("\n");
    const actualLines = serialised.split("\n");
    for (let i = 0; i < Math.max(expectedLines.length, actualLines.length); i += 1) {
      if (expectedLines[i] !== actualLines[i]) {
        console.error(`line ${i + 1}:\n  -${expectedLines[i] ?? ""}\n  +${actualLines[i] ?? ""}`);
      }
    }
    process.exit(1);
  }
}
