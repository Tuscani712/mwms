#!/usr/bin/env bash
# ═════════════════════════════════════════════════════════════════════════════
# WMS Local Dev Launcher
# ─────────────────────────────────────────────────────────────────────────────
#   • Checks Python + venv (creates if missing)
#   • Installs deps (only when missing)
#   • Seeds DB (only when missing)
#   • Detects port collisions (interactively offers to kill)
#   • Launches backend (uvicorn :8775) + frontend (http.server :8765)
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
# fail() must route through the EXIT trap so any already-started service is
# stopped before bash terminates. Don't call shutdown() directly here — the trap
# handles that, and double-invoking just adds noise (SHUTDOWN_DONE guards it).
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

BACKEND_PORT="${WMS_BACKEND_PORT:-8775}"
FRONTEND_PORT="${WMS_FRONTEND_PORT:-8765}"

# Tunables (seconds). Override via env if your machine is slow.
PORT_FREE_TIMEOUT="${WMS_PORT_FREE_TIMEOUT:-10}"
BACKEND_READY_TIMEOUT="${WMS_BACKEND_READY_TIMEOUT:-20}"
FRONTEND_READY_TIMEOUT="${WMS_FRONTEND_READY_TIMEOUT:-8}"
RESTART_LOCK="$PID_DIR/.restart.lock"

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
}
# INT/TERM = Ctrl+C and `kill <pid>`. HUP = terminal window closed.
# EXIT = catch-all for any other exit path (fail(), unexpected error under set -u,
# normal completion). SHUTDOWN_DONE makes shutdown() idempotent under double-fire
# (e.g. INT followed by EXIT).
trap shutdown INT TERM HUP EXIT

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
  # Sentinel: every runtime + test-runtime import we depend on must resolve.
  # pytest_xdist is the newest addition (parallel pytest); if it's missing,
  # this catches it without forcing a wholesale reinstall on every launch.
  local probe="import fastapi, sqlalchemy, bcrypt, jose, pytest, xdist"
  if [[ -x "$UVICORN" ]] && "$PY" -c "$probe" >/dev/null 2>&1; then
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

wait_for_port_free() {
  # Poll until no PIDs hold the port, escalate to SIGKILL after half the budget.
  local port="$1" timeout="${2:-$PORT_FREE_TIMEOUT}"
  local waited=0 half=$(( timeout / 2 )) escalated=0
  while :; do
    local pids; pids="$(pids_on_port "$port")"
    [[ -z "${pids// /}" ]] && return 0
    if (( waited >= timeout )); then
      warn "Port $port still held by: $pids after ${timeout}s"
      return 1
    fi
    if (( waited >= half && escalated == 0 )); then
      escalated=1
      for pid in $pids; do kill -9 "$pid" 2>/dev/null || true; done
    fi
    sleep 0.25
    waited=$(( waited + 1 ))  # ~0.25s tick, count as 1 for simplicity over short windows
  done
}

wait_for_port_open() {
  # Poll until something accepts TCP on the port. Returns 0 when open, 1 on timeout.
  local port="$1" timeout="${2:-$BACKEND_READY_TIMEOUT}"
  local waited=0
  while :; do
    if (echo >"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      return 0
    fi
    if (( waited >= timeout * 4 )); then
      return 1
    fi
    sleep 0.25
    waited=$(( waited + 1 ))
  done
}

http_ok() {
  # Return 0 if URL responds with a 2xx/3xx within 2s. Treats curl absence as a soft-skip (returns 0).
  command -v curl >/dev/null 2>&1 || return 0
  local url="$1"
  local code; code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$url" 2>/dev/null || echo 000)"
  [[ "$code" =~ ^[23] ]]
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
        kill "$pid" 2>/dev/null && ok "Sent SIGTERM to PID $pid" || warn "Could not signal $pid"
      done
      if wait_for_port_free "$port" "$PORT_FREE_TIMEOUT"; then
        ok "Port $port released"
      else
        fail "Port $port still occupied after ${PORT_FREE_TIMEOUT}s. Aborting."
      fi
      ;;
    *)
      fail "Port $port still occupied. Aborting."
      ;;
  esac
}

