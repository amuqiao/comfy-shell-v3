from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from app.core.exceptions import AppError

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def github_archive_url(repo_url: str, ref: str) -> str:
    parsed = urlparse(repo_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc == "github.com":
        repo_path = parsed.path.strip("/")
    else:
        raise AppError(
            "CONFIG_INVALID",
            details={"field": "COMFY__REPO_URL", "reason": "must be a GitHub HTTPS repository URL"},
        )

    repo_path = repo_path.removesuffix(".git")
    parts = repo_path.split("/")
    if len(parts) != 2 or not all(parts):
        raise AppError(
            "CONFIG_INVALID",
            details={"field": "COMFY__REPO_URL", "reason": "must look like https://github.com/owner/repo.git"},
        )
    owner, repo = parts
    return f"https://codeload.github.com/{owner}/{repo}/zip/{quote(ref, safe='')}"


def download_github_archive(repo_url: str, ref: str, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        github_archive_url(repo_url, ref),
        headers={"User-Agent": "comfy-shell-v3"},
    )
    try:
        with urlopen(request, timeout=120) as response:
            with archive_path.open("wb") as output:
                shutil.copyfileobj(response, output)
    except OSError as exc:
        raise AppError(
            "DEPENDENCY_UNAVAILABLE",
            details={"dependency": "github", "message": str(exc)},
        ) from exc


def archive_commit(archive_path: Path) -> str:
    with zipfile.ZipFile(archive_path) as archive:
        commit = archive.comment.decode("utf-8").strip()
    if not COMMIT_RE.fullmatch(commit):
        raise AppError(
            "DEPENDENCY_UNAVAILABLE",
            details={"dependency": "github", "reason": "archive_commit_missing"},
        )
    return commit


def extract_github_archive(archive_path: Path, target_dir: Path, extract_dir: Path) -> None:
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_dir.exists():
        raise AppError("RESOURCE_CONFLICT", details={"reason": "version_dir_exists", "path": str(target_dir)})

    with zipfile.ZipFile(archive_path) as archive:
        top_levels: set[str] = set()
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise AppError(
                    "DEPENDENCY_UNAVAILABLE",
                    details={"dependency": "github", "reason": "unsafe_archive_path", "path": item.filename},
                )
            top_levels.add(path.parts[0])
        if len(top_levels) != 1:
            raise AppError(
                "DEPENDENCY_UNAVAILABLE",
                details={"dependency": "github", "reason": "unexpected_archive_layout"},
            )
        archive.extractall(extract_dir)

    extracted_root = extract_dir / next(iter(top_levels))
    extracted_root.rename(target_dir)
