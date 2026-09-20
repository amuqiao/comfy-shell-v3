# FastAPI 服务骨架

本文定义 `fastapi-lite` 的建设目标：抽取一套基础能力齐全、业务语义干净、扩展范式统一的 FastAPI 服务骨架。

## 1. 核心定位

`fastapi-lite` 不是最小 demo，也不是大而全平台。它要解决的是多个 FastAPI 服务长期开发后工程范式漂移的问题。

目标状态：

```text
fastapi-lite
  -> 业务 API 服务
  -> worker 服务
  -> 内部管理服务
  -> 后续其他 FastAPI 微服务
```

开发新服务时，团队应直接继承这套骨架，按同一套规则添加业务模块、工具模块、外部依赖和测试。后续如果某个服务需要 taskiq、MQ、复杂权限、outbox、callbacker 或业务工作流，也应在这套骨架的既定扩展点上增加，而不是每个服务重新发明目录结构和接入方式。

这份文档负责确定本次抽取任务的目标、边界、代码范式和验收标准。它不是实现日志，也不是某个具体业务服务的设计文档。

首版 non-goals：

- 不是 task runner。
- 不是 IAM / RBAC 平台。
- 不是云存储适配层。
- 不是消息队列平台。
- 不是可观测性平台。
- 不是 Job Platform 或 AI 项目裁剪版。

## 2. 真实需求

当前要解决的不是“如何写一个 FastAPI 项目”，而是“如何让后续所有服务按同一套基础范式生长”。

一个合格的基础骨架必须满足：

- 有真实可运行的 FastAPI app。
- 有 HTTP 合同、错误合同和接口注册机制。
- 有统一中间件链路：请求上下文、追踪 ID、日志、异常处理、CORS 等。
- 有 FastAPI lifespan 和轻量 Lifecycle Provider Registry，统一管理基础设施资源启动、校验和关闭。
- 有兜底错误处理，但不静默吞错、不做隐式降级。
- 有真实数据库接入：ORM、migration、repository、UnitOfWork、测试。
- 有 Redis 接入范式：配置、client lifecycle、health check、示例调用、测试替身。
- 有 OSS / object storage 接入范式：统一接口、provider、配置、示例调用、测试替身。
- 有外部 HTTP client 接入范式：timeout、trace header 透传、错误映射、测试。
- 有工具模块目录约定，以及 provider / health check / operation 等注册机制，避免工具函数和外部 client 到处散落。
- 有基础示例模块，开发者照着它新增接口、仓储和服务。
- 有脚本和验证，能阻止合同、迁移、脚本和文档漂移。

它不是“只要能跑”的最小项目，也不是“把所有基础设施都生产化”的平台。它的意义是把标准范式定下来，并在代码中提供最小真实示例。

## 3. 来源与取舍

本次抽取需要吸收两个已验证项目的公共优点。

### 3.1 从 tasks-platform 吸收

保留这些公共工程能力：

- FastAPI app factory 和 lifespan。
- lifespan 内统一管理 provider startup / shutdown、registry freeze 和 startup validation。
- request id / trace id 上下文。
- 成功和错误 envelope。
- `AppError`、错误码 registry 和异常 handler。
- 兜底 `Exception` handler：输出 `INTERNAL_ERROR`，记录完整异常日志，响应不泄露内部细节。
- operation registry 与 route/OpenAPI drift check。
- schema 基类和 Pydantic v2 使用方式。
- SQLAlchemy async engine、session lifecycle、UnitOfWork、repository 分层。
- Alembic baseline migration 和单 head 检查。
- 结构化日志和 request context 注入。
- `dev.sh`、`deploy.sh`、`verify.sh` 的轻量脚本组织。
- PostgreSQL integration gate 的安全思路：只能打到专用 `_test` 数据库。
- current / contract / plan 文档分离方法。

不复制 Job Platform 业务能力：

- `job_run` / `job_node` / `job_attempt`。
- dispatch outbox / callback outbox。
- Worker Internal API。
- callbacker。
- registry / binding。
- reconciler。
- Phase 1 runtime、three-service smoke。
- Job Platform 设计文档。

### 3.2 从 fastapi-best-ai-architecture 吸收

保留这些已验证开发体验：

- 脚本入口清晰：`dev.sh`、`deploy.sh`、`verify.sh`、`scripts/lib/*`。
- 本地开发、compose、迁移、测试、检查命令可发现。
- 运行脚本有 help、非法命令保护和明确 exit code。
- 配置按 section 管理，顶层 settings 只做组合和跨 section 校验。
- `env_manifest.py` 作为配置 key 的可执行 truth source，`.env.example` 作为由它校验或生成的人类模板。
- application env、launcher env、derived env、deprecated env 分离。
- repository 和数据库测试有可参考范式。
- 工具型脚本有固定入口，不把操作逻辑散落在 README。
- 真实依赖接入有本地/dev 模式和验证命令。

不复制旧 AI 项目业务能力：

- AI capability、model registry、pricing、prompt templates。
- media、Triton、real LLM flow。
- job workflow、billing、旧任务模型。
- 旧项目里的领域命名和业务脚本。

## 4. 骨架的层次

`fastapi-lite` 应按三层组织。

