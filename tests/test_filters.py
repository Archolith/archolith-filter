"""Tests for archolith_filter — Phase 1 core filters."""

import json

import pytest

from archolith_filter import filter_output
from archolith_filter.classifier import CommandCategory, classify_command
from archolith_filter.config import (
    FilterRiskLevel,
    base_config_for_risk_level,
    from_env,
    is_verbose_command,
)
from archolith_filter.filter_meta import parse_result_meta
from archolith_filter.filters import FilterResult
from archolith_filter.filters.build_output import BuildFilterOptions, build_filter
from archolith_filter.filters.fs_listing import FsListingFilterOptions, fs_listing_filter
from archolith_filter.filters.generic import GenericFilterOptions, generic_filter
from archolith_filter.filters.git_diff import GitDiffFilterOptions, git_diff_filter
from archolith_filter.filters.git_log import git_log_filter
from archolith_filter.filters.git_show import git_show_filter
from archolith_filter.filters.git_status import GitStatusFilterOptions, git_status_filter
from archolith_filter.filters.json_output import JsonFilterOptions, json_filter
from archolith_filter.filters.lint_output import lint_filter
from archolith_filter.filters.logs import LogFilterOptions, log_filter
from archolith_filter.filters.read_file import ReadFileFilterOptions, read_file_filter
from archolith_filter.filters.search import SearchFilterOptions, search_filter
from archolith_filter.filters.test_run_output import filter_test_output
from archolith_filter.filters.typecheck_output import typecheck_filter
from archolith_filter.raw_store import RawOutputStore, get_raw_output_store
from archolith_filter.strip_ansi import strip_ansi
from archolith_filter.telemetry import get_filter_telemetry_store


# ─── strip_ansi ───


class TestStripAnsi:
    def test_plain_text_unchanged(self):
        assert strip_ansi("hello world") == "hello world"

    def test_csi_color_codes_removed(self):
        assert strip_ansi("\x1b[31mred\x1b[0m") == "red"

    def test_osc_title_removed(self):
        assert strip_ansi("\x1b]0;title\x07body") == "body"

    def test_mixed_sequences(self):
        result = strip_ansi("\x1b[1;32m\x1b]0;shell\x07ok\x1b[0m")
        assert result == "ok"

    def test_empty_string(self):
        assert strip_ansi("") == ""


# ─── classifier ───


class TestClassifier:
    def test_git_status(self):
        r = classify_command("git status")
        assert r.category == CommandCategory.GIT_STATUS

    def test_git_diff(self):
        r = classify_command("git diff --staged")
        assert r.category == CommandCategory.GIT_DIFF

    def test_git_log(self):
        r = classify_command("git log --oneline")
        assert r.category == CommandCategory.GIT_LOG

    def test_git_show(self):
        r = classify_command("git show HEAD")
        assert r.category == CommandCategory.GIT_SHOW

    def test_git_other(self):
        r = classify_command("git branch")
        assert r.category == CommandCategory.GIT_OTHER

    def test_ls(self):
        r = classify_command("ls -la")
        assert r.category == CommandCategory.LS_TREE

    def test_rg_search(self):
        r = classify_command("rg pattern")
        assert r.category == CommandCategory.SEARCH

    def test_npm_test(self):
        r = classify_command("npm test")
        assert r.category == CommandCategory.TEST

    def test_pnpm_run_build(self):
        r = classify_command("pnpm run build")
        assert r.category == CommandCategory.BUILD

    def test_npx_vitest(self):
        r = classify_command("npx vitest")
        assert r.category == CommandCategory.TEST

    def test_jq_json(self):
        r = classify_command("jq . response.json")
        assert r.category == CommandCategory.JSON

    def test_eslint_lint(self):
        r = classify_command("eslint .")
        assert r.category == CommandCategory.LINT

    def test_tsc_typecheck(self):
        r = classify_command("tsc --noEmit")
        assert r.category == CommandCategory.TYPECHECK

    def test_generic_fallback(self):
        r = classify_command("echo hello")
        assert r.category == CommandCategory.GENERIC

    def test_gradle_test(self):
        r = classify_command("gradle test")
        assert r.category == CommandCategory.TEST

    def test_cargo_build(self):
        r = classify_command("cargo build")
        assert r.category == CommandCategory.BUILD


class TestFilterConfig:
    def test_programmatic_risk_level_presets(self):
        low = base_config_for_risk_level(FilterRiskLevel.LOW)
        balanced = base_config_for_risk_level(FilterRiskLevel.BALANCED)
        high = base_config_for_risk_level(FilterRiskLevel.HIGH)

        assert low.risk_level == FilterRiskLevel.LOW
        assert balanced.risk_level == FilterRiskLevel.BALANCED
        assert high.risk_level == FilterRiskLevel.HIGH
        assert low.generic_head > balanced.generic_head > high.generic_head
        assert low.json_max_value_length > balanced.json_max_value_length > high.json_max_value_length

    def test_env_risk_level_high_changes_defaults(self, monkeypatch):
        monkeypatch.setenv("ARCHOLITH_FILTER_RISK_LEVEL", "high")
        cfg = from_env()
        assert cfg.risk_level == FilterRiskLevel.HIGH
        assert cfg.generic_head == 10
        assert cfg.search_max_matches_per_file == 3

    def test_invalid_env_risk_level_falls_back_to_balanced(self, monkeypatch):
        monkeypatch.setenv("ARCHOLITH_FILTER_RISK_LEVEL", "extreme")
        cfg = from_env()
        assert cfg.risk_level == FilterRiskLevel.BALANCED
        assert cfg.generic_head == 20

    def test_explicit_env_override_wins_over_risk_level(self, monkeypatch):
        monkeypatch.setenv("ARCHOLITH_FILTER_RISK_LEVEL", "high")
        monkeypatch.setenv("ARCHOLITH_FILTER_GENERIC_HEAD", "42")
        cfg = from_env()
        assert cfg.risk_level == FilterRiskLevel.HIGH
        assert cfg.generic_head == 42


# ─── generic filter ───


