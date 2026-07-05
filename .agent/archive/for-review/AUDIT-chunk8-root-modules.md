# AUDIT: Chunk 8 — archolith_filter Root Modules

**Date**: 2026-06-07
**Auditor**: GLM-5.1 (manual — 3 harness sessions failed)
**Scope**: `archolith_filter/` root-level modules (14 files)
**Prior Audits**: 3 adversarial reviews (context quality remediation, RTK quality remediation, two-pass vs two-curator)
**Architecture Ref**: `archolith-filter/.agent/architecture.md`

---

## Files Audited

| File | Lines | Role |
|------|-------|------|
| `__init__.py` | 536 | Public API, `filter_output()` pipeline, binary detection, oversized guard, category dispatch |
| `_patterns.py` | 65 | SSOT for shared regex (verbose flags, import/comment/declaration detection) |
| `agent_solo.py` | 586 | Agent-solo turn compression (4 strategies: shrink/dedup/filter-middle/compact-args) |
| `classifier.py` | 188 | Shell command → 13-category classifier |
| `config.py` | 502 | `FilterConfig` dataclass + env-var loading + risk-level presets |
| `dedupe.py` | 61 | Cross-turn SHA-256 dedup tracker |
| `filter_meta.py` | 35 | Exit code / timeout parsing |
| `normalize.py` | 78 | Runtime noise normalization (timestamps, PIDs, memory sizes) |
| `paths.py` | 196 | Workspace path normalization (env var / git walk / inference) |
| `raw_store.py` | 120 | LRU raw output recovery store |
| `redact.py` | 98 | Secret redaction (27 regex patterns → single alternation) |
| `strip_ansi.py` | 28 | ANSI escape sequence stripping |
| `strip_thinking.py` | 57 | Model-internal reasoning block stripping |
| `telemetry.py` | 224 | Filter telemetry accumulator (heuristic + tiktoken token counting) |

**Total**: ~2,694 lines

---

## Findings

### HIGH

#### H1: `redact.py` — Connection-string regex matches beyond credentials into URL paths
**File**: `redact.py:73`
**Category**: Correctness
**Detail**: Pattern `(?:mongodb|postgres|postgresql|mysql|redis)://[^\s\"'\)]+` matches the full URL including database names, query params, and path segments. A URL like `postgresql://user:pass@host:5432/production_db?sslmode=require` is fully replaced with `[REDACTED]`, losing the database name and query params that are not secrets. The intent is to redact embedded credentials, but the regex has no sub-group extraction — it nukes the entire URL.
**Prior Status**: NEW — not flagged in prior audits.
**Impact**: Loss of diagnostic context (database name, SSL mode, host) in filtered output when connection strings appear in logs or error messages.
**Fix**: Capture credential portion only: `(?<=://)[^\s@]+@[^\s\"'\)]+` for user:pass@host, or use a sub-group to replace only the credential segment while preserving the path.

#### H2: `agent_solo.py:578–583` — Skipped-reason logic contradicts actual behavior
**File**: `agent_solo.py:578–583`
**Category**: Correctness
**Detail**: After all four strategies run, the code checks `not shrink_enabled and not dedup_enabled and not filter_middle_enabled and stats.chars_saved_compact == 0` to set `skipped_reason = "no_strategies_enabled"`. But `compact_tool_args_enabled` defaults to `True` and is not checked in this condition. When `compact_tool_args_enabled=True` but compact saved 0 chars (no eligible tool calls), and the other three are disabled, the function returns `skipped_reason="no_strategies_enabled"` even though compact DID run. This is a misleading skip reason that could confuse telemetry consumers.
**Prior Status**: NEW
**Impact**: Telemetry misreporting — operators think no strategies ran when compact ran but found nothing to compact.
**Fix**: Check `compact_tool_args_enabled` in the condition, or set skipped_reason only when `strategies_applied` is empty.

#### H3: `paths.py:56–76` — `_find_workspace_root()` git walk uses `os.path.isdir()` on every call at module level
**File**: `paths.py:56–76`
**Category**: Performance
**Detail**: `_find_workspace_root()` walks up from CWD up to 20 levels, calling `os.path.isdir()` on each candidate `.git` directory. This runs on the first call to `get_path_config()`, which happens on every `filter_output()` invocation when `normalize_paths_enabled=True` and no cached config exists. The result is cached, but in environments where `reset_path_config()` is called (tests), or where the module is reloaded, this filesystem walk repeats. In containerized or network-mounted environments, `isdir()` can be slow.
**Prior Status**: NEW
**Impact**: Startup latency spike (20 `isdir` calls in worst case). Not a runtime concern after caching.
**Fix**: Add a `ARCHOLITH_RTK_WORKSPACE_ROOT` env var to all deployment configs so the git walk is skipped. Log a warning when the fallback path is used.

