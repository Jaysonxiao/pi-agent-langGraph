# Learning Log

## 当前快照

- 日期：2026-09-17
- 当前阶段：M3 Tool Calling 闭环和 M4 安全 Coding Tools 与人工审批均已验收；M5 技术实现已完成，等待最终验收/归档确认。
- 学习者基础：具备 Python 基础，已学习 LangChain/LangGraph 常规用法，但缺少完整生产级 Agent 项目经验。
- 当前工作区：已建立 Python 工程、typed state、最小图、受控 fake Tool Calling 循环、工作区路径策略、有界 read/list/search、无副作用文件变更提案、可恢复 approval node、版本复核原子写入、结构化 argv 进程边界和 prepare→approval→apply 集成；M5 正在补稳定事件投影，CLI 和持久化仍按里程碑推进；当前目录仍无有效 Git 元数据。

## 本轮学习进度

- [x] 阅读 `PROJECT_SPEC.md`，确认采用“从面到点，再从点回到面”的路线。
- [x] 检查本地长期规则；`AGENTS.md` 已存在，无需重复创建。
- [x] 固定 Pi Agent 分析基线：`main` @ `96317e50b8d6e7f6d0e47fd29122baf1461c00f5`。
- [x] 检查 ai、agent、coding-agent、tools、session、context、compaction、extensions、telemetry、evals、TUI、protocol/server/client。
- [x] 核对 LangGraph：2026-09-02 与 2026-09-16 两次复核的 PyPI 稳定版均为 `1.2.11`，满足项目要求的 1.1+。
- [x] 形成 MVP、增强阶段、生产化阶段和可选远程层的里程碑。
- [x] 用户于 2026-09-03 确认进入 M1；M1 已成为唯一进行中的里程碑。
- [x] 完成 M1 工程骨架、学习者实作、Python 3.11/3.12/3.13 测试和完整质量门禁。
- [x] 用户于 2026-09-03 确认进入 M2；M2 已成为唯一进行中的里程碑。
- [x] 学习者完成 M2 核心节点；助手完成审查、脚手架类型修复、全量门禁和“从点回到面”复盘。
- [x] 用户于 2026-09-04 确认理解 M2；已将必须掌握知识、Pi/LangGraph 设计映射、常见问题、答案要点与自检标准归档到 `docs/acceptance/M2.md`。
- [x] 用户于 2026-09-04 明确批准在 M2 归档后进入 M3；计划状态已切换，未进入 M4 范围。
- [x] 学习者于 2026-09-11 完成 M3 registry 核心练习；助手完成语义审查、边界补测、全量门禁和“从点回到面”归档。
- [x] 用户于 2026-09-11 回答 M3 理解检查并明确批准打开 M4；M4 成为唯一进行中的里程碑。
- [x] 完成并审查 M4 的工作区路径门禁练习；后续能力仍按 read/list/search、edit/write、进程控制与 HITL 的顺序留在本里程碑内。
- [x] 完成并复验 M4 的 `TextOutputBudget.apply()` 以及 read/list/search 接入；目标测试 `12 passed`，全仓 `46 passed`，mypy 与 Ruff 门禁通过。
- [x] 2026-09-16 重新读取 `PROJECT_SPEC.md`，核对 Pi 当前默认分支与 LangGraph 官方 API，并增量更新 `PLAN.md`/`LEARNING_LOG.md`；未修改业务代码。
- [x] 用户确认继续 M4；完成 edit/write `prepare` 脚手架、Pi 源码映射与失败测试，未实现 approval/apply 或受控进程。
- [x] 学习者完成并优化 `apply_exact_replacement()`；目标测试 `10 passed`，既有回归 `55 passed`，mypy 与 Ruff 门禁通过。
- [x] 建立 approval state/request/graph 测试脚手架；完整变更留在 checkpoint state，有界 payload 交给 `interrupt()`，未实现 learner TODO 或任何写盘。

## 已建立的架构认识

1. Pi 的核心循环很小，产品复杂度主要在外围。`packages/agent/src/agent-loop.ts:runLoop()` 只负责模型、工具结果和下一 turn；`packages/coding-agent/src/core/agent-session.ts:AgentSession.prompt()` 负责命令/skills、扩展、鉴权、压缩、重试和持久化协作。
2. Pi 区分运行时消息与 LLM 消息。`AgentMessage[]` 可含 UI/自定义消息，只有 `convertToLlm()` 后的标准消息发送给 provider。Python 版本也应保留“审计/显示状态”和“模型上下文”的边界。
3. 工具结果是消息协议的一部分。tool call ID、参数校验、执行错误和 `ToolMessage` 顺序必须保持一致，不能把工具仅当普通函数调用。
4. Pi session 是带 `parentId` 的 JSONL 树，并在上下文投影时应用 compaction/branch summary。LangGraph checkpointer 可以承接 checkpoint 与恢复，但 session 名称、列表、分支语义仍需要应用层仓储。
5. Pi 默认继承本地用户权限，`path-utils.ts` 允许绝对路径；本项目规格要求更强安全性，因此不会照搬该边界。
6. `protocol/server/client` 使用权威快照和实验性 CBOR 协议。它们说明远程会话边界，但不应阻塞本地 MVP。

## 关键决策

