# Pi 本机工作台

2026-10-01 归档：用户授权归档本机工作台及两轮扩展的已交付范围，并合并本地 `main`，暂不 push。当前结论见 [Web 归档](acceptance/web-archive-2026-10-01.md)，未关闭项见 [后续清单](follow-ups/web.md)；下方历史验证按执行日期保留。

2026-10-01 归档后调整：用户实际体验反馈基本可用，要求默认启用文件/命令工具、可配置审批、简化名称并支持全部工具勾选。当前行为和新验证见 [工具设置调整记录](acceptance/web-tool-settings-2026-10-01.md)，不回填归档基线的测试数字。

2026-09-29: 根据用户要求直接实现, 本扩展不使用教学练习或待填 TODO, 也不改变 M11 的验收状态。

2026-10-01: 按[后续计划](design/web-continuation.md)补齐 Bash 启动、显式中断恢复、完成 checkpoint 分支和流式文本。该轮验证单列于计划执行记录，不回填下方 2026-09-29 的历史结果。

2026-10-01 后续开发：按[服务管理与 Coding Tools 计划](design/web-coding-plan.md)增加服务管理、持久化文件/命令审批。新验证单列于[本轮验收记录](acceptance/web-coding-2026-10-01.md)，不改写旧记录。

## 已实现

- React / TypeScript 三栏界面, 中文交互, 手机窄屏侧栏, Markdown/代码块, 复制回复。
- 会话新建、列表、标题搜索、自动标题、重命名、归档与恢复。
- FastAPI 调用现有 `run_session`、LangGraph 异步只读工具图与 SQLite checkpoint。
- compatible 模型使用已有服务端配置; fake 模式明确标识为演示, 真实调用 read/list 后展示返回内容。
- SSE 推送模型/工具阶段和流式文本, 右侧展示真实 Hook 活动; compatible 使用原生响应分片, 无流能力模型保留完整消息输出。
- 服务端持有运行任务, 浏览器刷新/断线不主动取消, 显式停止按 run_id 取消并等待清理。
- 内建 Pi Workbench 系统提示词负责身份与工具边界; 项目规则独立使用 `PI-AGENTS.md`, 不加载 Codex 的 `AGENTS.md` / `CLAUDE.md`。规范见 [PI-AGENTS.md 规范](pi-agents.md)。
- 深色像素风工作台; 欢迎页覆盖写作、分析、规划与工作区任务。
- 设置面板可更换本地工作区、启用/停用全部六项工具；`read`、`list`、`search` 可分别配置每轮调用上限 (0–20, 默认各 4)。默认全部选中，右侧工具区也可直接勾选；选择和上限保存后从下一轮生效，进行中的一轮沿用启动时的快照。已创建会话固定使用创建时的工作区。
- 执行时间线中已完成的模型/工具节点可点击查看安全投影后的输入、输出与 checkpoint 前后快照; 系统提示词及原始图状态不会发送到浏览器。
- 持久化请求标识与内容摘要防止重复执行; 同一标识配不同内容返回 409。
- 消息按指定 checkpoint 分页, 每页最多 40 条、每条最多 16 KiB UTF-8, 长内容显示截断提示。
- 重启后保留会话; 未结束的运行登记为 needs_recovery, 不自动重放。用户点击“继续运行”后从当前 checkpoint 继续只读图，不追加第二条用户消息；可能重新调用未完成的模型/只读工具。
- 会话操作中可选择已完成的 checkpoint 创建独立分支。分支继承来源工作区并复制选中状态，不运行模型或工具；来源历史不变。列表展示最近 200 个快照中的最多 50 个完成 checkpoint。
- 服务 start/status/stop/restart；实例记录绑定数据库、PID、进程启动身份与随机控制令牌；旧版/身份不匹配的进程只报告占用，不自动控制。
- 模型可准备 `write` / `edit` 或 `propose_command` 提案，界面显示 `write`、`edit`、`command`。默认工具启用且修改/命令需审批；启动参数可关闭人工审批。两种模式均持久记录操作身份、结果并回灌模型；刷新和重启保留待审批提案。

