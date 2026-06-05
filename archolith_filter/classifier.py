"""Command classification for output filtering.

Maps shell command strings to one of 13 filter categories.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class CommandCategory(StrEnum):
    """Filter categories for shell output."""

    GIT_STATUS = "git-status"
    GIT_DIFF = "git-diff"
    GIT_LOG = "git-log"
    GIT_SHOW = "git-show"
    GIT_OTHER = "git-other"
    LS_TREE = "ls-tree"
    SEARCH = "search"
    JSON = "json"
    TEST = "test"
    BUILD = "build"
    LINT = "lint"
    TYPECHECK = "typecheck"
    GENERIC = "generic"


@dataclass(frozen=True)
class ClassifiedCommand:
    """Result of classifying a shell command."""

    category: CommandCategory
    base: str
    command: str


_RUNNER_RE = re.compile(r"^(npx|pnpm|yarn\s+run|yarn|npm\s+run|npm|bun|deno)\s+")

_TEST_BINS = frozenset({
    "vitest", "jest", "mocha", "ava", "tape", "tap",
    "pytest", "py.test", "unittest",
    "cargo", "go", "mvn", "gradle", "dotnet",
    "ruby", "rspec", "cucumber",
})

_BUILD_BINS = frozenset({
    "cargo", "go", "mvn", "gradle", "make", "cmake",
    "dotnet", "msbuild", "xcodebuild", "bazel", "ninja", "build",
})

_LINT_BINS = frozenset({
    "eslint", "ruff", "mypy", "clippy", "pylint",
    "flake8", "rubocop", "shellcheck", "hadolint",
})

_TYPECHECK_BINS = frozenset({"tsc", "tsc-watch", "pyright", "mypy"})


def _classify_runner_prefix(command: str) -> CommandCategory | None:
    """Match runner-prefix patterns that don't delegate to a known bin name."""
    if re.search(r"^(npm|pnpm|yarn|bun|deno)\s+test\b", command):
        return CommandCategory.TEST
    if re.search(r"^(npm|pnpm|yarn|bun|deno)\s+run\s+build\b", command):
        return CommandCategory.BUILD
    if re.search(r"^(npm|pnpm|yarn|bun|deno)\s+run\s+lint\b", command):
        return CommandCategory.LINT
    if re.search(r"^(npm|pnpm|yarn|bun|deno)\s+run\s+type[-]?check\b", command):
        return CommandCategory.TYPECHECK
    if re.search(r"^(npm|pnpm|yarn|bun|deno)\s+ls\b.*--json", command):
        return CommandCategory.JSON
    return None


def _classify_git(command: str) -> ClassifiedCommand:
    """Classify a git subcommand."""
    tokens = command.strip().split()
    sub = tokens[1] if len(tokens) > 1 else ""
    category_map = {
        "status": CommandCategory.GIT_STATUS,
        "diff": CommandCategory.GIT_DIFF,
        "log": CommandCategory.GIT_LOG,
        "show": CommandCategory.GIT_SHOW,
    }
    return ClassifiedCommand(
        category=category_map.get(sub, CommandCategory.GIT_OTHER),
        base="git",
        command=command,
    )


def _is_json_command(base: str, command: str) -> bool:
    """Check if the command typically produces JSON output."""
    if base in ("jq", "yq", "json_pp"):
        return True
    if base == "python3":
        return "-m json.tool" in command
    if base in ("aws", "gcloud", "az"):
        return "--output json" in command or "--format json" in command
    if base == "curl" and "jq" in command:
        return True
    if base in ("npm", "pnpm", "yarn") and "--json" in command:
        return True
    return False


def _is_test_command(base: str, command: str) -> bool:
    """Check if the command is a test runner."""
    if base in _TEST_BINS:
        if base == "cargo":
            return " test" in command
        if base == "go":
            return " test" in command
        if base in ("mvn", "gradle"):
            return "test" in command
        if base == "dotnet":
            return "test" in command
        return True
    return False


def _is_build_command(base: str, command: str) -> bool:
    """Check if the command is a build tool."""
    if base in _BUILD_BINS:
        if base == "cargo":
            return " build" in command or " check" in command
        if base == "go":
            return " build" in command
        if base in ("mvn", "gradle"):
            return "compile" in command or "build" in command
        return True
    return False


def _is_lint_command(base: str, command: str) -> bool:
    """Check if the command is a linter."""
    if base in _LINT_BINS:
        return True
    if base == "cargo" and " clippy" in command:
        return True
    return False


def _is_typecheck_command(base: str, command: str) -> bool:
    """Check if the command is a type checker."""
    if base in _TYPECHECK_BINS:
        return True
    if base == "biome" and "check" in command:
        return True
    return False


def classify_command(command: str) -> ClassifiedCommand:
    """Classify a shell command string into a filter category."""
    trimmed = command.strip()
    first_token = trimmed.split()[0] if trimmed else ""

    # Check runner-prefixed patterns FIRST.
    runner_cat = _classify_runner_prefix(trimmed)
    if runner_cat is not None:
        stripped = _RUNNER_RE.sub("", trimmed)
        base = stripped.split()[0] if stripped else first_token
        return ClassifiedCommand(category=runner_cat, base=base, command=command)

    # Strip runner prefix for direct tool names.
    stripped = _RUNNER_RE.sub("", trimmed)
    base = stripped.split()[0] if stripped != trimmed and stripped else first_token

    if base == "git":
        return _classify_git(command)
    if base in ("ls", "dir", "tree", "find"):
        return ClassifiedCommand(category=CommandCategory.LS_TREE, base=base, command=command)
    if base in ("grep", "rg", "findstr", "ag", "ack"):
        return ClassifiedCommand(category=CommandCategory.SEARCH, base=base, command=command)
    if _is_json_command(base, command):
        return ClassifiedCommand(category=CommandCategory.JSON, base=base, command=command)
    if _is_test_command(base, command):
        return ClassifiedCommand(category=CommandCategory.TEST, base=base, command=command)
    if _is_build_command(base, command):
        return ClassifiedCommand(category=CommandCategory.BUILD, base=base, command=command)
    if _is_lint_command(base, command):
        return ClassifiedCommand(category=CommandCategory.LINT, base=base, command=command)
    if _is_typecheck_command(base, command):
        return ClassifiedCommand(category=CommandCategory.TYPECHECK, base=base, command=command)

    return ClassifiedCommand(category=CommandCategory.GENERIC, base=base, command=command)
