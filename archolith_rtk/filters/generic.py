"""Generic head+tail filter — baseline for all command categories."""

from __future__ import annotations

from dataclasses import dataclass

from . import FilterResult


@dataclass(frozen=True)
class GenericFilterOptions:
    head_lines: int = 20
    tail_lines: int = 30


DEFAULT_OPTS = GenericFilterOptions()


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    """Collapse runs of 2+ blank lines into a single blank line."""
    out: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        out.append(line)
        prev_blank = is_blank
    return out


def _extract_header(lines: list[str]) -> tuple[list[str], list[str]]:
    """Separate header lines (starting with '$ ' or '[') from the body."""
    header_end = 0
    for i, ln in enumerate(lines):
        if ln.startswith("$ ") or ln.startswith("[") or ln == "":
            header_end = i + 1
        else:
            break
    return lines[:header_end], lines[header_end:]


def generic_filter(formatted: str, opts: GenericFilterOptions | None = None) -> FilterResult:
    """Apply generic head+tail windowing with collapsed blanks and omission marker."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    lines = formatted.split("\n")
    header, body = _extract_header(lines)
    collapsed_body = _collapse_blank_lines(body)

    # No truncation needed if body fits within the window.
    if len(collapsed_body) <= opts.head_lines + opts.tail_lines:
        result = "\n".join(header + collapsed_body)
        return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=False)

    head = collapsed_body[: opts.head_lines]
    tail = collapsed_body[-opts.tail_lines :]
    omitted = len(collapsed_body) - opts.head_lines - opts.tail_lines
    marker = f"[... {omitted} lines omitted ...]"

    result = "\n".join(header + head + ["", marker, ""] + tail)
    return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=True)