## 启动

需要 Node.js 22.12+ (或符合 Vite 要求的 Node LTS)、Python 3.11+ 和 uv。

```powershell
# 项目根目录; 安装依赖、构建并启动。
.\scripts\start-web.ps1

# 使用现有 compatible 配置; 自动读取项目根目录 .env。
.\scripts\start-web.ps1 -Provider compatible
```

macOS / Linux 使用 Bash：

```bash
./scripts/start-web.sh
./scripts/start-web.sh --provider compatible
./scripts/start-web.sh --help
```

地址: <http://127.0.0.1:8766>。默认数据库为用户目录下的 `~/.pi-agent/web.sqlite`，与项目工作区及既有手工运行数据库分开。可通过 `-Database`（启动脚本）或 `--database`（CLI）指定其他位置，但数据库必须位于所选工作区之外；更换工作区时也执行此检查。旧版项目目录中的 `.pi-agent/web.sqlite` 不会自动迁移，如需保留会话，请在服务关闭后自行复制到新的默认位置。

手工安装/构建:

```powershell
uv sync --extra web
Push-Location web-ui
npm ci
npm run build
Pop-Location
uv run --extra web pi-agent-web --provider fake --workspace .
```

真实模型:

```powershell
uv run --env-file .env --extra web pi-agent-web --provider compatible --workspace .
```

使用已有 `PI_AGENT_MODEL`、`PI_AGENT_BASE_URL`、`PI_AGENT_API_KEY` 等配置, 由现有模型配置解析器校验。Web 页面不会编辑或回显密钥。命令参数 `--port` 可更换端口, Ctrl+C 关闭服务。

### 服务管理

```bash
./scripts/start-web.sh status
./scripts/start-web.sh stop
./scripts/start-web.sh restart --provider compatible --workspace ./safe-workspace
# 只有显式要求时才在优雅停止超时后强制结束已验证的实例。
./scripts/start-web.sh stop --force
```

PowerShell 使用 `-Action status|stop|restart` 和 `-Force`。也可直接运行 `uv run --no-sync --extra web pi-agent-web status` 等命令。管理命令无需 Node/npm；需要此前已安装的 Python Web 环境。自定义数据库必须重复传入 `--database` / `-Database`，重启时提供所需 workspace/provider/port/能力参数。

状态为 healthy（健康）、paused（暂停）、unresponsive（无响应）、occupied（由未确认实例占用）、stale（过期记录）或 stopped（停止）。停止通过实例令牌请求服务清理运行并退出；POSIX 暂停实例先核对进程启动身份再发送 SIGCONT。旧版服务未登记身份时，在原终端 `fg`、`Ctrl+C` 退出后重启；不要用删除 `.web.lock` 代替停止进程。

### 文件与命令审批

```bash
./scripts/start-web.sh --provider compatible --workspace ./safe-workspace \
  --require-approval

# 关闭人工审批，直接执行当前选中的 write/edit/command。
./scripts/start-web.sh --provider compatible --no-require-approval

# 自定义允许列表会替换默认系统 shell，可重复指定多个程序。
./scripts/start-web.sh --provider compatible --allow-executable /usr/bin/git
```

默认六项工具全部选中，文件与命令需人工审批。PowerShell 关闭审批使用 `-RequireApproval $false`；自定义程序使用 `-AllowExecutable 'C:\\path\\to\\git.exe'`，多个程序使用字符串数组。默认程序是 macOS/Linux `/bin/sh` 或 Windows 系统 `cmd.exe`；允许 shell 后可通过 argv 执行脚本或 `-c`（Windows `/c`）命令，进程使用当前本机用户权限。Web 设置或模型不能扩展启动 allowlist；命令 cwd 固定为会话工作区。

右侧工具区与设置面板均可取消勾选全部或个别工具，设置跨刷新/重启保留；未选中的工具不会绑定给模型，强行调用也不会执行。运行中可以保存工具选择，但更换工作区需要等待当前运行结束。旧版仅有只读工具的设置首次升级会补选 write/edit/command，之后不覆盖用户取消选择。服务端硬禁用使用 `--no-enable-file-mutations` / `--disable-command`，PowerShell 对应 `-EnableFileMutations:$false` / `-DisableCommand`；页面不能重新开放硬禁用能力。

