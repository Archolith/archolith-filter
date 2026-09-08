"""Remediation for the 2026-09-07 wrapup review findings.

P2 — F-06: top-level JSON arrays were returned unshrunk.
P3 — L3: newly accepted ANSI escape sequences had no focused regression.
"""

import json

from archolith_filter.shrink import shrink_json_long_strings
from archolith_filter.strip_ansi import strip_ansi

LONG = "x" * 1000


class TestJsonArrayShrinking:
    """F-06: arrays are shrunk, at top level and nested."""

    def test_top_level_array_of_strings_is_shrunk(self):
        result = shrink_json_long_strings(json.dumps([LONG, "short"]))
        parsed = json.loads(result)
        assert "shrunk" in parsed[0]
        assert parsed[1] == "short"

    def test_top_level_array_of_objects_is_shrunk(self):
        result = shrink_json_long_strings(json.dumps([{"content": LONG}, {"n": 1}]))
        parsed = json.loads(result)
        assert "shrunk" in parsed[0]["content"]
        assert parsed[1]["n"] == 1

    def test_array_shrink_reports_length_and_lines(self):
        payload = "a\nb\n" + ("y" * 900)
        result = shrink_json_long_strings(json.dumps([payload]))
        marker = json.loads(result)[0]
        assert f"{len(payload)} chars" in marker
        assert "2 lines" in marker

    def test_nested_array_inside_object_is_shrunk(self):
        result = shrink_json_long_strings(json.dumps({"items": [LONG]}))
        parsed = json.loads(result)
        assert "shrunk" in parsed["items"][0]

    def test_deeply_nested_string_is_shrunk(self):
        result = shrink_json_long_strings(json.dumps({"a": {"b": [{"c": LONG}]}}))
        parsed = json.loads(result)
        assert "shrunk" in parsed["a"]["b"][0]["c"]

    def test_short_array_values_unchanged(self):
        payload = [1, 2, "short", None, True]
        assert json.loads(shrink_json_long_strings(json.dumps(payload))) == payload

    def test_top_level_scalar_returned_untouched(self):
        # Replacing the whole payload with a marker would leave nothing usable.
        raw = json.dumps(LONG)
        assert shrink_json_long_strings(raw) == raw

    def test_invalid_json_still_returns_head_marker(self):
        assert "unparsed" in shrink_json_long_strings("[" + "x" * 500)

    def test_object_shrinking_still_works(self):
        parsed = json.loads(shrink_json_long_strings(json.dumps({"content": LONG})))
        assert "shrunk" in parsed["content"]


class TestNewAnsiEscapeCoverage:
    """L3: ESC ) * + designators and ESC 6/7/8/9 single-character controls."""

    def test_charset_designators_all_four_stripped(self):
        for opener in ("(", ")", "*", "+"):
            for final in ("B", "0", "U", "K"):
                seq = f"\x1b{opener}{final}"
                assert strip_ansi(f"a{seq}b") == "ab", seq

    def test_single_character_controls_stripped(self):
        for digit in ("6", "7", "8", "9"):
            assert strip_ansi(f"a\x1b{digit}b") == "ab", digit

    def test_previously_supported_controls_still_stripped(self):
        for ch in (">", "#", "="):
            assert strip_ansi(f"a\x1b{ch}b") == "ab", ch

    def test_csi_and_osc_still_stripped(self):
        assert strip_ansi("a\x1b[31mred\x1b[0mb") == "aredb"
        assert strip_ansi("a\x1b]0;title\x07b") == "ab"

    def test_mixed_sequence_fully_stripped(self):
        raw = "\x1b(Bstart\x1b)0mid\x1b7saved\x1b8restored\x1b[1mbold\x1b[0mend"
        assert strip_ansi(raw) == "startmidsavedrestoredboldend"

    def test_plain_text_untouched(self):
        assert strip_ansi("no escapes here 6 7 8 9 ( ) * +") == "no escapes here 6 7 8 9 ( ) * +"
