# Web 审批卡片按对话位置展示修复

发现、实现与本机复验日期：2026-10-02（Asia/Shanghai）。用户截图指出：历史批准命令的卡片不断堆在整个聊天末尾，没有跟随所属那轮对话。本次为已归档 Web 的缺陷修复，历史归档与测试数字不回填。

## 原因与修复

原 `App.tsx` 先渲染全部消息，再独立遍历会话级 `view.proposals`，导致 command 和 write/edit 卡片均位于消息末尾，且该列表按数据库插入倒序返回。数据库已有 `message_id` 与 `tool_call_id`，但展示没有使用这些关联。

当前会话和 checkpoint 分页接口现在将审批卡片挂到所属模型工具请求的消息上，按模型原 tool-call 顺序排列。前端在该消息位置渲染卡片，随后才显示工具结果及后续回复。多个回合复用 call ID 时仍使用消息 ID 一起定位，不混淆操作；空文本的模型工具请求也保留卡片位置。write/edit/command 共用此行为。

历史分页按本页消息 ID 查询对应提案，不受原会话级最近 50 项列表限制；旧操作只在加载其历史消息后展示，不再被放到最新对话末尾。使用原有安全投影，不暴露内部文件目标。会话级提案接口保持原行为；审批、执行和去重逻辑没有更改。已有数据库无需迁移，旧提案可直接按现有关联显示；CLI/TCP 入口没有改动。

## 本次实际验证（macOS）

| 检查 | 结果 |
|---|---|
| `uv run --extra web pytest tests/web/test_approval_history.py tests/web/test_coding.py tests/web/test_projection.py -q --basetemp=/private/tmp/pi-agent-approval-history` | 20 passed；新增 55 轮分页、旧卡片超出最近 50 项、服务重启、重复 call ID、跨会话隔离、内部字段不暴露、多卡片按调用顺序排列和不属于本页的卡片不展示 |
| `uv run --extra web pytest -q --basetemp=/private/tmp/pi-agent-approval-final -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --tb=short` | 642 passed、6 skipped，15.95s；跳过为未显式启用的 live gate |
| `uv run mypy src tests scripts` | 280 source files 通过 |
| `uv run ruff check .` / `uv run ruff format --check .` / `git diff --check` | 通过；336 files already formatted |
| `npm run test` / `npm run build`（web-ui） | 4 passed；TypeScript/Vite 构建通过 |
| `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` | 最终 9 passed，29.6s；新增两轮真实命令批准后继续普通对话、刷新后的卡片 DOM 顺序检查，补充 write/edit 批准/拒绝顺序检查 |
| 浏览器截图 | `.pi-agent/qa/approval-turn-order.png` 已检查：命令卡片位于对应工具结果和最终回复之前；截图为合成测试会话，不入 Git |

新增浏览器检查初次为 8 passed、1 failed：第三轮发送后，测试匹配到上一轮的“已完成”提示，在新回复完成前读取 DOM，少了一条尚未生成的 assistant 消息。调整为等待实际消息/卡片 DOM 顺序后，全部 9 项通过；没有用固定延时掩盖问题。uv 使用临时缓存目录；完整测试与浏览器测试在允许 loopback/进程测试的权限下执行。

本次未运行真实 Provider、跨平台或部署验证。前后端均需加载新版本，正在运行的旧 Web 服务需重启后刷新页面；没有替用户停止其正在运行的会话。原 [整体归档](web-cli-review-2026-10-01.md) 与 [后续清单](../follow-ups/web.md) 的边界保持原归属。
