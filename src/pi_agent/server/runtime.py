"""Server-facing facade over the shared session runtime."""

from langgraph.types import StateSnapshot

from pi_agent.domain.state import AgentState
from pi_agent.graph.builder import build_async_tool_graph
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.protocol.messages import SessionSnapshot
from pi_agent.runtime.session import SessionRuntimeConfig, run_session
from pi_agent.server.snapshots import project_session_snapshot
from pi_agent.sessions import open_async_sqlite_checkpointer
from pi_agent.sessions.config import session_config


class ServerSessionRuntime:
    """Bind server-owned model, storage and workspace to session operations."""

    def __init__(self, *, model: AsyncChatModel, server_epoch: str) -> None:
        self._model = model
        self._server_epoch = server_epoch

    async def prompt(
        self, config: SessionRuntimeConfig, *, content: str, message_id: str
    ) -> AgentState:
        return await run_session(
            config,
            model=self._model,
            content=content,
            message_id=message_id,
        )

    async def snapshot(
        self,
        config: SessionRuntimeConfig,
        *,
        revision: int,
        run_phase: str = "idle",
        run_outcome: str | None = None,
        active_run_id: str | None = None,
    ) -> SessionSnapshot:
        async with open_async_sqlite_checkpointer(config.database) as saver:
            graph = build_async_tool_graph(saver)
            state: StateSnapshot = await graph.aget_state(session_config(config.session_id))
        return project_session_snapshot(
            state,
            session_id=config.session_id,
            server_epoch=self._server_epoch,
            revision=revision,
            run_phase=run_phase,
            run_outcome=run_outcome,
            active_run_id=active_run_id,
        )
