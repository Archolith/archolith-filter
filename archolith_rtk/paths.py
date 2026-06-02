"""Workspace path normalization — strip workspace root and normalize separators.

Replaces long absolute paths with project-relative equivalents, normalizes
``\\`` to ``/``, and preserves the project name to avoid ambiguity between
files with the same relative path in different projects.

Multi-project handling:
    ``C:\\Users\\thron\\IdeaProjects\\projects\\archolith\\archolith-rtk\\archolith_rtk\\filters\\json_output.py``
    → ``archolith-rtk/archolith_rtk/filters/json_output.py``

Root detection strategies (priority order):
    1. ``ARCHOLITH_RTK_WORKSPACE_ROOT`` env var
    2. Git-based: walk up from CWD to find ``.git`` directory
    3. Common-prefix inference from all paths in current output (fallback)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PathConfig:
    """Configuration for path normalization."""

    workspace_root: str
    project_roots: list[str]


# Match file paths (Windows drive letter or POSIX absolute/relative with 2+ segments).
_FILE_PATH_RE = re.compile(
    r"""
    (?:[A-Za-z]:[\\/]           # Windows: C:\ or D:/
    | (?<!\w)/                  # POSIX absolute: / (not preceded by word char)
    | (?<![/\\\w])(?:\.\.?[\\/])?\w+[/\\]  # Relative with separator: src/ or ./src/
    )
    (?:[^\s:*?"<>|]+[\\/])*     # middle segments
    [^\s:*?"<>|]+               # final segment (filename)
    """,
    re.VERBOSE,
)

# Common workspace root prefixes to detect.
_CANDIDATE_ROOTS = [
    "projects",
    "IdeaProjects",
    "workspace",
    "workspaces",
    "src",
    "home",
]


def _find_workspace_root() -> str:
    """Detect workspace root via env var or git walk."""
    # 1. Explicit env var.
    env_root = os.environ.get("ARCHOLITH_RTK_WORKSPACE_ROOT", "")
    if env_root and os.path.isdir(env_root):
        return env_root

    # 2. Git-based: walk up from CWD.
    cwd = os.getcwd()
    current = cwd
    for _ in range(20):  # safety limit
        git_dir = os.path.join(current, ".git")
        if os.path.isdir(git_dir):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    # 3. Fallback: CWD itself.
    return cwd


def _infer_project_roots(workspace_root: str) -> list[str]:
    """Find project subdirectories under the workspace root.

    Looks for a ``projects/`` subdirectory containing project dirs,
    or uses the workspace root itself if no ``projects/`` dir exists.
    """
    # Normalize to forward slashes for consistent matching.
    root = workspace_root.replace("\\", "/")

    # Look for a projects/ directory with subdirectories.
    projects_dir = os.path.join(workspace_root, "projects")
    if os.path.isdir(projects_dir):
        roots: list[str] = []
        for org in os.listdir(projects_dir):
            org_path = os.path.join(projects_dir, org)
            if os.path.isdir(org_path):
                for proj in os.listdir(org_path):
                    proj_path = os.path.join(org_path, proj)
                    if os.path.isdir(proj_path):
                        roots.append(proj_path.replace("\\", "/"))
        if roots:
            return roots

    # Fallback: workspace root itself.
    return [root]


def _default_config() -> PathConfig:
    """Build a default PathConfig from the environment."""
    root = _find_workspace_root()
    return PathConfig(
        workspace_root=root.replace("\\", "/"),
        project_roots=_infer_project_roots(root),
    )


# Module-level cached config.
_cached_config: PathConfig | None = None


def get_path_config() -> PathConfig:
    """Return the cached PathConfig, creating it on first call."""
    global _cached_config
    if _cached_config is None:
        _cached_config = _default_config()
    return _cached_config


def reset_path_config() -> None:
    """Reset the cached PathConfig (useful for testing)."""
    global _cached_config
    _cached_config = None


def normalize_paths(text: str, config: PathConfig | None = None) -> str:
    """Replace workspace-rooted paths with project-relative equivalents.

    - Strips the workspace root prefix for each path.
    - Preserves the project name and everything after it
      (e.g., ``projects/archolith/archolith-rtk/...`` → ``archolith-rtk/...``).
    - Normalizes ``\\`` to ``/``.
    - Only normalizes paths that match a known root prefix.
    - Off-switch: ``ARCHOLITH_RTK_STRIP_WORKSPACE_ROOT=off`` disables this.
    """
    # Off-switch check (standalone safety valve for direct callers).
    # When called through the RTK pipeline (filter_output), the primary
    # gate is ARCHOLITH_RTK_FILTER_NORMALIZE_PATHS_ENABLED in FilterConfig.
    off = os.environ.get("ARCHOLITH_RTK_STRIP_WORKSPACE_ROOT", "")
    if off.lower() in ("off", "false", "0"):
        return text

    if config is None:
        config = get_path_config()

    if not config.project_roots:
        return text

    # Sort project roots longest-first so most-specific prefix wins.
    sorted_roots = sorted(config.project_roots, key=len, reverse=True)

    def _replace_path(m: re.Match[str]) -> str:
        path = m.group(0)
        # Normalize separators for matching.
        normalized = path.replace("\\", "/")

        for root in sorted_roots:
            if normalized.startswith(root + "/"):
                # Strip the root prefix, keep everything after it.
                # The root already includes the project directory,
                # so what remains is the path within the project.
                # But we want to preserve the project name.
                # Strategy: find the project name by looking at the
                # difference between root and workspace_root.
                if config.workspace_root and root.startswith(config.workspace_root + "/"):
                    # What comes after workspace_root/ includes the
                    # project structure. We want to strip the
                    # workspace_root and any intermediate org dirs,
                    # keeping the project name and below.
                    after_ws = root[len(config.workspace_root) + 1:]
                    parts = after_ws.split("/")
                    # Common patterns:
                    #   projects/org/project  → keep "project/..."
                    #   org/project           → keep "project/..."
                    #   project               → keep "project/..."
                    # Strategy: use the LAST part of the root as the
                    # project name, and preserve it plus the relative.
                    project_name = parts[-1]
                    relative = normalized[len(root) + 1:]
                    return f"{project_name}/{relative}" if relative else project_name
                # Fallback: strip root, keep everything after it.
                relative = normalized[len(root) + 1:]
                if relative:
                    return relative
        # No matching root — return original (with separator normalization).
        return normalized

    result = _FILE_PATH_RE.sub(_replace_path, text)
    return result
