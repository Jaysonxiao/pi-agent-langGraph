# 学习日志

## 当前快照

- 更新日期：2026-09-29；时区：Asia/Shanghai。
- 学习者基础：具备 Python 基础，学习过 LangChain/LangGraph 常规用法；目标是能独立设计、实现和审查 Agent 系统。
- 进度：M0–M10 已按各自交付范围归档。M10 离线本机范围于 2026-09-28 完成归档复验，组合 **133 passed**、全仓非 live **565 passed、4 deselected**；范围和遗留见 [M10 归档](docs/acceptance/M10.md)。M8 的跨平台/真实故障注入与 M9 的 live/default CLI 边界仍按各自记录跟踪。
- 最近里程碑：M11 于 2026-09-29 按本地交付范围完成用户验收并归档。M11.1 的学习者练习 `collect_tool_names()` 已完成；M11.1–M11.4、本机 compatible 手工场景和 4 项 live tests 均有记录。新环境 Windows/Linux 与真实服务部署验证保留为后置 D1–D3；真实请求对应的 telemetry 文件脱敏检查及配置投影输出没有单独留存。详细结论以 [PLAN](PLAN.md) 和 [M11 归档](docs/acceptance/M11.md) 为准。
- 独立 Web 后续：2026-10-01 按用户要求先计划再直接开发，完成 Bash 启动、显式中断恢复、完成 checkpoint 分支和流式文本；macOS 本机离线验证完成，详见[计划与执行记录](docs/design/web-continuation.md)。恢复以新 run 明确授权继续待完成的只读节点；分支只复制完成状态。流式正文走独立临时预览，完整响应才进入持久图状态，不进入 lifecycle telemetry。
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
| M10 | 2026-09-24 启动；2026-09-28 完成 M10.4–M10.8 | 2026-09-28 用户条件授权后离线本机范围归档 | 133 项组合、565 项非 live 回归通过；4 项 live 未运行，边界保留 |
| M11 | 2026-09-28 启动；2026-09-29 本地范围归档 | completed（本地交付范围） | compatible read/session/isolation/path/remote restart 与 4 项 live tests 有用户实测；D1–D3 后置；telemetry 实际文件手工脱敏查询未留存 |

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

## M10 — 远程协议与客户端/服务端（已交付离线本机范围归档）

以下逐片文字保留当时的停点和“等待验收”语境；当前状态与最终测试数以 [M10 归档](docs/acceptance/M10.md) 为准。

2026-09-24 用户选择推进 M10，并要求先做好分片计划。贯穿请求沿用“请读取 probe.txt 并总结”，从另一个进程经过认证、协议、会话协调进入已有 async tool graph，再返回进展与服务端快照。启动时的缺口位于图外接入边界：既有 CLI 能调用会话运行器，但没有远程请求关联、连接生命周期和客户端状态契约。

本次读取 Pi 固定提交的 `protocol/framing.ts`、`schemas.ts`、`codec.ts`、`server/server.ts`、`sessions.ts`、`types.ts`、`connection.ts`、`snapshots.ts`、Unix listener，以及 `client/client.ts`、`connection.ts`、`state.ts`。确认设计主线为有界帧 → 严格消息 → 已授权连接上的版本握手 → 运行接口 → 权威快照 → 客户端按请求 ID/command 完成等待。认证 token、JSON/TCP、server epoch 与具体预算属于本项目选择，不宣称原样复制 Pi。源码链接、调用链和映射见 [M10 设计](docs/design/M10.md)。

待掌握的知识依次是：字节流的分片/粘包、边界类型校验、认证与握手状态机、图外运行端口、单会话并发与 task 所有权、request/run/session 标识、断线结果未知和快照版本。已有 LangGraph state/reducer/checkpointer 继续服务模型循环；连接状态不进入 AgentState，网络请求 ID 不充当持久幂等键。

计划决定：单主体、本机 TCP、长度前缀 + JSON、认证前置；服务端固定 workspace/database/model，只注册 read/list/search。将当前 `cli/runtime.py` 的公共装配和 `cli/read_only.py` 的路径过滤提取到运行边界，保留 CLI 包装与 M9 hooks；快照显式投影，不能直接序列化 checkpoint 或宽泛 StreamEvent payload。同 session 冲突立即 busy；断线取消拥有的 run 并等待清理；未完成 checkpoint 标记 needs_recovery，不自动重放。客户端重新连接先取快照，新 server epoch 重置 revision 比较。

分片为 M10.1 帧、M10.2 DTO/codec、M10.3 认证与 transport、M10.4 公共运行器/快照、M10.5 会话并发/取消、M10.6 服务端派发、M10.7 客户端、M10.8 公开入口与组合验收。每片最多一个学习者核心 TODO。2026-09-24 完成 M10.1：创建 `protocol/errors.py`、`protocol/framing.py` 和 `tests/protocol/test_framing.py`；学习者实现 `FrameDecoder.feed()` 的增量拆分/组装。对应 Pi 设计是固定提交 `packages/protocol/src/framing.ts::FrameDecoder.push()/end()`；Python 侧协议状态留在图外，不进入 AgentState。

同一请求的当前路径是：`encode_frame(prompt)` 得到长度前缀字节 → TCP 任意切块 → `FrameDecoder.feed()` 应逐次积累头/正文并在完成时返回 payload → 后续 M10.2 才将 payload 解成 command。坏头长度或零长度帧必须立刻把 decoder 置为 failed 并清空部分数据；EOF 带残余字节则是截断错误；完整结束后再次 feed 必须报 ended。测试分别保护拆包/粘包顺序、UTF-8 byte 长度、上限、截断和终态。

