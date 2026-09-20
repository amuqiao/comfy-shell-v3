# Extension Contract

本文说明新业务服务在这套骨架上扩展时应遵守的代码范式。它面向开发者，不面向外部 HTTP 调用者。

## Adding A Business Module

新增业务模块应沿用 `items` 的分层：

```text
app/api/routes/<resource>.py
  -> app/schemas/<resource>.py
  -> app/services/<resource>_service.py
  -> app/repositories/<resource>_repository.py
  -> app/models/<resource>.py
  -> alembic/versions/<revision>.py
  -> tests/test_<resource>_api.py
  -> tests/test_<resource>_service.py
```

Rules:

- Route 负责 HTTP dependency、envelope 和 status code。
- Service 负责事务编排和业务错误映射。
- Service 构造函数必须接收显式 `UowFactory`；不要在 service 内部直接创建 `UnitOfWork()` 或读取全局数据库状态。
- Repository 负责 SQLAlchemy 查询，不提交事务。
- Model 和 migration 必须同步。
- 新 ORM model 必须导入并登记到 `app/models/__init__.py`；Alembic、测试建表和 migration roundtrip 以 registered metadata 为验收来源。
- 新 route 必须登记到 `app/api/operations.py`。
- operation registry 条目必须包含 method、未挂载 path、operation id、成功状态码、auth 要求、route-specific 业务错误码和 schema 名称。业务 API 的公开路径由 `SERVICE__API_PREFIX` 渲染。
- route decorator 必须声明 `response_model`，并使用 `operation_responses(<operation_id>)` 声明注册错误响应。
- 新业务错误码必须登记到 `app/core/error_registry.py`。

Minimum checklist:

- Add request/response schema in `app/schemas/<resource>.py`.
- Add route in `app/api/routes/<resource>.py` and include it from `app.main.create_app()`.
- Add operation metadata in `app/api/operations.py`.
- Add business error codes in `app/core/error_registry.py`.
- Add service and repository modules.
- Add ORM model and register it in `app/models/__init__.py`.
- Add Alembic migration.
- Add API and service tests.
- Update `docs/contracts/api-contract.md` Routes table.
- Run `./scripts/verify.sh check`; run PostgreSQL gates when migrations or PostgreSQL-specific behavior changed.

## Adding Configuration

新增配置必须新增 section 或扩展所属 section，不能把无关字段堆进 `AppSettings`。

Required steps:

1. Add typed fields and validation in `app/core/config/sections.py`.
2. Add cross-section invariants in `app/core/config/validation.py` only when needed.
3. Add env keys to `app/core/config/env_manifest.py`.
4. Update `.env.example`.
5. Add or update config tests.

Providers must consume typed settings objects. They must not read `os.environ` directly.

## Adding Middleware

Middleware is only for cross-request HTTP concerns such as request context, CORS, access log, metrics, rate limit, body-size guard, or trusted host checks. Do not put business rules, database transactions, provider lifecycle, or route-specific authorization into middleware.

Rules:

- Middleware must be explicitly installed in `app.main.create_app()`; the skeleton does not use middleware auto-discovery or a middleware registry.
- If middleware needs configuration, read typed `AppSettings` sections. Do not read `os.environ` directly.
- Middleware constructors must not create network, database, file, or HTTP client resources. External resources must be attached through lifecycle providers and accessed from typed `app.state` getters during requests.
- Middleware that depends on `request_id` or `trace_id` must document its install order and have tests proving context headers, envelope fields, and log context still work.
- Middleware must not swallow exceptions or return bare JSON. Early responses must use registered error codes, the common error envelope, and must write `X-Request-ID` / `X-Trace-ID`.
- New caller-visible HTTP behavior must be reflected in `docs/contracts/api-contract.md`; internal engineering rules belong in this document.
- Add tests for normal pass-through and for the middleware's early-return or failure path.

## Adding A Provider

新增外部依赖必须走 lifecycle provider 范式：

```text
settings
  -> interface / protocol
  -> provider startup
  -> app.state typed resource
  -> health check registration
  -> shutdown
  -> tests
```

Rules:

