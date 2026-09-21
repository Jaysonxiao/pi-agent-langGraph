# Python Pi Agent（LangGraph）执行计划

## 1. 规划基线

- 初始规划日期：2026-09-02
- 最近复核日期：2026-09-18
- 上游仓库：`earendil-works/pi`
- 分支与提交：`main` @ `96317e50b8d6e7f6d0e47fd29122baf1461c00f5`
- 上游版本：核心包 `0.84.4`
- Python：3.11+
- LangGraph：2026-09-16 复核 PyPI 当前稳定版仍为 `1.2.11`；实现使用 `>=1.2,<1.3`，仅在依赖变更或相关 API 有变化风险时重新核对。
- 本地现状：M1-M4 已完成；M5 的事件投影、JSONL、纯文本 renderer、fake CLI、cooperative cancellation、SIGINT handler、终态过滤与最终 CLI 接线均已完成；当前等待 M5 最终确认/归档；当前目录尚无有效 Git 元数据。
- 当前验证基线：M5 最终接线后全仓 pytest `116 passed`、全仓 mypy 检查 67 个文件无问题、Ruff lint/format 通过；text CLI smoke 已输出 message + completed state 两行。M5 仍保持 `in_progress`，未自动归档。
- 上游复核：2026-09-16 确认 GitHub 默认分支仍为 `main`，当前 README/package 仍保持 ai → agent → coding-agent 的核心分层，并新增/强化 chord、telemetry、session backend、protocol/client/server 等外围包。为避免把持续变化的 `main` 与已实现代码混用，源码事实继续固定在下述 commit；只有显式重设基线时才迁移。

状态只允许 `pending`、`in_progress`、`completed`、`blocked`。任何时刻最多一个里程碑为 `in_progress`；本次复核不自动进入下一里程碑或启动新的实现切片。

| 里程碑 | 名称 | 状态 | 阶段 |
|---|---|---|---|
| M0 | 源码分析与路线设计 | completed | 总览 |
| M1 | Python 工程骨架 | completed | MVP |
| M2 | 消息、状态与最小图 | completed | MVP |
| M3 | Tool Calling 闭环 | completed | MVP |
| M4 | 安全 Coding Tools 与人工审批 | completed | MVP |
| M5 | 流式事件与 CLI 闭环 | in_progress | MVP |
| M6 | 会话持久化、恢复与分支 | pending | MVP |
| M7 | 上下文装配与长对话压缩 | pending | 增强 |
| M8 | 模型适配、重试、取消与容错 | pending | 增强 |
| M9 | 扩展、可观测性与评测 | pending | 生产化 |
| M10 | 远程协议与客户端/服务端 | pending | 可选扩展 |
| M11 | 全链路验收与架构复盘 | pending | 收束 |

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
| `AgentEvent` / streaming | `astream()` 的 messages/updates/custom 投影 + 自有稳定事件 DTO |
| steer/follow-up | 应用层输入队列；图只消费已提交的下一批输入 |
| JSONL session tree | LangGraph checkpointer + 独立 session 元数据仓储 |
| branch/restore | `get_state_history()`、checkpoint config、`update_state()` |
| compaction/transformContext | model 节点前的上下文策略节点，不修改完整审计记录 |
| extension hooks | 图外 middleware/hook registry；需要路由时返回 `Command` |
| pi-ai providers | `BaseChatModel` 适配器；不重写全部供应商 SDK |
| remote protocol/TUI | MVP 后独立适配层，不进入图的领域核心 |

优先级：必须掌握状态/reducer、节点与路由、工具循环、streaming、checkpoint、错误与测试；需要理解上下文压缩、provider 边界、hooks、telemetry；暂时了解远程协议、TUI、模型评测；第一版忽略完整 provider/OAuth 目录、图像能力、二进制发布、全量 Pi 扩展兼容。

## 4. 目标目录

```text
src/pi_agent/
  domain/        # 消息、状态、事件、错误
  graph/         # graph builder、nodes、routing
  tools/         # registry、安全策略与 Coding Tools
  models/        # BaseChatModel 适配器与 fake
  sessions/      # checkpoint 与 session 元数据
  context/       # AGENTS/skills/prompt/compaction
  runtime/       # orchestration、hooks、取消、重试
  telemetry/     # tracing contracts/adapters
  cli/           # 命令与渲染
tests/           # 与 src 镜像
docs/acceptance/ # 每个里程碑的验收记录
```

