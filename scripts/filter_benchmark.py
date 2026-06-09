#!/usr/bin/env python3
"""Filter Benchmark: Run filter_output() against real session data.

Extracts tool results from Claude JSONL, Codex JSONL, and OpenCode SQLite,
runs archolith_filter.filter_output() on each, and reports actual compression
ratios per tool, per category, and per size range.

Usage:
    python filter_benchmark.py --claude <jsonl> [--claude <more>...]
    python filter_benchmark.py --opencode <sqlite>
    python filter_benchmark.py --codex <jsonl>
    python filter_benchmark.py --all
"""

import argparse
import json
import sys
import os
from collections import defaultdict
from pathlib import Path

# Add parent to path so we can import archolith_filter
sys.path.insert(0, str(Path(__file__).parent.parent))

from archolith_filter import filter_output, FilterConfig, FilterResult, from_env
from archolith_filter.classifier import CommandCategory


# ---------------------------------------------------------------------------
# Tool name -> Filter dispatch mapping
# ---------------------------------------------------------------------------

# Claude tool names -> (tool_name_for_filter, command_for_filter)
CLAUDE_TOOL_MAP = {
    "Read": ("read_file", ""),
    "Bash": ("run_command", ""),
    "PowerShell": ("run_command", "powershell"),
    "Edit": ("edit_file", ""),
    "Write": ("edit_file", ""),
    "Grep": ("search_content", "rg"),
    "Glob": ("generic", ""),
    "WebSearch": ("web_search", ""),
    "WebFetch": ("web_fetch", ""),
    "Agent": ("generic", ""),
}

# Codex tool names
CODEX_TOOL_MAP = {
    "shell_command": ("run_command", ""),
    "view_image": ("generic", ""),  # base64 images - currently no filter
    "read_mcp_resource": ("generic", ""),
}

# OpenCode tool names
OPENCODE_TOOL_MAP = {
    "read": ("read_file", ""),
    "bash": ("run_command", ""),
    "edit": ("edit_file", ""),
    "write": ("edit_file", ""),
    "grep": ("search_content", "rg"),
    "glob": ("generic", ""),
}


def get_filter_dispatch(source: str, tool_name: str) -> tuple[str, str]:
    """Return (tool_name_for_filter, command_for_filter) based on source and tool."""
    if source == "claude":
        return CLAUDE_TOOL_MAP.get(tool_name, (tool_name, ""))
    elif source == "codex":
        return CODEX_TOOL_MAP.get(tool_name, (tool_name, ""))
    elif source == "opencode":
        return OPENCODE_TOOL_MAP.get(tool_name, (tool_name, ""))
    # MCP tools: detect if JSON
    if tool_name.startswith("mcp__"):
        return (tool_name, "")
    return (tool_name, "")


# ---------------------------------------------------------------------------
# Claude JSONL extraction
# ---------------------------------------------------------------------------

def extract_claude_tool_results(jsonl_path: str):
    """Extract (tool_name, output_text) pairs from Claude JSONL."""
    # First pass: build tool_use_id -> tool_name
    tool_use_id_to_name = {}
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "assistant":
                for block in entry.get("message", {}).get("content", []):
                    if isinstance(block, str):
                        continue
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_id = block.get("id", "")
                        name = block.get("name", "unknown")
                        if tool_id:
                            tool_use_id_to_name[tool_id] = name

    # Second pass: extract tool results
    results = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "user":
                for block in entry.get("message", {}).get("content", []):
                    if isinstance(block, str):
                        continue
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_use_id = block.get("tool_use_id", "")
                        tool_name = tool_use_id_to_name.get(tool_use_id, "unknown")
                        content = block.get("content", "")
                        if isinstance(content, str) and content:
                            results.append((tool_name, content))
                        elif isinstance(content, list):
                            for sub in content:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    text = sub.get("text", "")
                                    if text:
                                        results.append((tool_name, text))
    return results


# ---------------------------------------------------------------------------
# Codex JSONL extraction
# ---------------------------------------------------------------------------