```text
foundation
  通用服务基础：配置、日志、中间件、错误、HTTP 合同、注册机制、脚本

integrations
  通用外部依赖接入：Postgres、Redis、OSS、HTTP client

example domain
  中性示例业务：items，用来展示 route/schema/service/repository/model 的新增范式
```

这三层不能混淆：

- foundation 不知道业务。
- integrations 提供接入范式，不写业务逻辑。
- example domain 只演示怎么新增模块，不承担框架能力。

## 5. 目标目录形态

实现完成后，仓库应大致形成如下结构：

```text
app/
  main.py
  api/
    operations.py
    routes/
      health.py
      items.py
  core/
    config/
      __init__.py
      sections.py
      settings.py
      env_manifest.py
      validation.py
    context.py
    error_registry.py
    exceptions.py
    lifespan.py
    lifecycle.py
    logging.py
    middleware.py
    registry_checks.py
    security.py
  db/
    base.py
    database.py
    unit_of_work.py
    pagination.py
  integrations/
    redis.py
    storage.py
    http_client.py
  models/
    item.py
  repositories/
    base.py
    item_repository.py
  schemas/
    common.py
    envelope.py
    item.py
  services/
    item_service.py
  tools/
    example_tool.py
alembic/
  env.py
  versions/
docs/
  current/
  contracts/
  plans/
scripts/
  dev.sh
  deploy.sh
  verify.sh
  lib/
tests/
```

具体文件名可以随实现微调，但职责边界必须稳定。尤其是 Redis、OSS、HTTP client、工具模块和 health check 不能散落在业务 service 或 route 中。

目录到三层职责的映射：

| 层次 | 主要目录 | 职责 |
|---|---|---|
| foundation | `app/main.py`、`app/core/`、`app/api/operations.py`、`app/schemas/envelope.py`、`scripts/` | 服务启动、HTTP 合同、错误、日志、中间件、注册检查、脚本。 |
| integrations | `app/db/`、`app/integrations/` | Postgres、Redis、OSS、HTTP client 等外部依赖的接入范式和 lifecycle。 |
| example domain | `app/api/routes/items.py`、`app/models/item.py`、`app/repositories/item_repository.py`、`app/services/item_service.py`、`app/schemas/item.py` | 演示新增业务模块的完整代码形状。 |
| extension utilities | `app/tools/` | 可复用工具的目录、命名和测试范式；首版不做运行时动态登记机制。 |

## 6. 必须有的完整示例链路

骨架必须包含一条完整的 `items` 示例链路：

```text
HTTP route
  -> request schema
  -> auth dependency
  -> service
  -> repository
  -> ORM model
  -> database table
  -> response schema
  -> success/error envelope
  -> logs
  -> tests
```

示例域建议使用 `items`。它只用于演示新增模块范式，不代表业务方向。

示例接口建议：

```text
POST  /v1/items
GET   /v1/items/{item_id}
GET   /v1/items?status=&limit=&cursor=
PATCH /v1/items/{item_id}
DELETE /v1/items/{item_id}
```

示例数据表建议：

```text
item
  id
  owner_id
  name
  description
  status
  version
  created_at
  updated_at
  deleted_at
  deleted_by
```

`version` 用于展示乐观并发和更新范式。示例默认采用 soft delete，因为它能同时固定活动记录过滤、部分唯一索引、删除审计和后续清理任务的扩展位置。

### 6.1 Items 持久化合同

`items` 示例不是业务方向，但它必须足够真实，能让后续业务模块照着新增 CRUD。

字段建议：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `uuid` | 主键。 |
| `owner_id` | `varchar(64)` | 当前调用方或 service identity 的 opaque scope key，用于演示 auth dependency 如何进入 repository 查询；它不是推荐所有业务照抄的通用用户主键设计。 |
| `name` | `varchar(120)` | 示例资源名。 |
| `description` | `text null` | 示例可选字段。 |
| `status` | `varchar(16)` | 枚举：`draft`、`active`、`archived`。 |
| `version` | `integer` | 乐观并发版本，初始值为 `1`。 |
| `created_at` | `timestamptz` | 创建时间。 |
| `updated_at` | `timestamptz` | 更新时间。 |
| `deleted_at` | `timestamptz null` | soft delete 标记。业务查询默认只看 `deleted_at is null`。 |
| `deleted_by` | `varchar(64) null` | 删除操作者或调用方。 |

约束和索引建议：

- `status` 必须有数据库 `check constraint`。
- `version >= 1` 必须有数据库 `check constraint`。
- 活动记录唯一：`unique (owner_id, name) where deleted_at is null`。
- 活动列表索引：`(owner_id, status, created_at desc, id desc) where deleted_at is null`。
- 如果实现删除清理任务，再增加 `deleted_at` 索引。

### 6.2 Items CRUD 范式

列表合同：

- `GET /v1/items` 支持 `status`、`limit`、`cursor`。
- 默认只返回 `deleted_at is null` 的活动记录。
- 排序固定为 `created_at desc, id desc`，避免分页漂移。
- `limit` 必须有上限，非法分页参数映射为 `REQUEST_INVALID`。

更新合同：

- `PATCH /v1/items/{item_id}` 请求体必须包含 `expected_version`。
- 更新条件必须包含 `id`、`owner_id`、`version = expected_version`、`deleted_at is null`。
- 更新成功后 `version = version + 1`。
- 0 行受影响时，service 必须区分资源不存在和版本冲突：
  - 不存在或已删除：`ITEM_NOT_FOUND`。
  - 当前版本不等于 `expected_version`：`ITEM_VERSION_CONFLICT`。

