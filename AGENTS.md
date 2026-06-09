# AGENTS.md

## Project Instructions For Coding Agents

1. Before making changes, read the guidance files in `.agent/`.
2. Start with `.agent/README.md` for project workflow and conventions.
3. Use `.agent/data_models.md` for entity and schema expectations.
4. Use `.agent/architecture.md` for system design and external API context.
5. Check `.agent/workflows/` for task-specific runbooks before executing operational actions.
6. If there is a conflict between code and `.agent` docs, call it out explicitly and ask for clarification.

## Scope

These instructions apply to the entire repository.

## Build / Lint / Test Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run single test file
pytest tests/test_filter_output.py

# Run single test
pytest tests/test_filter_output.py::test_git_diff

# Lint
ruff check .

# Auto-fix lint issues
ruff check --fix .
```

## Code Style

See `.agent/workflows/code_conventions.md` for full rules. Key points:

- Python 3.11+, 4 spaces indent, 120 char max line length
- Builtin generics (`list`, `dict`), `X | Y` unions, not `typing.List`/`Optional`
- `%s`-style lazy formatting for loggers
- snake_case for modules/functions, PascalCase for classes

## Project-Specific Notes

- This is a **deterministic token reduction library** — it does NOT call any LLM. All filtering is mechanical and sub-millisecond.
- Zero mandatory external dependencies. tiktoken is optional (`archolith-filter[tokenizer]`).
- Three layers: L0 pre-filter (ANSI strip, secret redaction, path normalization), L1 category filters (13 command categories), L2 shrink (char/token budgets).
- The `_compact` convention is the workspace standard for reduced-response modes. See the parent `.agent/CONVENTIONS.md` for full rules.
- `_patterns.py` is the single source of truth for shared regex patterns used by `filters/read_file.py`, `shrink/read_file_truncate.py`, and `config.py`.
- `raw_store.py` provides LRU-backed raw output recovery by ID. Module-level singleton, cleared on process restart.
- `telemetry.py` provides `FilterTelemetryStore` — the live accumulator in archolith-mcp-audit reads from this.
