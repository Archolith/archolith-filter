"""Dedicated Layer 1 filter for read_file tool output.

Structure-aware compression for source code and similar file content
returned by the read_file tool. Preserves declarations, signatures,
selectors, and headings while collapsing large import blocks, long
comment runs, repetitive CSS rule bodies, excessive blank lines,
generated/minified content, huge literals/fixture sections, and
embedded SVG/path data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import FilterResult


@dataclass(frozen=True)
class ReadFileFilterOptions:
    import_collapse: bool = True
    blank_line_max: int = 1
    comment_threshold: int = 10
    css_rule_collapse: bool = True
    generated_min_line_len: int = 500
    generated_min_run: int = 5
    literal_threshold: int = 8


DEFAULT_OPTS = ReadFileFilterOptions()

_IMPORT_RE = re.compile(r"^\s*(?:from\s+\S+\s+)?import\s+")
_FROM_IMPORT_RE = re.compile(r"^\s*from\s+\S+\s+import\s+")
_CSS_RULE_RE = re.compile(r"^\s*[\w\-\.\#\[\]:,>+~*][\s\w\-\.\#\[\]:,>+~*]*\{")
_CSS_CLOSE_RE = re.compile(r"\}\s*$")
_COMMENT_BLOCK_RE = re.compile(r"^\s*(?:#\s|//\s?|/\*|\*\s|\*/)")
_LINE_COMMENT_RE = re.compile(r"^\s*(?://|#)\s")
_BLOCK_COMMENT_START = re.compile(r"^\s*/\*")
_BLOCK_COMMENT_END = re.compile(r"\*/\s*$")
_DECLARATION_RE = re.compile(
    r"^\s*"
    r"(?:"
    r"(?:class|def|async\s+def|function|const|let|var|type|interface|enum|namespace|module|export|pub|fn|struct|impl|trait)\s"
    r"|(?:@\w+)"
    r"|(?:(?:public|private|protected|static|final|abstract|override)\s+)+\w+\s*[\(<]"
    r"|(?:\w[\w\-]*\s*\.[\w\-]+\s*\()"
    r")"
)
_ARRAY_LITERAL_START_RE = re.compile(
    r"^\s*(?:const|let|var|)\s*\w+\s*[:=].*=\s*\[|^\s*(?:const|let|var|)\s*\w+\s*[:=]\s*\["
)
_OBJECT_LITERAL_START_RE = re.compile(
    r"^\s*(?:const|let|var|)\s*\w+\s*[:=].*=\s*\{|^\s*(?:const|let|var|)\s*\w+\s*[:=]\s*\{"
)
_MULTILINE_STRING_START_RE = re.compile(r'(?:"""|\'\'\'|`)')
_SVG_PATH_D_RE = re.compile(r"[dD]\s*=\s*\"[Mm][^\"]*")
_SVG_TAG_RE = re.compile(r"<svg[\s>]")
_EMBEDDED_JSON_RE = re.compile(r"^\s*(?:const|let|var|)\s*\w+\s*[:=]\s*JSON\.parse\(")
_DICT_LITERAL_START_RE = re.compile(
    r"^\s*\w+\s*[:=].*=\s*\{|^\s*\w+\s*[:=]\s*\{"
)


def _is_import_line(line: str) -> bool:
    return bool(_IMPORT_RE.match(line) or _FROM_IMPORT_RE.match(line))


def _is_css_rule_start(line: str) -> bool:
    return bool(_CSS_RULE_RE.match(line))


def _is_css_rule_end(line: str) -> bool:
    return bool(_CSS_CLOSE_RE.search(line))


def _is_comment_line(line: str) -> bool:
    return bool(_COMMENT_BLOCK_RE.match(line))


def _is_line_comment(line: str) -> bool:
    return bool(_LINE_COMMENT_RE.match(line))


def _is_block_comment_start(line: str) -> bool:
    return bool(_BLOCK_COMMENT_START.match(line))


def _is_block_comment_end(line: str) -> bool:
    return bool(_BLOCK_COMMENT_END.search(line))


def _is_long_line(line: str, min_len: int) -> bool:
    return len(line) >= min_len