删除合同：

- `DELETE /v1/items/{item_id}` 采用 soft delete。
- 请求体必须携带 `expected_version`，避免删除覆盖并发更新，并保持 OpenAPI 合同稳定。
- 删除成功后写入 `deleted_at`、`deleted_by`，并更新 `version`。
- 重复删除已删除资源按 `ITEM_NOT_FOUND` 处理，不返回伪成功。

分页 cursor 合同：

- cursor 基于排序键 `(created_at, id)`。
- 下一页查询条件为 `(created_at, id) < (:cursor_created_at, :cursor_id)`。
- cursor 必须使用不透明字符串编码，解码失败映射为 `REQUEST_INVALID`。
- 响应 envelope 的 `data` 内包含 `items`、`next_cursor`、`limit`。

## 7. HTTP 合同

骨架必须提供稳定 HTTP 合同。

必须包含：

- API version prefix，例如 `/v1`。
- request id header。
- trace id header。
- 成功响应 envelope。
- 错误响应 envelope。
- FastAPI validation error 统一映射。
- 未捕获异常统一映射为 `INTERNAL_ERROR`。
- OpenAPI 默认响应清理，避免暴露不符合合同的默认错误响应。
- operation registry，登记每个 route 的 method、未挂载 path、operation id、成功状态码、auth 要求、request/response schema 和允许错误码。
- drift check，验证 mounted routes、OpenAPI、API contract Routes 表和 operation registry 一致。

示例接口必须展示：

- 成功创建资源。
- 查询资源。
- 更新资源。
- 业务错误，例如资源不存在或名称冲突。
- 输入校验错误。
- request id / trace id 在响应 header、envelope 和日志中可追踪。

## 8. 错误处理

错误处理不能只停留在错误码表。骨架必须提供完整错误链路：

```text
service 抛 AppError
  -> exception handler 查 error registry
  -> 生成 ErrorEnvelope
  -> 写结构化错误日志
  -> 响应携带 request_id / trace_id
```

必须包含：

- `AppError`。
- error code registry。
- 错误码 metadata：
  - HTTP status。
  - 默认 message。
  - retryable。
  - visibility scope，用于声明错误可出现的 API 面或模块边界。
- validation error handler。
- auth error handler。
- fallback exception handler。
- 测试确保接口不能返回未注册错误码。

兜底异常处理的边界：

- 可以在 HTTP 边界捕获未处理异常，统一返回 `INTERNAL_ERROR`。
- 必须记录完整异常日志和 stack trace。
- 响应不能泄露内部异常细节。
- 不能静默吞错，不能继续执行后续业务逻辑，不能把错误降级成空结果。

基础错误码建议：

```text
REQUEST_INVALID
UNAUTHORIZED
FORBIDDEN
RESOURCE_NOT_FOUND
RESOURCE_CONFLICT
DEPENDENCY_UNAVAILABLE
INTERNAL_ERROR
```

示例域可以补充：

```text
ITEM_NOT_FOUND
ITEM_NAME_CONFLICT
ITEM_VERSION_CONFLICT
```

## 9. 中间件和请求上下文

骨架必须提供标准中间件链路。

必须包含：

- request context middleware。
- request id / trace id 生成和透传。
- response header 回写。
- access log middleware。
- CORS middleware。
- exception handlers。
- trusted host / proxy headers 的配置范式。
- request body size 或 timeout 的扩展位置。

可选但应预留位置：

- metrics middleware。
- rate limit middleware。
- compression middleware。

推荐中间件顺序：

```text
trusted host / proxy headers
  -> request context
  -> access log
  -> CORS
  -> route handlers
  -> exception handlers
```

中间件必须保证：

- 每条日志自动携带 request id、trace id、method、path、operation id。
- 下游 HTTP client 能透传 trace header。
- 异常日志也能关联请求。
- 健康检查可以按配置降低日志噪音。
- 无效 request id / trace id 按合同返回错误或重新生成的策略必须固定，并有测试覆盖。

## 10. 配置和环境

骨架必须使用 Pydantic Settings 管理配置，但不能把所有字段塞进一个巨大的 `Settings` 类。

配置模型的职责分三层：

```text
ConfigSection
  单个配置分组的字段、默认值、类型和组内校验

AppSettings
  聚合各 section，并负责跨 section 约束

EnvManifest / verify gate
  校验 .env.example、未知 key、废弃 key、派生 key 和 launcher key 边界
```

推荐目录：

```text
app/core/config/
  sections.py       # RuntimeSettings / ServiceSettings / DatabaseSettings 等
  settings.py       # AppSettings、get_settings()
  env_manifest.py   # application / launcher / derived / deprecated key 的唯一可执行清单
  validation.py     # release invariant、placeholder secret、条件必填
```

### 10.1 配置分组

首版内置 section：