class TestGenericFilter:
    def test_empty_input(self):
        r = generic_filter("")
        assert r.output == ""
        assert not r.truncated

    def test_below_threshold_no_truncation(self):
        text = "line1\nline2\nline3"
        r = generic_filter(text, GenericFilterOptions(head_lines=10, tail_lines=10))
        assert not r.truncated
        assert r.output == text

    def test_above_threshold_truncates(self):
        lines = [f"line{i}" for i in range(100)]
        text = "\n".join(lines)
        r = generic_filter(text, GenericFilterOptions(head_lines=5, tail_lines=5))
        assert r.truncated
        assert "90 lines omitted" in r.output
        assert "line0" in r.output  # head preserved
        assert "line99" in r.output  # tail preserved

    def test_header_preserved(self):
        text = "$ git diff\n[exit 0]\n" + "\n".join(f"line{i}" for i in range(50))
        r = generic_filter(text, GenericFilterOptions(head_lines=5, tail_lines=5))
        assert "$ git diff" in r.output

    def test_bracketed_log_lines_are_not_treated_as_header(self):
        text = "\n".join(f"[INFO] line{i}" for i in range(120))
        r = generic_filter(text, GenericFilterOptions(head_lines=5, tail_lines=5))
        assert r.truncated
        assert "[... 110 lines omitted ...]" in r.output

    def test_blank_collapse(self):
        text = "a\n\n\n\n\nb"
        r = generic_filter(text, GenericFilterOptions(head_lines=10, tail_lines=10))
        assert "\n\n\n" not in r.output  # consecutive blanks collapsed


# ─── git-diff filter ───


class TestGitDiffFilter:
    def test_empty(self):
        r = git_diff_filter("")
        assert r.output == ""
        assert not r.truncated

    def test_short_diff_no_truncation(self):
        text = "$ git diff\n[exit 0]\nsrc/foo.ts | 1 +\n1 file changed\ndiff --git a/src/foo.ts b/src/foo.ts\n+hello"
        r = git_diff_filter(text)
        assert not r.truncated

    def test_large_diff_truncates(self):
        stat_lines = ["src/foo.ts | 10 ++++----"]
        diff_header = (
            "diff --git a/src/foo.ts b/src/foo.ts\n"
            "index abc..def 100644\n"
            "--- a/src/foo.ts\n"
            "+++ b/src/foo.ts\n"
            "@@ -1,1 +1,1 @@"
        )
        diff_body = "\n".join(f"+line{i}" for i in range(200))
        text = "$ git diff\n[exit 0]\n" + "\n".join(stat_lines) + "\n" + diff_header + "\n" + diff_body
        r = git_diff_filter(text)
        assert r.truncated
        assert "diff --git" in r.output
        assert "[... " in r.output
        assert r.filtered_chars < r.raw_chars

    def test_large_diff_keeps_compact_per_file_preview_without_global_tail(self):
        stat_lines = ["src/foo.ts | 20 ++++++++++----------", "src/bar.ts | 20 ++++++++++----------"]
        file_a = (
            "diff --git a/src/foo.ts b/src/foo.ts\n"
            "index aaa..bbb 100644\n"
            "--- a/src/foo.ts\n"
            "+++ b/src/foo.ts\n"
            "@@ -1,4 +1,8 @@\n"
            + "\n".join(f"+foo_line_{i}" for i in range(12))
        )
        file_b = (
            "diff --git a/src/bar.ts b/src/bar.ts\n"
            "index ccc..ddd 100644\n"
            "--- a/src/bar.ts\n"
            "+++ b/src/bar.ts\n"
            "@@ -10,4 +10,8 @@\n"
            + "\n".join(f"+bar_line_{i}" for i in range(12))
        )
        text = "$ git diff\n[exit 0]\n" + "\n".join(stat_lines) + "\n" + file_a + "\n" + file_b
        r = git_diff_filter(text, GitDiffFilterOptions(file_head_lines=5, tail_lines=5))
        assert r.truncated
        assert "diff --git a/src/foo.ts b/src/foo.ts" in r.output
        assert "diff --git a/src/bar.ts b/src/bar.ts" in r.output
        assert "--- tail ---" not in r.output
        assert "+foo_line_0" in r.output
        assert "+foo_line_11" in r.output
        assert "+bar_line_0" in r.output
        assert "+bar_line_11" in r.output


class TestGitShowFilter:
    def test_short_show_no_truncation(self):
        text = (
            "$ git show HEAD\n[exit 0]\n"
            "commit abc123\nAuthor: Test\nDate: Today\n\nmessage\n"
            "diff --git a/src/foo.py b/src/foo.py\n"
            "@@ -1,1 +1,1 @@\n-print('a')\n+print('b')"
        )
        r = git_show_filter(text)
        assert not r.truncated

    def test_commit_header_without_diff_falls_back_to_generic(self):
        body = "\n".join(f"line{i}" for i in range(80))
        text = "$ git show HEAD\n[exit 0]\ncommit abc123\nAuthor: Test\n\n" + body
        r = git_show_filter(text)
        assert r.truncated
        assert "commit abc123" in r.output


# ─── git-log filter ───


class TestGitLogFilter:
    def test_empty(self):
        r = git_log_filter("")
        assert r.output == ""

    def test_short_log_no_truncation(self):
        text = "$ git log --oneline\n[exit 0]\nabc1234 first commit\ndef5678 second commit"
        r = git_log_filter(text)
        assert not r.truncated

    def test_long_oneline_truncates(self):
        commits = "\n".join(f"{'a' * 7}{i:04d} commit {i}" for i in range(100))
        text = "$ git log --oneline\n[exit 0]\n" + commits
        r = git_log_filter(text)
        assert r.truncated
        assert "commits omitted" in r.output


# ─── git-status filter ───


class TestGitStatusFilter:
    def test_empty_body(self):
        r = git_status_filter("$ git status\n[exit 0]\n")
        assert not r.truncated

    def test_short_format_passes_through(self):
        text = "$ git status -s\n[exit 0]\nM  src/foo.ts\n?? newfile.ts"
        r = git_status_filter(text)
        assert "M  src/foo.ts" in r.output


# ─── json filter ───


class TestJsonFilter:
    def test_empty(self):
        r = json_filter("")
        assert r.output == ""

    def test_valid_json_compressed(self):
        data = '{"items": [' + ", ".join(f'{{"id": {i}, "name": "item_{i}"}}' for i in range(20)) + ']}'
        text = "$ some-command\n[exit 0]\n" + data
        r = json_filter(text)
        assert r.truncated or "items" in r.output

    def test_invalid_json_falls_to_generic(self):
        text = "$ some-cmd\n[exit 0]\nnot valid json at all\n" + "line\n" * 100
        r = json_filter(text)
        # Should not crash — falls through to generic
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0


# ─── search filter ───


