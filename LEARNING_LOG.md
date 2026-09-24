# 学习日志

## 当前快照

- 更新日期：2026-09-24；时区：Asia/Shanghai。
- 学习者基础：具备 Python 基础，学习过 LangChain/LangGraph 常规用法；目标是能独立设计、实现和审查 Agent 系统。
- 进度：M0–M9 已按各自交付范围归档。M9 最终组合测试 **28 passed**、mypy **203 source files**、Ruff lint/format 与 fake eval CLI 由用户于 2026-09-24 报告通过；live eval、默认 CLI telemetry 与 CLI 工具轨迹仍按 [M9 归档](docs/acceptance/M9.md) 的边界跟踪。M8 的 Linux/POSIX 实进程树、真实 429/网络中取消、语义摘要质量等不随 M9 归档自动通过。
- 当前练习：M9 已交付范围完成归档；M10 远程协议为可选扩展，M11 全链路验收尚未启动。下一步以 [PLAN](PLAN.md) 的里程碑状态和 [M9 归档](docs/acceptance/M9.md) 的未关闭边界为准。
- 当前能力：默认 fake CLI 仍使用无持久化最小图；显式 compatible CLI 已连通异步只读工具图、受控模型重试/时限、SQLite 会话与节点事件。命令仅能由模型提案，再由人审入口执行；文件写入仍是独立 M4 审批边界。完整闭环、证据和限制见 [M8 纠正记录](docs/acceptance/M8-closure.md)。
- 状态唯一来源：[PLAN.md](PLAN.md)。本日志只总结学习和决策；旧过程流水见 [整理前快照](docs/history/2026-09-18-before-m5-archive/README.md)。

## 时间线

日期来自原有文档与本次会话；区分实现、用户验收和归档。没有可靠证据时不补写时分秒，不把本次整理日期当作所有历史工作的完成日期。

| 里程碑 | 学习/实现记录时间 | 验收或归档时间 | 阶段结果 |
|---|---|---|---|
| M0 | 2026-09-02 | 2026-09-02 初始规划记录 | 固定源码基线和路线 |
| M1 | 2026-09-03 | 2026-09-03 | 工程与质量门禁 |
| M2 | 2026-09-03 | 2026-09-04 用户验收归档 | 最小模型图 |
| M3 | 2026-09-04 至 2026-09-11 | 2026-09-11 | 工具调用闭环 |
| M4 | 2026-09-11 至 2026-09-16 | 2026-09-16 归档及重验 | 安全工具与审批 |
| M5 | 2026-09-16 至 2026-09-21 | 2026-09-18 初次归档；2026-09-21 闭合复验 | 同步事件/CLI 教学范围完整验收 |
| M6 | 2026-09-21 | 2026-09-21 归档 | 会话持久化、恢复、历史、状态分支与 metadata CLI |
| M7 | 2026-09-21 至 2026-09-22 | 2026-09-22 修复、最终验收与归档 | 上下文装配、同步摘要与失败恢复、诊断 CLI |
| M8 | 2026-09-22 至 2026-09-24 | 2026-09-23 首次归档；2026-09-24 端到端纠正及真实服务复验 | compatible provider/异步组件/公开 CLI 只读闭环；部分跨平台和质量复验保留 |
| M9 | 2026-09-24 | 2026-09-24 已交付范围归档 | 最终组合范围 28 passed；mypy 203 个文件、Ruff 与 fake eval CLI 通过；live 与默认 CLI telemetry 边界保留 |

阶段测试数是当时证据：M1 全仓 1、M2 全仓 9、M3 全仓 22、M4 当时全仓 76；M4 重验范围为 53；2026-09-18 全仓为 116、M5 范围为 40；2026-09-21 闭合复验全仓为 123、M5 范围为 47。这些数字对应不同时间和范围，不能混写为同一轮验证。

## M0 — 源码分析与路线设计

