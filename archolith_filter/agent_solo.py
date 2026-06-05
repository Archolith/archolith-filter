"""Agent-solo turn compression — mechanical token savings without an LLM call.

Four independent, composable strategies that reduce the token footprint of
tool-call continuation turns (where the last message role is "tool"):

A. **Shrink** — cap every tool-role message to an approximate token
   budget using char-length heuristics (~4 chars/token).  The cap is
   fuzzy — actual token count may be 10-20% above or below the nominal
   ``shrink_max_tokens`` value.  No tiktoken overhead.

B. **Dedup** — replace byte-identical tool results with compact markers
   using a caller-provided ``DedupeTracker``.

C. **Filter middle** — apply ``filter_output()`` to compressible tool
   results in the historical (middle) section while shrinking the
   coherence tail.

D. **Compact tool args** — replace large arguments in completed tool_use
   calls (Write, Edit, create_file) with compact summaries.  The file
   content is already cached by the proxy's file cache — the model can
   use Read to retrieve it if needed.

All four are fail-open: if anything raises, the original messages are
returned unchanged.

Usage::

    from archolith_filter.agent_solo import compress_agent_solo_turn, AgentSoloResult
    from archolith_filter.dedupe import DedupeTracker

    tracker = DedupeTracker()  # one per session
    result = compress_agent_solo_turn(
        messages,
        dedup_tracker=tracker,
        shrink_enabled=True,
        dedup_enabled=True,
        filter_middle_enabled=True,
    )
    print(result.stats)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dedupe import DedupeTracker


@dataclass
class AgentSoloStats:
    """Per-strategy savings from agent-solo compression."""

    strategies_applied: list[str] = field(default_factory=list)
    chars_saved_shrink: int = 0
    chars_saved_dedup: int = 0
    chars_saved_filter: int = 0
    chars_saved_compact: int = 0
    total_chars_saved: int = 0
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategies_applied": list(self.strategies_applied),
            "chars_saved_shrink": self.chars_saved_shrink,
            "chars_saved_dedup": self.chars_saved_dedup,
            "chars_saved_filter": self.chars_saved_filter,
            "chars_saved_compact": self.chars_saved_compact,
            "total_chars_saved": self.total_chars_saved,
            "skipped_reason": self.skipped_reason,
        }


@dataclass
class AgentSoloResult:
    """Return value of ``compress_agent_solo_turn``."""

    messages: list[dict[str, Any]]
    stats: AgentSoloStats


# ─── Helpers ────────────────────────────────────────────────────────────


def _tool_content_chars(messages: list[dict[str, Any]]) -> int:
    """Sum of char lengths of all tool-role message content."""
    total = 0
    for m in messages:
        if m.get("role") == "tool":
            c = m.get("content")
            if isinstance(c, str):
                total += len(c)
    return total


# ─── Compressible tool classification ───────────────────────────────────

# Tools whose output is informational/search and safe to filter in the
# middle section.  File-read tools (read, cat, head, tail) return exact
# content the model may need for edits — they are preserved verbatim.
_COMPRESSIBLE_TOOLS = frozenset({
    # Search/grep tools
    "search", "grep", "rg", "ripgrep", "search_content",
    "find", "fd", "locate",
    # Web and informational
    "web_fetch", "webfetch", "fetch",
    "web_search", "websearch",
    # Directory listing (not file content)
    "list_directory", "listdir", "ls", "glob",
    # Shell commands that return informational output
    "bash", "shell", "run_command", "execute",
})


def _is_compressible_tool(tool_name: str) -> bool:
    """Return True if this tool's result is safe to filter in the middle."""
    if not tool_name:
        return False
    name = tool_name.lower()
    if name in _COMPRESSIBLE_TOOLS:
        return True
    # Prefix match for namespaced tools (e.g. "mcp__brave__search")
    for compressible in _COMPRESSIBLE_TOOLS:
        if name.endswith(f"__{compressible}") or name.endswith(f"_{compressible}"):
            return True
    return False


# ─── Strategy A: Shrink ─────────────────────────────────────────────────

# Approximate chars-per-token for code/English — same constant used by
# the shrink subsystem.  Avoids tiktoken overhead entirely.
_CHARS_PER_TOKEN = 4


