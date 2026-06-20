# Changelog

## Unreleased

### 2026-06-20 — Audit remediation (archolith-filter-remediation-plan-2026-06-20)

Worked the 2026-06-20 audit remediation plan: Sessions A, C, E and a bulk safe-fixes commit landed in main. Session B (cross-project token-count accuracy bundle, archolith-filter + archolith-context CORR-07) is deferred to a separate tracked session. 4 commits in archolith-filter main + 1 closeout commit in the meta-archolith repo:

- **Session A (commit 6f2becb) — strip_thinking.py rewrite (AI-B1/B2/B3 + MAINT-02):**
  - `archolith_filter/strip_thinking.py`: rewrote closed/unclosed-block regex patterns to (a) accept an optional XML namespace prefix on any known tag (`<antml:thinking>`, `<anthropic:reasoning>`) — AI-B1; (b) use a negative-lookahead inner-content pattern that prefers the innermost closed pair plus loop-until-stable (cap 10) to unwind nested constructs like `<thinking>outer <reasoning>inner</reasoning> between</thinking>` (AI-B2); (c) strip dangling partial close-tag fragments at EOF (`</thinking` without `>`, including namespaced variants) left behind by stream cutoff (AI-B3).
  - `archolith_filter/__init__.py`: module docstring updated — "Two layers" → "Three layers"; added `compress_agent_solo_turn()` to the documented public API list (MAINT-02).
  - `tests/test_strip_thinking.py`: +18 new tests covering namespace-prefixed variants, nested 2/3/4-deep + mixed-tag nesting, namespaced nesting, loop-termination guarantees, and stream-cutoff artifacts.

- **Session C (commit 94b4eed) — agent_solo.py tail-guard for Strategy A shrink (AI-C1):**
  - `archolith_filter/agent_solo.py`: `_apply_shrink` accepts `tail_start_index: int | None = None`; skips tool-role messages whose index is at or above that boundary (mirrors the existing `_apply_dedup` tail-guard). Orchestrator's tail-boundary computation is now unconditional (was gated on `filter_middle_enabled or dedup_enabled`); `tail_start_index` is None when there is no middle section. The audit's A+C double-truncation edge case is documented in `_apply_shrink`'s docstring with a revisit clause (option A chosen over option B per plan §C.1). Drop unused `last_idx` local in `_apply_dedup` (pre-existing ruff F841).
  - `tests/test_agent_solo.py`: +5 new tests covering orchestrator-level tail-guard for 5-message list with coherence_tail_size=2, too-few-messages degenerate case, direct-API default (tail_start_index=None backward compat), explicit tail_start_index param, and system-prefix offset.

- **Session E (commit 3130a92) — redact.py tightening (SEC-B1 + DR-2):**
  - `archolith_filter/redact.py`: SEC-B1 — loosen OpenAI standard key pattern from `sk-[A-Za-z0-9]{48}` to `sk-[A-Za-z0-9]{32,}` to catch legacy 32-char tokens; add `sk_proj_[A-Za-z0-9\-_]{40,}` and `sk_svcacct_[A-Za-z0-9\-_]{40,}` underscore variants for non-standard keys seen in the wild. Audit's "ASIA missing" claim was a false positive — pattern #1 has always covered ASIA via the AWS prefix alternation; regression test locks this in. DR-2 — extend pattern #11 keyword alternation to include `auth_token | authToken | TWILIO_AUTH_TOKEN`. Per §E.2.2 revised plan the quote requirement on the value is intentionally kept (avoids git SHA / content-hash false positives); bare unquoted `auth_token=<hex>` is intentionally uncaught. JSON-quoted-key form is also unmatched in this revision (test documents the limitation). Added an audit-calibration comment block at the top of `_PATTERN_SPECS` capturing both calibration notes.
  - `tests/test_redact.py`: +12 new tests in a new `TestAuditCalibration2026_06_20` class.

