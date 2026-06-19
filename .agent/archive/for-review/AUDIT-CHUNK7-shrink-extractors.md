# Audit Report — Chunk 7: shrink/ and extractors/ Subsystems

**Auditor:** opencode (z-ai/glm-5.1)  
**Date:** 2026-06-07  
**Scope:** `archolith_filter/shrink/` (6 modules), `archolith_filter/extractors/` (5 modules), `archolith_filter/_patterns.py`  
**Test status:** 67/67 PASS (1 skip) — `tests/test_shrink.py`, `tests/test_extractors/`  

---

## 1. Import DAG

### shrink/ (leaf → root, no cycles)

```
models.py         → (stdlib only)           LEAF
token_counter.py  → (stdlib only)           LEAF
json_shrink.py    → (stdlib only)           LEAF
truncate.py       → token_counter           ─┐
read_file_truncate.py → truncate, token_counter, _patterns  ─┐
orchestrator.py   → models, token_counter, truncate, read_file_truncate, json_shrink  ROOT
__init__.py       → all above (re-exports)
```

**Cycle check: NO CYCLES DETECTED.** The DAG is clean and matches the documented order in `__init__.py:11-12` and `orchestrator.py:11`. The `models → token_counter → truncate/read_file_truncate/json_shrink → orchestrator` chain is a strict DAG with no back-edges.

### extractors/

```
_stubs.py         → (stdlib only)           LEAF
base.py           → _stubs (fallback) or archolith_proxy.extractor.base  LEAF
bash.py           → base, classifier, strip_ansi
read_file.py      → base, filters/read_file (lazy import inside method)
__init__.py       → bash, read_file (re-exports)
```

**Cycle check: NO CYCLES DETECTED.** The lazy import in `read_file.py:72` avoids a load-time cycle with `filters/read_file.py`.

### _patterns.py

```
_patterns.py      → (re, stdlib only)        LEAF — self-contained
```

Consumed by: `shrink/read_file_truncate.py`, `filters/read_file.py`, `config.py`, `filter_meta.py`. No back-imports from consumers.

---

## 2. Findings

### F-01: `truncate_for_tokens` early-return shortcut can skip tokenization for short-but-token-dense text

**File:** `shrink/truncate.py:48-53`  
**Severity:** Medium  
**Category:** Correctness — boundary error

```python
if len(text) <= max_tokens:
    return text
```

The comment says "Every token is ≥1 char — if length ≤ budget, tokens ≤ budget." This is correct for the trivial case, but the *next* check at line 51-53 also has a subtle issue:

```python
if len(text) <= max_tokens * _CHARS_PER_TOKEN_ESTIMATE:
    if count_tokens(text) <= max_tokens:
        return text
```

The early return at line 48-49 is safe. The estimate guard at line 51 is also safe. **No actual bug here** — the logic is correct. However, there's an asymmetry: the `truncate_for_chars` function has no such short-circuit guard at line 48 (`len(text) <= max_tokens`) because `max_tokens` is a token budget, not a char budget. This is fine but could confuse future readers. **Not actionable.**

**Status:** NOT A BUG — informational. Logic is correct.

---

### F-02: `count_tokens("")` returns 1 under char-heuristic fallback, but 0 under tiktoken

**File:** `shrink/token_counter.py:41`  
**Severity:** Low  
**Category:** Correctness — token counting accuracy

```python
return max(1, len(text) // 4)
```

For empty string `""`: `len("") // 4 == 0`, `max(1, 0) == 1`. But tiktoken would return 0 tokens for `""`. The test at `test_shrink.py:35` acknowledges this with `assert n >= 0` but the inconsistency means token budgeting with the heuristic fallback will over-count by 1 token for empty strings. In practice, empty-content messages are short-circuited before tokenization, so this is cosmetic.

**Status:** Low — cosmetic. Won't affect real token budgets.

---

### F-03: `truncate_read_file_for_tokens` — double token-counting on candidate pass

**File:** `shrink/read_file_truncate.py:214`  
**Severity:** Medium  
**Category:** Performance — redundant counting

```python
candidate = "\n".join(result_lines)
if count_tokens(candidate) <= max_tokens:
    return candidate
```

