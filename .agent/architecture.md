# archolith-rtk — Architecture

## Overview

archolith-rtk is a deterministic Token Reduction Toolkit for LLM agent contexts. It compresses tool output and truncates oversized conversation messages without requiring LLM calls.

The library is organized as two sequential layers:

1. **Layer 1 — Output Filters**: Compress tool results before they enter the model context. 13 shell-command categories plus tool-routed `read_file` compression decide which filter strategy to apply.
2. **Layer 2 — Shrink**: Truncate oversized tool-role messages in conversation history. Supports both char-based and token-based budgets.

Both layers are deterministic by default.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Packaging | hatchling (pyproject.toml) |
| Optional tokenizer | tiktoken (cl100k_base encoding) |
| Testing | pytest + pytest-cov |
| Linting | ruff |
| Typing | py.typed marker, fully typed public API |

## Data Flow

```
Tool output text
       │
       ▼
  filter_output()          ← Layer 1
  ├── strip_ansi()
  ├── classify_command()   →  CommandCategory
  ├── _category_filter()   →  category-specific FilterResult
  ├── raw_store.store()    →  recovery ID appended to output
  └── record_filter_telemetry()
       │
       ▼
  shrink_messages()        ← Layer 2
  ├── count_tokens()       →  tiktoken or heuristic
  ├── truncate_for_chars() / truncate_for_tokens()
  └── ShrinkCharsResult / ShrinkTokensResult
```

## Key Components

### Layer 1 — classifier.py

`classify_command(command: str) -> ClassifiedCommand` maps shell command strings to one of 13 `CommandCategory` values. Handles runner prefixes (npm/pnpm/yarn/deno), git subcommands, and tool-specific heuristics.

### Layer 1 — filters/

13 category-specific filter modules, each exposing a filter function and an options dataclass:

| Module | Category | Strategy |
|--------|----------|----------|
| `git_diff.py` | git-diff | Stat/diff split, per-file section compression |
| `git_log.py` | git-log | Oneline detection + head/tail commit windowing |
| `git_status.py` | git-status | Short-format pass-through |
| `git_show.py` | git-show | Commit header preserved, diff body compressed |
| `test_run_output.py` | test | Tail summary prioritized over verbose per-test output |
| `build_output.py` | build | Generic head+tail with build defaults |
| `lint_output.py` | lint | Generic head+tail with lint defaults |
| `typecheck_output.py` | typecheck | Generic head+tail with typecheck defaults |
| `fs_listing.py` | ls-tree | Important-file preservation, tree-style detection |
| `search.py` | search | File grouping, per-file match capping |
| `json_output.py` | json | Recursive value compression, depth/key/array capping |
| `logs.py` | logs | Duplicate-run collapse, important-line preservation |
| `generic.py` | generic | Head+tail windowing, blank collapse, header extraction |
| `read_file.py` | read_file | Structure-aware file-content compression for imports, comments, CSS, literals, and generated blobs |

### Layer 1 — config.py

`FilterConfig` dataclass with all per-category thresholds plus a `risk_level`
preset selector. Loaded from `ARCHOLITH_RTK_FILTER_*` env vars via
`from_env()`. `base_config_for_risk_level()` returns programmatic presets for
`low`, `balanced`, and `high` risk. Explicit env-var overrides are applied on
top of the selected preset. `boost_for_verbose()` doubles head/tail limits for
verbose commands. Upper bounds prevent typos from disabling filtering.

### Layer 2 — shrink/ package

`shrink_messages()` is the main entry point (compatibility wrapper for dict or ChatMessage lists). Internally routes to `shrink_oversized_tool_results()` (char-based) or `shrink_oversized_tool_results_by_tokens()` (token-based). Also exposes `shrink_oversized_tool_call_args_by_tokens()` for long JSON strings in tool_call arguments.

The shrink subsystem is organized into focused submodules with a strict import DAG:

| Module | Responsibility |
|--------|---------------|
| `models.py` | Frozen dataclasses: ChatMessage, ToolCall, ToolCallFunction, ShrinkCharsResult, ShrinkTokensResult |
| `token_counter.py` | `count_tokens()` — tiktoken `cl100k_base` if available, else ÷4 heuristic |
| `truncate.py` | `truncate_for_chars()` (head + 10% tail), `truncate_for_tokens()` (iterative convergence) |
| `read_file_truncate.py` | Declaration-preserving char and token truncation for `read_file` tool output |
| `json_shrink.py` | `shrink_json_long_strings()` — collapse long string values in tool_call arguments |
| `orchestrator.py` | Public API: `shrink_oversized_tool_results*`, `shrink_messages`, `estimate_*` |
| `__init__.py` | Re-exports all public symbols from submodules |

### Supporting modules

- **_patterns.py**: Single source of truth for shared regex patterns (import/comment/declaration detection, verbose flag patterns) used by `filters/read_file.py`, `shrink/read_file_truncate.py`, `config.py`, and `filter_meta.py`.
- **raw_store.py**: LRU store (200 entries, 256K chars cap) for recovering original pre-filter text by ID. Module-level singleton.
- **telemetry.py**: Session-scoped `FilterTelemetryStore` tracking per-call and aggregate token savings. `format_summary()` for human-readable output.
- **strip_ansi.py**: Regex-based ANSI escape stripping (CSI, OSC, 8-bit CSI, misc ESC).
- **strip_thinking.py**: Strips model-internal reasoning tags (`<thinking>`, `<antThinking>`, etc.) from tool output.
- **redact.py**: Secret redaction — strips API keys, tokens, credentials, and connection strings using compiled alternation regex.
- **normalize.py**: Runtime noise normalization — replaces timestamps, PIDs, elapsed times, memory sizes with stable placeholders for prompt caching.
- **paths.py**: Workspace path normalization — replaces absolute paths with project-relative equivalents, normalizes separators.
- **filter_meta.py**: `FilterMeta` dataclass and `parse_result_meta()` for extracting exit codes from formatted output headers.