## 5. 里程碑

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
- **实际结果（2026-09-03，2026-09-04 验收归档）**：学习者完成 `model_node`，成功路径只返回 assistant 消息增量，失败路径保留历史并写入结构化 `ModelError`；计划规定的测试为 `8 passed`，目标 mypy 检查 7 个源码文件无问题。附加仓库门禁 `ruff check`、`ruff format --check`、`mypy src tests` 和完整 pytest（`9 passed`）全部通过。M2 的系统位置、Pi 映射、必须掌握知识、常见错误、理解问题与答案已归档到 `docs/acceptance/M2.md`，用户确认理解并批准进入 M3。

### M3 — Tool Calling 闭环

- **目标**：实现 model → tools → model 的受控循环。
- **范围**：tool registry、Pydantic 参数校验、未知工具/执行异常转 `ToolMessage`、条件路由、最大轮次、并行能力的明确策略、fake tools。
- **非目标**：访问真实文件或启动进程。
- **交付物**：工具节点、路由函数、tool call 事件和确定性测试。
- **验收标准**：成功、非法参数、未知工具、异常、达到轮次上限均有稳定终态；tool call 与 result ID 一致。
- **验证命令**：`uv run pytest tests/tools/test_registry.py tests/graph/test_tool_loop.py -q`；`uv run ruff check src/pi_agent/graph src/pi_agent/tools`。
- **进入记录（2026-09-04）**：M2 已由用户验收并完成学习归档，M3 成为唯一 `in_progress` 里程碑。贯穿场景为“模型请求 `add(left=2, right=3)`，工具结果以同一 call ID 回灌，模型再生成最终答复”；首个学习者练习限定为 `ToolRegistry.execute_call()` 的注册查找、Pydantic 校验、执行与错误 `ToolMessage` 归一化。
- **脚手架结果（2026-09-04）**：已建立 typed tool definition、runtime registry、严格 fake add tool、scripted model、工具/上限节点、条件回路与确定性测试。M2 回归为 `8 passed`，全仓 Ruff/mypy/format 通过；M3 目标测试为预期的 `3 passed, 5 failed`，五个失败全部指向唯一学习者 TODO，不能作为 M3 最终验收结果。
- **实际结果（2026-09-11）**：学习者完成 `ToolRegistry.execute_call()` 并报告目标测试 `8 passed`、目标 Ruff 通过。审查保留其四分支实现和确定性消息 ID 思路，同时用 `ToolArgumentError` 分离 schema 校验失败与 handler 内部 `ValidationError`，将消息 ID 命名空间化为 `tool-result:{call_id}`，并补齐三类错误回灌和多调用源码顺序的图级证据。计划 pytest 最终为 `13 passed`，目标 Ruff 通过；全仓 Ruff/format/mypy 通过，完整 pytest 为 `22 passed`。

### M4 — 安全 Coding Tools 与人工审批

