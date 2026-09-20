#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/runtime.sh"
source "$SCRIPT_DIR/lib/modes.sh"

usage() {
  cat <<EOF
Usage:
  ./scripts/dev.sh <command> [args...]
  ./scripts/dev.sh -h|--help

职责:
  本地开发入口。管理当前仓库的 FastAPI API 进程、开发依赖检查、迁移、端口扫描和测试快捷命令。

不负责:
  不管理 Docker/Compose PostgreSQL、Redis、生产部署、远端资源、真实 Redis/S3 adapter、业务 worker 或跨仓库服务。
  Docker 依赖和 compose-full 生命周期请使用 ./scripts/deploy.sh。
  日常快捷 recipe 请使用 ./scripts/run.sh。

运行环境:
  Requires: Bash, uv, Python.
  Optional: lsof for richer port/process diagnostics.

命令:
  bootstrap        缺少 .env 时从 .env.example 创建，并执行 uv sync --all-groups。
  doctor           检查常用本地开发前置条件、配置文件、端口和脚本入口。
  run              前台运行 FastAPI API，启用 uvicorn --reload。
  start api        后台启动 FastAPI API。
  stop [api]       停止后台 API；省略 api 时等价于 stop api。
  restart [api]    重启后台 API；省略 api 时等价于 restart api。
  status           展示本地 API 进程、端口、URL、配置文件和日志路径。
  logs             tail API 日志。
  migrate          对当前 DATABASE__URL 执行 Alembic upgrade head。
  ports [ports...] 扫描本地端口；支持 --ports、端口范围、--json。
  test             运行 pytest。
  help             显示帮助。

配置与环境变量:
  ENV_FILE     可选，读取 launcher 配置的 env 文件，默认 .env。
  API_HOST     可选，覆盖 API 监听 host，默认 127.0.0.1。
  API_PORT     可选，覆盖 API 监听 port，默认 8100。
  TAIL_LINES   可选，logs 默认 tail 行数，默认 80。

输出:
  stdout: 状态、PID、URL、日志路径、端口扫描结果。
  stderr: 非法命令、缺少依赖、端口占用、配置或迁移失败详情。

运行产物:
  PID:  ${API_PID_FILE}
  日志: ${API_LOG_FILE}

副作用与保护边界:
  bootstrap 会创建 .env 并同步依赖。
  start/restart 会启动本地后台进程，并拒绝占用中的 API_PORT。
  stop 会停止本脚本 PID 文件记录的 API 进程。
  start/stop/restart/status 只管理本地 API，不启动或停止 Docker PostgreSQL/Redis。
  migrate 会写入 DATABASE__URL 指向的数据库，执行前会拒绝明显非本地 URL。
  doctor/status/ports 不修改服务状态。

成功标准:
  start 成功 = 进程存活且 /health 在超时内可访问。
  doctor 成功 = 必需工具、配置模板、脚本入口和 API_PORT 检查通过。

常用示例:
  ./scripts/dev.sh bootstrap
  ./scripts/dev.sh doctor
  ./scripts/dev.sh ports 8100 25432 26379

  # 常见本地开发：Docker 依赖 + 本地 API。
  ./scripts/run.sh up dev
  ./scripts/run.sh status dev
  ./scripts/run.sh down dev
  ./scripts/run.sh restart dev
  ./scripts/run.sh check dev

  # 精确控制：只操作本地 API 或 Docker 依赖。
  ./scripts/dev.sh restart api
  ./scripts/dev.sh stop api
  ./scripts/deploy.sh up compose-deps
  ./scripts/deploy.sh status compose-deps
  ./scripts/deploy.sh down compose-deps

Exit Codes:
  0  成功
  1  检查运行完成但结果不满足预期
  2  参数、配置或静态前置条件错误
  3  环境保护拒绝
  4  端口、进程、网络、数据库或子任务运行失败
  其他非 0 由 uv、pytest、alembic 或 uvicorn 透传
EOF
}

