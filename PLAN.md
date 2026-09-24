# Python Pi Agent（LangGraph）执行计划

## 1. 当前状态与文档分工

- 初始规划：2026-09-02；M5 初次归档：2026-09-18；M5 遗留项复验、M6 实现与归档：2026-09-21（Asia/Shanghai）。
- M0–M8 已按各自交付范围归档。M8 于 2026-09-23（Asia/Shanghai）首次归档；2026-09-24 补齐真实 Provider CLI 只读闭环、重试/时限、命令人审入口，并在配置的 compatible 服务完成 4 个 live smoke 与合成文件 CLI 工具调用。初次归档与后续复验分列于 [M8](docs/acceptance/M8.md)、[纠正记录](docs/acceptance/M8-closure.md)。M8.3/M8.4 及 R2-D–R2-F 由助手代写，学习者复盘另行进行。
- M9 于 2026-09-24 启动、完成已交付范围并归档。用户报告最终组合测试 **28 passed**、mypy **203 source files**、Ruff lint/format 与 fake eval CLI 通过；默认 CLI telemetry、带工具调用的 CLI eval 和可选 live eval 的边界见 [M9 归档](docs/acceptance/M9.md)。
- M5 同步取消与 M8 异步组件、主请求取消接线已分别验证；真实传输中取消、429 故障注入和跨平台进程树仍按 [剩余清单](docs/follow-ups/M1-M8.md) 单列，不扩大现有 smoke 结论。

| 文件 | 唯一职责 |
|---|---|
| PROJECT_SPEC.md | 项目目标与教学方式 |
| PLAN.md | 当前状态、里程碑范围、验收要求、阶段接口 |
| LEARNING_LOG.md | 学习者基础、按里程碑总结、关键决策、问题索引 |
| docs/acceptance/Mx.md | 对应里程碑的验收命令、结果、局限和归档结论 |
| docs/README.md | M1–M9 文档索引；审计、总结与后续任务入口 |
| docs/history/ | 已封存的过程记录；不能作为当前任务清单 |

状态取值为 `pending / in_progress / completed / blocked`；最多一个 `in_progress`，阶段间允许为零。归档只证明对应验收文件声明的范围，不能把教学范围扩张成生产能力。

| 里程碑 | 名称 | 状态 | 阶段 | 归档/依据 |
|---|---|---|---|---|
| M0 | 源码分析与路线设计 | completed | 总览 | 2026-09-02 初始规划记录 |
| M1 | Python 工程骨架 | completed | MVP | [M1](docs/acceptance/M1.md)，2026-09-03 |
| M2 | 消息、状态与最小图 | completed | MVP | [M2](docs/acceptance/M2.md)，2026-09-04 用户验收 |
| M3 | Tool Calling 闭环 | completed | MVP | [M3](docs/acceptance/M3.md)，2026-09-11 |
| M4 | 安全 Coding Tools 与人工审批 | completed | MVP | [M4](docs/acceptance/M4.md)，2026-09-16 |
| M5 | 流式事件与 CLI 闭环 | completed | MVP | [M5](docs/acceptance/M5.md)，2026-09-21 遗留项闭合复验 |
| M6 | 会话持久化、恢复与分支 | completed | MVP | [M6](docs/acceptance/M6.md)，2026-09-21 归档 |
| M7 | 上下文装配与长对话压缩 | completed | 增强 | [M7](docs/acceptance/M7.md)，2026-09-22 最终验收与归档 |
| M8 | 模型适配、重试、取消与容错 | completed | 增强 | 2026-09-23 首次归档；2026-09-24 接线纠正与真实 provider 复验；[M8 归档](docs/acceptance/M8.md)、[纠正记录](docs/acceptance/M8-closure.md) |
| M9 | 扩展、可观测性与评测 | completed | 生产化 | [M9 归档](docs/acceptance/M9.md)，2026-09-24 已交付离线范围验收；未关闭边界保留 |
| M10 | 远程协议与客户端/服务端 | pending | 可选扩展 | 尚未启动 |
| M11 | 全链路验收与架构复盘 | pending | 收束 | 尚未启动 |

日期规则：实现/学习日期、验收日期、归档日期、复验日期分别记录；历史测试数只代表对应阶段。未经核对的具体时间不补写。M5 子练习统一归入 M5，不再追加在 M4 标题下。

