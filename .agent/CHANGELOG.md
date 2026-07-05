# Changelog — archolith-filter

## Historical Context

**RTK** (Reasonix Token Kit) = historical internal code name for "archolith-filter", used prior to public release and remediation phases. References to "RTK" in older archived documents, comments, or deprecated notes refer to this project's earlier iteration. The current project name is **archolith-filter**.

## 2026-06-21 — Shared Token Accounting Dependency

- **refactor(shrink):** `shrink.token_counter` now delegates tokenizer selection and fallback token-count policy to `archolith-maintenance`.
- **packaging:** Added `archolith-maintenance` as the shared helper dependency for canonical token accounting.

## 2026-06-20 — Token-count accuracy remediation (Session B)

- **fix(shrink):** fallback token counting now uses a shape-aware heuristic: prose keeps the historical ~4 chars/token estimate, while code/config-like text uses a more conservative ~3.2 chars/token estimate and emits a one-time warning when `tiktoken` is unavailable.
- **fix(truncate):** token truncation no longer accepts a single fallback estimate as proof that text fits; edge-window sizing now uses bounded binary search to avoid the previous early-exit underfill from damped convergence.
- **fix(accounting):** `estimate_conversation_tokens()` now includes a 15-token per-message framing estimate so callers do not undercount chat-template overhead.
- **docs:** README, `.env.example`, and architecture/data-model docs updated to describe the fallback and Layer 3 agent-solo surface accurately.

## 2026-06-19 — Audit remediation (High tier)

Closed the surviving High findings from the 2026-06-07 chunk audits (re-verified against current code; 2 of 7 were already remediated).

- **fix(logs):** log header extraction now uses `generic._extract_header`, fixing `[exit N]`/`[killed]` headers previously treated as body (chunk6 H-2).
- **fix(redact):** connection-string redaction targets only the `user:pass` credential, preserving scheme/host/database/query for diagnostics; handles empty-username form (chunk8 H1).
- **refactor(_patterns):** added shared `LINE_COMMENT_RE` / `is_line_comment()`; `read_file.py` no longer shadows it locally (chunk6 H-1).
- **refactor(shrink):** extracted `_collapse_imports_and_comments()` shared by char/token read_file truncators, removing duplicated logic (chunk7 F-04).
- **Deferred:** chunk6 H-3 (json_output perf) — the audit's minified-JSON lower-bound heuristic is unsound because `_compress_value` truncates long strings and can be shorter than minified JSON; deferred pending a sound approach. All Medium/Low findings deferred per launch posture.
- **Verification:** `pytest` 341 passed / 1 skipped; `ruff check` clean on touched files.

## 2026-06-02 — Layer 0 pre-filter pipeline wiring

- **Layer 0 pipeline**: Wired `redact_secrets()`, `strip_thinking_blocks()`, and `normalize_paths()` into `filter_output()` with per-stage config gating. Added binary detection (NUL-byte scan, early return at <10% text ratio), oversized input guard (500KB default threshold, head/tail preview), and table whitespace minimization in `fs_listing_filter()`.
- **Runtime noise normalization**: `normalize_runtime_noise()` now called inside `log_filter()`, `build_filter()`, and `filter_test_output()` to replace timestamps/PIDs/elapsed times with stable placeholders.
- **9 new config knobs**: `REDACT_ENABLED`, `BINARY_DETECTION_ENABLED`, `OVERSIZED_GUARD_ENABLED`, `OVERSIZED_MAX_CHARS`, `STRIP_THINKING_ENABLED`, `NORMALIZE_PATHS_ENABLED`, `NORMALIZE_NOISE_ENABLED`, `TABLE_WHITESPACE_MIN_ENABLED` — all toggleable via `ARCHOLITH_FILTER_*` env vars.
- **Verification gates pass**: `ruff check archolith_filter` (0 errors in package code), `pytest tests/` (335/335), `benchmarks/practical_report.py` (all scenarios and acceptance checks pass).

## 2026-06-02 — format-switch benchmark coverage (Step 12)

- Added benchmark corpora generators for all 9 format-switch strategies to `benchmarks/corpora.py`.
- Added 9 filter scenarios with retention markers and min-savings thresholds to `benchmarks/practical_report.py`.
- Added truncation-only baseline comparison proving format-switch savings are materially better than truncation alone.
- Fixed `checks_passed` logic to correctly handle small corpora that pass through unchanged at low/balanced risk.
- Enlarged Python stack trace, dotted-key JSON, and build corpora to ensure meaningful compression at all risk levels.
- All format-switch scenarios now pass practical benchmark with `--exit-0`.
- Fixed the truncation-only baseline to disable every format-switch knob it was meant to compare against, including stack collapse, git-status grouping, build summaries, and `ls -la` abbreviation.
- Added aggregate baseline gates so Step 12 now proves material improvement at every preset: `+1175` low, `+1252` balanced, `+1296` high, `+3723` overall versus truncation-only.
- Fixed no-op `agent_solo` orchestration so unchanged turns preserve identity and still report `no_strategies_enabled`, which restores a clean full pytest run for the plan verification set.

## 2026-06-02 — format-switch compression (Strategies 1-9)

