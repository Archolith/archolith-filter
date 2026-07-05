#!/usr/bin/env python3
"""
Token-Level Corpus Analysis for archolith-filter research.

Runs tiktoken over actual tool result content from Codex and Claude session
corpora to produce ground-truth token counts. Re-ranks compression targets
by token savings instead of byte savings.

This addresses Research Methodology Gap M1 from the research-meta plan.

Usage:
    python token_corpus_analysis.py --codex <jsonl_path> [--codex <more>...] [--claude <jsonl_path>]
    python token_corpus_analysis.py --all
"""

import argparse
import json
import sys
import os
from collections import defaultdict
from pathlib import Path

import tiktoken


# ---------------------------------------------------------------------------
# Encoding selection
# ---------------------------------------------------------------------------

def get_encodings():
    """Return encodings for OpenAI and a Claude proxy."""
    encodings = {}
    # cl100k_base: GPT-4, GPT-4-turbo, text-embedding-ada-002
    encodings["cl100k_base"] = tiktoken.get_encoding("cl100k_base")
    # o200k_base: GPT-4o, GPT-5 (closest proxy for Claude's tokenizer)
    encodings["o200k_base"] = tiktoken.get_encoding("o200k_base")
    return encodings


# ---------------------------------------------------------------------------
# Codex JSONL parsing
# ---------------------------------------------------------------------------

