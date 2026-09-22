# Pi Agent LangGraph

This repository is a teaching-focused Python reconstruction of Pi Agent's core behavior using LangGraph. Development proceeds one independently testable milestone at a time; see `PLAN.md` for scope and acceptance criteria.

## Development

Requires Python 3.11+ and uv.

```powershell
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

M0–M7 have archived deliveries. The fake run CLI still uses the minimal non-persistent model graph and supports text or JSONL output:

```powershell
uv run pi-agent --provider fake --prompt hello --events text
uv run pi-agent --provider fake --prompt hello --events jsonl
```

M6 adds SQLite-backed session APIs for resume, history, state forks, application metadata, and a metadata listing command:

```powershell
uv run pi-agent session list --database .\checkpoints.sqlite
```

M7 prepares ephemeral model context through `RunContext.context_config`: explicit global/workspace rules, templates, approximate token budgets, a synchronous summary-model adapter, protected recent turns and tool facts. Context errors stop the main model while preserving durable history. Inspect the same preparation pipeline without a model call:

```powershell
uv run pi-agent context inspect --provider fake
uv run pi-agent context inspect --provider fake --workspace . --active-path src/pi_agent --max-tokens 4096
```

Inspection reports source paths, message roles, size estimates and compaction statistics without echoing prompt text. Token estimates are heuristics; real-provider capacity and summary quality remain M8/M9 work.

The run CLI does not yet invoke the coding-tool loop or persist its own fake run. Real provider/tool interruption remains a later runtime concern. See the [M5 archive](docs/acceptance/M5.md), [M6 archive](docs/acceptance/M6.md), [M7 archive](docs/acceptance/M7.md), current [PLAN.md](PLAN.md), and [LEARNING_LOG.md](LEARNING_LOG.md).