可复现基线：上游分析固定 `earendil-works/pi main@96317e50b8d6e7f6d0e47fd29122baf1461c00f5`，核心包 `0.84.4`；Python 3.11+，项目声明 LangGraph `>=1.2,<1.3`。历史 2026-09-16 记录的稳定版为 `1.2.11`；本次未重新核对上游最新版本，不将历史记录写成“当前最新”。

## 2. Pi Agent 源码架构地图

Pi 是一组可组合包，而不只是 CLI：

- `packages/ai/src/types.ts` 与 provider 实现统一模型、消息、工具 schema、流式事件、鉴权和用量。
- `packages/agent/src/agent.ts` 的 `Agent` 管理状态、steer/follow-up 队列和生命周期；`agent-loop.ts` 的 `runLoop()`、`streamAssistantResponse()`、`executeToolCalls()` 构成核心循环。
- `packages/coding-agent/src/cli.ts` → `main.ts:main()` → `AgentSessionRuntime` → `AgentSession.prompt()` → `Agent.prompt()` 是本地 CLI 主链路。
- Pi 的 Coding Tools 提供 read、grep/find、list、edit、write 和命令执行；本地可审查源码树已把核心实现集中到 `packages/agent/src/harness/tools/` 和 `harness/env/`。其环境抽象支持绝对路径和主机执行，本项目将在其外增加更严格的工作区权限边界。
- `session-manager.ts` 用树形 JSONL 保存消息、模型、thinking、compaction 和 branch；`resource-loader.ts` 逐级加载 `AGENTS.md` 等上下文；`compaction/` 负责摘要。
- `extensions/` 暴露命令、工具和生命周期钩子；`telemetry/` 提供后端无关 span；`evals/` 执行真实模型行为评测。
- `protocol/`、`server/`、`client/` 使用“长度前缀 + CBOR”和权威 session snapshot 支持远程会话；API 仍标为 experimental。
- `tui/` 是差分渲染终端框架，与 Agent 核心解耦。

核心运行链路：用户输入 → 资源/扩展预处理 → user message → 模型流 → assistant/tool calls → schema 校验与工具执行 → toolResult 回灌 → 条件继续或结束 → 事件派发与 session 持久化。

## 3. TypeScript 到 Python/LangGraph 的映射

| Pi 抽象 | Python/LangGraph 方案 |
|---|---|
| `AgentState` / `AgentMessage` | `TypedDict`/Pydantic 边界模型 + LangChain messages + reducer |
| `runLoop()` | `StateGraph` 的 model/tool 节点、条件边和 `Command` |
| `AgentTool` + TypeBox | `@tool`/Pydantic 参数模型 + 自定义安全执行器 |
| `AgentEvent` / streaming | 同步/异步投影及真实 Provider CLI 节点级/完整消息事件已接线；CLI token-by-token 输出仍非保证 |
| steer/follow-up | 应用层输入队列；图只消费已提交的下一批输入 |
| JSONL session tree | LangGraph checkpointer + 独立 session 元数据仓储 |
| branch/restore | `get_state_history()`、checkpoint config、`update_state()` |
| compaction/transformContext | 当前在 model 节点内派生临时上下文，不覆写持久历史；独立策略节点是可选后续设计 |
| extension hooks | 图外 middleware/hook registry；需要路由时返回 `Command` |
| pi-ai providers | 项目自有同步/异步模型协议与 compatible HTTP 适配；不重写全部供应商 SDK |
| remote protocol/TUI | MVP 后独立适配层，不进入图的领域核心 |

优先级：必须掌握状态/reducer、节点与路由、工具循环、streaming、checkpoint、错误与测试；需要理解上下文压缩、provider 边界、hooks、telemetry；暂时了解远程协议、TUI、模型评测；第一版忽略完整 provider/OAuth 目录、图像能力、二进制发布、全量 Pi 扩展兼容。

## 4. 目标目录

```text
src/pi_agent/
  domain/        # 消息、状态、错误
  events/        # 稳定事件投影、序列化、终态过滤
  graph/         # graph builder、nodes、routing
  tools/         # registry、安全策略与 Coding Tools
  models/        # 模型协议、compatible HTTP 适配与 fake
  sessions/      # checkpoint 与 session 元数据
  context/       # AGENTS/skills/prompt/compaction
  runtime/       # orchestration、取消、重试
  extensions/    # M9 受约束 lifecycle hooks
  telemetry/     # M9 后端无关 spans、metrics/log ports 与 lifecycle adapter
  evals/         # M9 fake suite/case/judge 与稳定 JSON report
  cli/           # 命令与渲染
tests/           # 与 src 镜像
docs/acceptance/ # 每个里程碑的验收记录
```

