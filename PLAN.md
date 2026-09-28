# Python Pi Agent（LangGraph）执行计划

## 1. 当前状态与文档分工

- 初始规划：2026-09-02；M5 初次归档：2026-09-18；M5 遗留项复验、M6 实现与归档：2026-09-21（Asia/Shanghai）。
- M0–M8 已按各自交付范围归档。M8 于 2026-09-23（Asia/Shanghai）首次归档；2026-09-24 补齐真实 Provider CLI 只读闭环、重试/时限、命令人审入口，并在配置的 compatible 服务完成 4 个 live smoke 与合成文件 CLI 工具调用。初次归档与后续复验分列于 [M8](docs/acceptance/M8.md)、[纠正记录](docs/acceptance/M8-closure.md)。M8.3/M8.4 及 R2-D–R2-F 由助手代写，学习者复盘另行进行。
- M9 于 2026-09-24 启动、完成已交付范围并归档。用户报告最终组合测试 **28 passed**、mypy **203 source files**、Ruff lint/format 与 fake eval CLI 通过；默认 CLI telemetry、带工具调用的 CLI eval 和可选 live eval 的边界见 [M9 归档](docs/acceptance/M9.md)。
- M10 于 2026-09-24 按用户要求启动；2026-09-28 完成全部切片和归档复验，并按用户本轮授权归档已交付的离线本机范围。验收证据、非目标和未关闭边界见 [M10 归档](docs/acceptance/M10.md)。
- M5 同步取消与 M8 异步组件、主请求取消接线已分别验证；真实传输中取消、429 故障注入和跨平台进程树仍按 [剩余清单](docs/follow-ups/M1-M8.md) 单列，不扩大现有 smoke 结论。

| 文件 | 唯一职责 |
|---|---|
| PROJECT_SPEC.md | 项目目标与教学方式 |
| PLAN.md | 当前状态、里程碑范围、验收要求、阶段接口 |
| LEARNING_LOG.md | 学习者基础、按里程碑总结、关键决策、问题索引 |
| docs/acceptance/Mx.md | 对应里程碑的验收命令、结果、局限和归档结论 |
| docs/README.md | M1–M10 文档索引；审计、总结与后续任务入口 |
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
| M10 | 远程协议与客户端/服务端 | completed | 已选择的可选扩展 | [M10 归档](docs/acceptance/M10.md)，2026-09-28 离线本机范围验收；[设计](docs/design/M10.md) |
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
  protocol/      # M10 计划新增：帧、版本化 DTO、严格编解码
  server/        # M10 计划新增：认证、会话协调、请求派发、TCP 入口
  client/        # M10 计划新增：连接、请求关联、快照缓存
