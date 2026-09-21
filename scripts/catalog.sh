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
  ComfyUI catalog 原子入口。负责校验、查看、按 catalog 下载模型，以及安装/更新插件。
  模型来源由 catalog/models/*.toml 的 source 字段决定，支持 url、huggingface、local。

不负责:
  不启动或停止服务，不切换 runtime，不安装插件依赖，不修改 workflow JSON。
  日常编排请使用 ./scripts/run.sh catalog ...。

命令:
  validate                         校验 catalog/models、catalog/workflows、catalog/plugins、catalog/assets。
  list <models|workflows|plugins|assets>
                                   列出 catalog 条目。
  show <model|workflow|plugin|asset> <id>
                                   查看模型、工作流、插件或插件额外依赖信息。
  inspect model <id> [--models-dir PATH]
                                   查看模型在目标 models 目录中的本地状态。
  inspect workflow <id> [--models-dir PATH]
                                   查看工作流依赖模型的本地状态矩阵。
  probe model <id>                 探测模型来源链接、大小和可用性，不下载。
  probe workflow <id>              探测工作流依赖模型来源链接、大小和可用性。
  missing workflow <id> [--models-dir PATH]
                                   列出工作流中缺失或校验异常的模型。
  metadata model <id> [--models-dir PATH]
                                   从已落盘模型文件计算 size 和 sha256。
  metadata workflow <id> [--models-dir PATH]
                                   批量计算工作流依赖模型的本地元信息。
  enrich model <id> [--models-dir PATH] [--write] [--overwrite]
                                   根据已落盘模型元信息生成或写回 catalog 补全字段。
  enrich workflow <id> [--models-dir PATH] [--write] [--overwrite]
                                   批量生成或写回工作流依赖模型的 catalog 补全字段。
  download model <id> [--models-dir PATH]
                                   下载指定模型到 models 目录。
  download workflow <id> [--models-dir PATH]
                                   下载指定工作流依赖的全部模型到 models 目录。
  download-bg model <id> [--models-dir PATH]
                                   用 nohup 在远端后台下载指定模型。
  download-bg workflow <id> [--models-dir PATH]
                                   用 nohup 在远端后台下载指定工作流依赖模型。
  download-bg-status <model|workflow> <id>
                                   查看后台下载 pid 和日志位置。
  install plugin <id>              安装指定 git 插件到当前 runtime 的 custom_nodes。
  install plugins                  安装 catalog 中的全部插件。
  update plugin <id>               更新指定已安装 git 插件。
  update plugins                   更新 catalog 中全部已安装插件。
  installed plugins                列出当前 runtime 已安装插件状态。
  installed plugin <id>            查看指定插件安装状态和 git 信息。
  help                             显示帮助。

常用示例:
  ./scripts/catalog.sh validate
  ./scripts/catalog.sh show workflow video_wan2_2_14b_animate
  ./scripts/catalog.sh show asset dwpose_yolox_l
  ./scripts/catalog.sh inspect workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/catalog.sh probe model clip_vision_h
  ./scripts/catalog.sh missing workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/catalog.sh metadata model clip_vision_h --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/catalog.sh enrich workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/catalog.sh download workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/catalog.sh download-bg workflow video_wan2_2_14b_animate --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
  ./scripts/catalog.sh download-bg-status workflow video_wan2_2_14b_animate
  ./scripts/catalog.sh install plugin comfyui_manager
  ./scripts/catalog.sh installed plugins

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

catalog_workspace_dir() {
  local value="${COMFY__WORKSPACE_DIR:-$(env_value COMFY__WORKSPACE_DIR)}"
  [[ -n "$value" ]] || die "COMFY__WORKSPACE_DIR is required for catalog background downloads" 2
  printf "%s" "$value"
}

safe_download_name() {
  local kind="$1"
  local id="$2"
  printf "%s-%s" "$kind" "$id" | tr -c 'A-Za-z0-9_.-' '-'
}

download_bg_paths() {
  local kind="$1"
  local id="$2"
  local workspace
  local safe_name
  workspace="$(catalog_workspace_dir)"
  safe_name="$(safe_download_name "$kind" "$id")"
  printf "%s\n%s\n%s\n%s\n" \
    "$workspace/run/catalog-download-$safe_name.pid" \
    "$workspace/logs/catalog-download-$safe_name.log" \
    "$workspace/run/catalog-download-$safe_name.status" \
    "$workspace/run/catalog-download-$safe_name.sh"
}

download_bg_active_file() {
  local workspace
  workspace="$(catalog_workspace_dir)"
  printf "%s" "$workspace/run/catalog-download.active"
}

download_bg_start_lock_dir() {
  printf "%s.lock" "$(download_bg_active_file)"
}

release_download_bg_start_lock() {
  local start_lock_dir="$1"
  rmdir "$start_lock_dir" 2>/dev/null || true
}

pid_is_running() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" >/dev/null 2>&1
}

print_download_bg_json() {
  local status="$1"
  local kind="$2"
  local id="$3"
  local pid="$4"
  local pid_file="$5"
  local log_file="$6"
  local status_file="$7"
  local runner_file="$8"
  local exit_code="${9:-}"
  local -a python_cmd
  if command -v python3 >/dev/null 2>&1; then
    python_cmd=(python3)
  elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    python_cmd=("$ROOT_DIR/.venv/bin/python")
  else
    require_command uv "install uv first"
    python_cmd=(uv run python)
  fi
  DOWNLOAD_BG_STATUS="$status" \
  DOWNLOAD_BG_KIND="$kind" \
  DOWNLOAD_BG_ID="$id" \
  DOWNLOAD_BG_PID="$pid" \
  DOWNLOAD_BG_PID_FILE="$pid_file" \
  DOWNLOAD_BG_LOG_FILE="$log_file" \
  DOWNLOAD_BG_STATUS_FILE="$status_file" \
  DOWNLOAD_BG_RUNNER_FILE="$runner_file" \
  DOWNLOAD_BG_EXIT_CODE="$exit_code" \
    "${python_cmd[@]}" - <<'PY'
import json
import os


def int_or_none(value: str):
    value = value.strip()
    if value.isdigit():
        return int(value)
    return None


payload = {
    "exit_code": int_or_none(os.environ.get("DOWNLOAD_BG_EXIT_CODE", "")),
    "id": os.environ["DOWNLOAD_BG_ID"],
    "kind": os.environ["DOWNLOAD_BG_KIND"],
    "log_file": os.environ["DOWNLOAD_BG_LOG_FILE"],
    "pid": int_or_none(os.environ.get("DOWNLOAD_BG_PID", "")),
    "pid_file": os.environ["DOWNLOAD_BG_PID_FILE"],
    "runner_file": os.environ["DOWNLOAD_BG_RUNNER_FILE"],
    "status_file": os.environ["DOWNLOAD_BG_STATUS_FILE"],
    "status": os.environ["DOWNLOAD_BG_STATUS"],
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
}

write_download_status() {
  local status_file="$1"
  local status="$2"
  local exit_code="${3:-}"
  local runner_file="${4:-}"
  local tmp_file="$status_file.tmp.$$"
  {
    printf "status=%s\n" "$status"
    printf "exit_code=%s\n" "$exit_code"
    printf "runner_file=%s\n" "$runner_file"
  } > "$tmp_file"
  mv "$tmp_file" "$status_file"
}

read_download_status_value() {
  local status_file="$1"
  local key="$2"
  [[ -f "$status_file" ]] || return 0
  grep -E "^${key}=" "$status_file" 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

write_download_active() {
  local active_file="$1"
  local kind="$2"
  local id="$3"
  local pid="$4"
  local pid_file="$5"
  local log_file="$6"
  local status_file="$7"
  local runner_file="$8"
  local tmp_file="$active_file.tmp.$$"
  {
    printf "kind=%s\n" "$kind"
    printf "id=%s\n" "$id"
    printf "pid=%s\n" "$pid"
    printf "pid_file=%s\n" "$pid_file"
    printf "log_file=%s\n" "$log_file"
    printf "status_file=%s\n" "$status_file"
    printf "runner_file=%s\n" "$runner_file"
  } > "$tmp_file"
  mv "$tmp_file" "$active_file"
}

read_download_active_value() {
  local active_file="$1"
  local key="$2"
  [[ -f "$active_file" ]] || return 0
  grep -E "^${key}=" "$active_file" 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

pid_matches_runner() {
  local pid="$1"
  local runner_file="$2"
  [[ -n "$runner_file" ]] || return 1
  if [[ -r "/proc/$pid/cmdline" ]]; then
    tr '\0' ' ' < "/proc/$pid/cmdline" | grep -F -- "$runner_file" >/dev/null 2>&1
    return $?
  fi
  ps -p "$pid" -o command= 2>/dev/null | grep -F -- "$runner_file" >/dev/null 2>&1
}

write_download_runner() {
  local runner_file="$1"
  local status_file="$2"
  local active_file="$3"
  shift 3
  local command_line=""
  local arg
  for arg in "$@"; do
    command_line+=" $(printf "%q" "$arg")"
  done
  cat > "$runner_file" <<EOF
#!/usr/bin/env bash
set +e
$command_line
rc=\$?
if [ "\$rc" -eq 0 ]; then
  {
    printf "status=%s\\n" completed
    printf "exit_code=%s\\n" "\$rc"
    printf "runner_file=%s\\n" $(printf "%q" "$runner_file")
  } > $(printf "%q" "$status_file.tmp.\$\$")
  mv $(printf "%q" "$status_file.tmp.\$\$") $(printf "%q" "$status_file")
else
  {
    printf "status=%s\\n" failed
    printf "exit_code=%s\\n" "\$rc"
    printf "runner_file=%s\\n" $(printf "%q" "$runner_file")
  } > $(printf "%q" "$status_file.tmp.\$\$")
  mv $(printf "%q" "$status_file.tmp.\$\$") $(printf "%q" "$status_file")
fi
if [ -f $(printf "%q" "$active_file") ] && grep -q "^pid=\$\$\\$" $(printf "%q" "$active_file"); then
  rm -f $(printf "%q" "$active_file")
fi
exit "\$rc"
EOF
  chmod +x "$runner_file"
}

download_bg() {
  local kind="${1:-}"
  local id="${2:-}"
  [[ "$kind" == "model" || "$kind" == "workflow" ]] || die "usage: ./scripts/catalog.sh download-bg <model|workflow> <id> [--models-dir PATH]" 2
  [[ -n "$id" ]] || die "usage: ./scripts/catalog.sh download-bg $kind <id> [--models-dir PATH]" 2
  shift 2

  local pid_file
  local log_file
  local status_file
  local runner_file
  local active_file
  local start_lock_dir
  local existing_pid
  local -a paths
  mapfile -t paths < <(download_bg_paths "$kind" "$id")
  pid_file="${paths[0]}"
  log_file="${paths[1]}"
  status_file="${paths[2]}"
  runner_file="${paths[3]}"
  active_file="$(download_bg_active_file)"
  start_lock_dir="$(download_bg_start_lock_dir)"
  mkdir -p "$(dirname "$pid_file")" "$(dirname "$log_file")" "$(dirname "$status_file")" "$(dirname "$active_file")"
  if ! mkdir "$start_lock_dir" 2>/dev/null; then
    die "catalog background download is starting; retry status or download-bg later" 2
  fi
  trap "release_download_bg_start_lock $(printf "%q" "$start_lock_dir")" RETURN EXIT
  trap "release_download_bg_start_lock $(printf "%q" "$start_lock_dir"); exit 130" INT TERM

  if [[ -f "$active_file" ]]; then
    local active_kind
    local active_id
    local active_pid
    local active_pid_file
    local active_log_file
    local active_status_file
    local active_runner_file
    active_kind="$(read_download_active_value "$active_file" kind)"
    active_id="$(read_download_active_value "$active_file" id)"
    active_pid="$(read_download_active_value "$active_file" pid)"
    active_pid_file="$(read_download_active_value "$active_file" pid_file)"
    active_log_file="$(read_download_active_value "$active_file" log_file)"
    active_status_file="$(read_download_active_value "$active_file" status_file)"
    active_runner_file="$(read_download_active_value "$active_file" runner_file)"
    if pid_is_running "$active_pid" && pid_matches_runner "$active_pid" "$active_runner_file"; then
      release_download_bg_start_lock "$start_lock_dir"
      print_download_bg_json "running" "$active_kind" "$active_id" "$active_pid" "$active_pid_file" "$active_log_file" "$active_status_file" "$active_runner_file"
      return 0
    fi
  fi

  if [[ -f "$pid_file" ]]; then
    existing_pid="$(tr -d '[:space:]' < "$pid_file")"
    if pid_is_running "$existing_pid" && pid_matches_runner "$existing_pid" "$runner_file"; then
      release_download_bg_start_lock "$start_lock_dir"
      print_download_bg_json "running" "$kind" "$id" "$existing_pid" "$pid_file" "$log_file" "$status_file" "$runner_file"
      return 0
    fi
  fi

  write_download_runner "$runner_file" "$status_file" "$active_file" "$SCRIPT_DIR/catalog.sh" download "$kind" "$id" "$@"
  write_download_status "$status_file" "running" "" "$runner_file"
  nohup "$runner_file" >"$log_file" 2>&1 < /dev/null &
  printf "%s\n" "$!" > "$pid_file"
  local pid
  pid="$(tr -d '[:space:]' < "$pid_file")"
  write_download_active "$active_file" "$kind" "$id" "$pid" "$pid_file" "$log_file" "$status_file" "$runner_file"
  release_download_bg_start_lock "$start_lock_dir"
  print_download_bg_json "started" "$kind" "$id" "$pid" "$pid_file" "$log_file" "$status_file" "$runner_file"
}

download_bg_status() {
  local kind="${1:-}"
  local id="${2:-}"
  [[ "$kind" == "model" || "$kind" == "workflow" ]] || die "usage: ./scripts/catalog.sh download-bg-status <model|workflow> <id>" 2
  [[ -n "$id" ]] || die "usage: ./scripts/catalog.sh download-bg-status $kind <id>" 2
  shift 2
  reject_extra_args "usage: ./scripts/catalog.sh download-bg-status $kind $id" "$@"

  local pid_file
  local log_file
  local status_file
  local runner_file
  local pid=""
  local status="missing"
  local exit_code=""
  local -a paths
  mapfile -t paths < <(download_bg_paths "$kind" "$id")
  pid_file="${paths[0]}"
  log_file="${paths[1]}"
  status_file="${paths[2]}"
  runner_file="${paths[3]}"
  if [[ -f "$pid_file" ]]; then
    pid="$(tr -d '[:space:]' < "$pid_file")"
    if pid_is_running "$pid" && pid_matches_runner "$pid" "$runner_file"; then
      status="running"
    else
      status="$(read_download_status_value "$status_file" status)"
      exit_code="$(read_download_status_value "$status_file" exit_code)"
      if [[ -z "$status" || "$status" == "running" ]]; then
        status="exited"
      fi
    fi
  fi
  print_download_bg_json "$status" "$kind" "$id" "$pid" "$pid_file" "$log_file" "$status_file" "$runner_file" "$exit_code"
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
  validate|list|show|inspect|probe|missing|metadata|enrich|download|install|update|installed)
    catalog_cli "$@"
    ;;
  download-bg)
    shift
    download_bg "$@"
    ;;
  download-bg-status)
    shift
    download_bg_status "$@"
    ;;
  *)
    usage >&2
    die "unknown command: $cmd" 2
    ;;
esac
