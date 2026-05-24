from archolith_rtk.context_manager import (
    DEFAULT_CONTEXT_TOKENS,
    ContextManager,
    PostUsageKind,
    get_context_limit,
    simple_extractive_summarizer,
)
from archolith_rtk.shrink import ChatMessage

# --- get_context_limit ---


class TestGetContextLimit:
    def test_deepseek_model(self):
        assert get_context_limit("deepseek-v3") == 131072

    def test_gpt4o(self):
        assert get_context_limit("gpt-4o") == 128000

    def test_gpt4_base(self):
        assert get_context_limit("gpt-4") == 8192

    def test_claude(self):
        assert get_context_limit("claude-3.5-sonnet") == 200000

    def test_gemini(self):
        assert get_context_limit("gemini-2.5-pro") == 1048576

    def test_unknown_falls_back(self):
        assert get_context_limit("unknown-model") == DEFAULT_CONTEXT_TOKENS

    def test_partial_match(self):
        assert get_context_limit("my-custom-deepseek-v4-finetune") == 131072


# --- decide_after_usage ---


class TestDecideAfterUsage:
    def setup_method(self):
        self.cm = ContextManager(ctx_max=100000)

    def test_low_usage_none(self):
        d = self.cm.decide_after_usage(prompt_tokens=30000)
        assert d.kind == PostUsageKind.NONE
        assert d.ratio == 0.3

    def test_fold_threshold(self):
        d = self.cm.decide_after_usage(prompt_tokens=55000)
        assert d.kind == PostUsageKind.FOLD
        assert not d.aggressive
        assert d.tail_budget == int(100000 * 0.2)

    def test_aggressive_fold(self):
        d = self.cm.decide_after_usage(prompt_tokens=75000)
        assert d.kind == PostUsageKind.FOLD
        assert d.aggressive
        assert d.tail_budget == int(100000 * 0.1)

    def test_force_summary(self):
        d = self.cm.decide_after_usage(prompt_tokens=85000)
        assert d.kind == PostUsageKind.EXIT_WITH_SUMMARY

    def test_already_folded_skips(self):
        d = self.cm.decide_after_usage(prompt_tokens=55000, already_folded_this_turn=True)
        assert d.kind == PostUsageKind.NONE

    def test_already_folded_does_not_skip_exit(self):
        d = self.cm.decide_after_usage(prompt_tokens=85000, already_folded_this_turn=True)
        assert d.kind == PostUsageKind.EXIT_WITH_SUMMARY

    def test_zero_ctx_max(self):
        cm = ContextManager(ctx_max=0)
        d = cm.decide_after_usage(prompt_tokens=1000)
        assert d.kind == PostUsageKind.NONE

    def test_exact_threshold_boundary(self):
        # Exactly at 0.5 -- should be NONE (threshold is >, not >=)
        d = self.cm.decide_after_usage(prompt_tokens=50000)
        assert d.kind == PostUsageKind.NONE

    def test_model_based_ctx_max(self):
        cm = ContextManager(model="gpt-4o")
        d = cm.decide_after_usage(prompt_tokens=70000)
        assert d.kind == PostUsageKind.FOLD
        assert d.ctx_max == 128000

    def test_decide_after_turn_alias_accepts_messages(self):
        msgs = [ChatMessage(role="user", content="hello")]
        d = self.cm.decide_after_turn(msgs, prompt_tokens=55000)
        assert d.kind == PostUsageKind.FOLD
        assert d.tail_budget == int(100000 * 0.2)


# --- decide_preflight ---


class TestDecidePreflight:
    def test_small_payload_no_action(self):
        cm = ContextManager(ctx_max=100000)
        msgs = [ChatMessage(role="user", content="hi")]
        d = cm.decide_preflight(msgs)
        assert not d.needs_action

    def test_huge_payload_trips_emergency(self):
        cm = ContextManager(ctx_max=1000)
        msgs = [ChatMessage(role="user", content="x" * 50000)]
        d = cm.decide_preflight(msgs)
        assert d.needs_action

    def test_with_tool_specs(self):
        cm = ContextManager(ctx_max=1000)
        msgs = [ChatMessage(role="user", content="x" * 20000)]
        specs = [{"name": f"tool_{i}", "description": "x" * 100} for i in range(20)]
        d = cm.decide_preflight(msgs, specs)
        assert d.estimate_tokens > 0


