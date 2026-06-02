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


# ---------------------------------------------------------------------------
# Format-switch strategy corpora (Strategies 1–9)
# ---------------------------------------------------------------------------


def get_csv_tabular_json_text() -> str:
    """Strategy 1/4: Large JSON array of uniform objects → CSV + column factoring."""
    import json

    items = []
    for i in range(40):
        items.append(
            {
                "id": f"card_{i:04d}",
                "name": f"Pokemon Card {i}",
                "set": "Base Set" if i % 3 == 0 else "Jungle" if i % 3 == 1 else "Fossil",
                "rarity": "common" if i % 5 != 0 else "rare",
                "price_usd": round(0.5 + i * 0.3, 2),
                "condition": "NM" if i % 4 != 0 else "LP",
            }
        )
    return json.dumps(items)


def get_kv_flat_object_text() -> str:
    """Strategy 2: Large flat JSON object → key-value lines."""
    import json

    obj = {}
    for i in range(60):
        obj[f"setting_{i}"] = f"value_with_some_padding_{i}_to_make_keys_longer"
    obj["important_key"] = "must_preserve_this"
    return json.dumps(obj)


def get_nested_json_dotted_text() -> str:
    """Strategy 3: Nested JSON object → dotted-key lines.

    Large enough to trigger truncation even at low risk (15 key limit).
    The object has many fields so the dotted-key format produces
    meaningful savings over truncated JSON.
    """
    import json

    obj = {
        "service": {
            "name": "archolith-rtk",
            "version": "1.2.3",
            "config": {
                "max_tokens": 4096,
                "risk_level": "balanced",
                "features": {
                    "csv_enabled": True,
                    "kv_enabled": True,
                    "stack_collapse": True,
                    "build_summary": True,
                    "search_heading": True,
                    "ls_abbreviate": True,
                },
            },
        },
        "deployment": {
            "region": "us-east-1",
            "environment": "production",
            "replicas": 3,
            "health_check": {
                "interval_ms": 5000,
                "timeout_ms": 3000,
            },
        },
        "metrics": {
            "requests_total": 1_234_567,
            "errors_total": 42,
            "latency_p50_ms": 120,
            "latency_p99_ms": 850,
            "uptime_seconds": 86_400,
        },
        "endpoints": [
            {"path": "/api/v1/cards", "method": "GET", "timeout_ms": 5000},
            {"path": "/api/v1/prices", "method": "GET", "timeout_ms": 3000},
            {"path": "/api/v1/sets", "method": "GET", "timeout_ms": 4000},
        ],
        "filters": {
            "json_filter": {
                "csv_enabled": True,
                "max_array_items": 20,
                "max_keys_per_object": 50,
                "max_depth": 6,
            },
            "git_filter": {
                "group_enabled": True,
                "head_lines": 20,
                "tail_lines": 15,
            },
            "search_filter": {
                "max_files": 15,
                "heading_enabled": True,
            },
        },
        "database": {
            "host": "db.archolith.dev",
            "port": 5432,
            "name": "rtk_production",
            "pool_size": 10,
            "connection_timeout_ms": 5000,
            "ssl": True,
            "ssl_cert_path": "/etc/ssl/certs/db-ca.pem",
        },
        "routes": {
            "get_cards": {"enabled": True, "rate_limit": 100, "cache_ttl": 300},
            "get_prices": {"enabled": True, "rate_limit": 100, "cache_ttl": 300},
            "get_sets": {"enabled": True, "rate_limit": 100, "cache_ttl": 300},
            "post_sync": {"enabled": True, "rate_limit": 10, "cache_ttl": 0},
            "get_health": {"enabled": True, "rate_limit": 1000, "cache_ttl": 10},
        },
        "logging": {
            "level": "info",
            "format": "json",
            "output": "stdout",
            "max_file_size_mb": 100,
            "max_files": 5,
            "compress_rotated": True,
        },
        "security": {
            "cors_origins": ["https://yawn.rip", "https://yawn.market"],
            "csrf_enabled": True,
            "rate_limiting": True,
            "jwt_expiry_seconds": 3600,
            "refresh_expiry_seconds": 86400,
        },
    }
    return json.dumps(obj, indent=2)