This tokenizes the entire collapsed candidate to see if it fits. If it doesn't, the code then tokenizes *each declaration line individually* at line 222-233 (`sum(count_tokens(line) for line in decl_lines)`). For a large file, the candidate tokenization + per-line tokenization = nearly 2× the cost. The candidate check is necessary, but the per-line sum is redundant if the candidate already exceeded budget — at that point you know you're in the "subset declarations" path and could skip the per-line sum and just iterate greedily.

**Impact:** On very large files (>10K lines) with tiktoken loaded, this causes ~2× tokenization cost in the worst case. With char-heuristic fallback, the cost is negligible.

**Status:** Medium — real but bounded. Only affects the hot path when both (a) the collapsed candidate still exceeds budget AND (b) tiktoken is available.

---

### F-04: Massive code duplication between `truncate_read_file_for_chars` and `truncate_read_file_for_tokens`

**File:** `shrink/read_file_truncate.py:28-144` vs `147-271`  
**Severity:** High  
**Category:** Maintainability — DRY violation

The import-collapse + comment-collapse loop (lines 33-88 and 156-211) are **byte-for-byte identical** logic duplicated between the char and token variants. The only difference is the budget enforcement at the end (char comparison vs `count_tokens` comparison). If a bug is fixed in one, it must be manually replicated in the other.

**Status:** High — will cause drift. Refactor: extract a shared `_collapse_imports_and_comments(lines) -> list[str]` helper.

---

### F-05: `truncate_read_file_for_tokens` tail-budget loop only pops head, never tail

**File:** `shrink/read_file_truncate.py:260-267`  
**Severity:** Medium  
**Category:** Correctness — truncation corruption risk

```python
while head_decl and count_tokens(result) > max_tokens:
    head_decl.pop()
    ...
```

This loop only removes from `head_decl` to bring the result under budget. It never removes from `tail_decl`. If `tail_decl` alone exceeds the budget (unlikely but possible with long declaration lines), this loop will pop all `head_decl` entries, fail, and fall through to `truncate_for_tokens` at line 270. The fallback is safe, but the loop could be more efficient by also trimming from the tail.

**Impact:** Low in practice — tail budget is capped at `_TAIL_MAX_TOKENS` (256), so tail is unlikely to exceed budget alone. The fallback prevents data corruption.

**Status:** Medium — safe fallback prevents corruption, but the loop logic is asymmetric and could confuse readers.

---

### F-06: `shrink_json_long_strings` only handles `dict`, not `list` at top level

**File:** `shrink/json_shrink.py:21`  
**Severity:** Low  
**Category:** Correctness — incomplete coverage

```python
if not isinstance(parsed, dict) or isinstance(parsed, list):
    return json_str
```

The condition is wrong: `isinstance(parsed, list)` is always False when `parsed` is a `dict` (the `or` never triggers for dict). But the intent seems to be: "if not a dict OR if a list, return unchanged." For a `list` input, `not isinstance(parsed, dict)` is True, so it returns unchanged — which is correct. But the `isinstance(parsed, list)` clause is dead code because the `not isinstance(parsed, dict)` already covers the list case. This is not a bug, but the condition reads oddly.

More importantly: JSON arrays with long string elements are not shrunk. If a tool call passes `["very long string 1", "very long string 2", ...]`, the function returns it unchanged. This is a coverage gap.

**Status:** Low — arrays are rare as tool-call args. The dead-code clause should be cleaned up.

---

### F-07: `_patterns.py` — `DECLARATION_RE` has no ReDoS risk but has a false-positive pattern

**File:** `_patterns.py:57-64`  
**Severity:** Low  
**Category:** Correctness — false positive

```python
r"(?:(?:public|private|protected|static|final|abstract|override)\s+)+\w+\s*[\(<]"
```

This matches `public static void main(` — good. But it also matches `public static myField =` (no `(` or `<`) — wait, no, it requires `[\(<]` so it needs `(` or `<`. Actually `public myField = value` won't match because `=` is not in `[\(<]`. This is fine.

However, the `@\\w+` alternative (line 62) matches decorator lines like `@property` — but it also matches `@dataclass(frozen=True)` only the `@dataclass` part. This means decorator-only lines (with no function on the same line) are treated as declarations and preserved during truncation. This is actually desired behavior for Python.

**Status:** Low — no ReDoS risk, no false-positive corruption. Decorator handling is correct.

---

### F-08: ReDoS audit — all regex patterns are safe

