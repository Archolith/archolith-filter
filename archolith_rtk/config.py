"""Filter configuration — env-var driven with sane defaults and clamped bounds."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace


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


@dataclass(frozen=True)
class FilterConfig:
    """Per-category head/tail line counts, configurable via env vars."""

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
    git_diff_file_head: int = 15
    git_diff_tail: int = 20
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


# Upper bounds to prevent env-var typos from disabling filtering or causing OOM.
_MAX_LINE_LINES = 500
_MAX_ENTRIES = 1000
_MAX_DEPTH = 10
_MAX_VALUE_LENGTH = 10_000

_VERBOSE_MULTIPLIER = 2


def from_env() -> FilterConfig:
    """Load filter config from environment variables (ARCHOLITH_RTK_FILTER_*)."""
    return FilterConfig(
        generic_head=_env_int("ARCHOLITH_RTK_FILTER_GENERIC_HEAD", 20, _MAX_LINE_LINES),
        generic_tail=_env_int("ARCHOLITH_RTK_FILTER_GENERIC_TAIL", 30, _MAX_LINE_LINES),
        test_head=_env_int("ARCHOLITH_RTK_FILTER_TEST_HEAD", 10, _MAX_LINE_LINES),
        test_tail=_env_int("ARCHOLITH_RTK_FILTER_TEST_TAIL", 40, _MAX_LINE_LINES),
        build_head=_env_int("ARCHOLITH_RTK_FILTER_BUILD_HEAD", 15, _MAX_LINE_LINES),
        build_tail=_env_int("ARCHOLITH_RTK_FILTER_BUILD_TAIL", 25, _MAX_LINE_LINES),
        lint_head=_env_int("ARCHOLITH_RTK_FILTER_LINT_HEAD", 15, _MAX_LINE_LINES),
        lint_tail=_env_int("ARCHOLITH_RTK_FILTER_LINT_TAIL", 30, _MAX_LINE_LINES),
        typecheck_head=_env_int("ARCHOLITH_RTK_FILTER_TYPECHECK_HEAD", 15, _MAX_LINE_LINES),
        typecheck_tail=_env_int("ARCHOLITH_RTK_FILTER_TYPECHECK_TAIL", 30, _MAX_LINE_LINES),
        git_diff_file_head=_env_int("ARCHOLITH_RTK_FILTER_GIT_DIFF_FILE_HEAD", 15, _MAX_LINE_LINES),
        git_diff_tail=_env_int("ARCHOLITH_RTK_FILTER_GIT_DIFF_TAIL", 20, _MAX_LINE_LINES),
        git_log_head=_env_int("ARCHOLITH_RTK_FILTER_GIT_LOG_HEAD", 25, _MAX_LINE_LINES),
        git_log_tail=_env_int("ARCHOLITH_RTK_FILTER_GIT_LOG_TAIL", 15, _MAX_LINE_LINES),
        git_status_head=_env_int("ARCHOLITH_RTK_FILTER_GIT_STATUS_HEAD", 50, _MAX_LINE_LINES),
        git_status_tail=_env_int("ARCHOLITH_RTK_FILTER_GIT_STATUS_TAIL", 30, _MAX_LINE_LINES),
        log_head=_env_int("ARCHOLITH_RTK_FILTER_LOG_HEAD", 15, _MAX_LINE_LINES),
        log_tail=_env_int("ARCHOLITH_RTK_FILTER_LOG_TAIL", 30, _MAX_LINE_LINES),
        log_max_consecutive_dupes=_env_int("ARCHOLITH_RTK_FILTER_LOG_MAX_DUPE", 3, _MAX_LINE_LINES),
        fs_max_entries=_env_int("ARCHOLITH_RTK_FILTER_FS_MAX_ENTRIES", 50, _MAX_ENTRIES),
        fs_head_lines=_env_int("ARCHOLITH_RTK_FILTER_FS_HEAD", 20, _MAX_LINE_LINES),
        fs_tail_lines=_env_int("ARCHOLITH_RTK_FILTER_FS_TAIL", 30, _MAX_LINE_LINES),
        search_max_matches_per_file=_env_int(
            "ARCHOLITH_RTK_FILTER_SEARCH_MAX_MATCHES", 5, _MAX_ENTRIES
        ),
        search_max_files=_env_int("ARCHOLITH_RTK_FILTER_SEARCH_MAX_FILES", 15, _MAX_ENTRIES),
        search_head_lines=_env_int("ARCHOLITH_RTK_FILTER_SEARCH_HEAD", 20, _MAX_LINE_LINES),
        search_tail_lines=_env_int("ARCHOLITH_RTK_FILTER_SEARCH_TAIL", 30, _MAX_LINE_LINES),
        json_max_keys_per_object=_env_int("ARCHOLITH_RTK_FILTER_JSON_MAX_KEYS", 10, _MAX_ENTRIES),
        json_max_array_items=_env_int("ARCHOLITH_RTK_FILTER_JSON_MAX_ARRAY", 5, _MAX_ENTRIES),
        json_max_depth=_env_int("ARCHOLITH_RTK_FILTER_JSON_MAX_DEPTH", 3, _MAX_DEPTH),
        json_max_value_length=_env_int("ARCHOLITH_RTK_FILTER_JSON_MAX_VALUE_LEN", 80, _MAX_VALUE_LENGTH),
        read_import_collapse=_env_int("ARCHOLITH_RTK_FILTER_READ_IMPORTS_COLLAPSE", 1, 1) == 1,
        read_blank_line_max=_env_int("ARCHOLITH_RTK_FILTER_READ_BLANK_LINE_MAX", 1, 10),
        read_comment_threshold=_env_int("ARCHOLITH_RTK_FILTER_READ_COMMENT_THRESHOLD", 10, 50),
        read_css_rule_collapse=_env_int("ARCHOLITH_RTK_FILTER_READ_CSS_RULE_COLLAPSE", 1, 1) == 1,
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
    """Detect verbose/debug flags in a command string."""
    import re

    verbose_flags = [
        r"(?:^|\s)--verbose\b",
        r"(?:^|\s)-verbose\b",
        r"(?:^|\s)-v{2,}\b",  # -vv, -vvv
        r"(?:^|\s)--debug\b",
        r"(?:^|\s)--full\b",
        r"(?:^|\s)--detailed\b",
        r"(?:^|\s)--show-all\b",
        r"(?:^|\s)--no-summary\b",
    ]
    return any(re.search(p, command) for p in verbose_flags)
