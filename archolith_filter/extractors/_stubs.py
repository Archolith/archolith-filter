"""Stub implementations used when archolith-context is not installed.

These duck-typed stubs match the interface of the real classes in
archolith_proxy.extractor.base. They allow the extractors subpackage
to load and be unit-tested without archolith-context installed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx


@dataclass
class ToolCallRecord:
    """One tool invocation: name, args, and the raw result string."""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    result: str


@dataclass
class PartialExtractionResult:
    """Facts/files produced by a single ToolExtractor."""

    source_tool: str
    facts: list[dict[str, Any]] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    used_llm: bool = False


class ToolExtractor(ABC):
    """Abstract base for per-tool extractors (stub)."""

    tool_names: tuple[str, ...] = ()
    may_use_llm: bool = False

    @abstractmethod
    async def extract(
        self,
        record: ToolCallRecord,
        http_client: httpx.AsyncClient,
        turn_number: int,
        session_goal: str | None,
    ) -> PartialExtractionResult:
        ...
