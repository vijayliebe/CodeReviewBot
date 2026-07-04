import os
import re
import yaml
from pathlib import Path

from src.platforms.registry import profile_repo
from src.utils.paths import repo_config_dir
from src.utils.rules_parser import parse_rules_file, check_file_rules
from src.memory.rule_harvester import generate_default_rules_file


def _load_manifest(manifest_path: Path) -> dict:
    with open(manifest_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_ground_truth(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("expected_findings", []) or data.get("tolerated_findings", [])


def _scan_repo_findings(repo_path: Path) -> list[dict]:
    """Scan repo using its own rules.yaml merged with platform-injected rules."""
    from src.platforms.registry import profile_repo, collect_rules

    rules_dir = repo_config_dir(repo_path)
    rules_yaml = rules_dir / "rules.yaml"
    if not rules_yaml.is_file():
        profile = profile_repo(repo_path)
        generate_default_rules_file(profile.to_dict(), rules_dir)

    config = parse_rules_file(rules_yaml)

    # Merge platform-injected rules (dedup by rule id) so platform checks
    # (bare-except, no-print-statements, mobile rules, ai_agent rules) fire
    # even when the repo's rules.yaml only defines custom business rules.
    profile = profile_repo(repo_path)
    platform_rules = collect_rules(profile.to_dict())
    existing_ids = {r.get("id") for r in config.get("rules", [])}
    for rule in platform_rules:
        if rule.get("id") not in existing_ids:
            rule = dict(rule)
            rule.setdefault("category", "Platform")
            config.setdefault("rules", []).append(rule)
            existing_ids.add(rule.get("id"))

    findings: list[dict] = []
    skip = {".venv", "node_modules", ".git", "__pycache__"}
    for path in repo_path.rglob("*"):
        if not path.is_file() or any(s in path.parts for s in skip):
            continue
        if path.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".swift", ".kt", ".dart", ".tf"}:
            continue
        rel = str(path.relative_to(repo_path))
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings.extend(check_file_rules(rel, content, config))
    return findings


def _matches_any_actual(expected: dict, actual: list[dict]) -> bool:
    """An expected finding is a TP if rule_id + file match (line optional/fuzzy)."""
    for act in actual:
        if act["rule_id"] != expected.get("rule_id"):
            continue
        if act["file"] != expected.get("file"):
            continue
        if expected.get("line") and act["line"] != expected["line"]:
            continue
        return True
    return False


def _is_expected_fp(actual: dict, expected: list[dict], tolerated: list[dict]) -> bool:
    """An actual finding is a real FP only if not expected and not tolerated."""
    for exp in expected:
        if exp.get("rule_id") == actual["rule_id"] and exp.get("file") == actual["file"]:
            return False
    for tol in tolerated:
        if tol.get("rule_id") == actual["rule_id"] and tol.get("file") == actual["file"]:
            return False
    return True


def run_scorecard(manifest_path: Path) -> dict:
    manifest = _load_manifest(manifest_path)
    manifest_dir = manifest_path.parent
    results = []
    total_tp = total_fp = total_fn = 0
    weighted_tp = weighted_fp = weighted_fn = 0.0

    for entry in manifest.get("repos", []):
        repo_path = (manifest_dir / entry["path"]).resolve()
        gt_path = manifest_dir / entry["ground_truth"]
        expected = _load_ground_truth(gt_path)

        gt_full_path = gt_path.parent / (gt_path.stem + "_tolerated.yaml")
        tolerated = _load_ground_truth(gt_full_path)

        actual = _scan_repo_findings(repo_path)
        weight = float(entry.get("weight", 1.0))

        tp = sum(1 for e in expected if _matches_any_actual(e, actual))
        fn = len(expected) - tp
        fp = sum(1 for a in actual if _is_expected_fp(a, expected, tolerated))

        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        total_tp += tp
        total_fp += fp
        total_fn += fn
        weighted_tp += tp * weight
        weighted_fp += fp * weight
        weighted_fn += fn * weight

        profile = profile_repo(repo_path)
        results.append({
            "id": entry["id"],
            "path": str(repo_path),
            "weight": weight,
            "kind": entry.get("kind", "violation"),
            "adapters": profile.platform_adapters,
            "expected": len(expected),
            "actual": len(actual),
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        })

    overall_p = weighted_tp / (weighted_tp + weighted_fp) if (weighted_tp + weighted_fp) else 1.0
    overall_r = weighted_tp / (weighted_tp + weighted_fn) if (weighted_tp + weighted_fn) else 1.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) else 0.0

    return {
        "summary": {
            "repos_tested": len(results),
            "true_positives": total_tp,
            "false_positives": total_fp,
            "false_negatives": total_fn,
            "precision": round(overall_p, 3),
            "recall": round(overall_r, 3),
            "f1": round(overall_f1, 3),
        },
        "repos": results,
    }


def format_scorecard_report(report: dict) -> str:
    lines = [
        "CodeReviewBot Benchmark Scorecard",
        "=" * 60,
        f"Repos tested: {report['summary']['repos_tested']}",
        f"Precision:    {report['summary']['precision']:.1%}",
        f"Recall:       {report['summary']['recall']:.1%}",
        f"F1:           {report['summary']['f1']:.1%}",
        f"TP/FP/FN:     {report['summary']['true_positives']}/{report['summary']['false_positives']}/{report['summary']['false_negatives']}",
        "",
        "Per-repo:",
    ]
    for r in report["repos"]:
        lines.append(
            f"  {r['id']:22} w={r['weight']:.1f} kind={r['kind']:10} adapters={r['adapters']}\n"
            f"  {'':22} P={r['precision']:.0%} R={r['recall']:.0%} F1={r['f1']:.0%}  "
            f"(TP={r['true_positives']} FP={r['false_positives']} FN={r['false_negatives']})"
        )
    return "\n".join(lines)