---

### MEDIUM

#### M1: `redact.py:69` — JWT regex can match non-JWT base64url strings
**File**: `redact.py:69`
**Category**: Security
**Detail**: `eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+` matches any three base64url segments where the first two start with `eyJ` (base64 for `{"`). This is correct for JWTs but also matches JWE (JSON Web Encryption) tokens and any base64url-encoded JSON that happens to use dot separators. Over-redaction in these cases is safe from a security standpoint but can cause false positives that strip non-sensitive data.
**Prior Status**: Known tradeoff — accepted by design.
**Impact**: Low — false positives in filtered output for rare base64url content.
**Fix**: No action needed. Document the tradeoff.

#### M2: `normalize.py:42–43` — Elapsed-seconds regex matches bare numbers in code
**File**: `normalize.py:43`
**Category**: Correctness
**Detail**: `\b\d+(?:\.\d+)?\s*s\b` matches `1.5s` but also matches variable names like `args`, types like `String`, and code identifiers ending in `s`. The word boundary `\b` only checks the left side. Example: `timeout=30s` is correctly normalized, but `class FooBars` would incorrectly match `Bars` as `[X]s` if preceded by a digit. The ms regex has the same issue but is less prone to false positives since `ms` is less common as a suffix.
**Prior Status**: Noted in docstring scoping ("only call from log/build/test filters").
**Impact**: Depends on caller discipline. If `normalize_runtime_noise()` is called on source code, it will corrupt identifiers.
**Fix**: Strengthen regex with lookbehind: `(?<=\d)\s*s\b` or `(?<=[0-9])\s*s\b` to require the `s` be preceded by a digit. The existing scoping rule is a soft constraint.

#### M3: `strip_thinking.py:56` — Redundant conditional in strip/strip chain
**File**: `strip_thinking.py:56`
**Category**: Maintainability
**Detail**: `result = result.strip() if result.strip() else result` — calls `.strip()` twice. If `result.strip()` is truthy, strips again. If falsy (all whitespace), returns the unstripped original. The intent is to avoid returning an empty string when the input was all whitespace, but the double-strip is wasteful. Should be `stripped = result.strip(); result = stripped if stripped else result`.
**Prior Status**: NEW
**Impact**: Negligible performance (double strip on small strings). Readability concern.
**Fix**: `stripped = result.strip(); return stripped if stripped else result`

#### M4: `telemetry.py:54–56` — O(1) eviction using `pop(0)` on list
**File**: `telemetry.py:54–56`
**Category**: Performance
**Detail**: `self._entries.pop(0)` on a Python `list` is O(n) because it shifts all subsequent elements. With `max_entries=10_000` and frequent calls, this causes periodic linear-time pauses. The dedupe tracker (dedupe.py:38) uses a dict with FIFO eviction which is also suboptimal but on a smaller scale.
**Prior Status**: NEW
**Impact**: With default `max_entries=10_000`, every eviction shifts up to 10K pointers. Noticeable under high-frequency tool call loads.
**Fix**: Use `collections.deque(maxlen=10_000)` which auto-evicts from the left in O(1), or use an `OrderedDict` and `popitem(last=False)`.

#### M5: `paths.py:92–100` — `_infer_project_roots()` does two-level `os.listdir()` at module load
**File**: `paths.py:92–100`
**Category**: Performance
**Detail**: Walks `projects/<org>/<project>` structure by listing all org dirs then all project dirs. For large monorepos with many orgs/projects, this can list hundreds of directories at config creation time. Combined with H3's git walk, the total startup cost for path config can be significant.
**Prior Status**: NEW
**Impact**: Startup latency. Not a per-call concern (cached).
**Fix**: Cache the result with a file-based fingerprint (e.g., mtime of `projects/` dir) to skip re-scanning on reload.