文件首版仅支持单个 UTF-8 文本文件的创建/完整替换和唯一精确 edit；修改前后各不超过 32 KiB，不支持删除、二进制或批量批准。界面显示完整 diff 和可展开的转义内容（包含换行）；批准后重新检查路径、版本和能力，再原子替换，已有文件权限保留。`.env`、`.git`、密钥等敏感路径受同一策略保护。

fake 可离线验证完整审批链，例如发送以下文本（需先启用文件能力）：

```text
写入 {"path":"demo.txt","content":"hello\n"}
修改 {"path":"demo.txt","old_text":"hello","new_text":"world"}
```

离线命令演示语法为 `执行 {"executable":"启动时允许的程序","argv":["--version"],"timeout_seconds":5}`。它仍创建实际待审提案，不是模拟成功；程序参数由用户完整审查。

等待审批时不保留模型连接、不允许发送下一轮或用普通恢复绕过决策。多个工具调用依次审批；分支只复制完成 checkpoint，不复制待执行授权。SQLite 认领和外部副作用不是同一事务：崩溃后的 claimed 操作标记 uncertain，人工核对后可继续模型对话，但原副作用不会自动重跑。取消/超时可能已产生部分外部效果；结果标记不会替用户撤销效果。

关闭审批仅影响新准备的操作。每份提案持久保存其审批策略；旧待审批提案即使以 `--no-require-approval` 重启仍需人工处理。自动模式仍先保存提案，再认领、执行并保存结果，不绕过路径、敏感文件、版本、程序列表、超时、取消和重放检查。

## 开发与模块

后端 `src/pi_agent/web/`: app 负责 HTTP、访问检查与 lifespan; lifecycle 管理本机实例; service 持有应用运行任务并复用 runtime/coordinator, 按已启用能力构造 Web 内建提示词并读取 `PI-AGENTS.md`; store 使用 web_* 表，tools/approval_store 在既有 command_proposals 表上做增量迁移，不修改 LangGraph 表；runtime/coding 编排提案与执行。原 TCP Server 继续读取 `AGENTS.md`。

前端 `web-ui/src/`: App 提供工作台; api 定义类型、请求和活动合并; style 定义响应式视觉。`npm run build` 输出到 `src/pi_agent/web/static`, 由后端同源托管。生成资源不进 Git, 每个新 checkout 需要构建。

开发时先启动 8766 后端, 再在 web-ui 执行 `npm run dev`。Vite 代理 /api 并保留原 Host, 浏览器访问 Vite 输出的本机地址。单个前端构建即可部署, 无需 Node 常驻服务。

## 安全与运行边界

- 服务只绑定 127.0.0.1, 单用户、单 worker。文件锁防止两个 Web 服务同时拥有同一数据库; 独立 CLI/TCP 进程不参与此锁, 不应同时驱动同一数据库。
- API 通过同源 bootstrap 建立 HttpOnly/SameSite=Strict cookie; 检查 Host、Origin、Sec-Fetch-Site 和写请求自定义头, 无跨站 CORS 放行。
- cookie 是本机浏览器访问门槛, 不是多人身份体系。当前不提供公网部署、TLS 或多租户权限。
- 工作区可从 Web 设置更换；模型、数据库、修改能力与程序 allowlist 由启动配置。数据库必须在当前及已有会话工作区之外。文件路径限制不是 OS 沙箱，批准程序可使用本机用户权限；不提供任意 shell 字符串或浏览器终端。
- 浏览器只接收白名单消息与活动元数据, 不接收原始图 state/config、系统提示词或 provider 凭据。展示的工具结果可能包含用户授权读取的文件正文。
- 模型内容经 React/Markdown 安全渲染, 不执行原始 HTML; 外部图片不自动加载。
- 活动最多保留每个会话最近 256 条, SSE 重连始终重新同步快照, 不是无损事件回放。会话列表目前最多返回 500 条, 搜索针对该列表标题。
- 取消/审批可能留下 next 或 interrupt 检查点，用户显式处理后才能继续；同一持久提案不会再次认领。恢复不是跨资源副作用恰好一次保证。
- 流式文本是最多 16 KiB UTF-8 的临时预览，仅完整响应通过校验后进入 checkpoint。失败/取消清除预览，重试使用新消息标识；浏览器重连/刷新取得当前预览和持久历史。预览只保留在运行内存，不写入 lifecycle telemetry；停止服务后不会保留半截文本。
- checkpoint 恢复/分支接口检查来源会话、忙碌/归档状态及检查点；恢复和分支请求各有持久去重记录。分支保留完成对话，节点活动属于各次运行，不复制旧活动记录。
- 命令结果有界，保留退出码、输出和耗时；失败、超时、取消与不确定状态分别记录。POSIX 可清理父进程退出后仍持有管道的进程组；Windows 若父进程先退出而子进程仍存活，当前无法从已退出 PID 可靠推断进程树，会释放管道并报告 uncertain，需人工核对子进程。既有 CLI/TCP 输出方式保留。

