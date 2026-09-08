"""Wave 4 of archolith-filter-post-launch-remediation-plan.md — robustness/coupling."""

from archolith_filter.shrink import (
    ChatMessage,
    ToolCall,
    ToolCallFunction,
    shrink_oversized_tool_call_args_by_tokens,
)


class TestMarkerConstantsShared:
    """F-12 (c7): the extractor reads the filter's marker constants, not copies."""

    def test_extractor_annotations_track_filter_markers(self):
        from archolith_filter.filters.read_file import MARKER_IMPORT

        content = "\n".join(f"import module_{i}" for i in range(20)) + "\ncode()\n"
        from archolith_filter.extractors.read_file import ReadFileFilterExtractor

        annotations = ReadFileFilterExtractor()._detect_annotations(content)
        assert "import-heavy" in annotations
        # The annotation is driven by the shared constant, not a retyped phrase.
        assert MARKER_IMPORT == "import lines omitted"

    def test_filter_emits_the_shared_marker(self):
        from archolith_filter.filters.read_file import (
            MARKER_IMPORT,
            ReadFileFilterOptions,
            read_file_filter,
        )

        content = "\n".join(f"import module_{i}" for i in range(20)) + "\ncode()\n"
        out = read_file_filter(content, ReadFileFilterOptions(import_collapse=True)).output
        assert MARKER_IMPORT in out


class TestToolCallRebuildPreservesFields:
    """F-15 (c7): rebuilding a message must not drop tool_call_id or name."""

    def test_fields_survive_tool_call_arg_shrink(self):
        big_args = '{"payload": "' + ("x" * 4000) + '"}'
        msg = ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(
                id="call_1",
                type="function",
                function=ToolCallFunction(id="call_1", name="write_file", arguments=big_args),
            )],
            tool_call_id="tc_42",
            name="write_file",
        )

        result = shrink_oversized_tool_call_args_by_tokens([msg], 50)
        out = result.messages[0]

        assert out.tool_calls is not None
        assert len(out.tool_calls[0].function.arguments) < len(big_args)
        assert out.tool_call_id == "tc_42"
        assert out.name == "write_file"
