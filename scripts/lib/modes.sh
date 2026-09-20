#!/usr/bin/env bash
set -euo pipefail

MODES_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$MODES_LIB_DIR/../.." && pwd)}"
source "$ROOT_DIR/scripts/lib/runtime.sh"
source "$ROOT_DIR/scripts/lib/compose.sh"

canonical_existing_dir() {
  local path="$1"
  if [[ -d "$path" ]]; then
    (cd "$path" >/dev/null 2>&1 && pwd -P) || printf "%s" "$path"
    return
  fi
  printf "%s" "$path"
}

pid_in_lines() {
  local needle="$1"
  local lines="$2"
  case "$lines" in
    "$needle"|"$needle"$'\n'*|*$'\n'"$needle"|*$'\n'"$needle"$'\n'*) return 0 ;;
    *) return 1 ;;
  esac
}

assert_no_compose_project_name_conflict() {
  local project_name
  local current_working_dir
  local working_dirs
  local working_dir
  local normalized_working_dir
  local conflicting_working_dirs=""

  command -v docker >/dev/null 2>&1 || die "docker is required for compose project checks" 2
  project_name="$(compose_project_name)"
  current_working_dir="$(canonical_existing_dir "$ROOT_DIR")"
  working_dirs="$(docker ps -a \
    --filter "label=com.docker.compose.project=$project_name" \
    --format '{{.Label "com.docker.compose.project.working_dir"}}')" \
    || die "docker ps failed while checking COMPOSE_PROJECT_NAME conflict" 2

  while IFS= read -r working_dir; do
    [[ -n "$working_dir" ]] || continue
    normalized_working_dir="$(canonical_existing_dir "$working_dir")"
    [[ "$normalized_working_dir" != "$current_working_dir" ]] || continue

    if [[ -z "$conflicting_working_dirs" ]]; then
      conflicting_working_dirs="$working_dir"
    elif ! pid_in_lines "$working_dir" "$conflicting_working_dirs"; then
      conflicting_working_dirs="${conflicting_working_dirs}"$'\n'"${working_dir}"
    fi
  done <<< "$working_dirs"

  [[ -z "$conflicting_working_dirs" ]] && return 0
  die "COMPOSE_PROJECT_NAME conflict: project '$project_name' already exists for '${conflicting_working_dirs//$'\n'/, }'" 4
}

compose_api_running() {
  compose_available || return 1
  docker ps \
    --filter "label=com.docker.compose.project.working_dir=$ROOT_DIR" \
    --filter "label=com.docker.compose.service=api" \
    --format '{{.Names}}' 2>/dev/null | head -n 1
}

assert_no_compose_full_api_running_for_local() {
  local api_name
  api_name="$(compose_api_running)"
  [[ -z "$api_name" ]] && return 0
  die "compose-full api is running: $api_name. Stop it before local dev with: ./scripts/deploy.sh down compose-full" 4
}

assert_no_compose_full_api_running_for_deps_down() {
  local api_name
  api_name="$(compose_api_running)"
  [[ -z "$api_name" ]] && return 0
  die "compose-full api is running: $api_name. Stop compose-full before stopping deps with: ./scripts/deploy.sh down compose-full" 4
}

assert_no_local_api_running_for_compose_full() {
  if api_running; then
    die "local api is running: pid=$(api_pid). Stop it before compose-full with: ./scripts/dev.sh stop api" 4
  fi
}