- **Bulk Safe Fixes #1 (commit 55abb82) — 15 no-observable-behavior-change items:**
  - `pyproject.toml`: removed deprecated `"License :: Other/Proprietary License"` classifier (CF-3) — license is canonical via `license = "LicenseRef-PolyForm-Noncommercial-1.0.0"`.
  - `archolith_filter/config.py:296`: added 8-space indent to match sibling fields in the FilterConfig constructor (CF-4) — audit's "BLOCKER" was a false positive; Python's tokenizer accepted the zero-indent form inside the open-parenthesized call.
  - `archolith_filter/_patterns.py:13-14`: updated stale comment ("currently recompiles on every call" → reflects pre-compiled VERBOSE_FLAG_PATTERNS) (CF-5).
  - `AGENTS.md:51`: expanded the "Three layers" project-notes bullet to expose agent-solo turn compression as a separate section listing the 4 strategies A-D (CF-6).
  - `archolith_filter/redact.py`: added attribution header listing public-spec sources for each pattern category (COMP-02); added SEC-C1 size guard at the top of `redact_secrets` — inputs over 50_000 chars return unchanged with `redaction_count=0` and a `WARNING` log. Empirical verification proved current redaction regex has NO ReDoS exposure (bounded-linear ~70-90ms on 500K-char pathological input); the guard is defense-in-depth insurance against future pattern additions that could regress that property.
  - `archolith_filter/agent_solo.py`: added `_log.debug(...)` inside all 4 strategy blocks' `except Exception` clauses (AI-C5 doc); added `_log.debug(...)` on non-MCP suffix-match classifications in `_is_compressible_tool` so production traces surface mis-classified custom tools after 30-60 days of observation (AI-C2 instrumentation — audit's `my_custom_bash_runner` example was empirically re-verified as a NON-match since `endswith` requires suffix at the END, not substring).
  - `archolith_filter/__init__.py`: added `_log.warning(...)` before the `filter_output` fail-open fallback (DR-1 doc) — fail-open semantics preserved; just emits a WARNING with command, tool, and exception message.
  - `archolith_filter/raw_store.py:52-56`: replaced `sorted(self._entries.keys())` with `list(self._entries.keys())[:excess]` — O(n) instead of O(n log n); semantically equivalent since `_next_id` is monotonic so insertion order matches numeric order (PERF-01). Added module-docstring note on eviction / telemetry-dangling-reference trade-off (FC-B2).
  - `archolith_filter/dedupe.py:35-37`: added comment explaining CPython 3.7+ dict insertion-order guarantee for the FIFO eviction at `next(iter(self._seen))` (FC-B1).
  - `archolith_filter/telemetry.py:16`: `@dataclass` → `@dataclass(frozen=True)` for `FilterTelemetryEntry` — prevents caller mutation of stored entries (FC-C2).
  - New files: `.env.example` (all 60+ `ARCHOLITH_FILTER_*` env vars indexed by category with defaults and usage notes) (COMP-03); `THIRD-PARTY-LICENSES.txt` (tiktoken/MIT, pytest/MIT, pytest-benchmark/BSD-2-Clause, pytest-cov/MIT, ruff/MIT + attribution notes for the public-spec sources behind `redact.py` patterns) (COMP-01).
  - `README.md`: added "Development Installation" section explaining `[tokenizer]` vs `[context]` optional extras; notes that `[context]` currently fails on fresh checkouts because `archolith-proxy` isn't published yet; cross-refs `ARCHOLITH-FILTER-DISTRIBUTION-PLAN` (CF-1 doc — code-level CF-1 fix is deferred).

  Items intentionally NOT shipped in this bulk commit:
  - #5 MAINT-02 already shipped in Session A.
  - #6 ARCH-01 (`py.typed` marker) was already pre-satisfied by the `archolith_rtk` → `archolith_filter` rename refactor (commit 1cf66f6, file tracked).
  - #19 audit-calibration marks deferred to the meta-archolith repo (the audit issues file lives at `projects/archolith/.agent/reviews/archolith-filter-outstanding-issues.md` outside the archolith-filter git boundary). Closed separately as commit `00225cf` in meta-archolith main.

- **Closeout (meta-archolith commit 00225cf):** appended a "Status — 2026-06-20 closeout" section to `.agent/reviews/archolith-filter-outstanding-issues.md` recording the resolution path for every audit ID, the Tier-0 calibration summary table (the empirically-verified false positives / severity overcalls for CF-4, AI-A2, AI-C2, SEC-C1, SEC-B1, DR-2), and the deferred-items list (CF-1 code fix, DR-3, AI-C3, Session B).

**Verification:** `pytest tests/` → 378 passed, 1 skipped (baseline 341 passed, 1 skipped — +37 new tests across Sessions A, C, E). `ruff check archolith_filter/<every touched source file>` → all checks passed. 68 pre-existing ruff errors in `archolith_filter/extractors/*.py` are NOT introduced by this work and are out of scope. `python -c "from archolith_filter import filter_output, redact_secrets, strip_thinking_blocks, compress_agent_solo_turn"` → imports OK. `python -c "FilterTelemetryEntry.__dataclass_params__.frozen == True"` → FC-C2 verified. `python -c "redact_secrets('x'*50001).redaction_count == 0"` → SEC-C1 size guard verified.

**Deferred to separate sessions:** Session B (cross-project token-count accuracy bundle, AI-A1 + AI-A2 + AI-A3 + AI-A4 + archolith-context CORR-07); `ARCHOLITH-FILTER-DISTRIBUTION-PLAN` (CF-1 code fix, DR-3); `archolith-filter-cross-turn-dedupe-plan` (AI-C3); test-coverage batch COV-01 / COV-02.

- - -

## Older Unreleased entries

- **Fix:** Payload-scoped keep-newest deduplication in `_apply_dedup()` (agent-solo Strategy B) and tail guard to prevent cross-request re-read doom loops. Previously, dedup state persisted across requests; identical content re-sent in request N+1 would be incorrectly marked as duplicate even though it was the only copy in that payload. The fix detects duplicates only within a single payload batch and keeps the NEWEST occurrence intact while marking earlier ones. Messages in the coherence tail are never replaced, preserving model context coherence. This eliminates the 37-call continuation loops observed when the proxy re-sent conversation history with stale dedup markers. (Fixes archolith-filter-cross-request-dedup-fix; 2026-06-10)

