import os
import sys
import json
import click
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from src.utils.paths import get_project_root, get_workspace_root, repo_config_dir, repo_rules_path, shared_rules_path, workspace_config_path
from src.platforms.registry import profile_repo, build_review_preamble
from src.utils.token_budget import (
    compact_diff,
    estimate_tokens,
    filter_diff,
    changed_files_summary,
    diff_stats,
)
from src.utils.static_analysis import run_static_analysis, format_static_findings

WORKSPACE_ROOT = get_workspace_root()
PROJECT_ROOT = get_project_root()


@click.group()
def cli():
    """CodeReviewBot CLI - Multi-agent automated code review and security auditing."""
    pass


@cli.command()
@click.option("--path", "repo_path", default=None, help="Repository root to profile (default: workspace root).")
def init(repo_path):
    """Analyze the repository stack and initialize a default rules configuration."""
    root = Path(repo_path).resolve() if repo_path else WORKSPACE_ROOT
    click.echo(f"🔍 Profiling repository at {root}...")

    profile = profile_repo(root)
    data = profile.to_dict()

    click.echo(f"Languages:         {', '.join(data['languages']) or 'none'}")
    click.echo(f"Frameworks:        {', '.join(data['frameworks']) or 'none'}")
    click.echo(f"Platform adapters: {', '.join(data['platform_adapters']) or 'generic'}")
    click.echo(f"Architecture:      {data['architecture']} ({data['repo_kind']})")
    if data["integration_layers"]:
        click.echo(f"Integrations:      {data['integration_layers']}")
    if data["infra_tools"]:
        click.echo(f"Infra:             {', '.join(data['infra_tools'])}")

    from src.memory.rule_harvester import generate_default_rules_file

    rules_dir = repo_config_dir(root)
    if root == PROJECT_ROOT or str(root).endswith("codereviewbot"):
        rules_dir = repo_config_dir(PROJECT_ROOT)

    file_path = generate_default_rules_file(data, rules_dir)
    click.echo(click.style(f"✔ Initialized {file_path} ({len(data.get('platform_adapters', []))} adapters)", fg="green"))


# --- Workspace commands ----------------------------------------------------


@cli.group()
def workspace():
    """Manage workspace-level config: shared rules, repo registry, relationships."""
    pass


@workspace.command("init")
@click.option("--product", default=None, help="Product/team name for this workspace.")
def workspace_init(product):
    """Create a workspace config (.crb-workspace/workspace.yaml) at the workspace root."""
    from src.workspace.store import init_workspace, shared_rules_path

    name = product or WORKSPACE_ROOT.name
    cfg = init_workspace(name, WORKSPACE_ROOT)
    click.echo(f"✔ Workspace '{cfg.product}' initialized at {workspace_config_path(WORKSPACE_ROOT)}")

    sp = shared_rules_path(WORKSPACE_ROOT)
    if not sp.is_file():
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(
            "# Shared business rules — inherited by ALL repos in this workspace.\n"
            "# Repo-level .crb/rules.yaml overrides these by rule_id.\n\n"
            "rules: []\n",
            encoding="utf-8",
        )
        click.echo(f"✔ Created {sp} (add product-level rules here)")


@workspace.command("register")
@click.option("--id", "repo_id", required=True, help="Unique repo identifier (e.g. 'frontend', 'backend').")
@click.option("--path", "repo_path", required=True, help="Path to the repo (relative to workspace root).")
@click.option("--kind", default="service", type=click.Choice(["frontend", "backend", "database", "service", "library", "infra", "mobile", "ai-agent"]))
def workspace_register(repo_id, repo_path, kind):
    """Register a repo in the workspace registry."""
    from src.workspace.store import register_repo

    cfg = register_repo(repo_id, repo_path, kind, WORKSPACE_ROOT)
    click.echo(f"✔ Registered '{repo_id}' ({kind}) → {repo_path}")
    click.echo(f"  Total repos in workspace: {len(cfg.repos)}")


