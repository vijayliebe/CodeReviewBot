"""Multi-repo indexing tests — verify repo_id metadata and cross-repo reference lookup."""

import pytest
from pathlib import Path

from src.memory.indexer import CodebaseIndexer


@pytest.fixture
def temp_db(tmp_path):
    return tmp_path / "chroma_db"


def test_multi_repo_indexing_separate_metadata(tmp_path, temp_db):
    """Indexing two repos should keep their chunks separate via repo_id metadata."""
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "a.py").write_text("def alpha():\n    return 1\n")
    (repo_b / "b.py").write_text("def beta():\n    return 2\n")

    idx_a = CodebaseIndexer(tmp_path, temp_db, repo_id="repo_a")
    idx_a.index_repo(repo_a)

    idx_b = CodebaseIndexer(tmp_path, temp_db, repo_id="repo_b")
    idx_b.index_repo(repo_b)

    # Query all chunks
    all_chunks = idx_a.chunks_collection.get()
    repo_ids = {m["repo_id"] for m in all_chunks["metadatas"]}
    assert repo_ids == {"repo_a", "repo_b"}

    # Filter by repo_id
    a_only = idx_a.chunks_collection.get(where={"repo_id": "repo_a"})
    b_only = idx_a.chunks_collection.get(where={"repo_id": "repo_b"})
    a_names = {m["name"] for m in a_only["metadatas"]}
    b_names = {m["name"] for m in b_only["metadatas"]}
    assert "alpha" in a_names
    assert "beta" in b_names
    assert "alpha" not in b_names
    assert "beta" not in a_names


def test_clear_repo_preserves_others(tmp_path, temp_db):
    """clear_repo should only remove chunks for the specified repo."""
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "a.py").write_text("def alpha():\n    return 1\n")
    (repo_b / "b.py").write_text("def beta():\n    return 2\n")

    CodebaseIndexer(tmp_path, temp_db, repo_id="repo_a").index_repo(repo_a)
    CodebaseIndexer(tmp_path, temp_db, repo_id="repo_b").index_repo(repo_b)

    # Clear only repo_a
    idx = CodebaseIndexer(tmp_path, temp_db, repo_id="repo_a")
    idx.clear_repo("repo_a")

    remaining = idx.chunks_collection.get()
    remaining_repos = {m["repo_id"] for m in remaining["metadatas"]}
    assert "repo_b" in remaining_repos
    assert "repo_a" not in remaining_repos


def test_per_repo_style_summary(tmp_path, temp_db):
    """Each repo gets its own style_summary record keyed by repo_id."""
    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    (repo_a / "a.py").write_text("def alpha():\n    return 1\n")

    idx = CodebaseIndexer(tmp_path, temp_db, repo_id="repo_a")
    idx.index_repo(repo_a)

    meta_col = idx.client.get_collection("codebase_metadata")
    result = meta_col.get(ids=["style_summary_repo_a"])
    assert result["metadatas"]
    assert result["metadatas"][0]["repo_id"] == "repo_a"
