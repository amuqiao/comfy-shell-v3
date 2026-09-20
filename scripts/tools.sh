#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/lib/common.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/tools.sh <command> [args...]
  ./scripts/tools.sh -h|--help

职责:
  无默认持久副作用的本地开发工具入口。提供 secret 生成和 env URL 编码。

不负责:
  不启动服务、不运行验证、不部署、不写 .env、不访问网络、不做业务运维。

运行环境:
  Requires: Bash, Python.

命令:
  secret              生成 URL-safe 随机 secret。
  env-url postgres    生成 postgresql+asyncpg DATABASE__URL。
  env-url redis       生成 redis REDIS__URL。
  help                显示帮助。

输出:
  stdout: 子命令结果；secret 只输出生成值；env-url 输出可复制 env 行和注释摘要。
  stderr: 非法命令、非法参数或缺少依赖。

副作用与保护边界:
  默认不读取或修改 .env。
  secret 不访问网络、不写文件。
  env-url 只做 URL encode，不测试连通性。
  推荐使用 --password-stdin，避免密码进入 shell history。

常用示例:
  ./scripts/tools.sh secret
  ./scripts/tools.sh secret --prefix dev_
  printf '%s' 'raw-password' | ./scripts/tools.sh env-url postgres --username postgres --host 127.0.0.1 --port 25432 --database fastapi_lite --password-stdin
  printf '%s' 'raw-password' | ./scripts/tools.sh env-url redis --host 127.0.0.1 --port 26379 --db 0 --password-stdin

Exit Codes:
  0  成功
  2  参数、命令或前置条件错误
EOF
}

secret_usage() {
  cat <<'EOF'
Usage:
  ./scripts/tools.sh secret [--prefix PREFIX]

职责:
  生成 URL-safe 随机 secret，适合本地 SERVICE__API_KEY 或服务间 token。

副作用与保护边界:
  不读取或修改 .env，不访问网络，不写文件。

常用示例:
  ./scripts/tools.sh secret
  ./scripts/tools.sh secret --prefix dev_
EOF
}

env_url_usage() {
  cat <<'EOF'
Usage:
  ./scripts/tools.sh env-url postgres --username USER --host HOST --database DB (--password-stdin | --password PASSWORD) [--port PORT]
  ./scripts/tools.sh env-url redis --host HOST [--username USER] [--password-stdin | --password PASSWORD] [--port PORT] [--db DB]

职责:
  生成标准 DATABASE__URL 或 REDIS__URL，并输出 URL 解析摘要。

副作用与保护边界:
  不读取或修改 .env，不访问网络。
  PostgreSQL 固定输出 async URL：postgresql+asyncpg://...
  摘要不输出原始密码，只显示 password_present。

常用示例:
  printf '%s' 'raw-password' | ./scripts/tools.sh env-url postgres --username postgres --host 127.0.0.1 --database fastapi_lite --password-stdin
  ./scripts/tools.sh env-url redis --host 127.0.0.1 --port 26379 --db 0
EOF
}

resolve_python_bin() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    require_command "$PYTHON_BIN" "install Python 3 or set PYTHON_BIN"
    printf "%s" "$PYTHON_BIN"
  elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    printf "%s" "$ROOT_DIR/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    die "python is not available; run: ./scripts/dev.sh bootstrap" 2
  fi
}

run_secret() {
  local prefix=""
  local python_bin

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h|--help)
        secret_usage
        return 0
        ;;
      --prefix)
        [[ $# -ge 2 ]] || die "--prefix requires a value" 2
        prefix="$2"
        shift 2
        ;;
      --prefix=*)
        prefix="${1#--prefix=}"
        shift
        ;;
      *)
        die "usage: ./scripts/tools.sh secret [--prefix PREFIX]; unexpected argument: $1" 2
        ;;
    esac
  done

  [[ "$prefix" =~ ^[A-Za-z0-9_-]*$ ]] || die "--prefix must contain only URL-safe characters: A-Z a-z 0-9 _ -" 2
  python_bin="$(resolve_python_bin)"
  TOOLS_SECRET_PREFIX="$prefix" "$python_bin" -c 'import os, secrets; print(os.environ["TOOLS_SECRET_PREFIX"] + secrets.token_urlsafe(32))'
}

run_env_url() {
  local python_bin

  if (( $# == 0 )); then
    env_url_usage >&2
    return 2
  fi
  case "${1:-}" in
    -h|--help)
      env_url_usage
      return 0
      ;;
  esac

  python_bin="$(resolve_python_bin)"
  "$python_bin" "$ROOT_DIR/scripts/tools/env_url.py" "$@"
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
  secret)
    shift
    run_secret "$@"
    ;;
  env-url)
    shift
    run_env_url "$@"
    ;;
  *)
    usage >&2
    die "unknown command: $cmd" 2
    ;;
esac
