"""Cross-turn exact-match deduplication for repeated identical tool output."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class DedupeHit:
    occurrence: int


class DedupeTracker:
    """Tracks content hashes of previously seen outputs for exact-match deduplication."""

    def __init__(self, max_entries: int = 500) -> None:
        self._seen: dict[str, DedupeHit] = {}
        self._max_entries = max_entries

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def check(self, text: str) -> DedupeHit | None:
        return self._seen.get(self._hash(text))

    def record(self, text: str) -> int:
        key = self._hash(text)
        existing = self._seen.get(key)
        if existing is not None:
            updated = DedupeHit(occurrence=existing.occurrence + 1)
            self._seen[key] = updated
            return updated.occurrence
        self._seen[key] = DedupeHit(occurrence=1)
        if len(self._seen) > self._max_entries:
            oldest_key = next(iter(self._seen))
            del self._seen[oldest_key]
        return 1

    @property
    def size(self) -> int:
        return len(self._seen)

    def clear(self) -> None:
        self._seen.clear()


_instance: DedupeTracker | None = None


def get_dedupe_tracker() -> DedupeTracker:
    global _instance
    if _instance is None:
        _instance = DedupeTracker()
    return _instance


def reset_dedupe_tracker() -> None:
    global _instance
    _instance = None
