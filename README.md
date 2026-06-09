# archolith-filter

Deterministic Token Reduction Toolkit for LLM agent contexts. Compresses tool output, truncates oversized conversation messages, and applies mechanical turn-level compression — all without requiring LLM calls.

Three layers of reduction:
1. **Layer 0** — Pre-filter: ANSI strip, secret redaction, thinking block strip, path normalization
2. **Layer 1** — Category filters: 13 shell-command categories + `read_file` structure-aware compression
3. **Layer 2** — Shrink: Char and token-based truncation of oversized messages

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
