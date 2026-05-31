"""Archolith RTK — Token Reduction Toolkit.

Deterministic output filtering for LLM agent contexts.
Two layers: output filters and shrink.

Public API:
    filter_output()  — Layer 1: compress tool results before model context
    shrink_messages() — Layer 2: truncate oversized messages in conversation history
"""

from __future__ import annotations

from .classifier import ClassifiedCommand, CommandCategory, classify_command
from .config import (
    FilterConfig,
    FilterRiskLevel,
    base_config_for_risk_level,
    boost_for_verbose,
    from_env,
    is_filter_enabled,
    is_verbose_command,
    normalize_risk_level,
)
from .dedupe import DedupeHit, DedupeTracker, get_dedupe_tracker, reset_dedupe_tracker
from .filter_meta import FilterMeta, parse_result_meta
from .filters import FilterResult
from .filters.build_output import BuildFilterOptions, build_filter
from .filters.fs_listing import FsListingFilterOptions, fs_listing_filter
from .filters.generic import GenericFilterOptions, generic_filter
from .filters.git_diff import GitDiffFilterOptions, git_diff_filter
from .filters.git_log import GitLogFilterOptions, git_log_filter
from .filters.git_show import GitShowFilterOptions, git_show_filter
from .filters.git_status import GitStatusFilterOptions, git_status_filter
from .filters.json_output import JsonFilterOptions, json_filter
from .filters.lint_output import LintFilterOptions, lint_filter
from .filters.logs import LogFilterOptions, log_filter
from .filters.read_file import ReadFileFilterOptions, read_file_filter
from .filters.search import SearchFilterOptions, search_filter
from .filters.test_run_output import TestFilterOptions, filter_test_output
from .filters.typecheck_output import TypecheckFilterOptions, typecheck_filter
from .raw_store import RawOutputStore, get_raw_output_store, reset_raw_output_store
from .shrink import (
    ChatMessage,
    ShrinkCharsResult,
    ShrinkTokensResult,
    ToolCall,
    ToolCallFunction,
    count_tokens,
    estimate_conversation_tokens,
    estimate_request_tokens,
    shrink_json_long_strings,
    shrink_messages,
    shrink_oversized_tool_call_args_by_tokens,
    shrink_oversized_tool_results,
    shrink_oversized_tool_results_by_tokens,
    truncate_for_chars,
    truncate_for_tokens,
    truncate_read_file_for_chars,
    truncate_read_file_for_tokens,
)
from .strip_ansi import strip_ansi
from .telemetry import (
    FilterTelemetrySummary,
    get_filter_telemetry_store,
    record_filter_telemetry,
    record_filter_telemetry_with_tokens,
    reset_filter_telemetry_store,
)

__all__ = [
    # ─── Core API ───
    "filter_output",
    "shrink_messages",
    # ─── Shrink ───
    "ChatMessage",
    "ShrinkCharsResult",
    "ShrinkTokensResult",
    "ToolCall",
    "ToolCallFunction",
    "count_tokens",
    "estimate_conversation_tokens",
    "estimate_request_tokens",
    "shrink_json_long_strings",
    "shrink_oversized_tool_call_args_by_tokens",
    "shrink_oversized_tool_results",
    "shrink_oversized_tool_results_by_tokens",
    "truncate_for_chars",
    "truncate_for_tokens",
    "truncate_read_file_for_chars",
    "truncate_read_file_for_tokens",
    # ─── Config ───
    "FilterConfig",
    "FilterRiskLevel",
    "base_config_for_risk_level",
    "from_env",
    "is_filter_enabled",
    "is_verbose_command",
    # ─── Filter ───
    "FilterMeta",
    "FilterResult",
    # ─── Classifier ───
    "ClassifiedCommand",
    "CommandCategory",
    "classify_command",
]

# Minimum result length (chars) to justify filtering overhead.
_MIN_FILTER_CHARS = 500


