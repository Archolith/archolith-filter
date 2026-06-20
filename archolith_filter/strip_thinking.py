"""Thinking block stripping — remove model-internal reasoning tags from tool output.

Strips ``<thinking>``, ``<antThinking>``, ``<reasoning>``, ``<scratchpad>``,
and ``<inner_monologue>`` blocks (including content and closing tags).
Also handles unclosed blocks (opening tag with no closing tag) and
dangling partial close-tag fragments left by stream cutoff.

The patterns accept an optional XML namespace prefix on any known tag
(e.g. ``<antml:thinking>``, ``<anthropic:reasoning>``) so future-proofs
the filter against vendor tag variations.

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

# Optional XML namespace prefix on any tag (e.g. "antml:", "anthropic:").
# Allows vendor-prefixed variants such as <antml:thinking> without enumerating
# every vendor's prefix explicitly.
_NS_PREFIX = r"(?:[a-zA-Z][a-zA-Z0-9_-]*:)?"

# Open-tag fragment: <tag> or <ns:tag>
_OPEN_RE_PART = rf"<{_NS_PREFIX}(?:{_TAG_ALT})>"
# Close-tag fragment: </tag> or </ns:tag>
_CLOSE_RE_PART = rf"</{_NS_PREFIX}(?:{_TAG_ALT})>"

# Closed blocks: <tag>...</tag>  (case-insensitive, dot matches newline).
# The inner content uses a negative lookahead for any OPEN tag so that
# the engine prefers the innermost closed pair (rather than greedily
# pairing an outer open with the first close-tag of any known name).
# Without this, nested constructs like
#   `<thinking>outer <reasoning>inner</reasoning> between</thinking>`
# cross-pair: the outer <thinking> pairs with </reasoning>, leaving the
# outer </thinking> orphaned. The negative lookahead forces pairing by
# tag-balance: the engine backs off and finds the shortest closed pair
# that does not straddle another open tag, so the loop-until-stable pass
# unwinds nesting correctly.
_INNER_CONTENT = rf"(?:(?!{_OPEN_RE_PART}).)*?"

_CLOSED_RE = re.compile(
    rf"{_OPEN_RE_PART}{_INNER_CONTENT}{_CLOSE_RE_PART}",
    re.IGNORECASE | re.DOTALL,
)

# Unclosed blocks: <tag>... to end of string.
_UNCLOSED_RE = re.compile(
    rf"{_OPEN_RE_PART}.*",
    re.IGNORECASE | re.DOTALL,
)

# Dangling partial close-tag fragment at EOF — e.g. ``</thinking`` (no closing
# ``>``) or ``</antml:thinking`` left behind when a stream was cut off
# mid-tag. Matches a partial close tag for any known tag name with optional
# namespace, anchored via lookahead to either an immediate ``>`` or end-of-
# string. Defended against matching legitimate markup by requiring the
# lookahead.
_DANGLING_CLOSE_RE = re.compile(
    rf"</{_NS_PREFIX}(?:{_TAG_ALT})(?:\s[^<>]*)?(?=>|$)",
    re.IGNORECASE | re.DOTALL,
)

# Collapse 3+ consecutive newlines down to 2.
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")

# Maximum iterations for the closed-block loop. Defends against pathological
# inputs that keep matching themselves; 10 is well above realistic nesting
# depth for reasoning tags.
_MAX_STABLE_ITERATIONS = 10


def strip_thinking_blocks(text: str) -> str:
    """Remove model-internal thinking/reasoning blocks from *text*.

    Both closed (``<tag>...</tag>``) and unclosed (``<tag>...`` to end)
    blocks are removed entirely. Namespace-prefixed variants
    (``<antml:thinking>``, ``<anthropic:reasoning>``) are removed too.
    Nested blocks are unwound by looping the closed-block sub until the
    output stabilises (capped at ``_MAX_STABLE_ITERATIONS``).
    Dangling partial close-tag fragments left by stream cutoff are
    stripped in a final cleanup pass. Excess blank lines from removal
    are collapsed to double newlines.
    """
    # Loop closed-block sub until stable to handle nested constructs.
    previous = None
    current = text
    iterations = 0
    while previous != current and iterations < _MAX_STABLE_ITERATIONS:
        previous = current
        current = _CLOSED_RE.sub("", current)
        iterations += 1

    # Remove unclosed blocks (opening tag with no closing tag).
    current = _UNCLOSED_RE.sub("", current)

    # Strip dangling partial close-tag fragments from stream cutoff (AI-B3).
    current = _DANGLING_CLOSE_RE.sub("", current)

    # Collapse excess blank lines from removal.
    current = _EXCESS_NEWLINES_RE.sub("\n\n", current)

    # Strip leading/trailing whitespace if non-empty.
    if current:
        current = current.strip() if current.strip() else current
    return current
