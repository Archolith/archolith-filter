"""Filter result data structure shared by all filters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FilterResult:
    """Result of applying a filter to tool output."""

    output: str
    raw_chars: int
    filtered_chars: int
    truncated: bool


__all__ = ["FilterResult"]
