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

M0–M5 have archived deliveries; M6 has not started. The fake CLI runs the minimal model graph and supports text or JSONL output:

```powershell
uv run pi-agent --provider fake --prompt hello --events text
uv run pi-agent --provider fake --prompt hello --events jsonl
```

The CLI does not yet invoke the coding-tool loop. M5's synchronous fake-provider streaming scope is accepted; real provider/tool interruption remains a later runtime concern. See the [M5 archive](docs/acceptance/M5.md), current [PLAN.md](PLAN.md), and [LEARNING_LOG.md](LEARNING_LOG.md).
