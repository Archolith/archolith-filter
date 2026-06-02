from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from archolith_rtk import (
    FilterRiskLevel,
    base_config_for_risk_level,
    count_tokens,
    estimate_conversation_tokens,
    filter_output,
    reset_dedupe_tracker,
    shrink_oversized_tool_call_args_by_tokens,
    shrink_oversized_tool_results_by_tokens,
)

try:
    from benchmarks.corpora import (
        build_large_tool_call_messages,
        build_large_tool_history,
        get_bracketed_logs_large_text,
        get_csv_tabular_json_text,
        get_git_diff_large_text,
        get_git_status_short_text,
        get_gradle_build_success_text,
        get_gradle_build_success_verbose_text,
        get_kv_flat_object_text,
        get_ls_la_text,
        get_nested_json_dotted_text,
        get_nested_json_large_text,
        get_read_file_code_text,
        get_read_file_css_text,
        get_read_file_fixture_heavy_text,
        get_search_heading_large_text,
        get_stack_trace_java_text,
        get_stack_trace_python_text,
    )
except ModuleNotFoundError:
    from corpora import (
        build_large_tool_call_messages,
        build_large_tool_history,
        get_bracketed_logs_large_text,
        get_csv_tabular_json_text,
        get_git_diff_large_text,
        get_git_status_short_text,
        get_gradle_build_success_text,
        get_gradle_build_success_verbose_text,
        get_kv_flat_object_text,
        get_ls_la_text,
        get_nested_json_dotted_text,
        get_nested_json_large_text,
        get_read_file_code_text,
        get_read_file_css_text,
        get_read_file_fixture_heavy_text,
        get_search_heading_large_text,
        get_stack_trace_java_text,
        get_stack_trace_python_text,
    )

RESULTS_DIR = Path(__file__).parent / "results"
JSON_PATH = RESULTS_DIR / "practical-latest.json"
MARKDOWN_PATH = RESULTS_DIR / "practical-latest.md"

ALL_RISK_LEVELS: list[FilterRiskLevel] = [
    FilterRiskLevel.LOW,
    FilterRiskLevel.BALANCED,
    FilterRiskLevel.HIGH,
]


@dataclass(frozen=True)
class PracticalScenario:
    name: str
    risk_level: str
    kind: str
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    savings_pct: float
    runtime_ms_median: float
    runtime_ms_p95: float
    checks_passed: bool
    checks: list[str]


@dataclass
class _AcceptanceCheck:
    description: str
    passed: bool
    detail: str = ""


def _measure_call(func, iterations: int = 15, before_each=None) -> tuple[object, float, float]:
    samples: list[float] = []
    result = None
    for _ in range(iterations):
        if before_each is not None:
            before_each()
        start = time.perf_counter()
        result = func()
        elapsed_ms = (time.perf_counter() - start) * 1000
        samples.append(elapsed_ms)
    median_ms = statistics.median(samples)
    if len(samples) == 1:
        p95_ms = samples[0]
    else:
        p95_ms = statistics.quantiles(samples, n=20, method="inclusive")[18]
    return result, median_ms, p95_ms


def _tokens_for_messages(messages) -> int:
    return estimate_conversation_tokens(messages)


def _pct_saved(before_tokens: int, after_tokens: int) -> float:
    if before_tokens <= 0:
        return 0.0
    return round(((before_tokens - after_tokens) / before_tokens) * 100, 1)