def _category_filter(
    category: CommandCategory | str,
    formatted: str,
    cfg: FilterConfig,
) -> FilterResult:
    """Route a classified command/tool to its category-specific filter."""
    if category == "git-diff":
        return git_diff_filter(formatted, GitDiffFilterOptions(
            file_head_lines=cfg.git_diff_file_head, tail_lines=cfg.git_diff_tail
        ))
    if category == "git-show":
        return git_show_filter(formatted, GitShowFilterOptions(
            file_head_lines=cfg.git_diff_file_head, tail_lines=cfg.git_diff_tail
        ))
    if category == "git-log":
        return git_log_filter(formatted, GitLogFilterOptions(
            head_commits=cfg.git_log_head, tail_commits=cfg.git_log_tail
        ))
    if category == "git-status":
        return git_status_filter(formatted, GitStatusFilterOptions(
            head_lines=cfg.git_status_head, tail_lines=cfg.git_status_tail
        ))
    if category == "test":
        return filter_test_output(formatted, TestFilterOptions(
            head_lines=cfg.test_head, tail_lines=cfg.test_tail
        ))
    if category == "build":
        return build_filter(formatted, BuildFilterOptions(
            head_lines=cfg.build_head, tail_lines=cfg.build_tail
        ))
    if category == "lint":
        return lint_filter(formatted, LintFilterOptions(
            head_lines=cfg.lint_head, tail_lines=cfg.lint_tail
        ))
    if category == "typecheck":
        return typecheck_filter(formatted, TypecheckFilterOptions(
            head_lines=cfg.typecheck_head, tail_lines=cfg.typecheck_tail
        ))
    if category == "ls-tree":
        return fs_listing_filter(formatted, FsListingFilterOptions(
            max_entries=cfg.fs_max_entries, head_lines=cfg.fs_head_lines, tail_lines=cfg.fs_tail_lines
        ))
    if category == "search":
        return search_filter(formatted, SearchFilterOptions(
            max_matches_per_file=cfg.search_max_matches_per_file,
            max_files=cfg.search_max_files,
            head_lines=cfg.search_head_lines,
            tail_lines=cfg.search_tail_lines,
        ))
    if category == "json":
        return json_filter(formatted, JsonFilterOptions(
            max_keys_per_object=cfg.json_max_keys_per_object,
            max_array_items=cfg.json_max_array_items,
            max_depth=cfg.json_max_depth,
            max_value_length=cfg.json_max_value_length,
        ))
    if category == "logs":
        return log_filter(formatted, LogFilterOptions(
            head_lines=cfg.log_head, tail_lines=cfg.log_tail,
            max_consecutive_dupes=cfg.log_max_consecutive_dupes,
        ))
    if category == "read_file":
        return read_file_filter(formatted, ReadFileFilterOptions(
            import_collapse=cfg.read_import_collapse,
            blank_line_max=cfg.read_blank_line_max,
            comment_threshold=cfg.read_comment_threshold,
            css_rule_collapse=cfg.read_css_rule_collapse,
            generated_min_line_len=cfg.read_generated_min_line_len,
            generated_min_run=cfg.read_generated_min_run,
            literal_threshold=cfg.read_literal_threshold,
        ))
    # Default: generic
    return generic_filter(formatted, GenericFilterOptions(
        head_lines=cfg.generic_head, tail_lines=cfg.generic_tail
    ))