从“模型能回答问题”扩大到完整 Agent：输入经过上下文装配进入模型，工具调用经校验/执行回灌，再由循环决定继续或结束；session、UI、扩展和遥测在核心循环外协作。

分析基线是 Pi `96317e50b8d6e7f6d0e47fd29122baf1461c00f5`。主要入口为 `packages/agent/src/agent-loop.ts` 与 coding-agent 的 `AgentSession.prompt()`。学习重点是区分运行时消息、发给模型的消息、显示事件和会话持久化；不追求 TypeScript 或远程协议的字节兼容。

规划结果是 M0–M11；MVP 路线为 M1–M6，增强为 M7–M9，M10 按远程需求选择，M11 总体验收。进入 M6 并不自动意味着产品已达到生产级。

## M1 — Python 工程骨架

交付 `src` 布局、uv/锁文件、pytest/mypy/Ruff/CI 基线。学习者实现从发行包元数据暴露版本，理解源码目录与安装包的区别，以及 lint 与格式检查是不同门禁。

历史验证包括 Python 3.11.13、3.12.3、3.13.5；这些是 M1 当时的结果，不代表本轮重新执行过三个解释器。详细命令见 [M1 验收](docs/acceptance/M1.md)。

## M2 — 消息、状态与最小图

贯穿请求：`hello → HumanMessage → model_node → AIMessage 增量 → reducer → END`。模型异常保留消息历史并写入结构化失败状态。

Pi 命令式循环映射为 LangGraph 的 state、节点和条件边。学习者实现 `model_node()`；核心认识是节点读完整状态、返回增量，模型对象通过 `RunContext` 注入而不放进持久状态。`add_messages` 会按 ID 替换消息，因此“返回历史一定重复”是错误简化，但仍应遵守增量契约。

历史上 M2 曾因教学结构调整暂停又恢复；这属于过程历史，当前状态不再退回 pending。验收与理解问题见 [M2](docs/acceptance/M2.md)。

## M3 — Tool Calling 闭环

贯穿请求：`calculate 2 + 3 → add tool call → registry/schema/handler → ToolMessage("5") → model final → END`。

学习者实现 `ToolRegistry.execute_call()`。未知工具、参数错误与执行异常必须分层，保留 call ID 关联后回灌模型；轮次上限属于图级终止，不能和可恢复工具错误混淆。`ToolMessage.id` 是消息身份，`tool_call_id` 是调用关联，不能无区分复用。

保留自定义 registry/node 以理解控制流；M3 串行执行 fake 工具，真实 provider 的工具绑定留到 M8。验收见 [M3](docs/acceptance/M3.md)。

## M4 — 安全 Coding Tools 与人工审批

贯穿场景：读取工作区 README，提出修改，审批后核对版本并落盘；越界路径、歧义替换、拒绝审批或版本变化都阻止写入。

| 已完成切片 | 学到的边界 |
|---|---|
| WorkspacePathPolicy.resolve | canonical containment，区分 not_found 与 invalid_path，覆盖 junction 逃逸 |
| TextOutputBudget.apply + read/list/search | 按 UTF-8 字节与整行截断；目录分类不为判断类型而跟随 junction |
| apply_exact_replacement | 两次 find 判断唯一性，第二次从首位置 + 1 开始覆盖重叠匹配 |
| file_approval_node | interrupt/resume 会重放节点；副作用应位于审批之后 |
| apply_approved_file_change | approved 门禁、哈希复核、同目录临时文件与原子替换 |
| run_controlled_process | 结构化 argv、allowlist、shell=False、超时回收与有界结果 |
| prepare→approval→apply 集成 | 批准、拒绝和 stale-version 三条路径 |

Pi 对应 harness/tools 与 harness/env；本项目增加更严格的 workspace 边界。路径校验后的 TOCTOU 风险仍存在；cwd 必须由路径策略提供，目录存在性检查不等于授权。进程 allowlist/超时不等于完整命令审批；M4 组件也尚未全部接入 CLI。原验收见 [M4](docs/acceptance/M4.md)。

