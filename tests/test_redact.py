"""Tests for archolith_rtk.redact — secret redaction module."""

from archolith_rtk.redact import redact_secrets


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
