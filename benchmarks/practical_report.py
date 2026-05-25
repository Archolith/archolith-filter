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
    shrink_oversized_tool_call_args_by_tokens,
    shrink_oversized_tool_results_by_tokens,
)

try:
    from benchmarks.corpora import (
        build_large_tool_call_messages,
        build_large_tool_history,
        get_bracketed_logs_large_text,
        get_git_diff_large_text,
        get_nested_json_large_text,
        get_read_file_code_text,
        get_read_file_css_text,
        get_read_file_fixture_heavy_text,
        get_search_heading_large_text,
    )
except ModuleNotFoundError:
    from corpora import (
        build_large_tool_call_messages,
        build_large_tool_history,
        get_bracketed_logs_large_text,
        get_git_diff_large_text,
        get_nested_json_large_text,
        get_read_file_code_text,
        get_read_file_css_text,
        get_read_file_fixture_heavy_text,
        get_search_heading_large_text,
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


def _measure_call(func, iterations: int = 15) -> tuple[object, float, float]:
    samples: list[float] = []
    result = None
    for _ in range(iterations):
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
    ]

    rows: list[PracticalScenario] = []
    for name, runner, before_tokens, required, forbidden in base_scenarios:
        for level in ALL_RISK_LEVELS:
            cfg = base_config_for_risk_level(level)
            result, median_ms, p95_ms = _measure_call(lambda c=cfg, r=runner: r(c))
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
                and result.truncated
                and after_tokens < before_tokens
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


def main() -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = _build_filter_scenarios() + _build_shrink_scenarios()
    acceptance = _run_acceptance_checks(rows)
    all_passed = all(row.checks_passed for row in rows) and all(ac.passed for ac in acceptance)

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
    MARKDOWN_PATH.write_text(_render_markdown(rows, acceptance), encoding="utf-8")
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

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
