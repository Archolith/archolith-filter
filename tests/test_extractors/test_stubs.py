"""Tests for stub interface drift detection.

If archolith-context is installed, verify that the stubs match the
real class interface. This prevents stub drift as the ABC evolves.
"""

from __future__ import annotations

import pytest

from archolith_rtk.extractors._stubs import (
    PartialExtractionResult as StubPartialExtractionResult,
    ToolCallRecord as StubToolCallRecord,
    ToolExtractor as StubToolExtractor,
)


def test_stubs_match_real_interface():
    """If archolith-context is installed, assert stub fields match real classes.

    This test is a no-op when archolith-context is not installed (the stubs
    are the only interface available).
    """
    try:
        from archolith_proxy.extractor.base import (
            PartialExtractionResult,
            ToolCallRecord,
            ToolExtractor,
        )
    except ImportError:
        # archolith-context not installed — stubs are the reference, nothing to compare
        pytest.skip("archolith-context not installed, stubs are the reference")

    # Check ToolCallRecord fields match
    stub_fields = {f for f in StubToolCallRecord.__dataclass_fields__}
    real_fields = {f for f in ToolCallRecord.__dataclass_fields__}
    assert stub_fields == real_fields, f"ToolCallRecord field mismatch: stub={stub_fields} real={real_fields}"

    # Check PartialExtractionResult fields match
    stub_fields = {f for f in StubPartialExtractionResult.__dataclass_fields__}
    real_fields = {f for f in PartialExtractionResult.__dataclass_fields__}
    assert stub_fields == real_fields, f"PartialExtractionResult field mismatch: stub={stub_fields} real={real_fields}"

    # Check ToolExtractor class attributes
    assert hasattr(StubToolExtractor, "tool_names")
    assert hasattr(StubToolExtractor, "may_use_llm")
    assert hasattr(StubToolExtractor, "extract")
