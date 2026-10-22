"""Minimal tool-use loop on top of Inspect's model API.

We deliberately execute tools ourselves (instead of letting a framework do it) so
that every call is routed through the environment's logged dispatcher: the agent
can neither skip logging nor reach the monitor.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable

from inspect_ai.model import (ChatMessageAssistant, ChatMessageSystem, ChatMessageTool,
                              ChatMessageUser)
from inspect_ai.tool import ToolInfo, ToolParams
from inspect_ai.util import JSONSchema


@dataclass
class ToolSpec:
    name: str
    description: str
    params: dict[str, tuple[str, str]]          # name -> (json type, description)
    required: tuple[str, ...] = ()

    def info(self) -> ToolInfo:
        props = {}
        for k, (t, d) in self.params.items():
            props[k] = JSONSchema(type="array", items=JSONSchema(type="string"), description=d) \
                if t == "array" else JSONSchema(type=t, description=d)
        return ToolInfo(name=self.name, description=self.description,
                        parameters=ToolParams(properties=props, required=list(self.required)))


def run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()


async def tool_loop(roster, role: str, system: str, user: str, tools: list[ToolSpec],
                    dispatch: Callable[[str, dict[str, Any]], str], max_turns: int = 20,
                    stop_tools: tuple[str, ...] = ("done",), temperature: float = 0.7) -> list:
    messages: list = [ChatMessageSystem(content=system), ChatMessageUser(content=user)]
    infos = [t.info() for t in tools]
    for _ in range(max_turns):
        out = await roster.generate(role, messages, tools=infos, temperature=temperature)
        msg: ChatMessageAssistant = out.message
        messages.append(msg)
        calls = msg.tool_calls or []
        if not calls:
            messages.append(ChatMessageUser(content="Continue. Use the tools; call `done` when finished."))
            continue
        stop = False
        for c in calls:
            args = c.arguments if isinstance(c.arguments, dict) else json.loads(c.arguments or "{}")
            result = dispatch(c.function, args)
            messages.append(ChatMessageTool(content=result, tool_call_id=c.id, function=c.function))
            if c.function in stop_tools:
                stop = True
        if stop:
            break
    return messages
