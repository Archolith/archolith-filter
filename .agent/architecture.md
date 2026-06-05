# archolith-filter — Architecture

## Overview

archolith-filter is a deterministic Token Reduction Toolkit for LLM agent contexts. It compresses tool output, truncates oversized conversation messages, and applies mechanical turn-level compression — all without requiring LLM calls.

The library is organized into three layers:

1. **Layer 1 — Output Filters**: Compress tool results before they enter the model context. 13 shell-command categories plus tool-routed `read_file` compression decide which filter strategy to apply. Nine format-switch strategies (CSV, key-value, dotted-key, column factoring, stack trace collapsing, git status grouping, search heading reformat, build task summary, ls -la abbreviation) provide denser representations when the data shape allows, falling back to truncation when format-switch output isn't shorter.
2. **Layer 2 — Shrink**: Truncate oversized tool-role messages in conversation history. Supports both char-based and token-based budgets.
3. **Layer 3 — Agent-Solo Turn Compression**: Four composable strategies (A-D) that reduce token footprint of tool-call continuation turns. These run on agent-solo turns (where the last message is a tool result, not a user message) and apply mechanical savings without an LLM call.

All layers are deterministic by default.

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
  filter_output()                    ← Layer 1
  ├── redact_secrets()               ← Layer 0: secret redaction
  ├── _is_binary_output()            ← Layer 0: binary detection (early return)
  ├── _oversized_guard()             ← Layer 0: oversized guard (early return)
  ├── strip_ansi()                   ← Layer 0: ANSI stripping
  ├── strip_thinking_blocks()        ← Layer 0: thinking block strip
  ├── normalize_paths()              ← Layer 0: path normalization
  ├── classify_command()             → CommandCategory
  ├── _category_filter()             → category-specific FilterResult
  │   ├── log_filter()               → normalize_runtime_noise() first
  │   ├── build_filter()             → normalize_runtime_noise() first
  │   ├── filter_test_output()       → normalize_runtime_noise() first
  │   └── fs_listing_filter()        → _minimize_table_whitespace() first
  ├── raw_store.store()              → recovery ID appended to output
  └── record_filter_telemetry()
       │
       ▼
  shrink_messages()                  ← Layer 2
  ├── count_tokens()                 → tiktoken or heuristic
  ├── truncate_for_chars() / truncate_for_tokens()
  └── ShrinkCharsResult / ShrinkTokensResult
       │
       ▼
  compress_agent_solo_turn()         ← Layer 3
  ├── _apply_compact_tool_args()     → D: compact Write/Edit arguments
  ├── _apply_filter_middle()         → C: filter_output() on middle section
  ├── _apply_dedup()                 → B: cross-turn content hash dedup
  └── _apply_shrink()                → A: char-budget all tool results
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
| `git_status.py` | git-status | Short-format prefix grouping by directory + status code (Strategy 6) |
| `git_show.py` | git-show | Commit header preserved, diff body compressed |
| `test_run_output.py` | test | Tail summary prioritized over verbose per-test output |
| `build_output.py` | build | Task summary for successful Gradle/Maven builds (Strategy 8) |
| `lint_output.py` | lint | Generic head+tail with lint defaults |
| `typecheck_output.py` | typecheck | Generic head+tail with typecheck defaults |
| `fs_listing.py` | ls-tree | Important-file preservation, tree-style detection, ls -la abbreviation (Strategy 9) |
| `search.py` | search | File grouping, per-file match capping, heading-style reformat for inline matches (Strategy 7) |
| `json_output.py` | json | Format-switch compression: CSV (Strategy 1), column factoring (Strategy 4), key-value lines (Strategy 2), dotted-key lines (Strategy 3), recursive truncation fallback |
| `logs.py` | logs | Duplicate-run collapse, important-line preservation |
| `generic.py` | generic | Head+tail windowing, blank collapse, header extraction, stack trace collapsing (Strategy 5) |
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

### Layer 3 — agent_solo.py