## 5. 里程碑契约

每项固定保留目标、范围、非目标、交付物、验收标准、验证命令。已完成项的事实与局限见归档；M10–M11 命令为未来验收目标，其中尚未创建的目录或入口不能当作现在可执行的命令。

### M0 — 源码分析与路线设计

- **目标**：固定真实源码基线，形成架构地图、重构边界和可验收路线。
- **范围**：Pi 根文档及 ai、agent、coding-agent、session、tools、extensions、telemetry、evals、TUI、protocol/server/client；LangGraph 官方 StateGraph、Command、streaming、checkpoint、interrupt。
- **非目标**：生成 Python 业务代码或运行上游测试。
- **交付物**：`PLAN.md`、`LEARNING_LOG.md`；确认已有 `AGENTS.md`。
- **验收标准**：记录 branch/SHA/version；每个后续里程碑包含六个固定字段；状态表无多个进行中项。
- **验证命令**：`Get-Content -Raw PLAN.md`；`Get-Content -Raw LEARNING_LOG.md`；`Select-String -Path PLAN.md -Pattern '^### M\d+'`。

### M1 — Python 工程骨架

- **目标**：建立可安装、可 lint、可测试的 `src` 项目。
- **范围**：`pyproject.toml`、uv lock、包目录、pytest/ruff/mypy 基线、`.env.example`、最小 CI、验收文档模板。
- **非目标**：Agent 图、真实模型或工具。
- **交付物**：可导入的 `pi_agent` 包和一个健康检查测试。
- **验收标准**：Python 3.11/3.12 均可安装；无网络/密钥即可通过静态检查和测试。
- **验证命令**：`uv sync --all-extras`；`uv run ruff check .`；`uv run ruff format --check .`；`uv run mypy src`；`uv run pytest`。

### M2 — 消息、状态与最小图

- **目标**：用 LangGraph 实现一次 user → model → END 的可理解闭环。
- **范围**：typed state、message reducer、运行配置、fake chat model、model node、条件结束、状态/事件契约测试。
- **非目标**：工具执行、持久化、真实 provider。
- **交付物**：`domain/`、`graph/`、fake model 与图级单测。
- **验收标准**：输入不会重复累计；输出类型稳定；错误状态可观察；无废弃 API。
- **验证命令**：`uv run pytest tests/domain tests/graph/test_minimal_graph.py -q`；`uv run mypy src/pi_agent/domain src/pi_agent/graph`。

### M3 — Tool Calling 闭环

- **目标**：实现 model → tools → model 的受控循环。
- **范围**：tool registry、Pydantic 参数校验、未知工具/执行异常转 `ToolMessage`、条件路由、最大轮次、并行能力的明确策略、fake tools。
- **非目标**：访问真实文件或启动进程。
- **交付物**：工具节点、路由函数、tool call 事件和确定性测试。
- **验收标准**：成功、非法参数、未知工具、异常、达到轮次上限均有稳定终态；tool call 与 result ID 一致。
- **验证命令**：`uv run pytest tests/tools/test_registry.py tests/graph/test_tool_loop.py -q`；`uv run ruff check src/pi_agent/graph src/pi_agent/tools`。

### M4 — 安全 Coding Tools 与人工审批

- **目标**：提供可实际工作的文件/搜索/修改/命令工具，并把安全边界作为产品能力。
- **范围**：read/list/search、edit/write、受控 subprocess；工作区 realpath 校验、symlink/路径穿越防护、输出限制、超时/取消、危险命令策略；写入和高风险命令用 `interrupt()` + `Command(resume=...)` 审批。
- **非目标**：容器隔离、任意主机 shell、网络工具。
- **交付物**：工具适配器、安全策略、审批 DTO、临时工作区集成测试。
- **验收标准**：无法越过允许根目录；默认拒绝高风险操作；超时会终止进程树；拒绝/批准均可恢复。
- **验证命令**：`uv run pytest tests/tools tests/security tests/integration/test_hitl.py -q`；`uv run ruff check .`。

M4 交付的是安全工具、文件审批和 prepare→approval→apply 集成。M5 的事件展示不属于 M4；本地 CLI 尚未接入 M4 的真实 Coding Tools。结构化进程 allowlist/超时也不等同完整高风险命令审批产品。

