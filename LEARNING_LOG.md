# 学习日志

## 当前快照

- 更新日期：2026-09-21；时区：Asia/Shanghai。
- 学习者基础：具备 Python 基础，学习过 LangChain/LangGraph 常规用法；目标是能独立设计、实现和审查 Agent 系统。
- 进度：M0–M5 已完成；M5-R1–R4 已在同步 fake-provider 教学范围内闭合，详见 [M5 归档](docs/acceptance/M5.md)。M6 尚未启动。
- 当前练习：无。下一步是按 M6 的整体链路进入 session/checkpoint 设计；本轮未启动 M6。
- 当前能力：最小图、fake 工具循环、安全文件/进程组件、独立文件审批图、稳定流式事件及 fake CLI。CLI 仍使用最小图，不能理解为已能执行真实文件工具。
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

## 关键决策

| 决策 | 结论与原因 |
|---|---|
| 图编排 | 使用 StateGraph 显式节点/条件边，使控制流可学习、可测试 |
| 数据边界 | TypedDict/reducer 管图内更新；Pydantic 校验边界；runtime 依赖不进入状态 |
| 工具协议 | schema 校验先于执行；ToolMessage 保留关联；副作用前单独审批 |
| 事件边界 | 消息、状态和 custom 分开投影，统一 sequence，再给 renderer 消费 |
| 持久化 | M4 仅内存审批 checkpoint；M6 承接持久存储、session 元数据和分支 |
| Provider | 先 fake 再真实适配；M5 fake CLI 不代表真实 token 流已验收 |
| 取消 | M5 完成同步消费侧协作取消与资源释放；provider/tool 的异步中断传播属于 M8 |
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
| M6 | SQLite checkpoint、session metadata、跨进程恢复和 fork | 尚未启动；不能以 M4 内存审批替代 |
| M7 | 上下文优先级、预算和摘要质量 | 用样例确定合并与压缩规则 |
| M8 | 真实 provider、工具绑定、异步流、重试/取消传播 | 凭据仅从安全配置读取；保持图状态独立 |
| M9–M11 | 扩展、评测、可选远程和全系统验收 | 按 PLAN 范围逐步进入 |

## 本次整理记录与后续写法

2026-09-18：按用户要求归档 M5 已交付版本。将原来落在 M4 下的 M5 记录分离；把反复追加的“当前下一步”和脚手架红灯移入历史快照；统一里程碑标题与时间线；保留原始验收要求，并登记新发现的缺口。本次无业务代码或测试改动。

2026-09-21：修复并复验 M5-R1–R4。同步 fake-provider 教学范围完整通过；真实 provider/tool 的异步取消、超时与任务中断仍按原计划归 M8，不因本次归档被视为完成。

以后一个里程碑一个总结段；新进展更新对应段落。当前快照仅有一份，详细验证只写对应验收文件。历史测试数必须标注时间和范围，归档不得把教学版局限写成生产级保证。
