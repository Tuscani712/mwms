#!/usr/bin/env bash
# ═════════════════════════════════════════════════════════════════════════════
# WMS Local Dev Launcher
# ─────────────────────────────────────────────────────────────────────────────
#   • Checks Python + venv (creates if missing)
#   • Installs deps (only when missing)
#   • Seeds DB (only when missing)
#   • Detects port collisions (interactively offers to kill)
#   • Launches backend (uvicorn :8000) + frontend (http.server :8765)
#   • Tracks PIDs; CTRL+C gracefully stops both
# ═════════════════════════════════════════════════════════════════════════════

set -u

# ── COLORS ───────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_RED=$'\033[0;31m'; C_GRN=$'\033[0;32m'; C_YEL=$'\033[1;33m'
  C_BLU=$'\033[0;34m'; C_DIM=$'\033[2m';    C_BLD=$'\033[1m'; C_RST=$'\033[0m'
else
  C_RED=''; C_GRN=''; C_YEL=''; C_BLU=''; C_DIM=''; C_BLD=''; C_RST=''
fi

log()   { printf "%s[wms]%s %s\n" "$C_BLU" "$C_RST" "$*"; }
ok()    { printf "%s ✓ %s%s\n" "$C_GRN" "$*" "$C_RST"; }
warn()  { printf "%s ⚠ %s%s\n" "$C_YEL" "$*" "$C_RST"; }
fail()  { printf "%s ✗ %s%s\n" "$C_RED" "$*" "$C_RST"; exit 1; }
info()  { printf "%s   %s%s\n" "$C_DIM" "$*" "$C_RST"; }

# ── PATHS ────────────────────────────────────────────────────────────────────
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
UVICORN="$VENV/bin/uvicorn"
DB_FILE="$BACKEND/data/wms.db"
PID_DIR="$ROOT/.run"
BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"
BACKEND_LOG="$PID_DIR/backend.log"
FRONTEND_LOG="$PID_DIR/frontend.log"

BACKEND_PORT="${WMS_BACKEND_PORT:-8000}"
FRONTEND_PORT="${WMS_FRONTEND_PORT:-8765}"

# ── BANNER ───────────────────────────────────────────────────────────────────
banner() {
  echo
  printf "%s┌────────────────────────────────────────────────────┐%s\n" "$C_DIM" "$C_RST"
  printf "%s│  WMS Software · Local Dev Launcher                 │%s\n" "$C_BLD" "$C_RST"
  printf "%s└────────────────────────────────────────────────────┘%s\n" "$C_DIM" "$C_RST"
  echo
}

# ── SIGNAL HANDLING ──────────────────────────────────────────────────────────
SHUTDOWN_DONE=0
shutdown() {
  if [[ $SHUTDOWN_DONE -eq 1 ]]; then return; fi
  SHUTDOWN_DONE=1
  echo
  log "Shutting down…"
  for f in "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"; do
    if [[ -f "$f" ]]; then
      local pid; pid="$(cat "$f" 2>/dev/null || true)"
      if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        # Give it 2s, then force.
        for _ in 1 2 3 4; do
          sleep 0.5
          kill -0 "$pid" 2>/dev/null || break
        done
        kill -9 "$pid" 2>/dev/null || true
        ok "Stopped PID $pid"
      fi
      rm -f "$f"
    fi
  done
  log "All services stopped. Logs preserved in $PID_DIR/"
  exit 0
}
trap shutdown INT TERM

# ── PRE-FLIGHT ───────────────────────────────────────────────────────────────
check_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found. Install Python 3.11+ and retry."
  fi
  local ver; ver="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
  ok "Python $ver detected"
}

check_or_create_venv() {
  if [[ -x "$PY" ]]; then
    ok "Virtualenv exists at backend/.venv"
  else
    log "Creating virtualenv at backend/.venv …"
    python3 -m venv "$VENV" || fail "Failed to create venv"
    "$PIP" install --quiet --upgrade pip || warn "Could not upgrade pip"
    ok "Virtualenv created"
  fi
}

check_or_install_deps() {
  # Use a sentinel: presence of `uvicorn` binary + `bcrypt` import = installed
  if [[ -x "$UVICORN" ]] && "$PY" -c "import fastapi, sqlalchemy, bcrypt, jose" >/dev/null 2>&1; then
    ok "Backend dependencies installed"
  else
    log "Installing backend dependencies (this is slow only the first time)…"
    ( cd "$BACKEND" && "$PIP" install --quiet -e ".[dev]" ) || fail "pip install failed"
    ok "Backend dependencies installed"
  fi
}

check_or_seed_db() {
  if [[ -f "$DB_FILE" ]]; then
    ok "Database present at backend/data/wms.db"
  else
    log "Seeding mock data (first run only)…"
    ( cd "$BACKEND" && "$PY" -m wms.seeders.seed ) || fail "Seeder failed"
    ok "Database seeded"
  fi
}

# ── PORT HANDLING ────────────────────────────────────────────────────────────
pids_on_port() {
  # Returns whitespace-separated PIDs listening on the given TCP port.
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u | tr '\n' ' '
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnpH "sport = :$port" 2>/dev/null \
      | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u | tr '\n' ' '
  else
    echo ""
  fi
}

