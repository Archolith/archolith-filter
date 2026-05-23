"""Layer 2: Shrink oversized tool results and tool-call args in conversation history.

Two modes:
- char-based: truncate tool-role messages exceeding a char budget
- token-based: truncate tool-role messages and tool_call arguments exceeding a token budget

Token mode requires tiktoken (optional dependency). Without it, falls back to
char-based heuristics (~4 chars per token for English/code).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# ─── Token counting ───

_count_tokens_fn = None


def _get_token_counter():
    """Lazy-load tiktoken; return None if unavailable."""
    global _count_tokens_fn
    if _count_tokens_fn is not None:
        return _count_tokens_fn
    try:
        import tiktoken

        _enc = tiktoken.get_encoding("cl100k_base")

        def _count(text: str) -> int:
            return len(_enc.encode(text))

        _count_tokens_fn = _count
        return _count_tokens_fn
    except ImportError:
        return None


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken if available, else char heuristic.

    The char heuristic divides by 4 (~4 chars/token for English/code).
    CJK text will be undercounted; use tiktoken for accuracy.
    """
    counter = _get_token_counter()
    if counter is not None:
        return counter(text)
    return max(1, len(text) // 4)


# ─── Truncation primitives ───

_TRUNCATION_MARKER = (
    "[…truncated {dropped} {unit} — raise budget or call the tool with a narrower scope…]"
)

_TAIL_FRACTION = 0.1
_TAIL_MAX_CHARS = 1024
_TAIL_MAX_TOKENS = 256
_MARKER_TOKEN_OVERHEAD = 48
_CONVERGENCE_ITERS = 6
_CHARS_PER_TOKEN_ESTIMATE = 4


def truncate_for_chars(text: str, max_chars: int) -> str:
    """Truncate text to max_chars using head+tail windowing.

    Keeps the head and a 10% tail (up to 1KB) so trailing errors/stack traces survive.
    """
    if len(text) <= max_chars:
        return text
    tail_budget = min(_TAIL_MAX_CHARS, max_chars // 10)
    head_budget = max(0, max_chars - tail_budget)
    head = text[:head_budget]
    tail = text[-tail_budget:] if tail_budget > 0 else ""
    dropped = len(text) - len(head) - len(tail)
    marker = f"\n\n[…truncated {dropped} chars — raise budget or call the tool with a narrower scope…]\n\n"
    return f"{head}{marker}{tail}"


def truncate_for_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to max_tokens using tiktoken if available.

    Never tokenizes full input — uses iterative convergence to avoid
    pathological cost on repetitive text.
    """
    if max_tokens <= 0:
        return ""
    if len(text) <= max_tokens:
        return text
    # Every token is ≥1 char — if length ≤ budget, tokens ≤ budget.
    if len(text) <= max_tokens * _CHARS_PER_TOKEN_ESTIMATE:
        if count_tokens(text) <= max_tokens:
            return text

    content_budget = max(0, max_tokens - _MARKER_TOKEN_OVERHEAD)
    tail_budget = min(_TAIL_MAX_TOKENS, content_budget // 10)
    head_budget = max(0, content_budget - tail_budget)

    head = _size_prefix_to_tokens(text, head_budget)
    tail = _size_suffix_to_tokens(text, tail_budget)
    dropped_chars = len(text) - len(head) - len(tail)

    # Estimate dropped tokens from the measured slice ratio.
    head_tokens = count_tokens(head) if head else 0
    tail_tokens = count_tokens(tail) if tail else 0
    sample_chars = len(head) + len(tail)
    sample_tokens = head_tokens + tail_tokens
    ratio = sample_tokens / sample_chars if sample_chars > 0 else 0.25
    est_total_tokens = int(len(text) * ratio)
    dropped_tokens = max(0, est_total_tokens - sample_tokens)

    marker = (
        f"\n\n[…truncated ~{dropped_tokens} tokens ({dropped_chars} chars)"
        f" — raise budget or call the tool with a narrower scope…]\n\n"
    )
    return f"{head}{marker}{tail}"


def _size_prefix_to_tokens(text: str, budget: int) -> str:
    """Slice text from start to the largest prefix that fits budget tokens."""
    if budget <= 0 or not text:
        return ""
    size = min(len(text), budget * _CHARS_PER_TOKEN_ESTIMATE)
    for _ in range(_CONVERGENCE_ITERS):
        if size <= 0:
            return ""
        chunk = text[:size]
        count = count_tokens(chunk)
        if count <= budget:
            return chunk
        next_size = int(size * (budget / count) * 0.95)
        if next_size >= size:
            return text[:max(0, size - 1)]
        size = next_size
    return text[:max(0, size)]


def _size_suffix_to_tokens(text: str, budget: int) -> str:
    """Slice text from end to the largest suffix that fits budget tokens."""
    if budget <= 0 or not text:
        return ""
    size = min(len(text), budget * _CHARS_PER_TOKEN_ESTIMATE)
    for _ in range(_CONVERGENCE_ITERS):
        if size <= 0:
            return ""
        chunk = text[-size:]
        count = count_tokens(chunk)
        if count <= budget:
            return chunk
        next_size = int(size * (budget / count) * 0.95)
        if next_size >= size:
            return text[-max(0, size - 1):]
        size = next_size
    return text[-max(0, size):]


# ─── JSON arg shrinking ───

_LONG_STRING_THRESHOLD = 300


def _shrink_json_long_strings(json_str: str) -> str:
    """Shrink long string values in a JSON object, keeping short keys/values verbatim."""
    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        head = json_str[:200]
        return f"{head}…[shrunk: {len(json_str)} chars, unparsed]"

    if not isinstance(parsed, dict) or isinstance(parsed, list):
        return json_str

    output: dict[str, object] = {}
    for k, v in parsed.items():
        if isinstance(v, str) and len(v) > _LONG_STRING_THRESHOLD:
            newline_count = v.count("\n")
            output[k] = (
                f"[…shrunk: {len(v)} chars, {newline_count} lines"
                f" — tool already responded, see result]"
            )
        else:
            output[k] = v
    return json.dumps(output)


# ─── Message types ───

@dataclass(frozen=True)
class ChatMessage:
    """Minimal OpenAI-format chat message."""
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict:
        d: dict[str, object] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls is not None:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ChatMessage:
        tool_calls = None
        if "tool_calls" in d and isinstance(d["tool_calls"], list):
            tool_calls = [ToolCall.from_dict(tc) for tc in d["tool_calls"]]
        return cls(
            role=d["role"],
            content=d.get("content"),
            tool_calls=tool_calls,
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
        )


@dataclass(frozen=True)
class ToolCall:
    """OpenAI-format tool call."""
    id: str
    type: str = "function"
    function: ToolCallFunction = field(default_factory=lambda: ToolCallFunction(id="", name="", arguments=""))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "function": self.function.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> ToolCall:
        fn = d.get("function", {})
        return cls(
            id=d.get("id", ""),
            type=d.get("type", "function"),
            function=ToolCallFunction(
                id=d.get("id", ""),
                name=fn.get("name", ""),
                arguments=fn.get("arguments", ""),
            ),
        )


@dataclass(frozen=True)
class ToolCallFunction:
    id: str
    name: str
    arguments: str

    def to_dict(self) -> dict:
        return {"name": self.name, "arguments": self.arguments}


# ─── Shrink results ───

@dataclass(frozen=True)
class ShrinkCharsResult:
    """Result of char-based shrinking."""
    messages: list[ChatMessage]
    healed_count: int
    healed_from: int


@dataclass(frozen=True)
class ShrinkTokensResult:
    """Result of token-based shrinking."""
    messages: list[ChatMessage]
    healed_count: int
    tokens_saved: int
    chars_saved: int


# ─── Public API ───

def shrink_oversized_tool_results(
    messages: list[ChatMessage],
    max_chars: int,
) -> ShrinkCharsResult:
    """Truncate tool-role messages exceeding max_chars.

    Only tool-role messages are truncated — user/assistant/system messages
    would corrupt authored intent.
    """
    healed_count = 0
    healed_from = 0
    out: list[ChatMessage] = []

    for msg in messages:
        if msg.role != "tool" or msg.content is None:
            out.append(msg)
            continue
        if len(msg.content) <= max_chars:
            out.append(msg)
            continue
        healed_count += 1
        healed_from += len(msg.content)
        truncated = truncate_for_chars(msg.content, max_chars)
        out.append(ChatMessage(
            role=msg.role,
            content=truncated,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        ))

    return ShrinkCharsResult(messages=out, healed_count=healed_count, healed_from=healed_from)


def shrink_oversized_tool_results_by_tokens(
    messages: list[ChatMessage],
    max_tokens: int,
) -> ShrinkTokensResult:
    """Truncate tool-role messages exceeding max_tokens.

    Token-cap variant — char cap would let CJK slip past at 2× the intended token cost.
    """
    healed_count = 0
    tokens_saved = 0
    chars_saved = 0
    out: list[ChatMessage] = []

    for msg in messages:
        if msg.role != "tool" or msg.content is None:
            out.append(msg)
            continue
        content = msg.content
        # length ≤ max_tokens ⇒ tokens ≤ max_tokens — skip tokenize.
        if len(content) <= max_tokens:
            out.append(msg)
            continue
        before_tokens = count_tokens(content)
        if before_tokens <= max_tokens:
            out.append(msg)
            continue
        truncated = truncate_for_tokens(content, max_tokens)
        after_tokens = count_tokens(truncated)
        healed_count += 1
        tokens_saved += max(0, before_tokens - after_tokens)
        chars_saved += max(0, len(content) - len(truncated))
        out.append(ChatMessage(
            role=msg.role,
            content=truncated,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        ))

    return ShrinkTokensResult(
        messages=out,
        healed_count=healed_count,
        tokens_saved=tokens_saved,
        chars_saved=chars_saved,
    )


def shrink_oversized_tool_call_args_by_tokens(
    messages: list[ChatMessage],
    max_tokens: int,
) -> ShrinkTokensResult:
    """Shrink long string values in tool_call arguments exceeding max_tokens.

    Caller must gate on paired tool_calls — in-flight calls would crash mid-turn.
    Keeps short keys/values (paths, ids) verbatim; only long string values get a marker.
    """
    healed_count = 0
    tokens_saved = 0
    chars_saved = 0
    out: list[ChatMessage] = []

    for msg in messages:
        if msg.role != "assistant" or not msg.tool_calls:
            out.append(msg)
            continue
        changed = False
        new_calls: list[ToolCall] = []
        for call in msg.tool_calls:
            args = call.function.arguments
            if not args or len(args) <= max_tokens:
                new_calls.append(call)
                continue
            before_tokens = count_tokens(args)
            if before_tokens <= max_tokens:
                new_calls.append(call)
                continue
            shrunk = _shrink_json_long_strings(args)
            after_tokens = count_tokens(shrunk)
            # Many-short-strings payloads can come back marginally larger.
            if after_tokens >= before_tokens:
                new_calls.append(call)
                continue
            changed = True
            healed_count += 1
            tokens_saved += before_tokens - after_tokens
            chars_saved += len(args) - len(shrunk)
            new_calls.append(ToolCall(
                id=call.id,
                type=call.type,
                function=ToolCallFunction(
                    id=call.function.id,
                    name=call.function.name,
                    arguments=shrunk,
                ),
            ))
        if not changed:
            out.append(msg)
        else:
            out.append(ChatMessage(
                role=msg.role,
                content=msg.content,
                tool_calls=new_calls,
            ))

    return ShrinkTokensResult(
        messages=out,
        healed_count=healed_count,
        tokens_saved=tokens_saved,
        chars_saved=chars_saved,
    )


def estimate_conversation_tokens(messages: list[ChatMessage]) -> int:
    """Estimate total tokens across all messages (content + tool_calls).

    Doesn't add chat-template framing overhead; under-counts ~3-6% vs real prompt_tokens.
    """
    total = 0
    for m in messages:
        if isinstance(m.content, str) and m.content:
            total += count_tokens(m.content)
        if m.tool_calls:
            total += count_tokens(json.dumps([tc.to_dict() for tc in m.tool_calls]))
    return total


def estimate_request_tokens(
    messages: list[ChatMessage],
    tool_specs: list[dict] | None = None,
) -> int:
    """Estimate total request tokens (messages + tool specs)."""
    total = estimate_conversation_tokens(messages)
    if tool_specs:
        total += count_tokens(json.dumps(tool_specs))
    return total
