# Python Pi Agent（LangGraph）执行计划

## 1. 当前状态与文档分工

- 初始规划：2026-09-02；M5 初次归档：2026-09-18；M5 遗留项复验、M6 实现与归档：2026-09-21（Asia/Shanghai）。
- M0–M7 已完成并归档；M7 最终验收/归档：2026-09-22（Asia/Shanghai）。M8.1–M8.8 已完成；M8.9-R1 与 R2-A–R2-F 的代码和离线验收已完成，全仓门禁为 403 passed、4 个 live gate 预期 skip，M8 保持 `in_progress` 并等待归档确认。R2-A 已有一次真实普通回复成功证据；streaming、resume、summary 的真实 smoke 尚未显式执行，归档时必须保留该验收缺口。M8.3/M8.4 及本轮 R2-D–R2-F 由助手代写，学习者复盘单独进行。
- 真实 provider/tool 的异步中断、超时和取消传播仍属于 M8，不能从 M5 的同步消费侧取消推断已经完成。

| 文件 | 唯一职责 |
|---|---|
| PROJECT_SPEC.md | 项目目标与教学方式 |
| PLAN.md | 当前状态、里程碑范围、验收要求、阶段接口 |
| LEARNING_LOG.md | 学习者基础、按里程碑总结、关键决策、问题索引 |
| docs/acceptance/Mx.md | 对应里程碑的验收命令、结果、局限和归档结论 |
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
| M8 | 模型适配、重试、取消与容错 | completed | 增强 | 2026-09-23 按用户指示归档已交付范围；保留真实服务与端到端接线验收缺口；[M8 归档](docs/acceptance/M8.md) |
| M9 | 扩展、可观测性与评测 | pending | 生产化 | 尚未启动 |
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
| `AgentEvent` / streaming | 已实现同步 `stream()` 的 messages/updates/custom 投影；异步运行仍是后续工作 |
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
  domain/        # 消息、状态、错误
  events/        # 稳定事件投影、序列化、终态过滤
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

## 5. 里程碑契约

每项固定保留目标、范围、非目标、交付物、验收标准、验证命令。已完成项的事实与局限见归档；M8–M11 命令为未来验收目标，其中尚未创建的目录或入口不能当作现在可执行的命令。

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

### M7 — 上下文装配与长对话压缩

- **目标**：按确定顺序组合系统提示词、项目规则和历史，并在预算内运行。
- **范围**：全局/祖先/当前目录 `AGENTS.md`、prompt template、token 估算、压缩阈值、摘要节点、保留最近 turn 与文件操作事实。
- **非目标**：兼容 Pi 的全部 skills/extensions 格式或精确 token 计费。
- **交付物**：`context/`、上下文快照诊断、压缩与恢复测试。
- **验收标准**：装配顺序可解释；摘要不删除持久化原记录；压缩失败不破坏会话；工具调用边界保持合法。
- **验证命令**：`uv run pytest tests/context tests/integration/test_compaction.py -q --basetemp=.pytest-tmp-m7-acceptance`；`uv run pi-agent context inspect --provider fake`。

归档结果：M7.1–M7.7 与归档修复已完成全局/祖先规则、prompt template、UTF-8 与 token 估算、阈值触发的同步摘要阶段、最近 turn/文件操作事实保留、最终预算门禁和诊断 CLI。摘要阶段在 `model_node` 内通过 `ModelSummarizer` 执行，不新增持久化派生消息；SQLite 测试证明失败后原记录可恢复。真实 provider 与精确计费不属于本轮验收。完整证据与局限见 [M7 归档](docs/acceptance/M7.md)。

### M8 — 模型适配、重试、取消与容错

- **目标**：把 graph runtime 与供应商、鉴权和瞬时故障解耦。
- **范围**：`BaseChatModel` 工厂、OpenAI-compatible 首个适配器、环境变量配置、超时、指数退避、错误分类、用量、取消传播、fake/stub 合约测试。
- **非目标**：重写 pi-ai 的完整 provider/OAuth/model catalog。
- **交付物**：`models/`、配置模型、provider contract tests、可选 live smoke 文档。
- **验收标准**：日志不含密钥；不可重试错误立即失败；重试有上限；取消传播到模型和工具。
- **验证命令**：`uv run pytest tests/models tests/runtime -q`；`uv run ruff check .`；`uv run mypy src`。

#### M8 A. 从面出发：把已验证组件接到真实模型

规划日期：2026-09-22（Asia/Shanghai）。实现基线：`ba930a0`。M7 归档记录的全仓 217 项通过是已有证据，本次规划没有重跑或新增业务测试。以下新增文件、接口和命令均为开发目标，不能当作已经交付。

系统现状：M3 工具循环、M4 安全工具/独立审批图、M5 同步事件、M6 SQLite 会话、M7 上下文组件已交付；默认 CLI 仍只运行 fake 最小图。M8 负责连接真实 provider 和运行时容错；M9 增加 hooks/tracing/evals，M11 做完整产品验收。

贯穿请求：在一个显式指定的临时工作区和会话中，要求“读取 README.md，结合上一轮讨论说明下一步”。长历史需要时先生成摘要；主模型首次遇到可重试的限流，等待后返回 read 工具调用；工具结果回灌后模型流式回答。变式是在摘要、退避、回答流或受控进程运行时按 Ctrl+C，确认停止后还能检查会话，没有自动重放副作用。