实现前，同一 `R1` 还没有稳定边界：TCP 将它拆开时，每次 read 都可能是不完整的头/正文。实现后，任意分块的帧会被重组成 payload，非法长度无需等待正文便会失败；贯穿请求现在推进到 M10.1 输出的完整 payload，下一片 M10.2 才将它解释为可信 DTO，尚未进入服务端或 Agent 图。审查确认实现先积累四字节大端头，再校验长度，只缓存已到达的正文，完成一帧后按顺序继续处理粘连帧；失败清理头/正文/期望长度并锁定 failed 状态，EOF 残帧报截断。测试覆盖分块、粘连、UTF-8 字节数、零/超限、截断和 ended/failed 状态。

实际验证：用户报告的命令与本地复跑一致，`uv run pytest tests/protocol/test_framing.py -q --basetemp=.pytest-tmp-m101` 为 **24 passed**；当时 `uv run mypy src tests` 检查 207 个文件通过；`uv run ruff check .` 通过；`uv run ruff format --check .` 检查 248 个文件通过。M10.1 标记 completed，随后 M10.2 进入并完成，M10 整体继续 in_progress。

### M10.2 — 版本化 DTO 与严格 codec（已完成，等待用户验收）

本片接收 M10.1 已还原的完整 JSON payload，将“字节完整”推进到“结构可信”；仍未认证、未派发，也不能直接进入 Agent 图。Pi 对应固定提交中的 `packages/protocol/src/schemas.ts` 与 `codec.ts`：消息按方向和判别字段验证，序列化边界使用 DTO，而不是把运行时对象泄漏到 wire。Python 侧用严格、冻结、禁止额外字段的 Pydantic models 表达 hello、四个命令、response、event 和快照；client/server 消息维持不同解析方向。

设计决策：JSON helper 先拒绝越界大小、非法 UTF-8、语法错误、重复 key 和 NaN/Infinity，再调用 TypeAdapter；对外统一抛安全 `ProtocolValidationError`，不回显 payload 或 Pydantic 的 input。unknown integer hello version（包括较大的非负整数）通过 DTO，留给握手层判定 `unsupported_version`；string/bool/负数是结构错误。request ID 仍是严格正整数并受 `2**63-1` 上限约束。展示文本上限按 UTF-8 byte 而不是 Python 字符数计算，response 成功标志和错误对象必须一致。

脚手架与证据：新增 `protocol/messages.py`、`codec.py` 和 `tests/protocol/test_messages.py`、`test_codec.py`；扩展 `ProtocolValidationError`。学习者提交的 `decode_client_message(payload: bytes) -> ClientMessage` 依次串接 `_load_json_payload()` 与 `CLIENT_MESSAGE_ADAPTER`，未重写安全 helper。审查确认非法 UTF-8/JSON、重复 key、非有限数和模型校验错误最终统一映射为固定安全异常；未知非负整数版本保留给握手，错误方向不会进入 ClientMessage。此前 50 passed、12 TODO failures 是脚手架阶段结果；实现后用户报告且本地复跑 `uv run pytest tests/protocol -q --basetemp=.pytest-tmp-m102` 为 **62 passed**。`uv run mypy src tests` 检查 211 个文件通过；`uv run ruff check .` 通过；`uv run ruff format --check .` 检查 252 个文件通过。

本片掌握了严格 DTO 与判别联合、Python `bool` 是 `int` 子类但协议不能因此接受 bool、UTF-8 字节预算、重复 JSON key 的解析行为，以及“未知版本”和“非法结构”的分层。回到整体看，同一 prompt 现在可从 TCP 分块经 M10.1 frame 重组，再由 M10.2 转成可信 ClientHello/ClientRequest；它仍不能越过认证或握手，也尚未抵达 server dispatcher/Agent graph。下一片 M10.3 才建立认证前置的字节连接；当前等待用户验收，不自动启动下一片。

### M10.3 — 认证前置的字节连接（已完成，等待用户验收）

贯穿路径从 M10.1 的 `FrameDecoder` 和 M10.2 的严格 DTO 往前一步：client connector 打开 loopback TCP 后先发送独立认证前导，server 在任何业务 callback 前验证 token；同一 TCP 连接中紧随其后的 hello 字节留在同一个 `StreamReader` 缓冲区，认证 gate 不得误读或丢弃。凭据缺失、错 token、超限长度、EOF/超时都必须 fail-closed，不能调用业务回调或返回 session 内容。M10.3 完成后也仍未握手派发或进入 graph。

Pi 的 `packages/server/src/connection.ts` 将 ByteConnection 定义为已授权连接，listener 管 socket 生命周期；本项目的 bearer token 前导和 loopback TCP 是针对 Windows/单信任主体的本地设计，不声称 Pi 使用同一认证方式。`protocol/transport.py` 定义 AsyncByteConnection 与 asyncio stream adapter：单 reader 约定、write lock、有界待发字节、send deadline、幂等 close；`server/transports/tcp.py` 管 loopback listener、活动连接/handler task 和 shutdown；`client/transport.py` 从 `PI_AGENT_REMOTE_TOKEN` 取 token 并先发认证前导。认证配置缺失在 bind 前失败。

