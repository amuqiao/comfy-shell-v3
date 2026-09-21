# comfy-shell-v3

<p align="center">
  <strong>一个用于远端 Linux GPU 机器的 ComfyUI 薄壳管理工具</strong>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.13+-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-shell-009688?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="ComfyUI" src="https://img.shields.io/badge/ComfyUI-remote_shell-111827?style=flat-square">
  <img alt="uv" src="https://img.shields.io/badge/uv-managed-6C47FF?style=flat-square">
  <img alt="Platform" src="https://img.shields.io/badge/macOS_to_Linux-SSH_tunnel-2563EB?style=flat-square">
  <img alt="Status" src="https://img.shields.io/badge/status-stable_ops-16A34A?style=flat-square">
</p>

<p align="center">
  <a href="#快速开始">快速开始</a>
  ·
  <a href="#日常运维">日常运维</a>
  ·
  <a href="#runtime-管理">Runtime 管理</a>
  ·
  <a href="#catalog-管理">Catalog 管理</a>
  ·
  <a href="#远端访问">远端访问</a>
</p>

`comfy-shell-v3` 是一个很薄的 ComfyUI 远端管理壳：本机 macOS 负责开发和维护代码，远端 Linux GPU 机器负责运行 ComfyUI，本机通过 SSH tunnel 在浏览器里打开 ComfyUI Web。

它不替代 ComfyUI，也不是通用的一键安装器。它只负责把一个个人远端 ComfyUI 工作流管稳定：切换已验证 runtime、共享唯一 `models/` 目录、启停服务、维护模型/工作流/插件信息、下载模型，并通过端口映射访问远端 ComfyUI。

## 核心模型

```text
macOS 本机
  -> 编辑和维护 comfy-shell-v3
  -> push 或同步代码到远端 GPU 机器
  -> 建立 SSH tunnel
  -> 浏览器打开 http://127.0.0.1:8188

Linux 远端 GPU 机器
  -> 运行 comfy-shell-v3
  -> 管理 ComfyUI runtimes、current 软链接、共享 models、日志和进程状态

ComfyUI
  -> 继续负责原生工作流 UI 和推理
```

项目刻意把“源码目录”和“运行资产目录”分开：

```text
code dir
  当前 Git 仓库
  存放 scripts、FastAPI app、CLI、catalog 配置和 docs

workspace dir
  远端运行资产
  存放 runtimes/current/current-env/models/logs/run/state
```

`workspace` 是长期运行状态和大文件所在位置，不要把它当成可以随时删除的项目源码。

## 能力范围

| 能力 | 说明 |
| --- | --- |
| ComfyUI runtime 管理 | 导入、准备、查看和切换已验证 runtime。 |
| 共享 models | 所有 runtime 共享同一份 workspace `models/`。 |
| 服务管理 | 通过 `run.sh` 启动、停止、重启、查看状态和日志。 |
| Catalog | 用 TOML 维护模型、工作流和插件信息。 |
| 模型下载 | 支持直链、Hugging Face、镜像地址和本地路径。 |
| 后台下载 | 支持远端 `nohup` 下载大模型，并查看状态。 |
| 插件管理 | 把 catalog 中的 custom nodes 安装或更新到当前 runtime。 |
| 远端访问 | 本机通过 SSH tunnel 打开远端 ComfyUI Web。 |

## 非目标

- 不重做 ComfyUI Web。
- 不自动解决所有 Torch、CUDA、driver 或 custom node 兼容问题。
- 不做多用户平台。
- 不同时管理多个 ComfyUI 服务实例。
- 不把模型下载历史写入数据库。
- 不为每个 ComfyUI 版本复制一份 `models/`。

## 目录结构

```text
app/
  comfy/              ComfyUI runtime、models、catalog、process、workspace 逻辑
  api/                FastAPI routes
  core/               settings、logging、errors 和服务基础能力

catalog/
  models/             模型来源、目标目录、大小和 sha256
  workflows/          工作流说明和依赖模型 ID
  plugins/            custom node 仓库信息
  workflow-files/     原始 ComfyUI workflow JSON

scripts/
  run.sh              日常运维总入口
  dev.sh              精确进程生命周期入口
  catalog.sh          catalog 校验、查看、下载、插件管理原子入口
  remote.sh           本机侧 SSH、deploy、status、logs、tunnel、sync helper
  verify.sh           项目验证入口

docs/
  architecture.md     架构和职责边界
  runbooks/           远程部署、runtime 修复和运维流程
```

