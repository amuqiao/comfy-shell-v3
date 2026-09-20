#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/run.sh <command> [recipe]
  ./scripts/run.sh -h|--help

职责:
  日常快捷 recipe 入口。只编排 dev.sh 和 deploy.sh 的稳定命令，方便本地高频启停。

不负责:
  不直接管理进程、Docker Compose、K8s、远端资源或跨仓库服务。
  宿主机本地进程请使用 ./scripts/dev.sh；Docker Compose 服务请使用 ./scripts/deploy.sh。

运行环境:
  Requires: Bash.
  Dependencies: recipe 调用到的 dev.sh / deploy.sh 子命令所需依赖。

命令:
  up dev        启动常见本地开发环境：compose-deps + 宿主机 API。
  status dev    查看常见本地开发环境：宿主机 API + compose-deps。
  down dev      停止常见本地开发环境：宿主机 API + compose-deps。
  restart dev   重启常见本地开发环境：先 down dev，再 up dev。
  check dev     检查常见本地开发环境：宿主机前置条件 + Compose/脚本配置。
  help          显示帮助。

副作用与保护边界:
  run.sh 只做顺序编排，不吞掉子命令失败，不添加额外兜底。
  dev recipe 表示当前项目的日常开发环境全集。
  up dev 先执行 ./scripts/deploy.sh up compose-deps，再执行 ./scripts/dev.sh start api。
  status dev 先执行 ./scripts/dev.sh status，再执行 ./scripts/deploy.sh status compose-deps。
  down dev 先执行 ./scripts/dev.sh stop api，再执行 ./scripts/deploy.sh down compose-deps。
  restart dev 先执行 ./scripts/run.sh down dev，再执行 ./scripts/run.sh up dev。
  check dev 先执行 ./scripts/dev.sh doctor，再执行 ./scripts/deploy.sh check。

常用示例:
  ./scripts/run.sh up dev
  ./scripts/run.sh status dev
  ./scripts/run.sh down dev
  ./scripts/run.sh restart dev
  ./scripts/run.sh check dev

Exit Codes:
  0  成功
  2  参数、命令或 recipe 错误
  其他非 0 由 dev.sh 或 deploy.sh 透传
EOF
}

command_usage() {
  local name="$1"
  case "$name" in
    up|status|down|restart|check)
      cat <<EOF
Usage:
  ./scripts/run.sh ${name} <dev>

职责:
  执行日常快捷 recipe ${name}。查看顶层 help 获取完整配置、输出和退出码合同。

副作用与保护边界:
  dev recipe 表示当前项目的日常开发环境全集。
  run.sh 不直接实现进程或 compose 细节。

常用示例:
  ./scripts/run.sh ${name} dev

Exit Codes:
  0  成功
  2  参数或 recipe 错误
  其他非 0 由 dev.sh 或 deploy.sh 透传
EOF
      ;;
    *)
      usage >&2
      return 2
      ;;
  esac
}

run_dev_up() {
  section "Run Dev"
  event "RUN" "compose-deps" "up"
  "$ROOT_DIR/scripts/deploy.sh" up compose-deps
  event "RUN" "api" "start"
  "$ROOT_DIR/scripts/dev.sh" start api
}

run_dev_status() {
  section "Run Dev"
  event "CHECK" "api" "status"
  "$ROOT_DIR/scripts/dev.sh" status
  event "CHECK" "compose-deps" "status"
  "$ROOT_DIR/scripts/deploy.sh" status compose-deps
}

run_dev_down() {
  section "Run Dev"
  event "RUN" "api" "stop"
  "$ROOT_DIR/scripts/dev.sh" stop api
  event "RUN" "compose-deps" "down"
  "$ROOT_DIR/scripts/deploy.sh" down compose-deps
}

run_dev_restart() {
  run_dev_down
  run_dev_up
}

run_dev_check() {
  section "Run Dev"
  event "CHECK" "dev" "doctor"
  "$ROOT_DIR/scripts/dev.sh" doctor
  event "CHECK" "deploy" "check"
  "$ROOT_DIR/scripts/deploy.sh" check
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
  up|down|status|restart|check)
    action="$cmd"
    shift
    if args_include_help "$@"; then command_usage "$action"; exit $?; fi
    recipe="${1:-}"
    [[ -n "$recipe" ]] || die "usage: ./scripts/run.sh $action <dev>" 2
    shift
    reject_extra_args "usage: ./scripts/run.sh $action $recipe" "$@"
    case "$action:$recipe" in
      up:dev) run_dev_up ;;
      down:dev) run_dev_down ;;
      status:dev) run_dev_status ;;
      restart:dev) run_dev_restart ;;
      check:dev) run_dev_check ;;
      *) die "unknown run recipe for $action: $recipe" 2 ;;
    esac
    ;;
  *)
    usage >&2
    die "unknown command: $cmd" 2
    ;;
esac
