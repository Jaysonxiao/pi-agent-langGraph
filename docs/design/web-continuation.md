# Web 工作台后续开发计划

计划日期：2026-10-01（Asia/Shanghai）。用户授权先计划、再直接开发；本轮独立于已归档的 M0–M11。

## 范围与顺序

1. **跨平台启动**：保留 Windows 脚本，补齐 macOS/Linux Bash 入口、文档和自动化启动 smoke。优先在当前 macOS 实测；CI 配置覆盖 Linux/macOS，远端结果另行记录，不能把配置当作通过。
2. **Web 中断恢复与分支**：用户明确点击后，从当前未完成 checkpoint 继续只读图，不重复加入用户消息；支持查看完成的 checkpoint 并复制为独立会话。保持原会话、工作区、审批边界和请求去重。归档/忙碌/过期 checkpoint 拒绝操作；重启不自动运行。
3. **Web 流式回复**：复用 compatible HTTP 原生 SSE 与完整 tool-call 装配；浏览器按文本分片更新。临时文本与持久完整消息分开，取消/失败/重试不能把半截回复写入历史或执行半截工具。浏览器刷新、SSE 重连通过快照恢复当前显示；不把正文放入 lifecycle telemetry。

本轮不增加文件写入、命令审批、公网服务、多用户身份、跨资源 exactly-once 或模型质量承诺。没有流能力的模型保留完整回复；离线 demo 分片用于界面验证，不冒充真实模型。

## 验收条件

- Bash 参数、带空格路径、失败退出可验证；实际 fake 服务能返回 bootstrap 并完成真实 read 请求。离线启动 smoke 可在隔离数据库中运行且回收服务。
- 恢复重复请求只创建一个运行；过期 checkpoint、忙碌和归档状态拒绝；取消/重启之后显式恢复不会新增重复用户消息。
- 分支只复制完成 checkpoint，不执行模型/工具；来源不变；分支继承来源工作区；新会话独立续聊，重复请求返回同一分支。
- 流式工具参数只有完整且合法才执行；失败/取消释放流，重试清除旧临时文本；刷新和完成后的展示与持久消息一致。
- 后端聚焦与全仓 pytest、mypy、Ruff；前端单测、构建、浏览器 E2E。真实 provider 和远端 Linux/macOS CI 仅在实际执行后记录通过。

## 执行记录

- 2026-10-01：先建立计划，再完成本轮开发；状态为本机离线范围开发与验证完成。用户验收另行进行，不改写 M0–M11 的历史结果。
- Bash 启动脚本设置可执行权限；相对路径以项目根目录解析；支持 provider/workspace/database/port 和帮助。增加标准库启动 smoke，以及 Ubuntu/macOS/Windows Web CI job（安装、构建、真实 launcher smoke、Chromium E2E）。
- Web 新增显式 resume、完成 checkpoint 列表和分支 API/界面；恢复去重记录区分 prompt/resume，旧数据库自动补充字段；分支先持久预留目标 ID，失败重试沿用同一目标。使用相同状态 schema 的终态 writer 复制完成状态，不调用节点。
- Web 注入独立 text observer，compatible 模型消费原生 SSE；完整文本、tool-call JSON 和最终 usage 装配后进入图。临时预览限制为 16 KiB UTF-8，带消息标识和递增 revision；重试丢弃旧预览，完成后按消息 ID 与持久历史对齐。CLI/TCP 不注入 observer，保留原输出行为。

### 2026-10-01 实际验证（macOS 本机）

| 命令/检查 | 实际结果 |
|---|---|
| `bash -n scripts/start-web.sh`、`--help`、隔离模拟命令流程 | 通过；覆盖默认/自定义参数、空格路径、项目根目录解析、.env 选择、安装复用、非法参数和失败传播 |
| `uv run python scripts/web_startup_smoke.py` | 退出码 0；真实 Bash launcher 完成 Python 同步、前端构建、HTTP bootstrap、合成文件 read、持久消息与服务回收。当前前端依赖已存在，因此该次未触发 `npm ci` |
| `.venv/bin/pytest -q --basetemp=.pytest-tmp -W error::ResourceWarning` | **604 passed、4 skipped**，9.07s；跳过均为未启用的 live Provider gate，无 ResourceWarning |
| `.venv/bin/mypy src tests scripts` | 通过，269 source files；修正既有 subprocess smoke 的 Windows 常量判断，使 macOS 类型检查通过 |
| Ruff lint / format-check、`git diff --check` | 通过；319 Python files 格式检查通过 |
| `npm run test` / `npm run build` | **4 passed**；TypeScript/Vite 构建通过 |
| `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` | **5 passed**，14.7s；涵盖真实 read、刷新/会话管理、移动端/安全渲染、停止、流式预览、显式恢复与分支独立续聊 |
| 原生 compatible HTTP SSE 离线集成 | MockTransport 驱动真实 HTTP adapter→图→read→回灌→最终流式回复；不完整参数流失败且零工具执行 |
| 文档链接与界面截图 | 改动文档本地链接存在；检查分支选择和流式预览截图，沿用工作台布局 |

执行边界：本机非交互 PATH 未加载 nvm，后来使用已有 nvm Node/npm 完成标准 npm 命令；曾尝试临时工具下载但网络失败，不计为通过。默认沙箱禁止 uv 共享缓存和本机端口，相关命令以正常权限复验。远端 CI 尚未触发，独立 Linux/Windows 环境、真实 compatible 服务的新流式路径没有本轮实测结果；M11 D1–D3 不因此关闭。
