#!/usr/bin/env python3
"""Agent-solo compression benchmark.

Generates realistic synthetic agent-solo turns (or loads from a JSON file)
and measures each strategy's savings independently and combined.

Usage:
    # Synthetic benchmark — simulates a 10-turn coding session
    python agent_solo_benchmark.py

    # With specific strategies
    python agent_solo_benchmark.py --strategies A B C

    # Custom turn count and tool result sizes
    python agent_solo_benchmark.py --turns 20 --tool-results 50

    # From a captured payload JSON (array of message dicts)
    python agent_solo_benchmark.py --payload captured.json

    # Verbose — show per-turn breakdown
    python agent_solo_benchmark.py -v

    # Sweep — run all strategy combinations and rank them
    python agent_solo_benchmark.py --sweep
"""

import argparse
import json
import random
import string
import sys
import time
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from archolith_rtk.agent_solo import compress_agent_solo_turn, AgentSoloStats
from archolith_rtk.dedupe import DedupeTracker


# --- Synthetic data generation ------------------------------------------

# Based on real analysis: 85K token agent-solo turn = 2K system + 2K user
# + 6.5K assistant + 75K tool results (87.7%).  39 Read results at 1,751
# chars avg = 68K chars.  75% of tool results byte-identical across
# consecutive turns.

TOOL_PROFILES = {
    "read_file": {
        "weight": 0.50,  # 50% of tool results are reads
        "min_chars": 500,
        "max_chars": 5000,
        "avg_chars": 1751,
    },
    "bash": {
        "weight": 0.15,
        "min_chars": 200,
        "max_chars": 8000,
        "avg_chars": 2000,
    },
    "grep": {
        "weight": 0.12,
        "min_chars": 300,
        "max_chars": 6000,
        "avg_chars": 1500,
    },
    "glob": {
        "weight": 0.08,
        "min_chars": 100,
        "max_chars": 3000,
        "avg_chars": 800,
    },
    "search_content": {
        "weight": 0.05,
        "min_chars": 200,
        "max_chars": 4000,
        "avg_chars": 1200,
    },
    "edit_file": {
        "weight": 0.05,
        "min_chars": 50,
        "max_chars": 500,
        "avg_chars": 150,
    },
    "web_fetch": {
        "weight": 0.03,
        "min_chars": 500,
        "max_chars": 10000,
        "avg_chars": 3000,
    },
    "list_directory": {
        "weight": 0.02,
        "min_chars": 100,
        "max_chars": 2000,
        "avg_chars": 600,
    },
}


def _random_code(n: int) -> str:
    """Generate n chars of plausible code-like content."""
    lines = []
    while sum(len(l) + 1 for l in lines) < n:
        indent = "    " * random.randint(0, 3)
        keywords = ["def ", "class ", "if ", "for ", "return ", "import ", "# ", "    "]
        line = indent + random.choice(keywords) + "".join(
            random.choices(string.ascii_lowercase + "_", k=random.randint(5, 40))
        )
        lines.append(line)
    return "\n".join(lines)[:n]


def _pick_tool() -> str:
    """Weighted random tool selection."""
    tools = list(TOOL_PROFILES.keys())
    weights = [TOOL_PROFILES[t]["weight"] for t in tools]
    return random.choices(tools, weights=weights, k=1)[0]


def _generate_tool_result(tool: str) -> str:
    """Generate a realistic tool result for the given tool."""
    p = TOOL_PROFILES[tool]
    # Normal distribution around avg, clamped to min/max
    size = int(random.gauss(p["avg_chars"], p["avg_chars"] * 0.4))
    size = max(p["min_chars"], min(p["max_chars"], size))
    return _random_code(size)


def generate_session(
    num_turns: int = 10,
    tool_results_per_turn: int = 8,
    dedup_ratio: float = 0.75,
) -> list[list[dict]]:
    """Generate a multi-turn session of agent-solo payloads.

    Each turn is a full message list (system + history + new tool results).
    ``dedup_ratio`` controls what fraction of tool results are carried
    forward from the previous turn (simulating unchanged file reads).

    Returns a list of turns, where each turn is a list of message dicts.
    """
    system = {
        "role": "system",
        "content": _random_code(2000),  # ~2K system prompt
    }

    # Build up conversation history turn by turn
    history: list[dict] = []
    turns: list[list[dict]] = []

    # Pool of "stable" tool results that get repeated across turns
    stable_pool: list[tuple[str, str]] = []  # (tool_name, content)

    for turn_idx in range(num_turns):
        # User message (only on first turn or occasionally)
        if turn_idx == 0 or random.random() < 0.1:
            history.append({"role": "user", "content": f"Turn {turn_idx}: " + _random_code(200)})

        # Assistant message with tool calls
        tool_calls = []
        for i in range(tool_results_per_turn):
            tool_calls.append({
                "id": f"tc_{turn_idx}_{i}",
                "type": "function",
                "function": {"name": _pick_tool(), "arguments": "{}"},
            })
        history.append({
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls,
        })

        # Tool results
        new_results: list[dict] = []
        for tc in tool_calls:
            tool_name = tc["function"]["name"]

            # Decide: reuse from stable pool or generate new
            if stable_pool and random.random() < dedup_ratio:
                # Pick a random stable result
                pool_tool, pool_content = random.choice(stable_pool)
                new_results.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": pool_tool,
                    "content": pool_content,
                })
            else:
                content = _generate_tool_result(tool_name)
                new_results.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tool_name,
                    "content": content,
                })
                # Add to stable pool (max 30 entries)
                if len(stable_pool) < 30:
                    stable_pool.append((tool_name, content))

        history.extend(new_results)

        # Build the full message list for this turn
        turns.append([system] + list(history))

    return turns


