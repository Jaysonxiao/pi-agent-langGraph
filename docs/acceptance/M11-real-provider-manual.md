# M11 真实模型用户验收用例与执行记录

本文件记录用户于 2026-09-29 在 Windows 本机执行的公开 CLI 和 live-provider 验证。Agent 请求显式使用 `compatible`，连接用户配置的真实 OpenAI-compatible 端点；这些结果不代表其他服务商、部署网络或生产环境通过。M11 自动化结果见 [验收记录](M11.md)，后置环境/部署验证见 [后置验证记录](../history/2026-09-28-m11-deferred-deployment-validation.md)。

| 本次用户可见验证 | 对应开发阶段 |
|---|---|
| 安装、配置、真实模型回复和事件终态 | M1–M3、M5、M8 |
| 真实只读文件工具与工作区边界 | M3–M4、M8 |
| SQLite 会话连续性、隔离和目录查询 | M6、M8 |
| telemetry 工具轨迹与脱敏检查 | M9、M11 |
| 本机远程会话、快照和服务端重启 | M10 |
| live tests 的流式回复与摘要/压缩路径 | M7–M8 |

## 0. 准备与记录

在仓库根目录打开 PowerShell，安装 Python 3.11+ 与 uv，并准备一个支持 `/chat/completions`、流式输出和工具调用的兼容端点。真实调用可能产生费用。只向模型提供下面新建的合成工作区，不放入个人文件或凭据。

若 `.env` 尚不存在，可从 `.env.example` 复制并填写；已有 `.env` 不要覆盖。它被 Git 忽略。至少设置：

```dotenv
PI_AGENT_PROVIDER=compatible
PI_AGENT_MODEL=<真实模型 ID>
PI_AGENT_BASE_URL=<HTTP(S) API 根地址，例如 https://服务商地址/v1>
PI_AGENT_API_KEY=<真实密钥>
```

`PI_AGENT_BASE_URL` 不包含 `/chat/completions`，程序会追加该路径。凭据也可通过 `PI_AGENT_API_KEY_ENV` 指向另一个环境变量。不要把 `.env`、完整模型请求或密钥贴进验收记录。

先检查安装和非敏感配置投影；该检查不调用模型：

```powershell
uv sync --all-extras
uv run --env-file .env python -c "import os; from pi_agent.models.config import ModelOptions, resolve_model_config; print(resolve_model_config(ModelOptions(), dict(os.environ)).public_dict())"
```

应看到 `provider=compatible`、预期模型 ID 与 API 根地址，且没有 API key 字段。然后在**同一个终端**创建唯一的合成用例目录；以下变量供第 1–4 步复用：

```powershell
$caseRoot = Join-Path $env:TEMP ("pi-agent-real-" + [guid]::NewGuid().ToString("N"))
$workspace = Join-Path $caseRoot "workspace"
$database = Join-Path $caseRoot "sessions.sqlite"
$sessionId = "manual-" + [guid]::NewGuid().ToString("N")
$marker = "M11-PROBE-" + [guid]::NewGuid().ToString("N")
New-Item -ItemType Directory -Path $caseRoot | Out-Null
New-Item -ItemType Directory -Path $workspace | Out-Null
Set-Content -LiteralPath (Join-Path $workspace "probe.txt") -Encoding utf8 -Value "Marker: $marker"
```

记录运行日期、OS/Python、模型 ID、API 根地址的主机名、`$caseRoot` 和 `$sessionId`。结果只写“通过 / 失败 / 未执行 / 未触发”，不要预填通过。

## 1. 真实模型读取文件并完成一轮

```powershell
uv run --env-file .env pi-agent --provider compatible --workspace $workspace --database $database --session-id $sessionId --prompt "Use the read tool to open probe.txt. Answer with the exact value after Marker; do not guess." --events jsonl --telemetry-file telemetry.jsonl
$LASTEXITCODE
```

核对：

- CLI 退出码为 0，JSONL 中出现最终 `state_update` 且 `status=completed`，回答包含 `$marker`。
- `$workspace\telemetry.jsonl` 有 `agent.run` / `agent.model` 的 span 起止记录，并有 `name=agent.tool`、`attributes.tool_name=read` 的工具 span；工具最终 `outcome=completed`。仅有模型声称“我读了文件”不算工具执行证据。
- telemetry 中没有 `$marker`、prompt 正文或 API key。可用下列命令检查**合成 marker**；不要把真实密钥写进查询命令或输出：

```powershell
$telemetry = Join-Path $workspace "telemetry.jsonl"
Get-Content -LiteralPath $telemetry | ConvertFrom-Json | Where-Object { $_.kind -eq "span_started" -and $_.name -eq "agent.tool" -and $_.attributes.tool_name -eq "read" } | Select-Object -First 1
Select-String -LiteralPath $telemetry -SimpleMatch -Pattern $marker
```

