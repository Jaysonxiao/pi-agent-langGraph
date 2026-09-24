"""Deterministic fake eval harness: suite/case/judge and a safe JSON artifact."""

from __future__ import annotations

import json
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

ANSWER_CHECK = "answer_contains"
TOOL_CHECK = "tool_names_match"


@dataclass(frozen=True, slots=True)
class EvalCase:
    """One scripted expectation; prompt stays an input and never reaches the artifact."""

    case_id: str
    prompt: str
    expected_response: str
    expected_tool_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvalSuite:
    """Ordered case collection; report order mirrors this order."""

    name: str
    cases: tuple[EvalCase, ...]


@dataclass(frozen=True, slots=True)
class EvalObservation:
    """What one execution produced; judged here, not stored in the artifact."""

    response: str
    tool_names: tuple[str, ...] = ()


class EvalExecutor(Protocol):
    """Injected runner; the harness never builds a provider or workspace itself."""

    def run(self, case: EvalCase) -> Awaitable[EvalObservation]:
        """Execute one case and return its observed response and tool trace."""
        ...


@dataclass(frozen=True, slots=True)
class EvalCaseResult:
    """Per-case verdict; only the case id and boolean checks are retained."""

    case_id: str
    checks: dict[str, bool]

    @property
    def passed(self) -> bool:
        """A case passes only when every check holds."""
        return all(self.checks.values())


@dataclass(frozen=True, slots=True)
class EvalReport:
    """Suite verdict rendered as a byte-stable, payload-free JSON artifact."""

    suite_name: str
    results: tuple[EvalCaseResult, ...]

    @property
    def total(self) -> int:
        """Return how many cases ran."""
        return len(self.results)

    @property
    def passed(self) -> int:
        """Return how many cases passed every check."""
        return sum(1 for result in self.results if result.passed)

    def to_json(self) -> str:
        """Render a repeatable artifact: no timestamps, prompts, replies or secrets."""
        # 固定 key 顺序和分隔符, 同一 suite 重跑必须逐字节一致.
        return json.dumps(
            {
                "suite": self.suite_name,
                "total": self.total,
                "passed": self.passed,
                "results": [
                    {
                        "case_id": result.case_id,
                        "checks": result.checks,
                        "passed": result.passed,
                    }
                    for result in self.results
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def judge_case(case: EvalCase, observation: EvalObservation, /) -> EvalCaseResult:
    """Apply case-insensitive answer matching and ordered tool-name equality."""
    return EvalCaseResult(
        case_id=case.case_id,
        checks={
            # 子串匹配且大小写无关: 回复措辞可变, 但必须包含期望要点.
            ANSWER_CHECK: case.expected_response.casefold() in observation.response.casefold(),
            # 工具轨迹要求顺序完全一致, 乱序视为不通过.
            TOOL_CHECK: tuple(observation.tool_names) == tuple(case.expected_tool_names),
        },
    )


class EvalHarness:
    """Run a suite through one injected executor and judge each observation."""

    def __init__(self, executor: EvalExecutor, /) -> None:
        self._executor = executor

    async def run(self, suite: EvalSuite, /) -> EvalReport:
        """Execute cases sequentially so both execution and report order are stable."""
        results: list[EvalCaseResult] = []
        for case in suite.cases:
            observation = await self._executor.run(case)
            results.append(judge_case(case, observation))
        return EvalReport(suite_name=suite.name, results=tuple(results))
