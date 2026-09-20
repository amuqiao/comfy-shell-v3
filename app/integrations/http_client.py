from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.core.config import AppSettings
from app.core.context import REQUEST_ID_HEADER, TRACE_ID_HEADER, get_request_id, get_trace_id
from app.core.lifecycle import HealthCheck, HealthCheckResult


class TraceHeaderAuth(httpx.Auth):
    def auth_flow(self, request: httpx.Request):
        request.headers.setdefault(REQUEST_ID_HEADER, get_request_id())
        request.headers.setdefault(TRACE_ID_HEADER, get_trace_id())
        yield request


class HttpClientProvider:
    name = "http_client"
    required = True

    async def startup(self, app: FastAPI, settings: AppSettings) -> httpx.AsyncClient:
        client = httpx.AsyncClient(timeout=settings.http_client.timeout_seconds, auth=TraceHeaderAuth())
        app.state.http_client = client
        return client

    async def shutdown(self, app: FastAPI, resource: httpx.AsyncClient) -> None:
        await resource.aclose()
        if hasattr(app.state, "http_client"):
            delattr(app.state, "http_client")

    def health_check(self, resource: httpx.AsyncClient) -> HealthCheck | None:
        async def check() -> HealthCheckResult:
            return HealthCheckResult("http_client", "failed" if resource.is_closed else "ok", {})

        return HealthCheck(name="http_client", check=check, required=self.required)


def get_http_client(app: FastAPI) -> httpx.AsyncClient:
    return app.state.http_client

