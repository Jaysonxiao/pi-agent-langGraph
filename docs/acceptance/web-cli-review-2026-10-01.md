# Web 整体复审与 CLI 基线兼容性归档

复审、修订、复验与整体归档日期：2026-10-01（Asia/Shanghai）。用户要求 review 当天全部 Web 改造，确认与原 CLI 基线无冲突后整体归档并提交 main。本次仅提交本地 `main`，不 push。

## 范围与结论

- CLI/M11 基线：`ed6b5ca`；当天改造起点：`626a16e`；被审功能最终提交：`d760c62`。检查初始 Web 到当前版本的累积变化，并重点复审当天启动、服务管理、流式、恢复/分支、持久审批和工具设置调整。
- 未发现需要阻止本地归档的 CLI/TCP 行为回归。修正一项 Web 指令冲突后，将全部已交付 Web 范围及工具设置调整整体归档；不新增里程碑，不改写 M0–M11 或此前各轮验收数字。
- CLI、TCP 服务端/客户端、协议、会话、领域状态和安全策略目录的生产源码相对 `ed6b5ca` 无差异。共用 context、异步节点、模型适配、工具和运行时有增量，兼容结论来自下表的调用链核对和本次实跑，不能只依据入口未变得出。

## 共用链路核对

| 边界 | 当前行为与兼容性依据 |
|---|---|
| CLI fake / compatible | fake 仍是离线最小图；compatible 使用原 `cli/runtime.py` 和 `cli/read_only.py`。默认只绑定 read/list/search，命令提案仍须显式 allowlist 与交互终端批准，没有 Web 默认 shell、自动审批或直接 write/edit 入口 |
| TCP 运行时 | `SessionRuntimeConfig` 默认工具仍为 read/list/search，coding executor 和文本 observer 默认空，默认工具轮次仍为 4；新恢复参数默认关闭。原认证、请求协调、取消、协议与快照链路保持原样 |
| 项目指令 | `ContextConfig` 与指令发现默认仍加载 AGENTS.md；Web 显式注入 PI-AGENTS.md 与内建提示词。现有 server 指令隔离测试通过，Web 配置不修改 CLI/TCP 上下文 |
| 流式 / 重试 / 取消 | 只有注入 text observer 且模型支持原生流时才启用 Web 文本预览。CLI/TCP 保留 ainvoke；取消/失败不提交半截回复，新增流关闭逻辑与 usage 元数据不替换原调用协议 |
| 审批表迁移 | 在旧 command_proposals 上新增列，旧行默认 kind=command、payload_json 为空。CLI 原提案身份、工作区和精确 argv 校验及一次性认领仍有效；Web recover_claims 只处理有 Web payload 的记录。新增四项回归直接预置旧版 pending/claimed/completed/rejected 数据，证明原内容和状态保留、旧 pending 可认领一次、其余不可重放 |
| 命令结果 | 共用 finish 现在保存有界输出、耗时，并将非零退出状态记为 failed，这是可观察的状态细化；CLI 仍输出 ProcessResult 并对非零退出返回 1，未新增自动执行权限。旧 completed 记录不被重写 |
| 文件 / 进程 | 文件原子替换补充保留现有权限；POSIX 增加父进程提前退出、子进程仍持有管道的回收。原文件审批和路径测试、命令取消/超时及真实进程树测试通过；Windows 特定回收限制保留 |
| 设置 / 持久化 | 六工具默认值、系统 shell 和审批开关仅在 Web 边界配置。每轮固定选择快照，旧待人工审批提案不因重启参数变化自动执行。Web 表增量扩展不替换 checkpoint 表；Web 与独立 CLI/TCP 不同时驱动同一数据库仍是使用前提 |
| 依赖 | Web 依赖属于可选 extra；原基础依赖约束保持不变，CLI/TCP 生产调用链不导入 Web 应用模块 |

## 发现与处理

复审发现根目录 `PI-AGENTS.md` 仍声称 Web 只提供只读操作，其文档示例同样过时。启动脚本默认以仓库为工作区，真实模型会读到这一旧规则，与当前 write/edit/command 能力冲突。已改为遵循本轮注册工具与服务端审批策略、只依据成功结果报告完成；同步修正 [指令规范](../pi-agents.md) 及 [Web 使用文档](../web-ui.md) 的旧只读图描述。CLI/TCP 继续读取 AGENTS.md，不受此指令修订影响。本次没有修改 Python/前端生产代码。

新增 [CLI 旧审批数据兼容测试](../../tests/tools/test_command_store_compatibility.py)，位于基础 tools suite，不依赖 FastAPI/Web extra。原 Web 迁移用例只预置旧表结构；本次补足已有四种状态记录的迁移和恢复隔离证据。

## 本次实际验证（macOS）

| 命令 / 检查 | 实际结果 |
|---|---|
| `uv run --extra web pytest tests/web tests/cli tests/server tests/context tests/tools tests/integration -q --basetemp=/private/tmp/pi-agent-review-focused-open -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --tb=short` | 增补测试前 318 passed，14.22s |
| `uv run pytest tests/tools/test_command_store_compatibility.py -q --basetemp=/private/tmp/pi-agent-review-migration` | 4 passed |
| `uv run --extra web pytest -q --basetemp=/private/tmp/pi-agent-review-final -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --tb=short` | 最终 640 passed、6 skipped，14.70s；跳过为未显式启用的真实 Provider gate |
| `uv run mypy src tests scripts` | 279 source files 通过 |
| `uv run ruff check .` / `uv run ruff format --check .` | 通过；334 files already formatted |
| `uv run pi-agent --provider fake --prompt hello --events jsonl` | fake reply 与 completed 事件，退出码 0 |
| `uv run pi-agent eval --suite tools --provider fake` | 1/1 passed |
| `npm run test` / `npm run build`（web-ui） | 4 passed；TypeScript/Vite 构建通过 |
| `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` | 8 passed，24.5s；选择、审批、读取、移动端、停止、流式、恢复及独立分支 |
| `uv run python scripts/web_startup_smoke.py` | 真实 Bash 启动、构建、HTTP bootstrap、真实 read、持久历史和服务退出通过 |
| `git diff --check` / 改动文档本地链接核对 | 通过 |

执行环境使用临时 `UV_CACHE_DIR=/private/tmp/pi-agent-review-uv`。首次聚焦执行为 305 passed、13 failed：失败源于沙箱禁止 loopback bind 和 ps；经允许本机服务/进程测试权限复跑后 318 项全部通过。npm 初次不在该 shell PATH，补充已有 Node 24.21.0 的 bin 路径后完成前端验证；未安装新的 Node。没有把环境拒绝记为代码通过。

## 整体归档与保留项

初始 Web、当天两轮扩展及工具默认值/审批/选择调整均按本机单用户已交付范围归档，原始证据仍见 [Web 初次归档](web-archive-2026-10-01.md)、[Coding 验收](web-coding-2026-10-01.md) 和 [工具设置调整](web-tool-settings-2026-10-01.md)。本记录是最新整体复审证据，不覆盖这些历史记录。

本次未重新运行真实 Provider、Windows/Linux 独立 runner、PowerShell 实机或部署验证。真实服务此前 2 passed 属于原 Coding 验收范围，不能外推为本次改动的真实模型验证。PI-AGENTS.md 修订后的模型遵循情况没有新的 live 实测；指令文本冲突已消除。W1–W4 与 M11 D1–D3 继续保留，见 [Web 后续清单](../follow-ups/web.md)。归档不等于跨平台或生产部署就绪。
