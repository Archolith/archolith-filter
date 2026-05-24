# Changelog — archolith-rtk

## 2026-05-24 — fixed heading-mode search calibration for practical risk benchmarks

- Preserved heading-mode search path lines in `search_filter()` output so grouped `rg --heading` results keep the file headings users need for review and benchmark retention checks.
- Stopped counting blank separator lines as per-file matches in heading-mode search parsing, which removed bogus omission markers and restored monotonic low/balanced/high token-savings ordering on the practical benchmark corpus.
- Added regressions covering heading-path preservation for digit-bearing search paths and reran the practical report so all acceptance checks pass again.

## 2026-05-24 — cleaned harness artifact noise

- Ignored generated harness handoff files via `TASK-*.md` so delegation prompts stop polluting repo status.
- Ignored local `logs/` output produced by harness-backed runs.
- Ignored generated benchmark result artifacts under `benchmarks/results/` while preserving `.gitkeep` so reruns do not clutter `git status`.

## 2026-05-24 — extended practical report with multi-preset evaluation and acceptance checks

- Extended `benchmarks/practical_report.py` to evaluate every Layer 1 filter scenario at all three `FilterRiskLevel` presets (low, balanced, high) instead of a single effective configuration.
- Added per-row `risk_level` field to Markdown and JSON artifacts.
- Added acceptance checks: preset ordering (high >= balanced >= low savings), minimum savings thresholds per scenario/level, and retention marker survival across all presets.
- Script exits non-zero on any acceptance failure, suitable for CI gating.
- Documented known non-monotonic preset ordering for `filter_search_heading` (balanced saves fewer tokens than low due to per-file match cap interaction with heading-mode grouping).
- Documented retention failure for `filter_search_heading/low` (marker `src/v4/search/generated_4.py` not retained at low preset).
- Updated README benchmark docs to describe multi-preset evaluation and acceptance check output.

## 2026-05-24 — added configurable compression risk levels

- Added `FilterRiskLevel` presets (`low`, `balanced`, `high`) and `base_config_for_risk_level()` so callers can pick a token-savings/data-loss posture explicitly.
- Added `ARCHOLITH_RTK_FILTER_RISK_LEVEL` support in `from_env()`, with explicit env overrides still taking precedence over the selected preset.
- Added regression coverage and README/docs updates for the new risk-level behavior.

## 2026-05-24 — added practical token-efficiency benchmark reporting

- Added shared benchmark corpora helpers so fixture generation and benchmark/reporting flows use the same payloads.
- Added `benchmarks/practical_report.py` to score realistic scenarios on tokens before/after, savings percentage, runtime, and retention checks.
- Documented the practical-report workflow and output artifacts in the main README.

## 2026-05-23 — added benchmark harness

- Added a dedicated `benchmarks/` suite with realistic fixture corpora for large git diff, heading-mode search, and bracketed log output.
- Added `pytest-benchmark` benchmark coverage for all three RTK layers: `filter_output()`, shrink helpers, and `ContextManager`.
- Documented benchmark installation and execution in the main README and wired `pytest-benchmark` into the dev extra.

## 2026-05-23 — resolved review-confirmed context reduction defects

- Fixed `ContextManager.fold()` so successful folds now compact the provided message list in place instead of only reporting a reduced count.
- Fixed `generic_filter()` header detection so bracket-prefixed output like `[INFO] ...` is treated as body content and can be truncated.
- Fixed `search_filter()` heading-mode grouping for paths containing digits, such as `src/v2/...`, and added regression coverage for all three defects.

## 2026-05-23 — compatibility and quality-gate cleanup

- Restored the documented public compatibility APIs: `shrink_messages()` and `ContextManager.decide_after_turn(...)`.
- Fixed heading-mode search grouping, `raw_output` / shell passthrough handling, and the Python 3.11 JSON filter compatibility issue.
- Added regression coverage for the API compatibility paths and filter edge cases, and cleaned repo-wide Ruff violations so `ruff check .` passes again.

## Unreleased

- Added missing public compatibility APIs: `shrink_messages()` for OpenAI-format message lists and `ContextManager.decide_after_turn(...)`.
- Fixed heading-mode search filtering and passthrough handling for `raw_output` / shell-routed tool classifications.
- Expanded filter and compatibility coverage to bring the documented RTK coverage gate back above 90%.

## 2026-05-23 — Agent scaffolding and docs population

- Added `.agent/` directory with full project documentation (README, architecture, data_models, code_conventions, CHANGELOG)
- Added LLM instruction files (CLAUDE.md, AGENTS.md, gemini.md, QWEN.md, .cursorrules, .windsurfrules, .clinerules, .github/copilot-instructions.md)
- Added `.githooks/pre-push` and configured `core.hooksPath`
- Populated all `.agent/` docs with real project content
