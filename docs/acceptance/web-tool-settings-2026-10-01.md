# Web 工具默认值、审批开关与选择调整

实现与验证日期：2026-10-01（Asia/Shanghai）。用户反馈归档版本基本可用，明确要求默认开启 write/edit/command、审批参数、简化工具名称、全部工具可取消选择。本轮是已归档 Web 的体验调整，开发在本地 main 工作区进行，不 push；不改写 [归档基线](web-archive-2026-10-01.md) 的验证数字。

## 已实现

- 新配置默认选中 read/list/search/write/edit/command；文件默认可用，命令默认允许 POSIX `/bin/sh` 或 Windows 系统 `cmd.exe`。自定义 `--allow-executable` 替换默认程序列表；服务端仍可硬禁用文件或命令能力。
- `--require-approval` 默认开启，`--no-require-approval` 关闭新操作的人工审批；PowerShell 使用 `-RequireApproval $false`。自动模式仍保存提案、认领、执行、保存结果并回灌模型，不绕过文件路径/版本、程序列表、超时、取消及 uncertain 边界。
- 右侧和设置面板支持全部六项工具勾选；工具名称展示 write/edit/command，内部 propose_command 保持历史兼容。选择跨刷新/重启保留；旧只读设置仅一次补选新工具，之后尊重用户取消选择。
- 设置保存从下一轮生效；进行中的一轮沿用创建时的工具/上限快照。未选择的工具不绑定给模型；模型强行发出调用也无副作用。页面在保存时暂缓发送下一轮，避免使用尚未持久保存的选择。
- 每份提案保存审批策略；旧待审批提案即使以自动模式重启也不会自动批准。取消选择后不得批准对应能力，可拒绝后继续。

## 实际验证（macOS）

| 检查 | 结果 |
|---|---|
| 新增 `tests/web/test_tool_policy.py` | 10 项在最终全仓回归通过：默认值、自动多工具真实执行/去重/重启、旧审批保留、三种取消选择、旧设置（有记录/空表）迁移、运行中更新与模型绑定、服务端硬禁用 |
| 全仓 pytest，ResourceWarning / PytestUnraisableExceptionWarning 作为错误 | 636 passed、6 skipped，15.38s；跳过为未显式启用的 live gate |
| mypy `src tests scripts` | 278 source files 通过 |
| Ruff lint / format-check、`git diff --check` | 通过；改动文档的本地文件链接存在 |
| 前端单测 / TypeScript/Vite 构建 | 4 passed；构建通过 |
| Chrome E2E | 8 passed，24.4s；默认六项选中、取消全部/刷新/下一轮拦截、设置面板及既有文件/命令审批、读取、移动端、取消、流式、恢复与分支；工具选择截图已检查 |
| 真实 Bash 启动 smoke | 通过；默认六项工具、默认审批和程序列表、真实 HTTP/read、持久历史与服务回收 |

初次浏览器实测发现受控勾选框在保存响应前短暂恢复旧状态，导致点击检查失败及后续用例受共享设置影响；已采用即时显示选择、保存失败恢复原值，并复验。沙箱下三项服务测试因本机监听/ps 权限失败，完整回归在允许权限下通过，未把环境拒绝记为代码通过。

最终检查补充旧版空 settings 表：其新增版本列默认值仍为 1，保存时必须显式写入版本 2，避免下次重启重新补选用户已取消的工具。已修复并由有记录/空表两类迁移用例覆盖。

未重新运行真实 Provider、新环境 Linux/Windows、PowerShell 实机或部署验证，既有 live 结果仍属于原验收范围；不据本轮离线结果外推。后置事项仍见 [Web 后续清单](../follow-ups/web.md)。用户“基本可用”的反馈不是全部场景手工验收证据。
