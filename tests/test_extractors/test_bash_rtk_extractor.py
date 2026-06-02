"""Tests for BashRtkExtractor — uses RTK's classifier for routing."""

from __future__ import annotations

import httpx
import pytest

from archolith_rtk.extractors.base import ToolCallRecord
from archolith_rtk.extractors.bash import BashRtkExtractor


@pytest.fixture
def extractor():
    return BashRtkExtractor()


@pytest.fixture
def http_client():
    return httpx.AsyncClient()


def _record(command: str, result: str) -> ToolCallRecord:
    return ToolCallRecord(
        tool_call_id="test-1",
        tool_name="Bash",
        args={"command": command},
        result=result,
    )


@pytest.mark.asyncio
async def test_classify_routes_pytest(extractor, http_client):
    """pytest output routes to test category with passed count."""
    record = _record("pytest tests/ -q", "5 passed, 1 failed")
    result = await extractor.extract(record, http_client, turn_number=3, session_goal=None)
    assert result.source_tool == "Bash"
    assert any("5 passed" in f["content"] for f in result.facts)
    assert any("1 failed" in f["content"] for f in result.facts)
    assert result.used_llm is False


@pytest.mark.asyncio
async def test_classify_routes_git_status(extractor, http_client):
    """git status output routes to git-status category with modified count."""
    output = """
On branch main
Changes not staged for commit:
  modified:   src/main.py
  modified:   src/utils.py

Untracked files:
  new_file:   src/new_module.py
"""
    record = _record("git status", output)
    result = await extractor.extract(record, http_client, turn_number=1, session_goal=None)
    assert any("git status" in f["content"] for f in result.facts)
    assert "src/main.py" in result.files_touched


@pytest.mark.asyncio
async def test_classify_routes_git_diff(extractor, http_client):
    """git diff output routes to git-diff category with changed file names."""
    output = """
diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
 import os
"""
    record = _record("git diff", output)
    result = await extractor.extract(record, http_client, turn_number=2, session_goal=None)
    assert any("git diff" in f["content"] for f in result.facts)
    assert "src/main.py" in result.files_touched


@pytest.mark.asyncio
async def test_classify_routes_git_log(extractor, http_client):
    """git log output routes to git-log category with commit hashes."""
    output = """
abc1234 Fix the widget parser
def5678 Add tests for parser
9ab0123 Bump version
"""
    record = _record("git log --oneline -3", output)
    result = await extractor.extract(record, http_client, turn_number=2, session_goal=None)
    assert any("git log" in f["content"] for f in result.facts)
    assert any("abc1234" in f["content"] for f in result.facts)
    assert result.used_llm is False


@pytest.mark.asyncio
async def test_builtin_produces_generic_fact(extractor, http_client):
    """Shell builtins produce a single generic fact, no crash."""
    record = _record("cd src && ls", "file1.py\nfile2.py\n")
    result = await extractor.extract(record, http_client, turn_number=1, session_goal=None)
    assert len(result.facts) >= 1
    assert result.used_llm is False


@pytest.mark.asyncio
async def test_ansi_stripped_before_classification(extractor, http_client):
    """ANSI-colored pytest output still routes to test category."""
    ansi_output = "\x1b[32m5 passed\x1b[0m, \x1b[31m1 failed\x1b[0m"
    record = _record("pytest tests/ -q", ansi_output)
    result = await extractor.extract(record, http_client, turn_number=1, session_goal=None)
    assert any("5 passed" in f["content"] for f in result.facts)


def test_tool_names_declared():
    """BashRtkExtractor declares tool_names for Bash and run_command."""
    ext = BashRtkExtractor()
    assert "Bash" in ext.tool_names
    assert "run_command" in ext.tool_names


def test_may_use_llm_false():
    """BashRtkExtractor never uses LLM."""
    ext = BashRtkExtractor()
    assert ext.may_use_llm is False
