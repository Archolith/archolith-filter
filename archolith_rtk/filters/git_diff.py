"""Git-diff filter — preserves stat summary + per-file diff headers with head/tail."""

from __future__ import annotations

from dataclasses import dataclass

from . import FilterResult
from .generic import _extract_header, generic_filter


@dataclass(frozen=True)
class GitDiffFilterOptions:
    file_head_lines: int = 15
    tail_lines: int = 20


DEFAULT_OPTS = GitDiffFilterOptions()


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

        # Keep header lines (diff --git, index, ---, +++, @@ ...) then head.
        header_lines: list[str] = []
        body_start = 0
        for i, ln in enumerate(section):
            if (
                ln.startswith("diff --git")
                or ln.startswith("diff --cc")
                or ln.startswith("index ")
                or ln.startswith("--- ")
                or ln.startswith("+++ ")
                or ln.startswith("@@")
                or ln.startswith("old mode")
                or ln.startswith("new mode")
                or ln.startswith("similarity index")
                or ln.startswith("rename from")
                or ln.startswith("rename to")
                or ln.startswith("copy from")
                or ln.startswith("copy to")
            ):
                header_lines.append(ln)
                body_start = i + 1
            else:
                break

        section_body = section[body_start:]
        head_count = max(0, opts.file_head_lines - len(header_lines))
        if len(section_body) <= head_count:
            out.extend(section)
        else:
            head = section_body[:head_count]
            omitted = len(section_body) - head_count
            out.extend(header_lines)
            out.extend(head)
            out.extend(["", f"[... {omitted} lines omitted in this file ...]", ""])

    # Append tail from the very end of the entire diff body.
    if opts.tail_lines > 0 and len(diff_lines) > opts.file_head_lines:
        tail = diff_lines[-opts.tail_lines :]
        if out and tail and out[-1] != tail[0]:
            out.extend(["", "--- tail ---"] + tail)

    return out


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