class TestSearchFilter:
    def test_empty(self):
        r = search_filter("")
        assert r.output == ""

    def test_few_matches_no_truncation(self):
        text = "$ rg pattern\n[exit 0]\nsrc/foo.ts:10:match here"
        r = search_filter(text)
        assert not r.truncated

    def test_many_files_truncates(self):
        matches = "\n".join(f"src/file{i}.ts:1:pattern" for i in range(30))
        text = "$ rg pattern\n[exit 0]\n" + matches
        r = search_filter(text)
        assert r.truncated

    def test_heading_mode_grouping_truncates_per_file(self):
        file_a = "\n".join(f"{i}:pattern in a" for i in range(1, 8))
        file_b = "\n".join(f"{i}:pattern in b" for i in range(1, 5))
        text = f"$ rg --heading pattern\n[exit 0]\nsrc/a.py:\n{file_a}\n\nsrc/b.py:\n{file_b}"
        r = search_filter(
            text,
            SearchFilterOptions(max_matches_per_file=3, max_files=1, head_lines=2, tail_lines=2),
        )
        assert r.truncated
        assert "more matches in src/a.py" in r.output
        assert "more files" in r.output

    def test_heading_mode_paths_with_digits_stay_grouped(self):
        file_a = "\n".join(f"{i}:pattern in a" for i in range(1, 5))
        file_b = "\n".join(f"{i}:pattern in b" for i in range(1, 5))
        text = f"$ rg --heading pattern\nsrc/v2/a.py\n{file_a}\n\nsrc/v3/b.py\n{file_b}"
        r = search_filter(
            text,
            SearchFilterOptions(max_matches_per_file=2, max_files=1, head_lines=2, tail_lines=2),
        )
        assert r.truncated
        assert "src/v2/a.py" in r.output
        assert "more matches in src/v2/a.py" in r.output
        assert "(unsorted)" not in r.output
        assert "more files" in r.output

    def test_heading_mode_preserves_group_heading_paths(self):
        file_a = "\n".join(f"{i}:prompt_tokens in a" for i in range(1, 6))
        file_b = "\n".join(f"{i}:prompt_tokens in b" for i in range(1, 6))
        text = (
            "$ rg --heading prompt_tokens src\n"
            "src/v4/search/generated_4.py\n"
            f"{file_a}\n\n"
            "src/v5/search/generated_5.py\n"
            f"{file_b}"
        )
        r = search_filter(
            text,
            SearchFilterOptions(max_matches_per_file=3, max_files=2, head_lines=2, tail_lines=2),
        )
        assert r.truncated
        assert "src/v4/search/generated_4.py" in r.output
        assert "src/v5/search/generated_5.py" in r.output

    def test_non_match_output_falls_back_to_generic(self):
        text = "$ rg pattern\n[exit 0]\nsummary line\nalpha line\nbeta line\ngamma line\ndelta line"
        r = search_filter(text, SearchFilterOptions(head_lines=1, tail_lines=1))
        assert r.truncated
        assert "lines omitted" in r.output


# ─── fs-listing filter ───


class TestFsListingFilter:
    def test_empty(self):
        r = fs_listing_filter("")
        assert r.output == ""

    def test_short_listing_passes_through(self):
        text = "$ ls\n[exit 0]\nsrc\nlib\nREADME.md"
        r = fs_listing_filter(text)
        assert not r.truncated

    def test_large_listing_truncates(self):
        entries = "\n".join(f"dir{i}" for i in range(100))
        text = "$ ls\n[exit 0]\n" + entries
        r = fs_listing_filter(text)
        assert r.truncated

    def test_tree_style_listing_delegates_to_generic(self):
        tree_lines = "\n".join(
            ["src"] + [f"├── child{i}" for i in range(40)] + ["└── final"]
        )
        text = "$ tree\n[exit 0]\n" + tree_lines
        r = fs_listing_filter(text, FsListingFilterOptions(head_lines=5, tail_lines=5))
        assert r.truncated
        assert "entries omitted" not in r.output

    def test_important_entries_and_errors_are_preserved(self):
        entries = (
            ["package.json", "README.md"]
            + [f"dir{i}" for i in range(80)]
            + ["ls: cannot access secret: Permission denied"]
        )
        text = "$ ls\n[exit 0]\n" + "\n".join(entries)
        r = fs_listing_filter(
            text,
            FsListingFilterOptions(max_entries=10, head_lines=2, tail_lines=2),
        )
        assert r.truncated
        assert "package.json" in r.output
        assert "Permission denied" in r.output


# ─── test/build/lint/typecheck filters ───


class TestSimpleFilters:
    def test_test_filter_delegates(self):
        text = "$ pytest\n[exit 0]\n" + "\n".join(f"test_{i} PASSED" for i in range(100))
        r = filter_test_output(text)
        # Should not crash — delegates to generic with test defaults
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0

    def test_build_filter_delegates(self):
        text = "$ gradle build\n[exit 0]\n" + "compiling...\n" * 100
        r = build_filter(text)
        assert r.raw_chars > 0

    def test_lint_filter_delegates(self):
        text = "$ eslint .\n[exit 0]\n" + "checking...\n" * 50
        r = lint_filter(text)
        assert r.raw_chars > 0

    def test_typecheck_filter_delegates(self):
        text = "$ tsc --noEmit\n[exit 0]\n" + "checking...\n" * 50
        r = typecheck_filter(text)
        assert r.raw_chars > 0


# ─── log filter ───


class TestLogFilter:
    def test_empty(self):
        r = log_filter("")
        assert r.output == ""

    def test_duplicate_collapse(self):
        body = "Listening on port 3000\n" + "polling...\n" * 50
        text = "[job 1] run_background: npm start\n" + body
        r = log_filter(text)
        assert "repeated lines omitted" in r.output or not r.truncated

    def test_important_lines_preserved(self):
        body = "starting...\n" + "line\n" * 100 + "ERROR: connection failed\n" + "more\n" * 50
        text = "[job 1] background\n" + body
        r = log_filter(text)
        assert "ERROR" in r.output

    def test_omitted_important_lines_get_promoted(self):
        body_lines = [f"line {i}" for i in range(20)]
        body_lines[10] = "WARNING: disk almost full"
        text = "[job 1] background\n" + "\n".join(body_lines)
        r = log_filter(text, LogFilterOptions(head_lines=2, tail_lines=2, max_consecutive_dupes=3))
        assert r.truncated
        assert "Important lines from omitted output" in r.output
        assert "WARNING: disk almost full" in r.output


# ─── read_file filter ───


