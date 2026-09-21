from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


def validate_relative_model_path(value: str, field: str, *, allow_trailing_slash: bool = True) -> str:
    if "\\" in value:
        raise ValueError(f"{field} must use POSIX path separators")
    normalized = value.strip().strip("/")
    path = PurePosixPath(value.strip())
    if not normalized or path.is_absolute() or ".." in path.parts or path.parts == (".",):
        raise ValueError(f"{field} must be a relative path")
    if not allow_trailing_slash and value.strip().endswith("/"):
        raise ValueError(f"{field} must be a file path")
    return normalized


def model_download_lock_path(models_dir: Path, target: str, filename: str | None, repo_id: str | None = None) -> Path:
    target = validate_relative_model_path(target, "target")
    if filename:
        filename = validate_relative_model_path(filename, "filename", allow_trailing_slash=False)
        relative = Path(target) / filename
        return models_dir / ".locks" / relative.with_name(f"{relative.name}.lock")
    safe_repo = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo_id or "huggingface")
    return models_dir / ".locks" / target / f"{safe_repo}.lock"