cleanup_stale_pids() {
  # Drop PID files whose process is no longer alive — left behind by ungraceful crashes.
  local cleaned=0
  for f in "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"; do
    if [[ -f "$f" ]]; then
      local pid; pid="$(cat "$f" 2>/dev/null || true)"
      if [[ -z "${pid:-}" ]] || ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$f"; cleaned=$(( cleaned + 1 ))
      fi
    fi
  done
  [[ -f "$RESTART_LOCK" ]] && rm -f "$RESTART_LOCK"
  (( cleaned > 0 )) && info "Cleared $cleaned stale PID file(s) from a prior run"
  return 0
}

# ── LAUNCHERS ────────────────────────────────────────────────────────────────
# Fatal-or-not switch: at boot, failures abort; in the menu, they return non-zero
# so the launcher keeps running and the user can inspect logs.
MENU_MODE=0
die_or_warn() {
  if (( MENU_MODE == 1 )); then
    warn "$*"; return 1
  else
    fail "$*"
  fi
}

start_backend() {
  log "Launching backend on :$BACKEND_PORT …"
  mkdir -p "$PID_DIR"
  if ! wait_for_port_free "$BACKEND_PORT" "$PORT_FREE_TIMEOUT"; then
    die_or_warn "Port $BACKEND_PORT not free — refusing to launch backend"
    return 1
  fi
  # No nohup: we *want* the child to receive SIGHUP if the terminal closes,
  # so it dies with us. The EXIT/HUP trap is the primary cleanup path; child
  # SIGHUP is the safety net if the trap is somehow bypassed.
  #
  # `exec` is critical: without it, `( cd && cmd & echo $! )` captures the bash
  # subshell's PID (the one running `cd && cmd`), not the server's. Killing the
  # subshell then orphans the server child — the bug behind the survival of
  # PIDs offset-by-one from what shutdown() reported killing. With `exec`, the
  # subshell replaces itself with uvicorn, so $! == uvicorn PID.
  ( cd "$BACKEND" && exec "$UVICORN" wms.main:app \
      --host 127.0.0.1 --port "$BACKEND_PORT" \
      >"$BACKEND_LOG" 2>&1 ) &
  echo $! >"$BACKEND_PID_FILE"
  local pid; pid="$(cat "$BACKEND_PID_FILE" 2>/dev/null || echo '?')"
  if ! wait_for_port_open "$BACKEND_PORT" "$BACKEND_READY_TIMEOUT"; then
    # Even if the process is alive, it didn't bind in time — capture last log lines.
    warn "Backend did not become ready on :$BACKEND_PORT within ${BACKEND_READY_TIMEOUT}s"
    [[ -f "$BACKEND_LOG" ]] && tail -n 15 "$BACKEND_LOG" | sed 's/^/    /'
    # Reap the half-started process so a retry can take the port.
    if [[ -n "${pid:-}" && "$pid" != "?" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait_for_port_free "$BACKEND_PORT" 5 || true
    fi
    rm -f "$BACKEND_PID_FILE"
    die_or_warn "Backend failed to start — full log at $BACKEND_LOG"
    return 1
  fi
  if kill -0 "$pid" 2>/dev/null; then
    ok "Backend running · PID $pid · http://127.0.0.1:$BACKEND_PORT"
    info "Swagger UI · http://127.0.0.1:$BACKEND_PORT/docs"
  else
    rm -f "$BACKEND_PID_FILE"
    die_or_warn "Backend port opened but process died — see $BACKEND_LOG"
    return 1
  fi
}

start_frontend() {
  log "Launching frontend on :$FRONTEND_PORT …"
  mkdir -p "$PID_DIR"
  if ! wait_for_port_free "$FRONTEND_PORT" "$PORT_FREE_TIMEOUT"; then
    die_or_warn "Port $FRONTEND_PORT not free — refusing to launch frontend"
    return 1
  fi
  # See start_backend: no nohup + `exec` so $! is the http.server PID directly,
  # not the bash subshell that would otherwise wrap it.
  ( cd "$FRONTEND" && exec python3 -m http.server "$FRONTEND_PORT" \
      --bind 127.0.0.1 \
      >"$FRONTEND_LOG" 2>&1 ) &
  echo $! >"$FRONTEND_PID_FILE"
  local pid; pid="$(cat "$FRONTEND_PID_FILE" 2>/dev/null || echo '?')"
  if ! wait_for_port_open "$FRONTEND_PORT" "$FRONTEND_READY_TIMEOUT"; then
    warn "Frontend did not become ready on :$FRONTEND_PORT within ${FRONTEND_READY_TIMEOUT}s"
    [[ -f "$FRONTEND_LOG" ]] && tail -n 10 "$FRONTEND_LOG" | sed 's/^/    /'
    if [[ -n "${pid:-}" && "$pid" != "?" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait_for_port_free "$FRONTEND_PORT" 5 || true
    fi
    rm -f "$FRONTEND_PID_FILE"
    die_or_warn "Frontend failed to start — see $FRONTEND_LOG"
    return 1
  fi
  if kill -0 "$pid" 2>/dev/null; then
    ok "Frontend running · PID $pid · http://127.0.0.1:$FRONTEND_PORT/login.html"
  else
    rm -f "$FRONTEND_PID_FILE"
    die_or_warn "Frontend port opened but process died — see $FRONTEND_LOG"
    return 1
  fi
}

# Smoke-test a running stack. Non-destructive: just hits known endpoints.
smoke_test() {
  echo
  log "Running smoke tests…"
  local fails=0 pass=0
  check() {
    local label="$1" url="$2"
    if http_ok "$url"; then
      printf "  %s ✓ %s%s  %s%s%s\n" "$C_GRN" "$label" "$C_RST" "$C_DIM" "$url" "$C_RST"
      pass=$(( pass + 1 ))
    else
      printf "  %s ✗ %s%s  %s%s%s\n" "$C_RED" "$label" "$C_RST" "$C_DIM" "$url" "$C_RST"
      fails=$(( fails + 1 ))
    fi
  }
  check "OpenAPI spec"     "http://127.0.0.1:$BACKEND_PORT/openapi.json"
  check "Swagger UI"       "http://127.0.0.1:$BACKEND_PORT/docs"
  check "Health route"     "http://127.0.0.1:$BACKEND_PORT/api/v1/health"
  check "Frontend login"   "http://127.0.0.1:$FRONTEND_PORT/login.html"
  check "Frontend dash"    "http://127.0.0.1:$FRONTEND_PORT/index.html"
  check "Frontend tokens"  "http://127.0.0.1:$FRONTEND_PORT/styles/tokens.css"

  # Auth-gated round-trip: proves the DB is seeded, auth router is mounted,
  # JWT issuance works, and an authenticated request resolves to a user.
  # Override via env if you've rotated the demo creds.
  local sc_user="${WMS_SMOKE_USER:-MCS-ADMIN}"
  local sc_pass="${WMS_SMOKE_PASS:-admin1234}"
  local sc_site="${WMS_SMOKE_SITE:-MCS}"
  if command -v curl >/dev/null 2>&1; then
    local login_body
    login_body=$(curl -s --max-time 3 -X POST \
      "http://127.0.0.1:$BACKEND_PORT/api/v1/auth/login" \
      -H "Content-Type: application/json" \
      -d "{\"employee_code\":\"$sc_user\",\"password\":\"$sc_pass\",\"site_id\":\"$sc_site\"}" 2>/dev/null || true)
    local token
    token=$(printf '%s' "$login_body" \
      | python3 -c 'import sys,json
try: print(json.loads(sys.stdin.read()).get("access_token") or "")
except Exception: pass' 2>/dev/null)
    if [[ -n "$token" ]]; then
      printf "  %s ✓ Auth login%s        %s%s@%s%s\n" "$C_GRN" "$C_RST" "$C_DIM" "$sc_user" "$sc_site" "$C_RST"
      pass=$(( pass + 1 ))
      local me_code
      me_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 \
        -H "Authorization: Bearer $token" \
        "http://127.0.0.1:$BACKEND_PORT/api/v1/auth/me" 2>/dev/null || echo 000)
      if [[ "$me_code" == "200" ]]; then
        printf "  %s ✓ Auth /me%s           %s/api/v1/auth/me → 200%s\n" "$C_GRN" "$C_RST" "$C_DIM" "$C_RST"
        pass=$(( pass + 1 ))
      else
        printf "  %s ✗ Auth /me%s           %s/api/v1/auth/me → %s%s\n" "$C_RED" "$C_RST" "$C_DIM" "$me_code" "$C_RST"
        fails=$(( fails + 1 ))
      fi

      # CRUD round-trips per admin resource. Each test creates a temp resource,
      # GETs it, then deletes it — proving router + service + auth + DB are all
      # talking. Failures are localized so you can tell *which* surface broke.
      _crud_check() {
        local label="$1" base_path="$2" create_body="$3" find_jq="$4" cleanup="$5"
        local resp code
        # Create
        resp=$(curl -s --max-time 5 -X POST -H "Content-Type: application/json" \
          -H "Authorization: Bearer $token" \
          -d "$create_body" \
          "http://127.0.0.1:$BACKEND_PORT$base_path" 2>/dev/null || echo '')
        local new_id
        new_id=$(printf '%s' "$resp" | python3 -c "import sys,json
try: print(json.loads(sys.stdin.read()).get('$find_jq',''))
except Exception: pass" 2>/dev/null)
        if [[ -z "$new_id" || "$new_id" == "None" ]]; then
          printf "  %s ✗ %s%s         %screate returned no id: %s%s\n" "$C_RED" "$label" "$C_RST" "$C_DIM" "${resp:0:80}" "$C_RST"
          fails=$(( fails + 1 ))
          return
        fi
        # Delete (cleanup is parameterized for path templating)
        local del_url="${cleanup//\{id\}/$new_id}"
        code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X DELETE \
          -H "Authorization: Bearer $token" \
          "http://127.0.0.1:$BACKEND_PORT$del_url" 2>/dev/null || echo 000)
        if [[ "$code" =~ ^2 ]]; then
          printf "  %s ✓ %s%s         %screate %s → delete %s%s\n" "$C_GRN" "$label" "$C_RST" "$C_DIM" "$new_id" "$code" "$C_RST"
          pass=$(( pass + 1 ))
        else
          printf "  %s ✗ %s%s         %screate ok, delete %s (leaked %s)%s\n" "$C_RED" "$label" "$C_RST" "$C_DIM" "$code" "$new_id" "$C_RST"
          fails=$(( fails + 1 ))
        fi
      }

      # Use suffix to avoid collisions if the same admin re-runs back-to-back.
      local suffix; suffix="$(date +%s)$$"
      # Users purge round-trip: create disposable user, hard-purge it, confirm 404.
      _purge_check() {
        local code
        code=$(date +%s%N | tail -c 8)
        local payload="{\"employee_code\":\"PRG-$code\",\"email\":\"prg-$code@wms.local\",\"full_name\":\"Purge Test\",\"password\":\"password123\"}"
        local create_resp
        create_resp=$(curl -s --max-time 5 -X POST -H "Content-Type: application/json" \
          -H "Authorization: Bearer $token" \
          -d "$payload" \
          "http://127.0.0.1:$BACKEND_PORT/api/v1/admin/users" 2>/dev/null || echo '')
        local uid
        uid=$(printf '%s' "$create_resp" | python3 -c "import sys,json
try: print(json.loads(sys.stdin.read()).get('id',''))
except Exception: pass" 2>/dev/null)
        if [[ -z "$uid" ]]; then
          printf "  %s ✗ Users purge%s        %screate failed: %s%s\n" "$C_RED" "$C_RST" "$C_DIM" "${create_resp:0:80}" "$C_RST"
          fails=$(( fails + 1 ))
          return
        fi
        local purge_code
        purge_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X POST \
          -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d '{}' \
          "http://127.0.0.1:$BACKEND_PORT/api/v1/admin/users/$uid/purge" 2>/dev/null || echo 000)
        local get_code
        get_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
          -H "Authorization: Bearer $token" \
          "http://127.0.0.1:$BACKEND_PORT/api/v1/admin/users/$uid" 2>/dev/null || echo 000)
        if [[ "$purge_code" == "204" && "$get_code" == "404" ]]; then
          printf "  %s ✓ Users purge%s        %screate %s → purge 204 → get 404%s\n" "$C_GRN" "$C_RST" "$C_DIM" "$uid" "$C_RST"
          pass=$(( pass + 1 ))
        else
          printf "  %s ✗ Users purge%s        %spurge %s, get %s (uid %s)%s\n" "$C_RED" "$C_RST" "$C_DIM" "$purge_code" "$get_code" "$uid" "$C_RST"
          fails=$(( fails + 1 ))
        fi
      }
      _purge_check

      _crud_check "Sites CRUD"   "/api/v1/sites" \
        "{\"id\":\"WHS-SMK${suffix: -6}\",\"name\":\"Smoke Test\",\"city\":\"Testville\"}" \
        "id" "/api/v1/sites/{id}"
      _crud_check "Roles CRUD"   "/api/v1/admin/roles" \
        "{\"name\":\"smoke-role-$suffix\",\"default_permission_level\":1,\"site_id\":null}" \
        "id" "/api/v1/admin/roles/{id}"
      _crud_check "Depts CRUD"   "/api/v1/admin/departments" \
        "{\"name\":\"smoke-dept-$suffix\"}" \
        "id" "/api/v1/admin/departments/{id}"
      _crud_check "Shifts CRUD"  "/api/v1/admin/shifts" \
        "{\"name\":\"smk-${suffix: -6}\",\"start_time\":\"06:00:00\",\"end_time\":\"14:00:00\"}" \
        "id" "/api/v1/admin/shifts/{id}"

      # SCO-142 Recipe round-trip: needs real SKU IDs from the seed, so
      # this helper does a GET first (unlike the other _crud_check calls
      # which use hardcoded payloads). Catches regressions in recipe POST,
      # the new DELETE endpoint, and the multi-line schema (SCO-141).
      _recipe_check() {
        local sku_resp
        sku_resp=$(curl -s --max-time 5 \
          -H "Authorization: Bearer $token" \
          "http://127.0.0.1:$BACKEND_PORT/api/v1/inventory/skus" 2>/dev/null || echo '[]')
        local ids
        ids=$(printf '%s' "$sku_resp" | python3 -c 'import sys,json
try:
    rows = json.loads(sys.stdin.read())
    print(" ".join(str(r.get("id","")) for r in rows[:2] if r.get("id")))
except Exception:
    pass' 2>/dev/null)
        # shellcheck disable=SC2206
        local arr=( $ids )
        if (( ${#arr[@]} < 2 )); then
          printf "  %s ✗ Recipe CRUD%s        %sneed ≥2 seeded SKUs (got %d)%s\n" \
            "$C_RED" "$C_RST" "$C_DIM" "${#arr[@]}" "$C_RST"
          fails=$(( fails + 1 ))
          return
        fi
        local product_sku="${arr[0]}" ingredient_sku="${arr[1]}"
        local body
        body="{\"sku_id\":$product_sku,\"name\":\"smoke-recipe-$suffix\",\"lines\":[{\"ingredient_sku_id\":$ingredient_sku,\"qty_per_unit\":1.0,\"uom\":\"EA\"}]}"
        local create_resp
        create_resp=$(curl -s --max-time 5 -X POST -H "Content-Type: application/json" \
          -H "Authorization: Bearer $token" -d "$body" \
          "http://127.0.0.1:$BACKEND_PORT/api/v1/production/recipes" 2>/dev/null || echo '')
        local rid
        rid=$(printf '%s' "$create_resp" | python3 -c "import sys,json
try: print(json.loads(sys.stdin.read()).get('id',''))
except Exception: pass" 2>/dev/null)
        if [[ -z "$rid" ]]; then
          printf "  %s ✗ Recipe CRUD%s        %screate failed: %s%s\n" \
            "$C_RED" "$C_RST" "$C_DIM" "${create_resp:0:80}" "$C_RST"
          fails=$(( fails + 1 ))
          return
        fi
        local del_code
        del_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X DELETE \
          -H "Authorization: Bearer $token" \
          "http://127.0.0.1:$BACKEND_PORT/api/v1/production/recipes/$rid" 2>/dev/null || echo 000)
        if [[ "$del_code" == "204" ]]; then
          printf "  %s ✓ Recipe CRUD%s        %screate %s → delete 204%s\n" \
            "$C_GRN" "$C_RST" "$C_DIM" "$rid" "$C_RST"
          pass=$(( pass + 1 ))
        else
          printf "  %s ✗ Recipe CRUD%s        %screate ok (%s), delete %s%s\n" \
            "$C_RED" "$C_RST" "$C_DIM" "$rid" "$del_code" "$C_RST"
          fails=$(( fails + 1 ))
        fi
      }
      _recipe_check
    else
      printf "  %s ✗ Auth login%s        %slogin returned no token (creds rotated? seed not run?)%s\n" \
        "$C_RED" "$C_RST" "$C_DIM" "$C_RST"
      fails=$(( fails + 1 ))
      # Skip /me check since we have no token — count as a single failure not two.
    fi
  else
    info "Skipping auth checks (curl not installed)"
  fi

  # Frontend JS tests — zero-dep node smokes (SCO-144 introduced this
  # runner pattern for the mass-unit conversion mirror). Catches drift
  # between Python and JS conversion tables that pytest can't see.
  if command -v node >/dev/null 2>&1 && [[ -d "$ROOT/frontend/tests" ]]; then
    local js_fail=0 js_total=0
    while IFS= read -r -d '' tfile; do
      js_total=$(( js_total + 1 ))
      if node "$tfile" >/dev/null 2>&1; then :; else js_fail=$(( js_fail + 1 )); fi
    done < <(find "$ROOT/frontend/tests" -maxdepth 1 -name '*.test.js' -print0)
    if (( js_total == 0 )); then
      info "Skipping JS tests (no *.test.js under frontend/tests)"
    elif (( js_fail == 0 )); then
      printf "  %s ✓ JS tests%s           %s%d/%d passing%s\n" \
        "$C_GRN" "$C_RST" "$C_DIM" "$js_total" "$js_total" "$C_RST"
      pass=$(( pass + 1 ))
    else
      printf "  %s ✗ JS tests%s           %s%d/%d failed — run [j] for detail%s\n" \
        "$C_RED" "$C_RST" "$C_DIM" "$js_fail" "$js_total" "$C_RST"
      fails=$(( fails + 1 ))
    fi
  else
    info "Skipping JS tests (node not installed or no frontend/tests dir)"
  fi

  # CSS lint pass — catches undefined CSS custom properties before they ship.
  # Silent-render failures (like the inventory dropdown bleed-through bug) come
  # from typos in var(--name) that browsers don't warn about, so we lint them.
  if command -v npx >/dev/null 2>&1 && [[ -f "$ROOT/package.json" ]] && [[ -d "$ROOT/node_modules/stylelint" ]]; then
    local css_out css_code
    css_out=$(cd "$ROOT" && npm run --silent lint:css 2>&1)
    css_code=$?
    if (( css_code == 0 )); then
      printf "  %s ✓ CSS lint%s          %sstylelint clean%s\n" "$C_GRN" "$C_RST" "$C_DIM" "$C_RST"
      pass=$(( pass + 1 ))
    else
      local err_count
      err_count=$(printf '%s' "$css_out" | grep -cE '✖' || true)
      printf "  %s ✗ CSS lint%s          %s%d stylelint error(s) — run: npm run lint:css%s\n" \
        "$C_RED" "$C_RST" "$C_DIM" "$err_count" "$C_RST"
      fails=$(( fails + 1 ))
    fi
  else
    info "Skipping CSS lint (run: npm install)"
  fi

  echo
  if (( fails == 0 )); then
    ok "Smoke test: $pass/$((pass+fails)) checks passed"
  else
    warn "Smoke test: $fails check(s) failed, $pass passed — see logs"
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
  MENU_MODE=1
  echo
  log "Servers are live. Use the menu below, or press CTRL+C to quit."
  while true; do
    echo
    echo "  ${C_BLD}[s]${C_RST} Status     ${C_BLD}[b]${C_RST} Tail backend log   ${C_BLD}[f]${C_RST} Tail frontend log"
    echo "  ${C_BLD}[r]${C_RST} Restart    ${C_BLD}[t]${C_RST} Smoke test         ${C_BLD}[l]${C_RST} CSS lint"
    echo "  ${C_BLD}[p]${C_RST} Pytest     ${C_BLD}[j]${C_RST} JS tests           ${C_BLD}[o]${C_RST} Open login URL"
    echo "  ${C_BLD}[q]${C_RST} Quit"
    printf "%swms>%s " "$C_BLU" "$C_RST"
    # Ctrl+D (EOF) → fall through to exit; EXIT trap stops both services.
    local cmd; read -r cmd || { echo; exit 0; }
    case "$cmd" in
      s|S|status) print_status ;;
      b|B) [[ -f "$BACKEND_LOG" ]] && tail -n 25 "$BACKEND_LOG" || warn "No backend log yet" ;;
      f|F) [[ -f "$FRONTEND_LOG" ]] && tail -n 25 "$FRONTEND_LOG" || warn "No frontend log yet" ;;
      t|T|test|smoke) smoke_test ;;
      p|P|pytest|py)
        # Full Python test suite, parallelized via pytest-xdist.
        # `-n auto` = one worker per logical core. Override with WMS_PYTEST_N=<n>
        # (e.g. WMS_PYTEST_N=4) when sharing the machine with heavy workloads.
        if ! "$PY" -c "import xdist" >/dev/null 2>&1; then
          warn "pytest-xdist not installed — falling back to single-process"
          ( cd "$BACKEND" && "$PY" -m pytest -q )
        else
          local n="${WMS_PYTEST_N:-auto}"
          log "Running pytest (-n $n)…"
          ( cd "$BACKEND" && "$PY" -m pytest -q -n "$n" )
        fi
        ;;
      l|L|lint)
        if [[ ! -d "$ROOT/node_modules/stylelint" ]]; then
          warn "stylelint not installed — run: npm install"
        else
          (cd "$ROOT" && npm run lint:css)
        fi
        ;;
      j|J|js|jstest)
        # SCO-144: run every frontend/tests/*.test.js with full output so
        # the operator can see which assertion drifted (e.g. NIST factor).
        if ! command -v node >/dev/null 2>&1; then
          warn "node not installed — install Node.js to run JS tests"
        elif [[ ! -d "$ROOT/frontend/tests" ]]; then
          warn "No frontend/tests directory yet"
        else
          local any=0 failed=0
          while IFS= read -r -d '' tfile; do
            any=1
            printf "%s── %s%s\n" "$C_DIM" "${tfile#$ROOT/}" "$C_RST"
            if ! node "$tfile"; then failed=$(( failed + 1 )); fi
          done < <(find "$ROOT/frontend/tests" -maxdepth 1 -name '*.test.js' -print0)
          if (( any == 0 )); then
            info "No *.test.js files under frontend/tests"
          elif (( failed > 0 )); then
            warn "$failed JS test file(s) failed"
          else
            ok "All JS test files passed"
          fi
        fi
        ;;
      r|R|restart)
        if [[ -f "$RESTART_LOCK" ]]; then
          warn "Restart already in progress — ignoring."
          continue
        fi
        : >"$RESTART_LOCK"
        shutdown_no_exit
        start_backend || warn "Backend not relaunched. Use [b] to inspect log."
        start_frontend || warn "Frontend not relaunched. Use [f] to inspect log."
        rm -f "$RESTART_LOCK"
        print_status
        ;;
      o|O|open)
        local url="http://127.0.0.1:$FRONTEND_PORT/login.html"
        if command -v xdg-open >/dev/null 2>&1; then xdg-open "$url" >/dev/null 2>&1 &
        elif command -v open >/dev/null 2>&1; then open "$url" >/dev/null 2>&1 &
        else info "Open: $url"; fi
        ;;
      q|Q|quit|exit)
        # EXIT trap will run shutdown() automatically and stop both services.
        log "Quit requested — stopping services and exiting."
        exit 0
        ;;
      "") ;;  # ignore empty
      *) info "Unknown command: $cmd" ;;
    esac
  done
}

shutdown_no_exit() {
  for f in "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"; do
    if [[ -f "$f" ]]; then
      local pid; pid="$(cat "$f" 2>/dev/null || true)"
      if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        # Up to 5s for graceful exit, then SIGKILL.
        for _ in $(seq 1 20); do
          sleep 0.25
          kill -0 "$pid" 2>/dev/null || break
        done
        kill -9 "$pid" 2>/dev/null || true
      fi
      rm -f "$f"
    fi
  done
  # Make sure both ports actually released before returning.
  wait_for_port_free "$BACKEND_PORT"  "$PORT_FREE_TIMEOUT" || warn "Port $BACKEND_PORT still busy"
  wait_for_port_free "$FRONTEND_PORT" "$PORT_FREE_TIMEOUT" || warn "Port $FRONTEND_PORT still busy"
}

# ── EXECUTE ──────────────────────────────────────────────────────────────────
banner
mkdir -p "$PID_DIR"
cleanup_stale_pids

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
