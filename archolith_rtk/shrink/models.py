"""Message data types for the shrink subsystem.

OpenAI-format chat message, tool call, and tool call function dataclasses,
plus shrink result containers.

Import DAG: leaf — no internal dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChatMessage:
    """Minimal OpenAI-format chat message."""

    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict:
        d: dict[str, object] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls is not None:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ChatMessage:
        tool_calls = None
        if "tool_calls" in d and isinstance(d["tool_calls"], list):
            tool_calls = [ToolCall.from_dict(tc) for tc in d["tool_calls"]]
        return cls(
            role=d["role"],
            content=d.get("content"),
            tool_calls=tool_calls,
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
        )


@dataclass(frozen=True)
class ToolCall:
    """OpenAI-format tool call."""

    id: str
    type: str = "function"
    function: ToolCallFunction = field(default_factory=lambda: ToolCallFunction(id="", name="", arguments=""))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "function": self.function.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> ToolCall:
        fn = d.get("function", {})
        return cls(
            id=d.get("id", ""),
            type=d.get("type", "function"),
            function=ToolCallFunction(
                id=d.get("id", ""),
                name=fn.get("name", ""),
                arguments=fn.get("arguments", ""),
            ),
        )


@dataclass(frozen=True)
class ToolCallFunction:
    id: str
    name: str
    arguments: str

    def to_dict(self) -> dict:
        return {"name": self.name, "arguments": self.arguments}


# ─── Shrink result containers ───


@dataclass(frozen=True)
class ShrinkCharsResult:
    """Result of char-based shrinking."""

    messages: list[ChatMessage]
    healed_count: int
    healed_from: int


@dataclass(frozen=True)
class ShrinkTokensResult:
    """Result of token-based shrinking."""

    messages: list[ChatMessage]
    healed_count: int
    tokens_saved: int
    chars_saved: int
