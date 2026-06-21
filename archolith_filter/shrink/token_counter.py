"""Token counting — tiktoken with conservative heuristic fallback.

Lazy-loads tiktoken on first use; falls back to shape-aware char heuristics
when unavailable.

Import DAG: leaf — no internal dependencies.
"""

from __future__ import annotations

import logging
import math
import re

_count_tokens_fn = None
_tokenizer_unavailable = False
_fallback_warning_emitted = False

_log = logging.getLogger(__name__)

_PROSE_CHARS_PER_TOKEN = 4.0
_CODE_CHARS_PER_TOKEN = 3.2
_CODE_KEYWORD_RE = re.compile(
    r"\b(?:class|def|function|const|let|var|import|from|return|if|else|for|while|try|except|async|await)\b"
)
_CODE_SYMBOLS = frozenset("{}[]();=<>|&")


def _get_token_counter():
    """Lazy-load tiktoken; return None if unavailable."""
    global _count_tokens_fn, _tokenizer_unavailable
    if _count_tokens_fn is not None:
        return _count_tokens_fn
    if _tokenizer_unavailable:
        return None
    try:
        import tiktoken

        _enc = tiktoken.get_encoding("cl100k_base")

        def _count(text: str) -> int:
            return len(_enc.encode(text))

        _count_tokens_fn = _count
        return _count_tokens_fn
    except ImportError:
        _tokenizer_unavailable = True
        return None


def token_counts_are_estimated() -> bool:
    """Return True when token counts use the fallback heuristic."""
    return _get_token_counter() is None


def _looks_code_like(text: str) -> bool:
    """Heuristic signal for code/config-heavy text."""
    if not text:
        return False
    newline_count = text.count("\n")
    symbol_count = sum(1 for ch in text if ch in _CODE_SYMBOLS)
    symbol_ratio = symbol_count / max(1, len(text))
    return (
        (newline_count >= 2 and bool(_CODE_KEYWORD_RE.search(text)))
        or symbol_ratio >= 0.08
        or "```" in text
    )


def estimate_tokens_fallback(text: str) -> int:
    """Fallback token estimate used when tiktoken is unavailable.

    Prose keeps the historical 4 chars/token heuristic. Code and
    punctuation-heavy content use a more conservative 3.2 chars/token estimate
    to reduce standalone over-budget errors.
    """
    if not text:
        return 0
    if _looks_code_like(text):
        return max(1, math.ceil(len(text) / _CODE_CHARS_PER_TOKEN))
    return max(1, len(text) // int(_PROSE_CHARS_PER_TOKEN))


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken if available, else char heuristic.

    The fallback is shape-aware: prose uses the historical ~4 chars/token
    estimate, while code/config-like text uses ~3.2 chars/token. CJK text can
    still be undercounted; install ``archolith-filter[tokenizer]`` for
    accurate counts.
    """
    global _fallback_warning_emitted
    counter = _get_token_counter()
    if counter is not None:
        return counter(text)
    if not _fallback_warning_emitted:
        _log.warning(
            "tiktoken is unavailable; archolith-filter is using conservative "
            "heuristic token counts. Install archolith-filter[tokenizer] for "
            "accurate token budgeting."
        )
        _fallback_warning_emitted = True
    return estimate_tokens_fallback(text)
