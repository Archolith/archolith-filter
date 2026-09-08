"""JSON arg shrinking — collapse long string values in tool_call arguments.

Import DAG: leaf — no internal dependencies.
"""

from __future__ import annotations

import json

_LONG_STRING_THRESHOLD = 300


def _shrink_value(value: object) -> object:
    """Recursively replace over-long strings with a marker, preserving structure."""
    if isinstance(value, str) and len(value) > _LONG_STRING_THRESHOLD:
        newline_count = value.count("\n")
        return (
            f"[…shrunk: {len(value)} chars, {newline_count} lines"
            f" — tool already responded, see result]"
        )
    if isinstance(value, dict):
        return {k: _shrink_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_shrink_value(item) for item in value]
    return value


def shrink_json_long_strings(json_str: str) -> str:
    """Shrink long string values in JSON arguments, keeping short keys/values verbatim.

    Objects and arrays are both shrunk, at any depth. Descending is what makes
    array support useful at all — the long strings in an array of objects live
    one level down — and once a dict inside an array is descended into, treating
    a top-level dict differently would be arbitrary.

    A top-level scalar is returned untouched: replacing the entire argument
    payload with a marker would leave the caller nothing to act on.
    """
    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        head = json_str[:200]
        return f"{head}…[shrunk: {len(json_str)} chars, unparsed]"

    if not isinstance(parsed, (dict, list)):
        return json_str

    return json.dumps(_shrink_value(parsed))
