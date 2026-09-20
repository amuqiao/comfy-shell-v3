from __future__ import annotations

from app.comfy.paths import ComfyPaths, comfy_paths
from app.core.config import AppSettings


def init_workspace(settings: AppSettings) -> ComfyPaths:
    paths = comfy_paths(settings)
    for path in (
        paths.root,
        paths.sources,
        paths.versions,
        paths.models,
        paths.logs,
        paths.run,
    ):
        path.mkdir(parents=True, exist_ok=True)
    if not paths.state_file.exists():
        paths.state_file.write_text("{}\n", encoding="utf-8")
    return paths

