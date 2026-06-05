"""Generic truncation primitives — char and token budget head+tail windowing.

Import DAG: depends on token_counter.
"""

from __future__ import annotations

from .token_counter import count_tokens

# ─── Constants ───

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
