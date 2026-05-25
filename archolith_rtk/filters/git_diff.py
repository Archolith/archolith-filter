"""Git-diff filter — preserves stat summary + per-file diff headers with head/tail."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from . import FilterResult
from .generic import _extract_header, generic_filter


@dataclass(frozen=True)
class GitDiffFilterOptions:
    file_head_lines: int = 15
    tail_lines: int = 20


DEFAULT_OPTS = GitDiffFilterOptions()

_DIFF_HEADER_PREFIXES = (
    "diff --git",
    "diff --cc",
    "index ",
    "--- ",
    "+++ ",
    "@@",
    "old mode",
    "new mode",
    "similarity index",
    "rename from",
    "rename to",
    "copy from",
    "copy to",
    "deleted file mode",
    "new file mode",
)


def _split_stat_and_diff(body: list[str]) -> tuple[list[str], list[str]]:
    """Split body into stat-block lines and diff-content lines."""
    stat_lines: list[str] = []
    diff_lines: list[str] = []
    past_stat = False

    for line in body:
        if not past_stat:
            if line.startswith("diff --git") or line.startswith("diff --cc"):
                past_stat = True
                diff_lines.append(line)
            else:
                stat_lines.append(line)
        else:
            diff_lines.append(line)

    return stat_lines, diff_lines


def _compress_diff_body(diff_lines: list[str], opts: GitDiffFilterOptions) -> list[str]:
    """Compress diff body: keep per-file headers, show head/tail per section."""
    # Split into file sections by "diff --git" boundaries.
    sections: list[list[str]] = []
    current: list[str] = []

    for line in diff_lines:
        if line.startswith("diff --git") or line.startswith("diff --cc"):
            if current:
                sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)

    out: list[str] = []

    for section in sections:
        if len(section) <= opts.file_head_lines:
            out.extend(section)
            continue

        header_lines: list[str] = []
        body_start = 0
        for i, ln in enumerate(section):
            if ln.startswith(_DIFF_HEADER_PREFIXES):
                header_lines.append(ln)
                body_start = i + 1
            else:
                break

        section_body = section[body_start:]
        if len(section_body) <= 3:
            out.extend(section)
            continue

        preview = _select_preview_lines(section_body, opts.file_head_lines)
        omitted = len(section_body) - len(preview)
        if omitted <= 0:
            out.extend(section)
        else:
            out.extend(header_lines)
            out.extend(preview)
            out.extend(["", f"[... {omitted} lines omitted in this file ...]", ""])

    return out


def _select_preview_lines(section_body: list[str], file_head_lines: int) -> list[str]:
    """Select a compact representative preview from a file diff body.

    Prefer changed lines over surrounding context and keep head/tail samples
    so the preview shows both the start and end of the file's changes.
    Uses a proportional budget derived from file_head_lines to balance
    compression and signal retention.
    """
    signal_positions = [
        index
        for index, line in enumerate(section_body)
        if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---"))
    ]

    if not signal_positions:
        preview_budget = max(2, ceil(file_head_lines / 3))
        if len(section_body) <= preview_budget:
            return section_body
        head_keep = max(1, preview_budget - 1)
        keep_positions = list(range(head_keep))
        keep_positions.append(len(section_body) - 1)
        return [section_body[index] for index in sorted(set(keep_positions))]

    preview_budget = max(2, ceil(file_head_lines / 3))

    if len(signal_positions) <= preview_budget:
        keep_positions = signal_positions
    else:
        head_keep = max(1, preview_budget // 2)
        tail_keep = max(1, preview_budget - head_keep)
        head_slice = signal_positions[:head_keep]
        tail_slice = signal_positions[-tail_keep:]
        keep_positions = head_slice + tail_slice

    return [section_body[index] for index in sorted(set(keep_positions))]


def git_diff_filter(formatted: str, opts: GitDiffFilterOptions | None = None) -> FilterResult:
    """Filter git diff output: keep stat block + per-file headers + head/tail of diff body."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    lines = formatted.split("\n")
    header, body = _extract_header(lines)
    stat_lines, diff_lines = _split_stat_and_diff(body)

    if not diff_lines:
        return generic_filter(formatted)

    combined = stat_lines + diff_lines
    if len(combined) <= opts.file_head_lines + opts.tail_lines + len(stat_lines):
        result = "\n".join(header + combined)
        return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=False)

    compressed = _compress_diff_body(diff_lines, opts)
    result = "\n".join(header + stat_lines + compressed)
    return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=True)