def get_stack_trace_java_text() -> str:
    """Strategy 5: Java stack trace with many framework frames → collapse."""
    lines = [
        "$ java -jar app.jar",
        "[exit 1]",
    ]
    # Core exception line
    lines.append(
        "Exception in thread 'main' "
        "rip.yawn.api.CardNotFoundException: Card pk001 not found"
    )
    # Application frame (kept)
    lines.append(
        "    at rip.yawn.api.controller.v1.CardController.getById("
        "CardController.java:45)"
    )
    # Framework frames (collapsed)
    spring_frames = [
        (
            "    at org.springframework.web.method.support."
            "InvocableHandlerMethod.doInvoke(InvocableHandlerMethod.java:205)"
        ),
        (
            "    at org.springframework.web.method.support."
            "InvocableHandlerMethod.invokeForRequest(InvocableHandlerMethod.java:150)"
        ),
        (
            "    at org.springframework.web.servlet.mvc.method.annotation."
            "ServletInvocableHandlerMethod.invokeAndHandle("
            "ServletInvocableHandlerMethod.java:117)"
        ),
        (
            "    at org.springframework.web.servlet.mvc.method.annotation."
            "RequestMappingHandlerAdapter.invokeHandlerMethod("
            "RequestMappingHandlerAdapter.java:895)"
        ),
        (
            "    at org.springframework.web.servlet.mvc.method.annotation."
            "RequestMappingHandlerAdapter.handleInternal("
            "RequestMappingHandlerAdapter.java:808)"
        ),
        (
            "    at org.springframework.web.servlet.mvc.method."
            "AbstractHandlerMethodAdapter.handle(AbstractHandlerMethodAdapter.java:87)"
        ),
        (
            "    at org.springframework.web.servlet.DispatcherServlet."
            "doDispatch(DispatcherServlet.java:1072)"
        ),
        (
            "    at org.springframework.web.servlet.DispatcherServlet."
            "doService(DispatcherServlet.java:965)"
        ),
    ]
    jdk_frames = [
        "    at jdk.internal.reflect.NativeMethodAccessorImpl.invoke0(Native Method)",
        (
            "    at jdk.internal.reflect.NativeMethodAccessorImpl.invoke("
            "NativeMethodAccessorImpl.java:62)"
        ),
        (
            "    at jdk.internal.reflect.DelegatingMethodAccessorImpl.invoke("
            "DelegatingMethodAccessorImpl.java:43)"
        ),
        "    at java.lang.reflect.Method.invoke(Method.java:566)",
    ]
    tomcat_frames = [
        (
            "    at org.apache.catalina.core.ApplicationFilterChain."
            "internalDoFilter(ApplicationFilterChain.java:228)"
        ),
        (
            "    at org.apache.catalina.core.ApplicationFilterChain."
            "doFilter(ApplicationFilterChain.java:166)"
        ),
        "    at javax.servlet.http.HttpServlet.service(HttpServlet.java:655)",
        (
            "    at org.springframework.web.servlet.FrameworkServlet."
            "service(FrameworkServlet.java:883)"
        ),
        "    at javax.servlet.http.HttpServlet.service(HttpServlet.java:764)",
    ]
    lines.extend(jdk_frames)
    lines.extend(spring_frames)
    lines.extend(tomcat_frames)
    lines.append(
        "    at org.apache.tomcat.util.threads.TaskThread$WrappingRunnable."
        "run(TaskThread.java:61)"
    )
    lines.append("    at java.lang.Thread.run(Thread.java:829)")
    lines.append("")
    lines.append("2026-06-02 10:15:32 ERROR [CardService] Failed to fetch card pk001")
    lines.append(
        "2026-06-02 10:15:33 INFO  [CardService] Retrying with fallback data source"
    )
    return "\n".join(lines)


def get_stack_trace_python_text() -> str:
    """Strategy 5: Python stack trace with many stdlib frames → collapse."""
    lines = [
        "$ python app.py",
        "[exit 1]",
        "Traceback (most recent call last):",
        '  File "/app/rip/yawn/api/controller.py", line 45, in get_card',
        "    card = card_service.find_by_id(card_id)",
        '  File "/app/rip/yawn/service/card_service.py", line 112, in find_by_id',
        "    return self._repository.query(card_id)",
        '  File "/app/rip/yawn/infrastructure/repository.py", line 88, in query',
        "    raise CardNotFoundError(f'Card {card_id} not found')",
        "rip.yawn.infrastructure.repository.CardNotFoundError: Card pk001 not found",
        "",
        "During handling of the above, another exception occurred:",
        "",
        "Traceback (most recent call last):",
        '  File "/usr/lib/python3.11/logging/__init__.py", line 1490, in callHandlers',
        "    hdlr.handle(record)",
        '  File "/usr/lib/python3.11/logging/__init__.py", line 938, in handle',
        "    self.emit(record)",
        '  File "/usr/lib/python3.11/logging/handlers.py", line 72, in emit',
        "    self.handleError(record)",
        '  File "/usr/lib/python3.11/logging/__init__.py", line 968, in handleError',
        "    sys.stderr.write(record.getMessage())",
        '  File "/usr/lib/python3.11/logging/__init__.py", line 1460, in getMessage',
        "    msg = str(msg)",
        "ValueError: Unterminated string",
        "",
        "The above exception was the direct cause of the following exception:",
        "",
        "Traceback (most recent call last):",
        '  File "/usr/lib/python3.11/logging/__init__.py", line 1490, in callHandlers',
        "    hdlr.handle(record)",
        '  File "/usr/lib/python3.11/logging/__init__.py", line 938, in handle',
        "    self.emit(record)",
        '  File "/usr/lib/python3.11/logging/handlers.py", line 72, in emit',
        "    self.handleError(record)",
        '  File "/usr/lib/python3.11/logging/__init__.py", line 968, in handleError',
        "    sys.stderr.write(record.getMessage())",
        '  File "/usr/lib/python3.11/logging/__init__.py", line 1460, in getMessage',
        "    msg = str(msg)",
        "ValueError: Unterminated string in logging formatter",
    ]
    # Add enough padding to exceed low-risk head+tail (30+45=75 lines)
    for i in range(40):
        lines.append(
            f"2026-06-02 10:15:{33 + i % 60:02d} INFO  [Worker-{i % 4}] "
            f"Processing batch {i} with {i * 10} items in queue"
        )
    return "\n".join(lines)