@workspace.command("link")
@click.option("--consumer", required=True, help="Repo ID that consumes an upstream service.")
@click.option("--provider", required=True, help="Repo ID that provides the service.")
@click.option("--contract", default=None, help="Optional contract description (e.g. 'REST /api/v1/users').")
def workspace_link(consumer, provider, contract):
    """Record that 'consumer' repo depends on 'provider' repo (upstream/downstream relationship)."""
    from src.workspace.store import load_workspace, save_workspace

    cfg = load_workspace(WORKSPACE_ROOT)
    if not cfg:
        click.echo(click.style("No workspace found. Run `codereviewbot workspace init` first.", fg="red"), err=True)
        sys.exit(1)
    if consumer not in cfg.repos or provider not in cfg.repos:
        click.echo(click.style(f"Both repos must be registered first. Found: {list(cfg.repos)}", fg="red"), err=True)
        sys.exit(1)

    if provider not in cfg.repos[consumer].consumes:
        cfg.repos[consumer].consumes.append(provider)
    if consumer not in cfg.repos[provider].provides:
        cfg.repos[provider].provides.append(consumer)
    if contract:
        cfg.repos[consumer].contracts.append({"from": provider, "contract": contract})

    save_workspace(cfg, WORKSPACE_ROOT)
    click.echo(f"✔ Linked {consumer} → {provider}" + (f" (contract: {contract})" if contract else ""))


@workspace.command("show")
def workspace_show():
    """Print the workspace registry: repos, relationships, and shared rule count."""
    from src.workspace.store import load_workspace, load_shared_rules

    cfg = load_workspace(WORKSPACE_ROOT)
    if not cfg:
        click.echo("No workspace configured. Run `codereviewbot workspace init`.")
        return

    click.echo(f"Product: {cfg.product}")
    click.echo(f"Repos ({len(cfg.repos)}):")
    for rid, r in cfg.repos.items():
        consumes = ", ".join(r.consumes) or "—"
        provides = ", ".join(r.provides) or "—"
        click.echo(f"  {rid:15} kind={r.kind:10} consumes=[{consumes}] provides=[{provides}]")

    shared = load_shared_rules(WORKSPACE_ROOT)
    click.echo(f"\nShared rules: {len(shared)} (from .crb-workspace/shared_rules.yaml)")


@cli.command()
@click.option("--path", "repo_path", default=None, help="Repository to index (default: workspace root).")
@click.option("--repo-id", default="default", help="Repo identifier within the workspace (enables cross-repo search).")
@click.option("--full", "force_full", is_flag=True, default=False,
              help="Force a full re-index (ignore the manifest; re-embed every file).")
def index(repo_path, repo_id, force_full):
    """Index a repository into the shared CodeMemory vector store.

    By default, indexing is incremental: a per-repo manifest tracks the last
    indexed commit SHA and per-file content hashes, so only changed files are
    re-embedded. Use --full to force a complete re-index.
    """
    from src.memory.refresh import refresh_index
    from src.utils.paths import get_workspace_root

    rpath = repo_path or ""
    target = Path(rpath).resolve() if rpath else WORKSPACE_ROOT
    mode = "full" if force_full else "incremental"
    click.echo(f"🧠 Indexing '{repo_id}' from {target} ({mode})...")
    try:
        summary = refresh_index(repo_id, target, WORKSPACE_ROOT, force_full=force_full)
        click.echo(f"  Mode:          {summary.get('mode', mode)}")
        click.echo(f"  Files indexed: {summary.get('indexed_files', 0)}")
        click.echo(f"  Code chunks:   {summary.get('code_chunks', 0)}")
        click.echo(f"  Imports:       {summary.get('imports', 0)}")
        if "changed_files" in summary:
            click.echo(f"  Changed files: {summary['changed_files']}")
        if "embedded" in summary:
            click.echo(f"  Re-embedded:   {summary['embedded']}, Deleted: {summary['deleted']}")
        click.echo(click.style("✔ Indexing complete!", fg="green"))
    except Exception as e:
        click.echo(click.style(f"Error indexing codebase: {e}", fg="red"), err=True)


