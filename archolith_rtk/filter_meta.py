"""Filter metadata — exit code parsing, verbose flag detection, timeout detection."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FilterMeta:
    tool: str
    command: str
    exit_code: int | None = None
    timed_out: bool = False


_VERBOSE_FLAGS: list[re.Pattern[str]] = [
    re.compile(r"(?:^|\s)--verbose\b"),
    re.compile(r"(?:^|\s)-verbose\b"),
    re.compile(r"(?:^|\s)-v{2,}\b"),  # -vv, -vvv
    re.compile(r"(?:^|\s)--debug\b"),
    re.compile(r"(?:^|\s)--full\b"),
    re.compile(r"(?:^|\s)--detailed\b"),
    re.compile(r"(?:^|\s)--show-all\b"),
    re.compile(r"(?:^|\s)--no-summary\b"),
]


def is_verbose_command(command: str) -> bool:
    """Detect verbose/debug flags in a command string."""
    return any(p.search(command) for p in _VERBOSE_FLAGS)


def parse_result_meta(formatted: str, tool: str) -> tuple[int | None, bool]:
    """Extract exitCode and timedOut from a formatted result header.

    Returns (exit_code, timed_out).
    """
    if "[killed after timeout]" in formatted:
        return None, True

    exit_match = re.search(r"\[exit (\d+)\]", formatted)
    if exit_match:
        return int(exit_match.group(1)), False

    job_exit_match = re.search(r"(?:exited|exit) (\d+)", formatted)
    if job_exit_match:
        return int(job_exit_match.group(1)), False

    return None, False
