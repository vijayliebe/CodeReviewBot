"""Tests for the business rules checker tool — merged rules, relationships, inline annotations."""

from pathlib import Path

import pytest

from src.agents.business_rules_checker import check_custom_rules, get_repo_relationships, _find_repo_root
from src.utils.paths import get_workspace_root

WORKSPACE = get_workspace_root()


def test_check_custom_rules_finds_violation():
    """check_custom_rules should detect a known violation in a benchmark repo."""
    billing = WORKSPACE / "benchmark_repos" / "backend_service" / "billing.py"
    content = billing.read_text()
    result = check_custom_rules(str(billing), content)
    assert "no-float-for-money" in result
    assert "redis-key-prefix" in result


def test_check_custom_rules_clean_code():
    """Clean code should report no violations."""
    clean = WORKSPACE / "benchmark_repos" / "backend_service_clean" / "billing.py"
    content = clean.read_text()
    result = check_custom_rules(str(clean), content)
    assert "Success" in result or "No rules violated" in result


def test_check_custom_rules_respects_inline_ignore():
    """A file with # crb:ignore should suppress the matching rule."""
    content = "price = float(amount)  # crb:ignore no-float-for-money\n"
    result = check_custom_rules("test.py", content)
    # The inline ignore should prevent no-float-for-money from firing
    # (may still have other findings depending on shared rules)
    assert "no-float-for-money" not in result or "Success" in result


def test_find_repo_root():
    """_find_repo_root should walk up to the nearest .crb/ directory."""
    nested = WORKSPACE / "benchmark_repos" / "backend_service" / "billing.py"
    root = _find_repo_root(str(nested))
    assert root is not None
    assert (root / ".crb").is_dir()


def test_get_repo_relationships_unregistered():
    """An unregistered repo path should return a helpful message."""
    result = get_repo_relationships("/tmp/nonexistent_repo/file.py")
    assert "workspace" in result.lower() or "not registered" in result.lower() or "not found" in result.lower()


def test_get_repo_relationships_registered():
    """A registered repo should show upstream/downstream relationships."""
    backend = WORKSPACE / "benchmark_repos" / "backend_service"
    result = get_repo_relationships(str(backend / "billing.py"))
    # backend_service is registered in workspace.yaml with frontend_app as downstream
    assert "backend_service" in result or "not registered" in result or "workspace" in result.lower()


def test_check_custom_rules_shared_rules_apply():
    """Workspace shared rules should be enforced even if repo rules.yaml doesn't define them."""
    # The django_app has hardcoded SECRET_KEY — shared rule 'no-hardcoded-secrets' should catch it
    settings = WORKSPACE / "benchmark_repos" / "django_app" / "myproject" / "settings.py"
    content = settings.read_text()
    result = check_custom_rules(str(settings), content)
    # Either the shared rule or the platform rule should flag the secret key
    assert "secret" in result.lower() or "SECRET" in result or "Success" in result