| 决策 | 当前结论 | 原因 |
|---|---|---|
| 编排 API | 使用 `StateGraph`，不以 prebuilt agent 隐藏核心循环 | 学习目标要求掌握状态、节点和路由 |
| LangGraph 版本 | M1 暂定 `>=1.2,<1.3` | 当前稳定版 1.2.11；避免混入旧 API |
| 项目布局 | `src/pi_agent/` + 镜像 `tests/` | 隔离包代码、便于测试和发布 |
| 包管理 | 首选 uv + `pyproject.toml` | 单一锁文件、命令简洁；M1 固化 |
| 状态模型 | 图内 TypedDict/reducer，边界使用 Pydantic | 兼顾 LangGraph 原生更新与输入校验 |
| 工具执行 | 自定义工具节点优先，必要时复用 `ToolNode` | 需要明确权限、进度、超时和错误契约 |
| 持久化 | checkpointer 与 session metadata 分离 | checkpoint 不是完整产品会话目录 |
| 人工审批 | `interrupt()` + `Command(resume=...)` | 官方可恢复 HITL 机制；重放前副作用须幂等 |
| Provider | 先 fake，再接一个 OpenAI-compatible 适配器 | 测试不依赖网络，同时尽早验证真实路径 |
| Pi 兼容性 | 保留设计思想，不追求 TypeScript/API/CBOR 字节兼容 | 采用 Python/LangGraph 惯用边界，控制范围 |
| 教学协作 | 引导式结对开发；学习者亲手实现关键小任务 | 目标是形成独立设计和编码能力，而非只得到成品 |
| 练习上下文 | TODO 前先讲 Pi 设计、LangGraph 映射、端到端位置与脚手架数据流 | 避免孤立函数任务，让编码练习服务于架构理解 |
| 教学叙事 | 项目和里程碑都采用“面 → 点 → 面”，并用同一请求贯穿讲解、实现和复盘 | 防止按模块讲得很细却失去整体运行方向 |

## 学习优先级

- **必须掌握**：消息与 reducer、StateGraph、条件边/Command、工具循环、streaming、checkpoint、interrupt、取消/错误传播、确定性测试、安全边界。
- **需要理解**：动态上下文、compaction、provider 适配、session metadata、hooks、telemetry、行为评测。
- **暂时了解**：远程协议、server/client lease、TUI 差分渲染、多 provider catalog。
- **第一版忽略**：完整 OAuth、图像生成、二进制发布、Pi 全量扩展兼容、公开网络服务。

## 待解决问题

这些问题不影响当前计划成立，但必须在对应里程碑或切片入口解决：

1. M4：首版命令工具采用结构化 argv 直接执行和可执行文件 allowlist；任意 PowerShell/shell 字符串不进入本里程碑。仍需在进程工具切片中确定默认 allowlist 和高风险分类。
2. M6：开发默认使用 SQLite checkpointer；生产候选是 PostgreSQL 还是保持存储接口不选型。
3. M7：AGENTS 层级覆盖规则、最大上下文预算和摘要质量指标需要用具体样例验收。
4. M8：第一个真实 provider 与模型由可用凭证决定；不得把 provider 特性泄漏到图状态。
5. M10：只有出现远程调用需求时才进入；需先明确认证、传输和兼容目标。

## 后续记录模板

每次只追加一个里程碑条目：

```markdown
## YYYY-MM-DD — Mx 名称
- 状态：in_progress | completed | blocked
- 本次目标：
- 对应 Pi 源码：
- LangGraph 知识点：
- 新增/修改文件：
- 验证命令与结果：
- 关键取舍：
- 常见错误/调试结论：
- 遗留问题：
- 理解检查：
```

## 2026-09-03 — M1 Python 工程骨架

- 状态：completed
- 本次目标：建立可安装、可 lint、可类型检查、可测试的 Python 3.11+ `src` 工程，为后续 LangGraph 代码提供稳定边界。
- 当前环境：`python` 为 3.12.4；`uv` 为 0.7.13；`py` launcher 未发现注册的 Python；当前目录不是 Git 仓库。
- 对应 Pi 源码：根 `package.json` 的 workspace/build/check/test 分层，以及 `packages/agent`、`packages/coding-agent` 的核心与产品层分离。
- LangGraph 知识点：本里程碑只固定依赖和 import 边界，不创建图；正式 API 从 M2 开始。
- 教学分工：助手先准备低学习价值的目录/工具脚手架和失败测试；学习者完成一个小型包接口，使测试通过；助手随后审查并解释打包、导入和质量门禁。
- 新增/修改文件：`pyproject.toml`、`uv.lock`、`README.md`、`.gitignore`、`.env.example`、`.github/workflows/ci.yml`、`src/pi_agent/__init__.py`、`tests/test_package.py`、`docs/acceptance/M1.md`。
- 验证结果：锁文件复现成功；Python 3.11.13、3.12.3、3.13.5 均为 `1 passed`；Ruff lint/format、mypy、包导入 smoke 全部通过。
- 遗留问题：当前目录是否初始化 Git 仓库由用户另行决定；进入 M2 前需用户明确确认。
- 学习者实作审查：正确使用发行包元数据实现 `__version__` 并通过公开接口测试；首次完整检查暴露格式化门禁，学习者使用 Ruff 修复后通过。
- 理解检查：已实际区分 `ruff check` 的 lint 规则与 `ruff format --check` 的排版规则，并验证源码安装后的发行包元数据读取方式。

## 2026-09-03 — M2 消息、状态与最小图

