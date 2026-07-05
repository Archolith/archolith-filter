"""Generic head+tail filter — baseline for all command categories.

Includes Strategy 5: stack trace frame collapsing for Java, Python,
Node, and Go stack traces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import FilterResult


@dataclass(frozen=True)
class GenericFilterOptions:
    head_lines: int = 20
    tail_lines: int = 30
    stack_collapse_enabled: bool = True
    stack_collapse_min_frames: int = 5
    stack_collapse_keep_app_frames: int = 2


DEFAULT_OPTS = GenericFilterOptions()

_TOOL_HEADER_PREFIXES = ("[exit", "[killed", "[job")

# ─── Stack trace detection (Strategy 5) ───

# Java: "    at com.example.MyClass.myMethod(MyClass.java:42)"
_JAVA_FRAME_RE = re.compile(r"\s+at\s+([\w.$]+)\(")
# Python: '  File "/usr/lib/python3/site-packages/django/core/handlers.py", line 42, in get_response'
_PYTHON_FRAME_RE = re.compile(r'\s+File\s+"([^"]+)",\s+line\s+\d+,\s+in\s+\w+')
# Node: "    at Object.<anonymous> (/path/to/node_modules/express/lib/router/index.js:42:15)"
_NODE_FRAME_RE = re.compile(r"\s+at\s+\S+\s+\(([^)]+)\)")
# Go: "    runtime/asm_amd64.s:42 +0x42"
_GO_FRAME_RE = re.compile(r"^\s+(\S+/\S+)\s+0x[0-9a-fA-F]+")

# Framework packages to classify as "framework" for collapsing
_FRAMEWORK_PACKAGES: tuple[str, ...] = (
    # Java
    "org.springframework.",
    "org.apache.",
    "java.lang.reflect.",
    "jdk.internal.",
    "io.netty.",
    "org.gradle.",
    "org.hibernate.",
    "com.fasterxml.",
    "org.eclipse.",
    "sun.reflect.",
    "org.tomcat.",
    "javax.servlet.",
    # Python
    "/usr/lib/python",
    "/opt/",
    "site-packages/",
    "lib/python",
    # Node
    "node:internal",
    "node_modules/",
    # Go
    "runtime/",
    "internal/",
)


def _classify_frame(package_path: str) -> str:
    """Classify a stack frame as 'framework' or 'application'.

    Returns 'framework' if the package matches a known framework prefix,
    'application' otherwise.  If a project_package_prefix is provided,
    frames matching it are classified as application.
    """
    for prefix in _FRAMEWORK_PACKAGES:
        if package_path.startswith(prefix):
            return "framework"
    return "application"


def _detect_stack_trace(lines: list[str], min_frames: int) -> list[tuple[int, int, str]] | None:
    """Detect consecutive stack-frame runs in the output.

    Returns a list of (start_idx, end_idx, language) tuples for each
    run of >= min_frames consecutive stack frames, or None if no
    run is found.
    """
    runs: list[tuple[int, int, str]] = []
    current_start: int | None = None
    current_lang: str | None = None

    for i, line in enumerate(lines):
        detected_lang: str | None = None
        if _JAVA_FRAME_RE.match(line):
            detected_lang = "java"
        elif _PYTHON_FRAME_RE.match(line):
            detected_lang = "python"
        elif _NODE_FRAME_RE.match(line):
            detected_lang = "node"
        elif _GO_FRAME_RE.match(line):
            detected_lang = "go"

        if detected_lang:
            if current_start is None:
                current_start = i
                current_lang = detected_lang
            elif current_lang != detected_lang:
                # Different language — end current run and start new
                if i - current_start >= min_frames:
                    runs.append((current_start, i, current_lang))
                current_start = i
                current_lang = detected_lang
        else:
            if current_start is not None and i - current_start >= min_frames:
                runs.append((current_start, i, current_lang))
            current_start = None
            current_lang = None

    # Final run
    if current_start is not None and len(lines) - current_start >= min_frames:
        runs.append((current_start, len(lines), current_lang))  # type: ignore[arg-type]

    return runs if runs else None


def _collapse_stack_frames(
    body_lines: list[str],
    opts: GenericFilterOptions,
) -> list[str]:
    """Collapse framework stack frames in detected stack traces."""
    if not opts.stack_collapse_enabled:
        return body_lines

    runs = _detect_stack_trace(body_lines, opts.stack_collapse_min_frames)
    if not runs:
        return body_lines

# Process runs in reverse order so indices stay valid
    result_lines = list(body_lines)
    for start_idx, end_idx, lang in reversed(runs):
        frame_lines = result_lines[start_idx:end_idx]

        # Exception line (before the stack trace) is already in result_lines
        # at start_idx - 1, outside the replacement range — it's naturally preserved.

        # Classify each frame
        classified: list[tuple[str, str]] = []  # (type, line)
        for line in frame_lines:
            # Extract package path for classification
            java_match = _JAVA_FRAME_RE.match(line)
            python_match = _PYTHON_FRAME_RE.match(line)
            node_match = _NODE_FRAME_RE.match(line)
            go_match = _GO_FRAME_RE.match(line)

            if java_match:
                pkg = java_match.group(1)
                classified.append((_classify_frame(pkg), line))
            elif python_match:
                pkg = python_match.group(1)
                classified.append((_classify_frame(pkg), line))
            elif node_match:
                pkg = node_match.group(1)
                classified.append((_classify_frame(pkg), line))
            elif go_match:
                pkg = go_match.group(1)
                classified.append((_classify_frame(pkg), line))
            else:
                classified.append(("application", line))

        app_frames = [(i, t, line) for i, (t, line) in enumerate(classified) if t == "application"]
        fw_frames = [(i, t, line) for i, (t, line) in enumerate(classified) if t == "framework"]

        # If all frames are framework, keep first and last 3 instead of collapsing
        if not app_frames:
            keep_count = min(3, len(frame_lines))
            kept = frame_lines[:keep_count]
            omitted = len(frame_lines) - keep_count
            last = frame_lines[-1] if keep_count < len(frame_lines) else ""
            replacement = kept
            if omitted > 0:
                replacement.append(f"[... {omitted} framework frames omitted ...]")
            if last and last not in replacement:
                replacement.append(last)
            result_lines[start_idx:end_idx] = replacement
            continue

        keep_count = opts.stack_collapse_keep_app_frames
        # Keep first N and last N application frames
        kept_app_indices: set[int] = set()
        if len(app_frames) <= keep_count * 2:
            # All app frames fit within budget
            kept_app_indices = {i for i, _, _ in app_frames}
        else:
            for idx in range(min(keep_count, len(app_frames))):
                kept_app_indices.add(app_frames[idx][0])
            for idx in range(max(0, len(app_frames) - keep_count), len(app_frames)):
                kept_app_indices.add(app_frames[idx][0])

        # Build replacement
        replacement: list[str] = []
        framework_count = 0
        in_framework_run = False

        for i, (frame_type, line) in enumerate(classified):
            if i in kept_app_indices:
                if in_framework_run and framework_count > 0:
                    frameworks_desc = _describe_frameworks(fw_frames)
                    replacement.append(f"[... {framework_count} {frameworks_desc} ...]")
                    framework_count = 0
                    in_framework_run = False
                replacement.append(line)
            else:
                if frame_type == "framework":
                    framework_count += 1
                    in_framework_run = True
                else:
                    # Other app frames not in keep set
                    if in_framework_run and framework_count > 0:
                        frameworks_desc = _describe_frameworks(fw_frames)
                        replacement.append(f"[... {framework_count} {frameworks_desc} ...]")
                        framework_count = 0
                        in_framework_run = False
                    replacement.append(line)

        if framework_count > 0:
            frameworks_desc = _describe_frameworks(fw_frames)
            replacement.append(f"[... {framework_count} {frameworks_desc} ...]")

        result_lines[start_idx:end_idx] = replacement

    return result_lines


def _describe_frameworks(fw_frames: list[tuple[int, str, str]]) -> str:
    """Describe the framework types in the collapsed frames."""
    frameworks: set[str] = set()
    for _, _, line in fw_frames:
        if _JAVA_FRAME_RE.match(line):
            # Extract top-level package
            match = _JAVA_FRAME_RE.match(line)
            if match:
                parts = match.group(1).split(".")
                if len(parts) >= 2:
                    frameworks.add(f"{parts[0]}.{parts[1]}")
        elif _PYTHON_FRAME_RE.match(line):
            frameworks.add("Python stdlib")
        elif _NODE_FRAME_RE.match(line):
            frameworks.add("Node")
        elif _GO_FRAME_RE.match(line):
            frameworks.add("Go runtime")

    if not frameworks:
        return "framework frames"
    return f"framework frames ({', '.join(sorted(frameworks))})"


# ─── Original filter ───


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
    """Separate tool metadata header lines from the body."""
    header_end = 0
    for i, ln in enumerate(lines):
        if ln.startswith("$ ") or ln.startswith(_TOOL_HEADER_PREFIXES):
            header_end = i + 1
            continue
        if ln == "" and header_end == i:
            header_end = i + 1
            continue
        break
    return lines[:header_end], lines[header_end:]


def generic_filter(formatted: str, opts: GenericFilterOptions | None = None) -> FilterResult:
    """Apply generic head+tail windowing with collapsed blanks and omission marker.

    Includes Strategy 5: stack trace frame collapsing when enabled.
    """
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    lines = formatted.split("\n")
    header, body = _extract_header(lines)

    # Strategy 5: collapse stack frames before windowing
    body = _collapse_stack_frames(body, opts)

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
