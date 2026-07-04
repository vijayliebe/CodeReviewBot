"""Skill Harvesting — persist auto-discovered patterns as durable rules.

Day 3 of the course describes "assisted authoring from traces": the agent
observes the codebase, surfaces repeating conventions, and the developer
approves the ones worth keeping. The approved rule is written into
``.crb/rules.yaml`` (procedural memory) so future reviews enforce it
without the LLM having to re-derive it.

This module is intentionally dependency-free (no ChromaDB, no LLM) so it can
run in any sandbox. Two entry points:

* ``append_rule(rules_path, rule)``  — write one rule into a rules.yaml
* ``harvest_suggested_rules(style_metrics)`` — turn a style summary into a
  list of *suggested* rules that a human can approve.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def append_rule(rules_path: Path, rule: dict[str, Any]) -> dict[str, Any]:
    """Append a single rule to the ``custom_rules`` list of a rules.yaml file.

    The file is created if missing. Idempotent: a rule with the same ``id``
    is replaced rather than duplicated, so re-approving an updated pattern
    updates it in place.
    """
    rules_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {}
    if rules_path.is_file():
        try:
            loaded = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                data = loaded
        except yaml.YAMLError:
            data = {}

    data.setdefault("custom_rules", [])
    custom = data["custom_rules"] or []

    rule_id = rule.get("id")
    if rule_id:
        custom = [r for r in custom if r.get("id") != rule_id]
    custom.append(rule)
    data["custom_rules"] = custom

    rules_path.write_text(
        "# CodeReviewBot rules — `custom_rules` are human-approved suggestions\n"
        "# harvested from observed codebase patterns.\n"
        + yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return {"rule_id": rule_id, "path": str(rules_path), "total_rules": len(custom)}


def harvest_suggested_rules(style_metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a style-summary dict into candidate rules for human approval.

    The style summary is produced by ``style_profiler.profile_style`` (or
    rehydrated from the ``codebase_metadata`` ChromaDB collection). We only
    surface *dominant* conventions (>= 80% of observed symbols) to avoid
    suggesting noisy rules.
    """
    suggestions: list[dict[str, Any]] = []

    fn_count = style_metrics.get("function_count", 0) or 0
    snake = style_metrics.get("snake_case_fns", 0) or 0
    camel = style_metrics.get("camelCase_fns", 0) or 0
    pascal_fn = style_metrics.get("PascalCase_fns", 0) or 0

    def _dominant(count: int) -> bool:
        return fn_count > 0 and count / fn_count >= 0.8

    if _dominant(snake):
        suggestions.append({
            "id": "style-py-snake-case",
            "description": "Functions in this repo are predominantly snake_case.",
            "pattern": r"^\s*def\s+[a-z]+[a-zA-Z0-9]*\s*\(",
            "severity": "low",
            "files": ["**/*.py"],
            "suggestion": "Rename to snake_case to match repo convention.",
            "source": "harvested:style_profiler",
        })
    elif _dominant(camel):
        suggestions.append({
            "id": "style-js-camel-case",
            "description": "Functions in this repo are predominantly camelCase.",
            "pattern": r"^\s*function\s+[a-z][a-zA-Z0-9]*\s*\(",
            "severity": "low",
            "files": ["**/*.js", "**/*.ts"],
            "suggestion": "Use camelCase for function names.",
            "source": "harvested:style_profiler",
        })

    classes = style_metrics.get("class_count", 0) or 0
    pascal_classes = style_metrics.get("PascalCase_classes", 0) or 0
    if classes > 0 and pascal_classes / classes >= 0.8:
        suggestions.append({
            "id": "style-pascal-classes",
            "description": "Classes in this repo are predominantly PascalCase.",
            "pattern": r"^\s*class\s+[a-z]",
            "severity": "low",
            "files": ["**/*.py", "**/*.js", "**/*.ts"],
            "suggestion": "Rename classes to PascalCase.",
            "source": "harvested:style_profiler",
        })

    return suggestions


def validate_pattern(pattern: str) -> bool:
    """Return True if the regex compiles, False otherwise."""
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False