def _looks_minified(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 200:
        return False
    semicolons = stripped.count(";")
    if semicolons >= 5 and len(stripped) / semicolons < 40:
        return True
    commas = stripped.count(",")
    if commas >= 10 and len(stripped) / commas < 20:
        return True
    return False


def _is_svg_path_line(line: str) -> bool:
    return bool(_SVG_PATH_D_RE.search(line))


def _is_svg_tag(line: str) -> bool:
    return bool(_SVG_TAG_RE.search(line))


def _is_multiline_string_start(line: str) -> bool:
    if not _MULTILINE_STRING_START_RE.search(line):
        return False
    for delim in ('"""', "'''", "`"):
        count = line.count(delim)
        if count % 2 == 1:
            return True
    return False


def _is_array_literal_start(line: str) -> bool:
    return bool(_ARRAY_LITERAL_START_RE.match(line))


def _is_object_literal_start(line: str) -> bool:
    stripped = line.strip()
    return bool(_OBJECT_LITERAL_START_RE.match(stripped)) and not _is_css_rule_start(stripped)


def _is_dict_literal_start(line: str) -> bool:
    stripped = line.strip()
    return bool(_DICT_LITERAL_START_RE.match(stripped)) and not _is_css_rule_start(stripped)


def _is_embedded_json_start(line: str) -> bool:
    return bool(_EMBEDDED_JSON_RE.match(line))


def _collapse_imports(lines: list[str], start: int) -> tuple[list[str], int]:
    idx = start
    count = 0
    first_line = lines[idx]
    while idx < len(lines) and _is_import_line(lines[idx]):
        count += 1
        idx += 1

    if count <= 3:
        return lines[start:idx], idx

    collapsed = [first_line, f" [... {count - 1} import lines omitted ...]"]
    return collapsed, idx


def _collapse_comment_block(lines: list[str], start: int, threshold: int) -> tuple[list[str], int]:
    idx = start
    count = 0
    first_line = lines[idx]

    if _is_block_comment_start(first_line) and not _is_block_comment_end(first_line):
        while idx < len(lines):
            count += 1
            if _is_block_comment_end(lines[idx]):
                idx += 1
                break
            idx += 1
            if idx >= len(lines):
                break
    else:
        while idx < len(lines) and _is_line_comment(lines[idx]):
            count += 1
            idx += 1
        if count == 0:
            idx += 1
            count = 1

    if count <= threshold:
        return lines[start:idx], idx

    collapsed = [first_line, f" [... {count - 1} comment lines omitted ...]"]
    return collapsed, idx


def _collapse_css_rules(lines: list[str], start: int) -> tuple[list[str], int]:
    if start >= len(lines):
        return [], start

    selector_line = lines[start]
    idx = start + 1

    if _is_css_rule_end(selector_line):
        return [selector_line], start + 1

    body_count = 0
    while idx < len(lines) and not _is_css_rule_end(lines[idx]):
        body_count += 1
        idx += 1

    if idx < len(lines):
        idx += 1

    if body_count <= 3:
        return lines[start:idx], idx

    return [selector_line, f" [... {body_count} CSS body lines omitted ...]", "}"], idx


def _collapse_generated_block(
    lines: list[str], start: int, min_line_len: int, min_run: int
) -> tuple[list[str], int]:
    idx = start
    count = 0
    sample_line = lines[idx]

    while idx < len(lines):
        line = lines[idx]
        if line.strip() == "":
            break
        if not _is_long_line(line, min_line_len) and not _looks_minified(line):
            if count < min_run:
                return lines[start:idx + 1], idx + 1
            break
        count += 1
        idx += 1

    if count < min_run:
        return lines[start:idx], idx

    marker_type = "minified" if _looks_minified(sample_line) else "generated"
    return [sample_line, f" [... {count - 1} {marker_type} lines omitted ...]"], idx


def _find_bracket_close(lines: list[str], start: int, open_char: str, close_char: str) -> int:
    first_line = lines[start]
    last_open_pos = first_line.rfind(open_char)
    depth = first_line[last_open_pos:].count(open_char) - first_line[last_open_pos:].count(close_char)
    if depth <= 0:
        return start + 1
    idx = start + 1
    while idx < len(lines):
        for ch in lines[idx]:
            if ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
            if depth <= 0:
                return idx + 1
        idx += 1
    return idx


def _collapse_literal_block(
    lines: list[str], start: int, threshold: int, block_type: str
) -> tuple[list[str], int]:
    first_line = lines[start]
    open_char = "{"
    close_char = "}"
    last_bracket = ""
    for ch in reversed(first_line):
        if ch in "{[":
            last_bracket = ch
            break
    if last_bracket == "[":
        open_char = "["
        close_char = "]"

    end_idx = _find_bracket_close(lines, start, open_char, close_char)
    block_len = end_idx - start

    if block_len <= threshold:
        return lines[start:end_idx], end_idx

    close_line = lines[end_idx - 1] if end_idx <= len(lines) else close_char
    return [
        first_line,
        f" [... {block_len - 2} {block_type} lines omitted ...]",
        close_line,
    ], end_idx


def _collapse_multiline_string(lines: list[str], start: int, threshold: int) -> tuple[list[str], int]:
    first_line = lines[start]
    delim = None
    for candidate in ('"""', "'''", "`"):
        if candidate in first_line and first_line.count(candidate) % 2 == 1:
            delim = candidate
            break
    if delim is None:
        return [first_line], start + 1

    idx = start + 1
    count = 1
    while idx < len(lines):
        count += 1
        if delim in lines[idx]:
            idx += 1
            break
        idx += 1

    if count <= threshold:
        return lines[start:idx], idx

    close_line = lines[idx - 1] if idx <= len(lines) else delim
    return [
        first_line,
        f" [... {count - 2} multiline string lines omitted ...]",
        close_line,
    ], idx


def _collapse_svg_path_block(lines: list[str], start: int) -> tuple[list[str], int]:
    idx = start
    count = 0
    has_path = False

    while idx < len(lines):
        line = lines[idx]
        count += 1
        if _is_svg_path_line(line):
            has_path = True
        if "</svg>" in line:
            idx += 1
            break
        idx += 1
        if idx >= len(lines):
            break

    if not has_path or count <= 6:
        return lines[start:idx], idx

    opening = lines[start]
    closing = lines[idx - 1] if idx <= len(lines) and "</svg>" in lines[idx - 1] else "</svg>"
    return [opening, f" [... {count - 2} SVG path/body lines omitted ...]", closing], idx


def _collapse_blank_lines(lines: list[str], max_blank: int) -> list[str]:
    if max_blank <= 0:
        max_blank = 1

    out: list[str] = []
    consecutive_blank = 0
    for line in lines:
        if line.strip() == "":
            consecutive_blank += 1
            if consecutive_blank <= max_blank:
                out.append(line)
        else:
            consecutive_blank = 0
            out.append(line)
    return out


def read_file_filter(formatted: str, opts: ReadFileFilterOptions | None = None) -> FilterResult:
    """Compress read_file tool output with structure-aware heuristics."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    lines = formatted.split("\n")
    result_lines: list[str] = []
    idx = 0
    changed = False

    while idx < len(lines):
        line = lines[idx]

        if line.strip() == "":
            result_lines.append(line)
            idx += 1
            continue

        if opts.import_collapse and _is_import_line(line):
            collapsed, next_idx = _collapse_imports(lines, idx)
            if len(collapsed) < next_idx - idx:
                changed = True
            result_lines.extend(collapsed)
            idx = next_idx
            continue

        if _is_comment_line(line) and opts.comment_threshold > 0:
            collapsed, next_idx = _collapse_comment_block(lines, idx, opts.comment_threshold)
            if len(collapsed) < next_idx - idx:
                changed = True
            result_lines.extend(collapsed)
            idx = next_idx
            continue

        if _is_multiline_string_start(line) and opts.literal_threshold > 0:
            collapsed, next_idx = _collapse_multiline_string(lines, idx, opts.literal_threshold)
            if len(collapsed) < next_idx - idx:
                changed = True
            result_lines.extend(collapsed)
            idx = next_idx
            continue

        if opts.literal_threshold > 0:
            if _is_array_literal_start(line):
                collapsed, next_idx = _collapse_literal_block(lines, idx, opts.literal_threshold, "array literal")
                if len(collapsed) < next_idx - idx:
                    changed = True
                result_lines.extend(collapsed)
                idx = next_idx
                continue

            if _is_embedded_json_start(line):
                collapsed, next_idx = _collapse_literal_block(lines, idx, opts.literal_threshold, "embedded JSON")
                if len(collapsed) < next_idx - idx:
                    changed = True
                result_lines.extend(collapsed)
                idx = next_idx
                continue

            if _is_dict_literal_start(line):
                collapsed, next_idx = _collapse_literal_block(lines, idx, opts.literal_threshold, "dict literal")
                if len(collapsed) < next_idx - idx:
                    changed = True
                result_lines.extend(collapsed)
                idx = next_idx
                continue

            if _is_object_literal_start(line):
                collapsed, next_idx = _collapse_literal_block(lines, idx, opts.literal_threshold, "object literal")
                if len(collapsed) < next_idx - idx:
                    changed = True
                result_lines.extend(collapsed)
                idx = next_idx
                continue

        if opts.css_rule_collapse and _is_css_rule_start(line) and not _is_css_rule_end(line):
            collapsed, next_idx = _collapse_css_rules(lines, idx)
            if len(collapsed) < next_idx - idx:
                changed = True
            result_lines.extend(collapsed)
            idx = next_idx
            continue

        if _is_svg_tag(line) and "</svg>" not in line:
            collapsed, next_idx = _collapse_svg_path_block(lines, idx)
            if len(collapsed) < next_idx - idx:
                changed = True
            result_lines.extend(collapsed)
            idx = next_idx
            continue

        if (
            opts.generated_min_run > 0
            and opts.generated_min_line_len > 0
            and (_is_long_line(line, opts.generated_min_line_len) or _looks_minified(line))
        ):
            collapsed, next_idx = _collapse_generated_block(
                lines, idx, opts.generated_min_line_len, opts.generated_min_run
            )
            if len(collapsed) < next_idx - idx:
                changed = True
            result_lines.extend(collapsed)
            idx = next_idx
            continue

        result_lines.append(line)
        idx += 1

    if opts.blank_line_max >= 0:
        before_blanks = len(result_lines)
        result_lines = _collapse_blank_lines(result_lines, opts.blank_line_max)
        if len(result_lines) < before_blanks:
            changed = True

    output = "\n".join(result_lines)
    truncated = changed and len(output) < raw_chars
    return FilterResult(
        output=output,
        raw_chars=raw_chars,
        filtered_chars=len(output),
        truncated=truncated,
    )
