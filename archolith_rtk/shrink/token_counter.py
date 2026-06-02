"""Token counting — tiktoken with char-heuristic fallback.

Lazy-loads tiktoken on first use; falls back to ~4 chars/token when unavailable.

Import DAG: leaf — no internal dependencies.
"""

from __future__ import annotations

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
