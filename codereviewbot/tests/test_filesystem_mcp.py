"""Tests for FileSystem MCP server — path sandboxing security and file operations."""

import pytest
from pathlib import Path

from src.mcp_servers.filesystem_mcp_server import _get_safe_path, read_file, list_directory, search_files
from src.utils.paths import get_workspace_root

WORKSPACE = get_workspace_root()


def test_safe_path_inside_workspace():
    """Paths inside the workspace root should resolve correctly."""
    safe = _get_safe_path("benchmark_repos/django_app/myproject/settings.py")
    assert "benchmark_repos" in str(safe)
    assert safe.is_file()


def test_safe_path_blocks_traversal(monkeypatch):
    """Directory traversal via ../../etc/passwd must be blocked."""
    from src.mcp_servers import filesystem_mcp_server as fs
    monkeypatch.setattr(fs, "WORKSPACE_ROOT", Path("/tmp/fake_workspace"))
    with pytest.raises(PermissionError):
        _get_safe_path("../../etc/passwd")


def test_safe_path_blocks_absolute_outside(monkeypatch):
    """Absolute paths outside workspace must be blocked."""
    from src.mcp_servers import filesystem_mcp_server as fs
    monkeypatch.setattr(fs, "WORKSPACE_ROOT", Path("/tmp/fake_workspace"))
    with pytest.raises(PermissionError):
        _get_safe_path("/etc/passwd")


def test_read_file_returns_content():
    """read_file should return file content with line numbers by default."""
    content = read_file("benchmark_repos/django_app/myproject/settings.py")
    assert "DEBUG" in content or "SECRET" in content
    assert "1:" in content  # line number prefix


def test_read_file_without_line_numbers():
    content = read_file("benchmark_repos/django_app/myproject/settings.py", with_line_numbers=False)
    assert "DEBUG" in content or "SECRET" in content
    assert not content.startswith("1:")


def test_read_file_nonexistent():
    result = read_file("nonexistent/file.py")
    assert "Error" in result or "not a file" in result


def test_list_directory_non_recursive():
    result = list_directory("benchmark_repos")
    assert "django_app" in result or "backend_service" in result


def test_search_files_finds_pattern():
    """search_files should find a regex pattern in workspace files."""
    result = search_files(r"DEBUG\s*=\s*True", "benchmark_repos/django_app", ".py")
    assert "settings.py" in result


def test_search_files_no_matches():
    result = search_files(r"zzz_no_match_zzz", "benchmark_repos/django_app", ".py")
    assert "No matches" in result
