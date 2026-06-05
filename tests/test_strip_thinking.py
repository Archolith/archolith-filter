"""Tests for archolith_filter.strip_thinking — thinking block stripping."""

from archolith_filter.strip_thinking import strip_thinking_blocks


class TestStripThinkingBlocks:
    def test_thinking_tag_removed(self):
        text = "before <thinking>internal reasoning</thinking> after"
        result = strip_thinking_blocks(text)
        assert "<thinking>" not in result
        assert "internal reasoning" not in result
        assert "before" in result
        assert "after" in result

    def test_ant_thinking_removed(self):
        text = "<antThinking>model thoughts</antThinking>response"
        result = strip_thinking_blocks(text)
        assert "<antThinking>" not in result
        assert "model thoughts" not in result
        assert "response" in result

    def test_reasoning_tag_removed(self):
        text = "<reasoning>step by step</reasoning>answer"
        result = strip_thinking_blocks(text)
        assert "<reasoning>" not in result
        assert "step by step" not in result

    def test_scratchpad_tag_removed(self):
        text = "<scratchpad>draft work</scratchpad>final"
        result = strip_thinking_blocks(text)
        assert "<scratchpad>" not in result

    def test_inner_monologue_tag_removed(self):
        text = "<inner_monologue>self-talk</inner_monologue>output"
        result = strip_thinking_blocks(text)
        assert "<inner_monologue>" not in result

    def test_multiline_content_removed(self):
        text = "before\n<thinking>\nline1\nline2\nline3\n</thinking>\nafter"
        result = strip_thinking_blocks(text)
        assert "line1" not in result
        assert "line2" not in result
        assert "before" in result
        assert "after" in result

    def test_unclosed_block_removed(self):
        text = "before <thinking>reasoning continues without end"
        result = strip_thinking_blocks(text)
        assert "<thinking>" not in result
        assert "reasoning continues" not in result
        assert "before" in result

    def test_multiple_blocks_removed(self):
        text = (
            "<thinking>block1</thinking>middle"
            "<reasoning>block2</reasoning>end"
        )
        result = strip_thinking_blocks(text)
        assert "block1" not in result
        assert "block2" not in result
        assert "middle" in result
        assert "end" in result

    def test_no_thinking_blocks_unchanged(self):
        text = "This is normal output without any thinking tags."
        result = strip_thinking_blocks(text)
        assert result == text

    def test_empty_string(self):
        assert strip_thinking_blocks("") == ""

    def test_excess_blank_lines_collapsed(self):
        text = "before\n<thinking>reasoning</thinking>\n\n\n\n\nafter"
        result = strip_thinking_blocks(text)
        assert "\n\n\n" not in result

    def test_case_insensitive(self):
        text = "<THINKING>content</THINKING>after"
        result = strip_thinking_blocks(text)
        assert "content" not in result
        assert "after" in result

    def test_empty_result_after_stripping(self):
        text = "<thinking>all content</thinking>"
        result = strip_thinking_blocks(text)
        assert result == "" or result.strip() == ""
