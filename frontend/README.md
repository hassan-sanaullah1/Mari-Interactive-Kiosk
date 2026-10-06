# MARI kiosk — Next.js frontend

The kiosk UI (App Router + CSS Modules, no other UI deps). It renders on top of the
**existing** speech-to-speech backend in `server/` — no pipeline logic lives here.

## Run

Two processes:

```bash
# 1. the existing FastAPI backend (unchanged)
python -m uvicorn server.app:app --host 127.0.0.1 --port 8010

# 2. this UI
cd frontend && npm install && npm run dev     # http://localhost:3000
```

The legacy static UI in `web/` is untouched and still served at http://127.0.0.1:8010/.

## How it talks to the backend

| Path | Transport | Notes |
|---|---|---|
| `/api/chat`, `/api/voice`, `/api/healthz` | Next rewrite → FastAPI | same-origin, so no CORS changes were needed server-side |
| `/ws` | direct WebSocket to FastAPI | Next's dev proxy doesn't forward WS upgrades; WebSockets bypass CORS |

Override the targets with `MARI_API_ORIGIN` (build/server side, see `next.config.ts`)
and `NEXT_PUBLIC_MARI_WS` (browser side, see `lib/endpoints.ts`).

`hooks/useVoiceSession.ts` is a port of `web/app.js` onto React state. The wire
protocol is unchanged: `{start,lang}` → 16 kHz PCM16 frames → `{end}` → `{stt}` /
`{reply}` + audio → `{done}`. Browser-side VAD thresholds are the original values.

## Layout

Two measured design spaces, both driven from `app/globals.css`:

| | reference | design space | background |
|---|---|---|---|
| desktop | `UI-sample-images/UI.png` | 2000 x 1125 | `public/bg-desktop-dark.png` / `bg-desktop-light.png` |
| phone (<= 760px) | `UI-sample-images/mobile_UI.png` | 402 x 874 | `public/bg-mobile-dark.png` / `bg-mobile-light.png` |

`--s` is one reference unit. The phone media query **redefines `--s`** against the
402x874 space and re-derives every control size token (`--mic`, `--dock-btn`,
`--pill-h`, `--edge-x`, ...), so the two layouts share components and markup but not
coordinates. Sizes scale as one piece rather than via per-breakpoint tweaks; icons
inside circular buttons are sized as a percentage of the button so they need no
per-layout rule.

While audio is live (`listening` or `speaking`), three concentric rings travel
outward from the mic button — see `.ripple` in `ControlDock.module.css`. They are
staggered by a third of the 2.1s cycle so one is always mid-flight, their strength
follows the real audio amplitude (`--lvl`), and 1.9x is the widest they can grow
without touching the ✕/pause buttons in either layout.

The background is art-directed with a plain `<picture>` element — a phone downloads
only the portrait crop, a desktop only the landscape one. The mic's halo is two
concentric rings (`--mic-ring1/2` + alphas): desktop sets the outer alpha to 0 for
the single ring `UI.png` shows, mobile uses both, as `mobile_UI.png` does.

## Theming

The sun/moon button beside the language pill switches dark ⇄ light. Themed surfaces
are driven by tokens in `app/globals.css` (`:root` = dark, `:root[data-theme="light"]`
= light); the choice persists in `localStorage` and is applied before first paint by
an inline script in `app/layout.tsx`, so there's no flash on reload.

Two things deliberately do **not** follow the theme:

- the dock's ✕ and pause buttons — always `--dock-surface` (#1f2021), fully opaque,
  because they sit over the artwork and the avatar rather than a themed surface;
- the avatar placeholder — the background image is dark in both themes.

## The 3D avatar

`components/AvatarStage.tsx` is the reserved container — correct position, size,
responsive behaviour and z-index (10: above the background, below the controls).
Replace the `.placeholder` div with the Three.js canvas mount; nothing else moves.
