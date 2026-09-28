#!/usr/bin/env bash
#
# Run the Samruddhi AI stack locally: FastAPI backend + Next.js frontend.
#
#   ./run.sh            start both services
#   ./run.sh --force    kill anything already holding ports 8000/3000 first
#
# macOS / Linux only. On Windows use the cross-platform equivalent:
#   uv run scripts/run_local.py
#
# Ctrl+C stops both services cleanly.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend/api"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
BACKEND_PORT=8000
FRONTEND_PORT=3000

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

BACKEND_PID=""
FRONTEND_PID=""

# --- pretty output ----------------------------------------------------------
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'
  GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi

info()  { printf '%s\n' "  $*"; }
ok()    { printf '%s\n' "  ${GREEN}✓${RESET} $*"; }
warn()  { printf '%s\n' "  ${YELLOW}!${RESET} $*"; }
fail()  { printf '%s\n' "  ${RED}✗${RESET} $*" >&2; }
head_() { printf '\n%s\n' "${BOLD}$*${RESET}"; }

# --- cleanup ----------------------------------------------------------------
cleanup() {
  local code=$?
  trap - INT TERM EXIT
  printf '\n%s\n' "${BOLD}Shutting down...${RESET}"

  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    [[ -z "$pid" ]] && continue
    if kill -0 "$pid" 2>/dev/null; then
      # Kill the whole process group: `npm run dev` and `uv run` both spawn
      # children that outlive the parent otherwise.
      kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    fi
  done

  # Give them a moment, then insist.
  for _ in 1 2 3 4 5; do
    if ! { [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; } &&
       ! { [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; }; then
      break
    fi
    sleep 1
  done
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    [[ -n "$pid" ]] && kill -KILL -"$pid" 2>/dev/null || true
  done

  ok "Stopped."
  exit "$code"
}
trap cleanup INT TERM EXIT

# --- prerequisites ----------------------------------------------------------
head_ "Checking prerequisites"
missing=0
for tool in node npm uv; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool $("$tool" --version 2>/dev/null | head -1)"
  else
    fail "$tool not found"
    missing=1
  fi
done
if (( missing )); then
  fail "Install the missing tools and retry. uv: https://docs.astral.sh/uv/"
  exit 1
fi

# --- environment files ------------------------------------------------------
head_ "Checking environment files"
env_missing=0
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  ok ".env"
else
  fail ".env missing (root) — backend variables from guides 1-7"
  env_missing=1
fi
if [[ -f "$FRONTEND_DIR/.env.local" ]]; then
  ok "frontend/.env.local"
else
  fail "frontend/.env.local missing — Clerk keys and NEXT_PUBLIC_API_URL"
  env_missing=1
fi
(( env_missing )) && exit 1

# --- ports ------------------------------------------------------------------
port_pids() { lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null || true; }

head_ "Checking ports"
conflict=0
for port in $BACKEND_PORT $FRONTEND_PORT; do
  pids="$(port_pids "$port")"
  if [[ -n "$pids" ]]; then
    if (( FORCE )); then
      warn "port $port busy (pid $(echo "$pids" | tr '\n' ' ')) — killing"
      # shellcheck disable=SC2086
      kill -TERM $pids 2>/dev/null || true
      sleep 2
      pids="$(port_pids "$port")"
      # shellcheck disable=SC2086
      [[ -n "$pids" ]] && kill -KILL $pids 2>/dev/null || true
      ok "port $port freed"
    else
      fail "port $port already in use (pid $(echo "$pids" | tr '\n' ' '))"
      conflict=1
    fi
  else
    ok "port $port free"
  fi
done
if (( conflict )); then
  fail "Re-run with ${BOLD}./run.sh --force${RESET} to stop what is holding them."
  exit 1
fi

# --- dependencies -----------------------------------------------------------
head_ "Checking dependencies"
if [[ ! -d "$BACKEND_DIR/.venv" ]]; then
  info "Syncing backend dependencies (uv sync)..."
  (cd "$BACKEND_DIR" && uv sync)
fi
ok "backend deps ready"

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  info "Installing frontend dependencies (npm install)..."
  (cd "$FRONTEND_DIR" && npm install)
fi
ok "frontend deps ready"

# --- start backend ----------------------------------------------------------
head_ "Starting backend"
cd "$BACKEND_DIR"
# Process substitution rather than a pipe: after `cmd | sed &`, $! is sed's PID,
# not the server's. `set -m` puts the job in its own process group so cleanup
# can signal the whole tree via `kill -PGID`.
set -m
uv run main.py > >(sed "s/^/${DIM}[api]${RESET} /") 2>&1 &
BACKEND_PID=$!
set +m
cd "$PROJECT_ROOT"

info "waiting for http://localhost:$BACKEND_PORT/health ..."
backend_up=0
for _ in $(seq 1 45); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    fail "backend exited during startup — see [api] output above"
    exit 1
  fi
  if curl -fsS -o /dev/null "http://localhost:$BACKEND_PORT/health" 2>/dev/null; then
    backend_up=1
    break
  fi
  sleep 1
done
if (( ! backend_up )); then
  fail "backend did not become healthy within 45s"
  exit 1
fi
ok "backend up on http://localhost:$BACKEND_PORT  (docs: /docs)"

# --- start frontend ---------------------------------------------------------
head_ "Starting frontend"
cd "$FRONTEND_DIR"
set -m
npm run dev > >(sed "s/^/${DIM}[web]${RESET} /") 2>&1 &
FRONTEND_PID=$!
set +m
cd "$PROJECT_ROOT"

info "waiting for http://localhost:$FRONTEND_PORT ..."
frontend_up=0
for _ in $(seq 1 60); do
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    fail "frontend exited during startup — see [web] output above"
    exit 1
  fi
  # Any HTTP response counts; Next redirects unauthenticated routes.
  if curl -fsS -o /dev/null "http://localhost:$FRONTEND_PORT" 2>/dev/null ||
     curl -s -o /dev/null -w '%{http_code}' "http://localhost:$FRONTEND_PORT" 2>/dev/null | grep -qE '^[2-4]'; then
    frontend_up=1
    break
  fi
  sleep 1
done
if (( ! frontend_up )); then
  fail "frontend did not respond within 60s"
  exit 1
fi
ok "frontend up on http://localhost:$FRONTEND_PORT"

# --- run --------------------------------------------------------------------
cat <<EOF

${BOLD}Samruddhi AI — running locally${RESET}
  Frontend   http://localhost:$FRONTEND_PORT
  Backend    http://localhost:$BACKEND_PORT
  API docs   http://localhost:$BACKEND_PORT/docs

${DIM}Logs are prefixed [api] and [web]. Press Ctrl+C to stop both.${RESET}

EOF

# Exit as soon as either service dies, so a crashed backend doesn't leave a
# frontend running against nothing.
while true; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    fail "backend stopped"
    exit 1
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    fail "frontend stopped"
    exit 1
  fi
  sleep 2
done
