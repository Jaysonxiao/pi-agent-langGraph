# Web 服务管理与 Coding Tools 验收记录

实现、验证日期：2026-10-01（Asia/Shanghai）。范围见[开发计划](../design/web-coding-plan.md)。本记录独立于 M0–M11 和上一轮 Web 扩展。

归档日期：2026-10-01。用户授权归档已交付范围并合并到本地 `main`，暂不 push。归档结论见 [Web 归档](web-archive-2026-10-01.md)，未关闭项统一见 [后续清单](../follow-ups/web.md)。逐项用户手工功能验收没有另行记录；下方保留实际自动化和 live 验证事实。

## 已交付行为

- Python Web 入口及 Bash/PowerShell 提供 start/status/stop/restart。实例登记只在持有数据库锁时发布；通过 PID 启动身份和本机随机令牌确认归属。POSIX 暂停实例可恢复后优雅退出；身份不匹配、旧版未登记服务不自动控制。状态/停止不需要构建前端，启动冲突有数据库/端口诊断。
- 在既有 command_proposals 表增量添加文件类型、内容、操作身份、版本和决策；旧 CLI 命令提案仍可显示/认领。相同操作去重，不同模型消息中的同参数命令得到不同提案；terminal 结果可回灌，不重复执行。
- 异步工具节点使用持久 interrupt 等待人工决策。多调用重入保留中断位置，恢复值绑定提案 ID；next 为空但仍有 interrupt 的检查点也能继续审批。普通 resume 不能绕过 pending；版本/会话/能力检查由服务端负责。
- 默认仍只有只读工具。文件与命令能力由启动选项启用，系统提示词随服务端能力调整；Web/模型不能扩大程序 allowlist。
- Web 显示文件 diff/完整转义内容、命令 executable/argv/cwd、等待审批、批准/拒绝及持久结果；刷新和断线不消耗批准，多个提案串行处理。
- 文件创建/替换/唯一 edit 先准备，再重新校验路径、敏感文件、目标和 before hash；原子替换保留既有权限。内容各限 32 KiB；不提供删除/二进制/批量批准。
- 命令审批复用原认领/执行组件，共享 Web 取消令牌；保存有界输出、退出码和耗时，非零、超时、取消及结果不明分别记录。重启将 Web claimed 操作标记 uncertain，不能自动重跑。
- POSIX 修复父进程已退出、子进程仍占管道时的清理。Windows 无法从已退出父 PID 可靠找回子进程树时，会释放管道并报告不确定，而非一直等待或宣称已回收。

## 本机实际验证

| 命令/检查 | 实际结果 |
|---|---|
| `pytest tests/web/test_lifecycle.py` | 3 passed：真实服务、暂停/停止/重启、重复停止、实例令牌、身份不匹配及端口冲突 |
| `pytest tests/web/test_coding.py` | 17 passed：持久审批、拒绝/冲突、多个提案、敏感路径、旧表迁移、认领中断、写入后登记失败、不确定结果、独立重复命令、取消后恢复、截断和非零退出 |
| 进程树/超时/取消与审批聚焦组合 | 31 passed；包括真实 POSIX 父子进程和父进程提前退出场景 |
| 全仓 pytest，ResourceWarning 与 PytestUnraisableExceptionWarning 均设为错误 | **626 passed、6 skipped**，13.97s，无警告；6 项 live gate 在默认离线套件中跳过 |
| mypy `src tests scripts` | 276 source files 通过 |
| mypy `--platform win32 src tests scripts` | 276 source files 通过；这是条件分支类型检查，不能替代 Windows 实际执行 |
| Ruff lint / format-check、`git diff --check` | 通过；Python 文件格式检查通过 |
| 前端单测 / 构建 | 4 passed；TypeScript/Vite 通过 |
| Chrome 浏览器 E2E | 7 passed，22.5s；文件 diff/批准/拒绝/刷新、命令真实输出、既有读取/设置/移动端/恢复/分支 |
| `uv run python scripts/web_startup_smoke.py` | 通过，真实 Bash launcher 在带空格隔离工作区完成安装/构建、HTTP/read、持久消息与服务回收 |
| 显式 live Web gate | **2 passed**，33.26s；命令见下方，真实 compatible 请求，合成工作区 |
| Linux/Windows CI | 未执行。此前开发分支推送被自动审批审查拒绝；归档时用户要求仅合并本地 main、暂不 push，未触发远端 CI；不能以矩阵配置视为通过 |

