# Pi Agent LangGraph

This repository is a teaching-focused Python reconstruction of Pi Agent's core behavior using LangGraph. Development proceeds one independently testable milestone at a time; see [PLAN.md](PLAN.md) for scope and acceptance criteria. For the M1–M8 document map, stage summaries, audit and prioritized follow-ups, see [docs/README.md](docs/README.md).

## Development

Requires Python 3.11+ and uv.

```powershell
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

M0–M8 have archived deliveries. The default fake run CLI remains deterministic and non-persistent:

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

Inspection reports source paths, message roles, size estimates and compaction statistics without echoing prompt text. Token estimates are heuristics; real-provider capacity and summary quality remain open for later evaluation.

## M8 compatible-provider CLI

The explicit `compatible` mode now runs the persistent async model/tool graph. It
exposes workspace-confined `read`, `list`, and `search`, bounded provider retries,
and JSONL/text graph events. It never enables network access merely because a
`.env` file exists. See [M8 closure](docs/acceptance/M8-closure.md) for validation
evidence and remaining boundaries.

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

Use a dedicated workspace containing only material you are comfortable sending
to the configured model. `--database` must point to a file in an existing
directory; `--session-id` chooses the durable conversation. `--trace-file` is
optional and writes content-free event/usage metadata inside the workspace.

```powershell
uv run --env-file .env pi-agent --provider compatible --workspace .\safe-workspace --database .\sessions.sqlite --session-id demo --prompt "Read probe.txt and summarize it" --events jsonl --trace-file trace.jsonl
uv run pi-agent session list --database .\sessions.sqlite
```

Sensitive file names such as `.env`, `.git`, private keys, and runtime caches are
excluded from provider-visible read/search tools. This is not an OS sandbox:
place untrusted tasks in an isolated workspace. By default no command can run.
To let the model *propose* an allowlisted command, pass `--allow-executable`;
this still does not execute it. Review the exact argv with `pi-agent command
show ID --database DB`, then use the interactive `command approve` or `command
reject` subcommand. A consumed proposal is never automatically replayed after
a crash. The provider CLI emits completed messages and graph events; token-by-token
terminal rendering is not yet a guarantee.
