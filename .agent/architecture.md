# archolith-rtk — Architecture

## Overview

archolith-rtk is a deterministic Token Reduction Toolkit for LLM agent contexts. It compresses tool output, truncates oversized conversation messages, and manages context window thresholds — all without requiring LLM calls (though an optional summarizer callback is supported for Layer 3).

The library is organized as three sequential layers:

1. **Layer 1 — Output Filters**: Compress tool results before they enter the model context. 13 category-specific filters route based on the shell command that produced the output.
2. **Layer 2 — Shrink**: Truncate oversized tool-role messages in conversation history. Supports both char-based and token-based budgets.
3. **Layer 3 — Context Manager**: Threshold-based conversation folding that decides when and how aggressively to compress history.

All three layers are deterministic by default. Layer 3 supports an optional LLM-backed summarizer via an injected callback.

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
       │
       ▼
  ContextManager           ← Layer 3
  ├── decide_after_usage() →  PostUsageDecision (none / fold / exit)
  ├── fold()               →  replaces old turns with summary message
  └── emergency_compact()  →  in-place truncation at >95% usage
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

### Layer 1 — config.py

`FilterConfig` dataclass with all per-category thresholds. Loaded from `ARCHOLITH_RTK_FILTER_*` env vars via `from_env()`. `boost_for_verbose()` doubles head/tail limits for verbose commands. Upper bounds prevent typos from disabling filtering.

### Layer 2 — shrink.py

`shrink_messages()` is the main entry point (compatibility wrapper for dict or ChatMessage lists). Internally routes to `shrink_oversized_tool_results()` (char-based) or `shrink_oversized_tool_results_by_tokens()` (token-based). Also exposes `shrink_oversized_tool_call_args_by_tokens()` for long JSON strings in tool_call arguments.

Truncation primitives:
- `truncate_for_chars()` — head + 10% tail windowing
- `truncate_for_tokens()` — iterative convergence via `_size_prefix_to_tokens()` / `_size_suffix_to_tokens()` (never tokenizes full input)

Token counting: `count_tokens()` uses tiktoken `cl100k_base` if available, else divides by 4.

### Layer 3 — context_manager.py

`ContextManager` with threshold-based decision logic:

| Usage Ratio | Action | Tail Budget |
|-------------|--------|-------------|
| < 50% | None | — |
| 50–70% | Normal fold | 20% of ctx_max |
| 70–80% | Aggressive fold | 10% of ctx_max |
| 80–95% | Exit with summary | — |
| > 95% | Emergency compact | — |

Built-in context limits for 16 models via `get_context_limit()`. Default summarizer is `simple_extractive_summarizer()` — deterministic, no LLM calls. Custom summarizer injected via constructor.

### Supporting modules

- **raw_store.py**: LRU store (200 entries, 256K chars cap) for recovering original pre-filter text by ID. Module-level singleton.
- **telemetry.py**: Session-scoped `FilterTelemetryStore` tracking per-call and aggregate token savings. `format_summary()` for human-readable output.
- **strip_ansi.py**: Regex-based ANSI escape stripping (CSI, OSC, 8-bit CSI, misc ESC).
- **filter_meta.py**: `FilterMeta` dataclass and `parse_result_meta()` for extracting exit codes from formatted output headers.

## Configuration / Environment Variables

All env vars use the prefix `ARCHOLITH_RTK_FILTER_`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `ARCHOLITH_RTK_FILTERS` | Set to `off`/`false`/`0` to disable all filtering | enabled |
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

All numeric values are clamped to upper bounds (lines: 500, entries: 1000, depth: 10, value length: 10000).

## External Dependencies

- **tiktoken** (optional): Provides accurate token counting for Layer 2 shrink and Layer 3 context management. Without it, falls back to heuristic of ~4 chars/token. Install via `archolith-rtk[tokenizer]`.
- No other external dependencies — the library is zero-dependency by default.
