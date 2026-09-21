# Repository Guidelines

## Project Structure & Module Organization

`PROJECT_SPEC.md` is the source of truth; `PLAN.md` owns current milestone status and scope, `LEARNING_LOG.md` summarizes learning and decisions by milestone, and `docs/acceptance/Mx.md` records acceptance evidence and open gaps. Treat `docs/history/` as historical snapshots, not current instructions. Keep implementation, acceptance, archive, and revalidation dates distinct. Archiving delivered work must not hide unmet acceptance criteria.

When code is introduced, use a `src` layout:

- `src/pi_agent/`: graph state, nodes, tools, model adapters, persistence, and CLI.
- `tests/`: pytest tests mirroring the source layout (for example, `tests/tools/test_file_read.py`).
- `docs/`: architecture notes and milestone acceptance records.
- `.env.example`: documented configuration names only; never include secrets.

Keep domain logic separate from LangGraph wiring, storage, model providers, and user interfaces.

## Guided Learning Workflow

This is a teaching project. Use a mandatory "whole → part → whole" narrative at both project and milestone scale.

For every milestone, follow this order:

1. **Whole system first:** show the end-to-end Agent flow and module map, marking what is already complete, what this milestone owns, and what remains. Explain why this milestone is needed and where the flow currently breaks without it.
2. **Current vertical slice:** follow one concrete request or failure case through this milestone's upstream input, state transitions, downstream output, and failure path.
3. **Focused source and design:** trace the relevant Pi call chain and design intent, then map it to Python/LangGraph in the causal order "problem → Pi design → rewrite choice → reason → code location → test evidence." Do not open with a directory, type, or API inventory.
4. **One learner exercise:** only after the first three steps, assign one small, testable core task. Explain how its scaffold modules collaborate and what part of the end-to-end flow the TODO connects. Include the target file, signature, inputs, outputs, constraints, tests, expected result, and acceptance condition; never hand off only a function name.
5. **Return to the whole:** after reviewing the attempt, rerun the same scenario through the updated flow, compare before and after, place changed files back in the module map, identify production simplifications and remaining gaps, and show exactly where the next milestone connects.

Do not implement an entire milestone for the learner by default. Provide scaffolding, interfaces, TODOs, examples, tests, and verification commands; let the learner implement a meaningful core section. Review their attempt and guide corrections before completing it. Write the learner's assigned code only when explicitly requested, after repeated blocking, or when it is low-value boilerplate, and state why.

Treat pinned commits and current dependency versions as concise reproducibility checks, not the teaching focus, unless they materially change the design.

## Build, Test, and Development Commands

The project uses a src layout, pyproject.toml, and uv. Keep these configured commands working:

```powershell
uv run pytest -q --basetemp=.pytest-tmp
uv run pytest tests/tools -q --basetemp=.pytest-tmp
uv run mypy src tests
uv run ruff check .
uv run ruff format --check .
uv run pi-agent --provider fake --prompt hello --events jsonl
```

The CLI currently runs a fake minimal graph. See the M5 acceptance record for its limits; do not infer real coding-tool access from the CLI entry point.

## Coding Style & Naming Conventions

Target Python 3.11+ and use four-space indentation, type annotations, and small modules with explicit responsibilities. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes and typed state models; and `UPPER_SNAKE_CASE` for constants. Prefer typed interfaces or protocols at model, tool, and persistence boundaries. Ruff should own formatting and lint rules once configured.

## Testing Guidelines

Use pytest. Name files `test_<subject>.py` and tests `test_<behavior>`. Cover graph routing, tool argument validation, iteration limits, cancellation, persistence recovery, and failure paths. Isolate external models, networks, and storage behind fakes, stubs, or mocks. Every milestone must finish with independently runnable tests and documented expected output.

## Commit & Pull Request Guidelines

Git history is not available in this workspace, so no repository-specific convention can be inferred. Use concise Conventional Commit subjects such as `feat: add minimal tool loop` or `test: cover command timeout`. Keep commits milestone-focused. Pull requests should explain the architectural change, list verification commands and results, link the relevant plan item or issue, and include terminal output or screenshots when CLI behavior changes.

## Security & Agent Safety

Read API keys only from environment variables. Restrict file and command tools to an approved workspace, validate arguments, enforce timeouts, and reject destructive commands by default. Never log secrets or persist credentials in checkpoints.