- 状态：completed
- 本次目标：用 LangGraph 完成一次 `user -> model -> END`，建立 typed state、消息 reducer、运行时模型依赖、fake model、显式结束路由及成功/失败契约。
- 对应 Pi 源码：`packages/ai/src/types.ts` 的标准消息类型；`packages/agent/src/types.ts` 的 `AgentMessage`、`AgentState` 与 `convertToLlm` 边界；`packages/agent/src/agent-loop.ts` 的 `runLoop()` 和 `streamAssistantResponse()`。
- LangGraph 知识点：`StateGraph`、`TypedDict`、`add_messages` reducer、节点增量更新、`context_schema`/`Runtime` 依赖注入、条件边与 `END`。
- 教学分工：助手创建领域/图/model 接口、fake、确定性测试和验收说明；学习者完成 `model_node` 的状态转换 TODO，助手审查后再完成全部门禁。
- 新增/修改文件：`pyproject.toml`、`uv.lock`、`src/pi_agent/domain/`、`src/pi_agent/models/`、`src/pi_agent/graph/`、`tests/domain/`、`tests/graph/test_minimal_graph.py`、`docs/acceptance/M2.md`，以及本日志和 `PLAN.md`。
- 验证命令与结果：脚手架阶段为预期的 `5 passed, 3 failed`；学习者实现后，计划规定的 pytest 为 `8 passed`，目标 mypy 检查 7 个源码文件无问题。最终附加门禁：Ruff lint 通过，21 个文件格式检查通过，`mypy src tests` 检查 14 个文件无问题，完整 pytest 为 `9 passed`。
- 关键取舍：模型作为运行时依赖传入，不写入可持久化图状态；M2 只保留标准 LangChain 消息，不提前实现 Pi 自定义消息投影。
- 教学方式调整：版本和 commit 仅作为简短兼容性校验；后续每个 TODO 必须先给出 Pi 原始设计、改造取舍、LangGraph 机制、端到端数据流和测试意图，再说明具体编码任务。
- 教学结构二次调整：用户暂不继续 M2 编码，先完善“从面到点，再从点回到面”的叙事。恢复 M2 前应先按新的 A/B/C 结构重讲系统全貌、当前切片和回归全局的路径，再决定是否继续现有 TODO。
- 暂停处理：不删除已经完成的 M2 脚手架和测试；`PLAN.md` 中 M2 退回 `pending`，恢复前需要用户重新确认进入。
- 恢复执行：用户于 2026-09-03 明确要求重新进入并执行 M2；恢复现有脚手架，先完成全局链路、当前切片和关键下钻点说明，再由学习者实现核心 TODO。
- 恢复点验证：计划规定的 mypy 命令通过；M2 测试为 `5 passed, 3 failed`，三个失败均由 `model_node` 的唯一教学 TODO 触发，未发现新的脚手架回归。
- 常见错误/调试结论：并行运行多个 `uv run` 会竞争 editable package 的安装步骤，质量门禁应顺序执行；LangGraph 的 `END` 在类型信息中是普通 `str`，路由函数需窄化为 `Literal["__end__"]`；严格 mypy 下 `list` 不协变，直接把 `list[HumanMessage]` 传给接收宽消息联合类型的 `add_messages` 会失败，测试改用 `list[MessageLikeRepresentation]` 明确边界。
- 学习者实作：已实现 `model_node`——成功只返回助手消息增量与 `completed`；失败不改 `messages`，写入可序列化 `model_error`。
- 验证命令与结果（练习完成后）：`uv run pytest tests/domain tests/graph/test_minimal_graph.py -q` 为 `8 passed`；`uv run mypy src/pi_agent/domain src/pi_agent/graph` 无问题。
- 从点回到面：`"hello"` 现在能够经过 `HumanMessage -> AgentState -> model_node -> FakeChatModel -> AIMessage delta -> add_messages -> route_after_model -> END`；加入 M2 前系统只有工程骨架，加入后已有无工具的最小 Agent 心跳。
- 知识总结：节点读取完整状态但返回增量；reducer 决定消息合并语义；模型等运行依赖通过 `RunContext` 注入而不进入状态；业务异常可转换为稳定终态供路由和调用者观察。
- 遗留问题：M2 只有同步 fake model 和标准消息；工具调用、循环上限、真实 provider、token streaming、checkpoint、重试与取消均按计划留在后续里程碑。
- 下一步：等待用户验收 M2；验收后仍需用户明确确认才能进入 M3。M3 将在当前 assistant message 后检查 `tool_calls`，把单向 `model -> END` 扩展为 `model -> tools -> model/END`。
- 理解检查：节点必须返回 `[reply]` 以免 `add_messages` 重复用户输入；模型走 `RunContext` 以免把不可序列化依赖写入状态；失败走图内 `failed` 而不是让异常冲出图。
- 验收归档（2026-09-04）：用户确认理解 M2。归档补充了七项必须掌握知识、Pi 命令式循环到 LangGraph 状态/节点/reducer/边的映射、五个架构问题及答案、自检场景，并修正“返回完整历史必然重复”的过度简化：`add_messages` 会按 ID 替换同一消息，但节点仍必须遵守增量更新契约。

## 2026-09-04 至 2026-09-11 — M3 Tool Calling 闭环

