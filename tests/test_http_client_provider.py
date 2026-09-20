import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.context import REQUEST_ID_HEADER, TRACE_ID_HEADER, set_request_context
from app.integrations.http_client import TraceHeaderAuth, get_http_client


@pytest.mark.asyncio
async def test_http_client_trace_auth_injects_headers():
    seen_headers = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_headers[REQUEST_ID_HEADER] = request.headers[REQUEST_ID_HEADER]
        seen_headers[TRACE_ID_HEADER] = request.headers[TRACE_ID_HEADER]
        return httpx.Response(200)

    set_request_context(request_id="req-out", trace_id="trace-out")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=TraceHeaderAuth()) as client:
        await client.get("https://example.test/")

    assert seen_headers == {REQUEST_ID_HEADER: "req-out", TRACE_ID_HEADER: "trace-out"}


def test_shared_http_client_provider_lifecycle(app):
    with TestClient(app) as client:
        http_client = get_http_client(client.app)
        assert not http_client.is_closed
    assert http_client.is_closed

