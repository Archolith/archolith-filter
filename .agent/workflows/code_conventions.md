# Code Conventions — archolith-rtk

## Style

- **Python 3.11+** with `from __future__ import annotations` in every module
- **Indent**: 4 spaces, no tabs
- **Max line length**: 120 characters (enforced by ruff)
- **Type hints**: Fully typed public API. All dataclasses use frozen=True by default. Use `X | Y` unions, not `Optional[X]`. Use builtin generics (`list`, `dict`), not `typing.List`.
- **String formatting**: Use f-strings for display/user-facing text. Use `%s`-style for logger calls (not applicable here — no logging, all print/stderr).
- **Imports**: stdlib → third-party → local. No unused imports.

## Naming

| Element | Convention | Example |
|---------|------------|---------|
| Modules | snake_case | `context_manager.py`, `strip_ansi.py` |
| Classes | PascalCase | `FilterConfig`, `ChatMessage`, `ContextManager` |
| Functions | snake_case | `filter_output()`, `classify_command()` |
| Constants | UPPER_SNAKE_CASE | `_MIN_FILTER_CHARS`, `DEFAULT_CONTEXT_TOKENS` |
| Private helpers | Leading underscore | `_classify_git()`, `_env_int()` |
| Enums | UPPER_SNAKE_CASE values | `CommandCategory.GIT_DIFF` |

## File Organization

```
archolith_rtk/
├── __init__.py          # Public API surface — re-exports everything
├── classifier.py        # Command → category mapping
├── config.py            # FilterConfig, env-var loading, verbose boost
├── context_manager.py   # Layer 3 — fold/compact decisions
├── filter_meta.py       # FilterMeta dataclass, exit code parsing
├── raw_store.py         # Pre-filter output LRU store
├── shrink.py            # Layer 2 — message truncation
├── strip_ansi.py        # ANSI escape stripping
├── telemetry.py         # Filter call tracking and summaries
├── py.typed             # PEP 561 marker
└── filters/
    ├── __init__.py      # FilterResult dataclass
    ├── generic.py       # Generic head+tail filter
    ├── git_diff.py      # Git diff stat/diff split filter
    ├── git_log.py       # Git log oneline filter
    ├── git_show.py      # Git show commit+diff filter
    ├── git_status.py    # Git status short-format filter
    ├── test_run_output.py  # Test output tail-summary filter
    ├── build_output.py  # Build output head+tail filter
    ├── lint_output.py   # Lint output head+tail filter
    ├── typecheck_output.py # Typecheck output head+tail filter
    ├── fs_listing.py    # Filesystem listing filter
    ├── search.py       # Search/grep result filter
    ├── json_output.py   # JSON recursive compression filter
    └── logs.py         # Log dedup/collapse filter
```

### Adding a new filter

1. Create `filters/<category>.py` with a filter function and an options dataclass
2. Add the category to `CommandCategory` in `classifier.py`
3. Add classification logic in `classifier.py`
4. Add routing in `_category_filter()` in `__init__.py`
5. Add config fields to `FilterConfig` in `config.py`
6. Add env-var loading in `from_env()` in `config.py`
7. Add tests in `tests/test_filters.py`

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=archolith_rtk --cov-report=term-missing

# Coverage HTML report
pytest tests/ -v --cov=archolith_rtk --cov-report=html

# Lint
ruff check .

# Type check (if mypy installed)
mypy archolith_rtk/
```

### Test conventions

- Tests in `tests/` directory, matching module names: `test_filters.py`, `test_shrink.py`, `test_context_manager.py`
- Use `reset_raw_output_store()` and `reset_filter_telemetry_store()` in test setup to avoid cross-test contamination
- All filter tests should verify `FilterResult.output`, `.raw_chars`, `.filtered_chars`, and `.truncated`
- Token-based tests: mark with `pytest.mark.skipif` if tiktoken is not installed
