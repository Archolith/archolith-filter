"""Generic truncation primitives — char and token budget head+tail windowing.

Import DAG: depends on token_counter.
"""

from __future__ import annotations

from .token_counter import count_tokens, token_counts_are_estimated

# ─── Constants ───

_TRUNCATION_MARKER = (
    "[…truncated {dropped} {unit} — raise budget or call the tool with a narrower scope…]"
)

_TAIL_FRACTION = 0.1
_TAIL_MAX_CHARS = 1024
_TAIL_MAX_TOKENS = 256
_MARKER_TOKEN_OVERHEAD = 48
_CHARS_PER_TOKEN_ESTIMATE = 3.2
_TOKEN_WINDOW_GROWTH_LIMIT = 6


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
    # Every token is >=1 char, so if length <= budget, tokens <= budget.
    if len(text) <= max_tokens:
        return text
    # Only exact tokenizers can prove fit from a single count. Fallback counts
    # are intentionally conservative estimates, so continue through truncation
    # instead of returning an optimistic "fits" decision.
    if not token_counts_are_estimated() and len(text) <= max_tokens * _CHARS_PER_TOKEN_ESTIMATE:
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
    size = _largest_fitting_edge_size(text, budget, from_end=False)
    return text[:size]


def _size_suffix_to_tokens(text: str, budget: int) -> str:
    """Slice text from end to the largest suffix that fits budget tokens."""
    if budget <= 0 or not text:
        return ""
    size = _largest_fitting_edge_size(text, budget, from_end=True)
    return text[-size:] if size > 0 else ""


def _largest_fitting_edge_size(text: str, budget: int, *, from_end: bool) -> int:
    """Find the largest edge slice fitting a token budget.

    The old damping loop could stop at the first under-budget slice and leave
    budget unused. This bounded binary search grows a window until it brackets
    the limit, then returns the largest slice that actually fits.
    """
    if budget <= 0 or not text:
        return 0

    high = min(len(text), max(1, int(budget * _CHARS_PER_TOKEN_ESTIMATE * 2)))
    low = 0
    growth_iters = 0
    while growth_iters < _TOKEN_WINDOW_GROWTH_LIMIT and high < len(text):
        chunk = text[-high:] if from_end else text[:high]
        if count_tokens(chunk) > budget:
            break
        low = high
        high = min(len(text), high * 2)
        growth_iters += 1

    if high == len(text):
        chunk = text[-high:] if from_end else text[:high]
        if count_tokens(chunk) <= budget:
            return high

    while low < high:
        mid = (low + high + 1) // 2
        chunk = text[-mid:] if from_end else text[:mid]
        if count_tokens(chunk) <= budget:
            low = mid
        else:
            high = mid - 1
    return low
