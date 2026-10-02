# Pi Agent LangGraph：Codex 项目速览

## 项目定位与当前状态

本项目面向正在学习 Agent 工程的 Python 开发者：参考 Pi Agent 的设计，用 Python / LangGraph 实现可运行、可测试的模型—工具循环、会话、上下文和运行时。重点是理解 Pi 的设计意图与本项目的改造取舍，不追求逐项复制 Pi。Python 要求 `>=3.11,<3.14`；依赖和脚本以 `pyproject.toml` 为准。仓库采用 MIT 协议，见 `LICENSE`。

M0–M11 均已按**各自交付范围**归档；本机 Web 工作台是独立扩展，已于 2026-10-01 按已交付范围归档，见 `docs/acceptance/web-archive-2026-10-01.md`。同日整体复审覆盖工具设置调整及 CLI/TCP 基线兼容性，归档证据见 `docs/acceptance/web-cli-review-2026-10-01.md`。2026-10-02 归档后修复审批卡片位置，并增加会话工作区分组及六项工具持久额度，独立证据见 `docs/acceptance/web-approval-history-2026-10-02.md` 、`docs/acceptance/web-workspace-budgets-2026-10-02.md` 和 `docs/acceptance/web-node-checkpoints-2026-10-02.md`（审批继续及多工具节点详情修复）。同日增加持久 Token 统计与节点弹窗优化，见 `docs/acceptance/web-token-usage-2026-10-02.md`；模型 usage 缺失明确标记，复制分支历史不重复累计。新环境 Windows/Linux 和真实服务部署验证仍有后置项，Web 未关闭项见 `docs/follow-ups/web.md`，不能将归档等同于生产就绪。`PLAN.md` 是当前状态、范围和验收门槛的权威记录；`docs/acceptance/` 保存实际证据和未关闭项。`README.md` 是运行入口，`docs/README.md` 是文档索引，`LEARNING_LOG.md` 记录学习与决策。`docs/history/` 只作历史追溯。实现、验收、归档和复验日期分别记录。

## 一条请求如何运行

用户请求从 Web、CLI 或本机客户端进入；会话与上下文层准备模型输入；LangGraph 模型节点决定回复或调用工具；工具层验证参数和工作区路径，将结果交回模型；事件与 Hook 暴露过程，SQLite 保存需要持久化的会话和检查点。失败、取消、超时及恢复要沿这条链路检查。图负责状态、节点和路由；路径授权、模型适配、存储、审批和界面由应用层负责。

- `pi-agent --provider fake`：默认离线、确定性的**最小图**，不代表真实工具对话。
- `pi-agent --provider compatible`：显式启用持久化异步模型/工具链；只读 `read`、`list`、`search` 受工作区限制。命令执行须先形成持久化提案，再由交互终端审批；没有直接文件写入入口。
- `pi-agent-web`：FastAPI + React 本机单用户工作台。默认 fake 演示会调用真实工具；compatible 使用服务端模型配置。Web 提供会话、设置、流式文本、节点详情、中断恢复与完成 checkpoint 分支，以及服务 status/stop/restart。六项工具默认选中，页面取消选择从下一轮生效；每次用户请求各项调用上限为 0–20，新设置默认各 20，旧数值保留；审批继续/恢复共享 SQLite 持久额度，操作重入不重复扣除，失败与拒绝占用次数。侧栏按会话保存的工作区分组。write/edit/command 默认人工审批，`--no-require-approval` 可关闭新操作审批；默认命令程序为系统 shell，自定义 allowlist 可替换。操作仍持久认领，结果不确定时不自动重放；旧待审批提案不随新参数自动批准。
- `pi-agent-server` / `pi-agent-client`：共享令牌认证的 loopback TCP 会话入口，服务端持有工作区、模型与数据库；不作为公网服务部署。