- Provider constructor must not create real network, database, file, or HTTP resources.
- Startup owns resource creation and startup validation.
- Shutdown must release only resources created or explicitly owned by that provider.
- Readiness checks must reuse started resources and have bounded timeout.
- Business code must use typed dependency/getter, not registry string lookup.
- Unsupported enabled modes must fail fast instead of silently using fake implementations.

## Adding An External Service Client

普通外部 HTTP API 调用不一定需要新增 provider。只有资源需要随应用生命周期统一启动、ready 和关闭时，才按 provider 接入；只调用外部 API 时，优先新增 integration client。

Recommended shape:

```text
settings section
  -> app/integrations/<service>_client.py
  -> shared http_client provider
  -> route or service composition root
  -> AppError mapping
  -> tests
```

Rules:

- 外部服务地址、token、timeout 和开关必须来自 typed settings section，不直接读取 `os.environ`。
- HTTP 调用优先复用 shared `httpx.AsyncClient`，不要在每次请求中创建新的 client。
- 外部请求必须透传当前 `request_id` / `trace_id`，除非对方协议明确不接受这些 header。
- Integration client 负责把外部错误、超时和无效响应收敛成明确的 `AppError` 或内部异常；不要返回裸 dict 让 route 自己猜语义。
- 不要 silent catch 外部错误；如果调用方可见，使用已登记错误码和 common error envelope。
- 不要把业务事务提交放在 integration client 里；事务编排仍属于 service。
- 新 client 应有成功、外部错误、超时或无效响应测试。调用方可见的新失败语义要同步 `app/core/error_registry.py` 和 `docs/contracts/api-contract.md`。

## Adding A Tool

Pure reusable tools belong under `app/tools/`.

Minimum shape:

```text
ToolSpec metadata
input schema
output schema
callable
validation test
behavior tests
```

The current example is `app/tools/example_tool.py`.首版不提供 dynamic tool catalog，也不提供 `invoke_tool(name, payload)`。

## Adding API Contract

For every new route:

- Update `app/api/operations.py` with method, unmounted path, operation id, success status, auth requirement, route-specific business errors, and schema names.
- Add `response_model` and `responses=operation_responses("<operation_id>")` to the route decorator.
- Add API tests for success and route-specific business errors.
- Keep response envelope shape unchanged.
- Use registered `AppError` codes for business failures.
- Access and error logs must preserve `request_id`, `trace_id`, `method`, `path`, `operation_id`, `status`, `duration_ms`, and `error_code` fields.
- Keep `docs/contracts/api-contract.md` Routes table aligned with operation registry; `./scripts/verify.sh registry` checks this drift.
- Run `./scripts/verify.sh check`.

## Verification

Before treating an extension as complete, run:

```bash
./scripts/verify.sh check
```

If the extension changes migrations or Postgres-specific behavior, also run:

```bash
./scripts/verify.sh postgres
./scripts/verify.sh migration-roundtrip
```

## Adding Script Commands

新脚本能力优先扩展现有入口：

- 本地开发生命周期、端口、迁移和环境检查归 `scripts/dev.sh`。
- 一次性验证归 `scripts/verify.sh`。
- Docker Compose 服务接入归 `scripts/deploy.sh`。
- 日常快捷 recipe 归 `scripts/run.sh`；`run.sh` 只编排稳定入口命令，不直接沉淀实现细节。标准 dev recipe 形状是 `up|status|down|restart|check dev`。
- 无默认持久副作用的本地辅助工具归 `scripts/tools.sh`。
- 公共 shell helper 放在 `scripts/lib/`。
- 某个入口的私有复杂 helper 才放进 `scripts/<entry>/`；不要为了目录对称性新增空的 `deploy/` 或 `run/` 子目录。
- 结构化或复杂解析优先用 Python helper，例如 `scripts/dev/check_ports.py`。

Rules:

- 顶层入口必须有 `Usage`、职责、输出、副作用与保护边界、常用示例和 `Exit Codes`。
- 未知命令必须返回 `2`。
- 默认人读输出走 stdout；错误和诊断走 stderr。
- 机器读输出必须显式启用，并保持 stdout 为单一 JSON 文档。
- 不要把业务命令、模型命令、media 命令或远端生产运维命令放进基础骨架。