- **目标**：提供可实际工作的文件/搜索/修改/命令工具，并把安全边界作为产品能力。
- **范围**：read/list/search、edit/write、受控 subprocess；工作区 realpath 校验、symlink/路径穿越防护、输出限制、超时/取消、危险命令策略；写入和高风险命令用 `interrupt()` + `Command(resume=...)` 审批。
- **非目标**：容器隔离、任意主机 shell、网络工具。
- **交付物**：工具适配器、安全策略、审批 DTO、临时工作区集成测试。
- **验收标准**：无法越过允许根目录；默认拒绝高风险操作；超时会终止进程树；拒绝/批准均可恢复。
- **验证命令**：`uv run pytest tests/tools tests/security tests/integration/test_hitl.py -q`；`uv run ruff check .`。
- **进入记录（2026-09-11）**：用户完成 M3 理解检查并明确批准打开 M4，因此 M3 验收通过，M4 成为唯一 `in_progress` 里程碑。整体链路为 `tool call -> schema -> security policy -> optional approval -> filesystem/process -> bounded ToolMessage`；首个纵向切片固定为工作区内 read 成功与路径穿越/symlink 逃逸在读取前失败。
- **首个学习练习（2026-09-11）**：已建立 `WorkspacePathPolicy`、稳定错误契约和安全测试；学习者只实现 `resolve()`，掌握 canonical path、目录成员关系以及读取/写入存在性差异。完成并审查此门禁后，才在 M4 内继续具体 read/list/search、edit/write、受控进程和 HITL，不提前进入 M5。
- **路径门禁结果（2026-09-14）**：学习者实现相对/绝对路径解析、空值防护、canonical containment、缺失目标和 junction 逃逸处理；首次 11 项通过。审查补充非“缺失”类解析错误测试后，学习者将 `FileNotFoundError` 与其他 `OSError/RuntimeError` 分层，最终路径测试 `12 passed`。连同 M3 registry/图回归共 `25 passed`，目标 mypy、Ruff lint/format 全部通过。M4 仍为 `in_progress`，下一切片是让 read/list/search 复用该门禁与统一输出预算。
- **只读工具切片（2026-09-14）**：贯穿请求为“列出项目、搜索 `LangGraph`、读取 README 命中窗口”。脚手架将 list/search/read 组合到既有 `ToolDefinition`/registry 和 `WorkspacePathPolicy`，并提供稳定排序、UTF-8 文本、扫描/匹配上限及失败测试；本次唯一学习 TODO 是三个工具共用的 `TextOutputBudget.apply()`，按整行、行数与 UTF-8 字节数限制模型可见输出。
- **只读工具脚手架结果（2026-09-14）**：目标 Ruff lint、9 个文件格式检查和 mypy 均通过；既有路径门禁、registry、工具循环回归为 `25 passed`。新切片测试为预期的 `3 passed, 9 failed`，九个失败全部指向唯一 `TextOutputBudget.apply()` TODO。list 的条目类型使用 `lstat`/reparse metadata，避免为了分类而跟随 Windows junction。
- **只读工具完成结果（2026-09-14，2026-09-16 复验）**：学习者完成 `TextOutputBudget.apply()`；实现按 UTF-8 字节数和行数取最大完整行前缀，不切分 Unicode 字符或行，并显式报告首行超预算。计划中的只读工具测试为 `12 passed`，目标 mypy、全仓 Ruff lint/format 均通过；2026-09-16 全仓 pytest 为 `46 passed`。M4 仍为 `in_progress`，下一切片是 edit/write 的变更契约与副作用前审批，随后才进入受控进程和最终 HITL 集成验收。
- **edit/write 准备切片（2026-09-16）**：采用 `prepare -> approve -> apply` 三段式链路。本切片先建立无副作用的 `FileChangePlanner`、write/edit 参数模型、稳定变更错误和版本摘要；学习者唯一 TODO 是 `apply_exact_replacement()`，要求零匹配、多匹配（含重叠）、空目标和 no-op 在审批前失败，并原样保留 BOM/换行。后续 approval node 将单独调用 `interrupt()`，避免当前 registry 的通用异常归一化吞掉 `GraphInterrupt`，也避免恢复时重放写副作用。
- **edit/write 脚手架结果（2026-09-16）**：新增目标测试为预期的 `3 passed, 7 failed`，七个失败全部来自唯一 `NotImplementedError`；既有 domain/graph/security/tools 回归 `45 passed`，目标 mypy 与全仓 Ruff lint/format 均通过。M4 保持 `in_progress`，在学习者实现、审查和回到整体之前不接 approval/apply，也不进入受控进程切片。
- **edit/write prepare 完成（2026-09-16）**：学习者把唯一匹配检查实现为两次 `find()`：首个命中后从 `match_offset + 1` 寻找第二处，因此覆盖重叠歧义；第二处命中即停止，避免构造全部匹配位置。目标测试 `10 passed`，既有回归 `55 passed`，mypy 与 Ruff lint/format 全部通过。该切片已验收，但 M4 仍为唯一 `in_progress`。
- **approval node 脚手架（2026-09-16）**：新增 checkpoint-safe `PendingFileChange`、有界审批请求、`InMemorySaver` 测试图以及暂停、批准/拒绝恢复、非 pending 和非法恢复载荷测试。完整 `after_text` 只留在图状态，`interrupt()` 载荷只公开 operation/path/hash/preview；本次唯一学习 TODO 是 `file_approval_node()`。脚手架测试为预期的 `2 passed, 5 failed`，五个失败全部停在该 TODO；既有回归 `55 passed`，mypy 检查 32 个文件无问题。实现和审查完成前不接 atomic apply、受控进程或 M5。
- **approval node 完成（2026-09-16）**：学习者完成 pending 门禁、`interrupt()`、严格 `ApprovalDecision` 校验及 approve/reject 状态增量；目标测试 `7 passed`，mypy 检查 12 个文件、目标 Ruff lint/format 均通过，全仓 pytest（当时）`63 passed`。M4 仍为唯一 `in_progress`，下一切片是批准后的版本复核与 atomic apply。
- **atomic apply 脚手架（2026-09-16）**：新增 `AppliedFileChange`、批准状态门禁、stale-version、CRLF 内容保真、原子 edit 和新文件 write 测试。当前唯一 learner TODO 是 `apply_approved_file_change()`；脚手架目标为 `1 passed, 4 failed`，四个失败全部停在该 TODO。未实现前不接受任何真实文件副作用结果，也不进入受控进程。
- **atomic apply 完成（2026-09-16）**：学习者完成 approved 门禁、路径重解析、版本哈希复核、同目录临时文件 `flush/fsync`、`os.replace()` 和异常清理；目标测试 `5 passed`，工具 mypy、Ruff lint/format 通过；排除 process learner 测试的全仓回归 `68 passed`。M4 仍为唯一 `in_progress`，下一切片是结构化 argv 受控进程。
- **受控进程脚手架（2026-09-16）**：新增严格 `ProcessArguments`、可序列化 `ProcessResult`、稳定进程错误和 Python subprocess 测试。当前唯一 learner TODO 是 `run_controlled_process()`；脚手架为预期的 `2 passed, 3 failed`，覆盖 allowlist、无 shell argv、超时语义；未实现前不进入最终 HITL 集成。
- **受控进程完成（2026-09-16）**：学习者完成 executable allowlist、目录存在性检查、`shell=False` 结构化 argv、Windows `taskkill /T` 或 POSIX 进程组终止、UTF-8 有界 stdout/stderr 和稳定 timeout/execution 错误；目标测试 `5 passed`，mypy、Ruff lint/format 通过；排除未来 HITL 集成测试的全仓 pytest `73 passed`。需在最终集成中由 `WorkspacePathPolicy` 负责提供受控 cwd，不能把本函数的目录检查误当作 workspace 授权。
- **M4 最终 HITL 集成（2026-09-16）**：新增 `tests/integration/test_hitl.py`，证明 `FileChangePlanner.prepare_edit -> approval interrupt/resume -> apply_approved_file_change` 的批准、拒绝和 stale-version 路径；审批前目标内容不变，拒绝不能 apply，版本变化不会覆盖磁盘。集成 `3 passed`，全仓 pytest `76 passed`，mypy/Ruff 全部通过。用户确认串联流程无问题，M4 归档，M5 成为唯一 `in_progress`。
- **M4 重新归档复验（2026-09-16）**：按 M4 范围重新执行 tools/security/HITL 验收，`53 passed`；mypy 检查 32 个文件无问题，Ruff lint 通过，32 个文件格式检查通过。归档操作保持幂等：M4 仍为 `completed`，M5 仍是唯一 `in_progress`，未运行或修改 M5 的预期红灯练习。
- **M5 第一切片脚手架（2026-09-16，2026-09-17 复核）**：新增严格 `StreamEvent` DTO 和 `updates` 模式的投影测试；本地 fake 图确认原始 chunk 为 `{node: {messages, status, error}}`，因此测试要求第一切片排除不可 JSON 序列化的消息对象。当前唯一 learner TODO 是 `project_stream_update()`，脚手架目标为 `1 passed, 4 failed`，四个失败全部来自该 TODO。先固定稳定 JSONL 事件边界，再接 message/token/tool/custom 事件和 CLI。
- **M5 第一切片完成（2026-09-17）**：学习者实现 error/tool/state_update 优先级和逐字段 JSON 安全过滤，目标测试 `5 passed`；全仓 pytest `81 passed`，mypy 检查 40 个文件无问题。审查确认不会把 `AIMessage` 用 `str()` 伪装进稳定 payload。
- **M5 第二切片脚手架（2026-09-17）**：新增 `project_update_chunks()` 和真实 `build_tool_graph().stream(stream_mode="updates")` 集成测试，固定 `model -> tools -> model` 的节点顺序及跨 chunk 零基 sequence。当前测试为预期的 `0 passed, 2 failed`，两个失败均来自唯一 learner TODO。
- **M5 第二切片完成（2026-09-17）**：学习者实现惰性 chunk/node 遍历、非 mapping 防护、复用单 update 投影和跨 chunk 连续 sequence；目标测试 `2 passed`，全仓 pytest `83 passed`，mypy 检查 42 个文件无问题。
- **M5 第三切片脚手架（2026-09-17）**：本地 `stream_mode="messages"` 确认为 `(AIMessage, metadata)`；新增稳定 message envelope、完整 assistant message、`AIMessageChunk` token、缺失 node metadata 和真实 fake graph 测试。当前为预期的 `1 passed, 4 failed`，四个失败全部来自 `project_message_chunk()` TODO。
- **M5 第三切片完成（2026-09-17）**：学习者实现稳定 role 映射、`BaseMessageChunk` 判定、非空 `langgraph_node` 门禁及固定 payload；目标测试 `5 passed`，全仓 pytest `88 passed`，全仓 mypy 检查 45 个文件无问题。审查确认未复制任意 metadata，也未使用 `str(message)`。
- **M5 第四切片脚手架（2026-09-17）**：本地 LangGraph 1.2 探针确认 `stream_mode="custom"` 直接产出 writer mapping，而 `stream_mode=["updates", "custom"]` 产出 `(mode, chunk)`；新增严格 progress 事件、字段校验和真实 custom stream 测试。当前为预期的 `1 passed, 4 failed`，四个失败全部来自唯一 `project_custom_chunk()` TODO。
- **M5 第四切片完成（2026-09-18）**：学习者实现 progress 类型门禁、非空 node/message、严格 int 且拒绝 bool、进度区间校验和固定 payload；目标测试 `5 passed`，全仓 pytest `93 passed`，全仓 mypy 检查 48 个文件无问题，Ruff lint/format 通过。
- **M5 第五切片脚手架（2026-09-18）**：本地三模式探针确认真实发出顺序为 `custom -> messages -> updates`，多模式 item 形状为 `(mode, chunk)`；新增三种 projector 统一分派、一个 updates chunk 多事件和全局连续 sequence 测试。当前为预期的 `0 passed, 3 failed`，三个失败全部来自唯一 `project_stream_chunks()` TODO。
- **M5 第五切片完成（2026-09-18）**：学习者完成三种 mode 的惰性分派、单 updates chunk 多节点展开、全局 sequence 以及 malformed mode/payload 错误边界；补充空 node 名称不得静默丢弃的回归。目标测试 `3 passed`，全仓 pytest `96 passed`，全仓 mypy 检查 50 个文件无问题，Ruff lint/format 通过。
- **M5 第六切片脚手架（2026-09-18）**：新增 UTF-8、紧凑 JSONL、逐事件换行和真实三模式 stream 集成测试。当前为预期的 `0 passed, 3 failed`，三个失败全部来自唯一 `iter_jsonl()` TODO；目标 mypy 通过，Ruff 导出排序问题已修复待复验。
- **M5 第六切片完成（2026-09-18）**：学习者实现惰性 JSONL 输出，沿稳定 DTO 字段顺序生成紧凑 UTF-8 JSON，每个事件恰好一行。目标测试 `3 passed`，全仓 pytest `99 passed`，全仓 mypy 检查 53 个文件无问题，Ruff lint/format 通过。
- **M5 第七切片脚手架（2026-09-18）**：新增纯 renderer 单测和真实三模式 stream 到文本行的集成测试；当前为预期的 `0 passed, 4 failed`，四个失败全部来自唯一 `render_event()` TODO；目标 mypy 与 Ruff lint/format 通过。
- **M5 第七切片完成（2026-09-18）**：学习者完成 progress/message/error/state_update 的纯文本渲染及真实三模式顺序验证；目标测试 `4 passed`，全仓 pytest `103 passed`，全仓 mypy 检查 57 个文件无问题，Ruff lint/format 通过。
- **M5 第八切片脚手架（2026-09-18）**：新增 argparse help、fake provider text/jsonl 输出测试，并注册 `pi-agent` console script；当前为预期的 `1 passed, 2 failed`，两个失败全部来自唯一 `run_cli()` TODO；目标 mypy 通过，Ruff 导入排序问题已修复待复验。
- **M5 第八切片完成（2026-09-18）**：学习者完成 fake provider 图运行、统一 stream 投影、text/jsonl 输出选择和传入 output 写入；CLI 目标测试 `3 passed`，console JSONL smoke 成功，全仓 pytest `106 passed`，全仓 mypy 检查 59 个文件无问题，Ruff lint/format 通过。
- **M5 第九切片脚手架（2026-09-18）**：新增幂等 CancellationToken、取消前/取消后关闭 upstream iterator，以及真实 graph projected stream 取消集成测试；当前为预期的 `1 passed, 3 failed`，三个失败全部来自唯一 `iter_cancellable()` TODO；目标 mypy 与 Ruff lint/format 通过。
- **M5 第九切片完成（2026-09-18）**：学习者完成取消前/取消后停止消费、关闭 generator-like upstream、异常不吞和 token 幂等；目标测试 `4 passed`，全仓 pytest `110 passed`，全仓 mypy 检查 62 个文件无问题，Ruff lint/format 通过。
- **M5 第十切片脚手架（2026-09-18）**：新增 scoped SIGINT handler 测试，固定临时安装、触发 token.cancel 和正常/异常退出恢复旧 handler；当前为预期的 `0 passed, 2 failed`，两个失败全部来自唯一 `sigint_cancels()` TODO；目标 mypy 与 Ruff lint/format 通过。
- **M5 第十切片完成（2026-09-18）**：学习者完成 SIGINT handler 的旧状态保存、token.cancel 触发和正常/异常恢复；目标测试 `2 passed`，全仓 pytest `112 passed`，全仓 mypy 检查 64 个文件无问题，Ruff lint/format 通过。
- **M5 第十一切片脚手架（2026-09-18）**：新增 completed/failed 首个终态保留、重复终态抑制和真实 graph 终态集成测试；当前为预期的 `0 passed, 3 failed`，三个失败全部来自唯一 `iter_terminal_once()` TODO；目标 mypy 与 Ruff lint/format 通过。
- **M5 第十一切片完成（2026-09-18）**：学习者完成 completed/failed 首个终态保留、重复终态抑制和真实 graph 证据；目标测试 `3 passed`，全仓 pytest `115 passed`，全仓 mypy 检查 67 个文件无问题，Ruff lint/format 通过。
- **M5 最终接线完成（2026-09-18）**：`run_cli()` 已组合 `sigint_cancels -> iter_cancellable -> project_stream_chunks -> iter_terminal_once -> text/jsonl renderer`；CLI 接线测试、全仓 pytest `116 passed`、mypy 67 个文件、Ruff lint/format 和 text CLI smoke 全部通过。M5 技术实现完成，等待用户确认后再将状态改为 `completed` 并归档。