**Files:** `_patterns.py`, `shrink/truncate.py`, `shrink/read_file_truncate.py`, `extractors/bash.py`, `filters/read_file.py`  
**Severity:** N/A (clean)  
**Category:** Security

All compiled regex patterns were reviewed for catastrophic backtracking:

| Pattern | File | Risk |
|---------|------|------|
| `VERBOSE_FLAG_PATTERNS` (7 patterns) | `_patterns.py:17-26` | Safe — anchored, no quantified alternation |
| `IMPORT_RE`, `FROM_IMPORT_RE` | `_patterns.py:38-39` | Safe — anchored, linear |
| `COMMENT_LINE_RE` | `_patterns.py:40` | Safe — anchored, no nested quantifiers |
| `DECLARATION_RE` | `_patterns.py:57-64` | Safe — anchored, alternation is flat |
| `_PASSED_RE`, `_FAILED_RE`, etc. | `extractors/bash.py:25-34` | Safe — simple `(\d+)` captures |
| `_GIT_STATUS_MODIFIED_RE` | `extractors/bash.py:30` | Safe — `re.MULTILINE` anchored |
| `_GIT_DIFF_FILE_RE` | `extractors/bash.py:31` | Safe — anchored alternation |
| `_GIT_LOG_RE` | `extractors/bash.py:32` | Safe — `[0-9a-f]{7,}` is fixed-width |
| `_ERROR_RE` | `extractors/bash.py:34` | Safe — `.{0,120}` is bounded |
| `_CSS_RULE_RE`, `_COMPOUND_LITERAL_RE`, etc. | `filters/read_file.py:36-51` | Safe — anchored or bounded |

**No ReDoS vectors found.** All patterns use anchored starts (`^`), fixed-width quantifiers, or bounded ranges.

---

### F-09: `token_counter.py` — global mutable `_count_tokens_fn` is not thread-safe

**File:** `shrink/token_counter.py:10-29`  
**Severity:** Medium  
**Category:** Correctness — thread safety

```python
_count_tokens_fn = None

def _get_token_counter():
    global _count_tokens_fn
    if _count_tokens_fn is not None:
        return _count_tokens_fn
    ...
    _count_tokens_fn = _count
    return _count_tokens_fn
```

In a multi-threaded environment, two threads could race: both see `_count_tokens_fn is None`, both load tiktoken, both assign. The worst case is double tiktoken initialization (wastes ~50ms). No corruption because the final value is idempotent (same function). Python's GIL makes the actual race window tiny.

**Status:** Medium — harmless in practice due to GIL, but technically not thread-safe.

---

### F-10: `extractors/bash.py` — `_ERROR_RE` captures only first 120 chars of error messages

**File:** `extractors/bash.py:34`  
**Severity:** Low  
**Category:** Correctness — data loss

```python
_ERROR_RE = re.compile(r"(?:error|Error|ERROR):?\s+(.{0,120})")
```

`.{0,120}` is greedy by default, so it captures up to 120 chars of the first error line. Multi-line error messages are truncated. This is intentional (bounded capture) but means stack traces are cut short.

**Status:** Low — intentional truncation for fact size control.

---

### F-11: `extractors/read_file.py:72` — lazy import inside method call is fragile

**File:** `extractors/read_file.py:70-72`  
**Severity:** Low  
**Category:** Maintainability

```python
def _detect_annotations(self, content: str) -> list[str]:
    from archolith_filter.filters.read_file import ReadFileFilterOptions, read_file_filter
```

