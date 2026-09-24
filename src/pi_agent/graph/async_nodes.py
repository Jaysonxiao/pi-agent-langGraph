"""Native async graph nodes for M8.5."""

import asyncio
from time import monotonic

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.config import get_config
from langgraph.runtime import Runtime

from pi_agent.context.async_runtime import prepare_model_messages_async
from pi_agent.domain.state import AgentState, AgentStateUpdate
from pi_agent.extensions.hooks import HookOutcome
from pi_agent.graph.async_context import AsyncRunContext
from pi_agent.graph.nodes import _latest_tool_request
from pi_agent.runtime.async_retry import arun_with_retry
from pi_agent.runtime.runner import run_cancellable
from pi_agent.tools.registry import _require_call_id, create_error_tool_message


async def async_model_node(
    state: AgentState,
    runtime: Runtime[AsyncRunContext],
) -> AgentStateUpdate:
    """Prepare context, await the model, and return one state delta."""
    try:
        # 派生模型输入, 不改 checkpoint 里的原始 messages.
        model_messages = await prepare_model_messages_async(
            state["messages"],
            runtime.context.context_config,
            get_config(),
        )
    except Exception as exc:
        # 上下文装配失败时模型尚未开始, 不伪造 before_model / after_model.
        return {
            "status": "failed",
            "error": {
                "code": "context_error",
                "exception_type": type(exc).__name__,
                "message": "Context preparation failed; original messages are preserved.",
            },
        }

    # 只在真正发起模型请求前派发; 事件不含 prompt / messages / 回复.
    await runtime.context.dispatch_hook("before_model", node="model")
    outcome: HookOutcome = "failed"
    try:
        # langgraph.runtime.get_config 与此为同一函数; 把当前图 config 交给 ainvoke.
        async def request() -> AIMessage:
            async def invoke() -> AIMessage:
                return await runtime.context.model.ainvoke(model_messages, get_config())

            timeout = runtime.context.request_timeout_seconds
            if timeout is None:
                return await run_cancellable(invoke, runtime.context.cancellation_token)
            async with asyncio.timeout(timeout):
                return await run_cancellable(invoke, runtime.context.cancellation_token)

        policy = runtime.context.retry_policy
        if policy is None:
            reply = await request()
        else:
            async with asyncio.timeout(policy.run_timeout_seconds):
                reply = await arun_with_retry(
                    request,
                    policy,
                    clock=monotonic,
                    sleep=asyncio.sleep,
                )
        outcome = "completed"
        return {
            "messages": [reply],
            "status": "awaiting_tools" if reply.tool_calls else "completed",
            "error": None,
        }
    except asyncio.CancelledError:
        # 取消仍向上传播, 由图边界包装成 NodeCancelledError; after_model 记 cancelled.
        outcome = "cancelled"
        raise
    except Exception as exc:
        # 固定正文, 避免把 Authorization 头或密钥写进 state 或 hook 事件.
        return {
            "status": "failed",
            "error": {
                "code": "model_error",
                "exception_type": type(exc).__name__,
                "message": "Model request failed.",
            },
        }
    finally:
        # 成功 / 失败 / 取消各恰好一次 after_model, 且不携带异常正文.
        await runtime.context.dispatch_hook("after_model", node="model", outcome=outcome)


async def async_tool_node(
    state: AgentState,
    runtime: Runtime[AsyncRunContext],
) -> AgentStateUpdate:
    """Execute requested tools sequentially and return result-message deltas."""
    assistant_message = _latest_tool_request(state)
    results: list[AnyMessage] = []
    for call in assistant_message.tool_calls:
        tool_name = call["name"]
        tool_call_id = _require_call_id(call)
        # 每个 tool_call 一对 before/after; 顺序与 assistant.tool_calls 一致.
        await runtime.context.dispatch_hook(
            "before_tool",
            node="tools",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )
        outcome: HookOutcome = "failed"
        try:
            result = await runtime.context.tools.execute_call(
                call, runtime.context.cancellation_token
            )
            # ToolMessage.status 是 success/error, hook 只映射成 completed/failed.
            outcome = "completed" if result.status == "success" else "failed"
            results.append(result)
        except asyncio.CancelledError:
            # 取消不投影半截 ToolMessage; after_tool 记 cancelled 后继续冒泡.
            outcome = "cancelled"
            raise
        finally:
            await runtime.context.dispatch_hook(
                "after_tool",
                node="tools",
                outcome=outcome,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
            )
    return {
        "messages": results,
        "status": "ready",
        "error": None,
        "tool_rounds": state["tool_rounds"] + 1,
    }


async def async_tool_limit_node(
    state: AgentState,
    runtime: Runtime[AsyncRunContext],
) -> AgentStateUpdate:
    """Return correlated errors instead of executing calls beyond the round limit."""
    assistant_message = _latest_tool_request(state)
    maximum = runtime.context.max_tool_rounds
    results: list[AnyMessage] = [
        create_error_tool_message(
            call,
            code="tool_round_limit",
            message=f"Tool round limit reached ({maximum}); call was not executed.",
        )
        for call in assistant_message.tool_calls
    ]
    return {
        "messages": results,
        "status": "failed",
        "error": {
            "code": "tool_round_limit",
            "max_rounds": maximum,
            "message": f"Tool round limit reached ({maximum}).",
        },
    }
