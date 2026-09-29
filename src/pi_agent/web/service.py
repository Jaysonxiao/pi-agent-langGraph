"""Browser-owned runs reuse the graph, workspace policy and run coordinator."""

import asyncio
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import StateSnapshot

from pi_agent.context.default_prompt import PI_WORKBENCH_SYSTEM_PROMPT
from pi_agent.context.instructions import PI_INSTRUCTION_FILENAME
from pi_agent.extensions import HookEvent, HookRegistry
from pi_agent.graph.builder import build_async_tool_graph
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.runtime.policy import RetryPolicy
from pi_agent.runtime.session import SessionRuntimeConfig, run_session
from pi_agent.server.sessions import RunLease, SessionCoordinator
from pi_agent.sessions import open_async_sqlite_checkpointer
from pi_agent.sessions.config import checkpoint_config, session_config
from pi_agent.web.schemas import (
    DEFAULT_TOOL_CALL_LIMITS,
    MAX_TOOL_CALLS_PER_TOOL,
    MessageItem,
    MessagePage,
    NewRun,
    RunItem,
    RunStatus,
    SessionView,
    SettingsUpdate,
    StepDetail,
)
from pi_agent.web.store import WebStore


class WebError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message


class Workbench:
    def __init__(
        self,
        *,
        database: Path,
        workspace: Path,
        model: AsyncChatModel,
        timeout: float = 120,
        request_timeout: float = 30,
        attempts: int = 3,
    ) -> None:
        self.database = database
        self.default_workspace = workspace.resolve()
        if self.database.resolve().is_relative_to(self.default_workspace):
            raise ValueError("Web database must be outside the workspace.")
        self.model = model
        self.timeout = timeout
        self.request_timeout = request_timeout
        self.attempts = attempts
        self.epoch = uuid4().hex
        self.store = WebStore(database, self.default_workspace)
        self.enabled_tools: tuple[str, ...]
        self.tool_call_limits: dict[str, int]
        saved_settings = self.store.settings()
        if saved_settings is None:
            self.workspace = self.default_workspace
            self.enabled_tools = ("read", "list", "search")
            self.tool_call_limits = DEFAULT_TOOL_CALL_LIMITS.copy()
            self.store.save_settings(str(self.workspace), self.enabled_tools, self.tool_call_limits)
        else:
            saved_workspace, saved_tools, saved_tool_limits = saved_settings
            candidate = Path(saved_workspace).resolve()
            valid_limits = set(saved_tool_limits) == set(DEFAULT_TOOL_CALL_LIMITS) and all(
                isinstance(limit, int) and 0 <= limit <= MAX_TOOL_CALLS_PER_TOOL
                for limit in saved_tool_limits.values()
            )
            if (
                candidate.is_dir()
                and not self.database.resolve().is_relative_to(candidate)
                and set(saved_tools).issubset(set(DEFAULT_TOOL_CALL_LIMITS))
                and valid_limits
            ):
                self.workspace = candidate
                self.enabled_tools = saved_tools
                self.tool_call_limits = saved_tool_limits
            else:
                self.workspace = self.default_workspace
                self.enabled_tools = ("read", "list", "search")
                self.tool_call_limits = DEFAULT_TOOL_CALL_LIMITS.copy()
        self.coordinator = SessionCoordinator()
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.lock = asyncio.Lock()
        self.closing = False

    def require_session(self, session_id: str) -> None:
        if self.store.session(session_id) is None:
            raise WebError(404, "找不到这个会话。")

    def public_config(self, provider: str, model_name: str) -> dict[str, object]:
        return {
            "workspace": str(self.workspace),
            "provider": provider,
            "model": model_name,
            "server_epoch": self.epoch,
            "capabilities": list(self.enabled_tools),
            "tool_limits": self.tool_call_limits.copy(),
        }

    async def update_settings(self, settings: SettingsUpdate) -> dict[str, object]:
        async with self.lock:
            if any(not task.done() for task in self.tasks.values()):
                raise WebError(409, "请等待当前运行结束后再修改工作区或工具。")
            if len(settings.tools) != len(set(settings.tools)):
                raise WebError(422, "工具不能重复选择。")
            if set(settings.tool_limits) != set(DEFAULT_TOOL_CALL_LIMITS):
                raise WebError(422, "请为 read、list、search 分别设置调用上限。")
            try:
                workspace = Path(settings.workspace).expanduser().resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                raise WebError(422, "工作区路径不存在或无法访问。") from None
            if not workspace.is_dir():
                raise WebError(422, "工作区必须是已存在的本机目录。")
            if self.database.resolve().is_relative_to(workspace):
                raise WebError(422, "工作区不能包含 Web 会话数据库。")
            self.workspace = workspace
            self.enabled_tools = tuple(settings.tools)
            self.tool_call_limits = {
                "read": settings.tool_limits["read"],
                "list": settings.tool_limits["list"],
                "search": settings.tool_limits["search"],
            }
            self.store.save_settings(str(workspace), self.enabled_tools, self.tool_call_limits)
        return self.public_config("", "")

    async def state(self, session_id: str, checkpoint: str | None = None) -> StateSnapshot:
        self.require_session(session_id)
        config = (
            checkpoint_config(session_id, checkpoint) if checkpoint else session_config(session_id)
        )
        async with open_async_sqlite_checkpointer(self.database) as saver:
            return await build_async_tool_graph(saver).aget_state(config)

    async def view(self, session_id: str) -> SessionView:
        state = await self.state(session_id)
        item = self.store.session(session_id)
        assert item is not None
        run = self.store.latest_run(session_id)
        return SessionView(
            session=item,
            server_epoch=self.epoch,
            run=run,
            needs_recovery=bool(state.next) and not self.coordinator.is_busy(session_id),
            history=project_history(state),
            activities=self.store.events(session_id),
        )

    async def activity_detail(self, session_id: str, event_id: int) -> StepDetail:
        activity = self.store.event_detail(session_id, event_id)
        if activity is None:
            raise WebError(404, "找不到这个执行节点。")
        node = (
            "model"
            if activity.phase == "after_model"
            else ("tools" if activity.phase == "after_tool" else None)
        )
        if node is None:
            raise WebError(409, "此节点尚无可展示的执行结果。")
        run = self.store.run(activity.run_id)
        if run is None:
            raise WebError(404, "找不到这次运行。")
        started_at = datetime.fromisoformat(run.created_at)
        phase_events = [
            item
            for item in self.store.events(session_id)
            if item.run_id == activity.run_id and item.phase == activity.phase
        ]
        try:
            node_index = next(
                index for index, item in enumerate(phase_events) if item.event_id == event_id
            )
        except (StopIteration, IndexError):
            raise WebError(404, "这个节点的执行记录不可用。") from None

        after: StateSnapshot | None = None
        chronological: list[StateSnapshot] = []
        for attempt in range(10):
            async with open_async_sqlite_checkpointer(self.database) as saver:
                graph = build_async_tool_graph(saver)
                history = [
                    snapshot
                    async for snapshot in graph.aget_state_history(session_config(session_id))
                ]
            chronological = sorted(history, key=lambda item: _snapshot_time(item) or started_at)
            node_snapshots = [
                snapshot
                for snapshot in chronological
                if _pending_node_result(snapshot, node) is not None
                and (_snapshot_time(snapshot) or started_at) >= started_at
            ]
            if node_index < len(node_snapshots):
                after = node_snapshots[node_index]
                break
            current_run = self.store.run(activity.run_id)
            if current_run is None or current_run.status != "running" or attempt == 9:
                break
            await asyncio.sleep(0.05)
        if after is None:
            raise WebError(404, "这个节点的 checkpoint 快照暂不可用，请稍后重试。")  # noqa: RUF001

        before_values = after.values if isinstance(after.values, Mapping) else {}
        after_values = before_values
        update = _pending_node_result(after, node) or {}
        delta = update.get("messages", []) if isinstance(update, Mapping) else []
        output = _display_messages(delta if isinstance(delta, (list, tuple)) else [])
        input_messages = before_values.get("messages", [])
        title = "模型响应" if node == "model" else f"工具 {activity.tool_name}"
        return StepDetail(
            event_id=event_id,
            title=title,
            node=node,
            input=_display_messages(
                input_messages if isinstance(input_messages, (list, tuple)) else []
            ),
            output=output,
            snapshot_before=_display_snapshot(before_values),
            snapshot_after=_display_snapshot(after_values, update),
        )

    async def start(self, session_id: str, request: NewRun) -> RunItem:
        # Reserve and persist before returning 202; browser disconnect never owns this task.
        async with self.lock:
            self.require_session(session_id)
            try:
                prior = self.store.prior_run(session_id, request.request_id, request.text)
            except ValueError as error:
                raise WebError(409, str(error)) from None
            if prior is not None:
                return prior
            if self.closing or len(self.tasks) >= 4 or self.coordinator.is_busy(session_id):
                raise WebError(409, "会话正在运行或服务繁忙, 请稍后重试。")
            item = self.store.session(session_id)
            if item is not None and item.archived:
                raise WebError(409, "请先恢复已归档的会话。")
            if (await self.state(session_id)).next:
                raise WebError(409, "上一轮留下未完成检查点, 请新建会话继续。")
            session_workspace = self.store.session_workspace(session_id).resolve()
            if not session_workspace.is_dir():
                raise WebError(409, "此会话关联的工作区已不存在，请新建会话或重新配置工作区。")  # noqa: RUF001
            if self.database.resolve().is_relative_to(session_workspace):
                raise WebError(409, "此会话工作区包含 Web 会话数据库，请新建会话。")  # noqa: RUF001
            run_id = uuid4().hex
            lease = self.coordinator.try_claim_run(session_id, run_id)
            try:
                record = self.store.add_run(session_id, run_id, request.request_id, request.text)
                self.store.event(session_id, run_id, "run_start")
            except BaseException:
                await self.coordinator.cancel_run(session_id, run_id)
                raise
            task = asyncio.create_task(
                self._execute(lease, request.text, session_workspace, self.enabled_tools)
            )
            self.tasks[run_id] = task
            task.add_done_callback(lambda _task: self.tasks.pop(run_id, None))
            return record

    async def _execute(
        self,
        lease: RunLease,
        text: str,
        workspace: Path,
        enabled_tools: tuple[str, ...],
    ) -> None:
        hooks = HookRegistry()

        async def observe(event: HookEvent) -> None:
            self.store.event(
                event.thread_id, event.run_id, event.phase, event.tool_name, event.outcome
            )

        hooks.register("web-activity", observe)
        config = SessionRuntimeConfig(
            database=self.database,
            workspace=workspace,
            session_id=lease.session_id,
            enabled_tools=enabled_tools,
            tool_call_limits=self.tool_call_limits.copy(),
            instruction_filename=PI_INSTRUCTION_FILENAME,
            prompt_template=f"{PI_WORKBENCH_SYSTEM_PROMPT}\n\n{{instructions}}",
            hooks=hooks,
            run_id=lease.run_id,
            cancellation_token=lease.cancellation_token,
            request_timeout_seconds=self.request_timeout,
            retry_policy=RetryPolicy(max_attempts=self.attempts, run_timeout_seconds=self.timeout),
        )
        outcome: RunStatus = "failed"
        error: str | None = None
        try:
            lease.cancellation_token.raise_if_cancelled()
            async with asyncio.timeout(self.timeout):
                result = await self.coordinator.run(
                    lease,
                    lambda _token: run_session(
                        config,
                        model=self.model,
                        content=text,
                        message_id=uuid4().hex,
                    ),
                )
            outcome = "completed" if result["status"] == "completed" else "failed"
            if outcome == "failed":
                error = "本轮未完成, 请检查模型配置或查看工具结果。"
        except asyncio.CancelledError:
            outcome = "cancelled"
        except TimeoutError:
            error = "本轮运行超时, 已停止。"
        except Exception:
            error = "运行失败, 请检查模型连接或服务日志中的错误类型。"
        finally:
            if lease.task is None:
                await self.coordinator.cancel_run(lease.session_id, lease.run_id)
            self.store.finish(lease.run_id, outcome, error)
            self.store.event(lease.session_id, lease.run_id, "run_end", outcome=outcome)

    async def cancel(self, run_id: str) -> RunItem:
        record = self.store.run(run_id)
        if record is None:
            raise WebError(404, "找不到这个运行。")
        if record.status == "running":
            result = await self.coordinator.cancel_run(record.session_id, run_id)
            if result == "needs_recovery":
                raise WebError(409, "停止请求已发送, 任务仍在清理。请稍后检查状态。")
            task = self.tasks.get(run_id)
            if task is not None:
                await asyncio.wait({task}, timeout=3)
        return self.store.run(run_id) or record

    async def close(self) -> None:
        self.closing = True
        for run_id in tuple(self.tasks):
            await self.cancel(run_id)
        if self.tasks:
            _, pending = await asyncio.wait(set(self.tasks.values()), timeout=5)
            if pending:
                raise TimeoutError("Web runs did not finish cleanup.")


