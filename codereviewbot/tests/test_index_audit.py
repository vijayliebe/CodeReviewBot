"""Tests for index coverage audit."""

from pathlib import Path

import pytest

from src.memory.index_audit import audit_repo, search_symbols
from src.memory.indexer import CodebaseIndexer
from src.memory.refresh import refresh_index
from src.utils.paths import workspace_chroma_path


@pytest.fixture
def audit_repo_tree(tmp_path):
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "billing.py").write_text(
        "from decimal import Decimal\n\n"
        "def process_payment(amount):\n"
        "    return Decimal(amount)\n"
    )
    (repo / "constants.py").write_text("TAX_RATE = 0.2\n")
    ws = tmp_path
    db = workspace_chroma_path(ws)
    return ws, repo, db


def test_audit_never_indexed(audit_repo_tree):
    ws, repo, db = audit_repo_tree
    report = audit_repo(repo, db, "sample")
    assert report.never_indexed
    assert report.disk_files == 2
    assert report.manifest_files == 0
    assert report.has_failures


def test_audit_passes_after_index(audit_repo_tree):
    ws, repo, db = audit_repo_tree
    refresh_index("sample", repo, ws, force_full=True)

    report = audit_repo(repo, db, "sample")
    assert not report.never_indexed
    assert report.disk_files == report.manifest_files == 2
    assert report.total_local_code_chunks >= 1
    assert report.total_chroma_code_chunks >= 1
    assert not report.chroma_missing_files
    assert not report.count_mismatch_files
    assert not report.has_failures


def test_audit_symbol_search(audit_repo_tree):
    ws, repo, db = audit_repo_tree
    refresh_index("sample", repo, ws, force_full=True)

    hits = search_symbols(db, "sample", ["process_payment"])
    assert len(hits) == 1
    assert hits[0].file_path == "billing.py"

    report = audit_repo(repo, db, "sample", symbols=["process_payment", "missing_fn"])
    assert len(report.symbol_hits) == 1
    assert report.has_failures  # missing_fn not found


def test_audit_flags_zero_chunk_file(audit_repo_tree):
    ws, repo, db = audit_repo_tree
    refresh_index("sample", repo, ws, force_full=True)

    report = audit_repo(repo, db, "sample")
    assert "constants.py" in report.zero_chunk_files


def test_audit_count_mismatch(audit_repo_tree):
    ws, repo, db = audit_repo_tree
    refresh_index("sample", repo, ws, force_full=True)

    indexer = CodebaseIndexer(ws, db, repo_id="sample")
    indexer._delete_file_chunks("billing.py")

    report = audit_repo(repo, db, "sample")
    assert "billing.py" in report.chroma_missing_files
    assert report.has_failures


def test_cli_index_audit(audit_repo_tree, monkeypatch):
    ws, repo, _db = audit_repo_tree
    monkeypatch.setenv("CRB_WORKSPACE_ROOT", str(ws))

    from click.testing import CliRunner
    from src.main import cli

    refresh_index("audit_cli", repo, ws, force_full=True)
    r = CliRunner().invoke(
        cli,
        ["index-audit", "--path", str(repo), "--repo-id", "audit_cli", "--symbol", "process_payment"],
        env={"CRB_WORKSPACE_ROOT": str(ws)},
    )
    assert r.exit_code == 0
    assert "process_payment" in r.output
