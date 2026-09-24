"""Red tests for the learner-owned M9.4 deterministic fake eval harness."""

import asyncio
import json

from pi_agent.evals.harness import EvalCase, EvalHarness, EvalObservation, EvalSuite


class FakeExecutor:
    def __init__(self, observations: dict[str, EvalObservation]) -> None:
        self._observations = observations
        self.calls: list[str] = []

    async def run(self, case: EvalCase) -> EvalObservation:
        self.calls.append(case.case_id)
        return self._observations[case.case_id]


def _suite() -> EvalSuite:
    return EvalSuite(
        name="smoke",
        cases=(
            EvalCase(
                case_id="read-probe",
                prompt="summarize synthetic probe contents",
                expected_response="summary",
                expected_tool_names=("read",),
            ),
            EvalCase(
                case_id="no-tool",
                prompt="answer without tools",
                expected_response="ready",
                expected_tool_names=(),
            ),
        ),
    )


def test_fake_suite_runs_in_order_and_writes_repeatable_safe_artifact() -> None:
    suite = _suite()
    observations = {
        "read-probe": EvalObservation(response="A concise summary is ready.", tool_names=("read",)),
        "no-tool": EvalObservation(response="Ready.", tool_names=()),
    }
    executor = FakeExecutor(observations)
    harness = EvalHarness(executor)

    first = asyncio.run(harness.run(suite))
    second = asyncio.run(harness.run(suite))

    assert executor.calls == ["read-probe", "no-tool", "read-probe", "no-tool"]
    assert first.passed == 2
    assert first.total == 2
    assert first.to_json() == second.to_json()
    artifact = json.loads(first.to_json())
    assert [result["case_id"] for result in artifact["results"]] == [
        "read-probe",
        "no-tool",
    ]
    serialized = first.to_json()
    assert "synthetic probe contents" not in serialized
    assert "A concise summary is ready" not in serialized


def test_judge_reports_answer_and_ordered_tool_mismatches() -> None:
    suite = EvalSuite(
        name="negative",
        cases=(
            EvalCase(
                case_id="expected-read",
                prompt="private prompt",
                expected_response="summary",
                expected_tool_names=("read", "search"),
            ),
        ),
    )
    executor = FakeExecutor(
        {
            "expected-read": EvalObservation(
                response="no matching answer", tool_names=("search", "read")
            )
        }
    )

    report = asyncio.run(EvalHarness(executor).run(suite))

    assert report.passed == 0
    assert report.total == 1
    result = report.results[0]
    assert result.case_id == "expected-read"
    assert result.checks == {"answer_contains": False, "tool_names_match": False}
    assert result.passed is False
    assert "private prompt" not in report.to_json()