def project_history(state: StateSnapshot, before: int | None = None) -> MessagePage:
    values = state.values if isinstance(state.values, Mapping) else {}
    raw = values.get("messages", [])
    messages = raw if isinstance(raw, (list, tuple)) else []
    end = min(before if before is not None else len(messages), len(messages))
    start = max(0, end - 40)
    names: dict[str, str] = {}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                call_id = call.get("id")
                if call_id:
                    names[call_id] = call["name"]
    items: list[MessageItem] = []
    for index in range(start, end):
        message = messages[index]
        if not isinstance(message, (HumanMessage, AIMessage, ToolMessage)):
            continue
        if not isinstance(message.content, str):
            continue
        content = message.content.encode("utf-8", errors="replace")
        items.append(
            MessageItem(
                message_id=message.id or f"message-{index}",
                role="user"
                if isinstance(message, HumanMessage)
                else ("tool" if isinstance(message, ToolMessage) else "assistant"),
                text=content[:16384].decode("utf-8", errors="ignore"),
                tool_name=names.get(message.tool_call_id)
                if isinstance(message, ToolMessage)
                else None,
                truncated=len(content) > 16384,
            )
        )
    checkpoint = state.config.get("configurable", {}).get("checkpoint_id")
    return MessagePage(
        messages=items,
        checkpoint_id=checkpoint if isinstance(checkpoint, str) else None,
        next_before=start if start else None,
    )


