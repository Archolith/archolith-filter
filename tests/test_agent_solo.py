"""Tests for archolith_rtk.agent_solo — agent-solo turn compression."""

import pytest

from archolith_rtk.agent_solo import (
    AgentSoloResult,
    AgentSoloStats,
    _is_compressible_tool,
    _split_sections,
    compress_agent_solo_turn,
)
from archolith_rtk.dedupe import DedupeTracker


# ─── Helpers ───


def _tool_msg(content: str, name: str = "read_file") -> dict:
    return {"role": "tool", "content": content, "name": name, "tool_call_id": "tc_1"}


def _user_msg(text: str = "hello") -> dict:
    return {"role": "user", "content": text}


def _assistant_msg(text: str = "ok") -> dict:
    return {"role": "assistant", "content": text}


def _system_msg(text: str = "you are helpful") -> dict:
    return {"role": "system", "content": text}


# ─── _is_compressible_tool ───


class TestIsCompressibleTool:
    def test_bash_compressible(self):
        assert _is_compressible_tool("bash") is True

    def test_grep_compressible(self):
        assert _is_compressible_tool("grep") is True

    def test_search_compressible(self):
        assert _is_compressible_tool("search") is True

    def test_read_file_not_compressible(self):
        assert _is_compressible_tool("read_file") is False

    def test_empty_not_compressible(self):
        assert _is_compressible_tool("") is False

    def test_namespaced_tool(self):
        assert _is_compressible_tool("mcp__brave__search") is True

    def test_unknown_not_compressible(self):
        assert _is_compressible_tool("custom_tool") is False


# ─── _split_sections ───


class TestSplitSections:
    def test_basic_split(self):
        msgs = [
            _system_msg(),
            _user_msg(), _assistant_msg(), _tool_msg("a"),
            _user_msg(), _assistant_msg(), _tool_msg("b"),
            _user_msg(), _assistant_msg(), _tool_msg("c"),
        ]
        system, middle, tail = _split_sections(msgs, coherence_tail_size=3)
        assert len(system) == 1
        assert len(tail) == 3
        assert len(middle) == 6

    def test_no_system(self):
        msgs = [_user_msg(), _assistant_msg(), _tool_msg("a"), _user_msg()]
        system, middle, tail = _split_sections(msgs, coherence_tail_size=2)
        assert len(system) == 0
        assert len(tail) == 2
        assert len(middle) == 2

    def test_too_few_for_middle(self):
        msgs = [_system_msg(), _user_msg(), _assistant_msg()]
        system, middle, tail = _split_sections(msgs, coherence_tail_size=5)
        assert len(system) == 1
        assert len(middle) == 0
        assert len(tail) == 2


# ─── Strategy A: Shrink ───


class TestShrinkStrategy:
    def test_shrink_reduces_large_tool_results(self):
        large_content = "x" * 20_000
        messages = [_user_msg(), _tool_msg(large_content)]
        result = compress_agent_solo_turn(
            messages,
            shrink_enabled=True,
            shrink_max_tokens=100,
        )
        assert result.stats.chars_saved_shrink > 0
        assert "shrink" in result.stats.strategies_applied
        # Output should be smaller
        out_content = result.messages[1]["content"]
        assert len(out_content) < len(large_content)

    def test_shrink_no_savings_on_small(self):
        messages = [_user_msg(), _tool_msg("small")]
        result = compress_agent_solo_turn(
            messages,
            shrink_enabled=True,
            shrink_max_tokens=2000,
        )
        assert result.stats.chars_saved_shrink == 0
        assert "shrink" not in result.stats.strategies_applied


# ─── Strategy B: Dedup ───


