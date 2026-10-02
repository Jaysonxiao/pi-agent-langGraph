"""Approval cards follow their own tool requests in current and paged history."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

pytest.importorskip("fastapi")

from tests.web.test_coding import local_client, make_app
from tests.web.test_workbench import login, session

from pi_agent.graph.builder import build_async_minimal_graph
from pi_agent.sessions import open_async_sqlite_checkpointer
from pi_agent.sessions.config import session_config
from pi_agent.tools.approval_store import ApprovalStore


def completed_file(store: ApprovalStore, sid: str, message: str, call: str, path: str) -> str:
    proposal = store.prepare(
        session=sid,
        workspace="synthetic-workspace",
        message=message,
        call=call,
        kind="file",
        payload={
            "operation": "write",
            "path": path,
            "before_text": None,
            "after_text": "synthetic content",
            "change": {"path": "private-internal-target"},
        },
    )
    store.decide(proposal.proposal_id, proposal.version, "approve")
    store.claim_file(proposal.proposal_id)
    store.finish_result(proposal.proposal_id, "completed", {"status": "applied"})
    return proposal.proposal_id


def seed_history(database: Path, sid: str, messages: list[AnyMessage]) -> None:
    async def seed() -> None:
        async with open_async_sqlite_checkpointer(database) as saver:
            await build_async_minimal_graph(saver).aupdate_state(
                session_config(sid), {"messages": messages, "status": "completed"}, as_node="model"
            )

    asyncio.run(seed())


def cards(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [proposal for message in page["messages"] for proposal in message["proposals"]]


def test_paged_history_keeps_old_cards_with_their_turn_after_restart(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    with local_client(app) as client:
        login(client)
        sid = session(client)
        other = session(client)
        store = app.state.workbench.approvals
        messages: list[AnyMessage] = []
        for index in range(55):
            request_id = f"request-{index}"
            proposal_id = completed_file(store, sid, request_id, "reused-call", f"{index}.txt")
            messages.extend(
                [
                    HumanMessage(content=f"turn {index}", id=f"user-{index}"),
                    AIMessage(
                        content="",
                        id=request_id,
                        tool_calls=[{"name": "write", "args": {}, "id": "reused-call"}],
                    ),
                    ToolMessage(content="applied", tool_call_id="reused-call", id=proposal_id),
                    AIMessage(content=f"done {index}", id=f"reply-{index}"),
                ]
            )
        completed_file(store, other, "request-0", "reused-call", "other-session.txt")
        seed_history(tmp_path / "web.sqlite", sid, messages)
        latest = client.get(f"/api/sessions/{sid}").json()
        assert len(latest["proposals"]) == 50
        assert [item["path"] for item in cards(latest["history"])] == [
            f"{index}.txt" for index in range(45, 55)
        ]
        checkpoint = latest["history"]["checkpoint_id"]

    with local_client(make_app(tmp_path, [])) as client:
        login(client)
        old = client.get(
            f"/api/sessions/{sid}/messages", params={"checkpoint": checkpoint, "before": 40}
        ).json()
        assert [item["path"] for item in cards(old)] == [f"{index}.txt" for index in range(10)]
        for message in old["messages"]:
            if message["proposals"]:
                index = int(message["message_id"].removeprefix("request-"))
                assert message["proposals"][0]["path"] == f"{index}.txt"
                assert message["proposals"][0]["status"] == "completed"
        assert "other-session.txt" not in str(old)
        assert "private-internal-target" not in str(old)


def test_multiple_cards_follow_call_order_and_stay_in_the_request_page(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    with local_client(app) as client:
        login(client)
        sid = session(client)
        store = app.state.workbench.approvals
        # Persistence order need not match the model's tool-call order.
        completed_file(store, sid, "request", "second", "second.txt")
        completed_file(store, sid, "request", "first", "first.txt")
        seed_history(
            tmp_path / "web.sqlite",
            sid,
            [
                HumanMessage(content="write two files", id="user"),
                AIMessage(
                    content="preparing",
                    id="request",
                    tool_calls=[
                        {"name": "write", "args": {}, "id": "first"},
                        {"name": "write", "args": {}, "id": "second"},
                    ],
                ),
                AIMessage(content="final reply", id="reply"),
            ],
        )
        history = client.get(f"/api/sessions/{sid}").json()["history"]
        assert [item["path"] for item in history["messages"][1]["proposals"]] == [
            "first.txt",
            "second.txt",
        ]
        assert not history["messages"][0]["proposals"]
        assert not history["messages"][2]["proposals"]
        first_page = client.get(
            f"/api/sessions/{sid}/messages",
            params={"checkpoint": history["checkpoint_id"], "before": 1},
        ).json()
        assert not cards(first_page)