| Section | 示例 env prefix | 职责 |
|---|---|---|
| `RuntimeSettings` | `RUNTIME__*` | 运行环境身份，例如 `RUNTIME__APP_ENV`。 |
| `ServiceSettings` | `SERVICE__*` | 服务名、标题、API prefix。 |
| `SecuritySettings` | `SECURITY__*` | dev API key、CORS、受保护接口开关。 |
| `DatabaseSettings` | `DATABASE__*` | PostgreSQL URL、SSL、连接池。 |
| `RedisSettings` | `REDIS__*` | Redis URL、enabled、连接超时。 |
| `StorageSettings` | `STORAGE__*` | storage backend、本地目录、S3-compatible 接入参数；支持 `disabled`、`local`、`s3_compatible`。 |
| `HttpClientSettings` | `HTTP_CLIENT__*` | 默认 timeout、连接池上限。 |
| `ObservabilitySettings` | `OBSERVABILITY__*` | 日志级别、access log、健康检查日志策略。 |

推荐使用 `env_nested_delimiter="__"`：

```text
RUNTIME__APP_ENV=local
SERVICE__NAME=fastapi-lite
SERVICE__TITLE=FastAPI Lite
SERVICE__API_PREFIX=/v1
SECURITY__SERVICE_API_KEY=<replace-me>
DATABASE__URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:25432/fastapi_lite
REDIS__ENABLED=true
REDIS__URL=redis://127.0.0.1:26379/0
STORAGE__BACKEND=local
STORAGE__LOCAL_PATH=storage/objects
HTTP_CLIENT__TIMEOUT_SECONDS=5
OBSERVABILITY__LOG_LEVEL=INFO
```

`AppSettings` 只能聚合 section 和做跨 section invariant，不能持续增加业务字段。业务服务如果需要自己的配置，应新增业务 section，例如 `BillingSettings` 或 `WorkerSettings`，并在该服务自己的配置包里扩展，不回灌到基础骨架。

### 10.2 配置 key 分类

骨架必须区分四类 key：

| 类型 | 示例 | 是否进入 `AppSettings` |
|---|---|---|
| application keys | `DATABASE__URL`、`STORAGE__BACKEND` | 是。 |
| launcher keys | `API_PORT`、`COMPOSE_PROJECT_NAME`、`POSTGRES_HOST_PORT` | 否，只给脚本和 compose 使用。 |
| derived keys | `SYNC_DATABASE_URL`、内部 timeout 链、默认目录派生值 | 否，只能由代码派生。 |
| deprecated keys | 已删除或改名的旧 key | 否，出现即失败。 |

`env_manifest.py` 是配置 key 的唯一可执行真相源；`.env.example` 是提交态本地开发模板，必须由 manifest 校验或生成，不能作为第二套手工清单。`verify.sh` 必须检查：

- `.env.example` 与 env manifest 完全对齐。
- `.env.example` 不包含 manifest 未声明的 key。
- 本地 `.env` 不包含未知 key、废弃 key、派生 key。
- key 必须大写，命名必须属于已声明 prefix。
- 至少能加载一次 local 配置。
- 至少能用 release profile 跑一次启动校验，证明 release 约束生效。

### 10.3 配置源优先级

推荐固定为：

```text
显式测试注入 / init kwargs
  > 进程环境变量
  > ENV_FILE 指定文件
  > 本地 .env
  > 代码默认值
```

测试必须通过显式 settings override 或 fake provider 注入配置，不能在测试中偷偷依赖开发机 `.env`。provider 只能依赖 typed settings，不能在 provider 内部直接读 `os.environ`。

### 10.4 校验规则

字段和 section 层必须校验：

- secret 使用 `SecretStr` 或等价机制，避免 repr/log 泄露。
- 连接池、timeout、retry、limit、list 类配置必须有类型和范围校验。
- 枚举类配置必须显式列出允许值。
- 列表配置必须拒绝空元素，例如 `a,,b`。
- 可选集成必须用显式 `enabled` 或 `backend`，不能靠空字符串隐式关闭。

跨 section 层必须校验：

- release 环境禁止 dev-only auth bypass。
- release 环境禁止 placeholder secret。
- release 环境禁止 `STORAGE__BACKEND=local`；如果服务不使用对象存储，应设置 `STORAGE__BACKEND=disabled`；如果使用对象存储，应接入非 local provider。
- dev-only insecure 开关只能在 loopback 数据库、Redis、API host 下启用。
- `backend/enabled` 决定条件必填项，例如 `disabled` 不注册 storage provider，`local` 必须提供本地目录，`s3_compatible` 必须提供 endpoint、bucket、region、credential 或 secret ref。

启动期和 verify gate 必须 fail fast：

- 必需配置缺失。
- 配置类型或范围非法。
- 未知、废弃、派生 key 被写进 env。
- `.env.example` 与 env manifest 漂移。
- provider 启用但配置不足。
- release profile 校验失败。

### 10.5 从旧项目吸收和避免

应吸收：

- section 化 settings。
- `env_manifest.py` 作为配置 key truth source，`.env.example` 作为被校验或生成的开发模板。
- application / launcher / derived / deprecated key 分离。
- unknown key 失败。
- release 环境强约束。
- 派生值不暴露成 env。

不应复制：

- 把 AI、Job、Callback、Dashboard 等业务配置塞进基础骨架。
- 复制旧项目的大型平铺 env 映射表；首版优先用 `__` 嵌套 env。
- 把业务 registry 文件校验都放进 `AppSettings`；业务 registry 应在对应 provider 或 registry startup validation 中校验。
- 把内部 buffer、批大小、恢复策略等低层实现细节过早公开成通用 env。

## 11. 数据库接入