### M5 — 流式事件与 CLI 闭环

- **目标**：形成可交互、可观测的端到端 MVP。
- **范围**：`astream()` 的 token/state/tool/custom 事件适配；稳定 JSONL 事件 DTO；简单 CLI、Ctrl+C 取消、fake provider 演示。
- **非目标**：Pi TUI 差分渲染、主题、图片或 RPC。
- **交付物**：CLI entry point、文本/JSONL renderer、端到端测试。
- **验收标准**：token 与工具进度按顺序输出；最终状态只发布一次；取消无悬挂任务。
- **验证命令**：`uv run pi-agent --provider fake --prompt "read README" --events jsonl`；`uv run pytest tests/cli tests/integration/test_streaming.py -q`。

- **第一切片目标**：先建立 `StreamEvent` 稳定 JSON 边界，把 LangGraph `stream_mode="updates"` 的单个节点更新投影为可序列化事件。
- **第一切片非目标**：不实现 token 聚合、CLI renderer、取消、custom stream 或真实 provider。
- **第一切片交付物**：`src/pi_agent/events/stream.py`、`tests/events/test_stream.py`；唯一学习者 TODO 为 `project_stream_update()`。
- **第一切片验收**：DTO 严格拒绝非法序列；model/tool/error update 分类稳定；目标测试全部通过后再接 `astream()` 和 JSONL renderer。