唯一学习者练习是 `server/auth.py::authenticate_connection(reader, expected_token, *, timeout_seconds) -> bool`。输入是连接的 `asyncio.StreamReader` 与已校验 token bytes；输出仅为是否认证成功。必须在 deadline 内恰好读取 4 字节大端长度，调用 `decode_auth_length()` 在读 body 前限制 token 到 4 KiB，再 `readexactly(length)` 并用 `hmac.compare_digest()` 比较；格式错、截断、超时或不匹配返回 False。禁止读取前导之外的数据，禁止发送失败响应或记录 token。`tests/server/test_auth.py` 检查 auth+hello+业务字节同批送达时尾部完整保留、长度/EOF/错 token 与超时 fail-closed；`test_tcp_transport.py` 检查 business callback 前置 gate、loopback、并发写、慢发送端 deadline 与关闭；`tests/client/test_transport.py` 检查客户端环境 token 与先发 auth。

实际验证：学习者实现 `authenticate_connection()` 后，完整切片命令 `uv run pytest tests/server/test_auth.py tests/server/test_tcp_transport.py tests/client/test_transport.py -q --basetemp=.pytest-tmp-m103` 为 **16 passed**；`uv run mypy src tests` 检查 221 个文件、Ruff lint 与 format 检查 262 个文件全部通过。复验时发现 auth 中文注释的全角标点违反 Ruff 规则，改用 ASCII 分隔符后门禁全绿。用户另外报告 `uv run pytest tests/server -q --basetemp=.pytest-tmp-m102` 为 **14 passed**。原始 10 passed/6 failed 是 TODO 阶段结果，不代表最终验证。

知识重点是 `StreamReader.readexactly()` 如何只消费认证前导并保留其缓冲尾部，超时作用域为什么要同时覆盖长度与正文，Python `bytes` constant-time compare 的责任，writer 并发与背压的区别，以及 close/abort 的资源所有权。贯穿请求现在到达认证 byte connection；M10.4 从 CLI 抽公共运行器与快照投影，M10.5 管 run ownership，M10.6 再把认证后连接接到握手和 dispatcher。

遗留与下一步：M10.3 无未关闭门禁；下一步是完成 M10.4 `project_session_snapshot()` 并运行完整切片验证。SQLite 跨连接事务、分布式所有权、跨重启 exactly-once、多租户/TLS、公网部署和完整 Pi lease 均不包含在本阶段；同步文件 I/O 的线程取消不能被描述为 OS 强制中断。M8/M9 原有开放边界继续留在各自记录。

### M10.4 — 公共运行器与安全快照（已完成）

整体路径现已越过 M10.3 认证连接，server 可经 `ServerSessionRuntime` 使用非 CLI `SessionRuntimeConfig` 进入已有 async tool graph。`runtime/session.py` 注入 model、hooks、run id、取消 token、workspace 与 SQLite；`runtime/read_only.py` 持有 read-only 路径策略和工具构造，`cli/read_only.py` 保留兼容包装。M10.4 对应 Pi 的 `packages/server/src/types.ts::PiSessionRuntime` 与 `sessions.ts` 调用链：应用边界负责装配运行能力，协议 DTO 与 graph state 保持分离。

唯一练习是 `server/snapshots.py::project_session_snapshot(...) -> SessionSnapshot`。输入包括 LangGraph `StateSnapshot` 和 server 自有 revision/run 字段，输出只允许 session/epoch/revision、checkpoint id、四态 graph status、run 字段、数量、有限 display messages 与 truncated。映射 Human/AI/Tool 角色和纯文本；过滤 system/structured content；最近 20 条、单条 8 KiB、总计 128 KiB；partial state 不伪造 completed；不得暴露 raw config/provider metadata。测试串联真实临时文件 read → ToolMessage → reply，并验证 server runtime 重开 SQLite、私有字段过滤和长历史预算。

最终验证：计划命令 **71 passed**；`uv run mypy src tests` 检查 227 个文件通过；Ruff lint 通过；format 检查 268 个文件通过。复审发现 `cli/read_only.py` 为异步 registry 重复追加 `propose_command`，已有 CLI 测试未覆盖 enabled 分支；删除重复追加并新增 `test_cli_async_registry_registers_command_proposal_once_when_enabled` 后全套回归通过。另增加 server runtime 的 hook thread/run correlation 断言。snapshot 按最新消息优先选择，系统/非文本消息不出网并置 `truncated`，per-message 和 128 KiB 总预算均由测试覆盖。早期 TODO 阶段的 65 passed/4 failed 与 scaffold Ruff 错误均已修复，不作为最终结果。

设计决策：共享只读注册表从 CLI 提取并让 CLI 保留原有薄包装；server 绝不导入 `pi_agent.cli`。snapshot 从 checkpoint 只读取投影所需字段，不能直接 JSON 化 LangGraph 对象；展示预算使用 UTF-8 字节，截断必须显式。M10.4 已通过计划验证，用户授权进入 M10.5。

### M10.5 — 会话运行所有权与取消（已完成）

M10.4 已让 server 进入共享 async graph；本片处理同一 session 上两个 prompt 同时到达的竞争。以具体场景说明：S 的 `run-1` 已启动 read/model，而第二个 prompt 到达 S 时必须立即得到 busy；T 上的 prompt 仍可独立启动。client 用旧 `run_id` 取消时不得影响当前 run；取消当前 run 时需要请求 token 与 task cancel，并 join 清理。若清理时间超过上限，S 继续 busy；新 server process 看见 pending checkpoint 时返回 `needs_recovery`，不自动重放。

Pi pinned `packages/server/src/sessions.ts` 的 `LiveSessionManager` 通过 `LiveSession.operationCount` 追踪正在执行的调用，`runOperation()` 在 `finally` 中扣减计数；`maybeDispose()` 只有连接/操作归零且 phase 可释放时才 dispose runtime。Python 重写把 M10.5 核心收窄为同 session 唯一 `RunLease`：进程内同步 check-and-set 是单 event loop 原子边界，LangGraph 仍负责节点与 checkpoint，server coordinator 负责 task ownership/取消/清理。它不构成跨进程租约。

