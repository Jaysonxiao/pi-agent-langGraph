"""M8.3 schema export and provider binding contracts."""

from collections.abc import Mapping, Sequence

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict

from pi_agent.models.base import ChatModel
from pi_agent.models.fake import ScriptedChatModel
from pi_agent.models.tool_binding import ToolBindingError, bind_registered_tools, tool_schema
from pi_agent.tools import ToolDefinition


class LookupArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class BindRecordingModel(ScriptedChatModel):
    def __init__(self, responses: Sequence[AIMessage]) -> None:
        super().__init__(responses)
        self.bound_schemas: list[Mapping[str, object]] | None = None

    def bind_tools(self, tools: Sequence[Mapping[str, object]], /) -> ChatModel:
        self.bound_schemas = list(tools)
        return self


def _tool(name: str = "lookup") -> ToolDefinition[LookupArguments]:
    return ToolDefinition(name, "Read one path.", LookupArguments, lambda args: args.path)


def test_tool_schema_exports_function_name_description_and_parameters() -> None:
    schema = tool_schema(_tool())

    assert schema["type"] == "function"
    function = schema["function"]
    assert isinstance(function, dict)
    assert function["name"] == "lookup"
    assert function["description"] == "Read one path."
    parameters = function["parameters"]
    assert isinstance(parameters, dict)
    assert parameters["required"] == ["path"]
    assert "handler" not in str(schema)


def test_binding_preserves_registration_order() -> None:
    model = BindRecordingModel([AIMessage(content="done")])

    bound = bind_registered_tools(model, [_tool("first"), _tool("second")])

    assert bound is model
    schemas = model.bound_schemas
    assert schemas is not None
    names: list[object] = []
    for schema in schemas:
        function = schema["function"]
        assert isinstance(function, Mapping)
        names.append(function["name"])
    assert names == [
        "first",
        "second",
    ]


def test_zero_tools_does_not_require_binding_capability() -> None:
    model = ScriptedChatModel([AIMessage(content="done")])

    assert bind_registered_tools(model, []) is model


def test_binding_failure_is_safe_and_does_not_expose_provider_text() -> None:
    class FailingModel(BindRecordingModel):
        def bind_tools(self, tools: Sequence[Mapping[str, object]], /) -> ChatModel:
            raise RuntimeError("secret-key https://user:pass@example.invalid/v1")

    with pytest.raises(ToolBindingError) as raised:
        bind_registered_tools(FailingModel([AIMessage(content="done")]), [_tool()])

    assert "secret-key" not in str(raised.value)
    assert "user:pass" not in str(raised.value)


def test_model_without_binding_capability_fails_only_for_non_empty_tools() -> None:
    with pytest.raises(ToolBindingError, match="model_does_not_support_tool_binding"):
        bind_registered_tools(ScriptedChatModel([AIMessage(content="done")]), [_tool()])
