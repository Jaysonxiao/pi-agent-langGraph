# Web Token 用量与节点详情展示

实现与复验日期：2026-10-02（Asia/Shanghai）。用户要求动态展示整体与当前会话 Token 消耗、默认展开执行快照，并优化节点弹窗。本次独立记录，不回填此前归档或修复的验证数字；模型思考强度按用户要求暂不实现。

## 交付行为与统计边界

- 输入框下方始终展示“累计 Token”和“当前会话 Token”，包含输入、输出、总数。累计覆盖当前 Web 数据库全部会话，包括归档；当前会话仅统计归属该会话的实际模型请求。复制 checkpoint 分支历史不再次计费，新分支从自己的实际请求开始累计。
- Web 在模型适配边界为每次实际调用建立 SQLite 用量记录，包括重试；审批继续只有发生新模型调用才增加。重复请求、刷新、服务重启及重复审批不重复计数。账本只存关联 ID、状态与数值，不保存提示词、正文或密钥；CLI/TCP 不注入此包装器。
- 原生流的 usage 到达时更新同一条请求记录，累计分片覆盖前值而非相加。会话 SSE 推送全局及当前会话统计，页面以 epoch/revision 和请求版本避免迟到响应覆盖；5 秒轮询补偿断连和没有活动会话的场景。compatible 客户端已有 `stream_options.include_usage` 请求配置，仍取决于服务端是否回传。
- 使用 Provider 回传的真实 usage，不新增估算或金额计算。未回传时显示“统计中”或“未提供”，不能解释成零；部分请求未知时数字标为“已知”，并提示未提供完整用量的请求数。失败、取消、进程中断保留已收到的数字，同时标记统计不完整。Provider 仅在结束时报告 usage 时，数字也只在结束时更新。
- 首次升级从已有会话最新状态中可取得的 AI 消息及模型任务结果回填一次；按消息 ID 去重复制历史、优先归属较早创建的会话。旧的失败调用、已压缩/删除的消息、缺少消息 ID 或 usage 的历史不能精确恢复；缺少 usage 的可识别消息计为未知。这不是模型账户账单或不可恢复历史的完整账本。
- 节点弹窗默认展开执行前、执行后快照；输入/输出分栏、消息数、状态/工具轮次、checkpoint ID 与快照复制按钮；固定标题/关闭入口，正文与长面板滚动。手机单列，无横向溢出；支持 Escape、焦点返回和按钮边界的 Tab 循环。沿用后端安全裁剪，批次快照与单次调用输出范围仍有明确说明；未完成和取消节点的查看规则不改变。

## 实际验证（macOS，离线）

| 检查 | 结果 |
|---|---|
| 新增 `tests/web/test_usage.py` 与工具策略聚焦回归 | 19 passed；新增 9 个用例覆盖累计/会话/归档/分支、去重与重启、审批继续、重试、未知 usage、流式累计覆盖、取消、历史回填及崩溃恢复 |
| `uv run --extra web pytest -q --basetemp=/private/tmp/pi-agent-tokens-final -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --tb=short` | 675 passed、6 skipped，19.61s；跳过未显式启用的 live gate |
| `uv run --extra web pytest tests/web -q --basetemp=/private/tmp/pi-agent-usage-web --tb=short` | 84 passed，16.82s |
| `uv run mypy src tests scripts` / `uv run ruff check .` / `uv run ruff format --check .` | 通过；286 source files、345 files already formatted |
| `npm run test` / `npm run build` | 9 passed；TypeScript/Vite 构建通过 |
| `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` | 11 passed，34.0s；Token SSE 展示/刷新/新会话、默认展开前后快照、复制 checkpoint、手机详情与 Escape 关闭，现有会话/审批/取消/恢复/分支同时通过 |
| `uv run pi-agent --provider fake --prompt hello --events jsonl` / `uv run pi-agent eval --suite tools --provider fake` | fake reply 与事件正常；工具套件 1/1 passed |
| `git diff --check` / 更新文档的本地链接检查 | 通过；引用的本地文件均存在 |
| 截图检查 | `.pi-agent/qa/token-usage.png`、`approved-command-checkpoint.png`、`mobile-node-details.png` 已逐张检查；仅合成测试数据，截图不入 Git |

首次浏览器运行 10 passed/1 failed：测试用 `innerText` 读取带换行的可见内容，再用默认比较 DOM 文本的 `toHaveText` 断言，导致空白差异；统一使用 `textContent` 后全部通过。首次严格全仓 674 passed/1 failed/6 skipped：旧服务生命周期测试把临时目录 `pi-agent-tokens-all` 的单词当成泄密；改为检查公开状态不包含敏感字段或实际随机控制令牌，原测试目的保留，最终通过。未修改产品行为掩盖失败。

浏览器首次启动曾因自动审批审查额度不足而未执行，用户要求继续后重试成功；上表仅记录实际执行结果。未运行真实 Provider、跨平台或部署验证。前后端需重启服务并刷新浏览器加载新版本；未停止用户现有服务。本轮改动保留工作区，未提交或推送。
