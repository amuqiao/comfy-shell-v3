# ComfyUI Shell 架构设计

本文定义 `comfy-shell-v3` 的第一版架构。结论是：基于当前 FastAPI 模板继续开发，但把它裁剪成 ComfyUI 远程管理壳，不另起一套 `src/comfy_shell` 项目，也不把模板里的 CRUD、数据库和 Compose 能力当作第一版核心。

## 文档职责

本文只回答第一版怎么搭：

- 哪些当前模板能力保留。
- ComfyUI shell 的核心能力放在哪里。
- 本机 macOS 到远程 Linux GPU 机器的开发、部署和运维边界。
- 第一版做什么，不做什么。

本文不写具体函数、命令参数大全、API 字段大全，也不规划复杂平台能力。实现细节进入代码、测试和脚本文档。

## 核心模型

这个项目不是重做 ComfyUI，也不是做一个通用运维平台。它是一个运行在远程 Linux GPU 机器上的薄壳：

```text
macOS 本机
  -> 编辑 comfy-shell-v3 源码
  -> git push
  -> ssh 到远程机器触发部署/启动
  -> 浏览器通过 SSH tunnel 访问

Linux 远程 GPU 机器
  -> git pull comfy-shell-v3
  -> 运行 FastAPI/CLI/scripts
  -> 管理 ComfyUI versions/current/models/process/logs

ComfyUI
  -> 仍然负责原生工作流 UI 和推理
```

需要分清两个目录：

```text
code dir
  = comfy-shell-v3 项目源码
  = git pull、uv sync、运行 scripts 的地方

workspace dir
  = ComfyUI 运行资产目录
  = versions/current/models/logs/run/state 的地方
```

源码可以重 clone；workspace 不能随便删，因为里面有模型、版本目录和运行状态。

推荐远程目录：

```text
/data/wangqiao/comfy-shell-v3/            # REMOTE__CODE_DIR，项目源码
/data/wangqiao/comfy-shell-v3-workspace/  # COMFY__WORKSPACE_DIR，ComfyUI 运行资产
```

## 架构结论

采用当前模板作为基础，但收敛它的用途：

```text
FastAPI template foundation
  -> config / logging / health / error boundary / scripts / docs
Comfy shell domain
  -> versions / models / process / state / remote workflow
Optional web panel
  -> 后期再加，只调用 FastAPI API
ComfyUI native UI
  -> 用户真正操作 workflow 的界面
```

不再推荐另建一套独立 `src/comfy_shell` 主项目。当前仓库已有 FastAPI 工程边界、脚本范式、配置校验和文档分层，第一版应该复用这些地基。

## 保留与删减

保留当前模板的这些能力：

| 能力 | 为什么保留 |
| --- | --- |
| `app/core/config` | 已有 `.env`、section settings、env key 漂移检查，适合承载 ComfyUI shell 配置。 |
| `app/core/logging`、middleware、exceptions | API、脚本和后续 Web 控制面需要统一错误和日志边界。 |
| `/health`、`/ready` | 远程服务启动和 SSH tunnel 验证需要最小健康检查。 |
| `scripts/dev.sh`、`scripts/run.sh`、`scripts/verify.sh` | 已有稳定服务管理范式，适合扩展为 ComfyUI 日常运维入口。 |
| `docs/current`、`docs/contracts`、`docs/plans` | 继续用 current/contract/plan 分层，避免架构文档变成杂记。 |

第一版删减或后置这些能力：

| 能力 | 处理方式 |
| --- | --- |
| `items` CRUD 示例 | 作为模板示例移除或停用，避免和 ComfyUI shell 领域混在一起。 |
| SQLAlchemy / Alembic / repository / UnitOfWork | 第一版不使用数据库，状态写入 workspace 文件。保留代码只会增加误解，应在实现阶段裁掉。 |
| Docker Compose PostgreSQL / Redis | 第一版不依赖数据库和 Redis，`run.sh up dev` 不应默认启动它们。 |
| K8s / release 脚本 | 远程开发机部署先走 SSH + git pull，不做云部署。 |
| 多用户鉴权、队列、任务平台 | 不是个人远程 GPU workflow 第一版需求。 |

## 模块放置

基于当前项目结构，ComfyUI shell 能力放在 `app/` 内，而不是新建平行应用：

