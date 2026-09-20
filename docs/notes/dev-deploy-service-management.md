# dev.sh / deploy.sh / run.sh 服务管理范式

本文定义可复用的服务启停范式：项目服务按运行位置分为 `local 服务` 和 `docker 服务`，日常开发环境 recipe 单独放进 `run.sh`。

## 这篇文档解决什么

这篇文档维护脚本使用的心智模型，方便新项目、新模板服务和大模型执行同一套服务管理规则。

它不替代 [`../../scripts/README.md`](../../scripts/README.md) 的当前命令合同；当前仓库已经按本文范式提供 `dev.sh`、`deploy.sh` 和 `run.sh` 三个入口。

## 核心模型

只保留三个用户入口：

```text
project operations
  -> local 服务
       -> 宿主机进程
       -> ./scripts/dev.sh

  -> docker 服务
       -> Docker Compose 容器
       -> ./scripts/deploy.sh

  -> daily recipe
       -> 日常环境全集
       -> ./scripts/run.sh
```

对应关系：

| 类型 | 管理入口 | 管理对象 | 典型命令 |
|---|---|---|---|
| local 服务 | `dev.sh` | 宿主机 API、Worker 等进程 | `./scripts/dev.sh start api` |
| docker 服务 | `deploy.sh` | Compose 依赖或完整容器形态 | `./scripts/deploy.sh up compose-deps` |
| 日常 recipe | `run.sh` | 面向人的日常环境全集 | `./scripts/run.sh up dev` |

一句话规则：

```text
dev.sh 管 local 进程；
deploy.sh 管 docker compose；
run.sh 管日常环境 recipe；
recipe 不能塞回 deploy.sh。
```

## 职责边界

`dev.sh` 只管理宿主机进程和本地开发辅助命令：

```text
dev.sh
  -> bootstrap / doctor / ports
  -> start / status / stop / restart / logs
  -> migrate / test
  -> 不启动或停止 Docker 服务
```

`deploy.sh` 只管理 Docker Compose 目标：

```text
deploy.sh
  -> compose-deps
       -> PostgreSQL / Redis 等依赖

  -> compose-full
       -> API / PostgreSQL / Redis 等完整 Docker 形态

  -> 不启动或停止宿主机 API / Worker
  -> 不承载 dev/local 这类 recipe 或别名
```

`run.sh` 只管理日常高频 recipe：

```text
run.sh
  -> dev
       -> 当前项目的日常开发环境全集
       -> compose-deps + 宿主机 API

  -> 只编排 dev.sh / deploy.sh 的稳定命令
  -> 不直接实现进程管理
  -> 不直接实现 Compose 管理
  -> 不吞掉子命令失败
```

## 标准命令形状

local 服务统一使用：

```bash
./scripts/dev.sh start <service>
./scripts/dev.sh status [service]
./scripts/dev.sh stop <service>
./scripts/dev.sh restart <service>
./scripts/dev.sh logs [service]
```

API 服务示例：

```bash
./scripts/dev.sh start api
./scripts/dev.sh status
./scripts/dev.sh stop api
```

Worker 服务示例：

当前 `fastapi-lite` 仓库只支持 `api`；如果某个派生项目或 worker 模板引入宿主机 Worker，应沿用同一命令形状：

```bash
./scripts/dev.sh start worker
./scripts/dev.sh status worker
./scripts/dev.sh stop worker
```

docker 服务统一使用：

```bash
./scripts/deploy.sh up <target>
./scripts/deploy.sh status <target>
./scripts/deploy.sh down <target>
```

标准 target：

```text
compose-deps
compose-full
```

日常 recipe 统一使用：

```bash
./scripts/run.sh up <recipe>
./scripts/run.sh status <recipe>
./scripts/run.sh down <recipe>
./scripts/run.sh restart <recipe>
./scripts/run.sh check <recipe>
```

当前标准 recipe：

```text
dev
```

## 常见操作路径

日常本地开发 API：

```text
启动
  -> ./scripts/run.sh up dev
     -> ./scripts/deploy.sh up compose-deps
     -> ./scripts/dev.sh start api

查看
  -> ./scripts/run.sh status dev
     -> ./scripts/dev.sh status
     -> ./scripts/deploy.sh status compose-deps

停止
  -> ./scripts/run.sh down dev
     -> ./scripts/dev.sh stop api
     -> ./scripts/deploy.sh down compose-deps

重启
  -> ./scripts/run.sh restart dev
     -> ./scripts/run.sh down dev
     -> ./scripts/run.sh up dev

检查
  -> ./scripts/run.sh check dev
     -> ./scripts/dev.sh doctor
     -> ./scripts/deploy.sh check
```

精确控制 API 和依赖：

```text
只启动依赖
  -> ./scripts/deploy.sh up compose-deps

只启动宿主机 API
  -> ./scripts/dev.sh start api

只查看 API
  -> ./scripts/dev.sh status

只停止依赖
  -> ./scripts/deploy.sh down compose-deps
```

全 Docker 验证：

