from __future__ import annotations

import filecmp
import os
import shutil
from pathlib import Path

from app.comfy.lock import WorkspaceLock
from app.comfy.paths import ComfyPaths, comfy_paths
from app.comfy.workspace import init_workspace
from app.core.config import AppSettings
from app.core.exceptions import AppError


def link_models(settings: AppSettings) -> dict[str, str]:
    paths = init_workspace(settings)
    with WorkspaceLock(paths.lock_file):
        return link_models_unlocked(paths)


def link_models_unlocked(paths: ComfyPaths) -> dict[str, str]:
    if not paths.current.exists():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "current", "path": str(paths.current)})
    models_link = paths.current / "models"
    paths.models.mkdir(parents=True, exist_ok=True)
    expected = paths.models.resolve()
    if models_link.is_symlink():
        actual = models_link.resolve()
        if actual != expected:
            raise AppError(
                "RESOURCE_CONFLICT",
                details={"reason": "models_link_wrong_target", "actual": str(actual), "expected": str(expected)},
            )
        return {"link": str(models_link), "target": str(expected)}
    if models_link.exists():
        if not models_link.is_dir():
            raise AppError(
                "RESOURCE_CONFLICT",
                details={"reason": "models_path_is_not_symlink", "path": str(models_link)},
            )
        merge_seed_models(models_link, paths.models)
    tmp = models_link.with_name(".models.tmp")
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(os.path.relpath(paths.models.resolve(), start=models_link.parent.resolve()))
    os.replace(tmp, models_link)
    return {"link": str(models_link), "target": str(expected)}


def merge_seed_models(source: Path, target: Path) -> None:
    for source_item in sorted(source.rglob("*"), key=lambda value: len(value.relative_to(source).parts)):
        relative = source_item.relative_to(source)
        target_item = target / relative
        if source_item.is_dir():
            target_item.mkdir(parents=True, exist_ok=True)
            continue
        if not source_item.is_file():
            raise AppError(
                "RESOURCE_CONFLICT",
                details={"reason": "models_seed_unsupported_path", "path": str(source_item)},
            )
        target_item.parent.mkdir(parents=True, exist_ok=True)
        if target_item.exists():
            if target_item.is_file() and filecmp.cmp(source_item, target_item, shallow=False):
                source_item.unlink()
                continue
            raise AppError(
                "RESOURCE_CONFLICT",
                details={
                    "reason": "models_seed_conflict",
                    "source": str(source_item),
                    "target": str(target_item),
                },
            )
        source_item.rename(target_item)
    shutil.rmtree(source)


def list_models(settings: AppSettings) -> list[dict[str, object]]:
    paths = comfy_paths(settings)
    if not paths.models.exists():
        return []
    items: list[dict[str, object]] = []
    for item in sorted(paths.models.rglob("*")):
        if item.is_file():
            items.append({"path": str(item.relative_to(paths.models)), "size": item.stat().st_size})
    return items


def hf_download(settings: AppSettings, repo_id: str, filename: str | None, target: str) -> dict[str, str]:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise AppError("DEPENDENCY_UNAVAILABLE", details={"dependency": "huggingface_hub"}) from exc
    paths = init_workspace(settings)
    target_dir = paths.models / target
    target_dir.mkdir(parents=True, exist_ok=True)
    token = settings.comfy.hf_token.get_secret_value() or None
    downloaded = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=target_dir,
        endpoint=settings.comfy.hf_endpoint,
        token=token,
    )
    return {"path": str(Path(downloaded)), "target": str(target_dir)}