### M6 — 会话持久化、恢复与分支

- **目标**：使同一会话可中断恢复、查看历史并从 checkpoint 分支。
- **范围**：开发用 SQLite checkpointer、`thread_id`、session metadata、恢复、历史、fork、崩溃/并发写测试；生产存储接口。
- **非目标**：多租户服务端、跨设备同步。
- **交付物**：`sessions/`、schema/migration 策略、CLI session 子命令。
- **验收标准**：重启后可续聊；checkpoint 不重复执行已完成副作用；分支不污染原会话；损坏数据给出明确错误。
- **验证命令**：`uv run pytest tests/sessions tests/integration/test_resume.py tests/integration/test_fork.py -q`；`uv run pi-agent session list`。

### M7 — 上下文装配与长对话压缩

- **目标**：按确定顺序组合系统提示词、项目规则和历史，并在预算内运行。
- **范围**：全局/祖先/当前目录 `AGENTS.md`、prompt template、token 估算、压缩阈值、摘要节点、保留最近 turn 与文件操作事实。
- **非目标**：兼容 Pi 的全部 skills/extensions 格式或精确 token 计费。
- **交付物**：`context/`、上下文快照诊断、压缩与恢复测试。
- **验收标准**：装配顺序可解释；摘要不删除持久化原记录；压缩失败不破坏会话；工具调用边界保持合法。
- **验证命令**：`uv run pytest tests/context tests/integration/test_compaction.py -q`；`uv run pi-agent context inspect --provider fake`。