### M5 — 流式事件与 CLI 闭环

- **目标**：形成可交互、可观测的端到端 MVP。
- **范围**：同步 `stream()` 的 token/state/tool/custom 事件适配、稳定 JSONL、简单 CLI、Ctrl+C 协作取消、fake provider 演示；真实 provider 的异步取消传播属于 M8。
- **非目标**：Pi TUI 差分渲染、主题、图片或 RPC。
- **交付物**：CLI entry point、文本/JSONL renderer、端到端测试。
- **验收标准**：token 与工具进度按顺序输出；最终状态只发布一次；取消无悬挂任务。
- **验证命令**：`uv run pytest tests/events tests/cli tests/integration --ignore=tests/integration/test_hitl.py -q --basetemp=.pytest-tmp`；`uv run pi-agent --provider fake --prompt hello --events text`；`uv run pi-agent --provider fake --prompt hello --events jsonl`。

归档结果：2026-09-21 复验 M5 范围 47 项、全仓 123 项通过。无密钥脚本流验证 token/tool/custom/terminal 顺序与逐事件 flush；终态只发布一次并立即关闭上游；预取消不启动生产者，取消和输出异常均释放已启动的 raw stream。M5-R1–R4 已闭合，边界见 [M5 归档](docs/acceptance/M5.md)。

### M6 — 会话持久化、恢复与分支

- **目标**：使同一会话可中断恢复、查看历史并从 checkpoint 分支。
- **范围**：开发用 SQLite checkpointer、`thread_id`、session metadata、恢复、历史、fork、崩溃/并发写测试；生产存储接口。
- **非目标**：多租户服务端、跨设备同步。
- **交付物**：`sessions/`、schema/migration 策略、CLI session 子命令。
- **验收标准**：重启后可续聊；checkpoint 不重复执行已完成副作用；分支不污染原会话；损坏数据给出明确错误。
- **验证命令**：`uv run pytest tests/sessions tests/cli/test_session_app.py tests/integration/test_resume.py tests/integration/test_session_history.py tests/integration/test_fork.py -q --basetemp=.pytest-tmp`；`uv run pi-agent session list --database .pytest-tmp\m6-session-list.sqlite`。

归档结果：M6.1–M6.7 已完成跨进程续聊、历史投影、受限状态 fork、应用 metadata、迁移恢复/并行写、损坏 SQLite 显式错误以及 `session list` CLI。fork 只复制选中状态且不执行节点；默认 fake 运行 CLI 仍不代表持久会话或 Coding Tools 已接通。完整证据与生产化局限见 [M6 归档](docs/acceptance/M6.md)。

原验收标准中的“checkpoint 不重复执行已完成副作用”只在 fork 不调用图节点这一窄场景得到验证；任意崩溃重放下的文件/命令副作用幂等尚未验收，继续由 [F07](docs/follow-ups/M1-M8.md) 跟踪。

### M7 — 上下文装配与长对话压缩

- **目标**：按确定顺序组合系统提示词、项目规则和历史，并在预算内运行。
- **范围**：全局/祖先/当前目录 `AGENTS.md`、prompt template、token 估算、压缩阈值、摘要阶段（原规划称“摘要节点”；实际嵌入 model 节点）、保留最近 turn 与文件操作事实。
- **非目标**：兼容 Pi 的全部 skills/extensions 格式或精确 token 计费。
- **交付物**：`context/`、上下文快照诊断、压缩与恢复测试。
- **验收标准**：装配顺序可解释；摘要不删除持久化原记录；压缩失败不破坏会话；工具调用边界保持合法。
- **验证命令**：`uv run pytest tests/context tests/integration/test_compaction.py -q --basetemp=.pytest-tmp-m7-acceptance`；`uv run pi-agent context inspect --provider fake`。

归档结果：M7.1–M7.7 与归档修复已完成全局/祖先规则、prompt template、UTF-8 与 token 估算、阈值触发的同步摘要阶段、最近 turn/文件操作事实保留、最终预算门禁和诊断 CLI。摘要阶段在 `model_node` 内通过 `ModelSummarizer` 执行，不新增持久化派生消息；SQLite 测试证明失败后原记录可恢复。真实 provider 与精确计费不属于本轮验收。完整证据与局限见 [M7 归档](docs/acceptance/M7.md)。

### M8 — 模型适配、重试、取消与容错

