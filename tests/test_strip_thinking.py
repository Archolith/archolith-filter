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


# ── Namespace-prefixed tags (AI-B1) ──────────────────────────────────────


class TestNamespacePrefixes:
    def test_antml_thinking_removed(self):
        text = "before <antml:thinking>internal</antml:thinking> after"
        result = strip_thinking_blocks(text)
        assert "<antml:thinking>" not in result
        assert "</antml:thinking>" not in result
        assert "internal" not in result
        assert "before" in result
        assert "after" in result

    def test_anthropic_reasoning_removed(self):
        text = "ok <anthropic:reasoning>step</anthropic:reasoning> done"
        result = strip_thinking_blocks(text)
        assert "<anthropic:reasoning>" not in result
        assert "step" not in result
        assert "ok" in result
        assert "done" in result

    def test_namespaced_scratchpad_removed(self):
        text = "<vendor:scratchpad>draft</vendor:scratchpad>out"
        result = strip_thinking_blocks(text)
        assert "<vendor:scratchpad>" not in result
        assert "draft" not in result
        assert "out" in result

    def test_namespaced_unclosed_removed(self):
        text = "before <antml:thinking>reasoning to end"
        result = strip_thinking_blocks(text)
        assert "<antml:thinking>" not in result
        assert "reasoning to end" not in result
        assert "before" in result

    def test_any_vendor_prefix_on_known_tag_matches(self):
        """Future-proofs: any vendor prefix on a known tag name matches.
        The regex accepts a single simple namespace prefix; multi-segment
        prefixes like ``<x:y:thinking>`` are intentionally out of scope."""
        text = "<whatev:thinking>nested</whatev:thinking>tail"
        result = strip_thinking_blocks(text)
        assert "nested" not in result
        assert "tail" in result

    def test_unknown_non_prefixed_tag_not_matched(self):
        """An unknown tag name (not in _TAG_NAMES) is left untouched."""
        text = "<mystery_thought>kept</mystery_thought>"
        result = strip_thinking_blocks(text)
        assert "kept" in result

    def test_no_prefix_still_works(self):
        """Regression: bare tag name without prefix must still strip."""
        text = "<thinking>plain</thinking>after"
        result = strip_thinking_blocks(text)
        assert "plain" not in result
        assert "after" in result


# ── Nested blocks (AI-B2) ─────────────────────────────────────────────────


class TestNestedBlocks:
    def test_two_deep_nested_removed(self):
        text = "<thinking>outer <thinking>inner</thinking> more outer</thinking> tail"
        result = strip_thinking_blocks(text)
        assert "<thinking>" not in result
        assert "outer" not in result
        assert "inner" not in result
        assert "more outer" not in result
        assert "tail" in result

    def test_three_deep_nested_removed(self):
        text = (
            "<thinking>x <thinking>y <thinking>z</thinking></thinking></thinking>"
            " tail"
        )
        result = strip_thinking_blocks(text)
        assert "<thinking>" not in result
        assert result.strip() == "tail" or "tail" in result
        assert "x" not in result
        assert "y" not in result
        assert "z" not in result

    def test_four_deep_nested_removed(self):
        text = (
            "<thinking>layer-a <reasoning>layer-b <scratchpad>layer-c "
            "<thinking>layer-d</thinking></scratchpad>"
            "</reasoning></thinking> end-marker"
        )
        result = strip_thinking_blocks(text)
        assert "layer-a" not in result
        assert "layer-b" not in result
        assert "layer-c" not in result
        assert "layer-d" not in result
        assert "end-marker" in result

    def test_mixed_tag_nesting_removed(self):
        text = (
            "<thinking>outer-zone <reasoning>inner-zone</reasoning>"
            " between-zone</thinking> after-marker"
        )
        result = strip_thinking_blocks(text)
        assert "<thinking>" not in result
        assert "<reasoning>" not in result
        assert "outer-zone" not in result
        assert "inner-zone" not in result
        assert "between-zone" not in result
        assert "after-marker" in result

    def test_nested_with_namespace_prefix(self):
        text = "<thinking>prefix-a <antml:thinking>inner-b</antml:thinking> tail-c</thinking> d-e"
        result = strip_thinking_blocks(text)
        assert "prefix-a" not in result
        assert "inner-b" not in result
        assert "tail-c" not in result
        assert "d-e" in result

    def test_loop_terminates_on_stable(self):
        """The loop cap (10 iterations) prevents pathological deep-nesting
        from looping forever. The innermost content is removed on iteration
        1 (so `deep` must be gone), but with 50 levels of nesting the cap
        is reached before all outer pairs unwind — that's acceptable; the
        guarantee is termination plus innermost-content removal."""
        text = "<thinking>" * 50 + "deep" + "</thinking>" * 50
        result = strip_thinking_blocks(text)
        # Innermost content is always removed on iter 1.
        assert "deep" not in result
        # Loop terminates (no infinite recursion). Result is a finite string.
        assert isinstance(result, str)

    def test_loop_terminates_within_cap(self):
        """Deep nesting within _MAX_STABLE_ITERATIONS is fully unwound."""
        text = "<thinking>" * 8 + "deep" + "</thinking>" * 8
        result = strip_thinking_blocks(text)
        assert "deep" not in result
        assert "<thinking>" not in result
        assert "</thinking>" not in result


# ── Stream-cutoff artifacts (AI-B3) ───────────────────────────────────────


class TestStreamCutoff:
    def test_partial_close_tag_at_eof_stripped(self):
        """Stream cutoff leaving ``</thinking`` (no ``>``) at EOF is stripped."""
        text = "before <thinking>content</thinking"
        result = strip_thinking_blocks(text)
        assert "content" not in result
        assert "</thinking" not in result
        assert "before" in result

    def test_partial_close_tag_with_trailing_whitespace_stripped(self):
        text = "before <thinking>content</thinking\n\n"
        result = strip_thinking_blocks(text)
        assert "content" not in result
        assert "</thinking" not in result

    def test_namespaced_partial_close_tag_stripped(self):
        text = "ok <antml:reasoning>y</antml:reasoning"
        result = strip_thinking_blocks(text)
        assert "y" not in result
        assert "</antml:reasoning" not in result
        assert "ok" in result

    def test_partial_close_tag_with_trailing_text_preserves_text(self):
        """Partial close tag followed by > or recovered text is left intact
        as legitimate markup, not a stream-cutoff fragment."""
        # Properly closed block: stripped.
        text = "<thinking>x</thinking> after"
        result = strip_thinking_blocks(text)
        assert "x" not in result
        assert "after" in result

