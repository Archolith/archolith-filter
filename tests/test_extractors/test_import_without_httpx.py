"""Import-time dependency checks for optional extractor runtime deps."""

from __future__ import annotations

import subprocess
import sys
import textwrap


def test_extractors_import_when_httpx_is_unavailable() -> None:
    """Extractor modules should import without the optional httpx runtime extra."""
    code = textwrap.dedent(
        """
        import importlib.abc
        import sys

        class BlockHttpx(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "httpx" or fullname.startswith("httpx."):
                    raise ImportError("blocked httpx import")
                return None

        sys.meta_path.insert(0, BlockHttpx())

        from archolith_filter.extractors.bash import BashFilterExtractor
        from archolith_filter.extractors.read_file import ReadFileFilterExtractor

        assert BashFilterExtractor.tool_names
        assert ReadFileFilterExtractor.tool_names
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
