from __future__ import annotations

import fcntl
from pathlib import Path
from types import TracebackType

from app.core.exceptions import AppError


class WorkspaceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = None

    def __enter__(self) -> "WorkspaceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AppError("RESOURCE_CONFLICT", details={"reason": "workspace_locked"}) from exc
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