command_usage() {
  local name="$1"
  case "$name" in
    bootstrap)
      cat <<'EOF'
Usage:
  ./scripts/dev.sh bootstrap

职责:
  缺少 .env 时从 .env.example 创建，并执行 uv sync --all-groups。

副作用与保护边界:
  已存在 .env 时保留原文件。
  会安装或同步 Python 依赖。

常用示例:
  ./scripts/dev.sh bootstrap
EOF
      ;;
    doctor)
      cat <<'EOF'
Usage:
  ./scripts/dev.sh doctor

职责:
  检查本地开发常用前置条件、配置文件、脚本入口和 API 端口状态。

副作用与保护边界:
  只读检查，不启动服务，不修改文件。

常用示例:
  ./scripts/dev.sh doctor
EOF
      ;;
    start|stop|restart)
      local usage_target="api"
      if [[ "$name" == "stop" || "$name" == "restart" ]]; then
        usage_target="[api]"
      fi
      cat <<EOF
Usage:
  ./scripts/dev.sh ${name} ${usage_target}

职责:
  执行本地 API 生命周期子命令 ${name}。查看顶层 help 获取完整配置、输出和退出码合同。

副作用与保护边界:
  start/restart 会启动本地后台进程，并拒绝占用中的 API_PORT。
  stop 只会停止本脚本启动且 PID/metadata 匹配的 API 进程。
  ${name} 不启动或停止 Docker PostgreSQL/Redis；依赖容器请使用 ./scripts/deploy.sh。
  PID 文件陈旧或 PID 不属于当前仓库 uvicorn 时，不会 kill 该进程。

常用示例:
  ./scripts/dev.sh ${name} api

Exit Codes:
  0  成功
  2  参数或前置条件错误
  4  端口、进程或健康检查失败
EOF
      ;;
    run|status|logs|migrate|test)
      cat <<EOF
Usage:
  ./scripts/dev.sh ${name}

职责:
  执行 dev 子命令 ${name}。查看顶层 help 获取完整配置、输出和退出码合同。

副作用与保护边界:
  run 会前台启动 uvicorn。
  migrate 会写入 DATABASE__URL 指向的数据库，并拒绝非本地主机。
  status/logs/test 按各自工具语义执行，不启动后台 API。

常用示例:
  ./scripts/dev.sh ${name}

Exit Codes:
  0  成功
  2  参数或前置条件错误
  3  环境保护拒绝
  其他非 0 由下层工具透传
EOF
      ;;
    ports)
      cat <<'EOF'
Usage:
  ./scripts/dev.sh ports [port ...]
  ./scripts/dev.sh ports --ports 8100,25432 --json

职责:
  扫描本地 TCP 端口并推荐空闲端口。

配置与环境变量:
  不读取 .env，不修改服务状态。

输出:
  默认输出人读扫描结果；--json 输出单个 JSON 文档。

副作用与保护边界:
  只读端口检查，不启动或停止进程。

常用示例:
  ./scripts/dev.sh ports 8100 25432 26379
  ./scripts/dev.sh ports --ports 8000-8010 --json

Exit Codes:
  0  找到空闲端口，或显式传入 --allow-busy
  1  没有可用端口
  2  参数错误
EOF
      ;;
    *)
      usage >&2
      return 2
      ;;
  esac
}

require_uv() {
  require_command uv "install uv first"
}

wait_for_api() {
  local timeout_seconds="${1:-20}"
  local elapsed=0
  while true; do
    if command -v curl >/dev/null 2>&1 && curl -fsS "$API_HEALTH_URL" >/dev/null 2>&1; then
      event "READY" "api" "$API_HEALTH_URL"
      return 0
    fi
    if (( elapsed >= timeout_seconds )); then
      tail -n 60 "$API_LOG_FILE" >&2 2>/dev/null || true
      die "api health check failed after ${timeout_seconds}s; inspect: ./scripts/dev.sh logs" 4
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
}