## 验证

```powershell
uv run --extra web pytest tests/web -q --basetemp=.pytest-tmp-web
uv run --extra web mypy src tests
uv run ruff check .
uv run ruff format --check .
uv run --extra web pytest -q --basetemp=.pytest-tmp
Push-Location web-ui
npm run test
npm run build
# 首次使用默认 Chromium 时执行 npx playwright install chromium。
# 本机也可以用 $env:PLAYWRIGHT_CHANNEL='msedge' 使用已安装的 Edge。
npm run test:e2e
Pop-Location

# 真实平台启动脚本 smoke：使用隔离工作区/数据库，安装、构建、读取并关闭服务。
uv run python scripts/web_startup_smoke.py
```

浏览器测试启动独立 fake 服务、测试工作区和数据库, 覆盖真实 read、刷新、重命名、归档/恢复、移动端、HTML 安全展示与停止。截图放在 `.pi-agent/qa/`, runtime 数据不进 Git。

后续新增 E2E 覆盖文件 diff/批准/拒绝/刷新以及真实命令审批。真实 Web Provider gate 为 `tests/live/test_web_provider.py`；必须显式加载 `.env` 并设置 `PI_AGENT_LIVE=1`，只在合成工作区执行经过精确校验的提案。实际结果及失败复验见本轮独立验收记录。

2026-09-29 本机验证:

| 检查 | 实际结果 |
|---|---|
| Web 后端聚焦测试 | 11 passed, 真实 LangGraph/SQLite/read 工具, 包含设置持久化与节点详情 |
| 全仓 pytest 资源警告复验 | 586 passed, 4 skipped; 启用 tracemalloc、ResourceWarning 与 PytestUnraisableExceptionWarning 错误门禁, 复验无警告 |
| mypy / Ruff lint / format | 263 source files 通过; lint 通过; 312 Python 文件格式检查通过 |
| 前端单元测试 | 2 passed, 重复活动合并与有界内存 |
| TypeScript / Vite 构建 | 通过 |
| Edge 真实浏览器 E2E | 3 passed, 覆盖读取/刷新/归档与恢复、390px 移动端/HTML 安全展示、停止、节点详情及工作区/工具设置 |
| CLI / wheel | pi-agent-web --help 通过; wheel 打包成功并检查包含静态 HTML/CSS/JS |

首次全仓运行曾出现一个延迟收集的 SQLite ResourceWarning, Web 聚焦与带 tracemalloc 的全仓错误门禁复验均通过, 未对既有代码做无依据的修复。浏览器联调修复了新建会话期间清空新输入的竞态, 测试服务改用直接子进程启动, 避免 Windows shell 包装进程留下监听器。

4 项跳过均为未启用真实 Provider 的既有 live gate。本轮没有读取 .env 或调用真实 compatible 模型; fake 模型、合成文件和本机浏览器证据不代表真实服务已经验证。
