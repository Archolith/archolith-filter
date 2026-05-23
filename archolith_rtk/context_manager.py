"""Layer 3: Context manager -- threshold-based conversation folding.

Decides when to fold conversation history based on token usage ratios,
and executes the fold by replacing older turns with a summary message.

Thresholds:
  < 50%  : carry on -- no action
  50-70% : normal fold -- keep recent 20% of context as tail
  70-80% : aggressive fold -- keep only 10% as tail
  80-95% : exit with summary (defense in depth)
  > 95%  : emergency preflight -- in-place compact

The summarize step is optional: pass a callable that takes a list of
messages and returns a summary string, or use the built-in simple
extractive summarizer for deterministic operation without LLM calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

from .shrink import (
    ChatMessage,
    estimate_conversation_tokens,
    estimate_request_tokens,
    shrink_oversized_tool_results,
)

# --- Thresholds ---

HISTORY_FOLD_THRESHOLD = 0.5
"""Auto-fold when promptTokens above this fraction of ctxMax."""

HISTORY_FOLD_TAIL_FRACTION = 0.2
"""Tail budget after a normal fold, as fraction of ctxMax."""

HISTORY_FOLD_AGGRESSIVE_THRESHOLD = 0.7
"""Above this fraction the normal fold did not buy enough headroom -- fold harder."""

HISTORY_FOLD_AGGRESSIVE_TAIL_FRACTION = 0.1
"""Tail budget after aggressive fold -- half the normal one."""

HISTORY_FOLD_MIN_SAVINGS_FRACTION = 0.3
"""Skip fold if head would not shrink the log by at least this fraction."""

FORCE_SUMMARY_THRESHOLD = 0.8
"""Above this fraction we exit with a summary instead of folding."""

PREFLIGHT_EMERGENCY_THRESHOLD = 0.95
"""Local preflight above this fraction trips emergency in-place compact."""

HISTORY_FOLD_MARKER = (
    "[CONVERSATION HISTORY SUMMARY -- earlier turns folded for context efficiency]\n\n"
)


# --- Decision types ---


class PostUsageKind(str, Enum):
    NONE = "none"
    FOLD = "fold"
    EXIT_WITH_SUMMARY = "exit-with-summary"


@dataclass(frozen=True)
class PostUsageDecision:
    """Decision after a turn's response -- fold, exit, or carry on."""
    kind: PostUsageKind
    prompt_tokens: int
    ctx_max: int
    ratio: float
    tail_budget: int | None = None
    aggressive: bool = False


@dataclass(frozen=True)
class PreflightDecision:
    """Local-side preflight before sending a request."""
    needs_action: bool
    estimate_tokens: int
    ctx_max: int


@dataclass(frozen=True)
class FoldResult:
    """Result of a fold operation."""
    folded: bool
    before_messages: int
    after_messages: int
    summary_chars: int


# --- Summarizer protocol ---


class SummarizerFn(Protocol):
    """Protocol for summarizer callables."""
    def __call__(self, messages: list[ChatMessage]) -> str: ...


# --- Simple extractive summarizer (deterministic, no LLM) ---

_IMPORTANT_LINE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(?:error|fail|todo|fix|hack|bug|warning|decision)"),
    re.compile(r"(?i)(?:goal|objective|purpose|intent)"),
    re.compile(r"(?i)(?:created|modified|deleted|renamed)\s+\S+"),
    re.compile(r"(?i)(?:feat|fix|refactor|chore):\s"),
]

_USER_LINE_MAX = 120