## M5 — 流式事件与 CLI 闭环

加入 M5 后，同一个 `hello` 请求从最小图依次产生 message 和 completed update，经稳定 DTO 转成 JSONL 或文本输出。LangGraph 负责产生框架 chunk，应用负责字段投影、sequence、呈现与 CLI 生命周期。

| 子切片 | 学习成果 |
|---|---|
| M5.1 updates 投影 | error/tool/state_update 分类；消息对象不直接泄漏到 payload |
| M5.2 updates adapter | 按节点与 chunk 源顺序展开；惰性迭代 |
| M5.3 message/token 投影 | role/content/id/chunk 标记；只读取必要 metadata |
| M5.4 custom/progress 投影 | writer 自带 node；严格整数拒绝 bool |
| M5.5 多模式 adapter | 按实际产出事件分配 sequence；空 node 明确失败 |
| M5.6 JSONL | 紧凑 JSON、保留 Unicode、一事件一行 |
| M5.7 text renderer | 格式化纯函数与 IO 分离 |
| M5.8 CLI 入口 | argparse、fake 最小图、三模式消费、text/jsonl、逐事件 flush |
| M5.9 cancellation | 预取消不启动生产者；已启动 iterator 的 close 逐层传播 |
| M5.10 SIGINT scope | 保存旧 handler、token.cancel、finally 恢复 |
| M5.11 终态过滤与接线 | completed/failed/error 首终态截止；退出码 0/1/130 |

闭合复验：M5 范围 `47 passed`，全仓 `123 passed`，mypy 68 个文件、Ruff lint/format 通过，text/jsonl smoke 通过。完整命令和证据在 [M5 归档](docs/acceptance/M5.md)。

本次修复把此前发现的缺口转成正式契约：未启动 generator 不能为触发 finally 而先 next；包装层必须在 finally 中把 close 传到 raw stream；failed 投影成 error 后仍属于运行终态；终态之后不再消费；CLI 每个事件写出后 flush。测试不仅检查输出，也检查不应发生的 next、raw close、异常退出清理和退出码。

## M6 — 会话持久化、恢复与分支

整体链路从单次运行扩展为：`session_id → thread_id → checkpointed graph → SQLite → 进程重建 → 同一 thread 的下一轮输入`。LangGraph checkpointer 保存 thread 内图状态；应用自有 metadata 负责列表和创建/更新时间，二者没有混成一个 schema。

M6.1 贯穿 `remember alpha → 关闭 SQLite → 重新打开 → what should you remember?`。图 builder 可注入 checkpointer，`AgentTurnInput` 明确“本轮输入”边界，SQLite context manager 负责连接关闭。`run_session_turn()` 先读取最新 snapshot，若 `next` 非空则拒绝普通新一轮；否则以 `durability="sync"` 调用图。普通续聊传新输入 mapping；只有恢复 `interrupt()` 才使用 `Command(resume=...)`。

M6.1 复验覆盖跨连接恢复、thread 隔离、输入校验和暂停 checkpoint 保护。`run_session_turn()` 保持普通新输入和 `Command(resume=...)` 的语义边界，并以同步 durability 写 checkpoint。

M6.2 已完成：`get_state_history()` 返回的 `StateSnapshot` 被严格投影为 `SessionCheckpoint`，保留 checkpoint ID、时间、来源、step、状态、消息数和待执行节点，不保留原始消息或框架对象。目标范围 `3 passed`，组合范围 `15 passed`，mypy 与 Ruff 通过。

M6.3 已完成：从一个已完成 source checkpoint 创建独立 target thread。锁定版本的 SQLite saver 未实现基类最新的 `copy_thread()`，因此采用公开 `graph.update_state(..., as_node="model")` 写入选中状态，不执行模型或重放先前节点。复查补充了“completed 但仍待执行 model”的真实 snapshot；实现会在写 target 前拒绝它，且 target 不会被创建。目标 `4 passed`，组合范围 `24 passed`。

