"""Output filter telemetry — tracks token savings per tool call and session totals."""

from __future__ import annotations

import time
from dataclasses import dataclass

# Heuristic: ~4 chars per token for English/code text.
CHARS_PER_TOKEN = 4


def _estimate_tokens_heuristic(char_count: int) -> int:
    return round(char_count / CHARS_PER_TOKEN)


@dataclass
class FilterTelemetryEntry:
    command: str
    tool: str | None
    filter_kind: str
    raw_chars: int
    filtered_chars: int
    estimated_raw_tokens: int
    estimated_filtered_tokens: int
    savings_pct: int
    raw_output_id: int | None
    fallback_used: bool
    token_counts_are_estimate: bool
    timestamp: float


@dataclass
class FilterTelemetrySummary:
    total_calls: int
    filtered_calls: int
    dedupe_calls: int
    fallback_calls: int
    total_raw_chars: int
    total_filtered_chars: int
    estimated_raw_tokens: int
    estimated_filtered_tokens: int
    estimated_saved_tokens: int
    average_savings_pct: int
    token_counts_are_estimate: bool


class FilterTelemetryStore:
    """Session-scoped telemetry store."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: list[FilterTelemetryEntry] = []
        self._max_entries = max_entries

    def record(self, entry: FilterTelemetryEntry) -> None:
        if len(self._entries) >= self._max_entries:
            self._entries.pop(0)
        self._entries.append(entry)

    @property
    def entries(self) -> list[FilterTelemetryEntry]:
        return list(self._entries)

    def get_summary(self) -> FilterTelemetrySummary:
        total_raw_chars = 0
        total_filtered_chars = 0
        filtered_calls = 0
        dedupe_calls = 0
        fallback_calls = 0
        savings_sum = 0
        savings_count = 0
        any_estimate = False

        for entry in self._entries:
            total_raw_chars += entry.raw_chars
            total_filtered_chars += entry.filtered_chars
            if entry.fallback_used:
                fallback_calls += 1
            elif entry.filter_kind == "dedupe":
                dedupe_calls += 1
            else:
                filtered_calls += 1
            if entry.raw_chars > 0:
                savings_sum += entry.savings_pct
                savings_count += 1
            if entry.token_counts_are_estimate:
                any_estimate = True

        estimated_raw_tokens = sum(e.estimated_raw_tokens for e in self._entries)
        estimated_filtered_tokens = sum(e.estimated_filtered_tokens for e in self._entries)

        return FilterTelemetrySummary(
            total_calls=len(self._entries),
            filtered_calls=filtered_calls,
            dedupe_calls=dedupe_calls,
            fallback_calls=fallback_calls,
            total_raw_chars=total_raw_chars,
            total_filtered_chars=total_filtered_chars,
            estimated_raw_tokens=estimated_raw_tokens,
            estimated_filtered_tokens=estimated_filtered_tokens,
            estimated_saved_tokens=estimated_raw_tokens - estimated_filtered_tokens,
            average_savings_pct=round(savings_sum / savings_count) if savings_count > 0 else 0,
            token_counts_are_estimate=any_estimate,
        )

    def format_summary(self) -> str:
        s = self.get_summary()
        if s.total_calls == 0:
            return "No filter activity recorded."

        def fmt(n: int) -> str:
            if n >= 1_000_000:
                return f"{n / 1_000_000:.1f}M"
            if n >= 1_000:
                return f"{n / 1_000:.1f}k"
            return str(n)

        est_tag = "~" if s.token_counts_are_estimate else ""
        return "\n".join([
            f"tool output raw: {fmt(s.total_raw_chars)} chars",
            f"tool output filtered: {fmt(s.total_filtered_chars)} chars",
            f"{est_tag}saved: {fmt(s.estimated_saved_tokens)} tokens",
            f"average savings: {s.average_savings_pct}%",
            f"dedupes: {s.dedupe_calls}",
            f"fallbacks: {s.fallback_calls}",
        ])

    def reset(self) -> None:
        self._entries.clear()


# Module-level singleton.
_store_instance: FilterTelemetryStore | None = None


def get_filter_telemetry_store() -> FilterTelemetryStore:
    """Get the singleton telemetry store."""
    global _store_instance
    if _store_instance is None:
        _store_instance = FilterTelemetryStore()
    return _store_instance


def reset_filter_telemetry_store() -> None:
    """Reset the telemetry store (for testing)."""
    global _store_instance
    if _store_instance is not None:
        _store_instance.reset()


def record_filter_telemetry(
    *,
    command: str,
    tool: str | None = None,
    filter_kind: str,
    raw_chars: int,
    filtered_chars: int,
    raw_output_id: int | None = None,
    fallback_used: bool = False,
) -> None:
    """Record a filter result in the telemetry store (heuristic token counts)."""
    savings_pct = round(((raw_chars - filtered_chars) / raw_chars) * 100) if raw_chars > 0 else 0

    get_filter_telemetry_store().record(
        FilterTelemetryEntry(
            command=command,
            tool=tool,
            filter_kind=filter_kind,
            raw_chars=raw_chars,
            filtered_chars=filtered_chars,
            estimated_raw_tokens=_estimate_tokens_heuristic(raw_chars),
            estimated_filtered_tokens=_estimate_tokens_heuristic(filtered_chars),
            savings_pct=savings_pct,
            raw_output_id=raw_output_id,
            fallback_used=fallback_used,
            token_counts_are_estimate=True,
            timestamp=time.time(),
        )
    )


def record_filter_telemetry_with_tokens(
    *,
    command: str,
    tool: str | None = None,
    filter_kind: str,
    raw_text: str,
    filtered_text: str,
    raw_chars: int,
    filtered_chars: int,
    raw_output_id: int | None = None,
    fallback_used: bool = False,
) -> None:
    """Record a filter result with real token counts (when strings are available)."""
    savings_pct = round(((raw_chars - filtered_chars) / raw_chars) * 100) if raw_chars > 0 else 0

    # Use tiktoken if available, otherwise heuristic.
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        raw_tokens = len(enc.encode(raw_text))
        filtered_tokens = len(enc.encode(filtered_text))
        is_estimate = False
    except (ImportError, Exception):
        raw_tokens = _estimate_tokens_heuristic(raw_chars)
        filtered_tokens = _estimate_tokens_heuristic(filtered_chars)
        is_estimate = True

    get_filter_telemetry_store().record(
        FilterTelemetryEntry(
            command=command,
            tool=tool,
            filter_kind=filter_kind,
            raw_chars=raw_chars,
            filtered_chars=filtered_chars,
            estimated_raw_tokens=raw_tokens,
            estimated_filtered_tokens=filtered_tokens,
            savings_pct=savings_pct,
            raw_output_id=raw_output_id,
            fallback_used=fallback_used,
            token_counts_are_estimate=is_estimate,
            timestamp=time.time(),
        )
    )