def parse_codex_session(jsonl_path: str):
    """Parse a Codex JSONL session and extract content by category."""
    entries_by_type = defaultdict(lambda: {"count": 0, "bytes": 0, "chars": 0, "content_samples": []})

    # We'll accumulate content for tokenization
    content_by_category = defaultdict(list)  # category -> [text_chunks]

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "unknown")
            payload = entry.get("payload", {})

            if entry_type == "response_item":
                subtype = payload.get("type", "unknown")

                if subtype == "function_call":
                    name = payload.get("name", "unknown")
                    args = payload.get("arguments", "")
                    if isinstance(args, str) and args:
                        key = f"tool_call_args/{name}"
                        content_by_category[key].append(args)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(args.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(args)

                elif subtype == "function_call_output":
                    call_id = payload.get("call_id", "")
                    output = payload.get("output", "")
                    # Try to find the tool name from a lookup - we'll use call_id mapping
                    if isinstance(output, str) and output:
                        key = "tool_result/unknown"
                        content_by_category[key].append(output)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(output.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(output)

                elif subtype == "reasoning":
                    # Codex reasoning is encrypted, skip
                    pass

                elif subtype == "message":
                    content = payload.get("content", "")
                    if isinstance(content, str) and content:
                        key = "assistant/message"
                        content_by_category[key].append(content)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(content.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(content)

            elif entry_type == "event_msg":
                subtype = payload.get("type", "unknown")
                if subtype == "mcp_tool_call_end":
                    name = payload.get("name", "unknown")
                    result = payload.get("result", "")
                    if isinstance(result, str) and result:
                        key = f"mcp_result/{name}"
                        content_by_category[key].append(result)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(result.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(result)

                elif subtype == "agent_message":
                    content = payload.get("content", "")
                    if isinstance(content, str) and content:
                        key = "agent_message"
                        content_by_category[key].append(content)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(content.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(content)

            elif entry_type == "session_meta":
                base_instructions = payload.get("base_instructions", "")
                dynamic_tools = payload.get("dynamic_tools", "")
                for label, text in [("base_instructions", base_instructions),
                                    ("dynamic_tools", dynamic_tools)]:
                    if isinstance(text, str) and text:
                        key = f"session_meta/{label}"
                        content_by_category[key].append(text)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(text)

            elif entry_type == "compacted":
                data = payload.get("data", "")
                if isinstance(data, str) and data:
                    key = "compacted"
                    content_by_category[key].append(data)
                    entries_by_type[key]["count"] += 1
                    entries_by_type[key]["bytes"] += len(data.encode("utf-8"))
                    entries_by_type[key]["chars"] += len(data)

            elif entry_type == "turn_context":
                user_instructions = payload.get("user_instructions", "")
                if isinstance(user_instructions, str) and user_instructions:
                    key = "turn_context/user_instructions"
                    content_by_category[key].append(user_instructions)
                    entries_by_type[key]["count"] += 1
                    entries_by_type[key]["bytes"] += len(user_instructions.encode("utf-8"))
                    entries_by_type[key]["chars"] += len(user_instructions)

    return entries_by_type, content_by_category


# ---------------------------------------------------------------------------
# Codex JSONL parsing (v2 — with function_call name tracking)
# ---------------------------------------------------------------------------

def parse_codex_session_v2(jsonl_path: str):
    """Parse Codex JSONL with function_call name tracking for output mapping."""
    # First pass: build call_id -> tool_name mapping
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

    # Second pass: extract content with tool name resolution
    entries_by_type = defaultdict(lambda: {"count": 0, "bytes": 0, "chars": 0})
    content_by_category = defaultdict(list)

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "unknown")
            payload = entry.get("payload", {})

            if entry_type == "response_item":
                subtype = payload.get("type", "unknown")

                if subtype == "function_call":
                    name = payload.get("name", "unknown")
                    args = payload.get("arguments", "")
                    if isinstance(args, str) and args:
                        key = f"tool_call_args/{name}"
                        content_by_category[key].append(args)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(args.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(args)

                elif subtype == "function_call_output":
                    call_id = payload.get("call_id", "")
                    output = payload.get("output", "")
                    tool_name = call_id_to_name.get(call_id, "unknown")
                    if isinstance(output, str) and output:
                        key = f"tool_result/{tool_name}"
                        content_by_category[key].append(output)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(output.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(output)
                    elif isinstance(output, list):
                        # view_image returns list of dicts with base64 data
                        for item in output:
                            item_str = json.dumps(item) if isinstance(item, dict) else str(item)
                            if item_str:
                                key = f"tool_result/{tool_name}"
                                content_by_category[key].append(item_str)
                                entries_by_type[key]["count"] += 1
                                entries_by_type[key]["bytes"] += len(item_str.encode("utf-8"))
                                entries_by_type[key]["chars"] += len(item_str)

                elif subtype == "reasoning":
                    content = payload.get("summary", "") or ""
                    if isinstance(content, str) and content:
                        key = "reasoning/summary"
                        content_by_category[key].append(content)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(content.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(content)
                    # encrypted_content is not tokenizable

                elif subtype == "message":
                    content = payload.get("content", "")
                    if isinstance(content, str) and content:
                        key = "assistant/message"
                        content_by_category[key].append(content)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(content.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(content)

            elif entry_type == "event_msg":
                subtype = payload.get("type", "unknown")
                if subtype == "mcp_tool_call_end":
                    name = payload.get("name", "unknown")
                    result = payload.get("result", "")
                    if isinstance(result, str) and result:
                        key = f"mcp_result/{name}"
                        content_by_category[key].append(result)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(result.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(result)

                elif subtype == "agent_message":
                    content = payload.get("content", "")
                    if isinstance(content, str) and content:
                        key = "agent_message"
                        content_by_category[key].append(content)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(content.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(content)

                elif subtype == "token_count":
                    # Metadata, skip
                    pass

            elif entry_type == "session_meta":
                base_instructions = payload.get("base_instructions", "")
                dynamic_tools = payload.get("dynamic_tools", "")
                for label, text in [("base_instructions", base_instructions),
                                    ("dynamic_tools", dynamic_tools)]:
                    if isinstance(text, str) and text:
                        key = f"session_meta/{label}"
                        content_by_category[key].append(text)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(text)

            elif entry_type == "compacted":
                data = payload.get("data", "")
                if isinstance(data, str) and data:
                    key = "compacted"
                    content_by_category[key].append(data)
                    entries_by_type[key]["count"] += 1
                    entries_by_type[key]["bytes"] += len(data.encode("utf-8"))
                    entries_by_type[key]["chars"] += len(data)

            elif entry_type == "turn_context":
                user_instructions = payload.get("user_instructions", "")
                if isinstance(user_instructions, str) and user_instructions:
                    key = "turn_context/user_instructions"
                    content_by_category[key].append(user_instructions)
                    entries_by_type[key]["count"] += 1
                    entries_by_type[key]["bytes"] += len(user_instructions.encode("utf-8"))
                    entries_by_type[key]["chars"] += len(user_instructions)

    return entries_by_type, content_by_category


# ---------------------------------------------------------------------------
# Claude JSONL parsing
# ---------------------------------------------------------------------------

def parse_claude_session(jsonl_path: str):
    """Parse a Claude JSONL session and extract content by category."""
    entries_by_type = defaultdict(lambda: {"count": 0, "bytes": 0, "chars": 0})
    content_by_category = defaultdict(list)

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = entry.get("type", "unknown")

            if msg_type == "assistant":
                message = entry.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    block_type = block.get("type", "unknown")
                    if block_type == "text":
                        text = block.get("text", "")
                        if text:
                            key = "assistant/text"
                            content_by_category[key].append(text)
                            entries_by_type[key]["count"] += 1
                            entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                            entries_by_type[key]["chars"] += len(text)
                    elif block_type == "thinking":
                        text = block.get("thinking", "")
                        if text:
                            key = "assistant/thinking"
                            content_by_category[key].append(text)
                            entries_by_type[key]["count"] += 1
                            entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                            entries_by_type[key]["chars"] += len(text)
                    elif block_type == "tool_use":
                        name = block.get("name", "unknown")
                        inp = block.get("input", {})
                        inp_str = json.dumps(inp) if inp else ""
                        if inp_str:
                            key = f"tool_call_args/{name}"
                            content_by_category[key].append(inp_str)
                            entries_by_type[key]["count"] += 1
                            entries_by_type[key]["bytes"] += len(inp_str.encode("utf-8"))
                            entries_by_type[key]["chars"] += len(inp_str)

            elif msg_type == "user":
                message = entry.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    block_type = block.get("type", "unknown")
                    if block_type == "tool_result":
                        tool_use_id = block.get("tool_use_id", "")
                        content_inner = block.get("content", "")
                        # Try to extract tool name from inner content structure
                        # Claude wraps tool results differently
                        if isinstance(content_inner, str) and content_inner:
                            key = "tool_result/unknown"
                            content_by_category[key].append(content_inner)
                            entries_by_type[key]["count"] += 1
                            entries_by_type[key]["bytes"] += len(content_inner.encode("utf-8"))
                            entries_by_type[key]["chars"] += len(content_inner)
                        elif isinstance(content_inner, list):
                            for sub in content_inner:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    text = sub.get("text", "")
                                    if text:
                                        key = "tool_result/unknown"
                                        content_by_category[key].append(text)
                                        entries_by_type[key]["count"] += 1
                                        entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                                        entries_by_type[key]["chars"] += len(text)
                    elif block_type == "text":
                        text = block.get("text", "")
                        if text:
                            key = "user/text"
                            content_by_category[key].append(text)
                            entries_by_type[key]["count"] += 1
                            entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                            entries_by_type[key]["chars"] += len(text)

            elif msg_type == "system":
                # System messages are in the first few lines
                text = entry.get("message", "")
                if isinstance(text, str) and text:
                    key = "system"
                    content_by_category[key].append(text)
                    entries_by_type[key]["count"] += 1
                    entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                    entries_by_type[key]["chars"] += len(text)

    return entries_by_type, content_by_category


def parse_claude_session_v2(jsonl_path: str):
    """Parse Claude JSONL with tool name resolution from preceding assistant messages."""
    # First pass: build tool_use_id -> tool_name mapping
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
                    if block.get("type") == "tool_use":
                        tool_id = block.get("id", "")
                        name = block.get("name", "unknown")
                        if tool_id:
                            tool_use_id_to_name[tool_id] = name

    # Second pass: extract with tool name resolution
    entries_by_type = defaultdict(lambda: {"count": 0, "bytes": 0, "chars": 0})
    content_by_category = defaultdict(list)

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = entry.get("type", "unknown")

            if msg_type == "assistant":
                message = entry.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    if isinstance(block, str):
                        # Plain string block (rare but valid)
                        key = "assistant/text"
                        content_by_category[key].append(block)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(block.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(block)
                        continue
                    block_type = block.get("type", "unknown")
                    if block_type == "text":
                        text = block.get("text", "")
                        if text:
                            key = "assistant/text"
                            content_by_category[key].append(text)
                            entries_by_type[key]["count"] += 1
                            entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                            entries_by_type[key]["chars"] += len(text)
                    elif block_type == "thinking":
                        text = block.get("thinking", "")
                        if text:
                            key = "assistant/thinking"
                            content_by_category[key].append(text)
                            entries_by_type[key]["count"] += 1
                            entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                            entries_by_type[key]["chars"] += len(text)
                    elif block_type == "tool_use":
                        name = block.get("name", "unknown")
                        inp = block.get("input", {})
                        inp_str = json.dumps(inp) if inp else ""
                        if inp_str:
                            key = f"tool_call_args/{name}"
                            content_by_category[key].append(inp_str)
                            entries_by_type[key]["count"] += 1
                            entries_by_type[key]["bytes"] += len(inp_str.encode("utf-8"))
                            entries_by_type[key]["chars"] += len(inp_str)

            elif msg_type == "user":
                message = entry.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    if isinstance(block, str):
                        # Plain string block
                        key = "user/text"
                        content_by_category[key].append(block)
                        entries_by_type[key]["count"] += 1
                        entries_by_type[key]["bytes"] += len(block.encode("utf-8"))
                        entries_by_type[key]["chars"] += len(block)
                        continue
                    block_type = block.get("type", "unknown")
                    if block_type == "tool_result":
                        tool_use_id = block.get("tool_use_id", "")
                        tool_name = tool_use_id_to_name.get(tool_use_id, "unknown")
                        content_inner = block.get("content", "")
                        if isinstance(content_inner, str) and content_inner:
                            key = f"tool_result/{tool_name}"
                            content_by_category[key].append(content_inner)
                            entries_by_type[key]["count"] += 1
                            entries_by_type[key]["bytes"] += len(content_inner.encode("utf-8"))
                            entries_by_type[key]["chars"] += len(content_inner)
                        elif isinstance(content_inner, list):
                            for sub in content_inner:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    text = sub.get("text", "")
                                    if text:
                                        key = f"tool_result/{tool_name}"
                                        content_by_category[key].append(text)
                                        entries_by_type[key]["count"] += 1
                                        entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                                        entries_by_type[key]["chars"] += len(text)
                                elif isinstance(sub, str):
                                    key = f"tool_result/{tool_name}"
                                    content_by_category[key].append(sub)
                                    entries_by_type[key]["count"] += 1
                                    entries_by_type[key]["bytes"] += len(sub.encode("utf-8"))
                                    entries_by_type[key]["chars"] += len(sub)
                    elif block_type == "text":
                        text = block.get("text", "")
                        if text:
                            key = "user/text"
                            content_by_category[key].append(text)
                            entries_by_type[key]["count"] += 1
                            entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                            entries_by_type[key]["chars"] += len(text)

            elif msg_type == "system":
                text = str(entry.get("message", ""))
                if isinstance(text, str) and text:
                    key = "system"
                    content_by_category[key].append(text)
                    entries_by_type[key]["count"] += 1
                    entries_by_type[key]["bytes"] += len(text.encode("utf-8"))
                    entries_by_type[key]["chars"] += len(text)

    return entries_by_type, content_by_category


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

def count_tokens_for_category(content_chunks, encoding, max_chunks=None):
    """Count tokens for a list of content strings using the given encoding."""
    total_tokens = 0
    total_bytes = 0
    total_chars = 0
    count = 0

    chunks = content_chunks if max_chunks is None else content_chunks[:max_chunks]

    for text in chunks:
        try:
            tokens = len(encoding.encode(text))
        except Exception:
            # Fallback: estimate at ~4 chars/token for English text
            tokens = len(text) // 4

        total_tokens += tokens
        total_bytes += len(text.encode("utf-8"))
        total_chars += len(text)
        count += 1

    return total_tokens, total_bytes, total_chars, count


# ---------------------------------------------------------------------------
# Content type classification for chars/token analysis
# ---------------------------------------------------------------------------

def classify_content_type(key: str, sample_text: str = "") -> str:
    """Classify a content category into a type for chars/token analysis."""
    key_lower = key.lower()

    if "view_image" in key_lower or "base64" in key_lower:
        return "base64/image"
    if any(k in key_lower for k in ["read_file", "read", "cat", "head"]):
        return "source_code"
    if any(k in key_lower for k in ["bash", "shell", "command", "run_command"]):
        return "cli_output"
    if any(k in key_lower for k in ["grep", "search", "rg", "glob"]):
        return "search_results"
    if any(k in key_lower for k in ["edit", "write", "patch"]):
        return "edit_content"
    if any(k in key_lower for k in ["log", "tail"]):
        return "log_output"
    if any(k in key_lower for k in ["json", "api", "http"]):
        return "json_api"
    if "test" in key_lower:
        return "test_output"
    if "session_meta" in key_lower:
        return "system_prompt"
    if "thinking" in key_lower:
        return "thinking"
    if "assistant" in key_lower or "agent_message" in key_lower:
        return "model_prose"
    if "user" in key_lower:
        return "user_text"
    if "compacted" in key_lower:
        return "compacted"
    if "mcp_result" in key_lower:
        # Check sample for base64
        if sample_text and len(sample_text) > 100 and "=" in sample_text[:200]:
            return "base64/image"
        return "json_api"

    return "other"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(session_name, entries_by_type, content_by_category, encodings,
                 top_n=25, max_chunks_per_category=500):
    """Print a token-level analysis report."""

    print(f"\n{'='*80}")
    print(f"TOKEN-LEVEL CORPUS ANALYSIS: {session_name}")
    print(f"{'='*80}")

    all_categories = sorted(entries_by_type.keys())

    # Per-category token counts for each encoding
    results = {}
    for enc_name, encoding in encodings.items():
        results[enc_name] = {}
        total_tokens = 0
        total_bytes = 0
        total_chars = 0

        for cat in all_categories:
            chunks = content_by_category.get(cat, [])
            # Limit chunks to avoid spending too long on huge categories
            if len(chunks) > max_chunks_per_category:
                # Sample evenly
                step = len(chunks) / max_chunks_per_category
                sampled = [chunks[int(i * step)] for i in range(max_chunks_per_category)]
                chunks = sampled
                sampled_note = f" (sampled {max_chunks_per_category}/{len(content_by_category.get(cat, []))})"
            else:
                sampled_note = ""

            tokens, bytes_, chars, count = count_tokens_for_category(chunks, encoding)
            results[enc_name][cat] = {
                "tokens": tokens,
                "bytes": bytes_,
                "chars": chars,
                "count": count,
                "chars_per_token": chars / tokens if tokens > 0 else 0,
                "bytes_per_token": bytes_ / tokens if tokens > 0 else 0,
                "sampled_note": sampled_note,
            }
            total_tokens += tokens
            total_bytes += bytes_
            total_chars += chars

        results[enc_name]["__total__"] = {
            "tokens": total_tokens,
            "bytes": total_bytes,
            "chars": total_chars,
        }

    # Print per-encoding reports
    for enc_name in encodings:
        print(f"\n--- Encoding: {enc_name} ---")
        total = results[enc_name]["__total__"]
        total_tokens = total["tokens"]
        total_bytes = total["bytes"]

        print(f"Total: {total_tokens:,} tokens, {total_bytes:,} bytes ({total_bytes/1024/1024:.1f} MB)")
        print(f"Average chars/token: {total['chars']/total_tokens:.2f}" if total_tokens else "N/A")
        print()

        # Sort categories by token count descending
        cat_data = [(cat, results[enc_name][cat]) for cat in all_categories]
        cat_data.sort(key=lambda x: x[1]["tokens"], reverse=True)

        print(f"{'Category':<45} {'Calls':>6} {'Tokens':>12} {'%T':>6} {'Bytes':>12} {'%B':>6} {'C/T':>6} {'Type':<15}")
        print("-" * 120)

        for cat, data in cat_data[:top_n]:
            pct_tokens = 100 * data["tokens"] / total_tokens if total_tokens else 0
            pct_bytes = 100 * data["bytes"] / total_bytes if total_bytes else 0
            cpt = data["chars_per_token"]
            content_type = classify_content_type(cat,
                content_by_category.get(cat, [""])[0][:200] if content_by_category.get(cat) else "")
            sample_note = data.get("sampled_note", "")

            print(f"{cat:<45} {data['count']:>6} {data['tokens']:>12,} {pct_tokens:>5.1f}% {data['bytes']:>12,} {pct_bytes:>5.1f}% {cpt:>5.2f} {content_type:<15}{sample_note}")

    # Cross-encoding comparison: where do byte% and token% diverge?
    if len(encodings) > 1:
        print(f"\n{'='*80}")
        print("BYTE vs TOKEN DIVERGENCE ANALYSIS")
        print(f"{'='*80}")
        print(f"{'Category':<45} {'Byte%':>7} {'Token%(cl100k)':>14} {'Token%(o200k)':>13} {'Delta':>7} {'C/T(cl)':>8} {'C/T(o2)':>8}")
        print("-" * 120)

        # Use first encoding as reference for byte%
        ref_enc = list(encodings.keys())[0]
        total_bytes = results[ref_enc]["__total__"]["bytes"]

        cat_data = [(cat, results[ref_enc][cat]) for cat in all_categories]
        cat_data.sort(key=lambda x: x[1]["bytes"], reverse=True)

        for cat, data in cat_data[:top_n]:
            pct_bytes = 100 * data["bytes"] / total_bytes if total_bytes else 0

            pct_tokens_cl = 0
            pct_tokens_o2 = 0
            cpt_cl = 0
            cpt_o2 = 0

            if "cl100k_base" in results and cat in results["cl100k_base"]:
                d = results["cl100k_base"][cat]
                total_t = results["cl100k_base"]["__total__"]["tokens"]
                pct_tokens_cl = 100 * d["tokens"] / total_t if total_t else 0
                cpt_cl = d["chars_per_token"]

            if "o200k_base" in results and cat in results["o200k_base"]:
                d = results["o200k_base"][cat]
                total_t = results["o200k_base"]["__total__"]["tokens"]
                pct_tokens_o2 = 100 * d["tokens"] / total_t if total_t else 0
                cpt_o2 = d["chars_per_token"]

            # Delta: token% minus byte% (positive = more tokens than bytes would suggest)
            delta = pct_tokens_cl - pct_bytes

            print(f"{cat:<45} {pct_bytes:>6.1f}% {pct_tokens_cl:>13.1f}% {pct_tokens_o2:>12.1f}% {delta:>+6.1f} {cpt_cl:>7.2f} {cpt_o2:>7.2f}")

    # Content-type aggregation
    print(f"\n{'='*80}")
    print("CONTENT-TYPE AGGREGATION (chars/token by type)")
    print(f"{'='*80}")

    type_stats = defaultdict(lambda: {"tokens": 0, "bytes": 0, "chars": 0, "count": 0, "categories": 0})
    ref_enc_name = list(encodings.keys())[0]

    for cat in all_categories:
        data = results[ref_enc_name][cat]
        sample_text = content_by_category.get(cat, [""])[0][:200] if content_by_category.get(cat) else ""
        ctype = classify_content_type(cat, sample_text)

        type_stats[ctype]["tokens"] += data["tokens"]
        type_stats[ctype]["bytes"] += data["bytes"]
        type_stats[ctype]["chars"] += data["chars"]
        type_stats[ctype]["count"] += data["count"]
        type_stats[ctype]["categories"] += 1

    total_tokens = results[ref_enc_name]["__total__"]["tokens"]

    type_data = sorted(type_stats.items(), key=lambda x: x[1]["tokens"], reverse=True)
    print(f"\n{'Content Type':<20} {'Tokens':>12} {'%T':>7} {'Bytes':>12} {'%B':>7} {'C/T':>6} {'Calls':>8} {'Cats':>5}")
    print("-" * 90)
    for ctype, stats in type_data:
        pct_t = 100 * stats["tokens"] / total_tokens if total_tokens else 0
        total_b = results[ref_enc_name]["__total__"]["bytes"]
        pct_b = 100 * stats["bytes"] / total_b if total_b else 0
        cpt = stats["chars"] / stats["tokens"] if stats["tokens"] else 0
        delta = pct_t - pct_b
        print(f"{ctype:<20} {stats['tokens']:>12,} {pct_t:>6.1f}% {stats['bytes']:>12,} {pct_b:>6.1f}% {cpt:>5.2f} {stats['count']:>8} {stats['categories']:>5}  delta={delta:+.1f}")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Token-level corpus analysis for archolith-filter")
    parser.add_argument("--codex", nargs="*", help="Codex JSONL session files")
    parser.add_argument("--claude", nargs="*", help="Claude JSONL session files")
    parser.add_argument("--all", action="store_true", help="Analyze all known session files")
    parser.add_argument("--top", type=int, default=30, help="Top N categories to show (default 30)")
    parser.add_argument("--max-chunks", type=int, default=500,
                        help="Max chunks per category to tokenize (default 500, for speed)")
    args = parser.parse_args()

    encodings = get_encodings()

    # Default session files
    codex_files = args.codex or []
    claude_files = args.claude or []

    if args.all:
        codex_dir = Path(r"C:\Users\thron\.codex\sessions")
        claude_dir = Path(r"C:\Users\thron\.claude\projects\C--Users-thron-IdeaProjects")

        if codex_dir.exists():
            codex_files = sorted(codex_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_size, reverse=True)[:5]
            codex_files = [str(f) for f in codex_files]

        if claude_dir.exists():
            claude_files = sorted(claude_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_size, reverse=True)[:2]
            claude_files = [str(f) for f in claude_files]

    for path in codex_files:
        print(f"\nParsing Codex session: {path}")
        entries, content = parse_codex_session_v2(path)
        session_name = Path(path).stem[:60]
        print_report(session_name, entries, content, encodings, top_n=args.top,
                     max_chunks_per_category=args.max_chunks)

    for path in claude_files:
        print(f"\nParsing Claude session: {path}")
        entries, content = parse_claude_session_v2(path)
        session_name = Path(path).stem[:60]
        print_report(session_name, entries, content, encodings, top_n=args.top,
                     max_chunks_per_category=args.max_chunks)


if __name__ == "__main__":
    main()