def get_git_status_short_text() -> str:
    """Strategy 6: git status short-format output → grouped by directory + status code."""
    lines = [
        "$ git status -s",
        "[exit 0]",
    ]
    # Add enough files in same directories to make grouping worthwhile
    for i in range(15):
        lines.append(f"M  src/api/file_{i}.py")
    for i in range(10):
        lines.append(f"M  src/service/handler_{i}.py")
    for i in range(8):
        lines.append(f"M  tests/unit/test_{i}.py")
    for i in range(5):
        lines.append(f"?? src/experiments/exp_{i}.py")
    lines.append("?? data/temp.json")
    return "\n".join(lines)


def get_gradle_build_success_text() -> str:
    """Strategy 8: Successful Gradle build output → compact task summary."""
    lines = [
        "$ gradle build",
        "",
        "> Task :compileJava",
        "> Task :processResources",
        "> Task :classes",
        "> Task :jar",
        "> Task :compileTestJava",
        "> Task :processTestResources",
        "> Task :testClasses",
        "> Task :test",
        "> Task :integrationTest",
        "> Task :check",
        "> Task :javadoc",
        "> Task :javadocJar",
        "> Task :sourcesJar",
        "> Task :assemble",
        "> Task :build",
        "",
        "BUILD SUCCESSFUL in 12s",
        "15 actionable tasks: 15 executed",
        "",
        "[exit 0]",
        "",
        "Additional output from the Gradle build process showing",
        "various compilation steps, resource processing, test runs",
        "and final assembly of the application artifact for deployment.",
        "This output is included to make the corpus large enough",
        "to trigger meaningful compression at low risk levels.",
        "The build process ran on the CI server with Java 17 and",
        "Gradle 8.5. All tests passed successfully with 42 test",
        "cases executed across 3 test suites in 8.2 seconds.",
        "Code coverage report generated at build/reports/jacoco/",
        "total line coverage: 87.3%, branch coverage: 72.1%.",
    ]
    return "\n".join(lines)


def get_gradle_build_success_verbose_text() -> str:
    """Strategy 8: Verbose successful Gradle build with many tasks + warnings."""
    lines = ["$ gradle build --info", ""]
    tasks = [
        "compileJava", "compileKotlin", "processResources", "classes",
        "compileTestJava", "compileTestKotlin", "processTestResources", "testClasses",
        "test", "integrationTest", "check", "jar", "bootJar",
        "javadoc", "javadocJar", "sourcesJar",
        "assemble", "build",
    ]
    for t in tasks:
        lines.append(f"> Task :{t}")
    lines.append("")
    lines.append("warning: [options] source value 11 is deprecated and will be removed in a future release")
    lines.append("warning: [deprecation] CardRepository.query() is deprecated: use findById() instead")
    lines.append("2 warnings")
    lines.append("")
    lines.append("BUILD SUCCESSFUL in 45s")
    lines.append(f"{len(tasks)} actionable tasks: {len(tasks)} executed")
    lines.append("")
    lines.append("[exit 0]")
    return "\n".join(lines)


def get_ls_la_text() -> str:
    """Strategy 9: ls -la directory listing → abbreviated form."""
    result_lines = ["total 48"]
    result_lines.append("drwxr-xr-x  8 thron staff  256 May 26 14:30 .")
    result_lines.append("drwxr-xr-x  5 thron staff  160 May 26 14:30 ..")
    result_lines.append("-rw-r--r--  1 thron staff  4205 May 26 14:30 package.json")
    result_lines.append("-rw-r--r--  1 thron staff  1052 May 22 09:15 tsconfig.json")
    result_lines.append("-rw-r--r--  1 thron staff  87432 May 26 14:30 yarn.lock")
    result_lines.append("drwxr-xr-x  3 thron staff   96 May 26 14:30 src")
    result_lines.append("drwxr-xr-x  4 thron staff  128 May 22 09:15 lib")
    result_lines.append("-rw-r--r--  1 thron staff   682 May 22 09:15 .gitignore")
    result_lines.append("-rw-r--r--  1 thron staff  1532 May 26 14:30 README.md")
    result_lines.append("-rw-r--r--  1 thron staff   524 May 22 09:15 Makefile")
    result_lines.append("lrwxr-xr-x  1 thron staff    12 May 26 14:30 node_modules -> .cache/nm")
    for i in range(20):
        ext = ".py" if i % 3 != 0 else ".ts"
        size = 500 + i * 200
        result_lines.append(f"-rw-r--r--  1 thron staff  {size:>5} May 26 14:30 module_{i}{ext}")
    return "\n".join(result_lines)
