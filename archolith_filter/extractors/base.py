"""Conditional import guard + FilterExtractorBase.

If archolith-context is installed, the real ToolExtractor ABC is used.
Otherwise, duck-typed stubs from _stubs.py are loaded so the module
can still be imported and unit-tested in isolation.
"""

from __future__ import annotations

try:
    from archolith_proxy.extractor.base import (
        PartialExtractionResult,
        ToolCallRecord,
        ToolExtractor,
    )

    _CONTEXT_AVAILABLE = True
except ImportError:
    from archolith_filter.extractors._stubs import (  # noqa: F401
        PartialExtractionResult,
        ToolCallRecord,
        ToolExtractor,
    )

    _CONTEXT_AVAILABLE = False


class FilterExtractorBase(ToolExtractor):
    """Base class for all filter-enhanced extractors.

    Adds no new abstract methods — it's a marker class for registry
    discovery. All filter extractors inherit from this to get a common
    ancestry that distinguishes them from archolith-context built-ins.
    """

    pass


# Backward compat: deprecated alias for FilterExtractorBase
RtkExtractorBase = FilterExtractorBase