bootstrap() {
  section "Bootstrap"
  require_uv
  copy_env_example_if_missing
  run_uv sync --all-groups
}

doctor() {
  section "Tools"
  require_uv
  event "OK" "uv" "$(uv --version 2>/dev/null || true)"
  if command -v curl >/dev/null 2>&1; then
    event "OK" "curl" "available"
  else
    die "curl is not available; install curl before using ./scripts/dev.sh start api" 2
  fi
  if command -v lsof >/dev/null 2>&1; then
    event "OK" "lsof" "available"
  elif [[ -L "/proc/$$/cwd" ]]; then
    event "OK" "procfs" "available"
  else
    die "lsof or /proc/<pid>/cwd is required for safe PID ownership checks" 2
  fi

  section "Files"
  require_file "$ROOT_DIR/pyproject.toml"
  event "OK" "pyproject" "present"
  require_file "$ROOT_DIR/.env.example"
  event "OK" ".env.example" "present"
  if [[ -f "$(env_file_path)" ]]; then
    event "OK" "ENV_FILE" "$(env_file_path)"
  else
    event "WARN" "ENV_FILE" "$(env_file_path) not found; run ./scripts/dev.sh bootstrap"
  fi

  section "Runtime"
  validate_port API_PORT "$API_PORT"
  row "api_url" "configured" "$API_URL"
  row "api_health" "configured" "$API_HEALTH_URL"
  if [[ -n "$(port_owner_pid "$API_PORT")" ]]; then
    row "api_port" "busy" "port=$API_PORT pid=$(port_owner_pid "$API_PORT")"
  else
    row "api_port" "free" "port=$API_PORT"
  fi

  section "Scripts"
  "$ROOT_DIR/scripts/dev.sh" help >/dev/null
  "$ROOT_DIR/scripts/deploy.sh" help >/dev/null
  "$ROOT_DIR/scripts/run.sh" help >/dev/null
  "$ROOT_DIR/scripts/verify.sh" help >/dev/null
  event "OK" "entrypoints" "help commands"
}

run_api() {
  require_uv
  validate_port API_PORT "$API_PORT"
  assert_no_compose_full_api_running_for_local
  assert_api_port_free_for_run
  cd "$ROOT_DIR"
  event "RUN" "api" "url=$API_URL docs=$API_DOCS_URL"
  exec uv run uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" --reload
}

start_api() {
  local python_bin
  local pid
  validate_port API_PORT "$API_PORT"
  if api_running; then
    event "RUNNING" "api" "pid=$(api_pid) url=$API_URL docs=$API_DOCS_URL"
    return 0
  fi
  require_uv
  require_command curl "install curl first"
  require_process_identity_check
  ensure_runtime_dirs
  assert_no_compose_full_api_running_for_local
  assert_api_port_free
  cd "$ROOT_DIR"
  python_bin="$(uv run python -c 'import sys; print(sys.executable)')"
  pid="$(uv run python scripts/dev/start_detached.py --cwd "$ROOT_DIR" --stdout "$API_LOG_FILE" -- "$python_bin" -m uvicorn app.main:app --host "$API_HOST" --port "$API_PORT")"
  echo "$pid" > "$API_PID_FILE"
  {
    printf "pid=%s\n" "$pid"
    printf "root_dir=%s\n" "$ROOT_DIR"
    printf "service=api\n"
    printf "url=%s\n" "$API_URL"
  } > "$API_META_FILE"
  sleep 1
  if ! api_running; then
    tail -n 60 "$API_LOG_FILE" >&2 2>/dev/null || true
    rm -f "$API_PID_FILE"
    rm -f "$API_META_FILE"
    die "api failed to stay running; inspect: ./scripts/dev.sh logs" 4
  fi
  event "STARTED" "api" "pid=$(api_pid) url=$API_URL docs=$API_DOCS_URL log=$API_LOG_FILE"
  wait_for_api 20
}

