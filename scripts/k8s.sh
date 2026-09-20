#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/k8s.sh <command> [args...]
  ./scripts/k8s.sh -h|--help

职责:
  K8s Pod 内手动运维入口。使用 Pod 内已注入的应用环境变量做配置、PostgreSQL、应用健康和 Alembic 检查。

不负责:
  不调用 kubectl、helm、docker compose。
  不创建或修改 Deployment、Service、Secret、ConfigMap、Job。
  不管理 API 生命周期，不替代 CI/CD 发布编排。

运行环境:
  Requires: Bash, Python.
  Alembic commands require alembic in .venv/bin/alembic, PATH, or uv.
  必须在 K8s Pod 内执行，且 KUBERNETES_SERVICE_HOST 必须存在。

命令:
  check             聚合执行 config、postgres、app、current、heads 检查。
  check config      检查应用配置加载和关键目标，不打印 secret。
  check postgres    检查 DATABASE__URL 解析结果，并执行 PostgreSQL SELECT 1。
  check app         请求 Pod 内 http://127.0.0.1:${API_PORT:-8100}/health 和 /ready。
  current           查看当前数据库 Alembic revision。
  heads             查看代码中的 Alembic head revision。
  history           查看 Alembic revision 历史。
  migrate --confirm 对当前 DATABASE__URL 执行 alembic upgrade head。
  help              显示帮助。

输出:
  stdout: 阶段化检查结果、配置目标、健康检查响应和 Alembic 输出。
  stderr: 非 Pod 环境、缺少依赖、缺少配置、连接失败或迁移失败详情。

副作用与保护边界:
  check/config/postgres/app/current/heads/history 不修改 Kubernetes 资源。
  check postgres 会连接 DATABASE__URL 并执行 SELECT 1。
  migrate 是写库动作，必须显式传入 --confirm。
  生产多副本部署时，只应在一个 Pod 内执行一次 migrate。
  输出不会打印数据库密码、API key 或 storage secret。

常用示例:
  kubectl exec -it <api-pod> -- ./scripts/k8s.sh check
  kubectl exec -it <api-pod> -- ./scripts/k8s.sh check config
  kubectl exec -it <api-pod> -- ./scripts/k8s.sh check postgres
  kubectl exec -it <api-pod> -- ./scripts/k8s.sh check app
  kubectl exec -it <api-pod> -- ./scripts/k8s.sh current
  kubectl exec -it <api-pod> -- ./scripts/k8s.sh migrate --confirm

Exit Codes:
  0  成功
  1  检查运行完成但结果不满足预期
  2  参数、命令、非 Pod 环境、缺少依赖或静态前置条件错误
  其他非 0 由 Python、Alembic 或数据库驱动透传
EOF
}

command_usage() {
  local name="$1"
  local target="${2:-}"
  case "$name:$target" in
    check:)
      cat <<'EOF'
Usage:
  ./scripts/k8s.sh check
  ./scripts/k8s.sh check <config|postgres|app>

职责:
  聚合执行 config、postgres、app、current、heads 检查，或执行单项检查。

常用示例:
  kubectl exec -it <api-pod> -- ./scripts/k8s.sh check
  kubectl exec -it <api-pod> -- ./scripts/k8s.sh check postgres
EOF
      ;;
    check:config|check:postgres|check:app)
      cat <<EOF
Usage:
  ./scripts/k8s.sh check ${target}

职责:
  执行 K8s Pod 内 ${target} 检查。

常用示例:
  kubectl exec -it <api-pod> -- ./scripts/k8s.sh check ${target}
EOF
      ;;
    current:|heads:|history:)
      cat <<EOF
Usage:
  ./scripts/k8s.sh ${name}

职责:
  查看 Alembic ${name} 信息。

常用示例:
  kubectl exec -it <api-pod> -- ./scripts/k8s.sh ${name}
EOF
      ;;
    migrate:)
      cat <<'EOF'
Usage:
  ./scripts/k8s.sh migrate --confirm

职责:
  对当前 DATABASE__URL 执行 alembic upgrade head。

副作用与保护边界:
  写库动作，必须显式传入 --confirm。
  生产多副本部署时，只应在一个 Pod 内执行一次。
EOF
      ;;
    *)
      usage >&2
      return 2
      ;;
  esac
}

require_k8s_pod() {
  [[ -n "${KUBERNETES_SERVICE_HOST:-}" ]] || die "k8s.sh must run inside a K8s Pod; KUBERNETES_SERVICE_HOST is not set" 2
}

require_no_args() {
  local command_name="$1"
  shift
  [[ "$#" -eq 0 ]] || die "$command_name does not accept arguments" 2
}

resolve_python_bin() {
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    printf "%s" "$ROOT_DIR/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  elif command -v uv >/dev/null 2>&1; then
    printf "uv run python"
  else
    die "python is not available in this Pod image" 2
  fi
}

resolve_alembic_bin() {
  if [[ -x "$ROOT_DIR/.venv/bin/alembic" ]]; then
    printf "%s" "$ROOT_DIR/.venv/bin/alembic"
  elif command -v alembic >/dev/null 2>&1; then
    command -v alembic
  elif command -v uv >/dev/null 2>&1; then
    printf "uv run alembic"
  else
    die "alembic is not available in this Pod image" 2
  fi
}

prepare_python_runtime() {
  require_k8s_pod
  PYTHON_BIN="$(resolve_python_bin)"
  export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
}

prepare_alembic_runtime() {
  prepare_python_runtime
  ALEMBIC_BIN="$(resolve_alembic_bin)"
}

run_python() {
  # shellcheck disable=SC2086
  $PYTHON_BIN "$@"
}

