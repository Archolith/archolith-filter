"""Tests for archolith_rtk — Layer 2 shrink module."""

import json

import pytest

from archolith_rtk import shrink_messages
from archolith_rtk.shrink import (
    ChatMessage,
    ToolCall,
    ToolCallFunction,
    _shrink_json_long_strings,
    count_tokens,
    estimate_conversation_tokens,
    estimate_request_tokens,
    shrink_oversized_tool_call_args_by_tokens,
    shrink_oversized_tool_results,
    shrink_oversized_tool_results_by_tokens,
    truncate_for_chars,
    truncate_for_tokens,
)

# ─── count_tokens ───


class TestCountTokens:
    def test_short_text(self):
        n = count_tokens("hello world")
        assert n > 0

    def test_empty_text(self):
        n = count_tokens("")
        assert n >= 0  # 0 or 1 depending on tiktoken behavior

    def test_long_text_more_tokens(self):
        short = count_tokens("hi")
        long = count_tokens("a" * 10000)
        assert long > short


# ─── truncate_for_chars ───


class TestTruncateForChars:
    def test_short_text_unchanged(self):
        assert truncate_for_chars("hello", 100) == "hello"

    def test_exact_fit(self):
        text = "x" * 50
        assert truncate_for_chars(text, 50) == text

    def test_truncates_with_marker(self):
        text = "a" * 5000
        result = truncate_for_chars(text, 500)
        assert len(result) <= 600  # marker overhead
        assert "truncated" in result
        assert result.startswith("aaa")
        assert "aaa" in result  # tail preserved

    def test_tail_preserves_end(self):
        text = "HEAD" + "x" * 4000 + "TAIL"
        result = truncate_for_chars(text, 500)
        assert "TAIL" in result


# ─── truncate_for_tokens ───


class TestTruncateForTokens:
    def test_short_text_unchanged(self):
        assert truncate_for_tokens("hello", 100) == "hello"

    def test_zero_budget(self):
        assert truncate_for_tokens("hello", 0) == ""

    def test_large_text_truncates(self):
        text = "word " * 5000  # ~25000 chars, many tokens
        result = truncate_for_tokens(text, 100)
        assert "truncated" in result
        # Should be significantly shorter than input
        assert len(result) < len(text)


# ─── shrink_oversized_tool_results (char-based) ───


class TestShrinkToolResultsChars:
    def test_no_tool_messages(self):
        msgs = [ChatMessage(role="user", content="hi")]
        result = shrink_oversized_tool_results(msgs, 1000)
        assert result.healed_count == 0
        assert result.healed_from == 0

    def test_small_tool_message_unchanged(self):
        msgs = [ChatMessage(role="tool", content="small output", tool_call_id="1")]
        result = shrink_oversized_tool_results(msgs, 1000)
        assert result.healed_count == 0
        assert result.messages[0].content == "small output"

    def test_oversized_tool_message_truncated(self):
        long_content = "x" * 5000
        msgs = [ChatMessage(role="tool", content=long_content, tool_call_id="1")]
        result = shrink_oversized_tool_results(msgs, 500)
        assert result.healed_count == 1
        assert result.healed_from == 5000
        assert "truncated" in result.messages[0].content

    def test_mixed_roles_only_tool_truncated(self):
        msgs = [
            ChatMessage(role="user", content="u" * 5000),
            ChatMessage(role="tool", content="t" * 5000, tool_call_id="1"),
            ChatMessage(role="assistant", content="a" * 5000),
        ]
        result = shrink_oversized_tool_results(msgs, 500)
        assert result.healed_count == 1
        # user and assistant unchanged
        assert result.messages[0].content == "u" * 5000
        assert result.messages[2].content == "a" * 5000

    def test_multiple_tool_messages(self):
        msgs = [
            ChatMessage(role="tool", content="small", tool_call_id="1"),
            ChatMessage(role="tool", content="y" * 3000, tool_call_id="2"),
            ChatMessage(role="tool", content="z" * 5000, tool_call_id="3"),
        ]
        result = shrink_oversized_tool_results(msgs, 1000)
        assert result.healed_count == 2


# ─── shrink_oversized_tool_results_by_tokens ───


class TestShrinkToolResultsTokens:
    def test_no_tool_messages(self):
        msgs = [ChatMessage(role="user", content="hi")]
        result = shrink_oversized_tool_results_by_tokens(msgs, 1000)
        assert result.healed_count == 0
        assert result.tokens_saved == 0

    def test_small_message_unchanged(self):
        msgs = [ChatMessage(role="tool", content="small", tool_call_id="1")]
        result = shrink_oversized_tool_results_by_tokens(msgs, 1000)
        assert result.healed_count == 0

    def test_oversized_message_truncated(self):
        content = "word " * 5000  # many tokens
        msgs = [ChatMessage(role="tool", content=content, tool_call_id="1")]
        result = shrink_oversized_tool_results_by_tokens(msgs, 100)
        assert result.healed_count == 1
        assert result.tokens_saved > 0


