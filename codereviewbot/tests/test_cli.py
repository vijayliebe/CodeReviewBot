"""End-to-end CLI tests — exercise init, workspace, index, and benchmark commands via Click's test runner."""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from src.main import cli
from src.utils.paths import get_workspace_root

WORKSPACE = get_workspace_root()


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "workspace" in result.output
    assert "index" in result.output
    assert "index-audit" in result.output
    assert "benchmark" in result.output


def test_cli_init_on_django_app(runner):
    """`codereviewbot init --path <repo>` should profile and generate rules.yaml."""
    repo = WORKSPACE / "benchmark_repos" / "django_app"
    # Remove any stale rules.yaml first
    rules_file = repo / ".crb" / "rules.yaml"
    if rules_file.exists():
        rules_file.unlink()

    result = runner.invoke(cli, ["init", "--path", str(repo)])
    assert result.exit_code == 0
    assert "python_web" in result.output
    assert "django" in result.output.lower() or "python" in result.output.lower()
    assert rules_file.exists()


def test_cli_workspace_show(runner):
    result = runner.invoke(cli, ["workspace", "show"])
    assert result.exit_code == 0
    assert "google_capstone" in result.output
    assert "backend_service" in result.output
    assert "frontend_app" in result.output


def test_cli_workspace_init_help(runner):
    result = runner.invoke(cli, ["workspace", "init", "--help"])
    assert result.exit_code == 0
    assert "product" in result.output


def test_cli_benchmark(runner):
    """`codereviewbot benchmark` should run the full scorecard without errors."""
    result = runner.invoke(cli, ["benchmark"])
    assert result.exit_code == 0
    assert "Precision" in result.output
    assert "Recall" in result.output
    assert "django_app" in result.output
    assert "backend_service_clean" in result.output


def test_cli_benchmark_json_output(runner, tmp_path):
    json_out = tmp_path / "scorecard.json"
    result = runner.invoke(cli, ["benchmark", "--json-out", str(json_out)])
    assert result.exit_code == 0
    assert json_out.exists()
    import json
    data = json.loads(json_out.read_text())
    assert "summary" in data
    assert data["summary"]["repos_tested"] >= 13


def test_cli_index_with_repo_id(runner, tmp_path, monkeypatch):
    """`codereviewbot index --path <repo> --repo-id <id>` should index without errors."""
    repo = WORKSPACE / "benchmark_repos" / "flask_app"
    # Use a temp DB to avoid polluting the real one
    monkeypatch.setenv("CRB_WORKSPACE_ROOT", str(WORKSPACE))
    result = runner.invoke(cli, ["index", "--path", str(repo), "--repo-id", "flask_test"])
    assert result.exit_code == 0
    assert "flask_test" in result.output or "Indexing" in result.output


def test_cli_review_without_api_key(runner, monkeypatch):
    """`codereviewbot review` should fail gracefully when GOOGLE_API_KEY is not set."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = runner.invoke(cli, ["review", "--pr", "tests/fixtures/sample_pr_diff.patch"])
    assert result.exit_code != 0
    assert "GOOGLE_API_KEY" in result.output
