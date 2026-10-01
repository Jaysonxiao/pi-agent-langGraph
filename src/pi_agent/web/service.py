"""Browser-owned runs reuse the graph, workspace policy and run coordinator."""

import asyncio
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import StateSnapshot

from pi_agent.context.default_prompt import workbench_prompt
from pi_agent.context.instructions import PI_INSTRUCTION_FILENAME
from pi_agent.extensions import HookEvent, HookRegistry
from pi_agent.graph.builder import build_async_minimal_graph, build_async_tool_graph
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.models.streaming import TextPreview
from pi_agent.runtime.coding import CodingExecutor, proposal_projection
from pi_agent.runtime.policy import RetryPolicy
from pi_agent.runtime.session import SessionRuntimeConfig, run_session
from pi_agent.server.sessions import RunLease, SessionCoordinator
from pi_agent.sessions import open_async_sqlite_checkpointer
from pi_agent.sessions.config import checkpoint_config, session_config
from pi_agent.tools.approval_store import ApprovalStore
from pi_agent.web.schemas import (
    ALL_TOOL_NAMES,
    CODING_TOOL_NAMES,
    DEFAULT_TOOL_CALL_LIMITS,
    MAX_TOOL_CALLS_PER_TOOL,
    ApprovalAction,
    CheckpointAction,
    CheckpointItem,
    MessageItem,
    MessagePage,
    NewRun,
    RunItem,
    RunStatus,
    SessionEdit,
    SessionItem,
    SessionView,
    SettingsUpdate,
    StepDetail,
    StreamingPreview,
)
from pi_agent.web.store import WebStore
from pi_agent.web.tool_policy import default_executables


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
        file_mutations: bool = True,
        allowed_executables: frozenset[str] | None = None,
        require_approval: bool = True,
    ) -> None:
        self.database = database
        self.default_workspace = workspace.resolve()
        if self.database.resolve().is_relative_to(self.default_workspace):
            raise ValueError("Web database must be outside the workspace.")
        self.model = model
        self.timeout = timeout
        self.request_timeout = request_timeout
        self.attempts = attempts
        self.file_mutations = file_mutations
        self.allowed_executables = (
            default_executables() if allowed_executables is None else allowed_executables
        )
        self.require_approval = require_approval
        self.approvals = ApprovalStore(database)
        self.approvals.initialize()
        self.epoch = uuid4().hex
        self.store = WebStore(database, self.default_workspace)
        self.enabled_tools: tuple[str, ...]
        self.tool_call_limits: dict[str, int]
        saved_settings = self.store.settings()
        if saved_settings is None:
            self.workspace = self.default_workspace
            self.enabled_tools = ALL_TOOL_NAMES
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
                and set(saved_tools).issubset(set(ALL_TOOL_NAMES))
                and valid_limits
            ):
                self.workspace = candidate
                self.enabled_tools = saved_tools
                self.tool_call_limits = saved_tool_limits
            else:
                self.workspace = self.default_workspace
                self.enabled_tools = ALL_TOOL_NAMES
                self.tool_call_limits = DEFAULT_TOOL_CALL_LIMITS.copy()
        self.coordinator = SessionCoordinator()
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.lock = asyncio.Lock()
        self.closing = False
        self.previews: dict[str, StreamingPreview] = {}
        self.preview_revision = 0

    def require_session(self, session_id: str) -> None:
        if self.store.session(session_id) is None:
            raise WebError(404, "找不到这个会话。")

    @property
    def available_tools(self) -> tuple[str, ...]:
        return (
            ("read", "list", "search")
            + (("write", "edit") if self.file_mutations else ())
            + (("propose_command",) if self.allowed_executables else ())
        )

    @property
    def selected_tools(self) -> tuple[str, ...]:
        return tuple(name for name in self.enabled_tools if name in self.available_tools)

    def public_config(self, provider: str, model_name: str) -> dict[str, object]:
        return {
            "workspace": str(self.workspace),
            "provider": provider,
            "model": model_name,
            "server_epoch": self.epoch,
            "capabilities": list(self.selected_tools),
            "available_tools": list(self.available_tools),
            "tool_limits": self.tool_call_limits.copy(),
            "approval_capabilities": [
                name
                for name in self.selected_tools
                if name in CODING_TOOL_NAMES and self.require_approval
            ],
            "require_approval": self.require_approval,
            "allowed_executables": sorted(self.allowed_executables),
        }

    async def update_settings(self, settings: SettingsUpdate) -> dict[str, object]:
        async with self.lock:
            if len(settings.tools) != len(set(settings.tools)):
                raise WebError(422, "工具不能重复选择。")
            if set(settings.tool_limits) != set(DEFAULT_TOOL_CALL_LIMITS):
                raise WebError(422, "请为 read、list、search 分别设置调用上限。")
            if not set(settings.tools).issubset(self.available_tools):
                raise WebError(422, "不能启用服务端未开放的工具。")
            try:
                workspace = Path(settings.workspace).expanduser().resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                raise WebError(422, "工作区路径不存在或无法访问。") from None
            if not workspace.is_dir():
                raise WebError(422, "工作区必须是已存在的本机目录。")
            if self.database.resolve().is_relative_to(workspace):
                raise WebError(422, "工作区不能包含 Web 会话数据库。")
            if workspace != self.workspace and any(not task.done() for task in self.tasks.values()):
                raise WebError(409, "请等待当前运行结束后再修改工作区; 工具选择可提前保存。")
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
        proposals = self.approvals.proposals(session_id)
        awaiting = any(
            item.status == "pending" and item.payload.get("requires_approval", True)
            for item in proposals
        )
        return SessionView(
            session=item,
            server_epoch=self.epoch,
            run=run,
            needs_recovery=bool(state.next or state.interrupts)
            and not self.coordinator.is_busy(session_id)
            and not awaiting,
            history=project_history(state),
            activities=self.store.events(session_id),
            preview=self.previews.get(session_id),
            awaiting_approval=awaiting,
            proposals=[proposal_projection(proposal) for proposal in proposals],
        )

    async def decide(self, session_id: str, proposal_id: str, action: ApprovalAction) -> RunItem:
        async with self.lock:
            self.require_session(session_id)
            proposal = self.approvals.proposal(proposal_id)
            if proposal is None or proposal.session_id != session_id:
                raise WebError(404, "找不到这个提案。")
            try:
                prior = self.store.prior_run(
                    session_id,
                    action.request_id,
                    proposal_id + action.version + action.decision,
                    operation="approval",
                )
            except ValueError as error:
                raise WebError(409, str(error)) from None
            if prior is not None:
                return prior
            self.require_idle_session(session_id)
            state = await self.state(session_id)
            request = next(
                (m for m in reversed(state.values.get("messages", [])) if isinstance(m, AIMessage)),
                None,
            )
            if (
                not (state.next or state.interrupts)
                or request is None
                or request.id != proposal.message_id
            ):
                raise WebError(409, "提案已不属于当前检查点, 请刷新会话。")
            if action.decision == "approve" and (
                ("propose_command" if proposal.kind == "command" else proposal.payload["operation"])
                not in self.selected_tools
                or (proposal.kind == "file" and not self.file_mutations)
                or (
                    proposal.kind == "command"
                    and proposal.payload["args"]["executable"] not in self.allowed_executables
                )
            ):
                raise WebError(409, "当前服务未启用此提案能力, 可拒绝提案后继续。")
            try:
                self.approvals.decide(proposal_id, action.version, action.decision)
            except ValueError as error:
                raise WebError(409, str(error)) from None
        checkpoint = project_history(state).checkpoint_id
        assert checkpoint is not None
        return await self.start(
            session_id,
            CheckpointAction(checkpoint_id=checkpoint, request_id=action.request_id),
            approval_text=proposal_id + action.version + action.decision,
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
            raise WebError(404, "这个节点的 checkpoint 快照暂不可用, 请稍后重试。")

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

    def require_idle_session(self, session_id: str) -> SessionItem:
        self.require_session(session_id)
        item = self.store.session(session_id)
        assert item is not None
        if self.closing or self.coordinator.is_busy(session_id):
            raise WebError(409, "会话正在运行或服务正在关闭。")
        if item.archived:
            raise WebError(409, "请先恢复已归档的会话。")
        return item

    async def checkpoints(self, session_id: str) -> list[CheckpointItem]:
        self.require_session(session_id)
        async with open_async_sqlite_checkpointer(self.database) as saver:
            graph = build_async_tool_graph(saver)
            snapshots = [
                state
                async for state in graph.aget_state_history(session_config(session_id), limit=200)
            ]
        result: list[CheckpointItem] = []
        for state in snapshots:
            if state.next or state.interrupts or state.values.get("status") != "completed":
                continue
            page = project_history(state)
            if page.checkpoint_id is not None and state.created_at is not None:
                preview = next(
                    (item.text for item in reversed(page.messages) if item.role == "user"), ""
                )
                result.append(
                    CheckpointItem(
                        checkpoint_id=page.checkpoint_id,
                        created_at=str(state.created_at),
                        preview=preview[:120],
                    )
                )
            if len(result) == 50:
                break
        return result

    async def fork(self, session_id: str, request: CheckpointAction) -> SessionItem:
        async with self.lock:
            source = self.require_idle_session(session_id)
            try:
                target = self.store.branch_target(
                    session_id, request.request_id, request.checkpoint_id
                )
            except ValueError as error:
                raise WebError(409, str(error)) from None
            async with open_async_sqlite_checkpointer(self.database) as saver:
                graph = build_async_tool_graph(saver)
                state = await graph.aget_state(checkpoint_config(session_id, request.checkpoint_id))
                if state.created_at is None:
                    raise WebError(404, "历史检查点不存在。")
                if state.next or state.interrupts or state.values.get("status") != "completed":
                    raise WebError(409, "只能从已完成的检查点创建分支。")
                if target is None:
                    target = uuid4().hex
                    self.store.reserve_branch(
                        session_id, request.request_id, request.checkpoint_id, target
                    )
                # A durable reservation allows retry after a crash without another branch.
                if (await graph.aget_state(session_config(target))).created_at is None:
                    # The terminal-state writer has the same channels and no runtime-dependent
                    # tool routing. Updating state executes no model or tool node.
                    await build_async_minimal_graph(saver).aupdate_state(
                        session_config(target), state.values, as_node="model"
                    )
            item = self.store.session(target)
            if item is None:
                self.store.create(target, Path(source.workspace))
                self.store.edit(target, SessionEdit(title=f"{source.title[:90]} · 分支"))
            item = self.store.session(target)
            assert item is not None
            return item

    async def start(
        self,
        session_id: str,
        request: NewRun | CheckpointAction,
        *,
        approval_text: str | None = None,
    ) -> RunItem:
        # Reserve and persist before returning 202; browser disconnect never owns this task.
        async with self.lock:
            self.require_session(session_id)
            resume = isinstance(request, CheckpointAction)
            text = request.checkpoint_id if isinstance(request, CheckpointAction) else request.text
            operation: Literal["prompt", "resume", "approval"] = (
                "approval" if approval_text else ("resume" if resume else "prompt")
            )
            if approval_text:
                text = approval_text
            try:
                prior = self.store.prior_run(
                    session_id, request.request_id, text, operation=operation
                )
            except ValueError as error:
                raise WebError(409, str(error)) from None
            if prior is not None:
                return prior
            if self.closing or len(self.tasks) >= 4 or self.coordinator.is_busy(session_id):
                raise WebError(409, "会话正在运行或服务繁忙, 请稍后重试。")
            self.require_idle_session(session_id)
            state = await self.state(session_id)
            if any(
                p.status == "pending" and p.payload.get("requires_approval", True)
                for p in self.approvals.proposals(session_id)
            ):
                raise WebError(409, "请先批准或拒绝待审批提案。")
            if isinstance(request, CheckpointAction):
                current = project_history(state).checkpoint_id
                if not (state.next or state.interrupts) or current != request.checkpoint_id:
                    raise WebError(409, "检查点已变化或无需恢复, 请刷新会话。")
            elif state.next or state.interrupts:
                raise WebError(409, "上一轮留下未完成检查点, 请先继续运行或创建分支。")
            session_workspace = self.store.session_workspace(session_id).resolve()
            if not session_workspace.is_dir():
                raise WebError(409, "此会话关联的工作区已不存在, 请新建会话或重新配置工作区。")
            if self.database.resolve().is_relative_to(session_workspace):
                raise WebError(409, "此会话工作区包含 Web 会话数据库, 请新建会话。")
            run_id = uuid4().hex
            lease = self.coordinator.try_claim_run(session_id, run_id)
            try:
                record = self.store.add_run(
                    session_id, run_id, request.request_id, text, operation=operation
                )
                self.store.event(session_id, run_id, "run_start")
            except BaseException:
                await self.coordinator.cancel_run(session_id, run_id)
                raise
            task = asyncio.create_task(
                self._execute(
                    lease,
                    text,
                    session_workspace,
                    self.selected_tools,
                    self.tool_call_limits.copy(),
                    resume=resume,
                )
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
        tool_call_limits: dict[str, int],
        *,
        resume: bool = False,
    ) -> None:
        hooks = HookRegistry()

        async def observe(event: HookEvent) -> None:
            self.store.event(
                event.thread_id, event.run_id, event.phase, event.tool_name, event.outcome
            )

        hooks.register("web-activity", observe)

        async def preview(update: TextPreview) -> None:
            self.preview_revision += 1
            self.previews[lease.session_id] = StreamingPreview(
                run_id=lease.run_id,
                message_id=update.message_id,
                revision=self.preview_revision,
                text=update.text,
                status=update.status,
                truncated=update.truncated,
            )

        config = SessionRuntimeConfig(
            database=self.database,
            workspace=workspace,
            session_id=lease.session_id,
            enabled_tools=tuple(name for name in enabled_tools if name in DEFAULT_TOOL_CALL_LIMITS),
            tool_call_limits=tool_call_limits,
            instruction_filename=PI_INSTRUCTION_FILENAME,
            prompt_template=workbench_prompt(
                file_mutations=bool({"write", "edit"}.intersection(enabled_tools)),
                command_approval="propose_command" in enabled_tools,
                require_approval=self.require_approval,
            )
            + "\n\n{instructions}",
            hooks=hooks,
            text_observer=preview,
            coding_executor=CodingExecutor(
                self.approvals,
                workspace,
                self.file_mutations,
                self.allowed_executables,
                enabled_tools=frozenset(enabled_tools),
                require_approval=self.require_approval,
            ),
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
                        resume=resume,
                    ),
                )
            pending_state = await self.state(lease.session_id)
            outcome = (
                "awaiting_approval"
                if pending_state.interrupts
                else ("completed" if result["status"] == "completed" else "failed")
            )
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
            self.previews.pop(lease.session_id, None)
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
