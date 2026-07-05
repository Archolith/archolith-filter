"""Tests for archolith_filter.redact — secret redaction module."""

from archolith_filter.redact import redact_secrets


class TestRedactSecrets:
    # ── Pattern 1: AWS access key IDs ──

    def test_aws_akia_key_redacted(self):
        result = redact_secrets("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
        assert "[REDACTED]" in result.output
        assert "AKIAIOSFODNN7EXAMPLE" not in result.output
        assert result.redaction_count >= 1

    def test_aws_asia_key_redacted(self):
        result = redact_secrets("key: ASIAIOSFODNN7EXAMPLE12")
        assert "[REDACTED]" in result.output

    def test_aws_key_too_short_not_redacted(self):
        # 15 chars after prefix instead of 16 — should NOT match.
        result = redact_secrets("fake=AKIAIOSFODNN7EXAMP")
        assert result.redaction_count == 0

    # ── Pattern 2: AI provider keys ──

    def test_anthropic_long_lived_redacted(self):
        key = "sk-ant-api03-" + "a" * 82
        result = redact_secrets(f"ANTHROPIC_KEY={key}")
        assert "[REDACTED]" in result.output
        assert "sk-ant-api03-" not in result.output

    def test_anthropic_standard_redacted(self):
        key = "sk-ant-" + "b" * 22
        result = redact_secrets(f"key={key}")
        assert "[REDACTED]" in result.output

    def test_openai_project_key_redacted(self):
        key = "sk-proj-" + "c" * 42
        result = redact_secrets(f"OPENAI={key}")
        assert "[REDACTED]" in result.output

    def test_openai_standard_key_redacted(self):
        key = "sk-" + "d" * 48
        result = redact_secrets(f"key={key}")
        assert "[REDACTED]" in result.output

    def test_sk_prefix_specificity(self):
        """sk-ant-api03- should match before sk-ant-."""
        key = "sk-ant-api03-" + "a" * 82
        result = redact_secrets(f"key={key}")
        assert result.redaction_count >= 1

    # ── Pattern 3: VCS tokens ──

    def test_github_pat_redacted(self):
        key = "github_pat_" + "e" * 38
        result = redact_secrets(f"GH_PAT={key}")
        assert "[REDACTED]" in result.output

    def test_github_classic_pat_redacted(self):
        key = "ghp_" + "f" * 38
        result = redact_secrets(f"GH={key}")
        assert "[REDACTED]" in result.output

    def test_gitlab_pat_redacted(self):
        key = "glpat-" + "g" * 22
        result = redact_secrets(f"GL={key}")
        assert "[REDACTED]" in result.output

    # ── Pattern 4: Payment keys ──

    def test_stripe_live_key_redacted(self):
        key = "sk_live_" + "h" * 26
        result = redact_secrets(f"STRIPE={key}")
        assert "[REDACTED]" in result.output

    # ── Pattern 5: SaaS tokens ──

    def test_slack_bot_token_redacted(self):
        key = "xoxb-1234567890-abcdefghij"
        result = redact_secrets(f"SLACK={key}")
        assert "[REDACTED]" in result.output

    def test_sendgrid_key_redacted(self):
        key = "SG." + "a" * 24 + "." + "b" * 45
        result = redact_secrets(f"SENDGRID={key}")
        assert "[REDACTED]" in result.output

    # ── Pattern 6: Package registry tokens ──

    def test_npm_token_redacted(self):
        key = "npm_" + "c" * 38
        result = redact_secrets(f"NPM_TOKEN={key}")
        assert "[REDACTED]" in result.output

    def test_pypi_token_redacted(self):
        key = "pypi-" + "d" * 22
        result = redact_secrets(f"PYPI={key}")
        assert "[REDACTED]" in result.output

    # ── Pattern 7: Observability ──

    def test_sentry_dsn_redacted(self):
        dsn = "https://abc123def456@sentry.io/12345"
        result = redact_secrets(f"SENTRY_DSN={dsn}")
        assert "[REDACTED]" in result.output

    # ── Pattern 8: JWTs ──

    def test_jwt_redacted(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456"
        result = redact_secrets(f"token={jwt}")
        assert "[REDACTED]" in result.output

    # ── Pattern 9: Private key headers ──

    def test_private_key_header_redacted(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA..."
        result = redact_secrets(text)
        assert "PRIVATE KEY" not in result.output or "[REDACTED]" in result.output

    # ── Pattern 10: Connection strings ──

    def test_mongodb_connection_string_redacted(self):
        cs = "mongodb://admin:secretpass@prod-db.example.com:27017/mydb"
        result = redact_secrets(f"DB_URL={cs}")
        assert "[REDACTED]" in result.output

    def test_postgres_connection_string_redacted(self):
        cs = "postgres://user:pass@localhost:5432/mydb"
        result = redact_secrets(f"DATABASE_URL={cs}")
        assert "[REDACTED]" in result.output

    def test_redis_connection_string_redacted(self):
        cs = "redis://:password@redis.example.com:6379/0"
        result = redact_secrets(f"REDIS_URL={cs}")
        assert "[REDACTED]" in result.output

    # ── Pattern 11: Generic key=value (32+ char) ──

    def test_api_key_32plus_chars_redacted(self):
        result = redact_secrets(f'api_key: "{"a" * 34}"')
        assert "[REDACTED]" in result.output

    def test_secret_key_32plus_chars_redacted(self):
        result = redact_secrets(f'secret_key = "{"b" * 36}"')
        assert "[REDACTED]" in result.output

    # ── False positive guards ──

    def test_short_api_key_not_redacted(self):
        """Keys under 32 chars should NOT be redacted (false positive guard)."""
        result = redact_secrets('api_key: "test"')
        assert result.redaction_count == 0

    def test_password_not_redacted(self):
        """password patterns are deliberately excluded."""
        result = redact_secrets('password: "supersecretpasswordvalue1234567890"')
        assert result.redaction_count == 0

    # ── Mixed content ──

    def test_multiple_secrets_in_same_output(self):
        text = (
            f"AWS_KEY=AKIAIOSFODNN7EXAMPLE\n"
            f"GITHUB_PAT=github_pat_{'e' * 38}\n"
            f"DB_URL=postgres://user:pass@localhost/db"
        )
        result = redact_secrets(text)
        assert result.redaction_count >= 2
        assert "AKIA" not in result.output
        assert "github_pat_" not in result.output

    def test_secrets_in_json_values(self):
        text = f'{{"api_key": "sk-{"d" * 48}"}}'
        result = redact_secrets(text)
        assert "[REDACTED]" in result.output

    def test_secrets_in_log_lines(self):
        text = "[2026-05-27T14:30:00Z] INFO Using key AKIAIOSFODNN7EXAMPLE for auth"
        result = redact_secrets(text)
        assert "AKIA" not in result.output

    # ── Edge cases ──

    def test_empty_string(self):
        result = redact_secrets("")
        assert result.output == ""
        assert result.redaction_count == 0

    def test_no_secrets(self):
        result = redact_secrets("Hello world, this is a normal log line.")
        assert result.redaction_count == 0
        assert result.output == "Hello world, this is a normal log line."

    def test_redaction_count_accurate(self):
        text = "key1=AKIAIOSFODNN7EXAMPLE key2=AKIAIOSFODNN7EXAMPLF"
        result = redact_secrets(text)
        assert result.redaction_count == 2


# ── 2026-06-20 audit calibration: SEC-B1 + DR-2 ──────────────────────────


class TestAuditCalibration2026_06_20:
    """New patterns added in the SEC-B1 + DR-2 remediation (see
    archolith-filter-remediation-plan-2026-06-20.md Session E)."""

    # ── SEC-B1: OpenAI key variants ──

    def test_openai_legacy_32_char_redacted(self):
        """Legacy OpenAI sk- keys are 32 alphanum chars — previously missed
        because the pattern required exactly 48 chars."""
        key = "sk-" + "a" * 32
        result = redact_secrets(f"token is {key} here")
        assert "[REDACTED]" in result.output
        assert key not in result.output

    def test_openai_modern_48_char_redacted(self):
        """Modern OpenAI sk- keys are 48 alphanum chars (regression guard)."""
        key = "sk-" + "a" * 48
        result = redact_secrets(f"token is {key} here")
        assert "[REDACTED]" in result.output
        assert key not in result.output

    def test_openai_long_alphanum_redacted(self):
        """Anything >= 32 alphanums after sk- is caught (regression guard
        for the {32,} lower bound)."""
        key = "sk-" + "x" * 60
        result = redact_secrets(f"OPENAI={key}")
        assert "[REDACTED]" in result.output

    def test_openai_short_31_char_not_redacted(self):
        """Keys shorter than 32 chars after sk- are NOT redacted
        (false positive guard)."""
        key = "sk-" + "a" * 31
        result = redact_secrets(f"OPENAI={key}")
        assert "[REDACTED]" not in result.output

    def test_openai_sk_proj_underscore_redacted(self):
        """Non-standard sk_proj_ underscore variant (seen in the wild)."""
        key = "sk_proj_" + "a" * 40
        result = redact_secrets(f"OPENAI={key}")
        assert "[REDACTED]" in result.output
        assert key not in result.output

    def test_openai_sk_svcacct_underscore_redacted(self):
        """Non-standard sk_svcacct_ underscore variant (seen in the wild)."""
        key = "sk_svcacct_" + "a" * 40
        result = redact_secrets(f"OPENAI={key}")
        assert "[REDACTED]" in result.output
        assert key not in result.output

    def test_openai_dash_variants_still_redacted(self):
        """Regression guard: dash-separated variants remain caught."""
        for prefix in ("sk-proj-", "sk-svcacct-"):
            key = prefix + "z" * 42
            result = redact_secrets(f"OPENAI={key}")
            assert "[REDACTED]" in result.output, f"{prefix} variant should be redacted"

    def test_asia_aws_key_still_redacted(self):
        """Regression guard for audit's incorrect SEC-B1 claim that 'ASIA'
        was missing — pattern #1 has always covered ASIA via the prefix
        alternation."""
        result = redact_secrets("role=ASIAIOSFODNN7EXAMPLE")
        assert "[REDACTED]" in result.output
        assert "ASIAIOSFODNN7EXAMPLE" not in result.output

    # ── DR-2: keyword extension for pattern #11 ──

    def test_auth_token_quoted_redacted(self):
        """`auth_token` keyword + quoted 32-char value (bare-keyword form,
        NOT the JSON-quoted-key form) is now caught via the pattern #11
        keyword extension."""
        text = 'auth_token="' + "a" * 32 + '"'
        result = redact_secrets(text)
        assert "[REDACTED]" in result.output

    def test_authToken_camel_case_quoted_redacted(self):
        """camelCase `authToken` keyword with quoted 32+ value is caught."""
        text = 'authToken: "' + "b" * 36 + '"'
        result = redact_secrets(text)
        assert "[REDACTED]" in result.output

    def test_auth_token_in_json_dict_NOT_redacted(self):
        """Documented limitation: when the keyword is JSON-quoted
        (``{"auth_token": "..."}``), pattern #11 does NOT match because the
        regex expects the keyword bare (not wrapped in its own quotes).
        The auth_token bare-keyword form (e.g. ``auth_token="..."`` from
        dotenv / env-var files) is the supported form; JSON-quoted keys are
        deferred to a follow-up pattern revision to avoid interaction with
        the JSON redaction-prevention guards."""
        text = '{"auth_token": "' + "a" * 32 + '"}'
        result = redact_secrets(text)
        assert "[REDACTED]" not in result.output

    def test_twilio_auth_token_quoted_redacted(self):
        """`TWILIO_AUTH_TOKEN` keyword + quoted 32-char hex is caught via
        pattern #11 keyword extension."""
        text = 'TWILIO_AUTH_TOKEN="' + "f" * 32 + '"'
        result = redact_secrets(text)
        assert "[REDACTED]" in result.output

    def test_bare_auth_token_NOT_redacted_for_now(self):
        """Documented limitation: bare `auth_token = <32 hex>` without
        surrounding quotes is intentionally NOT matched to avoid false
        positives on git SHAs / content hashes. Follow-up tracked in the
        distribution plan."""
        text = "auth_token = " + "a" * 32 + " here"
        result = redact_secrets(text)
        # The keyword and bare value should both be intact.
        assert "auth_token = " in result.output
        assert "a" * 32 in result.output
        # Value not redacted — no marker.
        assert "[REDACTED]" not in result.output

    def test_short_auth_token_quoted_NOT_redacted(self):
        """False-positive guard: <32 char values not flagged even with the
        auth_token keyword."""
        text = 'auth_token: "' + "a" * 20 + '"'
        result = redact_secrets(text)
        assert "[REDACTED]" not in result.output
