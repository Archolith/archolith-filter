"""Read-file-aware truncation — declaration-preserving char and token budgeting.

Structure-aware compression that preserves import blocks (collapsed),
comment blocks (collapsed), and declaration lines (class/def/function signatures)
while trimming body content to fit within a budget.

Import DAG: depends on truncate, token_counter, _patterns.
"""

from __future__ import annotations

from .._patterns import DECLARATION_RE, is_comment_line, is_import_line
from .token_counter import count_tokens
from .truncate import (
    _CHARS_PER_TOKEN_ESTIMATE,
    _MARKER_TOKEN_OVERHEAD,
    _TAIL_MAX_TOKENS,
    truncate_for_chars,
    truncate_for_tokens,
)

_READ_FILE_TOOL_NAME = "read_file"

_READ_FILE_DECL_PRESERVE_FRACTION = 0.6
_READ_FILE_MIN_TAIL_CHARS = 256


def _collapse_imports_and_comments(lines: list[str]) -> list[str]:
    """Collapse consecutive import runs (>3) and comment runs (>5) into a marker.

    Shared by the char- and token-budget read_file truncators so the collapse
    logic stays in one place. Behaviour-preserving: keeps the first line of an
    over-length run plus a count marker; short runs pass through unchanged.
    """
    result_lines: list[str] = []
    idx = 0
    import_count = 0
    comment_count = 0
    import_start = -1
    comment_start = -1

    while idx < len(lines):
        line = lines[idx]
        if is_import_line(line):
            if import_start == -1:
                import_start = idx
            import_count += 1
            idx += 1
            continue
        if import_start != -1:
            if import_count > 3:
                result_lines.append(lines[import_start])
                result_lines.append(f" [... {import_count - 1} more import lines …]")
            else:
                result_lines.extend(lines[import_start:import_start + import_count])
            import_start = -1
            import_count = 0

        if is_comment_line(line):
            if comment_start == -1:
                comment_start = idx
            comment_count += 1
            idx += 1
            continue
        if comment_start != -1:
            if comment_count > 5:
                result_lines.append(lines[comment_start])
                result_lines.append(f" [... {comment_count - 1} more comment lines …]")
            else:
                result_lines.extend(lines[comment_start:comment_start + comment_count])
            comment_start = -1
            comment_count = 0

        result_lines.append(line)
        idx += 1

    if import_start != -1:
        if import_count > 3:
            result_lines.append(lines[import_start])
            result_lines.append(f" [... {import_count - 1} more import lines …]")
        else:
            result_lines.extend(lines[import_start:import_start + import_count])

    if comment_start != -1:
        if comment_count > 5:
            result_lines.append(lines[comment_start])
            result_lines.append(f" [... {comment_count - 1} more comment lines …]")
        else:
            result_lines.extend(lines[comment_start:comment_start + comment_count])

    return result_lines


