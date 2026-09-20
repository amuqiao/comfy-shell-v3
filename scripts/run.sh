#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/run.sh <command> [args...]
  ./scripts/run.sh -h|--help

职责:
  日常总入口。编排 dev.sh、remote.sh 和 ComfyUI shell 原子命令，让常用服务管理只记 run.sh。

不负责:
  不直接管理进程、Docker Compose、K8s、远端资源或跨仓库服务。
  精确生命周期和排障可使用 ./scripts/dev.sh、./scripts/remote.sh 或 comfyctl。

运行环境:
  Requires: Bash.
  Dependencies: recipe 调用到的 dev.sh 子命令所需依赖。

命令:
  init dev      初始化 ComfyUI workspace。
  up dev        启动远程开发机常用服务：API + ComfyUI。
  status dev    查看远程开发机常用服务：API + ComfyUI。
  down dev      停止远程开发机常用服务：ComfyUI + API。
  restart dev   重启远程开发机常用服务：先 down dev，再 up dev。
  check dev     检查当前代码目录前置条件。
  logs <target> 查看日志，target 为 api 或 comfyui。
  versions ...  管理 ComfyUI 版本：list/current/fetch/use。
  switch <ref>   拉取指定 ComfyUI ref，设置为 current，并链接共享 models。
  models ...    管理共享 models：list/link/download。
  remote ...    本机侧远程操作：deploy/status/logs/shell/tunnel/sync-dev。
  help          显示帮助。

副作用与保护边界:
  run.sh 只做顺序编排，不吞掉子命令失败，不添加额外兜底。
  dev recipe 表示当前项目在远程开发机上的日常运行全集。
  init dev 执行 ./scripts/dev.sh comfy workspace init。
  up dev 先执行 ./scripts/dev.sh start api，再执行 ./scripts/dev.sh start comfyui。
  status dev 先执行 ./scripts/dev.sh status api，再执行 ./scripts/dev.sh status comfyui。
  down dev 先执行 ./scripts/dev.sh stop comfyui，再执行 ./scripts/dev.sh stop api。
  restart dev 先执行 ./scripts/run.sh down dev，再执行 ./scripts/run.sh up dev。
  check dev 执行 ./scripts/dev.sh doctor。
  versions/models/logs/remote 只转发到对应原子入口，不重复实现业务逻辑。

常用示例:
  ./scripts/run.sh init dev
  ./scripts/run.sh up dev
  ./scripts/run.sh status dev
  ./scripts/run.sh logs comfyui
  ./scripts/run.sh switch v0.36.0
  ./scripts/run.sh versions fetch main
  ./scripts/run.sh versions list
  ./scripts/run.sh versions use ComfyUI-main-a1b2c3d
  ./scripts/run.sh models link
  ./scripts/run.sh models download runwayml/stable-diffusion-v1-5 --filename v1-5-pruned.safetensors
  ./scripts/run.sh remote deploy
  ./scripts/run.sh remote tunnel
  ./scripts/run.sh down dev
  ./scripts/run.sh restart dev
  ./scripts/run.sh check dev

Exit Codes:
  0  成功
  2  参数、命令或 recipe 错误
  其他非 0 由 dev.sh、remote.sh 或 comfyctl 透传
EOF
}

command_usage() {
  local name="$1"
  case "$name" in
    init|up|status|down|restart|check)
      cat <<EOF
Usage:
  ./scripts/run.sh ${name} <dev>

职责:
  执行日常快捷 recipe ${name}。查看顶层 help 获取完整配置、输出和退出码合同。

副作用与保护边界:
  dev recipe 表示当前项目在远程开发机上的日常运行全集。
  run.sh 不直接实现进程细节。

常用示例:
  ./scripts/run.sh ${name} dev

Exit Codes:
  0  成功
  2  参数或 recipe 错误
  其他非 0 由 dev.sh 透传
EOF
      ;;
    logs)
      cat <<'EOF'
Usage:
  ./scripts/run.sh logs <api|comfyui>

职责:
  日常查看 API 或 ComfyUI 日志，底层转发到 ./scripts/dev.sh logs。

常用示例:
  ./scripts/run.sh logs api
  ./scripts/run.sh logs comfyui

Exit Codes:
  0  成功
  2  参数错误
  其他非 0 由 dev.sh 透传
EOF
      ;;
    versions)
      cat <<'EOF'
Usage:
  ./scripts/run.sh versions <list|current|fetch|use> [args...]

职责:
  日常管理 ComfyUI 版本，底层转发到 ./scripts/dev.sh comfy versions。

常用示例:
  ./scripts/run.sh versions fetch main
  ./scripts/run.sh versions list
  ./scripts/run.sh versions current
  ./scripts/run.sh versions use ComfyUI-main-a1b2c3d

Exit Codes:
  0  成功
  2  参数错误
  其他非 0 由 ComfyUI shell CLI 透传
EOF
      ;;
    switch)
      cat <<'EOF'
Usage:
  ./scripts/run.sh switch <ref>

职责:
  日常切换 ComfyUI 版本。按顺序执行 fetch ref、use resolved version、models link 和 current 展示。

常用示例:
  ./scripts/run.sh switch v0.36.0
  ./scripts/run.sh switch main

Exit Codes:
  0  成功
  2  参数错误
  其他非 0 由 ComfyUI shell CLI 透传
EOF
      ;;
    models)
      cat <<'EOF'
Usage:
  ./scripts/run.sh models <list|link|download> [args...]

职责:
  日常管理共享 models，底层转发到 ./scripts/dev.sh comfy models。

常用示例:
  ./scripts/run.sh models link
  ./scripts/run.sh models list
  ./scripts/run.sh models download runwayml/stable-diffusion-v1-5 --filename v1-5-pruned.safetensors