第一版默认 PostgreSQL + SQLAlchemy async。骨架不需要同时实现多数据库，但必须把替换边界定清楚。

必须包含：

- async engine。
- async session factory。
- declarative base。
- Alembic env。
- baseline migration。
- UnitOfWork。
- repository pattern。
- pagination helper。
- transaction commit / rollback 测试。
- repository 测试。
- PostgreSQL integration gate。

数据库替换范式：

- 业务 service 只依赖 repository / UoW，不直接依赖 engine 或 session。
- repository 内部使用 SQLAlchemy 查询。
- 如果未来切换数据库，主要影响应集中在 `app/db` 和 repository；service 是否需要小改取决于业务查询能力和事务语义。
- migration 策略必须随数据库实现一起维护。

事务和仓储规则：

- route 不直接接触 `AsyncSession`。
- service 负责事务编排和错误映射。
- UnitOfWork 持有单个 session 和本次事务所需 repository。
- 写事务必须在 service 作用域内完成，并在返回响应前确认 commit 成功。
- 不依赖 FastAPI dependency cleanup 阶段自动提交写事务。
- repository 可以 `flush` / `refresh`，不能 `commit` / `rollback`。
- repository 不返回 HTTP status 或 envelope。
- repository 不能静默吞掉 `IntegrityError`、连接错误或并发冲突。
- service 将数据库唯一约束冲突映射为注册错误码，例如 `ITEM_NAME_CONFLICT`。
- service 将 CAS 失败映射为 `ITEM_VERSION_CONFLICT` 或 `ITEM_NOT_FOUND`。

`items` repository 至少应展示：

```text
create(owner_id, input) -> Item
get_active_by_id(owner_id, item_id) -> Item | None
list_active(owner_id, status, limit, cursor) -> Page[Item]
update_cas(owner_id, item_id, expected_version, patch) -> MutationResult[Item]
soft_delete_cas(owner_id, item_id, expected_version, deleted_by) -> MutationResult[Item]
```

`MutationResult` 必须显式表达：

```text
updated(item)
not_found
version_conflict(current_version)
```

不能用 `None` 同时表示不存在、已删除和版本冲突。service 根据 `MutationResult` 映射 `ITEM_NOT_FOUND` 或 `ITEM_VERSION_CONFLICT`。

`list_active` 必须固定排序和分页语义，不能让不同业务模块各自发明列表行为。

必须避免：

- route 直接拿 session 写 SQL。
- service 直接创建 engine。
- repository 静默吞掉数据库异常。
- 普通测试误清本地数据库。

## 12. Redis 接入

Redis 是基础服务常见依赖，骨架应提供接入范式，而不是让各服务自行创建 client。

必须包含：

- Redis settings。
- client lifecycle。
- dependency/provider 获取方式。
- readiness check。
- 示例用途，例如 cache、distributed lock 占位、rate limit token store 或简单 key-value 操作。
- 测试替身或 fake client。

第一版不要求实现复杂缓存框架，也不要求分布式锁生产化。但必须给出统一位置和调用范式：

```text
route/service
  -> dependency/provider
  -> redis client interface
  -> concrete redis implementation or test fake
```

## 13. 外部依赖接入范式

Postgres、Redis、OSS、外部 HTTP client 以及未来其他 provider 都应遵循同一条接入流水线：

```text
settings
  -> typed interface / protocol
  -> concrete provider
  -> startup validation
  -> dependency/provider getter
  -> AppError / error mapping
  -> readiness probe
  -> test double
```

这个范式的目的不是让所有 provider 都能运行时热切换，而是让每个服务都知道：

- 配置写在哪里。
- client 由谁创建和关闭。
- 业务代码依赖哪个接口。
- 失败如何映射成错误合同。
- `/ready` 如何反映依赖状态。
- 测试如何替换真实依赖。

第一版可以只对部分 provider 做真实实现，但每个 provider 的扩展位置、接口形状和测试替身必须明确。

判定规则：

- **provider**：封装外部资源或生命周期，例如 database、Redis、object storage、HTTP client。
- **tool**：封装可复用能力或纯函数，不拥有外部连接生命周期。
- **health check**：只描述某个 provider 或服务状态，不负责创建 provider，也不承载业务逻辑。
- **registry**：只负责登记、查询、冻结和验证，不直接执行复杂业务流程。

### 13.1 Lifespan 和 Lifecycle Provider Registry

骨架必须使用 FastAPI lifespan 统一管理服务资源。provider 不能在 import 阶段创建真实连接，也不能在 route 或 service 里临时 new 全局 client。

lifespan 推荐流程：

```text
load settings
  -> configure logging
  -> register providers
  -> startup providers in order
  -> run startup validation
  -> register provider health checks
  -> freeze registries
  -> expose resources through app.state / dependencies
  -> yield
  -> shutdown providers in reverse order
```

`LifecycleProvider` 至少应表达：

```text
name
required
startup(app, settings) -> resource
shutdown(app, resource) -> None
health_check(resource) -> HealthResult
test_override / fake
```

首版内置 provider：

- Postgres provider：engine / session factory / UoW 入口。
- Redis provider：interface、fake、可选真实 client 接入位置。
- Object storage provider：local filesystem implementation。
- HTTP client provider：shared `httpx.AsyncClient`、timeout、trace header 注入。

