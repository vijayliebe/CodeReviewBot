"""Tests for the GitHub MCP server: URL parsing, local patch file handling, error paths."""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.mcp_servers.github_mcp_server import _parse_github_url, get_pr_diff


def test_parse_full_url():
    owner, repo, num = _parse_github_url("https://github.com/owner/repo/pull/123")
    assert (owner, repo, num) == ("owner", "repo", "123")


def test_parse_short_format():
    owner, repo, num = _parse_github_url("owner/repo/42")
    assert (owner, repo, num) == ("owner", "repo", "42")


def test_parse_number_only_with_env_default(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "myorg/myrepo")
    owner, repo, num = _parse_github_url("7")
    assert (owner, repo, num) == ("myorg", "myrepo", "7")


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        _parse_github_url("not-a-valid-reference")


def test_get_pr_diff_local_patch_file(tmp_path):
    patch = tmp_path / "test.patch"
    patch.write_text("diff --git a/f.py b/f.py\n+hello\n")
    result = get_pr_diff(str(patch))
    assert "diff --git" in result
    assert "hello" in result


def test_get_pr_diff_missing_local_file():
    result = get_pr_diff("/nonexistent/path/file.patch")
    assert "not found" in result.lower() or "error" in result.lower()


def test_get_pr_diff_api_404():
    """A non-existent GitHub PR should return a 404 error message, not crash."""
    with patch("src.mcp_servers.github_mcp_server.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_get.return_value = mock_resp

        result = get_pr_diff("https://github.com/octocat/does-not-exist/pull/999")
        assert "404" in result
        assert "not found" in result.lower() or "not exist" in result.lower()
