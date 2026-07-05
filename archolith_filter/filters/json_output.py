"""JSON output filter — detects JSON output and compresses structured data.

Implements format-switch compression strategies:
- Strategy 1: JSON array of uniform objects → CSV
- Strategy 2: Flat JSON object → key-value lines
- Strategy 3: Nested JSON object → dotted-key lines
- Strategy 4: CSV column factoring (dominant value extraction)
Falls back to recursive truncation when no format switch applies.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from . import FilterResult
from .generic import generic_filter

# ─── Options ───


@dataclass(frozen=True)
class JsonFilterOptions:
    max_keys_per_object: int = 10
    max_array_items: int = 5
    max_depth: int = 3
    max_value_length: int = 80
    # Strategy 1: CSV
    csv_enabled: bool = True
    csv_min_rows: int = 3
    csv_max_rows: int = 20
    csv_max_key_length: int = 40
    # Strategy 2: Key-value lines
    kv_enabled: bool = True
    kv_min_keys: int = 3
    kv_max_keys: int = 20
    # Strategy 3: Dotted-key lines
    dotkey_enabled: bool = True
    dotkey_max_keys: int = 30
    dotkey_max_depth: int = 3
    # Strategy 4: CSV column factoring
    csv_factor_enabled: bool = True
    csv_factor_threshold: float = 0.8
    csv_factor_max_columns: int = 3


DEFAULT_OPTS = JsonFilterOptions()


# ─── Strategy 1: Tabular check ───


def _is_tabular_array(data: list[object], min_rows: int = 3) -> bool:
    """Check if a JSON list is tabular (uniform list of dicts with flat values).

    Conditions:
    1. Top-level is a list
    2. At least min_rows items
    3. Every item is a dict
    4. >=60% of unique keys appear in >=80% of items
    5. No nested dicts or lists as values
    """
    if not isinstance(data, list):
        return False
    if len(data) < min_rows:
        return False
    if not all(isinstance(item, dict) for item in data):
        return False

    # Check for nested values (no dicts or lists as values)
    for item in data:
        for value in item.values():
            if isinstance(value, (dict, list)):
                return False

    # Check key overlap: >=60% of unique keys appear in >=80% of items
    all_keys: set[str] = set()
    for item in data:
        all_keys.update(item.keys())

    if not all_keys:
        return False

    common_keys = 0
    for key in all_keys:
        count = sum(1 for item in data if key in item)
        if count / len(data) >= 0.8:
            common_keys += 1

    return common_keys / len(all_keys) >= 0.6


# ─── Strategy 1: CSV serialization ───


def _csv_escape(value: str) -> str:
    """Escape a value for CSV output per RFC 4180."""
    if "," in value or '"' in value or "\n" in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def _value_to_csv_str(value: object) -> str:
    """Convert a JSON value to its CSV string representation."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


