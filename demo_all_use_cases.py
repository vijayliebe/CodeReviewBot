#!/usr/bin/env python3
"""Demonstrate CodeReviewBot use-cases and functionality end-to-end.

Walks through workspace setup, repo profiling, CodeMemory indexing, static
pre-pass, skill harvesting, golden-set benchmark, and (optionally) the full
multi-agent ADK review pipeline — starting from a clean local workspace.

Usage:
  cd codereviewbot && source .venv/bin/activate

  python ../demo_all_use_cases.py              # all, no LLM
  python ../demo_all_use_cases.py --fresh      # wipe .crb-workspace first
  python ../demo_all_use_cases.py --list       # show use-cases
  python ../demo_all_use_cases.py --only workspace
  python ../demo_all_use_cases.py --with-llm   # include live review
  python ../demo_all_use_cases.py --pause 2    # pause between steps

Environment:
  CRB_WORKSPACE_ROOT  — monorepo root (default: parent of codereviewbot/)
  GOOGLE_API_KEY      — required only for --with-llm live review
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent
KAGGLE_DIR = REPO_ROOT / ".docs" / "kaggle_submission"
CRB_DIR = REPO_ROOT / "codereviewbot"
WORKSPACE_DIR = REPO_ROOT / ".crb-workspace"
BENCHMARK_ROOT = REPO_ROOT / "benchmark_repos"
PATCH = CRB_DIR / "tests" / "fixtures" / "sample_pr_diff.patch"
SAMPLE_REVIEW_REPORT = REPO_ROOT / "sample_review_report.md"
SAMPLE_REVIEW_OUTPUT = REPO_ROOT / "sample_review_output.txt"
LIVE_REVIEW = False
ARTIFACTS_GENERATED = False

# Import project modules after PYTHONPATH is set (see _bootstrap).
def _bootstrap() -> None:
    os.environ.setdefault("CRB_WORKSPACE_ROOT", str(REPO_ROOT))
    if str(CRB_DIR) not in sys.path:
        sys.path.insert(0, str(CRB_DIR))
    try:
        from dotenv import load_dotenv

        load_dotenv(CRB_DIR / ".env")
    except ImportError:
        pass


@dataclass(frozen=True)
class UseCase:
    id: str
    title: str
    summary: str
    needs_llm: bool
    run: Callable[[], None]
    commands: tuple[str, ...] = ()
    regex_rules: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hr(char: str = "─") -> None:
    print(char * 72, flush=True)


def _section(num: int, total: int, uc: UseCase) -> None:
    print(f"\n{'=' * 72}")
    print(f"  USE CASE {num}/{total}: {uc.title}")
    print(f"  ID: {uc.id}")
    print(f"  {uc.summary}")
    if uc.commands:
        print("  Commands:")
        for cmd in uc.commands:
            print(f"    $ {cmd}")
    if uc.regex_rules:
        print("  Regex rules:")
        for rule in uc.regex_rules:
            print(f"    • {rule}")
    print("=" * 72 + "\n", flush=True)


def _subsection(title: str, *, command: str | None = None, note: str = "") -> None:
    print(f"\n── {title} {'─' * max(0, 66 - len(title))}\n", flush=True)
    if command:
        line = f"  $ {command}"
        if note:
            line += f"   # {note}"
        print(line + "\n", flush=True)


def _api_step(label: str) -> None:
    """Mark a Python API step (no separate CLI subcommand)."""
    print(f"  $ # API: {label}\n", flush=True)


def _print_regex_rules(rules: list[dict[str, Any]], *, limit: int = 10) -> None:
    if not rules:
        print("  (no regex rules loaded)")
        return
    print("  Regex rules applied:")
    for rule in rules[:limit]:
        pattern = rule.get("pattern", "")
        rid = rule.get("id", "?")
        sev = rule.get("severity", "?")
        print(f"    • {rid} [{sev}]  pattern={pattern!r}")
    if len(rules) > limit:
        print(f"    … and {len(rules) - limit} more")


def _codereviewbot(*args: str, check: bool = True, echo_cmd: bool = True) -> subprocess.CompletedProcess:
    venv_bin = CRB_DIR / ".venv" / "bin" / "codereviewbot"
    exe = str(venv_bin) if venv_bin.exists() else "codereviewbot"
    cmd = [exe, *args]
    if echo_cmd:
        print(f"  $ {' '.join(cmd)}\n", flush=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(CRB_DIR)
    env.setdefault("CRB_WORKSPACE_ROOT", str(REPO_ROOT))
    proc = subprocess.run(cmd, cwd=CRB_DIR, env=env, text=True, capture_output=False)
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


def _codereviewbot_capture(*args: str, check: bool = True, echo_cmd: bool = True) -> str:
    """Run codereviewbot and return combined stdout/stderr (also printed live)."""
    venv_bin = CRB_DIR / ".venv" / "bin" / "codereviewbot"
    exe = str(venv_bin) if venv_bin.exists() else "codereviewbot"
    cmd = [exe, *args]
    if echo_cmd:
        print(f"  $ {' '.join(cmd)}\n", flush=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(CRB_DIR)
    env.setdefault("CRB_WORKSPACE_ROOT", str(REPO_ROOT))
    proc = subprocess.run(cmd, cwd=CRB_DIR, env=env, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout, end="", flush=True)
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr, flush=True)
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc.stdout + proc.stderr


def _rel(path: Path) -> str:
    return os.path.relpath(path, CRB_DIR)


def _pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _has_api_key() -> bool:
    key = os.environ.get("GOOGLE_API_KEY", "")
    return bool(key and key != "your_gemini_api_key_here")


def _fresh_workspace() -> None:
    """Remove local workspace config so the demo starts from scratch."""
    import shutil

    if WORKSPACE_DIR.exists():
        shutil.rmtree(WORKSPACE_DIR)
        print(f"Removed {WORKSPACE_DIR}")
    else:
        print(f"No existing {WORKSPACE_DIR} — starting clean")


def _patch_file_contents(diff_text: str) -> dict[str, str]:
    """Extract added-line content per file from a unified diff."""
    from src.utils.static_analysis import _extract_added_lines
    from src.utils.token_budget import extract_changed_files

    filtered = diff_text
    contents: dict[str, str] = {}
    for rel in extract_changed_files(filtered):
        lines = _extract_added_lines(filtered, rel)
        if lines:
            contents[rel] = "\n".join(lines) + "\n"
    return contents


def _heuristic_findings(patch_files: dict[str, str]) -> list[dict[str, Any]]:
    """Deterministic findings for the sample patch (LLM-style agents, no API call)."""
    findings: list[dict[str, Any]] = []

    for path, content in patch_files.items():
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            if "API_KEY" in line and "sk_" in line:
                findings.append({
                    "agent": "security",
                    "severity": "CRITICAL",
                    "file": path,
                    "line": i,
                    "description": "Hardcoded API key detected.",
                    "suggestion": "Store API keys in environment variables or a secrets manager.",
                })
            if "py_fake_cryptography_pkg" in line:
                findings.append({
                    "agent": "security",
                    "severity": "HIGH",
                    "file": path,
                    "line": i,
                    "description": "Package `py_fake_cryptography_pkg` not found on PyPI (hallucinated dependency).",
                    "suggestion": "Remove or replace with a verified cryptography library.",
                })
            if "cur.execute(f" in line:
                findings.append({
                    "agent": "security",
                    "severity": "HIGH",
                    "file": path,
                    "line": i,
                    "description": "SQL injection risk — f-string in cur.execute().",
                    "suggestion": 'Use cur.execute("... %s", (payment_id,))',
                })
            if re.search(r"def getPaymentDetails", line):
                findings.append({
                    "agent": "style",
                    "severity": "WARNING",
                    "file": path,
                    "line": i,
                    "description": "Function name `getPaymentDetails` uses camelCase; repo convention is snake_case.",
                    "suggestion": "Rename to `get_payment_details`.",
                })
            if "float(" in line and "amount" in line:
                findings.append({
                    "agent": "impact",
                    "severity": "HIGH",
                    "file": path,
                    "line": i,
                    "description": "Using float for currency calculations — precision risk.",
                    "suggestion": "Use Decimal or integer cents for monetary values.",
                })
            if 'r.set(f"refund:' in line:
                findings.append({
                    "agent": "impact",
                    "severity": "MEDIUM",
                    "file": path,
                    "line": i,
                    "description": "Redis key lacks required service prefix (e.g. payment-).",
                    "suggestion": "Prefix keys with the service name.",
                })

        if path == "views.py" and "get_transaction_status" in content:
            if not re.search(r"^\s*@login_required\b", content, re.MULTILINE):
                findings.append({
                    "agent": "security",
                    "severity": "MEDIUM",
                    "file": path,
                    "line": 5,
                    "description": "API handler missing @login_required decorator.",
                    "suggestion": "Add authentication decorator to restrict access.",
                })
        if path == "views.py" and "getPaymentDetails" in content:
            findings.append({
                "agent": "style",
                "severity": "WARNING",
                "file": path,
                "line": 8,
                "description": "Calls camelCase function inconsistent with snake_case convention.",
                "suggestion": "Rename called function to snake_case.",
            })
        if path == "payment_handler.py" and "for oid in order_ids" in content and "cur.execute" in content:
            findings.append({
                "agent": "impact",
                "severity": "HIGH",
                "file": path,
                "line": 38,
                "description": "N+1 query pattern — SELECT inside a loop over order_ids.",
                "suggestion": "Batch fetch with WHERE order_id IN (...).",
            })

    return findings


def _enrich_profile_from_patch(profile: dict[str, Any], patch_files: dict[str, str]) -> dict[str, Any]:
    """Infer integration layers from patch imports (matches live review on new files)."""
    enriched = dict(profile)
    content = "\n".join(patch_files.values())
    layers: dict[str, str] = dict(enriched.get("integration_layers") or {})
    if "redis" in content and "cache" not in layers:
        layers["cache"] = "redis"
    if "psycopg2" in content and "db" not in layers:
        layers["db"] = "postgresql"
    enriched["integration_layers"] = layers
    return enriched


def _rules_for_patch_review(repo_root: Path, patch_files: dict[str, str]) -> list[dict[str, Any]]:
    """Effective rules plus integration-layer rules inferred from the patch."""
    from src.platforms._shared import INTEGRATION_DB_RULES, INTEGRATION_REDIS_RULES
    from src.workspace.store import get_effective_rules

    rules = list(get_effective_rules(repo_root, REPO_ROOT))
    seen = {r.get("id") for r in rules}
    content = "\n".join(patch_files.values())
    extra: list[dict] = []
    if "redis" in content:
        extra.extend(INTEGRATION_REDIS_RULES)
    if "psycopg2" in content:
        extra.extend(INTEGRATION_DB_RULES)
    for rule in extra:
        rid = rule.get("id")
        if rid and rid not in seen:
            rules.append(dict(rule))
            seen.add(rid)
    return rules


@dataclass
class ReviewAnalysis:
    profile: dict[str, Any]
    compact_diff: str
    token_before: int
    token_after: int
    static_summary: dict[str, Any]
    rule_findings: list[dict[str, Any]]
    heuristic_findings: list[dict[str, Any]] = field(default_factory=list)


def _analyze_sample_patch() -> ReviewAnalysis:
    """Build review inputs from the sample patch (no LLM)."""
    from src.platforms.registry import profile_repo
    from src.utils.rules_parser import check_file_rules
    from src.utils.static_analysis import format_static_findings, run_static_analysis
    from src.utils.token_budget import compact_diff, estimate_tokens, filter_diff
    from src.workspace.store import get_effective_rules

    backend = BENCHMARK_ROOT / "backend_service"
    raw = PATCH.read_text()
    filtered = filter_diff(raw)
    compact = compact_diff(filtered)
    patch_files = _patch_file_contents(filtered)
    profile = _enrich_profile_from_patch(profile_repo(backend).to_dict(), patch_files)
    rules = _rules_for_patch_review(backend, patch_files)

    rule_findings: list[dict[str, Any]] = []
    for rel, content in patch_files.items():
        for f in check_file_rules(rel, content, {"rules": rules}):
            rule_findings.append({**f, "agent": "rules"})

    static_summary = run_static_analysis(filtered, backend)
    if not static_summary["findings"] and patch_files:
        static_findings = []
        for rel, content in patch_files.items():
            for f in check_file_rules(rel, content, {"rules": rules}):
                static_findings.append({
                    "rule_id": f["rule_id"],
                    "severity": f["severity"],
                    "category": f.get("category", "Rules"),
                    "file": f["file"],
                    "line": f["line"],
                    "description": f["description"],
                    "suggestion": f["suggestion"],
                    "source": "static-pre-pass",
                })
        static_summary = {
            **static_summary,
            "files_scanned": len(patch_files),
            "files_skipped": max(0, static_summary["files_skipped"] - len(patch_files)),
            "findings": static_findings,
        }

    return ReviewAnalysis(
        profile=profile,
        compact_diff=compact,
        token_before=estimate_tokens(raw),
        token_after=estimate_tokens(compact),
        static_summary=static_summary,
        rule_findings=rule_findings,
        heuristic_findings=_heuristic_findings(patch_files),
    )


def _risk_rating(analysis: ReviewAnalysis) -> str:
    severities = {
        f.get("severity", "").upper()
        for f in analysis.rule_findings + analysis.heuristic_findings
    }
    if "CRITICAL" in severities:
        return "CRITICAL"
    if "HIGH" in severities:
        return "HIGH"
    return "MEDIUM"


def _format_offline_terminal_output(analysis: ReviewAnalysis) -> str:
    from src.utils.static_analysis import format_static_findings

    p = analysis.profile
    layers = p.get("integration_layers") or {}
    integration_parts: list[str] = []
    if layers.get("cache"):
        integration_parts.append("Redis" if "redis" in str(layers["cache"]).lower() else str(layers["cache"]))
    if layers.get("db"):
        integration_parts.append(
            "PostgreSQL" if "postgres" in str(layers["db"]).lower() else str(layers["db"])
        )
    layer_str = ", ".join(integration_parts) or "none detected"
    lines = [
        f"📉 Diff: {analysis.token_before} → {analysis.token_after} tokens "
        f"({analysis.token_before - analysis.token_after} saved)",
        f"🔍 Static pre-pass: {analysis.static_summary['files_scanned']} file(s) scanned, "
        f"{len(analysis.static_summary['findings'])} finding(s)",
        f"🚀 Reviewing change: tests/fixtures/sample_pr_diff.patch",
        f"   Adapters: {', '.join(p.get('platform_adapters') or ['generic'])}",
        "[profiler_agent]: **REPO_PROFILE**:",
        f"- Languages: {', '.join(p.get('languages') or ['none'])}",
        f"- Frameworks: {', '.join(p.get('frameworks') or ['none']) or 'none detected'}",
        f"- Platform adapters: {', '.join(p.get('platform_adapters') or ['generic'])}",
        f"- Architecture: {p.get('architecture', 'unknown')} | Kind: {p.get('repo_kind', 'application')}",
        f"- Integration layers: {layer_str}",
    ]
    lines.extend(["", "**DIFF_SUMMARY**:", "```diff", analysis.compact_diff.rstrip(), "```"])

    sec = [f for f in analysis.heuristic_findings if f["agent"] == "security"]
    if sec:
        lines.append("[security_auditor]: 🔒 SECURITY FINDINGS")
        for f in sec:
            lines.extend([
                f"- Severity: {f['severity']}",
                f"  File: {f['file']}",
                f"  Line: {f['line']}",
                f"  Description: {f['description']}",
                f"  Fix Suggestion: {f['suggestion']}",
                "",
            ])

    sty = [f for f in analysis.heuristic_findings if f["agent"] == "style"]
    if sty:
        lines.append("[style_checker]: 🎨 STYLE FINDINGS")
        for f in sty:
            lines.extend([
                f"- File: {f['file']}",
                f"  Line: {f['line']}",
                f"  Finding: {f['description']}",
                f"  Suggestion: {f['suggestion']}",
                "",
            ])

    imp = [f for f in analysis.heuristic_findings if f["agent"] == "impact"]
    if imp:
        lines.append("[impact_analyzer]: 💥 IMPACT & INTEGRATION FINDINGS")
        for f in imp:
            lines.extend([
                f"*   **Severity**: {f['severity']}",
                f"    *   **Description**: {f['description']}",
                f"    *   **Files/Repos Affected**: `{f['file']}`",
                f"    *   **Suggestion**: {f['suggestion']}",
                "",
            ])

    if analysis.rule_findings:
        lines.append("[business_rules_checker]: 📏 BUSINESS RULES FINDINGS")
        for f in analysis.rule_findings:
            lines.extend([
                f"- Rule ID: `{f['rule_id']}`",
                f"  - Severity: {f['severity'].upper()}",
                f"  - File: `{f['file']}`",
                f"  - Line: {f['line']}",
                f"  - Description: {f['description']}",
                f"  - Suggestion: {f.get('suggestion', '')}",
            ])

    rating = _risk_rating(analysis)
    narrative = _build_summary_narrative(analysis, rating)
    lines.extend([
        "[summary_generator]:",
        f"**Overall PR Risk Rating: {rating}**",
        "",
        narrative,
        "",
        format_static_findings(analysis.static_summary),
    ])
    return "\n".join(lines) + "\n"


_AGENT_SECTION_TITLES = {
    "profiler_agent": "Repository Profile & Diff",
    "security_auditor": "🔒 Security Findings",
    "style_checker": "🎨 Style Findings",
    "impact_analyzer": "💥 Impact & Integration Findings",
    "business_rules_checker": "📋 Business Rules Findings",
    "summary_generator": "📝 Summary & Recommendation",
}

_AGENT_MARKERS = re.compile(
    r"\[(profiler_agent|security_auditor|style_checker|impact_analyzer|"
    r"business_rules_checker|summary_generator)\]:\s*"
)


def _build_summary_narrative(analysis: ReviewAnalysis, rating: str) -> str:
    """Short narrative like the live Summary Generator agent."""
    sec = sum(1 for f in analysis.heuristic_findings if f["agent"] == "security")
    rules = len(analysis.rule_findings)
    parts = [
        f"This pull request has **{rating}** overall risk.",
        f"Security auditor flagged {sec} issue(s); business rules checker flagged {rules} violation(s).",
        "Address hardcoded secrets, SQL injection, and monetary float usage before merge.",
        "Add authentication on API handlers and fix integration-layer contracts (Redis key prefix, N+1 queries).",
    ]
    return " ".join(parts)


def _markdown_report_from_terminal(terminal: str, *, source: str = "offline") -> str:
    """Build a full Markdown report mirroring all agent sections in the terminal output."""
    lines = [
        "# CodeReviewBot — Sample Review Report",
        "",
        "Representative output from:",
        "",
        "```bash",
        "codereviewbot review --pr tests/fixtures/sample_pr_diff.patch \\",
        "  --repo ../benchmark_repos/backend_service --sequential",
        "```",
        "",
        f"*Source: {source} review capture*",
        "",
        "---",
        "",
        "## Review pipeline",
        "",
    ]
    for raw in terminal.splitlines():
        stripped = raw.strip()
        if stripped.startswith(("📉", "🔍", "🚀", "🔄", "🧠")) or stripped.startswith("Adapters:"):
            lines.append(f"- {stripped}")
        if stripped.startswith("Log setup"):
            break

    parts = _AGENT_MARKERS.split(terminal)
    idx = 1
    while idx < len(parts) - 1:
        agent_id = parts[idx]
        body = parts[idx + 1].strip()
        title = _AGENT_SECTION_TITLES.get(agent_id, agent_id)
        # Drop redundant agent banner line (e.g. "🔒 SECURITY FINDINGS")
        body = re.sub(
            r"^[🔒🎨💥📏🤖]\s*.+FINDINGS\s*\n+",
            "",
            body,
            count=1,
        )
        lines.extend(["", "---", "", f"## {title}", ""])
        if agent_id == "summary_generator" and body.startswith("```"):
            body = re.sub(r"^```\w*\n?", "", body)
            body = re.sub(r"\n?```\s*$", "", body.strip())
        lines.append(body)
        idx += 2

    lines.extend([
        "",
        "---",
        "",
        "## Full terminal log",
        "",
        "The complete multi-agent terminal output is saved in `sample_review_output.txt`.",
        "",
    ])
    return "\n".join(lines) + "\n"


def generate_sample_review_artifacts(*, live: bool = False) -> tuple[str, str]:
    """Run or simulate review; write sample_review_output.txt + sample_review_report.md."""
    global ARTIFACTS_GENERATED
    analysis = _analyze_sample_patch()
    terminal = ""
    source = "offline"

    # Prefer live capture when API key is available (matches `codereviewbot review` directly).
    if _has_api_key():
        print("  GOOGLE_API_KEY set — running live codereviewbot review for sample artifacts...")
        try:
            terminal = _codereviewbot_capture(
                "review",
                "--pr", str(PATCH),
                "--repo", _rel(BENCHMARK_ROOT / "backend_service"),
                "--sequential",
            )
            source = "live"
        except SystemExit:
            print("⚠ Live review failed — falling back to offline artifact generation.")
            terminal = ""
    elif live:
        print("⚠ GOOGLE_API_KEY not set — generating offline sample artifacts.")

    if not terminal:
        terminal = _format_offline_terminal_output(analysis)
        source = "offline"

    report = _markdown_report_from_terminal(terminal, source=source)
    SAMPLE_REVIEW_OUTPUT.write_text(terminal, encoding="utf-8")
    SAMPLE_REVIEW_REPORT.write_text(report, encoding="utf-8")
    ARTIFACTS_GENERATED = True
    print(f"\n✔ Wrote {SAMPLE_REVIEW_OUTPUT}")
    print(f"✔ Wrote {SAMPLE_REVIEW_REPORT} ({source})")
    return terminal, report


def _show_sample_review_output() -> None:
    """Print generated sample review terminal output."""
    if not SAMPLE_REVIEW_OUTPUT.is_file():
        print(f"  ⚠ Not generated yet: {SAMPLE_REVIEW_OUTPUT}")
        return
    _subsection("Sample review terminal output")
    print(SAMPLE_REVIEW_OUTPUT.read_text(encoding="utf-8"), end="")


def _print_setup_guide() -> None:
    print("End-to-end setup (commands run in order below):\n")
    steps = [
        ("1", "workspace init", "Create .crb-workspace/ (local, gitignored)"),
        ("2", "workspace register + link", "Multi-repo registry and upstream/downstream contracts"),
        ("3", "index", "Build CodeMemory for each registered repo (ChromaDB under .crb-workspace/)"),
        ("4", "review", "Multi-agent review — sample artifacts written at end of demo"),
        ("5", "benchmark", "Golden-set regression scorecard — local rules only, no LLM"),
    ]
    for num, cmd, desc in steps:
        print(f"  {num}. codereviewbot {cmd:<28} — {desc}")
    print("\nPer-repo rules come from benchmark_repos/*/.crb/ (in git).")
    print("Run `init --path` only for repos you add yourself.\n")


# ---------------------------------------------------------------------------
# Use-case implementations
# ---------------------------------------------------------------------------

def uc_repo_profiling() -> None:
    """Multi-platform stack detection (read-only — rules live in benchmark_repos/*/.crb/)."""
    from src.platforms.registry import profile_repo

    _subsection(
        "Rules source for this demo",
        command="codereviewbot init --path ../benchmark_repos/<repo>",
        note="only for new repos; benchmark rules are in git",
    )
    print("  benchmark_repos/*/.crb/rules.yaml are committed golden-set fixtures.")
    print()

    demos = [
        (BENCHMARK_ROOT / "backend_service", "Generic Python backend (Redis, PostgreSQL)"),
        (BENCHMARK_ROOT / "django_app", "Django web app → python_web adapter"),
        (BENCHMARK_ROOT / "ai_agent_repo", "AI agent repo → ai_agent adapter"),
        (BENCHMARK_ROOT / "flutter_app", "Flutter mobile → mobile adapter"),
        (BENCHMARK_ROOT / "frontend_app", "React/JS frontend"),
    ]
    for repo, label in demos:
        _subsection(
            label,
            command=f"profile_repo({_rel(repo)})",
            note="read-only Python API — stack detection",
        )
        data = profile_repo(repo).to_dict()
        print(f"  Languages:         {', '.join(data['languages']) or 'none'}")
        print(f"  Frameworks:        {', '.join(data['frameworks']) or 'none'}")
        print(f"  Platform adapters: {', '.join(data['platform_adapters']) or 'generic'}")
        print(f"  Architecture:      {data['architecture']} ({data['repo_kind']})")
        rules_path = repo / ".crb" / "rules.yaml"
        print(f"  Rules file:        {rules_path.relative_to(REPO_ROOT)} ({'present' if rules_path.is_file() else 'missing'})")


def uc_workspace() -> None:
    """Multi-repo registry, upstream/downstream links, shared rules."""
    _subsection("Starting state")
    if WORKSPACE_DIR.exists():
        print(f"  {WORKSPACE_DIR} exists — continuing with current config")
    else:
        print(f"  No {WORKSPACE_DIR} yet — first-time workspace setup")

    _subsection("Step 1 — workspace init", command="codereviewbot workspace init --product codereviewbot-demo")
    _codereviewbot("workspace", "init", "--product", "codereviewbot-demo", echo_cmd=False)

    _subsection(
        "Step 2 — register benchmark repos",
        command="codereviewbot workspace register --id backend_service --path benchmark_repos/backend_service --kind backend",
    )
    _codereviewbot(
        "workspace", "register",
        "--id", "backend_service",
        "--path", "benchmark_repos/backend_service",
        "--kind", "backend",
        echo_cmd=False,
    )
    _subsection(
        "Register frontend",
        command="codereviewbot workspace register --id frontend_app --path benchmark_repos/frontend_app --kind frontend",
    )
    _codereviewbot(
        "workspace", "register",
        "--id", "frontend_app",
        "--path", "benchmark_repos/frontend_app",
        "--kind", "frontend",
        echo_cmd=False,
    )

    _subsection(
        "Step 3 — link consumer → provider",
        command='codereviewbot workspace link --consumer frontend_app --provider backend_service --contract "REST /api/billing"',
    )
    _codereviewbot(
        "workspace", "link",
        "--consumer", "frontend_app",
        "--provider", "backend_service",
        "--contract", "REST /api/billing",
        echo_cmd=False,
    )

    _subsection("Step 4 — verify workspace", command="codereviewbot workspace show")
    _codereviewbot("workspace", "show", echo_cmd=False)


def uc_business_rules() -> None:
    """3-tier rules: platform + shared + repo + inline `# crb:ignore`."""
    from src.platforms.registry import profile_repo, collect_rules
    from src.utils.rules_parser import check_file_rules, find_inline_annotations
    from src.workspace.store import get_effective_rules

    backend = BENCHMARK_ROOT / "backend_service"
    _subsection(
        "Effective rules merge (platform ∪ shared ∪ repo)",
        command="get_effective_rules(backend_service)",
        note="Python API — merges shared + repo + platform rules",
    )
    effective = get_effective_rules(backend, REPO_ROOT)
    print(f"Total effective rules for backend_service: {len(effective)}")
    _print_regex_rules(effective)
    print()
    for rule in effective[:8]:
        print(f"  • {rule['id']} [{rule.get('severity', '?')}] — {rule.get('description', '')[:60]}")
    if len(effective) > 8:
        print(f"  … and {len(effective) - 8} more")

    _subsection(
        "Platform adapter rules (ai_agent_repo)",
        command="collect_rules(profile_repo(ai_agent_repo))",
        note="Python API",
    )
    ai_repo = BENCHMARK_ROOT / "ai_agent_repo"
    profile = profile_repo(ai_repo)
    adapter_rules = collect_rules(profile.to_dict())
    for rule in adapter_rules:
        print(f"  • {rule['id']}: {rule.get('description', '')[:70]}")

    _subsection(
        "Inline annotations (Tier 3 — highest priority)",
        command='find_inline_annotations(source)  # crb:ignore / crb:rule',
        note="Python API",
    )
    sample = textwrap.dedent("""\
        refund_amount = float(amount)  # crb:ignore no-float-for-money
        API_KEY = "sk_test"  # crb:rule "Never commit API keys in this module"
    """)
    ann = find_inline_annotations(sample)
    print(f"  Ignores on lines: {ann['ignores']}")
    print(f"  Inline rules on lines: {ann['rules']}")

    _subsection(
        "Rule check on ai_agent orchestrator.py",
        command="check_file_rules('orchestrator.py', content, rules)",
        note="Python API — regex scan",
    )
    orch = ai_repo / "orchestrator.py"
    findings = check_file_rules("orchestrator.py", orch.read_text(), {"rules": adapter_rules})
    for f in findings:
        print(f"  [{f['severity']}] {f['rule_id']} @ line {f['line']}: {f['description'][:60]}")


def uc_codememory_index() -> None:
    """ChromaDB indexing — incremental embed + import graph."""
    _subsection("Prerequisite: workspace init (creates .crb-workspace/chroma_db/)")
    if not WORKSPACE_DIR.is_dir():
        print("  Workspace missing — run the `workspace` use-case first.")
        return

    repos = [
        ("backend_service", BENCHMARK_ROOT / "backend_service"),
        ("frontend_app", BENCHMARK_ROOT / "frontend_app"),
    ]
    for repo_id, path in repos:
        cmd = f"codereviewbot index --path {_rel(path)} --repo-id {repo_id}"
        _subsection(f"Index {repo_id} → {path.name}", command=cmd)
        _codereviewbot("index", "--path", _rel(path), "--repo-id", repo_id, echo_cmd=False)


def uc_index_health() -> None:
    """Manifest status, stale detection, chunk audit, symbol lookup."""
    backend = BENCHMARK_ROOT / "backend_service"
    _subsection(
        "Index manifest status",
        command=f"codereviewbot index-status --path {_rel(backend)} --repo-id backend_service",
    )
    _codereviewbot("index-status", "--path", _rel(backend), "--repo-id", "backend_service", echo_cmd=False)

    _subsection(
        "Chunk coverage audit + symbol spot-check",
        command=(
            f"codereviewbot index-audit --path {_rel(backend)} --repo-id backend_service "
            "--symbol process_payment --symbol billing"
        ),
    )
    _codereviewbot(
        "index-audit",
        "--path", _rel(backend),
        "--repo-id", "backend_service",
        "--symbol", "process_payment",
        "--symbol", "billing",
        check=False,
        echo_cmd=False,
    )
    print("  (symbol_not_found is expected on this tiny benchmark repo)")


def uc_token_budget() -> None:
    """Diff filter, lockfile skip, compaction — saves LLM tokens."""
    from src.utils.token_budget import (
        compact_diff,
        estimate_tokens,
        filter_diff,
        diff_stats,
        changed_files_summary,
    )

    raw = PATCH.read_text()
    filtered = filter_diff(raw)
    compact = compact_diff(filtered)

    _subsection(
        "Diff filtering (skip lockfiles, binaries, whitespace-only)",
        command="filter_diff(patch) + diff_stats()",
        note="Python API — runs inside codereviewbot review",
    )
    before = diff_stats(raw)
    after = diff_stats(filtered)
    print(f"  Files before filter: {before['files']}")
    print(f"  Files after filter:  {after['files']}")
    print(f"  Skipped:             {before['files'] - after['files']}")

    _subsection("Token compaction", command="compact_diff(filtered) + estimate_tokens()", note="Python API")
    b_tok = estimate_tokens(raw)
    a_tok = estimate_tokens(compact)
    pct = round(100 * (1 - a_tok / b_tok), 1) if b_tok else 0
    print(f"  Tokens: {b_tok} → {a_tok} ({pct}% reduction)")

    _subsection("Changed-files summary (sent to agents)", command="changed_files_summary(filtered)", note="Python API")
    print(changed_files_summary(filtered))


def uc_static_prepass() -> None:
    """Free local regex scan before any LLM call."""
    from src.utils.rules_parser import check_file_rules
    from src.utils.static_analysis import run_static_analysis, format_static_findings
    from src.utils.token_budget import filter_diff
    from src.workspace.store import get_effective_rules

    backend = BENCHMARK_ROOT / "backend_service"
    django = BENCHMARK_ROOT / "django_app"
    filtered = filter_diff(PATCH.read_text())

    _subsection(
        "Static pre-pass on sample_pr_diff.patch",
        command="run_static_analysis(patch, backend_service)",
        note="Python API — same regex engine as review pre-pass",
    )
    summary = run_static_analysis(filtered, backend)
    rules = get_effective_rules(backend, REPO_ROOT)
    _print_regex_rules(rules)
    print()
    print(f"  Files scanned: {summary['files_scanned']} (patch adds new files not on disk yet)")
    print(f"  Files skipped: {summary['files_skipped']}")
    print("  → Regex rules run on existing files; new-file hunks go to LLM agents.")
    print()
    print(format_static_findings(summary))

    _subsection(
        "Static rules on django_app/settings.py",
        command="check_file_rules('myproject/settings.py', content, rules)",
        note="Python API — regex scan on disk file",
    )
    settings = django / "myproject" / "settings.py"
    rules = get_effective_rules(django, REPO_ROOT)
    findings = check_file_rules("myproject/settings.py", settings.read_text(), {"rules": rules})
    print(f"  Rules checked: {len(rules)}")
    print(f"  Findings:      {len(findings)} (no LLM call)")
    for f in findings:
        print(f"    [{f['severity']}] {f['rule_id']} @ line {f['line']}: {f['description'][:55]}")


def uc_skill_harvesting() -> None:
    """Auto-discovered conventions → candidate rules (Day 3 Skill Harvesting)."""
    backend = BENCHMARK_ROOT / "backend_service"
    _subsection(
        "Harvest dominant style conventions",
        command=f"codereviewbot harvest-rules --path {_rel(backend)} --repo-id backend_service",
    )
    _codereviewbot("harvest-rules", "--path", _rel(backend), "--repo-id", "backend_service", check=False, echo_cmd=False)

    _subsection(
        "Approve a rule (demo — temp file)",
        command='codereviewbot approve-rule --id demo-no-print --pattern "print\\(" ...',
        note="Python API demo — append_rule()",
    )
    from src.memory.rule_approver import append_rule, validate_pattern

    pattern = r"print\("
    print(f"  Pattern compiles: {validate_pattern(pattern)}")
    with tempfile.TemporaryDirectory() as tmp:
        rules_path = Path(tmp) / "rules.yaml"
        rules_path.write_text("rules: []\n", encoding="utf-8")
        result = append_rule(
            rules_path,
            {
                "id": "demo-no-print",
                "description": "Demo harvested rule — no print() in production",
                "pattern": pattern,
                "severity": "medium",
                "files": ["**/*.py"],
                "suggestion": "Use logging instead of print()",
                "source": "harvested:approved",
            },
        )
        print(f"  ✔ Wrote rule '{result['rule_id']}' → {result['path']}")
        print("  Preview:")
        for line in rules_path.read_text().splitlines()[:12]:
            print(f"    {line}")


def uc_benchmark() -> None:
    """Golden-set evaluation — precision / recall / F1 (no LLM)."""
    _subsection("Golden-set scorecard", command="codereviewbot benchmark", note="regex scan vs ground_truth/*.yaml")
    _codereviewbot("benchmark", echo_cmd=False)
    _subsection("Per-repo breakdown saved in benchmark_scorecard.txt")
    scorecard = KAGGLE_DIR / "benchmark_scorecard.txt"
    if scorecard.is_file():
        print(scorecard.read_text())


def uc_agent_capabilities() -> None:
    """What each of the 6 agents checks — mapped to sample PR findings."""
    from src.utils.token_budget import filter_diff

    filtered = filter_diff(PATCH.read_text())
    agents = [
        (
            "Repo Profiler & Diff Analyzer",
            "Detects Python + Redis + PostgreSQL; structures diff for downstream agents.",
            ["Languages: python", "Integration layers: Redis, PostgreSQL"],
        ),
        (
            "Security Auditor",
            "Hardcoded secrets, SQL injection, hallucinated PyPI/npm packages.",
            [
                "CRITICAL: API_KEY = sk_live_… (hardcoded secret)",
                "CRITICAL: py_fake_cryptography_pkg — not on PyPI (Active Defense)",
                "HIGH: f-string in cur.execute() — SQL injection risk",
            ],
        ),
        (
            "Style & Convention Checker",
            "Naming conventions via CodeMemory style profile.",
            [
                "getPaymentDetails uses camelCase; repo convention is snake_case",
            ],
        ),
        (
            "Impact & Integration Analyzer",
            "Blast radius, Redis key contracts, N+1 queries.",
            [
                "Redis key refund:{id} missing payment- prefix — cache break",
                "SELECT inside for-loop — N+1 query pattern",
                "New refund flow touches Redis + PostgreSQL",
            ],
        ),
        (
            "Business Rules Auditor",
            "YAML rules + inline # crb:ignore + auto-discovered patterns.",
            [
                "no-float-for-money: float(amount) in payment_handler.py",
                "require-login-decorator: API handler missing @login_required",
            ],
        ),
        (
            "Summary Generator",
            "Consolidates all findings → Markdown report with overall risk rating.",
            ["Overall Risk: CRITICAL — Do not merge"],
        ),
    ]

    _subsection(
        "Sample PR diff (intentional bugs)",
        command="filter_diff(tests/fixtures/sample_pr_diff.patch)",
        note="Python API — input to review pipeline",
    )
    for line in filtered.splitlines()[:20]:
        print(f"  {line}")
    print("  …")

    for name, role, findings in agents:
        _subsection(name)
        print(f"  Role: {role}")
        print("  Expected findings on sample patch:")
        for f in findings:
            print(f"    • {f}")

    print("  Sample artifacts (output + report) are written at the end of the demo.")


def uc_multi_agent_review() -> None:
    """Full ADK orchestrator — parallel agents + Summary Generator."""
    review_cmd = (
        "codereviewbot review --pr tests/fixtures/sample_pr_diff.patch "
        "--repo ../benchmark_repos/backend_service --sequential"
    )
    _subsection("Multi-agent review command", command=review_cmd)
    if LIVE_REVIEW and not _has_api_key():
        print("\n⚠ GOOGLE_API_KEY not set — offline artifacts will be generated at end of demo.")
        print("  Set key in codereviewbot/.env and re-run with --with-llm for a live Gemini run.")
    elif LIVE_REVIEW:
        print("\nLive Gemini review will run when sample artifacts are generated (final step).")
    else:
        print("\nOffline review simulation — sample artifacts generated in the final step.")
        print("  Pass --with-llm for a live Gemini run when GOOGLE_API_KEY is set.")
    print(f"\n  → {SAMPLE_REVIEW_OUTPUT}")
    print(f"  → {SAMPLE_REVIEW_REPORT}")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

USE_CASES: list[UseCase] = [
    UseCase(
        "workspace",
        "Multi-Repo Workspace Setup",
        "First-time setup: init, register repos, link contracts, show registry.",
        False,
        uc_workspace,
        commands=(
            "codereviewbot workspace init --product codereviewbot-demo",
            "codereviewbot workspace register --id backend_service --path benchmark_repos/backend_service --kind backend",
            "codereviewbot workspace register --id frontend_app --path benchmark_repos/frontend_app --kind frontend",
            'codereviewbot workspace link --consumer frontend_app --provider backend_service --contract "REST /api/billing"',
            "codereviewbot workspace show",
        ),
    ),
    UseCase(
        "profiling",
        "Repo Profiling & Platform Adapters",
        "Detects languages, frameworks, integrations; rules come from benchmark_repos/*/.crb/.",
        False,
        uc_repo_profiling,
        commands=(
            "profile_repo(path)  # read-only Python API",
            "codereviewbot init --path ../benchmark_repos/<repo>  # only for new repos",
        ),
    ),
    UseCase(
        "rules",
        "3-Tier Business Rules",
        "Platform + shared + repo rules merge; inline # crb:ignore annotations.",
        False,
        uc_business_rules,
        commands=(
            "get_effective_rules(repo)  # Python API",
            "check_file_rules(file, content, rules)  # Python API — regex scan",
            "find_inline_annotations(source)  # crb:ignore / crb:rule",
        ),
        regex_rules=(
            "no-float-for-money → float\\(",
            "bare-except → except\\s*:",
            "raw-sql-injection-risk → .execute\\(.*f['\"]",
            "agent-no-hardcoded-api-key → (GOOGLE_API_KEY|OPENAI_API_KEY|…)\\s*=",
            "agent-unsandboxed-shell → subprocess\\.(run|call|Popen)\\(.*shell\\s*=\\s*True",
        ),
    ),
    UseCase(
        "index",
        "CodeMemory Indexing",
        "AST chunking, ChromaDB embeddings, import/reference graph for blast radius.",
        False,
        uc_codememory_index,
        commands=(
            "codereviewbot index --path ../benchmark_repos/backend_service --repo-id backend_service",
            "codereviewbot index --path ../benchmark_repos/frontend_app --repo-id frontend_app",
        ),
    ),
    UseCase(
        "index-health",
        "Index Status & Audit",
        "Manifest staleness, chunk coverage gaps, symbol spot-check in ChromaDB.",
        False,
        uc_index_health,
        commands=(
            "codereviewbot index-status --path ../benchmark_repos/backend_service --repo-id backend_service",
            "codereviewbot index-audit --path ../benchmark_repos/backend_service --repo-id backend_service "
            "--symbol process_payment --symbol billing",
        ),
    ),
    UseCase(
        "token-budget",
        "Token Budget & Diff Compaction",
        "Filter lockfiles/binaries; compact diff to fit agent context windows.",
        False,
        uc_token_budget,
        commands=(
            "filter_diff(patch)  # Python API — inside codereviewbot review",
            "compact_diff(filtered)",
            "estimate_tokens(text)",
            "changed_files_summary(filtered)",
        ),
    ),
    UseCase(
        "static-prepass",
        "Static Pre-Pass (Free, No LLM)",
        "Regex rules run locally; findings injected as STATIC_FINDINGS to save tokens.",
        False,
        uc_static_prepass,
        commands=(
            "run_static_analysis(patch, repo)  # Python API — review pre-pass",
            "check_file_rules(file, content, rules)",
        ),
        regex_rules=(
            "no-float-for-money → float\\(",
            "py-web-no-debug-true → DEBUG\\s*=\\s*True",
            "py-web-secret-key-leak → SECRET_KEY\\s*=\\s*['\"]",
        ),
    ),
    UseCase(
        "harvest",
        "Skill Harvesting",
        "Surface dominant conventions; approve-rule persists them as durable memory.",
        False,
        uc_skill_harvesting,
        commands=(
            "codereviewbot harvest-rules --path ../benchmark_repos/backend_service --repo-id backend_service",
            'codereviewbot approve-rule --id <id> --pattern "<regex>" --description "..."',
        ),
        regex_rules=(
            "demo-no-print → print\\(  # example approved harvested rule",
        ),
    ),
    UseCase(
        "benchmark",
        "Golden-Set Benchmark",
        "13 repos, ground-truth labels, precision/recall/F1 scorecard (no LLM).",
        False,
        uc_benchmark,
        commands=("codereviewbot benchmark",),
        regex_rules=("check_file_rules() on all 13 golden-set repos",),
    ),
    UseCase(
        "agents",
        "Multi-Agent Capabilities",
        "Maps each ADK agent to concrete findings on the sample PR patch.",
        False,
        uc_agent_capabilities,
        commands=(
            "filter_diff(tests/fixtures/sample_pr_diff.patch)  # walkthrough — no CLI",
        ),
    ),
    UseCase(
        "review",
        "Multi-Agent Review",
        "Explains review step; sample_review_output.txt + sample_review_report.md written at end.",
        False,
        uc_multi_agent_review,
        commands=(
            "codereviewbot review --pr tests/fixtures/sample_pr_diff.patch "
            "--repo ../benchmark_repos/backend_service --sequential",
            "generate_sample_review_artifacts()  # writes sample_review_output.txt + sample_review_report.md",
        ),
        regex_rules=(
            "Static pre-pass regex rules run before LLM agents (see static-prepass use-case)",
        ),
    ),
]

USE_CASE_MAP = {uc.id: uc for uc in USE_CASES}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demonstrate every CodeReviewBot use-case and feature.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Use-case IDs:
              workspace, profiling, rules, index, index-health,
              token-budget, static-prepass, harvest, benchmark,
              agents, review
        """),
    )
    parser.add_argument("--list", action="store_true", help="List use-cases and exit")
    parser.add_argument("--only", action="append", metavar="ID", help="Run only these use-case IDs (repeatable)")
    parser.add_argument("--skip", action="append", metavar="ID", help="Skip these use-case IDs (repeatable)")
    parser.add_argument("--fresh", action="store_true", help="Delete .crb-workspace/ before running (clean first-time setup)")
    parser.add_argument("--with-llm", action="store_true", help="Run live multi-agent review instead of pre-recorded output")
    parser.add_argument("--pause", type=float, default=0, help="Seconds to pause between use-cases")
    args = parser.parse_args()

    if args.list:
        print(f"{'ID':<16} {'LLM?':<5} Title")
        _hr()
        for uc in USE_CASES:
            llm = "yes" if uc.needs_llm else "no"
            print(f"{uc.id:<16} {llm:<5} {uc.title}")
            print(f"{'':16}       {uc.summary}")
            if uc.commands:
                print(f"{'':16}       Commands:")
                for cmd in uc.commands:
                    print(f"{'':16}         $ {cmd}")
            if uc.regex_rules:
                print(f"{'':16}       Regex rules:")
                for rule in uc.regex_rules:
                    print(f"{'':16}         • {rule}")
            print()
        return

    if not (CRB_DIR / "src" / "main.py").exists():
        sys.exit(f"❌ codereviewbot not found at {CRB_DIR}")

    _bootstrap()

    global LIVE_REVIEW
    LIVE_REVIEW = args.with_llm

    if args.fresh:
        _fresh_workspace()
        print()

    selected = list(USE_CASES)
    if args.only:
        unknown = set(args.only) - set(USE_CASE_MAP)
        if unknown:
            sys.exit(f"❌ Unknown use-case IDs: {', '.join(sorted(unknown))}")
        selected = [USE_CASE_MAP[i] for i in args.only]
    if args.skip:
        skip = set(args.skip)
        selected = [uc for uc in selected if uc.id not in skip]

    if not selected:
        sys.exit("❌ No use-cases selected.")

    print("CodeReviewBot — Full Use-Case Demonstration")
    print(f"Workspace: {REPO_ROOT}")
    print(f"Running {len(selected)} use-case(s)" + (" (live LLM review at end)" if args.with_llm else ""))
    _hr("=")
    _print_setup_guide()

    failed: list[str] = []
    total = len(selected)
    for i, uc in enumerate(selected, 1):
        _section(i, total, uc)
        try:
            uc.run()
            print(f"\n✔ {uc.id} complete")
        except SystemExit as e:
            if e.code:
                failed.append(uc.id)
                print(f"\n✗ {uc.id} failed (exit {e.code})", file=sys.stderr)
        except Exception as e:
            failed.append(uc.id)
            print(f"\n✗ {uc.id} error: {e}", file=sys.stderr)
        _pause(args.pause)

    _hr("=")
    print("\nGenerating sample review artifacts at repo root...")
    _subsection(
        "Write sample_review_output.txt + sample_review_report.md",
        command="generate_sample_review_artifacts()",
        note="Python API — offline or live (--with-llm)",
    )
    try:
        generate_sample_review_artifacts(live=LIVE_REVIEW)
        _subsection("sample_review_output.txt (preview)")
        preview = SAMPLE_REVIEW_OUTPUT.read_text(encoding="utf-8")
        preview_lines = preview.splitlines()
        for line in preview_lines[:40]:
            print(line)
        if len(preview_lines) > 40:
            print(f"  … ({len(preview_lines) - 40} more lines in {SAMPLE_REVIEW_OUTPUT})")
        print(f"\n  Markdown report: {SAMPLE_REVIEW_REPORT}")
    except Exception as e:
        failed.append("artifacts")
        print(f"\n✗ artifact generation error: {e}", file=sys.stderr)

    _hr("=")
    if failed:
        print(f"Finished with failures: {', '.join(failed)}")
        sys.exit(1)
    print(f"✔ All {total} use-case(s) demonstrated successfully.")


if __name__ == "__main__":
    main()
