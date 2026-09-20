#!/usr/bin/env bash
set -euo pipefail

COMPOSE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$COMPOSE_LIB_DIR/../.." && pwd)}"
source "$ROOT_DIR/scripts/lib/common.sh"

compose_available() {
  docker compose version >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1
}

compose_project_name() {
  local env_file
  local project_name

  env_file="$(env_file_path)"
  project_name="${COMPOSE_PROJECT_NAME:-$(env_value_from COMPOSE_PROJECT_NAME "$env_file")}"
  project_name="${project_name:-fastapi-lite}"
  printf "%s" "$project_name"
}

compose() {
  local env_file
  local resolved_project_name

  env_file="$(env_file_path)"
  resolved_project_name="$(compose_project_name)"

  if docker compose version >/dev/null 2>&1; then
    if [[ -f "$env_file" ]]; then
      docker compose --env-file "$env_file" -p "$resolved_project_name" "$@"
    else
      docker compose -p "$resolved_project_name" "$@"
    fi
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    if [[ -f "$env_file" ]]; then
      docker-compose --env-file "$env_file" -p "$resolved_project_name" "$@"
    else
      docker-compose -p "$resolved_project_name" "$@"
    fi
    return
  fi
  die "Docker Compose is not available. Install Docker Desktop or docker-compose." 2
}

compose_env_value_or_default() {
  local name="$1"
  local default_value="$2"
  local env_file
  local value

  env_file="$(env_file_path)"
  value="${!name:-$(env_value_from "$name" "$env_file")}"
  printf "%s" "${value:-$default_value}"
}

validate_compose_host_port() {
  local name="$1"
  local value="$2"
  case "$value" in
    ''|*[!0-9]*) die "$name must be numeric: $value" 2 ;;
  esac
  if (( value < 1 || value > 65535 )); then
    die "$name must be between 1 and 65535: $value" 2
  fi
}

host_port_listener_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | sort -u | tr '\n' ' ' | sed 's/[[:space:]]*$//' || true
    return 0
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -H -ltnp 2>/dev/null | awk -v port=":$port" '$4 ~ port "$" { print $0 }' | head -n 3 | tr '\n' ' ' | sed 's/[[:space:]]*$//' || true
    return 0
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -an 2>/dev/null | awk -v port=".$port" '$4 ~ port "$" && $6 == "LISTEN" { print $0 }' | head -n 3 | tr '\n' ' ' | sed 's/[[:space:]]*$//' || true
    return 0
  fi
  die "lsof, ss, or netstat is required for host port preflight" 2
}

compose_service_running() {
  local service="$1"
  docker ps \
    --filter "label=com.docker.compose.project=$(compose_project_name)" \
    --filter "label=com.docker.compose.project.working_dir=$ROOT_DIR" \
    --filter "label=com.docker.compose.service=$service" \
    --format '{{.Names}}' 2>/dev/null | head -n 1 || true
}

compose_service_publishes_host_port() {
  local container="$1"
  local container_port="$2"
  local expected_host_port="$3"
  docker port "$container" "$container_port" 2>/dev/null | awk -F: -v port="$expected_host_port" '$NF == port { found = 1 } END { exit found ? 0 : 1 }'
}

assert_compose_host_ports_free() {
  local mode="$1"
  shift
  local entry
  local name
  local default_value
  local port
  local label
  local container_port
  local seen_ports=""
  local owner_pids
  local running_service

  section "Host Ports"
  for entry in "$@"; do
    IFS=: read -r name default_value label container_port <<< "$entry"
    port="$(compose_env_value_or_default "$name" "$default_value")"
    validate_compose_host_port "$name" "$port"

    if [[ "$seen_ports" == *"|$port|"* ]]; then
      die "$mode maps more than one service to host port $port; adjust $name" 4
    fi
    seen_ports="${seen_ports}|${port}|"

    running_service="$(compose_service_running "$label")"
    if [[ -n "$running_service" ]] && compose_service_publishes_host_port "$running_service" "$container_port" "$port"; then
      event "RUNNING" "port" "$name=$port $label container=$running_service"
      continue
    fi

    owner_pids="$(host_port_listener_pids "$port")"
    if [[ -n "$owner_pids" ]]; then
      die "$mode requires $name=$port for $label, but host port $port is already used by pid(s): $owner_pids; set $name to a free port or stop the conflicting service" 4
    fi
    event "OK" "port" "$name=$port $label"
  done
}
