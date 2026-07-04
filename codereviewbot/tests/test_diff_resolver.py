"""Tests for commit/PR diff resolution."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.utils.diff_resolver import (
    DiffResolveError,
    is_commit_reference,
    is_pr_reference,
    parse_commit_reference,
    local_git_diff,
    resolve_commit_diff,
    resolve_diff,
)


def test_is_commit_reference_single_sha():
    assert is_commit_reference("abc1234") is True
    assert is_commit_reference("abc1234def5678901234567890abcd12345678") is True  # 40-char SHA


def test_is_commit_reference_range():
    assert is_commit_reference("abc1234..def5678") is True
    assert is_commit_reference("abc1234...def5678") is True


def test_is_commit_reference_owner_repo():
    assert is_commit_reference("owner/repo@abc1234..def5678") is True


def test_is_commit_reference_compare_url():
    assert is_commit_reference("https://github.com/o/r/compare/abc...def") is True


def test_is_pr_reference():
    assert is_pr_reference("https://github.com/o/r/pull/12") is True
    assert is_pr_reference("o/r/12") is True
    assert is_pr_reference("abc1234..def5678") is False


def test_parse_commit_reference_range():
    parsed = parse_commit_reference("aaa1111..bbb2222")
    assert parsed["base"] == "aaa1111"
    assert parsed["head"] == "bbb2222"
    assert parsed["owner"] is None


def test_parse_commit_reference_owner_repo():
    parsed = parse_commit_reference("myorg/myrepo@aaa1111..bbb2222")
    assert parsed == {"owner": "myorg", "repo": "myrepo", "base": "aaa1111", "head": "bbb2222"}


def test_parse_commit_reference_single_sha():
    parsed = parse_commit_reference("deadbeef")
    assert parsed["base"] == "deadbeef"
    assert parsed["head"] is None


def test_local_git_diff_range(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c1"], cwd=tmp_path, check=True, capture_output=True)
    f.write_text("x = 2\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c2"], cwd=tmp_path, check=True, capture_output=True)

    shas = subprocess.run(
        ["git", "rev-list", "--max-count=2", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip().splitlines()
    head, base = shas[0], shas[1]

    diff = local_git_diff(tmp_path, base, head)
    assert "a.py" in diff
    assert "-x = 1" in diff or "+x = 2" in diff


def test_resolve_commit_diff_local(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "b.py").write_text("y = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()

    diff = resolve_commit_diff(sha, tmp_path)
    assert "b.py" in diff


def test_get_commit_diff_github_api():
    from src.mcp_servers.github_mcp_server import get_commit_diff

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "diff --git a/f.py b/f.py\n+line\n"
        mock_get.return_value = mock_resp

        result = get_commit_diff("myorg/myrepo@aaa..bbb")
        assert "diff --git" in result


def test_get_pr_diff_routes_commit_reference():
    from src.mcp_servers.github_mcp_server import get_pr_diff

    with patch("src.utils.diff_resolver.local_git_diff") as mock_local:
        mock_local.return_value = "diff --git a/x b/x\n"
        import os
        os.environ["CRB_WORKSPACE_ROOT"] = "/tmp/fake"
        with patch("pathlib.Path.exists", return_value=True):
            with patch("src.utils.diff_resolver.resolve_commit_diff") as mock_resolve:
                mock_resolve.return_value = "diff --git a/x b/x\n"
                result = get_pr_diff("aaa1111..bbb2222")
                assert "diff --git" in result


def test_resolve_diff_patch_file(tmp_path):
    patch = tmp_path / "change.patch"
    patch.write_text("diff --git a/f.py b/f.py\n+hello\n")
    assert "hello" in resolve_diff(str(patch))
