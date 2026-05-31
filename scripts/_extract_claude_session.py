#!/usr/bin/env python3
"""Extract agent-solo turns from a Claude Code JSONL and convert to OpenAI format.

Claude Code stores Anthropic-format messages (content blocks with tool_use /
tool_result types).  This script reconstructs progressive conversation snapshots,
converts to OpenAI format, and identifies agent-solo turns (tool-call continuations).

Usage:
    python _extract_claude_session.py <jsonl_path> [-o output.json] [--min-chars 10000]
"""

import argparse
import json
import sys
from pathlib import Path


def _anthropic_to_openai(messages: list[dict]) -> list[dict]:
    """Convert Anthropic-format messages to OpenAI-format messages.

    Anthropic format:
        - assistant content can include tool_use blocks
        - user content can include tool_result blocks

    OpenAI format:
        - assistant messages have tool_calls array
        - tool results are separate role="tool" messages
    """
    result = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            if isinstance(content, str):
                result.append({"role": "system", "content": content})
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                result.append({"role": "system", "content": "\n".join(text_parts)})
            continue

        if role == "assistant":
            if isinstance(content, str):
                result.append({"role": "assistant", "content": content})
                continue

            if isinstance(content, list):
                text_parts = []
                tool_calls = []

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", "unknown"),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        })

                if tool_calls:
                    msg_out = {
                        "role": "assistant",
                        "content": "\n".join(text_parts) if text_parts else None,
                        "tool_calls": tool_calls,
                    }
                    result.append(msg_out)
                elif text_parts:
                    result.append({"role": "assistant", "content": "\n".join(text_parts)})
            continue

        if role == "user":
            if isinstance(content, str):
                result.append({"role": "user", "content": content})
                continue

            if isinstance(content, list):
                text_parts = []
                tool_results = []

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        tool_id = block.get("tool_use_id", "")
                        block_content = block.get("content", "")
                        if isinstance(block_content, list):
                            parts = []
                            for p in block_content:
                                if isinstance(p, dict) and p.get("type") == "text":
                                    parts.append(p.get("text", ""))
                            block_content = "\n".join(parts)
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "name": "unknown",
                            "content": str(block_content),
                        })

                # Emit text parts as user message first
                if text_parts:
                    result.append({"role": "user", "content": "\n".join(text_parts)})

                # Emit tool results as separate tool messages
                result.extend(tool_results)
            continue

    return result


def _find_tool_name(tool_id: str, messages: list[dict]) -> str:
    """Look up the tool name for a tool_call_id from assistant tool_calls."""
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls", []):
            if tc.get("id") == tool_id:
                return tc.get("function", {}).get("name", "unknown")
    return "unknown"


def extract_turns(jsonl_path: str, min_chars: int = 10000) -> list[list[dict]]:
    """Extract agent-solo turn snapshots from a Claude Code JSONL.

    Returns a list of progressive message snapshots, one per agent-solo turn.
    """
    # Reconstruct conversation from JSONL records
    conversation: list[dict] = []

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            rtype = record.get("type", "")

            if rtype in ("user", "assistant"):
                msg = record.get("message")
                if msg and isinstance(msg, dict):
                    conversation.append(msg)

    if not conversation:
        print("No messages found in JSONL", file=sys.stderr)
        return []

    print("Raw messages: %d" % len(conversation))

    # Convert to OpenAI format
    openai_msgs = _anthropic_to_openai(conversation)
    print("OpenAI messages: %d" % len(openai_msgs))

    # Resolve tool names in tool results
    for msg in openai_msgs:
        if msg.get("role") == "tool" and msg.get("name") == "unknown":
            name = _find_tool_name(msg.get("tool_call_id", ""), openai_msgs)
            msg["name"] = name

    # Build progressive snapshots at each tool result (agent-solo turns)
    turns = []
    for i, msg in enumerate(openai_msgs):
        if msg.get("role") != "tool":
            continue

        snapshot = openai_msgs[:i + 1]
        total_chars = sum(len(str(m.get("content", ""))) for m in snapshot)

        if total_chars >= min_chars:
            turns.append(snapshot)

    print("Agent-solo snapshots: %d (>= %d chars)" % (len(turns), min_chars))
    return turns


def main():
    parser = argparse.ArgumentParser(description="Extract Claude JSONL for agent-solo benchmark")
    parser.add_argument("jsonl", help="Path to Claude Code JSONL")
    parser.add_argument("-o", "--output", help="Output JSON path")
    parser.add_argument("--min-chars", type=int, default=10000, help="Min chars per turn snapshot")
    parser.add_argument("--max-turns", type=int, default=200, help="Max turns to extract")
    args = parser.parse_args()

    turns = extract_turns(args.jsonl, min_chars=args.min_chars)

    if not turns:
        print("No turns extracted", file=sys.stderr)
        sys.exit(1)

    # Limit turns
    if len(turns) > args.max_turns:
        # Sample evenly across the session
        step = len(turns) // args.max_turns
        turns = turns[::step][:args.max_turns]
        print("Sampled to %d turns" % len(turns))

    total_chars = sum(sum(len(str(m.get("content", ""))) for m in t) for t in turns)
    total_tool = sum(
        sum(len(str(m.get("content", ""))) for m in t if m.get("role") == "tool")
        for t in turns
    )
    pct = (total_tool / total_chars * 100) if total_chars else 0
    print("Total: %d chars, %d tool chars (%.1f%%)" % (total_chars, total_tool, pct))
    print("Avg turn: %d chars" % (total_chars // max(len(turns), 1)))

    out_path = args.output or "claude_session.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(turns, f)
    print("Written to %s" % out_path)


if __name__ == "__main__":
    main()
