import pytest
from pathlib import Path

from src.platforms.registry import profile_repo, collect_rules, ADAPTER_BY_ID
from src.utils.token_budget import compact_diff, should_skip_file, estimate_tokens

from src.utils.paths import get_workspace_root

WORKSPACE = get_workspace_root()
PROJECT = WORKSPACE / "codereviewbot"


def test_profile_django_app():
    root = WORKSPACE / "benchmark_repos" / "django_app"
    profile = profile_repo(root)
    assert "python_web" in profile.platform_adapters
    assert "django" in profile.frameworks or "python" in profile.languages
    rules = collect_rules(profile.to_dict())
    ids = {r["id"] for r in rules}
    assert "py-web-no-debug-true" in ids


def test_profile_flutter_app():
    root = WORKSPACE / "benchmark_repos" / "flutter_app"
    profile = profile_repo(root)
    assert "mobile" in profile.platform_adapters
    assert profile.repo_kind == "mobile"


def test_profile_react_native():
    root = WORKSPACE / "benchmark_repos" / "react_native_app"
    profile = profile_repo(root)
    assert "mobile" in profile.platform_adapters
    assert "react-native" in profile.frameworks


def test_profile_ai_agent_repo():
    root = WORKSPACE / "benchmark_repos" / "ai_agent_repo"
    profile = profile_repo(root)
    assert "ai_agent" in profile.platform_adapters
    rules = collect_rules(profile.to_dict())
    assert any(r["id"] == "agent-no-hardcoded-api-key" for r in rules)


def test_codereviewbot_profiles_as_ai_agent():
    profile = profile_repo(PROJECT)
    assert "ai_agent" in profile.platform_adapters


def test_token_budget_compact_diff():
    huge = "\n".join([f"+line {i}" for i in range(1000)])
    diff = f"diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1,3 +1,3 @@\n{huge}"
    compact = compact_diff(diff, max_lines=50)
    assert len(compact.splitlines()) <= 55
    assert estimate_tokens(compact) < estimate_tokens(diff)


def test_should_skip_lockfiles():
    assert should_skip_file("package-lock.json") is True
    assert should_skip_file("src/app.py") is False


def test_all_adapters_registered():
    assert set(ADAPTER_BY_ID) >= {"python_web", "mobile", "ai_agent", "web_frontend", "infra"}