- **目标**：把 graph runtime 与供应商、鉴权和瞬时故障解耦。
- **范围**：模型工厂（原规划称 `BaseChatModel` 工厂，实际使用项目模型协议）、OpenAI-compatible 首个适配器、环境变量配置、超时、指数退避、错误分类、用量、取消传播、fake/stub 合约测试。
- **非目标**：重写 pi-ai 的完整 provider/OAuth/model catalog。
- **交付物**：`models/`、配置模型、provider contract tests、可选 live smoke 文档。
- **验收标准**：日志不含密钥；不可重试错误立即失败；重试有上限；取消传播到模型和工具。
- **验证命令**：`uv run pytest tests/models tests/runtime -q`；`uv run ruff check .`；`uv run mypy src`。

#### M8 交付与验收边界（已归档）

M8.1–M8.9 的配置、模型适配、工具 schema、同步/异步重试策略、异步模型/上下文、流投影、用量、取消与进程组件、异步 SQLite、Provider 会话入口及离线测试均已交付。实现经过 2026-09-23 全仓验证和 2026-09-24 的离线复验。详细切片过程和历史判定保存在 [整理前快照](docs/history/2026-09-23-m1-m8-review/PLAN.md)，当前实际结果见 [M8 归档](docs/acceptance/M8.md)。

2026-09-23 初次归档时的断点已在 2026-09-24 的 [纠正记录](docs/acceptance/M8-closure.md) 中逐项处理：Provider session 改为 async tool graph，HTTP 发送只读 schema，公开 CLI 可显式使用 compatible provider，模型请求接入 retry/deadline/cancel，命令另走持久提案与人审。真实 provider 4 个 live smoke 和合成只读 CLI 闭环已通过。不能将该结果扩展为 POSIX 实进程树、真实 429 注入、跨资源恰好一次或语义摘要质量通过；余项见 [后续清单](docs/follow-ups/M1-M8.md)。

验证入口：`uv run pytest -q -m 'not live' --basetemp=.pytest-tmp-m8-close`；`uv run mypy src tests`；`uv run ruff check src tests`；`uv run ruff format --check src tests`。真实 smoke 命令、前置条件与脱敏范围见 [README](README.md) 与 [M8 纠正记录](docs/acceptance/M8-closure.md)。


### M9 — 扩展、可观测性与评测

- **目标**：提供受约束扩展点，并能证明行为质量和运行可靠性。
- **范围**：before/after model/tool、run lifecycle hooks；结构化日志、span/metrics；fake 回归集与可选真实模型 eval；敏感字段脱敏。
- **非目标**：执行任意第三方 Python 插件、完整 LangSmith 平台部署。
- **交付物**：hook registry、telemetry adapter、eval harness、基线报告。
- **验收标准**：hook 顺序确定且故障隔离；trace 可关联 thread/run/tool；回归评测可重复；无密钥写入 artifact。
- **验证命令**：`uv run pytest tests/extensions tests/telemetry tests/evals -q`；`uv run pi-agent eval --suite smoke --provider fake`。

#### M9 归档结论

M9.1–M9.6 已交付观察型 hook、Provider/model/tool 生命周期、脱敏 span/metrics/log 接口、lifecycle-to-span adapter、fake eval harness 与 smoke CLI。2026-09-24 用户报告最终组合范围 28 passed、mypy 203 个文件、Ruff lint/format 与 fake eval CLI 通过。归档表示该离线教学范围结案；默认 CLI telemetry、带工具调用的 CLI eval 和可选 live eval 仍按 [M9 归档的未关闭边界](docs/acceptance/M9.md) 跟踪。

### M10 — 远程协议与客户端/服务端

- **目标**：在不污染核心图的前提下支持远程会话。
- **范围**：版本化 DTO、长度限制 framing、认证前置的 transport 接口、权威 session snapshot、request correlation、最小 server/client。
- **非目标**：复刻 Pi CBOR 字节兼容、互联网公开部署、完整 Web/TUI。
- **交付物**：`protocol/`、`server/`、`client/` 与 transport conformance tests。
- **验收标准**：畸形/超大帧被拒绝；断线状态明确；并发请求可关联；服务端快照是唯一权威状态。
- **验证命令**：`uv run pytest tests/protocol tests/server tests/client -q`；`uv run pi-agent-server --help`。

### M11 — 全链路验收与架构复盘

