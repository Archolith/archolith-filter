# archolith-filter

Deterministic Token Reduction Toolkit for LLM agent contexts. Compresses tool output, truncates oversized conversation messages, and applies mechanical turn-level compression — all without requiring LLM calls.

Reduction layers:
1. **Layer 0** — Pre-filter: ANSI strip, secret redaction, thinking block strip, path normalization
2. **Layer 1** — Category filters: 13 shell-command categories + `read_file` structure-aware compression
3. **Layer 2** — Shrink: Char and token-based truncation of oversized messages
4. **Layer 3** — Agent-solo turn compression: mechanical shrink/dedup/filter/compact strategies for tool-call continuation payloads

Zero mandatory external dependencies. tiktoken is optional for accurate token counting.

## Quick Start

```bash
pip install -e .

# Optional: install with accurate token counting
pip install -e ".[tokenizer]"
```

```python
from archolith_filter import filter_output, shrink_messages

# Compress a tool result
result = filter_output("git diff --stat\n...")

# Shrink oversized messages
messages = [{"role": "tool", "content": "..."}]
shrunk = shrink_messages(messages, max_chars=4000)
```

## Development Installation

```bash
# Dev dependencies: pytest, pytest-benchmark, pytest-cov, ruff
pip install -e ".[dev]"
```

Two more optional extras:

- `[tokenizer]` — installs `tiktoken` for accurate BPE token counting.
  Without it, the library falls back to a shape-aware heuristic: prose uses
  the historical ~4 chars/token estimate, while code/config-like text uses
  a more conservative ~3.2 chars/token estimate. This matters primarily for standalone installs
  that don't also have `tiktoken` available. Production deployments via
  `archolith-context` and `archolith-mcp-audit` always pull `tiktoken` as
  a hard dependency, so the heuristic fallback is just a development
  convenience path here.
- `[context]` — installs `archolith-proxy>=0.1.0`, the local clone of
  `archolith-context`'s proxy module. **Note**: `archolith-proxy` is not
  published to PyPI yet, so this extra currently fails on
  a fresh checkout. For local development against a checked-out
  `archolith-context` worktree, point `pip` at the local clone
  (`pip install -e "../archolith-context[archolith_filter]"`) instead.
  Distribution is tracked in the separate `ARCHOLITH-FILTER-DISTRIBUTION-PLAN` follow-up.

## Documentation

| File | Purpose |
|------|---------|
| [.agent/README.md](.agent/README.md) | Agent context and maintenance rules |
| [.agent/architecture.md](.agent/architecture.md) | System design, filter pipeline, config reference |
| [.agent/data_models.md](.agent/data_models.md) | Data classes, enums, telemetry models |
| [.agent/CHANGELOG.md](.agent/CHANGELOG.md) | Running log of changes |

## License

Source-available under the PolyForm Noncommercial License 1.0.0.

archolith&trade; is a trademark of Charles Harvey.
