"""Physical model usage survives graph boundaries, retries, copies and restarts."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage
from langchain_core.runnables import RunnableConfig

pytest.importorskip("fastapi")

from tests.web.test_approval_history import seed_history
from tests.web.test_coding import CodingModel, begin, decision, local_client, make_app, wait_run
from tests.web.test_workbench import HEADERS, login, session

from pi_agent.models.errors import ModelProviderError
from pi_agent.web.schemas import NewRun
from pi_agent.web.service import Workbench
from pi_agent.web.store import WebStore


class UsedTextModel:
    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        return AIMessage(
            content="answer",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


def usage(client: Any, sid: str | None = None) -> dict[str, Any]:
    response = client.get("/api/usage", params={"session_id": sid} if sid else {})
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_totals_sessions_archives_forks_idempotency_and_restart(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    app.state.workbench.model = UsedTextModel()
    with local_client(app) as client:
        login(client)
        assert usage(client)["overall"]["total_tokens"] == 0
        first = session(client)
        begin(client, first)
        assert usage(client, first)["session"]["total_tokens"] == 15
        begin(client, first)  # Identical request never calls the model again.
        assert usage(client)["overall"]["total_tokens"] == 15
        checkpoint = client.get(f"/api/sessions/{first}/checkpoints").json()[0]["checkpoint_id"]
        branch = client.post(
            f"/api/sessions/{first}/branches",
            headers=HEADERS,
            json={"checkpoint_id": checkpoint, "request_id": "usage-branch"},
        ).json()["session_id"]
        assert usage(client, branch)["session"]["total_tokens"] == 0
        assert usage(client)["overall"]["total_tokens"] == 15
        begin(client, branch)
        second = session(client)
        begin(client, second)
        client.patch(f"/api/sessions/{first}", headers=HEADERS, json={"archived": True})
        totals = usage(client, second)
        assert totals["overall"]["total_tokens"] == 45
        assert totals["overall"]["input_tokens"] == 30
        assert totals["overall"]["output_tokens"] == 15
        assert totals["overall"]["unknown_calls"] == 0
        assert totals["session"]["total_tokens"] == 15
        assert client.get("/api/usage", params={"session_id": "foreign"}).status_code == 404
    with local_client(make_app(tmp_path, [])) as client:
        login(client)
        assert usage(client, second)["overall"] == totals["overall"]
        assert usage(client, branch)["session"]["total_tokens"] == 15


class UsedCodingModel(CodingModel):
    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        response = await super().ainvoke(messages, config)
        response.usage_metadata = {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
        return response


def test_approval_continuation_only_counts_actual_model_calls(tmp_path: Path) -> None:
    calls = [{"name": "write", "args": {"path": "new.txt", "content": "new"}, "id": "write-one"}]
    app = make_app(tmp_path, calls)
    app.state.workbench.model = UsedCodingModel(calls)
    with local_client(app) as client:
        login(client)
        sid = session(client)
        proposal = begin(client, sid)["proposals"][0]
        assert usage(client, sid)["session"]["total_tokens"] == 6
        response = decision(client, sid, proposal)
        wait_run(client, response.json()["run_id"])
        assert usage(client, sid)["session"]["total_tokens"] == 12
        decision(client, sid, proposal)
        assert usage(client)["overall"]["recorded_calls"] == 2


class RetryModel(UsedTextModel):
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        self.calls += 1
        if self.calls == 1:
            raise ModelProviderError("provider_call_failed", "HTTPStatusError", status_code=503)
        return await super().ainvoke(messages, config)


def test_retry_and_missing_usage_are_not_zero_or_lost_attempts(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    app.state.workbench.model = RetryModel()
    with local_client(app) as client:
        login(client)
        sid = session(client)
        begin(client, sid)
        totals = usage(client, sid)["session"]
        assert totals["total_tokens"] == 15
        assert totals["recorded_calls"] == 2 and totals["unknown_calls"] == 1
    with local_client(make_app(tmp_path, [])) as client:
        login(client)
        empty_usage = session(client)
        begin(client, empty_usage)
        totals = usage(client, empty_usage)["session"]
        assert totals["total_tokens"] is None and totals["input_tokens"] is None
        assert totals["unknown_calls"] == 1


class UsageStream:
    def __init__(self, *, reported: bool, pause: bool) -> None:
        self.reported, self.pause = reported, pause
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = 0

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        raise AssertionError("Should use the native stream.")

    async def astream(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AsyncIterator[AIMessageChunk]:
        try:
            yield AIMessageChunk(
                content="a",
                usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
                if self.reported
                else None,
            )
            self.entered.set()
            if self.pause:
                await self.release.wait()
            yield AIMessageChunk(
                content="b",
                usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
                if self.reported
                else None,
            )
        finally:
            self.closed += 1

    async def aclose(self) -> None:
        pass


@pytest.mark.parametrize("cancel", [True, False])
@pytest.mark.parametrize("reported", [True, False])
def test_stream_usage_updates_in_place_and_is_preserved_on_cancel(
    tmp_path: Path, cancel: bool, reported: bool
) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        model = UsageStream(reported=reported, pause=True)
        bench = Workbench(database=tmp_path / "db.sqlite", workspace=workspace, model=model)
        sid = bench.store.create("usage-stream").session_id
        run = await bench.start(sid, NewRun(text="stream", request_id="usage-stream-request"))
        await asyncio.wait_for(model.entered.wait(), 3)
        mid = await bench.usage(sid)
        assert mid.session.pending_calls == 1
        assert mid.session.total_tokens == (12 if reported else None)
        if cancel:
            await bench.cancel(run.run_id)
        else:
            model.release.set()
            await asyncio.gather(*bench.tasks.values())
        final = await bench.usage(sid)
        assert final.revision > mid.revision and final.session.pending_calls == 0
        assert final.session.recorded_calls == 1
        assert final.session.total_tokens == ((12 if cancel else 14) if reported else None)
        assert final.session.unknown_calls == (1 if cancel or not reported else 0)
        assert model.closed == 1
        await bench.close()

    asyncio.run(scenario())


def test_legacy_messages_backfill_once_and_inherited_history_is_not_charged_twice(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database = tmp_path / "web.sqlite"
    store = WebStore(database, workspace)
    store.create("old-original", workspace)
    store.create("old-branch", workspace)
    message = AIMessage(
        content="legacy",
        id="legacy-shared",
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    unknown = AIMessage(content="unknown usage", id="unknown-message")
    for sid in ("old-original", "old-branch"):
        seed_history(database, sid, [message, unknown])
    for _ in range(2):
        with local_client(make_app(tmp_path, [])) as client:
            login(client)
            totals = usage(client, "old-original")
            assert totals["overall"]["total_tokens"] == 15
            assert totals["overall"]["recorded_calls"] == 2
            assert totals["session"]["total_tokens"] == 15
            assert usage(client, "old-branch")["session"]["recorded_calls"] == 0


def test_orphaned_attempt_after_crash_becomes_unknown_instead_of_pending(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    with local_client(app) as client:
        login(client)
        sid = session(client)
        usage(client, sid)
        app.state.workbench.usage_store.begin(sid, "crashed-run")
        assert usage(client, sid)["session"]["pending_calls"] == 1
    with local_client(make_app(tmp_path, [])) as client:
        login(client)
        totals = usage(client, sid)["session"]
        assert totals["pending_calls"] == 0 and totals["unknown_calls"] == 1
        assert totals["total_tokens"] is None
