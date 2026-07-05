# Audit Report: archolith_filter/filters/

**Auditor**: z-ai/glm-5.1 (opencode)  
**Date**: 2026-06-07  
**Scope**: All 14 Python files in `archolith_filter/filters/` + `_patterns.py`, `normalize.py`  
**Tests**: 335 passed, 1 skipped (baseline verified)

---

## Summary

The `filters/` package implements 13 L1 category filters atop a shared `FilterResult` dataclass and a `generic_filter` head+tail baseline. Overall code quality is **good**: frozen dataclasses, compiled regex at module level, clean separation of concerns, and a working format-switch cascade in `json_output.py`. No security vulnerabilities or AI anti-patterns detected.

Key concerns cluster around **regex consolidation drift** (3 comment/import regexes that shadow `_patterns.py`), **format-switch fallback chain fragility** in `json_output.py` and `build_output.py`, and a few **correctness edge cases** around boundary indices and duplicate header extraction.

**Severity breakdown**: 0 Critical, 3 High, 8 Medium, 9 Low

---

## Findings

### H-1: `_is_import_line` / `_is_comment_line` shadow `_patterns.py` — consolidation drift

**File**: `filters/read_file.py:54-69`  
**Severity**: High  
**Category**: Maintainability / SSOT violation

`read_file.py` imports `is_import_line` and `is_comment_line` from `_patterns.py` (line 16-18), then wraps them in private `_is_import_line()` and `_is_comment_line()` that simply delegate. However, it also defines a local `_LINE_COMMENT_RE` (line 38) that matches `//` and `#` comments — a subset of `_patterns.COMMENT_LINE_RE` which also matches `/*`, `* `, `*/`. The local `_is_line_comment()` (line 73) uses this local regex, while `_is_comment_line()` (line 67) delegates to the shared version. This creates a confusing two-tier comment detection where:

1. The shared `is_comment_line` detects `/*`, `* `, `*/` block-comment lines
2. The local `_is_line_comment` detects `//` and `#` only
3. `_collapse_comment_block` (line 179) uses BOTH — `_is_block_comment_start/end` for block comments and `_is_line_comment` for consecutive line comments

The drift risk: if `_patterns.COMMENT_LINE_RE` is updated (e.g., adding HTML `<!--` comments), `read_file.py` won't pick up the change for line-comment collapsing, because it uses its own `_LINE_COMMENT_RE`.

**Recommendation**: Merge `_LINE_COMMENT_RE` into `_patterns.py` as `LINE_COMMENT_RE` (or add a `is_line_comment()` helper). Remove the local regex. Keep `_is_block_comment_start/end` local since they're structural (start/end markers), not pattern-matching.

---

### H-2: `_extract_header` duplicated in `logs.py` as `_extract_job_header` with divergent logic

**File**: `filters/logs.py:67-75`  
**Severity**: High  
**Category**: Maintainability / consolidation drift

`logs.py` defines `_extract_job_header()` which is almost identical to `generic._extract_header()` but differs:

| Feature | `_extract_header` (generic) | `_extract_job_header` (logs) |
|---|---|---|
| `$ ` prefix | Yes | Yes |
| `[exit`/`[killed`/`[job` prefixes | Yes (via `_TOOL_HEADER_PREFIXES`) | Partial (`[job` only) |
| Blank line after header | Yes | No |
| `[killed` detection | Yes | No |

This means `logs.py` will NOT correctly extract `[killed after timeout]` or `[exit N]` headers — they'll be treated as body. The divergent behavior is a bug for log output that starts with `[exit 0]`.

**Recommendation**: Replace `_extract_job_header` with `generic._extract_header`. The `[job` prefix is already in `_TOOL_HEADER_PREFIXES`.

---

### H-3: `json_output.py` fallback chain computes `_compress_value` even when format-switch wins

**File**: `filters/json_output.py:449-467`  
**Severity**: High  
**Category**: Performance

