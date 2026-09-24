# M8 端到端纠正与复验（2026-09-24）

本页是 [M8 初次归档](M8.md) 的后续纠正记录，不把 2026-09-24 的结果倒填为 2026-09-23 的原验收。用户要求直接修复 P0/P1/P2，且不新增测试用例；本轮改生产代码、沿用既有测试，并执行临时工作区的运行探针。M9 仍未启动。

## 主链路

显式 `--provider compatible` → 环境配置/HTTP 客户端 → SQLite 会话恢复 → M7 临时上下文 → async model/tool graph → HTTP `tools` schema → 工作区只读工具 → `ToolMessage` 回灌 → 最终回复 → JSONL/text 事件与 session 目录。默认 `fake` 路径保持原有最小图、离线运行。

| 项 | 本轮修复与源码依据 | 复验结论 |
|---|---|---|
| F01 | [HTTP](../../src/pi_agent/models/http_client.py) 将 schema 发送到普通/SSE 请求；[Provider runtime](../../src/pi_agent/cli/runtime.py) 绑定 `read/list/search` 并选择 async tool graph；[CLI 文件策略](../../src/pi_agent/cli/read_only.py) 排除 `.env`、私钥等敏感路径 | 真实 compatible 工具闭环在仅有合成 `probe.txt` 的工作区产出 `model → tools → model`，最终回复 `M8_SYNTHETIC_READ_OK`，退出 0；未知工具、轮次上限仍由原图/registry 契约处理 |
| F02 | [async model node](../../src/pi_agent/graph/async_nodes.py) 将每次 provider 请求包入取消、单次 deadline 和有界 async retry；HTTP 错误保留状态码供 [策略](../../src/pi_agent/runtime/policy.py) 分类；CLI 外层还有整轮 deadline | 本地 HTTP `MockTransport` 穿过真实 Provider session 主图：401 失败且只请求 1 次，429 后成功且请求 2 次，两个请求均带受控 tools schema；运行中取消以 `CancelledError` 传播，HTTP handler 的 `finally` 已执行。真实供应商主动限流/中断仍未制造 |
| F03 | [异步进程](../../src/pi_agent/tools/async_process.py) 返回实际退出码、POSIX 新进程组/终止升级、Windows 新进程组、双管道固定头部采集上限；产品调用传入工作区策略；Windows `taskkill /T` 非零退出现在显式失败并回收直接子进程，不再无限等待管道 | Windows 短进程退出码 7、1 MB 输出被截断、越界 cwd 拒绝均实跑通过；获准的 Windows 执行环境中真实父子进程在超时后返回 `timeout`、子进程已消失。默认沙箱对同一 `taskkill /T` 返回 `Access denied`，现会明确报 `execution_failed`；WSL 无可列举发行版、Docker daemon 不可用，**POSIX 实进程树尚未复验** |
| F04/F07 | [提案存储](../../src/pi_agent/tools/command_approval.py) 只让模型创建 allowlist 命令提案；[命令 CLI](../../src/pi_agent/cli/command.py) 展示精确 argv 并要求交互终端键入 `approve ID`；SQLite 原子 `pending→claimed` 后才 spawn，已领取/已拒绝不重放 | 本机非交互批准被拒、拒绝零 spawn、已领取提案第二次领取失败；交互终端确认 `python -V` 后退出 0、提案变为 completed，另一个获批短进程的退出码 7 原样返回。文件变更重放被版本哈希拒绝。`claimed` 后崩溃是**待人工核对**，不能宣传“恰好一次”；命令进程不具备 OS 沙箱 |
| F05 | 沿用 [4 个 opt-in live 用例](../../tests/live/test_provider_smoke.py)：普通回复、SSE、SQLite reopen/resume、摘要路径 | 2026-09-24，compatible，`deepseek-v4-flash`，`api.deepseek.com`：最终复跑 **4 passed / 9.56s**（此前一次 4 passed / 9.05s）。默认沙箱网络被拒时曾 4 failed；在获准的网络执行环境中重新运行后通过。另有真实 CLI 合成文件读取及下一轮续聊通过；不推断其他模型/供应商 |
| F06 | [公开 CLI](../../src/pi_agent/cli/app.py) 显式选择 provider、session、workspace、数据库、事件格式、可选命令提案及脱敏 trace；[流消费者](../../src/pi_agent/cli/runtime.py) 逐节点输出并在完成后记录 session metadata；[metadata](../../src/pi_agent/sessions/metadata.py) 显式关闭 SQLite 连接 | JSONL 工具调用 6 个顺序事件，最终 completed/退出 0；续聊返回上一轮合成标记，`session list` 找到会话。事件是节点级/完整消息级，**不承诺 token-by-token CLI 输出** |
| F08 | [HTTP](../../src/pi_agent/models/http_client.py) 保留 provider 响应的 token usage；[事件投影](../../src/pi_agent/events/message.py) 可携带已知用量；[trace](../../src/pi_agent/events/trace.py) 只留序号、节点、状态、错误码和 token 数 | 合成密文标记未进入 trace；真实续聊 trace 得到 `input=786, output=25, total=811`，且无 prompt/回复正文。用量来源是 provider 报告，不是计费估计；语义摘要质量与 M9 完整 hook/eval 平台仍需单独验收 |
| F09 | [审计](../reviews/M1-M8-audit.md) 继续区分当前复验与历史证据；固定上游 SHA 的 agent-loop 并行条件已在公开源码重新核对 | 缺少旧 CI 原始日志的历史精确时间/多 Python 版本结果仍标“待核实”，不以今天的测试倒填 |

## 可重复门禁

离线：`uv run pytest -q -m 'not live' --basetemp=.pytest-tmp-m8-close`、`uv run mypy src tests`、`uv run ruff check src tests`、`uv run ruff format --check src tests`。2026-09-24 本轮为 **403 passed, 4 deselected**，mypy **182 source files**，Ruff lint/format 通过。未新增测试文件。

真实接口仅在用户已配置且明确允许触网时执行：`$env:PI_AGENT_LIVE='1'; uv run --env-file .env pytest tests/live/test_provider_smoke.py -m live -q --basetemp=.pytest-tmp-m8-live`。本轮由于默认沙箱不能访问外部网络，实际获准运行使用同一 `.venv` 的 pytest 和进程内加载 `.env`，没有打印密钥值。真实 CLI 工具探针只发送合成标记；对把项目文档发送到外部 provider 的尝试，沙箱拒绝后未再执行该路径。

后续门槛：在 Linux/POSIX 宿主复验真进程树；真实 429 与取消中的网络连接、语义摘要质量和完整 M9 hooks/evals 属于独立复验；不得把当前通过的离线或 4 个 live smoke 扩大解释为这些结论。使用命令提案时，`claimed`/异常状态必须查看外部效果后人工处置，不做自动重试。
