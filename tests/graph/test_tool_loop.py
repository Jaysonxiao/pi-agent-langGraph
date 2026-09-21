"""End-to-end contracts for the M3 model/tool loop."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from pi_agent.domain import create_initial_state
from pi_agent.graph import RunContext, build_tool_graph
from pi_agent.models.fake import ScriptedChatModel
from pi_agent.tools import (
    RecordingAddHandler,
    ToolDefinition,
    ToolRegistry,
    create_add_tool,
)


def test_tool_loop_returns_result_to_model_then_finishes() -> None:
    tool_request = AIMessage(
        content="",
        id="assistant-tool-call",
        tool_calls=[{"name": "add", "args": {"left": 2, "right": 3}, "id": "call-1"}],
    )
    final_answer = AIMessage(content="The result is 5.", id="assistant-final")
    model = ScriptedChatModel([tool_request, final_answer])
    handler = RecordingAddHandler()

    result = build_tool_graph().invoke(
        create_initial_state("calculate 2 + 3", message_id="user-1"),
        context=RunContext(
            model=model,
            tools=ToolRegistry([create_add_tool(handler)]),
            max_tool_rounds=2,
        ),
    )

    assert result["messages"] == [
        HumanMessage(content="calculate 2 + 3", id="user-1"),
        tool_request,
        ToolMessage(
            content="5",
            tool_call_id="call-1",
            name="add",
            status="success",
            id="tool-result:call-1",
        ),
        final_answer,
    ]
    assert result["status"] == "completed"
    assert result["error"] is None
    assert result["tool_rounds"] == 1
    assert len(model.calls) == 2
    assert model.calls[1][2] == ToolMessage(
        content="5",
        tool_call_id="call-1",
        name="add",
        status="success",
        id="tool-result:call-1",
    )


def test_tool_graph_still_ends_when_model_requests_no_tool() -> None:
    final_answer = AIMessage(content="No action required.", id="assistant-final")
    model = ScriptedChatModel([final_answer])

    result = build_tool_graph().invoke(
        create_initial_state("hello"),
        context=RunContext(model=model),
    )

    assert result["messages"][-1] == final_answer
    assert result["status"] == "completed"
    assert result["tool_rounds"] == 0
    assert len(model.calls) == 1


def test_tool_graph_returns_correlated_error_when_round_limit_is_zero() -> None:
    tool_request = AIMessage(
        content="",
        id="assistant-tool-call",
        tool_calls=[{"name": "add", "args": {"left": 2, "right": 3}, "id": "call-limit"}],
    )
    model = ScriptedChatModel([tool_request])

    result = build_tool_graph().invoke(
        create_initial_state("calculate 2 + 3"),
        context=RunContext(model=model, max_tool_rounds=0),
    )

    limit_message = result["messages"][-1]
    assert isinstance(limit_message, ToolMessage)
    assert limit_message.tool_call_id == "call-limit"
    assert limit_message.id == "tool-result:call-limit"
    assert limit_message.status == "error"
    assert isinstance(limit_message.content, str)
    assert json.loads(limit_message.content)["code"] == "tool_round_limit"
    assert result["status"] == "failed"
    assert result["error"] == {
        "code": "tool_round_limit",
        "max_rounds": 0,
        "message": "Tool round limit reached (0).",
    }
    assert result["tool_rounds"] == 0
    assert len(model.calls) == 1


def test_tool_node_executes_multiple_calls_in_assistant_order() -> None:
    tool_request = AIMessage(
        content="",
        id="assistant-tool-calls",
        tool_calls=[
            {"name": "add", "args": {"left": 1, "right": 2}, "id": "call-first"},
            {"name": "add", "args": {"left": 10, "right": 20}, "id": "call-second"},
        ],
    )
    model = ScriptedChatModel(
        [tool_request, AIMessage(content="The results are 3 and 30.", id="assistant-final")]
    )
    handler = RecordingAddHandler()

    result = build_tool_graph().invoke(
        create_initial_state("calculate both additions"),
        context=RunContext(
            model=model,
            tools=ToolRegistry([create_add_tool(handler)]),
        ),
    )

    tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert [message.tool_call_id for message in tool_messages] == ["call-first", "call-second"]
    assert [message.content for message in tool_messages] == ["3", "30"]
    assert [(args.left, args.right) for args in handler.calls] == [(1, 2), (10, 20)]
    assert result["status"] == "completed"


class FailingArguments(BaseModel):
    """Arguments for the graph-level execution-error case."""

    value: str


def _fail_tool(_: FailingArguments) -> str:
    raise RuntimeError("graph-level tool failure")


@pytest.mark.parametrize(
    ("registry", "tool_name", "args", "expected_code"),
    [
        (ToolRegistry(), "missing", {}, "unknown_tool"),
        (
            ToolRegistry([create_add_tool(RecordingAddHandler())]),
            "add",
            {"left": "not-an-int", "right": 3},
            "invalid_arguments",
        ),
        (
            ToolRegistry(
                [
                    ToolDefinition(
                        "fail",
                        "Always fail.",
                        FailingArguments,
                        _fail_tool,
                    )
                ]
            ),
            "fail",
            {"value": "x"},
            "tool_execution_error",
        ),
    ],
)
def test_tool_errors_are_returned_to_model_before_stable_completion(
    registry: ToolRegistry,
    tool_name: str,
    args: dict[str, object],
    expected_code: str,
) -> None:
    tool_request = AIMessage(
        content="",
        id="assistant-tool-call",
        tool_calls=[{"name": tool_name, "args": args, "id": "call-error"}],
    )
    final_answer = AIMessage(content="I handled the tool error.", id="assistant-final")
    model = ScriptedChatModel([tool_request, final_answer])

    result = build_tool_graph().invoke(
        create_initial_state("use a tool"),
        context=RunContext(model=model, tools=registry),
    )

    tool_message = result["messages"][2]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.status == "error"
    assert tool_message.tool_call_id == "call-error"
    assert isinstance(tool_message.content, str)
    assert json.loads(tool_message.content)["code"] == expected_code
    assert model.calls[1][2] == tool_message
    assert result["status"] == "completed"
    assert result["error"] is None
