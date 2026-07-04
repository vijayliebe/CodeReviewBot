"""Tests for diff-aware incremental indexing and the lazy-at-review refresh.

These tests build real (tiny) git repos in temp dirs so the git-native path
(`git diff --name-only`, `git merge-base --is-ancestor`) is exercised end-to-end,
not mocked. The content-hash fallback is tested with non-git temp dirs.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.memory.index_manifest import (
    file_hash,
    git_head_sha,
    git_is_ancestor,
    git_changed_files,
    git_default_branch,
    load_manifest,
    save_manifest,
    build_manifest_entry,
    diff_files,
    manifest_path,
)
from src.memory.indexer import CodebaseIndexer
from src.memory.refresh import (
    refresh_index,
    refresh_index_if_stale,
    refresh_target_and_upstream,
    format_refresh_summary,
    _is_stale,
)


# ---------------------------------------------------------------------------
# Git test helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo` and return stdout. Raises on failure."""
    env = {
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@e.st",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@e.st",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "HOME": "/tmp",
    }
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, env=env, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args} failed: {result.stderr}")
    return result.stdout.strip()


def _make_git_repo(repo: Path) -> str:
    """Init a git repo with an initial commit. Returns the initial SHA."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    (repo / "app.py").write_text("def hello():\n    return 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return _git(repo, "rev-parse", "HEAD")


def _commit_change(repo: Path, msg: str = "change") -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


# ---------------------------------------------------------------------------
# index_manifest helpers
# ---------------------------------------------------------------------------


def test_file_hash_is_stable(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    h1 = file_hash(f)
    h2 = file_hash(f)
    assert h1 == h2 and len(h1) == 64


def test_file_hash_changes_with_content(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    h1 = file_hash(f)
    f.write_text("x = 2\n")
    h2 = file_hash(f)
    assert h1 != h2


def test_git_head_sha_returns_none_for_non_git(tmp_path):
    assert git_head_sha(tmp_path) is None


def test_git_head_sha_returns_sha_for_git_repo(tmp_path):
    sha = _make_git_repo(tmp_path)
    assert git_head_sha(tmp_path) == sha


def test_git_default_branch_detects_main(tmp_path):
    _make_git_repo(tmp_path)
    assert git_default_branch(tmp_path) == "main"


def test_git_is_ancestor_true_for_linear_history(tmp_path):
    _make_git_repo(tmp_path)
    old = git_head_sha(tmp_path)
    (tmp_path / "app.py").write_text("def hello():\n    return 2\n")
    new = _commit_change(tmp_path, "second")
    assert git_is_ancestor(old, new, tmp_path) is True


def test_git_is_ancestor_false_after_force_push(tmp_path):
    """Simulate a force-push by amending the initial commit — old SHA becomes unreachable."""
    _make_git_repo(tmp_path)
    old = git_head_sha(tmp_path)
    (tmp_path / "app.py").write_text("def hello():\n    return 'rewritten'\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--amend", "-m", "rewritten initial", "--no-edit")
    new = git_head_sha(tmp_path)
    assert old != new
    assert git_is_ancestor(old, new, tmp_path) is False


def test_git_changed_files_classifies_correctly(tmp_path):
    _make_git_repo(tmp_path)
    # Start with two files so we can test delete + modify against a real baseline
    (tmp_path / "app.py").write_text("def hello():\n    return 1\n")
    (tmp_path / "extra.py").write_text("x = 1\n")
    _commit_change(tmp_path, "add extra")
    old = git_head_sha(tmp_path)
    # modify app.py, delete extra.py, add new.py
    (tmp_path / "app.py").write_text("def hello():\n    return 2\n")
    (tmp_path / "extra.py").unlink()
    (tmp_path / "new.py").write_text("y = 2\n")
    new = _commit_change(tmp_path, "modify+delete+add")
    changes = git_changed_files(old, new, tmp_path)
    assert "app.py" in changes["modified"]
    assert "extra.py" in changes["deleted"]
    assert "new.py" in changes["added"]


def test_diff_files_classifies_added_changed_unchanged_deleted():
    current = {"a.py": "h1", "b.py": "h2", "c.py": "h3"}
    manifest = {"file_hashes": {"a.py": "h1", "b.py": "hX", "d.py": "h4"}}
    d = diff_files(current, manifest)
    assert d["unchanged"] == ["a.py"]
    assert d["changed"] == ["b.py"]
    assert d["added"] == ["c.py"]
    assert d["deleted"] == ["d.py"]


# ---------------------------------------------------------------------------
# Indexer — incremental paths
# ---------------------------------------------------------------------------


def test_first_index_is_full_mode(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def hello():\n    return 1\n")
    db = tmp_path / "db"

    idx = CodebaseIndexer(tmp_path, db, repo_id="r")
    summary = idx.index_repo(repo)

    assert summary["mode"] == "full"
    assert summary["code_chunks"] >= 1
    # Manifest written
    manifest = load_manifest(db, "r")
    assert manifest is not None
    assert "app.py" in manifest["file_hashes"]


def test_second_index_with_no_changes_is_skip(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def hello():\n    return 1\n")
    db = tmp_path / "db"

    idx = CodebaseIndexer(tmp_path, db, repo_id="r")
    idx.index_repo(repo)  # full
    summary = idx.index_repo(repo)  # skip (no manifest SHA match since non-git, but hashes match)

    # Non-git repo: current_sha is None → falls to hash-incremental path.
    # With no changes, hash-incremental embeds 0 files.
    assert summary["mode"] in ("skip", "hash-incremental")
    assert summary.get("embedded", 0) == 0


def test_git_incremental_re_embeds_only_changed_files(tmp_path):
    repo = tmp_path / "repo"
    _make_git_repo(repo)
    (repo / "a.py").write_text("def a():\n    return 1\n")
    (repo / "b.py").write_text("def b():\n    return 2\n")
    _commit_change(repo, "add a and b")
    db = tmp_path / "db"

    idx = CodebaseIndexer(tmp_path, db, repo_id="r")
    idx.index_repo(repo)  # full
    old_sha = git_head_sha(repo)

    # Change only a.py; b.py untouched
    (repo / "a.py").write_text("def a():\n    return 99\n")
    _commit_change(repo, "modify a")
    new_sha = git_head_sha(repo)

    summary = idx.index_repo(repo)
    assert summary["mode"] == "git-incremental"
    assert summary["from_sha"] == old_sha
    assert summary["to_sha"] == new_sha
    assert summary["embedded"] == 1
    assert summary["deleted"] == 0


def test_git_incremental_handles_deleted_files(tmp_path):
    repo = tmp_path / "repo"
    _make_git_repo(repo)
    (repo / "a.py").write_text("def a():\n    return 1\n")
    (repo / "b.py").write_text("def b():\n    return 2\n")
    _commit_change(repo, "add a and b")
    db = tmp_path / "db"

    idx = CodebaseIndexer(tmp_path, db, repo_id="r")
    idx.index_repo(repo)

    (repo / "b.py").unlink()
    _commit_change(repo, "delete b")

    summary = idx.index_repo(repo)
    assert summary["mode"] == "git-incremental"
    assert summary["deleted"] == 1
    # b.py's chunks should be gone from the collection
    remaining = idx.chunks_collection.get(
        where={"$and": [{"repo_id": "r"}, {"file_path": "b.py"}]}
    )
    assert not remaining.get("ids")


def test_force_push_falls_back_to_hash_incremental(tmp_path):
    repo = tmp_path / "repo"
    _make_git_repo(repo)
    (repo / "a.py").write_text("def a():\n    return 1\n")
    _commit_change(repo, "add a")
    db = tmp_path / "db"

    idx = CodebaseIndexer(tmp_path, db, repo_id="r")
    idx.index_repo(repo)
    old_sha = git_head_sha(repo)

    # Force-push: amend the commit so old_sha is no longer an ancestor
    (repo / "a.py").write_text("def a():\n    return 'rewritten'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "--amend", "-m", "rewritten", "--no-edit")

    summary = idx.index_repo(repo)
    # Ancestor check fails → content-hash walk → still incremental, re-embeds a.py
    assert summary["mode"] == "hash-incremental"
    assert summary["embedded"] >= 1
    assert git_head_sha(repo) != old_sha


def test_full_flag_forces_full_reindex(tmp_path):
    repo = tmp_path / "repo"
    _make_git_repo(repo)
    (repo / "a.py").write_text("def a():\n    return 1\n")
    _commit_change(repo, "add a")
    db = tmp_path / "db"

    idx = CodebaseIndexer(tmp_path, db, repo_id="r")
    idx.index_repo(repo)  # full
    # Even though nothing changed, --full forces a re-index
    summary = idx.index_repo(repo, incremental=False)
    assert summary["mode"] == "full"


def test_non_git_repo_uses_hash_incremental(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def a():\n    return 1\n")
    (repo / "b.py").write_text("def b():\n    return 2\n")
    db = tmp_path / "db"

    idx = CodebaseIndexer(tmp_path, db, repo_id="r")
    idx.index_repo(repo)  # full (no manifest)

    # Change only a.py
    (repo / "a.py").write_text("def a():\n    return 99\n")
    summary = idx.index_repo(repo)
    assert summary["mode"] == "hash-incremental"
    assert summary["embedded"] == 1


def test_manifest_records_sha_and_file_hashes(tmp_path):
    repo = tmp_path / "repo"
    _make_git_repo(repo)
    (repo / "a.py").write_text("def a():\n    return 1\n")
    _commit_change(repo, "add a")
    db = tmp_path / "db"

    idx = CodebaseIndexer(tmp_path, db, repo_id="r")
    idx.index_repo(repo)

    manifest = load_manifest(db, "r")
    assert manifest["last_indexed_sha"] == git_head_sha(repo)
    assert "a.py" in manifest["file_hashes"]
    assert manifest["last_run"]  # ISO timestamp


# ---------------------------------------------------------------------------
# Refresh module — lazy-at-review + upstream
# ---------------------------------------------------------------------------


def test_is_stale_true_when_no_manifest(tmp_path):
    repo = tmp_path / "repo"
    _make_git_repo(repo)
    db = tmp_path / "db"
    assert _is_stale(repo, db, "r") is True


def test_is_stale_false_when_sha_matches(tmp_path):
    repo = tmp_path / "repo"
    _make_git_repo(repo)
    db = tmp_path / "db"

    idx = CodebaseIndexer(tmp_path, db, repo_id="r")
    idx.index_repo(repo)
    assert _is_stale(repo, db, "r") is False


def test_is_stale_true_when_sha_advanced(tmp_path):
    repo = tmp_path / "repo"
    _make_git_repo(repo)
    (repo / "a.py").write_text("def a():\n    return 1\n")
    _commit_change(repo, "add a")
    db = tmp_path / "db"

    idx = CodebaseIndexer(tmp_path, db, repo_id="r")
    idx.index_repo(repo)

    (repo / "a.py").write_text("def a():\n    return 2\n")
    _commit_change(repo, "change a")
    assert _is_stale(repo, db, "r") is True


def test_refresh_index_if_stale_skips_when_current(tmp_path):
    repo = tmp_path / "repo"
    _make_git_repo(repo)
    (repo / "a.py").write_text("def a():\n    return 1\n")
    _commit_change(repo, "add a")
    db = tmp_path / "db"

    refresh_index("r", repo, tmp_path)  # initial index
    result = refresh_index_if_stale("r", repo, tmp_path)
    assert result["mode"] == "skip"


def test_refresh_index_if_stale_refreshes_when_advanced(tmp_path):
    repo = tmp_path / "repo"
    _make_git_repo(repo)
    (repo / "a.py").write_text("def a():\n    return 1\n")
    _commit_change(repo, "add a")
    db = tmp_path / "db"

    refresh_index("r", repo, tmp_path)  # initial index

    (repo / "a.py").write_text("def a():\n    return 2\n")
    _commit_change(repo, "change a")
    result = refresh_index_if_stale("r", repo, tmp_path)
    assert result["mode"] == "git-incremental"
    assert result["embedded"] == 1


def test_refresh_target_and_upstream_refreshes_related_repos(tmp_path, monkeypatch):
    """When the target repo has upstream repos, all of them are checked + refreshed."""
    from src.utils.paths import get_workspace_root
    from src.workspace.store import (
        init_workspace, register_repo, save_workspace, WorkspaceConfig, RepoRecord,
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".crb-workspace").mkdir()

    # Build two git repos: backend (upstream) and frontend (consumes backend)
    backend = ws / "backend"
    _make_git_repo(backend)
    (backend / "api.py").write_text("def get_users():\n    return []\n")
    _commit_change(backend, "add api")

    frontend = ws / "frontend"
    _make_git_repo(frontend)
    (frontend / "app.py").write_text("import api\napi.get_users()\n")
    _commit_change(frontend, "add app")

    # Register a workspace: frontend consumes backend
    monkeypatch.setattr("src.utils.paths.get_workspace_root", lambda: ws)
    monkeypatch.setattr("src.workspace.store.get_workspace_root", lambda: ws)
    cfg = WorkspaceConfig(product="test", repos={
        "backend": RepoRecord(id="backend", path="backend", kind="backend"),
        "frontend": RepoRecord(id="frontend", path="frontend", kind="frontend", consumes=["backend"]),
    })
    save_workspace(cfg, ws)

    # Initial index of both
    refresh_index("backend", backend, ws)
    refresh_index("frontend", frontend, ws)

    # Advance backend's default branch (frontend unchanged)
    (backend / "api.py").write_text("def get_users():\n    return ['u']\n")
    _commit_change(backend, "change api")

    # Reviewing frontend should refresh frontend (skip) AND backend (git-incremental)
    results = refresh_target_and_upstream(frontend, ws)
    by_id = {r["repo_id"]: r for r in results}
    assert by_id["frontend"]["mode"] == "skip"
    assert by_id["backend"]["mode"] == "git-incremental"
    assert by_id["backend"]["embedded"] == 1


def test_refresh_target_and_upstream_skips_missing_related_repo(tmp_path, monkeypatch):
    """A related repo whose path doesn't exist locally is skipped, not crashed."""
    from src.workspace.store import save_workspace, WorkspaceConfig, RepoRecord

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".crb-workspace").mkdir()

    frontend = ws / "frontend"
    _make_git_repo(frontend)
    (frontend / "app.py").write_text("x = 1\n")
    _commit_change(frontend, "init")

    monkeypatch.setattr("src.utils.paths.get_workspace_root", lambda: ws)
    monkeypatch.setattr("src.workspace.store.get_workspace_root", lambda: ws)
    cfg = WorkspaceConfig(product="test", repos={
        "frontend": RepoRecord(id="frontend", path="frontend", kind="frontend",
                               consumes=["backend"]),
        "backend": RepoRecord(id="backend", path="backend", kind="backend"),
    })
    save_workspace(cfg, ws)

    results = refresh_target_and_upstream(frontend, ws)
    by_id = {r["repo_id"]: r for r in results}
    # backend path doesn't exist → skipped, not error
    assert by_id["backend"]["mode"] == "skipped"
    # frontend still gets refreshed (or skipped if up-to-date)
    assert by_id["frontend"]["mode"] in ("skip", "git-incremental", "hash-incremental", "full")


def test_format_refresh_summary_handles_all_modes():
    results = [
        {"repo_id": "a", "mode": "skip"},
        {"repo_id": "b", "mode": "git-incremental", "embedded": 3, "deleted": 1},
        {"repo_id": "c", "mode": "hash-incremental", "embedded": 2, "deleted": 0},
        {"repo_id": "d", "mode": "full", "indexed_files": 10},
        {"repo_id": "e", "mode": "skipped", "reason": "path not found"},
        {"repo_id": "f", "mode": "error", "error": "boom"},
    ]
    out = format_refresh_summary(results)
    assert "a" in out and "up-to-date" in out
    assert "b" in out and "git diff" in out
    assert "c" in out and "content-hash" in out
    assert "d" in out and "full re-index" in out
    assert "e" in out and "skipped" in out
    assert "f" in out and "error" in out