M6.4 建立独立的 metadata catalog：`pi_agent_schema_migrations` 管本项目 schema 版本，`pi_agent_sessions` 只保存 session ID 与创建/更新时间，和 LangGraph 的 checkpoint/writes 表分离。原子 UPSERT 保留首次 `created_at`，每次记录只更新 `updated_at`。

2026-09-21 复查发现初版 timestamp 直接调用 `isoformat()`，会保留非 UTC offset 并接受 naive datetime。新增测试要求 catalog 只持久化 UTC ISO-8601，naive clock 明确失败；这两点已闭合。

M6.4 已完成：`record_session()` 以单条 UPSERT 保持初始创建时间、更新 UTC 时间，并在 catalog 重建后可列出记录。低判断量接线已把可选 `SessionCatalog` 放入 `run_session_turn()`：图返回终态后记录 metadata；暂停 thread 在 `get_state()` 门禁失败时不记录。checkpoint 已落盘但 catalog 写失败时可能产生跨连接不一致，这是归档后明确保留的生产化边界。

M6.5 已完成 schema 中间态恢复：如果应用在 `pi_agent_sessions` 建表后、migration marker 写入前崩溃，下一次启动会以 `CREATE TABLE IF NOT EXISTS` 恢复表，并在表可用后用 `INSERT OR IGNORE` 补写 marker。并行 catalog 写入测试确认每个调用使用自己的 connection；DDL、marker 和 UPSERT 都可安全重试。2026-09-21 验证：metadata/recovery 7 passed，sessions 的 mypy、Ruff lint 与 format-check 通过。

M6.6 将不可读 SQLite 文件产生的 `DatabaseError` 转换为带绝对路径的 `SessionCheckpointError` 并保留异常链；锁冲突等 `OperationalError` 不伪装成损坏数据。M6.7 增加 `pi-agent session list --database PATH`，以稳定 JSONL 列出 metadata，且测试直接证明不会构造 Agent 图。

M6 归档复验为全仓 `158 passed`、mypy 86 个文件、Ruff lint 与 101 个文件格式检查通过。fork 测试直接断言创建分支期间模型调用列表不变；CLI console smoke 退出码为 0。详细范围和局限见 [M6 归档](docs/acceptance/M6.md)。

## M7 — 上下文装配与长对话压缩

M7 已归档。贯穿请求从 SQLite 原始历史和活动文件进入，按 global→workspace root→leaf 读取规则，经模板装配、完整历史压缩计划、同步摘要阶段和最终预算校验后调用模型；图只新增实际模型/工具消息。Pi resource loader / transformContext 的职责在此映射为 context 组件与模型调用前的运行时依赖。

学习者完成 M7.1–M7.6 的核心函数，助手按明确请求完成 M7.7 和归档修复。归档复查纠正了“组件测试绿灯等于组合已验收”的判断：先裁剪会丢摘要来源；插入摘要后必须重算预算；工具请求和批次结果必须一起保留；最近 turn 的完整性比单纯消息条数更重要。

最终实现增加全局规则与模板、启发式 token 估算、ModelSummarizer、旧工具事实保留和 context inspect。上下文失败独立报告 context_error，主模型不被调用；最新 checkpoint 可记录失败和新输入，旧 checkpoint/原消息保持可读，SQLite 重开后可继续。全仓 217 项通过，M7 原计划范围 56 项通过，完整结果见 [M7 归档](docs/acceptance/M7.md)。

局限：token 估算不是精确计费；真实模型摘要质量和异步容错归 M8/M9。摘要阶段在 model_node 内同步执行，未增加独立的持久化摘要图状态；重复调用会重新计算，摘要缓存属于后续优化。默认 fake run CLI 仍不是生产 Coding Agent 入口。