Lifecycle Provider Registry 负责：

- provider 登记。
- startup 顺序。
- shutdown 反序。
- startup validation。
- health check 注册。
- app state 资源挂载。
- 测试 fake provider 替换。
- startup 后 freeze，禁止运行中随意注册。
- 已启动 provider 部分成功后，后续 provider 启动失败时，已启动资源必须反向清理。

Lifecycle Provider Registry 不负责：

- 业务 service 注册。
- handler / taskiq worker 注册。
- runtime plugin。
- 动态热切换 provider。
- 业务策略选择。
- 把业务对象变成 service locator。
- 运行时模块扫描和自动发现。
- 字符串查找式依赖获取，例如业务代码直接访问 `app.state.providers["redis"]`。
- 通用依赖图求解器；首版最多允许很轻的 `depends_on` 顺序声明。

业务代码获取 provider 应通过 typed dependency / getter，例如 `get_redis_client()`、`get_storage()`、`get_http_client()`，而不是直接索引 registry 或 `app.state`。

## 14. OSS / Object Storage 接入

对象存储属于常见基础能力，骨架应提供统一接口和示例 provider。

必须包含：

- `ObjectStorage` protocol / interface。
- `disabled` backend，用于明确声明当前服务不启用对象存储。
- local filesystem provider，用于本地开发和测试。
- S3-compatible / MinIO provider 的接入位置和配置范式。
- put / get / delete / presign 或等价最小接口。
- readiness check 或配置检查。
- 示例调用和测试。

第一版必须实现 `disabled` backend 和 local provider，并保留 S3-compatible / MinIO provider 的接口位置和配置范式；真实云 provider adapter 不作为首版必交付。关键是业务代码不能直接依赖具体 OSS SDK。

`disabled` 不是静默降级：如果某个 route 或 service 声明对象存储为必需 provider，而配置为 `disabled`，启动期必须 fail fast。

必须避免：

- 业务 service 里直接 new OSS client。
- 将 bucket、endpoint、secret 散落在业务代码。
- 上传失败被吞掉后返回成功。

## 15. 外部 HTTP Client 接入

骨架应提供统一外部 HTTP client 范式，避免不同服务各自 new `httpx.AsyncClient`。

必须包含：

- shared async HTTP client lifecycle。
- timeout 配置。
- trace header 透传。
- request id / trace id 日志。
- 外部依赖错误映射为 `DEPENDENCY_UNAVAILABLE` 或更具体错误。
- MockTransport 或 fake client 测试范式。

不做：

- 复杂 service discovery。
- circuit breaker 生产化。
- 全局 retry 框架。

如果后续需要 retry、backoff、bulkhead，应在该 client provider 层扩展，而不是散落在业务 service。

## 16. 注册机制

注册机制是骨架的核心价值之一。不是所有东西都要 registry，但容易漂移的横切能力必须有统一登记位置。

必须有：

- error code registry。
- operation registry。
- lifecycle provider registry。
- health check registry。

所有 registry 至少应具备：

```text
register()
get()
all()
freeze()
validate()
```

约束：

- startup 后 registry 应冻结，避免运行中被随意改写。
- unknown key / duplicate key 应快速失败。
- verify gate 应能检查 registry 与实际代码面是否漂移。
- 只复用注册机制，不复制旧 AI 项目的具体 tool/capability/job 领域结构。
- lifecycle provider registry 只管理基础设施资源生命周期，不作为业务 service locator。

### 16.1 Health Check Registry

健康检查不应写死在 `/ready` route 里。

范式：

```text
register_health_check("database", check_database)
register_health_check("redis", check_redis)
register_health_check("storage", check_storage)
```

每个 probe 至少包含：

- name。
- async check function。
- timeout。
- required。

`/health` 只检查进程存活；`/ready` 聚合 registry 中的 readiness checks，并有超时和结构化结果。`required=false` 的可选依赖可以显示 degraded，但不能让结果含糊。`degraded` 只用于 readiness 结果表达，不代表业务请求期允许自动降级、静默吞错或伪成功。

### 16.2 Lifecycle Provider Registry

外部依赖接入应集中登记：

```text
postgres
redis
object_storage
http_client
```

登记内容包括：

- provider name。
- concrete implementation。
- config section。
- startup / shutdown lifecycle。
- readiness probe factory。
- test fake。

Lifecycle Provider Registry 是 provider 生命周期的唯一可执行真相源。`app/integrations/` 只放 provider 实现、typed interface 和 typed getter，不再维护第二套运行时 registry。

provider 可以声明“如何基于已启动资源生成 readiness probe”，但真正登记、执行、聚合 readiness 的唯一入口是 Health Check Registry。probe 只能复用已启动资源并带超时，不能为了检查临时新建连接。

### 16.3 工具模块约定

工具模块不能无序散落在 `utils.py`。

工具分两类：

- 纯函数工具：放在明确模块中，例如 `app/tools/text.py`、`app/tools/time.py`。
- 依赖配置或外部资源的工具：优先改为 provider 上的一层显式 facade。

示例：

```text
app/tools/example_tool.py
```

首版工具模块至少要求：

- tool name。
- callable / provider。
- input schema 或参数说明。
- owner module。
- tests。

第一版只需要一个简单示例，目的是固定公共工具扩展位置，不做运行时动态注册。