```text
app/
  api/routes/
    comfy.py          # FastAPI 控制面路由
  comfy/
    versions.py       # download archive/materialize/use
    models.py         # shared models 和 current/models 软链接
    process.py        # ComfyUI start/stop/status/logs
    state.py          # workspace/state.json
    paths.py          # workspace 路径计算
    archives.py       # GitHub source archive 下载与解压
    hf.py             # Hugging Face 下载
```

脚本仍然放在现有 `scripts/`：

```text
scripts/dev.sh       # 精确控制：doctor/start/stop/status/logs/test
scripts/run.sh       # 日常 recipe：up/status/down/restart/check dev
scripts/remote.sh    # 本机侧 SSH/tunnel/deploy/sync-dev
scripts/verify.sh    # lint/test/config/script checks
```

规则：

- Python 业务能力放在 `app/comfy/`，脚本只编排。
- API route 只做 HTTP 投影，不直接写 Git、软链接或进程逻辑。
- 共享 models、版本目录、PID、日志、状态都属于 workspace，不属于项目源码。

## 配置模型

配置只保留一个真源：每个代码目录里的 `.env`。

```text
macOS 本机 code dir
  .env            # RUNTIME__APP_ENV=local，包含 REMOTE__HOST/REMOTE__CODE_DIR
  .env.example    # 仓库模板

Linux 远程 code dir
  .env            # RUNTIME__APP_ENV=dev，包含 COMFY__WORKSPACE_DIR/API/HF key
  .env.example    # git pull 得到的模板
```

第一版不要再引入 `config.local.toml`、`config.dev.toml`、`.env.local`、`.env.dev`。这些会制造第二套配置入口。

新增配置进入 `app/core/config`：

```text
RuntimeSettings
ServiceSettings
SecuritySettings
ComfySettings       # 新增：workspace、ComfyUI repo、host/port、HF endpoint/token
RemoteSettings      # 新增：仅 local 环境使用，远程主机和远程代码目录
```

配置规则：

- `.env.example` 是配置 key 模板。
- 真实 `.env` 不提交。
- 环境变量可以覆盖 `.env` 中的同名配置。
- `RUNTIME__APP_ENV=dev` 时不允许出现 `REMOTE__*`，因为远程服务不应该知道本机编排参数。
- 配置错误启动即失败，不做默认路径猜测。

## 运行时 Workspace

远程 workspace 结构：

```text
/data/wangqiao/comfy-shell-v3-workspace/
  versions/
    ComfyUI-main-a1b2c3d/
    ComfyUI-v0.3.10-deadbee/
  current -> versions/ComfyUI-v0.3.10-deadbee
  models/
    checkpoints/
    loras/
    vae/
    controlnet/
  logs/
    api.log
    comfyui.log
  run/
    comfyui.pid
    comfyui.meta
    workspace.lock
  state.json
```

关键规则：

- `current` 只指向 `versions/<version-id>`。
- `version-id` 必须包含 resolved commit，不能只叫 `main`。
- `models/` 是唯一模型真源。
- `current/models` 只能是指向 workspace `models/` 的软链接。
- 版本 archive 自带的 `models/` 模板会在首次使用时合并进 workspace `models/`；同名不同内容直接报冲突。
- 切换版本、链接 models、启动/停止服务都必须加 workspace lock。
- 服务运行时拒绝切换版本。

## 远程生命周期

稳定路径只走 Git：

```text
macOS 本机
  -> 修改代码
  -> ./scripts/verify.sh check
  -> git commit
  -> git push

Linux 远程
  -> cd $REMOTE__CODE_DIR
  -> git pull --ff-only
  -> uv sync --frozen
  -> ./scripts/run.sh check dev
  -> ./scripts/run.sh restart dev
```

本机侧可以有 `scripts/remote.sh`，但它只包装 SSH：

```text
./scripts/remote.sh deploy
./scripts/remote.sh status
./scripts/remote.sh logs comfyui
./scripts/remote.sh tunnel
```

远程机器一般不改代码。若需要临时同步未提交代码，只允许显式 `sync-dev`，并且使用独立代码目录、独立 workspace 和独立端口。

## 第一版能力

第一版只做这些：

