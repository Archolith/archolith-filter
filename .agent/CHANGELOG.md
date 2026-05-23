# Changelog — archolith-rtk

## Unreleased

- Added missing public compatibility APIs: `shrink_messages()` for OpenAI-format message lists and `ContextManager.decide_after_turn(...)`.
- Fixed heading-mode search filtering and passthrough handling for `raw_output` / shell-routed tool classifications.
- Expanded filter and compatibility coverage to bring the documented RTK coverage gate back above 90%.

## 2026-05-23 — Agent scaffolding and docs population

- Added `.agent/` directory with full project documentation (README, architecture, data_models, code_conventions, CHANGELOG)
- Added LLM instruction files (CLAUDE.md, AGENTS.md, gemini.md, QWEN.md, .cursorrules, .windsurfrules, .clinerules, .github/copilot-instructions.md)
- Added `.githooks/pre-push` and configured `core.hooksPath`
- Populated all `.agent/` docs with real project content
