"""Build-output filter — compresses verbose compilation output.

Strategy 8: For successful build output, detect Gradle/Maven task lines
and emit a compact summary instead of the full task list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import FilterResult
from .generic import GenericFilterOptions, generic_filter


@dataclass(frozen=True)
class BuildFilterOptions:
    head_lines: int = 15
    tail_lines: int = 25
    summary_enabled: bool = True


DEFAULT_OPTS = BuildFilterOptions()

# Gradle: "> Task :compileJava", "> Task :test"
_GRADLE_TASK_RE = re.compile(r"^>\s*Task\s+:(\S+)")
# Maven: "[INFO] --- maven-compiler-plugin:3.8.1:compile (default-compile) @ project ---"
_MAVEN_PHASE_RE = re.compile(r"^\[INFO\]\s+---\s+\S+?:(\S+)\s+")
# Build success markers
_BUILD_SUCCESS_RE = re.compile(
    r"BUILD SUCCESSFUL|BUILD SUCCESS|build\s+successful",
    re.IGNORECASE,
)
# Build failure markers
_BUILD_FAILURE_RE = re.compile(
    r"BUILD FAILED|BUILD FAILURE|FAILURE|error:",
    re.IGNORECASE,
)
# Warning lines to preserve even on success
_WARNING_RE = re.compile(r"warning|warn:", re.IGNORECASE)


def _detect_build_tasks(body_lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Detect build task lines and collect task names, warnings, and other lines.

    Returns (task_names, warning_lines, other_lines).
    """
    task_names: list[str] = []
    warning_lines: list[str] = []
    other_lines: list[str] = []
    has_tasks = False

    for line in body_lines:
        stripped = line.strip()

        gradle_match = _GRADLE_TASK_RE.match(stripped)
        if gradle_match:
            task_names.append(gradle_match.group(1))
            has_tasks = True
            continue

        maven_match = _MAVEN_PHASE_RE.match(stripped)
        if maven_match:
            task_names.append(maven_match.group(1).split("@")[0])
            has_tasks = True
            continue

        if _WARNING_RE.search(stripped):
            warning_lines.append(line)
        else:
            other_lines.append(line)

    if not has_tasks:
        return [], [], body_lines

    return task_names, warning_lines, other_lines


def build_filter(formatted: str, opts: BuildFilterOptions | None = None) -> FilterResult:
    """Filter build output: successful builds get a compact task summary.

    Strategy 8: When build_summary_enabled and the output looks like a
    successful build with detectable task lines, emit a summary instead
    of the full task list. Failed builds always pass through unchanged.
    """
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    if not opts.summary_enabled:
        return generic_filter(formatted, GenericFilterOptions(head_lines=opts.head_lines, tail_lines=opts.tail_lines))

    lines = formatted.split("\n")
    header: list[str] = []
    body_start = 0
    for i, ln in enumerate(lines):
        if ln.startswith("$ ") or (ln.startswith("[") and (ln.startswith("[exit") or ln.startswith("[killed"))):
            body_start = i + 1
        elif ln == "" and body_start == i:
            body_start = i + 1
        else:
            break
    header = lines[:body_start]
    body = lines[body_start:]

    if not body:
        return FilterResult(output=formatted, raw_chars=raw_chars, filtered_chars=raw_chars, truncated=False)

    # Check for build failure — never summarize failed builds
    body_text = "\n".join(body)
    if _BUILD_FAILURE_RE.search(body_text) and not _BUILD_SUCCESS_RE.search(body_text):
        return generic_filter(formatted, GenericFilterOptions(head_lines=opts.head_lines, tail_lines=opts.tail_lines))

    # Check for build success
    if not _BUILD_SUCCESS_RE.search(body_text):
        # No clear success marker — fall back to generic
        return generic_filter(formatted, GenericFilterOptions(head_lines=opts.head_lines, tail_lines=opts.tail_lines))

    # Detect tasks
    task_names, warning_lines, other_lines = _detect_build_tasks(body)

    if not task_names:
        # No detectable task pattern — fall back to generic
        return generic_filter(formatted, GenericFilterOptions(head_lines=opts.head_lines, tail_lines=opts.tail_lines))

    # Build the summary
    parts = list(header)

    # Success marker
    # Find the original BUILD SUCCESS line for timing info
    success_line = next((ln for ln in body if _BUILD_SUCCESS_RE.search(ln)), "BUILD SUCCESSFUL")
    parts.append(success_line.strip())

    # Task list
    task_list = ", ".join(task_names)
    parts.append(f"Tasks: {task_list}")

    # Warning lines (if any)
    if warning_lines:
        parts.append("")
        parts.append("Warnings:")
        parts.extend(warning_lines[:10])  # Cap warnings at 10 lines
        if len(warning_lines) > 10:
            parts.append(f"  [... {len(warning_lines) - 10} more warnings ...]")

    result = "\n".join(parts)
    truncated = len(result) < raw_chars
    return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=truncated)