def extract_codex_tool_results(jsonl_path: str):
    """Extract (tool_name, output_text) pairs from Codex JSONL."""
    # Build call_id -> tool_name
    call_id_to_name = {}
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "response_item":
                payload = entry.get("payload", {})
                if payload.get("type") == "function_call":
                    call_id = payload.get("call_id", "")
                    name = payload.get("name", "unknown")
                    if call_id:
                        call_id_to_name[call_id] = name

    results = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "response_item":
                payload = entry.get("payload", {})
                if payload.get("type") == "function_call_output":
                    call_id = payload.get("call_id", "")
                    tool_name = call_id_to_name.get(call_id, "unknown")
                    output = payload.get("output", "")
                    if isinstance(output, str) and output:
                        results.append((tool_name, output))
                    elif isinstance(output, list):
                        for item in output:
                            item_str = json.dumps(item) if isinstance(item, dict) else str(item)
                            if item_str:
                                results.append((tool_name, item_str))
    return results


# ---------------------------------------------------------------------------
# OpenCode SQLite extraction
# ---------------------------------------------------------------------------

def extract_opencode_tool_results(sqlite_path: str, session_id: str = None, limit: int = 5000):
    """Extract (tool_name, output_text) pairs from OpenCode SQLite."""
    import sqlite3
    db = sqlite3.connect(sqlite_path)
    c = db.cursor()

    query = "SELECT data FROM part WHERE data LIKE '%\"type\":\"tool\"%'"
    if session_id:
        query += f" AND session_id = '{session_id}'"
    query += f" LIMIT {limit}"

    results = []
    for row in c.execute(query):
        try:
            data = json.loads(row[0])
        except:
            continue
        tool_name = data.get("tool", "unknown")
        state = data.get("state", {})
        if isinstance(state, dict):
            output = state.get("output", "")
            if output:
                results.append((tool_name, output))

    db.close()
    return results


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark(tool_results, source: str, config: FilterConfig = None, max_results: int = None):
    """Run filter_output on each tool result and collect compression stats."""
    if config is None:
        config = FilterConfig()

    # Reset per-run state
    from archolith_filter import reset_dedupe_tracker, reset_raw_output_store, reset_filter_telemetry_store
    reset_dedupe_tracker()
    reset_raw_output_store()
    reset_filter_telemetry_store()

    # Per-tool stats
    tool_stats = defaultdict(lambda: {
        "count": 0, "total_raw_chars": 0, "total_filtered_chars": 0,
        "filtered_count": 0, "skipped_small": 0, "skipped_error": 0,
        "deduped_count": 0, "savings_pct": [],
    })

    # Per-category stats (from telemetry)
    category_stats = defaultdict(lambda: {
        "count": 0, "total_raw_chars": 0, "total_filtered_chars": 0,
    })

    # Size distribution
    size_buckets = {
        "<500B": 0, "500B-2KB": 0, "2-10KB": 0, "10-50KB": 0,
        "50-100KB": 0, "100-500KB": 0, ">500KB": 0,
    }
    size_savings = defaultdict(lambda: {"raw": 0, "filtered": 0, "count": 0})

    items = tool_results if max_results is None else tool_results[:max_results]

    for tool_name, text in items:
        filter_tool, filter_command = get_filter_dispatch(source, tool_name)
        raw_chars = len(text)

        # Size bucket
        if raw_chars < 500:
            bucket = "<500B"
        elif raw_chars < 2000:
            bucket = "500B-2KB"
        elif raw_chars < 10000:
            bucket = "2-10KB"
        elif raw_chars < 50000:
            bucket = "10-50KB"
        elif raw_chars < 100000:
            bucket = "50-100KB"
        elif raw_chars < 500000:
            bucket = "100-500KB"
        else:
            bucket = ">500KB"

        try:
            result = filter_output(
                text,
                tool=filter_tool,
                command=filter_command,
                exit_code=0,
                config=config,
            )
            filtered_chars = result.filtered_chars
            truncated = result.truncated
        except Exception as e:
            # Fail open
            filtered_chars = raw_chars
            truncated = False

        savings_pct = (1 - filtered_chars / raw_chars) * 100 if raw_chars > 0 else 0

        stats = tool_stats[tool_name]
        stats["count"] += 1
        stats["total_raw_chars"] += raw_chars
        stats["total_filtered_chars"] += filtered_chars
        if savings_pct > 1:
            stats["filtered_count"] += 1
        elif raw_chars < 500:
            stats["skipped_small"] += 1

        size_savings[bucket]["raw"] += raw_chars
        size_savings[bucket]["filtered"] += filtered_chars
        size_savings[bucket]["count"] += 1

    # Get telemetry for category-level breakdown
    from archolith_filter import get_filter_telemetry_store
    telemetry = get_filter_telemetry_store()
    for entry in telemetry.entries:
        cat = entry.filter_kind
        category_stats[cat]["count"] += 1
        category_stats[cat]["total_raw_chars"] += entry.raw_chars
        category_stats[cat]["total_filtered_chars"] += entry.filtered_chars

    return tool_stats, category_stats, size_savings