- **Strategy 1 (CSV)**: JSON arrays of uniform objects are serialized as CSV with header rows, showing significantly more data in fewer tokens than truncated JSON.
- **Strategy 2 (KV)**: Flat JSON objects (≥3 keys, no nesting) are rendered as `key: value` lines, removing JSON syntax overhead.
- **Strategy 3 (Dotted-key)**: Nested JSON objects with flat leaf values are flattened to `a.b.c: value` dotted-key lines.
- **Strategy 4 (Column factoring)**: Extends CSV by extracting columns where one dominant value appears in ≥80% of rows as `key=value` lines above the header.
- **Strategy 5 (Stack trace collapsing)**: Detects Java, Python, Node, and Go stack traces in generic output; collapses framework frames into a summary line while preserving application frames.
- **Strategy 6 (Git status grouping)**: Groups short-format `git status -s` lines by directory prefix and status code, reducing repeated path prefixes.
- **Strategy 7 (Search heading reformat)**: Reformats inline-style grep matches (`path:line:content`) to heading style with the file path stated once and matches indented below.
- **Strategy 8 (Build task summary)**: For successful Gradle/Maven builds, detects task lines and emits a compact summary (`BUILD SUCCESSFUL in Xs / Tasks: ...`) instead of the full task list.
- **Strategy 9 (ls -la abbreviation)**: Parses `ls -la/l` column format and emits abbreviated output with just name, type hint, and human-readable size.
- All 9 strategies include safety checks and fall back to existing behavior when format-switch output isn't shorter.
- Added 17 new config knobs with env-var overrides and risk-level presets for all strategies.
- Added 29 new tests covering strategy detection, serialization, edge cases, and knob controls.
- Updated `architecture.md`, `README.md`, and both changelogs.

## 2026-05-31 — agent-solo turn compression (Layer 3)

- Added `agent_solo.py` with four composable compression strategies (A-D) for tool-call continuation turns.
- **Strategy A (Shrink)**: Char-budget every tool result to `max_tokens * 4` chars. Replaced tiktoken with char-based math for 636x speedup on large sessions.
- **Strategy B (Dedup)**: Cross-turn content hash tracking via `DedupeTracker`. Replaces byte-identical results with compact markers.
- **Strategy C (Filter middle)**: Splits messages into system/middle/tail. Applies `filter_output()` to compressible tools in the middle, shrinks tail results.
- **Strategy D (Compact tool args)**: Replaces large Write/Edit/create_file content in completed tool_use calls with compact summaries. Model can Read to recover. Default on.
- Added `AgentSoloStats`, `AgentSoloResult` dataclasses and exported from `__init__.py`.
- Added `tests/test_agent_solo.py` with 21 tests covering all strategies.
- Updated architecture docs to document Layer 3 and dedupe module.

## 2026-05-31 — completed quality remediation closeout

- Committed the missing `normalize.py`, `paths.py`, `redact.py`, and `strip_thinking.py` modules that the trimmed public API already referenced, eliminating the detached-review import failure in `archolith_filter.__init__`.
- Committed focused regression coverage for runtime-noise normalization, path normalization, secret redaction, and thinking-block stripping so the new public helpers are exercised directly.
- Re-ran the full pytest suite (`293 passed, 1 skipped`) plus the targeted compound-literal regression subset (`13 passed`) to confirm the remediation plan now lands as a runnable work product rather than untracked drift.

## 2026-05-25 — added dedupe and read_file-aware Layer 2 shrink

- Added exact-match cross-turn output deduplication with `DedupeTracker`, public reset/get helpers, raw-output recovery markers, and telemetry accounting for dedupe hits.
- Added declaration-aware `read_file` truncation in Layer 2 for both char and token budgets so oversized file reads preserve imports/comments/declarations more intelligently than generic head-tail truncation.
- Extended filter/shrink test coverage and updated the practical benchmark harness to reset dedupe state between timed filter scenarios.

## 2026-05-25 — deepened read_file compression

- Replaced the lightweight `read_file` filter with a more aggressive structure-aware pass that collapses generated/minified blobs, large literal fixtures, embedded JSON, multiline strings, and SVG-heavy blocks while preserving declarations and nearby anchors.
- Extended `FilterConfig`, tests, and practical benchmark corpora/reporting to cover code, CSS, and fixture-heavy `read_file` scenarios.
- Kept the package positioned as a two-layer RTK by merging the delegated `read_file` work without reintroducing the removed Layer 3 docs or benchmark surface.

## 2026-05-24 — strengthened git diff compression

- Reworked `git_diff_filter()` to stop re-inflating compressed output with a redundant whole-diff tail.
- Switched large per-file diff previews to compact representative changed-line sampling while preserving structural diff headers.
- Added regressions covering multi-file preview retention and reran the practical benchmark report, raising `filter_git_diff` savings from roughly `5%` to `45-50%` on the benchmark corpus.

## 2026-05-24 — removed Layer 3 suite surface from RTK

- Removed `context_manager.py` and its public exports so `archolith-filter` now owns only Layer 1 filtering, Layer 2 shrinking, and shared token/truncation primitives.
- Removed Layer 3 tests and benchmark coverage, including the context-fold scenario from the practical benchmark report.
- Updated README, root changelog, and agent docs to describe `archolith-context` as the owner of conversation-level context strategy.

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
- Added `ARCHOLITH_FILTER_RISK_LEVEL` support in `from_env()`, with explicit env overrides still taking precedence over the selected preset.
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
