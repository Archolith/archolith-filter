"""Filesystem listing filter — compresses ls/dir/tree/find output with semantic awareness."""

from __future__ import annotations

import re

from dataclasses import dataclass

from . import FilterResult
from .generic import generic_filter, GenericFilterOptions, _extract_header


@dataclass(frozen=True)
class FsListingFilterOptions:
    max_entries: int = 50
    head_lines: int = 20
    tail_lines: int = 30


DEFAULT_OPTS = FsListingFilterOptions()

_IMPORTANT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^package\.json$", re.IGNORECASE),
    re.compile(r"^tsconfig\.json$", re.IGNORECASE),
    re.compile(r"^Cargo\.toml$", re.IGNORECASE),
    re.compile(r"^pyproject\.toml$", re.IGNORECASE),
    re.compile(r"^go\.mod$", re.IGNORECASE),
    re.compile(r"^Makefile$", re.IGNORECASE),
    re.compile(r"^Dockerfile$", re.IGNORECASE),
    re.compile(r"^docker-compose", re.IGNORECASE),
    re.compile(r"^\.env", re.IGNORECASE),
    re.compile(r"^README", re.IGNORECASE),
    re.compile(r"^CHANGELOG", re.IGNORECASE),
    re.compile(r"^LICENSE", re.IGNORECASE),
    re.compile(r"^\.gitignore$", re.IGNORECASE),
    re.compile(r"^\.gitmodules$", re.IGNORECASE),
    re.compile(r"^src$", re.IGNORECASE),
    re.compile(r"^lib$", re.IGNORECASE),
    re.compile(r"^test", re.IGNORECASE),
    re.compile(r"^spec", re.IGNORECASE),
    re.compile(r"^__tests__$", re.IGNORECASE),
    re.compile(r"^src/", re.IGNORECASE),
    re.compile(r"^lib/", re.IGNORECASE),
]

_ERROR_RE = re.compile(r"Permission denied|No such file|not found|cannot access|cannot open", re.IGNORECASE)


def _is_important_entry(entry: str) -> bool:
    basename = entry.rstrip("/").split("/")[-1] if "/" in entry else entry
    return any(p.match(basename) for p in _IMPORTANT_PATTERNS)


def fs_listing_filter(formatted: str, opts: FsListingFilterOptions | None = None) -> FilterResult:
    """Filter filesystem listing output with important-file preservation."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    lines = formatted.split("\n")
    header, body = _extract_header(lines)

    if not body:
        return FilterResult(output=formatted, raw_chars=raw_chars, filtered_chars=raw_chars, truncated=False)

    # Detect tree-style output: box-drawing characters.
    tree_style = any(
        re.match(r"^[\u2502\u251c\u2514\u2500\u250c\u2518\u2510]", ln)
        or re.search(r"\s[\u2502\u251c\u2514\u2500]", ln)
        for ln in body
    )

    preserved_errors = [ln for ln in body if _ERROR_RE.search(ln)]

    if tree_style:
        return generic_filter(
            formatted, GenericFilterOptions(head_lines=opts.head_lines, tail_lines=opts.tail_lines)
        )

    non_blank = [ln for ln in body if ln.strip() != ""]
    if len(non_blank) <= opts.max_entries:
        result = "\n".join(header + body)
        return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=False)

    important: list[str] = []
    regular: list[str] = []
    seen_important: set[str] = set()

    for ln in body:
        trimmed = ln.strip()
        if trimmed == "":
            regular.append(ln)
            continue
        if _is_important_entry(trimmed) and trimmed not in seen_important:
            important.append(ln)
            seen_important.add(trimmed)
        else:
            regular.append(ln)

    max_regular = opts.max_entries - len(important) - len(preserved_errors)
    head_regular = max(0, max_regular // 2)
    tail_regular = max(0, max_regular - head_regular)

    regular_non_blank = [ln for ln in regular if ln.strip() != ""]

    if len(regular_non_blank) <= max_regular:
        result = "\n".join(header + body)
        return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=False)

    kept_head = regular_non_blank[:head_regular]
    kept_tail = regular_non_blank[-tail_regular:]
    omitted = len(regular_non_blank) - head_regular - tail_regular

    parts = list(header)
    if important:
        parts.extend(important)
        parts.append("")
    parts.extend(kept_head)
    parts.extend(["", f"[... {omitted} entries omitted ...]", ""])
    parts.extend(kept_tail)
    for err in preserved_errors:
        if err not in parts:
            parts.append(err)

    result = "\n".join(parts)
    return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=True)
