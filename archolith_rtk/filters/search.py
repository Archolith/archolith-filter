"""Search result filter — compresses grep/rg/findstr/ag/ack output with match grouping."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import FilterResult
from .generic import GenericFilterOptions, _extract_header, generic_filter


@dataclass(frozen=True)
class SearchFilterOptions:
    max_matches_per_file: int = 5
    max_files: int = 15
    head_lines: int = 20
    tail_lines: int = 30


DEFAULT_OPTS = SearchFilterOptions()


class _FileGroup:
    __slots__ = ("path", "lines", "is_heading")

    def __init__(self, path: str, is_heading: bool = False) -> None:
        self.path = path
        self.is_heading = is_heading
        self.lines: list[str] = []


_INLINE_PATH_RE = re.compile(r"^([^:\s]+?):(\d+[:-])")
_HEADING_PATH_RE = re.compile(r"^[^\s:][^\s]*[^\s:](?::?$)")
_HEADING_MATCH_RE = re.compile(r"^\d+[:-]")


def _next_non_blank_line(lines: list[str], start: int) -> str | None:
    """Return the next non-blank line after ``start``."""
    for line in lines[start:]:
        if line.strip() != "":
            return line
    return None


def _is_heading_path_line(line: str, next_non_blank: str | None) -> bool:
    """Detect ``rg --heading`` path lines, including paths that contain digits."""
    trimmed = line.strip()
    if trimmed == "" or _INLINE_PATH_RE.match(trimmed):
        return False
    if trimmed.endswith(":"):
        return True
    return bool(next_non_blank and _HEADING_MATCH_RE.match(next_non_blank.strip()))


def _group_by_file(body_lines: list[str]) -> list[_FileGroup]:
    """Parse search output into per-file groups."""
    groups: list[_FileGroup] = []
    current_path = ""
    current_lines: list[str] = []
    current_is_heading = False

    def flush_current_group() -> None:
        if current_path and current_lines:
            group = _FileGroup(current_path, is_heading=current_is_heading)
            group.lines = list(current_lines)
            groups.append(group)

    for index, ln in enumerate(body_lines):
        trimmed = ln.strip()

        if trimmed == "":
            continue

        # Heading-mode path (rg --heading): line is just a path, possibly with trailing colon.
        next_non_blank = _next_non_blank_line(body_lines, index + 1)
        if _HEADING_PATH_RE.match(trimmed) and _is_heading_path_line(ln, next_non_blank):
            candidate_path = trimmed.rstrip(":")
            flush_current_group()
            current_path = candidate_path
            current_lines = []
            current_is_heading = True
            continue

        # Inline path:number:content
        inline_match = _INLINE_PATH_RE.match(trimmed)
        if inline_match:
            file_path = inline_match.group(1)
            if file_path != current_path:
                flush_current_group()
                current_path = file_path
                current_lines = [ln]
                current_is_heading = False
            else:
                current_lines.append(ln)
            continue

        # Fallback
        if current_path:
            current_lines.append(ln)
        else:
            current_path = "(unsorted)"
            current_lines = [ln]
            current_is_heading = False

    flush_current_group()

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

    # Check for inline search-pattern lines (path:lineNumber:content) or
    # heading-mode output (rg --heading).
    has_search_pattern = any(
        ln.strip() != "" and re.search(r"[^:\s]+:\d+[:-]", ln) for ln in body
    )
    has_heading_mode = any(
        _HEADING_PATH_RE.match(ln.strip())
        and _is_heading_path_line(ln, _next_non_blank_line(body, index + 1))
        for index, ln in enumerate(body)
        if ln.strip() != ""
    )

    if not has_search_pattern and not has_heading_mode:
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
        if groups[i].is_heading:
            parts.append(groups[i].path)
        parts.extend(compressed)

    if len(groups) > opts.max_files:
        omitted_files = len(groups) - opts.max_files
        omitted_matches = sum(len(g.lines) for g in groups[opts.max_files :])
        parts.extend(["", f"[... {omitted_files} more files with {omitted_matches} matches omitted ...]"])

    result = "\n".join(parts)
    return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=True)
