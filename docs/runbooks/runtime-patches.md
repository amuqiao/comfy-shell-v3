# Runtime Patch 记录

本文记录已经跑通但不属于 `comfy-shell-v3` 源码的 runtime 级修复。它用于重建 runtime、迁移机器或排查启动失败时复现环境。

## 管理边界

```text
comfy-shell-v3 源码
  -> 通过 git 管理
  -> 不记录 ComfyUI 第三方包源码

workspace runtime
  -> /data/wangqiao/comfy-shell-v3-workspace/runtimes/<name>/
  -> 包含 ComfyUI 源码和独立 .venv
  -> 可按 runtime 做最小依赖修复
```

不要把某个 runtime 的补丁直接套到所有版本。`comfyui-0.27.0-known-good` 是回滚和 seed 环境，默认不修改。

## comfyui-0.36.0

当前已验证状态：

```text
runtime: comfyui-0.36.0
ComfyUI commit: ee71d5c4993f29086b27fde1629a945ae48425bf
workspace: /data/wangqiao/comfy-shell-v3-workspace
ComfyUI: /data/wangqiao/comfy-shell-v3-workspace/runtimes/comfyui-0.36.0/ComfyUI
venv: /data/wangqiao/comfy-shell-v3-workspace/runtimes/comfyui-0.36.0/.venv
python: /data/wangqiao/comfy-shell-v3-workspace/runtimes/comfyui-0.36.0/.venv/bin/python
```

来源：

```text
本机 zip: .data/ComfyUI-0.36.0.zip
远端 staging: /data/wangqiao/comfy-shell-v3-workspace/staging/ComfyUI-0.36.0.zip
seed runtime: comfyui-0.27.0-known-good
```

环境策略：

```text
保留 torch 2.6.0+cu124
不升级 CUDA/Torch
只修 comfyui-0.36.0 的独立 .venv
不污染 comfyui-0.27.0-known-good
```

已应用依赖：

```bash
uv pip install \
  --default-index https://pypi.tuna.tsinghua.edu.cn/simple \
  --python /data/wangqiao/comfy-shell-v3-workspace/runtimes/comfyui-0.36.0/.venv/bin/python \
  comfy-kitchen==0.2.31 \
  comfy-aimdo==0.5.3
```

已应用兼容补丁：

```text
file:
  /data/wangqiao/comfy-shell-v3-workspace/runtimes/comfyui-0.36.0/.venv/lib/python3.12/site-packages/comfy_kitchen/backends/eager/na.py

reason:
  torch 2.6.0 的 torch.library.infer_schema 不接受 PEP 585 的 list[int] / list[bool] annotation。

change:
  import math
  from typing import List

  list[int]  -> List[int]
  list[bool] -> List[bool]

backup:
  na.py.comfy-shell-bak
```

验证命令：

```bash
cd /data/wangqiao/comfy-shell-v3

./scripts/run.sh runtimes current
./scripts/run.sh status dev
curl -fsS -I http://127.0.0.1:8188/
```

期望结果：

```text
current runtime 是 comfyui-0.36.0
ComfyUI running=true
远端 127.0.0.1:8188 返回 HTTP 200
```