## M8 — 模型适配、重试、取消与容错（已归档，验收缺口保留）

2026-09-22 完成 M8.1–M8.4。2026-09-23 完成 M8.5-R1：原生 async model node、上下文派生、配置透传、安全失败和 LangGraph 图边界取消语义通过 5 项测试及静态检查；完成 R2：异步摘要序列化、config 透传、回复校验和取消传播通过 5 项测试；完成 R3：异步摘要接回临时上下文，目标 3 项与同步上下文回归 12 项通过；完成 R4：原生 async retry/deadline 通过 4 项测试及静态检查；完成 R5：异步 Provider 适配器通过 5 项测试及静态检查。完成 M8.6-R1–R4：异步多模式流投影、工具调用参数分片、usage 归一化/attempt 去重和 Provider stream 聚合均通过目标测试及静态检查。完成 M8.7-R1–R10：runtime 取消信号、owned task join、async tool registry/batch、spawned process 生命周期、受控 spawn、deadline、有界结果、进程树策略及树终止接线均通过目标测试和静态检查；M8.7 已归档。完成 M8.8-R1–R5：async checkpoint、session runner、CLI 选项、provider session 装配和只读 registry 均通过目标测试，M8.8 已归档。完成 M8.9-R1 离线合约回归（103 passed）；R2-A 真实普通回复曾 1 passed；R2-B/C 完成 tool-call 归一化和 async tool loop；按用户要求一次性完成 R2-D–R2-F：SSE 文本/tool-call/usage 聚合及断流/取消资源释放、SQLite 重开续聊、provider-backed 摘要成功/失败/取消。最终全仓 403 passed、4 个 live gate skip，mypy 179 files、Ruff 与两个 CLI smoke 通过。

本轮关键复盘：Provider SSE 必须等 `[DONE]` 才能提交完整消息和 usage，EOF 视为断流；第二轮工具请求必须回传 assistant `tool_calls`，否则孤立的 `ToolMessage` 不符合兼容协议；session resume 的证明点是第二次调用真正看到 checkpoint 历史，而不只是最终 state 看起来连续；摘要是临时上下文派生，原始 durable history 不被摘要替换。节点主动取消在 LangGraph 图边界表现为以 `CancelledError` 为 cause 的 `NodeCancelledError`。为使全仓门禁可执行，pytest 固定 importlib 导入，mypy 固定 `src` 包基准，消除了同名测试模块冲突。

M8 初次归档时，异步组件虽分别补齐，CLI 仍只公开 fake 最小图，provider session 未把工具、重试、事件/取消接线。学习重点是：函数叫异步不等于底层可取消；模型重试不能重放已执行工具；部分回答发出后重试会造成重复输出；摘要也需要超时、取消和独立事件归属。工厂和 SDK 适配保留在模型边界，LangGraph 继续负责图与状态。

规划决策：只设一个模型重试所有者，SDK 内层重试关闭；完整回复才提交消息状态；凭据仅存运行依赖；错误、日志和 checkpoint 统一使用安全字段。`tests/live` 的真实请求必须由 `PI_AGENT_LIVE=1` 与显式加载 `.env` 双重启用，默认测试不触网；公开 CLI 只在显式 `--provider compatible` 且提供有效配置时才发起真实请求。

当时 Context7 工具不可用，改用官方框架文档及固定提交 Pi agent-loop 源码；本地临时上游快照的 HEAD 和 provider 文件不完整，不把它当作完整可验证 checkout。M8 的详细设计为本项目选择，不宣称复制了尚未核验的 Pi provider 重试实现。真实普通回复已有用户执行的成功证据；streaming/resume/summary live tests 未启用网络，不能将 4 个默认 skip 写成真实服务通过。2026-09-23 用户要求先归档已交付范围；2026-09-24 离线复验 403 passed、4 deselected，详见 [阶段总结](docs/stage-summary/M1-M8.md) 与 [审计](docs/reviews/M1-M8-audit.md)。