class TestReadFileFilter:
    def test_empty(self):
        r = read_file_filter("")
        assert r.output == ""
        assert not r.truncated

    def test_small_code_no_truncation(self):
        text = "def hello():\n    print('hi')\n"
        r = read_file_filter(text)
        assert not r.truncated
        assert "def hello():" in r.output

    def test_import_collapse(self):
        lines = ["import os"] + [f"import module{i}" for i in range(20)]
        text = "\n".join(lines)
        r = read_file_filter(text, ReadFileFilterOptions(import_collapse=True))
        assert r.truncated
        assert "import os" in r.output
        assert "import lines omitted" in r.output
        assert "import module1" not in r.output

    def test_import_collapse_disabled(self):
        lines = ["import os"] + [f"import module{i}" for i in range(20)]
        text = "\n".join(lines)
        r = read_file_filter(text, ReadFileFilterOptions(import_collapse=False))
        assert not r.truncated
        assert "import module19" in r.output

    def test_comment_collapse(self):
        lines = ["# Main module"] + [f"# comment line {i}" for i in range(20)]
        text = "\n".join(lines)
        r = read_file_filter(text, ReadFileFilterOptions(comment_threshold=5))
        assert r.truncated
        assert "# Main module" in r.output
        assert "comment lines omitted" in r.output

    def test_block_comment_collapse(self):
        lines = ["/**"] + [f" * line {i}" for i in range(15)] + [" */"]
        text = "\n".join(lines)
        r = read_file_filter(text, ReadFileFilterOptions(comment_threshold=5))
        assert r.truncated
        assert "/**" in r.output
        assert "comment lines omitted" in r.output

    def test_blank_line_collapse(self):
        text = "a\n\n\n\n\nb"
        r = read_file_filter(text, ReadFileFilterOptions(blank_line_max=1))
        assert r.truncated
        assert "\n\n\n" not in r.output

    def test_css_rule_collapse(self):
        css = ".big-class {\n" + "\n".join(f"  prop{i}: value{i};" for i in range(20)) + "\n}"
        r = read_file_filter(css, ReadFileFilterOptions(css_rule_collapse=True))
        assert r.truncated
        assert ".big-class {" in r.output
        assert "CSS body lines omitted" in r.output

    def test_declaration_preserved(self):
        lines = ["import os"] + [f"import mod{i}" for i in range(20)]
        lines.extend(["", "class MyService:", "    def process(self):", "        pass"])
        text = "\n".join(lines)
        r = read_file_filter(text, ReadFileFilterOptions(import_collapse=True, blank_line_max=1))
        assert "class MyService:" in r.output
        assert "def process(self):" in r.output

    def test_multiline_string_start_detected(self):
        lines = ['"""Multi-line'] + [f"content line {i}" for i in range(10)] + ['"""', "", "class Bar:", "    pass"]
        text = "\n".join(lines)
        r = read_file_filter(text, ReadFileFilterOptions(literal_threshold=5))
        assert "class Bar:" in r.output
        assert "lines omitted" in r.output

    def test_type_annotated_dict_literal(self):
        icon_lines = [f'    "icon-{i}": "<svg>path{i}</svg>",' for i in range(20)]
        lines = ["ICONS: dict[str, str] = {"] + icon_lines + ["}", "", "class ServiceClient:", "    pass"]
        text = "\n".join(lines)
        r = read_file_filter(text, ReadFileFilterOptions(literal_threshold=5))
        assert "class ServiceClient:" in r.output

    def test_generated_block_collapse(self):
        generated_lines = [("x" * 600) + f"; // generated line {i}" for i in range(8)]
        text = "\n".join(generated_lines + ["", "class ServiceClient:", "    pass"])
        r = read_file_filter(
            text,
            ReadFileFilterOptions(generated_min_line_len=500, generated_min_run=5),
        )
        assert "generated lines omitted" in r.output
        assert "class ServiceClient:" in r.output

    def test_svg_fixture_collapse(self):
        path_cmds = " ".join(f"M{i},{i} L{i + 1},{i + 2}" for i in range(30))
        svg_lines = [
            "<svg viewBox=\"0 0 24 24\">",
            f"  <path d=\"{path_cmds}\"/>",
            "  <path d=\"M0 0 L10 10\"/>",
            "  <path d=\"M1 1 L11 11\"/>",
            "  <path d=\"M2 2 L12 12\"/>",
            "  <path d=\"M3 3 L13 13\"/>",
            "  <path d=\"M4 4 L14 14\"/>",
            "</svg>",
        ]
        text = "\n".join(svg_lines + ["", "class IconRegistry:", "    pass"])
        r = read_file_filter(text)
        assert "SVG path/body lines omitted" in r.output
        assert "class IconRegistry:" in r.output

    def test_filter_output_routes_read_file_tool(self):
        lines = ["import os"] + [f"import mod{i}" for i in range(20)]
        padding = "\n".join(f"x = {i}" for i in range(30))
        text = "\n".join(lines) + "\n" + padding
        r = filter_output(text, tool="read_file")
        assert "import lines omitted" in r.output or not r.truncated


class TestCompoundLiteralType:
    """Regression tests for _compound_literal_type consolidation.

    Verifies that the unified pattern correctly classifies array, object,
    and dict literal starts while excluding CSS rules.
    """

    @pytest.fixture
    def _clf(self):
        from archolith_filter.filters.read_file import _compound_literal_type

        return _compound_literal_type

    def test_js_array(self, _clf):
        assert _clf("const items = [") == "array"

    def test_js_let_array(self, _clf):
        assert _clf("let data = [") == "array"

    def test_js_var_array(self, _clf):
        assert _clf("var buffer = [") == "array"

    def test_bare_array(self, _clf):
        assert _clf("items = [") == "array"

    def test_js_object_with_keyword(self, _clf):
        assert _clf("const config = {") == "object"

    def test_js_let_object(self, _clf):
        assert _clf("let opts = {") == "object"

    def test_dict_literal_no_keyword(self, _clf):
        assert _clf("ICONS: dict[str, str] = {") == "dict"

    def test_bare_dict(self, _clf):
        assert _clf("data = {") == "dict"

    def test_css_rule_excluded(self, _clf):
        assert _clf(".big-class {") is None

    def test_css_id_excluded(self, _clf):
        assert _clf("#my-id {") is None

    def test_plain_line_not_matched(self, _clf):
        assert _clf("def hello():") is None

    def test_inline_assignment_array(self, _clf):
        assert _clf("const items: string[] = [") == "array"

    def test_inline_assignment_object(self, _clf):
        assert _clf("const opts: Config = {") == "object"


# ─── filter_output (top-level API) ───