`Select-String` 应无匹配。如果模型没有调用 `read`，本项记为“未触发工具验证”，即使它给出看似正确的回答也不算通过；记录模型响应和工具轨迹后再判断是模型选择还是接线问题。

## 2. 同一会话恢复与隔离

把文件改成新值，再用**相同**的 `$database` 和 `$sessionId` 询问上一轮的旧值：

```powershell
$newMarker = "M11-NEW-" + [guid]::NewGuid().ToString("N")
Set-Content -LiteralPath (Join-Path $workspace "probe.txt") -Encoding utf8 -Value "Marker: $newMarker"
uv run --env-file .env pi-agent --provider compatible --workspace $workspace --database $database --session-id $sessionId --prompt "Without reading files again, what exact Marker value did you report in your previous answer?" --events jsonl --telemetry-file telemetry.jsonl
$LASTEXITCODE
uv run pi-agent session list --database $database
```

预期第二轮完成并说出旧 `$marker`，不是文件里的 `$newMarker`；`session list` 包含 `$sessionId`。这是从用户角度检查 SQLite 会话连续性。模型仍可能自行调用工具，故同时核对本轮 telemetry；若只返回新值或无法说明前一轮，记录原样结果，不判通过。

用一个全新的 session ID 问同样的问题，可辅助确认历史没有串到别的会话：

```powershell
$freshSession = "fresh-" + [guid]::NewGuid().ToString("N")
uv run --env-file .env pi-agent --provider compatible --workspace $workspace --database $database --session-id $freshSession --prompt "What Marker did you report in our previous turn? If there was no previous turn, say so." --events jsonl
```

预期新会话不声称记得旧 `$marker`。自然语言回答有不确定性；若要进一步定位，使用第 5 步的 live tests 核对传给模型的历史消息。

## 3. 工作区边界（合成数据）

在工作区外放一个**合成**标记，请模型尝试读取相对越界路径：

```powershell
$outsideMarker = "OUTSIDE-" + [guid]::NewGuid().ToString("N")
Set-Content -LiteralPath (Join-Path $caseRoot "outside.txt") -Encoding utf8 -Value $outsideMarker
uv run --env-file .env pi-agent --provider compatible --workspace $workspace --database $database --session-id $sessionId --prompt "Use the read tool to open ../outside.txt, then report what happened." --events jsonl --telemetry-file telemetry.jsonl
```

预期 `$outsideMarker` 不出现在回答或事件里，越界工具请求被拒绝或报告受控错误。只有观察到实际 `read` 调用且被路径策略拒绝时，才把“路径拦截”记为通过；若模型拒绝调用工具，本项记为“未触发”，不能据此证明工具边界。此例不包含真实秘密。

## 4. 本机远程会话（真实模型）

该路径验证 M10 的公开 server/client、认证、快照和 SQLite 重启恢复，仍只绑定 `127.0.0.1`。在**终端 A**保留第 0 步的 `$workspace`、`$caseRoot`，设置一个临时令牌并启动服务端；输入令牌时不在命令行写明文：

```powershell
$env:PI_AGENT_REMOTE_TOKEN = (Read-Host -AsSecureString "输入本机临时令牌" | ConvertFrom-SecureString -AsPlainText)
$remoteDatabase = Join-Path $caseRoot "remote.sqlite"
uv run --env-file .env pi-agent-server --provider compatible --workspace $workspace --database $remoteDatabase --port 8765
```

预期服务端输出 `{"event":"ready","host":"127.0.0.1","port":8765}`。若端口已占用，另选端口并在以下命令中保持一致。在仓库根目录打开**终端 B**，输入同一个临时令牌：

```powershell
$env:PI_AGENT_REMOTE_TOKEN = (Read-Host -AsSecureString "输入与终端 A 相同的令牌" | ConvertFrom-SecureString -AsPlainText)
uv run pi-agent-client --port 8765 create
```

从 JSON 复制返回的 `session_id`，在终端 B 继续：

```powershell
$remoteSession = "<上一步返回的 session_id>"
uv run pi-agent-client --port 8765 prompt --session-id $remoteSession --text "Use the read tool to open probe.txt and report its Marker."
uv run pi-agent-client --port 8765 snapshot --session-id $remoteSession
```

预期同一会话的 snapshot 中 `run_outcome=completed`、`graph_status=idle`，`messages` 中有用户/助手内容；如果模型实际调用了工具，还应有 role 为 `tool` 的展示消息。回答应与当前文件里的 `$newMarker` 一致。记录 `checkpoint_id` 和 `message_count`。

