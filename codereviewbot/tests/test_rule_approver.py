"""Tests for Skill Harvesting: rule_approver + CLI approve-rule / harvest-rules."""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from src.memory.rule_approver import (
    append_rule,
    harvest_suggested_rules,
    validate_pattern,
)
from src.main import cli


def test_append_rule_creates_file(tmp_path: Path):
    target = tmp_path / ".crb" / "rules.yaml"
    res = append_rule(target, {
        "id": "no-float-for-money",
        "description": "Do not use float for money.",
        "pattern": r"float\s*\(",
        "severity": "high",
        "files": ["**/billing*.py"],
    })
    assert res["rule_id"] == "no-float-for-money"
    assert res["total_rules"] == 1
    assert target.is_file()
    text = target.read_text()
    assert "no-float-for-money" in text
    assert "float\\s*\\(" in text


def test_append_rule_is_idempotent(tmp_path: Path):
    target = tmp_path / ".crb" / "rules.yaml"
    for _ in range(2):
        append_rule(target, {"id": "dup", "description": "d", "pattern": "x", "severity": "low"})
    import yaml
    data = yaml.safe_load(target.read_text())
    assert len(data["custom_rules"]) == 1


def test_validate_pattern_rejects_bad_regex():
    assert validate_pattern(r"foo\s+") is True
    assert validate_pattern(r"[unclosed") is False


def test_harvest_suggested_rules_dominant_snake_case():
    suggestions = harvest_suggested_rules({
        "function_count": 10,
        "snake_case_fns": 9,
        "camelCase_fns": 1,
        "PascalCase_fns": 0,
        "class_count": 0,
        "PascalCase_classes": 0,
    })
    ids = [s["id"] for s in suggestions]
    assert "style-py-snake-case" in ids


def test_harvest_suggested_rules_no_dominant_convention():
    suggestions = harvest_suggested_rules({
        "function_count": 10,
        "snake_case_fns": 4,
        "camelCase_fns": 4,
        "PascalCase_fns": 2,
        "class_count": 0,
        "PascalCase_classes": 0,
    })
    # 40% snake / 40% camel — neither crosses the 80% bar
    assert suggestions == []


def test_harvest_suggested_rules_pascal_classes():
    suggestions = harvest_suggested_rules({
        "function_count": 0,
        "snake_case_fns": 0,
        "camelCase_fns": 0,
        "PascalCase_fns": 0,
        "class_count": 10,
        "PascalCase_classes": 9,
    })
    assert any(s["id"] == "style-pascal-classes" for s in suggestions)


# --- CLI smoke tests ---------------------------------------------------


def test_cli_approve_rule_writes_yaml(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "approve-rule",
        "--id", "no-float-for-money",
        "--pattern", r"float\s*\(",
        "--description", "Do not use float for money.",
        "--severity", "high",
        "--files", "**/billing*.py",
        "--path", str(tmp_path),
    ])
    assert result.exit_code == 0, result.output
    rules_yaml = tmp_path / ".crb" / "rules.yaml"
    assert rules_yaml.is_file()
    assert "no-float-for-money" in rules_yaml.read_text()


def test_cli_approve_rule_rejects_bad_regex(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "approve-rule",
        "--id", "bad",
        "--pattern", "[unclosed",
        "--description", "x",
        "--path", str(tmp_path),
    ])
    assert result.exit_code != 0


def test_cli_harvest_rules_applies_snake_case(tmp_path: Path):
    # Create a synthetic repo with 5 snake_case functions — crosses the 80% bar.
    (tmp_path / "demo.py").write_text(
        "def calculate_total():\n    pass\n"
        "def process_order():\n    pass\n"
        "def validate_input():\n    pass\n"
        "def fetch_user_data():\n    pass\n"
        "def save_record():\n    pass\n"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["harvest-rules", "--path", str(tmp_path), "--apply"])
    assert result.exit_code == 0, result.output
    assert "style-py-snake-case" in result.output
    rules_yaml = tmp_path / ".crb" / "rules.yaml"
    assert rules_yaml.is_file()
    assert "style-py-snake-case" in rules_yaml.read_text()


def test_cli_harvest_rules_no_conventions(tmp_path: Path):
    (tmp_path / "empty.py").write_text("# nothing here\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["harvest-rules", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "No dominant style conventions" in result.output
