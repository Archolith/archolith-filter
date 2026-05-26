# Changelog

## Unreleased

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
