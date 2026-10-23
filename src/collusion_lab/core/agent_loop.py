"""Minimal tool-use loop on top of Inspect's model API.

We execute tools ourselves (instead of letting a framework do it) so that every
call is routed through the environment's logged dispatcher: the agent can neither
skip logging nor reach the monitor.

Two tool-calling modes:
  native - OpenAI/Anthropic-style function calling
  json   - prompted protocol for models without function calling (e.g. gemma2 on
           Ollama, some free endpoints): the model replies with one JSON object
           {"tool": "<name>", "args": {...}} per turn.
The roster switches a model to json mode automatically if its API rejects tools.
"""
from __future__ import annotations

import asyncio
import json
import re
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

    def signature(self) -> str:
        args = ", ".join(f"{k}: {t}{'' if k in self.required else '?'}" for k, (t, _) in self.params.items())
        return f"- {self.name}({args}): {self.description}"


JSON_PROTOCOL = """
TOOLS (call exactly one per reply):
{sigs}

Reply with ONLY a JSON object, no prose, no code fences, e.g.
{{"tool": "read_file", "args": {{"path": "SPEC.md"}}}}
You will then receive the tool result. Call "done" when finished."""


def run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()


def parse_json_call(text: str, names: set[str]) -> tuple[str, dict] | None:
    """Extract {"tool": ..., "args": {...}} (also accepts name/arguments, function/parameters)."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    for m in re.finditer(r"\{", text):
        depth, end = 0, None
        for i in range(m.start(), len(text)):
            depth += text[i] == "{"
            depth -= text[i] == "}"
            if depth == 0:
                end = i + 1
                break
        if end is None:
            continue
        try:
            d = json.loads(text[m.start():end])
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        name = d.get("tool") or d.get("name") or d.get("function")
        args = d.get("args") or d.get("arguments") or d.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if name in names and isinstance(args, dict):
            return name, args
    return None


async def tool_loop(roster, role: str, system: str, user: str, tools: list[ToolSpec],
                    dispatch: Callable[[str, dict[str, Any]], str], max_turns: int = 20,
                    stop_tools: tuple[str, ...] = ("done",), temperature: float = 0.7) -> list:
    from .models import AllModelsFailed, ToolModeSwitch
    names = {t.name for t in tools}
    mode = roster.tool_mode(role)

    def sys_msg() -> ChatMessageSystem:
        if mode == "json":
            return ChatMessageSystem(content=system + JSON_PROTOCOL.format(sigs="\n".join(t.signature() for t in tools)))
        return ChatMessageSystem(content=system)

    messages: list = [sys_msg(), ChatMessageUser(content=user)]
    infos = [t.info() for t in tools]
    turns = 0
    while turns < max_turns:
        turns += 1
        try:
            out = await roster.generate(role, messages, tools=infos if mode == "native" else None,
                                        temperature=temperature)
        except ToolModeSwitch:
            mode = "json"
            messages[0] = sys_msg()
            turns -= 1
            continue
        except AllModelsFailed:
            break                                   # agent "times out"; episode continues
        msg: ChatMessageAssistant = out.message
        calls = [(c.id, c.function, c.arguments if isinstance(c.arguments, dict) else json.loads(c.arguments or "{}"))
                 for c in (msg.tool_calls or [])]
        if not calls:
            parsed = parse_json_call(out.completion, names)
            if parsed:
                calls = [(None, parsed[0], parsed[1])]
        if mode == "json" or not msg.tool_calls:
            messages.append(ChatMessageAssistant(content=out.completion or ""))
        else:
            messages.append(msg)
        if not calls:
            hint = ('Reply with one JSON tool call, e.g. {"tool": "done", "args": {}}' if mode == "json"
                    else "Continue. Use the tools; call `done` when finished.")
            messages.append(ChatMessageUser(content=hint))
            continue
        stop = False
        for cid, fn, args in calls:
            try:
                result = dispatch(fn, args)
            except TypeError as e:   # bad/missing arguments from weak models
                result = f"error: bad arguments for {fn}: {e}"
            if cid is not None and mode == "native" and msg.tool_calls:
                messages.append(ChatMessageTool(content=result, tool_call_id=cid, function=fn))
            else:
                messages.append(ChatMessageUser(content=f"RESULT of {fn}:\n{result}"))
            if fn in stop_tools:
                stop = True
        if stop:
            break
    return messages
