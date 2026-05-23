# archolith-rtk — Data Models

## Core Data Classes

### FilterResult (`filters/__init__.py`)

```python
@dataclass(frozen=True)
class FilterResult:
    output: str         # Compressed text
    raw_chars: int      # Original character count
    filtered_chars: int # Compressed character count
    truncated: bool     # Whether compression occurred
```

### ClassifiedCommand (`classifier.py`)

```python
@dataclass(frozen=True)
class ClassifiedCommand:
    category: CommandCategory  # One of 13 filter categories
    base: str                  # Base command name
    command: str               # Full command string
```

### CommandCategory (`classifier.py`)

```python
class CommandCategory(str, Enum):
    GIT_STATUS = "git-status"
    GIT_DIFF = "git-diff"
    GIT_LOG = "git-log"
    GIT_SHOW = "git-show"
    GIT_OTHER = "git-other"
    LS_TREE = "ls-tree"
    SEARCH = "search"
    JSON = "json"
    TEST = "test"
    BUILD = "build"
    LINT = "lint"
    TYPECHECK = "typecheck"
    GENERIC = "generic"
```

### FilterConfig (`config.py`)

```python
@dataclass(frozen=True)
class FilterConfig:
    # Per-category head/tail line counts (see architecture.md for full list)
    generic_head: int = 20
    generic_tail: int = 30
    test_head: int = 10
    test_tail: int = 40
    # ... 30+ more fields for all category thresholds
    # read_file compressor knobs
    read_import_collapse: bool = True
    read_blank_line_max: int = 1
    read_comment_threshold: int = 10
    read_css_rule_collapse: bool = True
```

### FilterMeta (`filter_meta.py`)

```python
@dataclass(frozen=True)
class FilterMeta:
    tool: str
    command: str
    exit_code: int | None = None
    timed_out: bool = False
```

## Layer 2 — Shrink Models (`shrink.py`)

### ChatMessage

```python
@dataclass(frozen=True)
class ChatMessage:
    role: str                                    # "user" | "assistant" | "tool" | "system"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> ChatMessage: ...
```

### ToolCall / ToolCallFunction

```python
@dataclass(frozen=True)
class ToolCall:
    id: str
    type: str = "function"
    function: ToolCallFunction = ...

@dataclass(frozen=True)
class ToolCallFunction:
    id: str
    name: str
    arguments: str
```

### ShrinkCharsResult

```python
@dataclass(frozen=True)
class ShrinkCharsResult:
    messages: list[ChatMessage]
    healed_count: int     # Number of messages truncated
    healed_from: int      # Total chars removed
```

### ShrinkTokensResult

```python
@dataclass(frozen=True)
class ShrinkTokensResult:
    messages: list[ChatMessage]
    healed_count: int     # Number of messages truncated
    tokens_saved: int     # Tokens recovered
    chars_saved: int      # Characters recovered
```

## Layer 3 — Context Manager Models (`context_manager.py`)

### PostUsageKind

```python
class PostUsageKind(str, Enum):
    NONE = "none"
    FOLD = "fold"
    EXIT_WITH_SUMMARY = "exit-with-summary"
```

### PostUsageDecision

```python
@dataclass(frozen=True)
class PostUsageDecision:
    kind: PostUsageKind
    prompt_tokens: int
    ctx_max: int
    ratio: float
    tail_budget: int | None = None
    aggressive: bool = False
```

### PreflightDecision

```python
@dataclass(frozen=True)
class PreflightDecision:
    needs_action: bool       # True if emergency compact needed
    estimate_tokens: int
    ctx_max: int
```

### FoldResult

```python
@dataclass(frozen=True)
class FoldResult:
    folded: bool             # Whether a fold actually happened
    before_messages: int
    after_messages: int
    summary_chars: int
```

## Raw Output Store (`raw_store.py`)

### RawOutputEntry

```python
@dataclass
class RawOutputEntry:
    id: int                  # Auto-incremented store ID
    raw: str                 # Original pre-filter text (capped at 256K chars)
    command: str
    tool: str
    filtered_chars: int
    stored_at: float         # time.time() timestamp
```

### RawOutputStore

- LRU store, default 200 entries max, 256K chars per entry
- Module-level singleton via `get_raw_output_store()`
- `store() -> int`, `get(entry_id)`, `get_filtered(entry_id, tail_lines, max_chars)`
- `reset_raw_output_store()` for tests

## Telemetry (`telemetry.py`)

### FilterTelemetryEntry

```python
@dataclass
class FilterTelemetryEntry:
    command: str
    tool: str | None
    filter_kind: str
    raw_chars: int
    filtered_chars: int
    estimated_raw_tokens: int
    estimated_filtered_tokens: int
    savings_pct: int
    raw_output_id: int | None
    fallback_used: bool
    token_counts_are_estimate: bool
    timestamp: float
```

### FilterTelemetrySummary

```python
@dataclass
class FilterTelemetrySummary:
    total_calls: int
    filtered_calls: int
    fallback_calls: int
    total_raw_chars: int
    total_filtered_chars: int
    estimated_raw_tokens: int
    estimated_filtered_tokens: int
    estimated_saved_tokens: int
    average_savings_pct: int
    token_counts_are_estimate: bool
```

## Enums

| Enum | Location | Values |
|------|----------|--------|
| `CommandCategory` | `classifier.py` | 13 categories (see above) |
| `PostUsageKind` | `context_manager.py` | `NONE`, `FOLD`, `EXIT_WITH_SUMMARY` |

## Repository Reference

No database. All state is session-scoped and in-memory:
- `RawOutputStore` — module-level singleton, cleared on process restart
- `FilterTelemetryStore` — module-level singleton, cleared on process restart

Both stores expose `reset_*()` functions for test isolation.
