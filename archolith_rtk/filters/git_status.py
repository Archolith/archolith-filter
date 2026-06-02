"""Git-status filter — keeps short-status intact, compresses long format.

Strategy 6: Groups short-format files by directory + status code
when enabled, producing more compact output than per-file lines.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from . import FilterResult
from .generic import GenericFilterOptions, _extract_header, generic_filter


@dataclass(frozen=True)
class GitStatusFilterOptions:
    head_lines: int = 50
    tail_lines: int = 30
    group_enabled: bool = True
    group_max_per_line: int = 10


DEFAULT_OPTS = GitStatusFilterOptions()

_SHORT_STATUS_RE = re.compile(r"^([A-Z? !]{2})\s+(.+)$")


def _group_short_status(lines: list[str], max_per_line: int) -> list[str] | None:
    """Group short-format status lines by (status_code, directory).

    Files sharing the same status code and directory are combined into
    one line:  ``M src/auth/ handler.ts, session.ts, middleware.ts``

    Returns None if any line doesn't match the short-status pattern.
    """
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    order: list[tuple[str, str]] = []  # preserve first-seen order

    for line in lines:
        match = _SHORT_STATUS_RE.match(line.strip())
        if match:
            status = match.group(1)
            path = match.group(2).strip()
            # Split into directory + filename
            if "/" in path:
                slash_idx = path.rfind("/")
                directory = path[: slash_idx + 1]
                filename = path[slash_idx + 1 :]
            else:
                directory = ""
                filename = path
            key = (status, directory)
            if key not in groups:
                order.append(key)
            groups[key].append(filename)
        else:
            # Not a short-status line — can't group
            return None

    result: list[str] = []
    for status, directory in order:
        filenames = groups[(status, directory)]
        if len(filenames) == 1:
            # Single file: keep compact
            if directory:
                result.append(f"{status} {directory}{filenames[0]}")
            else:
                result.append(f"{status} {filenames[0]}")
        else:
            # Multiple files: group on one line
            display = ", ".join(filenames[:max_per_line])
            remaining = len(filenames) - max_per_line
            if remaining > 0:
                display += f", +{remaining} more"
            if directory:
                result.append(f"{status} {directory}{display}")
            else:
                result.append(f"{status} {display}")

    return result


def git_status_filter(formatted: str, opts: GitStatusFilterOptions | None = None) -> FilterResult:
    """Filter git status output.

    Short-format (-s) output is grouped by directory + status code
    when group_enabled is True. Long-format falls to generic.
    """
    if opts is None:
        opts = DEFAULT_OPTS

    lines = formatted.split("\n")
    _, body = _extract_header(lines)

    if not body:
        return FilterResult(
            output=formatted, raw_chars=len(formatted), filtered_chars=len(formatted), truncated=False
        )

    non_blank = next((ln for ln in body if ln.strip() != ""), None)
    if non_blank and _SHORT_STATUS_RE.match(non_blank):
        # Short-format detected — try grouping if enabled
        if opts.group_enabled:
            grouped = _group_short_status(body, opts.group_max_per_line)
            if grouped is not None:
                # Check that grouping actually shortened the output
                grouped_text = "\n".join(grouped)
                original_len = sum(len(ln) for ln in body if ln.strip())
                grouped_len = sum(len(ln) for ln in grouped if ln.strip())
                if grouped_len <= original_len:
                    header_text = "\n".join(_extract_header(lines)[0])
                    if header_text:
                        result = header_text + "\n" + grouped_text
                    else:
                        result = grouped_text
                    truncated = len(result) < len(formatted)
                    return FilterResult(
                        output=result, raw_chars=len(formatted), filtered_chars=len(result), truncated=truncated
                    )
        # Grouping not enabled or didn't help — fall through to generic
        return generic_filter(
            formatted, GenericFilterOptions(head_lines=opts.head_lines, tail_lines=opts.tail_lines)
        )

    return generic_filter(formatted)