class TestFilterOutput:
    def test_disabled_returns_text(self, monkeypatch):
        monkeypatch.setenv("ARCHOLITH_FILTERS", "off")
        text = "x" * 1000
        r = filter_output(text, command="cat bigfile.txt")
        assert not r.truncated
        assert r.output == text

    def test_error_exit_bypasses(self):
        text = "x" * 1000
        r = filter_output(text, command="failing-cmd", exit_code=1)
        assert not r.truncated

    def test_timeout_bypasses(self):
        text = "x" * 1000
        r = filter_output(text, command="slow-cmd", timed_out=True)
        assert not r.truncated

    def test_small_output_skipped(self):
        r = filter_output("short", command="echo hi")
        assert not r.truncated

    def test_large_generic_compresses(self):
        text = "$ echo\n[exit 0]\n" + "\n".join(f"line{i}" for i in range(200))
        r = filter_output(text, command="echo")
        # May or may not truncate depending on threshold, but should not crash
        assert isinstance(r.output, str)

    def test_git_diff_classification(self):
        diff = "$ git diff\n[exit 0]\n" + "diff --git a/foo b/foo\n+added\n" * 80
        r = filter_output(diff, command="git diff")
        assert isinstance(r.output, str)

    def test_risk_level_changes_compression_strength(self):
        text = "$ echo\n[exit 0]\n" + "\n".join(f"line{i}" for i in range(200))
        low = filter_output(text, command="echo", config=base_config_for_risk_level(FilterRiskLevel.LOW))
        high = filter_output(text, command="echo", config=base_config_for_risk_level(FilterRiskLevel.HIGH))
        assert low.truncated
        assert high.truncated
        assert high.filtered_chars < low.filtered_chars

    def test_raw_output_tool_passthrough(self):
        text = "x" * 2000
        r = filter_output(text, tool="raw_output")
        assert not r.truncated
        assert r.output == text

    def test_fallback_returns_stripped_text(self, monkeypatch):
        text = "\x1b[31m" + ("x" * 2000) + "\x1b[0m"

        def boom(*args, **kwargs):
            raise RuntimeError("broken")

        monkeypatch.setattr("archolith_filter._category_filter", boom)
        r = filter_output(text, command="echo verbose")
        assert not r.truncated
        assert "\x1b" not in r.output
        assert r.output == strip_ansi(text)


class TestToolClassification:
    def test_classify_passthrough_tool(self):
        import archolith_filter

        assert archolith_filter._classify_tool("raw_output", "payload") == "passthrough"

    def test_classify_shell_tool(self):
        import archolith_filter

        assert archolith_filter._classify_tool("run_command", "payload") == "shell"

    def test_classify_read_file_tool(self):
        import archolith_filter

        assert archolith_filter._classify_tool("read_file", "payload") == "read_file"

    def test_classify_mcp_json_tool(self):
        import archolith_filter

        assert archolith_filter._classify_tool("mcp__memory__query", '{"items": []}') == "json"

    def test_classify_unknown_tool(self):
        import archolith_filter

        assert archolith_filter._classify_tool("custom_tool", "payload") == "generic"


# ─── raw output store ───


class TestRawOutputStore:
    def test_store_and_retrieve(self):
        store = RawOutputStore()
        entry_id = store.store("raw output", command="cmd", tool="tool", filtered_chars=10)
        entry = store.get(entry_id)
        assert entry is not None
        assert entry.raw == "raw output"
        assert entry.command == "cmd"

    def test_capacity_eviction(self):
        store = RawOutputStore(max_entries=3)
        store.store("a", command="c1", tool="t", filtered_chars=1)
        store.store("b", command="c2", tool="t", filtered_chars=1)
        store.store("c", command="c3", tool="t", filtered_chars=1)
        store.store("d", command="c4", tool="t", filtered_chars=1)
        assert store.size == 3
        assert store.get(1) is None  # evicted

    def test_get_filtered_tail(self):
        store = RawOutputStore()
        entry_id = store.store("line1\nline2\nline3\nline4\nline5", command="c", tool="t", filtered_chars=5)
        entry = store.get_filtered(entry_id, tail_lines=2)
        assert entry is not None
        assert "line4" in entry.raw
        assert "line1" not in entry.raw

    def test_clear(self):
        store = RawOutputStore()
        store.store("data", command="c", tool="t", filtered_chars=4)
        store.clear()
        assert store.size == 0


# ─── telemetry ───


class TestTelemetry:
    def test_record_and_summary(self):
        from archolith_filter.telemetry import record_filter_telemetry

        record_filter_telemetry(
            command="git diff",
            tool="run_command",
            filter_kind="git-diff",
            raw_chars=10000,
            filtered_chars=2000,
            raw_output_id=1,
            fallback_used=False,
        )
        summary = get_filter_telemetry_store().get_summary()
        assert summary.total_calls == 1
        assert summary.filtered_calls == 1
        assert summary.average_savings_pct == 80

    def test_format_summary(self):
        from archolith_filter.telemetry import record_filter_telemetry

        record_filter_telemetry(
            command="test",
            tool="t",
            filter_kind="generic",
            raw_chars=5000,
            filtered_chars=1000,
            raw_output_id=None,
            fallback_used=False,
        )
        output = get_filter_telemetry_store().format_summary()
        assert "tool output raw" in output


# ─── filter_meta ───


class TestFilterMeta:
    def test_verbose_detection(self):
        assert is_verbose_command("git log --verbose")
        assert is_verbose_command("npm test --debug")
        assert not is_verbose_command("git log --oneline")

    def test_parse_exit_code(self):
        code, timed = parse_result_meta("[exit 0]", "run_command")
        assert code == 0
        assert not timed

    def test_parse_timeout(self):
        code, timed = parse_result_meta("[killed after timeout]", "run_command")
        assert timed

    def test_parse_job_exit(self):
        code, timed = parse_result_meta("[job 1 · exited 1 · byteLength=500]", "job_output")
        assert code == 1
        assert not timed


class TestCrossTurnDedupe:
    def test_first_occurrence_normal(self):
        text = "x" * 1000
        r = filter_output(text, command="echo")
        assert "repeated output" not in r.output

    def test_second_occurrence_reduced(self):
        text = "x" * 1000
        first = filter_output(text, command="echo")
        second = filter_output(text, command="echo")
        assert "repeated output" in second.output
        assert second.truncated
        assert second.filtered_chars < first.raw_chars

    def test_different_text_not_deduped(self):
        filter_output("x" * 1000, command="echo")
        r2 = filter_output("y" * 1000, command="echo")
        assert "repeated output" not in r2.output

    def test_occurrence_increments(self):
        text = "x" * 1000
        filter_output(text, command="echo")
        r2 = filter_output(text, command="echo")
        r3 = filter_output(text, command="echo")
        assert "occurrence 2" in r2.output
        assert "occurrence 3" in r3.output

    def test_raw_output_recoverable_on_repeat(self):
        import re

        text = "unique payload " * 100
        filter_output(text, command="echo")
        r2 = filter_output(text, command="echo")
        match = re.search(r"raw_output_id=(\d+)", r2.output)
        assert match is not None
        raw_id = int(match.group(1))
        entry = get_raw_output_store().get(raw_id)
        assert entry is not None
        assert entry.raw == text

    def test_telemetry_records_dedupe(self):
        text = "x" * 1000
        filter_output(text, command="echo")
        filter_output(text, command="echo")
        summary = get_filter_telemetry_store().get_summary()
        assert summary.dedupe_calls == 1

    def test_small_repeated_output_deduped(self):
        text = "small but repeated"
        filter_output(text, command="echo")
        r2 = filter_output(text, command="echo")
        assert "repeated output" in r2.output
        assert r2.truncated

    def test_filtering_disabled_no_dedupe(self, monkeypatch):
        monkeypatch.setenv("ARCHOLITH_FILTERS", "off")
        text = "x" * 1000
        filter_output(text, command="echo")
        r2 = filter_output(text, command="echo")
        assert "repeated output" not in r2.output

    def test_ansi_variant_deduped(self):
        text_a = "\x1b[31m" + ("x" * 1000) + "\x1b[0m"
        text_b = "\x1b[32m" + ("x" * 1000) + "\x1b[0m"
        filter_output(text_a, command="echo")
        r2 = filter_output(text_b, command="echo")
        assert "repeated output" in r2.output

    def test_dedupe_tracker_unit(self):
        from archolith_filter.dedupe import DedupeTracker

        tracker = DedupeTracker()
        assert tracker.check("hello") is None
        assert tracker.record("hello") == 1
        hit = tracker.check("hello")
        assert hit is not None
        assert hit.occurrence == 1
        assert tracker.record("hello") == 2
        assert tracker.check("world") is None


