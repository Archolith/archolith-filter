"""Tests for archolith_rtk.normalize — runtime noise normalization."""

from archolith_rtk.normalize import normalize_runtime_noise


class TestTimestampNormalization:
    def test_iso_timestamp_replaced(self):
        text = "2026-05-27T14:30:00Z request started"
        result = normalize_runtime_noise(text)
        assert "[TIMESTAMP]" in result
        assert "2026-05-27T14:30:00Z" not in result

    def test_iso_timestamp_with_millis_replaced(self):
        text = "2026-05-27T14:30:00.123Z event"
        result = normalize_runtime_noise(text)
        assert "[TIMESTAMP]" in result

    def test_iso_timestamp_with_offset_replaced(self):
        text = "2026-05-27T14:30:00+00:00 event"
        result = normalize_runtime_noise(text)
        assert "[TIMESTAMP]" in result

    def test_bracketed_iso_timestamp_replaced(self):
        text = "[2026-05-27T14:30:00.123Z] INFO message"
        result = normalize_runtime_noise(text)
        assert "[TIMESTAMP]" in result

    def test_space_separated_datetime_replaced(self):
        text = "2026-05-27 14:30:00 INFO message"
        result = normalize_runtime_noise(text)
        assert "[TIMESTAMP]" in result

    def test_clf_timestamp_replaced(self):
        text = '27/May/2026:14:30:00 +0000 "GET / HTTP/1.1"'
        result = normalize_runtime_noise(text)
        assert "[TIMESTAMP]" in result

    def test_year_only_not_replaced(self):
        """A year by itself is NOT a timestamp."""
        text = "year: 2026"
        result = normalize_runtime_noise(text)
        assert "2026" in result

    def test_version_date_not_replaced(self):
        text = "version: 2026.05"
        result = normalize_runtime_noise(text)
        assert "2026.05" in result

    def test_short_time_not_replaced(self):
        """10:30 AM without full date is NOT replaced."""
        text = "meeting at 10:30 AM"
        result = normalize_runtime_noise(text)
        assert "10:30 AM" in result


class TestPIDNormalization:
    def test_pid_with_space(self):
        text = "Server started PID 29482"
        result = normalize_runtime_noise(text)
        assert "[PID]" in result
        assert "29482" not in result

    def test_pid_with_equals(self):
        text = "pid=12345 running"
        result = normalize_runtime_noise(text)
        assert "[PID]" in result

    def test_pid_with_colon(self):
        text = "PID: 54321 started"
        result = normalize_runtime_noise(text)
        assert "[PID]" in result

    def test_pid_case_insensitive(self):
        text = "process Pid 11111 started"
        result = normalize_runtime_noise(text)
        assert "[PID]" in result


class TestElapsedTimeNormalization:
    def test_milliseconds_replaced(self):
        text = "completed in 42ms"
        result = normalize_runtime_noise(text)
        assert "[X]ms" in result
        assert "42ms" not in result

    def test_decimal_milliseconds_replaced(self):
        text = "latency: 4.234ms"
        result = normalize_runtime_noise(text)
        assert "[X]ms" in result

    def test_seconds_replaced(self):
        text = "build took 1.5s"
        result = normalize_runtime_noise(text)
        assert "[X]s" in result
        assert "1.5s" not in result

    def test_integer_seconds_replaced(self):
        text = "timeout after 30s"
        result = normalize_runtime_noise(text)
        assert "[X]s" in result


class TestMemorySizeNormalization:
    def test_mb_replaced(self):
        text = "heap used 512 MB"
        result = normalize_runtime_noise(text)
        assert "[X]SIZE" in result
        assert "512 MB" not in result

    def test_gb_replaced(self):
        text = "allocated 1.234 GB"
        result = normalize_runtime_noise(text)
        assert "[X]SIZE" in result

    def test_kb_replaced(self):
        text = "cache 2048 KB"
        result = normalize_runtime_noise(text)
        assert "[X]SIZE" in result

    def test_tb_replaced(self):
        text = "storage 2 TB"
        result = normalize_runtime_noise(text)
        assert "[X]SIZE" in result

    def test_case_insensitive(self):
        text = "used 512 mb"
        result = normalize_runtime_noise(text)
        assert "[X]SIZE" in result


class TestMixedContent:
    def test_timestamp_pid_and_message(self):
        text = "2026-05-27T14:30:00Z [INFO] PID 29482 request started in 42ms using 512 MB"
        result = normalize_runtime_noise(text)
        assert "[TIMESTAMP]" in result
        assert "[PID]" in result
        assert "[X]ms" in result
        assert "[X]SIZE" in result

    def test_no_runtime_noise_unchanged(self):
        text = "Hello world, nothing to normalize here."
        result = normalize_runtime_noise(text)
        assert result == text

    def test_empty_string(self):
        assert normalize_runtime_noise("") == ""
