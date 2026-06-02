# Changelog

## Unreleased

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

- Added exact-match cross-turn output deduplication so repeated identical tool results collapse to a short recovery marker with a `raw_output_id`.
- Added declaration-aware Layer 2 `read_file` shrinking for char and token budgets, preserving signatures and structure when oversized file reads survive Layer 1.
- Hardened the practical benchmark harness to reset the dedupe tracker between measured filter runs so acceptance checks remain scenario-isolated.
- Added a deeper `read_file` Layer 1 filter that collapses generated/minified blocks, large literals, embedded JSON, and SVG-heavy fixture sections while preserving declarations and representative anchors.
- Extended `read_file` configuration, tests, and practical benchmark coverage to measure real code, CSS, and fixture-heavy file-content compression.
- Refocused `archolith-rtk` on Layer 1 output filtering and Layer 2 message/tool-argument shrinking.
- Removed the former Layer 3 `ContextManager` surface so conversation-level context strategy lives in `archolith-context`.
- Reworked `git_diff_filter()` to keep structural diff headers while using much smaller per-file previews, materially improving token savings on large diffs.
- Fixed heading-mode search filtering and passthrough handling for `raw_output` / shell-routed tool classifications.
- Expanded filter and compatibility coverage to bring the documented RTK coverage gate back above 90%.