tests/           # 与 src 镜像
docs/acceptance/ # 每个里程碑的验收记录
```

## 5. 里程碑契约

每项固定保留目标、范围、非目标、交付物、验收标准、验证命令。已完成项的事实与局限见归档；M10 已启动规划，M10–M11 尚未创建的目录或入口对应命令仍为未来验收目标，不能当作已经执行或通过。

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

#### M10 执行边界与分片顺序

以下逐片实际结果保留各片完成当时的状态；M10 当前归档结论以 [验收记录](docs/acceptance/M10.md) 和本页里程碑总表为准。

贯穿场景：客户端认证并建立协议连接 → 创建会话 S → 提交“请读取 probe.txt 并总结” → 服务端进入已有 async tool graph → 客户端看到带请求/run 标识的事件与最终快照 → 客户端重连，读取 S 的服务端快照并续聊。失败变式贯穿各片：报文被拆开、未认证、同会话并发、回复前断线、取消和服务端重启。

首版采用单服务进程、单信任主体、服务端固定 workspace/database/model 的本机 TCP；四字节大端长度前缀加 UTF-8 JSON。认证在协议核心之前完成；协议 v1 只公开 `create_session / get_snapshot / prompt / cancel`。远程会话仅注册 read/list/search，命令提案与审批、文件写入、多租户、公网/TLS 部署、自动重放、后台脱离连接运行、Pi CBOR 字节兼容均不在 M10 内。具体限制与失败语义见 [设计决策](docs/design/M10.md#c-首版契约与边界)。

分片制定时先只落地计划。随后每片先讲全链路和 Pi 对应设计，再提供脚手架、测试和一个学习者核心 TODO；审查通过后回到同一请求链路。下表保留分片依据与最终状态，不表示曾同时布置八项作业。

| 切片 | 解决的链路断点 | 依赖 | 状态 | 学习者核心点 |
|---|---|---|---|---|
| M10.1 | 字节流无法确定消息边界 | 无 | completed | `FrameDecoder.feed()` 与 24 项聚焦测试通过 |
| M10.2 | 完整 payload 尚不可信 | M10.1 | completed | 学习者实现 `decode_client_message()`；62 项 protocol 测试与静态门禁通过 |
| M10.3 | 未认证连接可能进入业务 | M10.2 | completed | 认证 gate 与 asyncio transport 全部验证通过 |
| M10.4 | 会话装配仍依赖 CLI | M10.2 | completed | 71 项切片/回归测试与静态门禁通过 |
| M10.5 | 并发与取消缺少单一所有者 | M10.4 | completed | 7 项聚焦测试与统一静态门禁通过 |
| M10.6 | 连接尚未接入会话操作 | M10.3、M10.5 | completed | 学习者完成 `dispatch_message()` 路由；104 项协议/服务端测试与静态门禁通过 |
| M10.7 | 客户端无法可靠关联响应/状态 | M10.6 | completed | pending response 按 request ID/command 恰好一次结算；客户端权威快照/断连语义通过验证 |
| M10.8 | 组件尚未形成公开可运行入口 | M10.7 | completed | server/client 公开入口、transport conformance、合成工具/SQLite 子进程 smoke、四命令 client CLI 分派通过；已纳入 M10 归档 |

##### M10.1 — 有界增量帧解码

- **目标**：把任意拆分/合并的网络字节块还原为完整 payload。
- **范围**：新增 `src/pi_agent/protocol/framing.py`、`errors.py`、`__init__.py` 和 `tests/protocol/test_framing.py`；实现四字节长度、上限、EOF 与失败终态。
- **非目标**：JSON、认证、socket、模型或数据库调用。
- **交付物**：长度前缀编码器、增量解码器、结束/失败清理和契约测试；完整设计与实现复盘见 [首片记录](docs/design/M10.md#d-首片练习与实现复盘)。
- **验收标准**：拆头/拆正文、逐字节输入、粘包、恰好上限均正确；零长度/超限在完整头部到达时立即拒绝；截断 EOF 报错；失败后不继续解码；只缓存尚未完成的一帧。
- **验证命令**：`uv run pytest tests/protocol/test_framing.py -q --basetemp=.pytest-tmp-m101`；本节末尾统一静态门禁。

##### M10.2 — 版本化 DTO 与严格 codec

- **目标**：完整字节 payload 通过校验后才成为业务请求。
- **范围**：新增 `protocol/messages.py`、`codec.py`；扩展 `protocol/errors.py`；新增 `tests/protocol/test_messages.py`、`test_codec.py`。定义 hello、request、response、event、snapshot 与四个命令。
- **非目标**：接受任意对象字段、复用 LangGraph StateSnapshot 作为 wire DTO、Pi 的完整命令集合。
- **交付物**：严格 Pydantic DTO、入站/出站编码、稳定安全错误；学习者只实现 `decode_client_message(payload: bytes) -> ClientMessage`，其余 DTO、严格 JSON 载入和服务端解析由脚手架提供。完整调用链、输入样例和测试意图见 [M10.2 练习](docs/design/M10.md#e-m102-切片与练习复盘)。
- **验收标准**：非法 UTF-8/JSON、重复 JSON key、非有限数、额外字段、错误类型/方向均拒绝；版本不能从字符串或 bool 强转；未知整数版本可解析为 hello 再由握手报告 `unsupported_version`；出站同样受限；错误不回显原文或校验异常详情。
- **验证命令**：`uv run pytest tests/protocol -q --basetemp=.pytest-tmp-m102`；统一静态门禁。

实际结果（2026-09-24，completed）：学习者完成 `decode_client_message()`，按先安全 JSON loader、后 client 专用严格 TypeAdapter 的顺序校验；未知非负整数版本留待握手判断，客户端方向错误和额外字段由 DTO 拒绝，错误保持固定安全文案。`uv run pytest tests/protocol -q --basetemp=.pytest-tmp-m102` 为 **62 passed**；`uv run mypy src tests` 检查 211 个文件通过；`uv run ruff check .` 通过；`uv run ruff format --check .` 检查 252 个文件通过。此前 50 passed/12 TODO failures 是练习脚手架阶段结果，已由此次全绿复验取代。贯穿请求现在从 M10.1 完整帧进入可信 client DTO；认证和派发仍未发生。

##### M10.3 — 认证前置的字节连接

- **目标**：让协议核心只接收到已认证、有序、有界的连接。
- **范围**：新增 `protocol/transport.py`、`server/auth.py`、`server/transports/tcp.py`、`client/transport.py`；新增 `tests/server/test_auth.py`、`test_tcp_transport.py`、`tests/client/test_transport.py`。
- **非目标**：公网监听、TLS/OAuth 平台、多用户授权、把鉴权 token 塞入 AgentState。
- **交付物**：AsyncByteConnection 端口、asyncio TCP 适配、独立认证前导帧、单 reader/串行 writer、发送与关闭时限；学习者实现认证 gate，业务 accept 回调由助手脚手架注入。完整链路和练习见 [M10.3 说明](docs/design/M10.md#g-m103-当前切片与学习者练习)。
- **验收标准**：缺失/错误凭据、认证超时、超限 auth 帧均使业务调用次数为零；认证与 hello 同包也不丢后续字节；并行写无帧交错；慢读端在预算内关闭；重复关闭安全；默认与显式非法监听地址均受限制。
- **验证命令**：`uv run pytest tests/server/test_auth.py tests/server/test_tcp_transport.py tests/client/test_transport.py -q --basetemp=.pytest-tmp-m103`；统一静态门禁。

实际结果（2026-09-24，completed）：学习者实现 `authenticate_connection()`，在单一 deadline 内以 `readexactly()` 读取有界认证前导，并以常量时间比较 token；完整切片命令 **16 passed**，mypy 检查 **221 source files** 通过，Ruff lint 通过，format 检查 **262 files** 通过。此前 Ruff 报告的全角标点问题已修复并重跑。用户报告的 `tests/server` 子集为 14 passed；切片完整 client/server transport 测试另为 16 passed。认证和 hello 同批到达仍保留在同一个 reader 缓冲中；M10.3 完成后请求只到认证 byte connection，尚无握手派发。

##### M10.4 — 可复用的会话运行边界与快照

- **目标**：同一 async graph/session 能由 CLI 和服务端调用，服务端输出框架无关快照。
- **范围**：新增 `runtime/session.py`、`runtime/read_only.py`、`server/runtime.py`、`server/snapshots.py`；把 `cli/runtime.py`、`cli/read_only.py` 的公共装配/过滤移到上述运行边界并保留 CLI 薄包装；必要时给 `sessions/async_runtime.py` 增加读取接口。新增 `tests/server/test_runtime.py`、`test_snapshots.py`。
- **非目标**：改写 model/tools 图算法、改变既有 CLI 行为、让 client 选择服务端路径/凭据、远程副作用工具。
- **交付物**：非 CLI options 的运行配置、注入 model/hooks/run_id/cancellation 的接口、checkpoint 读取与安全事件/快照投影；学习者完成 `project_session_snapshot(...) -> SessionSnapshot` 的状态/消息白名单映射。
- **验收标准**：fake 模型完成真实临时文件 read → ToolMessage → 回复；SQLite 重开能读同一会话；敏感路径过滤和 M9 hook 关联保留；原始 checkpoint/config/provider metadata 不出网；长历史按展示预算显式截断；部分 checkpoint 不伪装完成；server 不导入 `pi_agent.cli`。
- **验证命令**：`uv run pytest tests/server/test_runtime.py tests/server/test_snapshots.py tests/cli tests/sessions tests/integration/test_provider_lifecycle.py tests/integration/test_telemetry_lifecycle.py -q --basetemp=.pytest-tmp-m104`；统一静态门禁。

##### M10.5 — 会话并发、运行所有权与取消

- **目标**：为每个运行确定领取者、取消者和最终清理责任。
- **范围**：新增 `server/sessions.py`，必要时扩展 `server/runtime.py`；新增 `tests/server/test_sessions.py`、`test_cancellation.py`。本片由 coordinator 维护 active run，并将同 session 并发限制为 1，不写入图业务状态。server epoch/revision 字段由 M10.4 runtime/snapshot 边界承载；全局连接数、活动 run 和在途请求上限由 M10.6 dispatcher/connection 执行（见资源预算表）。
- **非目标**：分布式租约、跨进程 exactly-once、取消后自动恢复未完成工具批次、无限队列。
- **交付物**：按 session 原子领取、冲突立即 `busy`、不同会话可并发、精确 run_id 取消与 join、断线取消所有者的运行；学习者实现 `try_claim_run(...) -> RunLease` 的领取/冲突契约。
- **验收标准**：同 S 两个 prompt 仅一个调用模型；不同 S 不互相串状态；旧 run_id 不能取消新 run；cancel 不等待 prompt 完成才被派发；清理后才能释放 busy；清理超时保持不可重用；重启遇到 pending checkpoint 返回 `needs_recovery`，不自动重放。
- **验证命令**：`uv run pytest tests/server/test_sessions.py tests/server/test_cancellation.py -q --basetemp=.pytest-tmp-m105`；统一静态门禁。

##### M10.6 — 服务端协议派发

- **目标**：连通已认证连接、版本握手、四个命令和已有会话运行器。
- **范围**：新增 `server/connection.py`、`server/dispatcher.py`；新增 `tests/server/test_dispatcher.py`、`test_protocol.py`。分离接收循环与运行 task，统一 response/event writer。
- **非目标**：新增业务图节点、广播订阅体系、自动重试 prompt、完整 Pi attach/steer/lease API。
- **交付物**：`awaiting_hello → ready → closing → closed` 状态机、request ID/command 回填、事件关联和错误映射；学习者实现 `dispatch_message(...)` 的状态门禁与路由。
- **验收标准**：握手前业务、重复 hello、未知版本、重复请求 ID、超并发均拒绝；两个请求可乱序完成但 ID 不串；prompt 只有一个最终 response，事件不重复终态；连接关闭后禁止发送/启动任务；模型失败和协议错误可区分。
- **验证命令**：`uv run pytest tests/protocol tests/server -q --basetemp=.pytest-tmp-m106`；统一静态门禁。

M10.6 实际结果（completed，2026-09-28，等待用户验收）：学习者实现 `ServerDispatcher.dispatch_message()`，把四种命令路由至 `ServerCommandService`，保持 request ID/command 关联，转发 prompt 的 `run_started` 事件，并将已知安全错误和意外错误映射为不泄漏内部细节的 response。代码审查发现断开清理期间可能有第二个在途 prompt 在 owned-run 快照后才注册；连接进入 closing 后，event callback 现以取消拒绝继续启动该运行，并以竞态测试覆盖。最终计划命令 `uv run pytest tests/protocol tests/server -q --basetemp=.pytest-tmp-m106` **104 passed**；`uv run mypy src tests` 检查 **234 source files** 通过；`uv run ruff check .` 通过；`uv run ruff format --check .` 检查 **275 files** 通过。结果证明协议/服务端切片，不代表 M10 客户端、公开入口或端到端验收已经完成。用户随后授权进入 M10.7。

##### M10.7 — 最小客户端与权威快照

- **目标**：客户端可靠完成请求、展示进展，并在断线/重连时承认结果未知。
- **范围**：新增 `client/connection.py`、`client/client.py`、`client/state.py`、`client/errors.py`；新增 `tests/client/test_connection.py`、`test_requests.py`、`test_state.py`。
- **非目标**：客户端自行拼接权威 transcript、自动重放请求、用最后一个 token 判定成功、共享/exclusive lease 全量兼容。
- **交付物**：一个接收循环、pending future 表、请求 deadline、四个 public async 方法、快照缓存；学习者实现 `resolve_response(...)`，按 ID/command 对 pending future 完成一次。
- **验收标准**：乱序响应正确分发；未知/重复响应和 command 不匹配显式失败；断线清空 pending 并标记旧快照 stale；请求超时关闭连接并让未完成请求报告结果未知；重连更换 connection epoch，忽略旧连接事件；新 server epoch 重置 revision 比较；同 epoch 旧快照不能覆盖新快照。
- **验证命令**：`uv run pytest tests/client -q --basetemp=.pytest-tmp-m107`；统一静态门禁。

M10.7 实际结果（completed，2026-09-28，等待用户验收）：学习者实现 `RemoteClient.resolve_response(response, *, connection_generation)`，旧连接代次响应被忽略；pending 依 request ID 恰好取出并核对 command；未知/重复 ID 和 command mismatch 使当前连接以协议错误关闭；安全服务端错误映射为 `ServerRejectedError`；成功响应应用权威快照并完成 Future。用户执行 `uv run pytest tests/client -q --basetemp=.pytest-tmp-m107-final` **17 passed**；复核 `uv run pytest tests/client -q --basetemp=.pytest-tmp-m107-review` **17 passed**；`uv run pytest tests/protocol -q --basetemp=.pytest-tmp-m107-review-protocol` **63 passed**；`uv run mypy src tests` **241 source files** 通过；`uv run ruff check .`、`uv run ruff format --check .`（282 files）和 `git diff --check` 通过。M10.2 的 strict tuple DTO 与 JSON array round-trip 边界已在 validator 做 list→tuple 归一化并由协议回归覆盖。本结果证明 client/protocol 切片，不代表 M10 公开入口、真实 TCP 组合或跨进程 exactly-once 已验收；下一片 M10.8 尚未启动。

##### M10.8 — 公开入口与组合验收

- **目标**：从公开入口证明“认证 → 请求 → 工具 → 持久化 → 客户端 → 重连”的完整链路。
- **范围**：新增 `server/app.py`、`client/app.py`、`tests/server/test_app.py`、`tests/client/test_app.py`、`tests/server/test_conformance.py`、`tests/server/test_subprocess_smoke.py`；修改 `pyproject.toml` 注册 `pi-agent-server` 与 `pi-agent-client`，更新 `README.md`、`.env.example` 配置名、`docs/README.md`；创建 `docs/acceptance/M10.md`。
- **非目标**：真实模型质量验收、外网部署、替 M8/M9 关闭原有遗留项、进入 M11。
- **交付物**：默认 fake、显式 compatible 的 server；最小 create/snapshot/prompt/cancel client CLI；内存 transport 与本机 TCP 共用 conformance 案例；fake 工具场景 fixture 与独立子进程 smoke；验收记录。
- **验收标准**：合成 workspace 中完成 read/续聊；服务端重启后同 session 可查且已完成轮次不重跑；运行中断线、cancel/完成竞态、错误 token/版本/帧、同 session 并发、慢消费者和停机都闭合；日志无密钥/正文；原有 CLI/hook 回归通过。server shutdown 必须退出，残留 task/资源算失败。
- **验证命令**：执行下面的最终门禁；记录退出码与实际结果；失败先修复，不把 localhost socket、子进程或关键失败用例设为 skip。

M10.8 实际结果（completed，2026-09-28）：学习者完成 `client/app.py::dispatch_command()`，将 create/snapshot/prompt/cancel 映射到 M10.7 的 `RemoteClient` API。归档审查补齐完成/取消竞态、服务端进程日志的 token/正文断言，以及 TCP listener/handler 关闭超时不能静默成功的契约。最终 M10 组合 **133 passed**、全仓非 live 回归 **565 passed、4 deselected**；`uv sync --all-extras`、server/client help、mypy（247 source files）、Ruff lint、format（289 files）、fake JSONL CLI、fake eval smoke 和 `git diff --check` 均通过。pytest cache 有权限警告，不影响测试；4 deselected 为 live 标记范围。完整命令、验收映射和归档边界见 [M10 归档](docs/acceptance/M10.md)。

每片统一静态门禁（实现后执行，uv 命令顺序运行）：

```powershell
uv run mypy src tests
uv run ruff check .
uv run ruff format --check .
```

M10 最终门禁保留原计划两条命令，并增加完整回归与公开入口 smoke：

```powershell
uv sync --all-extras
uv run pytest tests/protocol tests/server tests/client -q
uv run pi-agent-server --help
uv run pi-agent-client --help
uv run mypy src tests
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -m "not live" --basetemp=.pytest-tmp-m10-regression
uv run pi-agent --provider fake --prompt hello --events jsonl
uv run pi-agent eval --suite smoke --provider fake
```

子进程 smoke 放在原计划测试目录内，由 `test_subprocess_smoke.py` 自动选择空闲端口、创建合成临时工作区/数据库、通过环境注入合成 token、启动两个真实入口并在 finally 关闭进程；不靠手工启动后遗留服务。真实 compatible 服务仅在明确启用时做补充验证，不作为 M10 离线可复现验收的替代。

阶段计划依据：固定提交源码和本地接口核对形成 M10.1–M10.8 分片，各片计划验证已完成。用户于 2026-09-28 授权在满足条件时立即归档；归档审查和复验通过后，M10 已交付离线本机范围归档。M11 仍为 pending，不自动启动。

M10.4 于 2026-09-28 完成。共享 async session runtime、只读工具装配和 allowlist snapshot projection 已实现；检查发现 CLI 命令提案分支重复注册 `propose_command`，已修复并增加回归测试。完整验证命令 `uv run pytest tests/server/test_runtime.py tests/server/test_snapshots.py tests/cli tests/sessions tests/integration/test_provider_lifecycle.py tests/integration/test_telemetry_lifecycle.py -q --basetemp=.pytest-tmp-m104` **71 passed**；`uv run mypy src tests` 检查 **227 source files** 通过；`uv run ruff check .` 通过；`uv run ruff format --check .` 检查 **268 files** 通过。另增加 server runtime hook thread/run correlation 断言。server/runtime 没有 `pi_agent.cli` import；快照只投影允许字段并执行 per-message/overall 预算。

M10.5 于 2026-09-28 完成。学习者实现 `SessionCoordinator.try_claim_run()` 后，计划命令 `uv run pytest tests/server/test_sessions.py tests/server/test_cancellation.py -q --basetemp=.pytest-tmp-m105` **7 passed**；`uv run mypy src tests` 检查 **230 source files** 通过；`uv run ruff check .` 通过；`uv run ruff format --check .` 检查 **271 files** 通过。首次复验发现实现注释中的全角标点和格式问题，修复后四项计划验证重跑全绿。用户另报告 `uv run pytest tests/server -q --basetemp=.pytest-tmp-m102` **26 passed**。同 session 冲突、独立 session、完成后释放、精确 run_id 取消/join、清理超时期间保持 busy 和 pending checkpoint 恢复均由测试覆盖。M10.6 进度见下节。

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
$milestoneCount = (Select-String -Path PLAN.md -Pattern '^\|\s+M\d+\s+\|.*\|\s+in_progress\s+\|').Count
if ($milestoneCount -gt 1) { throw "More than one milestone is in_progress" }
```

M5 整理前全文保存在 [历史快照](docs/history/2026-09-18-before-m5-archive/README.md)，M7 原文保存在 [M7 归档前快照](docs/history/2026-09-22-before-m7-archive/README.md)。Pi 源码分析继续沿用 M0 固定基线；M7 归档复核了 LangGraph 官方历史管理说明，未变更框架依赖。
