/**
 * GET /version.json: the commit this frontend container is running.
 *
 * Read from the environment on every request, not baked in at build time, so the
 * value comes from the container (Coolify's APP_COMMIT=$SOURCE_COMMIT) and the build
 * cache is not invalidated by every commit.
 */
export const dynamic = "force-dynamic";

export function GET(): Response {
  return Response.json({ commit: process.env.APP_COMMIT || "local" });
}