ensure_port_free() {
  local port="$1" label="$2"
  local pids; pids="$(pids_on_port "$port")"
  if [[ -z "${pids// /}" ]]; then
    ok "Port $port free for $label"
    return 0
  fi
  warn "Port $port is in use by PID(s): $pids ($label)"
  printf "%s   Kill them and continue? [y/N] %s" "$C_YEL" "$C_RST"
  local answer; read -r answer
  case "$answer" in
    y|Y|yes|YES)
      for pid in $pids; do
        kill "$pid" 2>/dev/null && ok "Killed PID $pid" || warn "Could not kill $pid"
      done
      sleep 1
      ;;
    *)
      fail "Port $port still occupied. Aborting."
      ;;
  esac
}

# ── LAUNCHERS ────────────────────────────────────────────────────────────────
start_backend() {
  log "Launching backend on :$BACKEND_PORT …"
  mkdir -p "$PID_DIR"
  ( cd "$BACKEND" && nohup "$UVICORN" wms.main:app \
      --host 127.0.0.1 --port "$BACKEND_PORT" \
      >"$BACKEND_LOG" 2>&1 & echo $! >"$BACKEND_PID_FILE" )
  sleep 2
  local pid; pid="$(cat "$BACKEND_PID_FILE" 2>/dev/null || echo '?')"
  if kill -0 "$pid" 2>/dev/null; then
    ok "Backend running · PID $pid · http://127.0.0.1:$BACKEND_PORT"
    info "Swagger UI · http://127.0.0.1:$BACKEND_PORT/docs"
  else
    fail "Backend failed to start — see $BACKEND_LOG"
  fi
}

start_frontend() {
  log "Launching frontend on :$FRONTEND_PORT …"
  mkdir -p "$PID_DIR"
  ( cd "$FRONTEND" && nohup python3 -m http.server "$FRONTEND_PORT" \
      --bind 127.0.0.1 \
      >"$FRONTEND_LOG" 2>&1 & echo $! >"$FRONTEND_PID_FILE" )
  sleep 1
  local pid; pid="$(cat "$FRONTEND_PID_FILE" 2>/dev/null || echo '?')"
  if kill -0 "$pid" 2>/dev/null; then
    ok "Frontend running · PID $pid · http://127.0.0.1:$FRONTEND_PORT/login.html"
  else
    fail "Frontend failed to start — see $FRONTEND_LOG"
  fi
}

# ── MAIN MENU LOOP ───────────────────────────────────────────────────────────
print_status() {
  echo
  printf "%s┌─ STATUS ───────────────────────────────────────────┐%s\n" "$C_DIM" "$C_RST"
  for f in "$BACKEND_PID_FILE:Backend:$BACKEND_PORT" "$FRONTEND_PID_FILE:Frontend:$FRONTEND_PORT"; do
    IFS=':' read -r pf label port <<< "$f"
    local pid; pid="$(cat "$pf" 2>/dev/null || echo '')"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      printf "%s│%s %s%-10s%s · PID %-6s · :%s · %sRUNNING%s\n" \
        "$C_DIM" "$C_RST" "$C_BLD" "$label" "$C_RST" "$pid" "$port" "$C_GRN" "$C_RST"
    else
      printf "%s│%s %s%-10s%s · %sSTOPPED%s\n" \
        "$C_DIM" "$C_RST" "$C_BLD" "$label" "$C_RST" "$C_RED" "$C_RST"
    fi
  done
  printf "%s└────────────────────────────────────────────────────┘%s\n" "$C_DIM" "$C_RST"
}

menu_loop() {
  echo
  log "Servers are live. Use the menu below, or press CTRL+C to quit."
  while true; do
    echo
    echo "  ${C_BLD}[s]${C_RST} Status     ${C_BLD}[b]${C_RST} Tail backend log   ${C_BLD}[f]${C_RST} Tail frontend log"
    echo "  ${C_BLD}[r]${C_RST} Restart    ${C_BLD}[o]${C_RST} Open login URL     ${C_BLD}[q]${C_RST} Quit"
    printf "%swms>%s " "$C_BLU" "$C_RST"
    local cmd; read -r cmd || { echo; shutdown; }
    case "$cmd" in
      s|S|status) print_status ;;
      b|B) [[ -f "$BACKEND_LOG" ]] && tail -n 25 "$BACKEND_LOG" || warn "No backend log yet" ;;
      f|F) [[ -f "$FRONTEND_LOG" ]] && tail -n 25 "$FRONTEND_LOG" || warn "No frontend log yet" ;;
      r|R|restart)
        shutdown_no_exit
        start_backend
        start_frontend
        ;;
      o|O|open)
        local url="http://127.0.0.1:$FRONTEND_PORT/login.html"
        if command -v xdg-open >/dev/null 2>&1; then xdg-open "$url" >/dev/null 2>&1 &
        elif command -v open >/dev/null 2>&1; then open "$url" >/dev/null 2>&1 &
        else info "Open: $url"; fi
        ;;
      q|Q|quit|exit) shutdown ;;
      "") ;;  # ignore empty
      *) info "Unknown command: $cmd" ;;
    esac
  done
}

shutdown_no_exit() {
  for f in "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"; do
    if [[ -f "$f" ]]; then
      local pid; pid="$(cat "$f" 2>/dev/null || true)"
      [[ -n "${pid:-}" ]] && kill "$pid" 2>/dev/null || true
      rm -f "$f"
    fi
  done
  sleep 1
}

# ── EXECUTE ──────────────────────────────────────────────────────────────────
banner
mkdir -p "$PID_DIR"

log "Pre-flight checks…"
check_python
check_or_create_venv
check_or_install_deps
check_or_seed_db

log "Port checks…"
ensure_port_free "$BACKEND_PORT" "backend"
ensure_port_free "$FRONTEND_PORT" "frontend"

log "Starting services…"
start_backend
start_frontend
print_status
menu_loop
