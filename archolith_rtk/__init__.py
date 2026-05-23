"""Archolith RTK — Token Reduction Toolkit.

Deterministic output filtering for LLM agent contexts.
Three layers: output filters, shrink, context manager.

Public API:
    filter_output()  — Layer 1: compress tool results before model context
    shrink_messages() — Layer 2: truncate oversized messages in conversation history
    ContextManager   — Layer 3: threshold-based conversation folding
"""

from __future__ import annotations

from .classifier import classify_command, CommandCategory, ClassifiedCommand
from .config import FilterConfig, from_env, boost_for_verbose, is_filter_enabled, is_verbose_command
from .filter_meta import FilterMeta, parse_result_meta
from .filters import FilterResult
from .filters.generic import generic_filter, GenericFilterOptions
from .filters.git_diff import git_diff_filter, GitDiffFilterOptions
from .filters.git_log import git_log_filter, GitLogFilterOptions
from .filters.git_status import git_status_filter, GitStatusFilterOptions
from .filters.git_show import git_show_filter, GitShowFilterOptions
from .filters.json_output import json_filter, JsonFilterOptions
from .filters.fs_listing import fs_listing_filter, FsListingFilterOptions
from .filters.search import search_filter, SearchFilterOptions
from .filters.test_run_output import filter_test_output, TestFilterOptions
from .filters.build_output import build_filter, BuildFilterOptions
from .filters.lint_output import lint_filter, LintFilterOptions
from .filters.typecheck_output import typecheck_filter, TypecheckFilterOptions
from .filters.logs import log_filter, LogFilterOptions
from .raw_store import RawOutputStore, get_raw_output_store, reset_raw_output_store
from .strip_ansi import strip_ansi
from .telemetry import (
    record_filter_telemetry,
    record_filter_telemetry_with_tokens,
    get_filter_telemetry_store,
    reset_filter_telemetry_store,
    FilterTelemetrySummary,
)
from .shrink import (
    count_tokens,
    truncate_for_chars,
    truncate_for_tokens,
    shrink_oversized_tool_results,
    shrink_oversized_tool_results_by_tokens,
    shrink_oversized_tool_call_args_by_tokens,
    estimate_conversation_tokens,
    estimate_request_tokens,
    ChatMessage,
    ToolCall,
    ShrinkCharsResult,
    ShrinkTokensResult,
)
from .context_manager import (
    ContextManager,
    PostUsageDecision,
    PostUsageKind,
    PreflightDecision,
    FoldResult,
    get_context_limit,
    simple_extractive_summarizer,
    HISTORY_FOLD_THRESHOLD,
    HISTORY_FOLD_TAIL_FRACTION,
    HISTORY_FOLD_AGGRESSIVE_THRESHOLD,
    FORCE_SUMMARY_THRESHOLD,
    PREFLIGHT_EMERGENCY_THRESHOLD,
    DEFAULT_CONTEXT_TOKENS,
)

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
        if mapped == "read_file":
            # Use generic for now; compress_read_file is a future enhancement.
            return "generic"
        return mapped

    # MCP tools: if output looks like JSON, use JSON filter.
    if tool_name.startswith("mcp__"):
        trimmed = text.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            return "json"
        return "generic"

    return "generic"
