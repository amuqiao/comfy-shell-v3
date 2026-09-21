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
  精确生命周期和排障可使用 ./scripts/dev.sh、./scripts/catalog.sh、./scripts/remote.sh 或 comfyctl。

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
  runtimes ...  管理已导入 ComfyUI runtime：list/current/import/use。
  versions ...  低层版本归档工具：list/current/fetch/use。
  envs ...      低层环境排障工具：list/current/prepare。
  import-runtime <name> --comfy-dir <path> --venv-dir <path>
                复制已有可运行 ComfyUI runtime 到 workspace 规范位置。
  stage-runtime <name> --archive <zip> --seed-runtime <name>
                从 ComfyUI zip 和已有 runtime venv 准备一个新 runtime。
  switch <name>  切换到已导入 runtime，并链接共享 models。
  models ...    管理共享 models：list/link/download。
  catalog ...   管理模型、插件和工作流信息表：validate/list/show/inspect/probe/missing/metadata/enrich/download/download-bg/install/update/installed。
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
  runtimes/versions/envs/models/catalog/logs/remote 只转发到对应原子入口，不重复实现业务逻辑。

常用示例:
  ./scripts/run.sh init dev
  ./scripts/run.sh up dev
  ./scripts/run.sh status dev
  ./scripts/run.sh logs comfyui
  ./scripts/run.sh import-runtime comfyui-0.27.0 --comfy-dir /data/wangqiao/comfy-shell/ComfyUI --venv-dir /data/wangqiao/comfy-shell/.venv
  ./scripts/run.sh stage-runtime comfyui-0.36.0 --archive /data/wangqiao/comfy-shell-v3-workspace/staging/ComfyUI-0.36.0.zip --seed-runtime comfyui-0.27.0-known-good
  ./scripts/run.sh switch comfyui-0.27.0
  ./scripts/run.sh runtimes list
  ./scripts/run.sh runtimes current
  ./scripts/run.sh versions fetch main
  ./scripts/run.sh versions list
  ./scripts/run.sh versions use ComfyUI-main-a1b2c3d
  ./scripts/run.sh envs current
  ./scripts/run.sh models link
  ./scripts/run.sh models download runwayml/stable-diffusion-v1-5 --filename v1-5-pruned.safetensors
  ./scripts/run.sh catalog validate
  ./scripts/run.sh catalog show workflow video_wan2_2_14b_animate
  ./scripts/run.sh catalog inspect workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog probe model clip_vision_h
  ./scripts/run.sh catalog missing workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog metadata model clip_vision_h --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog enrich workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog download workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog download-bg workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog download-bg-status workflow video_wan2_2_14b_animate
  ./scripts/run.sh catalog install plugin comfyui_manager
  ./scripts/run.sh catalog update plugin comfyui_manager
  ./scripts/run.sh catalog installed plugins
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
  低层版本归档工具，底层转发到 ./scripts/dev.sh comfy versions。日常切换优先使用 runtimes。

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
    runtimes)
      cat <<'EOF'
Usage:
  ./scripts/run.sh runtimes <list|current|import|use> [args...]

职责:
  日常管理已复制到 workspace 的 ComfyUI runtime，底层转发到 ./scripts/dev.sh comfy runtimes。

常用示例:
  ./scripts/run.sh runtimes list
  ./scripts/run.sh runtimes current
  ./scripts/run.sh runtimes use comfyui-0.27.0

Exit Codes:
  0  成功
  2  参数错误
  其他非 0 由 ComfyUI shell CLI 透传
EOF
      ;;
    envs)
      cat <<'EOF'
Usage:
  ./scripts/run.sh envs <list|current|prepare> [args...]

职责:
  低层环境排障工具，底层转发到 ./scripts/dev.sh comfy envs。日常启动不依赖自动安装环境。

常用示例:
  ./scripts/run.sh envs list
  ./scripts/run.sh envs current
  ./scripts/run.sh envs prepare ComfyUI-archive-example

Exit Codes:
  0  成功
  2  参数错误
  其他非 0 由 ComfyUI shell CLI 透传
EOF
      ;;
    switch)
      cat <<'EOF'
Usage:
  ./scripts/run.sh switch <name>

职责:
  日常切换已导入 ComfyUI runtime。按顺序执行 runtimes use、models link 和 runtimes current。

常用示例:
  ./scripts/run.sh switch comfyui-0.27.0

Exit Codes:
  0  成功
  2  参数错误
  其他非 0 由 ComfyUI shell CLI 透传
EOF
      ;;
    import-runtime)
      cat <<'EOF'
Usage:
  ./scripts/run.sh import-runtime <name> --comfy-dir <path> --venv-dir <path>

职责:
  复制一个已经验证可运行的 ComfyUI 源码目录和 venv 到 workspace/runtimes/<name>/。

