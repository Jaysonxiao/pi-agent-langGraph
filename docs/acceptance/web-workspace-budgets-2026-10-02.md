# Web 工作区分组与六项工具额度

评估、用户授权、实现与本机复验日期：2026-10-02（Asia/Shanghai）。用户认可工作区分组及所有工具最大调用次数方案，并说明未来可能引入直接调用或 LLM 审批；本轮仅增加统一额度，不新增审批方式。本记录独立于此前归档及审批卡片修复的历史测试数字。

## 当前行为

- 左侧按会话保存的完整工作区路径聚合，组内和组间按最近活动排序；文件夹同名但完整路径不同的会话保持独立。组可折叠，显示会话数，悬停查看完整路径；选择会话时展开所属组。折叠状态保存在浏览器，搜索时展开匹配结果。标题和工作区路径均可搜索，归档视图沿用分组。
- 无工作区记录的旧会话显示在“历史 / 未标记”，新增 `workspace_known` 投影区分记录来源；重命名/归档不会把当前默认目录写成旧会话归属。分组不改变现有会话的执行工作区或设置。
- `read`、`list`、`search`、`write`、`edit`、`command` 每项上限均可设置为 0–20，新设置默认各 20。上限为 0 时不执行、不创建新的审批提案。旧设置中已保存的 0/4/7 等数值保留，缺失工具的额度补为 20；旧浏览器提交只读三项额度仍可兼容保存，保留已有 Coding Tools 额度。
- 一次用户请求建立固定额度，跨其中所有模型轮次、审批继续、取消后显式恢复及服务重启共享。新用户消息获得新额度。设置变化不重置原请求额度；恢复时保留原工具集合并尊重当前取消选择的权限限制。
- 执行前扣除槽位，因此失败和拒绝审批也占用次数；同一模型消息与 tool-call 的节点重入复用原判定，不重复扣除。超限返回关联工具错误，不调用执行器。人工审批与既有无需审批启动模式均使用相同入口限制；额度表不提供副作用重放授权。

## 实现与兼容边界

运行时增加可选 `ToolCallBudget` 接口；Web 在 SQLite 新增 `web_tool_turns` 和 `web_tool_calls` 表，保存额度快照、工具集合与调用判定。`BEGIN IMMEDIATE` 保证槽位检查与占用原子完成；调用表只存身份、工具名及判定，不存参数、命令输出或文件正文。图、领域和 CLI/TCP 不依赖 Web 表；CLI/TCP 未注入预算对象，沿用原有默认行为与权限边界。

恢复升级前的 checkpoint 时，首次从当前设置创建额度快照，并根据最后一条用户消息之后的工具结果及已存在提案补记可识别的尝试；已准备提案保留其原操作槽位，未执行的后续调用不提前占用。旧版本没有保存原额度快照，不能追溯精确的旧设置，也不能还原没有任何 checkpoint/提案记录的尝试。新版本创建的请求均有持久账本。

SQLite 更新为增量建表和设置补齐，无需手工迁移。文件/命令的持久提案、认领及 uncertain 不重放机制保持原职责；本轮没有实现新的 LLM 审批策略。

## 实际验证（macOS）

| 检查 | 结果 |
|---|---|
| `uv run --extra web pytest -q --basetemp=/private/tmp/pi-agent-budget-final -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --tb=short` | 660 passed、6 skipped，16.58s；严格完整回归含 CLI/TCP/Web，跳过为未启用的 live gate |
| `uv run --extra web pytest tests/web/test_tool_budget.py -q --basetemp=/private/tmp/pi-agent-budget-final-cases --tb=short` | 18 passed：六项工具分别超限、Coding Tools 的零额度、失败占槽、批准/拒绝后重启继续、额度快照与新请求重置、并发原子占槽、幂等重入、跨会话隔离、旧设置/旧 checkpoint、未标记会话、默认 20 次跨模型轮次、取消/重启/显式恢复 |
| `uv run mypy src tests scripts` | 283 source files 通过 |
| `uv run ruff check .` / `uv run ruff format --check .` / `git diff --check` | 通过；340 files already formatted |
| `npm run test` / `npm run build`（web-ui） | 7 passed；TypeScript/Vite 构建通过 |
| `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` | 10 passed，31.7s：同名工作区分组、路径/标题搜索、折叠与刷新、归档，以及六项上限显示与持久化；原审批顺序、命令、文件、恢复/分支、流式及手机布局均通过 |
| `uv run pi-agent --provider fake --prompt hello --events jsonl` / `uv run pi-agent eval --suite tools --provider fake` | 退出码均为 0；fake 图输出 completed；tools eval 1/1 passed |
| 浏览器截图 | `.pi-agent/qa/workspace-groups.png` 已检查，分组与归档布局正常；合成测试数据和截图不入 Git |

初次完整 Web 子集在受限沙箱中为 64 passed、3 failed；失败均为 lifecycle 测试的 loopback 绑定或 `ps` 权限受限，随后在允许本机端口及进程测试的权限下执行完整回归。新增测试曾遗漏消息分页或使用过短请求 ID，修正测试输入并按指定 checkpoint 加载历史后通过，没有修改产品逻辑掩盖失败。

本轮只验证本机离线模型与真实本机工具，未执行真实 Provider、Windows/Linux 新环境或部署检查。前后端需加载新版本，现有服务重启后刷新页面生效；没有替用户停止运行中的会话。本轮功能与前一项审批卡片修复保留在工作区，未提交或推送。此前 [整体归档](web-cli-review-2026-10-01.md) 与 [后续清单](../follow-ups/web.md) 保留各自边界。