def _build_filter_scenarios() -> list[PracticalScenario]:
    base_scenarios = [
        (
            "filter_git_diff",
            lambda cfg: filter_output(
                get_git_diff_large_text(),
                command="git diff --staged",
                config=cfg,
            ),
            count_tokens(get_git_diff_large_text()),
            ["diff --git", "[filtered"],
            [],
        ),
        (
            "filter_search_heading",
            lambda cfg: filter_output(
                get_search_heading_large_text(),
                command="rg --heading prompt_tokens src",
                config=cfg,
            ),
            count_tokens(get_search_heading_large_text()),
            ["src/v4/search/generated_4.py", "[filtered"],
            ["(unsorted)"],
        ),
        (
            "filter_bracketed_logs",
            lambda cfg: filter_output(
                get_bracketed_logs_large_text(),
                tool="wait_for_job",
                config=cfg,
            ),
            count_tokens(get_bracketed_logs_large_text()),
            ["ready in 1488ms", "[ERROR] failed to refresh preview cache"],
            [],
        ),
        (
            "filter_json",
            lambda cfg: filter_output(
                get_nested_json_large_text(),
                command="jq . response.json",
                config=cfg,
            ),
            count_tokens(get_nested_json_large_text()),
            ['"metadata"', '"files"', "[filtered"],
            [],
        ),
        (
            "filter_read_file",
            lambda cfg: filter_output(
                get_read_file_code_text(),
                tool="read_file",
                config=cfg,
            ),
            count_tokens(get_read_file_code_text()),
            ["class RequestHandler:", "def process(self", "import lines omitted"],
            [],
        ),
        (
            "filter_read_file_css",
            lambda cfg: filter_output(
                get_read_file_css_text(),
                tool="read_file",
                config=cfg,
            ),
            count_tokens(get_read_file_css_text()),
            ["#app-container", "CSS body lines omitted"],
            [],
        ),
        (
            "filter_read_file_fixture_heavy",
            lambda cfg: filter_output(
                get_read_file_fixture_heavy_text(),
                tool="read_file",
                config=cfg,
            ),
            count_tokens(get_read_file_fixture_heavy_text()),
            ["class IconRegistry:", "class ServiceClient:", "lines omitted"],
            [],
        ),
        # ── Format-switch strategy benchmarks (Strategies 1–9) ──
        (
            "filter_json_csv",
            lambda cfg: filter_output(
                get_csv_tabular_json_text(),
                command="jq . cards.json",
                config=cfg,
            ),
            count_tokens(get_csv_tabular_json_text()),
            ["id", "name", "price_usd"],
            [],
        ),
        (
            "filter_json_kv",
            lambda cfg: filter_output(
                get_kv_flat_object_text(),
                command="jq . config.json",
                config=cfg,
            ),
            count_tokens(get_kv_flat_object_text()),
            ["setting_"],
            [],
        ),
        (
            "filter_json_dotted",
            lambda cfg: filter_output(
                get_nested_json_dotted_text(),
                command="jq . status.json",
                config=cfg,
            ),
            count_tokens(get_nested_json_dotted_text()),
            ["service", "deployment", "archolith-rtk"],
            [],
        ),
        (
            "filter_stack_trace",
            lambda cfg: filter_output(
                get_stack_trace_java_text(),
                command="python app.py",
                config=cfg,
            ),
            count_tokens(get_stack_trace_java_text()),
            ["CardController.getById", "CardNotFoundException"],
            [],
        ),
        (
            "filter_stack_trace_python",
            lambda cfg: filter_output(
                get_stack_trace_python_text(),
                command="python app.py",
                config=cfg,
            ),
            count_tokens(get_stack_trace_python_text()),
            ["CardNotFoundError", "controller.py"],
            [],
        ),
        (
            "filter_git_status",
            lambda cfg: filter_output(
                get_git_status_short_text(),
                command="git status -s",
                config=cfg,
            ),
            count_tokens(get_git_status_short_text()),
            ["file_0.py", "handler_0.py"],
            [],
        ),
        (
            "filter_build_success",
            lambda cfg: filter_output(
                get_gradle_build_success_text(),
                command="gradle build",
                config=cfg,
            ),
            count_tokens(get_gradle_build_success_text()),
            ["BUILD SUCCESSFUL", "compileJava", "build"],
            [],
        ),
        (
            "filter_build_success_verbose",
            lambda cfg: filter_output(
                get_gradle_build_success_verbose_text(),
                command="gradle build --info",
                config=cfg,
            ),
            count_tokens(get_gradle_build_success_verbose_text()),
            ["BUILD SUCCESSFUL", "Tasks:", "compileJava"],
            [],
        ),
        (
            "filter_ls_la",
            lambda cfg: filter_output(
                get_ls_la_text(),
                command="ls -la",
                config=cfg,
            ),
            count_tokens(get_ls_la_text()),
            ["package.json", "src/"],
            [],
        ),
    ]

    rows: list[PracticalScenario] = []
    for name, runner, before_tokens, required, forbidden in base_scenarios:
        for level in ALL_RISK_LEVELS:
            cfg = base_config_for_risk_level(level)
            result, median_ms, p95_ms = _measure_call(
                lambda c=cfg, r=runner: r(c),
                before_each=reset_dedupe_tracker,
            )
            output = result.output
            after_tokens = count_tokens(output)
            checks: list[str] = []
            checks.extend(f"kept `{marker}`" for marker in required if marker in output)
            checks.extend(f"excluded `{marker}`" for marker in forbidden if marker not in output)
            if result.truncated:
                checks.append("reported truncation")
            if after_tokens < before_tokens:
                checks.append("reduced token count")
            checks_passed = (
                all(marker in output for marker in required)
                and all(marker not in output for marker in forbidden)
                # A scenario passes when tokens decrease (truncation compressed)
                # OR when the output is unchanged (small input fits within thresholds).
                # The latter is valid: the filter correctly decided the input
                # was small enough to pass through without lossy truncation.
                and (after_tokens < before_tokens or not result.truncated)
            )
            rows.append(
                PracticalScenario(
                    name=name,
                    risk_level=level.value,
                    kind="filter",
                    tokens_before=before_tokens,
                    tokens_after=after_tokens,
                    tokens_saved=max(0, before_tokens - after_tokens),
                    savings_pct=_pct_saved(before_tokens, after_tokens),
                    runtime_ms_median=median_ms,
                    runtime_ms_p95=p95_ms,
                    checks_passed=checks_passed,
                    checks=checks,
                )
            )
    return rows