2026-09-24 端到端纠正：HTTP 绑定 `tools` schema，Provider 会话选择 async tool graph，公开 CLI 接通隔离工作区的 read/list/search、SQLite 续聊、节点事件与脱敏 trace；命令只产生持久提案，需交互人审后才能一次性领取并执行。Windows 本机实跑非零退出码、输出洪流截断、越界 cwd 拒绝；真实 compatible provider 普通回复、SSE、续聊、摘要 4 项通过，合成文件真实 read→ToolMessage→最终回复也通过。复盘要点是“允许列表 + cwd”不是 OS 沙箱；副作用恢复采取 fail-closed 的 at-most-once 领取，不能声称跨资源恰好一次。详细证据见 [M8 纠正记录](docs/acceptance/M8-closure.md)。

## M9 — 扩展、可观测性与评测（已交付范围归档）

M9 把 M8 已能运行的 provider/tool/session 链路变成可解释、可关联、可重复评测的系统。贯穿请求为 `请读取 probe.txt 并总结`：同一 `thread_id/run_id` 下应观察 run、model、tool 的前后事件，后续 telemetry 形成父子 span，fake eval 对最终回复、工具调用与脱敏 artifact 做确定性断言。

M9.1 先缩小到观察型 hook registry。Pi 固定源码中的 `ExtensionRunner` 按 extension/handler 注册顺序串行派发事件，并对多数观察/变换事件收集扩展错误；tool-call 拦截具有更强的失败语义。本项目首版不复制任意 TypeScript/Python 插件加载、UI/命令注册和结果改写，只允许应用显式注入 async handler，并且事件不携带 prompt、工具参数、回复或输出。这样普通观察 hook 可以 fail-open，取消仍作为控制流传播；未来若增加安全拦截 hook，必须另设 fail-closed 契约，不能复用观察型语义。

脚手架提供 `HookEvent`、`HookFailure`、`HookDispatchResult` 与注册表。学习者完成 `HookRegistry.dispatch()`：对注册表取快照并保持调用顺序；普通异常隔离后仅记录类型名；`CancelledError` 原样传播。学习者报告目标测试 `5 passed`；本轮 mypy 检查 185 个源文件、Ruff lint 与 format 均通过。审查确认实现与契约一致。

同一请求仍按 M8 的 `probe.txt → read → ToolMessage → 最终回复` 路径执行。M9.1–M9.3 为同一 run 增加有序、隔离故障的 run/model/tool hooks 与脱敏 telemetry 接口；M9.6 将事件接为同一 trace 的 root/model/tool spans，并修复 child `end()` 失败时其余 spans 的清理。M9.4–M9.5 提供确定性 fake judge、无正文 JSON 报告和公开 smoke CLI。新文件位于 `extensions/`、`telemetry/`、`evals/` 与 `cli/eval.py`：Provider/graph 上游产生受限元数据，telemetry 和 eval 下游消费，checkpoint 状态不承载这些运行期依赖。最终组合范围 28 passed、mypy 203 个文件、Ruff 与 fake smoke CLI 通过，均为用户执行报告；归档范围和开放边界见 [M9 归档](docs/acceptance/M9.md)。

## 关键决策

| 决策 | 结论与原因 |
|---|---|
| 图编排 | 使用 StateGraph 显式节点/条件边，使控制流可学习、可测试 |
| 数据边界 | TypedDict/reducer 管图内更新；Pydantic 校验边界；runtime 依赖不进入状态 |
| 工具协议 | schema 校验先于执行；ToolMessage 保留关联；副作用前单独审批 |
| 事件边界 | 消息、状态和 custom 分开投影，统一 sequence，再给 renderer 消费 |
| 持久化 | checkpointer 保存 thread 内图状态，session metadata 另设应用边界；M6 开发环境使用 SQLite，生产 saver 留接口 |
| Provider | 先 fake 再真实适配；M5 fake CLI 不代表真实 token 流已验收 |
| 取消 | M5 完成同步消费侧协作取消；M8 接入 provider 请求和工具 owned task，真实传输中取消仍需故障注入复验 |
| 测试方法 | 测试通过只证明已写断言；需覆盖不应发生的副作用和真实数据形状 |
| 学习方式 | 先完整链路，再小练习，再返回系统；切片按所属里程碑汇总 |