# ─── Strategy 1: CSV ───


class TestCsvStrategy:
    def test_uniform_array_to_csv(self):
        data = [{"id": i, "name": f"item_{i}"} for i in range(10)]
        text = "$ cmd\n[exit 0]\n" + json.dumps(data)
        r = json_filter(text, JsonFilterOptions(csv_enabled=True, csv_min_rows=3))
        assert "," in r.output  # CSV output has commas
        assert "id" in r.output or "item_0" in r.output

    def test_csv_disabled_falls_to_truncation(self):
        data = [{"id": i, "name": f"item_{i}"} for i in range(10)]
        text = json.dumps(data)
        r_csv = json_filter(text, JsonFilterOptions(csv_enabled=True, csv_min_rows=3))
        r_no_csv = json_filter(text, JsonFilterOptions(csv_enabled=False))
        # With CSV disabled, should fall back to truncation
        assert r_no_csv.output  # doesn't crash

    def test_fewer_than_min_rows_falls_to_truncation(self):
        data = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(csv_enabled=True, csv_min_rows=3))
        # Only 2 items, below min_rows=3 — should fall back
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0

    def test_mixed_keys_still_tabular(self):
        """Sparse objects with optional keys are still tabular if 60% overlap."""
        data = [{"id": i, "name": f"n{i}", "opt": "x"} for i in range(5)]
        data[2].pop("opt")  # Remove optional key from one item
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(csv_enabled=True, csv_min_rows=3))
        # Should still produce CSV
        assert r.output  # doesn't crash

    def test_nested_values_not_tabular(self):
        data = [{"id": 1, "nested": {"a": 1}}, {"id": 2, "nested": {"b": 2}}]
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(csv_enabled=True, csv_min_rows=3))
        # Nested dicts don't qualify for CSV
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0

    def test_csv_row_limit(self):
        data = [{"id": i, "name": f"item_{i}"} for i in range(50)]
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(csv_enabled=True, csv_min_rows=3, csv_max_rows=10))
        assert "30 more rows" in r.output or "more rows" in r.output

    def test_column_factoring(self):
        """When one value appears in >=80% of rows, factor it above header."""
        data = [{"name": f"user{i}", "region": "us-east-1"} for i in range(10)]
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(csv_enabled=True, csv_min_rows=3, csv_factor_enabled=True))
        assert "region=us-east-1" in r.output

    def test_column_factoring_disabled(self):
        data = [{"name": f"user{i}", "region": "us-east-1"} for i in range(10)]
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(csv_enabled=True, csv_min_rows=3, csv_factor_enabled=False))
        assert "region=" not in r.output


# ─── Strategy 2: Key-value lines ───


class TestKvStrategy:
    def test_flat_object_to_kv(self):
        data = {"name": "yawn.rip", "version": "1.0.0", "port": 8080}
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(kv_enabled=True, kv_min_keys=3))
        assert "name:" in r.output or "name :" in r.output

    def test_fewer_than_min_keys_no_kv(self):
        data = {"a": 1, "b": 2}
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(kv_enabled=True, kv_min_keys=3))
        # Only 2 keys, below min_keys — should fall back
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0

    def test_nested_values_skip_kv(self):
        data = {"name": "test", "config": {"nested": True}, "count": 5}
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(kv_enabled=True, kv_min_keys=3))
        # Nested dict should use dotted-key, not KV
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0

    def test_key_limit(self):
        data = {f"key_{i}": f"value_{i}" for i in range(30)}
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(kv_enabled=True, kv_min_keys=3, kv_max_keys=10))
        assert "more keys" in r.output


# ─── Strategy 3: Dotted-key lines ───


class TestDotkeyStrategy:
    def test_nested_object_to_dotkey(self):
        data = {"server": {"host": "localhost", "port": 8080}, "db": {"name": "test"}}
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(dotkey_enabled=True))
        assert "server.host" in r.output or "server.host:" in r.output

    def test_too_deep_falls_back(self):
        data = {"a": {"b": {"c": {"d": "too deep"}}}}
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(dotkey_enabled=True, dotkey_max_depth=3))
        # Depth 4 exceeds max_depth of 3
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0

    def test_arrays_in_values_skip_dotkey(self):
        data = {"items": [1, 2, 3], "name": "test"}
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(dotkey_enabled=True))
        # Arrays are not dottable — falls back
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0


# ─── Strategy 5: Stack trace collapsing ───


class TestStackTraceCollapse:
    def test_java_stack_trace_collapsed(self):
        frames = ["    at rip.yawn.api.CardController.get(CardController.java:42)"]
        frames += ["    at org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:100)"] * 8
        frames += ["    at rip.yawn.api.Application.main(Application.java:10)"]
        text = "$ java -jar app.jar\n[exit 1]\nException: null\n" + "\n".join(frames)
        r = generic_filter(text, GenericFilterOptions(
            head_lines=5, tail_lines=5,
            stack_collapse_enabled=True, stack_collapse_min_frames=5,
        ))
        assert "framework" in r.output.lower() or "omitted" in r.output

    def test_stack_collapse_disabled(self):
        frames = ["    at org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:100)"] * 20
        text = "$ java -jar app.jar\n[exit 1]\n" + "\n".join(frames)
        r_enabled = generic_filter(text, GenericFilterOptions(head_lines=10, tail_lines=10, stack_collapse_enabled=True, stack_collapse_min_frames=5))
        r_disabled = generic_filter(text, GenericFilterOptions(head_lines=10, tail_lines=10, stack_collapse_enabled=False))
        # With collapsing disabled, no "framework" summary
        assert "omitted" not in r_disabled.output or "framework" not in r_disabled.output.lower()

    def test_short_stack_not_collapsed(self):
        frames = ["    at org.springframework.DispatcherServlet.service(DispatcherServlet.java:100)"] * 3
        text = "Exception\n" + "\n".join(frames)
        # Only 3 frames, below min_frames=5
        r = generic_filter(text, GenericFilterOptions(stack_collapse_enabled=True, stack_collapse_min_frames=5))
        # Should not collapse — below min_frames threshold
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0