# --- Benchmark runner ---------------------------------------------------


def _total_chars(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c)
    return total


def _tool_chars(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        if m.get("role") == "tool":
            c = m.get("content")
            if isinstance(c, str):
                total += len(c)
    return total


def run_strategy(
    turns: list[list[dict]],
    label: str,
    shrink: bool = False,
    dedup: bool = False,
    filter_middle: bool = False,
    shrink_max_tokens: int = 2000,
    coherence_tail_size: int = 10,
    verbose: bool = False,
) -> dict:
    """Run a strategy config across all turns and return aggregate stats."""
    tracker = DedupeTracker() if dedup else None

    total_input_chars = 0
    total_output_chars = 0
    total_tool_input = 0
    total_tool_output = 0
    per_strategy_saved = {"shrink": 0, "dedup": 0, "filter": 0}
    turn_results = []
    elapsed_ms = 0.0

    for i, messages in enumerate(turns):
        input_chars = _total_chars(messages)
        tool_input = _tool_chars(messages)
        total_input_chars += input_chars
        total_tool_input += tool_input

        t0 = time.perf_counter()
        result = compress_agent_solo_turn(
            messages,
            dedup_tracker=tracker,
            shrink_enabled=shrink,
            dedup_enabled=dedup,
            filter_middle_enabled=filter_middle,
            shrink_max_tokens=shrink_max_tokens,
            coherence_tail_size=coherence_tail_size,
        )
        elapsed_ms += (time.perf_counter() - t0) * 1000

        output_chars = _total_chars(result.messages)
        tool_output = _tool_chars(result.messages)
        total_output_chars += output_chars
        total_tool_output += tool_output

        per_strategy_saved["shrink"] += result.stats.chars_saved_shrink
        per_strategy_saved["dedup"] += result.stats.chars_saved_dedup
        per_strategy_saved["filter"] += result.stats.chars_saved_filter

        if verbose:
            saved_pct = (1 - output_chars / input_chars) * 100 if input_chars else 0
            turn_results.append({
                "turn": i,
                "input": input_chars,
                "output": output_chars,
                "saved_pct": saved_pct,
                "strategies": result.stats.strategies_applied,
            })

    total_saved = total_input_chars - total_output_chars
    savings_pct = (total_saved / total_input_chars * 100) if total_input_chars else 0
    tool_saved = total_tool_input - total_tool_output
    tool_pct = (tool_saved / total_tool_input * 100) if total_tool_input else 0

    return {
        "label": label,
        "total_input_chars": total_input_chars,
        "total_output_chars": total_output_chars,
        "total_saved_chars": total_saved,
        "savings_pct": savings_pct,
        "tool_input_chars": total_tool_input,
        "tool_saved_chars": tool_saved,
        "tool_savings_pct": tool_pct,
        "per_strategy": per_strategy_saved,
        "elapsed_ms": elapsed_ms,
        "turns": len(turns),
        "turn_results": turn_results,
    }


def print_result(r: dict, verbose: bool = False) -> None:
    """Pretty-print a benchmark result."""
    est_tokens = r["total_saved_chars"] // 4
    print(f"\n{'-' * 60}")
    print(f"  {r['label']}")
    print(f"{'-' * 60}")
    print(f"  Turns:           {r['turns']}")
    print(f"  Total input:     {r['total_input_chars']:>10,} chars")
    print(f"  Total output:    {r['total_output_chars']:>10,} chars")
    print(f"  Saved:           {r['total_saved_chars']:>10,} chars  ({r['savings_pct']:.1f}%)")
    print(f"  Est. tokens:     {est_tokens:>10,} saved")
    print(f"  Tool input:      {r['tool_input_chars']:>10,} chars")
    print(f"  Tool saved:      {r['tool_saved_chars']:>10,} chars  ({r['tool_savings_pct']:.1f}%)")
    print(f"  Latency:         {r['elapsed_ms']:>10.1f} ms total  ({r['elapsed_ms']/r['turns']:.1f} ms/turn)")

    ps = r["per_strategy"]
    active = {k: v for k, v in ps.items() if v > 0}
    if active:
        print(f"  Breakdown:")
        for k, v in active.items():
            print(f"    {k:>8}: {v:>10,} chars")

    if verbose and r["turn_results"]:
        print(f"\n  Per-turn:")
        for t in r["turn_results"]:
            strats = ",".join(t["strategies"]) or "none"
            print(f"    T{t['turn']:>2}: {t['input']:>8,} -> {t['output']:>8,}  "
                  f"({t['saved_pct']:>5.1f}%)  [{strats}]")


def run_sweep(turns: list[list[dict]], verbose: bool = False) -> None:
    """Run all strategy combinations and rank by savings."""
    strategies = {
        "A": {"shrink": True},
        "B": {"dedup": True},
        "C": {"filter_middle": True},
    }

    results = []

    # Individual strategies
    for name, kwargs in strategies.items():
        r = run_strategy(turns, label=f"Strategy {name} only", **kwargs)
        results.append(r)

    # Pairwise combinations
    for combo in combinations(strategies.keys(), 2):
        merged = {}
        for c in combo:
            merged.update(strategies[c])
        label = "+".join(combo)
        r = run_strategy(turns, label=f"Strategies {label}", **merged)
        results.append(r)

    # All three
    merged = {}
    for s in strategies.values():
        merged.update(s)
    r = run_strategy(turns, label="Strategies A+B+C (all)", **merged)
    results.append(r)

    # Sort by savings
    results.sort(key=lambda r: r["savings_pct"], reverse=True)

    print("\n" + "=" * 60)
    print("  SWEEP RESULTS — ranked by savings %")
    print("=" * 60)
    for r in results:
        est_tok = r["total_saved_chars"] // 4
        print(f"  {r['label']:<25} {r['savings_pct']:>5.1f}%  "
              f"({r['total_saved_chars']:>8,} chars / ~{est_tok:,} tok)  "
              f"{r['elapsed_ms']:.0f}ms")

    if verbose:
        for r in results:
            print_result(r, verbose=True)


# --- CLI ----------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark agent-solo turn compression strategies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--payload", type=str, default=None,
        help="Path to a JSON file containing a message list (or array of message lists for multi-turn)",
    )
    parser.add_argument(
        "--strategies", nargs="*", default=["A", "B", "C"],
        choices=["A", "B", "C"],
        help="Strategies to enable (default: all)",
    )
    parser.add_argument(
        "--turns", type=int, default=10,
        help="Number of synthetic turns to generate (default: 10)",
    )
    parser.add_argument(
        "--tool-results", type=int, default=8,
        help="Tool results per turn (default: 8)",
    )
    parser.add_argument(
        "--dedup-ratio", type=float, default=0.75,
        help="Fraction of tool results duplicated across turns (default: 0.75)",
    )
    parser.add_argument(
        "--shrink-tokens", type=int, default=2000,
        help="Max tokens per result for shrink strategy (default: 2000)",
    )
    parser.add_argument(
        "--tail-size", type=int, default=10,
        help="Coherence tail size for filter-middle strategy (default: 10)",
    )
    parser.add_argument(
        "--sweep", action="store_true",
        help="Run all strategy combinations and rank by savings",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducible synthetic data (default: 42)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show per-turn breakdown",
    )

    args = parser.parse_args()
    random.seed(args.seed)

    # Load or generate data
    if args.payload:
        payload_path = Path(args.payload)
        if not payload_path.exists():
            print(f"Error: payload file not found: {payload_path}", file=sys.stderr)
            sys.exit(1)
        with open(payload_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Accept either a single message list or array of message lists
        if data and isinstance(data[0], dict):
            turns = [data]  # Single turn
        else:
            turns = data
        print(f"Loaded {len(turns)} turn(s) from {payload_path}")
    else:
        print(f"Generating synthetic session: {args.turns} turns, "
              f"{args.tool_results} tool results/turn, "
              f"{args.dedup_ratio:.0%} dedup ratio, seed={args.seed}")
        turns = generate_session(
            num_turns=args.turns,
            tool_results_per_turn=args.tool_results,
            dedup_ratio=args.dedup_ratio,
        )

    # Show input stats
    total_chars = sum(_total_chars(t) for t in turns)
    total_tool = sum(_tool_chars(t) for t in turns)
    tool_pct = (total_tool / total_chars * 100) if total_chars else 0
    print(f"Input: {total_chars:,} total chars, {total_tool:,} tool chars ({tool_pct:.1f}%)")
    print(f"Avg turn: {total_chars // len(turns):,} chars")

    if args.sweep:
        run_sweep(turns, verbose=args.verbose)
        return

    # Run selected strategies
    shrink = "A" in args.strategies
    dedup = "B" in args.strategies
    filter_middle = "C" in args.strategies

    label_parts = []
    if shrink: label_parts.append("A(shrink)")
    if dedup: label_parts.append("B(dedup)")
    if filter_middle: label_parts.append("C(filter)")
    label = " + ".join(label_parts) or "none"

    result = run_strategy(
        turns,
        label=label,
        shrink=shrink,
        dedup=dedup,
        filter_middle=filter_middle,
        shrink_max_tokens=args.shrink_tokens,
        coherence_tail_size=args.tail_size,
        verbose=args.verbose,
    )
    print_result(result, verbose=args.verbose)


if __name__ == "__main__":
    main()
