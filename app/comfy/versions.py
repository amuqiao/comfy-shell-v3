from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from app.comfy import archives, process
from app.comfy.lock import WorkspaceLock
from app.comfy.models import link_models_unlocked
from app.comfy.paths import comfy_paths
from app.comfy.state import merge_state, utc_now
from app.comfy.workspace import init_workspace
from app.core.config import AppSettings
from app.core.exceptions import AppError

VERSION_META = ".comfy-shell-version.json"


def safe_ref(ref: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", ref).strip("-")
    if not value:
        raise AppError("REQUEST_INVALID", details={"field": "ref", "reason": "empty"})
    return value


def version_id(ref: str, commit: str) -> str:
    return f"ComfyUI-{safe_ref(ref)}-{commit[:7]}"


def fetch_version(settings: AppSettings, ref: str) -> dict[str, Any]:
    paths = init_workspace(settings)
    with WorkspaceLock(paths.lock_file):
        ref_id = safe_ref(ref)
        archive_path = paths.versions / f".download-{ref_id}.zip"
        extract_dir = paths.versions / f".extract-{ref_id}"
        shutil.rmtree(extract_dir, ignore_errors=True)
        archive_path.unlink(missing_ok=True)

        try:
            archives.download_github_archive(settings.comfy.repo_url, ref, archive_path)
            commit = archives.archive_commit(archive_path)
            name = version_id(ref, commit)
            target = paths.versions / name
            if target.exists():
                meta_path = target / VERSION_META
                if not meta_path.exists():
                    raise AppError(
                        "RESOURCE_CONFLICT",
                        details={"reason": "version_dir_missing_meta", "path": str(target)},
                    )
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
                if existing.get("commit") != commit:
                    raise AppError(
                        "RESOURCE_CONFLICT",
                        details={"reason": "version_dir_commit_mismatch", "path": str(target)},
                    )
            else:
                archives.extract_github_archive(archive_path, target, extract_dir)
        finally:
            archive_path.unlink(missing_ok=True)
            shutil.rmtree(extract_dir, ignore_errors=True)
        meta = {
            "name": name,
            "ref": ref,
            "commit": commit,
            "path": str(target),
            "created_at": utc_now(),
        }
        (target / VERSION_META).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return meta


def list_versions(settings: AppSettings) -> list[dict[str, Any]]:
    paths = comfy_paths(settings)
    if not paths.versions.exists():
        return []
    items: list[dict[str, Any]] = []
    for item in sorted(paths.versions.iterdir(), key=lambda value: value.name):
        if not item.is_dir():
            continue
        meta_path = item / VERSION_META
        if meta_path.exists():
            items.append(json.loads(meta_path.read_text(encoding="utf-8")))
        else:
            items.append({"name": item.name, "path": str(item)})
    return items


def current_version(settings: AppSettings) -> dict[str, Any] | None:
    paths = comfy_paths(settings)
    if not paths.current.is_symlink():
        return None
    target = paths.current.resolve()
    meta_path = target / VERSION_META
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {"name": target.name, "path": str(target)}


def use_version(settings: AppSettings, name: str) -> dict[str, Any]:
    paths = init_workspace(settings)
    target = paths.versions / name
    if not target.is_dir():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "version", "name": name})
    with WorkspaceLock(paths.lock_file):
        if process.is_running(paths):
            raise AppError("RESOURCE_CONFLICT", details={"reason": "comfyui_running"})
        tmp = paths.root / ".current.tmp"
        tmp.unlink(missing_ok=True)
        tmp.symlink_to(Path("versions") / name)
        os.replace(tmp, paths.current)
        link_models_unlocked(paths)
        meta = current_version(settings) or {"name": name, "path": str(target)}
        merge_state(
            paths.state_file,
            {
                "current_version": name,
                "current_path": str(target),
                "current_commit": meta.get("commit"),
            },
        )
        return meta