如果未来确实需要跨模块发现工具，可以在 P1 增加 `Tool Catalog`；它不进入 lifespan 主路径，不负责启动资源，也不提供 `invoke_tool(name, payload)`、动态装载或 schema 驱动执行。

## 17. 启动期校验和失败策略

骨架必须把启动期错误和请求期错误分开。

启动期必须 fail fast：

- 必需配置缺失。
- 配置类型或范围非法。
- registry duplicate / unknown reference。
- 必需 provider 启用但无法构造。
- Alembic head 不唯一。

请求期必须按 HTTP 合同响应：

- `AppError` -> 注册错误码。
- `RequestValidationError` -> `REQUEST_INVALID`。
- auth failure -> `UNAUTHORIZED` / `FORBIDDEN`。
- 未捕获异常 -> `INTERNAL_ERROR`，并记录完整异常日志。

禁止：

- silent catch。
- provider 自动降级。
- 缺配置时使用隐藏默认值继续运行。
- 外部依赖失败后返回空结果伪装成功。

## 18. 安全边界

基础骨架不需要完整用户系统，但需要清晰的安全入口。

必须包含：

- auth dependency 或 middleware 的轻实现。
- dev bearer token / API key 示例。
- public route 和 protected route 的区分范式。
- current principal / service identity 上下文。
- 测试覆盖缺少凭据或凭据错误时的错误 envelope。

不做：

- 用户注册登录。
- OAuth/OIDC。
- 多租户权限。
- 完整 RBAC 管理后台。

这些由具体业务服务决定。

## 19. 脚本和开发体验

骨架必须有可直接使用的脚本入口。

必须包含：

```text
./scripts/dev.sh
./scripts/deploy.sh
./scripts/verify.sh
```

最低职责：

- `dev.sh`
  - bootstrap。
  - start / stop / restart / status。
  - logs。
  - migrate。
  - 本地 API 进程管理。
  - 本地 Postgres / Redis 依赖管理。
  - local storage 目录初始化；MinIO 只作为后续真实 OSS provider 的可选扩展。

- `deploy.sh`
  - compose config check。
  - compose up / down / status。
  - 不承担 K8s 或远程部署。

- `verify.sh`
  - syntax。
  - tests。
  - env manifest / `.env.example` alignment。
  - local / release profile 配置加载校验。
  - Alembic head / offline SQL。
  - operation registry drift check。
  - error registry check。
  - registry freeze / validate check。
  - compose config。
  - PostgreSQL integration gate。

脚本必须有：

- help。
- unknown command 保护。
- 明确 exit code。
- 本地 DB 保护。
- 测试覆盖脚本 help 和关键命令存在。

## 20. 测试基线

基础骨架完成时，测试不应只覆盖 happy path。

P0 必须覆盖：

- app 创建和 lifespan。
- lifespan startup 初始化 provider。
- lifespan shutdown 关闭 provider。
- startup validation 失败时 fail fast。
- fake provider 能覆盖真实 provider。
- health 和 ready。
- success envelope。
- error envelope。
- validation error。
- fallback exception handler。
- request id / trace id。
- 无效 request id / trace id。
- access log 基础字段。
- outbound HTTP trace header 传播。
- auth 成功和失败。
- section 化 settings 加载。
- `.env.example` 与 env manifest 对齐。
- unknown / deprecated / derived env key 失败。
- release 环境拒绝 placeholder secret、dev-only auth bypass 和 local storage。
- provider 不直接读取 `os.environ`。
- operation registry drift。
- error registry visibility scope。
- health check registry。
- registry duplicate / unknown ref / freeze。
- lifecycle provider registry startup / shutdown / reverse shutdown order。
- startup 部分成功后失败能反向清理已启动 provider。
- fake provider override 只影响测试作用域，不污染正式 wiring。
- provider 配置缺失或非法配置失败。
- 工具模块目录和示例工具测试。
- `/ready` 成功、失败和 degraded 分支。
- items route contract。
- items service。
- items repository。
- items create / get / list / patch / delete。
- items 列表分页排序稳定。
- items `PATCH` 成功后 `version + 1`。
- items stale `expected_version` 返回 `ITEM_VERSION_CONFLICT`。
- items name 唯一约束冲突返回 `ITEM_NAME_CONFLICT`。
- items soft delete 后默认查询不可见。
- UnitOfWork commit / rollback。
- Alembic baseline。
- Redis provider interface / fake 测试。
- object storage local provider 测试。
- external HTTP client MockTransport 测试。
- PostgreSQL integration 使用专用 `_test` 数据库。
- 脚本 help / unknown command / verify gate。
- import boundary，避免示例层错误依赖不该依赖的模块。

P1 可在首版后补：

- 真实 Redis 容器集成测试。
- MinIO / S3-compatible adapter 集成测试。
- metrics middleware 测试。
- rate limit middleware 测试。
- 更复杂的 provider retry / backoff / bulkhead 测试。

普通 `pytest` 不应误清本地数据库。会清表的集成测试必须显式启用，并且只能使用专用测试库。

## 21. 文档结构

骨架应使用三类文档分离长期事实：

```text
docs/current/
  当前已经实现的工程事实

docs/contracts/
  外部调用者和新业务开发者可依赖的合同

docs/plans/
  尚未实现但计划保留的工作
```

本次任务至少需要：

