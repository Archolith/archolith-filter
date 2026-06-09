"""BashFilterExtractor — Filter-enhanced Bash command extractor.

Uses archolith-filter's ``classify_command()`` as the single source of truth
for routing, then applies category-specific regex extraction. No LLM calls
are made — ``may_use_llm`` is always False. If a category route doesn't
produce structured facts, a single generic fact is emitted.
"""

from __future__ import annotations

import re

import httpx

from archolith_filter.classifier import classify_command
from archolith_filter.extractors.base import (
    PartialExtractionResult,
    FilterExtractorBase,
    ToolCallRecord,
)
from archolith_filter.strip_ansi import strip_ansi

# --- Regex patterns for category-specific extraction ---

_PASSED_RE = re.compile(r"(\d+) passed")
_FAILED_RE = re.compile(r"(\d+) failed")
_WARNING_RE = re.compile(r"(\d+) warning")
_FAILED_TEST_RE = re.compile(r"FAILED\s+([\w/.:]+)")

_GIT_STATUS_MODIFIED_RE = re.compile(r"^\s+(?:modified|new file|deleted):\s+(.+)", re.MULTILINE)
_GIT_DIFF_FILE_RE = re.compile(r"^(?:\+\+\+|---)\s+(?:a/|b/)(.+)", re.MULTILINE)
_GIT_LOG_RE = re.compile(r"^([0-9a-f]{7,}) (.+)", re.MULTILINE)

_ERROR_RE = re.compile(r"(?:error|Error|ERROR):?\s+(.{0,120})")


class BashFilterExtractor(FilterExtractorBase):
    """Bash extractor that uses archolith-filter's classifier for routing.

    Key difference from the built-in BashExtractor: uses
    ``classify_command()`` as the single source of truth, so when
    archolith-filter adds a new category, routing here picks it up automatically.
    """

    tool_names = ("Bash", "run_command")
    may_use_llm = False

    async def extract(
        self,
        record: ToolCallRecord,
        http_client: httpx.AsyncClient,
        turn_number: int,
        session_goal: str | None,
    ) -> PartialExtractionResult:
        command = record.args.get("command", "")
        output = strip_ansi(record.result)

        classified = classify_command(command)
        category = classified.category

        facts: list[dict] = []
        files_touched: list[str] = []

        if category == "test":
            facts, files_touched = self._extract_test(command, output)
        elif category == "git-status":
            facts, files_touched = self._extract_git_status(command, output)
        elif category == "git-diff":
            facts, files_touched = self._extract_git_diff(command, output)
        elif category == "git-log":
            facts = self._extract_git_log(command, output)
        elif category in ("build", "lint", "typecheck"):
            facts = self._extract_errors(command, output, category)
        elif category in ("passthrough", "shell"):
            facts = self._generic_fact(command, output, turn_number)
        else:
            # Generic route for any unhandled category
            facts = self._generic_fact(command, output, turn_number)

        return PartialExtractionResult(
            source_tool="Bash",
            facts=facts,
            files_touched=files_touched,
            used_llm=False,
        )

    def _extract_test(self, command: str, output: str) -> tuple[list[dict], list[str]]:
        """Extract test results from test runner output."""
        facts: list[dict] = []

        for m in _PASSED_RE.findall(output):
            facts.append({
                "content": f"[Bash] test: {m} passed",
                "fact_type": "tool_result",
                "confidence": 1.0,
            })
        for m in _FAILED_RE.findall(output):
            facts.append({
                "content": f"[Bash] test: {m} failed",
                "fact_type": "error",
                "confidence": 1.0,
            })
        for m in _WARNING_RE.findall(output):
            facts.append({
                "content": f"[Bash] test: {m} warnings",
                "fact_type": "tool_result",
                "confidence": 1.0,
            })
        for m in _FAILED_TEST_RE.findall(output):
            facts.append({
                "content": f"[Bash] FAILED: {m}",
                "fact_type": "error",
                "confidence": 1.0,
            })

        if not facts:
            facts = self._generic_fact(command, output, 0)

        return facts, []

    def _extract_git_status(self, command: str, output: str) -> tuple[list[dict], list[str]]:
        """Extract modified/untracked file paths from git status."""
        facts: list[dict] = []
        paths = _GIT_STATUS_MODIFIED_RE.findall(output)

        for path in paths:
            facts.append({
                "content": f"[Bash] git status: {path.strip()}",
                "fact_type": "tool_result",
                "confidence": 1.0,
            })

        if not facts:
            facts = self._generic_fact(command, output, 0)

        return facts, [p.strip() for p in paths]

    def _extract_git_diff(self, command: str, output: str) -> tuple[list[dict], list[str]]:
        """Extract changed file names from git diff."""
        facts: list[dict] = []
        paths = _GIT_DIFF_FILE_RE.findall(output)

        for path in paths:
            facts.append({
                "content": f"[Bash] git diff file: {path.strip()}",
                "fact_type": "tool_result",
                "confidence": 1.0,
            })

        if not facts:
            facts = self._generic_fact(command, output, 0)

        return facts, [p.strip() for p in paths]

    def _extract_git_log(self, command: str, output: str) -> list[dict]:
        """Extract commit hashes and messages from git log."""
        facts: list[dict] = []

        for commit_hash, msg in _GIT_LOG_RE.findall(output):
            facts.append({
                "content": f"[Bash] git log: {commit_hash} {msg.strip()}",
                "fact_type": "tool_result",
                "confidence": 1.0,
            })

        if not facts:
            facts = self._generic_fact(command, output, 0)

        return facts

    def _extract_errors(self, command: str, output: str, category: str) -> list[dict]:
        """Extract error/warning counts from build/lint/typecheck output."""
        facts: list[dict] = []

        for err_msg in _ERROR_RE.findall(output):
            facts.append({
                "content": f"[Bash] {category} error: {err_msg.strip()}",
                "fact_type": "error",
                "confidence": 0.9,
            })

        if not facts:
            facts = self._generic_fact(command, output, 0)

        return facts

    def _generic_fact(self, command: str, output: str, turn_number: int) -> list[dict]:
        """Emit a single generic fact for commands without structured extraction."""
        exit_indicator = ""
        if "error" in output.lower() or "fail" in output.lower():
            exit_indicator = " (errors detected)"

        return [{
            "content": f"[Bash] {command[:100]}{exit_indicator}",
            "fact_type": "tool_result",
            "confidence": 0.6,
        }]


# Backward compat: deprecated alias for BashFilterExtractor
BashRtkExtractor = BashFilterExtractor
