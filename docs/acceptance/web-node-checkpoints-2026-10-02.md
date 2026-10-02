# Web 执行节点 checkpoint 详情关联修复

发现、实现与复验日期：2026-10-02（Asia/Shanghai）。用户询问哪些节点可查看 checkpoint，并报告“这个节点的 checkpoint 快照暂不可用, 请稍后重试”。本次检查与修复独立记录，不回填此前 Web 归档、卡片位置及工具额度的验证数字。

## 可查看范围

- 模型响应结束、工具执行返回结果的事件，可在对应图节点提交结果后查看输入、输出及执行前后快照；错误返回若已提交结果也可展示。内容沿用安全裁剪投影，不展示系统提示词和原始图状态。
- 六项工具均支持，包含 read/list/search 及经审批执行的 write/edit/command。同一模型响应的多个调用共用一个 `tools` 图节点快照；新事件按 tool-call ID 单独展示被点击调用的输出，执行前后快照覆盖整批调用。
- run_start/run_end、before_model/before_tool 不是可查看的结果节点。取消且没有提交结果的事件不能查看完成快照，界面禁用入口并明确显示取消状态。
- 部分工具已结束但同批工具仍在执行或待审批时，尚无整批完成快照，返回明确 409 提示；处理剩余审批并完成整批后，先前的工具事件即可查看。

## 根因与修复

原接口将某次运行的第 N 条 after_tool 事件映射到第 N 个 tools 结果快照，而一个 tools 节点可以包含多个调用，数量不对应。审批继续会创建新的运行登记，原接口又只选择创建时间不早于新登记的快照；被恢复的工具任务使用的是审批前创建的 checkpoint，因此完成的工具仍会返回 404。旧实现还可能把后续轮次的快照错配给前一事件。

Web 观察 Hook 现在读取 LangGraph 公共 Runtime 的 `execution_info.checkpoint_id`，同时保留工具调用 ID；在 `web_activity` 增量添加两个可空字段，无需修改共享 Hook 契约。详情按会话及明确 checkpoint ID 读取任务结果，避免事件序号与运行时间推测；同批事件关联同一快照，工具输出按调用 ID 过滤。弹窗显示 checkpoint ID 并说明整批快照范围。

旧事件未保存 checkpoint ID 时，按事件发生时最近的同类图任务兼容定位；包含未完成任务，避免把旧的完成结果当成当前待完成结果。旧事件没有调用 ID，同批多次同名工具只能按名称展示匹配结果，不能精确还原单次调用；缺失关联或不存在的 checkpoint 给出明确错误，不承诺重试一定能恢复。读取始终按活动所属会话限定，不能借 checkpoint ID 读取另一会话。

## 实际验证（macOS，离线）

| 检查 | 结果 |
|---|---|
| 新增复现测试修复前 | 3 failed：多工具输出未按单次调用过滤、审批继续工具详情 404、待完成整批提示错误 |
| `uv run --extra web pytest tests/web/test_node_details.py tests/web/test_coding.py tests/web/test_continuation.py -q --basetemp=/private/tmp/pi-agent-node-focused --tb=short` | 30 passed；新增 6 项覆盖多工具/重复工具名、批准后查看及重启/后续对话、待审批整批、旧活动无 ID、跨会话隔离和取消节点 |
| `uv run --extra web pytest -q --basetemp=/private/tmp/pi-agent-node-final -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --tb=short` | 666 passed、6 skipped，19.59s；跳过为未显式启用的 live gate |
| `uv run mypy src tests scripts` / `uv run ruff check .` / `uv run ruff format --check .` / `git diff --check` | 通过；284 source files，342 files already formatted |
| `npm run test` / `npm run build` | 7 passed；TypeScript/Vite 构建通过 |
| `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` | 10 passed，38.6s；增加批准 command 后实际打开详情、checkpoint ID 和输出检查，以及取消节点入口禁用检查 |
| `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e -- --grep 'stop action\|command review'` | 最终 2 passed，6.7s；取消用例等待实际流式预览再停止，确保节点已经开始执行 |
| 截图 | `.pi-agent/qa/approved-command-checkpoint.png` 已检查，详情展示合成命令的结果及正确 checkpoint；测试数据和截图不入 Git |

取消用例补充运行曾为 1 passed/1 failed：仅等待时间线文本可能在模型节点开始前取消，因而没有 after_model 取消事件。改为等待实际流式预览再停止后通过，没有修改产品逻辑掩盖失败。紧接着的重跑因测试端口刚退出仍被占用未启动，确认无监听并等待端口释放后重新执行通过。

仅运行本机离线测试和真实本机工具，未新增真实 Provider、跨平台或部署验证。前后端需重启/刷新加载新版本。未停止用户正在运行的服务，本轮修改保留在工作区，未提交或推送。
