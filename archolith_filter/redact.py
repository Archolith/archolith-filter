"""Secret redaction — strip API keys, tokens, and credentials from tool output.

Compiles all secret patterns into a single alternation regex at module load
time for O(1) per-call overhead. Returns the cleaned text and a count of
redactions for telemetry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionResult:
    """Result of secret redaction pass."""

    output: str
    redaction_count: int


# ── Pattern categories ──────────────────────────────────────────────────
# Each pattern is a raw regex string. They are joined into a single
# alternation and compiled once at module load. Order matters where prefixes
# overlap (e.g., sk-ant-api03- before sk-ant- before sk-).

_PATTERN_SPECS: list[str] = [
    # 1. AWS access key IDs — well-documented 4-letter prefixes + 16 alphanum chars
    r"(?:AKIA|ASIA|AGPA|AIDA|AROA)[A-Z0-9]{16}",
    # 2. AI provider keys (most-specific-first because they share sk- prefix)
    #    Anthropic long-lived
    r"sk-ant-api03-[A-Za-z0-9\-_]{80,}",
    #    Anthropic standard
    r"sk-ant-[A-Za-z0-9\-_]{20,}",
    #    OpenAI project
    r"sk-proj-[A-Za-z0-9\-_]{40,}",
    #    OpenAI service account
    r"sk-svcacct-[A-Za-z0-9\-_]{40,}",
    #    OpenAI standard (exactly 48 alphanum after sk-)
    r"sk-[A-Za-z0-9]{48}",
    # 3. VCS tokens
    #    GitHub fine-grained PAT
    r"github_pat_[A-Za-z0-9_]{36,}",
    #    GitHub classic PAT
    r"gh[pousr]_[A-Za-z0-9_]{36,}",
    #    GitLab PAT
    r"glpat-[A-Za-z0-9\-_]{20,}",
    # 4. Payment keys — Stripe
    r"(?:sk_live|rk_live|pk_live)_[A-Za-z0-9]{24,}",
    # 5. SaaS tokens
    #    Slack bot/user tokens
    r"xox[baprs]-[A-Za-z0-9\-]{10,}",
    #    Slack webhook URLs (full URL redacted)
    r"https://hooks\.slack\.com/services/T[A-Z0-9]{8,}/B[A-Z0-9]{8,}/[A-Za-z0-9]{24,}",
    #    SendGrid API key (three-segment format: SG.x.y)
    r"SG\.[A-Za-z0-9\-_]{22,}\.[A-Za-z0-9\-_]{43,}",
    #    Twilio auth token (key=value with 32 hex chars)
    r"twilio[^=]*=\s*[a-f0-9]{32}\b",
    # 6. Package registry tokens
    #    npm
    r"npm_[A-Za-z0-9]{36,}",
    #    PyPI
    r"pypi-[A-Za-z0-9_\-]{20,}",
    #    Docker Hub
    r"dckr_pat_[A-Za-z0-9\-_]{20,}",
    # 7. Observability — Sentry DSN (URL with embedded hex key)
    r"https://[a-f0-9]+@sentry\.io/[0-9]+",
    # 8. JWTs — three base64url segments starting with eyJ
    r"eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+",
    # 9. Private key headers (begin marker only — PEM body already handled by read_file filter)
    r"-----BEGIN\s+(?:[A-Z0-9]+\s+)?PRIVATE\s+KEY-----",
    # 10. Connection strings — redact only the user:pass credential, preserving
    #     scheme, host, database, and query params for diagnostic context.
    #     Handles empty-username form (e.g. redis://:password@host).
    r"""(?<=://)[^\s:@/"']*:[^\s@/"']+(?=@)""",
    # 11. Generic key=value patterns — 32+ char quoted values for apikey/api_key/secret_key
    r"""(?:apikey|api_key|secret_key)\s*[=:]\s*["'][A-Za-z0-9\-_]{32,}["']""",
]

# Compile into a single alternation regex with IGNORECASE.
_SECRET_RE = re.compile("|".join(f"(?:{p})" for p in _PATTERN_SPECS), re.IGNORECASE)

_REDACTION_MARKER = "[REDACTED]"


def redact_secrets(text: str) -> RedactionResult:
    """Redact known secret patterns from *text*.

    Returns a RedactionResult with the cleaned output and the number of
    redactions performed. The redaction marker is ``[REDACTED]``.
    """
    count = 0

    def _replace(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return _REDACTION_MARKER

    output = _SECRET_RE.sub(_replace, text)
    return RedactionResult(output=output, redaction_count=count)
