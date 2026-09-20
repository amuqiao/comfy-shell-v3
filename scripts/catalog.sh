#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/catalog.sh <command> [args...]
  ./scripts/catalog.sh -h|--help

职责:
  ComfyUI catalog 原子入口。负责校验、查看和按 catalog 下载模型。
  模型来源由 catalog/models/*.toml 的 source 字段决定，支持 url、huggingface、local。

不负责:
  不启动或停止服务，不切换 runtime，不安装插件，不修改 workflow JSON。
  日常编排请使用 ./scripts/run.sh catalog ...。

命令:
  validate                         校验 catalog/models、catalog/workflows、catalog/plugins。
  list <models|workflows|plugins>  列出 catalog 条目。
  show <model|workflow|plugin> <id>
                                   查看模型、工作流或插件信息。
  download model <id> [--models-dir PATH]
                                   下载指定模型到 models 目录。
  download workflow <id> [--models-dir PATH]
                                   下载指定工作流依赖的全部模型到 models 目录。
  help                             显示帮助。

常用示例:
  ./scripts/catalog.sh validate
  ./scripts/catalog.sh show workflow video_wan2_2_14b_animate
  ./scripts/catalog.sh download workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models

Exit Codes:
  0  成功
  2  参数、配置或静态前置条件错误
  其他非 0 由 comfyctl 透传
EOF
}

catalog_cli() {
  cd "$ROOT_DIR"
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    "$ROOT_DIR/.venv/bin/python" -m app.comfy.cli catalog "$@"
  else
    require_command uv "install uv first"
    uv run python -m app.comfy.cli catalog "$@"
  fi
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
  validate|list|show|download)
    catalog_cli "$@"
    ;;
  *)
    usage >&2
    die "unknown command: $cmd" 2
    ;;
esac