@cli.command("index-status")
@click.option("--path", "repo_path", default=None, help="Repository to check (default: workspace root).")
@click.option("--repo-id", default=None, help="Repo identifier (default: derived from path).")
def index_status(repo_path, repo_id):
    """Show index manifest status and disk vs manifest coverage."""
    from src.memory.index_manifest import load_manifest, manifest_path, git_head_sha
    from src.memory.indexer import scan_supported_files
    from src.workspace.store import workspace_chroma_path, find_repo_id_for_path

    target = Path(repo_path).resolve() if repo_path else WORKSPACE_ROOT
    rid = repo_id or find_repo_id_for_path(target, WORKSPACE_ROOT) or target.name
    db_path = workspace_chroma_path(WORKSPACE_ROOT)
    disk_files = len(scan_supported_files(target))

    click.echo(f"Repo:       {rid}")
    click.echo(f"Path:       {target}")
    click.echo(f"Manifest:   {manifest_path(db_path, rid)}")
    click.echo(f"Disk files: {disk_files} (supported extensions on disk)")

    manifest = load_manifest(db_path, rid)
    if not manifest:
        click.echo(click.style("Status:     never indexed (run `codereviewbot index`)", fg="yellow"))
        click.echo("Tip:        run `codereviewbot index-audit` for a full chunking report")
        return

    stats = manifest.get("stats", {})
    last_sha = manifest.get("last_indexed_sha")
    current_sha = git_head_sha(target)
    manifest_file_count = len(manifest.get("file_hashes", {}))

    click.echo(f"Last SHA:   {last_sha or '(non-git repo)'}")
    click.echo(f"Current SHA:{current_sha or '(non-git repo)'}")
    click.echo(f"Manifest:   {manifest_file_count} files")
    click.echo(f"Chunks:     {stats.get('code_chunks', '?')} code, {stats.get('imports', '?')} imports")
    click.echo(f"Last run:   {manifest.get('last_run', '?')}")

    if disk_files != manifest_file_count:
        click.echo(
            click.style(
                f"Coverage:   disk={disk_files} vs manifest={manifest_file_count} — run index-audit",
                fg="yellow",
            )
        )

    if last_sha and current_sha:
        if last_sha == current_sha:
            click.echo(click.style("Status:     up-to-date", fg="green"))
        else:
            click.echo(click.style("Status:     STALE — HEAD advanced since last index", fg="yellow"))
    else:
        click.echo("Status:     non-git (content-hash incremental only)")


@cli.command("index-audit")
@click.option("--path", "repo_path", default=None, help="Repository to audit (default: workspace root).")
@click.option("--repo-id", default=None, help="Repo identifier (default: derived from path).")
@click.option(
    "--symbol",
    "symbols",
    multiple=True,
    help="Spot-check symbol(s) in Chroma (repeatable). Example: --symbol process_payment",
)
@click.option("--verbose", is_flag=True, help="List OK files in addition to issues.")
@click.option("--strict", is_flag=True, help="Fail on zero-chunk files (module-level-only code).")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def index_audit(repo_path, repo_id, symbols, verbose, strict, as_json):
    """Audit chunking coverage: disk vs manifest vs Chroma, flag gaps and mismatches."""
    import json

    from src.memory.index_audit import audit_repo, format_audit_report
    from src.workspace.store import workspace_chroma_path, find_repo_id_for_path

    target = Path(repo_path).resolve() if repo_path else WORKSPACE_ROOT
    rid = repo_id or find_repo_id_for_path(target, WORKSPACE_ROOT) or target.name
    db_path = workspace_chroma_path(WORKSPACE_ROOT)

    report = audit_repo(
        target,
        db_path,
        rid,
        symbols=list(symbols),
        include_ok_files=verbose,
    )

    if as_json:
        payload = {
            "repo_id": report.repo_id,
            "repo_path": str(report.repo_path),
            "never_indexed": report.never_indexed,
            "stale": report.stale,
            "disk_files": report.disk_files,
            "manifest_files": report.manifest_files,
            "chroma_files": report.chroma_files,
            "total_local_code_chunks": report.total_local_code_chunks,
            "total_chroma_code_chunks": report.total_chroma_code_chunks,
            "zero_chunk_files": report.zero_chunk_files,
            "not_in_manifest": report.not_in_manifest,
            "orphan_manifest_files": report.orphan_manifest_files,
            "chroma_missing_files": report.chroma_missing_files,
            "count_mismatch_files": report.count_mismatch_files,
            "symbol_hits": [
                {
                    "name": h.name,
                    "type": h.chunk_type,
                    "file_path": h.file_path,
                    "start_line": h.start_line,
                    "end_line": h.end_line,
                }
                for h in report.symbol_hits
            ],
            "rows": [
                {
                    "file": r.rel_path,
                    "local_code_chunks": r.local_code_chunks,
                    "local_imports": r.local_imports,
                    "chroma_code_chunks": r.chroma_code_chunks,
                    "chroma_imports": r.chroma_imports,
                    "issues": r.issues,
                }
                for r in report.rows
                if r.issues or verbose
            ],
        }
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(format_audit_report(report, verbose=verbose))
        if report.has_warnings:
            click.echo(
                click.style(
                    f"\nWarnings: {len(report.zero_chunk_files)} zero-chunk file(s)"
                    + ("; index is stale" if report.stale else ""),
                    fg="yellow",
                )
            )

    failed = report.has_failures or (strict and bool(report.zero_chunk_files))
    if failed:
        raise SystemExit(1)