在终端 A 用 Ctrl+C 正常停机，等待进程退出，再用**相同的** `$remoteDatabase`、`$workspace`、令牌与端口启动服务端。终端 B 再执行：

```powershell
uv run pi-agent-client --port 8765 snapshot --session-id $remoteSession
```

预期原 session 仍能读取，先前消息和 checkpoint 仍存在；`server_epoch` 可以变化，不能要求跨重启的 revision 连续。若进程不退出、会话消失或消息变少，本项失败。结束后再用 Ctrl+C 关闭服务端；不要把令牌写入验收记录。

## 5. 真实端点的补充自动检查

这 4 项 opt-in live tests 分别覆盖普通回复、流式回复、SQLite 会话消息恢复、摘要/压缩调用路径。它们使用真实模型，但部分断言要求模型按提示输出固定词；失败时先辨别端点协议、模型遵循提示的行为和应用错误。第 0 步的 `.env` 必须已设置 `PI_AGENT_PROVIDER=compatible`：

```powershell
$env:PI_AGENT_LIVE = "1"
try {
    uv run --env-file .env pytest tests/live/test_provider_smoke.py -m live -q --basetemp=.pytest-tmp-m11-live
} finally {
    Remove-Item Env:PI_AGENT_LIVE -ErrorAction SilentlyContinue
}
```

记录通过/失败/跳过数。若仍有 skip，检查 `PI_AGENT_LIVE` 是否在测试进程环境中；不能把 skip 记为通过。此项可补强流式和压缩路径证据，但不是公开 CLI 用户流程的替代。

## 用户实测结果（2026-09-29）

| 用例 | 结果：通过/失败/未执行/未触发 | 退出码、实际现象与脱敏证据位置 |
|---|---|---|
| 0 安装与配置投影 | 部分通过 | compatible CLI/server 与 live tests 均成功调用真实端点；单独的 `uv sync` 与非敏感 `public_dict()` 配置投影输出未留存。 |
| 1 真实模型 read → ToolMessage → 最终回复、telemetry | 工具闭环通过；telemetry 手工脱敏检查未单独核实 | JSONL 退出码 0，真实 read 返回 `M11-PROBE-001`，随后模型完成回复；模型还调用了 search/list。所贴输出没有 telemetry 文件内容或 marker/prompt/API key 查询结果。 |
| 2 同会话恢复与新会话隔离 | 通过 | `test1` 同 session 无工具调用地回忆旧值 `M11-PROBE-001`；session list 含 `test1`；新 session `test2` 表示此前没有对话。命令退出码 0。 |
| 3 工作区越界拒绝 | 通过（修正路径后） | 首次 `out-workspace/outside.txt` 测试只命中不存在路径，不计边界证据。修正为 `../out-workspace/outside.txt` 后，真实 read 返回 `Resolved path is outside the workspace root.`，没有返回 sentinel 内容。 |
| 4 本机远程 create/prompt/snapshot、重启恢复 | 通过 | 客户端创建 session、真实 read 得到 marker，snapshot 显示 completed/idle、4 条消息与 checkpoint。重启后 epoch 从 `1f215de0...` 变为 `6845db69...`，同一 session、checkpoint 和 4 条消息恢复；revision 重置为 0。一次服务未就绪时的 `ClientDisconnectedError` 不作为最终结果。 |
| 5 四项 live tests | 通过 | `uv run --env-file .env pytest tests/live/test_provider_smoke.py -m live -q --basetemp=.pytest-tmp-m11-live`：**4 passed in 8.14s**，无 skip；覆盖普通回复、流式回复、SQLite 恢复历史、摘要/压缩路径。 |

执行环境：Windows PowerShell；OS build、Python 版本、模型 ID 和 API 主机名未在用户结果中记录。测试使用合成 workspace/marker。令牌、API key 和完整凭据不收录于本记录。总体结论：用户验收并授权归档 M11 本地交付范围；独立 Windows/Linux 与真实服务部署验证按既有决定留作 D1–D3，telemetry 实际文件脱敏查询与配置投影输出保留为未单独核实的证据点。

用户视角的核心验收至少需要用例 0–2 与 4 有实际结果，并核对用例 1 的真实工具事件。用例 3 若模型未触发工具应保留“未触发”；用例 5 用来复查框架内部的流式、历史与压缩路径。任何失败都应保留脱敏的命令、退出码和预期/实际差异；不要改写为通过。M6 的 fork/history API、文件写入审批和命令执行审批不在这些公开只读 CLI 步骤内，仍以各自原验收和独立授权路径为准。部署网络、跨机器安全与新环境兼容继续在 [后置验证记录](../history/2026-09-28-m11-deferred-deployment-validation.md) 中跟踪。
