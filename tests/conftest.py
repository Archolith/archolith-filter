"""Shared test fixtures for archolith_filter tests."""

import pytest

from archolith_filter.dedupe import reset_dedupe_tracker
from archolith_filter.raw_store import reset_raw_output_store
from archolith_filter.telemetry import reset_filter_telemetry_store


@pytest.fixture(autouse=True)
def _reset_stores():
    """Reset singleton stores between tests."""
    reset_raw_output_store()
    reset_filter_telemetry_store()
    reset_dedupe_tracker()
    yield
    reset_raw_output_store()
    reset_filter_telemetry_store()
    reset_dedupe_tracker()
