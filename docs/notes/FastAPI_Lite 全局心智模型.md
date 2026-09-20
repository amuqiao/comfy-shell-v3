# FastAPI Lite 全局心智模型

这是一份精简版全局视角：打开它，只需要快速知道 `fastapi-lite` 的地基有什么、新服务怎么落地、新业务怎么接、哪些能力不要误以为已经有。

## 这是什么

`fastapi-lite` 是一个轻量 FastAPI 服务骨架。

它不追求预置所有功能，而是固定一套基础工程范式：

- HTTP 请求怎么进来。
- 配置、日志、错误码怎么统一。
- 数据库、仓储、迁移怎么组织。
- 外部资源怎么接入生命周期。
- 新业务怎么验证不漂移。

更细的规则看：

- 文档入口：[`docs/README.md`](../README.md)
- 当前实现：[`../current/implementation.md`](../current/implementation.md)
- 扩展规则：[`../contracts/extension-contract.md`](../contracts/extension-contract.md)
- 后续缺口：[`../plans/drift-checklist.md`](../plans/drift-checklist.md)

## 地基有哪些

- `create_app()`：统一装配 settings、logging、middleware、exception handlers、routers、OpenAPI。
- `lifespan`：统一启动和关闭 provider，并注册 `/ready` 检查。
- 配置管理：section 化 `AppSettings`，配合 env manifest 和 `.env.example` 校验。
- 请求上下文：`X-Request-ID`、`X-Trace-ID` 贯穿响应、日志和下游 HTTP client。
- 日志合同：access/error log 保留 request、trace、method、path、operation、status、duration、error code 等字段。
- 错误合同：`AppError`、error registry、统一 error envelope。
- HTTP 合同：operation registry、OpenAPI、API docs drift check。
- 数据层：SQLAlchemy async、Alembic、`UnitOfWork`、repository。
- 示例业务：`items` CRUD 展示完整业务接口范式。
- Provider：Postgres、Redis fake boundary、object storage、shared HTTP client。
- 工具模块：`app/tools/` 提供纯工具示例。
- 脚本入口：`dev.sh`、`deploy.sh`、`run.sh`、`verify.sh`、`tools.sh`。
- 文档分层：`current` 写已实现事实，`contracts` 写稳定合同，`plans` 写后续缺口。

## 关键术语

这些词不是额外概念，而是后续开发时的固定放置点：

- `UnitOfWork`：事务工作单元。一次业务写操作里需要多个 repository 协作时，由它统一提交或回滚。
- `UowFactory`：`UnitOfWork` 的创建入口。service 显式接收它，避免 service 自己创建数据库 session。
- `Repository`：数据访问对象。只负责查询和数据变更，不负责 HTTP、业务编排和事务提交。
- `Provider`：基础设施资源接入单元，例如 PostgreSQL、Redis、OSS、HTTP client。负责启动、挂载、健康检查和关闭。
- `Registry`：注册表。用来集中登记错误码、operation、ORM model 等需要被验证和防漂移检查的对象。
- `lifespan`：FastAPI 生命周期入口。负责按顺序启动 provider、注册 readiness、关闭资源。
- `app.state`：应用级资源挂载点。provider 初始化后的资源放在这里，再通过 typed getter 或 dependency 取用。
- `envelope`：统一响应包裹。成功和失败响应都按固定结构输出，避免接口各自定义格式。

## 新服务怎么落地

复制或派生一个新 FastAPI 服务时，先确认服务身份和运行边界，再开始写业务代码：

```text
1. 服务身份
   SERVICE__NAME
   SERVICE__API_PREFIX
   README 中的服务说明

2. 本地端口和依赖
   API_HOST / API_PORT
   DATABASE__URL / REDIS__URL
   docker-compose.yml 的 host port

3. 配置合同
   .env.example
   app/core/config/env_manifest.py
   app/core/config/sections.py

4. 文档入口
   README.md
   docs/README.md
   docs/current / docs/contracts / docs/plans

5. 验证入口
   ./scripts/dev.sh doctor
   ./scripts/verify.sh check
```

`items` 是业务模块范式示例，不一定是新服务的真实领域模型。新服务可以保留它作为脚手架示例，也可以在建立真实业务模块后移除；无论哪种选择，都要同步 operation registry、API contract、migration 和测试。

## 新业务怎么接

先分清两个视角：**request 运行时链路** 和 **开发验证链路**。

运行时 request 链路：

```text
request
  -> request_id / trace_id middleware
  -> auth dependency
  -> schema validation
  -> route
  -> service
  -> UowFactory
  -> UnitOfWork
  -> repository
  -> ORM model
  -> database
  -> error mapping
  -> envelope response
```