数据流：用户输入 → M6 原始历史 → M7 规则/预算/可选摘要 → **M8 模型适配与受控重试** → M3 工具循环/M4 安全执行 → **M8 异步事件与取消** → M5 渲染 + M6 checkpoint。客户端、密钥和取消句柄只属于运行依赖；图状态只保留消息及安全、可序列化的状态信息。

当前实际缺口及其影响：

| 现有位置 | 已有能力 | M8 接入点 |
|---|---|---|
| `models/base.py`、`fake.py` | 自定义 `ChatModel.invoke`，确定性 fake/scripted | 保留同步契约，新增真实适配和原生异步能力 |
| `graph/nodes.py` | 同步上下文与模型调用；模型异常直接 `str(exc)` | 分类、脱敏、异步节点；避免凭据进入 error/checkpoint |
| `tools/base.py`、`registry.py` | Pydantic 校验与串行执行；公共协议未暴露 schema | 发布工具 schema；异步执行与取消边界 |
| `context/runtime.py`、`summarizer.py` | 摘要也是同步模型调用 | 主模型和摘要共同接入超时、重试、取消；区分事件来源 |
| `events/`、`cli/app.py` | 同步投影和消费侧取消；fake 最小图 | 原生异步流消费、真实 provider 和最小只读工具运行入口 |
| `sessions/sqlite.py`、`runtime.py` | 同步 SqliteSaver 与普通续聊 | AsyncSqliteSaver 生命周期、异步续聊和取消后 checkpoint 处理 |

M8 范围补充：为真实 provider 联调所必需的工具 schema、异步摘要、异步 SQLite 与 CLI 只读接线纳入本阶段；这些是原有 provider/取消目标的集成依赖。真实写文件审批产品入口、任意 shell、多 provider 自动切换、OAuth、精确计费、多模态、摘要质量评测集不纳入 M8。M4 写工具继续使用已有审批组件，不能因绑定工具而绕过审批；M9/M11 承接后续产品化与质量验收。

#### M8 B. 进入点：设计依据与实施约束

Pi 固定源码链路：`packages/agent/src/agent-loop.ts:streamAssistantResponse()` 先做 `transformContext`、`convertToLlm`，再解析 API key，将 tools 与 signal 传给 `streamFunction`；工具准备与执行也接收同一 signal。保留“运行依赖与状态分开、取消贯穿整轮”的设计，Python 用适配器和异步任务表达。Pi 会维护 partial message；本项目选择只将完整、验证后的回复提交消息状态，部分响应只供流式展示。

