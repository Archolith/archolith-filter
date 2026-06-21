"""Archolith Filter — Deterministic output filtering for LLM agent contexts.

Three layers:

- Layer 0 — Pre-filter: ANSI strip, secret redaction, thinking-block strip,
  binary detection, path normalization, dedupe, oversized guard.
- Layer 1 — Category filters: 13 shell-command categories + ``read_file``
  structure-aware compression.
- Layer 2 — Shrink: char and token-based truncation of oversized messages,
  plus agent-solo turn compression.

Public API:
    filter_output() — Layer 1: compress tool results before model context
    shrink_messages() — Layer 2: truncate oversized messages in conversation history
    compress_agent_solo_turn() — Layer 3: turn-level compression for tool-call
        continuation payloads (four independent strategies: shrink, dedup,
        filter-middle, compact-tool-args)

Stable public API is documented in ``__all__``.  Everything else is internal
and may change without notice.
"""

from __future__ import annotations

import logging

from .agent_solo import AgentSoloResult, AgentSoloStats, compress_agent_solo_turn
from .classifier import ClassifiedCommand, CommandCategory, classify_command
from .config import (
    FilterConfig,
    FilterRiskLevel,
    base_config_for_risk_level,
    boost_for_verbose,
    from_env,
    is_filter_enabled,
    is_verbose_command,
    normalize_risk_level,  # noqa: F401 — re-exported in __all__
)
from .dedupe import DedupeHit, DedupeTracker, get_dedupe_tracker, reset_dedupe_tracker  # noqa: F401
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
from .normalize import normalize_runtime_noise
from .paths import normalize_paths
from .raw_store import RawOutputStore, get_raw_output_store, reset_raw_output_store  # noqa: F401
from .redact import redact_secrets
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
from .strip_thinking import strip_thinking_blocks
from .telemetry import (  # noqa: F401 — re-exported in __all__
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
# ─── Agent-solo compression ───
"AgentSoloResult",
"AgentSoloStats",
"compress_agent_solo_turn",
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
# ─── Filter ───
"FilterMeta",
"FilterResult",
"parse_result_meta",
# ─── Classifier ───
"ClassifiedCommand",
"CommandCategory",
"classify_command",
# ─── Normalization & Stripping ───
"normalize_paths",
"normalize_runtime_noise",
"redact_secrets",
"strip_ansi",
"strip_thinking_blocks",
]

_log = logging.getLogger(__name__)

# Minimum result length (chars) to justify filtering overhead.
_MIN_FILTER_CHARS = 500

# ── Binary detection ──────────────────────────────────────────────────────
# Scan the first 64 KB for NUL bytes. If >3 NUL bytes, compute text ratio.
_BINARY_SCAN_BYTES = 64_000
_BINARY_NUL_THRESHOLD = 3
_BINARY_TEXT_RATIO = 0.1


def _is_binary_output(text: str) -> tuple[bool, int, float]:
    """Check if *text* appears to be binary content.

    Returns (is_binary, nul_count, text_ratio).
    """
    nul_count = 0
    scan_chars = min(len(text), _BINARY_SCAN_BYTES)
    for ch in text[:scan_chars]:
        if ch == '\x00':
            nul_count += 1
            if nul_count > _BINARY_NUL_THRESHOLD:
                break

    if nul_count <= _BINARY_NUL_THRESHOLD:
        return False, nul_count, 1.0

    # Strip control chars to measure text content (limited to same scan window).
    scan_text = text[:_BINARY_SCAN_BYTES]
    cleaned = ''.join(
        ch for ch in scan_text
        if ch >= ' ' or ch in '\n\r\t'
    )
    text_ratio = len(cleaned.strip()) / max(1, len(scan_text))
    return text_ratio < _BINARY_TEXT_RATIO, nul_count, text_ratio


# ── Oversized input guard ─────────────────────────────────────────────────
_OVERSIZED_HEAD_CHARS = 2000
_OVERSIZED_TAIL_CHARS = 1000


