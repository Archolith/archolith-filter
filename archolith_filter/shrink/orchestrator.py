"""Orchestrator — public shrink API functions.

Top-level functions that compose the shrink subsystem:
- shrink_oversized_tool_results (char-based)
- shrink_oversized_tool_results_by_tokens (token-based)
- shrink_oversized_tool_call_args_by_tokens
- shrink_messages (compat wrapper)
- estimate_conversation_tokens
- estimate_request_tokens

Import DAG: depends on models, token_counter, truncate, read_file_truncate, json_shrink.
"""

from __future__ import annotations

import json

from .json_shrink import shrink_json_long_strings
from .models import (
    ChatMessage,
    ShrinkCharsResult,
    ShrinkTokensResult,
    ToolCall,
    ToolCallFunction,
)
from .read_file_truncate import (
    _READ_FILE_TOOL_NAME,
    truncate_read_file_for_chars,
    truncate_read_file_for_tokens,
)
from .token_counter import count_tokens
from .truncate import truncate_for_chars, truncate_for_tokens

_MESSAGE_FRAMING_TOKENS = 15


def shrink_oversized_tool_results(
    messages: list[ChatMessage],
    max_chars: int,
) -> ShrinkCharsResult:
    """Truncate tool-role messages exceeding max_chars.

    Only tool-role messages are truncated — user/assistant/system messages
    would corrupt authored intent. read_file tool output gets declaration-aware
    truncation preserving signatures and class/function definitions; other tool
    output uses generic head/tail truncation.
    """
    healed_count = 0
    healed_from = 0
    out: list[ChatMessage] = []

    for msg in messages:
        if msg.role != "tool" or msg.content is None:
            out.append(msg)
            continue
        if len(msg.content) <= max_chars:
            out.append(msg)
            continue
        healed_count += 1
        healed_from += len(msg.content)
        if msg.name == _READ_FILE_TOOL_NAME:
            truncated = truncate_read_file_for_chars(msg.content, max_chars)
        else:
            truncated = truncate_for_chars(msg.content, max_chars)
        out.append(ChatMessage(
            role=msg.role,
            content=truncated,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        ))

    return ShrinkCharsResult(messages=out, healed_count=healed_count, healed_from=healed_from)


def shrink_oversized_tool_results_by_tokens(
    messages: list[ChatMessage],
    max_tokens: int,
) -> ShrinkTokensResult:
    """Truncate tool-role messages exceeding max_tokens.

    Token-cap variant — char cap would let CJK slip past at 2× the intended token cost.
    read_file tool output gets declaration-aware truncation; other tool output
    uses generic head/tail truncation.
    """
    healed_count = 0
    tokens_saved = 0
    chars_saved = 0
    out: list[ChatMessage] = []

    for msg in messages:
        if msg.role != "tool" or msg.content is None:
            out.append(msg)
            continue
        content = msg.content
        # Char-length fast path: every token is ≥1 char, so if char count
        # ≤ token budget the content definitely fits and no tokenization is needed.
        if len(content) <= max_tokens:
            out.append(msg)
            continue
        before_tokens = count_tokens(content)
        if before_tokens <= max_tokens:
            out.append(msg)
            continue
        if msg.name == _READ_FILE_TOOL_NAME:
            truncated = truncate_read_file_for_tokens(content, max_tokens)
        else:
            truncated = truncate_for_tokens(content, max_tokens)
        after_tokens = count_tokens(truncated)
        healed_count += 1
        tokens_saved += max(0, before_tokens - after_tokens)
        chars_saved += max(0, len(content) - len(truncated))
        out.append(ChatMessage(
            role=msg.role,
            content=truncated,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        ))

    return ShrinkTokensResult(
        messages=out,
        healed_count=healed_count,
        tokens_saved=tokens_saved,
        chars_saved=chars_saved,
    )


def shrink_oversized_tool_call_args_by_tokens(
    messages: list[ChatMessage],
    max_tokens: int,
) -> ShrinkTokensResult:
    """Shrink long string values in tool_call arguments exceeding max_tokens.

    Caller must gate on paired tool_calls — in-flight calls would crash mid-turn.
    Keeps short keys/values (paths, ids) verbatim; only long string values get a marker.
    """
    healed_count = 0
    tokens_saved = 0
    chars_saved = 0
    out: list[ChatMessage] = []

    for msg in messages:
        if msg.role != "assistant" or not msg.tool_calls:
            out.append(msg)
            continue
        changed = False
        new_calls: list[ToolCall] = []
        for call in msg.tool_calls:
            args = call.function.arguments
            if not args or len(args) <= max_tokens:
                new_calls.append(call)
                continue
            before_tokens = count_tokens(args)
            if before_tokens <= max_tokens:
                new_calls.append(call)
                continue
            shrunk = shrink_json_long_strings(args)
            after_tokens = count_tokens(shrunk)
            # Many-short-strings payloads can come back marginally larger.
            if after_tokens >= before_tokens:
                new_calls.append(call)
                continue
            changed = True
            healed_count += 1
            tokens_saved += before_tokens - after_tokens
            chars_saved += len(args) - len(shrunk)
            new_calls.append(ToolCall(
                id=call.id,
                type=call.type,
                function=ToolCallFunction(
                    id=call.function.id,
                    name=call.function.name,
                    arguments=shrunk,
                ),
            ))
        if not changed:
            out.append(msg)
        else:
            out.append(ChatMessage(
                role=msg.role,
                content=msg.content,
                tool_calls=new_calls,
            ))

    return ShrinkTokensResult(
        messages=out,
        healed_count=healed_count,
        tokens_saved=tokens_saved,
        chars_saved=chars_saved,
    )


def shrink_messages(
    messages: list[dict] | list[ChatMessage],
    *,
    max_chars: int | None = None,
    max_tokens: int | None = None,
) -> list[dict] | list[ChatMessage]:
    """Compatibility wrapper for shrinking OpenAI-format message lists.

    Accepts either dict-format OpenAI messages or ChatMessage objects and
    returns the same shape it received. Exactly one budget must be set.
    """
    if (max_chars is None) == (max_tokens is None):
        raise ValueError("Provide exactly one of max_chars or max_tokens")

    typed_messages = [
        msg if isinstance(msg, ChatMessage) else ChatMessage.from_dict(msg)
        for msg in messages
    ]

    if max_tokens is not None:
        result_messages = shrink_oversized_tool_results_by_tokens(
            typed_messages, max_tokens=max_tokens
        ).messages
    else:
        result_messages = shrink_oversized_tool_results(
            typed_messages, max_chars=max_chars or 0
        ).messages

    if not messages or isinstance(messages[0], ChatMessage):
        return result_messages
    return [msg.to_dict() for msg in result_messages]


def estimate_conversation_tokens(messages: list[ChatMessage]) -> int:
    """Estimate total tokens across all messages (content + tool_calls).

    Includes a small per-message framing estimate so callers do not undercount
    chat-template overhead when comparing against prompt budgets.
    """
    total = 0
    for m in messages:
        total += _MESSAGE_FRAMING_TOKENS
        if isinstance(m.content, str) and m.content:
            total += count_tokens(m.content)
        if m.tool_calls:
            total += count_tokens(json.dumps([tc.to_dict() for tc in m.tool_calls]))
    return total


def estimate_request_tokens(
    messages: list[ChatMessage],
    tool_specs: list[dict] | None = None,
) -> int:
    """Estimate total request tokens (messages + tool specs)."""
    total = estimate_conversation_tokens(messages)
    if tool_specs:
        total += count_tokens(json.dumps(tool_specs))
    return total
