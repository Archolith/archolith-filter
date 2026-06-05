"""Log-output filter — compresses background job output with dedup and readiness preservation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..normalize import normalize_runtime_noise
from . import FilterResult


@dataclass(frozen=True)
class LogFilterOptions:
    head_lines: int = 15
    tail_lines: int = 30
    max_consecutive_dupes: int = 3
    normalize_noise_enabled: bool = True


DEFAULT_OPTS = LogFilterOptions()

_IMPORTANT_PATTERNS: list[re.Pattern[str]] = [
    # Readiness / server banners
    re.compile(r"\blistening on\b", re.IGNORECASE),
    re.compile(r"\blocal:\s+https?://", re.IGNORECASE),
    re.compile(r"\bhttps?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?\b", re.IGNORECASE),
    re.compile(r"\b(?:ready|server started|started server|app listening|compiled successfully)\b", re.IGNORECASE),
    re.compile(r"\bbuild complete(?:d)?\b", re.IGNORECASE),
    re.compile(r"\bready in \d+", re.IGNORECASE),
    re.compile(r"\bstartup (?:complete|finished)\b", re.IGNORECASE),
    # Errors and warnings
    re.compile(r"\b(error|fatal|critical|panic|abort|segfault|core dump)\b", re.IGNORECASE),
    re.compile(r"\b(warn(?:ing)?|deprecated|caution)\b", re.IGNORECASE),
    re.compile(r"\b(fail(?:ed|ure)?|exception|unhandled|uncaught)\b", re.IGNORECASE),
]


def _collapse_duplicate_runs(lines: list[str], max_dupes: int) -> list[str]:
    """Collapse consecutive duplicate lines, keeping up to max_dupes copies."""
    if max_dupes <= 0:
        return lines

    out: list[str] = []
    i = 0
    while i < len(lines):
        current = lines[i]
        run_len = 1
        while i + run_len < len(lines) and lines[i + run_len] == current:
            run_len += 1
        if run_len <= max_dupes:
            for _ in range(run_len):
                out.append(current)
        else:
            for _ in range(max_dupes):
                out.append(current)
            omitted = run_len - max_dupes
            out.append(f"[... {omitted} repeated lines omitted ...]")
        i += run_len
    return out


def _extract_important_lines(lines: list[str]) -> list[str]:
    """Extract lines matching readiness/error/warning patterns."""
    return [ln for ln in lines if any(p.search(ln) for p in _IMPORTANT_PATTERNS)]


def _extract_job_header(lines: list[str]) -> tuple[list[str], list[str]]:
    """Separate job header lines from the body."""
    header_end = 0
    for i, ln in enumerate(lines):
        if ln.startswith("[job") or ln.startswith("$ ") or ln == "":
            header_end = i + 1
        else:
            break
    return lines[:header_end], lines[header_end:]


def log_filter(formatted: str, opts: LogFilterOptions | None = None) -> FilterResult:
    """Filter log output from background jobs with dedup and readiness preservation."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    # Normalize runtime noise (timestamps, PIDs, etc.) before filtering.
    if opts.normalize_noise_enabled:
        formatted = normalize_runtime_noise(formatted)

    lines = formatted.split("\n")
    header, body = _extract_job_header(lines)

    deduped_body = _collapse_duplicate_runs(body, opts.max_consecutive_dupes)

    if len(deduped_body) <= opts.head_lines + opts.tail_lines:
        result = "\n".join(header + deduped_body)
        return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=False)

    important_lines = _extract_important_lines(deduped_body)

    head = deduped_body[: opts.head_lines]
    tail = deduped_body[-opts.tail_lines :]
    window_set = set(head + tail)

    lost_important = [ln for ln in important_lines if ln not in window_set]
    omitted = len(deduped_body) - opts.head_lines - opts.tail_lines
    marker = f"[... {omitted} lines omitted ...]"

    if lost_important:
        important_section = ["", "Important lines from omitted output:"] + lost_important
        result = "\n".join(header + head + ["", marker] + important_section + [""] + tail)
    else:
        result = "\n".join(header + head + ["", marker, ""] + tail)

    return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=True)
