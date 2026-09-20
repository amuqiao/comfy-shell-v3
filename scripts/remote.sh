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
  status          远程执行 ./scripts/run.sh status dev。
  logs <target>   远程查看日志，target 为 api 或 comfyui。
  shell           SSH 到远程代码目录。
  tunnel          建立 API 和 ComfyUI 的 SSH tunnel。
  sync-dev        显式同步本机未提交代码到 REMOTE__SYNC_CODE_DIR。
  help            显示帮助。

配置:
  REMOTE__HOST           必填，例如 47.94.108.140。
  REMOTE__CODE_DIR       必填，例如 /data/wangqiao/comfy-shell-v3。
  REMOTE__SYNC_CODE_DIR  sync-dev 必填，例如 /data/wangqiao/comfy-shell-v3-sync。
  API_PORT               本机和远程 API tunnel 端口，默认 8700。
  COMFY__PORT            本机和远程 ComfyUI tunnel 端口，默认 8188。

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

remote_run() {
  local command="$1"
  ssh "$(remote_host)" "cd '$(remote_code_dir)' && $command"
}

deploy() {
  remote_run "git pull --ff-only && uv sync --frozen && ./scripts/run.sh check dev && ./scripts/run.sh restart dev"
}

status() {
  remote_run "./scripts/run.sh status dev"
}

logs() {
  local target="${1:-}"
  [[ "$target" == "api" || "$target" == "comfyui" ]] || die "usage: ./scripts/remote.sh logs <api|comfyui>" 2
  remote_run "./scripts/dev.sh logs $target"
}

shell_remote() {
  ssh -t "$(remote_host)" "cd '$(remote_code_dir)' && exec \$SHELL -l"
}

tunnel() {
  local api
  local comfy
  api="$(api_port)"
  comfy="$(comfy_port)"
  ssh -N -L "$api:127.0.0.1:$api" -L "$comfy:127.0.0.1:$comfy" "$(remote_host)"
}

sync_dev() {
  local target
  target="$(remote_sync_code_dir)"
  rsync -az --delete \
    --exclude ".git/" \
    --exclude ".venv/" \
    --exclude ".run/" \
    --exclude "logs/" \
    --exclude "__pycache__/" \
    "$ROOT_DIR/" "$(remote_host):$target/"
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
