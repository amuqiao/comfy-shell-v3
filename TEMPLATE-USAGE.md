# Template Usage

本文只解决一个问题：如何从 `fastapi-lite` 复制出一个新的真实 FastAPI 服务仓库。

复制完成后，这个文件可以从真实服务仓库里删除，不需要改 README。

## 仓库模型

```text
fastapi-lite
= 可复用 FastAPI 服务模板
= 单独维护工程范式、脚本、配置、provider、API envelope 和示例模块
= 不直接承载真实业务服务

order-api
= 从模板复制出来的一个真实服务
= 在这里修改服务身份、配置、业务模块、数据库迁移、文档和部署材料
```

模板仓库是模具，服务仓库是产品。不要直接在模板仓库里开发并提交真实业务服务。

## 创建新服务仓库

只改顶部变量区，然后整段复制粘贴执行。模板目录和新服务目录不需要在同一个父目录下：

```bash
TEMPLATE_PATH="/Users/admin/Code/lite/fastapi-lite"
SERVICE_PARENT="/Users/admin/Code/work"

SERVICE_DIR="order-api"
SERVICE_REPO="git@github.com:amuqiao/order-api.git"

cd "$SERVICE_PARENT"

git clone "$SERVICE_REPO" "$SERVICE_DIR"

rsync -av \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='.env' \
  --exclude='.pytest_cache' \
  --exclude='.run' \
  --exclude='logs' \
  --exclude='TEMPLATE-USAGE.md' \
  "$TEMPLATE_PATH"/ \
  "$SERVICE_DIR"/

cd "$SERVICE_DIR"

cp .env.example .env
uv sync
./scripts/verify.sh check
```

变量怎么改：

| 变量 | 改什么 |
|---|---|
| `TEMPLATE_PATH` | 模板仓库的绝对路径，例如 `/Users/admin/Code/lite/fastapi-lite`。 |
| `SERVICE_PARENT` | 新服务仓库要放置的父目录，不要求和模板仓库同级。 |
| `SERVICE_DIR` | 新服务目录名，通常等于仓库名。 |
| `SERVICE_REPO` | 新服务空仓库地址。 |

如果这个文件已经复制到了真实服务仓库，确认上面的命令跑通后可以删除：

```bash
rm TEMPLATE-USAGE.md
```

## 第一批服务专属修改

在复制出来的服务仓库里，优先改这些地方：

```text
pyproject.toml                 包名、描述、依赖分组
uv.lock                        修改 pyproject.toml 后重新生成
.env.example                   示例服务名、标题、数据库名、端口和 Compose 项目名
.env                           本机实际开发配置，不能提交真实密钥
docker-compose.yml             Compose 默认服务名、数据库名和容器环境默认值
alembic.ini                    本地默认 migration URL
README.md                      服务名、职责、Quick Start 和文档入口
docs/README.md                 文档入口里的服务定位和阅读路径
docs/current/implementation.md 当前实现事实
docs/contracts/api-contract.md 对外 HTTP 合同
docs/contracts/extension-contract.md 扩展范式，按需保留或收敛
app/core/config/sections.py    服务名、标题、数据库 URL 的代码默认值
app/api/operations.py          operation id 注册
app/core/error_registry.py     错误码注册
app/api/routes/                真实业务 routes
app/schemas/                   真实业务 schema
app/services/                  真实业务 service
app/repositories/              真实业务 repository
app/models/                    真实业务 model
alembic/versions/              真实业务 migration
tests/                         对应业务、合同、脚本和配置测试
deploy/                        真实环境 release 脚本或部署入口
```

脚本扩展按 [scripts/README.md](scripts/README.md) 的范式做：新增稳定入口或私有 helper 时，先明确入口职责、输出、退出码和副作用，再接入必要的 recipe。不要把长命令直接堆进 README 或 `pyproject.toml`。

## 新服务初始化清单

复制模板后，用这份清单把“模板身份”替换成“服务身份”：

