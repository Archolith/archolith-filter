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


def get_read_file_code_text() -> str:
    lines: list[str] = []
    lines.append("#!/usr/bin/env python3")
    lines.append('"""Application service module — handles request routing and processing."""')
    lines.append("")
    lines.append("import os")
    lines.append("import sys")
    for i in range(30):
        lines.append(f"from package.sub{i}.module_{i} import Handler{i}, Processor{i}, Config{i}")
    lines.extend(
        [
            "from package.utils import helpers",
            "from package.models import UserModel, SessionModel",
            "from package.database import get_connection",
            "from package.cache import RedisCache",
            "from package.logging import configure_logger",
            "",
            "",
            "",
            "# Block comment start",
        ]
    )
    for i in range(25):
        lines.append(f"# Configuration note {i}: This module implements the core request pipeline")
    lines.extend(["# Block comment end", ""])
    for i in range(5):
        lines.append(f"# TODO: refactor handler {i}")
    lines.extend(["", "", "", "class RequestHandler:", '    """Main request handler with middleware support."""', ""])
    lines.extend(
        [
            "    def __init__(self, config, logger=None):",
            "        self.config = config",
            "        self.logger = logger or configure_logger()",
            "        self._middleware = []",
            "",
            "    async def process(self, request):",
            '        """Process an incoming request through the middleware chain."""',
            "        for mw in self._middleware:",
            "            request = await mw(request)",
            "        return await self._dispatch(request)",
            "",
            "    def add_middleware(self, middleware):",
            "        self._middleware.append(middleware)",
            "",
            "",
            "class ResponseBuilder:",
            '    """Builds standardized response objects."""',
            "",
            "    @staticmethod",
            "    def success(data, status=200):",
            "        return {'status': 'ok', 'data': data, 'code': status}",
            "",
            "    @staticmethod",
            "    def error(message, status=400):",
            "        return {'status': 'error', 'message': message, 'code': status}",
            "",
        ]
    )
    for i in range(40):
        lines.extend([f"# Implementation detail {i}", f"def utility_{i}(arg):", f"    return arg + {i}", ""])
    return "\n".join(lines)


def get_read_file_css_text() -> str:
    lines: list[str] = ["/* Main application stylesheet */", ""]
    for i in range(25):
        lines.append(f".component-{i} {{")
        for j in range(8):
            lines.append(f" prop-{j}: value-{i}-{j};")
        lines.append("}")
    lines.extend(["", "#app-container {", " display: flex;", " flex-direction: column;", "}", ""])
    lines.append("@media (max-width: 768px) {")
    for i in range(10):
        lines.extend([f" .responsive-{i} {{", f" width: {i * 10}%;", f" padding: {i}px;", " }"])
    lines.append("}")
    return "\n".join(lines)


def get_read_file_fixture_heavy_text() -> str:
    lines: list[str] = ["import os", "import json", "from typing import Any", "", ""]
    lines.extend(
        [
            "class IconRegistry:",
            ' """Registry of SVG icon paths for the UI framework."""',
            "",
            " ICONS: dict[str, str] = {",
        ]
    )
    for i in range(40):
        path_cmds = " ".join([f"M{i * 10 + j},{j * 5} L{i * 10 + j + 5},{j * 5 + 3}" for j in range(20)])
        lines.append(f'  "icon-{i}": "<svg viewBox=\\"0 0 24 24\\"><path d=\\"{path_cmds}\\"/></svg>",')
    lines.extend([" }", "", " def get_icon(self, name: str) -> str:", " return self.ICONS.get(name, '')", "", ""])
    lines.extend(
        [
            "class SnapshotTests:",
            ' """Snapshot test fixtures for API response validation."""',
            "",
            " RESPONSE_FIXTURES: list[dict[str, Any]] = [",
        ]
    )
    for i in range(30):
        lines.extend(
            [
                "  {",
                f'   "id": "resp_{i}",',
                f'   "status": {200 + (i % 4)},',
                ' "data": ' + '{"items": [' + ", ".join(f'"item_{i}_{j}"' for j in range(20)) + '],',
                f'    "metadata": {{"page": {i}, "total": 600, "cursor": "cursor_{i}_abcdef123456"}},',
                "  },",
            ]
        )
    lines.extend([" ]", "", " CONFIG_BLOB = JSON.parse('"])
    parts = [f'setting_{j}":"value_{j}_with_padding_' for j in range(50)]
    config_inner = '{"'.join(parts)
    lines.append(f" {config_inner}")
    lines.extend(["')", "", ""])
    for i in range(10):
        lines.append(("x" * 600) + f"; // generated line {i}")
    lines.extend(["", "", "class ServiceClient:", ' """HTTP client wrapper for the service API."""', ""])
    lines.extend(
        [
            " async def fetch(self, url: str) -> dict:",
            " async with self.session.get(url) as resp:",
            " return await resp.json()",
            "",
            " def health_check(self) -> bool:",
            " return self._healthy",
            "",
        ]
    )
    return "\n".join(lines)
