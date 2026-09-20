#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/remote.sh <command> [args...]
  ./scripts/remote.sh -h|--help

职责:
  macOS 本机侧远程运维入口。读取本机 .env 里的 REMOTE__* 配置，通过 SSH 操作远程代码目录。

不负责:
  不在远程机器上编辑源码；不直接操作 ComfyUI workspace；不替代远程 ./scripts/run.sh 和 ./scripts/dev.sh。

命令:
  deploy          远程 git pull --ff-only、uv sync --frozen、check、restart dev。
  status          展示本机/远端端口映射，并远程执行 ./scripts/run.sh status dev。
  logs <target>   远程查看日志，target 为 api 或 comfyui。
  shell           SSH 到远程代码目录。
  tunnel          检查端口后建立 API 和 ComfyUI 的 SSH tunnel。
  sync-dev        显式同步本机未提交代码到 REMOTE__SYNC_CODE_DIR。
  help            显示帮助。

配置:
  REMOTE__HOST           必填，例如 47.94.108.140。
  REMOTE__CODE_DIR       必填，例如 /data/wangqiao/comfy-shell-v3。
  REMOTE__SYNC_CODE_DIR  sync-dev 必填，例如 /data/wangqiao/comfy-shell-v3-sync。
  API_PORT               本机和远程 API tunnel 端口，默认 8700。
  COMFY__PORT            本机和远程 ComfyUI tunnel 端口，默认 8188。

端口规则:
  第一版采用同名映射：local API_PORT -> remote API_PORT，local COMFY__PORT -> remote COMFY__PORT。
  tunnel 启动前会拒绝本机端口占用，并要求远端对应端口已经监听。

Exit Codes:
  0  成功
  2  参数或配置错误
  其他非 0 由 ssh、rsync、git、uv 或远程脚本透传
EOF
}

remote_host() {
  local value="${REMOTE__HOST:-$(env_value REMOTE__HOST)}"
  [[ -n "$value" ]] || die "REMOTE__HOST is required in local .env" 2
  printf "%s" "$value"
}

remote_code_dir() {
  local value="${REMOTE__CODE_DIR:-$(env_value REMOTE__CODE_DIR)}"
  [[ -n "$value" ]] || die "REMOTE__CODE_DIR is required in local .env" 2
  printf "%s" "$value"
}

remote_sync_code_dir() {
  local value="${REMOTE__SYNC_CODE_DIR:-$(env_value REMOTE__SYNC_CODE_DIR)}"
  [[ -n "$value" ]] || die "REMOTE__SYNC_CODE_DIR is required for sync-dev" 2
  printf "%s" "$value"
}

api_port() {
  local value="${API_PORT:-$(env_value API_PORT)}"
  printf "%s" "${value:-8700}"
}

comfy_port() {
  local value="${COMFY__PORT:-$(env_value COMFY__PORT)}"
  printf "%s" "${value:-8188}"
}

validate_port_value() {
  local name="$1"
  local value="$2"
  case "$value" in
    ''|*[!0-9]*) die "$name must be numeric: $value" 2 ;;
  esac
  if (( value < 1 || value > 65535 )); then
    die "$name must be between 1 and 65535: $value" 2
  fi
}

local_port_owner_pid() {
  local port="$1"
  require_command lsof "install lsof before using ./scripts/remote.sh tunnel"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n 1 || true
    return 0
  fi
}

assert_distinct_tunnel_ports() {
  local api="$1"
  local comfy="$2"
  [[ "$api" != "$comfy" ]] || die "API_PORT and COMFY__PORT must be different for tunnel: $api" 2
}

assert_local_tunnel_port_free() {
  local label="$1"
  local port="$2"
  local owner
  owner="$(local_port_owner_pid "$port")"
  [[ -z "$owner" ]] || die "local $label tunnel port $port is already used by pid=$owner; stop it or change .env" 4
}

port_is_listening_command() {
  cat <<'EOF'
port_is_loopback_listening() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP@127.0.0.1:"$port" -sTCP:LISTEN -t >/dev/null 2>&1
    return $?
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -H -ltn 2>/dev/null | awk -v addr="127.0.0.1:$port" '$4 == addr { found = 1 } END { exit found ? 0 : 1 }'
    return $?
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -an 2>/dev/null | awk -v colon="127.0.0.1:$port" -v dot="127.0.0.1.$port" '($4 == colon || $4 == dot) && $6 == "LISTEN" { found = 1 } END { exit found ? 0 : 1 }'
    return $?
  fi
  return 2
}
EOF
}

print_port_map() {
  local host="$1"
  local api="$2"
  local comfy="$3"
  section "Port Map"
  row "api" "tunnel" "local 127.0.0.1:$api -> $host:127.0.0.1:$api"
  row "comfyui" "tunnel" "local 127.0.0.1:$comfy -> $host:127.0.0.1:$comfy"
}

