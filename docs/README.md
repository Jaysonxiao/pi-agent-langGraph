# 项目文档索引（M1–M11 与 Web 扩展）

当前状态和交付范围以 [执行计划](../PLAN.md) 为准；项目定位与协作方式见 [AGENTS.md](../AGENTS.md)。本文是导航，不另立一套状态或验收口径。

| 查找内容 | 当前入口 | 用途 |
|---|---|---|
| 阶段状态、范围、验收门槛 | [PLAN](../PLAN.md) | M0–M11 的目标、六项契约与唯一状态表 |
| 学习进度与跨阶段决策 | [LEARNING_LOG](../LEARNING_LOG.md) | 概念迁移和决策摘要 |
| M1–M8 已归档阶段对照 | [阶段总结](stage-summary/M1-M8.md) | 已归档阶段目标、成果、接口、测试、遗留与下一阶段影响 |
| 发现、修订、证据、待核实 | [文档审计](reviews/M1-M8-audit.md) | 本轮检查的方法和逐项纠正 |
| 优先级、依赖、完成标准 | [后续开发清单](follow-ups/M1-M8.md) | 初次归档问题基线与 2026-09-24 纠正后的 M8 剩余复验；M9 未关闭边界见其归档文件 |
| 当前使用和配置 | [README](../README.md) | 可执行命令和 CLI/Provider 限制 |
| Web 已交付范围归档 | [Web 归档](acceptance/web-archive-2026-10-01.md)、[归档后续清单](follow-ups/web.md) | 2026-10-01 用户授权本机范围归档及本地 main 合并；暂不 push，平台与部署验证保留 |
| Web 使用与首轮扩展 | [Web UI](web-ui.md)、[2026-10-01 原计划及证据](design/web-continuation.md) | 启动、流式文本、中断恢复与 checkpoint 分支；保留该轮测试数字 |
| Web 服务管理与 Coding Tools | [原开发计划](design/web-coding-plan.md)、[独立验收记录](acceptance/web-coding-2026-10-01.md) | 用户选择任务 1、2、4、5；代码与本机/live 验证已归档，未执行项转入后续清单 |
| M10 远程接入设计与练习 | [M10 设计](design/M10.md) | 系统链路、Pi 源码映射、M10.1–M10.4 复盘；切片状态与验证命令仍由 PLAN 管理 |
| M11 全链路收束、架构复盘与验收 | [M11 设计](design/M11.md)、[M11 架构](architecture/M11.md)、[M11 归档](acceptance/M11.md)、[真实模型手工执行记录](acceptance/M11-real-provider-manual.md) | 2026-09-29 本地交付范围已验收归档；D1–D3 与两项未单独留存的手工证据仍明确保留 |
| M11 后置验证决定 | [遗留历史记录](history/2026-09-28-m11-deferred-deployment-validation.md) | 新环境 Windows/Linux、真实服务部署验证经用户授权后置；不视为通过 |
| 原始教学过程 | [2026-09-23 整理前快照](history/2026-09-23-m1-m8-review/INDEX.md) | 留存红灯、旧状态与长篇设计记录 |

## 分阶段入口

| 阶段 | 归档与验收 | 主要源码 / 测试 |
|---|---|---|
| M1 Python 工程骨架 | [M1](acceptance/M1.md) | [包入口](../src/pi_agent/__init__.py)、[质量配置](../pyproject.toml)、[CI](../.github/workflows/ci.yml) |
| M2 消息状态与最小图 | [M2](acceptance/M2.md) | [状态](../src/pi_agent/domain/state.py)、[图](../src/pi_agent/graph/builder.py)、[测试](../tests/graph/test_minimal_graph.py) |
| M3 工具调用循环 | [M3](acceptance/M3.md) | [注册表](../src/pi_agent/tools/registry.py)、[路由](../src/pi_agent/graph/routing.py)、[测试](../tests/graph/test_tool_loop.py) |
| M4 安全工具与文件审批 | [M4](acceptance/M4.md) | [路径](../src/pi_agent/security/path_policy.py)、[审批](../src/pi_agent/graph/file_approval.py)、[集成测试](../tests/integration/test_hitl.py) |
| M5 同步事件与 fake CLI | [M5](acceptance/M5.md) | [事件](../src/pi_agent/events/adapter.py)、[CLI](../src/pi_agent/cli/app.py)、[测试](../tests/cli/test_app.py) |
| M6 SQLite 会话 | [M6](acceptance/M6.md) | [会话](../src/pi_agent/sessions/runtime.py)、[fork](../src/pi_agent/sessions/fork.py)、[测试](../tests/integration/test_resume.py) |
| M7 上下文与压缩 | [M7](acceptance/M7.md) | [上下文](../src/pi_agent/context/runtime.py)、[摘要](../src/pi_agent/context/summarizer.py)、[组合测试](../tests/context/test_acceptance.py) |
| M8 Provider 与异步组件 | [M8 初次归档](acceptance/M8.md)、[端到端纠正](acceptance/M8-closure.md) | [HTTP](../src/pi_agent/models/http_client.py)、[Provider CLI](../src/pi_agent/cli/runtime.py)、[live gate](../tests/live/test_provider_smoke.py) |
| M9 扩展、可观测性与评测 | [M9 归档](acceptance/M9.md) | [hooks](../src/pi_agent/extensions/hooks.py)、[lifecycle spans](../src/pi_agent/telemetry/lifecycle.py)、[eval harness](../src/pi_agent/evals/harness.py)、[集成测试](../tests/integration/test_telemetry_lifecycle.py) |
| M10 远程协议与客户端/服务端 | [M10 归档](acceptance/M10.md)，2026-09-28 已交付离线本机范围验收；[设计与复盘](design/M10.md)、[分片计划](../PLAN.md) | protocol/server/client 组合 133 passed；全仓非 live 565 passed |
| M11 全链路验收与架构复盘 | [归档记录](acceptance/M11.md)、[单一练习](design/M11.md)、[架构复盘](architecture/M11.md)、[真实模型执行记录](acceptance/M11-real-provider-manual.md) | 本地范围已验收归档；独立环境与部署验证仍后置 |

术语统一：**归档**表示已交付范围结案；**验收通过**只指该记录中明确执行的范围；**待核实**表示证据不足，不能推断通过；**历史快照**仅作追溯。实现、验收、归档和复验日期分别记，不把一次较晚复验回填到更早里程碑。
