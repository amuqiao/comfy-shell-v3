#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$RUNTIME_DIR/../.." && pwd)}"
source "$ROOT_DIR/scripts/lib/common.sh"

API_HOST="${API_HOST:-$(env_value API_HOST)}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-$(env_value API_PORT)}"
API_PORT="${API_PORT:-8100}"
API_URL="${API_URL:-http://${API_HOST}:${API_PORT}}"
API_HEALTH_URL="${API_HEALTH_URL:-${API_URL}/health}"
API_READY_URL="${API_READY_URL:-${API_URL}/ready}"
API_DOCS_URL="${API_DOCS_URL:-${API_URL}/docs}"
API_OPENAPI_URL="${API_OPENAPI_URL:-${API_URL}/openapi.json}"

API_PID_FILE="${API_PID_FILE:-$RUN_DIR/api.pid}"
API_META_FILE="${API_META_FILE:-$RUN_DIR/api.meta}"
API_LOG_FILE="${API_LOG_FILE:-$LOG_DIR/api.log}"
TAIL_LINES="${TAIL_LINES:-80}"

bool_enabled() {
  local name="$1"
  local value="$2"
  case "$value" in
    true|True|TRUE) return 0 ;;
    false|False|FALSE|"") return 1 ;;
    *) die "$name must be true or false" 2 ;;
  esac
}

validate_port() {
  local name="$1"
  local value="$2"
  case "$value" in
    ''|*[!0-9]*) die "$name must be numeric: $value" 2 ;;
  esac
  if (( value < 1 || value > 65535 )); then
    die "$name must be between 1 and 65535: $value" 2
  fi
}

ensure_runtime_dirs() {
  mkdir -p "$RUN_DIR" "$LOG_DIR"
}

canonical_dir() {
  local path="$1"
  (cd "$path" >/dev/null 2>&1 && pwd -P) || return 1
}

process_cwd_available() {
  command -v lsof >/dev/null 2>&1 && return 0
  [[ -L "/proc/$$/cwd" ]] && return 0
  return 1
}

require_process_identity_check() {
  process_cwd_available || die "lsof or /proc/<pid>/cwd is required for safe PID ownership checks" 2
}

process_cwd() {
  local pid="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
    return 0
  fi
  if [[ -L "/proc/$pid/cwd" ]]; then
    (cd "/proc/$pid/cwd" >/dev/null 2>&1 && pwd -P) || return 1
    return 0
  fi
  return 1
}

process_has_open_file() {
  local pid="$1"
  local file="$2"
  local canonical_file
  [[ -f "$file" ]] || return 1
  canonical_file="$(cd "$(dirname "$file")" >/dev/null 2>&1 && printf "%s/%s" "$(pwd -P)" "$(basename "$file")")" || return 1
  if command -v lsof >/dev/null 2>&1; then
    lsof -a -p "$pid" "$canonical_file" >/dev/null 2>&1
    return $?
  fi
  if [[ -d "/proc/$pid/fd" ]]; then
    local fd
    local target
    for fd in /proc/"$pid"/fd/*; do
      target="$(readlink "$fd" 2>/dev/null || true)"
      [[ "$target" == "$canonical_file" ]] && return 0
    done
  fi
  return 1
}

api_pid() {
  [[ -f "$API_PID_FILE" ]] && cat "$API_PID_FILE" 2>/dev/null || true
}

api_pid_owned() {
  local pid="$1"
  local command
  local cwd
  local expected_cwd
  [[ -f "$API_META_FILE" ]] || return 1
  grep -Fx "pid=$pid" "$API_META_FILE" >/dev/null 2>&1 || return 1
  grep -Fx "root_dir=$ROOT_DIR" "$API_META_FILE" >/dev/null 2>&1 || return 1
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  case "$command" in
    *uvicorn*"app.main:app"*|*"app.main:app"*)
      ;;
    *)
      return 1
      ;;
  esac
  cwd="$(process_cwd "$pid")" || return 1
  expected_cwd="$(canonical_dir "$ROOT_DIR")" || return 1
  [[ "$cwd" == "$expected_cwd" ]] || return 1
  process_has_open_file "$pid" "$API_LOG_FILE"
}

pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

api_running() {
  local pid
  pid="$(api_pid)"
  pid_running "$pid" && api_pid_owned "$pid"
}

api_meta_port() {
  local url
  local authority
  local port
  if [[ -f "$API_META_FILE" ]]; then
    url="$(sed -n 's/^url=//p' "$API_META_FILE" | tail -n 1)"
  fi
  if [[ -z "${url:-}" ]]; then
    printf "%s" "$API_PORT"
    return 0
  fi
  authority="${url#*://}"
  authority="${authority%%/*}"
  case "$authority" in
    *:*) port="${authority##*:}" ;;
    *) port="$API_PORT" ;;
  esac
  validate_port "api meta port" "$port"
  printf "%s" "$port"
}

port_owner_pid() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n 1 || true
  fi
}

wait_for_pid_exit() {
  local pid="$1"
  local timeout_seconds="${2:-10}"
  local elapsed=0
  [[ -z "$pid" ]] && return 0
  while pid_running "$pid"; do
    if (( elapsed >= timeout_seconds )); then
      return 1
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
}

wait_for_port_free() {
  local port="$1"
  local timeout_seconds="${2:-10}"
  local elapsed=0
  while [[ -n "$(port_owner_pid "$port")" ]]; do
    if (( elapsed >= timeout_seconds )); then
      return 1
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
}

assert_api_port_free() {
  local owner_pid
  local running_pid
  owner_pid="$(port_owner_pid "$API_PORT")"
  running_pid="$(api_pid)"
  [[ -z "$owner_pid" ]] && return 0
  if [[ -n "$running_pid" && "$owner_pid" == "$running_pid" ]] && api_pid_owned "$running_pid"; then
    return 0
  fi
  die "api port $API_PORT is already used by pid=$owner_pid; stop it or set API_PORT" 4
}

assert_api_port_free_for_run() {
  local owner_pid
  owner_pid="$(port_owner_pid "$API_PORT")"
  [[ -z "$owner_pid" ]] && return 0
  die "api port $API_PORT is already used by pid=$owner_pid; stop it before ./scripts/dev.sh run or set API_PORT" 4
}