When a format-switch strategy produces a result (CSV, KV, or dotted-key), the code at line 450 computes `_compress_value(parsed, 0, opts)` purely to compare lengths and decide whether to use the format-switch output or the recursive compression. For large JSON objects, `_compress_value` recursively walks the entire tree — this is wasted work when the format-switch result is already shorter (which it usually is for tabular data).

**Recommendation**: Add a fast size estimate (e.g., `len(json.dumps(parsed, separators=(',', ':')))` as a lower bound comparison before calling `_compress_value`. If the format-switch result is already shorter than the minified JSON, skip the recursive call.

---

### M-1: `_collapse_blank_lines` duplicated across `generic.py` and `read_file.py`

**File**: `filters/generic.py:260-270`, `filters/read_file.py:360-374`  
**Severity**: Medium  
**Category**: Maintainability / DRY

Both files implement blank-line collapsing with slightly different semantics:
- `generic._collapse_blank_lines`: collapses runs of 2+ blank → 1 blank
- `read_file._collapse_blank_lines`: collapses to a configurable `max_blank` count

The `read_file` version is strictly more general. The `generic` version is a special case (`max_blank=1`).

**Recommendation**: Move the configurable version to `_patterns.py` (or a shared `utils` module) and have both files import it.

---

### M-2: `git_status.py:110-112` grouping length comparison uses body chars, not formatted chars

**File**: `filters/git_status.py:110-112`  
**Severity**: Medium  
**Category**: Correctness

The grouping-shortening check compares `grouped_len` (sum of line lengths in the grouped output) against `original_len` (sum of line lengths in the original body). But `original_len` counts body line lengths, not including newlines, while `grouped_text` (the joined string) does include newlines between lines. This makes the comparison slightly asymmetrical. More importantly, the header is re-extracted at line 113 with a redundant `_extract_header(lines)[0]` call, which is wasteful since `_extract_header` was already called at line 95 (but the header was discarded with `_`).

**Recommendation**: Capture the header at line 95 instead of discarding it. Fix the length comparison to compare both as joined strings or both as char sums without newlines.

---

### M-3: `fs_listing.py:231` redefines `non_blank` after it was already defined at line 210

**File**: `filters/fs_listing.py:210,231`  
**Severity**: Medium  
**Category**: Correctness / code smell

`non_blank` is computed at line 210 for the ls-abbreviate branch, then recomputed identically at line 231 for the important-entry branch. If execution reaches line 231, the ls-abbreviate branch was skipped (ls_parseable_count < 60%), so the `non_blank` at line 210 is from a different scope that was never reached. Python doesn't scope block-locals, so line 231 would actually use the variable from line 210 if that branch executed — but since the two branches are mutually exclusive (line 211 returns if the condition is true), this is functionally correct but confusing.

**Recommendation**: Move the `non_blank` computation at line 231 before the if-block, or compute it once at the top of the function.

---

### M-4: `_find_bracket_close` in `read_file.py:257-273` doesn't handle strings or comments

**File**: `filters/read_file.py:257-273`  
**Severity**: Medium  
**Category**: Correctness edge case

The bracket-matching function counts `{`/`}` and `[`/`]` depth by scanning every character. It does not account for brackets inside string literals or comments. For example:

```python
data = {"key": "value with {brace}"}
```

The `{` inside the string would be counted as opening a new nesting level, causing the close to be found too late or not at all. This is a known limitation for structure-aware compression, but it can produce incorrect collapsing for files with string-embedded brackets.

**Recommendation**: Document this as a known limitation. For a future improvement, add string-literal awareness (track quote state).

---

### M-5: `build_output.py` `_BUILD_FAILURE_RE` matches `error:` too broadly

**File**: `filters/build_output.py:38-39`  
**Severity**: Medium  
**Category**: Correctness

`_BUILD_FAILURE_RE` includes `error:` as a pattern. But many successful builds emit `error:` in non-fatal contexts (deprecation warnings with "error code", lint advisories, etc.). The check at line 120 also verifies `_BUILD_SUCCESS_RE` is absent, which mitigates this — but if a build outputs both "BUILD SUCCESSFUL" and a line with "error:", the success check wins, which is correct. The risk is the inverse: a build with a non-fatal "error:" line and no explicit "BUILD SUCCESSFUL" marker gets treated as a failure and falls through to generic, which is overly conservative but not lossy.

**Recommendation**: Tighten `error:` to `\berror:` and consider adding a negative lookahead for known non-fatal patterns (e.g., `warning:` followed by `error:`).

---

### M-6: `search.py` `_HEADING_PATH_RE` can match inline path lines

**File**: `filters/search.py:39`  
**Severity**: Medium  
**Category**: Correctness

`_HEADING_PATH_RE = re.compile(r"^[^\s:][^\s]*[^\s:](?::?$)")` matches any non-whitespace string that optionally ends with `:`. This can match inline `path:line:content` lines if the content after the line number happens to be empty. The secondary check `_is_heading_path_line` (line 51-58) mitigates this by checking that the next non-blank line starts with a line number, but the regex itself is over-broad.

**Recommendation**: Tighten the regex to require the line to NOT match `_INLINE_PATH_RE` first (already done in `_is_heading_path_line` at line 54, but the initial scan at line 181-185 doesn't apply this filter).

---

### M-7: `json_output.py:324-326` `omitted_keys_suffix` is a trivial identity function

**File**: `filters/json_output.py:324-326`  
**Severity**: Medium  
**Category**: AI anti-pattern / dead code

`omitted_keys_suffix(count)` just returns `str(count)`. The docstring says "grammatically correct suffix" suggesting it was intended to handle pluralization (e.g., "1 key" vs "5 keys"), but it was never implemented. The call site at line 317 uses it as: `f"... +{omitted_keys_suffix(omitted)} more keys"`, which always produces "... +5 more keys" — grammatically correct for plural but wrong for singular ("... +1 more keys" should be "... +1 more key").

**Recommendation**: Either implement proper singular/plural handling or remove the function and inline `str(count)`, adding a conditional for "key" vs "keys".

---

### M-8: `_collapse_stack_frames` in `generic.py` double-classifies every frame

**File**: `filters/generic.py:148-168`  
**Severity**: Medium  
**Category**: Performance

Each frame line is first classified in `_detect_stack_trace` (to find runs), then re-classified in `_collapse_stack_frames` (to decide which to keep). The classification logic runs 4 regex matches per line, twice. For a stack trace with 100 frames, that's 800 regex matches where 400 would suffice.

**Recommendation**: Have `_detect_stack_trace` return the classification alongside the run info, or cache classification results.

---

### L-1: `_patterns.py` `COMMENT_LINE_RE` matches `* ` (asterisk-space) which can match bullet lists

**File**: `_patterns.py:40`  
**Severity**: Low  
**Category**: Correctness edge case

`COMMENT_LINE_RE = re.compile(r"^\s*(?:#\s|//\s?|/\*|\*\s|\*/)")` matches lines starting with `* ` (asterisk-space). In Markdown or plain text, `* item` is a bullet list, not a comment. When `read_file.py` uses `is_comment_line()` via `_is_comment_line()`, it will incorrectly identify Markdown bullet lines as comments and potentially collapse them.

**Recommendation**: Restrict `\*\s` to only match when preceded by a `/*` block comment start. Alternatively, track block-comment state rather than relying on line-level heuristics.

---

### L-2: `read_file.py:297` potential index-out-of-range in `_collapse_literal_block`

**File**: `filters/read_file.py:297`  
**Severity**: Low  
**Category**: Correctness edge case

`close_line = lines[end_idx - 1] if end_idx <= len(lines) else close_char` — the condition should be `end_idx - 1 < len(lines)` (i.e., `end_idx <= len(lines)` is correct for accessing `lines[end_idx - 1]`). But when `_find_bracket_close` returns `len(lines)` (bracket never closed), `end_idx - 1 = len(lines) - 1`, which is valid. The `else close_char` branch would only trigger if `end_idx > len(lines)`, which `_find_bracket_close` can return as `idx` at line 273 after the while loop. This is technically safe but the intent is unclear.

**Recommendation**: Add a comment clarifying the boundary, or use `end_idx - 1 < len(lines)` for clarity.

---

### L-3: `read_file.py:327` same boundary pattern in `_collapse_multiline_string`

**File**: `filters/read_file.py:327`  
**Severity**: Low  
**Category**: Correctness edge case (same pattern as L-2)

`close_line = lines[idx - 1] if idx <= len(lines) else delim` — if the multiline string is never closed, `idx` can be `len(lines)`, making `lines[idx-1]` the last line (which is fine). The `else delim` branch handles `idx > len(lines)`, which shouldn't happen given the loop logic but is defensive.

---

### L-4: `build_output.py:106-111` header extraction differs from `generic._extract_header`

**File**: `filters/build_output.py:106-111`  
**Severity**: Low  
**Category**: Maintainability / consolidation drift

`build_output.py` implements its own header extraction inline instead of using `_extract_header`. The logic is similar but not identical — it checks `ln.startswith("[")` and then `ln.startswith("[exit")` or `ln.startswith("[killed")`, while `_extract_header` checks `_TOOL_HEADER_PREFIXES` which also includes `[job`.

**Recommendation**: Use `_extract_header` from `generic.py` (already imported via `generic_filter`).

---

### L-5: `json_output.py:411` header detection logic reimplements `_extract_header`

**File**: `filters/json_output.py:408-417`  
**Severity**: Low  
**Category**: Maintainability / consolidation drift

`json_output.py` implements its own header extraction at lines 408-417 instead of using `_extract_header`. The comment explains why (to avoid matching JSON `[` as a header), and the logic explicitly checks `ln.startswith("[exit")` or `ln.startswith("[killed")` rather than the broader `_TOOL_HEADER_PREFIXES`. This is intentional and correct, but it's a third variant of header extraction.

**Recommendation**: Add a parameter to `_extract_header` to control whether `[`-prefixed lines are treated as headers, or document why JSON needs special handling.

---

### L-6: `generic.py:121` type:ignore comment for arg-type

**File**: `filters/generic.py:121`  
**Severity**: Low  
**Category**: Type safety

`runs.append((current_start, len(lines), current_lang)) # type: ignore[arg-type]` — `len(lines)` returns `int`, which should be a valid `end_idx`. The `arg-type` ignore suggests the tuple type doesn't match. This is likely because `current_start` is `int | None` at this point, but the `if current_start is not None` check on line 120 should narrow it. The type checker may not be able to prove this.

**Recommendation**: Add an explicit `assert current_start is not None` before the append to satisfy the type checker without the ignore comment.

---

### L-7: `fs_listing.py:28-50` `_IMPORTANT_PATTERNS` could use a single combined regex

**File**: `filters/fs_listing.py:28-50`  
**Severity**: Low  
**Category**: Performance

22 compiled regex patterns are checked individually in `_is_important_entry`. For each entry, all 22 patterns are tested until one matches. A single combined regex with alternation would be faster.

**Recommendation**: Combine into `re.compile(r"^(?:package\.json|tsconfig\.json|...)$", re.IGNORECASE)`.

---

### L-8: `logs.py:22-35` same pattern — `_IMPORTANT_PATTERNS` uses 12 individual regexes

**File**: `filters/logs.py:22-35`  
**Severity**: Low  
**Category**: Performance (same as L-7)

12 individual regex patterns checked sequentially in `_extract_important_lines`.

---

### L-9: No `__all__` exports in filter modules

**File**: All filter modules  
**Severity**: Low  
**Category**: Maintainability

None of the filter modules define `__all__`, making their public API implicit. The main entry points (e.g., `git_diff_filter`, `json_filter`) are clearly the public functions, but the Options dataclasses and helper functions are also importable.

**Recommendation**: Add `__all__` to each module listing the filter function and Options class.

---

## Import DAG

```
_patterns.py (leaf — no internal deps)
    ↑
normalize.py (leaf — no internal deps)
    ↑
filters/__init__.py (FilterResult dataclass — leaf)
    ↑
filters/generic.py (imports: FilterResult)
    ├── _extract_header (used by 6 filters)
    ├── _collapse_blank_lines (used internally)
    ├── _collapse_stack_frames (used internally)
    └── generic_filter (used by 8 filters as fallback)
    ↑
filters/build_output.py → generic, normalize
filters/fs_listing.py → generic
filters/git_diff.py → generic
filters/git_log.py → generic
filters/git_show.py → generic, git_diff
filters/git_status.py → generic
filters/json_output.py → generic
filters/lint_output.py → generic
filters/logs.py → normalize (NO generic._extract_header — uses own _extract_job_header)
filters/read_file.py → _patterns (is_import_line, is_comment_line)
filters/search.py → generic
filters/test_run_output.py → generic, normalize
filters/typecheck_output.py → generic
```

**Cycle risk**: None detected. DAG is clean with `generic.py` as the clear hub.

**Coupling hotspots**:
- `generic.py` imported by 10 of 14 filter modules
- `_extract_header` imported by 6 modules (but reimplemented by 2)
- `_patterns.py` imported by only 2 modules (`filters/read_file.py`, `shrink/read_file_truncate.py`) — underutilized given the regex drift

---

## Metrics

| Module | Lines | Regexes | Functions | Imports | Cyclomatic (est.) |
|---|---|---|---|---|---|
| `__init__.py` | 15 | 0 | 0 | 1 | 0 |
| `generic.py` | 318 | 4 | 9 | 1 | ~25 |
| `read_file.py` | 502 | 11 | 21 | 2 | ~35 |
| `json_output.py` | 474 | 0 (uses `json` stdlib) | 14 | 3 | ~30 |
| `fs_listing.py` | 277 | 25 | 6 | 2 | ~15 |
| `search.py` | 255 | 3 | 7 | 2 | ~18 |
| `build_output.py` | 157 | 5 | 3 | 3 | ~8 |
| `git_status.py` | 127 | 1 | 3 | 3 | ~8 |
| `logs.py` | 116 | 12 | 4 | 2 | ~6 |
| `git_diff.py` | 167 | 0 | 4 | 2 | ~8 |
| `git_show.py` | 64 | 0 | 1 | 3 | ~4 |
| `git_log.py` | 56 | 1 | 1 | 2 | ~3 |
| `lint_output.py` | 31 | 0 | 1 | 2 | ~1 |
| `typecheck_output.py` | 31 | 0 | 1 | 2 | ~1 |
| `test_run_output.py` | 35 | 0 | 1 | 3 | ~1 |
| **Total** | **2,625** | **61** | **75** | — | — |

---

## Recommendations (prioritized)

1. **[High] Fix `_extract_job_header` in `logs.py`** — replace with `generic._extract_header` to fix `[exit`/`[killed` header detection (H-2)
2. **[High] Consolidate comment/import regexes** — move `_LINE_COMMENT_RE` to `_patterns.py`, remove shadowing wrappers in `read_file.py` (H-1)
3. **[High] Optimize JSON fallback chain** — add fast size estimate before calling `_compress_value` (H-3)
4. **[Medium] Unify blank-line collapsing** — move configurable version to shared module (M-1)
5. **[Medium] Fix `git_status.py` header capture** — don't discard header from `_extract_header` (M-2)
6. **[Medium] Fix `omitted_keys_suffix`** — implement or remove the dead function (M-7)
7. **[Medium] Optimize stack frame classification** — avoid double-classification (M-8)
8. **[Low] Consolidate header extraction** — 3 variants exist (`generic._extract_header`, `build_output` inline, `json_output` inline); add parameter or document divergence (L-4, L-5)
9. **[Low] Combine `_IMPORTANT_PATTERNS`** — single alternation regex in `fs_listing.py` and `logs.py` (L-7, L-8)
10. **[Low] Add `__all__`** to all filter modules (L-9)