Exit Codes:
  0  成功
  2  参数错误
  其他非 0 由 ComfyUI shell CLI 透传
EOF
      ;;
    remote)
      cat <<'EOF'
Usage:
  ./scripts/run.sh remote <deploy|status|logs|shell|tunnel|sync-dev> [args...]

职责:
  本机侧远程日常入口，底层转发到 ./scripts/remote.sh。

常用示例:
  ./scripts/run.sh remote deploy
  ./scripts/run.sh remote status
  ./scripts/run.sh remote logs comfyui
  ./scripts/run.sh remote tunnel

Exit Codes:
  0  成功
  2  参数错误
  其他非 0 由 remote.sh、ssh、git、uv 或远程脚本透传
EOF
      ;;
    *)
      usage >&2
      return 2
      ;;
  esac
}

run_dev_init() {
  section "Run Dev"
  event "RUN" "workspace" "init"
  "$ROOT_DIR/scripts/dev.sh" comfy workspace init
}

run_dev_up() {
  section "Run Dev"
  event "RUN" "api" "start"
  "$ROOT_DIR/scripts/dev.sh" start api
  event "RUN" "comfyui" "start"
  "$ROOT_DIR/scripts/dev.sh" start comfyui
}

run_dev_status() {
  section "Run Dev"
  event "CHECK" "api" "status"
  "$ROOT_DIR/scripts/dev.sh" status api
  event "CHECK" "comfyui" "status"
  "$ROOT_DIR/scripts/dev.sh" status comfyui
}

run_dev_down() {
  section "Run Dev"
  event "RUN" "comfyui" "stop"
  "$ROOT_DIR/scripts/dev.sh" stop comfyui
  event "RUN" "api" "stop"
  "$ROOT_DIR/scripts/dev.sh" stop api
}

run_dev_restart() {
  run_dev_down
  run_dev_up
}

run_dev_check() {
  section "Run Dev"
  event "CHECK" "dev" "doctor"
  "$ROOT_DIR/scripts/dev.sh" doctor
}

run_logs() {
  local target="$1"
  [[ "$target" == "api" || "$target" == "comfyui" ]] || die "usage: ./scripts/run.sh logs <api|comfyui>" 2
  "$ROOT_DIR/scripts/dev.sh" logs "$target"
}

run_versions() {
  [[ $# -gt 0 ]] || die "usage: ./scripts/run.sh versions <list|current|fetch|use> [args...]" 2
  "$ROOT_DIR/scripts/dev.sh" comfy versions "$@"
}

run_switch() {
  local ref="$1"
  local fetch_output
  local version_name
  local output_file
  [[ -n "$ref" ]] || die "usage: ./scripts/run.sh switch <ref>" 2

  section "Switch ComfyUI"
  event "RUN" "version" "fetch $ref"
  output_file="$(mktemp)"
  if ! "$ROOT_DIR/scripts/dev.sh" comfy versions fetch "$ref" >"$output_file"; then
    cat "$output_file" >&2
    rm -f "$output_file"
    die "failed to fetch ComfyUI ref: $ref" 4
  fi
  fetch_output="$(cat "$output_file")"
  rm -f "$output_file"
  printf "%s\n" "$fetch_output"
  version_name="$(printf "%s" "$fetch_output" | uv run python -c 'import json,sys; print(json.load(sys.stdin)["name"])')"

  event "RUN" "version" "use $version_name"
  "$ROOT_DIR/scripts/dev.sh" comfy versions use "$version_name"
  event "RUN" "models" "link"
  "$ROOT_DIR/scripts/dev.sh" comfy models link
  event "CHECK" "version" "current"
  "$ROOT_DIR/scripts/dev.sh" comfy versions current
}

run_models() {
  [[ $# -gt 0 ]] || die "usage: ./scripts/run.sh models <list|link|download> [args...]" 2
  "$ROOT_DIR/scripts/dev.sh" comfy models "$@"
}

run_remote() {
  [[ $# -gt 0 ]] || die "usage: ./scripts/run.sh remote <deploy|status|logs|shell|tunnel|sync-dev> [args...]" 2
  "$ROOT_DIR/scripts/remote.sh" "$@"
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
  init|up|down|status|restart|check)
    action="$cmd"
    shift
    if args_include_help "$@"; then command_usage "$action"; exit $?; fi
    recipe="${1:-}"
    [[ -n "$recipe" ]] || die "usage: ./scripts/run.sh $action <dev>" 2
    shift
    reject_extra_args "usage: ./scripts/run.sh $action $recipe" "$@"
    case "$action:$recipe" in
      init:dev) run_dev_init ;;
      up:dev) run_dev_up ;;
      down:dev) run_dev_down ;;
      status:dev) run_dev_status ;;
      restart:dev) run_dev_restart ;;
      check:dev) run_dev_check ;;
      *) die "unknown run recipe for $action: $recipe" 2 ;;
    esac
    ;;
  logs)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    target="${1:-}"
    [[ -n "$target" ]] || die "usage: ./scripts/run.sh logs <api|comfyui>" 2
    shift
    reject_extra_args "usage: ./scripts/run.sh logs $target" "$@"
    run_logs "$target"
    ;;
  versions)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    run_versions "$@"
    ;;
  switch)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    ref="${1:-}"
    [[ -n "$ref" ]] || die "usage: ./scripts/run.sh switch <ref>" 2
    shift
    reject_extra_args "usage: ./scripts/run.sh switch $ref" "$@"
    run_switch "$ref"
    ;;
  models)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    run_models "$@"
    ;;
  remote)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    run_remote "$@"
    ;;
  *)
    usage >&2
    die "unknown command: $cmd" 2
    ;;
esac
