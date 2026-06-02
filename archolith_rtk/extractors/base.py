"""Conditional import guard + RtkExtractorBase.

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
    from archolith_rtk.extractors._stubs import (  # noqa: F401
        PartialExtractionResult,
        ToolCallRecord,
        ToolExtractor,
    )

    _CONTEXT_AVAILABLE = False


class RtkExtractorBase(ToolExtractor):
    """Base class for all RTK-enhanced extractors.

    Adds no new abstract methods — it's a marker class for registry
    discovery. All RTK extractors inherit from this to get a common
    ancestry that distinguishes them from built-in archolith-context
    extractors.
    """

    pass