def print_benchmark_report(source_name, tool_stats, category_stats, size_savings):
    """Print a formatted benchmark report."""
    print(f"\n{'='*100}")
    print(f"FILTER BENCHMARK: {source_name}")
    print(f"{'='*100}")

    # Sort tools by total raw chars
    sorted_tools = sorted(tool_stats.items(), key=lambda x: -x[1]["total_raw_chars"])

    total_raw = sum(s["total_raw_chars"] for _, s in sorted_tools)
    total_filtered = sum(s["total_filtered_chars"] for _, s in sorted_tools)
    overall_pct = (1 - total_filtered / total_raw) * 100 if total_raw > 0 else 0

    print(f"\nOverall: {total_raw:,} raw -> {total_filtered:,} filtered chars ({overall_pct:.1f}% savings)")
    print()

    print(f"{'Tool':<50} {'Count':>6} {'Raw':>12} {'Filtered':>12} {'Save%':>7} {'Filtered':>8}")
    print("-" * 100)
    for tool, stats in sorted_tools[:30]:
        raw = stats["total_raw_chars"]
        filtered = stats["total_filtered_chars"]
        pct = (1 - filtered / raw) * 100 if raw > 0 else 0
        filtered_count = stats["filtered_count"]
        print(f"{tool:<50} {stats['count']:>6} {raw:>12,} {filtered:>12,} {pct:>6.1f}% {filtered_count:>8}")

    # Category breakdown
    if category_stats:
        print(f"\n{'='*100}")
        print("FILTER CATEGORY BREAKDOWN (from telemetry)")
        print(f"{'='*100}")
        sorted_cats = sorted(category_stats.items(), key=lambda x: -x[1]["total_raw_chars"])
        print(f"\n{'Category':<20} {'Count':>6} {'Raw':>12} {'Filtered':>12} {'Save%':>7}")
        print("-" * 60)
        for cat, stats in sorted_cats:
            raw = stats["total_raw_chars"]
            filtered = stats["total_filtered_chars"]
            pct = (1 - filtered / raw) * 100 if raw > 0 else 0
            print(f"{cat:<20} {stats['count']:>6} {raw:>12,} {filtered:>12,} {pct:>6.1f}%")

    # Size distribution
    print(f"\n{'='*100}")
    print("SIZE DISTRIBUTION (savings by output size)")
    print(f"{'='*100}")
    print(f"\n{'Size Range':<15} {'Count':>6} {'Raw':>12} {'Filtered':>12} {'Save%':>7} {'AvgRaw':>10}")
    print("-" * 70)
    bucket_order = ["<500B", "500B-2KB", "2-10KB", "10-50KB", "50-100KB", "100-500KB", ">500KB"]
    for bucket in bucket_order:
        s = size_savings.get(bucket, {"raw": 0, "filtered": 0, "count": 0})
        if s["count"] == 0:
            continue
        raw = s["raw"]
        filtered = s["filtered"]
        pct = (1 - filtered / raw) * 100 if raw > 0 else 0
        avg = raw // s["count"]
        print(f"{bucket:<15} {s['count']:>6} {raw:>12,} {filtered:>12,} {pct:>6.1f}% {avg:>10,}")

    return overall_pct


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Filter benchmark against real session data")
    parser.add_argument("--claude", nargs="*", help="Claude JSONL session files")
    parser.add_argument("--codex", nargs="*", help="Codex JSONL session files")
    parser.add_argument("--opencode", help="OpenCode SQLite database path")
    parser.add_argument("--opencode-session", help="Specific OpenCode session ID")
    parser.add_argument("--all", action="store_true", help="Benchmark all available sessions")
    parser.add_argument("--max-results", type=int, default=None, help="Max tool results to process per source")
    args = parser.parse_args()

    claude_files = args.claude or []
    codex_files = args.codex or []
    opencode_db = args.opencode

    if args.all:
        claude_dir = Path(r"C:\Users\thron\.claude\projects\C--Users-thron-IdeaProjects")
        codex_dir = Path(r"C:\Users\thron\.codex\sessions")
        opencode_db = r"C:\Users\thron\.local\share\opencode\opencode.db"

        if claude_dir.exists():
            # Pick representative sessions: monster, gradle, vps, short
            targets = [
                "5bb0dc8d-e286-4f0b-ae6b-8b716b6ca0e6.jsonl",
                "99c6368f-036d-48ea-92a2-6a4b08cd70e5.jsonl",
                "91cb2965-d483-47d2-bc26-0a11a6ebb948.jsonl",
                "d24918fa-b936-4c9c-8173-3e6bb8af1a89.jsonl",
            ]
            for t in targets:
                p = claude_dir / t
                if p.exists() and str(p) not in claude_files:
                    claude_files.append(str(p))

        if codex_dir.exists():
            targets = [
                "2026/05/12/rollout-2026-05-12T21-21-48-019e1f23-ebf8-79f1-8db3-1d727c0c7758.jsonl",
                "2026/03/06/rollout-2026-03-06T10-39-17-019cc404-8851-7a22-81a4-11845c49d5b5.jsonl",
            ]
            for t in targets:
                p = codex_dir / t
                if p.exists():
                    codex_files.append(str(p))

    # Claude sessions
    for path in claude_files:
        name = Path(path).stem[:40]
        print(f"\nExtracting Claude session: {name}")
        results = extract_claude_tool_results(path)
        print(f"  Extracted {len(results)} tool results")
        if args.max_results:
            results = results[:args.max_results]
        tool_stats, cat_stats, size_stats = run_benchmark(results, "claude")
        print_benchmark_report(f"Claude: {name}", tool_stats, cat_stats, size_stats)

    # Codex sessions
    for path in codex_files:
        name = Path(path).stem[:40]
        print(f"\nExtracting Codex session: {name}")
        results = extract_codex_tool_results(path)
        print(f"  Extracted {len(results)} tool results")
        if args.max_results:
            results = results[:args.max_results]
        tool_stats, cat_stats, size_stats = run_benchmark(results, "codex")
        print_benchmark_report(f"Codex: {name}", tool_stats, cat_stats, size_stats)

    # OpenCode SQLite
    if opencode_db and os.path.exists(opencode_db):
        print(f"\nExtracting OpenCode tool results from: {opencode_db}")
        results = extract_opencode_tool_results(
            opencode_db,
            session_id=args.opencode_session,
            limit=args.max_results or 5000,
        )
        print(f"  Extracted {len(results)} tool results")
        tool_stats, cat_stats, size_stats = run_benchmark(results, "opencode")
        print_benchmark_report("OpenCode", tool_stats, cat_stats, size_stats)


if __name__ == "__main__":
    main()
