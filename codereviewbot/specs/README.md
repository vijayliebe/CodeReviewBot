# Specs — Behavior-Driven Development for CodeReviewBot

These `.feature` files use Gherkin syntax (`Scenario` / `Given` / `When` / `Then`)
to specify the agent's behavior in **State → Action → Outcome** form, as
described in the Day 5 session on Spec-Driven Development.

## Files

- `code_review_pipeline.feature` — the end-to-end multi-agent review pipeline:
  hallucinated package detection, business-rule enforcement via the static
  pre-pass, cross-repo impact analysis, and the diff-aware incremental
  CodeMemory refresh (linear advance, skip, and force-push fallback).
- `skill_harvesting.feature` — the Skill Harvesting loop (Day 3): observing
  dominant style conventions, surfacing candidate rules, and approving them
  into durable `rules.yaml` procedural memory.

## Relationship to tests

Each `Scenario` maps to one or more pytest cases:

| Scenario | Test |
|---|---|
| Hallucinated package | `tests/test_package_validator.py::test_pypi_hallucinated_package` |
| no-float-for-money static pre-pass | `tests/test_token_budget_v2.py::test_run_static_analysis_finds_violations` |
| Cross-repo impact | `tests/test_end_to_end.py::test_full_pipeline_cross_repo_reference` |
| Lazy-at-review skip | `tests/test_incremental_index.py::test_refresh_index_if_stale_skips_when_current` |
| Force-push fallback | `tests/test_incremental_index.py::test_force_push_falls_back_to_hash_incremental` |
| Harvest dominant snake_case | `tests/test_rule_approver.py::test_harvest_suggested_rules_dominant_snake_case` |
| Approve single rule | `tests/test_rule_approver.py::test_cli_approve_rule_writes_yaml` |
| Reject invalid regex | `tests/test_rule_approver.py::test_cli_approve_rule_rejects_bad_regex` |
| No dominant convention | `tests/test_rule_approver.py::test_cli_harvest_rules_no_conventions` |

Run the full suite with:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```