### M8 — 模型适配、重试、取消与容错

- **目标**：把 graph runtime 与供应商、鉴权和瞬时故障解耦。
- **范围**：`BaseChatModel` 工厂、OpenAI-compatible 首个适配器、环境变量配置、超时、指数退避、错误分类、用量、取消传播、fake/stub 合约测试。
- **非目标**：重写 pi-ai 的完整 provider/OAuth/model catalog。
- **交付物**：`models/`、配置模型、provider contract tests、可选 live smoke 文档。
- **验收标准**：日志不含密钥；不可重试错误立即失败；重试有上限；取消传播到模型和工具。
- **验证命令**：`uv run pytest tests/models tests/runtime -q`；`uv run ruff check .`；`uv run mypy src`。

### M9 — 扩展、可观测性与评测

- **目标**：提供受约束扩展点，并能证明行为质量和运行可靠性。
- **范围**：before/after model/tool、run lifecycle hooks；结构化日志、span/metrics；fake 回归集与可选真实模型 eval；敏感字段脱敏。
- **非目标**：执行任意第三方 Python 插件、完整 LangSmith 平台部署。
- **交付物**：hook registry、telemetry adapter、eval harness、基线报告。
- **验收标准**：hook 顺序确定且故障隔离；trace 可关联 thread/run/tool；回归评测可重复；无密钥写入 artifact。
- **验证命令**：`uv run pytest tests/extensions tests/telemetry tests/evals -q`；`uv run pi-agent eval --suite smoke --provider fake`。

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

