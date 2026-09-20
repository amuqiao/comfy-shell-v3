# FastAPI Lite Docs

本文是 `fastapi-lite` 的文档入口。`fastapi-lite` 是轻量 FastAPI 服务模板，文档的目标是帮助新服务复用既有工程范式，而不是把某个具体业务平台能力预置进骨架。

## 阅读路径

新服务或新业务接入时，推荐按这个顺序阅读：

```text
notes/FastAPI_Lite 全局心智模型.md
  -> notes/dev-deploy-service-management.md
  -> contracts/extension-contract.md
  -> contracts/api-contract.md
  -> current/implementation.md
  -> plans/drift-checklist.md
  -> ../scripts/README.md
```

各文档职责：

| 文档 | 职责 |
|---|---|
| [全局心智模型](<notes/FastAPI_Lite 全局心智模型.md>) | 快速建立模板边界、业务接入方式、能力放置点和验证思路。 |
| [Service Management 范式](notes/dev-deploy-service-management.md) | 维护 `dev.sh` / `deploy.sh` / `run.sh` 的服务管理规则，指导新项目复用和脚本收敛。 |
| [Extension Contract](contracts/extension-contract.md) | 新增业务模块、配置、provider、middleware、工具和脚本时必须遵守的工程合同。 |
| [API Contract](contracts/api-contract.md) | 当前调用方可依赖的 HTTP header、envelope、route、错误码和兼容性合同。 |
| [Current Implementation](current/implementation.md) | 当前已经实现并由测试覆盖的工程事实。 |
| [Drift Checklist](plans/drift-checklist.md) | 尚未完成的 P1 缺口、变更检查项和关闭准入。 |
| [Scripts Contract](../scripts/README.md) | 本地开发、验证、部署和工具脚本的稳定入口合同。 |

## 文档边界

`fastapi-lite` 的文档按三类事实维护：

```text
docs/current/    -> 已实现事实
docs/contracts/  -> 调用方或开发者可依赖的稳定合同
docs/plans/      -> 未完成缺口、计划和验收标准
docs/notes/      -> 心智模型和目标范式，不等同于当前实现合同
```

不要把 `docs/plans/` 中的内容当作当前能力；只有代码、测试、脚本或迁移已经支持的行为，才能进入 `docs/current/` 或 `docs/contracts/`。

## 模板边界

`fastapi-lite` 负责固定通用 FastAPI 服务范式：

```text
HTTP foundation
  -> settings / logging / request context / envelope / registries
business modules
  -> route / schema / service / repository / model / migration / tests
integrations
  -> typed settings / provider or client / app.state / readiness / tests
operations
  -> dev.sh / deploy.sh / run.sh / verify.sh / tools.sh / k8s.sh
```

`fastapi-lite` 不预置具体任务平台、worker runtime、消息队列、outbox、DLQ、reconciler 或业务领域模型。这些能力应在具体服务有真实需求时，按现有配置、provider、合同、测试和文档范式接入。

## 常见入口

新增业务模块时，从 [Extension Contract](contracts/extension-contract.md) 的 `Adding A Business Module` 开始。

新增外部依赖时，从 [Extension Contract](contracts/extension-contract.md) 的 `Adding A Provider` 或 `Adding Configuration` 开始。

新增外部 HTTP API 调用时，从 [Extension Contract](contracts/extension-contract.md) 的 `Adding An External Service Client` 开始。

变更 HTTP route 时，同时看 [API Contract](contracts/api-contract.md)、`app/api/operations.py` 和 `app/core/error_registry.py`。

变更脚本能力时，同时看 [Scripts Contract](../scripts/README.md) 和 [Drift Checklist](plans/drift-checklist.md)。
