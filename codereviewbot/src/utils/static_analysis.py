"""Static-first analysis — run all regex rules locally for free, before any LLM call.

The Business Rules LLM agent is expensive. Most business-rule findings are simple
regex matches that `check_file_rules` already computes locally. By running the
merged rule set (shared + repo + platform) against every changed file *before*
invoking the LLM, we can:

  1. Pass the LLM a compact `STATIC_FINDINGS` block so it doesn't re-derive them
     (saves reasoning tokens).
  2. Let the LLM focus on ambiguous cases, cross-repo impact, and inline-rule
     intent — the parts that actually need language understanding.

This module is deliberately framework-agnostic and side-effect-free.
"""

import json
import re
from pathlib import Path

from src.utils.token_budget import extract_changed_files, should_skip_file
from src.utils.rules_parser import parse_rules_file, check_file_rules
from src.utils.paths import find_rules_yaml, get_workspace_root
from src.workspace.store import load_shared_rules
from src.platforms.registry import collect_rules, profile_repo


def _extract_added_lines(diff_text: str, file_path: str) -> list[str]:
    """Return the `+` lines (added content) for a given file from the diff."""
    lines = diff_text.splitlines()
    in_file = False
    in_hunk = False
    added: list[str] = []
    for line in lines:
        if line.startswith("diff --git"):
            in_file = line.endswith(f" b/{file_path}") or f" b/{file_path} " in line
            in_hunk = False
            continue
        if not in_file:
            continue
        if line.startswith("@@"):
            in_hunk = True
            continue
        if in_hunk and line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    return added


def _merged_rules_for_repo(repo_root: Path) -> list[dict]:
    """Merge workspace shared rules + repo rules.yaml + platform rules, deduped by rule_id."""
    merged: dict[str, dict] = {}

    for r in load_shared_rules(get_workspace_root()):
        rid = r.get("id") or f"_shared_{len(merged)}"
        merged[rid] = r

    rules_path = find_rules_yaml(repo_root)
    if rules_path:
        for r in parse_rules_file(rules_path).get("rules", []):
            rid = r.get("id") or f"_repo_{len(merged)}"
            merged[rid] = r  # repo overrides shared

    try:
        profile = profile_repo(repo_root)
        for r in collect_rules(profile):
            rid = r.get("id") or f"_platform_{len(merged)}"
            # Platform rules only fill in gaps; never override repo/shared.
            if rid not in merged:
                merged[rid] = r
    except Exception:
        pass

    return list(merged.values())


def run_static_analysis(diff_text: str, repo_root: Path | None = None) -> dict:
    """Run all merged regex rules against the added lines of every changed file.

    Returns a compact dict:
      {
        "files_scanned": N,
        "files_skipped": M,
        "findings": [ {rule_id, severity, file, line, description, suggestion} ],
        "files_with_no_findings": [...]
      }

    This is the free, local pre-pass. The LLM Business Rules agent should receive
    this as STATIC_FINDINGS and avoid re-deriving them.
    """
    repo_root = (repo_root or get_workspace_root()).resolve()
    changed = [f for f in extract_changed_files(diff_text) if not should_skip_file(f)]

    rules = _merged_rules_for_repo(repo_root)
    findings: list[dict] = []
    scanned = 0
    skipped = 0
    clean: list[str] = []

    for rel_path in changed:
        # Try to read the file locally to run rules against full content (more accurate
        # than diff-only). If the file doesn't exist (e.g. deleted), skip.
        candidate = (repo_root / rel_path).resolve()
        try:
            if not candidate.is_file() or not str(candidate).startswith(str(repo_root)):
                skipped += 1
                continue
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped += 1
            continue

        file_findings = check_file_rules(rel_path, content, {"rules": rules})
        scanned += 1
        if file_findings:
            for f in file_findings:
                findings.append({
                    "rule_id": f["rule_id"],
                    "severity": f["severity"],
                    "category": f["category"],
                    "file": f["file"],
                    "line": f["line"],
                    "description": f["description"],
                    "suggestion": f["suggestion"],
                    "source": "static-pre-pass",
                })
        else:
            clean.append(rel_path)

    return {
        "files_scanned": scanned,
        "files_skipped": skipped,
        "findings": findings,
        "files_with_no_findings": clean,
    }


def format_static_findings(summary: dict, max_findings: int = 30) -> str:
    """Compact markdown block to inject into the LLM query as STATIC_FINDINGS."""
    if not summary or not summary.get("findings"):
        return (
            "## STATIC_FINDINGS (from local pre-pass — do NOT re-derive these)\n"
            f"- Files scanned locally: {summary.get('files_scanned', 0)}\n"
            f"- Files skipped (lockfile/binary/unreadable): {summary.get('files_skipped', 0)}\n"
            "- Findings: none from static rules. Focus on ambiguous / cross-repo impact."
        )

    shown = summary["findings"][:max_findings]
    lines = [
        "## STATIC_FINDINGS (from local pre-pass — do NOT re-derive these)",
        f"- Files scanned locally: {summary['files_scanned']}",
        f"- Files skipped: {summary['files_skipped']}",
        f"- Static findings: {len(summary['findings'])} (showing {len(shown)})",
        "",
    ]
    for f in shown:
        lines.append(
            f"- [{f['severity']}] {f['rule_id']} in {f['file']}:{f['line']} — {f['description']}"
        )
    if len(summary["findings"]) > max_findings:
        lines.append(f"... and {len(summary['findings']) - max_findings} more (omitted for token budget)")
    lines.append("")
    lines.append("Focus your analysis on AMBIGUOUS cases, cross-repo impact, and inline-rule intent.")
    return "\n".join(lines)


def static_findings_json(summary: dict) -> str:
    """JSON-encoded summary for the LLM query (compact, no indentation)."""
    return json.dumps(summary, separators=(",", ":"))
