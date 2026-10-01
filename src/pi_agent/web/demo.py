"""Deterministic offline demo using real workspace tools, not a model simulation."""

import asyncio
import json
import re
from collections.abc import AsyncIterator, Sequence

from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig


class DemoModel:
    async def astream(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AsyncIterator[AIMessageChunk]:
        reply = await self.ainvoke(messages, config)
        for index, call in enumerate(reply.tool_calls):
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "name": call["name"],
                        "args": json.dumps(call["args"]),
                        "id": call["id"],
                        "index": index,
                    }
                ],
            )
        if isinstance(reply.content, str):
            for offset in range(0, len(reply.content), 12):
                await asyncio.sleep(0.025)
                yield AIMessageChunk(content=reply.content[offset : offset + 12])

    async def aclose(self) -> None:
        """No owned provider resource in the offline demonstration."""

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        del config
        await asyncio.sleep(0.35)
        last_user = max(
            i for i, message in enumerate(messages) if isinstance(message, HumanMessage)
        )
        results = [m for m in messages[last_user + 1 :] if isinstance(m, ToolMessage)]
        if results:
            return AIMessage(
                content=(
                    "工具操作已处理。下面是工具返回的实际内容: \n\n"
                    f"```text\n{str(results[-1].content)[:6000]}\n```\n\n"
                    "当前是离线演示模式, 可以验证会话、工具和历史记录。"
                    "启动时选择 compatible 模型后, 即可进行分析与总结。"
                )
            )
        text = str(messages[last_user].content)
        for prefix, tool in (("写入 ", "write"), ("修改 ", "edit"), ("执行 ", "propose_command")):
            if text.startswith(prefix):
                try:
                    arguments = json.loads(text[len(prefix) :])
                    if not isinstance(arguments, dict):
                        raise ValueError("Expected a JSON object.")
                except ValueError:
                    return AIMessage(content="离线审批演示需要一个 JSON 参数对象, 请检查格式。")
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": tool,
                            "args": arguments,
                            "id": f"demo-{len(messages)}",
                            "type": "tool_call",
                        }
                    ],
                )
        if _is_greeting(text):
            return AIMessage(content="你好! 我可以按你的需求回答问题或读取工作区文件。")
        match = re.search(r"(?:读取|read)\s*[`\"']?([\w./\\-]+)", text, re.IGNORECASE)
        if match:
            name, args = "read", {"path": match.group(1)}
        elif re.search(r"(?:列出|列表|目录|文件|list|files)", text, re.IGNORECASE):
            name, args = "list", {"path": "."}
        else:
            return AIMessage(
                content=(
                    "当前是离线演示模式 可直接聊天 如要验证工作区工具请明确要求读取文件或列出文件"
                )
            )
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": args,
                    "id": f"demo-{len(messages)}",
                    "type": "tool_call",
                }
            ],
        )


def _is_greeting(text: str) -> bool:
    normalized = re.sub(r"[\W_]+", "", text.casefold())
    return normalized in {"你好", "您好", "嗨", "hi", "hello", "hey", "早上好", "晚上好"}