remote_run() {
  local command="$1"
  local host
  local code_dir
  host="$(remote_host)"
  code_dir="$(remote_code_dir)"
  ssh "$host" "export PATH=\"\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH\"; cd '$code_dir' && $command"
}

deploy() {
  remote_run "git pull --ff-only && uv sync --frozen && ./scripts/run.sh check dev && ./scripts/run.sh restart dev"
}

status() {
  local host
  local api
  local comfy
  host="$(remote_host)"
  api="$(api_port)"
  comfy="$(comfy_port)"
  validate_port_value API_PORT "$api"
  validate_port_value COMFY__PORT "$comfy"
  print_port_map "$host" "$api" "$comfy"
  remote_port_status "$api" "$comfy"
  remote_run "./scripts/run.sh status dev"
}

remote_port_status() {
  local api="$1"
  local comfy="$2"
  local check_script
  check_script="$(port_is_listening_command)"
  section "Remote Ports"
  remote_run "$check_script
for entry in api:$api comfyui:$comfy; do
  label=\"\${entry%%:*}\"
  port=\"\${entry##*:}\"
  if port_is_loopback_listening \"\$port\"; then
    printf '  %-16s %-12s %s\n' \"\$label\" listening \"127.0.0.1:\$port\"
  else
    status=\$?
    if [ \"\$status\" -eq 2 ]; then
      printf '  %-16s %-12s %s\n' \"\$label\" unknown \"lsof/ss/netstat unavailable\"
    else
      printf '  %-16s %-12s %s\n' \"\$label\" closed \"127.0.0.1:\$port\"
    fi
  fi
done"
}

assert_remote_tunnel_ports_ready() {
  local api="$1"
  local comfy="$2"
  local check_script
  check_script="$(port_is_listening_command)"
  remote_run "$check_script
for entry in API_PORT:$api COMFY__PORT:$comfy; do
  name=\"\${entry%%:*}\"
  port=\"\${entry##*:}\"
  if port_is_loopback_listening \"\$port\"; then
    continue
  fi
  status=\$?
  if [ \"\$status\" -eq 2 ]; then
    echo \"ERROR: remote port check requires lsof, ss, or netstat\" >&2
    exit 2
  else
    echo \"ERROR: remote \$name port \$port is not listening on 127.0.0.1; start remote services before tunnel\" >&2
    exit 4
  fi
done"
}

logs() {
  local target="${1:-}"
  [[ "$target" == "api" || "$target" == "comfyui" ]] || die "usage: ./scripts/remote.sh logs <api|comfyui>" 2
  remote_run "./scripts/dev.sh logs $target"
}

shell_remote() {
  local host
  local code_dir
  host="$(remote_host)"
  code_dir="$(remote_code_dir)"
  ssh -t "$host" "cd '$code_dir' && exec \$SHELL -l"
}

tunnel() {
  local host
  local api
  local comfy
  host="$(remote_host)"
  api="$(api_port)"
  comfy="$(comfy_port)"
  validate_port_value API_PORT "$api"
  validate_port_value COMFY__PORT "$comfy"
  assert_distinct_tunnel_ports "$api" "$comfy"
  assert_local_tunnel_port_free api "$api"
  assert_local_tunnel_port_free comfyui "$comfy"
  assert_remote_tunnel_ports_ready "$api" "$comfy"
  print_port_map "$host" "$api" "$comfy"
  ssh -N -L "$api:127.0.0.1:$api" -L "$comfy:127.0.0.1:$comfy" "$host"
}

sync_dev() {
  local host
  local target
  host="$(remote_host)"
  target="$(remote_sync_code_dir)"
  rsync -az --delete \
    --exclude ".git/" \
    --exclude ".venv/" \
    --exclude ".run/" \
    --exclude "logs/" \
    --exclude "__pycache__/" \
    "$ROOT_DIR/" "$host:$target/"
}

cmd="${1:-}"
case "$cmd" in
  help|-h|--help)
    usage
    ;;
  "")
    usage >&2
    exit 2
    ;;
  deploy)
    shift
    reject_extra_args "usage: ./scripts/remote.sh deploy" "$@"
    deploy
    ;;
  status)
    shift
    reject_extra_args "usage: ./scripts/remote.sh status" "$@"
    status
    ;;
  logs)
    shift
    logs "$@"
    ;;
  shell)
    shift
    reject_extra_args "usage: ./scripts/remote.sh shell" "$@"
    shell_remote
    ;;
  tunnel)
    shift
    reject_extra_args "usage: ./scripts/remote.sh tunnel" "$@"
    tunnel
    ;;
  sync-dev)
    shift
    reject_extra_args "usage: ./scripts/remote.sh sync-dev" "$@"
    sync_dev
    ;;
  *)
    usage >&2
    die "unknown command: $cmd" 2
    ;;
esac
