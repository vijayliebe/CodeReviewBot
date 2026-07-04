from pathlib import Path

from src.benchmark.scorecard import run_scorecard, format_scorecard_report
from src.utils.paths import get_workspace_root

MANIFEST = get_workspace_root() / "benchmark_repos" / "manifest.yaml"


def test_benchmark_scorecard_runs():
    assert MANIFEST.is_file()
    report = run_scorecard(MANIFEST)
    assert report["summary"]["repos_tested"] >= 13
    assert report["summary"]["recall"] >= 0.95
    assert report["summary"]["precision"] >= 0.95
    text = format_scorecard_report(report)
    assert "Precision" in text
    assert "django_app" in text
    assert "backend_service_clean" in text  # FP control repo


def test_clean_repo_has_no_findings():
    """FP control: clean backend service must produce zero findings."""
    from src.benchmark.scorecard import _scan_repo_findings
    root = get_workspace_root() / "benchmark_repos" / "backend_service_clean"
    findings = _scan_repo_findings(root)
    assert findings == [], f"Expected 0 findings on clean repo, got: {findings}"