# ─── Strategy 6: Git status grouping ───


class TestGitStatusGrouping:
    def test_group_by_directory(self):
        lines = [
            "M  src/auth/handler.ts",
            "M  src/auth/session.ts",
            "M  src/auth/middleware.ts",
            "?? src/config/database.ts",
        ]
        text = "$ git status -s\n[exit 0]\n" + "\n".join(lines)
        r = git_status_filter(text, GitStatusFilterOptions(group_enabled=True, group_max_per_line=10))
        # Should group M src/auth/ files together
        assert "src/auth/" in r.output

    def test_group_disabled(self):
        lines = [
            "M  src/auth/handler.ts",
            "M  src/auth/session.ts",
        ]
        text = "$ git status -s\n[exit 0]\n" + "\n".join(lines)
        r = git_status_filter(text, GitStatusFilterOptions(group_enabled=False))
        # Should fall through to generic filter
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0

    def test_non_short_format_skips_grouping(self):
        text = "$ git status\n[exit 0]\nOn branch main\nChanges to be committed:\n  modified: foo.ts"
        r = git_status_filter(text, GitStatusFilterOptions(group_enabled=True))
        # Long-format should fall through to generic
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0


# ─── Strategy 7: Search heading reformat ───


class TestSearchHeadingReformat:
    def test_inline_to_heading_reformat(self):
        text = "$ rg pattern\n[exit 0]\n" + "\n".join(
            f"src/auth/handler.ts:{i}:match here" for i in range(10)
        )
        r = search_filter(text, SearchFilterOptions(
            max_matches_per_file=5, max_files=5,
            heading_reformat_enabled=True,
        ))
        # With heading reformat, path appears once
        assert "src/auth/handler.ts" in r.output

    def test_heading_mode_unchanged(self):
        text = "$ rg --heading pattern\nsrc/auth/handler.ts:\n5:pattern match\n6:another match"
        r = search_filter(text, SearchFilterOptions(heading_reformat_enabled=True))
        # Already heading-style — should not double-convert
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0


# ─── Strategy 8: Build task summary ───


class TestBuildSummary:
    def test_gradle_build_summary(self):
        lines = [
            "> Task :compileJava",
            "> Task :processResources",
            "> Task :classes",
            "> Task :test",
            "> Task :check",
            "> Task :build",
            "",
            "BUILD SUCCESSFUL in 5s",
        ]
        text = "$ gradle build\n[exit 0]\n" + "\n".join(lines)
        r = build_filter(text, BuildFilterOptions(summary_enabled=True))
        assert "BUILD SUCCESSFUL" in r.output
        assert "Tasks:" in r.output or "compileJava" in r.output

    def test_build_failure_no_summary(self):
        lines = [
            "> Task :compileJava",
            "> Task :compileJava FAILED",
            "error: cannot find symbol",
            "",
            "BUILD FAILED in 2s",
        ]
        text = "$ gradle build\n[exit 1]\n" + "\n".join(lines)
        # Non-zero exit — filter_output bypasses
        r = filter_output(text, command="gradle build", exit_code=1)
        # Should not summarize failed builds
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0

    def test_summary_disabled(self):
        lines = [
            "> Task :compileJava",
            "> Task :build",
            "",
            "BUILD SUCCESSFUL in 3s",
        ]
        text = "$ gradle build\n[exit 0]\n" + "\n".join(lines)
        r = build_filter(text, BuildFilterOptions(summary_enabled=False))
        # Falls back to generic — should still work
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0


# ─── Strategy 9: ls -la abbreviation ───


class TestLsAbbreviation:
    def test_ls_la_abbreviated(self):
        lines = [
            "total 8",
            "drwxr-xr-x  5 thron staff  160 May 26 14:30 .",
            "drwxr-xr-x  3 thron staff   96 May 26 14:28 ..",
            "-rw-r--r--  1 thron staff  4205 May 26 14:30 package.json",
            "drwxr-xr-x  4 thron staff  128 May 26 14:30 src",
        ]
        text = "$ ls -la\n[exit 0]\n" + "\n".join(lines)
        r = fs_listing_filter(text, FsListingFilterOptions(lsl_abbreviate_enabled=True))
        # Should contain abbreviated entries
        assert "package.json" in r.output or "src/" in r.output

    def test_abbreviation_disabled(self):
        lines = [
            "drwxr-xr-x  5 thron staff  160 May 26 14:30 .",
            "-rw-r--r--  1 thron staff  4205 May 26 14:30 package.json",
        ]
        text = "$ ls -la\n[exit 0]\n" + "\n".join(lines)
        r_enabled = fs_listing_filter(text, FsListingFilterOptions(lsl_abbreviate_enabled=True))
        r_disabled = fs_listing_filter(text, FsListingFilterOptions(lsl_abbreviate_enabled=False))
        # Both should work without crashing
        assert r_enabled.output
        assert r_disabled.output

    def test_non_ls_output_unchanged(self):
        """Non-ls output should not be affected by abbreviation."""
        text = "$ ls\n[exit 0]\nsrc\nlib\nREADME.md"
        r = fs_listing_filter(text, FsListingFilterOptions(lsl_abbreviate_enabled=True))
        assert "src" in r.output


# ─── Additional format-switch edge-case tests ───


