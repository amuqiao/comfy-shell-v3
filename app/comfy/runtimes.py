from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.comfy import archives
from app.comfy.lock import WorkspaceLock
from app.comfy.models import link_models_unlocked, validate_models_link_target
from app.comfy.paths import ComfyPaths, comfy_paths
from app.comfy.state import merge_state, utc_now
from app.comfy.workspace import init_workspace
from app.core.config import AppSettings
from app.core.exceptions import AppError

RUNTIME_META = ".comfy-shell-runtime.json"


def safe_runtime_name(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    if not value:
        raise AppError("REQUEST_INVALID", details={"field": "name", "reason": "empty"})
    if value != name:
        raise AppError("REQUEST_INVALID", details={"field": "name", "reason": "unsafe"})
    return value


def runtime_root(paths: ComfyPaths, name: str) -> Path:
    return paths.runtimes / safe_runtime_name(name)


def runtime_comfy_dir(paths: ComfyPaths, name: str) -> Path:
    return runtime_root(paths, name) / "ComfyUI"


def runtime_venv_dir(paths: ComfyPaths, name: str) -> Path:
    return runtime_root(paths, name) / ".venv"


def runtime_python_from_venv(venv_dir: Path) -> Path:
    return venv_dir / "bin" / "python"


def validate_runtime_paths(comfy_dir: Path, venv_dir: Path) -> None:
    main_py = comfy_dir / "main.py"
    python = runtime_python_from_venv(venv_dir)
    if not comfy_dir.is_dir():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "comfy_dir", "path": str(comfy_dir)})
    if not main_py.is_file():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "comfy_main", "path": str(main_py)})
    if not venv_dir.is_dir():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "venv_dir", "path": str(venv_dir)})
    if not python.is_file():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "runtime_python", "path": str(python)})
    if not os.access(python, os.X_OK):
        raise AppError("RESOURCE_CONFLICT", details={"reason": "runtime_python_not_executable", "path": str(python)})


def read_registry(paths: ComfyPaths) -> dict[str, dict[str, Any]]:
    if not paths.runtime_registry_file.exists():
        return {}
    raw = json.loads(paths.runtime_registry_file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AppError(
            "RESOURCE_CONFLICT",
            details={"reason": "invalid_runtime_registry", "path": str(paths.runtime_registry_file)},
        )
    return raw


def write_registry(paths: ComfyPaths, registry: dict[str, dict[str, Any]]) -> None:
    tmp = paths.runtime_registry_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, paths.runtime_registry_file)


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        raise AppError("RESOURCE_CONFLICT", details={"reason": "runtime_target_exists", "path": str(target)})
    executable = shutil.which("rsync")
    if executable is None:
        raise AppError("DEPENDENCY_UNAVAILABLE", details={"dependency": "rsync"})
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [executable, "-a", f"{source.resolve()}/", f"{target}/"],
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise AppError(
            "DEPENDENCY_UNAVAILABLE",
            details={"dependency": "rsync", "returncode": result.returncode, "source": str(source), "target": str(target)},
        )


def import_runtime(settings: AppSettings, name: str, comfy_dir: str, venv_dir: str) -> dict[str, Any]:
    paths = init_workspace(settings)
    runtime_name = safe_runtime_name(name)
    source_comfy_dir = Path(comfy_dir).expanduser().resolve()
    source_venv_dir = Path(venv_dir).expanduser().resolve()
    validate_runtime_paths(source_comfy_dir, source_venv_dir)

    target_root = runtime_root(paths, runtime_name)
    target_comfy_dir = runtime_comfy_dir(paths, runtime_name)
    target_venv_dir = runtime_venv_dir(paths, runtime_name)
    with WorkspaceLock(paths.lock_file):
        registry = read_registry(paths)
        if runtime_name in registry or target_root.exists():
            raise AppError("RESOURCE_CONFLICT", details={"reason": "runtime_exists", "name": runtime_name})
        try:
            copy_tree(source_comfy_dir, target_comfy_dir)
            copy_tree(source_venv_dir, target_venv_dir)
        except Exception:
            shutil.rmtree(target_root, ignore_errors=True)
            raise
        validate_runtime_paths(target_comfy_dir, target_venv_dir)
        meta = {
            "name": runtime_name,
            "comfy_dir": str(target_comfy_dir),
            "venv_dir": str(target_venv_dir),
            "python": str(runtime_python_from_venv(target_venv_dir)),
            "source_comfy_dir": str(source_comfy_dir),
            "source_venv_dir": str(source_venv_dir),
            "imported_at": utc_now(),
        }
        target_root.mkdir(parents=True, exist_ok=True)
        (target_root / RUNTIME_META).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        registry[runtime_name] = meta
        write_registry(paths, registry)
        return meta


