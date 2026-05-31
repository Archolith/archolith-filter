"""Filter configuration — env-var driven with sane defaults and clamped bounds."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from enum import StrEnum


def _env_int(name: str, fallback: int, max_val: int | None = None) -> int:
    """Read a numeric env var, returning the default if missing or invalid.

    Clamps to [0, max_val] when max_val is provided.
    """
    raw = os.environ.get(name, "")
    if not raw:
        return fallback
    try:
        n = int(raw)
    except ValueError:
        return fallback
    if n < 0:
        return fallback
    if max_val is not None and n > max_val:
        return max_val
    return n


class FilterRiskLevel(StrEnum):
    """Risk tolerance for context compression."""

    LOW = "low"
    BALANCED = "balanced"
    HIGH = "high"


@dataclass(frozen=True)
class FilterConfig:
    """Per-category head/tail line counts, configurable via env vars."""

    risk_level: FilterRiskLevel = FilterRiskLevel.BALANCED
    generic_head: int = 20
    generic_tail: int = 30
    test_head: int = 10
    test_tail: int = 40
    build_head: int = 15
    build_tail: int = 25
    lint_head: int = 15
    lint_tail: int = 30
    typecheck_head: int = 15
    typecheck_tail: int = 30
    git_diff_file_head: int = 8
    git_diff_tail: int = 10
    git_log_head: int = 25
    git_log_tail: int = 15
    git_status_head: int = 50
    git_status_tail: int = 30
    log_head: int = 15
    log_tail: int = 30
    log_max_consecutive_dupes: int = 3
    fs_max_entries: int = 50
    fs_head_lines: int = 20
    fs_tail_lines: int = 30
    search_max_matches_per_file: int = 5
    search_max_files: int = 15
    search_head_lines: int = 20
    search_tail_lines: int = 30
    json_max_keys_per_object: int = 10
    json_max_array_items: int = 5
    json_max_depth: int = 3
    json_max_value_length: int = 80
    # read_file compressor knobs
    read_import_collapse: bool = True
    read_blank_line_max: int = 1
    read_comment_threshold: int = 10
    read_css_rule_collapse: bool = True
    read_generated_min_line_len: int = 500
    read_generated_min_run: int = 5
    read_literal_threshold: int = 8


# Upper bounds to prevent env-var typos from disabling filtering or causing OOM.
_MAX_LINE_LINES = 500
_MAX_ENTRIES = 1000
_MAX_DEPTH = 10
_MAX_VALUE_LENGTH = 10_000

_VERBOSE_MULTIPLIER = 2

_BALANCED_DEFAULT_CONFIG = FilterConfig()

_LOW_RISK_OVERRIDES = {
    "generic_head": 30,
    "generic_tail": 45,
    "test_head": 15,
    "test_tail": 60,
    "build_head": 20,
    "build_tail": 35,
    "lint_head": 20,
    "lint_tail": 40,
    "typecheck_head": 20,
    "typecheck_tail": 40,
    "git_diff_file_head": 12,
    "git_diff_tail": 14,
    "git_log_head": 35,
    "git_log_tail": 20,
    "git_status_head": 80,
    "git_status_tail": 45,
    "log_head": 25,
    "log_tail": 45,
    "log_max_consecutive_dupes": 5,
    "fs_max_entries": 80,
    "fs_head_lines": 30,
    "fs_tail_lines": 45,
    "search_max_matches_per_file": 6,
    "search_max_files": 16,
    "search_head_lines": 30,
    "search_tail_lines": 45,
    "json_max_keys_per_object": 15,
    "json_max_array_items": 8,
    "json_max_depth": 4,
    "json_max_value_length": 160,
}

_HIGH_RISK_OVERRIDES = {
    "generic_head": 10,
    "generic_tail": 15,
    "test_head": 8,
    "test_tail": 20,
    "build_head": 10,
    "build_tail": 15,
    "lint_head": 10,
    "lint_tail": 20,
    "typecheck_head": 10,
    "typecheck_tail": 20,
    "git_diff_file_head": 5,
    "git_diff_tail": 5,
    "git_log_head": 15,
    "git_log_tail": 8,
    "git_status_head": 25,
    "git_status_tail": 15,
    "log_head": 10,
    "log_tail": 20,
    "log_max_consecutive_dupes": 1,
    "fs_max_entries": 30,
    "fs_head_lines": 10,
    "fs_tail_lines": 15,
    "search_max_matches_per_file": 3,
    "search_max_files": 8,
    "search_head_lines": 10,
    "search_tail_lines": 15,
    "json_max_keys_per_object": 5,
    "json_max_array_items": 3,
    "json_max_depth": 2,
    "json_max_value_length": 50,
}


def normalize_risk_level(value: str | FilterRiskLevel | None) -> FilterRiskLevel:
    """Parse a risk level string, defaulting invalid values to balanced."""
    if isinstance(value, FilterRiskLevel):
        return value
    if not value:
        return FilterRiskLevel.BALANCED
    normalized = value.strip().lower()
    for level in FilterRiskLevel:
        if normalized == level.value:
            return level
    return FilterRiskLevel.BALANCED


def base_config_for_risk_level(level: str | FilterRiskLevel = FilterRiskLevel.BALANCED) -> FilterConfig:
    """Return the preset base config for a given risk level."""
    normalized = normalize_risk_level(level)
    if normalized == FilterRiskLevel.LOW:
        return replace(_BALANCED_DEFAULT_CONFIG, risk_level=normalized, **_LOW_RISK_OVERRIDES)
    if normalized == FilterRiskLevel.HIGH:
        return replace(_BALANCED_DEFAULT_CONFIG, risk_level=normalized, **_HIGH_RISK_OVERRIDES)
    return replace(_BALANCED_DEFAULT_CONFIG, risk_level=normalized)


def from_env() -> FilterConfig:
    """Load filter config from environment variables (ARCHOLITH_RTK_FILTER_*)."""
    risk_level = normalize_risk_level(os.environ.get("ARCHOLITH_RTK_FILTER_RISK_LEVEL"))
    base = base_config_for_risk_level(risk_level)
    return FilterConfig(
        risk_level=risk_level,
        generic_head=_env_int("ARCHOLITH_RTK_FILTER_GENERIC_HEAD", base.generic_head, _MAX_LINE_LINES),
        generic_tail=_env_int("ARCHOLITH_RTK_FILTER_GENERIC_TAIL", base.generic_tail, _MAX_LINE_LINES),
        test_head=_env_int("ARCHOLITH_RTK_FILTER_TEST_HEAD", base.test_head, _MAX_LINE_LINES),
        test_tail=_env_int("ARCHOLITH_RTK_FILTER_TEST_TAIL", base.test_tail, _MAX_LINE_LINES),
        build_head=_env_int("ARCHOLITH_RTK_FILTER_BUILD_HEAD", base.build_head, _MAX_LINE_LINES),
        build_tail=_env_int("ARCHOLITH_RTK_FILTER_BUILD_TAIL", base.build_tail, _MAX_LINE_LINES),
        lint_head=_env_int("ARCHOLITH_RTK_FILTER_LINT_HEAD", base.lint_head, _MAX_LINE_LINES),
        lint_tail=_env_int("ARCHOLITH_RTK_FILTER_LINT_TAIL", base.lint_tail, _MAX_LINE_LINES),
        typecheck_head=_env_int("ARCHOLITH_RTK_FILTER_TYPECHECK_HEAD", base.typecheck_head, _MAX_LINE_LINES),
        typecheck_tail=_env_int("ARCHOLITH_RTK_FILTER_TYPECHECK_TAIL", base.typecheck_tail, _MAX_LINE_LINES),
        git_diff_file_head=_env_int(
            "ARCHOLITH_RTK_FILTER_GIT_DIFF_FILE_HEAD", base.git_diff_file_head, _MAX_LINE_LINES
        ),
        git_diff_tail=_env_int("ARCHOLITH_RTK_FILTER_GIT_DIFF_TAIL", base.git_diff_tail, _MAX_LINE_LINES),
        git_log_head=_env_int("ARCHOLITH_RTK_FILTER_GIT_LOG_HEAD", base.git_log_head, _MAX_LINE_LINES),
        git_log_tail=_env_int("ARCHOLITH_RTK_FILTER_GIT_LOG_TAIL", base.git_log_tail, _MAX_LINE_LINES),
        git_status_head=_env_int("ARCHOLITH_RTK_FILTER_GIT_STATUS_HEAD", base.git_status_head, _MAX_LINE_LINES),
        git_status_tail=_env_int("ARCHOLITH_RTK_FILTER_GIT_STATUS_TAIL", base.git_status_tail, _MAX_LINE_LINES),
        log_head=_env_int("ARCHOLITH_RTK_FILTER_LOG_HEAD", base.log_head, _MAX_LINE_LINES),
        log_tail=_env_int("ARCHOLITH_RTK_FILTER_LOG_TAIL", base.log_tail, _MAX_LINE_LINES),
        log_max_consecutive_dupes=_env_int(
            "ARCHOLITH_RTK_FILTER_LOG_MAX_DUPE", base.log_max_consecutive_dupes, _MAX_LINE_LINES
        ),
        fs_max_entries=_env_int("ARCHOLITH_RTK_FILTER_FS_MAX_ENTRIES", base.fs_max_entries, _MAX_ENTRIES),
        fs_head_lines=_env_int("ARCHOLITH_RTK_FILTER_FS_HEAD", base.fs_head_lines, _MAX_LINE_LINES),
        fs_tail_lines=_env_int("ARCHOLITH_RTK_FILTER_FS_TAIL", base.fs_tail_lines, _MAX_LINE_LINES),
        search_max_matches_per_file=_env_int(
            "ARCHOLITH_RTK_FILTER_SEARCH_MAX_MATCHES", base.search_max_matches_per_file, _MAX_ENTRIES
        ),
        search_max_files=_env_int("ARCHOLITH_RTK_FILTER_SEARCH_MAX_FILES", base.search_max_files, _MAX_ENTRIES),
        search_head_lines=_env_int("ARCHOLITH_RTK_FILTER_SEARCH_HEAD", base.search_head_lines, _MAX_LINE_LINES),
        search_tail_lines=_env_int("ARCHOLITH_RTK_FILTER_SEARCH_TAIL", base.search_tail_lines, _MAX_LINE_LINES),
        json_max_keys_per_object=_env_int(
            "ARCHOLITH_RTK_FILTER_JSON_MAX_KEYS", base.json_max_keys_per_object, _MAX_ENTRIES
        ),
        json_max_array_items=_env_int(
            "ARCHOLITH_RTK_FILTER_JSON_MAX_ARRAY", base.json_max_array_items, _MAX_ENTRIES
        ),
        json_max_depth=_env_int("ARCHOLITH_RTK_FILTER_JSON_MAX_DEPTH", base.json_max_depth, _MAX_DEPTH),
        json_max_value_length=_env_int(
            "ARCHOLITH_RTK_FILTER_JSON_MAX_VALUE_LEN", base.json_max_value_length, _MAX_VALUE_LENGTH
        ),
        read_import_collapse=_env_int(
            "ARCHOLITH_RTK_FILTER_READ_IMPORTS_COLLAPSE", 1 if base.read_import_collapse else 0, 1
        ) == 1,
        read_blank_line_max=_env_int("ARCHOLITH_RTK_FILTER_READ_BLANK_LINE_MAX", base.read_blank_line_max, 10),
        read_comment_threshold=_env_int(
            "ARCHOLITH_RTK_FILTER_READ_COMMENT_THRESHOLD", base.read_comment_threshold, 50
        ),
        read_css_rule_collapse=_env_int(
            "ARCHOLITH_RTK_FILTER_READ_CSS_RULE_COLLAPSE", 1 if base.read_css_rule_collapse else 0, 1
        ) == 1,
        read_generated_min_line_len=_env_int(
            "ARCHOLITH_RTK_FILTER_READ_GENERATED_MIN_LINE_LEN", base.read_generated_min_line_len, 5000
        ),
        read_generated_min_run=_env_int(
            "ARCHOLITH_RTK_FILTER_READ_GENERATED_MIN_RUN", base.read_generated_min_run, 50
        ),
        read_literal_threshold=_env_int(
            "ARCHOLITH_RTK_FILTER_READ_LITERAL_THRESHOLD", base.read_literal_threshold, 100
        ),
    )


def boost_for_verbose(cfg: FilterConfig) -> FilterConfig:
    """Boost head/tail/entry limits for verbose output; re-clamps to MAX constants."""
    m = _VERBOSE_MULTIPLIER
    return replace(
        cfg,
        generic_head=min(cfg.generic_head * m, _MAX_LINE_LINES),
        generic_tail=min(cfg.generic_tail * m, _MAX_LINE_LINES),
        test_head=min(cfg.test_head * m, _MAX_LINE_LINES),
        test_tail=min(cfg.test_tail * m, _MAX_LINE_LINES),
        build_head=min(cfg.build_head * m, _MAX_LINE_LINES),
        build_tail=min(cfg.build_tail * m, _MAX_LINE_LINES),
        lint_head=min(cfg.lint_head * m, _MAX_LINE_LINES),
        lint_tail=min(cfg.lint_tail * m, _MAX_LINE_LINES),
        typecheck_head=min(cfg.typecheck_head * m, _MAX_LINE_LINES),
        typecheck_tail=min(cfg.typecheck_tail * m, _MAX_LINE_LINES),
        git_diff_file_head=min(cfg.git_diff_file_head * m, _MAX_LINE_LINES),
        git_diff_tail=min(cfg.git_diff_tail * m, _MAX_LINE_LINES),
        git_log_head=min(cfg.git_log_head * m, _MAX_LINE_LINES),
        git_log_tail=min(cfg.git_log_tail * m, _MAX_LINE_LINES),
        git_status_head=min(cfg.git_status_head * m, _MAX_LINE_LINES),
        git_status_tail=min(cfg.git_status_tail * m, _MAX_LINE_LINES),
        log_head=min(cfg.log_head * m, _MAX_LINE_LINES),
        log_tail=min(cfg.log_tail * m, _MAX_LINE_LINES),
        fs_max_entries=min(cfg.fs_max_entries * m, _MAX_ENTRIES),
        fs_head_lines=min(cfg.fs_head_lines * m, _MAX_LINE_LINES),
        fs_tail_lines=min(cfg.fs_tail_lines * m, _MAX_LINE_LINES),
        search_max_matches_per_file=min(cfg.search_max_matches_per_file * m, _MAX_ENTRIES),
        search_max_files=min(cfg.search_max_files * m, _MAX_ENTRIES),
        search_head_lines=min(cfg.search_head_lines * m, _MAX_LINE_LINES),
        search_tail_lines=min(cfg.search_tail_lines * m, _MAX_LINE_LINES),
        json_max_keys_per_object=min(cfg.json_max_keys_per_object * m, _MAX_ENTRIES),
        json_max_array_items=min(cfg.json_max_array_items * m, _MAX_ENTRIES),
    )


def is_filter_enabled() -> bool:
    """Check if filtering is enabled. Env var ARCHOLITH_RTK_FILTERS=off overrides."""
    env = os.environ.get("ARCHOLITH_RTK_FILTERS", "")
    if env.lower() in ("off", "false", "0"):
        return False
    return True


def is_verbose_command(command: str) -> bool:
    """Detect verbose/debug flags in a command string.

    Delegates to the shared implementation in ``_patterns`` to avoid
    recompiling regex on every call.
    """
    from ._patterns import is_verbose_command as _impl

    return _impl(command)
