"""Tool registry contracts for the M3 learner exercise."""

import json

from langchain_core.messages import ToolCall
from pydantic import BaseModel, ConfigDict

from pi_agent.tools import RecordingAddHandler, ToolDefinition, ToolRegistry, create_add_tool


def test_execute_call_validates_executes_and_preserves_call_id() -> None:
    handler = RecordingAddHandler()
    registry = ToolRegistry([create_add_tool(handler)])

    result = registry.execute_call(_call("add", {"left": 2, "right": 3}, "call-1"))

    assert result.content == "5"
    assert result.tool_call_id == "call-1"
    assert result.id == "tool-result:call-1"
    assert result.name == "add"
    assert result.status == "success"
    assert [(args.left, args.right) for args in handler.calls] == [(2, 3)]


def test_execute_call_returns_error_for_unknown_tool() -> None:
    registry = ToolRegistry()

    result = registry.execute_call(_call("missing", {}, "call-missing"))

    assert _error_code(result.content) == "unknown_tool"
    assert result.tool_call_id == "call-missing"
    assert result.id == "tool-result:call-missing"
    assert result.name == "missing"
    assert result.status == "error"


def test_execute_call_rejects_invalid_arguments_before_handler() -> None:
    handler = RecordingAddHandler()
    registry = ToolRegistry([create_add_tool(handler)])

    result = registry.execute_call(_call("add", {"left": "not-an-int", "right": 3}, "call-bad"))

    assert _error_code(result.content) == "invalid_arguments"
    assert _error_payload(result.content)["message"] == "Tool arguments failed validation."
    assert "not-an-int" not in str(result.content)
    assert result.tool_call_id == "call-bad"
    assert result.status == "error"
    assert handler.calls == []


class ExplodeArguments(BaseModel):
    """Arguments for a fake handler that always fails."""

    model_config = ConfigDict(extra="forbid")

    value: str


def test_execute_call_converts_handler_exception_to_error_message() -> None:
    def explode(_: ExplodeArguments) -> str:
        raise RuntimeError("controlled explosion")

    registry = ToolRegistry([ToolDefinition("explode", "Always fail.", ExplodeArguments, explode)])

    result = registry.execute_call(_call("explode", {"value": "x"}, "call-error"))

    assert _error_code(result.content) == "tool_execution_error"
    assert "controlled explosion" in str(result.content)
    assert "Traceback" not in str(result.content)
    assert result.tool_call_id == "call-error"
    assert result.status == "error"


class InternalValidationArguments(BaseModel):
    """Model used to prove handler failures are not input-validation failures."""

    count: int


def test_execute_call_treats_handler_validation_error_as_execution_error() -> None:
    def fail_inside_handler(_: ExplodeArguments) -> str:
        InternalValidationArguments.model_validate({"count": "not-an-int"})
        raise AssertionError("unreachable")

    registry = ToolRegistry(
        [
            ToolDefinition(
                "internal_validation",
                "Raise ValidationError inside the handler.",
                ExplodeArguments,
                fail_inside_handler,
            )
        ]
    )

    result = registry.execute_call(
        _call("internal_validation", {"value": "x"}, "call-internal-validation")
    )

    assert _error_code(result.content) == "tool_execution_error"
    assert result.tool_call_id == "call-internal-validation"
    assert result.status == "error"


def test_registry_rejects_duplicate_names() -> None:
    first = create_add_tool(RecordingAddHandler())
    second = create_add_tool(RecordingAddHandler())

    try:
        ToolRegistry([first, second])
    except ValueError as exc:
        assert str(exc) == "Duplicate tool name: add"
    else:
        raise AssertionError("Duplicate tool registration must fail.")


def _call(name: str, args: dict[str, object], call_id: str) -> ToolCall:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _error_code(content: str | list[str | dict[object, object]]) -> object:
    return _error_payload(content).get("code")


def _error_payload(content: str | list[str | dict[object, object]]) -> dict[object, object]:
    assert isinstance(content, str)
    payload = json.loads(content)
    assert isinstance(payload, dict)
    return payload
