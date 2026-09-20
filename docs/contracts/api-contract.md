# API Contract

本文描述当前调用者可依赖的 HTTP 合同。内部实现细节见 [`../current/implementation.md`](../current/implementation.md)。

## Common Headers

| Header | Direction | Contract |
|---|---|---|
| `X-Request-ID` | request/response | 可由调用方传入；缺失时服务生成；非法值返回 `REQUEST_INVALID`。 |
| `X-Trace-ID` | request/response | 可由调用方传入；缺失时服务生成；非法值返回 `REQUEST_INVALID`。 |
| `Authorization` | request | 受保护接口使用 `Bearer <service_api_key>`。 |

## Envelope

成功响应：

```json
{
  "request_id": "req-...",
  "trace_id": "trace-...",
  "server_time": "2026-07-22T00:00:00Z",
  "code": "OK",
  "data": {}
}
```

错误响应：

```json
{
  "request_id": "req-...",
  "trace_id": "trace-...",
  "server_time": "2026-07-22T00:00:00Z",
  "code": "REQUEST_INVALID",
  "message": "Request is invalid.",
  "retryable": false,
  "details": {}
}
```

## Routes

下表使用默认 `SERVICE__API_PREFIX=/v1` 展示公开路径。代码中的 operation registry 保存未挂载业务路径，例如 `/items`；运行时由 `SERVICE__API_PREFIX` 渲染成公开路径。

| Operation | Method / Path | Auth | Success | Stable Errors |
|---|---|---|---|---|
| `health` | `GET /health` | no | `200` | none |
| `ready` | `GET /ready` | no | `200` | `DEPENDENCY_UNAVAILABLE` |
| `create_item` | `POST /v1/items` | yes | `201` | `UNAUTHORIZED`, `REQUEST_INVALID`, `ITEM_NAME_CONFLICT` |
| `get_item` | `GET /v1/items/{item_id}` | yes | `200` | `UNAUTHORIZED`, `ITEM_NOT_FOUND` |
| `list_items` | `GET /v1/items` | yes | `200` | `UNAUTHORIZED`, `REQUEST_INVALID` |
| `update_item` | `PATCH /v1/items/{item_id}` | yes | `200` | `UNAUTHORIZED`, `REQUEST_INVALID`, `ITEM_NOT_FOUND`, `ITEM_NAME_CONFLICT`, `ITEM_VERSION_CONFLICT` |
| `delete_item` | `DELETE /v1/items/{item_id}` | yes | `200` | `UNAUTHORIZED`, `REQUEST_INVALID`, `ITEM_NOT_FOUND`, `ITEM_VERSION_CONFLICT` |

Cross-cutting errors such as `UNAUTHORIZED`, `REQUEST_INVALID`, and `INTERNAL_ERROR` are defined by the common error contract. `app/api/operations.py` tracks route-specific business errors; the table above lists the caller-visible union where useful.

`GET /ready` returns `200` with `data.status=ok` when all checks pass. If only optional checks fail, it still returns `200` with `data.status=degraded`. If any required check fails, it returns `503 DEPENDENCY_UNAVAILABLE`.

## Items Request Shapes

`POST /v1/items`:

```json
{
  "name": "alpha",
  "description": "optional",
  "status": "active"
}
```

Rules:

- `name`: required, length `1..120`.
- `description`: optional string or null.
- `status`: `draft`, `active`, or `archived`; default is `active`.

`PATCH /v1/items/{item_id}`:

```json
{
  "expected_version": 1,
  "name": "alpha",
  "description": "optional",
  "status": "archived"
}
```

Rules:

- `expected_version`: required, integer `>= 1`.
- Patch fields are optional, but provided values must pass schema validation.
- Stale `expected_version` returns `ITEM_VERSION_CONFLICT`.

`DELETE /v1/items/{item_id}`:

```json
{
  "expected_version": 1
}
```

`GET /v1/items` query:

| Query | Contract |
|---|---|
| `status` | Optional `draft`, `active`, or `archived`. |
| `limit` | Optional integer `1..100`; default `50`. |
| `cursor` | Optional opaque cursor returned by previous page. Invalid cursor returns `REQUEST_INVALID`. |

## Items Response Shape

Item response data:

```json
{
  "id": "uuid",
  "owner_id": "service",
  "name": "alpha",
  "description": null,
  "status": "active",
  "version": 1,
  "created_at": "2026-07-22T00:00:00Z",
  "updated_at": "2026-07-22T00:00:00Z"
}
```

List response data:

```json
{
  "items": [],
  "next_cursor": null,
  "limit": 50
}
```

## Error Codes

| Code | HTTP | Retryable |
|---|---:|---|
| `REQUEST_INVALID` | 422 | no |
| `UNAUTHORIZED` | 401 | no |
| `FORBIDDEN` | 403 | no |
| `RESOURCE_NOT_FOUND` | 404 | no |
| `RESOURCE_CONFLICT` | 409 | no |
| `DEPENDENCY_UNAVAILABLE` | 503 | yes |
| `INTERNAL_ERROR` | 500 | yes |
| `ITEM_NOT_FOUND` | 404 | no |
| `ITEM_NAME_CONFLICT` | 409 | no |
| `ITEM_VERSION_CONFLICT` | 409 | no |

## Compatibility

The public API prefix is configured by `SERVICE__API_PREFIX` and defaults to `/v1`. `./scripts/verify.sh check` verifies mounted route method/path/operation id/success status drift, OpenAPI request schema/error response/security metadata, registered error code validity, API contract route table drift, required docs, env config, migrations, scripts, and tests. Envelope fields, route-specific error sets, and schema names are stable contract surfaces maintained by registry metadata, tests, and this document.
