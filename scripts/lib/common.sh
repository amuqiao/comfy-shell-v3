#!/usr/bin/env bash
set -euo pipefail

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$COMMON_DIR/../.." && pwd)}"
RUN_DIR="${RUN_DIR:-$ROOT_DIR/.run}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"

section() {
  printf "\n== %s ==\n" "$1"
}

event() {
  printf "%-9s %-14s %s\n" "$1" "$2" "${3:-}"
}

row() {
  printf "  %-16s %-12s %s\n" "$1" "$2" "${3:-}"
}

detail() {
  printf "    %-12s %s\n" "${1}:" "$2"
}

die() {
  local message="$1"
  local code="${2:-1}"
  printf "ERROR: %s\n" "$message" >&2
  exit "$code"
}

args_include_help() {
  local arg
  for arg in "$@"; do
    case "$arg" in
      -h|--help)
        return 0
        ;;
    esac
  done
  return 1
}

require_command() {
  local name="$1"
  local hint="${2:-install $1 first}"
  command -v "$name" >/dev/null 2>&1 || die "$name is not available; $hint" 2
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || die "$path not found" 2
}

reject_extra_args() {
  local usage_text="$1"
  shift
  if (( $# > 0 )); then
    die "$usage_text; unexpected argument: $1" 2
  fi
}

require_executable() {
  local path="$1"
  local hint="${2:-make it executable}"
  [[ -x "$path" ]] || die "$path not found or not executable; $hint" 2
}

resolve_repo_path() {
  local path="$1"
  case "$path" in
    /*) printf "%s" "$path" ;;
    *) printf "%s/%s" "$ROOT_DIR" "$path" ;;
  esac
}

env_file_path() {
  resolve_repo_path "${ENV_FILE:-.env}"
}

env_value_from() {
  local key="$1"
  local path="$2"
  [[ -f "$path" ]] || return 0
  grep -E "^${key}=" "$path" 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

env_value() {
  local key="$1"
  env_value_from "$key" "$(env_file_path)"
}

copy_env_example_if_missing() {
  if [[ -f "$ROOT_DIR/.env" ]]; then
    event "EXISTS" ".env" "kept"
    return 0
  fi
  require_file "$ROOT_DIR/.env.example"
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  event "CREATED" ".env" "from .env.example"
}

assert_local_url() {
  local key="$1"
  local value
  local host
  value="${!key:-$(env_value "$key")}"
  [[ -n "$value" ]] || return 0
  require_command uv "install uv first"
  host="$(URL_VALUE="$value" uv run python -c 'from urllib.parse import urlsplit; import os; print(urlsplit(os.environ["URL_VALUE"]).hostname or "")')"
  case "$host" in
    127.0.0.1|localhost|0.0.0.0|::1|host.docker.internal|postgres|redis)
      return 0
      ;;
  esac
  die "$key host does not look local: ${host:-unknown}" 3
}

run_uv() {
  cd "$ROOT_DIR"
  uv "$@"
}