真实 Web 验证命令：

```bash
PI_AGENT_LIVE=1 uv run --env-file .env --extra web pytest tests/live/test_web_provider.py \
  -q --basetemp=.pytest-tmp-live-web --tb=short
```

第一项在真实响应分片到达后施加测试门控，验证取消传输、关闭/重开数据库、显式恢复只保留一个用户消息与最终回复，再创建独立完成 checkpoint 分支。门控只用于稳定取消时机，不冒充 Provider 断网或故障恢复。第二项让真实模型生成文件/命令提案，测试精确核对文件名与内容或 `sys.executable --version` 后提交人工决策，验证实际副作用及模型回灌。测试不会批准模型提出的任意其他命令。

## 失败与修复记录

- 最初服务测试漏设 loopback TestClient 地址，被 Host 检查拒绝；修正测试地址。
- 多工具调用恢复时跳过已完成提案的 interrupt 会错配后续恢复值；现在保持位置稳定并校验提案身份。状态读取也显式识别 interrupt，不仅检查 next。
- 相同 tool-call ID 在后续模型消息重复出现时，原结果 ID 会覆盖历史；Coding Tools 结果 ID 现在绑定持久操作身份，独立重复命令测试通过。
- 第一轮全仓回归 620 passed，但新迁移测试未关闭 sqlite 连接，出现 ResourceWarning；改为显式关闭，后续严格错误门禁无警告。
- 初次 live 流取消测试适配器漏了 aclose 协议，实际落到完整回复路径；补齐协议。默认 Web 提示词仍声明只读，现按已启用能力构造提示词。
- live 回灌曾出现 Provider 请求失败，文件提案已成功写入但模型回复未完成；保留此失败事实。合成消息的直接传输探测可成功，添加不含 URL/密钥/正文的异常分类诊断，并按 Web 默认重试策略组合复验，最终两项通过。不能由此次成功推断 Provider 永久稳定或所有真实取消场景已覆盖。
- 沙箱中 uv 共享缓存、本机监听/进程身份权限与网络调用受限；相关真实命令在允许权限下执行，未将环境拒绝视为代码通过。
- 为触发实际平台 CI，创建本地 `codex/web-service-approvals` 分支并提交开发结果。推送到当前 origin `https://github.com/Jaysonxiao/pi-agent-langGraph.git` 被自动审批审查拒绝：尚未确认向此具体目的地导出代码的授权。没有推送成功或远端 CI 运行证据；后续需用户明确批准这一目的地。

## 边界与剩余项

- 用户授权已交付范围归档；逐项手工功能验收和远端矩阵证据仍未另行记录，见后续清单 W1/W3。M11 D1–D3 只按对应实际证据更新，公网部署仍不在本轮范围。
- 文件与数据库、进程与数据库不是同一事务。uncertain 需要人工核对；没有跨资源 exactly-once 保证，也不自动撤销已发生的部分效果。
- Windows 父进程提前退出后遗留子进程的严格回收需要独立进程容器/Job Object 能力；当前明确报告不确定。普通父进程仍存活时沿用 taskkill /T。
- 文件路径限制不是 OS 沙箱。程序 allowlist/argv 审批也不限制程序以当前用户权限访问其他主机资源；本轮限本机单用户使用。
- 新建过往只读会话、CLI/TCP 行为、历史验收数与日期保留；没有自动迁移用户旧版服务进程或删除其文件锁。