# --- fold ---


class TestFold:
    def test_empty_messages(self):
        cm = ContextManager(ctx_max=100000)
        r = cm.fold([])
        assert not r.folded

    def test_single_message_no_fold(self):
        cm = ContextManager(ctx_max=100000)
        msgs = [ChatMessage(role="user", content="hello")]
        r = cm.fold(msgs)
        assert not r.folded

    def test_many_messages_folds(self):
        cm = ContextManager(ctx_max=100000)
        msgs = []
        for i in range(20):
            msgs.append(ChatMessage(role="user", content=f"User message {i} with enough text " * 50))
            msgs.append(ChatMessage(role="assistant", content=f"Response {i} with enough text " * 50))
            msgs.append(
                ChatMessage(
                    role="tool",
                    content=f"Tool output {i} with enough text " * 100,
                    tool_call_id=str(i),
                )
            )
        r = cm.fold(msgs, keep_recent_tokens=500)
        assert r.folded
        assert len(msgs) == r.after_messages
        assert msgs[0].role == "assistant"
        assert "CONVERSATION HISTORY SUMMARY" in (msgs[0].content or "")

    def test_fold_with_custom_summarizer(self):
        call_count = 0

        def my_summarizer(messages):
            nonlocal call_count
            call_count += 1
            return "Custom summary of the conversation."

        cm = ContextManager(ctx_max=100000, summarizer=my_summarizer)
        msgs = []
        for i in range(10):
            msgs.append(ChatMessage(role="user", content=f"Message {i} " * 200))
            msgs.append(ChatMessage(role="assistant", content=f"Reply {i} " * 200))
        r = cm.fold(msgs, keep_recent_tokens=500)
        if r.folded:
            assert call_count > 0
            assert r.summary_chars > 0


# --- emergency_compact ---


class TestEmergencyCompact:
    def test_short_messages_unchanged(self):
        cm = ContextManager(ctx_max=100000)
        msgs = [ChatMessage(role="user", content="hi"), ChatMessage(role="tool", content="ok", tool_call_id="1")]
        result = cm.emergency_compact(msgs)
        assert len(result) == 2
        assert result[1].content == "ok"

    def test_long_tool_message_compacted(self):
        cm = ContextManager(ctx_max=100000)
        msgs = [ChatMessage(role="tool", content="x" * 10000, tool_call_id="1")]
        result = cm.emergency_compact(msgs, max_result_chars=500)
        assert len(result[0].content) < 10000
        assert "truncated" in result[0].content

    def test_non_tool_messages_untouched(self):
        cm = ContextManager(ctx_max=100000)
        long_content = "y" * 10000
        msgs = [
            ChatMessage(role="user", content=long_content),
            ChatMessage(role="assistant", content=long_content),
        ]
        result = cm.emergency_compact(msgs, max_result_chars=500)
        assert result[0].content == long_content
        assert result[1].content == long_content


# --- simple_extractive_summarizer ---


class TestSimpleExtractiveSummarizer:
    def test_extracts_user_goals(self):
        msgs = [
            ChatMessage(role="user", content="I want to fix the login bug"),
            ChatMessage(role="tool", content="everything is fine", tool_call_id="1"),
        ]
        summary = simple_extractive_summarizer(msgs)
        assert "fix the login bug" in summary

    def test_extracts_important_tool_lines(self):
        msgs = [
            ChatMessage(role="tool", content="line1\nERROR: something failed\nline3", tool_call_id="1"),
        ]
        summary = simple_extractive_summarizer(msgs)
        assert "ERROR" in summary

    def test_empty_messages(self):
        summary = simple_extractive_summarizer([])
        assert summary == ""

    def test_fallback_head_tail(self):
        # No important lines, no user goals -- falls back to concatenation
        msgs = [ChatMessage(role="assistant", content="just some response text")]
        summary = simple_extractive_summarizer(msgs)
        assert "just some response" in summary

    def test_max_chars_respected(self):
        msgs = [ChatMessage(role="user", content="goal " * 10000)]
        summary = simple_extractive_summarizer(msgs, max_chars=200)
        assert len(summary) <= 300  # overhead for truncation marker
