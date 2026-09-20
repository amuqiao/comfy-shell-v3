# Drift Checklist

本文保留尚未完成的 P1 方向和每次改动后的漂移检查项。当前事实见 [`../current/implementation.md`](../current/implementation.md)，稳定合同见 [`../contracts/api-contract.md`](../contracts/api-contract.md) 和 [`../contracts/extension-contract.md`](../contracts/extension-contract.md)。

## Current Baseline

- Foundation、HTTP envelope、error registry、operation registry、health registry 和 lifecycle provider registry 已实现。
- registry gate 已覆盖 route/OpenAPI/docs Routes 表的关键 HTTP 合同漂移。
- `items` 示例 CRUD、repository、UnitOfWork、migration 和测试已实现。
- `app.models` 是 ORM metadata 注册入口；migration roundtrip 按 registered metadata 表集合检查。
- Postgres provider、Redis fake boundary、object storage `disabled/local`、shared HTTP client provider 已接入 lifespan。
- `app/tools/example_tool.py` 已作为工具模块范式示例。
- `./scripts/verify.sh check` 是默认验收入口。

## Remaining P1 Gaps

- 真实 Redis adapter 和 Redis integration gate。
- MinIO / S3-compatible object storage adapter 和 integration gate。
- metrics middleware。
- rate limit middleware。
- provider retry / backoff / bulkhead。
- OpenTelemetry / Prometheus 接入。
- Tool Catalog，仅当多个服务确实需要跨模块工具发现时再做。
- 更完整的本地依赖管理脚本，例如 Postgres / Redis compose lifecycle 和 storage 初始化。

## Change Checklist

代码改动后检查：

- [ ] 新 route 已登记到 `app/api/operations.py`，并包含未挂载 path、状态码、auth 要求、route-specific 业务错误码和 schema 名称。
- [ ] 新 route decorator 已声明 `response_model` 和 `operation_responses()`。
- [ ] `docs/contracts/api-contract.md` Routes 表与 operation registry 保持一致。
- [ ] 新错误码已登记到 `app/core/error_registry.py`。
- [ ] 新 ORM model 已登记到 `app/models/__init__.py`，并有同步 migration。
- [ ] 新配置 key 已同步 `sections.py`、`env_manifest.py`、`.env.example` 和测试。
- [ ] 新 provider 通过 lifecycle registry 启动、ready 和关闭。
- [ ] 新工具放在 `app/tools/`，并有 schema、metadata 和测试。
- [ ] 新脚本子命令已同步 help、`scripts/README.md` 和脚本 smoke 测试。
- [ ] README 和 `docs/current/` 没有描述未实现行为。
- [ ] `docs/contracts/` 只写调用者或开发者可依赖的稳定合同。
- [ ] 未完成内容只留在 `docs/plans/`。
- [ ] 普通测试不依赖真实 Postgres / Redis / OSS。
- [ ] PostgreSQL 集成测试只使用专用 `_test` 数据库。

## Acceptance For Closing P1 Items

每个 P1 项完成时必须同时满足：

- 有代码实现。
- 有配置和 provider lifecycle 边界。
- 有 ready 或明确不进入 ready 的理由。
- 有单元测试；真实外部依赖必须有 gated integration 测试。
- 文档从本计划移入 current 或 contract。
- `./scripts/verify.sh check` 通过。