def _oversized_guard(text: str, max_chars: int) -> FilterResult | None:
    """Check if *text* exceeds *max_chars* and return a head/tail preview.

    Returns a FilterResult with truncated output if oversized, or None
    if the text is within limits.
    """
    if len(text) <= max_chars:
        return None

    head = text[:_OVERSIZED_HEAD_CHARS]
    tail = text[-_OVERSIZED_TAIL_CHARS:]
    marker = (
        f"\n[... Output truncated: {len(text):,} chars (limit: {max_chars:,}). "
        f"Showing first {_OVERSIZED_HEAD_CHARS:,} and last {_OVERSIZED_TAIL_CHARS:,} chars. "
        f"Use targeted queries or narrower tool scope to see the full output. ...]\n"
    )
    output = f"{head}{marker}{tail}"
    return FilterResult(
        output=output,
        raw_chars=len(text),
        filtered_chars=len(output),
        truncated=True,
    )


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
            head_lines=cfg.git_status_head, tail_lines=cfg.git_status_tail,
            group_enabled=cfg.git_status_group_enabled, group_max_per_line=cfg.git_status_group_max_per_line,
        ))
    if category == "test":
        return filter_test_output(formatted, TestFilterOptions(
            head_lines=cfg.test_head, tail_lines=cfg.test_tail,
            normalize_noise_enabled=cfg.normalize_noise_enabled,
        ))
    if category == "build":
        return build_filter(formatted, BuildFilterOptions(
            head_lines=cfg.build_head, tail_lines=cfg.build_tail,
            summary_enabled=cfg.build_summary_enabled,
            normalize_noise_enabled=cfg.normalize_noise_enabled,
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
            max_entries=cfg.fs_max_entries, head_lines=cfg.fs_head_lines, tail_lines=cfg.fs_tail_lines,
            lsl_abbreviate_enabled=cfg.fs_lsl_abbreviate_enabled,
            table_whitespace_min_enabled=cfg.table_whitespace_min_enabled,
        ))
    if category == "search":
        return search_filter(formatted, SearchFilterOptions(
            max_matches_per_file=cfg.search_max_matches_per_file,
            max_files=cfg.search_max_files,
            head_lines=cfg.search_head_lines,
            tail_lines=cfg.search_tail_lines,
            heading_reformat_enabled=cfg.search_heading_reformat_enabled,
        ))
    if category == "json":
        return json_filter(formatted, JsonFilterOptions(
            max_keys_per_object=cfg.json_max_keys_per_object,
            max_array_items=cfg.json_max_array_items,
            max_depth=cfg.json_max_depth,
            max_value_length=cfg.json_max_value_length,
            csv_enabled=cfg.json_csv_enabled,
            csv_min_rows=cfg.json_csv_min_rows,
            csv_max_rows=cfg.json_csv_max_rows,
            csv_max_key_length=cfg.json_csv_max_key_length,
            kv_enabled=cfg.json_kv_enabled,
            kv_min_keys=cfg.json_kv_min_keys,
            kv_max_keys=cfg.json_kv_max_keys,
            dotkey_enabled=cfg.json_dotkey_enabled,
            dotkey_max_keys=cfg.json_dotkey_max_keys,
            dotkey_max_depth=cfg.json_dotkey_max_depth,
            csv_factor_enabled=cfg.json_csv_factor_enabled,
            csv_factor_threshold=cfg.json_csv_factor_threshold,
            csv_factor_max_columns=cfg.json_csv_factor_max_columns,
        ))
    if category == "logs":
        return log_filter(formatted, LogFilterOptions(
            head_lines=cfg.log_head, tail_lines=cfg.log_tail,
            max_consecutive_dupes=cfg.log_max_consecutive_dupes,
            normalize_noise_enabled=cfg.normalize_noise_enabled,
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
        head_lines=cfg.generic_head, tail_lines=cfg.generic_tail,
        stack_collapse_enabled=cfg.generic_stack_collapse_enabled,
        stack_collapse_min_frames=cfg.generic_stack_collapse_min_frames,
        stack_collapse_keep_app_frames=cfg.generic_stack_collapse_keep_app_frames,
    ))


