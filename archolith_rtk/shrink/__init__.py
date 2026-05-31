"""Layer 2: Shrink oversized tool results and tool-call args in conversation history.

Two modes:
- char-based: truncate tool-role messages exceeding a char budget
- token-based: truncate tool-role messages and tool_call arguments exceeding a token budget

Token mode requires tiktoken (optional dependency). Without it, falls back to
char-based heuristics (~4 chars per token for English/code).

Package structure (import DAG, leaf→root):
  models → token_counter → truncate → read_file_truncate → orchestrator
  json_shrink (leaf) → orchestrator
"""

from __future__ import annotations

from .json_shrink import shrink_json_long_strings
from .models import (
    ChatMessage,
    ShrinkCharsResult,
    ShrinkTokensResult,
    ToolCall,
    ToolCallFunction,
)
from .orchestrator import (
    estimate_conversation_tokens,
    estimate_request_tokens,
    shrink_messages,
    shrink_oversized_tool_call_args_by_tokens,
    shrink_oversized_tool_results,
    shrink_oversized_tool_results_by_tokens,
)
from .read_file_truncate import (
    truncate_read_file_for_chars,
    truncate_read_file_for_tokens,
)
from .token_counter import count_tokens
from .truncate import truncate_for_chars, truncate_for_tokens

__all__ = [
    "ChatMessage",
    "ShrinkCharsResult",
    "ShrinkTokensResult",
    "ToolCall",
    "ToolCallFunction",
    "count_tokens",
    "estimate_conversation_tokens",
    "estimate_request_tokens",
    "shrink_json_long_strings",
    "shrink_messages",
    "shrink_oversized_tool_call_args_by_tokens",
    "shrink_oversized_tool_results",
    "shrink_oversized_tool_results_by_tokens",
    "truncate_for_chars",
    "truncate_for_tokens",
    "truncate_read_file_for_chars",
    "truncate_read_file_for_tokens",
]