工程经验：Windows tmp_path 权限与 junction 条件应单独核查；使用 `uv run` 确保包导入环境一致；多个 uv 命令顺序执行以避免 editable 安装竞争；mypy 下注意 list 不协变。

## 已闭合纠正项

| 编号 | 闭合结果 | 证据位置 |
|---|---|---|
| M5-R1 | 预取消 next=0，显式 close=1 | cli cancellation tests |
| M5-R2 | close 逐层传播到 raw stream，输出异常也清理 | adapter/CLI integration tests |
| M5-R3 | 统一终态并在首终态截止；退出码 0/1/130 | terminal 与 CLI tests |
| M5-R4 | 三模式顺序、token/tool/progress、逐事件 flush | scripted no-key CLI test |

## 未解决问题与归属

| 归属 | 问题 | 下一步/证据位置 |
|---|---|---|
| 后续真实模型质量评测 | 供应商 tokenizer、多模态计费与真实摘要语义质量 | M7 已验收确定性估算/假模型调用与恢复；后续用真实 provider 做质量和容量评测 |
| M8 跨环境复验 | POSIX 实进程树、真实 429/传输中取消、命令 `claimed` 后崩溃核对 | [M8 纠正记录](docs/acceptance/M8-closure.md) 与 [剩余清单](docs/follow-ups/M1-M8.md) |
| 生产持久化 | SQLite 仅为开发存储；checkpoint 与 metadata 跨连接写入不是原子事务；CLI 无默认数据库策略 | 保留为后续生产化设计，不反向扩张 M6 归档范围 |
| M9 归档后 / M10–M11 | M9 未关闭边界、可选远程和全系统验收 | M9 边界见 [归档记录](docs/acceptance/M9.md)；M10 可选，M11 尚未启动 |

## 本次整理记录与后续写法

2026-09-18：按用户要求归档 M5 已交付版本。将原来落在 M4 下的 M5 记录分离；把反复追加的“当前下一步”和脚手架红灯移入历史快照；统一里程碑标题与时间线；保留原始验收要求，并登记新发现的缺口。本次无业务代码或测试改动。

2026-09-21：修复并复验 M5-R1–R4。同步 fake-provider 教学范围完整通过；真实 provider/tool 的异步取消、超时与任务中断仍按原计划归 M8，不因本次归档被视为完成。

2026-09-21：归档 M6。统一清理 M6.1/M6.5 “当前练习”、M6 未启动/未归档等旧状态；保留 SQLite 开发限定、状态 fork 不复制完整祖先历史、显式数据库路径以及 checkpoint/metadata 非原子等边界。

2026-09-22：按用户要求修复并归档 M7。清理旧的“当前任务”与过早验收描述，保留原计划范围并补齐组合预算、摘要生成、失败恢复和诊断 CLI。过程记录与当时测试数完整保存在 [M7 归档前快照](docs/history/2026-09-22-before-m7-archive/README.md)。

2026-09-23：按用户要求先归档 M8 已交付范围；2026-09-24：核对 M1–M8 文档与源码、Git 和离线门禁，统一索引、阶段总结、问题修订与后续清单。原始长篇切片过程保存在 [整理前快照](docs/history/2026-09-23-m1-m8-review/INDEX.md)，不再作为当前待办。

以后一个里程碑一个总结段；新进展更新对应段落。当前快照仅有一份，详细验证只写对应验收文件。历史测试数必须标注时间和范围，归档不得把教学版局限写成生产级保证。
