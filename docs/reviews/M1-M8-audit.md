# M1–M8 文档审计与修订记录

审计日期：2026-09-24（Asia/Shanghai）。检查范围：PROJECT_SPEC、PLAN、LEARNING_LOG、README、AGENTS、M1–M8 验收文档、两次旧历史快照、现有源码/测试及当时可见的 Git 历史。M8 先按用户指示于 2026-09-23 归档，再进行文档审计；同日后续的代码纠正与复验另记于 [M8 纠正记录](../acceptance/M8-closure.md)。历史快照只作为过程证据，不按当前说明使用。

## 核查口径

1. 需求以 [PROJECT_SPEC](../../PROJECT_SPEC.md) 为准；里程碑范围和状态以 [PLAN](../../PLAN.md) 为准；运行事实以当前源码和可执行测试为准；用户提供的 live 输出单列为用户报告。
2. 初次审计时 Git 可见 `d1560b0`（回溯提交 M1–M5）和 `ba930a0`（提交 M6/M7）；后来新增 `c4e91b8` 文档整理提交。它们均不能单独证明每个子切片的具体实现时间；M8 代码当前仍有未提交工作树内容。
3. 2026-09-24 执行 `uv run pytest -q -m 'not live' --basetemp=.pytest-tmp-doc-audit-20260923` 为 **403 passed、4 deselected**；mypy **179 source files**，Ruff lint 全部通过，format **200 files**。2026-09-23 记录的全仓结果是 **403 passed、4 skipped**，范围/日期不同，不能写成同一次运行。

## 发现与修订

| ID | 发现与依据 | 修订/结论 |
|---|---|---|
| D01 | [PLAN](../../PLAN.md) 表中 M8 `completed`，正文仍写等待归档；[旧稿](../history/2026-09-23-m1-m8-review/PLAN.md) 含大量“当前练习” | 统一 M8 为 2026-09-23 已交付归档；过程移入历史快照，当前 PLAN 只保留范围、实际边界和门禁 |
| D02 | M2 验收稿“最终验收”记 2026-09-03，PLAN 记 2026-09-04 用户验收；[旧 M2](../history/2026-09-23-m1-m8-review/docs/acceptance/M2.md) | 分别记 **技术验证 09-03、用户确认/归档 09-04**；不猜具体时分 |
| D03 | M4 文档把独立文件审批与“高风险命令审批”并列；[审批图](../../src/pi_agent/graph/file_approval.py) 只处理 file change，[进程函数](../../src/pi_agent/tools/process.py) 直接执行 allowlisted argv | M4 归档明确为文件 prepare→approval→apply 与受控进程组件，高风险命令的人审接线仍缺失 |
| D04 | M6 写“checkpoint 不重复执行已完成副作用”；[fork](../../src/pi_agent/sessions/fork.py) 用 `update_state`，集成测试只证明 fork 期间不调用模型 | 结论限定为**状态 fork 不执行图节点**；崩溃重放、外部副作用幂等仍未证明 |
| D05 | M7 计划写“摘要节点”；[同步模型节点](../../src/pi_agent/graph/nodes.py)、[上下文](../../src/pi_agent/context/runtime.py) 将摘要作为节点内准备阶段 | 统一称“摘要阶段/适配器”，说明没有独立持久图节点 |
| D06 | M8 工具循环记录易误读为真实 read/list/search 闭环；[Provider session](../../src/pi_agent/cli/runtime.py) 实际编译 async minimal graph，未注入只读注册表；[HTTP client](../../src/pi_agent/models/http_client.py) 请求未发送 `tools` schema | 当前 M8 归档写清组件级离线闭环与产品入口断点；真实工具调用列 P0 |
| D07 | M8 “重试/取消传播”容易误认为 provider session 已应用；[async retry](../../src/pi_agent/runtime/async_retry.py) 仅在独立测试调用，[async_model_node](../../src/pi_agent/graph/async_nodes.py) 直接 `model.ainvoke` | 修订为已交付策略和局部执行端口，端到端的 deadline、retry、取消接线未验收 |
| D08 | [异步进程](../../src/pi_agent/tools/async_process.py) 的 POSIX tree terminate 用 `killpg(pid)`，spawn 未设置 `start_new_session`；正常 `ProcessResult` 的 returncode 固定为 0；测试大多使用 fake | 将真实 POSIX 进程组、实际 exit code、输出采集上限列 P0；不把 fake 策略测试写成跨平台实测 |
| D09 | M8 旧记录“默认 CI 不触网”与实际 `skipif(PI_AGENT_LIVE)` 条件并存；[live tests](../../tests/live/test_provider_smoke.py) 与 [CI](../../.github/workflows/ci.yml) | 当前口径：普通环境变量未启用时 skip；CI 必须显式保证未设置 live gate，避免环境继承触网 |
| D10 | [README](../../README.md) 将运行 CLI 描述为 fake，但 M8 文档有 provider options/runtime；[CLI app](../../src/pi_agent/cli/app.py) parser 仍只接受 `fake` | 将“ProviderCliOptions 是程序化边界”写入入口文档；不称其为公开兼容 CLI |
| D11 | M1–M4/M6/M8 验收稿把历史红灯与当前结论混排，标题/格式不统一；M5/M7 较清晰 | 统一 M1–M8 的归档标题、状态口径与文档索引；M1–M4/M6/M8 压缩为目标、设计/交付、验证/遗留结构，M5/M7 保留已有教学叙事；完整过程留在 [整理前快照](../history/2026-09-23-m1-m8-review/INDEX.md) |
| D12 | [PLAN](../../PLAN.md) 的 Pi→LangGraph 对照表把设计建议写成当前实现，例如 `BaseChatModel` 子类、独立 context node；M6/M7/M8 原范围词也易与实现混淆 | 对照表与原范围补充实际实现说明：M7 摘要阶段位于 model 节点内，M8 使用项目模型协议；M6 副作用幂等未完成 |