@cli.command()
@click.option(
    "--pr",
    "pr",
    required=True,
    help="PR URL, commit SHA/range, or path to a local .patch / .diff file.",
)
@click.option("--repo", default=None, help="Repository root for platform profiling (default: workspace root).")
def review(pr, repo):
    """Run the multi-agent code review pipeline on a PR, commit range, or local diff."""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key or api_key == "your_gemini_api_key_here":
        click.echo(click.style("Error: GOOGLE_API_KEY is not set.", fg="red"), err=True)
        sys.exit(1)

    root = Path(repo).resolve() if repo else WORKSPACE_ROOT

    # Lazy-at-review index refresh: ensure the target repo AND its upstream
    # related repos are current against their default branch before reviewing.
    # This is the "dynamic rules update" mechanism — the CodeMemory snapshot
    # reflects the merged default branch, never the unmerged PR. Cheap when
    # nothing moved (one `git rev-parse` per repo); re-embeds only fire on
    # actual advancement.
    try:
        from src.memory.refresh import refresh_target_and_upstream, format_refresh_summary
        refresh_results = refresh_target_and_upstream(root, WORKSPACE_ROOT)
        stale = [r for r in refresh_results if r.get("mode") not in ("skip",)]
        if stale:
            click.echo("🔄 Refreshing CodeMemory (default branch advanced since last index):")
            click.echo(format_refresh_summary(refresh_results))
        else:
            click.echo("🧠 CodeMemory up-to-date for target + upstream repos")
    except Exception as e:
        click.echo(f"⚠ Index refresh skipped: {e}", err=True)

    profile = profile_repo(root)
    preamble = build_review_preamble(profile)

    patch_text = ""
    filtered = ""
    static_summary = None

    try:
        from src.utils.diff_resolver import (
            resolve_diff,
            DiffResolveError,
            is_commit_reference,
            is_pr_reference,
        )

        raw_patch = resolve_diff(pr, root)
        filtered = filter_diff(raw_patch)
        skipped_files = diff_stats(raw_patch)["files"] - diff_stats(filtered)["files"]
        patch_text = compact_diff(filtered)

        before_tok = estimate_tokens(raw_patch)
        after_tok = estimate_tokens(patch_text)
        click.echo(
            f"📉 Diff: {before_tok} → {after_tok} tokens "
            f"({before_tok - after_tok} saved; {skipped_files} lockfile/binary file(s) skipped)"
        )

        try:
            static_summary = run_static_analysis(filtered, root)
            click.echo(
                f"🔍 Static pre-pass: {static_summary['files_scanned']} file(s) scanned, "
                f"{len(static_summary['findings'])} finding(s) — sent to LLM as STATIC_FINDINGS"
            )
        except Exception as e:
            static_summary = None
            click.echo(f"⚠ Static pre-pass skipped: {e}", err=True)
    except DiffResolveError as e:
        click.echo(click.style(f"Error resolving diff: {e}", fg="red"), err=True)
        sys.exit(1)

    if is_commit_reference(pr):
        ref_kind = "commit(s)"
    elif is_pr_reference(pr):
        ref_kind = "PR"
    else:
        ref_kind = "change"
    click.echo(f"🚀 Reviewing {ref_kind}: {pr}")
    click.echo(f"   Adapters: {', '.join(profile.platform_adapters) or 'generic'}")

    query_parts = [preamble, f"\nAnalyze PR reference: {pr}"]
    if patch_text:
        query_parts.append(f"\n## PATCH\n{patch_text}")
        # Compact changed-file list (lockfiles already filtered) — gives the LLM a
        # high-level map without re-reading the whole diff.
        files_summary = changed_files_summary(filtered)
        if files_summary and "No reviewable files" not in files_summary:
            query_parts.append(f"\n## CHANGED_FILES\n{files_summary}")
    if static_summary is not None:
        query_parts.append("\n" + format_static_findings(static_summary))
    query = "\n".join(query_parts)

    try:
        adk_bin = PROJECT_ROOT / ".venv" / "bin" / "adk"
        if not adk_bin.exists():
            adk_bin = "adk"

        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        env["CRB_WORKSPACE_ROOT"] = str(root)

        process = subprocess.Popen(
            [str(adk_bin), "run", str(PROJECT_ROOT / "src" / "agents"), query],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        for line in process.stdout:
            if "[EXPERIMENTAL]" in line or "FeatureName" in line:
                continue
            click.echo(line, nl=False)

        process.wait()
        if process.returncode != 0:
            click.echo(click.style(f"\nADK failed ({process.returncode}):", fg="red"), err=True)
            click.echo(process.stderr.read(), err=True)
            sys.exit(process.returncode)
    except Exception as e:
        click.echo(click.style(f"Error running review: {e}", fg="red"), err=True)
        sys.exit(1)


@cli.command("approve-rule")
@click.option("--id", "rule_id", required=True, help="Unique rule identifier (e.g. 'no-float-for-money').")
@click.option("--pattern", required=True, help="Regex pattern that triggers the violation.")
@click.option("--description", required=True, help="Human-readable rule description.")
@click.option("--severity", default="medium", type=click.Choice(["low", "medium", "high", "critical"]))
@click.option("--files", "files_glob", default="*", help="Glob pattern scoping the rule (default: all files).")
@click.option("--suggestion", default=None, help="Optional fix suggestion text.")
@click.option("--path", "repo_path", default=None, help="Repository root (default: workspace root).")
@click.option("--shared", is_flag=True, default=False, help="Write to workspace shared_rules.yaml instead of repo rules.yaml.")
def approve_rule(rule_id, pattern, description, severity, files_glob, suggestion, repo_path, shared):
    """Approve a harvested rule and persist it to rules.yaml (Skill Harvesting).

    Turns an auto-discovered pattern into durable procedural memory so future
    reviews enforce it locally (in the static pre-pass) without an LLM call.
    """
    from src.memory.rule_approver import append_rule, validate_pattern

    if not validate_pattern(pattern):
        click.echo(click.style(f"Error: pattern does not compile: {pattern}", fg="red"), err=True)
        sys.exit(1)

    root = Path(repo_path).resolve() if repo_path else WORKSPACE_ROOT
    target = shared_rules_path(WORKSPACE_ROOT) if shared else repo_rules_path(root)

    rule = {
        "id": rule_id,
        "description": description,
        "pattern": pattern,
        "severity": severity,
        "files": [files_glob],
        "suggestion": suggestion or "Please verify and fix this pattern.",
        "source": "harvested:approved",
    }
    result = append_rule(target, rule)
    click.echo(click.style(
        f"✔ Approved rule '{result['rule_id']}' → {result['path']} ({result['total_rules']} rule(s) total)",
        fg="green",
    ))


@cli.command("harvest-rules")
@click.option("--path", "repo_path", default=None, help="Repository to scan (default: workspace root).")
@click.option("--repo-id", default=None, help="Repo identifier with an indexed style summary (default: derived from path).")
@click.option("--apply", "auto_apply", is_flag=True, default=False, help="Approve all suggestions and write them to rules.yaml without prompting.")
def harvest_rules(repo_path, repo_id, auto_apply):
    """Surface auto-discovered style conventions as candidate rules (Skill Harvesting).

    Reads the indexed style summary and prints dominant naming conventions
    as suggested rules. Use --apply to persist all of them, or pick one and
    run `codereviewbot approve-rule ...` to write it individually.
    """
    from src.memory.rule_approver import harvest_suggested_rules, append_rule, validate_pattern
    from src.memory.index_manifest import load_manifest
    from src.workspace.store import workspace_chroma_path, find_repo_id_for_path
    from src.memory.style_profiler import profile_style

    root = Path(repo_path).resolve() if repo_path else WORKSPACE_ROOT
    rid = repo_id or find_repo_id_for_path(root, WORKSPACE_ROOT) or root.name

    style_metrics: dict | None = None
    try:
        import chromadb  # local import; only needed for this command
        db_path = workspace_chroma_path(WORKSPACE_ROOT)
        client = chromadb.PersistentClient(path=str(db_path))
        meta = client.get_or_create_collection("codebase_metadata")
        res = meta.get(ids=[f"style_summary_{rid}"])
        if res and res.get("metadatas"):
            style_metrics = res["metadatas"][0]
    except Exception as e:
        click.echo(f"⚠ Could not read indexed style summary: {e}", err=True)

    if not style_metrics:
        click.echo("No indexed style summary found — falling back to a fresh scan of *.py / *.js files.")
        files = [p for p in root.rglob("*.py") if ".venv" not in str(p) and "__pycache__" not in str(p)][:200]
        files += [p for p in root.rglob("*.js") if "node_modules" not in str(p)][:200]
        style_metrics = profile_style(files)

    suggestions = harvest_suggested_rules(style_metrics)
    if not suggestions:
        click.echo("No dominant style conventions found — nothing to harvest.")
        return

    click.echo(f"Suggested rules from style profile of '{rid}':")
    for s in suggestions:
        ok = "✔" if validate_pattern(s["pattern"]) else "⚠ bad regex"
        click.echo(f"  {ok} {s['id']}: {s['description']}  [files={s['files']}]")

    if not auto_apply:
        click.echo("\nRe-run with --apply to persist all suggestions, or use `approve-rule` to pick one.")
        return

    target = repo_rules_path(root)
    for s in suggestions:
        append_rule(target, s)
    click.echo(click.style(f"✔ Applied {len(suggestions)} rule(s) → {target}", fg="green"))


@cli.command()
@click.option(
    "--manifest",
    default=None,
    help="Path to benchmark manifest.yaml (default: ../benchmark_repos/manifest.yaml).",
)
@click.option("--json-out", default=None, help="Write JSON scorecard to this path.")
def benchmark(manifest, json_out):
    """Run golden-set benchmark and print precision/recall scorecard."""
    manifest_path = Path(manifest).resolve() if manifest else (WORKSPACE_ROOT / "benchmark_repos" / "manifest.yaml")
    if not manifest_path.is_file():
        click.echo(click.style(f"Manifest not found: {manifest_path}", fg="red"), err=True)
        sys.exit(1)

    from src.benchmark.scorecard import run_scorecard, format_scorecard_report

    report = run_scorecard(manifest_path)
    click.echo(format_scorecard_report(report))

    if json_out:
        Path(json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        click.echo(f"\nJSON written to {json_out}")

    if report["summary"]["recall"] < 0.85:
        click.echo(click.style("\n⚠ Recall below 0.85 target", fg="yellow"))


if __name__ == "__main__":
    cli()
