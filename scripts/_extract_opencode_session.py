#!/usr/bin/env python3
"""Extract a full conversation from OpenCode SQLite as agent-solo benchmark input.

Usage:
    # List recent sessions
    python _extract_opencode_session.py --list

    # Extract a session to JSON (for agent_solo_benchmark.py --payload)
    python _extract_opencode_session.py --session <id> --output payload.json

    # Extract the most recent session
    python _extract_opencode_session.py --latest --output payload.json
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = r"C:\Users\thron\.local\share\opencode\opencode.db"


def list_sessions(db_path: str, limit: int = 15):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "SELECT id, title, time_created, time_updated, model "
        "FROM session ORDER BY time_updated DESC LIMIT ?",
        (limit,),
    )
    rows = c.fetchall()
    conn.close()

    print(f"{'ID':<14} {'Created':<18} {'Updated':<18} {'Model':<25} {'Title'}")
    print("-" * 110)
    for sid, title, tc, tu, model in rows:
        created = datetime.fromtimestamp(tc / 1000 if tc > 1e10 else tc)
        updated = datetime.fromtimestamp(tu / 1000 if tu > 1e10 else tu)
        model_s = (model or "?")[:24]
        title_s = (title or "?")[:50]
        print(f"{sid[:12]}..  {str(created)[:16]}  {str(updated)[:16]}  {model_s:<25} {title_s}")


def extract_session_messages(db_path: str, session_id: str) -> list[list[dict]]:
    """Extract conversation as a list of turn snapshots (progressive message lists).

    Each 'turn' is the full message list as it would have been at that point,
    built by replaying the message/part history.
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Resolve partial session ID
    c.execute("SELECT id FROM session WHERE id LIKE ?", (session_id + "%",))
    matches = c.fetchall()
    if not matches:
        print(f"No session matching '{session_id}'", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"Ambiguous session ID '{session_id}', matches: {[m[0][:12] for m in matches]}", file=sys.stderr)
        sys.exit(1)
    full_id = matches[0][0]

    # Get all messages in order
    c.execute(
        "SELECT id, data, time_created FROM message "
        "WHERE session_id = ? ORDER BY time_created ASC",
        (full_id,),
    )
    messages_raw = c.fetchall()

    # Get all parts for each message
    c.execute(
        "SELECT message_id, data, time_created FROM part "
        "WHERE session_id = ? ORDER BY time_created ASC",
        (full_id,),
    )
    parts_raw = c.fetchall()
    conn.close()

    # Build message objects from parts
    # OpenCode stores messages and parts separately. Each message has parts
    # that contain the actual content (text, tool calls, tool results).
    messages_by_id = {}
    for mid, data_str, tc in messages_raw:
        try:
            data = json.loads(data_str) if data_str else {}
        except json.JSONDecodeError:
            data = {}
        messages_by_id[mid] = {"id": mid, "data": data, "time": tc, "parts": []}

    for mid, data_str, tc in parts_raw:
        if mid not in messages_by_id:
            continue
        try:
            data = json.loads(data_str) if data_str else {}
        except json.JSONDecodeError:
            continue
        messages_by_id[mid]["parts"].append(data)

    # Convert to OpenAI message format
    openai_messages = []
    for mid in sorted(messages_by_id, key=lambda k: messages_by_id[k]["time"]):
        msg_info = messages_by_id[mid]
        msg_data = msg_info["data"]
        parts = msg_info["parts"]

        role = msg_data.get("role", "")

        # Build from parts if available
        for part in parts:
            part_type = part.get("type", "")

            if part_type == "text":
                content = part.get("text", "")
                if content:
                    openai_messages.append({"role": role, "content": content})

            elif part_type == "tool-invocation":
                # Assistant tool call
                tool_name = part.get("toolName", part.get("tool", "unknown"))
                tool_id = part.get("toolInvocationId", part.get("id", ""))
                args = part.get("args", part.get("input", {}))
                openai_messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tool_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
                        },
                    }],
                })

            elif part_type == "tool-result" or part_type == "tool":
                # Tool result
                tool_id = part.get("toolInvocationId", part.get("toolCallId", ""))
                tool_name = part.get("toolName", part.get("tool", "unknown"))
                state = part.get("state", {})
                if isinstance(state, dict):
                    output = state.get("output", state.get("result", ""))
                else:
                    output = str(state)

                # Some results are in 'result' directly
                if not output and "result" in part:
                    result = part["result"]
                    if isinstance(result, list):
                        # Multi-part content
                        texts = []
                        for r in result:
                            if isinstance(r, dict) and r.get("type") == "text":
                                texts.append(r.get("text", ""))
                        output = "\n".join(texts)
                    elif isinstance(result, str):
                        output = result

                if output:
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "name": tool_name,
                        "content": str(output),
                    })

        # Fallback: no parts, just message data
        if not parts and role:
            content = msg_data.get("content", "")
            if content:
                openai_messages.append({"role": role, "content": content})

    if not openai_messages:
        print(f"No messages extracted from session {full_id[:12]}", file=sys.stderr)
        sys.exit(1)

    # Build progressive turn snapshots: each agent-solo turn is the full
    # message history up to and including the latest tool result
    turns = []
    for i, msg in enumerate(openai_messages):
        if msg.get("role") == "tool":
            # Check if this is part of a tool-call continuation (agent-solo)
            # by looking at whether a user message appears between here and
            # the previous tool result
            turns.append(list(openai_messages[: i + 1]))

    # Filter to turns that are large enough to be interesting (>10K chars)
    large_turns = [t for t in turns if sum(len(str(m.get("content", ""))) for m in t) > 10000]

    return large_turns if large_turns else turns[-5:] if turns else [openai_messages]


def main():
    parser = argparse.ArgumentParser(description="Extract OpenCode sessions for benchmarking")
    parser.add_argument("--db", default=DB_PATH, help="OpenCode SQLite path")
    parser.add_argument("--list", action="store_true", help="List recent sessions")
    parser.add_argument("--session", type=str, help="Session ID (prefix match)")
    parser.add_argument("--latest", action="store_true", help="Use most recent session")
    parser.add_argument("--output", "-o", type=str, help="Output JSON path")
    args = parser.parse_args()

    if args.list or (not args.session and not args.latest):
        list_sessions(args.db)
        return

    if args.latest:
        conn = sqlite3.connect(args.db)
        c = conn.cursor()
        c.execute("SELECT id FROM session ORDER BY time_updated DESC LIMIT 1")
        row = c.fetchone()
        conn.close()
        if not row:
            print("No sessions found", file=sys.stderr)
            sys.exit(1)
        session_id = row[0]
    else:
        session_id = args.session

    print(f"Extracting session {session_id[:12]}...")
    turns = extract_session_messages(args.db, session_id)
    print(f"Extracted {len(turns)} turns")

    total_chars = sum(sum(len(str(m.get("content", ""))) for m in t) for t in turns)
    total_tool = sum(
        sum(len(str(m.get("content", ""))) for m in t if m.get("role") == "tool")
        for t in turns
    )
    print(f"Total chars: {total_chars:,}, tool chars: {total_tool:,} ({total_tool/total_chars*100:.1f}%)")

    out_path = args.output or f"session_{session_id[:8]}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(turns, f)
    print(f"Written to {out_path}")


if __name__ == "__main__":
    main()
