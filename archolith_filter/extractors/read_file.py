"""ReadFileFilterExtractor — Filter-enhanced Read file extractor.

Uses archolith-filter's ``read_file_filter()`` to detect structural
characteristics (import-heavy, generated, CSS) and surfaces them as
richer facts than the built-in ReadExtractor's line count.
"""

from __future__ import annotations

import httpx

from archolith_filter.extractors.base import (
    FilterExtractorBase,
    PartialExtractionResult,
    ToolCallRecord,
)


def _extract_path(args: dict) -> str:
    return (
        args.get("file_path") or args.get("path")
        or args.get("filePath") or args.get("filename")
        or args.get("target_file") or ""
    )


class ReadFileFilterExtractor(FilterExtractorBase):
    """Read extractor that uses archolith-filter's read_file_filter for structural characterisation.

    When the filter detects import-heavy content, generated files, or CSS
    rules, the fact includes that annotation. Normal files get a plain
    provenance fact.
    """

    tool_names = ("Read",)
    may_use_llm = False

    async def extract(
        self,
        record: ToolCallRecord,
        http_client: httpx.AsyncClient,
        turn_number: int,
        session_goal: str | None,
    ) -> PartialExtractionResult:
        path = _extract_path(record.args)
        if not path:
            first_line = record.result.splitlines()[0] if record.result else ""
            path = first_line.strip() or "unknown"

        annotations = self._detect_annotations(record.result)
        line_count = record.result.count("\n") + 1 if record.result.strip() else 0

        if annotations:
            ann_str = ", ".join(annotations)
            fact_content = f"[Read] {path} read at turn {turn_number} ({line_count} lines) — {ann_str}"
        else:
            fact_content = f"[Read] {path} read at turn {turn_number}"

        return PartialExtractionResult(
            source_tool="Read",
            facts=[{
                "content": fact_content,
                "fact_type": "file_state",
                "confidence": 1.0,
            }],
            files_touched=[path] if path and path != "unknown" else [],
            used_llm=False,
        )

    def _detect_annotations(self, content: str) -> list[str]:
        """Run archolith-filter's read_file_filter to detect structural characteristics."""
        from archolith_filter.filters.read_file import ReadFileFilterOptions, read_file_filter

        if not content.strip():
            return []

        opts = ReadFileFilterOptions(
            import_collapse=True,
            generated_min_line_len=500,
            generated_min_run=5,
            css_rule_collapse=True,
        )

        result = read_file_filter(content, opts)

        annotations: list[str] = []

        # If the filter compressed the output, examine the markers it left
        filtered = result.output

        if "import lines omitted" in filtered:
            annotations.append("import-heavy")
        if "generated lines omitted" in filtered or "minified lines omitted" in filtered:
            annotations.append("generated file, collapsed")
        if "CSS body lines omitted" in filtered:
            annotations.append("stylesheet")
        if "comment lines omitted" in filtered:
            annotations.append("comment-heavy")

        return annotations


# Backward compat: deprecated alias for ReadFileFilterExtractor
ReadFileRtkExtractor = ReadFileFilterExtractor