| 文件或目录 | 必改内容 | 原因 |
|---|---|---|
| `pyproject.toml` | `project.name`、`description`、真实服务依赖 | 包元数据和安装结果要指向真实服务。 |
| `uv.lock` | 运行 `uv lock` | 保持锁文件与新的项目元数据、依赖一致。 |
| `.env.example` | `SERVICE__NAME`、`SERVICE__TITLE`、`DATABASE__URL`、`COMPOSE_PROJECT_NAME`、`POSTGRES_DB`、端口 | 新服务的默认本地环境不能继续使用模板名和数据库名。 |
| `.env` | 本机端口、数据库、Redis、API key、CORS origin | `.env` 是本地实际配置，不能把模板默认密钥当作真实服务配置。 |
| `docker-compose.yml` | 默认 `SERVICE__NAME`、`SERVICE__TITLE`、`POSTGRES_DB`、`DATABASE__URL` | 即使没有 `.env`，Compose 默认行为也应表现为真实服务。 |
| `alembic.ini` | 默认 `sqlalchemy.url` | 手动 Alembic 命令和脚本默认值要落到真实服务数据库。 |
| `app/core/config/sections.py` | `ServiceSettings`、`DatabaseSettings` 默认值 | 代码级默认值要和文档、`.env.example` 保持一致。 |
| `README.md` | 标题、服务职责、Quick Start、验证入口 | README 面向真实服务使用者，不再描述模板仓库本身。 |
| `docs/README.md` | 文档边界和阅读路径 | 真实服务应区分当前事实、稳定合同、计划和 notes。 |
| `docs/current/implementation.md` | 已实现能力 | 只能写代码和测试已经支持的事实。 |
| `docs/contracts/api-contract.md` | headers、envelope、routes、错误码、兼容性合同 | 调用方依赖这里，不要保留与真实 API 不符的示例合同。 |
| `app/api/routes/items.py` | 删除或替换示例 `items` API | 示例模块只证明模板链路，不应无意成为真实服务能力。 |
| `app/api/operations.py` | 注册真实 operation id | registry gate 会检查 route、文档和操作注册是否漂移。 |
| `app/core/error_registry.py` | 注册真实错误码 | API 错误 envelope 要保持可枚举、可测试。 |
| `app/models/`、`app/repositories/`、`app/services/`、`app/schemas/` | 替换为真实业务边界 | 保持 route -> schema -> service -> repository -> model 的分层。 |
| `alembic/versions/` | 新增真实业务迁移，按需删除示例迁移 | 数据库结构必须由 migration 表达。 |
| `tests/` | 修改模板身份断言，补齐真实 API、service、repository、migration 测试 | `./scripts/verify.sh check` 必须能证明真实服务行为。 |
| `deploy/` | 真实环境 release 脚本、目标和变量 | 发布入口不能继续指向模板环境或占位配置。 |

如果要把 `FASTAPI_LITE_POSTGRES_INTEGRATION` 这种测试开关改成服务专属名称，必须同时修改 `scripts/verify.sh` 和 `tests/test_postgres_integration.py`，并重新运行验证。

## 业务接入顺序

新服务不要先从大范围重构开始。建议按这个顺序落地：

```text
1. 改服务身份
   -> pyproject.toml / .env.example / docker-compose.yml / README.md

2. 明确第一个业务模块
   -> route / schema / service / repository / model / migration

3. 更新稳定合同
   -> docs/contracts/api-contract.md
   -> app/api/operations.py
   -> app/core/error_registry.py

4. 更新当前事实
   -> docs/current/implementation.md
   -> tests/

5. 做本地验证
   -> ./scripts/verify.sh check
   -> 按需运行 PostgreSQL 和 migration roundtrip gate
```

新增外部依赖、provider、中间件、工具脚本或 HTTP client 时，先看 [docs/contracts/extension-contract.md](docs/contracts/extension-contract.md)，再改代码和测试。

## 提交前最小验证

只改文档或项目身份时，至少运行：

```bash
uv lock
uv sync
./scripts/verify.sh check
```

改了数据库模型或 migration 时，额外运行：

```bash
./scripts/deploy.sh up compose-deps
./scripts/verify.sh postgres
./scripts/verify.sh migration-roundtrip
./scripts/deploy.sh down compose-deps
```

改了本地启停脚本、Docker Compose 或服务管理规则时，额外运行：

```bash
./scripts/run.sh up dev
./scripts/run.sh check dev
./scripts/run.sh down dev
```

不要上传或提交 `.env`、`.venv/`、`.run/`、`logs/`、`.pytest_cache/`。真实服务的密钥用部署平台或本地安全配置管理，`.env.example` 只保留可公开的示例值和占位符。
