"""JSON arg shrinking — collapse long string values in tool_call arguments.

Import DAG: leaf — no internal dependencies.
"""

from __future__ import annotations

import json

_LONG_STRING_THRESHOLD = 300


def shrink_json_long_strings(json_str: str) -> str:
    """Shrink long string values in a JSON object, keeping short keys/values verbatim."""
    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        head = json_str[:200]
        return f"{head}…[shrunk: {len(json_str)} chars, unparsed]"

    if not isinstance(parsed, dict) or isinstance(parsed, list):
        return json_str

    output: dict[str, object] = {}
    for k, v in parsed.items():
        if isinstance(v, str) and len(v) > _LONG_STRING_THRESHOLD:
            newline_count = v.count("\n")
            output[k] = (
                f"[…shrunk: {len(v)} chars, {newline_count} lines"
                f" — tool already responded, see result]"
            )
        else:
            output[k] = v
    return json.dumps(output)
