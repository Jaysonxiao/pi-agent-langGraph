# Pi 本机工作台

2026-09-29: 根据用户要求直接实现, 本扩展不使用教学练习或待填 TODO, 也不改变 M11 的验收状态。

## 已实现

- React / TypeScript 三栏界面, 中文交互, 手机窄屏侧栏, Markdown/代码块, 复制回复。
- 会话新建、列表、标题搜索、自动标题、重命名、归档与恢复。
- FastAPI 调用现有 `run_session`、LangGraph 异步只读工具图与 SQLite checkpoint。
- compatible 模型使用已有服务端配置; fake 模式明确标识为演示, 真实调用 read/list 后展示返回内容。
- SSE 推送模型/工具阶段, 右侧展示真实 Hook 活动; 回答以完整消息呈现, 不是逐 token 输出。
- 服务端持有运行任务, 浏览器刷新/断线不主动取消, 显式停止按 run_id 取消并等待清理。
- 内建 Pi Workbench 系统提示词负责身份与工具边界; 项目规则独立使用 `PI-AGENTS.md`, 不加载 Codex 的 `AGENTS.md` / `CLAUDE.md`。规范见 [PI-AGENTS.md 规范](pi-agents.md)。
- 深色像素风工作台; 欢迎页覆盖写作、分析、规划与工作区任务。
- 设置面板可更换本地工作区、启用/停用 `read`、`list`、`search`, 并分别配置每轮运行的调用上限 (0–20, 默认各 4); 达到单工具上限后会返回明确的未执行结果。已创建会话固定使用创建时的工作区, 设置应用于后续运行。
- 执行时间线中已完成的模型/工具节点可点击查看安全投影后的输入、输出与 checkpoint 前后快照; 系统提示词及原始图状态不会发送到浏览器。
- 持久化请求标识与内容摘要防止重复执行; 同一标识配不同内容返回 409。
- 消息按指定 checkpoint 分页, 每页最多 40 条、每条最多 16 KiB UTF-8, 长内容显示截断提示。
- 重启后保留会话; 未结束的运行登记为 needs_recovery, 不自动重放。

## 启动

需要 Node.js 22.12+ (或符合 Vite 要求的 Node LTS)、Python 3.11+ 和 uv。

```powershell
# 项目根目录; 安装依赖、构建并启动。
.\scripts\start-web.ps1

# 使用现有 compatible 配置; 自动读取项目根目录 .env。
.\scripts\start-web.ps1 -Provider compatible
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

## 开发与模块

后端 `src/pi_agent/web/`: app 负责 HTTP、访问检查与 lifespan; service 持有应用运行任务并复用 runtime/coordinator, 显式选用 Web 的内建提示词和 `PI-AGENTS.md`; store 在 Web 数据库内新增 web_* 表, 不修改 LangGraph 表; schemas 定义展示契约; demo 是离线工具演示。原 TCP Server 继续读取 `AGENTS.md`。

前端 `web-ui/src/`: App 提供工作台; api 定义类型、请求和活动合并; style 定义响应式视觉。`npm run build` 输出到 `src/pi_agent/web/static`, 由后端同源托管。生成资源不进 Git, 每个新 checkout 需要构建。

开发时先启动 8766 后端, 再在 web-ui 执行 `npm run dev`。Vite 代理 /api 并保留原 Host, 浏览器访问 Vite 输出的本机地址。单个前端构建即可部署, 无需 Node 常驻服务。

## 安全与运行边界

- 服务只绑定 127.0.0.1, 单用户、单 worker。文件锁防止两个 Web 服务同时拥有同一数据库; 独立 CLI/TCP 进程不参与此锁, 不应同时驱动同一数据库。
- API 通过同源 bootstrap 建立 HttpOnly/SameSite=Strict cookie; 检查 Host、Origin、Sec-Fetch-Site 和写请求自定义头, 无跨站 CORS 放行。
- cookie 是本机浏览器访问门槛, 不是多人身份体系。当前不提供公网部署、TLS 或多租户权限。
- 工作区可从 Web 设置更换；模型与数据库由服务端启动配置。数据库必须在当前及已有会话工作区之外。read/list/search 延续现有路径策略; 不提供写文件、浏览器终端或命令审批入口。
- 浏览器只接收白名单消息与活动元数据, 不接收原始图 state/config、系统提示词或 provider 凭据。展示的工具结果可能包含用户授权读取的文件正文。
- 模型内容经 React/Markdown 安全渲染, 不执行原始 HTML; 外部图片不自动加载。
- 活动最多保留每个会话最近 256 条, SSE 重连始终重新同步快照, 不是无损事件回放。会话列表目前最多返回 500 条, 搜索针对该列表标题。
- 部分运行被取消时可能留下 `next` 检查点; 界面提示新建会话继续, 不提供自动恢复副作用。
- 本版完整消息/节点级进度已接线; 逐 token、checkpoint 分支与命令审批尚未接入 Web。既有 CLI/TCP 行为不因此升级。

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
```

浏览器测试启动独立 fake 服务、测试工作区和数据库, 覆盖真实 read、刷新、重命名、归档/恢复、移动端、HTML 安全展示与停止。截图放在 `.pi-agent/qa/`, runtime 数据不进 Git。

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
