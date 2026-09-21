from __future__ import annotations

import fcntl
from pathlib import Path
from types import TracebackType
from typing import Any

from app.core.exceptions import AppError


class WorkspaceLock:
    def __init__(self, path: Path, *, details: dict[str, Any] | None = None) -> None:
        self.path = path
        self.details = details or {"reason": "workspace_locked"}
        self._file = None

    def __enter__(self) -> "WorkspaceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AppError("RESOURCE_CONFLICT", details=self.details) from exc
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()
