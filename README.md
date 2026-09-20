# fastapi-lite

`fastapi-lite` 是一套轻量但不空心的 FastAPI 服务骨架，用来统一后续业务 API、worker-adjacent API 和内部服务的工程范式。

## What Is Included

- FastAPI app factory 和 lifespan。
- section 化配置、`.env.example` manifest 校验和 release invariant。
- request id / trace id 中间件、access log、CORS、异常处理。
- success/error envelope、error registry、operation registry。
- `/health` 和 `/ready`。
- SQLAlchemy async、Alembic、UnitOfWork、repository。
- `items` CRUD 示例模块。
- lifecycle providers：Postgres、Redis fake boundary、object storage、shared HTTP client。
- `app/tools/` 示例工具模块。
- `dev.sh`、`deploy.sh`、`run.sh`、`verify.sh`、`tools.sh` 脚本入口。
- 脚本公共能力：`doctor`、端口扫描、PID/log 管理、Docker Compose 管理、日常 recipe、迁移入口、secret/env-url 工具、registry/env/docs drift gate。
- Dockerfile、docker-compose.yml 和 `start-api.sh` API 容器入口。

## Quick Start

Install dependencies:

```bash
uv sync
```

Run the default verification:

```bash
./scripts/verify.sh check
```

Show local development commands:

```bash
./scripts/dev.sh help
```

Check the local development environment:

```bash
./scripts/dev.sh doctor
```

Scan common local ports:

```bash
./scripts/dev.sh ports 8100 25432 26379
```

Start the common local development stack:

```bash
./scripts/run.sh up dev
./scripts/run.sh status dev
./scripts/run.sh down dev
./scripts/run.sh restart dev
./scripts/run.sh check dev
```

This starts PostgreSQL and Redis with Docker Compose, then starts the FastAPI app on the host. The app process can start without opening a database connection, but `/ready` and the `items` API require a reachable PostgreSQL database unless tests inject a session override.

Manage local services in three ways:

| Entry | Use it for |
|---|---|
| `./scripts/run.sh up|status|down|restart|check dev` | Daily local development environment as one recipe: Docker PostgreSQL / Redis plus host API. |
| `./scripts/dev.sh start|status|stop api` | Precise host API process control. |
| `./scripts/deploy.sh up|status|down compose-deps|compose-full` | Explicit Docker Compose dependencies or full Docker API/dependencies. |

Run only local dependencies with Docker Compose:

```bash
./scripts/deploy.sh up compose-deps
```

Run only the host API:

```bash
./scripts/dev.sh start api
```

Run the API, PostgreSQL, and Redis in Compose:

```bash
./scripts/deploy.sh up compose-full
```

Generate local secrets and encoded connection URLs:

```bash
./scripts/tools.sh secret
./scripts/tools.sh env-url postgres --username postgres --host 127.0.0.1 --database fastapi_lite --password-stdin
```

## Documentation

- Docs index: [`docs/README.md`](docs/README.md)
- Global mental model: [`docs/notes/FastAPI_Lite 全局心智模型.md`](<docs/notes/FastAPI_Lite 全局心智模型.md>)
- Current implementation facts: [`docs/current/implementation.md`](docs/current/implementation.md)
- HTTP API contract: [`docs/contracts/api-contract.md`](docs/contracts/api-contract.md)
- Extension contract: [`docs/contracts/extension-contract.md`](docs/contracts/extension-contract.md)
- Drift checklist and P1 plan: [`docs/plans/drift-checklist.md`](docs/plans/drift-checklist.md)
- Scripts contract: [`scripts/README.md`](scripts/README.md)
- Original skeleton target, retained as historical input: [`docs/FastAPI服务骨架.md`](docs/FastAPI服务骨架.md)

## Verification

Default gate:

```bash
./scripts/verify.sh check
```

PostgreSQL integration gate:

```bash
./scripts/verify.sh postgres
```

The Postgres gate is opt-in and protected by a `_test` database check.

Migration roundtrip gate:

```bash
./scripts/verify.sh migration-roundtrip
```