学习者实现 `src/pi_agent/server/sessions.py::SessionCoordinator.try_claim_run(session_id, run_id) -> RunLease`：拒绝空/无效 ID；同步检查并登记同 session lease，不覆盖当前运行；不同 session 各自独立。回到整体请求场景，S 上第二个 prompt 在模型重入前失败为 busy，T 可以领取自己的 lease；成功、失败和取消的 ownership 均在 task 真正结束后释放。旧 run ID 不能取消当前 task；cleanup 超时期间 S 仍 busy；重启后 pending checkpoint 只投影 `needs_recovery`，不重放 graph。

验证：计划命令 `uv run pytest tests/server/test_sessions.py tests/server/test_cancellation.py -q --basetemp=.pytest-tmp-m105` **7 passed**；`uv run mypy src tests` 检查 **230 source files** 通过；`uv run ruff check .` 通过；`uv run ruff format --check .` 检查 **271 files** 通过。首次复验指出学习者注释中的全角标点和格式问题，修复后完整重跑全绿。用户另报告 `uv run pytest tests/server -q --basetemp=.pytest-tmp-m102` **26 passed**。

知识总结与设计决策：单 event loop 中不含 `await` 的 check-and-set 是本片进程内领取边界；lease 同时关联 session、run、cancellation token 和 task；取消 token 让协作式逻辑观察取消，`Task.cancel()` 让 asyncio task 进入取消路径，随后必须有界 join。不能因为 cancel 请求已发出就提前开放 session，task 尚未退出时要继续保持 busy。checkpoint 持久化与内存 lease 分属不同生命周期；恢复判断不等于安全重放。epoch/revision 由 M10.4 快照边界持有，本片仅保证每 session 一个活动 run；全局连接/run 预算在 M10.6 派发边界应用。未解决边界是跨进程互斥/exactly-once 不在本切片范围内。

贯穿链路现在从帧、DTO、认证连接、共享 graph runtime 延伸到 session run ownership；连接尚未经过 hello 握手和命令 dispatcher。下一片 M10.6 会把 request ID、协议状态机和本片 coordinator 接起来。本片已完成并停在 M10.5 等待验收，不自动开始 M10.6。

### M10.6 — 服务端协议派发（已完成，等待验收）

贯穿场景继续为客户端 request `R1`: `prompt(S, "读取 probe.txt 并总结")`。M10.3 的 TCP handler 已将认证完成的 `AsyncByteConnection` 交给上层，但此前没有业务 reader；M10.6 新增 `ServerConnection` 作为唯一 reader，解帧并验证 `ClientMessage`，必须先接受版本 1 `hello` 才切换至 `ready`。随后它为每个递增 request ID 建立独立 dispatch task，统一发送 event/response；dispatcher 调 `ServerCommandService`，再接到 M10.5 coordinator 与 M10.4 runtime。完成时 `run_started(R1,U1)` 先关联原请求，最终只有一个 response(R1,prompt)；乱序完成不能串 ID。

Pi 设计对照是固定源码基线 `earendil-works/pi@96317e50b8d6e7f6d0e47fd29122baf1461c00f5` 的 `packages/server/src/server.ts::receive → dispatchMessage → finishHandshake/handleRequest`、`packages/server/src/sessions.ts::executeCommand/runOperation` 和 `packages/protocol` 严格 envelope。Python 将 Pi 的 CBOR 换成本项目已经实现的长度前缀 JSON DTO；保留握手门禁、消息关联与执行边界，丢弃完整 attach/steer/lease API。LangGraph 不接管 socket、request ID 或连接 phase，它只管理已有 graph、工具、状态 reducer 与 checkpoint。

只实现 `src/pi_agent/server/dispatcher.py::ServerDispatcher.dispatch_message(request: ClientRequest, *, send_event: EventSender) -> ServerResponse`。输入是已完成 DTO 校验且通过 ready/request ID 门禁的请求；四种变体分别调用 `create_session()`、`get_snapshot(session_id)`、`prompt(session_id,text,request_id,send_event)`、`cancel(session_id,run_id)`。返回必须使用同一 `request_id` 和 command；把 `ServerCommandFailure` 变为其安全的 `ProtocolError`，意外异常映射为不含异常文本的通用 `internal_error`。prompt 必须透传 run_started event，最终只返回一个 response。不要改连接状态机、service 和协议 DTO，也不要添加第二个 TODO。

测试脚手架 `tests/server/test_dispatcher.py` 校验四命令与事件/错误语义；`tests/server/test_protocol.py` 校验 hello 顺序/版本、重复 hello 和 request ID、乱序关联、在途上限及断开清理。学习者完成 `dispatch_message()` 后，审查补充发现关闭流程在等待已有 run cleanup 时，另一在途请求可能晚注册运行。`ServerConnection._send_request_event()` 现在在 closing/closed 时拒绝 event，并通过定时序竞态测试证明第二个 prompt 不会在清理快照后继续启动。

最终验证（2026-09-28）：`uv run pytest tests/protocol tests/server -q --basetemp=.pytest-tmp-m106` **104 passed**；`uv run mypy src tests` 检查 **234 source files** 通过；`uv run ruff check .` 通过；`uv run ruff format --check .` 检查 **275 files** 通过。期间新增测试首次触发 mypy 的属性窄化错误；改用字符串化状态断言后，四项完整命令均重新通过。

