"""Thinking block stripping — remove model-internal reasoning tags from tool output.

Strips ``<thinking>``, ``<antThinking>``, ``<reasoning>``, ``<scratchpad>``,
and ``<inner_monologue>`` blocks (including content and closing tags).
Also handles unclosed blocks (opening tag with no closing tag).
Case-insensitive matching.
"""

from __future__ import annotations

import re

# All known model-internal reasoning tag names.
_TAG_NAMES = [
    "thinking",
    "antThinking",
    "reasoning",
    "scratchpad",
    "inner_monologue",
]

# Build alternation of tag names for regex.
_TAG_ALT = "|".join(re.escape(t) for t in _TAG_NAMES)

# Closed blocks: <tag>...</tag>  (case-insensitive, dot matches newline)
_CLOSED_RE = re.compile(
    rf"<(?:{_TAG_ALT})>.*?</(?:{_TAG_ALT})>",
    re.IGNORECASE | re.DOTALL,
)

# Unclosed blocks: <tag>... to end of string
_UNCLOSED_RE = re.compile(
    rf"<(?:{_TAG_ALT})>.*",
    re.IGNORECASE | re.DOTALL,
)

# Collapse 3+ consecutive newlines down to 2.
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


def strip_thinking_blocks(text: str) -> str:
    """Remove model-internal thinking/reasoning blocks from *text*.

    Both closed (``<tag>...</tag>``) and unclosed (``<tag>...`` to end)
    blocks are removed entirely. Excess blank lines from removal are
    collapsed to double newlines.
    """
    # Remove closed blocks first.
    result = _CLOSED_RE.sub("", text)
    # Remove unclosed blocks (opening tag with no closing tag).
    result = _UNCLOSED_RE.sub("", result)
    # Collapse excess blank lines from removal.
    result = _EXCESS_NEWLINES_RE.sub("\n\n", result)
    # Strip leading/trailing whitespace if non-empty.
    if result:
        result = result.strip() if result.strip() else result
    return result
