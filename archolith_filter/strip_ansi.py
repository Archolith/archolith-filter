"""Strip ANSI escape sequences from terminal output.

Handles CSI (color/style), OSC (title), and other common escape sequences.
"""

import re

# CSI sequences: ESC [ followed by parameter bytes (digits/semicolons) and a final letter.
_CSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# OSC sequences: ESC ] followed by text until BEL (\x07) or ST (ESC \).
_OSC_RE = re.compile(r"\x1b\](?:[^\x07]|\x1b(?=\\))*\x07|\x1b\].*?\x1b\\")

# Other ESC sequences: charset designators ESC (, ), *, + followed by a
# character; ESC #, >, = ; the single-character controls ESC 6/7/8/9 (DECBI,
# DECSC, DECRC, DECFI); and ESC \ (string terminator).
# The designator class previously listed only "(" although the comment claimed
# all four.
_ESC_MISC_RE = re.compile(r"\x1b[()*+][B0UK]|\x1b[>#=6789]|\x1b\\\\")

# 8-bit CSI: \x9b followed by parameter bytes and a final letter.
_CSI_8BIT_RE = re.compile(r"\x9b[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """Strip all ANSI escape sequences from a string."""
    text = _OSC_RE.sub("", text)
    text = _CSI_RE.sub("", text)
    text = _ESC_MISC_RE.sub("", text)
    text = _CSI_8BIT_RE.sub("", text)
    return text
