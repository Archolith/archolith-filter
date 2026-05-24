"""JSON output filter — detects JSON output and compresses structured data."""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import FilterResult
from .generic import generic_filter


@dataclass(frozen=True)
class JsonFilterOptions:
    max_keys_per_object: int = 10
    max_array_items: int = 5
    max_depth: int = 3
    max_value_length: int = 80


DEFAULT_OPTS = JsonFilterOptions()


def _compress_value(value: object, depth: int, opts: JsonFilterOptions) -> str:
    """Compress a parsed JSON value recursively."""
    if value is None:
        return "null"

    if isinstance(value, str):
        if len(value) <= opts.max_value_length:
            return json.dumps(value)
        truncated = value[: opts.max_value_length]
        return f"{json.dumps(truncated)}... [{len(value)} chars]"

    if isinstance(value, (int, float, bool)):
        return json.dumps(value)

    if isinstance(value, list):
        if len(value) == 0:
            return "[]"
        if depth >= opts.max_depth:
            return f"[... {len(value)} items]"

        items = [_compress_value(item, depth + 1, opts) for item in value[: opts.max_array_items]]
        omitted = len(value) - opts.max_array_items
        if omitted > 0:
            items.append(f"... +{omitted} more items")

        indent = "  " * (depth + 1)
        inner = f",\n{indent}".join(items)
        close_brace = "  " * depth + "]"
        return f"[\n{indent}{inner}\n{close_brace}"

    if isinstance(value, dict):
        keys = list(value.keys())
        if len(keys) == 0:
            return "{}"
        if depth >= opts.max_depth:
            return f"{{... {len(keys)} keys}}"

        shown_keys = keys[: opts.max_keys_per_object]
        omitted_keys = len(keys) - opts.max_keys_per_object

        entries: list[str] = []
        for key in shown_keys:
            compressed_val = _compress_value(value[key], depth + 1, opts)
            entries.append(f"{'  ' * (depth + 1)}{json.dumps(key)}: {compressed_val}")

        if omitted_keys > 0:
            remaining = ", ".join(keys[opts.max_keys_per_object :])
            entries.append(f"{'  ' * (depth + 1)}... +{omitted_keys} more keys: [{remaining}]")

        close_brace = "  " * depth + "}"
        joined_entries = ",\n".join(entries)
        return f"{{\n{joined_entries}\n{close_brace}"

    return str(value)


def json_filter(formatted: str, opts: JsonFilterOptions | None = None) -> FilterResult:
    """Filter JSON output: compress structured data while preserving key names and structure."""
    if opts is None:
        opts = DEFAULT_OPTS

    raw_chars = len(formatted)
    if raw_chars == 0:
        return FilterResult(output="", raw_chars=0, filtered_chars=0, truncated=False)

    lines = formatted.split("\n")

    # Identify the tool header block (only match [exit...] or [killed...], not JSON array brackets).
    tool_header: list[str] = []
    header_end = 0
    for i, ln in enumerate(lines):
        if ln.startswith("$ ") or (ln.startswith("[") and (ln.startswith("[exit") or ln.startswith("[killed"))):
            header_end = i + 1
        elif ln == "":
            header_end = i + 1
        else:
            break
    tool_header = lines[:header_end]
    body = "\n".join(lines[header_end:])

    if body.strip() == "":
        return FilterResult(output=formatted, raw_chars=raw_chars, filtered_chars=raw_chars, truncated=False)

    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return generic_filter(formatted)

    compressed = _compress_value(parsed, 0, opts)
    result = "\n".join(tool_header + [compressed])

    truncated = len(result) < raw_chars
    return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=truncated)