def filter_output(
    text: str,
    *,
    command: str = "",
    tool: str = "",
    exit_code: int | None = None,
    timed_out: bool = False,
    config: FilterConfig | None = None,
    dedupe_tracker: DedupeTracker | None = None,
) -> FilterResult:
    """Layer 1: Filter a tool result before it enters model context.

    Pipeline order:
        1. Secret redaction — strip secrets before anything else touches text
        2. Binary detection — early return for NUL-byte content
        3. Oversized guard — early return for >configured_max chars
        4. ANSI stripping — strip terminal control codes
        5. Thinking block strip — remove model-internal reasoning tags
        6. Path normalization — strip workspace root, normalize separators
        7. Cross-turn dedupe — exact-match repeat detection
        8. Error-awareness — non-zero exit bypasses filtering
        9. 500-char minimum — skip small results
       10. Category dispatch — route to category-specific filter

    Args:
        text: The raw tool output text.
        command: The shell command that produced this output (for classification).
        tool: The tool name (e.g. "run_command", "read_file").
        exit_code: Process exit code (None if unknown). Non-zero exits bypass filtering.
        timed_out: Whether the command was killed after timeout.
        config: Optional FilterConfig override. Defaults to env-var config.
        dedupe_tracker: Optional DedupeTracker for Stage 7 (cross-turn dedupe).
            When provided, this tracker is used instead of the process-global
            singleton. Use a fresh tracker per request batch for payload-replay
            semantics (re-sent history is never markered). Omit or pass None
            to use the persistent process-global singleton for live-stream
            semantics (genuine new outputs are deduped across calls).

    Returns:
        FilterResult with compressed output, char counts, and truncation flag.
    """
    if config is None:
        config = from_env()

    if not is_filter_enabled():
        return FilterResult(output=text, raw_chars=len(text), filtered_chars=len(text), truncated=False)

    raw_chars = len(text)

    # ── Layer 0: Pre-filter pipeline ────────────────────────────────
    # Stage 1: Secret redaction — FIRST, before anything else.
    redacted = text
    redaction_count = 0
    if config.redact_enabled:
        redacted_result = redact_secrets(text)
        redacted = redacted_result.output
        redaction_count = redacted_result.redaction_count
        if redaction_count > 0:
            record_filter_telemetry(
                command=command or tool,
                tool=tool or None,
                filter_kind="redact",
                raw_chars=raw_chars,
                filtered_chars=len(redacted),
                raw_output_id=None,
                fallback_used=False,
            )

    # Stage 2: Binary detection — early return if content is binary.
    if config.binary_detection_enabled:
        is_binary, nul_count, text_ratio = _is_binary_output(redacted)
        if is_binary:
            output = (
                f"[Binary output suppressed — {nul_count} NUL bytes, "
                f"{text_ratio:.1%} text content.]"
            )
            record_filter_telemetry(
                command=command or tool,
                tool=tool or None,
                filter_kind="binary",
                raw_chars=raw_chars,
                filtered_chars=len(output),
                raw_output_id=None,
                fallback_used=False,
            )
            return FilterResult(
                output=output,
                raw_chars=raw_chars,
                filtered_chars=len(output),
                truncated=True,
            )

    # Stage 3: Oversized input guard — early return for huge outputs.
    if config.oversized_guard_enabled:
        oversized_result = _oversized_guard(redacted, config.oversized_max_chars)
        if oversized_result is not None:
            record_filter_telemetry(
                command=command or tool,
                tool=tool or None,
                filter_kind="oversized",
                raw_chars=raw_chars,
                filtered_chars=oversized_result.filtered_chars,
                raw_output_id=None,
                fallback_used=False,
            )
            return oversized_result

    # ── Core pipeline ─────────────────────────────────────────────────
    # Stage 4: Strip ANSI escape codes.
    stripped = strip_ansi(redacted)

    # Stage 5: Thinking block strip — remove model reasoning tags.
    if config.strip_thinking_enabled:
        stripped = strip_thinking_blocks(stripped)

    # Stage 6: Path normalization — strip workspace root, normalize separators.
    if config.normalize_paths_enabled:
        stripped = normalize_paths(stripped)

    # Stage 7: Cross-turn dedupe — check for exact repeats.
    # Use caller-provided tracker if present; otherwise use process-global singleton.
    dedupe = dedupe_tracker if dedupe_tracker is not None else get_dedupe_tracker()
    dedupe_hit = dedupe.check(stripped)
    if dedupe_hit is not None:
        occurrence = dedupe.record(stripped)
        store = get_raw_output_store()
        raw_id = store.store(redacted, command=command or tool, tool=tool, filtered_chars=0)
        marker = f"[repeated output, occurrence {occurrence}, raw_output_id={raw_id}]"
        record_filter_telemetry(
            command=command or tool,
            tool=tool or None,
            filter_kind="dedupe",
            raw_chars=raw_chars,
            filtered_chars=len(marker),
            raw_output_id=raw_id,
            fallback_used=False,
        )
        return FilterResult(output=marker, raw_chars=raw_chars, filtered_chars=len(marker), truncated=True)
    dedupe.record(stripped)

    # Stage 8: Error-aware — never filter failed commands.
    if timed_out or (exit_code is not None and exit_code != 0):
        return FilterResult(output=stripped, raw_chars=raw_chars, filtered_chars=len(stripped), truncated=False)

    # Stage 9: Skip small results — overhead outweighs savings.
    if len(stripped) < _MIN_FILTER_CHARS:
        return FilterResult(output=stripped, raw_chars=raw_chars, filtered_chars=len(stripped), truncated=False)

    try:
        # Stage 10: Verbose commands get doubled head/tail limits.
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
                raw_chars=raw_chars,
                filtered_chars=len(stripped),
                truncated=False,
            )

        result = _category_filter(category, stripped, effective_cfg)

        # Store raw output and add recovery marker when output was compressed.
        if result.truncated:
            store = get_raw_output_store()
            raw_id = store.store(redacted, command=command or tool, tool=tool, filtered_chars=result.filtered_chars)
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

    except Exception as exc:
        # Fail open: any error returns the stripped string.
        _log.warning(
            "filter_output pipeline raised; fail-open returned unfiltered text "
            "(command=%r tool=%r error=%s)",
            command, tool, exc,
        )
        store = get_raw_output_store()
        raw_id = store.store(redacted, command=command or tool, tool=tool, filtered_chars=len(stripped))
        record_filter_telemetry(
            command=command or tool,
            tool=tool or None,
            filter_kind="fallback",
            raw_chars=raw_chars,
            filtered_chars=len(stripped),
            raw_output_id=raw_id,
            fallback_used=True,
        )
        return FilterResult(output=stripped, raw_chars=raw_chars, filtered_chars=len(stripped), truncated=False)


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
