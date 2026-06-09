"""Tests for ReadFileFilterExtractor — uses archolith-filter's read_file_filter for characterisation."""

from __future__ import annotations

import httpx
import pytest

from archolith_filter.extractors.base import ToolCallRecord
from archolith_filter.extractors.read_file import ReadFileFilterExtractor


@pytest.fixture
def extractor():
    return ReadFileFilterExtractor()


@pytest.fixture
def http_client():
    return httpx.AsyncClient()


def _record(file_path: str, result: str) -> ToolCallRecord:
    return ToolCallRecord(
        tool_call_id="test-1",
        tool_name="Read",
        args={"file_path": file_path},
        result=result,
    )


# Build a barrel file with 50+ import lines
_BARREL_FILE = "\n".join(
    [f"from module.sub{i} import thing{i}" for i in range(60)]
)

# Build a generated file (long lines, 500+ chars, 5+ consecutive)
_GENERATED_FILE = "\n".join(
    ["x" * 600 + " = data"] * 8
)

# Normal Python file
_NORMAL_FILE = '''"""Module docstring."""

import os


def main():
    print("hello")


if __name__ == "__main__":
    main()
'''


@pytest.mark.asyncio
async def test_import_heavy_file_characterised(extractor, http_client):
    """Barrel file with 50+ imports gets 'import-heavy' annotation."""
    record = _record("src/__init__.py", _BARREL_FILE)
    result = await extractor.extract(record, http_client, turn_number=5, session_goal=None)
    assert len(result.facts) == 1
    assert "import-heavy" in result.facts[0]["content"]


@pytest.mark.asyncio
async def test_generated_file_characterised(extractor, http_client):
    """Lock file content gets 'generated' annotation."""
    record = _record("poetry.lock", _GENERATED_FILE)
    result = await extractor.extract(record, http_client, turn_number=5, session_goal=None)
    assert len(result.facts) == 1
    assert "generated" in result.facts[0]["content"]


@pytest.mark.asyncio
async def test_plain_file_no_annotation(extractor, http_client):
    """Normal Python file gets plain fact with no structural annotation."""
    record = _record("src/auth.py", _NORMAL_FILE)
    result = await extractor.extract(record, http_client, turn_number=3, session_goal=None)
    assert len(result.facts) == 1
    # Should NOT contain import-heavy or generated
    assert "import-heavy" not in result.facts[0]["content"]
    assert "generated" not in result.facts[0]["content"]
    assert "[Read] src/auth.py read at turn 3" in result.facts[0]["content"]


@pytest.mark.asyncio
async def test_files_touched_populated(extractor, http_client):
    """files_touched contains the file path."""
    record = _record("src/main.py", _NORMAL_FILE)
    result = await extractor.extract(record, http_client, turn_number=1, session_goal=None)
    assert "src/main.py" in result.files_touched


@pytest.mark.asyncio
async def test_empty_result_no_crash(extractor, http_client):
    """Empty result string produces a fact without line count."""
    record = _record("src/empty.py", "")
    result = await extractor.extract(record, http_client, turn_number=1, session_goal=None)
    assert len(result.facts) == 1
    assert "[Read] src/empty.py read at turn 1" in result.facts[0]["content"]
    assert result.used_llm is False


@pytest.mark.asyncio
async def test_small_file_no_annotation(extractor, http_client):
    """Small files under filter threshold get plain fact with no annotation."""
    record = _record("src/tiny.py", "x = 1\n")
    result = await extractor.extract(record, http_client, turn_number=1, session_goal=None)
    assert len(result.facts) == 1
    assert "import-heavy" not in result.facts[0]["content"]
    assert "generated" not in result.facts[0]["content"]
