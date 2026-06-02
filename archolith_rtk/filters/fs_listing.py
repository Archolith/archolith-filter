"""Filesystem listing filter — compresses ls/dir/tree/find output with semantic awareness.

Strategy 9: When ls -la/l output is detected, parse columns and emit
abbreviated form (name, type hint, human-readable size) instead of
full permission/owner/group/timestamp columns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import FilterResult
from .generic import GenericFilterOptions, _extract_header, generic_filter


@dataclass(frozen=True)
class FsListingFilterOptions:
    max_entries: int = 50
    head_lines: int = 20
    tail_lines: int = 30
    lsl_abbreviate_enabled: bool = True


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

# ls -la line pattern: permissions, hard links, owner, group, size, date, name
_LS_LINE_RE = re.compile(
    r"^([dlcbps-][-rwxsStT]{9})"  # permissions (10 chars)
    r"\s+(\d+)"  # hard links
    r"\s+(\S+)"  # owner
    r"\s+(\S+)"  # group
    r"\s+(\d+)"  # size in bytes
    r"\s+(.+)"  # date + name (rest of line)
    r"$"
)

_LS_TOTAL_RE = re.compile(r"^total\s+\d+")

# ls -la date pattern: "Mon DD HH:MM" or "Mon DD  YYYY" or "Mon DD YYYY "
_LS_DATE_RE = re.compile(
    r"\s+\d{1,2}\s+\d{2}:\d{2}(?=\s)|\s+\d{1,2}\s+\d{4}(?=\s)"
)


def _is_important_entry(entry: str) -> bool:
    basename = entry.rstrip("/").split("/")[-1] if "/" in entry else entry
    return any(p.match(basename) for p in _IMPORTANT_PATTERNS)


def _human_readable_size(size_bytes: int) -> str:
    """Convert byte count to human-readable size string."""
    if size_bytes < 1024:
        return str(size_bytes)
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}K"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}M"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f}G"


def _abbreviate_ls_line(line: str) -> str:
    """Convert a single ls -la line to abbreviated form.

    drwxr-xr-x  5 thron staff  160 May 26 14:30 src
    →  src/             (dir, 5 entries)

    -rw-r--r--  1 thron staff  4205 May 26 14:30 package.json
    →  package.json     4.2K
    """
    match = _LS_LINE_RE.match(line.strip())
    if not match:
        return line  # Not a parseable ls line — return as-is

    perms = match.group(1)
    links = int(match.group(2))
    size = int(match.group(5))
    date_and_name = match.group(6)

    # Split date_and_name into date portion and filename
    # Date format: "Mon DD HH:MM" or "Mon DD  YYYY"
    # Find where the date ends and filename begins
    name = date_and_name
    date_match = _LS_DATE_RE.search(date_and_name)
    if date_match:
        # Filename starts after the date match
        end_pos = date_match.end()
        name = date_and_name[end_pos:].strip()
    else:
        # Fallback: try to split at the last space before a non-numeric portion
        # This handles "May 26 14:30 filename" → filename
        parts = date_and_name.split()
        if len(parts) >= 4:
            name = " ".join(parts[3:])
        else:
            name = date_and_name

    # Handle symlinks: "foo -> bar"
    symlink_target = ""
    if " -> " in name:
        name, symlink_target = name.split(" -> ", 1)

    is_dir = perms.startswith("d")

    # Build abbreviated line
    if is_dir:
        abbr = f"{name}/             (dir"
        if links > 2:  # . and .. are minimum, >2 means more entries
            abbr += f", {links - 2} entries"  # links-2 ≈ number of items
        abbr += ")"
    else:
        abbr = f"{name}     {_human_readable_size(size)}"

    if symlink_target:
        abbr += f" -> {symlink_target}"

    return abbr


def fs_listing_filter(formatted: str, opts: FsListingFilterOptions | None = None) -> FilterResult:
    """Filter filesystem listing output with important-file preservation.

    Strategy 9: When lsl_abbreviate_enabled and ls -la/l output is detected,
    abbreviate permission/owner/group/timestamp columns.
    """
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

    # Strategy 9: detect ls -la/l output and abbreviate
    if opts.lsl_abbreviate_enabled:
        ls_lines = [ln for ln in body if ln.strip() and not _LS_TOTAL_RE.match(ln.strip())]
        ls_parseable_count = sum(1 for ln in ls_lines if _LS_LINE_RE.match(ln.strip()))
        # If >= 60% of non-blank body lines are ls -la format, abbreviate
        non_blank = [ln for ln in body if ln.strip() != ""]
        if len(ls_lines) >= 3 and ls_parseable_count / max(len(non_blank), 1) >= 0.6:
            abbreviated: list[str] = list(header)
            total_lines = [ln for ln in body if _LS_TOTAL_RE.match(ln.strip())]
            if total_lines:
                abbreviated.append(total_lines[0].strip())
            for ln in body:
                if ln.strip() == "":
                    abbreviated.append("")
                    continue
                if _ERROR_RE.search(ln):
                    abbreviated.append(ln)
                    continue
                if _LS_TOTAL_RE.match(ln.strip()):
                    continue  # Already handled above
                abbreviated.append(_abbreviate_ls_line(ln))

            result = "\n".join(abbreviated)
            truncated = len(result) < raw_chars
            return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=truncated)

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