## 6. 阶段边界与执行规则

- 当前验收点：M4 已完成并归档；M5 是唯一 `in_progress` 里程碑。全部事件、JSONL、renderer、fake CLI、取消、SIGINT、终态过滤和最终接线已完成；等待用户确认归档，不得提前进入 M6。
- MVP 为 M1-M6：具备安全工具、流式 CLI、持久化和分支后才算闭环。
- M7-M9 补齐长对话、供应商适配、扩展与质量工程；M10 是独立可选能力。
- 每次只进入一个里程碑；进入前更新本表和 `LEARNING_LOG.md`，退出前保存实际验证命令、输出摘要和遗留项。
- 状态表机械检查：`$count = (Select-String -Path PLAN.md -Pattern '\|\s+in_progress\s+\|').Count; if ($count -gt 1) { throw "More than one milestone is in_progress" }`。
- 默认采用引导式结对开发：先解释并搭好可测试骨架，再一次只交给学习者一个关键、范围可控的编码练习；审查其实现后再推进，不直接包办整个里程碑。
- 每个里程碑先实现最小可理解版本，再增加生产约束；不得跨里程碑提前铺设未验收抽象。
- 每次实现都引用对应 Pi 源码路径，但以 Python/LangGraph 惯用设计为准，不逐行翻译 TypeScript。
- 涉及外部模型的验收必须同时提供不使用 API Key 的 fake 路径；真实模型 smoke 不能替代确定性测试。

## 7. 官方资料

- Pi 源码基线：<https://github.com/earendil-works/pi/tree/96317e50b8d6e7f6d0e47fd29122baf1461c00f5>
- LangGraph PyPI：<https://pypi.org/project/langgraph/>
- Graph API：<https://docs.langchain.com/oss/python/langgraph/graph-api>
- Streaming：<https://docs.langchain.com/oss/python/langgraph/streaming>
- Persistence：<https://docs.langchain.com/oss/python/langgraph/persistence>
- Interrupts：<https://docs.langchain.com/oss/python/langgraph/interrupts>
