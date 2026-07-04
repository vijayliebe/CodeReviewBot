"""Tests for workspace store: shared rules inheritance, repo relationships, multi-repo indexing."""

import pytest
from pathlib import Path

from src.workspace.store import (
    init_workspace,
    register_repo,
    load_workspace,
    save_shared_rules,
    load_shared_rules,
    merge_rules,
    get_related_repos,
    get_effective_rules,
)
from src.utils.paths import get_workspace_root

WORKSPACE = get_workspace_root()


@pytest.fixture
def temp_workspace(tmp_path, monkeypatch):
    """Create a temporary workspace root for isolation."""
    monkeypatch.setenv("CRB_WORKSPACE_ROOT", str(tmp_path))
    # Reload paths module so get_workspace_root picks up the new env
    import importlib
    import src.utils.paths as paths_mod
    importlib.reload(paths_mod)
    monkeypatch.setattr("src.workspace.store.get_workspace_root", lambda: tmp_path)
    return tmp_path


def test_init_workspace(temp_workspace):
    cfg = init_workspace("test-product", temp_workspace)
    assert cfg.product == "test-product"
    assert (temp_workspace / ".crb-workspace" / "workspace.yaml").is_file()


def test_register_repo(temp_workspace):
    init_workspace("test-product", temp_workspace)
    cfg = register_repo("backend", "repos/backend", "backend", temp_workspace)
    assert "backend" in cfg.repos
    assert cfg.repos["backend"].kind == "backend"


def test_shared_rules_inheritance(temp_workspace):
    init_workspace("test-product", temp_workspace)
    shared = [
        {"id": "no-float-for-money", "pattern": r"float\(", "severity": "critical"},
        {"id": "all-keys-prefixed", "pattern": r"redis\.(get|set)\(", "severity": "high"},
    ]
    save_shared_rules(shared, temp_workspace)
    loaded = load_shared_rules(temp_workspace)
    ids = {r["id"] for r in loaded}
    assert "no-float-for-money" in ids
    assert "all-keys-prefixed" in ids
    # All shared rules should be tagged with source
    assert all(r.get("source") == "workspace-shared" for r in loaded)


def test_merge_rules_repo_overrides_shared(temp_workspace):
    shared = [
        {"id": "no-float-for-money", "pattern": r"float\(", "severity": "critical", "suggestion": "Use Decimal"},
    ]
    repo_rules = [
        {"id": "no-float-for-money", "pattern": r"float\(", "severity": "critical", "suggestion": "Repo override"},
    ]
    merged = merge_rules(shared, repo_rules)
    assert len(merged) == 1
    assert merged[0]["suggestion"] == "Repo override"


def test_repo_relationships(temp_workspace):
    init_workspace("test-product", temp_workspace)
    register_repo("frontend", "repos/frontend", "frontend", temp_workspace)
    register_repo("backend", "repos/backend", "backend", temp_workspace)

    cfg = load_workspace(temp_workspace)
    cfg.repos["frontend"].consumes.append("backend")
    cfg.repos["backend"].provides.append("frontend")
    from src.workspace.store import save_workspace
    save_workspace(cfg, temp_workspace)

    related = get_related_repos("frontend", temp_workspace)
    assert len(related["upstream"]) == 1
    assert related["upstream"][0].id == "backend"

    related = get_related_repos("backend", temp_workspace)
    assert len(related["downstream"]) == 1
    assert related["downstream"][0].id == "frontend"


def test_effective_rules_merges_layers(temp_workspace, tmp_path):
    """get_effective_rules should merge platform + shared + repo rules."""
    init_workspace("test-product", temp_workspace)

    # Create a repo with a requirements.txt so python_web adapter activates
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask\n")
    (repo / ".crb").mkdir()
    (repo / ".crb" / "rules.yaml").write_text(
        "rules:\n  - id: repo-specific-rule\n    pattern: 'foo'\n    severity: low\n"
    )

    # Add a shared rule
    save_shared_rules([{"id": "shared-rule", "pattern": "bar", "severity": "medium"}], temp_workspace)

    rules = get_effective_rules(repo, temp_workspace)
    ids = {r["id"] for r in rules}
    assert "shared-rule" in ids          # workspace shared
    assert "repo-specific-rule" in ids   # repo-level
    # Platform rules from python_web adapter
    assert "py-web-no-debug-true" in ids or "bare-except" in ids
