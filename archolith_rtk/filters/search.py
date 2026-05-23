"""Search result filter — compresses grep/rg/findstr/ag/ack output with match grouping."""

from __future__ import annotations

import re

from dataclasses import dataclass

from . import FilterResult
from .generic import generic_filter, GenericFilterOptions, _extract_header


@dataclass(frozen=True)
class SearchFilterOptions:
    max_matches_per_file: int = 5
    max_files: int = 15
    head_lines: int = 20
    tail_lines: int = 30


DEFAULT_OPTS = SearchFilterOptions()


class _FileGroup:
    __slots__ = ("path", "lines")

    def __init__(self, path: str) -> None:
        self.path = path
        self.lines: list[str] = []


_INLINE_PATH_RE = re.compile(r"^([^:\s]+?):(\d+[:-])")
_HEADING_PATH_RE = re.compile(r"^[^\s:][^\s]*[^\s:](?::?$)")


def _group_by_file(body_lines: list[str]) -> list[_FileGroup]:
    """Parse search output into per-file groups."""
    groups: list[_FileGroup] = []
    current_path = ""
    current_lines: list[str] = []

    for ln in body_lines:
        trimmed = ln.strip()

        if trimmed == "":
            if current_path:
                current_lines.append(ln)
            continue

        # Heading-mode path (rg --heading): line is just a path, possibly with trailing colon.
        if _HEADING_PATH_RE.match(trimmed) and not _INLINE_PATH_RE.match(trimmed):
            candidate_path = trimmed.rstrip(":")
            if not re.search(r"\d", trimmed) or trimmed.endswith(":"):
                if current_path and current_lines:
                    groups.append(_FileGroup(current_path))
                    groups[-1].lines = list(current_lines)
                current_path = candidate_path
                current_lines = []
                continue

        # Inline path:number:content
        inline_match = _INLINE_PATH_RE.match(trimmed)
        if inline_match:
            file_path = inline_match.group(1)
            if file_path != current_path:
                if current_path and current_lines:
                    groups.append(_FileGroup(current_path))
                    groups[-1].lines = list(current_lines)
                current_path = file_path
                current_lines = [ln]
            else:
                current_lines.append(ln)
            continue

        # Fallback
        if current_path:
            current_lines.append(ln)
        else:
            current_path = "(unsorted)"
            current_lines = [ln]

    if current_path and current_lines:
        groups.append(_FileGroup(current_path))
        groups[-1].lines = list(current_lines)

    return groups


def _compress_file_group(group: _FileGroup, max_matches: int) -> list[str]:
    """Keep up to max_matches match lines; summarize the rest."""
    if len(group.lines) <= max_matches:
        return group.lines

    kept = group.lines[:max_matches]
    omitted = len(group.lines) - max_matches
    return [*kept, f"  [... {omitted} more matches in {group.path} ...]"]


def search_filter(formatted: str, opts: SearchFilterOptions | None = None) -> FilterResult:
    """Filter search command output with file grouping and match capping."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    lines = formatted.split("\n")
    header, body = _extract_header(lines)

    if not body:
        return FilterResult(output=formatted, raw_chars=raw_chars, filtered_chars=raw_chars, truncated=False)

    # Check for search-pattern lines (path:lineNumber:content).
    has_search_pattern = any(
        ln.strip() != "" and re.search(r"[^:\s]+:\d+[:-]", ln) for ln in body
    )

    if not has_search_pattern:
        non_blank = [ln for ln in body if ln.strip() != ""]
        if len(non_blank) <= 3:
            return FilterResult(
                output=formatted, raw_chars=raw_chars, filtered_chars=raw_chars, truncated=False
            )
        return generic_filter(
            formatted, GenericFilterOptions(head_lines=opts.head_lines, tail_lines=opts.tail_lines)
        )

    groups = _group_by_file(body)

    if not groups:
        return FilterResult(output=formatted, raw_chars=raw_chars, filtered_chars=raw_chars, truncated=False)

    total_match_lines = sum(len(g.lines) for g in groups)
    any_file_exceeds = any(len(g.lines) > opts.max_matches_per_file for g in groups)
    if (
        len(groups) <= opts.max_files
        and total_match_lines <= opts.max_files * opts.max_matches_per_file
        and not any_file_exceeds
    ):
        return FilterResult(output=formatted, raw_chars=raw_chars, filtered_chars=raw_chars, truncated=False)

    compressed_groups = [
        _compress_file_group(g, opts.max_matches_per_file) for g in groups[: opts.max_files]
    ]

    parts = list(header)
    for i, compressed in enumerate(compressed_groups):
        if i > 0 and groups[i].path != groups[i - 1].path:
            parts.append("")
        parts.extend(compressed)

    if len(groups) > opts.max_files:
        omitted_files = len(groups) - opts.max_files
        omitted_matches = sum(len(g.lines) for g in groups[opts.max_files :])
        parts.extend(["", f"[... {omitted_files} more files with {omitted_matches} matches omitted ...]"])

    result = "\n".join(parts)
    return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=True)