| 能力 | 最小行为 |
| --- | --- |
| 初始化 workspace | 创建 `versions/models/logs/run/state.json`。 |
| 拉取版本 | 从 ComfyUI GitHub source archive 下载指定 ref，解析 archive commit，物化到 `versions/`。 |
| 切换版本 | 停止服务后更新 `current` 软链接，并链接 `current/models`。 |
| 共享 models | workspace `models/` 是真源，版本目录只保留软链接。 |
| 下载模型 | 支持 HF endpoint/token，下载到指定模型子目录。 |
| 服务管理 | 启动、停止、状态、日志，只管理本项目拥有的 ComfyUI 进程。 |
| API 控制面 | 暴露版本、模型、服务状态和启停接口，默认只绑定 `127.0.0.1`。 |
| 脚本入口 | `run.sh` 负责日常 recipe，`dev.sh` 负责精确生命周期，`remote.sh` 负责 SSH。 |

## 不做的事情

第一版明确不做：

- 不做 ComfyUI 内部 API 兼容层。
- 不重做 ComfyUI 原生 UI。
- 不做数据库。
- 不做 Redis、队列、后台任务平台。
- 不做多用户登录和权限系统。
- 不做公网部署。
- 不做插件市场。
- 不自动覆盖已有模型目录。
- 不在远程机器上直接编辑源码作为常规流程。

这些不是永远不能做，而是不进入第一版架构。

## API 与 Web UI

FastAPI 控制面第一版只服务本机 SSH tunnel：

```text
远程:
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8700
  comfyui --listen 127.0.0.1 --port 8188

本机:
  ssh -L 8700:127.0.0.1:8700 -L 8188:127.0.0.1:8188 user@gpu-host
```

后期如果加前端页面，只作为控制面板：

```text
Vite UI
  -> 调用 FastAPI
  -> FastAPI 调用 app/comfy
  -> app/comfy 操作 workspace 和 ComfyUI 进程
```

前端不直接操作远程文件系统、Git、软链接或进程。

## 失败模式

第一版必须处理这些失败：

| 失败 | 处理原则 |
| --- | --- |
| 服务运行时切版本 | 直接拒绝，提示先停止服务。 |
| `current/models` 已是普通目录 | 直接拒绝，不自动删除、不自动迁移。 |
| 两个入口同时修改 workspace | Python 核心层加 workspace lock，拿不到锁就失败。 |
| Git ref 不存在 | 失败即停止，不创建假版本目录。 |
| branch ref 移动 | 版本身份记录 resolved commit。 |
| PID 陈旧 | 报告 stale，只清理本项目 PID/meta，不 kill 不归属进程。 |
| 端口被占用 | 启动前失败，不抢占。 |
| 远程 tracked file 有本地修改 | deploy 失败，要求本机提交后再部署。 |
| API 暴露到公网 | 第一版不支持，默认只绑定 `127.0.0.1`。 |

## 开发顺序

按这个顺序进入实现：

1. 清理模板：移除或停用 `items`、DB、Alembic、Compose 依赖路径，让项目先回到薄服务。
2. 配置：在 `app/core/config` 增加 `ComfySettings` 和 `RemoteSettings`，更新 `.env.example` 和配置 drift 检查。
3. Workspace 核心：实现 `app/comfy/paths.py`、`state.py`、workspace init 和 lock。
4. 版本与 models：实现 fetch/materialize/use、models link。
5. 服务管理：实现 ComfyUI start/stop/status/logs，并接入 `dev.sh`。
6. API 投影：新增 `app/api/routes/comfy.py`，路由只调用 `app/comfy/`。
7. 远程入口：新增或改造 `scripts/remote.sh`，完成 deploy/status/logs/tunnel。
8. 验证：`./scripts/verify.sh check` 覆盖配置、脚本、核心单测和 API smoke。

## 收口规则

这份文档到此为第一版架构边界。后续只有这些情况才继续改架构文档：

- 不再基于当前 FastAPI 模板开发。
- 配置真源不再是单 `.env`。
- 从单远程机器变成多机器、多实例或公网访问。
- 引入数据库、队列、鉴权、多用户或长期任务系统。
- ComfyUI shell 从个人运维工具变成多人平台。

普通实现细节、命令参数、错误文案、测试用例和脚本内部写法，不再反复扩大本架构文档。
