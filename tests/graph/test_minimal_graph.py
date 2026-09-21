"""End-to-end contract tests for the M2 minimal graph."""

from langchain_core.messages import AIMessage, HumanMessage

from pi_agent.domain.state import create_initial_state
from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models.fake import FakeChatModel


def test_minimal_graph_appends_only_the_new_assistant_message() -> None:
    model = FakeChatModel("hello from fake")
    graph = build_minimal_graph()

    result = graph.invoke(
        create_initial_state("hello", message_id="input-1"),
        context=RunContext(model=model),
    )

    assert result["messages"] == [
        HumanMessage(content="hello", id="input-1"),
        AIMessage(content="hello from fake", id="fake-assistant-1"),
    ]
    assert result["status"] == "completed"
    assert result["error"] is None
    assert model.calls == [(HumanMessage(content="hello", id="input-1"),)]


def test_minimal_graph_exposes_model_failure_without_losing_input() -> None:
    model = FakeChatModel(error=RuntimeError("provider unavailable"))
    graph = build_minimal_graph()

    result = graph.invoke(
        create_initial_state("hello", message_id="input-1"),
        context=RunContext(model=model),
    )

    assert result["messages"] == [HumanMessage(content="hello", id="input-1")]
    assert result["status"] == "failed"
    assert result["error"] == {
        "code": "model_error",
        "exception_type": "RuntimeError",
        "message": "provider unavailable",
    }


def test_minimal_graph_emits_one_typed_model_update() -> None:
    model = FakeChatModel("done")
    graph = build_minimal_graph()

    updates = list(
        graph.stream(
            create_initial_state("hello", message_id="input-1"),
            context=RunContext(model=model),
            stream_mode="updates",
        )
    )

    assert updates == [
        {
            "model": {
                "messages": [AIMessage(content="done", id="fake-assistant-1")],
                "status": "completed",
                "error": None,
            }
        }
    ]
