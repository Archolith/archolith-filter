"""Filter configuration — env-var driven with sane defaults and clamped bounds."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace
from enum import StrEnum

from ._patterns import is_verbose_command  # noqa: F401 — re-exported for backward compat


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


def _env_float(name: str, fallback: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Read a float env var, returning the default if missing or invalid.

    Clamps to [min_val, max_val].
    """
    raw = os.environ.get(name, "")
    if not raw:
        return fallback
    try:
        n = float(raw)
    except ValueError:
        return fallback
    return max(min_val, min(max_val, n))


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
    # JSON format-switch knobs (Strategies 1-4)
    json_csv_enabled: bool = True
    json_csv_min_rows: int = 3
    json_csv_max_rows: int = 20
    json_csv_max_key_length: int = 40
    json_kv_enabled: bool = True
    json_kv_min_keys: int = 3
    json_kv_max_keys: int = 20
    json_dotkey_enabled: bool = True
    json_dotkey_max_keys: int = 30
    json_dotkey_max_depth: int = 3
    json_csv_factor_enabled: bool = True
    json_csv_factor_threshold: float = 0.8
    json_csv_factor_max_columns: int = 3
    # Strategy 5: stack trace collapsing
    generic_stack_collapse_enabled: bool = True
    generic_stack_collapse_min_frames: int = 5
    generic_stack_collapse_keep_app_frames: int = 2
    # Strategy 6: git status prefix grouping
    git_status_group_enabled: bool = True
    git_status_group_max_per_line: int = 10
    # Strategy 7: search heading reformat
    search_heading_reformat_enabled: bool = True
    # Strategy 8: build task summary
    build_summary_enabled: bool = True
    # Strategy 9: ls -la abbreviation
    fs_lsl_abbreviate_enabled: bool = True
    # ─── Layer 0: Pre-filter pipeline ──────────────────────────────────
    # Secret redaction (redact.py)
    redact_enabled: bool = True
    # Thinking block stripping (strip_thinking.py)
    strip_thinking_enabled: bool = True
    # Path normalization (paths.py)
    normalize_paths_enabled: bool = True
    # Binary detection (inline in filter_output)
    binary_detection_enabled: bool = True
    # Oversized input guard (inline in filter_output, chars)
    oversized_guard_enabled: bool = True
    oversized_max_chars: int = 500_000
    # Runtime noise normalization in log/build/test filters
    normalize_noise_enabled: bool = True
    # Table whitespace minimization in fs_listing
    table_whitespace_min_enabled: bool = True
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

_LOW_RISK_OVERRIDES: dict[str, int | bool | float] = {
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
    "json_csv_max_rows": 30,
    "json_csv_max_key_length": 60,
    "json_kv_max_keys": 30,
    "json_dotkey_max_keys": 40,
    "json_dotkey_max_depth": 4,
    "generic_stack_collapse_min_frames": 5,
    "generic_stack_collapse_keep_app_frames": 3,
    "git_status_group_max_per_line": 15,
}