def truncate_read_file_for_chars(text: str, max_chars: int) -> str:
    """Structure-aware truncation for read_file tool output."""
    if len(text) <= max_chars:
        return text

    lines = text.split("\n")
    result_lines = _collapse_imports_and_comments(lines)

    candidate = "\n".join(result_lines)
    if len(candidate) <= max_chars:
        return candidate

    decl_budget = int(max_chars * _READ_FILE_DECL_PRESERVE_FRACTION)
    tail_budget = min(_READ_FILE_MIN_TAIL_CHARS, max_chars - decl_budget)
    head_budget = max(0, decl_budget - tail_budget)
    decl_lines = [line for line in result_lines if DECLARATION_RE.match(line)]
    if not decl_lines:
        return truncate_for_chars(text, max_chars)

    head_decl: list[str] = []
    tail_decl: list[str] = []
    total_decl_chars = sum(len(line) + 1 for line in decl_lines)
    if total_decl_chars <= decl_budget:
        head_decl = decl_lines
    else:
        acc = 0
        for dl in decl_lines:
            if acc + len(dl) + 1 <= head_budget:
                head_decl.append(dl)
                acc += len(dl) + 1
            else:
                break
        tail_acc = 0
        for dl in reversed(decl_lines):
            if tail_acc + len(dl) + 1 <= tail_budget:
                tail_decl.insert(0, dl)
                tail_acc += len(dl) + 1
            else:
                break

    if not head_decl and not tail_decl:
        return truncate_for_chars(text, max_chars)

    dropped_decl = len(decl_lines) - len(head_decl) - len(tail_decl)
    marker = f"\n[…{dropped_decl} declarations & body lines omitted — raise budget or narrow the read scope…]\n"
    while head_decl and (
        sum(len(line) + 1 for line in head_decl)
        + sum(len(line) + 1 for line in tail_decl)
        + len(marker) > max_chars
    ):
        if len(head_decl) > len(tail_decl):
            head_decl.pop()
        elif tail_decl:
            tail_decl.pop(0)
        else:
            head_decl.pop()

    if not head_decl and not tail_decl:
        return truncate_for_chars(text, max_chars)

    dropped_decl = len(decl_lines) - len(head_decl) - len(tail_decl)
    marker = f"\n[…{dropped_decl} declarations & body lines omitted — raise budget or narrow the read scope…]\n"
    return "\n".join(head_decl) + marker + "\n".join(tail_decl)


def truncate_read_file_for_tokens(text: str, max_tokens: int) -> str:
    """Structure-aware token-budget truncation for read_file tool output."""
    if max_tokens <= 0:
        return ""
    if len(text) <= max_tokens:
        return text
    if len(text) <= max_tokens * _CHARS_PER_TOKEN_ESTIMATE and count_tokens(text) <= max_tokens:
        return text

    lines = text.split("\n")
    result_lines = _collapse_imports_and_comments(lines)

    candidate = "\n".join(result_lines)
    if count_tokens(candidate) <= max_tokens:
        return candidate

    decl_lines = [line for line in result_lines if DECLARATION_RE.match(line)]
    if not decl_lines:
        return truncate_for_tokens(text, max_tokens)

    content_budget = max(0, max_tokens - _MARKER_TOKEN_OVERHEAD)
    total_decl_tokens = sum(count_tokens(line) for line in decl_lines)
    if total_decl_tokens <= content_budget:
        marker = f"\n\n[…read_file compressed: {len(lines) - len(decl_lines)} non-declaration lines omitted…]\n\n"
        return "\n".join(decl_lines) + marker

    head_budget = int(content_budget * _READ_FILE_DECL_PRESERVE_FRACTION)
    tail_budget = min(_TAIL_MAX_TOKENS, content_budget - head_budget)
    head_decl: list[str] = []
    tail_decl: list[str] = []
    acc = 0
    for dl in decl_lines:
        tokens = count_tokens(dl)
        if acc + tokens <= head_budget:
            head_decl.append(dl)
            acc += tokens
        else:
            break

    tail_acc = 0
    for dl in reversed(decl_lines):
        if dl in head_decl:
            break
        tokens = count_tokens(dl)
        if tail_acc + tokens <= tail_budget:
            tail_decl.insert(0, dl)
            tail_acc += tokens
        else:
            break

    if not head_decl and not tail_decl:
        return truncate_for_tokens(text, max_tokens)

    dropped = len(decl_lines) - len(head_decl) - len(tail_decl)
    marker = (
        f"\n\n[…read_file compressed: ~{dropped} declarations & body lines omitted"
        f" — raise budget or narrow the read scope…]\n\n"
    )
    result = "\n".join(head_decl) + marker + "\n".join(tail_decl)
    while head_decl and count_tokens(result) > max_tokens:
        head_decl.pop()
        dropped = len(decl_lines) - len(head_decl) - len(tail_decl)
        marker = (
            f"\n\n[…read_file compressed: ~{dropped} declarations & body lines omitted"
            f" — raise budget or narrow the read scope…]\n\n"
        )
        result = "\n".join(head_decl) + marker + "\n".join(tail_decl)

    if not head_decl and not tail_decl:
        return truncate_for_tokens(text, max_tokens)
    return result
