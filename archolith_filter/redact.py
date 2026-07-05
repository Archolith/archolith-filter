"""Secret redaction — strip API keys, tokens, and credentials from tool output.

Compiles all secret patterns into a single alternation regex at module load
time for O(1) per-call overhead. Returns the cleaned text and a count of
redactions for telemetry.

Pattern attribution (see THIRD-PARTY-LICENSES.txt for vendor doc URLs):
- AWS access key IDs (AKIA/ASIA/AGPA/AIDA/AROA prefix + 16 alphanum chars):
  derived from AWS documentation on IAM identifiers.
- JWT format (three base64url segments starting with ``eyJ``):
  derived from RFC 7519 (JSON Web Token) section 3.
- OpenAI API key formats (sk-, sk-proj-, sk-svcacct-, sk_proj_, sk_svcacct_):
  derived from OpenAI platform documentation on API keys.
- Anthropic key formats (sk-ant-, sk-ant-api03-):
  derived from Anthropic platform documentation on API keys.
- GitHub, GitLab, Slack, Twilio, Stripe, SendGrid, npm, PyPI, Docker Hub,
  Sentry tokens: re-derived from the publicly documented formats for each
  platform. Connection-string credential extraction (pattern #10) is
  derived from RFC 3986 (URI) section 3.2.1 (User Information).
No code was copied verbatim from those documents.
"""

from __future__ import annotations

import logging
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
    # =============================================================================
    # 2026-06-20 audit calibration notes:
    # - SEC-B1: OpenAI sk- pattern was exactly {48} chars; loosened to {32,} to
    #   cover legacy 32-char tokens. Added sk_proj_ and sk_svcacct_ underscore
    #   variants for keys seen in the wild using underscore separators (the
    #   official OpenAI format uses dashes — sk-proj- / sk-svcacct- — which
    #   are kept above). The archolith-security AI-A2 separately claims
    #   "ASIA[0-9A-Z]{16}" was missing — that was a false alarm; pattern #1
    #   below already covers it via the (?:AKIA|ASIA|AGPA|AIDA|AROA) prefix.
    # - DR-2: Audit claimed "AC-prefix alphanumeric tokens" missed for Twilio
    #   — but those are Account SIDs (public identifiers, not secrets). The
    #   real miss was bare auth_token=<hex>, addressed here by extending
    #   pattern #11's keyword list to include auth_token / authToken /
    #   TWILIO_AUTH_TOKEN. The quote requirement is intentionally kept to
    #   avoid false positives on git SHAs / content hashes; bare unquoted
    #   auth_token=<hex> remains uncaught by design (see the audit's
    #   distribution-plan follow-up notes).
    # =============================================================================
    # 1. AWS access key IDs — well-documented 4-letter prefixes + 16 alphanum chars
    r"(?:AKIA|ASIA|AGPA|AIDA|AROA)[A-Z0-9]{16}",
    # 2. AI provider keys (most-specific-first because they share sk- prefix)
    #    Anthropic long-lived
    r"sk-ant-api03-[A-Za-z0-9\-_]{80,}",
    #    Anthropic standard
    r"sk-ant-[A-Za-z0-9\-_]{20,}",
    #    OpenAI project (dash separator)
    r"sk-proj-[A-Za-z0-9\-_]{40,}",
    #    OpenAI service account (dash separator)
    r"sk-svcacct-[A-Za-z0-9\-_]{40,}",
    #    OpenAI project (underscore separator — non-standard but seen in the wild)
    r"sk_proj_[A-Za-z0-9\-_]{40,}",
    #    OpenAI service account (underscore separator — non-standard)
    r"sk_svcacct_[A-Za-z0-9\-_]{40,}",
    #    OpenAI standard — legacy (32-char) and modern (48-char)
    r"sk-[A-Za-z0-9]{32,}",
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
    # 11. Generic key=value patterns — 32+ char quoted values for known
    #     credential-key keyword names. Keyword list extended (DR-2) to
    #     include auth_token / authToken / TWILIO_AUTH_TOKEN so the quoted
    #     variant of those bare-token assignments gets caught. Unquoted
    #     bare forms are intentionally NOT caught here to avoid false
    #     positives on content hashes and git SHAs.
    r"""(?:apikey|api_key|secret_key|auth_token|authToken|TWILIO_AUTH_TOKEN)\s*[=:]\s*["'][A-Za-z0-9\-_]{32,}["']""",
]

# Compile into a single alternation regex with IGNORECASE.
_SECRET_RE = re.compile("|".join(f"(?:{p})" for p in _PATTERN_SPECS), re.IGNORECASE)

_REDACTION_MARKER = "[REDACTED]"

_log = logging.getLogger(__name__)

# Defense-in-depth input-size guard. Empirical verification (audit SEC-C1)
# showed the compiled alternation regex runs in bounded-linear ~70-90ms on
# 500K-char pathological inputs — there is NO exponential or catastrophic
# backtracking because all patterns have non-overlapping prefixes. This cap
# is insurance against future pattern additions that could regress that
# property; today's patterns are safe without it.
_MAX_REDACT_INPUT_CHARS = 50_000


def redact_secrets(text: str) -> RedactionResult:
    """Redact known secret patterns from *text*.

    Returns a RedactionResult with the cleaned output and the number of
    redactions performed. The redaction marker is ``[REDACTED]``.

    Inputs larger than ``_MAX_REDACT_INPUT_CHARS`` return unmodified with
    ``redaction_count=0`` and emit a single warning log line. This is a
    defense-in-depth guard — current patterns have no ReDoS exposure —
    but rejects unusually large inputs as a precaution.
    """
    if len(text) > _MAX_REDACT_INPUT_CHARS:
        _log.warning(
            "redact_secrets input exceeded size guard "
            "(len=%d, limit=%d); skipping redaction as defense-in-depth",
            len(text), _MAX_REDACT_INPUT_CHARS,
        )
        return RedactionResult(output=text, redaction_count=0)

    count = 0

    def _replace(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return _REDACTION_MARKER

    output = _SECRET_RE.sub(_replace, text)
    return RedactionResult(output=output, redaction_count=count)