def _pending_node_result(snapshot: StateSnapshot, node: str) -> Mapping[str, object] | None:
    for task in snapshot.tasks:
        if task.name == node and isinstance(task.result, Mapping):
            return task.result
    return None


def _snapshot_time(snapshot: StateSnapshot) -> datetime | None:
    created_at = snapshot.created_at
    if isinstance(created_at, datetime):
        return created_at
    if isinstance(created_at, str):
        try:
            return datetime.fromisoformat(created_at)
        except ValueError:
            return None
    return None


def _display_messages(messages: object, *, item_limit: int = 12) -> list[dict[str, object]]:
    if not isinstance(messages, (list, tuple)):
        return []
    displayed: list[dict[str, object]] = []
    for message in messages[-item_limit:]:
        if isinstance(message, SystemMessage):
            continue
        if isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage):
            role = "assistant"
        elif isinstance(message, ToolMessage):
            role = "tool"
        else:
            continue
        content = message.content if isinstance(message.content, str) else ""
        item: dict[str, object] = {"role": role, "text": content[:8192]}
        if isinstance(message, ToolMessage):
            item["tool_name"] = message.name or "tool"
        if isinstance(message, AIMessage) and message.tool_calls:
            item["tool_calls"] = [
                {
                    "name": call.get("name"),
                    "args": _display_tool_args(call.get("name"), call.get("args")),
                }
                for call in message.tool_calls[:8]
            ]
        displayed.append(item)
    return displayed


