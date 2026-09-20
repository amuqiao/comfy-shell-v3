# Git 规则
- 提交必须保持单一意图，不混入无关改动；跨主题改动应拆分提交。
- 提交前确认改动范围、提交主题、入口文档或规则文件同步情况。
- 提交前完成最小必要验证；无法验证时说明原因和剩余风险。
- 提交信息默认使用中文；无仓库规范时优先使用 Conventional Commits，例如 `docs:`、`feat:`、`fix:`、`refactor:`、`chore:`。
- 提交信息优先写“改了什么”和对象，不写空泛标题。
- 只在用户明确要求时提交；非明确要求下不做 `amend`，不改写历史。

# 本地服务启停规则
- `scripts/dev.sh` 只管理宿主机本地 FastAPI API 进程。
  - 启动 API：`./scripts/dev.sh start api`
  - 停止 API：`./scripts/dev.sh stop api`
  - 重启 API：`./scripts/dev.sh restart api`
  - 查看 API：`./scripts/dev.sh status`
- `scripts/deploy.sh` 只管理 Docker/Compose 服务。
  - 仅 Docker 依赖：`./scripts/deploy.sh up|status|down compose-deps`
  - 全 Docker API / 依赖：`./scripts/deploy.sh up|status|down compose-full`
- `scripts/run.sh` 只管理日常快捷 recipe，不直接实现进程或 Compose 细节。
  - 启动常用本地开发环境全集：`./scripts/run.sh up dev`
  - 查看常用本地开发环境全集：`./scripts/run.sh status dev`
  - 停止常用本地开发环境全集：`./scripts/run.sh down dev`
  - 重启常用本地开发环境全集：`./scripts/run.sh restart dev`
  - 检查常用本地开发环境全集：`./scripts/run.sh check dev`
- 不要使用裸 `./scripts/deploy.sh down`；该命令应报错，避免误停服务。
- 不要使用 `./scripts/deploy.sh up|status|down dev` 或 `local`；日常 dev 环境归 `run.sh`。
- 不要新增或使用 `./scripts/run.sh down all`；`./scripts/run.sh down dev` 已表示停止日常 dev 环境全集。
- 排查状态优先使用 `status`，不要直接用 `docker stop`、`kill` 或手工清理 PID，除非用户明确要求。
- 验证文档或脚本帮助时，不要执行会改变服务状态的 `up` / `down`，除非任务目标就是验证启停行为。

# 配置规则
- ./scripts 不应把可动态推导的路径、目录、端口列表、派生配置或脚本私有常量写入 .env / .env.example。应用配置只保存应用运行所需的显式输入；脚本内部行为优先从仓库结构、应用配置动态推导，无法推导时使用脚本内默认常量，并可按需支持临时 shell env 覆盖。