`compress_agent_solo_turn()` applies four composable, fail-open strategies to
tool-call continuation turns (agent-solo turns where the last message is "tool").
Strategies run in order D→C→B→A so each layer operates on already-compressed output.

| Strategy | Function | What it does |
|----------|----------|-------------|
| **D — Compact** | `_apply_compact_tool_args()` | Replace large Write/Edit/create_file arguments in completed tool_use calls with compact summaries. The model can Read the file to recover content. Default **on**. |
| **C — Filter middle** | `_apply_filter_middle()` | Split messages into system/middle/tail. Apply `filter_output()` to compressible tools (bash, grep, glob, search) in the middle. Shrink tool results in the tail. |
| **B — Dedup** | `_apply_dedup()` | Replace byte-identical tool results with compact markers using a caller-provided `DedupeTracker`. Cross-turn state scoped per session. |
| **A — Shrink** | `_apply_shrink()` | Cap every tool-role message to `shrink_max_tokens * 4` chars (~4 chars/token, fuzzy). No tiktoken overhead. |

Key types:
- `AgentSoloStats` — per-strategy char savings (`chars_saved_shrink`, `_dedup`, `_filter`, `_compact`)
- `AgentSoloResult` — `messages` + `stats`

Helper functions:
- `_is_compressible_tool(name)` — classifies tools safe to filter in the middle (bash, grep, glob, search, web_fetch, etc.)
- `_split_sections(messages, tail_size)` — separates system prefix, middle, coherence tail
- `_shrink_tail_messages(tail, max_tokens)` — char-based tail shrinking
- `_filter_middle_messages(middle)` — applies `filter_output()` to compressible tools

### dedupe.py

`DedupeTracker` provides exact-match cross-turn output deduplication.

- `check(content) -> int | None` — returns occurrence count if content was seen before
- `record(content) -> int` — records content hash, returns occurrence number
- `clear()` — reset all state
- `get_hashes() -> set[str]` — return current hash set