```text
启动完整容器形态
  -> ./scripts/deploy.sh up compose-full

查看容器状态
  -> ./scripts/deploy.sh status compose-full

停止完整容器形态
  -> ./scripts/deploy.sh down compose-full
```

## 文字可视化速查

选择入口时先问目的：

```text
我要直接控制宿主机进程？
  -> dev.sh
     -> api
     -> worker

我要直接控制 Docker Compose？
  -> deploy.sh
     -> compose-deps
     -> compose-full

我要执行高频组合动作？
  -> run.sh
     -> dev
```

选择命令时再问动作：

```text
启动
  -> local:  dev.sh start <service>
  -> docker: deploy.sh up <target>
  -> recipe: run.sh up <recipe>

查看
  -> local:  dev.sh status [service]
  -> docker: deploy.sh status <target>
  -> recipe: run.sh status <recipe>

停止
  -> local:  dev.sh stop <service>
  -> docker: deploy.sh down <target>
  -> recipe: run.sh down <recipe>

检查
  -> local:  dev.sh doctor
  -> docker: deploy.sh check
  -> recipe: run.sh check <recipe>
```

## scripts 目录维护规则

目录结构优先保持简单：

```text
scripts/
  dev.sh
  deploy.sh
  run.sh
  verify.sh
  tools.sh
  k8s.sh

  lib/
  dev/
  verify/
  tools/
```

规则：

- 顶层 `*.sh` 是稳定用户入口，优先保持少而清晰。
- `lib/` 只放多个入口共享的 shell helper。
- `scripts/<entry>/` 只放某个入口的私有复杂 helper，例如当前 `dev/` 和 `verify/`。
- 不为了目录对称性新增 `deploy/` 或 `run/` 子目录。
- 只有出现 deploy/run 私有解析、检查、生成或多文件实现时，才新增对应子目录。
- `run.sh` 必须保持薄编排，不沉淀进程、Compose 或业务实现细节。

判断是否需要新增子目录：

```text
只是几行 shell 编排？
  -> 留在顶层入口脚本

多个入口都要复用？
  -> 放进 scripts/lib/

只有某个入口需要，且已经复杂到单文件难维护？
  -> 新增 scripts/<entry>/
```

## 禁止的混淆入口

不要把这些名称放进 `deploy.sh`：

```text
dev
local
worker
dev-worker
compose-worker
```

如果项目确实需要高频组合动作，新增到 `run.sh`：

```text
run.sh up dev
run.sh check dev
run.sh up worker
run.sh up api-worker
```

其中 recipe 名称描述“日常工作流”，不是描述底层运行位置。底层运行位置仍由 `dev.sh` 和 `deploy.sh` 负责。不要新增 `run.sh down all` 这类全局别名；`run.sh down dev` 已表示停止当前项目日常 dev recipe 的全部组成部分。

## 设计取舍

为什么不是只保留 `dev.sh` 和 `deploy.sh`？

```text
dev.sh / deploy.sh 表达服务在哪里运行；
run.sh 表达人每天想做什么。
```

日常命令确实需要存在，否则用户和大模型每天都要记住多条组合命令。但 recipe 如果放进 `deploy.sh`，`deploy.sh` 会同时表示 Docker 服务、local 服务和组合动作，边界会越来越模糊。

为什么现在不拆 `scripts/deploy/` 和 `scripts/run/`？

```text
目录服务于复杂度，不服务于对称性。
```

当前 `run.sh` 只是薄编排，不需要私有目录。当前 `deploy.sh` 的复杂度主要在共享 Compose helper 和 `docker-compose.yml`，已经由 `scripts/lib/compose.sh` 与 `scripts/lib/modes.sh` 承载。

## 新项目复用步骤

1. 先确认服务运行位置：宿主机进程还是 Docker Compose。
2. 宿主机进程加入 `dev.sh`，使用 `start/status/stop/restart/logs <service>` 形状。
3. Docker Compose 目标加入 `deploy.sh`，使用 `up/status/down <target>` 形状。
4. 高频组合动作加入 `run.sh`，只顺序调用 `dev.sh` 和 `deploy.sh`。
5. 每个标准日常 recipe 优先提供 `up/status/down/restart/check <recipe>` 五个动作。
6. 同步 `scripts/README.md`、`AGENTS.md`、`docs/current/implementation.md` 和相关测试。
7. 验证至少覆盖 `bash -n`、入口 help、目标 modes、recipe 调用顺序和脚本 smoke。

## 当前 fastapi-lite 命令

```bash
# 日常本地开发
./scripts/run.sh up dev
./scripts/run.sh status dev
./scripts/run.sh down dev
./scripts/run.sh restart dev
./scripts/run.sh check dev

# 精确控制宿主机 API
./scripts/dev.sh start api
./scripts/dev.sh status
./scripts/dev.sh stop api

# 精确控制 Docker Compose
./scripts/deploy.sh up compose-deps
./scripts/deploy.sh status compose-deps
./scripts/deploy.sh down compose-deps
./scripts/deploy.sh up compose-full
./scripts/deploy.sh status compose-full
./scripts/deploy.sh down compose-full
```