知识总结与设计决策：网络连接 phase、单连接 request ID、session run ID 分属连接、请求和运行三个生命周期，不能互换。连接持有单一 reader 与统一 writer；每个请求用独立 task 支持乱序结束，response 始终回填 command 和 request ID；prompt event 先关联原 request，再由 service/coordinator 建立 session run ownership。dispatcher 负责命令路由和安全错误边界；LangGraph 仍只负责图状态、工具循环与 checkpoint。shutdown 竞态的关键是 closing 状态要在任何 await 前阻止新 owner 注册，否则先取消运行快照再 join 请求任务会遗漏正在启动的 prompt。

回到整体：`hello(v1) → request(prompt,S,R1) → run_started(R1,U1) → coordinator/runtime → response(R1,prompt,snapshot)` 现在可在协议/服务端切片中完整流转；握手前请求、版本错误、重复 ID、过载、模型错误和断线均有明确失败边界。改动落在 `server/connection.py`（协议状态/传输接收与清理）、`server/dispatcher.py`（命令/服务边界）、`tests/server`（路由与生命周期证据）和三份状态/教学文档。未解决项是 M10 整体客户端/公开入口/重连组合验收尚未实现，且 loopback/单进程 coordinator 不等于分布式租约。用户随后授权 M10.7，当前切片负责客户端 pending response 与权威快照状态。

### M10.7 — 最小客户端与权威快照（已完成，等待用户验收）

**全链路位置**：服务端接收并处理 request 的能力已由 M10.6 接通；客户端从已经认证的 byte stream 发 v1 hello，随后把 `create_session/get_snapshot/prompt/cancel` 编码为 request。接收循环把 response/event 交给客户端状态层。本片前，缺少 response ID 到等待调用的映射，客户端无法安全并行发请求，也没有 epoch/revision 规则保护缓存。

**贯穿场景**：同一个 `R1 = prompt(S, “读取 probe.txt 并总结”)`。客户端发出 R1 前先创建 pending future 并登记 request ID；再并发发出查询 `R2 = get_snapshot(S)`。服务器可先回 R2 后回 R1，客户端按各自 ID 完成 future 并核对 command。成功 response snapshot 才更新本地 authority；断线时等待中的请求成为 `RequestOutcomeUnknownError`，旧 snapshot 保留显示但标记 stale；重连的本地 connection generation 丢弃旧连接迟到事件，新 server epoch 则清空旧 revision 比较基线。

**Pi → Python/LangGraph**：Pi `packages/client/src/client.ts` 的 `#request()` 先把 pending entry 放入 Map 再写 frame；`#handleMessage()` 取出对应 pending、核对 command、应用结果后完成 Promise；`#handleConnectionStateChange()` 断开时拒绝所有 pending。Pi `ClientState` 维护 server snapshot 与事件投影。Python 用 `asyncio.Future`、字典和 JSON DTO 实现相同的 client 应用边界；protocol client/connection 不进入 LangGraph State，LangGraph 仍限于服务端图和 checkpoint。保留 ID/command 校验及权威快照，不实现 Pi 完整 session lease API。

**脚手架与范围**：`client/connection.py` 有 hello 握手、单 receive loop 和 frame 编解码；`client/client.py` 提供四个公共 async 方法、请求 deadline 和 pending 表；`client/state.py` 管 connection generation、server epoch、snapshot revision 与 stale 标记；`client/errors.py` 定义 disconnect/outcome unknown/protocol/server error。`tests/client/test_connection.py` 保护握手和错误方向；`test_state.py` 保护 revision、epoch、stale 和 generation；`test_requests.py` 保护乱序 ID、command mismatch、server error、未知/重复响应和 timeout/disconnect。

**学习者实现复盘**：完成 `src/pi_agent/client/client.py::RemoteClient.resolve_response(response: ServerResponse, *, connection_generation: int) -> None`。实现先以 generation fence 丢弃旧连接响应，再依 request ID 取出 pending 并验证 command；唯一响应负责结算 Future，未知/重复 ID 和 command mismatch 通过 `ClientConnection.fail(ClientProtocolError(...))` 关闭当前连接。安全 server error 映射为 `ServerRejectedError`；成功响应应用 snapshot 后 resolve Future。没有自动重试，也没有把 progress event 当作权威快照。

**验证结果**：用户执行 `uv run pytest tests/client -q --basetemp=.pytest-tmp-m107-final` **17 passed**；复核 client **17 passed**，完整 protocol **63 passed**；`uv run mypy src tests` 检查 241 个源码文件通过；Ruff lint、282 文件 format-check 和 `git diff --check` 通过。测试覆盖乱序 response、prompt/cancel、错误映射、未知/重复 ID、断线/timeout、generation fencing 与 snapshot revision/epoch 规则。DTO 的 JSON array→tuple 归一化由 codec round-trip 测试保护。

**设计重点与边界**：request ID 是一次连接会话中的 response key；connection generation 是客户端本地 fencing token；server epoch 表示服务端进程 incarnation；snapshot revision 只在同一 server epoch 内单调比较。四者用途不同。断线或 timeout 只能说明结果未观察到，不证明服务端没有执行，因此必须标为 outcome unknown 且禁止自动重放。本片不做自动重连、请求重放、完整订阅/lease 语义或公开 CLI；这些与后续 M10.8 组合验收区分。

**回到整体**：认证 byte stream 已进入 client hello/单 receive loop；四类 request 可乱序应答但按 ID 回到正确调用；快照只由成功 response/snapshot event 进入缓存，断线标记 stale，服务端 epoch 变化时重置 revision 比较基线。文件落在 `client/connection.py`、`client/client.py`、`client/state.py`、`client/errors.py` 和 `tests/client`，协议 wire JSON 保持独立。未覆盖真实 TCP 组合、公开 CLI、自动重连以及跨进程 lease/exactly-once；这些属于 M10.8 或后续系统边界。M10.7 已完成计划验证并停在这里等待用户验收，不自动进入 M10.8。

