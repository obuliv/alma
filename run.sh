#!/usr/bin/env bash
# One-command dev launcher: sets up the backend venv (incl. Playwright's
# Chromium, for form-fill), runs migrations, starts the API, then starts the
# frontend dev server in the foreground. Safe to re-run — every step is
# idempotent.
set -euo pipefail
# Job control: gives each backgrounded job (API, frontend) its own process
# group, so cleanup below can kill the *whole* group, not just the top PID.
# uvicorn --reload spawns its own subprocess to run the server; a bare `kill`
# on just the top PID can leave that subprocess (and anything it spawns)
# orphaned and still holding port 8000.
set -m

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "==> Backend: setting up venv"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "==> Backend: installing dependencies"
pip install -q -r "$BACKEND_DIR/requirements.txt"

echo "==> Backend: installing Playwright (form-fill's headed browser)"
pip install -q playwright==1.49.0
playwright install chromium

echo "==> Backend: running migrations"
(cd "$BACKEND_DIR" && alembic upgrade head)

echo "==> Backend: starting API on http://localhost:8000 (logs: $LOG_DIR/api.log)"
# exec replaces the subshell with uvicorn itself, so $! is uvicorn's real PID
# (not a wrapper shell) and kill/wait below act on the right process.
(cd "$BACKEND_DIR" && exec uvicorn app.main:app --reload) > "$LOG_DIR/api.log" 2>&1 &
API_PID=$!

cleanup() {
  echo ""
  echo "==> Stopping API (pid $API_PID) and frontend (pid ${FRONTEND_PID:-none})"
  # Negative PID = whole process group (see the `set -m` note above). Fall
  # back to a plain kill in case job control didn't give it its own group.
  kill -TERM -- "-$API_PID" 2>/dev/null || kill "$API_PID" 2>/dev/null || true
  if [ -n "${FRONTEND_PID:-}" ]; then
    kill -TERM -- "-$FRONTEND_PID" 2>/dev/null || kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  sleep 1
  # Anything that ignored SIGTERM (e.g. a stuck subprocess) gets SIGKILL.
  kill -KILL -- "-$API_PID" 2>/dev/null || true
  [ -n "${FRONTEND_PID:-}" ] && kill -KILL -- "-$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
# EXIT alone is enough: bash always runs the EXIT trap on the way out, even
# when terminated by INT/TERM — and running the frontend as a background job
# (below) rather than a plain foreground subshell means `wait` is actually
# interruptible by the signal, so cleanup isn't skipped.
trap cleanup EXIT

echo "==> Frontend: installing dependencies"
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  (cd "$FRONTEND_DIR" && npm install)
fi

echo "==> Frontend: starting dev server (logs: $LOG_DIR/ui.log, proxies /api -> :8000)"
(cd "$FRONTEND_DIR" && exec npm run dev) > "$LOG_DIR/ui.log" 2>&1 &
FRONTEND_PID=$!

echo "==> Tail both with: tail -f $LOG_DIR/api.log $LOG_DIR/ui.log"
echo "==> Vite's URL (usually http://localhost:5173) is printed in $LOG_DIR/ui.log"

wait "$FRONTEND_PID"