def stage_runtime_from_zip(settings: AppSettings, name: str, archive: str, seed_runtime: str) -> dict[str, Any]:
    paths = init_workspace(settings)
    runtime_name = safe_runtime_name(name)
    seed_runtime_name = safe_runtime_name(seed_runtime)
    archive_path = Path(archive).expanduser().resolve()
    if not archive_path.is_file():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "runtime_archive", "path": str(archive_path)})

    target_root = runtime_root(paths, runtime_name)
    target_comfy_dir = runtime_comfy_dir(paths, runtime_name)
    target_venv_dir = runtime_venv_dir(paths, runtime_name)
    extract_dir = paths.staging / f".extract-{runtime_name}"

    with WorkspaceLock(paths.lock_file):
        registry = read_registry(paths)
        if runtime_name in registry or target_root.exists():
            raise AppError("RESOURCE_CONFLICT", details={"reason": "runtime_exists", "name": runtime_name})
        if seed_runtime_name not in registry:
            raise AppError("RESOURCE_NOT_FOUND", details={"resource": "seed_runtime", "name": seed_runtime_name})

        seed_meta = runtime_info(paths, seed_runtime_name)
        seed_venv_dir = Path(seed_meta["venv_dir"])
        commit = archives.archive_commit(archive_path)
        shutil.rmtree(extract_dir, ignore_errors=True)
        meta: dict[str, Any]
        try:
            archives.extract_github_archive(archive_path, target_comfy_dir, extract_dir)
            validate_models_link_target(paths, target_comfy_dir / "models")
            copy_tree(seed_venv_dir, target_venv_dir)
            validate_runtime_paths(target_comfy_dir, target_venv_dir)
            meta = {
                "name": runtime_name,
                "comfy_dir": str(target_comfy_dir),
                "venv_dir": str(target_venv_dir),
                "python": str(runtime_python_from_venv(target_venv_dir)),
                "source_archive": str(archive_path),
                "seed_runtime": seed_runtime_name,
                "seed_venv_dir": str(seed_venv_dir),
                "commit": commit,
                "staged_at": utc_now(),
            }
            target_root.mkdir(parents=True, exist_ok=True)
            (target_root / RUNTIME_META).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            registry[runtime_name] = meta
            write_registry(paths, registry)
        except Exception:
            registry.pop(runtime_name, None)
            shutil.rmtree(target_root, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)
        return meta


def list_runtimes(settings: AppSettings) -> list[dict[str, Any]]:
    paths = comfy_paths(settings)
    return [item for _, item in sorted(read_registry(paths).items())]


def runtime_info(paths: ComfyPaths, name: str) -> dict[str, Any]:
    runtime_name = safe_runtime_name(name)
    registry = read_registry(paths)
    if runtime_name not in registry:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "runtime", "name": runtime_name})
    meta = registry[runtime_name]
    validate_runtime_paths(Path(meta["comfy_dir"]), Path(meta["venv_dir"]))
    return meta


def current_runtime(settings: AppSettings) -> dict[str, Any] | None:
    paths = comfy_paths(settings)
    if not paths.current.is_symlink():
        return None
    current_dir = paths.current.resolve()
    for item in read_registry(paths).values():
        if Path(item["comfy_dir"]).resolve() == current_dir:
            return item
    return {"name": current_dir.name, "comfy_dir": str(current_dir)}


def use_runtime(settings: AppSettings, name: str) -> dict[str, Any]:
    paths = init_workspace(settings)
    with WorkspaceLock(paths.lock_file):
        from app.comfy import process

        if process.is_running(paths):
            raise AppError("RESOURCE_CONFLICT", details={"reason": "comfyui_running"})
        meta = runtime_info(paths, name)
        comfy_dir = Path(meta["comfy_dir"]).resolve()
        venv_dir = Path(meta["venv_dir"]).resolve()
        validate_models_link_target(paths, comfy_dir / "models")
        old_current = paths.current.resolve() if paths.current.is_symlink() else None
        old_env = paths.current_env.resolve() if paths.current_env.is_symlink() else None

        try:
            replace_symlink(paths.root, paths.current, comfy_dir)
            replace_symlink(paths.root, paths.current_env, venv_dir)

            link_models_unlocked(paths)
            merge_state(
                paths.state_file,
                {
                    "current_runtime": meta["name"],
                    "current_path": str(comfy_dir),
                    "current_env": str(venv_dir),
                    "current_env_python": meta["python"],
                },
            )
        except Exception:
            restore_symlink(paths.root, paths.current, old_current)
            restore_symlink(paths.root, paths.current_env, old_env)
            raise
        return meta


def replace_symlink(root: Path, link: Path, target: Path) -> None:
    if link.exists() and not link.is_symlink():
        raise AppError("RESOURCE_CONFLICT", details={"reason": "path_is_not_symlink", "path": str(link)})
    tmp = link.with_name(f".{link.name}.tmp")
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(os.path.relpath(target, start=root.resolve()))
    os.replace(tmp, link)


def restore_symlink(root: Path, link: Path, target: Path | None) -> None:
    if target is None:
        link.unlink(missing_ok=True)
        return
    replace_symlink(root, link, target)


def current_runtime_python(paths: ComfyPaths) -> Path:
    if not paths.current_env.is_symlink():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "current_env", "path": str(paths.current_env)})
    python = runtime_python_from_venv(paths.current_env.resolve())
    if not python.exists():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "runtime_python", "path": str(python)})
    return python