## 待核实

| ID | 疑点 | 所需依据 |
|---|---|---|
| V01 | **部分核实**：公开的 [固定 SHA 源码](https://github.com/earendil-works/pi/tree/96317e50b8d6e7f6d0e47fd29122baf1461c00f5) 可访问；[agent-loop.ts](https://github.com/earendil-works/pi/blob/96317e50b8d6e7f6d0e47fd29122baf1461c00f5/packages/agent/src/agent-loop.ts#L2511-L2523) 显示仅在配置 `toolExecution === "sequential"` 或工具声明 sequential 时走串行，否则走并行；[同文件](https://github.com/earendil-works/pi/blob/96317e50b8d6e7f6d0e47fd29122baf1461c00f5/packages/agent/src/agent-loop.ts#L2740-L2743) 用 `Promise.all` 执行并保持结果顺序 | 2026-09-24 仅复核上述具体路径/语义；`coding-agent` 与其他目录的逐项完整追溯仍需固定 SHA 完整源码或可访问页面，不用单文件推断全仓 |
| V02 | M1 在 Python 3.11/3.12/3.13 的历史运行、M2–M7 的历史精确耗时/文件数 | 当时的 CI run URL 或原始命令日志；当前只保留原验收记录，Git 两次合并式提交不能独立重建 |
| V03 | R2-A 用户报告的兼容服务 `1 passed` 及随后 ConnectError 的网络环境原因 | 用户原终端日志、endpoint 的可用性证据、在相同配置下重新执行；当前不读取密钥或请求正文 |
| V04 | 真实 provider 的 streaming、工具调用、SQLite 续聊、摘要与 usage 是否符合其兼容协议 | 在显式 `PI_AGENT_LIVE=1` 的隔离环境运行 smoke 和只读工具回路，保留脱敏的状态/错误码与模型响应结构 |
| V05 | 跨平台进程树真实终止、输出洪流内存限制、文件审批后崩溃重放 | Windows 与 POSIX 实进程/子进程集成测试及持久审批场景，不能由 fake 测试代替 |

## 保留的历史与变更

M5 曾于 2026-09-18 先归档已交付，R1–R4 于 2026-09-21 闭合复验；M7 于 2026-09-22 经过组合修复再归档；M8 于 2026-09-23 先归档已交付。可沿 [M5](../acceptance/M5.md)、[M7](../acceptance/M7.md)、[M8](../acceptance/M8.md) 与三套 [历史快照](../history/) 比较。旧文档是过程记录，当前状态只看 PLAN。