def _serialize_csv(
    data: list[dict[str, object]],
    opts: JsonFilterOptions,
) -> str:
    """Serialize a tabular JSON array to CSV string."""
    # Collect all keys in order of first appearance
    seen_keys: list[str] = []
    key_set: set[str] = set()
    for item in data:
        for key in item:
            if key not in key_set:
                seen_keys.append(key)
                key_set.add(key)

    # Truncate column names if needed
    headers: list[str] = []
    for key in seen_keys:
        if len(key) > opts.csv_max_key_length:
            headers.append(key[: opts.csv_max_key_length])
        else:
            headers.append(key)

    # Strategy 4: Column factoring — find dominant values
    # A factored column is removed from the table entirely if ALL rows
    # match the default. If any row has a non-default value, the column
    # stays in the table but rows matching the default have empty cells.
    factored: dict[str, str] = {}
    factored_all_default: dict[str, bool] = {}  # True if every row matches default
    if opts.csv_factor_enabled:
        for key in seen_keys:
            values = [_value_to_csv_str(item.get(key)) for item in data if key in item]
            if not values:
                continue
            counter = Counter(values)
            dominant_value, dominant_count = counter.most_common(1)[0]
            if dominant_count / len(data) >= opts.csv_factor_threshold and len(factored) < opts.csv_factor_max_columns:
                factored[key] = dominant_value
                # Check if ALL rows have the default value
                all_default = all(_value_to_csv_str(item.get(key)) == dominant_value for item in data)
                factored_all_default[key] = all_default

    # Build header row — exclude factored columns that have 100% default
    # Include factored columns where some rows have non-default values
    display_keys = [k for k in seen_keys if k not in factored or not factored_all_default.get(k, False)]
    display_headers = [headers[seen_keys.index(k)] for k in display_keys]

    # Build rows
    rows: list[list[str]] = []
    for item in data[: opts.csv_max_rows]:
        row: list[str] = []
        for key in display_keys:
            if key in item:
                val = _value_to_csv_str(item[key])
                if key in factored and val == factored[key]:
                    # Row matches the factored default → empty cell
                    row.append("")
                else:
                    row.append(_csv_escape(_value_to_csv_str(item[key])))
            else:
                row.append("")  # missing key → empty field
        rows.append(row)

    # Build output
    lines: list[str] = []

    # Factored lines first
    for key, value in factored.items():
        key_display = key[: opts.csv_max_key_length] if len(key) > opts.csv_max_key_length else key
        lines.append(f"{key_display}={value}")

    if factored:
        lines.append("")  # blank line separator

    # Header row
    lines.append(",".join(_csv_escape(h) for h in display_headers))

    # Data rows
    for row in rows:
        lines.append(",".join(row))

    # Row limit footer
    remaining = len(data) - opts.csv_max_rows
    if remaining > 0:
        omitted_keys = ", ".join(headers[:5])
        suffix = ", ..." if len(headers) > 5 else ""
        lines.append(f"[... {remaining} more rows, keys: {omitted_keys}{suffix}]")

    return "\n".join(lines)


# ─── Strategy 2: Key-value lines ───


def _is_flat_object(data: dict[str, object], min_keys: int = 3) -> bool:
    """Check if a dict has only flat values (no nested dicts or lists)."""
    if len(data) < min_keys:
        return False
    return all(not isinstance(v, (dict, list)) for v in data.values())


def _serialize_kv(data: dict[str, object], opts: JsonFilterOptions) -> str:
    """Serialize a flat JSON object to key-value lines.

    One ``key: value`` pair per line. Keys are unquoted. String values are
    unquoted unless they contain newlines.
    """
    keys = list(data.keys())[: opts.kv_max_keys]
    lines: list[str] = []
    for key in keys:
        value = data[key]
        value_str = _format_flat_value(value, opts)
        key_display = key[: opts.csv_max_key_length] if len(key) > opts.csv_max_key_length else key
        lines.append(f"{key_display}: {value_str}")

    omitted_keys = len(data) - opts.kv_max_keys
    if omitted_keys > 0:
        remaining = ", ".join(list(data.keys())[opts.kv_max_keys : opts.kv_max_keys + 5])
        lines.append(f"... +{omitted_keys} more keys: [{remaining}]")

    return "\n".join(lines)


