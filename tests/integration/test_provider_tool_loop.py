"""M8.3 provider-shaped tool loop using only deterministic local doubles."""

from collections.abc import Mapping, Sequence

from langchain_core.messages import AIMessage

from pi_agent.domain.state import create_initial_state
from pi_agent.graph.builder import build_tool_graph
from pi_agent.graph.context import RunContext
from pi_agent.models.base import ChatModel
from pi_agent.models.fake import ScriptedChatModel
from pi_agent.models.tool_binding import bind_registered_tools
from pi_agent.tools import RecordingAddHandler, ToolRegistry, create_add_tool


class BindableScriptedChatModel(ScriptedChatModel):
    """Small provider double exposing the same capability as a real adapter."""

    def __init__(self, responses: Sequence[AIMessage]) -> None:
        super().__init__(responses)
        self.bound_tools: tuple[Mapping[str, object], ...] = ()

    def bind_tools(self, tools: Sequence[Mapping[str, object]], /) -> ChatModel:
        self.bound_tools = tuple(tools)
        return self


def test_bound_provider_shape_executes_tool_and_preserves_call_id() -> None:
    handler = RecordingAddHandler()
    registry = ToolRegistry([create_add_tool(handler)])
    model = BindableScriptedChatModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "add",
                        "args": {"left": 2, "right": 3},
                        "id": "call-add-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="5", id="assistant-final"),
        ]
    )
    bound = bind_registered_tools(model, registry.tools)

    result = build_tool_graph().invoke(
        create_initial_state("calculate 2 + 3"),
        context=RunContext(model=bound, tools=registry),
    )

    assert result["status"] == "completed"
    assert result["messages"][-1].content == "5"
    assert result["messages"][2].tool_call_id == "call-add-1"
    assert [(call.left, call.right) for call in handler.calls] == [(2, 3)]