class TestDedupStrategy:
    def test_dedup_replaces_repeated_content(self):
        content = "a" * 500
        tracker = DedupeTracker()

        # First turn — records hashes
        msgs1 = [_user_msg(), _tool_msg(content)]
        r1 = compress_agent_solo_turn(
            msgs1, dedup_tracker=tracker, dedup_enabled=True,
        )
        assert r1.stats.chars_saved_dedup == 0  # first time, no savings

        # Second turn — same content should be deduped
        msgs2 = [_user_msg(), _tool_msg(content)]
        r2 = compress_agent_solo_turn(
            msgs2, dedup_tracker=tracker, dedup_enabled=True,
        )
        assert r2.stats.chars_saved_dedup > 0
        assert "dedup" in r2.stats.strategies_applied
        assert "identical" in r2.messages[1]["content"].lower()

    def test_dedup_skips_small_content(self):
        tracker = DedupeTracker()
        messages = [_user_msg(), _tool_msg("tiny")]
        # First pass
        compress_agent_solo_turn(messages, dedup_tracker=tracker, dedup_enabled=True)
        # Second pass
        r = compress_agent_solo_turn(messages, dedup_tracker=tracker, dedup_enabled=True)
        assert r.stats.chars_saved_dedup == 0  # too small to dedup

    def test_dedup_different_content_not_replaced(self):
        tracker = DedupeTracker()
        msgs1 = [_user_msg(), _tool_msg("a" * 500)]
        compress_agent_solo_turn(msgs1, dedup_tracker=tracker, dedup_enabled=True)
        msgs2 = [_user_msg(), _tool_msg("b" * 500)]
        r = compress_agent_solo_turn(msgs2, dedup_tracker=tracker, dedup_enabled=True)
        assert r.stats.chars_saved_dedup == 0


# ─── Strategy C: Filter middle ───


class TestFilterMiddleStrategy:
    def test_filter_middle_compresses_bash_in_middle(self):
        large_bash = "line\n" * 2000  # ~10K chars of bash output
        messages = [
            _system_msg(),
            _user_msg(), _assistant_msg(),
            _tool_msg(large_bash, name="bash"),
            _user_msg(), _assistant_msg(),
            _tool_msg("recent result", name="read_file"),
        ]
        result = compress_agent_solo_turn(
            messages,
            filter_middle_enabled=True,
            coherence_tail_size=3,
        )
        assert result.stats.chars_saved_filter > 0
        assert "filter" in result.stats.strategies_applied

    def test_filter_middle_preserves_read_file_in_middle(self):
        large_read = "x" * 2000
        messages = [
            _system_msg(),
            _user_msg(), _assistant_msg(),
            _tool_msg(large_read, name="read_file"),
            _user_msg(), _assistant_msg(),
            _tool_msg("tail", name="read_file"),
        ]
        result = compress_agent_solo_turn(
            messages,
            filter_middle_enabled=True,
            coherence_tail_size=3,
        )
        # read_file is not compressible — middle should be preserved
        assert result.stats.chars_saved_filter >= 0
        # The middle read_file content should not be filtered
        middle_tool = result.messages[3]
        assert middle_tool["content"] == large_read


# ─── Orchestrator ───


class TestOrchestrator:
    def test_no_strategies_returns_original(self):
        messages = [_user_msg(), _tool_msg("hello")]
        result = compress_agent_solo_turn(messages)
        assert result.messages is messages
        assert result.stats.skipped_reason == "no_strategies_enabled"

    def test_all_strategies_combined(self):
        tracker = DedupeTracker()
        large = "x" * 10_000
        messages = [
            _system_msg(),
            _user_msg(), _assistant_msg(),
            _tool_msg(large, name="bash"),
            _user_msg(), _assistant_msg(),
            _tool_msg("tail content", name="read_file"),
        ]
        result = compress_agent_solo_turn(
            messages,
            dedup_tracker=tracker,
            shrink_enabled=True,
            dedup_enabled=True,
            filter_middle_enabled=True,
            shrink_max_tokens=500,
            coherence_tail_size=3,
        )
        assert result.stats.total_chars_saved > 0

    def test_stats_to_dict(self):
        stats = AgentSoloStats(
            strategies_applied=["shrink"],
            chars_saved_shrink=100,
            total_chars_saved=100,
        )
        d = stats.to_dict()
        assert d["strategies_applied"] == ["shrink"]
        assert d["chars_saved_shrink"] == 100
        assert d["total_chars_saved"] == 100
        assert d["skipped_reason"] is None

    def test_non_tool_messages_preserved(self):
        messages = [
            _system_msg("sys"),
            _user_msg("hi"),
            _assistant_msg("bye"),
        ]
        result = compress_agent_solo_turn(
            messages, shrink_enabled=True, shrink_max_tokens=100,
        )
        assert len(result.messages) == 3
        assert result.messages[0]["content"] == "sys"
        assert result.messages[1]["content"] == "hi"
        assert result.messages[2]["content"] == "bye"