开发验证链路：

```text
schema
  -> route
  -> operation registry
  -> error registry
  -> service
  -> repository
  -> ORM model
  -> Alembic migration
  -> OpenAPI / docs drift gate
  -> tests
  -> verify
```

核心规则：

- route 只处理 HTTP dependency、status code 和 envelope。
- service 处理事务编排和业务错误映射。
- service 必须显式接收 `UowFactory`，不要自己创建数据库 session。
- repository 只写查询和数据变更，不提交事务。
- ORM model 要登记到 `app/models/__init__.py`。
- 新 route、错误码、API docs 要同步注册。
- 最后跑 `./scripts/verify.sh check`。

## 新能力放哪里

新增能力前先判断它属于哪一类，再去对应合同文档看细则。这里负责帮你选入口，不重复维护完整规则：

| 需求 | 主要放置点 | 继续阅读 |
|---|---|---|
| 新 HTTP 资源 | `app/api/routes/`、`app/schemas/`、`app/services/`、`app/repositories/`、`app/models/` | [`Adding A Business Module`](../contracts/extension-contract.md#adding-a-business-module) |
| 新配置 | `app/core/config/` | [`Adding Configuration`](../contracts/extension-contract.md#adding-configuration) |
| 新外部资源 | `app/integrations/` + lifecycle provider | [`Adding A Provider`](../contracts/extension-contract.md#adding-a-provider) |
| 新外部 HTTP 调用 | `app/integrations/` | [`Adding An External Service Client`](../contracts/extension-contract.md#adding-an-external-service-client) |
| 新 middleware | `app/core/` | [`Adding Middleware`](../contracts/extension-contract.md#adding-middleware) |
| 新纯工具 | `app/tools/` | [`Adding A Tool`](../contracts/extension-contract.md#adding-a-tool) |
| 新脚本能力 | `scripts/` | [`Adding Script Commands`](../contracts/extension-contract.md#adding-script-commands) 和 [`scripts/README.md`](../../scripts/README.md) |

如果一个能力同时命中多类，先确定主边界，再用最小 wiring 串起来。不要因为一次业务需求就新增自动发现、动态注册或全局抽象。

## 新基础设施怎么接

新增外部资源按 provider 范式走：

```text
config section
  -> provider startup
  -> app.state resource
  -> health check
  -> readiness
  -> shutdown
  -> tests
```

核心规则：

- 配置先进入 typed settings section。
- provider 在 lifespan 中启动和关闭。
- 资源挂到 `app.state`，业务代码通过 typed getter 或 dependency 使用。
- readiness 要能暴露依赖状态。
- 未实现的真实后端要 fail fast，不要静默降级。

## 外部服务怎么接

外部服务集成不等同于新增 provider。先做这个判断：

```text
需要被应用生命周期统一启动、ready、关闭
  -> provider

只是通过 HTTP 或 SDK 调用外部 API
  -> integration client
```

完整规则看 [`Adding A Provider`](../contracts/extension-contract.md#adding-a-provider) 和 [`Adding An External Service Client`](../contracts/extension-contract.md#adding-an-external-service-client)。这里不要自行发明第三种接入路径。

## 改完怎么验

默认验收入口是 `./scripts/verify.sh check`。更窄或更重的验证由改动类型决定，细则看 [`Verification`](../contracts/extension-contract.md#verification)、[`Scripts And Verification`](../current/implementation.md#scripts-and-verification) 和 [`scripts/README.md`](../../scripts/README.md)。

`./scripts/verify.sh registry` 只覆盖 registry、route/OpenAPI/API contract 和必需文档存在性，不会检查 README、notes 或所有 Markdown 链接。只改说明性文档时，仍需要人工检查阅读路径和相对链接；如果文档改变了稳定合同或当前事实，再跑对应的 registry、check 或更重 gate。

不要只看 diff 就认为完成。文档、注册表、OpenAPI、migration、脚本 help 和测试都可能漂移。

## 当前不要误解

当前骨架不是完整 worker 平台。

这些能力现在不要假设已经可用：

- Celery / Taskiq / Kafka / RabbitMQ。
- broker adapter、outbox、DLQ、reconciler。
- 真实 Redis adapter。
- S3-compatible storage adapter。
- 完整 metrics / rate limit / OpenTelemetry / Prometheus。
- dynamic tool catalog。

这些不是不重要，而是应该等具体业务服务或 worker 服务有真实需求后，再按现有配置、provider、生命周期、测试和文档范式接入。

## 记住一条原则

```text
能复用已有范式就复用；
需要新增范式时，先补合同、示例和验证；
没有真实业务需求时，不提前引入复杂基础设施。
```
