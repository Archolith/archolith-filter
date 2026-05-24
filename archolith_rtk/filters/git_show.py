"""Git-show filter — preserves commit header + compresses the diff body."""

from __future__ import annotations

from dataclasses import dataclass

from . import FilterResult
from .generic import GenericFilterOptions, _extract_header, generic_filter
from .git_diff import GitDiffFilterOptions, git_diff_filter


@dataclass(frozen=True)
class GitShowFilterOptions:
    file_head_lines: int = 15
    tail_lines: int = 20


DEFAULT_OPTS = GitShowFilterOptions()


def git_show_filter(formatted: str, opts: GitShowFilterOptions | None = None) -> FilterResult:
    """Filter git show output: preserve commit header, compress the diff body."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    lines = formatted.split("\n")
    tool_header, body = _extract_header(lines)

    if not body:
        return FilterResult(output=formatted, raw_chars=raw_chars, filtered_chars=raw_chars, truncated=False)

    # Find where the commit header ends (before "diff --git").
    commit_header_end = 0
    for i, ln in enumerate(body):
        if ln.startswith("diff --git") or ln.startswith("diff --cc"):
            commit_header_end = i
            break

    if commit_header_end == 0:
        return generic_filter(formatted, GenericFilterOptions(head_lines=40, tail_lines=20))

    commit_header = body[:commit_header_end]
    diff_body = body[commit_header_end:]

    # Reconstruct a synthetic string for the diff filter.
    synthetic = "\n".join(tool_header + diff_body)
    diff_result = git_diff_filter(
        synthetic,
        GitDiffFilterOptions(file_head_lines=opts.file_head_lines, tail_lines=opts.tail_lines),
    )

    if not diff_result.truncated:
        return FilterResult(output=formatted, raw_chars=raw_chars, filtered_chars=raw_chars, truncated=False)

    # Reattach the commit header to the filtered diff output.
    filtered_lines = diff_result.output.split("\n")
    filtered_tool_header, filtered_body = _extract_header(filtered_lines)

    result = "\n".join(filtered_tool_header + commit_header + filtered_body)
    return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=True)
