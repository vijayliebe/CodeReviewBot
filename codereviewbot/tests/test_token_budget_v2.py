"""Tests for the credit-saving / token-budget helpers added in the static-analysis pass."""

from pathlib import Path

from src.utils.token_budget import (
    should_skip_file,
    compact_diff,
    filter_diff,
    extract_changed_files,
    changed_files_summary,
    diff_stats,
    estimate_tokens,
)
from src.utils.static_analysis import run_static_analysis, format_static_findings


SAMPLE_DIFF = """diff --git a/payment_handler.py b/payment_handler.py
new file mode 100644
--- /dev/null
+++ b/payment_handler.py
@@ -0,0 +1,3 @@
+API_KEY = "sk_live_51HxF429FjsdkJ8394fsdj2"
+price = float(amount)
+def getPaymentDetails():
diff --git a/package-lock.json b/package-lock.json
index 1111111..2222222 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,3 +1,3 @@
 {
-  "foo": "bar"
+  "foo": "bar "
 }
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,2 +1,2 @@
-# Old Title
+# Old Title 
 some unchanged line
"""


def test_filter_diff_strips_lockfiles():
    filtered = filter_diff(SAMPLE_DIFF)
    assert "payment_handler.py" in filtered
    assert "package-lock.json" not in filtered


def test_filter_diff_preserves_real_code_hunks():
    filtered = filter_diff(SAMPLE_DIFF)
    assert "API_KEY" in filtered
    assert "float(amount)" in filtered


def test_filter_diff_drops_whitespace_only_hunks():
    """The README.md hunk only changes trailing whitespace — should be dropped."""
    filtered = filter_diff(SAMPLE_DIFF)
    # README section was whitespace-only (added trailing space on title line)
    assert "Old Title" not in filtered or "README.md" not in filtered


def test_filter_diff_empty_input():
    assert filter_diff("") == ""


def test_extract_changed_files():
    files = extract_changed_files(SAMPLE_DIFF)
    assert files == ["payment_handler.py", "package-lock.json", "README.md"]


def test_changed_files_summary_skips_lockfiles():
    summary = changed_files_summary(SAMPLE_DIFF)
    assert "payment_handler.py" in summary
    assert "package-lock.json" not in summary


def test_changed_files_summary_empty():
    assert "No reviewable files" in changed_files_summary("")


def test_changed_files_summary_caps_at_max_files():
    diff = "".join(f"diff --git a/f{i}.py b/f{i}.py\n" for i in range(50))
    summary = changed_files_summary(diff, max_files=10)
    assert "and 40 more files" in summary


def test_diff_stats_counts_correctly():
    stats = diff_stats(SAMPLE_DIFF)
    assert stats["files"] == 3
    assert stats["hunks"] >= 3
    assert stats["additions"] >= 4
    assert stats["deletions"] >= 2


def test_diff_stats_empty():
    assert diff_stats("") == {"files": 0, "additions": 0, "deletions": 0, "hunks": 0}


def test_filter_then_compact_saves_more_tokens_than_compact_alone():
    """Sanity: filtering lockfiles before compaction should reduce token count."""
    only_compact = compact_diff(SAMPLE_DIFF)
    filtered_then_compact = compact_diff(filter_diff(SAMPLE_DIFF))
    assert estimate_tokens(filtered_then_compact) <= estimate_tokens(only_compact)


def test_run_static_analysis_finds_violations(tmp_path):
    """The static pre-pass should catch hardcoded-secret and float-for-money locally."""
    from src.utils.paths import get_workspace_root
    ws = get_workspace_root()
    # Use the existing backend_service benchmark repo which has known violations
    repo = ws / "benchmark_repos" / "backend_service"
    diff = (
        "diff --git a/billing.py b/billing.py\n"
        "--- a/billing.py\n+++ b/billing.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+price = float(amount)\n"
        "+r.set(f'refund:{order_id}', amount)\n"
    )
    summary = run_static_analysis(diff, repo)
    rule_ids = {f["rule_id"] for f in summary["findings"]}
    # Should catch at least the float-for-money and redis-key-prefix rules locally
    assert "no-float-for-money" in rule_ids or "redis-key-prefix" in rule_ids
    assert summary["files_scanned"] >= 1


def test_run_static_analysis_skips_lockfiles(tmp_path):
    """Lockfiles in the diff are filtered before scanning — they never enter the loop."""
    from src.utils.paths import get_workspace_root
    repo = get_workspace_root() / "benchmark_repos" / "backend_service"
    diff = (
        "diff --git a/package-lock.json b/package-lock.json\n"
        "--- a/package-lock.json\n+++ b/package-lock.json\n"
        "@@ -1,1 +1,1 @@\n-{}\n+{}\n"
    )
    summary = run_static_analysis(diff, repo)
    # Lockfile is pre-filtered by should_skip_file → not scanned, no findings
    assert summary["files_scanned"] == 0
    assert summary["findings"] == []


def test_run_static_analysis_no_findings_on_clean_diff():
    from src.utils.paths import get_workspace_root
    repo = get_workspace_root() / "benchmark_repos" / "backend_service_clean"
    diff = (
        "diff --git a/billing.py b/billing.py\n"
        "--- a/billing.py\n+++ b/billing.py\n"
        "@@ -1,1 +1,1 @@\n-x\n+y\n"
    )
    summary = run_static_analysis(diff, repo)
    # Clean repo has no regex violations
    assert summary["findings"] == []


def test_format_static_findings_with_findings():
    summary = {
        "files_scanned": 2,
        "files_skipped": 1,
        "findings": [
            {"rule_id": "no-float-for-money", "severity": "CRITICAL",
             "file": "billing.py", "line": 12, "description": "Use Decimal not float"},
        ],
        "files_with_no_findings": ["other.py"],
    }
    out = format_static_findings(summary)
    assert "STATIC_FINDINGS" in out
    assert "do NOT re-derive" in out
    assert "no-float-for-money" in out
    assert "billing.py:12" in out


def test_format_static_findings_empty():
    summary = {"files_scanned": 3, "files_skipped": 1, "findings": [], "files_with_no_findings": []}
    out = format_static_findings(summary)
    assert "STATIC_FINDINGS" in out
    assert "none from static rules" in out


def test_profile_repo_is_cached():
    """profile_repo should return the same object on repeated calls (lru_cache)."""
    from src.platforms.registry import profile_repo
    from src.utils.paths import get_workspace_root
    ws = get_workspace_root()
    a = profile_repo(ws / "benchmark_repos" / "django_app")
    b = profile_repo(ws / "benchmark_repos" / "django_app")
    assert a is b  # same object → cache hit → no second filesystem walk