### M10.8 — 公开入口与组合验收（已完成，纳入 M10 归档）

**全链路位置**：M10.1–M10.7 已分别接通 frame/DTO、auth transport、server runtime 与 session ownership、dispatcher、client pending 和快照。M10.8 启动前的断点位于 composition root 和可执行入口：尚不能以两个公开进程启动 server/client，也没有用同一行为案例证明 memory/TCP、真实子进程、SQLite 重启与关闭资源之间的组合契约。M10.8 已闭合这一断点；M11 才做全局架构复盘。

**贯穿场景**：在合成 workspace 写入 `probe.txt`；`pi-agent-server --provider fake` 启动 loopback listener；独立 client 创建 session、prompt 读取并总结文件。关闭 server 后复用 database 与 session ID 重启，再经 client 查询 snapshot 并发送续聊；读取历史应仍在 checkpoint 中，查询本身不得重放前一轮。错误 token/协议版本或坏帧必须失败关闭；shutdown 要退出并回收 connection handler task 和模型资源。

**Pi → Python/LangGraph**：Pi [`server.ts::Server`](https://github.com/earendil-works/pi/blob/96317e50b8d6e7f6d0e47fd29122baf1461c00f5/packages/server/src/server.ts) 的 start/accept/close 控制 listeners、connection 和 session router；[`client.ts::PiClient`](https://github.com/earendil-works/pi/blob/96317e50b8d6e7f6d0e47fd29122baf1461c00f5/packages/client/src/client.ts) 的 `#request()`/`#handleMessage()` 将 public API 请求和 response ID/pending map 关联；[client README](https://github.com/earendil-works/pi/blob/96317e50b8d6e7f6d0e47fd29122baf1461c00f5/packages/client/README.md) 强调 transport-neutral byte port。固定 SHA GitHub 页面本轮返回 cache miss；源码行为对照了上游 main 页面，不能把 main 冒充固定基线。

Python composition root 把 server-owned model、workspace、SQLite catalog、coordinator 和 `ServerDispatcher` 注入 `TcpByteServer`/`ServerConnection`；LangGraph 只在已有 `ServerSessionRuntime` 内运行，不接管网络生命周期。client CLI 则把解析后的参数映射到 M10.7 `RemoteClient`，connection close 由入口的 `finally` 所有。保留 Pi 的服务端/客户端/transport 分层，采用 loopback token-authenticated TCP 与本项目 strict JSON，不实现 Pi 的 session lease/attach 扩展。

**知识总结**：composition root 是应用配置和对象图的边界，不是新增 Agent node；API key/token 只能从环境变量读取，不能作为 argv、快照、日志或错误正文。内存与 TCP conformance 复用相同 server `ServerConnection` 和 dispatcher 案例，区分协议逻辑和 socket 适配器。真实 subprocess smoke 补上单进程 fixture 无法证明的信号处理、退出状态、独立环境和 checkpoint reopen；本地 localhost 结果不等于外网部署安全。

**练习复盘**：学习者实现了 `src/pi_agent/client/app.py::dispatch_command(client: RemoteClient, args: argparse.Namespace) -> SessionSnapshot`。参数来自 `build_parser()` 的 create/snapshot/prompt/cancel 子命令，函数将其分别映射到 `create_session()`、`get_snapshot(args.session_id)`、`prompt(args.session_id, args.text)`、`cancel(args.session_id, args.run_id)` 并返回最终 snapshot。连接生命周期、JSON 输出和异常边界仍由 `run_cli()` 负责。四条 CLI 路由、finally-close 与真实子进程 create→read prompt→server restart→snapshot smoke 均通过。

**脚手架、测试与实际验证**：`server/app.py` 负责模型/config/catalog/coordinator/runtime/dispatcher/TCP 组装、信号和资源清理；`client/app.py` 负责 argparse、connector、四命令映射、JSON 输出和 finally-close。`tests/server/test_app.py` 覆盖真实 loopback read + SQLite reopen/续聊；`test_conformance.py` 对同一 create/prompt/snapshot 场景分别使用 memory 与 localhost TCP；`test_subprocess_smoke.py` 启动公开入口并复用数据库；`tests/client/test_app.py` 锁定 CLI 分派。

- `uv sync --all-extras --offline`：本地设置临时 `UV_CACHE_DIR` 后通过；2026-09-28 用户在 PowerShell 默认环境复验也成功（Resolved 56 packages、Audited 54 packages）。
- `uv run pi-agent-server --help` 与 `uv run pi-agent-client --help`：本地与用户 PowerShell 实测均通过；输出包含预期 server 参数及 create/snapshot/prompt/cancel client 子命令。
- `uv run pytest tests/client/test_app.py tests/server/test_subprocess_smoke.py -q --basetemp=.pytest-tmp-m108-dispatch-review`：**6 passed**；命令路由、连接清理和公开子进程重启场景通过。
- 归档复验前 `uv run pytest tests/protocol tests/server tests/client -q --basetemp=.pytest-tmp-m108-combined-review` 为 **131 passed**；全仓非 live 为 **563 passed、4 deselected**。
- 归档审查发现完成/取消交界与服务端日志检查缺少直接证据：`SessionCoordinator.cancel_run()` 现在先识别已完成 task，返回 `not_found` 且不改写取消状态；子进程 smoke 在服务端退出后检查 stdout/stderr 不含合成 token、请求文本或文件正文。针对测试 **5 passed**。
- 归档关机审查又发现 `TcpByteServer.close()` 对 handler/listener 清理超时可能静默返回；现关闭连接后等待所有 handler 与 listener，超时明确失败，不把残留 task 当作成功关闭。transport 目标测试 **8 passed**。最终计划组合 `uv run pytest tests/protocol tests/server tests/client -q --basetemp=.pytest-tmp-m10-archive-combined-final`：**133 passed**；全仓 `uv run pytest -q -m 'not live' --basetemp=.pytest-tmp-m10-regression-final`：**565 passed、4 deselected**。
- `uv sync --all-extras`：通过（56 packages resolved、54 audited）；`pi-agent-server --help` 和 `pi-agent-client --help` 用户实测通过。
- `uv run mypy src tests`：用户实测 **247 source files** 通过；`uv run ruff check .` 通过；`uv run ruff format --check .` **289 files** 已格式化。
- `uv run pi-agent --provider fake --prompt hello --events jsonl`：通过，输出 assistant fake reply 与 completed 状态。
- `uv run pi-agent eval --suite smoke --provider fake`：通过，1/1 case passed。
- `git diff --check`：通过；pytest cache 有权限警告，不影响测试结果。

**设计重点、未决边界与下一步**：session ID/data 由 server catalog/checkpoint 持有，client 只传业务命令；重启换 server epoch，但 SQLite checkpoint 延续。fake server 模型固定发起 `read(probe.txt)` 再给 deterministic summary，只为离线组合验收，不证明真实模型质量。完成与取消相遇时，以 `task.done()` 的事实防止将已完成 run 误报取消；进程日志检查覆盖服务端 stdout/stderr，客户端 stdout/stderr 检查 token。关机超时必须向上报告失败，不能把仍在运行的 handler 当作已回收。外网、跨进程 lease/exactly-once、真实 compatible 模型质量与 M11 threat/performance audit 仍是范围外事项。M10 已按已交付范围归档，下一步由用户决定是否启动 M11。

## M11 — 全链路验收与架构复盘（已归档：本地交付范围）

启动日期：2026-09-28；2026-09-29 用户验收并归档本地交付范围。用户选择“保留一个核心练习，按引导式推进”，由学习者完成 M11.1 核心轨迹投影；随后按计划推进剩余切片。教学见 [M11 设计](docs/design/M11.md)，架构复盘见 [M11 架构](docs/architecture/M11.md)，结果统一记录在 [M11 归档](docs/acceptance/M11.md) 与[真实模型手工执行记录](docs/acceptance/M11-real-provider-manual.md)。

从整体看，已有链路是入口 → session/thread → 上下文 → model/tools 循环 → SQLite → 事件/快照。M11 加的是验收证据：同一“读取 probe.txt 并总结”必须同时证明工具真的返回、结果回灌、终态完成和观察轨迹正确。仅有 assistant tool call 或完成状态不够。M9 原 `_tool_names()` 猜测 StreamEvent 中存在 `tool_names/tool_name`，实际通用更新投影不提供这些字段；原 smoke 没有工具，无法揭示这个缺口。

Pi 固定提交的 `runLoop → streamAssistantResponse → executeToolCalls → emitToolExecutionEnd` 本轮从 GitHub 源码核对；上下文变换先于模型转换，工具结果回到循环，执行结束事件包含 call ID 和结果。Python 保留这些因果边界，用 StateGraph 节点/条件边表达循环，以现有 `after_tool` HookEvent 提供元数据。LangGraph checkpoint 管 thread 内图状态；hook、连接、task ownership、外部副作用去重仍由应用管理。官方 persistence 文档与本地实现已核对，未变更依赖。

M11.1 的 `cli/eval_tools.py` 是应用脚手架：独立临时工作区与数据库、确定性 fake 请求 list/read、真实工具及 ToolMessage 回灌、完整消费 async stream、关闭清理。`evals/tool_trace.py` 是学习者纯函数：只取成功 after_tool，按 `(thread_id, run_id, tool_call_id)` 去重，保留到达顺序和不同调用的同名工具。`EvalHarness` 继续负责实际观察与独立期望比较，JSON 报告不保存正文或运行身份。移除旧的无证据字段提取入口，不改通用事件 DTO。

测试保护三层：场景测试独立证明真实工具和 run_end；投影测试保护成功筛选、调用身份、顺序与不可变输入；公开 eval CLI 测试要求 tools suite 重复输出一致、1/1 成功且无正文。首次基线 565 passed、4 个 live gate skipped，覆盖率 84%；脚手架全仓为 567 passed、6 failed、4 skipped、84%，eval 子集 5 passed、6 failed。失败来自唯一 TODO，未视作通过。完整计划门禁已执行：依赖同步、mypy（src 125 / src+tests 251）、lint、295 文件格式检查、fake run 和 smoke CLI 通过；tools CLI 返回 1。文档代码块格式失败已修复，SQLite 三个资源 warning 保留待查。详细结果以验收文件为准。

练习复核：学习者报告 `pytest tests/evals` **11 passed**，tools CLI **1/1**。本地复跑一致；成功轨迹来自 `after_tool`，同一 thread/run/call 去重，不合并不同调用的同名工具。

M11.2 已实现公开 compatible CLI telemetry opt-in：`--telemetry-file` 使用工作区内 JSONL sink，接入 lifecycle root/child spans、低基数 phase/outcome metrics 与只含标识的 logs。公开入口测试以合成 provider client 驱动真实 read 工具和 SQLite，检查同 trace parent、结束 outcome、凭据/正文脱敏、client 关闭与非法路径在 provider client 创建前拒绝。M11.2 组合 **45 passed**，mypy **255 source files**、Ruff lint、299 文件格式均通过。sink 使用同步逐条追加，未证明高负载性能、跨进程写原子性、轮转和实际遥测后端兼容。

M11.3 复盘与决策：性能脚本启动 loopback authenticated client/server，以 fake model 实际发起只读 read 工具；预热 1 次、测量 5 次，记录 OS/Python 和 min/median/p95/max/mean。2026-09-28 Windows 11 / Python 3.13.5 的样本 median 为 53.115 ms、p95 为 55.049 ms；样本量小，仅作可复现本机参考，不是 SLA。全量 tracemalloc warnings-as-errors 复测定位出 `tests/sessions/test_metadata.py` 与 `test_metadata_recovery.py` 三处连接创建；SQLite connection 的 context manager 管事务但不会自动 close，修复为 `contextlib.closing` 外包原 transaction context。CI 已配置 Ubuntu/Windows × Python 3.11/3.12，但未取得任一新环境 runner 的实际结果。

M11.4 已补齐全链路架构图、Pi 源码因果映射、LangGraph/checkpointer 与应用生命周期边界、资产/威胁/现有控制/责任人表、生产差距、陌生 Agent 源码分析步骤和架构评审 checklist，见 [M11 架构复盘](docs/architecture/M11.md)。本地门禁完成后于 2026-09-29 由用户验收并归档本地交付范围；Windows/Ubuntu 新环境 CI job 仍无成功结果。真实模型质量、公网部署安全、跨进程 exactly-once 仍未由本次验收证明。

用户实测与归档（2026-09-29）：compatible CLI 的实际 `read` 返回 `M11-PROBE-001` 并完成回答；同一 SQLite 会话在文件更新后回忆旧 marker，新 session 未继承旧轮次；错误相对路径的首次测试只证明目标不存在，不能证明 confinement，修正为 `../out-workspace/outside.txt` 后实际 read 收到 `Resolved path is outside the workspace root.`；本机 server/client 的 `create → prompt/read → snapshot` 成功，服务端重启后 epoch 改变而同 session、checkpoint 和 4 条消息保留。`tests/live/test_provider_smoke.py` 用户运行结果为 **4 passed in 8.14s**。这些结果支持当前 Windows 本机和该 compatible 端点，不外推到部署环境或其他模型。真实 telemetry JSONL 的 marker/prompt/API key 检查和用例 0 的独立配置投影未见用户输出，因此保留为未单独核实的证据点；代码层的 telemetry redaction tests 已通过。

归档边界：新环境 Windows、新环境 Linux、目标部署环境的真实服务验证仍为 D1–D3，延期不等于通过，未来须分别取得环境/部署实测证据。同步 JSONL 写入的负载、轮转、跨进程写协调，远程公网安全、跨进程 lease/exactly-once 和副作用工具也没有被本次本地验收关闭。

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
| M9 归档后 / M11 | 真实模型质量、独立环境/部署与 telemetry 负载边界 | M11 已完成本地 tools eval、CLI telemetry、性能样本与架构复盘；后置项按 [M11 验收](docs/acceptance/M11.md) 跟踪 |

## 本次整理记录与后续写法

2026-09-18：按用户要求归档 M5 已交付版本。将原来落在 M4 下的 M5 记录分离；把反复追加的“当前下一步”和脚手架红灯移入历史快照；统一里程碑标题与时间线；保留原始验收要求，并登记新发现的缺口。本次无业务代码或测试改动。

2026-09-21：修复并复验 M5-R1–R4。同步 fake-provider 教学范围完整通过；真实 provider/tool 的异步取消、超时与任务中断仍按原计划归 M8，不因本次归档被视为完成。

2026-09-21：归档 M6。统一清理 M6.1/M6.5 “当前练习”、M6 未启动/未归档等旧状态；保留 SQLite 开发限定、状态 fork 不复制完整祖先历史、显式数据库路径以及 checkpoint/metadata 非原子等边界。

2026-09-22：按用户要求修复并归档 M7。清理旧的“当前任务”与过早验收描述，保留原计划范围并补齐组合预算、摘要生成、失败恢复和诊断 CLI。过程记录与当时测试数完整保存在 [M7 归档前快照](docs/history/2026-09-22-before-m7-archive/README.md)。

2026-09-23：按用户要求先归档 M8 已交付范围；2026-09-24：核对 M1–M8 文档与源码、Git 和离线门禁，统一索引、阶段总结、问题修订与后续清单。原始长篇切片过程保存在 [整理前快照](docs/history/2026-09-23-m1-m8-review/INDEX.md)，不再作为当前待办。

以后一个里程碑一个总结段；新进展更新对应段落。当前快照仅有一份，详细验证只写对应验收文件。历史测试数必须标注时间和范围，归档不得把教学版局限写成生产级保证。


## 2026-10-01：Web 服务管理与持久审批

用户选择后续任务 1、2、4、5，先完成依赖计划，再授权直接开发。暂停进程仍持有数据库锁，因此服务管理要验证进程启动身份并通过实例令牌优雅停止，不能靠删除锁文件。文件和命令复用同一持久提案表；LangGraph 的多工具节点恢复会重入，需要保持 interrupt 次序并绑定提案 ID，结果消息也要绑定操作身份，避免重复 tool-call ID 覆盖历史。

批准与副作用不是同一事务：先认领、后执行、再存结果；崩溃或记录失败产生 uncertain，人工核对，不能自动重放。取消只表示停止继续执行，不会撤销已经发生的外部效果。当前本机严格回归、浏览器审批与真实 Web gate 已有证据；平台 CI 与用户验收另列，详见 [独立验收记录](docs/acceptance/web-coding-2026-10-01.md)。