def _display_tool_args(name: object, args: object) -> dict[str, str | int | bool]:
    allowed = {
        "read": {"path", "offset", "limit"},
        "list": {"path"},
        "search": {"path", "query", "case_sensitive"},
    }
    if not isinstance(name, str) or not isinstance(args, Mapping):
        return {}
    projected: dict[str, str | int | bool] = {}
    for key in allowed.get(name, set()):
        value = args.get(key)
        if isinstance(value, bool | int):
            projected[key] = value
        elif isinstance(value, str):
            projected[key] = value[:512]
    return projected


def _display_snapshot(
    values: Mapping[str, object], updates: Mapping[str, object] | None = None
) -> dict[str, object]:
    state = {**values, **(updates or {})}
    before_messages = values.get("messages", [])
    extra_messages = updates.get("messages", []) if updates is not None else []
    messages = [
        *(before_messages if isinstance(before_messages, (list, tuple)) else []),
        *(extra_messages if isinstance(extra_messages, (list, tuple)) else []),
    ]
    snapshot: dict[str, object] = {
        "status": state.get("status"),
        "tool_rounds": state.get("tool_rounds"),
        "messages": _display_messages(messages, item_limit=6),
    }
    error = state.get("error")
    if isinstance(error, Mapping):
        snapshot["error"] = {
            key: error[key]
            for key in ("code", "exception_type", "max_rounds")
            if isinstance(error.get(key), str | int)
        }
    return snapshot