- `docs/current/implementation.md`
- `docs/contracts/api-contract.md`
- `docs/contracts/extension-contract.md`
- `docs/plans/drift-checklist.md`

本文就是首版 implementation plan 和任务目标文档，不再另建重复计划文档。后续实现完成后，当前事实必须进入 `docs/current/`，外部可依赖行为必须进入 `docs/contracts/`，未完成项才留在 `docs/plans/`。

## 22. 本次任务目标

本次任务不是讨论骨架应该有什么，而是要把 `fastapi-lite` 建成可运行的第一版基础骨架。

### 22.1 P0 首版必需

完成以下内容：

- 初始化 Python / FastAPI 项目结构。
- 添加 section 化配置包、env manifest、配置 verify gate、日志、请求上下文、中间件、lifespan 和异常处理。
- 添加统一 envelope 和错误码 registry。
- 添加 operation registry、lifecycle provider registry 和 health check registry。
- 添加 SQLAlchemy async 数据库层。
- 添加 UnitOfWork 和 repository。
- 添加 Redis provider 接口、配置、fake 和 readiness 接入范式；真实 Redis 容器集成可作为 P1。
- 添加 object storage interface、`disabled` backend 和 local filesystem provider；真实 MinIO/S3 adapter 可作为 P1。
- 添加 shared HTTP client provider、timeout、trace header 透传和 MockTransport 测试。
- 添加一个完整 `items` 示例模块，覆盖 create / get / list / patch / delete、分页、CAS、软删和仓储层。
- 添加一个工具模块示例。
- 添加 Alembic baseline migration。
- 添加 health / ready route。
- 添加轻量 auth 示例。
- 添加 dev / deploy / verify 脚本。
- 添加 README 和 current / contract / plan 文档。
- 添加测试，证明新增接口、仓储层、集成 provider、工具模块和脚本可用。
- 添加测试，证明 lifespan 能统一 startup / shutdown provider，并支持 fake provider 覆盖。

### 22.2 P1 预留扩展

首版应预留但不强制完成：

- 真实 Redis integration gate。
- MinIO / S3-compatible provider adapter。
- metrics middleware。
- rate limit middleware。
- provider retry / backoff / bulkhead。
- OpenTelemetry / Prometheus 接入。
- Tool Catalog。

### 22.3 验收标准

完成后必须满足：

- 新开发者能照着 `items` 示例新增一个业务模块。
- 新业务配置能按 section 扩展，不需要把字段堆进单个 `Settings` 类。
- 新工具能按 `app/tools/` 目录范式添加，而不是散落在 `utils.py`。
- 新外部依赖能按 provider registry 范式接入，并能进入 `/ready`。
- 新 provider 能按 lifecycle provider registry 范式接入，并由 lifespan 统一启动和关闭。
- provider 遵循 `settings -> interface -> implementation -> startup validation -> error mapping -> readiness -> test double`。
- 新接口不用重新设计 envelope、错误、日志、UoW、repository 或 route registry。
- `./scripts/verify.sh check` 通过。
- `.env.example`、env manifest 和配置 section 不漂移。
- 普通测试不依赖真实 Postgres / Redis / OSS。
- PostgreSQL integration 只能显式打到 `_test` 数据库。
- OpenAPI、operation registry、API contract Routes 表和 route 不漂移。
- 未捕获异常会进入 `INTERNAL_ERROR` envelope，并记录可追踪日志。
- request id / trace id 在响应、日志和下游 HTTP client 中一致传递。
- 文档能清楚说明：
  - 当前已实现什么。
  - 调用者可依赖什么。
  - 新能力应接到哪里。
  - 后续哪些能力不在基础骨架内。

### 22.4 明确不做

本次不做：

- taskiq。
- worker 常驻消费。
- MQ publisher / consumer。
- transactional outbox。
- saga / process manager。
- callbacker。
- Job Platform。
- AI 模型、prompt、pricing、media、Triton。
- 完整用户系统。
- 生产级 RBAC。
- 生产级 object storage 多云适配。
- 生产级 Redis 分布式锁。
- K8s 部署。

这些能力应在具体服务中按需添加，不应污染基础骨架。

## 23. 成功后的使用方式

当 `fastapi-lite` 完成后，新服务开发应按以下方式开始：

```text
基于 fastapi-lite 初始化服务
  -> 修改 SERVICE__NAME、数据库名和 README
  -> 如需新增业务配置，添加独立 Settings section 并同步 env manifest / .env.example / tests
  -> 复制 items 示例为业务模块
  -> 添加业务 model/schema/repository/service/route
  -> 注册 operation
  -> 添加 migration
  -> 如需 Redis / OSS / HTTP client，接入对应 provider
  -> 如需工具，放入 app/tools/ 并补测试；确需跨模块发现时再引入 Tool Catalog
  -> 如需 readiness，登记到 health check registry
  -> 添加 tests
  -> 跑 ./scripts/verify.sh check
```

如果是 worker 服务，也先从这套骨架开始：

```text
fastapi-lite
  -> 添加 worker service API 或管理接口
  -> 添加 task handler registry
  -> 按需接 taskiq / broker adapter
  -> 按需添加 heartbeat、idempotency、DLQ、reconciler
```

taskiq、broker、outbox、reconciler 属于 worker 服务的后续能力，不属于 `fastapi-lite` 的初始骨架。