- **目标**：交付可运行、可测试、可扩展的 Python Agent，并完成“从点回到面”。
- **范围**：全量测试、Windows/Linux smoke、文档、威胁模型、性能基线；最终请求链路、模块边界、Pi 差异和陌生 Agent 分析清单。
- **非目标**：隐藏未完成项或以 mock 代替声明的真实验收。
- **交付物**：README、架构文档、验收矩阵、生产差距清单、源码分析与架构检查清单。
- **验收标准**：M1-M9 全部通过；M10 若未启用则明确标为可选；新环境可按文档完成安装和 smoke；所有已知风险有 owner/下一步。
- **验证命令**：`uv sync --all-extras`；`uv run ruff check .`；`uv run ruff format --check .`；`uv run mypy src`；`uv run pytest --cov=pi_agent --cov-report=term-missing`；`uv run pi-agent --provider fake --prompt "inspect this workspace"`。

## 6. 范围接口与执行规则

- M3 定义工具循环；M4 定义文件/进程安全能力；M5 定义事件和 CLI 消费。组件分别通过测试不等于 CLI 已连通所有工具。
- M4 的 InMemorySaver 只支持审批教学测试；M6 才负责持久化会话、跨进程恢复和分支。
- M5 的 SIGINT/token 是同步消费侧协作取消，并已验证迭代器资源释放；M8 的 provider/tool 异步取消传播仍属于运行时能力。
- M7/M8 已归档；M8-R2-A 真实普通回复已通过一次，R2-D–R2-F 的真实 streaming/resume/summary smoke 与端到端接线仍待显式执行，继续记录在 M8 验收和后续清单中。
- 每个里程碑坚持“整体请求 → 当前切片 → Pi 设计与 Python 映射 → 一个练习 → 回到整体”；学习者优先实现有价值的核心代码，明确委托助手代写的切片单独记录。
- 修改范围或验收口径时保留原要求，明确已实现部分和未覆盖部分；不可通过搬移文档隐去缺口。
- 里程碑编号 M0–M11 固定。M5 内的十一道练习属于子切片，不是十一项新里程碑。
- PLAN 不再追加每轮测试流水；最新快照更新原段落，详细证据放到对应验收文件。历史“下一步”和预期红灯仅保存在历史快照。

## 7. 本次复验与记录维护

2026-09-23 M8 归档前复验：全仓 pytest `403 passed, 4 skipped`，4 项均为未启用 `PI_AGENT_LIVE=1` 的预期 live gate；mypy 检查 179 个源文件；Ruff lint 与 200 个文件格式检查通过；fake JSONL CLI 与 context inspect smoke 退出码均为 0。真实普通回复已有一次用户执行的 1 passed 证据，新增 streaming/resume/summary live smoke 尚未执行。2026-09-24 文档审计复验：离线 `403 passed, 4 deselected`，mypy/Ruff/format 通过；见 [审计](docs/reviews/M1-M8-audit.md)。

2026-09-22 M7 归档复验：全仓 pytest `217 passed`；M7 原计划范围 `56 passed`；mypy 108 个文件；Ruff lint 与 124 个文件格式检查通过；context inspect 与 fake JSONL CLI smoke 退出码均为 0。原始文档保留在 [M7 归档前快照](docs/history/2026-09-22-before-m7-archive/README.md)。

2026-09-21 M5 复验：全仓 pytest `123 passed`；M5 范围 `47 passed`（排除 M4 HITL 集成）；mypy 检查 68 个文件；Ruff lint 通过、92 个文件格式通过；text/jsonl CLI smoke 均通过。

2026-09-21 M6 归档复验：全仓 pytest `158 passed`；mypy 检查 86 个文件；Ruff lint 通过、101 个文件格式通过；`pi-agent session list --database ...` console smoke 退出码为 0。M6 的应用边界与未覆盖的生产能力见 [M6 归档](docs/acceptance/M6.md)。

```powershell
uv run pytest -q --basetemp=.pytest-tmp
uv run mypy src tests
uv run ruff check .
uv run ruff format --check .
$milestoneCount = (Select-String -Path PLAN.md -Pattern '\|\s+in_progress\s+\|').Count
if ($milestoneCount -gt 1) { throw "More than one milestone is in_progress" }
```

M5 整理前全文保存在 [历史快照](docs/history/2026-09-18-before-m5-archive/README.md)，M7 原文保存在 [M7 归档前快照](docs/history/2026-09-22-before-m7-archive/README.md)。Pi 源码分析继续沿用 M0 固定基线；M7 归档复核了 LangGraph 官方历史管理说明，未变更框架依赖。