## Configuration / Environment Variables

All env vars use the prefix `ARCHOLITH_RTK_FILTER_`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `ARCHOLITH_RTK_FILTERS` | Set to `off`/`false`/`0` to disable all filtering | enabled |
| `ARCHOLITH_RTK_FILTER_RISK_LEVEL` | Preset compression posture: `low`, `balanced`, or `high` | `balanced` |
| `ARCHOLITH_RTK_FILTER_GENERIC_HEAD` | Generic head lines | 20 |
| `ARCHOLITH_RTK_FILTER_GENERIC_TAIL` | Generic tail lines | 30 |
| `ARCHOLITH_RTK_FILTER_TEST_HEAD` | Test head lines | 10 |
| `ARCHOLITH_RTK_FILTER_TEST_TAIL` | Test tail lines | 40 |
| `ARCHOLITH_RTK_FILTER_BUILD_HEAD` | Build head lines | 15 |
| `ARCHOLITH_RTK_FILTER_BUILD_TAIL` | Build tail lines | 25 |
| `ARCHOLITH_RTK_FILTER_LINT_HEAD` | Lint head lines | 15 |
| `ARCHOLITH_RTK_FILTER_LINT_TAIL` | Lint tail lines | 30 |
| `ARCHOLITH_RTK_FILTER_TYPECHECK_HEAD` | Typecheck head lines | 15 |
| `ARCHOLITH_RTK_FILTER_TYPECHECK_TAIL` | Typecheck tail lines | 30 |
| `ARCHOLITH_RTK_FILTER_GIT_DIFF_FILE_HEAD` | Lines per file in diff stat | 15 |
| `ARCHOLITH_RTK_FILTER_GIT_DIFF_TAIL` | Diff body tail lines | 20 |
| `ARCHOLITH_RTK_FILTER_GIT_LOG_HEAD` | Git log head commits | 25 |
| `ARCHOLITH_RTK_FILTER_GIT_LOG_TAIL` | Git log tail commits | 15 |
| `ARCHOLITH_RTK_FILTER_GIT_STATUS_HEAD` | Git status head lines | 50 |
| `ARCHOLITH_RTK_FILTER_GIT_STATUS_TAIL` | Git status tail lines | 30 |
| `ARCHOLITH_RTK_FILTER_LOG_HEAD` | Log head lines | 15 |
| `ARCHOLITH_RTK_FILTER_LOG_TAIL` | Log tail lines | 30 |
| `ARCHOLITH_RTK_FILTER_LOG_MAX_DUPE` | Max consecutive duplicate lines | 3 |
| `ARCHOLITH_RTK_FILTER_FS_MAX_ENTRIES` | Max filesystem entries | 50 |
| `ARCHOLITH_RTK_FILTER_FS_HEAD` | FS listing head lines | 20 |
| `ARCHOLITH_RTK_FILTER_FS_TAIL` | FS listing tail lines | 30 |
| `ARCHOLITH_RTK_FILTER_SEARCH_MAX_MATCHES` | Max matches per file | 5 |
| `ARCHOLITH_RTK_FILTER_SEARCH_MAX_FILES` | Max files in search results | 15 |
| `ARCHOLITH_RTK_FILTER_SEARCH_HEAD` | Search head lines | 20 |
| `ARCHOLITH_RTK_FILTER_SEARCH_TAIL` | Search tail lines | 30 |
| `ARCHOLITH_RTK_FILTER_JSON_MAX_KEYS` | Max keys per JSON object | 10 |
| `ARCHOLITH_RTK_FILTER_JSON_MAX_ARRAY` | Max JSON array items | 5 |
| `ARCHOLITH_RTK_FILTER_JSON_MAX_DEPTH` | Max JSON recursion depth | 3 |
| `ARCHOLITH_RTK_FILTER_JSON_MAX_VALUE_LEN` | Max JSON value length | 80 |
| `ARCHOLITH_RTK_FILTER_READ_IMPORTS_COLLAPSE` | Collapse large import blocks | 1 |
| `ARCHOLITH_RTK_FILTER_READ_BLANK_LINE_MAX` | Max consecutive blank lines kept in `read_file` output | 1 |
| `ARCHOLITH_RTK_FILTER_READ_COMMENT_THRESHOLD` | Comment-run collapse threshold for `read_file` output | 10 |
| `ARCHOLITH_RTK_FILTER_READ_CSS_RULE_COLLAPSE` | Collapse verbose CSS rule bodies | 1 |
| `ARCHOLITH_RTK_FILTER_READ_GENERATED_MIN_LINE_LEN` | Long-line threshold for generated/minified block collapse | 500 |
| `ARCHOLITH_RTK_FILTER_READ_GENERATED_MIN_RUN` | Consecutive long lines required before collapsing generated/minified blocks | 5 |
| `ARCHOLITH_RTK_FILTER_READ_LITERAL_THRESHOLD` | Collapse threshold for multiline strings and large literal blocks | 8 |

All numeric values are clamped to upper bounds (lines: 500, entries: 1000, depth: 10, value length: 10000).

Risk-level presets adjust multiple thresholds together:

- `low`: preserves more lines, files, keys, and tail context
- `balanced`: existing default behavior
- `high`: more aggressive compression for higher token savings

## External Dependencies

- **tiktoken** (optional): Provides accurate token counting for Layer 2 shrink. Without it, falls back to heuristic of ~4 chars/token. Install via `archolith-rtk[tokenizer]`.
- No other external dependencies — the library is zero-dependency by default.
