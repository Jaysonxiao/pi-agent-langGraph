"""Native async graph nodes for M8.5."""

import asyncio
from time import monotonic

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.config import get_config
from langgraph.runtime import Runtime

from pi_agent.context.async_runtime import prepare_model_messages_async
from pi_agent.domain.state import AgentState, AgentStateUpdate
from pi_agent.graph.async_context import AsyncRunContext
from pi_agent.graph.nodes import _latest_tool_request
from pi_agent.runtime.async_retry import arun_with_retry
from pi_agent.runtime.runner import run_cancellable
from pi_agent.tools.registry import create_error_tool_message


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
        return {
            "status": "failed",
            "error": {
                "code": "context_error",
                "exception_type": type(exc).__name__,
                "message": "Context preparation failed; original messages are preserved.",
            },
        }

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
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # 固定正文, 避免把 Authorization 头或密钥写进 state.
        return {
            "status": "failed",
            "error": {
                "code": "model_error",
                "exception_type": type(exc).__name__,
                "message": "Model request failed.",
            },
        }

    return {
        "messages": [reply],
        "status": "awaiting_tools" if reply.tool_calls else "completed",
        "error": None,
    }


async def async_tool_node(
    state: AgentState,
    runtime: Runtime[AsyncRunContext],
) -> AgentStateUpdate:
    """Execute requested tools sequentially and return result-message deltas."""
    assistant_message = _latest_tool_request(state)
    results: list[AnyMessage] = [
        await runtime.context.tools.execute_call(call, runtime.context.cancellation_token)
        for call in assistant_message.tool_calls
    ]
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