- 状态：completed；用户于 2026-09-11 完成理解检查并批准进入 M4
- 本次目标：把 M2 的 `user -> model -> END` 扩展为可终止的 `user -> model -> tools -> model -> END`，并让成功、未知工具、非法参数、执行异常和轮次上限都形成稳定消息/状态。
- 系统断点：M2 能保存带 `tool_calls` 的 `AIMessage`，但当前路由只会结束；模型提出的动作没有注册、校验、执行和结果回灌路径。
- 贯穿场景：用户要求计算 `2 + 3`；fake model 首次返回 `add(left=2, right=3)`，工具节点返回 call ID 一致的 `ToolMessage("5")`，fake model 第二次看到结果后返回最终文本。
- 对应 Pi 源码：`packages/agent/src/agent-loop.ts` 的 `runLoop()`、`prepareToolCall()`、`executeToolCallsSequential()`、`executeToolCallsParallel()`、`executePreparedToolCall()`、`createToolResultMessage()`；`packages/agent/src/types.ts` 的 `AgentTool`、`AgentToolResult` 和工具生命周期事件。
- LangGraph/LangChain 知识点：`AIMessage.tool_calls`、`ToolMessage.tool_call_id`、Pydantic schema 校验、自定义工具节点、条件边、循环终止、运行时 registry 注入、节点增量和确定性 fake。
- 改造决策：为教学保留自定义 registry/tool node，不用预制 `ToolNode` 隐藏核心链路；M3 固定按 assistant 源顺序串行执行，多工具并发留到具备取消和事件顺序契约后；真实文件/进程访问与人工审批严格留给 M4。
- 学习者练习：实现 `src/pi_agent/tools/registry.py:ToolRegistry.execute_call()`，把单个 tool call 归一化为成功或失败的 `ToolMessage`；图、fake 和测试由脚手架提供。
- 新增/修改文件：新增 `src/pi_agent/tools/`、`tests/tools/test_registry.py`、`tests/graph/test_tool_loop.py`、`docs/acceptance/M3.md`；扩展 state、runtime context、model/tool nodes、routing、graph builder、scripted fake model、项目依赖和锁文件。
- 脚手架验证：`uv run mypy src tests` 检查 20 个文件无问题；`uv run ruff check .` 通过；`uv run ruff format --check .` 为 28 个文件已格式化；M2 回归为 `8 passed`。首次 mypy 暴露 `list[ToolMessage]` 到 `list[AnyMessage]` 的不协变问题，已在节点边界显式使用宽消息类型修复；首次全仓 Ruff 暴露导出排序问题，已修复并复验。
- 学习者基线：M3 目标测试为 `3 passed, 5 failed`；五个失败全部停在 `ToolRegistry.execute_call()` 的预期 `NotImplementedError`。无工具终止、零轮次上限、重复注册三个路径已通过。最终仍必须让 PLAN 中两条 M3 命令全部通过，不得把当前预期红灯当作验收。
- 学习者实作审查：正确实现成功、未知工具、非法参数和 handler 异常四条路径；注册查找先于执行，非法参数不会触发 handler，成功/失败均保留 name 和 call ID，异常内容不含 traceback。学习者报告目标测试 `8 passed`、目标 Ruff 通过。
- 审查修复：原实现无法区分 schema 阶段 `ValidationError` 与 handler 内部同类异常，新增 `ToolArgumentError` 只包装参数校验错误；验证错误改用稳定消息和去除 input/context/version URL 的 details。保留确定性消息身份的意图，但将 `ToolMessage.id` 改为 `tool-result:{call_id}`，与关联字段 `tool_call_id` 分开命名。
- 补充测试：新增 handler 内部 `ValidationError` 分类、未知/非法/执行异常的图级回灌终态，以及多工具按 assistant 源顺序串行执行。M3 目标测试最终 `13 passed`。
- 最终验证：计划命令 `uv run pytest tests/tools/test_registry.py tests/graph/test_tool_loop.py -q` 为 `13 passed`；`uv run ruff check src/pi_agent/graph src/pi_agent/tools` 通过。附加全仓门禁：Ruff lint 通过，28 个文件格式检查通过，mypy 检查 20 个文件无问题，完整 pytest 为 `22 passed`。
- 从点回到面：`calculate 2 + 3` 现在经过 `HumanMessage -> model tool call -> conditional route -> registry -> Pydantic -> handler -> correlated ToolMessage -> reducer -> model final answer -> END`。与 M2 相比，Agent 从“能表达动作意图”升级为“能执行无副作用 fake 动作并消费结果”。
- 知识总结：工具是 schema/handler/消息协议的组合边界；输入校验必须发生在副作用前；验证错误和执行错误要分层；可恢复工具错误应回灌模型；消息 ID 与 call ID 职责不同；图循环需要业务终止条件；运行依赖和可持久状态仍需分离。
- 常见错误/调试结论：测试全部通过仍可能隐藏异常分类错误；捕获过宽或在错误层级捕获会改变业务语义。为了 reducer 幂等而设置确定性消息 ID 时，应使用独立命名空间，不能把关联 ID 当作消息身份而不加区分。
- 遗留问题：真实 provider 的 `bind_tools` 边界留到 M8；稳定跨界流式事件 DTO 留到 M5；工具权限与副作用审批留到 M4。
- 验收结果：用户于 2026-09-11 正确说明 recoverable error 与轮次上限的差别、消息 ID 与调用关联 ID 的职责，并确认 `max_tool_rounds` 是按已执行工具批次计算的图级门禁；随后明确批准打开 M4。M3 已归档，无遗留验收动作。
- 理解检查：为什么 recoverable tool error 回灌模型但轮次上限直接失败；`ToolMessage.id` 与 `tool_call_id` 各自服务什么；`max_tool_rounds=1` 时第二批工具请求如何走到 `tool_limit_node`。

## 2026-09-11 — M4 安全 Coding Tools 与人工审批