stop_api() {
  local pid
  local stopped_port
  pid="$(api_pid)"
  stopped_port="$(api_meta_port)"
  if [[ -n "$pid" ]] && pid_running "$pid" && ! api_pid_owned "$pid"; then
    rm -f "$API_PID_FILE" "$API_META_FILE"
    event "STALE" "api" "removed pid file for unowned pid=$pid"
    return 0
  fi
  if ! api_running; then
    rm -f "$API_PID_FILE"
    rm -f "$API_META_FILE"
    event "STOPPED" "api" "not running"
    return 0
  fi
  kill "$pid"
  if ! wait_for_pid_exit "$pid" 10; then
    die "api pid $pid did not exit after 10s" 4
  fi
  rm -f "$API_PID_FILE" "$API_META_FILE"
  if ! wait_for_port_free "$stopped_port" 10; then
    die "api stopped but port $stopped_port is still used by pid=$(port_owner_pid "$stopped_port")" 4
  fi
  event "STOPPED" "api" "pid=$pid"
}

status_api() {
  section "API"
  row "scope" "local-only" "Docker deps: ./scripts/deploy.sh status compose-deps"
  if api_running; then
    row "process" "running" "pid=$(api_pid)"
  else
    row "process" "stopped" "-"
  fi
  row "url" "configured" "$API_URL"
  row "docs" "configured" "$API_DOCS_URL"
  row "openapi" "configured" "$API_OPENAPI_URL"
  row "health" "configured" "$API_HEALTH_URL"
  row "pid_file" "path" "$API_PID_FILE"
  row "log_file" "path" "$API_LOG_FILE"
  local owner
  owner="$(port_owner_pid "$API_PORT")"
  if [[ -n "$owner" ]]; then
    row "port" "busy" "port=$API_PORT pid=$owner"
  else
    row "port" "free" "port=$API_PORT"
  fi
}

logs_api() {
  ensure_runtime_dirs
  touch "$API_LOG_FILE"
  tail -n "$TAIL_LINES" "$API_LOG_FILE"
}

migrate() {
  assert_local_url "DATABASE__URL"
  require_uv
  section "Database"
  cd "$ROOT_DIR"
  uv run alembic upgrade head
}

scan_ports() {
  require_uv
  cd "$ROOT_DIR"
  uv run python scripts/dev/check_ports.py "$@"
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
  bootstrap)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/dev.sh bootstrap" "$@"
    bootstrap
    ;;
  doctor)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/dev.sh doctor" "$@"
    doctor
    ;;
  run)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/dev.sh run" "$@"
    run_api
    ;;
  start)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    [[ "${1:-}" == "api" ]] || die "usage: ./scripts/dev.sh start api" 2
    shift
    reject_extra_args "usage: ./scripts/dev.sh start api" "$@"
    start_api
    ;;
  stop)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    if [[ "${1:-}" == "api" ]]; then shift; fi
    reject_extra_args "usage: ./scripts/dev.sh stop [api]" "$@"
    stop_api
    ;;
  restart)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    if [[ "${1:-}" == "api" ]]; then shift; fi
    reject_extra_args "usage: ./scripts/dev.sh restart [api]" "$@"
    stop_api
    start_api
    ;;
  status)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/dev.sh status" "$@"
    status_api
    ;;
  logs)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/dev.sh logs" "$@"
    logs_api
    ;;
  migrate)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/dev.sh migrate" "$@"
    migrate
    ;;
  ports)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    scan_ports "$@"
    ;;
  test)
    shift
    if args_include_help "$@"; then command_usage "$cmd"; exit $?; fi
    reject_extra_args "usage: ./scripts/dev.sh test" "$@"
    cd "$ROOT_DIR"
    uv run pytest
    ;;
  *)
    usage >&2
    die "unknown command: $cmd" 2
    ;;
esac