常用示例:
  ./scripts/run.sh import-runtime comfyui-0.27.0 --comfy-dir /data/wangqiao/comfy-shell/ComfyUI --venv-dir /data/wangqiao/comfy-shell/.venv

Exit Codes:
  0  成功
  2  参数错误
  其他非 0 由 ComfyUI shell CLI 透传
EOF
      ;;
    stage-runtime)
      cat <<'EOF'
Usage:
  ./scripts/run.sh stage-runtime <name> --archive <zip> --seed-runtime <name>

职责:
  从一个 ComfyUI zip 源码包和一个已导入 runtime 的 venv 复制出新 runtime，写入 workspace/runtimes.json。

常用示例:
  ./scripts/run.sh stage-runtime comfyui-0.36.0 --archive /data/wangqiao/comfy-shell-v3-workspace/staging/ComfyUI-0.36.0.zip --seed-runtime comfyui-0.27.0-known-good

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
    catalog)
      cat <<'EOF'
Usage:
  ./scripts/run.sh catalog <validate|list|show|inspect|probe|missing|metadata|enrich|download|download-bg|download-bg-status|install|update|installed> [args...]

职责:
  日常管理 catalog 信息表，底层转发到 ./scripts/catalog.sh。

常用示例:
  ./scripts/run.sh catalog validate
  ./scripts/run.sh catalog list workflows
  ./scripts/run.sh catalog show workflow video_wan2_2_14b_animate
  ./scripts/run.sh catalog inspect workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog probe model clip_vision_h
  ./scripts/run.sh catalog missing workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog metadata model clip_vision_h --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog enrich workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog download model wan2_2_animate_14b_fp8_e4m3fn_scaled_kj --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog download workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog download-bg workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/run.sh catalog download-bg-status workflow video_wan2_2_14b_animate
  ./scripts/run.sh catalog install plugin comfyui_manager
  ./scripts/run.sh catalog install plugins
  ./scripts/run.sh catalog update plugin comfyui_manager
  ./scripts/run.sh catalog installed plugins

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

run_runtimes() {
  [[ $# -gt 0 ]] || die "usage: ./scripts/run.sh runtimes <list|current|import|use> [args...]" 2
  "$ROOT_DIR/scripts/dev.sh" comfy runtimes "$@"
}

run_envs() {
  [[ $# -gt 0 ]] || die "usage: ./scripts/run.sh envs <list|current|prepare> [args...]" 2
  "$ROOT_DIR/scripts/dev.sh" comfy envs "$@"
}

run_switch() {
  local name="$1"
  [[ -n "$name" ]] || die "usage: ./scripts/run.sh switch <name>" 2

  section "Switch ComfyUI"
  event "RUN" "runtime" "use $name"
  "$ROOT_DIR/scripts/dev.sh" comfy runtimes use "$name"
  event "RUN" "models" "link"
  "$ROOT_DIR/scripts/dev.sh" comfy models link
  event "CHECK" "runtime" "current"
  "$ROOT_DIR/scripts/dev.sh" comfy runtimes current
}

run_import_runtime() {
  [[ $# -gt 0 ]] || die "usage: ./scripts/run.sh import-runtime <name> --comfy-dir <path> --venv-dir <path>" 2
  "$ROOT_DIR/scripts/dev.sh" comfy runtimes import "$@"
}

run_stage_runtime() {
  [[ $# -gt 0 ]] || die "usage: ./scripts/run.sh stage-runtime <name> --archive <zip> --seed-runtime <name>" 2
  "$ROOT_DIR/scripts/dev.sh" comfy runtimes stage-zip "$@"
}

run_models() {
  [[ $# -gt 0 ]] || die "usage: ./scripts/run.sh models <list|link|download> [args...]" 2
  "$ROOT_DIR/scripts/dev.sh" comfy models "$@"
}

run_catalog() {
  [[ $# -gt 0 ]] || die "usage: ./scripts/run.sh catalog <validate|list|show|inspect|probe|missing|metadata|enrich|download|download-bg|download-bg-status|install|update|installed> [args...]" 2
  "$ROOT_DIR/scripts/catalog.sh" "$@"
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
  runtimes)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    run_runtimes "$@"
    ;;
  envs)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    run_envs "$@"
    ;;
  switch)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    name="${1:-}"
    [[ -n "$name" ]] || die "usage: ./scripts/run.sh switch <name>" 2
    shift
    reject_extra_args "usage: ./scripts/run.sh switch $name" "$@"
    run_switch "$name"
    ;;
  import-runtime)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    run_import_runtime "$@"
    ;;
  stage-runtime)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    run_stage_runtime "$@"
    ;;
  models)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    run_models "$@"
    ;;
  catalog)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    run_catalog "$@"
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
