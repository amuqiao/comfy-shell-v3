from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.comfy.paths import ComfyPaths
from app.comfy.lock import WorkspaceLock
from app.comfy.paths import comfy_paths
from app.comfy.state import utc_now
from app.comfy.workspace import init_workspace
from app.core.config import AppSettings
from app.core.exceptions import AppError

ENV_META = ".comfy-shell-env.json"


def run_tool(args: list[str]) -> str:
    executable = shutil.which(args[0])
    if executable is None:
        raise AppError("DEPENDENCY_UNAVAILABLE", details={"dependency": args[0]})
    result = subprocess.run(
        [executable, *args[1:]],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise AppError(
            "DEPENDENCY_UNAVAILABLE",
            details={
                "dependency": args[0],
                "command": args,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            },
        )
    return result.stdout.strip()


def env_dir_for(paths: ComfyPaths, version_name: str) -> Path:
    return paths.envs / version_name


def env_python(env_dir: Path) -> Path:
    return env_dir / "bin" / "python"


def prepare_env_unlocked(
    settings: AppSettings,
    paths: ComfyPaths,
    *,
    version_name: str,
    version_dir: Path,
) -> dict[str, Any]:
    requirements = version_dir / "requirements.txt"
    if not requirements.is_file():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "requirements", "path": str(requirements)})

    env_dir = env_dir_for(paths, version_name)
    python = env_python(env_dir)
    if not python.exists():
        run_tool(["uv", "venv", "--python", settings.comfy.python, str(env_dir)])

    install_command = ["uv", "pip", "install", "--python", str(python)]
    if settings.comfy.pypi_index_url:
        install_command.extend(["--index-url", settings.comfy.pypi_index_url])
    install_command.extend(["-r", str(requirements)])
    run_tool(install_command)

    meta = {
        "version": version_name,
        "env_path": str(env_dir),
        "python": str(python),
        "requirements": str(requirements),
        "pypi_index_url": settings.comfy.pypi_index_url,
        "updated_at": utc_now(),
    }
    (env_dir / ENV_META).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return meta


def use_env_unlocked(paths: ComfyPaths, version_name: str) -> dict[str, str]:
    env_dir = env_dir_for(paths, version_name)
    python = env_python(env_dir)
    if not python.exists():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "env_python", "path": str(python)})

    tmp = paths.root / ".current-env.tmp"
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(Path("envs") / version_name)
    os.replace(tmp, paths.current_env)
    return {"env": str(env_dir), "python": str(python)}


def current_env_python(paths: ComfyPaths) -> Path:
    if not paths.current_env.is_symlink():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "current_env", "path": str(paths.current_env)})
    python = env_python(paths.current_env.resolve())
    if not python.exists():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "env_python", "path": str(python)})
    return python


def prepare_env(settings: AppSettings, version_name: str) -> dict[str, Any]:
    paths = init_workspace(settings)
    version_dir = paths.versions / version_name
    if not version_dir.is_dir():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "version", "name": version_name})
    with WorkspaceLock(paths.lock_file):
        return prepare_env_unlocked(settings, paths, version_name=version_name, version_dir=version_dir)


def list_envs(settings: AppSettings) -> list[dict[str, str]]:
    paths = comfy_paths(settings)
    if not paths.envs.exists():
        return []
    items: list[dict[str, str]] = []
    for item in sorted(paths.envs.iterdir(), key=lambda value: value.name):
        if not item.is_dir():
            continue
        python = env_python(item)
        items.append({"name": item.name, "path": str(item), "python": str(python)})
    return items


def current_env(settings: AppSettings) -> dict[str, str] | None:
    paths = comfy_paths(settings)
    if not paths.current_env.is_symlink():
        return None
    env_dir = paths.current_env.resolve()
    return {"name": env_dir.name, "path": str(env_dir), "python": str(env_python(env_dir))}
