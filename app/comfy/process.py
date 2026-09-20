from __future__ import annotations

import json
import os
import signal
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from app.comfy import runtimes
from app.comfy.lock import WorkspaceLock
from app.comfy.paths import ComfyPaths, comfy_paths
from app.core.config import AppSettings
from app.core.exceptions import AppError


def pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def port_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def current_pid(paths: ComfyPaths) -> int | None:
    if not paths.comfyui_pid_file.exists():
        return None
    raw = paths.comfyui_pid_file.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise AppError("RESOURCE_CONFLICT", details={"reason": "invalid_pid_file", "path": str(paths.comfyui_pid_file)}) from exc


def read_meta(paths: ComfyPaths) -> dict[str, Any]:
    if not paths.comfyui_meta_file.exists():
        return {}
    return json.loads(paths.comfyui_meta_file.read_text(encoding="utf-8"))


def write_meta(paths: ComfyPaths, meta: dict[str, Any]) -> None:
    paths.comfyui_meta_file.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def process_command(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def process_cwd(pid: int) -> Path | None:
    proc_cwd = Path(f"/proc/{pid}/cwd")
    if proc_cwd.exists() or proc_cwd.is_symlink():
        try:
            return proc_cwd.resolve()
        except OSError:
            return None
    if not shutil.which("lsof"):
        return None
    result = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            return Path(line[1:]).resolve()
    return None


def process_owned(paths: ComfyPaths, pid: int) -> bool:
    meta = read_meta(paths)
    if meta.get("pid") != pid:
        return False
    if meta.get("service") != "comfyui":
        return False
    if Path(str(meta.get("workspace", ""))).expanduser().resolve() != paths.root.resolve():
        return False
    command = process_command(pid)
    if "main.py" not in command:
        return False
    expected_cwd = Path(str(meta.get("cwd", ""))).expanduser().resolve()
    cwd = process_cwd(pid)
    return cwd == expected_cwd


def is_running(paths: ComfyPaths) -> bool:
    pid = current_pid(paths)
    return pid is not None and pid_running(pid) and process_owned(paths, pid)


def status(settings: AppSettings) -> dict[str, Any]:
    paths = comfy_paths(settings)
    pid = current_pid(paths)
    running = pid is not None and pid_running(pid) and process_owned(paths, pid)
    stale = pid is not None and not running
    return {
        "running": running,
        "stale": stale,
        "pid": pid,
        "url": f"http://{settings.comfy.host}:{settings.comfy.port}",
        "pid_file": str(paths.comfyui_pid_file),
        "log_file": str(paths.comfyui_log_file),
        "meta": read_meta(paths),
    }


def start(settings: AppSettings) -> dict[str, Any]:
    paths = comfy_paths(settings)
    with WorkspaceLock(paths.lock_file):
        if not paths.current.exists():
            raise AppError("RESOURCE_NOT_FOUND", details={"resource": "current", "path": str(paths.current)})
        if is_running(paths):
            return status(settings)
        if port_busy(settings.comfy.host, settings.comfy.port):
            raise AppError(
                "RESOURCE_CONFLICT",
                details={"reason": "port_busy", "host": settings.comfy.host, "port": settings.comfy.port},
            )
        paths.run.mkdir(parents=True, exist_ok=True)
        paths.logs.mkdir(parents=True, exist_ok=True)
        extra_args = settings.comfy.extra_args.split() if settings.comfy.extra_args.strip() else []
        python = runtimes.current_runtime_python(paths)
        command = [
            str(python),
            "main.py",
            "--listen",
            settings.comfy.host,
            "--port",
            str(settings.comfy.port),
            *extra_args,
        ]
        with paths.comfyui_log_file.open("ab") as output:
            process = subprocess.Popen(
                command,
                cwd=paths.current.resolve(),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
            )
        paths.comfyui_pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
        write_meta(
            paths,
            {
                "pid": process.pid,
                "service": "comfyui",
                "cwd": str(paths.current.resolve()),
                "workspace": str(paths.root),
                "url": f"http://{settings.comfy.host}:{settings.comfy.port}",
                "python": str(python),
                "command": command,
            },
        )
        time.sleep(1)
        if not pid_running(process.pid):
            raise AppError(
                "DEPENDENCY_UNAVAILABLE",
                details={"dependency": "comfyui", "log_file": str(paths.comfyui_log_file)},
            )
        return status(settings)


def stop(settings: AppSettings) -> dict[str, Any]:
    paths = comfy_paths(settings)
    with WorkspaceLock(paths.lock_file):
        pid = current_pid(paths)
        if pid is None or not pid_running(pid):
            paths.comfyui_pid_file.unlink(missing_ok=True)
            paths.comfyui_meta_file.unlink(missing_ok=True)
            return status(settings)
        if not process_owned(paths, pid):
            paths.comfyui_pid_file.unlink(missing_ok=True)
            paths.comfyui_meta_file.unlink(missing_ok=True)
            return status(settings)
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 10
        while time.time() < deadline:
            if not pid_running(pid):
                paths.comfyui_pid_file.unlink(missing_ok=True)
                paths.comfyui_meta_file.unlink(missing_ok=True)
                return status(settings)
            time.sleep(0.2)
        raise AppError("DEPENDENCY_UNAVAILABLE", details={"dependency": "comfyui", "reason": "stop_timeout", "pid": pid})


def tail_log(settings: AppSettings, lines: int = 80) -> str:
    paths = comfy_paths(settings)
    if not paths.comfyui_log_file.exists():
        return ""
    content = paths.comfyui_log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])
