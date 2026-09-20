from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from fastapi import FastAPI

from app.core.config import AppSettings

HealthStatus = Literal["ok", "failed", "degraded"]
HealthCheckFunc = Callable[[], Awaitable["HealthCheckResult"]]


@dataclass(frozen=True)
class HealthCheckResult:
    name: str
    status: HealthStatus
    details: dict[str, object]


@dataclass(frozen=True)
class HealthCheck:
    name: str
    check: HealthCheckFunc
    timeout_seconds: float = 1
    required: bool = True


class LifecycleProvider(Protocol):
    name: str
    required: bool

    async def startup(self, app: FastAPI, settings: AppSettings) -> Any:
        ...

    async def shutdown(self, app: FastAPI, resource: Any) -> None:
        ...

    def health_check(self, resource: Any) -> HealthCheck | None:
        ...


class HealthCheckRegistry:
    def __init__(self) -> None:
        self._items: dict[str, HealthCheck] = {}
        self._frozen = False

    def register(self, item: HealthCheck) -> None:
        if self._frozen:
            raise RuntimeError("health check registry is frozen")
        if item.name in self._items:
            raise RuntimeError(f"duplicate health check: {item.name}")
        self._items[item.name] = item

    def all(self) -> tuple[HealthCheck, ...]:
        return tuple(self._items.values())

    def freeze(self) -> None:
        self._frozen = True

    def validate(self) -> None:
        for item in self._items.values():
            if item.timeout_seconds <= 0:
                raise RuntimeError(f"health check timeout must be positive: {item.name}")


async def run_health_checks(registry: HealthCheckRegistry) -> dict[str, object]:
    checks = []
    for item in registry.all():
        try:
            result = await asyncio.wait_for(item.check(), timeout=item.timeout_seconds)
        except TimeoutError:
            result = HealthCheckResult(item.name, "failed", {"reason": "timeout"})
        except Exception as exc:
            result = HealthCheckResult(item.name, "failed", {"reason": type(exc).__name__})
        checks.append((item, result))

    required_failed = any(item.required and result.status == "failed" for item, result in checks)
    degraded = any((not item.required and result.status == "failed") or result.status == "degraded" for item, result in checks)
    status = "failed" if required_failed else "degraded" if degraded else "ok"
    return {
        "status": status,
        "checks": [
            {
                "name": result.name,
                "status": result.status,
                "required": item.required,
                "details": result.details,
            }
            for item, result in checks
        ],
    }


async def process_health_check() -> HealthCheckResult:
    return HealthCheckResult(name="process", status="ok", details={})


def build_health_registry() -> HealthCheckRegistry:
    registry = HealthCheckRegistry()
    registry.register(HealthCheck(name="process", check=process_health_check, required=True))
    registry.validate()
    return registry


class LifecycleProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LifecycleProvider] = {}
        self._started: list[tuple[LifecycleProvider, Any]] = []
        self._frozen = False

    def register(self, provider: LifecycleProvider) -> None:
        if self._frozen:
            raise RuntimeError("lifecycle provider registry is frozen")
        if provider.name in self._providers:
            raise RuntimeError(f"duplicate lifecycle provider: {provider.name}")
        self._providers[provider.name] = provider

    def all(self) -> tuple[LifecycleProvider, ...]:
        return tuple(self._providers.values())

    def get_resource(self, name: str) -> Any:
        for provider, resource in self._started:
            if provider.name == name:
                return resource
        raise RuntimeError(f"provider is not started: {name}")

    def freeze(self) -> None:
        self._frozen = True

    def validate(self) -> None:
        if not self._providers:
            raise RuntimeError("lifecycle provider registry must not be empty")

    async def startup(self, app: FastAPI, settings: AppSettings, health_registry: HealthCheckRegistry) -> None:
        self.validate()
        try:
            for provider in self._providers.values():
                resource = await provider.startup(app, settings)
                self._started.append((provider, resource))
                check = provider.health_check(resource)
                if check is not None:
                    health_registry.register(check)
        except Exception as startup_exc:
            try:
                await self.shutdown(app)
            except Exception as cleanup_exc:
                startup_exc.add_note(
                    f"provider cleanup failed after startup failure: {type(cleanup_exc).__name__}: {cleanup_exc}"
                )
            raise
        self.freeze()

    async def shutdown(self, app: FastAPI) -> None:
        errors: list[Exception] = []
        while self._started:
            provider, resource = self._started.pop()
            try:
                await provider.shutdown(app, resource)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError(f"provider shutdown failed: {[type(error).__name__ for error in errors]}")