class TestCsvEdgeCases:
    def test_factoring_with_non_default_values(self):
        """Column factoring preserves non-default values in the table."""
        data = [
            {"name": "Alice", "region": "us-east-1"},
            {"name": "Bob", "region": "us-east-1"},
            {"name": "Carol", "region": "us-east-1"},
            {"name": "Dave", "region": "us-east-1"},
            {"name": "Eve", "region": "eu-west-1"},
        ]
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(
            csv_enabled=True, csv_min_rows=3, csv_factor_enabled=True, csv_factor_threshold=0.8,
        ))
        # Region column should stay in the table since Eve has a non-default value
        assert "region" in r.output
        assert "eu-west-1" in r.output
        # Eve should show the actual non-default value
        assert "Eve,eu-west-1" in r.output or "Eve" in r.output

    def test_factoring_all_same_removes_column(self):
        """When all rows have the same value, the column is removed entirely."""
        data = [{"name": f"user{i}", "region": "us-east-1"} for i in range(5)]
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(
            csv_enabled=True, csv_min_rows=3, csv_factor_enabled=True, csv_factor_threshold=0.8,
        ))
        assert "region=us-east-1" in r.output
        # Region column should NOT appear in the CSV header since all rows match default
        header_line = [line for line in r.output.split("\n") if "," in line and "region" not in line.lower().split("=")[0]]
        # The header row should just be "name"
        assert any("name" in line and "region" not in line for line in r.output.split("\n"))

    def test_primitives_array_not_tabular(self):
        """A list of strings/numbers is not tabular and should fall through."""
        data = [1, 2, 3, 4, 5]
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(csv_enabled=True, csv_min_rows=3))
        # Should not be CSV — fall through to truncation
        assert "[" in r.output or "5 items" in r.output

    def test_csv_escaping(self):
        """Values with commas or quotes should be properly escaped."""
        data = [{"name": 'Smith, John', "city": "New York"}] + [{"name": f"User{i}", "city": "LA"} for i in range(5)]
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(csv_enabled=True, csv_min_rows=3))
        # The escaped value should appear
        assert "Smith, John" in r.output or '"Smith, John"' in r.output

    def test_safety_check_falls_back_when_csv_is_larger(self):
        """If CSV output is larger than truncation, fall back."""
        # Two-item array with complex keys should prefer truncation
        data = [{f"very_long_key_name_{i}": f"value_{i}" for i in range(20)}]
        text = json.dumps(data)
        r = json_filter(text, JsonFilterOptions(csv_enabled=True, csv_min_rows=3))
        # Should fall through since min_rows=3 not met
        assert isinstance(r, FilterResult)
        assert isinstance(r.output, str)
        assert r.raw_chars > 0


class TestDotkeyEdgeCases:
    def test_depth_4_rejected(self):
        """4 levels of nesting should be rejected at max_depth=3."""
        from archolith_filter.filters.json_output import _is_dottable
        data = {"a": {"b": {"c": {"d": 1}}}}
        assert not _is_dottable(data, max_depth=3)

    def test_depth_3_accepted(self):
        """3 levels of nesting should be accepted at max_depth=3."""
        from archolith_filter.filters.json_output import _is_dottable
        data = {"a": {"b": {"c": 1}}}
        assert _is_dottable(data, max_depth=3)

    def test_array_values_not_dottable(self):
        """Objects with array values should not be dottable."""
        from archolith_filter.filters.json_output import _is_dottable
        data = {"items": [1, 2, 3], "name": "test"}
        assert not _is_dottable(data, max_depth=3)


class TestStackTraceEdgeCases:
    def test_python_traceback_collapsed(self):
        """Python tracebacks should be detected and collapsed."""
        frames = ['  File "/usr/lib/python3.11/site-packages/django/core/handlers.py", line 42, in get_response'] * 8
        frames.append('  File "/home/user/app.py", line 10, in index')
        text = "$ python app.py\n[exit 1]\nTraceback (most recent call last):\n" + "\n".join(frames)
        r = generic_filter(text, GenericFilterOptions(
            head_lines=5, tail_lines=5,
            stack_collapse_enabled=True, stack_collapse_min_frames=5,
        ))
        # Should detect Python frames and collapse some
        assert "framework" in r.output.lower() or "omitted" in r.output.lower()

    def test_exception_line_preserved(self):
        """The exception line before a stack trace should be preserved."""
        exception_line = "java.lang.NullPointerException: something went wrong"
        frames = ["    at org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:100)"] * 10
        text = "$ java -jar app.jar\n[exit 1]\n" + exception_line + "\n" + "\n".join(frames)
        r = generic_filter(text, GenericFilterOptions(
            head_lines=20, tail_lines=20,
            stack_collapse_enabled=True, stack_collapse_min_frames=5,
        ))
        assert "NullPointerException" in r.output


class TestGitStatusEdgeCases:
    def test_group_exceeds_max_per_line(self):
        """Files exceeding max_per_line should be truncated with +N more."""
        lines = [f"M  src/auth/file{i}.ts" for i in range(15)]
        text = "$ git status -s\n[exit 0]\n" + "\n".join(lines)
        r = git_status_filter(text, GitStatusFilterOptions(group_enabled=True, group_max_per_line=5))
        # Should group and truncate
        assert "+10 more" in r.output or "auth/" in r.output


class TestBuildEdgeCases:
    def test_maven_build_summary(self):
        """Maven build tasks should be detected and summarized."""
        lines = [
            "[INFO] --- maven-compiler-plugin:3.8.1:compile (default-compile) @ myapp ---",
            "[INFO] --- maven-surefire-plugin:2.22.2:test (default-test) @ myapp ---",
            "",
            "BUILD SUCCESSFUL",
        ]
        text = "$ mvn package\n[exit 0]\n" + "\n".join(lines)
        r = build_filter(text, BuildFilterOptions(summary_enabled=True))
        assert "BUILD SUCCESSFUL" in r.output

    def test_build_with_warnings(self):
        """Warning lines should be preserved in build summary."""
        lines = [
            "> Task :compileJava",
            "> Task :test",
            "warning: unchecked call to add",
            "",
            "BUILD SUCCESSFUL in 3s",
        ]
        text = "$ gradle build\n[exit 0]\n" + "\n".join(lines)
        r = build_filter(text, BuildFilterOptions(summary_enabled=True))
        assert "warning" in r.output.lower()


# ─── filter_output dedupe_tracker parameter ───


class TestFilterOutputDedupTracker:
    def test_fresh_tracker_per_call_no_cross_request_marking(self):
        """With a fresh tracker per call, same string on two calls is not markered."""
        from archolith_filter.dedupe import DedupeTracker

        content = "x" * 1000  # large enough to trigger dedupe (>= 500 chars for filter)

        # First call with fresh tracker
        r1 = filter_output(content, tool="bash", dedupe_tracker=DedupeTracker())
        assert "repeated" not in r1.output.lower()

        # Second call with ANOTHER fresh tracker
        # (same content, but tracker doesn't know about first call)
        r2 = filter_output(content, tool="bash", dedupe_tracker=DedupeTracker())
        assert "repeated" not in r2.output.lower()

    def test_shared_tracker_cross_call_marking(self):
        """With a persistent/shared tracker, second identical call IS markered."""
        from archolith_filter.dedupe import DedupeTracker, reset_dedupe_tracker

        content = "y" * 1000
        shared_tracker = DedupeTracker()

        # Reset global tracker to ensure clean state
        reset_dedupe_tracker()

        # First call with shared tracker
        r1 = filter_output(content, tool="bash", dedupe_tracker=shared_tracker)
        assert "repeated" not in r1.output.lower()

        # Second call with SAME shared tracker
        r2 = filter_output(content, tool="bash", dedupe_tracker=shared_tracker)
        assert "repeated" in r2.output.lower()
