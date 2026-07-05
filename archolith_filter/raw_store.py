"""Session-scoped store for pre-filter output, recoverable by ID.

Eviction policy trade-off note (FC-B2 / PERF-01):
    The store uses a dict keyed by an ever-increasing integer ID. Under
    CPython 3.7+ dict insertion order matches ID order, so eviction by
    ``list(self._entries.keys())[:excess]`` (per PERF-01 fix) evicts
    the OLDEST entries in O(n) without an O(n log n) sort.

    When an entry is evicted, the telemetry store
    (``FilterTelemetryStore``) and any other references it owns on a
    ``raw_output_id`` are NOT synchronously cleared — callers that
    resolve a stale ``raw_output_id`` via ``RawOutputStore.get()`` will
    receive ``None`` (the entry is gone) and must handle that
    gracefully. This is a deliberate trade-off: synchronous cross-store
    callback on eviction would add coupling and lock contention for a
    telemetry-stale-reference case that is rare (and only matters for
    diagnostic dashboards trying to fetch raw output long after the
    filter call). The trade-off is documented here so future maintainers
    know the dangling-reference behaviour is intended, not a bug.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

DEFAULT_MAX_ENTRIES = 200
DEFAULT_MAX_RAW_CHARS = 256_000


@dataclass
class RawOutputEntry:
    id: int
    raw: str
    command: str
    tool: str
    filtered_chars: int
    stored_at: float


class RawOutputStore:
    """LRU store for original tool outputs, recoverable by ID."""

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_raw_chars: int = DEFAULT_MAX_RAW_CHARS,
    ) -> None:
        self._next_id = 1
        self._entries: dict[int, RawOutputEntry] = {}
        self._max_entries = max_entries
        self._max_raw_chars = max_raw_chars

    def store(self, raw: str, *, command: str, tool: str, filtered_chars: int) -> int:
        """Store a raw output and return its ID. Evicts oldest if at capacity."""
        entry_id = self._next_id
        self._next_id += 1

        capped = raw[: self._max_raw_chars] if len(raw) > self._max_raw_chars else raw

        self._entries[entry_id] = RawOutputEntry(
            id=entry_id,
            raw=capped,
            command=command,
            tool=tool,
            filtered_chars=filtered_chars,
            stored_at=time.time(),
        )

        # Evict oldest entries over capacity. CPython 3.7+ guarantees dict
        # insertion order, so list(self._entries.keys())[:excess] returns
        # the oldest keys (which, given monotonic _next_id, are also the
        # numerically smallest IDs) in O(n) — no sort needed (PERF-01).
        if len(self._entries) > self._max_entries:
            excess = len(self._entries) - self._max_entries
            for key in list(self._entries.keys())[:excess]:
                del self._entries[key]

        return entry_id

    def get(self, entry_id: int) -> RawOutputEntry | None:
        """Retrieve a stored raw output by ID."""
        return self._entries.get(entry_id)

    def get_filtered(
        self,
        entry_id: int,
        tail_lines: int | None = None,
        max_chars: int | None = None,
    ) -> RawOutputEntry | None:
        """Retrieve with optional tail/cap filtering."""
        entry = self._entries.get(entry_id)
        if entry is None:
            return None
        if tail_lines is None and max_chars is None:
            return entry

        raw = entry.raw
        if tail_lines and tail_lines > 0:
            lines = raw.split("\n")
            if len(lines) > tail_lines:
                dropped = len(lines) - tail_lines
                raw = f"[... {dropped} earlier lines ...]\n" + "\n".join(lines[-tail_lines:])
        if max_chars and max_chars > 0 and len(raw) > max_chars:
            raw = raw[:max_chars]

        return RawOutputEntry(
            id=entry.id,
            raw=raw,
            command=entry.command,
            tool=entry.tool,
            filtered_chars=entry.filtered_chars,
            stored_at=entry.stored_at,
        )

    @property
    def size(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        """Clear all stored entries."""
        self._entries.clear()
        self._next_id = 1


# Module-level singleton for the current session.
_instance: RawOutputStore | None = None


def get_raw_output_store() -> RawOutputStore:
    """Get or create the session-scoped raw output store."""
    global _instance
    if _instance is None:
        _instance = RawOutputStore()
    return _instance


def reset_raw_output_store() -> None:
    """Reset the store (for tests or session restart)."""
    global _instance
    _instance = None