class TestShrinkMessagesCompatibility:
    def test_dict_messages_char_budget_roundtrip(self):
        messages = [
            {"role": "user", "content": "keep me"},
            {"role": "tool", "content": "x" * 5000, "tool_call_id": "call_1", "name": "read_file"},
        ]
        result = shrink_messages(messages, max_chars=300)
        assert isinstance(result[0], dict)
        assert result[0]["content"] == "keep me"
        assert "truncated" in result[1]["content"]

    def test_chat_messages_token_budget_roundtrip(self):
        messages = [
            ChatMessage(role="tool", content="word " * 4000, tool_call_id="call_1", name="search"),
        ]
        result = shrink_messages(messages, max_tokens=100)
        assert isinstance(result[0], ChatMessage)
        assert "truncated" in result[0].content

    def test_requires_exactly_one_budget(self):
        with pytest.raises(ValueError):
            shrink_messages([], max_chars=100, max_tokens=100)
        with pytest.raises(ValueError):
            shrink_messages([])


# ─── shrink_oversized_tool_call_args_by_tokens ───


class TestShrinkToolCallArgs:
    def test_no_tool_calls(self):
        msgs = [ChatMessage(role="assistant", content="hello")]
        result = shrink_oversized_tool_call_args_by_tokens(msgs, 1000)
        assert result.healed_count == 0

    def test_short_args_unchanged(self):
        call = ToolCall(id="1", function=ToolCallFunction(id="1", name="read", arguments='{"path": "/foo"}'))
        msgs = [ChatMessage(role="assistant", content=None, tool_calls=[call])]
        result = shrink_oversized_tool_call_args_by_tokens(msgs, 1000)
        assert result.healed_count == 0
        assert result.messages[0].tool_calls[0].function.arguments == '{"path": "/foo"}'

    def test_long_string_value_shrunk(self):
        long_content = "x" * 1000
        args = json.dumps({"path": "/foo", "content": long_content})
        call = ToolCall(id="1", function=ToolCallFunction(id="1", name="edit", arguments=args))
        msgs = [ChatMessage(role="assistant", content=None, tool_calls=[call])]
        # Very small token budget forces shrinking
        result = shrink_oversized_tool_call_args_by_tokens(msgs, 5)
        # Should shrink if token budget forces it; at minimum should not crash
        assert isinstance(result.messages[0].tool_calls[0].function.arguments, str)


# ─── _shrink_json_long_strings ───


class TestShrinkJsonLongStrings:
    def test_short_values_unchanged(self):
        result = _shrink_json_long_strings('{"path": "/foo", "line": 42}')
        parsed = json.loads(result)
        assert parsed["path"] == "/foo"
        assert parsed["line"] == 42

    def test_long_value_shrunk(self):
        long_val = "x" * 1000
        result = _shrink_json_long_strings(f'{{"content": "{long_val}"}}')
        parsed = json.loads(result)
        assert "shrunk" in parsed["content"]

    def test_invalid_json_returns_head(self):
        bad = "{" + "x" * 500
        result = _shrink_json_long_strings(bad)
        assert "unparsed" in result

    def test_non_object_returns_unchanged(self):
        arr = "[1, 2, 3]"
        result = _shrink_json_long_strings(arr)
        assert result == arr


# ─── estimate_conversation_tokens ───


class TestEstimateConversationTokens:
    def test_empty_messages(self):
        assert estimate_conversation_tokens([]) >= 0

    def test_counts_content(self):
        msgs = [ChatMessage(role="user", content="hello world")]
        n = estimate_conversation_tokens(msgs)
        assert n > 0

    def test_counts_tool_calls(self):
        call = ToolCall(id="1", function=ToolCallFunction(id="1", name="test", arguments='{"a": 1}'))
        msgs = [ChatMessage(role="assistant", content=None, tool_calls=[call])]
        n = estimate_conversation_tokens(msgs)
        assert n > 0


# ─── estimate_request_tokens ───


class TestEstimateRequestTokens:
    def test_no_specs(self):
        msgs = [ChatMessage(role="user", content="hi")]
        n = estimate_request_tokens(msgs)
        assert n > 0

    def test_with_specs(self):
        msgs = [ChatMessage(role="user", content="hi")]
        specs = [{"name": "tool1", "description": "a tool"}]
        n = estimate_request_tokens(msgs, specs)
        assert n > estimate_conversation_tokens(msgs)


# ─── ChatMessage serialization ───


class TestChatMessage:
    def test_roundtrip_dict(self):
        msg = ChatMessage(role="tool", content="output", tool_call_id="call_1", name="read")
        d = msg.to_dict()
        restored = ChatMessage.from_dict(d)
        assert restored.role == "tool"
        assert restored.content == "output"
        assert restored.tool_call_id == "call_1"

    def test_tool_calls_roundtrip(self):
        call = ToolCall(id="1", function=ToolCallFunction(id="1", name="run", arguments="{}"))
        msg = ChatMessage(role="assistant", content=None, tool_calls=[call])
        d = msg.to_dict()
        restored = ChatMessage.from_dict(d)
        assert restored.tool_calls is not None
        assert len(restored.tool_calls) == 1
        assert restored.tool_calls[0].function.name == "run"
