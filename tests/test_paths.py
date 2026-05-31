"""Tests for archolith_rtk.paths — workspace path normalization."""

import pytest

from archolith_rtk.paths import PathConfig, normalize_paths, reset_path_config


@pytest.fixture(autouse=True)
def _reset():
    reset_path_config()
    yield
    reset_path_config()


class TestPathNormalization:
    def test_windows_path_shortened(self):
        config = PathConfig(
            workspace_root="C:/Users/thron/IdeaProjects",
            project_roots=["C:/Users/thron/IdeaProjects/projects/archolith/archolith-rtk"],
        )
        text = (
            "C:\\Users\\thron\\IdeaProjects\\projects\\archolith\\"
            "archolith-rtk\\archolith_rtk\\filters\\json_output.py"
        )
        result = normalize_paths(text, config=config)
        assert "archolith-rtk/archolith_rtk/filters/json_output.py" in result
        assert "IdeaProjects" not in result

    def test_posix_path_shortened(self):
        config = PathConfig(
            workspace_root="/home/user/projects",
            project_roots=["/home/user/projects/myapp"],
        )
        text = "/home/user/projects/myapp/src/main.py"
        result = normalize_paths(text, config=config)
        assert "myapp/src/main.py" in result
        assert "/home/user/projects/myapp/src/main.py" not in result

    def test_separator_normalization(self):
        config = PathConfig(
            workspace_root="C:/Users/thron/IdeaProjects",
            project_roots=["C:/Users/thron/IdeaProjects/projects/yawn/yawn.rip"],
        )
        text = "C:\\Users\\thron\\IdeaProjects\\projects\\yawn\\yawn.rip\\src\\main.py"
        result = normalize_paths(text, config=config)
        assert "\\" not in result
        assert "yawn.rip/src/main.py" in result

    def test_path_outside_workspace_not_modified(self):
        config = PathConfig(
            workspace_root="C:/Users/thron/IdeaProjects",
            project_roots=["C:/Users/thron/IdeaProjects/projects/archolith/archolith-rtk"],
        )
        text = "/etc/nginx/nginx.conf"
        result = normalize_paths(text, config=config)
        assert "/etc/nginx/nginx.conf" in result

    def test_multi_project_preserves_project_name(self):
        config = PathConfig(
            workspace_root="C:/Users/thron/IdeaProjects",
            project_roots=[
                "C:/Users/thron/IdeaProjects/projects/archolith/archolith-rtk",
                "C:/Users/thron/IdeaProjects/projects/archolith/archolith-context",
            ],
        )
        text_rtk = "C:/Users/thron/IdeaProjects/projects/archolith/archolith-rtk/src/main.py"
        text_ctx = "C:/Users/thron/IdeaProjects/projects/archolith/archolith-context/src/main.py"
        result_rtk = normalize_paths(text_rtk, config=config)
        result_ctx = normalize_paths(text_ctx, config=config)
        assert "archolith-rtk/src/main.py" in result_rtk
        assert "archolith-context/src/main.py" in result_ctx

    def test_longest_root_prefix_wins(self):
        """More-specific root should be matched first."""
        config = PathConfig(
            workspace_root="C:/Users/thron",
            project_roots=[
                "C:/Users/thron/IdeaProjects/projects/yawn",
                "C:/Users/thron/IdeaProjects/projects/yawn/yawn.rip",
            ],
        )
        text = "C:/Users/thron/IdeaProjects/projects/yawn/yawn.rip/src/main.py"
        result = normalize_paths(text, config=config)
        # Should match yawn/yawn.rip (longest) not just yawn.
        assert "yawn.rip/src/main.py" in result

    def test_empty_text(self):
        config = PathConfig(workspace_root="/home", project_roots=["/home/proj"])
        result = normalize_paths("", config=config)
        assert result == ""

    def test_off_switch(self, monkeypatch):
        monkeypatch.setenv("ARCHOLITH_RTK_STRIP_WORKSPACE_ROOT", "off")
        config = PathConfig(
            workspace_root="C:/Users/thron/IdeaProjects",
            project_roots=["C:/Users/thron/IdeaProjects/projects/myapp"],
        )
        text = "C:/Users/thron/IdeaProjects/projects/myapp/src/main.py"
        result = normalize_paths(text, config=config)
        # Feature disabled — text unchanged.
        assert result == text

    def test_config_reset(self):
        """reset_path_config should clear the cached config."""
        from archolith_rtk import paths

        reset_path_config()
        assert paths._cached_config is None
