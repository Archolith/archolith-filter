"""Token counting — shared Archolith token accounting policy.

Import DAG: leaf — no internal dependencies beyond archolith-maintenance.
"""

from __future__ import annotations

import logging

from archolith_maintenance.token_accounting import (
    count_text_tokens,
    estimate_tokens_fallback,
    token_counts_are_estimated,
)

_fallback_warning_emitted = False

_log = logging.getLogger(__name__)

__all__ = ["count_tokens", "estimate_tokens_fallback", "token_counts_are_estimated"]


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken if available, else char heuristic.

    The fallback is shape-aware: prose uses the historical ~4 chars/token
    estimate, while code/config-like text uses ~3.2 chars/token. CJK text can
    still be undercounted; install ``archolith-filter[tokenizer]`` for
    accurate counts.
    """
    global _fallback_warning_emitted
    if token_counts_are_estimated() and not _fallback_warning_emitted:
        _log.warning(
            "tiktoken is unavailable; archolith-filter is using conservative "
            "heuristic token counts. Install archolith-filter[tokenizer] for "
            "accurate token budgeting."
        )
        _fallback_warning_emitted = True
    return count_text_tokens(text)