def filter_output(
    text: str,
    *,
    command: str = "",
    tool: str = "",
    exit_code: int | None = None,
    timed_out: bool = False,
    config: FilterConfig | None = None,
) -> FilterResult:
    """Layer 1: Filter a tool result before it enters model context.

    Args:
        text: The raw tool output text.
        command: The shell command that produced this output (for classification).
        tool: The tool name (e.g. "run_command", "read_file").
        exit_code: Process exit code (None if unknown). Non-zero exits bypass filtering.
        timed_out: Whether the command was killed after timeout.
        config: Optional FilterConfig override. Defaults to env-var config.

    Returns:
        FilterResult with compressed output, char counts, and truncation flag.
    """
    if config is None:
        config = from_env()

    if not is_filter_enabled():
        return FilterResult(output=text, raw_chars=len(text), filtered_chars=len(text), truncated=False)

    # Strip ANSI escape codes — the model doesn't need color/styling.
    stripped = strip_ansi(text)

    # Cross-turn dedupe: check if we've seen this exact content before.
    dedupe = get_dedupe_tracker()
    dedupe_hit = dedupe.check(stripped)
    if dedupe_hit is not None:
        occurrence = dedupe.record(stripped)
        store = get_raw_output_store()
        raw_id = store.store(text, command=command or tool, tool=tool, filtered_chars=0)
        marker = f"[repeated output, occurrence {occurrence}, raw_output_id={raw_id}]"
        record_filter_telemetry(
            command=command or tool,
            tool=tool or None,
            filter_kind="dedupe",
            raw_chars=len(text),
            filtered_chars=len(marker),
            raw_output_id=raw_id,
            fallback_used=False,
        )
        return FilterResult(output=marker, raw_chars=len(text), filtered_chars=len(marker), truncated=True)
    dedupe.record(stripped)

    # Error-aware: never filter failed commands.
    if timed_out or (exit_code is not None and exit_code != 0):
        return FilterResult(output=stripped, raw_chars=len(text), filtered_chars=len(stripped), truncated=False)

    # Skip small results — overhead outweighs savings.
    if len(stripped) < _MIN_FILTER_CHARS:
        return FilterResult(output=stripped, raw_chars=len(text), filtered_chars=len(stripped), truncated=False)

    try:
        # Verbose commands get doubled head/tail limits.
        effective_cfg = boost_for_verbose(config) if is_verbose_command(command) else config

        # Classify the command to route to the right filter.
        if command:
            classified = classify_command(command)
            category: CommandCategory | str = classified.category
        elif tool:
            # Tool-level dispatch (non-shell tools).
            category = _classify_tool(tool, stripped)
        else:
            category = CommandCategory.GENERIC

        if category in {"passthrough", "shell"}:
            return FilterResult(
                output=stripped,
                raw_chars=len(text),
                filtered_chars=len(stripped),
                truncated=False,
            )

        result = _category_filter(category, stripped, effective_cfg)

        # Store raw output and add recovery marker when output was compressed.
        if result.truncated:
            store = get_raw_output_store()
            raw_id = store.store(text, command=command or tool, tool=tool, filtered_chars=result.filtered_chars)
            record_filter_telemetry(
                command=command or tool,
                tool=tool or None,
                filter_kind=str(category),
                raw_chars=result.raw_chars,
                filtered_chars=result.filtered_chars,
                raw_output_id=raw_id,
                fallback_used=False,
            )
            marker = f"[filtered {result.raw_chars} chars -> {result.filtered_chars} chars, raw_output_id={raw_id}]"
            output = f"{result.output}\n{marker}"
            return FilterResult(output=output, raw_chars=result.raw_chars, filtered_chars=len(output), truncated=True)

        record_filter_telemetry(
            command=command or tool,
            tool=tool or None,
            filter_kind=str(category),
            raw_chars=result.raw_chars,
            filtered_chars=result.filtered_chars,
            raw_output_id=None,
            fallback_used=False,
        )

        return result

    except Exception:
        # Fail open: any error returns the ANSI-stripped string.
        store = get_raw_output_store()
        raw_id = store.store(text, command=command or tool, tool=tool, filtered_chars=len(stripped))
        record_filter_telemetry(
            command=command or tool,
            tool=tool or None,
            filter_kind="fallback",
            raw_chars=len(stripped),
            filtered_chars=len(stripped),
            raw_output_id=raw_id,
            fallback_used=True,
        )
        return FilterResult(output=stripped, raw_chars=len(text), filtered_chars=len(stripped), truncated=False)


# Tool name classification for non-shell dispatch.
_SHELL_TOOLS = frozenset({"run_command", "run_background", "job_output", "stop_job"})
_NEVER_FILTER = frozenset({"raw_output"})

_TOOL_CATEGORY_MAP: dict[str, str] = {
    "read_file": "read_file",
    "edit_file": "edit_file",
    "search_content": "search",
    "wait_for_job": "logs",
    "list_jobs": "logs",
    "remember": "generic",
    "forget": "generic",
    "recall_memory": "generic",
    "web_search": "generic",
    "web_fetch": "generic",
}


def _classify_tool(tool_name: str, text: str) -> str:
    """Classify a non-shell tool name into a filter category."""
    if tool_name in _NEVER_FILTER:
        return "passthrough"
    if tool_name in _SHELL_TOOLS:
        return "shell"  # Already filtered by shell pipeline

    mapped = _TOOL_CATEGORY_MAP.get(tool_name)
    if mapped:
        return mapped

    # MCP tools: if output looks like JSON, use JSON filter.
    if tool_name.startswith("mcp__"):
        trimmed = text.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            return "json"
        return "generic"

    return "generic"
