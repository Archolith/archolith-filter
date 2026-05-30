# archolith-rtk

Token Reduction Toolkit — deterministic output filtering for LLM agent contexts.

A clean-room Python reimplementation of the RTK output filtering system from
[reasonix](https://github.com/nicepkg/reasonix). Two layers of deterministic
context reduction that operate on tool output and oversized conversation
messages.

Part of the [archolith&trade;](https://archolith.dev) stack.

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
```

Both layers are deterministic and require no LLM calls.

## Layer 1 — Output Filters

Compress tool output before it enters the model context. Routes output through
13 shell-command categories plus tool-routed `read_file` compression.

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
| `read_file` | `read_file_filter` | Structure-aware file compression for imports, comments, CSS, literals, and generated blobs |
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
ARCHOLITH_RTK_FILTER_RISK_LEVEL=balanced    # low | balanced | high
ARCHOLITH_RTK_FILTER_GENERIC_HEAD=20         # Generic head lines
ARCHOLITH_RTK_FILTER_GENERIC_TAIL=30         # Generic tail lines
ARCHOLITH_RTK_FILTER_GIT_DIFF_FILE_HEAD=5    # Lines per file in diff stat
ARCHOLITH_RTK_FILTER_GIT_DIFF_TAIL=50        # Diff body tail lines
ARCHOLITH_RTK_FILTER_TEST_HEAD=10            # Test output head lines
ARCHOLITH_RTK_FILTER_TEST_TAIL=40            # Test output tail lines
ARCHOLITH_RTK_FILTER_READ_LITERAL_THRESHOLD=8  # Collapse large fixture/literal blocks
```

`ARCHOLITH_RTK_FILTER_RISK_LEVEL` controls the default compression posture:

- `low`: lower risk of information loss, lower token savings
- `balanced`: default preset
- `high`: higher token savings, higher risk of information loss

Programmatic callers can use the same presets without environment variables:

```python
from archolith_rtk import FilterRiskLevel, base_config_for_risk_level, filter_output

config = base_config_for_risk_level(FilterRiskLevel.HIGH)
result = filter_output(large_text, command="rg --heading prompt_tokens src", config=config)
```

Explicit environment-variable overrides still win over the preset. For example,
`ARCHOLITH_RTK_FILTER_RISK_LEVEL=high` plus
`ARCHOLITH_RTK_FILTER_JSON_MAX_DEPTH=4` uses the high-risk preset for everything
except JSON depth, which is forced to `4`.

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
    shrink_messages,
    shrink_oversized_tool_results,
    shrink_oversized_tool_results_by_tokens,
    shrink_oversized_tool_call_args_by_tokens,
)

messages = [
    ChatMessage(role="user", content="run the tests"),
    ChatMessage(role="assistant", content=None, tool_calls=[...]),
    ChatMessage(role="tool", content=huge_test_output, tool_call_id="1"),
]

# Compatibility wrapper for OpenAI-format dict messages or ChatMessage objects
messages = shrink_messages(messages, max_tokens=2000)

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

## Suite Boundary

`archolith-rtk` is the deterministic hygiene layer of the Archolith suite:

- Layer 1: tool-output filtering
- Layer 2: oversized message and tool-argument shrinking
- shared primitives: token counting, truncation, raw-output recovery, telemetry

Conversation-level context strategy such as folding, graph assembly, curator
selection, and emergency compaction belongs in
`archolith-context`, not this package.

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

## Benchmarking

The repository includes a dedicated benchmark suite under
`benchmarks/`. It is not part of the default `pytest tests` run.

```bash
# Install benchmark dependency via the dev extra
pip install -e ".[dev]"

# Run only the benchmark suite
pytest benchmarks -v --benchmark-only

# Show skipped benchmark modules if pytest-benchmark is missing
pytest benchmarks -v -rs

# Save a machine-readable result file for comparisons
pytest benchmarks -v --benchmark-only --benchmark-json benchmarks/results/latest.json
```

The benchmark suite covers:

- Layer 1: `filter_output()` on git diff, heading-mode search, bracketed logs, JSON payloads, and `read_file` corpora
- Layer 2: `shrink_messages()` and the lower-level shrink helpers

Fixture corpora live in `benchmarks/fixtures/`, and larger synthetic
conversation histories are generated in `benchmarks/conftest.py`.

For a more practical benchmark focused on token savings plus retention checks,
run the reporting script:

```bash
python benchmarks/practical_report.py
```

That writes:

- `benchmarks/results/practical-latest.json`
- `benchmarks/results/practical-latest.md`

The practical report evaluates every Layer 1 filter scenario at all three
`FilterRiskLevel` presets (low, balanced, high) and tracks:

- risk level per scenario row
- tokens before and after compression
- tokens saved and savings percentage
- median and p95 runtime per scenario
- scenario-specific retention checks (e.g. preserving readiness lines and
  JSON keys)
- acceptance checks: preset ordering (high >= balanced >= low savings),
  minimum savings thresholds, and retention marker survival across presets

The script exits non-zero when any scenario or acceptance check fails,
making it suitable for CI gating.

## License

Source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE).
Free for non-commercial use; commercial use requires permission from the licensor.

archolith&trade; is a trademark of Charles Harvey.