def simple_extractive_summarizer(messages: list[ChatMessage], max_chars: int = 3000) -> str:
    """Deterministic extractive summarizer -- no LLM calls.

    Extracts important lines from tool results and user messages,
    preserving user goals and key decisions. Falls back to generic
    head+tail truncation if no important lines found.
    """
    important: list[str] = []
    user_goals: list[str] = []

    for msg in messages:
        if msg.role == "user" and msg.content:
            for line in msg.content.splitlines():
                stripped = line.strip()
                if stripped and len(stripped) <= _USER_LINE_MAX:
                    user_goals.append(stripped)
                    if len(user_goals) >= 10:
                        break

        if msg.role == "tool" and msg.content:
            for line in msg.content.splitlines():
                stripped = line.strip()
                if any(p.search(stripped) for p in _IMPORTANT_LINE_PATTERNS):
                    important.append(stripped)

    if not important and not user_goals:
        all_text = "\n".join(
            msg.content for msg in messages if msg.content
        )
        if len(all_text) <= max_chars:
            return all_text
        head = all_text[: max_chars // 2]
        tail = all_text[-(max_chars // 2):]
        return f"{head}\n\n[...middle omitted...]\n\n{tail}"

    parts: list[str] = []
    if user_goals:
        parts.append("User goals/intent:")
        parts.extend(f"- {g}" for g in user_goals[:10])
        parts.append("")
    if important:
        parts.append("Key findings:")
        parts.extend(f"- {l}" for l in important[:30])

    result = "\n".join(parts)
    if len(result) > max_chars:
        return result[:max_chars] + "\n[...truncated...]"
    return result


# --- Context Manager ---

_MODEL_CONTEXT_TOKENS: dict[str, int] = {
    # Order matters for partial matching: longer/more-specific keys first.
    "gemini-2.5-pro": 1048576,
    "gemini-2.0-flash": 1048576,
    "claude-4-opus": 200000,
    "claude-3.5-sonnet": 200000,
    "claude-3-opus": 200000,
    "o3-mini": 200000,
    "o1": 200000,
    "o1-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4o": 128000,
    "gpt-4": 8192,
    "deepseek-v4-flash": 131072,
    "deepseek-v4": 131072,
    "deepseek-v3": 131072,
    "deepseek-reasoner": 131072,
    "deepseek-chat": 131072,
}

DEFAULT_CONTEXT_TOKENS = 128000


def get_context_limit(model: str) -> int:
    """Get the context window size for a model name.

    Falls back to DEFAULT_CONTEXT_TOKENS for unknown models.
    """
    model_lower = model.lower()
    for key, limit in _MODEL_CONTEXT_TOKENS.items():
        if key in model_lower:
            return limit
    return DEFAULT_CONTEXT_TOKENS


@dataclass
class ContextManager:
    """Threshold-based context window manager.

    Args:
        summarizer: Callable that produces a summary string from messages.
            Defaults to simple_extractive_summarizer (deterministic, no LLM).
        ctx_max: Override context window size. If None, auto-detected from model.
        model: Model name for context size lookup.
    """
    summarizer: Callable[[list[ChatMessage]], str] = field(
        default_factory=lambda: simple_extractive_summarizer
    )
    ctx_max: int | None = None
    model: str = ""

    def _get_ctx_max(self) -> int:
        if self.ctx_max is not None:
            return self.ctx_max
        return get_context_limit(self.model)

    def decide_after_usage(
        self,
        prompt_tokens: int,
        already_folded_this_turn: bool = False,
    ) -> PostUsageDecision:
        """Decide what to do after a turn based on token usage ratios."""
        ctx_max = self._get_ctx_max()
        if ctx_max <= 0:
            return PostUsageDecision(
                kind=PostUsageKind.NONE, prompt_tokens=prompt_tokens,
                ctx_max=ctx_max, ratio=0,
            )

        ratio = prompt_tokens / ctx_max
        base = PostUsageDecision(
            kind=PostUsageKind.NONE, prompt_tokens=prompt_tokens,
            ctx_max=ctx_max, ratio=ratio,
        )

        if ratio > FORCE_SUMMARY_THRESHOLD:
            return PostUsageDecision(
                kind=PostUsageKind.EXIT_WITH_SUMMARY,
                prompt_tokens=prompt_tokens, ctx_max=ctx_max, ratio=ratio,
            )

        if already_folded_this_turn:
            return base

        if ratio > HISTORY_FOLD_AGGRESSIVE_THRESHOLD:
            return PostUsageDecision(
                kind=PostUsageKind.FOLD,
                prompt_tokens=prompt_tokens, ctx_max=ctx_max, ratio=ratio,
                tail_budget=int(ctx_max * HISTORY_FOLD_AGGRESSIVE_TAIL_FRACTION),
                aggressive=True,
            )

        if ratio > HISTORY_FOLD_THRESHOLD:
            return PostUsageDecision(
                kind=PostUsageKind.FOLD,
                prompt_tokens=prompt_tokens, ctx_max=ctx_max, ratio=ratio,
                tail_budget=int(ctx_max * HISTORY_FOLD_TAIL_FRACTION),
                aggressive=False,
            )

        return base

    def decide_preflight(
        self,
        messages: list[ChatMessage],
        tool_specs: list[dict] | None = None,
    ) -> PreflightDecision:
        """Local-side preflight check before API call."""
        ctx_max = self._get_ctx_max()
        estimate = estimate_request_tokens(messages, tool_specs)
        return PreflightDecision(
            needs_action=(estimate / ctx_max > PREFLIGHT_EMERGENCY_THRESHOLD) if ctx_max > 0 else False,
            estimate_tokens=estimate,
            ctx_max=ctx_max,
        )

    def fold(
        self,
        messages: list[ChatMessage],
        keep_recent_tokens: int | None = None,
    ) -> FoldResult:
        """Replace older turns with one summary message; keep tail within budget."""
        ctx_max = self._get_ctx_max()
        tail_budget = keep_recent_tokens or int(ctx_max * HISTORY_FOLD_TAIL_FRACTION)

        noop = FoldResult(
            folded=False,
            before_messages=len(messages),
            after_messages=len(messages),
            summary_chars=0,
        )

        if not messages:
            return noop

        token_counts = [estimate_conversation_tokens([m]) for m in messages]
        total_tokens = sum(token_counts)

        # Walk backward from end, accumulating tokens until budget.
        cum_tokens = 0
        boundary = len(messages)
        for i in range(len(messages) - 1, -1, -1):
            if cum_tokens + token_counts[i] > tail_budget:
                break
            cum_tokens += token_counts[i]
            if messages[i].role == "user":
                boundary = i

        if boundary <= 0:
            return noop

        head = messages[:boundary]
        tail = messages[boundary:]
        head_tokens = total_tokens - cum_tokens

        if head_tokens < total_tokens * HISTORY_FOLD_MIN_SAVINGS_FRACTION:
            return noop

        # Shrink tool results in head before summarizing.
        shrunk = shrink_oversized_tool_results(head, max_chars=5000)

        summary = self.summarizer(shrunk.messages)
        if not summary:
            return noop

        summary_msg = ChatMessage(
            role="assistant",
            content=HISTORY_FOLD_MARKER + summary,
        )
        replacement = [summary_msg] + tail

        return FoldResult(
            folded=True,
            before_messages=len(messages),
            after_messages=len(replacement),
            summary_chars=len(summary),
        )

    def emergency_compact(
        self,
        messages: list[ChatMessage],
        max_result_chars: int = 2000,
    ) -> list[ChatMessage]:
        """Emergency in-place compact for preflight > 95%."""
        from .shrink import truncate_for_chars

        out: list[ChatMessage] = []
        for msg in messages:
            if msg.role == "tool" and msg.content and len(msg.content) > max_result_chars:
                truncated = truncate_for_chars(msg.content, max_result_chars)
                out.append(ChatMessage(
                    role=msg.role, content=truncated,
                    tool_call_id=msg.tool_call_id, name=msg.name,
                ))
            else:
                out.append(msg)
        return out
