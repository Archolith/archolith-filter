"""Shared compiled regex patterns and helpers — single source of truth.

Centralises patterns that are duplicated across modules:
- Verbose flag detection (filter_meta, config)
- Import/comment/declaration detection (shrink, filters/read_file)
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Verbose flag detection — used by filter_meta.is_verbose_command and
# config.is_verbose_command (which currently recompiles on every call).
# ---------------------------------------------------------------------------

VERBOSE_FLAG_PATTERNS: list[re.Pattern[str]] = [
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
    return any(p.search(command) for p in VERBOSE_FLAG_PATTERNS)


# ---------------------------------------------------------------------------
# Import and comment detection — shared by shrink.py and filters/read_file.py.
# ---------------------------------------------------------------------------

IMPORT_RE = re.compile(r"^\s*(?:from\s+\S+\s+)?import\s+")
FROM_IMPORT_RE = re.compile(r"^\s*from\s+\S+\s+import\s+")
COMMENT_LINE_RE = re.compile(r"^\s*(?:#\s|//\s?|/\*|\*\s|\*/)")
# Single-line comments only (#, //) — narrower than COMMENT_LINE_RE, used for
# collapsing consecutive line-comment runs without matching block-comment bodies.
LINE_COMMENT_RE = re.compile(r"^\s*(?://|#)\s")


def is_import_line(line: str) -> bool:
    """Return True if *line* looks like a Python/JS/TS import statement."""
    return bool(IMPORT_RE.match(line) or FROM_IMPORT_RE.match(line))


def is_comment_line(line: str) -> bool:
    """Return True if *line* looks like a comment (#, //, /*, * , */)."""
    return bool(COMMENT_LINE_RE.match(line))


def is_line_comment(line: str) -> bool:
    """Return True if *line* is a single-line comment (# or //)."""
    return bool(LINE_COMMENT_RE.match(line))


# ---------------------------------------------------------------------------
# Declaration detection — shared by shrink.py and filters/read_file.py.
# ---------------------------------------------------------------------------

DECLARATION_RE = re.compile(
    r"^\s*"
    r"(?:"
    r"(?:class|def|async\s+def|function|const|let|var|type|interface|enum|namespace|module|export|pub|fn|struct|impl|trait)\s"
    r"|(?:@\w+)"
    r"|(?:(?:public|private|protected|static|final|abstract|override)\s+)+\w+\s*[\(<]"
    r"|(?:\w[\w\-]*\s*\.[\w\-]+\s*\()"
    r")"
)