run_alembic() {
  # shellcheck disable=SC2086
  $ALEMBIC_BIN "$@"
}

run_check_config() {
  require_no_args "check config" "$@"
  prepare_python_runtime
  section "K8s Config"
  cd "$ROOT_DIR"
  run_python <<'PY' || return 2
from urllib.parse import urlsplit

from app.core.config import get_settings


def url_target(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    database = parsed.path.lstrip("/") or "-"
    port = parsed.port if parsed.port is not None else "-"
    username = parsed.username or "-"
    return f"scheme={parsed.scheme} host={parsed.hostname or '-'} port={port} database={database} user={username} password_present={str(bool(parsed.password)).lower()}"


settings = get_settings()
print(f"runtime_app_env={settings.runtime.app_env}")
print(f"service_name={settings.service.name}")
print(f"service_api_prefix={settings.service.api_prefix}")
print(f"database={url_target(settings.database.url)}")
print(f"database_ssl={str(settings.database.ssl).lower()}")
print(f"redis_enabled={str(settings.redis.enabled).lower()}")
print(f"redis_url_present={str(bool(settings.redis.url)).lower()}")
print(f"storage_backend={settings.storage.backend}")
print(f"http_client_timeout_seconds={settings.http_client.timeout_seconds}")
print("OK config")
PY
}

run_check_postgres() {
  require_no_args "check postgres" "$@"
  prepare_python_runtime
  section "PostgreSQL"
  cd "$ROOT_DIR"
  run_python <<'PY'
import asyncio
import sys
from urllib.parse import urlsplit

import asyncpg

from app.core.config import get_settings


async def main() -> int:
    try:
        settings = get_settings()
    except Exception as exc:
        print(f"ERROR config {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    raw_url = settings.database.url
    parsed = urlsplit(raw_url)
    if not parsed.scheme.startswith("postgresql"):
        print(f"ERROR DATABASE__URL must be PostgreSQL for K8s postgres check: {parsed.scheme}", file=sys.stderr)
        return 2
    port = parsed.port if parsed.port is not None else 5432
    database = parsed.path.lstrip("/")
    print(f"target scheme={parsed.scheme} host={parsed.hostname} port={port} database={database} user={parsed.username or '-'} password_present={str(bool(parsed.password)).lower()}")
    connection = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=port,
        database=database,
        ssl=False if not settings.database.ssl else None,
        timeout=5,
    )
    try:
        value = await connection.fetchval("SELECT 1")
    finally:
        await connection.close()
    print(f"OK postgres select_1={value}")
    return 0


raise SystemExit(asyncio.run(main()))
PY
}

run_check_app() {
  require_no_args "check app" "$@"
  prepare_python_runtime
  section "App"
  cd "$ROOT_DIR"
  run_python <<'PY'
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


host = os.getenv("K8S_CHECK_APP_HOST", "127.0.0.1")
port = os.getenv("API_PORT", "8100")
base_url = os.getenv("K8S_CHECK_APP_URL", f"http://{host}:{port}")
paths = ("/health", "/ready")
status = 0

for path in paths:
    url = f"{base_url.rstrip('/')}{path}"
    try:
        with urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")
            print(f"OK app path={path} status={response.status} body={body}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"ERROR app path={path} status={exc.code} body={body}")
        status = 1
    except URLError as exc:
        print(f"ERROR app path={path} reason={exc.reason}")
        status = 1

raise SystemExit(status)
PY
}

run_check() {
  local target="${1:-}"
  case "$target" in
    "")
      local status=0
      if ! run_check_config; then status=1; fi
      if ! run_check_postgres; then status=1; fi
      if ! run_check_app; then status=1; fi
      if ! run_current; then status=1; fi
      if ! run_heads; then status=1; fi
      return "$status"
      ;;
    config)
      shift
      run_check_config "$@"
      ;;
    postgres)
      shift
      run_check_postgres "$@"
      ;;
    app)
      shift
      run_check_app "$@"
      ;;
    *)
      die "check target must be config, postgres, or app" 2
      ;;
  esac
}

run_current() {
  require_no_args current "$@"
  prepare_alembic_runtime
  section "Alembic"
  cd "$ROOT_DIR"
  run_alembic current
}

run_heads() {
  require_no_args heads "$@"
  prepare_alembic_runtime
  section "Alembic"
  cd "$ROOT_DIR"
  run_alembic heads
}

run_history() {
  require_no_args history "$@"
  prepare_alembic_runtime
  section "Alembic"
  cd "$ROOT_DIR"
  run_alembic history
}

run_migrate() {
  [[ "${1:-}" == "--confirm" ]] || die "migrate requires --confirm because it writes to the configured database" 2
  shift
  require_no_args migrate "$@"
  prepare_alembic_runtime
  section "Alembic"
  cd "$ROOT_DIR"
  event "RUN" "upgrade" "head"
  run_alembic upgrade head
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
  check)
    shift
    if args_include_help "$@"; then
      case "${1:-}" in
        ""|-h|--help) command_usage check ;;
        *) command_usage check "$1" ;;
      esac
      exit $?
    fi
    run_check "$@"
    ;;
  current)
    shift
    if args_include_help "$@"; then command_usage current; exit $?; fi
    run_current "$@"
    ;;
  heads)
    shift
    if args_include_help "$@"; then command_usage heads; exit $?; fi
    run_heads "$@"
    ;;
  history)
    shift
    if args_include_help "$@"; then command_usage history; exit $?; fi
    run_history "$@"
    ;;
  migrate)
    shift
    if args_include_help "$@"; then command_usage migrate; exit $?; fi
    run_migrate "$@"
    ;;
  *)
    usage >&2
    die "unknown command: $cmd" 2
    ;;
esac
