#!/usr/bin/env bash
# mari.sh — start / stop / restart the whole MARI kiosk stack:
#   the FastAPI backend (server/app.py, scripts/run_web.sh), the Next.js
#   frontend (frontend/), and the Audio2Face-3D NIM (deploy/a2f/, the avatar's
#   lipsync inference service). Backend/frontend logs go under .run/ at the
#   repo root; a2f's own logs stay with docker (`docker compose logs`).
#
# Usage:
#   ./mari.sh start     start a2f + backend + frontend (no-op for any already running)
#   ./mari.sh stop       stop all three
#   ./mari.sh restart   stop then start
#   ./mari.sh status    show whether each is running, and on what port
#
# Env overrides (same names run_web.sh already honors, plus one for the frontend):
#   MARI_HOST=127.0.0.1  MARI_PORT=8010   MARI_PYTHON=...
#   MARI_FRONTEND_PORT=3000
#
# Each of backend/frontend is launched with `setsid`, giving it its own
# process group (group id == the pid we record). `next dev` in particular
# forks a next-server child and its own CLI wrapper can exit once that child
# is up, orphaning it — tracking a single pid then misses it entirely.
# Stopping by process group (`kill -- -PID`) reaches that child (and anything
# else the tool forks) too, since a plain fork inherits its parent's group.
#
# a2f is a Docker Compose service (GPU, ~10GB model) instead: its lifecycle is
# docker's job, not ours. It degrades gracefully by design (see
# deploy/a2f/docker-compose.yml) — if docker, the GPU, or deploy/a2f/.env
# (NGC_API_KEY) aren't there, `start` warns and moves on to backend/frontend
# rather than failing the whole stack; the avatar just won't move its mouth.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
ROOT="$(pwd)"

RUN_DIR=".run"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"

BACKEND_PORT="${MARI_PORT:-8010}"
FRONTEND_PORT="${MARI_FRONTEND_PORT:-3000}"

A2F_DIR="$ROOT/deploy/a2f"
A2F_CONTAINER="mari-a2f-nim"

mkdir -p "$RUN_DIR"

# A recorded pid is a process-group id: alive iff the group still has members.
group_alive() {
  local pgid="$1"
  [ -n "$pgid" ] && kill -0 -- "-$pgid" 2>/dev/null
}

is_running() {
  # $1 = pid file
  [ -f "$1" ] || return 1
  group_alive "$(cat "$1")"
}

start_backend() {
  if is_running "$BACKEND_PID_FILE"; then
    echo "backend already running (pgid $(cat "$BACKEND_PID_FILE"))"
    return
  fi
  echo "starting backend  →  http://${MARI_HOST:-127.0.0.1}:${BACKEND_PORT}"
  setsid nohup ./scripts/run_web.sh >"$BACKEND_LOG" 2>&1 &
  echo $! >"$BACKEND_PID_FILE"
}

start_frontend() {
  if is_running "$FRONTEND_PID_FILE"; then
    echo "frontend already running (pgid $(cat "$FRONTEND_PID_FILE"))"
    return
  fi
  if [ ! -d frontend/node_modules ]; then
    echo "frontend/node_modules missing — run 'npm install' in frontend/ first" >&2
    exit 1
  fi
  echo "starting frontend →  http://localhost:${FRONTEND_PORT}"
  # The cd must stay inside the backgrounded subshell, or `$!` below would be
  # captured in the (unbackgrounded) parent and never actually match the job.
  # The local `next` binary directly — not `npm run dev` (package.json's dev
  # script hardcodes -p 3000) and not `npx next` (an extra layer of forking).
  setsid nohup bash -c '
    cd "$1"/frontend
    exec ./node_modules/.bin/next dev -p "$2"
  ' _ "$ROOT" "$FRONTEND_PORT" >"$FRONTEND_LOG" 2>&1 &
  echo $! >"$FRONTEND_PID_FILE"
}

# "$state|$health" from docker, or empty if the container doesn't exist.
a2f_inspect() {
  docker inspect \
    --format '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
    "$A2F_CONTAINER" 2>/dev/null
}

is_a2f_running() {
  local s
  s="$(a2f_inspect)" || return 1
  [ -n "$s" ] && [[ "$s" == running* ]]
}

start_a2f() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "a2f: docker not found — skipping (avatar will run without lipsync)"
    return
  fi
  if [ ! -f "$A2F_DIR/.env" ]; then
    echo "a2f: $A2F_DIR/.env missing (see .env.example for NGC_API_KEY) — skipping"
    return
  fi
  if is_a2f_running; then
    echo "a2f already running"
    return
  fi
  echo "starting a2f (Audio2Face-3D NIM) — first boot can take minutes to load the model"
  if ! (cd "$A2F_DIR" && docker compose up -d) >>"$RUN_DIR/a2f.log" 2>&1; then
    echo "a2f: failed to start — see $RUN_DIR/a2f.log (continuing without lipsync)" >&2
  fi
}

stop_a2f() {
  if ! command -v docker >/dev/null 2>&1; then
    return
  fi
  if ! is_a2f_running; then
    echo "a2f not running"
    return
  fi
  echo "stopping a2f"
  (cd "$A2F_DIR" && docker compose stop) >>"$RUN_DIR/a2f.log" 2>&1 || true
}

status_a2f() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "a2f:      docker not found"
    return
  fi
  local s state health
  s="$(a2f_inspect)"
  if [ -z "$s" ]; then
    echo "a2f:      stopped (no container)"
    return
  fi
  state="${s%%|*}"
  health="${s##*|}"
  if [ "$state" = "running" ]; then
    echo "a2f:      running (${health}, port 52000)"
  else
    echo "a2f:      $state"
  fi
}

stop_one() {
  # $1 = pid file, $2 = label
  if ! is_running "$1"; then
    echo "$2 not running"
    rm -f "$1"
    return
  fi
  local pgid
  pgid="$(cat "$1")"
  echo "stopping $2 (pgid $pgid)"
  kill -- "-$pgid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    group_alive "$pgid" || break
    sleep 0.5
  done
  group_alive "$pgid" && kill -9 -- "-$pgid" 2>/dev/null || true
  rm -f "$1"
}

do_start() {
  start_a2f
  start_backend
  start_frontend
}

do_stop() {
  stop_one "$FRONTEND_PID_FILE" "frontend"
  stop_one "$BACKEND_PID_FILE" "backend"
  stop_a2f
}

do_status() {
  status_a2f
  if is_running "$BACKEND_PID_FILE"; then
    echo "backend:  running (pgid $(cat "$BACKEND_PID_FILE"), port ${BACKEND_PORT})"
  else
    echo "backend:  stopped"
  fi
  if is_running "$FRONTEND_PID_FILE"; then
    echo "frontend: running (pgid $(cat "$FRONTEND_PID_FILE"), port ${FRONTEND_PORT})"
  else
    echo "frontend: stopped"
  fi
}

case "${1:-}" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; do_start ;;
  status)  do_status ;;
  *)
    echo "usage: $0 {start|stop|restart|status}" >&2
    exit 1
    ;;
esac