- 状态：in_progress
- 本次目标：把 M3 的无副作用工具循环升级为受控主机能力链；先建立 read/list/search/edit/write 共用的工作区路径门禁，再逐步加入输出预算、写入审批和受控进程。
- 整体断点：registry 已能校验和执行工具，但当前没有定义模型可访问的主机能力范围；若直接注册文件或命令 handler，模型将继承进程账户权限。
- 当前纵向切片：`read("README.md")` 应解析为工作区内 canonical path；`read("../secret.txt")` 及工作区内 symlink 指向外部文件必须在读取前以稳定策略错误失败。
- 对应 Pi 源码：`packages/agent/src/harness/types.ts` 的环境能力抽象；`harness/tools/path-utils.ts`、`read.ts`、`write.ts`、`edit.ts`、`bash.ts`；`harness/tools/file-mutation-queue.ts`；`harness/env/nodejs.ts` 的超时、取消和进程树终止。
- LangGraph 知识点：`interrupt()` 暂停需要 checkpointer 和 `thread_id`；用 `Command(resume=...)` 恢复相同线程；恢复会从节点开头重放，所以 interrupt 前不得发生不可幂等副作用。
- Pi 到本项目的取舍：保留环境/工具分层、输出截断、超时取消和同路径写入串行的思想；不继承 Pi 的主机权限边界。本项目所有文件能力先过 workspace canonical-path policy，首版命令只接受结构化 argv 和 allowlist，不开放任意 shell。
- 新增/修改文件：新增 `src/pi_agent/security/`、`tests/security/test_path_policy.py`、`docs/acceptance/M4.md`；同步更新 `PLAN.md` 与本日志。
- 唯一学习练习：实现 `WorkspacePathPolicy.resolve()`；输入输出、稳定错误、禁止方案、边界样例和验收命令详见 `docs/acceptance/M4.md`。
- 验证命令与结果：目标 Ruff lint 通过，3 个文件格式检查通过，mypy 检查 3 个文件无问题。pytest 首次被沙箱账户无权访问用户级临时目录阻断；改用工作区 `--basetemp` 后发现 Windows symlink 权限导致关键用例 skip，已增加 directory-junction fallback。最终脚手架基线为 `1 passed, 10 failed`，无 skip，十个失败全部停在唯一 `NotImplementedError`。这不是 M4 最终验收结果。
- 关键取舍：安全策略独立于具体工具和图；使用 `Path` 的 canonical 解析和目录成员判断，禁止字符串前缀判断；读目标与待写目标用 `must_exist` 区分，但都不能产生副作用。
- 遗留问题：路径练习审查后，仍需完成 concrete tools、统一输出上限、命令 allowlist/timeout/process-tree kill、审批 DTO 以及批准/拒绝恢复集成测试。
- 常见错误/调试结论：pytest 的 `tmp_path` 默认位置受运行账户 ACL 影响；环境错误必须与代码红灯区分。symlink 权限不足也不能让关键安全证据永久 skip，Windows 可用无需管理员权限的 directory junction 覆盖同类 canonical-path 逃逸。
- 学习者首次实作审查：原有 11 项路径契约、mypy、Ruff lint/format 均通过，测试未被削弱；`resolve(strict=False)` 配合 `is_relative_to()` 正确处理相对/绝对路径、父级穿越、同名前缀 sibling、缺失写目标和 junction 逃逸。审查发现所有 `OSError/RuntimeError` 被统一误分为 `not_found`，会把权限、路径格式或链接循环故障伪装成文件缺失；已补一项失败测试，等待学习者将真正的 `FileNotFoundError` 与其他解析故障分开。
- 学习者修正与最终审查（2026-09-14）：已将 `FileNotFoundError -> not_found` 与其他 `OSError/RuntimeError -> invalid_path` 分开，新增测试通过且未削弱原有安全断言。最终复验：路径门禁和 M3 registry/图回归合计 `25 passed`；`mypy src/pi_agent/security tests/security`、目标 Ruff lint、目标 Ruff format 全部通过。
- 从点回到面：`read("README.md")` 的路径现在可被解析为工作区内 canonical path；`read("../secret.txt")`、同名前缀 sibling 和经 Windows junction 指向外部的路径均在文件内容被访问前失败。`WorkspacePathPolicy` 将作为 read/list/search/edit/write 的共同上游，使具体工具无需各自重复安全判断。
- 生产简化：当前策略仍是“按路径解析后再由具体工具打开”，无法彻底消除校验与使用之间的 TOCTOU；真正抗恶意并发替换需要平台相关的句柄/目录描述符方案。M4 首版记录此风险，并要求具体工具在解析后立即操作、不缓存已授权路径。
- 当时的下一步（2026-09-14 路径门禁完成时）：等待用户确认后，在 M4 内建立 read/list/search 与统一输出预算切片；M4 状态保持 `in_progress`，不进入 M5。该切片现已完成，最新下一步见本节末尾。
- 只读工具切片（2026-09-14）：贯穿请求为“list 项目根目录 → search `LangGraph` → read README 命中窗口”。Pi 的 `FileSystem` 把 `readTextLines`、`listDir`、`canonicalPath` 与稳定 `FileError` 放在环境能力边界，`read.ts` 支持 offset/limit，`truncate.ts` 以行数和 UTF-8 字节数双重限制输出；本项目保留这些思想，并让每个路径先经过已完成的 `WorkspacePathPolicy`。当前可核验 Pi 快照没有独立 search 实现，因此 Python search 明确作为项目规格新增的受限 literal search。
- 本切片分工：助手完成只读工具参数模型、handler/factory、稳定遍历和测试脚手架；学习者只实现 `TextOutputBudget.apply()`，使 read/list/search 共用相同整行截断语义。图和 registry 不修改，证明主机能力可以从现有运行时依赖边界插入。
- 只读工具脚手架验证：目标 Ruff lint 通过，9 个文件格式检查通过，mypy 检查 9 个文件无问题；既有路径门禁、registry 和工具循环回归为 `25 passed`。新测试为预期的 `3 passed, 9 failed`，九个失败均停在唯一 `TextOutputBudget.apply()` 的 `NotImplementedError`。脚手架审查额外将 list 条目分类改为 `lstat`/Windows reparse metadata，避免 `is_dir()` 为判断类型而跟随 junction 目标。
- 只读工具完成与复验（2026-09-14，2026-09-16）：`TextOutputBudget.apply()` 已实现 UTF-8 字节预算、完整行前缀、双重截断原因和首行超预算标志；read/list/search 均在返回 registry/model 前复用该策略。计划测试 `uv run pytest tests/tools/test_output.py tests/tools/test_read_only.py -q --basetemp=.pytest-tmp` 为 `12 passed`，目标 mypy 无问题，全仓 Ruff lint/format 通过；全仓 pytest 为 `46 passed`。
- 从点回到面：`list(".") -> search("LangGraph", ".") -> read("README.md", ...) -> ToolMessage -> model` 现已具备共同的工作区授权、确定性遍历、扫描/匹配上限和模型可见输出预算。LangGraph 继续只负责状态、节点与工具路由；路径授权、文件遍历、解码和预算仍属于应用工具层。
- 上一轮计划复核时的下一步：等待用户确认后继续 M4 的 edit/write 变更契约；用户现已确认，最新任务见本节末尾。
- edit/write 准备切片（2026-09-16）：贯穿请求为“将 `README.md` 中唯一的 `M1 establishes...` 替换为 `M1-M4 establish...`”。整体链路规划为 `tool call -> schema/path -> prepare proposal -> approval interrupt -> apply -> ToolMessage`；本轮只落地副作用前的 prepare proposal。
- Pi 映射：Pi `write.ts` 在路径解析后覆盖写入，`edit.ts` 要求旧文本唯一且保留 BOM/行尾，并用 `file-mutation-queue.ts` 串行化同 canonical path 的写操作。本项目保留唯一匹配、内容保真和同路径并发保护的意图，但增加工作区授权、显式审批和批准后版本复核，不照搬 Pi 默认主机权限边界。
- LangGraph/HITL 决策：官方语义要求 `interrupt()` 使用 checkpointer + 稳定 `thread_id`，恢复时会从节点开头重跑，且中断异常不能被通用 `except Exception` 捕获。本地 `GraphInterrupt` 确认继承 `Exception`，因此审批将放到独立 graph node，而不是直接藏进当前会捕获 handler 异常的 registry；prepare、approval、apply 分节点后，审批之前没有写副作用。
- 新增/修改文件：新增 `src/pi_agent/tools/file_mutation.py` 与 `tests/tools/test_file_mutation.py`，扩展 `src/pi_agent/tools/__init__.py`，同步更新 `PLAN.md`、`docs/acceptance/M4.md` 与本日志。
- 脚手架验证：新增测试为预期的 `3 passed, 7 failed`，七个失败均停在 `apply_exact_replacement()` 的唯一 `NotImplementedError`；既有 domain/graph/security/registry/output/read-only 回归 `45 passed`，mypy 检查 11 个工具相关文件无问题，全仓 Ruff lint 通过且 39 个 Python 文件格式检查通过。
- prepare 完成与性能审查（2026-09-16）：实现以第一次 `find()` 区分 not-found，再从 `match_offset + 1` 做第二次 `find()`，既识别 `aaa`/`aa` 的重叠匹配，又在第二处命中时提前失败；相较收集全部匹配位置，额外空间从随匹配数增长降为常量。目标测试 `10 passed`；既有 domain/graph/security/tools 回归 `55 passed`；mypy 检查 29 个文件无问题，Ruff lint/format 通过。
- approval node 子切片（2026-09-16）：整体链路更新为 `prepared change -> checkpoint state -> interrupt payload -> Command(resume=...) -> approval delta`。`PendingFileChange` 持有后续 apply 所需的 `after_text`，但给人的 JSON payload 只含 operation、path、前后哈希和 preview，避免把完整替换内容复制进中断响应。
- approval 脚手架验证：`tests/graph/test_file_approval.py` 为预期的 `2 passed, 5 failed`，五项失败都来自唯一 `file_approval_node()` TODO，并覆盖暂停、批准/拒绝、非 pending 和非法恢复载荷；既有回归 `55 passed`，`mypy src tests` 检查 32 个文件无问题，Ruff lint 通过，Ruff format 检查 45 个文件通过。
- 当前下一步：学习者实现 `src/pi_agent/graph/file_approval.py:file_approval_node()`；该节点只中断、校验恢复值并返回状态增量，不得写文件、捕获 `GraphInterrupt` 或调用 apply。审查完成后才进入版本复核与 atomic apply。
- approval node 完成与审查（2026-09-16）：实现严格检查 `pending`，通过 `interrupt(build_file_approval_request(...))` 暂停，并用 `ApprovalDecision.model_validate()` 拒绝多余字段；恢复后仅写入 approved/rejected 状态增量，不改变 checkpoint 中的 proposal。目标测试 `7 passed`；mypy、Ruff lint/format 和全仓 pytest（新增 apply 脚手架前）均通过。
- atomic apply 子切片（2026-09-16）：整体链路推进为 `approved state -> re-resolve path -> compare before_sha256 -> temp file + flush/fsync -> os.replace -> result`。脚手架保留四条核心证据：未批准不触碰文件、磁盘版本变化先失败、edit 保留 CRLF、write 可创建新文件。
- atomic apply 脚手架验证：`tests/tools/test_file_apply.py` 为预期的 `1 passed, 4 failed`，四项失败均来自唯一 `apply_approved_file_change()` TODO；mypy 检查 13 个工具文件无问题，目标 Ruff lint/format 通过。当前没有把 TODO 红灯误报为 M4 验收结果。
- 当前下一步：学习者实现 `src/pi_agent/tools/file_apply.py:apply_approved_file_change()`；该函数必须先验证 approved 和 `before_sha256`，再用同目录临时文件 + `os.replace()` 完成原子替换，并在异常时清理临时文件。审查完成后才接受控进程切片。
- atomic apply 完成与审查（2026-09-16）：实现先验证 approved，再重新解析路径并比较实际 `before_sha256`；通过同目录临时文件、`flush/fsync` 和 `os.replace()` 写盘，异常清理残留临时文件。目标测试 `5 passed`，排除 process learner 测试的全仓回归 `68 passed`，mypy/Ruff 门禁通过。
- 受控进程子切片（2026-09-16）：整体链路推进为 `approved/apply -> structured argv -> executable allowlist -> subprocess timeout/termination -> bounded ProcessResult`。脚手架只允许列表参数，不接受 shell 字符串；测试用 Python 当前解释器验证输出和超时，避免依赖外部命令。
- 受控进程脚手架验证：`tests/tools/test_process.py` 为预期的 `2 passed, 3 failed`，三个失败均来自唯一 `run_controlled_process()` TODO；mypy、Ruff lint/format 通过。当前下一步：学习者实现该函数，重点处理 allowlist、`shell=False`、超时进程树终止、UTF-8 输出上限和稳定错误分类。
- 受控进程完成与审查（2026-09-16）：实现精确 executable allowlist，先检查 cwd 为目录，再以 `shell=False` 运行结构化 argv；Windows 使用 `taskkill /T`，POSIX 使用独立进程组，超时后回收 pipes；stdout/stderr 通过 `TextOutputBudget` 限制，非零退出保留 `ProcessResult`。目标测试 `5 passed`，排除未来 HITL 集成测试的全仓 pytest `73 passed`，mypy/Ruff 门禁通过。
- 复盘要点：模型不能提交 shell 字符串；allowlist 是“能不能启动”的策略，cwd 目录检查只是“路径当前可用”的前置条件，最终调用方仍必须使用 `WorkspacePathPolicy` 产生 workspace 内 cwd；超时不是普通返回码，而是需要终止并回收进程树的控制错误；stdout/stderr 也是不可信模型上下文，必须有界。
- 当前下一步：进入 M4 最终 HITL 集成复盘，串起 `prepare -> approval interrupt/resume -> approved apply`，并补一条“受控进程 cwd 由 workspace policy 提供”的端到端证据；完成后才评估 M4 是否可标记 `completed`。
- 最终 HITL 集成（2026-09-16）：`tests/integration/test_hitl.py` 覆盖批准写入、拒绝不写入和 stale-version 拒绝覆盖三条路径；集成 `3 passed`，全仓 pytest `76 passed`，mypy 检查 37 个文件无问题，Ruff lint 通过，49 个文件已格式化。M4 技术验收完成，等待用户确认归档。
- 从点回到面：`prepare_edit` 读取并生成版本固定 proposal；approval graph 在稳定 thread 上 interrupt/resume；只有 approved state 才能进入 apply，apply 再次走 workspace policy 和 before hash；受控进程使用 policy 提供的 cwd、allowlist 和有界输出。所有文件副作用均位于批准之后。
- 当前下一步：M4 已完成并归档；M5 是唯一 `in_progress`，当前学习者实现稳定 `updates` 事件投影，尚不进入 CLI 或 token 聚合。
- M5 第一切片脚手架（2026-09-16，2026-09-17 复核）：新增 `StreamEvent(sequence, kind, node, payload)` 严格 DTO，以及 model/tool/error 三类 `updates` 投影测试。本地 fake 图的真实 chunk 含 `AIMessage`，故补充“排除不可 JSON 序列化消息对象”测试；目标测试为 `1 passed, 4 failed`，四项失败均来自唯一 `project_stream_update()` TODO；mypy、Ruff lint/format 通过。
- 当前下一步：学习者实现 `src/pi_agent/events/stream.py:project_stream_update()`；保持 sequence/node，优先识别 error/tool，再落到 state_update，payload 只能包含 JSON 可序列化字段。完成后复盘一个 `build_tool_graph().stream(stream_mode="updates")` 请求，再进入 token/custom 事件。
- M4 重新归档复验（2026-09-16）：`uv run pytest tests/tools tests/security tests/integration/test_hitl.py -q --basetemp=.pytest-tmp` 为 `53 passed`；M4 范围 mypy 检查 32 个文件无问题，Ruff lint/format 通过。状态机械检查为一个 `in_progress`，对应 M5；本次未改动 M5 业务代码或其预期红灯。
- M5 update 投影完成（2026-09-17）：`project_stream_update()` 先识别非空 error，再识别 tools/tool_limit/tool_rounds，最后回退 state_update；payload 逐字段以标准 `json.dumps` 检查，排除消息等框架对象且不字符串化。目标测试 `5 passed`，全仓 pytest `81 passed`，mypy 检查 40 个文件无问题。
- M5 第二切片脚手架（2026-09-17）：新增 `project_update_chunks()`，使用真实 fake tool graph 验证 `model -> tools -> model` 事件顺序、连续 sequence、消息对象不进入 payload，并固定 malformed node update 的失败路径。当前为预期的 `0 passed, 2 failed`；mypy/Ruff lint 通过，格式问题已修正。
- 当前下一步：学习者实现 `src/pi_agent/events/adapter.py:project_update_chunks()`；按 chunk/node 源顺序调用 `project_stream_update()`，跨所有 chunk 分配连续 sequence，非 mapping update 抛出含 `mapping` 的 `ValueError`。完成后再进入 message/token 模式。
- M5 update adapter 完成（2026-09-17）：实现为惰性 generator，按 chunk/node 插入顺序复用 `project_stream_update()`，sequence 跨所有 chunk 连续递增，malformed update 在投影前失败。目标测试 `2 passed`，全仓 pytest `83 passed`，mypy 检查 42 个文件无问题。
- M5 message/token 脚手架（2026-09-17）：本地 fake 图确认 `stream_mode="messages"` 产出 `(AIMessage, metadata)`，metadata 以 `langgraph_node` 标识来源。新增完整消息、`AIMessageChunk`、缺失 node metadata 和真实 graph 测试；当前预期 `1 passed, 4 failed`，四项失败均来自唯一 `project_message_chunk()` TODO。
- M5 message/token 完成（2026-09-17）：学习者实现 AI/Human/System/Tool 稳定 role 映射、基于 `BaseMessageChunk` 的 chunk 判定以及非空 `langgraph_node` 校验；目标测试 `5 passed`，全仓 pytest `88 passed`，全仓 mypy 检查 45 个文件无问题，目标 Ruff lint/format 通过。
- M5 custom/progress 脚手架（2026-09-17）：本地 LangGraph 1.2 探针确认单 custom 模式直接产出 writer mapping，多模式则产出 `(mode, chunk)`。新增 `progress` kind、严格字段/边界测试和真实 custom stream 集成；当前预期 `1 passed, 4 failed`，四项失败均来自唯一 `project_custom_chunk()` TODO；目标 mypy/Ruff lint 通过。
- M5 custom/progress 完成（2026-09-18）：学习者使用 `type(value) is int` 排除 bool，完成类型、非空字符串、total 正数及 completed 区间门禁，并只发布固定 payload。目标测试 `5 passed`；全仓 pytest `93 passed`，全仓 mypy 检查 48 个文件无问题，Ruff lint/format 通过。
- M5 统一多模式 adapter 脚手架（2026-09-18）：本地三模式图确认 `(mode, chunk)` 依次为 custom mapping、messages `(BaseMessage, metadata)`、updates node mapping。新增跨 mode 顺序、单 update chunk 多事件、连续 sequence、malformed payload 和真实图测试；当前预期 `0 passed, 3 failed`，均来自唯一 `project_stream_chunks()` TODO；目标 mypy/Ruff lint 通过。
- M5 统一多模式 adapter 完成（2026-09-18）：学习者完成 custom/messages/updates 惰性分派，按实际事件递增全局 sequence，并修复空 node 名称静默丢弃问题。目标测试 `3 passed`；全仓 pytest `96 passed`，全仓 mypy 检查 50 个文件无问题，Ruff lint/format 通过。
- M5 JSONL 脚手架（2026-09-18）：新增 `iter_jsonl()`，固定 UTF-8、紧凑 JSON、每个事件恰好一行和真实三模式 stream 到 JSONL 的集成边界；当前预期 `0 passed, 3 failed`，均来自唯一 `iter_jsonl()` TODO；目标 mypy 通过，Ruff 导出排序问题已修复待复验。
- M5 JSONL 完成（2026-09-18）：学习者实现按输入顺序惰性消费、`ensure_ascii=False`、紧凑 separators 和单个换行结尾；目标测试 `3 passed`，全仓 pytest `99 passed`，全仓 mypy 检查 53 个文件无问题，Ruff lint/format 通过。
- M5 CLI renderer 脚手架（2026-09-18）：新增 `render_event()`/`iter_text()`，固定 progress、message、error 和 state_update 的纯文本输出契约，并用真实三模式 stream 验证顺序；当前预期 `0 passed, 4 failed`，均来自唯一 `render_event()` TODO；目标 mypy/Ruff lint/format 通过。
- M5 CLI renderer 完成（2026-09-18）：学习者完成 progress/message/error/state_update 纯文本格式化，`iter_text()` 保持顺序且不执行 IO；目标测试 `4 passed`，全仓 pytest `103 passed`，全仓 mypy 检查 57 个文件无问题，Ruff lint/format 通过。
- M5 CLI entry point 脚手架（2026-09-18）：新增 `pi-agent` console script、fake provider 参数解析、text/jsonl 两种输出测试和 help 测试；当前预期 `1 passed, 2 failed`，两个失败均来自唯一 `run_cli()` TODO；目标 mypy 通过，Ruff 导入排序问题已修复待复验。
- M5 CLI entry point 完成（2026-09-18）：学习者完成 fake graph stream、统一事件投影、text/jsonl renderer 选择和 output 注入；目标测试 `3 passed`，console JSONL smoke 成功，全仓 pytest `106 passed`，全仓 mypy 检查 59 个文件无问题，Ruff lint/format 通过。
- M5 cancellation 脚手架（2026-09-18）：新增幂等 `CancellationToken`，要求取消前后都停止消费并关闭可关闭 upstream iterator；真实 projected graph stream 也有集成场景。当前预期 `1 passed, 3 failed`，三个失败均来自唯一 `iter_cancellable()` TODO；目标 mypy/Ruff lint/format 通过。
- M5 cancellation 完成（2026-09-18）：学习者实现取消前后停止消费、close upstream iterator、异常透传和 token 幂等；目标测试 `4 passed`，全仓 pytest `110 passed`，全仓 mypy 检查 62 个文件无问题，Ruff lint/format 通过。
- M5 SIGINT 脚手架（2026-09-18）：新增 `sigint_cancels()` context manager 测试，要求临时安装 SIGINT handler、触发 token.cancel，并在正常/异常退出时恢复旧 handler；当前预期 `0 passed, 2 failed`，均来自唯一 `sigint_cancels()` TODO；目标 mypy/Ruff lint/format 通过。
- M5 SIGINT 完成（2026-09-18）：学习者完成 scoped handler 生命周期、token.cancel 触发和异常安全恢复；目标测试 `2 passed`，全仓 pytest `112 passed`，全仓 mypy 检查 64 个文件无问题，Ruff lint/format 通过。
- M5 终态过滤脚手架（2026-09-18）：新增 `iter_terminal_once()`，要求 completed/failed 首个终态保留、后续终态抑制、非终态和 tool/message 保持；真实 graph 集成固定 completed 只出现一次。当前预期 `0 passed, 3 failed`，均来自唯一 TODO；目标 mypy/Ruff lint/format 通过。
- 当前下一步：学习者实现 `src/pi_agent/events/terminal.py:iter_terminal_once()`；只识别 `kind == "state_update"` 且 status 为 completed/failed 的事件，保留第一个并抑制后续，其他事件原序透传；完成后将过滤器接回 CLI 并做 M5 最终归档。
- M5 终态过滤完成（2026-09-18）：学习者实现首个 completed/failed 终态保留、重复终态抑制和真实 graph 证据；目标测试 `3 passed`，全仓 pytest `115 passed`，mypy 67 个文件、Ruff lint/format 通过。
- M5 最终接线完成（2026-09-18）：CLI 现在在 scoped SIGINT 下运行 cancellable projected stream，经 terminal-once filter 后选择 text/jsonl 输出；接线测试、全仓 pytest `116 passed`、mypy 67 个文件、Ruff lint/format 和 text CLI smoke 全部通过。等待用户确认后归档 M5。
