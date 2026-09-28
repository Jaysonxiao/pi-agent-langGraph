"""Exercise real tools and their hooks independently of the learner projection."""

import asyncio
from dataclasses import replace

from pi_agent.cli.eval_tools import PROBE_TEXT, TOOLS_SUITE, run_tool_case


def test_scenario_observes_real_list_read_results_and_terminal_hooks() -> None:
    trace = asyncio.run(run_tool_case(TOOLS_SUITE.cases[0]))
    assert trace.completed
    assert trace.response == f"Verified probe: {PROBE_TEXT}"
    completed = [event for event in trace.events if event.phase == "after_tool"]
    assert [(event.tool_name, event.outcome) for event in completed] == [
        ("list", "completed"),
        ("read", "completed"),
    ]
    assert [event.tool_call_id for event in completed] == ["list-1", "read-1"]
    assert trace.events[0].phase == "run_start"
    assert trace.events[-1].phase == "run_end"
    assert trace.events[-1].outcome == "completed"
    assert len({event.run_id for event in trace.events}) == 1
    assert PROBE_TEXT not in repr(trace.events)


def test_scenario_never_derives_observation_from_expected_answer_or_tools() -> None:
    case = replace(
        TOOLS_SUITE.cases[0], expected_response="invented answer", expected_tool_names=("write",)
    )
    trace = asyncio.run(run_tool_case(case))
    assert trace.completed
    assert "invented answer" not in trace.response
    assert "write" not in [event.tool_name for event in trace.events]
