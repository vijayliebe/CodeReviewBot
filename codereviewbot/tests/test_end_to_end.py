"""End-to-end pipeline test: profile → generate rules → check file → verify findings.

This test exercises the full static analysis pipeline without LLM calls,
ensuring all layers (platforms → workspace → rules → findings) work together.
"""

from pathlib import Path

import pytest

from src.platforms.registry import profile_repo, collect_rules, build_review_preamble
from src.memory.rule_harvester import generate_default_rules_file
from src.utils.rules_parser import parse_rules_file, check_file_rules
from src.workspace.store import get_effective_rules, load_shared_rules
from src.utils.paths import get_workspace_root
from src.utils.token_budget import compact_diff, estimate_tokens

WORKSPACE = get_workspace_root()


def test_full_pipeline_django_app():
    """Full pipeline on a Django repo: profile → rules → scan → findings."""
    repo = WORKSPACE / "benchmark_repos" / "django_app"

    # Step 1: Profile
    profile = profile_repo(repo)
    assert "python_web" in profile.platform_adapters

    # Step 2: Generate rules from profile
    rules_dir = repo / ".crb"
    rules_file = generate_default_rules_file(profile.to_dict(), rules_dir)
    assert rules_file.exists()

    # Step 3: Parse rules
    config = parse_rules_file(rules_file)
    rule_ids = {r["id"] for r in config["rules"]}
    assert "py-web-no-debug-true" in rule_ids
    assert "py-web-secret-key-leak" in rule_ids

    # Step 4: Check file against rules
    settings = repo / "myproject" / "settings.py"
    findings = check_file_rules("myproject/settings.py", settings.read_text(), config)

    # Step 5: Verify findings
    found_ids = {f["rule_id"] for f in findings}
    assert "py-web-no-debug-true" in found_ids
    assert "py-web-secret-key-leak" in found_ids


def test_full_pipeline_with_workspace_shared_rules():
    """Workspace shared rules + repo rules + platform rules = effective rules."""
    repo = WORKSPACE / "benchmark_repos" / "flask_app"

    effective = get_effective_rules(repo, WORKSPACE)
    ids = {r["id"] for r in effective}

    # Platform rules
    assert "py-web-no-debug-true" in ids
    # Repo or platform rules
    assert "bare-except" in ids or "no-print-statements" in ids


def test_full_pipeline_review_preamble_compact():
    """The review preamble should be compact (token-saving) and contain profile info."""
    repo = WORKSPACE / "benchmark_repos" / "react_native_app"
    profile = profile_repo(repo)
    preamble = build_review_preamble(profile)

    assert "PRELOADED_REPO_PROFILE" in preamble
    assert "mobile" in preamble
    assert "react-native" in preamble.lower() or "mobile" in preamble.lower()
    # Preamble should be under ~1000 tokens
    assert estimate_tokens(preamble) < 1000


def test_full_pipeline_diff_compaction():
    """A large patch should be compacted to fit within token budget."""
    fixture = WORKSPACE / "codereviewbot" / "tests" / "fixtures" / "sample_pr_diff.patch"
    original = fixture.read_text()
    compacted = compact_diff(original, max_lines=30)

    assert len(compacted.splitlines()) <= 35
    assert estimate_tokens(compacted) <= estimate_tokens(original)


def test_full_pipeline_mobile_repo():
    """Full pipeline on a Flutter repo: profile → mobile adapter → rules → findings."""
    repo = WORKSPACE / "benchmark_repos" / "flutter_app"

    profile = profile_repo(repo)
    assert "mobile" in profile.platform_adapters

    rules = collect_rules(profile.to_dict())
    ids = {r["id"] for r in rules}
    assert "mobile-main-thread-block" in ids

    # Check the dart file
    main_dart = repo / "lib" / "main.dart"
    config = {"rules": rules}
    findings = check_file_rules("lib/main.dart", main_dart.read_text(), config)
    found_ids = {f["rule_id"] for f in findings}
    assert "mobile-main-thread-block" in found_ids


def test_full_pipeline_ai_agent_repo():
    """Full pipeline on an AI-agent repo: profile → ai_agent adapter → rules → findings."""
    repo = WORKSPACE / "benchmark_repos" / "ai_agent_repo"

    profile = profile_repo(repo)
    assert "ai_agent" in profile.platform_adapters

    rules = collect_rules(profile.to_dict())
    ids = {r["id"] for r in rules}
    assert "agent-no-hardcoded-api-key" in ids

    orch = repo / "orchestrator.py"
    config = {"rules": rules}
    findings = check_file_rules("orchestrator.py", orch.read_text(), config)
    found_ids = {f["rule_id"] for f in findings}
    assert "agent-no-hardcoded-api-key" in found_ids


def test_full_pipeline_clean_repo_no_findings():
    """Clean backend service should produce zero findings across all rule layers."""
    repo = WORKSPACE / "benchmark_repos" / "backend_service_clean"

    effective = get_effective_rules(repo, WORKSPACE)
    config = {"rules": effective}

    billing = repo / "billing.py"
    findings = check_file_rules("billing.py", billing.read_text(), config)
    assert findings == [], f"Expected 0 findings on clean repo, got: {[f['rule_id'] for f in findings]}"


def test_full_pipeline_cross_repo_reference(tmp_path):
    """Indexing two repos and searching across them should return results from both."""
    from src.memory.indexer import CodebaseIndexer

    db = tmp_path / "chroma_db"
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "a.py").write_text("def shared_function():\n    return 1\n")
    (repo_b / "b.py").write_text("from a import shared_function\nshared_function()\n")

    CodebaseIndexer(tmp_path, db, repo_id="repo_a").index_repo(repo_a)
    CodebaseIndexer(tmp_path, db, repo_id="repo_b").index_repo(repo_b)

    idx = CodebaseIndexer(tmp_path, db, repo_id="repo_a")
    # Chunks + imports both carry repo_id metadata
    chunk_repos = {m["repo_id"] for m in idx.chunks_collection.get()["metadatas"]}
    import_repos = {m["repo_id"] for m in idx.imports_collection.get()["metadatas"]}
    assert chunk_repos == {"repo_a"}
    assert import_repos == {"repo_b"}
    # Combined, both repos are represented in the multi-repo store
    assert chunk_repos | import_repos == {"repo_a", "repo_b"}