Web 工作区指令使用 `PI-AGENTS.md`，**不加载根目录这个 Codex 用的 `AGENTS.md`**；CLI/TCP 的上下文管线仍使用工作区 `AGENTS.md`。见 `docs/pi-agents.md`。

## 代码地图

- `src/pi_agent/domain/`、`graph/`：消息状态、节点、工具路由与图构建。
- `tools/`、`security/`：工具注册、只读操作、命令/文件安全策略与路径约束。
- `models/`、`runtime/`：fake/compatible 适配、请求、重试、超时与取消。
- `sessions/`、`context/`：SQLite 检查点、会话元数据、规则装配与压缩。
- `events/`、`extensions/`、`telemetry/`、`evals/`：过程投影、Hook、脱敏观测与评测。
- `cli/`、`protocol/`、`server/`、`client/`：终端入口及本机协议链。
- `web/`、`web-ui/`：Web 后端与 React/TypeScript 前端；`scripts/start-web.ps1`（Windows）和 `scripts/start-web.sh`（macOS/Linux）安装、构建并启动。生成的 `src/pi_agent/web/static/` 不入 Git。
- `tests/`：按领域对应源码的 pytest；`web-ui/e2e/` 为浏览器测试。

让领域逻辑与图编排、存储、Provider 和 UI 保持分离。修改跨模块行为时沿具体请求追踪上游输入、状态变化、输出和失败路径，并检查相应测试。

## 协作与教学方式

用户要求引导式里程碑时，按“系统全貌 → 一个可验证切片 → 回到全貌”讲解：用一个请求追踪真实 Pi 调用链，再按“问题 → Pi 设计 → Python/LangGraph 选择 → 原因 → 代码位置 → 测试证据”说明。提供脚手架、接口、测试和一个有意义的学习者 TODO；评审其实现并等待验收，不默认代写整阶段。用户明确要求直接实现的任务（例如 Web 工作台扩展）按直接交付处理，不强行改成教学练习。没有新的里程碑授权时，不自行推进下一阶段。

判断当前行为以代码、配置和可运行证据为准；历史验收数只代表当时范围。修改 README、PLAN 或验收文档时同步核对有效链接和状态，不能用较新的测试结果回填旧阶段。不要把未经运行的真实模型、网络、CI、数据库或部署检查写成通过。

## 开发与验证

Windows / PowerShell 在仓库根目录运行；优先用 `uv run`，按改动范围先运行聚焦测试，再运行必要的质量门禁：

```powershell
uv run pytest tests/tools -q --basetemp=.pytest-tmp-tools
uv run pytest -q --basetemp=.pytest-tmp
uv run mypy src tests
uv run ruff check .
uv run ruff format --check .
uv run pi-agent --provider fake --prompt hello --events jsonl
uv run pi-agent eval --suite tools --provider fake
```

Web 改动另运行 `uv run --extra web pytest tests/web -q --basetemp=.pytest-tmp-web`，并在 `web-ui/` 运行 `npm run test`、`npm run build`；浏览器交互改动再运行 `npm run test:e2e`。首次环境安装见 `README.md`。真实 Provider 测试必须显式配置 `.env` 和 `PI_AGENT_LIVE=1`；默认测试保持离线。`uv` 缓存权限问题应区分于代码失败，记录实际执行边界。

## 安全与提交

密钥只从环境或显式 `.env` 加载，`.env.example` 只写变量名与说明。不要在日志、checkpoint、测试输出或提交中暴露密钥、Authorization 头及私有正文。文件和命令工具必须验证工作区、参数、超时及审批；路径限制不是 OS 沙箱。Web 数据库应放在工作区之外；避免 Web 与独立 CLI/TCP 同时驱动同一数据库。

使用 Python 类型标注、四空格缩进和小模块；Ruff 管格式，mypy 管类型。提交保持单一主题，可用简短 Conventional Commit 标题。PR 描述说明触发场景、行为变化、验证命令与结果，并链接相关计划/验收项。