The lazy import avoids a load-time dependency cycle but means: (1) ImportError at runtime if `filters/read_file.py` is broken, (2) repeated import overhead on every call (mitigated by Python's import cache). This is an acceptable pattern but should be documented.

**Status:** Low — acceptable pattern, but worth a comment explaining *why* it's lazy.

---

### F-12: `extractors/read_file.py` — annotation detection depends on English marker strings

**File:** `extractors/read_file.py:89-98`  
**Severity:** Medium  
**Category:** Correctness — fragile coupling

```python
if "import lines omitted" in filtered:
    annotations.append("import-heavy")
if "generated lines omitted" in filtered or "minified lines omitted" in filtered:
    annotations.append("generated file, collapsed")
```

The extractor checks for substring markers that the `read_file_filter` function embeds in its output. If `filters/read_file.py` changes its marker strings (e.g., `"import lines omitted"` → `"import lines hidden"`), this detector silently breaks — it will stop annotating. This is a fragile string-based contract between two modules.

**Status:** Medium — should use shared constants or a structured result (e.g., a set of flags on `FilterResult`) instead of string matching.

---

### F-13: `truncate_for_chars` output can exceed `max_chars` by marker overhead

**File:** `shrink/truncate.py:24-37`  
**Severity:** Low  
**Category:** Correctness — budget overrun

```python
marker = f"\n\n[…truncated {dropped} chars — ...]\n\n"
return f"{head}{marker}{tail}"
```

The marker itself is ~80-100 chars and is not subtracted from the budget. `head_budget = max(0, max_chars - tail_budget)` allocates head+tail but the marker is free-floating. The total output can be `head_budget + tail_budget + len(marker)` which exceeds `max_chars` by ~80-100 chars. The `truncate_for_tokens` function accounts for this with `_MARKER_TOKEN_OVERHEAD = 48` but the char variant does not.

**Status:** Low — char budgets are typically generous (1000+), so ~80 chars of overrun is noise. But it violates the function's contract ("truncate text to max_chars").

---

### F-14: `shrink_oversized_tool_results_by_tokens` double-counts tokens for read_file messages

**File:** `shrink/orchestrator.py:98-106`  
**Severity:** Medium  
**Category:** Performance — redundant counting

```python
before_tokens = count_tokens(content)     # 1st count
...
truncated = truncate_read_file_for_tokens(content, max_tokens)  # counts internally
after_tokens = count_tokens(truncated)    # 2nd count
```

For `read_file` messages, `count_tokens(content)` is called at line 98, and then `truncate_read_file_for_tokens` internally calls `count_tokens` multiple times (candidate check, per-declaration, convergence). Then `count_tokens(truncated)` is called again. For a non-read_file message using `truncate_for_tokens`, the same pattern applies. In total, the original text is tokenized at least 2× (once for the budget check, once inside the truncate function).

**Status:** Medium — the `before_tokens` count is needed for `tokens_saved` accounting. Could be avoided by having the truncate functions return the before-count, but that changes the API. Acceptable for now.

---

### F-15: `shrink_messages` loses `tool_calls` when rebuilding assistant messages

**File:** `shrink/orchestrator.py:176-180`  
**Severity:** Low  
**Category:** Correctness — potential data loss (not triggered in current code path)

```python
out.append(ChatMessage(
    role=msg.role,
    content=msg.content,
    tool_calls=new_calls,
))
```

When `shrink_oversized_tool_call_args_by_tokens` rebuilds a message, it preserves `content` and `tool_calls` but drops `tool_call_id` and `name` fields. If the original `ChatMessage` had these fields set, they're silently lost. In the OpenAI format, assistant messages don't typically have `tool_call_id`/`name`, so this is not a live bug. But if the dataclass is used more broadly, this is a silent data-loss trap.

**Status:** Low — not a live bug for OpenAI-format messages. Should copy all fields explicitly.

---

## 3. AI Anti-Pattern Scan

| Pattern | Status |
|---------|--------|
| God file/class | PASS — largest file is `read_file_truncate.py` (271 lines), `orchestrator.py` (245 lines). Reasonable. |
| Over-abstracted | PASS — `RtkExtractorBase` is a marker class with no methods. Appropriate. |
| Premature optimization | PASS — `_CONVERGENCE_ITERS = 6` is a bounded iteration limit. Good. |
| Magic numbers | MINOR — `_LONG_STRING_THRESHOLD = 300`, `_TAIL_FRACTION = 0.1`, `_TAIL_MAX_CHARS = 1024` are module-level constants. Good. But `_READ_FILE_DECL_PRESERVE_FRACTION = 0.6` and `_READ_FILE_MIN_TAIL_CHARS = 256` in `read_file_truncate.py` could use doc comments. |
| Over-commenting | PASS — comments are purposeful, not AI-generated filler. |
| Sycophantic naming | PASS — no "smart", "intelligent", "advanced" naming. |
| Boilerplate patterns | PASS — no unnecessary ABCs, no pointless `__slots__`. |

**Summary:** Code is clean of AI anti-patterns. No slop detected.

---

## 4. _patterns.py Self-Containment Check

`_patterns.py` imports only `re` (stdlib). It exports:
- `VERBOSE_FLAG_PATTERNS` (list of compiled patterns)
- `is_verbose_command()` 
- `IMPORT_RE`, `FROM_IMPORT_RE`, `COMMENT_LINE_RE` (compiled patterns)
- `is_import_line()`, `is_comment_line()`
- `DECLARATION_RE` (compiled pattern)

**Self-containment: CONFIRMED.** No internal dependencies. All consumers import from `_patterns` without circularity.

---

## 5. Test Coverage Assessment

| Module | Test File | Coverage Assessment |
|--------|-----------|-------------------|
| `shrink/models.py` | `test_shrink.py::TestChatMessage` | Good — roundtrip tested |
| `shrink/token_counter.py` | `test_shrink.py::TestCountTokens` | Minimal — no test for heuristic fallback path |
| `shrink/truncate.py` | `test_shrink.py::TestTruncateForChars/ForTokens` | Good — boundary cases tested |
| `shrink/read_file_truncate.py` | `test_shrink.py::TestTruncateReadFileForChars/ForTokens` | Good — import/comment/declaration paths tested |
| `shrink/json_shrink.py` | `test_shrink.py::TestShrinkJsonLongStrings` | Good — covers valid/invalid/non-object JSON |
| `shrink/orchestrator.py` | `test_shrink.py` (multiple classes) | Good — all public functions tested |
| `extractors/bash.py` | `test_bash_rtk_extractor.py` | Good — covers all category routes |
| `extractors/read_file.py` | `test_read_file_rtk_extractor.py` | Good — covers annotations and edge cases |
| `extractors/base.py` | `test_stubs.py` (skipped) | Minimal — stubs test requires archolith-context |
| `extractors/_stubs.py` | (indirect) | No direct test — used via base.py fallback |

**Gaps:**
1. No test for `count_tokens` with tiktoken unavailable (heuristic fallback)
2. No test for `truncate_for_tokens` with CJK/multibyte text (char heuristic under-counts)
3. No test for `truncate_read_file_for_tokens` where `tail_decl` alone exceeds budget
4. No test for `shrink_json_long_strings` with JSON array at top level
5. No test for thread-safety of `_get_token_counter()`

---

## 6. Prior Audit Status

No prior chunk-7 specific audit was found. The codebase has a clean test baseline (67/67 pass).

---

## 7. Summary Table

| ID | Severity | Category | File:Line | Description |
|----|----------|----------|-----------|-------------|
| F-04 | **High** | Maintainability (DRY) | `read_file_truncate.py:33-88,156-211` | Identical import/comment collapse loop duplicated between char and token variants |
| F-03 | Medium | Performance | `read_file_truncate.py:214,222` | Double tokenization: candidate check + per-declaration sum |
| F-05 | Medium | Correctness | `read_file_truncate.py:260-267` | Token-budget loop only trims head, never tail; safe fallback prevents corruption |
| F-09 | Medium | Thread safety | `token_counter.py:10-29` | Global `_count_tokens_fn` not thread-safe (harmless under GIL) |
| F-12 | Medium | Maintainability | `extractors/read_file.py:89-98` | Annotation detection coupled to English marker strings — fragile |
| F-14 | Medium | Performance | `orchestrator.py:98-106` | Double tokenization in token-based shrink path |
| F-13 | Low | Correctness | `truncate.py:24-37` | Char truncation output can exceed max_chars by ~marker length |
| F-02 | Low | Correctness | `token_counter.py:41` | `count_tokens("")` returns 1 (heuristic) vs 0 (tiktoken) |
| F-06 | Low | Correctness | `json_shrink.py:21` | Dead code clause; JSON arrays not shrunk |
| F-10 | Low | Correctness | `extractors/bash.py:34` | Error message capture bounded to 120 chars |
| F-11 | Low | Maintainability | `extractors/read_file.py:70-72` | Lazy import fragile if dependency broken |
| F-15 | Low | Correctness | `orchestrator.py:176-180` | `tool_call_id`/`name` dropped when rebuilding assistant messages |
| F-08 | N/A | Security | All | **No ReDoS vectors found** — all patterns safe |
| F-01 | N/A | Correctness | `truncate.py:48-53` | Informational — early-return logic is correct |

**Critical findings: 0**  
**High findings: 1** (F-04 — code duplication, maintenance risk)  
**Medium findings: 5**  
**Low findings: 7**  
**Clean: ReDoS (0 vectors), import DAG (0 cycles), AI anti-patterns (0)**
