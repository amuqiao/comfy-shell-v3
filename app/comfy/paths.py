from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import AppSettings


@dataclass(frozen=True)
class ComfyPaths:
    root: Path
    sources: Path
    source_repo: Path
    versions: Path
    models: Path
    logs: Path
    run: Path
    current: Path
    state_file: Path
    lock_file: Path
    comfyui_pid_file: Path
    comfyui_meta_file: Path
    comfyui_log_file: Path


def comfy_paths(settings: AppSettings) -> ComfyPaths:
    root = Path(settings.comfy.workspace_dir).expanduser()
    logs = root / "logs"
    run = root / "run"
    return ComfyPaths(
        root=root,
        sources=root / "sources",
        source_repo=root / "sources" / "ComfyUI.git",
        versions=root / "versions",
        models=root / "models",
        logs=logs,
        run=run,
        current=root / "current",
        state_file=root / "state.json",
        lock_file=run / "workspace.lock",
        comfyui_pid_file=run / "comfyui.pid",
        comfyui_meta_file=run / "comfyui.meta",
        comfyui_log_file=logs / "comfyui.log",
    )