def _format_flat_value(value: object, opts: JsonFilterOptions) -> str:
    """Format a flat JSON value for KV or dotted-key output."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        if "\n" in value:
            return f'"{value[:opts.max_value_length]}..."' if len(value) > opts.max_value_length else json.dumps(value)
        if len(value) > opts.max_value_length:
            return f'"{value[:opts.max_value_length]}..." [{len(value)} chars]'
        # Unquoted string is fine for KV output
        return value
    return str(value)


# ─── Strategy 3: Dotted-key lines ───


def _has_nested_dicts(data: dict[str, object]) -> bool:
    """Check whether any value in the dict is itself a dict."""
    return any(isinstance(v, dict) for v in data.values())


def _is_dottable(data: dict[str, object], max_depth: int = 3) -> bool:
    """Check if a nested dict can be flattened to dotted keys within max_depth.

    All leaf values must be flat (strings, numbers, booleans, null).
    Lists at any level are not dottable (they get markers instead).
    """
    leaves = _collect_leaves(data, 0, max_depth)
    return leaves is not None


def _collect_leaves(
    data: dict[str, object], depth: int, max_depth: int
) -> list[tuple[str, object]] | None:
    """Recursively collect leaf (key_path, value) pairs.

    Returns None if the structure is not dottable (too deep, or
    contains lists as values).

    Depth is measured as nesting levels below the root dict.
    max_depth=3 allows depths 0,1,2 (3 levels of keys).
    """
    if depth >= max_depth:
        return None
    leaves: list[tuple[str, object]] = []
    for key, value in data.items():
        if isinstance(value, list):
            # Lists are not dottable — we emit markers instead
            return None
        if isinstance(value, dict):
            inner = _collect_leaves(value, depth + 1, max_depth)
            if inner is None:
                return None
            for inner_key, inner_value in inner:
                leaves.append((f"{key}.{inner_key}", inner_value))
        else:
            leaves.append((key, value))
    return leaves


def _serialize_dotkey(data: dict[str, object], opts: JsonFilterOptions) -> str:
    """Serialize a nested JSON object to dotted-key lines.

    One ``dotted.key: value`` pair per line for each leaf value.
    """
    leaves = _collect_leaves(data, 0, opts.dotkey_max_depth)
    if leaves is None:
        # Should not happen — _is_dottable should be checked first
        return _compress_value(data, 0, opts)

    if len(leaves) > opts.dotkey_max_keys:
        shown = leaves[: opts.dotkey_max_keys]
        omitted = len(leaves) - opts.dotkey_max_keys
        lines = [f"{k[:opts.csv_max_key_length]}: {_format_flat_value(v, opts)}" for k, v in shown]
        remaining = ", ".join(k for k, _ in leaves[opts.dotkey_max_keys : opts.dotkey_max_keys + 5])
        lines.append(f"... +{omitted_keys_suffix(omitted)} more keys: [{remaining}]")
        return "\n".join(lines)

    lines = [f"{k}: {_format_flat_value(v, opts)}" for k, v in leaves]
    return "\n".join(lines)


def omitted_keys_suffix(count: int) -> str:
    """Return the grammatically correct suffix for a count of omitted keys."""
    return str(count)


# ─── Legacy recursive compression (fallback) ───


def _compress_value(value: object, depth: int, opts: JsonFilterOptions) -> str:
    """Compress a parsed JSON value recursively (original Strategy 0)."""
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


# ─── Main entry point ───


def json_filter(formatted: str, opts: JsonFilterOptions | None = None) -> FilterResult:
    """Filter JSON output: compress structured data while preserving key names and structure.

    Tries format-switch strategies first (CSV, key-value, dotted-key),
    falling back to recursive truncation when no strategy applies or
    when the format-switch output is larger than truncation.
    """
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

    # ── Strategy selection ──

    format_result: str | None = None

    # Strategy 1 + 4: Tabular array → CSV (with optional column factoring)
    if opts.csv_enabled and isinstance(parsed, list):
        if _is_tabular_array(parsed, min_rows=opts.csv_min_rows):
            format_result = _serialize_csv(parsed, opts)

    # Strategy 3: Nested object → dotted-key lines
    if format_result is None and opts.dotkey_enabled and isinstance(parsed, dict):
        if _has_nested_dicts(parsed) and _is_dottable(parsed, max_depth=opts.dotkey_max_depth):
            format_result = _serialize_dotkey(parsed, opts)

    # Strategy 2: Flat object → key-value lines
    if format_result is None and opts.kv_enabled and isinstance(parsed, dict):
        if _is_flat_object(parsed, min_keys=opts.kv_min_keys):
            format_result = _serialize_kv(parsed, opts)

    # Safety check: only use format-switch result if it's actually shorter
    # than what truncation would produce.
    if format_result is not None:
        truncated = _compress_value(parsed, 0, opts)
        # Include header length in comparison
        header_len = len("\n".join(tool_header) + "\n") if tool_header else 0
        format_total = header_len + len(format_result)
        truncated_total = header_len + len(truncated)
        if format_total <= truncated_total:
            result = (
                "\n".join(tool_header + [format_result])
                if tool_header
                else format_result
            )
            truncated_flag = len(result) < raw_chars
            return FilterResult(
                output=result,
                raw_chars=raw_chars,
                filtered_chars=len(result),
                truncated=truncated_flag,
            )

    # Fallback: original recursive compression
    compressed = _compress_value(parsed, 0, opts)
    result = "\n".join(tool_header + [compressed])

    truncated = len(result) < raw_chars
    return FilterResult(output=result, raw_chars=raw_chars, filtered_chars=len(result), truncated=truncated)