_HIGH_RISK_OVERRIDES: dict[str, int | bool | float] = {
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
    "json_csv_max_rows": 10,
    "json_csv_max_key_length": 20,
    "json_kv_max_keys": 15,
    "json_dotkey_max_keys": 20,
    "json_dotkey_max_depth": 2,
    "generic_stack_collapse_min_frames": 3,
    "generic_stack_collapse_keep_app_frames": 1,
    "git_status_group_max_per_line": 5,
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


@dataclass(frozen=True)
class _EnvBinding:
    """How one FilterConfig field is read from the environment."""

    env: str
    kind: str  # "int" | "bool" | "float"
    bounds: tuple[float, ...]


# Single declaration point for each field's env var and clamp bounds. from_env()
# walks dataclasses.fields(FilterConfig) and applies these, so a field's name,
# env var, and bounds are each written once. test_config_env_bindings_cover_all_fields
# fails if a new field is added without a binding here.
_ENV_BINDINGS: dict[str, _EnvBinding] = {
    "generic_head": _EnvBinding("ARCHOLITH_FILTER_GENERIC_HEAD", "int", (_MAX_LINE_LINES,)),
    "generic_tail": _EnvBinding("ARCHOLITH_FILTER_GENERIC_TAIL", "int", (_MAX_LINE_LINES,)),
    "test_head": _EnvBinding("ARCHOLITH_FILTER_TEST_HEAD", "int", (_MAX_LINE_LINES,)),
    "test_tail": _EnvBinding("ARCHOLITH_FILTER_TEST_TAIL", "int", (_MAX_LINE_LINES,)),
    "build_head": _EnvBinding("ARCHOLITH_FILTER_BUILD_HEAD", "int", (_MAX_LINE_LINES,)),
    "build_tail": _EnvBinding("ARCHOLITH_FILTER_BUILD_TAIL", "int", (_MAX_LINE_LINES,)),
    "lint_head": _EnvBinding("ARCHOLITH_FILTER_LINT_HEAD", "int", (_MAX_LINE_LINES,)),
    "lint_tail": _EnvBinding("ARCHOLITH_FILTER_LINT_TAIL", "int", (_MAX_LINE_LINES,)),
    "typecheck_head": _EnvBinding("ARCHOLITH_FILTER_TYPECHECK_HEAD", "int", (_MAX_LINE_LINES,)),
    "typecheck_tail": _EnvBinding("ARCHOLITH_FILTER_TYPECHECK_TAIL", "int", (_MAX_LINE_LINES,)),
    "git_diff_file_head": _EnvBinding("ARCHOLITH_FILTER_GIT_DIFF_FILE_HEAD", "int", (_MAX_LINE_LINES,)),
    "git_diff_tail": _EnvBinding("ARCHOLITH_FILTER_GIT_DIFF_TAIL", "int", (_MAX_LINE_LINES,)),
    "git_log_head": _EnvBinding("ARCHOLITH_FILTER_GIT_LOG_HEAD", "int", (_MAX_LINE_LINES,)),
    "git_log_tail": _EnvBinding("ARCHOLITH_FILTER_GIT_LOG_TAIL", "int", (_MAX_LINE_LINES,)),
    "git_status_head": _EnvBinding("ARCHOLITH_FILTER_GIT_STATUS_HEAD", "int", (_MAX_LINE_LINES,)),
    "git_status_tail": _EnvBinding("ARCHOLITH_FILTER_GIT_STATUS_TAIL", "int", (_MAX_LINE_LINES,)),
    "log_head": _EnvBinding("ARCHOLITH_FILTER_LOG_HEAD", "int", (_MAX_LINE_LINES,)),
    "log_tail": _EnvBinding("ARCHOLITH_FILTER_LOG_TAIL", "int", (_MAX_LINE_LINES,)),
    "log_max_consecutive_dupes": _EnvBinding("ARCHOLITH_FILTER_LOG_MAX_DUPE", "int", (_MAX_LINE_LINES,)),
    "fs_max_entries": _EnvBinding("ARCHOLITH_FILTER_FS_MAX_ENTRIES", "int", (_MAX_ENTRIES,)),
    "fs_head_lines": _EnvBinding("ARCHOLITH_FILTER_FS_HEAD", "int", (_MAX_LINE_LINES,)),
    "fs_tail_lines": _EnvBinding("ARCHOLITH_FILTER_FS_TAIL", "int", (_MAX_LINE_LINES,)),
    "search_max_matches_per_file": _EnvBinding("ARCHOLITH_FILTER_SEARCH_MAX_MATCHES", "int", (_MAX_ENTRIES,)),
    "search_max_files": _EnvBinding("ARCHOLITH_FILTER_SEARCH_MAX_FILES", "int", (_MAX_ENTRIES,)),
    "search_head_lines": _EnvBinding("ARCHOLITH_FILTER_SEARCH_HEAD", "int", (_MAX_LINE_LINES,)),
    "search_tail_lines": _EnvBinding("ARCHOLITH_FILTER_SEARCH_TAIL", "int", (_MAX_LINE_LINES,)),
    "json_max_keys_per_object": _EnvBinding("ARCHOLITH_FILTER_JSON_MAX_KEYS", "int", (_MAX_ENTRIES,)),
    "json_max_array_items": _EnvBinding("ARCHOLITH_FILTER_JSON_MAX_ARRAY", "int", (_MAX_ENTRIES,)),
    "json_max_depth": _EnvBinding("ARCHOLITH_FILTER_JSON_MAX_DEPTH", "int", (_MAX_DEPTH,)),
    "json_max_value_length": _EnvBinding("ARCHOLITH_FILTER_JSON_MAX_VALUE_LEN", "int", (_MAX_VALUE_LENGTH,)),
    "json_csv_enabled": _EnvBinding("ARCHOLITH_FILTER_JSON_CSV_ENABLED", "bool", (1,)),
    "json_csv_min_rows": _EnvBinding("ARCHOLITH_FILTER_JSON_CSV_MIN_ROWS", "int", (_MAX_ENTRIES,)),
    "json_csv_max_rows": _EnvBinding("ARCHOLITH_FILTER_JSON_CSV_MAX_ROWS", "int", (_MAX_ENTRIES,)),
    "json_csv_max_key_length": _EnvBinding("ARCHOLITH_FILTER_JSON_CSV_MAX_KEY_LEN", "int", (_MAX_VALUE_LENGTH,)),
    "json_kv_enabled": _EnvBinding("ARCHOLITH_FILTER_JSON_KV_ENABLED", "bool", (1,)),
    "json_kv_min_keys": _EnvBinding("ARCHOLITH_FILTER_JSON_KV_MIN_KEYS", "int", (_MAX_ENTRIES,)),
    "json_kv_max_keys": _EnvBinding("ARCHOLITH_FILTER_JSON_KV_MAX_KEYS", "int", (_MAX_ENTRIES,)),
    "json_dotkey_enabled": _EnvBinding("ARCHOLITH_FILTER_JSON_DOTKEY_ENABLED", "bool", (1,)),
    "json_dotkey_max_keys": _EnvBinding("ARCHOLITH_FILTER_JSON_DOTKEY_MAX_KEYS", "int", (_MAX_ENTRIES,)),
    "json_dotkey_max_depth": _EnvBinding("ARCHOLITH_FILTER_JSON_DOTKEY_MAX_DEPTH", "int", (_MAX_DEPTH,)),
    "json_csv_factor_enabled": _EnvBinding("ARCHOLITH_FILTER_JSON_CSV_FACTOR_ENABLED", "bool", (1,)),
    "json_csv_factor_threshold": _EnvBinding("ARCHOLITH_FILTER_JSON_CSV_FACTOR_THRESHOLD", "float", (0.0, 1.0,)),
    "json_csv_factor_max_columns": _EnvBinding("ARCHOLITH_FILTER_JSON_CSV_FACTOR_MAX_COLS", "int", (10,)),
    "generic_stack_collapse_enabled": _EnvBinding("ARCHOLITH_FILTER_GENERIC_STACK_COLLAPSE_ENABLED", "bool", (1,)),
    "generic_stack_collapse_min_frames": _EnvBinding(
        "ARCHOLITH_FILTER_GENERIC_STACK_COLLAPSE_MIN_FRAMES",
        "int",
        (_MAX_LINE_LINES,),
    ),
    "generic_stack_collapse_keep_app_frames": _EnvBinding(
        "ARCHOLITH_FILTER_GENERIC_STACK_COLLAPSE_KEEP_APP",
        "int",
        (_MAX_LINE_LINES,),
    ),
    "git_status_group_enabled": _EnvBinding("ARCHOLITH_FILTER_GIT_STATUS_GROUP_ENABLED", "bool", (1,)),
    "git_status_group_max_per_line": _EnvBinding("ARCHOLITH_FILTER_GIT_STATUS_GROUP_MAX", "int", (_MAX_ENTRIES,)),
    "search_heading_reformat_enabled": _EnvBinding("ARCHOLITH_FILTER_SEARCH_HEADING_REFORMAT_ENABLED", "bool", (1,)),
    "build_summary_enabled": _EnvBinding("ARCHOLITH_FILTER_BUILD_SUMMARY_ENABLED", "bool", (1,)),
    "fs_lsl_abbreviate_enabled": _EnvBinding("ARCHOLITH_FILTER_FS_LSL_ABBREVIATE_ENABLED", "bool", (1,)),
    "redact_enabled": _EnvBinding("ARCHOLITH_FILTER_REDACT_ENABLED", "bool", (1,)),
    "strip_thinking_enabled": _EnvBinding("ARCHOLITH_FILTER_STRIP_THINKING_ENABLED", "bool", (1,)),
    "normalize_paths_enabled": _EnvBinding("ARCHOLITH_FILTER_NORMALIZE_PATHS_ENABLED", "bool", (1,)),
    "binary_detection_enabled": _EnvBinding("ARCHOLITH_FILTER_BINARY_DETECTION_ENABLED", "bool", (1,)),
    "oversized_guard_enabled": _EnvBinding("ARCHOLITH_FILTER_OVERSIZED_GUARD_ENABLED", "bool", (1,)),
    "oversized_max_chars": _EnvBinding("ARCHOLITH_FILTER_OVERSIZED_MAX_CHARS", "int", (10000000,)),
    "normalize_noise_enabled": _EnvBinding("ARCHOLITH_FILTER_NORMALIZE_NOISE_ENABLED", "bool", (1,)),
    "table_whitespace_min_enabled": _EnvBinding("ARCHOLITH_FILTER_TABLE_WHITESPACE_MIN_ENABLED", "bool", (1,)),
    "read_import_collapse": _EnvBinding("ARCHOLITH_FILTER_READ_IMPORTS_COLLAPSE", "bool", (1,)),
    "read_blank_line_max": _EnvBinding("ARCHOLITH_FILTER_READ_BLANK_LINE_MAX", "int", (10,)),
    "read_comment_threshold": _EnvBinding("ARCHOLITH_FILTER_READ_COMMENT_THRESHOLD", "int", (50,)),
    "read_css_rule_collapse": _EnvBinding("ARCHOLITH_FILTER_READ_CSS_RULE_COLLAPSE", "bool", (1,)),
    "read_generated_min_line_len": _EnvBinding("ARCHOLITH_FILTER_READ_GENERATED_MIN_LINE_LEN", "int", (5000,)),
    "read_generated_min_run": _EnvBinding("ARCHOLITH_FILTER_READ_GENERATED_MIN_RUN", "int", (50,)),
    "read_literal_threshold": _EnvBinding("ARCHOLITH_FILTER_READ_LITERAL_THRESHOLD", "int", (100,)),
}


def from_env() -> FilterConfig:
    """Load filter config from environment variables (ARCHOLITH_FILTER_*)."""
    risk_level = normalize_risk_level(os.environ.get("ARCHOLITH_FILTER_RISK_LEVEL"))
    base = base_config_for_risk_level(risk_level)

    values: dict[str, object] = {"risk_level": risk_level}
    for f in fields(FilterConfig):
        if f.name == "risk_level":
            continue
        binding = _ENV_BINDINGS[f.name]
        default = getattr(base, f.name)
        if binding.kind == "bool":
            values[f.name] = _env_int(binding.env, 1 if default else 0, *binding.bounds) == 1
        elif binding.kind == "float":
            values[f.name] = _env_float(binding.env, default, *binding.bounds)
        else:
            values[f.name] = _env_int(binding.env, default, *binding.bounds)
    return FilterConfig(**values)



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
        json_csv_max_rows=min(cfg.json_csv_max_rows * m, _MAX_ENTRIES),
        json_kv_max_keys=min(cfg.json_kv_max_keys * m, _MAX_ENTRIES),
        json_dotkey_max_keys=min(cfg.json_dotkey_max_keys * m, _MAX_ENTRIES),
    )


def is_filter_enabled() -> bool:
    """Check if filtering is enabled. Env var ARCHOLITH_FILTERS=off overrides."""
    env = os.environ.get("ARCHOLITH_FILTERS", "")
    if env.lower() in ("off", "false", "0"):
        return False
    return True