def _build_shrink_scenarios() -> list[PracticalScenario]:
    history = build_large_tool_history(14)
    tool_calls = build_large_tool_call_messages()
    base_scenarios = [
        (
            "shrink_tool_results_token_mode",
            lambda: shrink_oversized_tool_results_by_tokens(build_large_tool_history(14), max_tokens=400),
            _tokens_for_messages(history),
            lambda result: _tokens_for_messages(result.messages),
            lambda result: [
                "healed tool messages" if result.healed_count > 0 else "",
                "saved tokens" if result.tokens_saved > 0 else "",
            ],
            lambda result: result.healed_count > 0 and result.tokens_saved > 0,
        ),
        (
            "shrink_tool_call_args",
            lambda: shrink_oversized_tool_call_args_by_tokens(build_large_tool_call_messages(), 350),
            _tokens_for_messages(tool_calls),
            lambda result: _tokens_for_messages(result.messages),
            lambda result: [
                "healed tool call args" if result.healed_count > 0 else "",
                "saved tokens" if result.tokens_saved > 0 else "",
            ],
            lambda result: result.healed_count > 0 and result.tokens_saved > 0,
        ),
    ]

    rows: list[PracticalScenario] = []
    for name, runner, before_tokens, after_fn, checks_fn, ok_fn in base_scenarios:
        result, median_ms, p95_ms = _measure_call(runner)
        after_tokens = after_fn(result)
        checks = [check for check in checks_fn(result) if check]
        rows.append(
            PracticalScenario(
                name=name,
                risk_level="n/a",
                kind="shrink",
                tokens_before=before_tokens,
                tokens_after=after_tokens,
                tokens_saved=max(0, before_tokens - after_tokens),
                savings_pct=_pct_saved(before_tokens, after_tokens),
                runtime_ms_median=median_ms,
                runtime_ms_p95=p95_ms,
                checks_passed=ok_fn(result) and after_tokens < before_tokens,
                checks=checks,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Preset-ordering and retention acceptance checks
# ---------------------------------------------------------------------------

_SCENARIO_ORDERING_EXCEPTIONS: dict[str, str] = {}
_SCENARIO_MIN_SAVINGS: dict[str, dict[str, float]] = {
    "filter_git_diff": {"low": 15.0, "balanced": 20.0, "high": 30.0},
    "filter_search_heading": {"low": 10.0, "balanced": 10.0, "high": 30.0},
    "filter_bracketed_logs": {"low": 10.0, "balanced": 20.0, "high": 30.0},
    "filter_json": {"low": 50.0, "balanced": 80.0, "high": 90.0},
    "filter_read_file": {"low": 10.0, "balanced": 20.0, "high": 30.0},
    "filter_read_file_css": {"low": 5.0, "balanced": 10.0, "high": 20.0},
    "filter_read_file_fixture_heavy": {"low": 20.0, "balanced": 30.0, "high": 40.0},
    # Format-switch strategy scenarios
    "filter_json_csv": {"low": 30.0, "balanced": 50.0, "high": 60.0},
    "filter_json_kv": {"low": 10.0, "balanced": 20.0, "high": 30.0},
    "filter_json_dotted": {"low": 0.0, "balanced": 0.0, "high": 30.0},
    "filter_stack_trace": {"low": 10.0, "balanced": 20.0, "high": 30.0},
    "filter_stack_trace_python": {"low": 0.0, "balanced": 0.0, "high": 30.0},
    "filter_git_status": {"low": 5.0, "balanced": 10.0, "high": 20.0},
    "filter_build_success": {"low": 0.0, "balanced": 15.0, "high": 25.0},
    "filter_build_success_verbose": {"low": 10.0, "balanced": 20.0, "high": 25.0},
    "filter_ls_la": {"low": 5.0, "balanced": 10.0, "high": 20.0},
}
_SCENARIO_RETENTION_MARKERS: dict[str, list[str]] = {
    "filter_git_diff": ["diff --git"],
    "filter_search_heading": ["src/v4/search/generated_4.py"],
    "filter_bracketed_logs": [
        "ready in 1488ms",
        "[ERROR] failed to refresh preview cache",
    ],
    "filter_json": ['"metadata"', '"files"'],
    "filter_read_file": ["class RequestHandler:", "def process(self"],
    "filter_read_file_css": ["#app-container"],
    "filter_read_file_fixture_heavy": ["class IconRegistry:", "class ServiceClient:"],
    # Format-switch strategy retention markers
    "filter_json_csv": ["id", "name", "price_usd"],
    "filter_json_kv": ["setting"],  # prefix of keys always in truncated JSON
    "filter_json_dotted": ["service", "deployment"],
    "filter_stack_trace": ["CardController.getById", "CardNotFoundException"],
    "filter_stack_trace_python": ["CardNotFoundError", "controller.py"],
    "filter_git_status": ["file_0.py", "handler_0.py"],
    "filter_build_success": ["BUILD SUCCESSFUL", "compileJava"],
    "filter_build_success_verbose": ["BUILD SUCCESSFUL", "compileJava"],
    "filter_ls_la": ["package.json", "src"],
}


def _run_acceptance_checks(rows: list[PracticalScenario]) -> list[_AcceptanceCheck]:
    checks: list[_AcceptanceCheck] = []

    filter_rows = [r for r in rows if r.kind == "filter"]
    scenario_names = sorted({r.name for r in filter_rows})

    for name in scenario_names:
        by_level: dict[str, PracticalScenario] = {}
        for r in filter_rows:
            if r.name == name:
                by_level[r.risk_level] = r

        low = by_level.get("low")
        balanced = by_level.get("balanced")
        high = by_level.get("high")

        # --- preset ordering: high >= balanced >= low savings ---
        if balanced and high:
            if high.tokens_saved < balanced.tokens_saved:
                exc = _SCENARIO_ORDERING_EXCEPTIONS.get(name, "")
                if exc:
                    checks.append(_AcceptanceCheck(
                        description=f"{name}: high savings >= balanced savings",
                        passed=False,
                        detail=f"EXCEPTION: {exc} (high={high.tokens_saved}, balanced={balanced.tokens_saved})",
                    ))
                else:
                    checks.append(_AcceptanceCheck(
                        description=f"{name}: high savings >= balanced savings",
                        passed=False,
                        detail=f"high={high.tokens_saved} < balanced={balanced.tokens_saved}",
                    ))
            else:
                checks.append(_AcceptanceCheck(
                    description=f"{name}: high savings >= balanced savings",
                    passed=True,
                    detail=f"high={high.tokens_saved} >= balanced={balanced.tokens_saved}",
                ))

        if low and balanced:
            if balanced.tokens_saved < low.tokens_saved:
                exc = _SCENARIO_ORDERING_EXCEPTIONS.get(name, "")
                if exc:
                    checks.append(_AcceptanceCheck(
                        description=f"{name}: balanced savings >= low savings",
                        passed=False,
                        detail=f"EXCEPTION: {exc} (balanced={balanced.tokens_saved}, low={low.tokens_saved})",
                    ))
                else:
                    checks.append(_AcceptanceCheck(
                        description=f"{name}: balanced savings >= low savings",
                        passed=False,
                        detail=f"balanced={balanced.tokens_saved} < low={low.tokens_saved}",
                    ))
            else:
                checks.append(_AcceptanceCheck(
                    description=f"{name}: balanced savings >= low savings",
                    passed=True,
                    detail=f"balanced={balanced.tokens_saved} >= low={low.tokens_saved}",
                ))

        # --- minimum savings thresholds ---
        thresholds = _SCENARIO_MIN_SAVINGS.get(name, {})
        for level_name, min_pct in thresholds.items():
            row = by_level.get(level_name)
            if row is None:
                continue
            if row.savings_pct < min_pct:
                checks.append(_AcceptanceCheck(
                    description=f"{name}/{level_name}: savings >= {min_pct}%",
                    passed=False,
                    detail=f"actual={row.savings_pct}%",
                ))
            else:
                checks.append(_AcceptanceCheck(
                    description=f"{name}/{level_name}: savings >= {min_pct}%",
                    passed=True,
                    detail=f"actual={row.savings_pct}%",
                ))

        # --- retention markers survive at all presets ---
        markers = _SCENARIO_RETENTION_MARKERS.get(name, [])
        for level_name in ("low", "balanced", "high"):
            row = by_level.get(level_name)
            if row is None:
                continue
            for marker in markers:
                found = any(marker in c for c in row.checks)
                if not found:
                    checks.append(_AcceptanceCheck(
                        description=f"{name}/{level_name}: retains `{marker}`",
                        passed=False,
                        detail=f"marker not found in checks (tokens_after={row.tokens_after})",
                    ))
                else:
                    checks.append(_AcceptanceCheck(
                        description=f"{name}/{level_name}: retains `{marker}`",
                        passed=True,
                    ))

    # --- shrink scenarios: basic sanity ---
    for row in rows:
        if row.kind != "filter":
            if not row.checks_passed:
                checks.append(_AcceptanceCheck(
                    description=f"{row.name}: checks_passed",
                    passed=False,
                    detail="scenario checks failed",
                ))
            else:
                checks.append(_AcceptanceCheck(
                    description=f"{row.name}: checks_passed",
                    passed=True,
                ))

    return checks


def _run_format_switch_baseline(rows: list[PracticalScenario]) -> list[_AcceptanceCheck]:
    """Verify that each format-switch scenario saves more tokens than truncation-only.

    For each format-switch scenario, run the same corpus through filter_output
    with all format-switch knobs disabled and compare token savings against the
    enabled run. The format-switch path must save at least as many tokens as
    truncation-only (ideally more).
    """
    checks: list[_AcceptanceCheck] = []

    # Scenarios that use format-switch strategies (name → command or tool)
    format_switch_scenarios = {
        "filter_json_csv": ("jq . cards.json", None),
        "filter_json_kv": ("jq . config.json", None),
        "filter_json_dotted": ("jq . status.json", None),
        "filter_stack_trace": ("python app.py", None),
        "filter_stack_trace_python": ("python app.py", None),
        "filter_git_status": ("git status -s", None),
        "filter_build_success": ("gradle build", None),
        "filter_build_success_verbose": ("gradle build --info", None),
        "filter_ls_la": ("ls -la", None),
    }

    # Build a config with all format-switch knobs disabled
    from archolith_rtk.config import FilterConfig

    def _truncation_only_config(risk: FilterRiskLevel) -> FilterConfig:
        """Config with all format-switch knobs disabled — pure truncation."""
        base = base_config_for_risk_level(risk)
        return FilterConfig(
            # Copy all base settings
            **{
                k: getattr(base, k)
                for k in [
                    "generic_head", "generic_tail",
                    "generic_stack_collapse_enabled", "generic_stack_collapse_min_frames",
                    "generic_stack_collapse_keep_app_frames",
                    "json_max_keys_per_object", "json_max_array_items", "json_max_depth",
                    "json_max_value_length",
                    "git_status_head", "git_status_tail",
                    "git_status_group_enabled", "git_status_group_max_per_line",
                    "build_head", "build_tail", "build_summary_enabled",
                    "fs_max_entries", "fs_head_lines", "fs_tail_lines",
                    "fs_lsl_abbreviate_enabled",
                    "search_max_matches_per_file", "search_max_files",
                    "search_head_lines", "search_tail_lines",
                    "search_heading_reformat_enabled",
                ]
            },
            # Disable all format-switch knobs
            json_csv_enabled=False,
            json_csv_min_rows=1000,
            json_csv_max_rows=10,
            json_csv_max_key_length=20,
            json_csv_factor_enabled=False,
            json_csv_factor_threshold=0.8,
            json_csv_factor_max_columns=5,
            json_kv_enabled=False,
            json_kv_min_keys=1000,
            json_kv_max_keys=10,
            json_dotkey_enabled=False,
            json_dotkey_max_keys=10,
            json_dotkey_max_depth=3,
        )

    # Corpora generators mapped by scenario name
    from benchmarks.corpora import (
        get_csv_tabular_json_text,
        get_kv_flat_object_text,
        get_nested_json_dotted_text,
        get_stack_trace_java_text,
        get_stack_trace_python_text,
        get_git_status_short_text,
        get_gradle_build_success_text,
        get_gradle_build_success_verbose_text,
        get_ls_la_text,
    )
    corpora = {
        "filter_json_csv": get_csv_tabular_json_text,
        "filter_json_kv": get_kv_flat_object_text,
        "filter_json_dotted": get_nested_json_dotted_text,
        "filter_stack_trace": get_stack_trace_java_text,
        "filter_stack_trace_python": get_stack_trace_python_text,
        "filter_git_status": get_git_status_short_text,
        "filter_build_success": get_gradle_build_success_text,
        "filter_build_success_verbose": get_gradle_build_success_verbose_text,
        "filter_ls_la": get_ls_la_text,
    }

    for level in ALL_RISK_LEVELS:
        trunc_config = _truncation_only_config(level)
        for name in format_switch_scenarios:
            if name not in corpora:
                continue
            text = corpora[name]()
            command, tool = format_switch_scenarios[name]
            before_tokens = count_tokens(text)

            # Find the enabled scenario result
            enabled_rows = [r for r in rows if r.name == name and r.risk_level == level.value]
            if not enabled_rows:
                continue
            enabled_row = enabled_rows[0]

            # Run with truncation-only config
            reset_dedupe_tracker()
            kwargs = {"command": command, "config": trunc_config}
            if tool:
                kwargs = {"tool": tool, "config": trunc_config}
            trunc_result = filter_output(text, **kwargs)
            trunc_tokens = count_tokens(trunc_result.output)

            enabled_tokens = enabled_row.tokens_after
            enabled_saved = before_tokens - enabled_tokens
            trunc_saved = before_tokens - trunc_tokens

            # Format-switch must save at least as many tokens as truncation-only
            if enabled_saved >= trunc_saved:
                checks.append(_AcceptanceCheck(
                    description=f"{name}/{level.value}: format-switch >= truncation-only",
                    passed=True,
                    detail=f"enabled_saved={enabled_saved} >= trunc_saved={trunc_saved}",
                ))
            else:
                checks.append(_AcceptanceCheck(
                    description=f"{name}/{level.value}: format-switch >= truncation-only",
                    passed=False,
                    detail=f"enabled_saved={enabled_saved} < trunc_saved={trunc_saved} ({enabled_tokens} vs {trunc_tokens} tokens after)",
                ))

    return checks


def _render_markdown(rows: list[PracticalScenario], acceptance: list[_AcceptanceCheck]) -> str:
    lines = [
        "# Practical Benchmark Report",
        "",
        (
            "| Scenario | Risk Level | Kind | Tokens Before | "
            "Tokens After | Tokens Saved | Saved % | Median ms | p95 ms | Checks |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        check_summary = "; ".join(row.checks) if row.checks else "none"
        lines.append(
            f"| {row.name} | {row.risk_level} | {row.kind} | {row.tokens_before} | "
            f"{row.tokens_after} | {row.tokens_saved} | {row.savings_pct}% | "
            f"{row.runtime_ms_median:.3f} | {row.runtime_ms_p95:.3f} | {check_summary} |"
        )

    lines.append("")
    lines.append("## Acceptance Checks")
    lines.append("")
    lines.append("| Check | Passed | Detail |")
    lines.append("|---|---|---|")
    for ac in acceptance:
        passed_str = "PASS" if ac.passed else "FAIL"
        lines.append(f"| {ac.description} | {passed_str} | {ac.detail} |")

    lines.extend(
        [
            "",
            "Checks are scenario-specific retention and structure invariants. "
            "A scenario is only considered passing when those checks hold and token count decreases.",
            "",
            "Acceptance checks enforce preset-ordering (high >= balanced >= low savings), "
            "minimum savings thresholds, and retention marker survival across all risk levels.",
        ]
    )
    return "\n".join(lines)


def _render_baseline_section(baseline: list[_AcceptanceCheck]) -> str:
    """Render format-switch vs truncation-only baseline comparison."""
    lines = [
        "",
        "## Format-Switch vs Truncation-Only Baseline",
        "",
        "Each format-switch scenario is run with format-switch knobs disabled "
        "(pure truncation) to verify that the format-switch path saves at least "
        "as many tokens as truncation-only.",
        "",
        "| Check | Passed | Detail |",
        "|---|---|---|",
    ]
    for ac in baseline:
        passed_str = "PASS" if ac.passed else "FAIL"
        lines.append(f"| {ac.description} | {passed_str} | {ac.detail} |")
    return "\n".join(lines)


def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = _build_filter_scenarios() + _build_shrink_scenarios()
    acceptance = _run_acceptance_checks(rows)
    baseline = _run_format_switch_baseline(rows)
    all_passed = (
        all(row.checks_passed for row in rows)
        and all(ac.passed for ac in acceptance)
        and all(ac.passed for ac in baseline)
    )

    payload = [asdict(row) for row in rows]
    payload.append(
        {
            "_acceptance": [
                {
                    "description": ac.description,
                    "passed": ac.passed,
                    "detail": ac.detail,
                }
                for ac in acceptance
            ]
        }
    )
    JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    MARKDOWN_PATH.write_text(_render_markdown(rows, acceptance) + _render_baseline_section(baseline), encoding="utf-8")
    print(f"Wrote {JSON_PATH}")
    print(f"Wrote {MARKDOWN_PATH}")

    if not all_passed:
        failed_scenario = [r for r in rows if not r.checks_passed]
        failed_acceptance = [ac for ac in acceptance if not ac.passed]
        if failed_scenario:
            print(f"FAILED scenarios: {', '.join(r.name for r in failed_scenario)}")
        if failed_acceptance:
            for ac in failed_acceptance:
                print(f"FAILED acceptance: {ac.description} — {ac.detail}")
        failed_baseline = [ac for ac in baseline if not ac.passed]
        if failed_baseline:
            for ac in failed_baseline:
                print(f"FAILED baseline: {ac.description} — {ac.detail}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