def _apply_shrink(
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> tuple[list[dict[str, Any]], int]:
    """Char-budget every tool-role message (~4 chars/token).

    Uses ``truncate_for_chars`` instead of tiktoken-based shrinking so
    the cost is O(n) string slicing, not O(n) tokenization.

    Returns (processed_messages, chars_saved).
    """
    from .shrink.truncate import truncate_for_chars

    max_chars = max_tokens * _CHARS_PER_TOKEN
    result: list[dict[str, Any]] = []
    chars_saved = 0

    for msg in messages:
        if msg.get("role") != "tool":
            result.append(msg)
            continue

        content = msg.get("content")
        if not isinstance(content, str) or len(content) <= max_chars:
            result.append(msg)
            continue

        truncated = truncate_for_chars(content, max_chars)
        chars_saved += len(content) - len(truncated)
        result.append({**msg, "content": truncated})

    return result, chars_saved


# ─── Strategy B: Dedup ──────────────────────────────────────────────────

# Minimum content length to bother hashing — smaller results cost less
# than the marker overhead.
_DEDUP_MIN_CHARS = 200


def _apply_dedup(
    messages: list[dict[str, Any]],
    tracker: DedupeTracker,
) -> tuple[list[dict[str, Any]], int]:
    """Replace byte-identical tool results with compact markers.

    Uses the caller-provided ``DedupeTracker`` so that dedup state is
    scoped per-session (the caller creates one tracker per session and
    reuses it across turns).

    Returns (processed_messages, chars_saved).
    """
    result: list[dict[str, Any]] = []
    chars_saved = 0

    for msg in messages:
        if msg.get("role") != "tool":
            result.append(msg)
            continue

        content = msg.get("content")
        if not isinstance(content, str) or len(content) < _DEDUP_MIN_CHARS:
            result.append(msg)
            continue

        hit = tracker.check(content)
        if hit is not None:
            # Already seen — replace with compact marker
            occurrence = tracker.record(content)
            marker = (
                f"[identical to prior result, occurrence {occurrence}"
                f" -- {len(content):,} chars omitted]"
            )
            result.append({**msg, "content": marker})
            chars_saved += len(content) - len(marker)
        else:
            # First time — record hash and pass through
            tracker.record(content)
            result.append(msg)

    return result, chars_saved


# ─── Strategy C: Filter middle ──────────────────────────────────────────

# Maximum chars before a tool result triggers filtering.
_FILTER_MIN_CHARS = 500


def _split_sections(
    messages: list[dict[str, Any]],
    coherence_tail_size: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split messages into (system_prefix, middle, tail).

    System messages at the start form the prefix.  The last
    ``coherence_tail_size`` non-system messages form the tail.
    Everything between is the middle section.
    """
    system: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "system" and not rest:
            system.append(msg)
        else:
            rest.append(msg)

    if len(rest) <= coherence_tail_size:
        # Not enough messages to have a middle section
        return system, [], rest

    tail_start = len(rest) - coherence_tail_size
    return system, rest[:tail_start], rest[tail_start:]


def _filter_middle_messages(
    middle: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Apply ``filter_output()`` to compressible tool results in the middle.

    Returns (processed_middle, chars_saved).
    """
    from . import filter_output

    result: list[dict[str, Any]] = []
    chars_saved = 0

    for msg in middle:
        if msg.get("role") != "tool":
            result.append(msg)
            continue

        content = msg.get("content")
        if not isinstance(content, str) or len(content) < _FILTER_MIN_CHARS:
            result.append(msg)
            continue

        tool_name = (msg.get("name") or "").lower()
        if not _is_compressible_tool(tool_name):
            result.append(msg)
            continue

        try:
            fr = filter_output(content, tool=tool_name)
            if fr.truncated and fr.filtered_chars < len(content):
                result.append({**msg, "content": fr.output})
                chars_saved += len(content) - fr.filtered_chars
            else:
                result.append(msg)
        except Exception:
            result.append(msg)

    return result, chars_saved


def _shrink_tail_messages(
    tail: list[dict[str, Any]],
    max_tokens: int,
) -> tuple[list[dict[str, Any]], int]:
    """Shrink tool results in the coherence tail (char-based).

    Returns (processed_tail, chars_saved).
    """
    from .shrink.truncate import truncate_for_chars

    max_chars = max_tokens * _CHARS_PER_TOKEN
    result: list[dict[str, Any]] = []
    chars_saved = 0

    for msg in tail:
        if msg.get("role") != "tool":
            result.append(msg)
            continue

        content = msg.get("content")
        if not isinstance(content, str) or len(content) <= max_chars:
            result.append(msg)
            continue

        truncated = truncate_for_chars(content, max_chars)
        chars_saved += len(content) - len(truncated)
        result.append({**msg, "content": truncated})

    return result, chars_saved


def _apply_filter_middle(
    messages: list[dict[str, Any]],
    coherence_tail_size: int,
    tail_shrink_tokens: int,
) -> tuple[list[dict[str, Any]], int]:
    """Strategy C: filter compressible tools in middle, shrink tail.

    Returns (processed_messages, chars_saved).
    """
    system, middle, tail = _split_sections(messages, coherence_tail_size)

    if not middle:
        # No middle section — only shrink the tail
        if tail:
            shrunk_tail, saved = _shrink_tail_messages(tail, tail_shrink_tokens)
            return system + shrunk_tail, saved
        return messages, 0

    filtered_middle, middle_saved = _filter_middle_messages(middle)
    shrunk_tail, tail_saved = _shrink_tail_messages(tail, tail_shrink_tokens)

    return system + filtered_middle + shrunk_tail, middle_saved + tail_saved


# ─── Strategy D: Compact completed tool_use arguments ──────────────────

# Tool names whose arguments contain file content worth compacting.
_WRITE_TOOLS = frozenset({
    "write", "write_file", "create_file", "create",
    "str_replace_editor",  # Cursor/Aider style
})
_EDIT_TOOLS = frozenset({
    "edit", "edit_file", "patch", "str_replace",
})

# Minimum argument length to bother compacting.
_COMPACT_MIN_CHARS = 500


def _apply_compact_tool_args(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Compact large arguments in completed tool_use calls.

    For Write/Edit tool calls that have a matching tool result (i.e., the
    call has been executed), replace the file content in the arguments
    with a compact summary.  The model can use Read to retrieve the
    original content from the proxy's file cache if needed.

    Only processes assistant messages in the middle of the conversation
    (not the last assistant message, which may be an in-progress call).

    Returns (processed_messages, chars_saved).
    """
    import json as _json

    # Build set of tool_call_ids that have matching tool results
    completed_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            completed_ids.add(msg["tool_call_id"])

    if not completed_ids:
        return messages, 0

    result: list[dict[str, Any]] = []
    chars_saved = 0
    any_changed = False

    for msg in messages:
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            result.append(msg)
            continue

        new_tool_calls = []
        msg_changed = False

        for tc in msg["tool_calls"]:
            fn = tc.get("function", {})
            tc_id = tc.get("id", "")
            name = (fn.get("name") or "").lower()
            args_str = fn.get("arguments", "")

            # Only compact completed calls with large arguments
            if (
                tc_id not in completed_ids
                or len(args_str) < _COMPACT_MIN_CHARS
            ):
                new_tool_calls.append(tc)
                continue

            # Parse arguments to find file content
            try:
                args = _json.loads(args_str)
            except (ValueError, TypeError):
                new_tool_calls.append(tc)
                continue

            compacted = False
            original_len = len(args_str)

            if name in _WRITE_TOOLS and "content" in args:
                content = args["content"]
                if isinstance(content, str) and len(content) > _COMPACT_MIN_CHARS:
                    path = args.get("file_path") or args.get("path") or "file"
                    lines = content.count("\n") + 1
                    args["content"] = (
                        f"[written, {lines} lines, {len(content):,} chars"
                        f" -- use Read on {path} to review]"
                    )
                    compacted = True

            elif name in _EDIT_TOOLS:
                for key in ("old_string", "old_str", "old"):
                    if key in args and isinstance(args[key], str) and len(args[key]) > _COMPACT_MIN_CHARS:
                        lines = args[key].count("\n") + 1
                        args[key] = f"[{lines} lines replaced]"
                        compacted = True
                for key in ("new_string", "new_str", "new"):
                    if key in args and isinstance(args[key], str) and len(args[key]) > _COMPACT_MIN_CHARS:
                        lines = args[key].count("\n") + 1
                        path = args.get("file_path") or args.get("path") or "file"
                        args[key] = (
                            f"[{lines} lines -- use Read on {path} to review]"
                        )
                        compacted = True

            if compacted:
                new_args_str = _json.dumps(args, ensure_ascii=False)
                saved = original_len - len(new_args_str)
                if saved > 0:
                    new_fn = {**fn, "arguments": new_args_str}
                    new_tool_calls.append({**tc, "function": new_fn})
                    chars_saved += saved
                    msg_changed = True
                else:
                    new_tool_calls.append(tc)
            else:
                new_tool_calls.append(tc)

        if msg_changed:
            result.append({**msg, "tool_calls": new_tool_calls})
            any_changed = True
        else:
            result.append(msg)

    if not any_changed:
        return messages, 0

    return result, chars_saved


# ─── Orchestrator ────────────────────────────────────────────────────────


def compress_agent_solo_turn(
    messages: list[dict[str, Any]],
    *,
    dedup_tracker: DedupeTracker | None = None,
    shrink_enabled: bool = False,
    dedup_enabled: bool = False,
    filter_middle_enabled: bool = False,
    compact_tool_args_enabled: bool = True,
    shrink_max_tokens: int = 2000,
    coherence_tail_size: int = 10,
    tail_shrink_tokens: int = 2000,
) -> AgentSoloResult:
    """Apply enabled agent-solo compression strategies.

    Strategies are applied in order D -> C -> B -> A so that:
    - Tool arg compaction runs first (removes dead-weight file content)
    - Middle compression runs next (structural reduction)
    - Dedup runs on the structurally compressed output
    - Shrink runs last as a catch-all cap

    Args:
        messages: OpenAI-format message list (list of dicts).
        dedup_tracker: Session-scoped DedupeTracker.  Required when
            ``dedup_enabled`` is True.
        shrink_enabled: Enable Strategy A (token-budget all tool results).
        dedup_enabled: Enable Strategy B (cross-turn content dedup).
        filter_middle_enabled: Enable Strategy C (filter middle, shrink tail).
        compact_tool_args_enabled: Enable Strategy D (compact completed
            Write/Edit tool_use arguments).  Default True — essentially
            free and always beneficial.
        shrink_max_tokens: Approximate per-result token cap for Strategy A
            (converted to chars via ~4 chars/token — fuzzy, not exact).
        coherence_tail_size: Number of trailing messages for the tail
            (Strategy C).
        tail_shrink_tokens: Per-result token cap for tail shrinking
            (Strategy C).

    Returns:
        AgentSoloResult with processed messages and per-strategy stats.
    """
    stats = AgentSoloStats()

    any_enabled = shrink_enabled or dedup_enabled or filter_middle_enabled or compact_tool_args_enabled
    if not any_enabled:
        stats.skipped_reason = "no_strategies_enabled"
        return AgentSoloResult(messages=messages, stats=stats)

    result = messages

    # Strategy D — compact completed tool_use arguments (Write/Edit content)
    if compact_tool_args_enabled:
        try:
            result, saved = _apply_compact_tool_args(result)
            stats.chars_saved_compact = saved
            if saved > 0:
                stats.strategies_applied.append("compact")
        except Exception:
            pass  # fail-open

    # Strategy C — filter middle section + shrink tail
    if filter_middle_enabled:
        try:
            result, saved = _apply_filter_middle(
                result,
                coherence_tail_size=coherence_tail_size,
                tail_shrink_tokens=tail_shrink_tokens,
            )
            stats.chars_saved_filter = saved
            if saved > 0:
                stats.strategies_applied.append("filter")
        except Exception:
            pass  # fail-open

    # Strategy B — dedup (before shrink so markers stay compact)
    if dedup_enabled and dedup_tracker is not None:
        try:
            result, saved = _apply_dedup(result, dedup_tracker)
            stats.chars_saved_dedup = saved
            if saved > 0:
                stats.strategies_applied.append("dedup")
        except Exception:
            pass  # fail-open

    # Strategy A — shrink remaining tool results
    if shrink_enabled:
        try:
            result, saved = _apply_shrink(result, max_tokens=shrink_max_tokens)
            stats.chars_saved_shrink = saved
            if saved > 0:
                stats.strategies_applied.append("shrink")
        except Exception:
            pass  # fail-open

    stats.total_chars_saved = (
        stats.chars_saved_shrink
        + stats.chars_saved_dedup
        + stats.chars_saved_filter
        + stats.chars_saved_compact
    )

    if (
        not shrink_enabled
        and not dedup_enabled
        and not filter_middle_enabled
        and stats.chars_saved_compact == 0
    ):
        stats.skipped_reason = "no_strategies_enabled"

    return AgentSoloResult(messages=result, stats=stats)
