from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from fastapi import FastAPI

from app.core.config import AppSettings
from app.core.lifecycle import HealthCheck, HealthCheckResult


class RedisClient(Protocol):
    async def get(self, key: str) -> str | None:
        ...

    async def set(self, key: str, value: str) -> None:
        ...

    async def ping(self) -> bool:
        ...

    async def close(self) -> None:
        ...


@dataclass
class FakeRedisClient:
    values: dict[str, str] = field(default_factory=dict)
    closed: bool = False

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str) -> None:
        self.values[key] = value

    async def ping(self) -> bool:
        return not self.closed

    async def close(self) -> None:
        self.closed = True


class RedisProvider:
    name = "redis"
    required = False

    async def startup(self, app: FastAPI, settings: AppSettings) -> RedisClient:
        if settings.redis.enabled:
            raise RuntimeError("real Redis provider is not implemented in the current skeleton")
        client = FakeRedisClient()
        app.state.redis = client
        return client

    async def shutdown(self, app: FastAPI, resource: RedisClient) -> None:
        await resource.close()
        if hasattr(app.state, "redis"):
            delattr(app.state, "redis")

    def health_check(self, resource: RedisClient) -> HealthCheck | None:
        async def check() -> HealthCheckResult:
            ok = await resource.ping()
            return HealthCheckResult("redis", "ok" if ok else "failed", {"fake": True})

        return HealthCheck(name="redis", check=check, required=self.required)


def get_redis_client(app: FastAPI) -> RedisClient:
    return app.state.redis