The caller creates one tracker per session and passes it to `compress_agent_solo_turn()`.
Minimum content length for hashing: 200 chars (`_DEDUP_MIN_CHARS`).

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
| `ARCHOLITH_RTK_FILTER_JSON_CSV_ENABLED` | Enable CSV format-switch for tabular arrays | 1 |
| `ARCHOLITH_RTK_FILTER_JSON_CSV_MIN_ROWS` | Min rows for CSV format-switch | 3 |
| `ARCHOLITH_RTK_FILTER_JSON_CSV_MAX_ROWS` | Max rows in CSV output | 20 |
| `ARCHOLITH_RTK_FILTER_JSON_CSV_MAX_KEY_LEN` | Max CSV key length | 40 |
| `ARCHOLITH_RTK_FILTER_JSON_KV_ENABLED` | Enable key-value format-switch | 1 |
| `ARCHOLITH_RTK_FILTER_JSON_KV_MIN_KEYS` | Min keys for key-value format-switch | 3 |
| `ARCHOLITH_RTK_FILTER_JSON_KV_MAX_KEYS` | Max keys in key-value output | 20 |
| `ARCHOLITH_RTK_FILTER_JSON_DOTKEY_ENABLED` | Enable dotted-key format-switch | 1 |
| `ARCHOLITH_RTK_FILTER_JSON_DOTKEY_MAX_KEYS` | Max keys in dotted-key output | 30 |
| `ARCHOLITH_RTK_FILTER_JSON_DOTKEY_MAX_DEPTH` | Max depth for dotted-key flattening | 3 |
| `ARCHOLITH_RTK_FILTER_JSON_CSV_FACTOR_ENABLED` | Enable CSV column factoring | 1 |
| `ARCHOLITH_RTK_FILTER_JSON_CSV_FACTOR_THRESHOLD` | Dominant value threshold for factoring | 0.8 |
| `ARCHOLITH_RTK_FILTER_JSON_CSV_FACTOR_MAX_COLS` | Max factored columns | 3 |
| `ARCHOLITH_RTK_FILTER_GENERIC_STACK_COLLAPSE_ENABLED` | Enable stack trace frame collapsing | 1 |
| `ARCHOLITH_RTK_FILTER_GENERIC_STACK_COLLAPSE_MIN_FRAMES` | Min frames for stack collapsing | 5 |
| `ARCHOLITH_RTK_FILTER_GENERIC_STACK_COLLAPSE_KEEP_APP` | App frames to keep at start/end | 2 |
| `ARCHOLITH_RTK_FILTER_GIT_STATUS_GROUP_ENABLED` | Enable git status prefix grouping | 1 |
| `ARCHOLITH_RTK_FILTER_GIT_STATUS_GROUP_MAX` | Max files per grouped line | 10 |
| `ARCHOLITH_RTK_FILTER_SEARCH_HEADING_REFORMAT_ENABLED` | Enable search heading reformat | 1 |
| `ARCHOLITH_RTK_FILTER_BUILD_SUMMARY_ENABLED` | Enable build task summary | 1 |
| `ARCHOLITH_RTK_FILTER_FS_LSL_ABBREVIATE_ENABLED` | Enable ls -la abbreviation | 1 |
| `ARCHOLITH_RTK_FILTER_READ_IMPORTS_COLLAPSE` | Collapse large import blocks | 1 |
| `ARCHOLITH_RTK_FILTER_READ_BLANK_LINE_MAX` | Max consecutive blank lines kept in `read_file` output | 1 |
| `ARCHOLITH_RTK_FILTER_READ_COMMENT_THRESHOLD` | Comment-run collapse threshold for `read_file` output | 10 |
| `ARCHOLITH_RTK_FILTER_READ_CSS_RULE_COLLAPSE` | Collapse verbose CSS rule bodies | 1 |
| `ARCHOLITH_RTK_FILTER_READ_GENERATED_MIN_LINE_LEN` | Long-line threshold for generated/minified block collapse | 500 |
| `ARCHOLITH_RTK_FILTER_READ_GENERATED_MIN_RUN` | Consecutive long lines required before collapsing generated/minified blocks | 5 |
| `ARCHOLITH_RTK_FILTER_READ_LITERAL_THRESHOLD` | Collapse threshold for multiline strings and large literal blocks | 8 |
| `ARCHOLITH_RTK_FILTER_REDACT_ENABLED` | Enable secret redaction | 1 |
| `ARCHOLITH_RTK_FILTER_STRIP_THINKING_ENABLED` | Enable thinking block stripping | 1 |
| `ARCHOLITH_RTK_FILTER_NORMALIZE_PATHS_ENABLED` | Enable path normalization | 1 |
| `ARCHOLITH_RTK_FILTER_BINARY_DETECTION_ENABLED` | Enable binary output detection | 1 |
| `ARCHOLITH_RTK_FILTER_OVERSIZED_GUARD_ENABLED` | Enable oversized input guard | 1 |
| `ARCHOLITH_RTK_FILTER_OVERSIZED_MAX_CHARS` | Threshold for oversized guard (chars) | 500000 |
| `ARCHOLITH_RTK_FILTER_NORMALIZE_NOISE_ENABLED` | Enable runtime noise normalization in log/build/test filters | 1 |
| `ARCHOLITH_RTK_FILTER_TABLE_WHITESPACE_MIN_ENABLED` | Enable table whitespace minimization | 1 |

All numeric values are clamped to upper bounds (lines: 500, entries: 1000, depth: 10, value length: 10000).

Risk-level presets adjust multiple thresholds together:

- `low`: preserves more lines, files, keys, and tail context
- `balanced`: existing default behavior
- `high`: more aggressive compression for higher token savings

## External Dependencies

- **tiktoken** (optional): Provides accurate token counting for Layer 2 shrink. Without it, falls back to heuristic of ~4 chars/token. Install via `archolith-filter[tokenizer]`.
- No other external dependencies — the library is zero-dependency by default.