#### M6: `classifier.py` — `cargo` appears in both `_TEST_BINS` and `_BUILD_BINS`
**File**: `classifier.py:45,49`
**Category**: Correctness
**Detail**: `cargo` is in both `_TEST_BINS` and `_BUILD_BINS`. The classification functions `_is_test_command` and `_is_build_command` both check for `cargo` with different subcommand matching (`" test" in command` vs `" build" in command or " check" in command`). The dispatch order in `classify_command()` checks test before build, so `cargo test` correctly maps to TEST. But `cargo` alone (no subcommand) would match `_is_test_command` first (returns `True` on line 120 since `base in _TEST_BINS` and `base != "cargo"` path is skipped — wait, no: line 112-113 checks `if base == "cargo": return " test" in command`, which would return False, and then line 120 `return True` is NOT reached because the `if` chain returns. So `cargo` alone returns `False` from `_is_test_command`. Then `_is_build_command` line 128 checks `if base == "cargo": return " build" in command or " check" in command`, which also returns False. So `cargo` with no subcommand falls through to GENERIC. This is correct but confusing — the dual membership creates cognitive overhead.
**Prior Status**: NEW
**Impact**: No functional bug, but maintenance risk. Future changes to the early-return logic could accidentally classify `cargo` incorrectly.
**Fix**: Remove `cargo` from `_TEST_BINS` and `_BUILD_BINS`; handle it as a special case in `classify_command()` directly with explicit subcommand routing.

#### M7: `config.py` — `from_env()` calls `base_config_for_risk_level()` then reconstructs entire FilterConfig
**File**: `config.py:258–456`
**Category**: Maintainability
**Detail**: `from_env()` first builds a base config via `base_config_for_risk_level()`, then constructs a completely new `FilterConfig` with every field individually wrapped in `_env_int()`. This means every config field appears 3 times: once as a default in the dataclass, once in the risk-level overrides dict, and once in `from_env()`. Adding a new field requires editing all three locations, violating DRY. The `_LOW_RISK_OVERRIDES` and `_HIGH_RISK_OVERRIDES` dicts are also untyped — a typo in a key name silently fails.
**Prior Status**: Known design debt — acknowledged in prior review.
**Impact**: New config fields require 3 edits. Untyped override dicts are error-prone.
**Fix**: Generate `from_env()` from the dataclass field list using introspection, or use a declarative schema that maps field names to env var names and bounds.

---

### LOW

#### L1: `dedupe.py:37–38` — FIFO eviction uses `next(iter(self._seen))` which is insertion-order dependent
**File**: `dedupe.py:37–38`
**Category**: Maintainability
**Detail**: Relies on CPython 3.7+ dict insertion order for FIFO eviction. Semantically correct but fragile if the code is ever ported or the dict is replaced.
**Prior Status**: Known — accepted for CPython target.
**Fix**: Document the CPython dependency or use `OrderedDict`.

#### L2: `raw_store.py:53–56` — Eviction sorts all keys on every store
**File**: `raw_store.py:53–56`
**Category**: Performance
**Detail**: `keys = sorted(self._entries.keys())` sorts all keys to find the oldest. With 200 entries this is trivial, but it's called on every `store()` when at capacity.
**Prior Status**: NEW
**Impact**: Negligible at default `max_entries=200`.
**Fix**: Use `OrderedDict` or maintain a separate `collections.deque` of key order.

#### L3: `strip_ansi.py:16` — `_ESC_MISC_RE` handles limited set of ESC sequences
**File**: `strip_ansi.py:16`
**Category**: Correctness
**Detail**: Only handles `ESC (`, `ESC >`, `ESC #`, `ESC =`, `ESC \`. Does not handle `ESC )` (character set designation), `ESC 6`/`ESC 7` (cursor save/restore), or `ESC 8` (cursor restore). Rare in tool output but possible.
**Prior Status**: NEW
**Impact**: Stray escape characters in filtered output for uncommon terminal sequences.
**Fix**: Extend regex to cover `ESC [0-9]` patterns.

#### L4: `filter_meta.py:8` — `is_verbose_command` re-exported from `_patterns` but also re-exported from `config.py`
**File**: `filter_meta.py:8`, `config.py:9`
**Category**: Maintainability
**Detail**: Both `filter_meta.py` and `config.py` re-export `is_verbose_command` from `_patterns.py`. The `__init__.py` imports it from `config` (line 26). Callers may import from either, causing confusion about the canonical source.
**Prior Status**: Identified in chunk 6 (shadow pattern finding).
**Fix**: Single re-export point: `__init__.py` should import from `_patterns.py` directly, and `config.py`/`filter_meta.py` should not re-export.

#### L5: `agent_solo.py:259` — Deferred import of `filter_output` inside `_filter_middle_messages`
**File**: `agent_solo.py:259`
**Category**: Maintainability
**Detail**: `from . import filter_output` is a deferred import to avoid circular dependencies. This works but adds import-time overhead on every call to `_filter_middle_messages`. If `agent_solo.py` is imported before `__init__.py` is fully loaded, this can also cause partial-import issues.
**Prior Status**: Known — necessary for circular import avoidance.
**Fix**: Accept the tradeoff. Document why the deferred import exists.

#### L6: `__init__.py:134–157` — `_is_binary_output()` scans char-by-char for NUL bytes
**File**: `__init__.py:134–157`
**Category**: Performance
**Detail**: The NUL-byte scan iterates character-by-character up to 64K chars. Using `text.find('\x00')` or `text.count('\x00')` would be faster (C-level implementation).
**Prior Status**: NEW
**Impact**: Minor — CPython's `str.find()` is O(n) in C, much faster than Python-level char iteration.
**Fix**: Replace the for-loop with `nul_count = text[:_BINARY_SCAN_BYTES].count('\x00')`.

#### L7: `telemetry.py:198–207` — `record_filter_telemetry_with_tokens()` re-creates tiktoken encoding on every call
**File**: `telemetry.py:198–207`
**Category**: Performance
**Detail**: `tiktoken.get_encoding("cl100k_base")` is called on every invocation. The tiktoken library caches encodings internally, so this is not a major concern, but the `try/except ImportError` on every call adds overhead.
**Prior Status**: NEW
**Impact**: Negligible (tiktoken caches internally). Exception-check overhead per call.
**Fix**: Cache the encoding at module level: `_ENC = tiktoken.get_encoding("cl100k_base")` on first successful import.

#### L8: `normalize.py:72–73` — ms→s ordering comment says "ms before s to avoid partial match" but the concern is about subsumption
**File**: `normalize.py:72–73`
**Category**: Maintainability
**Detail**: The comment says "ms before s to avoid partial match on '1.5ms'" but the actual concern is that the `s` regex would match the trailing `s` in `1.5ms`. Since the ms regex already consumed `1.5ms`, the s regex won't see it. The comment is misleading about why the order matters.
**Prior Status**: NEW
**Impact**: Documentation clarity only.
**Fix**: Clarify comment: "ms before s to avoid the s regex matching the trailing 's' in '1.5ms' after the ms regex already consumed it."

#### L9: `paths.py:33–43` — Path regex can match URLs with path components
**File**: `paths.py:33–43`
**Category**: Correctness
**Detail**: The `_FILE_PATH_RE` regex matches POSIX absolute paths starting with `/`, which also matches URL paths like `https://example.com/path`. The regex requires `(?<!\w)/` to avoid matching the `//` in `https://`, but `https:/path` (single slash) would match. In practice, URLs in tool output usually have `://` which the regex avoids, but edge cases exist.
**Prior Status**: NEW
**Impact**: False positive path normalization on malformed URLs. Rare in practice.
**Fix**: Add negative lookbehind for `:`` — `(?<![:/])/` instead of `(?<!\w)/`.

---

## Summary

| Severity | Count | Files |
|----------|-------|-------|
| Critical | 0 | — |
| High | 3 | `redact.py`, `agent_solo.py`, `paths.py` |
| Medium | 7 | `redact.py`, `normalize.py`, `strip_thinking.py`, `telemetry.py`, `paths.py`, `classifier.py`, `config.py` |
| Low | 9 | `dedupe.py`, `raw_store.py`, `strip_ansi.py`, `filter_meta.py`, `agent_solo.py`, `__init__.py`, `telemetry.py`, `normalize.py`, `paths.py` |
| **Total** | **19** | |

### Resolved from Prior Audits
- K1 (verbose command detection duplication): RESOLVED — `_patterns.py` now centralizes `is_verbose_command()` and `VERBOSE_FLAG_PATTERNS`. Both `config.py` and `filter_meta.py` re-export from `_patterns`.

### Cross-Chunk Integration Concerns
- **redact.py ↔ archolith-context proxy**: The proxy sends user API keys in bearer headers (Chunk 5 H2). The redaction module strips keys from tool output but NOT from HTTP headers the proxy itself sends. These are orthogonal systems — redaction only sees tool output text.
- **agent_solo.py ↔ archolith-context proxy**: Strategy D (compact tool args) assumes the proxy has a file cache so the model can "use Read to retrieve" compacted content. If the proxy's file cache is misconfigured or evicted, the model loses access to the original file content. This is a cross-boundary contract that needs documentation.
- **paths.py ↔ workspace root**: `ARCHOLITH_RTK_WORKSPACE_ROOT` env var is the primary root detection mechanism. If the proxy and filter disagree on workspace root, path normalization will produce inconsistent results across the pipeline. Single env var shared by both processes mitigates this.

### Positive Observations
- **_patterns.py** is genuinely the SSOT for shared regex — chunk 6's shadow pattern findings have been partially addressed
- **redact.py** compiles all 27 patterns into a single alternation regex at module load — O(1) per-call, excellent design
- **dedupe.py** uses SHA-256 for content hashing — no collision risk in practice
- **Fail-open design** across the pipeline — any exception in filter_output returns the unfiltered text. This is correct for a token-reduction tool.
- **agent_solo.py** four-strategy composition is clean and well-documented
- **config.py** risk-level presets with env-var overrides and clamped bounds is thorough
