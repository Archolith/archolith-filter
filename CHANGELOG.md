# Changelog

## Unreleased

- Added a deeper `read_file` Layer 1 filter that collapses generated/minified blocks, large literals, embedded JSON, and SVG-heavy fixture sections while preserving declarations and representative anchors.
- Extended `read_file` configuration, tests, and practical benchmark coverage to measure real code, CSS, and fixture-heavy file-content compression.
- Refocused `archolith-rtk` on Layer 1 output filtering and Layer 2 message/tool-argument shrinking.
- Removed the former Layer 3 `ContextManager` surface so conversation-level context strategy lives in `archolith-context`.
- Reworked `git_diff_filter()` to keep structural diff headers while using much smaller per-file previews, materially improving token savings on large diffs.
- Fixed heading-mode search filtering and passthrough handling for `raw_output` / shell-routed tool classifications.
- Expanded filter and compatibility coverage to bring the documented RTK coverage gate back above 90%.