来源核验：本地临时 Pi 快照有部分源码，但 HEAD 无法解析、provider/session 文件不完整；本轮通过[固定提交源码](https://raw.githubusercontent.com/earendil-works/pi/96317e50b8d6e7f6d0e47fd29122baf1461c00f5/packages/agent/src/agent-loop.ts)复核上述调用链。不把下述重试策略宣称为 Pi 原样实现；M8.4 开工时再核对固定提交的 provider/session 重试实现及差异。

框架检查：锁文件为 langgraph 1.2.11、langchain-core 1.6.1、langgraph-checkpoint-sqlite 3.1.1；本地包可见 AsyncSqliteSaver。Context7 工具不可用，改查 [ChatOpenAI 官方集成说明](https://docs.langchain.com/oss/python/integrations/chat/openai) 和 [LangGraph streaming](https://docs.langchain.com/oss/python/langgraph/streaming)。`langchain-openai` 尚未加入项目，M8.2 再选择与现有锁文件兼容的版本并验证；不在规划阶段升级依赖。

| 问题 → 设计选择 | 原因、代码落点与测试证据 |
|---|---|
| 供应商 SDK 不进入图 → `BaseChatModel` 工厂外包项目适配器 | 工厂创建模型，绑定工具后的对象通过适配器满足项目协议；`models/factory.py`、`adapter.py`；fake 与真实适配共用契约测试 |
| 兼容服务并非全部等价 → 首个适配器限定标准 Chat Completions 子集 | 文本、工具调用、异步流、可选 usage；base URL 直接作为 API 根，不自行重复拼接 `/v1`；供应商额外字段另行适配 |
| 多层重试会放大调用 → `runtime/retry.py` 是唯一重试所有者 | SDK 重试显式关闭；图节点不再外包第二层重试；主调用/摘要各有 attempt ID，但共享整轮 deadline |
| 把同步调用放入线程不能保证中断 → 真正异步的 model/context/tool/session 路径 | 保留同步 API；不可取消的任意同步工具不声称可中断；受控进程由持有句柄的执行器回收 |
| provider 异常可能含密钥 → `models/errors.py` 只暴露安全错误字段 | 禁止直接把 SDK 异常正文、headers、客户端对象写事件或 checkpoint；合成哨兵密钥覆盖 repr、CLI、日志和 SQLite |
| 流与落盘生命周期不同 → 展示增量，完成后提交 AIMessage | 半截 tool arguments 不执行；部分输出后失败不静默重试；终态只发布一次，用集成测试检查资源关闭 |

固定运行时策略：

- `max_attempts` 包含首次请求，建议默认 3；单次模型请求建议 30 秒，整轮建议 120 秒，退避基数 0.5 秒、上限 8 秒，均可配置。使用单调时钟与可注入 sleep/jitter，测试不真实等待。
- 连接错误、超时、429 rate limit 与选定瞬时 5xx 可以在剩余预算内重试；鉴权、非法参数、上下文超限、协议损坏、额度耗尽不重试。429 需区分 rate limit 与 quota；未知错误默认不重试。解析 Retry-After 后仍受整轮 deadline 约束。
- 只重试单次模型请求，工具不自动重试，不重跑整轮 graph。流尚未对外发布内容时可重试；首个正文或工具参数增量发出后，后续失败直接进入失败终态，防止重复展示或工具执行。远端是否已计费不能由本地失败推断。
- `CancelledError` 作为控制信号传播，不能转为普通可重试错误。取消源由 runtime 持有，CLI signal handler 只通知；运行器等待子任务、流、客户端和进程资源清理，再报告取消。同步文件提交有明确不可中断短区间，不承诺回滚已经完成的写入。
- LangGraph 管 reducer、路由、checkpoint 与图流；应用负责凭据、错误分类、重试预算、进程树回收和安全策略。Python 3.11 的异步调用显式传递 RunnableConfig/callbacks，保持 token 流与调用归属。
- 摘要和主回复必须有独立角色标签；摘要 token 不显示成用户答案。usage 按逻辑调用/attempt 区分，缺失为 unknown，不能记成 0；供应商用量与 M7 估算分开，不做费用结算。

#### M8 切片及独立验收

以下切片按顺序推进；M8.1–M8.8 已完成，M8.9-R1 与 R2-A–R2-F 的代码/离线验收已完成，当前等待 M8 归档确认。M8.3/M8.4 作为助手代写切片由学习者另行复盘；R2-D–R2-F 按用户明确要求由助手一次性完成，不再保留学习者 TODO。

##### M8.1 — 配置与凭据边界

- **切片状态**：`completed`（2026-09-22；57 项测试、mypy、Ruff 和格式检查通过）。

- **目标**：在构造模型和发请求之前确定本次运行配置。
- **范围**：fake/compatible provider、model、base URL、环境变量密钥、timeout/max_attempts/整轮预算；显式参数优先于项目环境变量，最后才是非敏感默认值。
- **非目标**：安装 SDK、访问网络、实现重试。
- **交付物**：`models/config.py`、`.env.example` 配置名说明、`tests/models/test_config.py`；密钥保留在运行期 secret 容器，公开配置不包含明文密钥。
- **验收标准**：fake 无密钥可用；真实配置缺字段、空白密钥、非法 URL/数值时提前失败；拒绝 URL 内凭据；错误/repr 不泄密；参数和环境映射不被修改。供应商 model ID 不设猜测默认值。
- **验证命令**：`uv run pytest tests/models/test_config.py -q --basetemp=.pytest-tmp-m81`。

##### M8.2 — 首个真实模型适配器

- **切片状态**：`completed`（2026-09-22；65 项模型配置/适配器/工厂测试通过，mypy、Ruff 和格式检查通过）。

- **目标**：同一项目模型边界可以调用 fake 或真实兼容服务。
- **范围**：兼容版本依赖、BaseChatModel 工厂、项目 adapter、同步调用和客户端生命周期；标准消息/错误归一化，SDK 自动重试关闭。
- **非目标**：工具 schema、图异步化、多供应商自动探测。
- **交付物**：`models/factory.py`、`adapter.py`、`errors.py`，`pyproject.toml`/`uv.lock`，`tests/models/test_adapter.py`。以 transport stub 验证真实 SDK 序列化，不能仅 mock 工厂返回值。
- **验收标准**：保留 messages/ID/tool_calls，非法响应明确失败；base URL 不重复路径；同步旧图可注入 adapter；关闭客户端；假密钥不出现在异常、state 或日志。
- **验证命令**：`uv run pytest tests/models/test_adapter.py tests/graph/test_minimal_graph.py -q --basetemp=.pytest-tmp-m82`。

##### M8.3 — 工具 schema 与真实协议闭环

- **切片状态**：`completed`（2026-09-22；12 项离线 schema/registry/provider-shaped 闭环测试、mypy、Ruff 和格式检查通过）。真实 SDK/network smoke 明确留到 M8.9，不作为本切片的隐含前置条件。

- **目标**：模型看到的工具定义与应用实际执行的工具一致。
- **范围**：从现有 ToolDefinition 导出 JSON schema；registry 提供稳定只读视图；绑定工具；保留调用 ID、校验和轮次上限。
- **非目标**：CLI 开放写文件、命令执行或自动审批。
- **交付物**：`tools/base.py`、`registry.py` 的显式 schema 契约，`models/tool_binding.py`，`tests/models/test_tool_binding.py`、`tests/integration/test_provider_tool_loop.py`。
- **验收标准**：stub 返回调用 → registry 校验执行 → 原 call ID 的 ToolMessage → 第二次模型回答；未知工具、坏参数、invalid_tool_calls/缺 ID 均不产生意外副作用；零工具时不要求服务支持工具绑定。
- **验证命令**：`uv run pytest tests/models/test_tool_binding.py tests/integration/test_provider_tool_loop.py tests/tools/test_registry.py -q --basetemp=.pytest-tmp-m83`。

##### M8.4 — 错误分类与有界重试

- **切片状态**：`completed`（2026-09-22；助手代写，6 项目标测试和静态检查通过；学习者复盘另行进行）。

- **目标**：恢复瞬时失败，并明确什么时候必须停止。
- **范围**：错误分类、attempt 计数、指数退避/jitter、Retry-After、单次超时和整轮 deadline；同步策略测试先行，异步调用在 M8.5 接入同一策略。
- **非目标**：重试工具、重启整张图、流中断后拼接两次回复。
- **交付物**：`runtime/retry.py`、`runtime/policy.py`、`models/errors.py`；`tests/runtime/test_retry.py`、`tests/models/test_errors.py`。
- **验收标准**：429→成功次数精确；401、quota、坏参数仅一次；失败不超过配置；等待计入预算；最后一次失败后不再 sleep；异常消息/响应中的合成密钥不进入公开结果。
- **验证命令**：`uv run pytest tests/runtime/test_retry.py tests/models/test_errors.py -q --basetemp=.pytest-tmp-m84`。

##### M8.5 — 原生异步模型、上下文与图

- **切片状态**：`completed`（M8.5-R1–R5 于 2026-09-23 完成）。

- **目标**：主调用和摘要都可以被 deadline/取消控制。
- **范围**：项目异步模型协议、原生 SDK ainvoke/astream 能力；异步模型节点与上下文摘要入口，复用 M7 纯预算/配对逻辑；异步 builder 与同步 API 并存。
- **非目标**：将任意同步 handler 的线程包装称为真正可取消、CLI 完整接线。
- **交付物**：`models/base.py`/`adapter.py`、`graph/async_nodes.py`/`builder.py`/`context.py`、`context/async_runtime.py`/`summarizer.py`，`tests/models/test_async_adapter.py`、`tests/integration/test_async_context.py`。
- **验收标准**：成功消息顺序与同步图一致；摘要异常阻止主调用且保留原历史；摘要超时/取消清理任务；取消退避立即停止；显式 config 保持事件 callback 归属。异步 fake 保证全程无密钥可测。
- **验证命令**：`uv run pytest tests/models/test_async_adapter.py tests/integration/test_async_context.py tests/context -q --basetemp=.pytest-tmp-m85`。

##### M8.6 — 异步流、工具增量与用量

- **切片状态**：`completed`（2026-09-23；M8.6-R1–R4 离线交付完成。真实 Provider 网络 smoke 仍属于 M8.9）。

- **目标**：真实 SDK 的增量可显示，完整回复可安全交给图。
- **范围**：async stream adapter、chunk 聚合、tool-call 参数分片、usage、attempt/主模型/摘要归属；延续现有三模式投影与 sequence 契约。
- **非目标**：重新设计全部事件协议、价格计算、供应商私有 reasoning 字段。
- **交付物**：`events/async_adapter.py`、`models/usage.py` 及现有 events 必要增量；`tests/events/test_async_adapter.py`、`tests/models/test_usage.py`、`tests/integration/test_provider_streaming.py`。
- **验收标准**：token 顺序和完整消息仅计一次；分片工具参数完成前不执行；摘要不混入答案；usage 无重复累加、缺失标记 unknown；首增量后断流不重试、不执行不完整调用、不提交半条成功消息；全部退出路径关闭上游。
- **验证命令**：`uv run pytest tests/events/test_async_adapter.py tests/models/test_usage.py tests/integration/test_provider_streaming.py -q --basetemp=.pytest-tmp-m86`。

##### M8.7 — 取消传播与工具资源回收

- **切片状态**：`completed`（2026-09-23；M8.7-R1–R10 离线交付完成，目标测试与静态检查通过）。

- **目标**：用户取消能停止实际工作，并得到唯一取消终态。
- **范围**：runtime 任务所有权、取消/超时区分、async registry、受控进程句柄和进程树回收、工具批次中止策略；CLI 0/1/130 及事件 terminal 扩展。
- **非目标**：回滚已落盘文件、对未知外部副作用提供 exactly-once 保证。
- **交付物**：`runtime/cancellation.py`、`runtime/runner.py`、`tools/async_registry.py`、`tools/async_process.py`，domain/events/CLI 取消契约；`tests/runtime/test_cancellation.py`、`tests/tools/test_async_process.py`。
- **验收标准**：预取消零调用；摘要/主模型等待、退避、流、进程五处都可取消；关闭并 await 所有 owned tasks/管道/客户端；受控子进程及其子进程退出；批次后续工具不启动；已完成结果与未执行/结果未知分别记录；取消不被转成可重试错误。文件原子提交边界需实测并说明。
- **验证命令**：`uv run pytest tests/runtime/test_cancellation.py tests/tools/test_async_process.py tests/cli/test_cancel.py tests/cli/test_signals.py -q --basetemp=.pytest-tmp-m87`。

##### M8.8 — SQLite、CLI 与最小只读端到端联调

- **切片状态**：`completed`（2026-09-23；M8.8-R1–R5 离线交付完成，目标测试与静态检查通过）。

- **目标**：从用户命令进入真实模型、只读工具、上下文和可恢复会话。
- **范围**：AsyncSqliteSaver 与异步 session runner；显式 database/session/workspace/context 配置；compatible provider CLI；read/list/search 最小注册；取消后检查和显式恢复门禁。
- **非目标**：CLI 写文件/危险命令审批界面、隐式默认数据库、通用崩溃事务恢复。
- **交付物**：`sessions/async_sqlite.py`、`sessions/async_runtime.py`、`cli/app.py` 及运行装配层；`tests/integration/test_async_resume.py`、`test_provider_cli.py`、`tests/cli/test_provider_app.py`。
- **验收标准**：同一临时 DB 重开可续聊；fake 入口、session list/context inspect 保持可用；取消后的 checkpoint 可读，pending tool calls 必须显式处理且不自动重放；已完成 tool 结果不因模型重试再次执行。工具结果已发生而 checkpoint 未提交的崩溃窗口明确标记为需人工确认，不能声称 exactly-once。text/JSONL 终态唯一且退出码正确。
- **验证命令**：`uv run pytest tests/integration/test_async_resume.py tests/integration/test_provider_cli.py tests/cli/test_provider_app.py -q --basetemp=.pytest-tmp-m88`。

###### M8.8-R1 — 异步 SQLite checkpoint 生命周期

- **目标**：让异步图在单一 app-owned SQLite 上完成打开、写入、关闭、重开和读取，且不把连接生命周期泄漏给调用方。
- **范围**：`sessions/async_sqlite.py::open_async_sqlite_checkpointer`；路径校验、`AsyncSqliteSaver` async context、异常/取消原样传播和连接关闭。
- **非目标**：异步 session runner、CLI provider 参数、真实网络调用、checkpoint 冲突恢复和 pending tool replay。
- **交付物**：async checkpointer 上下文管理器及 `tests/sessions/test_async_sqlite.py`。
- **验收标准**：同一临时 DB 关闭后可重开并读取同一 thread 的 checkpoint；目录路径在打开前拒绝；离开上下文后连接关闭；不得调用同步 checkpoint API 或吞掉取消。
- **验证命令**：`uv run pytest tests/sessions/test_async_sqlite.py -q --basetemp=.pytest-tmp-m88-r1`；`uv run mypy src/pi_agent/sessions/async_sqlite.py tests/sessions/test_async_sqlite.py`；`uv run ruff check src/pi_agent/sessions/async_sqlite.py tests/sessions/test_async_sqlite.py`；`uv run ruff format --check src/pi_agent/sessions/async_sqlite.py tests/sessions/test_async_sqlite.py`。

###### M8.8-R2 — 异步 session runner 与恢复

- **目标**：让异步应用层以稳定 session ID 驱动 `aget_state`/`ainvoke`，在重开数据库后继续同一对话，并拒绝绕过暂停 checkpoint。
- **范围**：`sessions/async_runtime.py::run_async_session_turn`；async session config、输入校验、暂停门禁、metadata 记录时机和 AgentState 返回。
- **非目标**：CLI 参数解析、provider 网络调用、工具注册、pending tool replay 和跨进程崩溃事务恢复。
- **交付物**：异步 session runner 及 `tests/sessions/test_async_runtime.py`。
- **验收标准**：同一数据库重开后第二轮模型收到第一轮历史；暂停 thread 不调用模型且抛出 `SessionNotReadyError`；空白输入在模型调用前拒绝；成功后才记录 metadata。
- **验证命令**：`uv run pytest tests/sessions/test_async_runtime.py -q --basetemp=.pytest-tmp-m88-r2`；`uv run mypy src/pi_agent/sessions/async_runtime.py tests/sessions/test_async_runtime.py`；`uv run ruff check src/pi_agent/sessions/async_runtime.py tests/sessions/test_async_runtime.py`；`uv run ruff format --check src/pi_agent/sessions/async_runtime.py tests/sessions/test_async_runtime.py`。

###### M8.8-R3 — provider CLI 选项边界

- **目标**：将 provider、prompt、事件格式、database、session 和 workspace 作为显式非敏感运行选项传入后续装配层。
- **范围**：`cli/provider.py::ProviderCliOptions` 与 `resolve_provider_cli_options`；路径/字符串校验和 provider/event literal 投影。
- **非目标**：真实网络调用、API key 读取、异步 graph 执行、只读工具注册和终态渲染。
- **交付物**：provider CLI 选项 DTO/解析函数及 `tests/cli/test_provider_app.py`。
- **验收标准**：显式路径和 session ID 原样保留；缺失 database/session 被拒绝；解析结果不携带 secret 字段；不读取全局环境或创建 provider client。
- **验证命令**：`uv run pytest tests/cli/test_provider_app.py -q --basetemp=.pytest-tmp-m88-r3`；`uv run mypy src/pi_agent/cli/provider.py tests/cli/test_provider_app.py`；`uv run ruff check src/pi_agent/cli/provider.py tests/cli/test_provider_app.py`；`uv run ruff format --check src/pi_agent/cli/provider.py tests/cli/test_provider_app.py`。

###### M8.8-R4 — provider session 运行装配

- **目标**：把显式 provider CLI 选项组装成 async graph、AsyncSqliteSaver、workspace context 和 session runner 的单次运行。
- **范围**：`cli/runtime.py::run_provider_session`；注入 `AsyncChatModel`、异步 checkpoint 上下文、`AsyncRunContext` 和 `run_async_session_turn`。
- **非目标**：真实 SDK/network client、CLI 终态渲染、只读工具注册、API key 解析和取消后的 pending tool replay。
- **交付物**：provider session 运行装配函数及 `tests/integration/test_provider_cli.py`。
- **验收标准**：fake/injected model 可在显式 database/session/workspace 下完成一轮；同一 DB 第二轮能看到历史；workspace instructions 进入 context；运行装配不隐式创建或读取 provider client。
- **验证命令**：`uv run pytest tests/integration/test_provider_cli.py -q --basetemp=.pytest-tmp-m88-r4`；`uv run mypy src/pi_agent/cli/runtime.py tests/integration/test_provider_cli.py`；`uv run ruff check src/pi_agent/cli/runtime.py tests/integration/test_provider_cli.py`；`uv run ruff format --check src/pi_agent/cli/runtime.py tests/integration/test_provider_cli.py`。

###### M8.8-R5 — 只读工具注册与 workspace 边界

- **目标**：为 CLI 运行时注册最小 `read/list/search` 集合，保持工作区约束并明确排除写文件和进程命令。
- **范围**：`cli/read_only.py::create_cli_read_only_registry`；`WorkspacePathPolicy`、输出预算和现有只读工具工厂的组合。
- **非目标**：异步 tool-call graph、文件修改审批、受控进程、真实 provider、pending tool replay 和终态渲染。
- **交付物**：只读 registry 装配函数及 `tests/cli/test_read_only_registry.py`。
- **验收标准**：注册顺序稳定且只有 read/list/search；三种工具可在 workspace 内执行；越界路径不泄露内容；apply/process 等写入或命令工具不出现在 registry。
- **验证命令**：`uv run pytest tests/cli/test_read_only_registry.py -q --basetemp=.pytest-tmp-m88-r5`；`uv run mypy src/pi_agent/cli/read_only.py tests/cli/test_read_only_registry.py`；`uv run ruff check src/pi_agent/cli/read_only.py tests/cli/test_read_only_registry.py`；`uv run ruff format --check src/pi_agent/cli/read_only.py tests/cli/test_read_only_registry.py`。

##### M8.9 — 合约回归、真实服务 smoke 与归档

- **切片状态**：`completed`（2026-09-23；R1 与 R2-A–R2-F 代码/离线验收完成；全仓 403 passed、4 个未启用 live 测试 skip，mypy/Ruff/format 通过）。M8 仍为 `in_progress`，等待用户确认归档；R2-D–R2-F 的真实网络 smoke 未执行。

- **目标**：用可重复证据判断 M8 完成度，交接 M9。
- **范围**：离线 transport 合约/故障矩阵、全仓回归、明确启用的 live smoke（普通回复、只读工具、流式、续聊及摘要路径）、文档整理。
- **非目标**：默认 CI 使用付费密钥、全面评估摘要语义质量、将兼容服务 A 的结果推广到所有 provider。
- **交付物**：`tests/integration/test_provider_acceptance.py`、`tests/live/test_provider_smoke.py`、`docs/acceptance/M8.md` 实测矩阵、README 配置/联调说明。
- **验收标准**：离线套件与静态检查全部通过；CI 缺少凭据时 live 测试明确 skip。真实服务仅在用户配置并显式启用后调用，记录日期/provider/model/endpoint 类型和结果，不留密钥或请求正文。live 未执行时保留“真实服务验证未完成”，不得写成已通过；摘要质量评测继续归 M9。
- **验证命令**：`uv run pytest tests/models tests/runtime tests/integration/test_provider_acceptance.py -q --basetemp=.pytest-tmp-m89`；全仓门禁见下文。可选 live 命令为 `uv run pytest tests/live/test_provider_smoke.py -m live -q --basetemp=.pytest-tmp-m8-live`，须同时设置专用启用变量和安全凭据，marker 在实现时注册。

###### M8.9-R1 — 离线合约回归

- **目标**：用一条无网络的 fake provider 路径回归 M8.8 的 session、workspace 和只读工具边界。
- **范围**：`tests/integration/test_provider_acceptance.py`；不改变生产实现，不读取真实凭据。
- **非目标**：真实 provider/network smoke、摘要质量评测、全仓最终归档。
- **交付物**：离线 acceptance 回归测试及 M8 实测矩阵更新。
- **验收标准**：fake provider session 可完成；只读 registry 仍只暴露 `read/list/search`；测试不访问网络、不依赖 API key。
- **验证命令**：`uv run pytest tests/models tests/runtime tests/integration/test_provider_acceptance.py -q --basetemp=.pytest-tmp-m89`。

###### M8.9-R2 — 真实 provider smoke

- **目标**：在用户显式配置兼容 endpoint、model ID 和安全凭据后，验证普通回复、只读工具、流式、续聊和摘要路径。
- **范围**：`tests/live/test_provider_smoke.py` 及其安全配置读取；只记录 provider/model/endpoint 类型和结果摘要。
- **非目标**：默认 CI 触网、持久化 API key、记录请求正文、摘要质量评测。
- **交付物**：live smoke 测试、skip 逻辑、compatible async client、README 配置说明和 M8 实测矩阵。
- **验收标准**：无凭据时明确 skip；启用后只访问用户指定 endpoint；失败不泄露 secret；未执行时保持“真实服务验证未完成”。
- **验证命令**：`uv run pytest tests/live/test_provider_smoke.py -m live -q --basetemp=.pytest-tmp-m8-live`（需用户显式配置后执行）。

###### M8.9-R2-A — compatible async client 普通回复

- **切片状态**：`completed`（2026-09-23；用户真实 smoke `1 passed`；离线契约 `3 passed, 1 skipped`；mypy、Ruff、format-check 通过）。本轮复跑受当前网络 `ConnectError` 影响，保留为 live revalidation gap，不把它写成代码回归。
- **目标**：在显式 `PI_AGENT_LIVE=1` 时，通过用户 `.env` 配置向兼容 endpoint 发起一次最小异步对话，并归一化为项目 `AIMessage`。
- **范围**：`src/pi_agent/models/http_client.py::build_async_provider_client`；`tests/live/test_provider_smoke.py` 的显式 gate、资源关闭和普通回复断言。
- **非目标**：工具绑定、流式增量、SQLite 续聊、摘要质量、默认测试触网和请求/响应正文日志。
- **交付物**：compatible async client 实现；不泄露 API key 的异常边界；live smoke 的可重复命令。
- **验收标准**：未设置 `PI_AGENT_LIVE=1` 时明确 skip；启用后只使用 `ModelConfig` 中的 endpoint/model/key；成功响应包含 `LIVE_SMOKE_OK`；异常正文和密钥不进入项目异常；`aclose()` 释放客户端资源。
- **验证命令**：`uv run pytest tests/live/test_provider_smoke.py -q --basetemp=.pytest-tmp-m89-r2a`；显式 live 为 `$env:PI_AGENT_LIVE="1"; uv run --env-file .env pytest tests/live/test_provider_smoke.py -m live -q --basetemp=.pytest-tmp-m8-live`；另加 `uv run mypy src/pi_agent/models/http_client.py tests/live/test_provider_smoke.py`、Ruff check 与 format-check。

###### M8.9-R2-B — provider tool-call 响应归一化

- **切片状态**：`completed`（2026-09-23；4 passed；mypy、Ruff、format-check 通过）。
- **目标**：把兼容服务的 `tool_calls` 响应安全归一化为 `AIMessage.tool_calls`，保留 call ID、函数名和 JSON 参数，供后续 async tool loop 使用。
- **范围**：`_ai_message_from_payload()` 的 tool-call 分支及 `tests/models/test_http_client.py::test_client_normalizes_provider_tool_call`。
- **非目标**：执行工具、工具权限、流式 tool-call 分片、SQLite 回灌和真实工具调用。
- **交付物**：严格校验的 tool-call payload 解析；非法参数或缺字段时稳定失败且不泄露 provider body。
- **验收标准**：`content: null` 且存在合法 function call 时返回空内容 `AIMessage`；`name`、`id`、JSON `arguments` 正确映射；非法结构返回 `invalid_response`；R2-A 回归保持通过。
- **验证命令**：`uv run pytest tests/models/test_http_client.py -q --basetemp=.pytest-tmp-m89-r2b`；另加 `uv run mypy src/pi_agent/models/http_client.py tests/models/test_http_client.py`、Ruff check 与 format-check。

###### M8.9-R2-C — async read-only tool loop

- **切片状态**：`completed`（2026-09-23；主路径与未知工具/轮次上限边界共 `3 passed`；mypy、Ruff、format-check 通过）。
- **目标**：把 R2-B 产生的 `AIMessage.tool_calls` 接入 async graph，执行受控的 `read/list/search`，再将带 call ID 的 `ToolMessage` 回灌给 provider。
- **范围**：`AsyncRunContext` 的工具依赖、async tool node/路由、最小 async tool graph、`AsyncToolRegistry` 的只读工具装配。
- **非目标**：写文件、进程工具、真实流式 tool-call 分片、无限循环、摘要质量和跨 provider 工具语义推广。
- **交付物**：async tool graph、工具轮次上限、未知工具/参数错误投影、provider tool-call 集成测试。
- **验收标准**：provider 请求 read 时只执行 workspace 内只读工具；结果 `ToolMessage.tool_call_id` 与请求一致；未知工具和参数错误不触发越界副作用；达到轮次上限后终止；fake/offline 回归保持通过。
- **验证命令**：`uv run pytest tests/integration/test_async_provider_tool_loop.py -q --basetemp=.pytest-tmp-m89-r2c`；另加相关 mypy、Ruff 与 format-check。

###### M8.9-R2-D — provider streaming

- **切片状态**：`completed`（2026-09-23；6 项专属离线测试通过，live stream 测试默认 skip，静态检查通过）。
- **目标**：将兼容 provider 的流式响应安全转换为 `AIMessageChunk`，复用现有 collector 完成文本、tool-call 分片和最终 usage 归一化。
- **范围**：async provider client 的 stream 边界、SSE/Provider-shaped chunk 解析、`collect_async_response` 接线和资源关闭。
- **非目标**：流式摘要质量、跨 provider 私有事件协议、默认 CI 触网、把半截 tool-call 提前写入 checkpoint。
- **交付物**：provider stream adapter、断流/空流/非法 chunk 错误边界、离线 stream contract tests；显式 live smoke 只记录结果摘要。
- **验收标准**：正常文本流完整聚合；tool-call 分片只在自然结束后形成完整 `AIMessage.tool_calls`；最后 chunk 才计 usage；断流或取消关闭底层响应且不提交半截消息；API key/正文不进入异常。
- **验证命令**：`uv run pytest tests/models/test_async_provider_stream_client.py tests/integration/test_async_provider_streaming.py -q --basetemp=.pytest-tmp-m89-r2d`；另加相关 mypy、Ruff 与 format-check。

###### M8.9-R2-E — session resume

- **切片状态**：`completed`（2026-09-23；1 项 provider-backed SQLite 重开/续聊集成测试通过，live resume 测试默认 skip）。
- **目标**：在真实 provider 结果下验证 SQLite checkpoint 重开、同一 session 续聊和消息历史连续性。
- **范围**：provider-backed async session runner、数据库重开、第二轮 prompt 与历史投影。
- **非目标**：分支 fork、摘要质量、默认触网。
- **交付物**：`tests/integration/test_provider_session_resume.py` 与 gated live resume smoke。
- **验收标准**：两轮调用之间 saver 关闭并重开；第二轮 provider 输入包含首轮用户/助手消息和第二轮用户消息；durable history 连续且不持久化客户端或凭据。
- **验证命令**：`uv run pytest tests/integration/test_provider_session_resume.py -q --basetemp=.pytest-tmp-m89-r2e`；live 统一使用 R2 命令。

###### M8.9-R2-F — summary/compaction path

- **切片状态**：`completed`（2026-09-23；成功、失败脱敏、取消 3 项 provider-backed 离线测试通过，live summary 测试默认 skip）。
- **目标**：验证 provider-backed context summary/compaction 成功、失败和取消路径，不把密钥或原文写入 checkpoint。
- **范围**：async summary context、预算门禁、provider response 与 durable history 边界。
- **非目标**：摘要语义质量评测（归 M9）、多 provider 对比。
- **交付物**：`tests/integration/test_provider_summary_compaction.py` 与 gated live summary smoke。
- **验收标准**：摘要只进入临时模型上下文，不替换 durable history；摘要失败不调用主模型且错误脱敏；取消保持 LangGraph 的 `NodeCancelledError` 边界；真实质量不在本片断言。
- **验证命令**：`uv run pytest tests/integration/test_provider_summary_compaction.py -q --basetemp=.pytest-tmp-m89-r2f`；live 统一使用 R2 命令。

#### 当前归档确认门槛

整体链路已具备：`显式配置 → compatible async client → 完整回复/SSE stream → async graph → SQLite resume → 临时 summary/compaction → durable history`。R2-D 将文本、tool-call 分片和 terminal usage 聚合为完整消息；断流、非法数据和取消均关闭响应且不提交半截 usage。R2-E 证明 SQLite 重开后的第二轮 provider 输入历史连续。R2-F 证明摘要只影响临时上下文，失败停止主模型，取消按 LangGraph 边界传播。

本轮按用户明确要求不设置学习者 TODO，由助手完成 R2-D–R2-F。专属离线集合为 15 passed、4 个 live gate skip；最终全仓为 403 passed、4 skipped，mypy 179 source files、Ruff lint/format、fake CLI 与 context inspect 均通过。真实普通回复已有 2026-09-23 的 1 passed 证据；streaming、resume、summary 的真实网络 smoke 尚未执行。用户确认后可以归档“已交付”，但不得把这三项 live 缺口改写为完整真实验收。

#### M8 C. 从点回到面：验收门槛与后续接口

每片复盘同一条“读取 README 并结合历史回答”链路：新能力接在哪里，失败时哪些步骤没有执行，原始消息/工具副作用是否保留；不只记录测试数。M8.9 将成功、401、限流恢复、重试耗尽、断流、摘要失败、五处取消和 SQLite 重开逐一对应到测试。

最终全仓门禁：

```powershell
uv run pytest -q --basetemp=.pytest-tmp
uv run mypy src tests
uv run ruff check .
uv run ruff format --check .
uv run pi-agent --provider fake --prompt hello --events jsonl
uv run pi-agent context inspect --provider fake
```

异步测试优先使用 `asyncio.run` 和注入的 clock/sleep；只有测试生命周期确有需要才增加异步 pytest 插件。新增模型 SDK 作为可选 provider extra 或普通依赖的选择在 M8.2 做兼容性验证后固定，fake 路径必须能在无凭据环境运行。

进入真实服务 smoke 前需要用户确定兼容端点和 model ID，并在本机环境变量配置凭据；这不阻塞 M8.1–M8.8 离线开发。使用临时合成工作区和会话验证，避免默认发送真实项目文件。提交/推送不属于本次开发规划操作。

M9 从这里接入运行/调用 ID、脱敏错误、usage 和生命周期事件，扩展 tracing、hooks 与 evals。M8 不以合约测试替代真实连通性，也不把 M7 估算替换为供应商计费承诺。

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

## 6. 范围接口与执行规则

- M3 定义工具循环；M4 定义文件/进程安全能力；M5 定义事件和 CLI 消费。组件分别通过测试不等于 CLI 已连通所有工具。
- M4 的 InMemorySaver 只支持审批教学测试；M6 才负责持久化会话、跨进程恢复和分支。
- M5 的 SIGINT/token 是同步消费侧协作取消，并已验证迭代器资源释放；M8 的 provider/tool 异步取消传播仍属于运行时能力。
- M7 已归档；M8.1–M8.9 代码与离线门禁已完成，等待 M8 归档确认。R2-A 真实普通回复已通过一次；R2-D–R2-F 的真实 streaming/resume/summary smoke 仍待显式执行并按 §5 M8 记录。
- 每个里程碑坚持“整体请求 → 当前切片 → Pi 设计与 Python 映射 → 一个练习 → 回到整体”。学习者实现有价值的核心代码。
- 修改范围或验收口径时保留原要求，明确已实现部分和未覆盖部分；不可通过搬移文档隐去缺口。
- 里程碑编号 M0–M11 固定。M5 内的十一道练习属于子切片，不是十一项新里程碑。
- PLAN 不再追加每轮测试流水；最新快照更新原段落，详细证据放到对应验收文件。历史“下一步”和预期红灯仅保存在历史快照。

## 7. 本次复验与记录维护

2026-09-23 M8 归档前复验：全仓 pytest `403 passed, 4 skipped`，4 项均为未启用 `PI_AGENT_LIVE=1` 的预期 live gate；mypy 检查 179 个源文件；Ruff lint 与 200 个文件格式检查通过；fake JSONL CLI 与 context inspect smoke 退出码均为 0。真实普通回复已有一次用户执行的 1 passed 证据，新增 streaming/resume/summary live smoke 尚未执行。

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
