from __future__ import annotations

import json
from pathlib import Path

from archolith_rtk import ChatMessage, ToolCall
from archolith_rtk.shrink import ToolCallFunction

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def get_git_diff_large_text() -> str:
    return load_fixture("git_diff_large.txt")


def get_search_heading_large_text() -> str:
    base = load_fixture("search_heading_large.txt").strip()
    blocks = [base]
    for index in range(4, 18):
        blocks.append(
            "\n".join(
                [
                    f"src/v{index}/search/generated_{index}.py",
                    f"5:prompt_tokens = compute_budget(payload_{index})",
                    f"9:if prompt_tokens > threshold_{index}:",
                    f"13:logger.info('prompt_tokens reached branch {index}')",
                    "17:return prompt_tokens",
                    "21:summary.append(prompt_tokens)",
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def get_bracketed_logs_large_text() -> str:
    base = load_fixture("bracketed_logs_large.txt").strip()
    extra_lines = [f"[INFO] polling cycle {index} completed" for index in range(1, 41)]
    return "\n".join([base, *extra_lines, "[INFO] final readiness check passed"]) + "\n"


def get_nested_json_large_text() -> str:
    payload = {
        "metadata": {
            "request_id": "req_bench_001",
            "agent": "archolith-rtk-benchmark",
            "labels": ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"],
        },
        "files": [
            {
                "path": f"src/module_{index}/component_{index}.ts",
                "summary": "Large nested payload for JSON compression benchmarking",
                "diagnostics": [
                    {
                        "line": line,
                        "message": f"Type mismatch at module {index}, branch {line}",
                        "snippet": "value = someVeryLongIdentifier + anotherVeryLongIdentifier" * 3,
                    }
                    for line in range(1, 10)
                ],
            }
            for index in range(18)
        ],
    }
    return "$ mcp__memory__query\n[exit 0]\n" + json.dumps(payload)


def build_large_tool_history(turns: int = 12) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    tool_payloads = [
        get_git_diff_large_text(),
        get_search_heading_large_text(),
        get_bracketed_logs_large_text(),
    ]
    for index in range(turns):
        messages.append(ChatMessage(role="user", content=f"Investigate issue {index} " * 20))
        messages.append(ChatMessage(role="assistant", content=f"Working on issue {index} " * 20))
        messages.append(
            ChatMessage(
                role="tool",
                content=tool_payloads[index % len(tool_payloads)],
                tool_call_id=f"call_{index}",
                name="run_command",
            )
        )
    return messages


def build_large_dict_history(turns: int = 12) -> list[dict]:
    return [message.to_dict() for message in build_large_tool_history(turns)]


def build_large_tool_call_messages(calls: int = 6, repeated_lines: int = 180) -> list[ChatMessage]:
    tool_calls: list[ToolCall] = []
    for index in range(calls):
        arguments = json.dumps(
            {
                "path": f"src/generated/file_{index}.ts",
                "content": "\n".join(
                    f"const value_{index}_{line} = 'long benchmark content';"
                    for line in range(repeated_lines)
                ),
            }
        )
        tool_calls.append(
            ToolCall(
                id=f"tool_{index}",
                function=ToolCallFunction(
                    id=f"tool_{index}",
                    name="edit_file",
                    arguments=arguments,
                ),
            )
        )
    return [ChatMessage(role="assistant", content=None, tool_calls=tool_calls)]
