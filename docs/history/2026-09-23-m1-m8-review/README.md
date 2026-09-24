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

## M8 compatible-provider verification

M8 provides a programmatic compatible-provider boundary for complete replies,
SSE streaming, SQLite session resume, and async summary/compaction. The public
`pi-agent` command remains the deterministic fake teaching CLI; it does not
silently read provider credentials or switch to the network path.

Create a local, gitignored `.env` from `.env.example` and set these values:

```dotenv
PI_AGENT_PROVIDER=compatible
PI_AGENT_MODEL=your-model-id
PI_AGENT_BASE_URL=https://provider.example/v1
PI_AGENT_API_KEY=your-secret
```

`PI_AGENT_BASE_URL` is the API root; the client appends `/chat/completions`.
Never commit `.env`, and do not include `/chat/completions` in the base URL.
Configuration is loaded only when explicitly requested:

```powershell
uv run --env-file .env python -c "import os; from pi_agent.models.config import ModelOptions, resolve_model_config; print(resolve_model_config(ModelOptions(), dict(os.environ)).public_dict())"
```

The default suite remains offline. Live smoke is opt-in and uses only synthetic
prompts plus temporary workspaces/databases:

```powershell
$env:PI_AGENT_LIVE="1"
uv run --env-file .env pytest tests/live/test_provider_smoke.py -m live -q --basetemp=.pytest-tmp-m8-live
Remove-Item Env:PI_AGENT_LIVE
```

The smoke module covers a normal reply, native streaming, SQLite reopen/resume,
and the summary/compaction path. Passing it proves the configured endpoint's
basic protocol integration, not summary quality or compatibility with every
OpenAI-compatible provider.

The run CLI does not yet invoke the coding-tool loop or persist its own fake run. Real provider/tool interruption remains a later runtime concern. See the [M5 archive](docs/acceptance/M5.md), [M6 archive](docs/acceptance/M6.md), [M7 archive](docs/acceptance/M7.md), current [PLAN.md](PLAN.md), and [LEARNING_LOG.md](LEARNING_LOG.md).