- **Feature:** Added optional `dedupe_tracker` parameter to `filter_output()` (Stage 7). When provided, the caller's tracker is used instead of the process-global singleton. Fresh trackers per request batch enable payload-replay semantics (no cross-request marking); persistent/shared trackers preserve live-stream semantics (genuine new outputs deduped across calls). Fully backward compatible — omit or pass None to use the existing process-global tracker.

- **Rename:** package `archolith_rtk` -> `archolith_filter`, distribution `archolith-rtk` -> `archolith-filter`, and the config env-var prefix `ARCHOLITH_RTK_FILTER_*` -> `ARCHOLITH_FILTER_*` (master switch `ARCHOLITH_RTK_FILTERS` -> `ARCHOLITH_FILTERS`). Aligns with the public brand name. RTK-concept identifiers (`BashRtkExtractor`, etc.) unchanged.

- **Layer 0 pre-filter pipeline**: wired `redact_secrets()`, `strip_thinking_blocks()`, and `normalize_paths()` into `filter_output()` with per-stage config gating (env vars `ARCHOLITH_FILTER_*_ENABLED`). Added binary detection (NUL-byte scan, early return), oversized input guard (>500KB head/tail preview, configurable via `ARCHOLITH_FILTER_OVERSIZED_MAX_CHARS`), runtime noise normalization in log/build/test filters (`normalize_runtime_noise()`), and table whitespace minimization in `fs_listing_filter()`. Each stage individually toggleable. Added 9 new config knobs and risk-level presets. (Closes `archolith-filter-layer0-hardening-plan.md`)
- Added format-switch compression for JSON output: CSV for tabular arrays (Strategy 1), column factoring for dominant values (Strategy 4), key-value lines for flat objects (Strategy 2), and dotted-key lines for nested objects (Strategy 3). Each strategy has safety checks that fall back to truncation when the format-switch output isn't shorter.
- Added stack trace frame collapsing (Strategy 5): detects Java, Python, Node, and Go stack traces in generic output, classifies framework vs application frames, and collapses framework frames into a summary line.
- Added git status prefix grouping (Strategy 6): groups short-format git status lines by directory and status code, producing more compact output when many files share the same directory.
- Added search heading reformat (Strategy 7): reformats inline-style grep matches (`path:line:content`) to heading style, stating the file path once with indented match lines below.
- Added build task summary (Strategy 8): for successful Gradle/Maven builds, detects task lines and emits a compact summary instead of the full task list, preserving warning lines.
- Added ls -la abbreviation (Strategy 9): parses `ls -la/l` column format and emits abbreviated output with just name, type hint, and human-readable size, stripping permissions/owner/group/timestamp.
- Added 17 new config knobs with env-var overrides and risk-level presets for all format-switch strategies.
- Added 29 new tests covering all 9 format-switch strategies plus edge cases.
- Added benchmark corpora and scenarios for all 9 format-switch strategies, with truncation-only baseline comparison verifying format-switch savings are materially better than truncation alone.
- Fixed `checks_passed` logic in practical benchmark to correctly handle scenarios where small corpora pass through unchanged at low/balanced risk.
- Fixed the truncation-only benchmark harness to disable all format-switch knobs, including stack-trace collapse, git-status grouping, build summaries, and `ls -la` abbreviation, so the baseline now measures a real truncation-only path.
- Added aggregate material-improvement gates to the practical benchmark report and JSON output, with the latest run showing `+1175` low-risk, `+1252` balanced, `+1296` high-risk, and `+3723` overall savings versus truncation-only.
- Fixed no-op `compress_agent_solo_turn()` behavior so unchanged turns preserve message identity and report `no_strategies_enabled`, clearing the previously failing full-suite pytest case.

- Added exact-match cross-turn output deduplication so repeated identical tool results collapse to a short recovery marker with a `raw_output_id`.
- Added declaration-aware Layer 2 `read_file` shrinking for char and token budgets, preserving signatures and structure when oversized file reads survive Layer 1.
- Hardened the practical benchmark harness to reset the dedupe tracker between measured filter runs so acceptance checks remain scenario-isolated.
- Added a deeper `read_file` Layer 1 filter that collapses generated/minified blocks, large literals, embedded JSON, and SVG-heavy fixture sections while preserving declarations and representative anchors.
- Extended `read_file` configuration, tests, and practical benchmark coverage to measure real code, CSS, and fixture-heavy file-content compression.
- Refocused `archolith-filter` on Layer 1 output filtering and Layer 2 message/tool-argument shrinking.
- Removed the former Layer 3 `ContextManager` surface so conversation-level context strategy lives in `archolith-context`.
- Reworked `git_diff_filter()` to keep structural diff headers while using much smaller per-file previews, materially improving token savings on large diffs.
- Fixed heading-mode search filtering and passthrough handling for `raw_output` / shell-routed tool classifications.
- Expanded filter and compatibility coverage to bring the documented RTK coverage gate back above 90%.
