from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI

from app.core.config import AppSettings
from app.core.lifecycle import HealthCheck, HealthCheckResult


class ObjectStorage(Protocol):
    async def put(self, key: str, content: bytes) -> None:
        ...

    async def get(self, key: str) -> bytes:
        ...

    async def delete(self, key: str) -> None:
        ...

    async def close(self) -> None:
        ...


class DisabledObjectStorage:
    async def put(self, key: str, content: bytes) -> None:
        raise RuntimeError("object storage is disabled")

    async def get(self, key: str) -> bytes:
        raise RuntimeError("object storage is disabled")

    async def delete(self, key: str) -> None:
        raise RuntimeError("object storage is disabled")

    async def close(self) -> None:
        return None


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("storage key escapes storage root") from exc
        if path == self.root:
            raise ValueError("storage key escapes storage root")
        return path

    async def put(self, key: str, content: bytes) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, content)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)

    async def close(self) -> None:
        return None


class ObjectStorageProvider:
    name = "object_storage"
    required = False

    async def startup(self, app: FastAPI, settings: AppSettings) -> ObjectStorage:
        if settings.storage.backend == "disabled":
            storage: ObjectStorage = DisabledObjectStorage()
        elif settings.storage.backend == "local":
            storage = LocalObjectStorage(Path(settings.storage.local_path))
        else:
            raise RuntimeError("s3_compatible storage adapter is not implemented in the current skeleton")
        app.state.object_storage = storage
        return storage

    async def shutdown(self, app: FastAPI, resource: ObjectStorage) -> None:
        await resource.close()
        if hasattr(app.state, "object_storage"):
            delattr(app.state, "object_storage")

    def health_check(self, resource: ObjectStorage) -> HealthCheck | None:
        async def check() -> HealthCheckResult:
            return HealthCheckResult("object_storage", "ok", {"backend": type(resource).__name__})

        return HealthCheck(name="object_storage", check=check, required=self.required)


def get_storage(app: FastAPI) -> ObjectStorage:
    return app.state.object_storage