## 环境要求

- 本机 macOS 可以 SSH 到远端 GPU 机器。
- 远端 Linux GPU 机器已有可用或可导入的 ComfyUI runtime。
- 使用 `uv` 管理本项目 Python 环境。
- 使用 Bash 运行项目脚本。
- 本项目 Python 版本要求 `>=3.13`。
- 本机和远端代码目录之间可以通过 Git 或受控同步更新代码。

稳定使用时，优先复用已经验证过的 ComfyUI runtime，再做最小依赖修复。

## 配置

每个代码目录只维护一份配置真源：`.env`。

```text
本机 macOS code dir
  .env                 本机编排配置，包含 REMOTE__*

远端 Linux code dir
  .env                 远端运行配置，包含 COMFY__*
```

从模板创建配置：

```bash
cp .env.example .env
```

关键配置：

```dotenv
RUNTIME__APP_ENV=local
COMFY__WORKSPACE_DIR=/data/wangqiao/comfy-shell-v3-workspace
COMFY__HOST=127.0.0.1
COMFY__PORT=8188
COMFY__CUDA_VISIBLE_DEVICES=1
COMFY__HF_ENDPOINT=https://hf-mirror.com
API_HOST=127.0.0.1
API_PORT=8700
REMOTE__HOST=47.94.108.140
REMOTE__CODE_DIR=/data/wangqiao/comfy-shell-v3
```

`REMOTE__*` 只放在本机 `.env`。远端 GPU 机器不应该依赖本机编排配置。

`COMFY__CUDA_VISIBLE_DEVICES` 用来绑定 ComfyUI 可见的物理 GPU。比如 `1` 表示远端 ComfyUI 只看到物理 GPU 1，并在 ComfyUI / PyTorch 内部把它作为 `cuda:0` 使用。

`COMFY__HF_ENDPOINT` 会作为 `HF_ENDPOINT` 注入 ComfyUI 子进程，用来约束 custom node 运行时通过 `huggingface_hub` 下载模型时使用的 Hub 地址。模型管理主路径仍然是 catalog 提前下载到共享 `models/`。

## 快速开始

安装依赖：

```bash
uv sync
```

运行默认验证：

```bash
./scripts/verify.sh check
```

查看日常运维入口：

```bash
./scripts/run.sh help
```

在远端代码目录初始化 workspace：

```bash
./scripts/run.sh init dev
```

在远端启动日常开发服务集合：

```bash
./scripts/run.sh up dev
./scripts/run.sh status dev
```

本机 macOS 建立 SSH tunnel：

```bash
./scripts/run.sh remote tunnel
```

然后在本机浏览器打开：

```text
http://127.0.0.1:8188
```

## 日常运维

日常只需要记 `run.sh`：

```bash
./scripts/run.sh status dev
./scripts/run.sh up dev
./scripts/run.sh down dev
./scripts/run.sh restart dev
./scripts/run.sh logs comfyui
```

精确排障时再使用底层脚本：

```bash
./scripts/dev.sh status comfyui
./scripts/dev.sh stop comfyui
./scripts/catalog.sh validate
./scripts/remote.sh status
```

不要手工修改 `current`、`current-env` 或 `current/models` 软链接。切换 runtime 使用 `run.sh`。

## Runtime 管理

远端 workspace 中的 ComfyUI runtime 独立于本项目源码：

```text
/data/wangqiao/comfy-shell-v3-workspace/
  runtimes/
    comfyui-0.27.0-known-good/
    comfyui-0.36.0/
  current -> runtimes/<name>/ComfyUI
  current-env -> runtimes/<name>/.venv
  models/
```

导入一个已验证 runtime：

```bash
./scripts/run.sh import-runtime comfyui-0.27.0-known-good \
  --comfy-dir /data/wangqiao/comfy-shell/ComfyUI \
  --venv-dir /data/wangqiao/comfy-shell/.venv
```

从 ComfyUI 源码包和 seed runtime 环境准备新 runtime：

```bash
./scripts/run.sh stage-runtime comfyui-0.36.0 \
  --archive /data/wangqiao/comfy-shell-v3-workspace/staging/ComfyUI-0.36.0.zip \
  --seed-runtime comfyui-0.27.0-known-good
```

切换当前 runtime：

```bash
./scripts/dev.sh stop comfyui
./scripts/run.sh switch comfyui-0.36.0
./scripts/dev.sh start comfyui
```

