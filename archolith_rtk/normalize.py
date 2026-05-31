"""Runtime noise normalization — replace volatile values with stable placeholders.

Replaces timestamps, PIDs, elapsed times, and memory sizes with stable
placeholders like ``[TIMESTAMP]``, ``[PID]``, ``[X]ms``, ``[X]SIZE``.
This saves tokens and enables prompt caching at the provider level
(identical prefix tokens get cache hits).

**Scoping**: only call from log/build/test filters — NOT as a global
pre-filter, because normalizing timestamps in source code or diffs
would destroy meaningful content.
"""

from __future__ import annotations

import re

# ── Timestamps ────────────────────────────────────────────────────────
# Bracketed ISO timestamps: [2026-05-27T14:30:00.123Z] or [2026-05-27 14:30:00]
_BRACKETED_ISO_RE = re.compile(
    r"\[\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\]",
)

# Bare ISO timestamps: 2026-05-27T14:30:00.123Z or 2026-05-27 14:30:00
# (must include time component — just a date is NOT replaced)
_BARE_ISO_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
)

# Common Log Format timestamps: 27/May/2026:14:30:00 +0000
_CLF_RE = re.compile(
    r"\d{2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2}\s+[+-]\d{4}",
)

# ── Process IDs ───────────────────────────────────────────────────────
# PID 12345, pid=12345, pid: 12345
_PID_RE = re.compile(
    r"\bPID\s*[:=]?\s*\d{1,7}\b",
    re.IGNORECASE,
)

# ── Elapsed times ─────────────────────────────────────────────────────
_ELAPSED_MS_RE = re.compile(r"\b\d+(?:\.\d+)?\s*ms\b")
_ELAPSED_SEC_RE = re.compile(r"\b\d+(?:\.\d+)?\s*s\b")

# ── Memory sizes ──────────────────────────────────────────────────────
_MEMORY_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:KB|MB|GB|TB)\b",
    re.IGNORECASE,
)


def normalize_runtime_noise(text: str) -> str:
    """Replace volatile runtime values with stable placeholders.

    Replacement table:
        Full ISO timestamps → [TIMESTAMP]
        Common Log Format timestamps → [TIMESTAMP]
        PIDs (PID 12345, pid=12345) → [PID]
        Elapsed ms (42ms, 4.234ms) → [X]ms
        Elapsed sec (1.5s, 2s) → [X]s
        Memory sizes (512 MB, 1.2 GB) → [X]SIZE
    """
    # Bracketed timestamps first (more specific, avoids partial matches).
    result = _BRACKETED_ISO_RE.sub("[TIMESTAMP]", text)
    result = _CLF_RE.sub("[TIMESTAMP]", result)
    result = _BARE_ISO_RE.sub("[TIMESTAMP]", result)

    # PIDs.
    result = _PID_RE.sub("[PID]", result)

    # Elapsed times (ms before s to avoid partial match on "1.5ms").
    result = _ELAPSED_MS_RE.sub("[X]ms", result)
    result = _ELAPSED_SEC_RE.sub("[X]s", result)

    # Memory sizes.
    result = _MEMORY_RE.sub("[X]SIZE", result)

    return result
