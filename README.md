# archolith-rtk

Token Reduction Toolkit — deterministic output filtering for LLM agent contexts.

A clean-room Python reimplementation of the RTK output filtering system from
[reasonix](https://github.com/nicepkg/reasonix). Three layers of context
reduction that operate on tool output, conversation history, and context window
management.

Part of the Archolith suite.

## Install

```bash
pip install git+https://github.com/archolith/archolith-rtk.git
```

Optional tokenizer support (recommended for accuracy):

```bash
pip install "archolith-rtk[tokenizer]"
```

## Architecture

```
Layer 1: filter_output()     Compress tool results before model context
Layer 2: shrink_messages()   Truncate oversized messages in conversation history
Layer 3: ContextManager      Threshold-based conversation folding decisions
```

All three layers are deterministic and require no LLM calls. Layer 3 supports
optional LLM-backed summarization via an injected callback.

## Layer 1 — Output Filters

Compress tool output before it enters the model context. Routes output through
13 category-specific filters based on the command that produced it.

```python
from archolith_rtk import filter_output

result = filter_output(
    large_diff_text,
    command="git diff --staged",
    exit_code=0,
)

print(result.output)         # compressed text
print(result.raw_chars)      # original char count
print(result.filtered_chars) # compressed char count
print(result.truncated)      # whether compression occurred
```

### Category Filters

| Category | Filter | Behavior |
|----------|--------|----------|
| `git-diff` | `git_diff_filter` | Stat/diff split, per-file section compression |
| `git-log` | `git_log_filter` | Oneline detection + head/tail commit windowing |
| `git-status` | `git_status_filter` | Short-format pass-through |
| `git-show` | `git_show_filter` | Commit header preserved, diff body compressed |
| `test` | `filter_test_output` | Tail summary prioritized over verbose per-test output |
| `build` | `build_filter` | Generic head+tail with build defaults |
| `lint` | `lint_filter` | Generic head+tail with lint defaults |
| `typecheck` | `typecheck_filter` | Generic head+tail with typecheck defaults |
| `ls-tree` | `fs_listing_filter` | Important-file preservation, tree-style detection |
| `search` | `search_filter` | File grouping, per-file match capping |
| `json` | `json_filter` | Recursive value compression, depth/key/array capping |
| `logs` | `log_filter` | Duplicate-run collapse, important-line preservation |
| generic | `generic_filter` | Head+tail windowing, blank collapse, header extraction |

### Bypass Rules

- **Failed commands** (non-zero exit code or timeout): ANSI-stripped only, no filtering
- **Small output** (<500 chars): returned as-is, overhead would exceed savings
- **Disabled** (`ARCHOLITH_RTK_FILTERS=off`): no filtering applied
- **Exceptions**: fail-open — returns ANSI-stripped string unchanged

### Configuration

All thresholds are configurable via environment variables with the prefix
`ARCHOLITH_RTK_FILTER_*`:

```bash
ARCHOLITH_RTK_FILTERS=off                    # Disable all filtering
ARCHOLITH_RTK_FILTER_GENERIC_HEAD=20         # Generic head lines
ARCHOLITH_RTK_FILTER_GENERIC_TAIL=30         # Generic tail lines
ARCHOLITH_RTK_FILTER_GIT_DIFF_FILE_HEAD=5    # Lines per file in diff stat
ARCHOLITH_RTK_FILTER_GIT_DIFF_TAIL=50        # Diff body tail lines
ARCHOLITH_RTK_FILTER_TEST_HEAD=10            # Test output head lines
ARCHOLITH_RTK_FILTER_TEST_TAIL=40            # Test output tail lines
```

### Verbose Boosting

Commands with verbose/debug flags get doubled head/tail limits automatically:

```python
# These commands get 2x head/tail budgets:
# git log --verbose, npm test --debug, gradle test --info, etc.
```

### Raw Output Store

When output is compressed, the original text is stored for recovery:

```python
from archolith_rtk import get_raw_output_store

store = get_raw_output_store()
entry = store.get(raw_output_id)         # full raw text
tail = store.get_filtered(id, tail_lines=50)  # tail slice
```

### Telemetry

Filter calls are recorded for monitoring:

```python
from archolith_rtk import get_filter_telemetry_store

summary = get_filter_telemetry_store().get_summary()
print(f"Total calls: {summary.total_calls}")
print(f"Avg savings: {summary.average_savings_pct}%")
```

## Layer 2 — Shrink

Truncate oversized tool-role messages in conversation history. Two modes:
char-based and token-based.

```python
from archolith_rtk import (
    ChatMessage,
    shrink_oversized_tool_results,
    shrink_oversized_tool_results_by_tokens,
    shrink_oversized_tool_call_args_by_tokens,
)

messages = [
    ChatMessage(role="user", content="run the tests"),
    ChatMessage(role="assistant", content=None, tool_calls=[...]),
    ChatMessage(role="tool", content=huge_test_output, tool_call_id="1"),
]

# Char-based: truncate tool messages > max_chars
result = shrink_oversized_tool_results(messages, max_chars=5000)
print(f"Healed {result.healed_count} messages, saved {result.healed_from} chars")

# Token-based: truncate tool messages > max_tokens
result = shrink_oversized_tool_results_by_tokens(messages, max_tokens=2000)
print(f"Saved {result.tokens_saved} tokens, {result.chars_saved} chars")

# Shrink long JSON strings in tool_call arguments
result = shrink_oversized_tool_call_args_by_tokens(messages, max_tokens=2000)
```

### Token Counting

With tiktoken installed, uses `cl100k_base` encoding (GPT-4 class). Without
it, falls back to a heuristic of ~4 chars/token (accurate for English/code,
underestimates CJK).

```python
from archolith_rtk import count_tokens

n = count_tokens("some text to count")
```

### Truncation Primitives

```python
from archolith_rtk import truncate_for_chars, truncate_for_tokens

# Head + 10% tail truncation with marker
short = truncate_for_chars(huge_text, max_chars=5000)

# Token-accurate truncation with iterative convergence
short = truncate_for_tokens(huge_text, max_tokens=2000)
```

## Layer 3 — Context Manager

Threshold-based conversation folding to keep conversations within context
window limits.

### Decision Logic

| Usage Ratio | Action | Tail Budget |
|-------------|--------|-------------|
| < 50% | None | — |
| 50-70% | Normal fold | 20% of ctx_max |
| 70-80% | Aggressive fold | 10% of ctx_max |
| 80-95% | Exit with summary | — |
| > 95% | Emergency compact | — |

```python
from archolith_rtk import ContextManager, ChatMessage

cm = ContextManager(ctx_max=128000)

# After a turn's API response
decision = cm.decide_after_usage(prompt_tokens=65000)
if decision.kind == "fold":
    # Fold conversation history
    result = cm.fold(messages, keep_recent_tokens=decision.tail_budget)

# Before sending a request
preflight = cm.decide_preflight(messages, tool_specs)
if preflight.needs_action:
    messages = cm.emergency_compact(messages)
```

### Model Context Sizes

Built-in context limits for 16 known models:

```python
from archolith_rtk import get_context_limit

limit = get_context_limit("gpt-4o")       # 128000
limit = get_context_limit("deepseek-v3")   # 131072
limit = get_context_limit("claude-3.5-sonnet")  # 200000
limit = get_context_limit("gemini-2.5-pro")  # 1048576
```

### Custom Summarizer

By default, the fold operation uses a deterministic extractive summarizer that
extracts important lines (errors, decisions, file changes) without LLM calls.
You can inject your own:

```python
def my_llm_summarizer(messages):
    # Call your LLM here
    return "Summary of the conversation..."

cm = ContextManager(
    ctx_max=128000,
    summarizer=my_llm_summarizer,
)
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check .

# Type check (if mypy installed)
mypy archolith_rtk/
```

## License

MIT