同一个端口上同一时间只应该运行一个 ComfyUI runtime。

## Catalog 管理

`catalog/` 是给人读、也给脚本读的信息真源：

```text
catalog/workflows/*.toml
  工作流说明和依赖模型 ID

catalog/models/*.toml
  模型来源、文件名、目标 models 子目录、大小和 sha256

catalog/plugins/*.toml
  custom node 仓库信息
```

映射关系保持单向：

```text
workflow model id
  -> catalog model entry
  -> source + filename + target
  -> workspace models/<target>/<filename>
```

校验 catalog：

```bash
./scripts/run.sh catalog validate
```

查看某个工作流的模型状态：

```bash
./scripts/run.sh catalog inspect workflow video_wan2_2_14b_animate \
  --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
```

只探测链接，不下载：

```bash
./scripts/run.sh catalog probe workflow video_wan2_2_14b_animate
```

远端后台下载工作流缺失模型：

```bash
./scripts/run.sh catalog download-bg workflow video_wan2_2_14b_animate \
  --models-dir /data/wangqiao/comfy-shell-v3-workspace/models
```

查看后台下载状态：

```bash
./scripts/run.sh catalog download-bg-status workflow video_wan2_2_14b_animate
```

模型已经落盘后，计算或回填元信息：

```bash
./scripts/run.sh catalog metadata workflow video_wan2_2_14b_animate \
  --models-dir /data/wangqiao/comfy-shell-v3-workspace/models

./scripts/run.sh catalog enrich workflow video_wan2_2_14b_animate \
  --models-dir /data/wangqiao/comfy-shell-v3-workspace/models \
  --write
```

`size_hint` 只给人读。`size_bytes` 和 `sha256` 是机器可校验字段。

## 插件管理

通过 plugin catalog 安装和更新 custom nodes：

```bash
./scripts/run.sh catalog install plugins
./scripts/run.sh catalog update plugins
./scripts/run.sh catalog installed plugins
```

插件命令负责把仓库 clone、fetch、checkout、pull 到当前 runtime 的 `custom_nodes/` 目录。它不会自动安装所有插件依赖。安装或更新插件前先停止 ComfyUI。

## 远端访问

常用远端目录：

```text
/data/wangqiao/comfy-shell-v3/             code dir
/data/wangqiao/comfy-shell-v3-workspace/   workspace dir
```

本机开发流程：

```bash
./scripts/verify.sh check
git push
./scripts/run.sh remote status
```

远端部署流程：

```bash
cd /data/wangqiao/comfy-shell-v3
git pull --ff-only
uv sync --frozen
./scripts/run.sh restart dev
```

本机建立 tunnel：

```bash
./scripts/run.sh remote tunnel
```

浏览器入口：

```text
ComfyUI Web      http://127.0.0.1:8188
Comfy shell API  http://127.0.0.1:8700/docs
```

## 文档

- 架构设计：[docs/architecture.md](docs/architecture.md)
- 远程部署：[docs/runbooks/远程部署.md](docs/runbooks/远程部署.md)
- Runtime 修复记录：[docs/runbooks/runtime-patches.md](docs/runbooks/runtime-patches.md)
- 脚本合同：[scripts/README.md](scripts/README.md)
- Agent 维护规则：[AGENTS.md](AGENTS.md)

项目里仍保留部分 FastAPI 模板历史文档。判断当前 ComfyUI shell 行为时，优先看本 README、`docs/architecture.md`、runbooks、scripts 和 tests。

## 验证

默认验证：

```bash
./scripts/verify.sh check
```

运行测试：

```bash
uv run pytest
```

校验 catalog：

```bash
./scripts/run.sh catalog validate
```

修改 runtime、模型、插件或远端运维相关能力前，先运行最小相关脚本命令，再运行默认验证。

## 运维规则

- 同一个端口只运行一个 ComfyUI runtime。
- ComfyUI GPU 绑定通过 `COMFY__CUDA_VISIBLE_DEVICES` 声明，不手工 `export CUDA_VISIBLE_DEVICES` 绕过 `run.sh`。
- 只维护一份共享 workspace `models/`。
- 模型、工作流和插件信息放在 `catalog/`。
- 日常操作优先使用 `scripts/run.sh`。
- 不在远端 GPU 机器上手改源码；本机修改后再部署或远端拉取。
- 大模型文件、runtime 目录、日志和真实密钥不进 Git。
