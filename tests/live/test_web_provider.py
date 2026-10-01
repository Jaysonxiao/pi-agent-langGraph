"""Opt-in compatible Web evidence using synthetic workspaces and exact approvals."""

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage
from langchain_core.runnables import RunnableConfig

pytest.importorskip("fastapi")

from pi_agent.models.async_adapter import CompatibleAsyncChatModel
from pi_agent.models.config import ModelOptions, resolve_model_config
from pi_agent.models.errors import ModelProviderError
from pi_agent.models.http_client import build_async_provider_client
from pi_agent.web.schemas import ApprovalAction, CheckpointAction, NewRun
from pi_agent.web.service import Workbench

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("PI_AGENT_LIVE") != "1", reason="requires PI_AGENT_LIVE=1 and explicit .env"
    ),
]


class PausedLiveStream:
    """Pause after a real transport chunk so cancellation timing is deterministic."""

    def __init__(
        self, model: CompatibleAsyncChatModel, started: asyncio.Event, release: asyncio.Event
    ) -> None:
        self.model, self.started, self.release = model, started, release

    def bind_tools(self, schemas: Sequence[Mapping[str, Any]]) -> "PausedLiveStream":
        return PausedLiveStream(self.model.bind_tools(schemas), self.started, self.release)

    async def aclose(self) -> None:
        await self.model.aclose()

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        return await self.model.ainvoke(messages, config)

    async def astream(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AsyncIterator[AIMessageChunk]:
        stream = self.model.astream(messages, config)
        try:
            async for chunk in stream:
                yield chunk
                self.started.set()
                await self.release.wait()
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()


class DiagnosticLiveModel:
    def __init__(self, model: CompatibleAsyncChatModel) -> None:
        self.model = model
        self.errors: list[dict[str, str | int | None]] = []

    def bind_tools(self, schemas: Sequence[Mapping[str, Any]]) -> "DiagnosticLiveModel":
        self.model.bind_tools(schemas)
        return self

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        return await self.model.ainvoke(messages, config)

    async def astream(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AsyncIterator[AIMessageChunk]:
        stream = self.model.astream(messages, config)
        try:
            async for chunk in stream:
                yield chunk
        except ModelProviderError as error:
            self.errors.append(
                {"code": error.code, "type": error.exception_type, "status": error.status_code}
            )
            raise
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()

    async def aclose(self) -> None:
        await self.model.aclose()


def live_model() -> CompatibleAsyncChatModel:
    config = resolve_model_config(ModelOptions(provider="compatible"), os.environ)
    return CompatibleAsyncChatModel(build_async_provider_client(config))


async def settle(workbench: Workbench) -> None:
    async with asyncio.timeout(150):
        while workbench.tasks:
            await asyncio.gather(*list(workbench.tasks.values()))


def test_live_web_transport_cancel_reopen_resume_and_branch(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        owned = live_model()
        started, release = asyncio.Event(), asyncio.Event()
        model = PausedLiveStream(owned, started, release)
        database = tmp_path / "web.sqlite"
        workbench = Workbench(database=database, workspace=workspace, model=model)
        sid = workbench.store.create("live-web").session_id
        try:
            run = await workbench.start(
                sid, NewRun(text="Reply with exactly WEB_LIVE_OK", request_id="live-initial")
            )
            await asyncio.wait_for(started.wait(), 45)
            assert (await workbench.cancel(run.run_id)).status == "cancelled"
            await workbench.close()
            release.set()
            workbench = Workbench(database=database, workspace=workspace, model=model)
            workbench.store.recover()
            view = await workbench.view(sid)
            assert view.needs_recovery and view.history.checkpoint_id is not None
            await workbench.start(
                sid,
                CheckpointAction(
                    checkpoint_id=view.history.checkpoint_id, request_id="live-resume"
                ),
            )
            await settle(workbench)
            view = await workbench.view(sid)
            assert view.run is not None and view.run.status == "completed"
            assert [m.role for m in view.history.messages] == ["user", "assistant"]
            assert "WEB_LIVE_OK" in view.history.messages[-1].text
            checkpoints = await workbench.checkpoints(sid)
            branch = await workbench.fork(
                sid,
                CheckpointAction(
                    checkpoint_id=checkpoints[0].checkpoint_id, request_id="live-branch"
                ),
            )
            assert (
                await workbench.view(branch.session_id)
            ).history.messages == view.history.messages
        finally:
            await workbench.close()
            await owned.aclose()

    asyncio.run(scenario())


def test_live_web_exact_file_and_command_proposals(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        owned = live_model()
        diagnostic = DiagnosticLiveModel(owned)
        workbench = Workbench(
            database=tmp_path / "web.sqlite",
            workspace=workspace,
            model=diagnostic,
            file_mutations=True,
            allowed_executables=frozenset({sys.executable}),
        )
        try:
            cases = [
                (
                    "file",
                    'Call write exactly once with path "live.txt" and content "WEB_FILE_OK". '
                    "Do not call other tools. After its result, reply briefly.",
                ),
                (
                    "command",
                    f"Call propose_command exactly once with executable {sys.executable!r}, "
                    'argv ["--version"], timeout_seconds 5. Do not call other tools. '
                    "After its result, reply briefly.",
                ),
            ]
            for kind, prompt in cases:
                sid = workbench.store.create(f"live-{kind}").session_id
                await workbench.start(sid, NewRun(text=prompt, request_id=f"live-{kind}-request"))
                await settle(workbench)
                proposals = workbench.approvals.proposals(sid)
                assert len(proposals) == 1 and proposals[0].status == "pending"
                proposal = proposals[0]
                assert proposal.kind == kind
                if kind == "file":
                    assert proposal.payload["path"] == "live.txt"
                    assert proposal.payload["after_text"] == "WEB_FILE_OK"
                    assert not (workspace / "live.txt").exists()
                else:
                    assert proposal.payload["args"] == {
                        "executable": sys.executable,
                        "argv": ["--version"],
                        "timeout_seconds": 5,
                    }
                await workbench.decide(
                    sid,
                    proposal.proposal_id,
                    ApprovalAction(
                        version=proposal.version,
                        decision="approve",
                        request_id=f"live-{kind}-decision",
                    ),
                )
                await settle(workbench)
                finished = workbench.approvals.proposal(proposal.proposal_id)
                assert finished is not None and finished.status == "completed"
                view = await workbench.view(sid)
                assert view.run is not None and view.run.status == "completed", diagnostic.errors
            assert (workspace / "live.txt").read_text() == "WEB_FILE_OK"
        finally:
            await workbench.close()
            await owned.aclose()

    asyncio.run(scenario())
