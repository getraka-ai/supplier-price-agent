"""A manual tool-use loop on the Claude Messages API.

Claude decides which tool to call, we run it against SQLite, send the result
back, and repeat until Claude answers in plain text.
"""

import json
import os
import sqlite3

from . import db
from .tools import TOOL_FUNCS, TOOL_SCHEMAS, ToolError

DEFAULT_MODEL = os.environ.get("RAKA_MODEL", "claude-sonnet-5-5")
MAX_TURNS = 8

SYSTEM_PROMPT = """You help independent restaurant owners keep food costs under control.
You have tools over the restaurant's supplier invoices. Always use them to get numbers; never guess a price.
When a price went up, say by how much, what it does to the affected dishes, and whether another supplier is cheaper.
If the owner asks for an email to a supplier, write a short, polite draft they can send themselves. Never claim you sent it.
Keep answers short and concrete. Use dollar amounts and percents from the tool results."""


def run_tool(conn: sqlite3.Connection, name: str, args: dict) -> tuple[str, bool]:
    """Run one tool. Returns (json_text, is_error)."""
    func = TOOL_FUNCS.get(name)
    if func is None:
        return json.dumps({"error": f"Unknown tool {name}"}), True
    try:
        return json.dumps(func(conn, **args)), False
    except (ToolError, TypeError) as e:
        return json.dumps({"error": str(e)}), True


def ask(question: str, client=None, conn=None, model: str = DEFAULT_MODEL, verbose: bool = False) -> dict:
    """Answer one question. Returns {"answer", "tool_calls", "usage"}."""
    if client is None:
        import anthropic  # imported lazily so tests run without an API key
        client = anthropic.Anthropic()
    conn = conn or db.load()

    messages = [{"role": "user", "content": question}]
    tool_calls = []
    usage = {"input_tokens": 0, "output_tokens": 0}

    for _ in range(MAX_TURNS):
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens

        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            return {"answer": text, "tool_calls": tool_calls, "usage": usage}

        # Keep Claude's turn (including its tool_use blocks) in the history.
        messages.append({"role": "assistant", "content": response.content})

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            output, is_error = run_tool(conn, block.name, block.input)
            tool_calls.append({"name": block.name, "input": block.input, "is_error": is_error})
            if verbose:
                print(f"  -> {block.name}({json.dumps(block.input)}){' ERROR' if is_error else ''}")
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                "is_error": is_error,
            })
        messages.append({"role": "user", "content": results})

    return {"answer": "Stopped: too many tool calls.", "tool_calls": tool_calls, "usage": usage}
