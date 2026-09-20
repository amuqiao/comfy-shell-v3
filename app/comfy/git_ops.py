from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.exceptions import AppError


def run_git(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise AppError(
            "DEPENDENCY_UNAVAILABLE",
            details={"dependency": "git", "command": ["git", *args], "message": detail},
        )
    return result.stdout.strip()


def ensure_source_repo(repo_url: str, source_repo: Path) -> None:
    source_repo.parent.mkdir(parents=True, exist_ok=True)
    if source_repo.exists():
        run_git(["--git-dir", str(source_repo), "fetch", "--prune", "--tags", "origin"])
        return
    run_git(["clone", "--mirror", repo_url, str(source_repo)])


def resolve_ref(source_repo: Path, ref: str) -> str:
    return run_git(["--git-dir", str(source_repo), "rev-parse", f"{ref}^{{commit}}"])


def materialize_version(source_repo: Path, target_dir: Path, commit: str) -> None:
    if target_dir.exists():
        current = run_git(["rev-parse", "HEAD"], cwd=target_dir)
        if current != commit:
            raise AppError(
                "RESOURCE_CONFLICT",
                details={"reason": "version_dir_commit_mismatch", "path": str(target_dir)},
            )
        return
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    run_git(["clone", str(source_repo), str(target_dir)])
    run_git(["checkout", "--detach", commit], cwd=target_dir)

